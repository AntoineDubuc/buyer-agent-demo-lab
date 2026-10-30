"""Acceptance criteria per change, evaluated on one lab result file (pure, stdlib only).

Every criterion is objective and comes from ../CONTRACTS.md or the scenario data.
``evaluate(change, doc)`` returns a list of ``Check``; a change passes only when
every check passes. ``notes(change, doc)`` returns plain observations that are
shown next to the checks but never decide PASS or FAIL (for example, where the
adaptive negotiator does NOT beat today's one).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .sellers import load_config, params_from_dict, reference_simple_loop, tournament_deals

CHANGES = ("pacing", "creatives", "negotiation", "budget-desk")
CENT = 0.01


@dataclass
class Check:
    ok: bool
    criterion: str
    observed: str

    def line(self) -> str:
        return f"{'PASS' if self.ok else 'FAIL'}  {self.criterion} — {self.observed}"


def _section(doc: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(doc, dict):
        return {}
    res = doc.get("result")
    return res if isinstance(res, dict) else {}


def _guard(fn: Callable[[], tuple[bool, str]]) -> tuple[bool, str]:
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - a malformed result is a FAIL, never a crash
        return False, f"could not evaluate ({type(exc).__name__}: {exc})"


def _env_text(env: dict[str, Any] | None) -> str:
    env = env or {}
    if env.get("status") in ("not_available", "error"):
        reason = str(env.get("reason") or "")
        return reason if reason.startswith(env["status"]) else f"{env['status']}: {reason}"
    return "no answer"


# ---------------------------------------------------------------- pacing


def _scenario(sec: dict[str, Any], sid: str) -> dict[str, Any]:
    return next((r for r in sec.get("scenarios") or [] if r.get("id") == sid), {})


def _run_result(row: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    """The run_pacing_check answer (dict) or (None, why not)."""
    env = row.get("run_pacing_check") or {}
    if env.get("status") != "ok" or not isinstance(env.get("raw"), dict):
        return None, f"run_pacing_check gave {_env_text(env)}"
    return env["raw"], ""


def _channels(res: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(c.get("channel")).upper(): c for c in res.get("channel_pacing") or [] if isinstance(c, dict)}


def _recs(res: dict[str, Any]) -> list[dict[str, Any]]:
    return [r for r in res.get("recommendations") or [] if isinstance(r, dict)]


def _status_check(sec: dict[str, Any], sid: str, ch: str, want: str) -> tuple[bool, str]:
    res, why = _run_result(_scenario(sec, sid))
    if res is None:
        return False, why
    c = _channels(res).get(ch)
    if not c:
        return False, f"no {ch} row in channel_pacing"
    return c.get("status") == want, f"{ch} status {c.get('status')!r}, deviation {c.get('deviation_pct')}%"


def _pacing_checks(doc: dict[str, Any]) -> list[Check]:
    sec = _section(doc)
    out: list[Check] = []

    def add(criterion: str, fn: Callable[[], tuple[bool, str]]) -> None:
        ok, obs = _guard(fn)
        out.append(Check(ok, criterion, obs))

    def tool() -> tuple[bool, str]:
        has = bool((sec.get("capabilities") or {}).get("run_pacing_check_tool"))
        return has, "MCP tool run_pacing_check exists" if has else "MCP tool run_pacing_check is missing"

    add("run_pacing_check is available", tool)
    add("ctv_cant_spend: CTV is behind", lambda: _status_check(sec, "ctv_cant_spend", "CTV", "behind"))
    add("ctv_cant_spend: DISPLAY is ahead", lambda: _status_check(sec, "ctv_cant_spend", "DISPLAY", "ahead"))
    add("ctv_cant_spend: AUDIO is on_track", lambda: _status_check(sec, "ctv_cant_spend", "AUDIO", "on_track"))

    def one_move() -> tuple[bool, str]:
        res, why = _run_result(_scenario(sec, "ctv_cant_spend"))
        if res is None:
            return False, why
        recs = _recs(res)
        desc = "; ".join(f"{r.get('source_channel')}->{r.get('target_channel')} {r.get('amount')}" for r in recs)
        if len(recs) != 1:
            return False, f"{len(recs)} recommendations ({desc or 'none'})"
        r = recs[0]
        amt = float(r.get("amount") or 0)
        ok = (str(r.get("source_channel")).upper(), str(r.get("target_channel")).upper()) == ("CTV", "DISPLAY")
        return ok and amt > 0, f"1 recommendation: {desc}"

    add("ctv_cant_spend: exactly one CTV->DISPLAY recommendation with amount > 0", one_move)

    def snapshot() -> tuple[bool, str]:
        row = _scenario(sec, "ctv_cant_spend")
        res, why = _run_result(row)
        if res is None:
            return False, why
        env = row.get("check_pacing") or {}
        snap = env.get("raw") if env.get("status") == "ok" else None
        if not isinstance(snap, dict):
            return False, f"check_pacing gave {_env_text(env)}"
        want = {k: v.get("status") for k, v in _channels(res).items()}
        got = {k: v.get("status") for k, v in _channels(snap).items()}
        return bool(want) and want == got, f"check_pacing channel statuses {got or snap.get('pacing_status')}"

    add("ctv_cant_spend: check_pacing then returns the saved snapshot (same channel statuses)", snapshot)

    def audio_over() -> tuple[bool, str]:
        res, why = _run_result(_scenario(sec, "audio_over"))
        if res is None:
            return False, why
        got = {k: v.get("status") for k, v in _channels(res).items()}
        return got == {"CTV": "on_track", "DISPLAY": "on_track", "AUDIO": "ahead"}, f"statuses {got}"

    add("audio_over: AUDIO ahead, CTV and DISPLAY on_track", audio_over)

    def quiet() -> tuple[bool, str]:
        res, why = _run_result(_scenario(sec, "all_on_pace"))
        if res is None:
            return False, why
        chans = _channels(res)
        if not chans:
            return False, f"no channel_pacing (status {res.get('status') or res.get('pacing_status')!r})"
        recs = _recs(res)
        all_ok = all(c.get("status") == "on_track" for c in chans.values())
        return all_ok and not recs, (f"{len(recs)} recommendations; statuses "
                                     f"{ {k: v.get('status') for k, v in chans.items()} }")

    add("all_on_pace: every channel on_track and no recommendations", quiet)

    def capped() -> tuple[bool, str]:
        row = _scenario(sec, "two_behind_one_ahead")
        res, why = _run_result(row)
        if res is None:
            return False, why
        if not _channels(res):
            return False, "no channel_pacing"
        d = (row.get("input") or {}).get("DISPLAY") or {}
        over = round(float(d["spend"]) - float(d["expected_spend"]), 2)
        total = round(sum(float(r.get("amount") or 0) for r in _recs(res)), 2)
        return total <= over + CENT, f"recommended ${total:,.2f} in total; Display overspend ${over:,.2f}"

    add("two_behind_one_ahead: total recommended <= Display overspend", capped)

    def no_data() -> tuple[bool, str]:
        res, why = _run_result(_scenario(sec, "no_delivery_yet"))
        if res is None:
            return False, why
        return res.get("status") == "no_delivery_data", f"status {res.get('status') or res.get('pacing_status')!r}"

    add("no_delivery_yet: status is no_delivery_data", no_data)

    def unknown() -> tuple[bool, str]:
        env = (sec.get("probes") or {}).get("unknown_campaign_run_pacing_check") or {}
        raw = env.get("raw") if env.get("status") == "ok" else None
        if not isinstance(raw, dict):
            return False, f"run_pacing_check gave {_env_text(env)}"
        err = str(raw.get("error") or "")
        return "Campaign not found" in err, f"error {err!r}" if err else f"answer {raw}"

    add("unknown campaign: run_pacing_check answers \"Campaign not found\"", unknown)
    return out


# ---------------------------------------------------------------- creatives


def _case(sec: dict[str, Any], cid: str) -> dict[str, Any]:
    return next((r for r in sec.get("cases") or [] if r.get("id") == cid), {})


def _asset(case: dict[str, Any], fixture: str) -> dict[str, Any]:
    return next((a for a in case.get("assets") or [] if a.get("fixture") == fixture), {})


def _reasons(a: dict[str, Any]) -> list[str]:
    r = a.get("product_reasons")
    if isinstance(r, list):
        return [str(x) for x in r if str(x).strip()]
    return [str(r)] if r else []


def _asset_obs(a: dict[str, Any]) -> str:
    if not a:
        return "ad not found in the results"
    rs = _reasons(a)
    return f"status {a.get('product_status')!r}" + (f", reason {'; '.join(rs)!r}" if rs else ", no reason")


def _invalid_with(case: dict[str, Any], fixture: str, needles: tuple[str, ...]) -> tuple[bool, str]:
    a = _asset(case, fixture)
    text = " ".join(_reasons(a)).lower()
    ok = str(a.get("product_status")).lower() == "invalid" and all(n.lower() in text for n in needles)
    return ok, _asset_obs(a)


def _creative_checks(doc: dict[str, Any]) -> list[Check]:
    sec = _section(doc)
    out: list[Check] = []

    def add(criterion: str, fn: Callable[[], tuple[bool, str]]) -> None:
        ok, obs = _guard(fn)
        out.append(Check(ok, criterion, obs))

    def tool() -> tuple[bool, str]:
        has = bool((sec.get("capabilities") or {}).get("validate_campaign_creatives_tool"))
        return has, ("MCP tool validate_campaign_creatives exists" if has
                     else "MCP tool validate_campaign_creatives is missing")

    add("validate_campaign_creatives is available", tool)
    head = _case(sec, "headline_three")

    def held(case: dict[str, Any]) -> tuple[bool, str]:
        if not case:
            return False, "case not found in the results"
        st = case.get("final_status")
        return (not case.get("became_ready")) and st == "booking", f"final status {st!r}"

    add("headline case: NOT ready, stays booking", lambda: held(head))
    add("headline case: 45s ad invalid, reason mentions 45 and 30",
        lambda: _invalid_with(head, "ctv_too_long_45s", ("45", "30")))
    add("headline case: VAST 2.0 ad invalid, reason mentions VAST 4",
        lambda: _invalid_with(head, "ctv_vast20", ("VAST 4",)))

    def valid() -> tuple[bool, str]:
        a = _asset(head, "ctv_valid_30s")
        return str(a.get("product_status")).lower() == "valid", _asset_obs(a)

    add("headline case: the valid ad is valid", valid)

    def names() -> tuple[bool, str]:
        mr = head.get("mark_ready") or {}
        if not mr.get("raised"):
            return False, "mark_ready did not refuse"
        msg = str(mr.get("message") or "")
        bad = [a.get("asset_name") for a in head.get("assets") or [] if a.get("lab_expected_problem")]
        missing = [n for n in bad if n and n not in msg]
        return not missing, ("refusal names every broken ad" if not missing
                             else f"refusal does not name {missing}")

    add("headline case: the refusal message names each broken ad", names)
    seven = _case(sec, "seven_fixtures")
    add("seven-ad case: NOT ready, stays booking", lambda: held(seven))

    def six() -> tuple[bool, str]:
        bad = [a for a in seven.get("assets") or [] if a.get("lab_expected_problem")]
        caught = [a for a in bad if str(a.get("product_status")).lower() == "invalid" and _reasons(a)]
        missed = [a.get("fixture") for a in bad if a not in caught]
        ok = len(bad) == 6 and not missed
        return ok, f"{len(caught)} of {len(bad)} broken ads invalid with a reason" + (
            f"; missed {missed}" if missed else "")

    add("seven-ad case: all six broken ads invalid, each with a non-empty reason", six)
    good = _case(sec, "all_valid")

    def positive() -> tuple[bool, str]:
        if not good:
            return False, "case not found in the results"
        sts = [str(a.get("product_status")) for a in good.get("assets") or []]
        return bool(good.get("became_ready")), f"final status {good.get('final_status')!r}; ad statuses {sts}"

    add("all-valid case: a campaign with only valid ads CAN reach READY", positive)
    return out


# ---------------------------------------------------------------- negotiation


def _strategy(sec: dict[str, Any], name: str) -> dict[str, Any]:
    return (sec.get("strategies") or {}).get(name) or {}


def _per(env: dict[str, Any], pid: str) -> dict[str, Any]:
    return ((env.get("summary") or {}).get("per_personality") or {}).get(pid) or {}


def _ran(env: dict[str, Any]) -> bool:
    return env.get("status") == "ok" and bool(env.get("deals"))


def _negotiation_checks(doc: dict[str, Any]) -> list[Check]:
    sec = _section(doc)
    out: list[Check] = []
    max_cpm = float((sec.get("buyer") or {}).get("max_cpm", 30.0))
    simple, adapt = _strategy(sec, "simple"), _strategy(sec, "adaptive")

    def add(criterion: str, fn: Callable[[], tuple[bool, str]]) -> None:
        ok, obs = _guard(fn)
        out.append(Check(ok, criterion, obs))

    def runs() -> tuple[bool, str]:
        if not _ran(adapt):
            return False, f"AdaptiveStrategy: {_env_text(adapt)}"
        t = (adapt.get("summary") or {}).get("total") or {}
        path = (adapt.get("detection") or {}).get("import_path")
        ok = (path == "ad_buyer.negotiation.strategies" and not t.get("errors") and not adapt.get("truncated")
              and t.get("deals") == (sec.get("tournament") or {}).get("deals"))
        return ok, f"imported from {path}; {t.get('deals')} deals, {t.get('errors')} errors"

    add("AdaptiveStrategy() imports from ad_buyer.negotiation.strategies and runs every deal", runs)

    def never_above() -> tuple[bool, str]:
        if not _ran(adapt):
            return False, f"AdaptiveStrategy: {_env_text(adapt)}"
        paid = [d["final_price"] for d in adapt["deals"] if d.get("outcome") == "accepted"]
        offers = [r["buyer"] for d in adapt["deals"] for r in d.get("rounds") or []]
        top_paid, top_offer = max(paid, default=0.0), max(offers, default=0.0)
        ok = top_paid <= max_cpm + 1e-9 and top_offer <= max_cpm + 1e-9
        return ok, f"highest price paid ${top_paid:.2f}, highest offer ${top_offer:.2f} (max ${max_cpm:.2f})"

    add("adaptive never pays or offers above max_cpm in any deal", never_above)

    def regression() -> tuple[bool, str]:
        if not _ran(simple):
            return False, f"today's negotiator: {_env_text(simple)}"
        b = sec.get("buyer") or {}
        cfg = load_config()
        caps = sec.get("caps") or cfg["caps"]
        ref = {d["deal_id"]: d["params"] for d in tournament_deals(cfg)}
        diffs = []
        for d in simple["deals"]:
            r = reference_simple_loop(params_from_dict(ref[d["deal_id"]]), b.get("target_cpm", 20.0),
                                      b.get("max_cpm", 30.0), b.get("concession_step", 2.0),
                                      b.get("max_rounds", 6), caps["max_seller_rounds"])
            got = (d.get("outcome"), d.get("final_price"), [(x["buyer"], x["seller"]) for x in d.get("rounds") or []])
            want = (r["outcome"], r["final"], [(o, p) for o, p, _ in r["rounds"]])
            if got != want:
                diffs.append(d["deal_id"])
        n = len(simple["deals"])
        missing = len(ref) - n
        ok = not diffs and missing == 0
        return ok, (f"{n - len(diffs)} of {len(ref)} deals identical to the reference loop"
                    + (f"; differ: {diffs[:5]}" if diffs else ""))

    add("today's negotiator (Simple) matches the lab's reference loop deal-for-deal", regression)

    def floor() -> tuple[bool, str]:
        if not _ran(adapt):
            return False, f"AdaptiveStrategy: {_env_text(adapt)}"
        a, s = _per(adapt, "floor_accepting"), _per(simple, "floor_accepting")
        return (a.get("won") or 0) >= 1, f"adaptive {a.get('won')} of {a.get('deals')}, today's {s.get('won')}"

    add("adaptive closes at least 1 deal with the floor-accepting seller", floor)

    def cheaper() -> tuple[bool, str]:
        if not _ran(adapt) or not _ran(simple):
            return False, f"adaptive: {_env_text(adapt) if not _ran(adapt) else 'ran'}; simple: " \
                          f"{_env_text(simple) if not _ran(simple) else 'ran'}"
        a, s = _per(adapt, "proportional_conceder"), _per(simple, "proportional_conceder")
        ok = (a.get("won") == s.get("won") and a.get("avg_final_cpm") is not None
              and s.get("avg_final_cpm") is not None and a["avg_final_cpm"] < s["avg_final_cpm"])
        return ok, (f"adaptive {a.get('won')}/{a.get('deals')} at ${a.get('avg_final_cpm')}, "
                    f"today's {s.get('won')}/{s.get('deals')} at ${s.get('avg_final_cpm')}")

    add("proportional conceder: adaptive average price lower than today's, same deals won", cheaper)
    return out


def _negotiation_notes(doc: dict[str, Any]) -> list[str]:
    sec = _section(doc)
    simple, adapt = _strategy(sec, "simple"), _strategy(sec, "adaptive")
    if not (_ran(simple) and _ran(adapt)):
        return []
    notes = []
    for p in sec.get("personalities") or []:
        pid, title = p.get("id"), p.get("title", p.get("id"))
        a, s = _per(adapt, pid), _per(simple, pid)
        aw, sw = a.get("won") or 0, s.get("won") or 0
        if aw < sw:
            notes.append(f"{title}: adaptive closes FEWER deals than today's ({aw} vs {sw} of {a.get('deals')}).")
        elif aw == 0 and sw == 0:
            notes.append(f"{title}: neither negotiator closes any deal (0 of {a.get('deals')}).")
    return notes


# ---------------------------------------------------------------- budget desk


def _budget_desk_checks(doc: dict[str, Any]) -> list[Check]:
    from .budget_desk_criteria import criteria

    sec = dict(_section(doc))
    sec["_network_attempts"] = ((doc or {}).get("network") or {}).get("outbound_attempts_blocked")
    if sec.get("skipped"):
        return [Check(False, "the Budget Move Desk tools exist", str(sec["skipped"]))]
    out = []
    for name, fn in criteria(sec):
        ok, obs = _guard(fn)
        out.append(Check(ok, name, obs))
    return out


# ---------------------------------------------------------------- public


def evaluate(change: str, doc: dict[str, Any] | None) -> list[Check]:
    fn = {"pacing": _pacing_checks, "creatives": _creative_checks, "negotiation": _negotiation_checks,
          "budget-desk": _budget_desk_checks}[change]
    try:
        checks = fn(doc or {})
    except Exception as exc:  # noqa: BLE001
        checks = [Check(False, "the results could be read", f"{type(exc).__name__}: {exc}")]
    sec = _section(doc)
    if not sec or sec.get("status") == "error":
        why = "no results" if not sec else f"the run failed: {sec.get('reason')}"
        checks.insert(0, Check(False, "the lab ran this change", why))
    return checks


def notes(change: str, doc: dict[str, Any] | None) -> list[str]:
    return _negotiation_notes(doc or {}) if change == "negotiation" else []


def passed(checks: list[Check]) -> bool:
    return bool(checks) and all(c.ok for c in checks)

