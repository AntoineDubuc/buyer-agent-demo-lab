"""Acceptance criteria for the Budget Move Desk, Part 1 (pure, standard library only).

One criterion per acceptance criterion of the PRD that the lab can prove through
the agent tools in-process (FR-001 to FR-016 and FR-021). Each criterion names
its AC id. The screens (FR-017 to FR-020), HTTP-only behaviour (AC-FR016-02),
AC-FR015-02/03 (sizing-level) and NFR-COMPAT-02 are proven by the change's own
pytest and DOM checks, not here.
"""

from __future__ import annotations

from typing import Any, Callable

ERR = {
    "campaign_not_found": "Campaign not found: {}",
    "move_not_found": "Move not found: {}",
}


def _s(sec: dict[str, Any], step: str) -> Any:
    env = (sec.get("steps") or {}).get(step) or {}
    return env.get("raw") if env.get("status") == "ok" else None


def _why(sec: dict[str, Any], step: str) -> str:
    env = (sec.get("steps") or {}).get(step)
    if not env:
        return f"step {step} did not run"
    return f"step {step}: {env.get('status')} {env.get('reason') or ''}".strip()


def _ch(check: Any, name: str) -> dict[str, Any]:
    return next((c for c in (check or {}).get("channels") or [] if c.get("channel") == name), {})


def _moves(check: Any) -> list[dict[str, Any]]:
    return list((check or {}).get("moves") or [])


def _mv(check: Any) -> list[tuple[str, str, float]]:
    return [(m.get("source"), m.get("target"), m.get("amount")) for m in _moves(check)]


def _err(raw: Any, code: str, detail: str | None = None) -> tuple[bool, str]:
    if not isinstance(raw, dict):
        return False, f"answer {raw!r}"
    ok = raw.get("error") == code and (detail is None or raw.get("detail") == detail)
    return ok, f"error {raw.get('error')!r}, detail {raw.get('detail')!r}"


def _num(x: Any) -> float | None:
    try:
        return round(float(x), 2)
    except (TypeError, ValueError):
        return None


def _channels_of(campaign: Any) -> dict[str, dict[str, Any]]:
    import json

    raw = (campaign or {}).get("channels")
    data = json.loads(raw) if isinstance(raw, str) else (raw or [])
    return {c.get("channel"): c for c in data if isinstance(c, dict)}


def _budgets(campaign: Any) -> dict[str, tuple[float | None, float | None]]:
    return {k: (_num(v.get("budget_amount")), _num(v.get("budget_pct"))) for k, v in _channels_of(campaign).items()}


def criteria(sec: dict[str, Any]) -> list[tuple[str, Callable[[], tuple[bool, str]]]]:
    s = lambda step: _s(sec, step)  # noqa: E731
    out: list[tuple[str, Callable[[], tuple[bool, str]]]] = []

    def add(name: str) -> Callable[[Callable[[], tuple[bool, str]]], None]:
        def deco(fn: Callable[[], tuple[bool, str]]) -> None:
            out.append((name, fn))
        return deco

    @add("AC-FR016-01 all eleven Budget Move Desk tools exist and main's tools are still there")
    def _() -> tuple[bool, str]:
        cap = sec.get("capabilities") or {}
        missing = [k for k, v in cap.items() if not v]
        return not missing and bool(cap), f"missing: {missing or 'none'}"

    @add("setup: an operator key labelled 'A. Dubuc' could be minted")
    def _() -> tuple[bool, str]:
        return bool(sec.get("key_minted")), f"key minted: {sec.get('key_minted')}"

    @add("AC-FR001-01 spend to date sums rows before the as-of date; data as of 2026-08-15, not stale")
    def _() -> tuple[bool, str]:
        chk = s("s01_check")
        if not chk:
            return False, _why(sec, "s01_check")
        sp = {n: _num(_ch(chk, n).get("spend")) for n in ("CTV", "DISPLAY", "AUDIO")}
        ok = sp == {"CTV": 26703.30, "DISPLAY": 30041.21, "AUDIO": 14835.16}
        ok = ok and chk.get("data_as_of") == "2026-08-15" and chk.get("stale") is False
        return ok, f"spend {sp}, data_as_of {chk.get('data_as_of')}, stale {chk.get('stale')}"

    @add("AC-FR001-02 data ending 12 Aug is stale with data as of 2026-08-13")
    def _() -> tuple[bool, str]:
        chk = s("s15_check")
        if not chk:
            return False, _why(sec, "s15_check")
        return chk.get("data_as_of") == "2026-08-13" and chk.get("stale") is True, \
            f"data_as_of {chk.get('data_as_of')}, stale {chk.get('stale')}"

    @add("AC-FR001-03 a file that is not JSON gives delivery_file_unreadable with the path")
    def _() -> tuple[bool, str]:
        path = s("s20_bad_path")
        return _err(s("s20_unreadable"), "delivery_file_unreadable", f"The delivery file {path} is not valid JSON.")

    @add("AC-FR001-04 two rows for one campaign and date give delivery_file_invalid")
    def _() -> tuple[bool, str]:
        return _err(s("s20_duplicate"), "delivery_file_invalid", "Two rows for BD-S01 on 2026-08-01.")

    @add("AC-FR001-05 an empty PACING_DELIVERY_FILE gives delivery_file_missing")
    def _() -> tuple[bool, str]:
        return _err(s("s20_missing"), "delivery_file_missing",
                    "PACING_DELIVERY_FILE is not set or points to a file that does not exist: ")

    @add("AC-FR002-01 15 Aug pace: 45 of 91 days; CTV -28.00 behind, DISPLAY 35.00 ahead, AUDIO 0.00 on track; campaign -3.50")
    def _() -> tuple[bool, str]:
        chk = s("s01_check")
        if not chk:
            return False, _why(sec, "s01_check")
        got = {n: (_num(_ch(chk, n).get("expected")), _num(_ch(chk, n).get("deviation_pct")), _ch(chk, n).get("status"))
               for n in ("CTV", "DISPLAY", "AUDIO")}
        want = {"CTV": (37087.91, -28.0, "behind"), "DISPLAY": (22252.75, 35.0, "ahead"),
                "AUDIO": (14835.16, 0.0, "on_track")}
        camp = (_num(chk.get("campaign_spend")), _num(chk.get("campaign_expected")), _num(chk.get("campaign_deviation_pct")))
        ok = got == want and camp == (71579.67, 74175.82, -3.5) and (chk.get("days_elapsed"), chk.get("flight_length")) == (45, 91)
        return ok, f"{got}; campaign {camp}; days {chk.get('days_elapsed')}/{chk.get('flight_length')}"

    @add("AC-FR002-02 exactly -10.00% is on track")
    def _() -> tuple[bool, str]:
        c = _ch(s("s19_boundary"), "CTV")
        return _num(c.get("deviation_pct")) == -10.0 and c.get("status") == "on_track", \
            f"deviation {c.get('deviation_pct')}, status {c.get('status')}"

    @add("AC-FR002-03 no rows before the date gives no_delivery_data and writes nothing")
    def _() -> tuple[bool, str]:
        raw, hist = s("s19_no_data"), s("s19_no_data_history")
        ok = raw == {"status": "no_delivery_data", "campaign_id": "BD-NODATA", "as_of": "2026-07-10"}
        ok = ok and isinstance(hist, dict) and not hist.get("events")
        return ok, f"answer {raw}; history events {len((hist or {}).get('events') or [])}"

    @add("AC-FR002-04 an as-of that is not a date gives invalid_date")
    def _() -> tuple[bool, str]:
        return _err(s("s19_bad_date"), "invalid_date", 'as_of must be a date in YYYY-MM-DD form; got "15/08/2026".')

    @add("AC-FR003-01 CPA 48.10 / 39.20 / 52.75; over target -3.80 / -12.89 / -4.09")
    def _() -> tuple[bool, str]:
        chk = s("s01_check")
        got = {n: (_num(_ch(chk, n).get("cpa")), _num(_ch(chk, n).get("pct_over_target"))) for n in ("CTV", "DISPLAY", "AUDIO")}
        return got == {"CTV": (48.1, -3.8), "DISPLAY": (39.2, -12.89), "AUDIO": (52.75, -4.09)}, f"{got}"

    @add("AC-FR003-02 49 conversions: DISPLAY cpa null, results unknown with the exact reason")
    def _() -> tuple[bool, str]:
        c = _ch(s("s07_check"), "DISPLAY")
        ok = c.get("cpa") is None and c.get("results") == "unknown" and \
            c.get("results_reason") == "fewer than 50 conversions in the last 14 days"
        return ok, f"cpa {c.get('cpa')}, results {c.get('results')}, reason {c.get('results_reason')!r}"

    @add("AC-FR003-03 no AUDIO target: cpa 52.75, results unknown, reason 'no cost target set'")
    def _() -> tuple[bool, str]:
        c = _ch(s("s08_check"), "AUDIO")
        ok = _num(c.get("cpa")) == 52.75 and c.get("target_cpa") is None and c.get("results") == "unknown" \
            and c.get("results_reason") == "no cost target set"
        return ok, f"cpa {c.get('cpa')}, target {c.get('target_cpa')}, results {c.get('results')}, reason {c.get('results_reason')!r}"

    @add("AC-FR004-01 exactly one move CTV to DISPLAY 7788.46 with the sizing sentence first")
    def _() -> tuple[bool, str]:
        chk = s("s01_check")
        m = _moves(chk)
        first = (m[0].get("reason") or [""])[0] if m else ""
        want = "Streaming TV is behind (spent 26,703.30 of 37,087.91 expected); Display is ahead and can absorb the shift."
        return _mv(chk) == [("CTV", "DISPLAY", 7788.46)] and first == want, f"moves {_mv(chk)}; first reason {first!r}"

    @add("AC-FR004-02 one source, two targets: CTV to DISPLAY 7788.46 then CTV to AUDIO 2596.15")
    def _() -> tuple[bool, str]:
        got = _mv(s("s09_check"))
        return got == [("CTV", "DISPLAY", 7788.46), ("CTV", "AUDIO", 2596.15)], f"moves {got}"

    @add("AC-FR004-03 a 70,000 floor across two targets leaves one move CTV to DISPLAY 5000.00")
    def _() -> tuple[bool, str]:
        chk = s("s10_check")
        reasons = (_moves(chk)[0].get("reason") if _moves(chk) else []) or []
        ok = _mv(chk) == [("CTV", "DISPLAY", 5000.0)] and \
            "Reduced to keep Streaming TV at its 70,000.00 minimum." in reasons
        return ok, f"moves {_mv(chk)}; reasons {reasons}"

    @add("AC-FR004-04 a locked source means no move")
    def _() -> tuple[bool, str]:
        chk = s("s11_check")
        return chk is not None and _mv(chk) == [], f"moves {_mv(chk)}"

    @add("AC-FR004-05 a floor leaving 50.00 (below the 100.00 minimum) means no move")
    def _() -> tuple[bool, str]:
        chk = s("s12_check")
        return chk is not None and _mv(chk) == [], f"moves {_mv(chk)}"

    @add("AC-FR005-01 the 15 Aug move passes results, is pending, with the pass sentence")
    def _() -> tuple[bool, str]:
        m = (_moves(s("s01_check")) or [{}])[0]
        ok = m.get("results") == "pass" and m.get("status") == "pending" and \
            "Display's cost per acquisition (39.20) is within its 45.00 target." in (m.get("reason") or [])
        return ok, f"results {m.get('results')}, status {m.get('status')}, reasons {m.get('reason')}"

    @add("AC-FR005-02 DISPLAY at 57.30 vs 45.00 (27.33% over): the move is blocked with the fail sentence")
    def _() -> tuple[bool, str]:
        chk = s("s05_check")
        m = (_moves(chk) or [{}])[0]
        sent = "Display's cost per acquisition (57.30) is 27.33% above its 45.00 target; the limit is 25%."
        ok = _mv(chk) == [("CTV", "DISPLAY", 7788.46)] and m.get("results") == "fail" and m.get("status") == "blocked" \
            and sent in (m.get("reason") or [])
        return ok, f"moves {_mv(chk)}, results {m.get('results')}, status {m.get('status')}, reasons {m.get('reason')}"

    @add("AC-FR005-03 unknown results are never approved automatically")
    def _() -> tuple[bool, str]:
        m = (_moves(s("s06_check")) or [{}])[0]
        sent = "Display's results are unknown: fewer than 50 conversions in the last 14 days."
        ok = m.get("results") == "unknown" and m.get("status") == "pending" and sent in (m.get("reason") or [])
        return ok, f"results {m.get('results')}, status {m.get('status')}, reasons {m.get('reason')}"

    @add("AC-FR006-01 a 5000.00 move within the limits is approved automatically and applied")
    def _() -> tuple[bool, str]:
        m = (_moves(s("s13_check")) or [{}])[0]
        b = _budgets(s("s13_campaign_after"))
        ok = m.get("status") == "auto_approved" and m.get("decided_by") == "auto-approve" and \
            "Approved automatically (within the limits)." in (m.get("reason") or []) and \
            b == {"CTV": (70000.0, 46.67), "DISPLAY": (50000.0, 33.33), "AUDIO": (30000.0, 20.0)}
        return ok, f"status {m.get('status')}, by {m.get('decided_by')}, budgets {b}"

    @add("AC-FR006-02 the daily limit stops automatic approval")
    def _() -> tuple[bool, str]:
        m = (_moves(s("s14_check")) or [{}])[0]
        ok = m.get("status") == "pending" and "Over today's automatic approval limit." in (m.get("reason") or [])
        return ok, f"status {m.get('status')}, reasons {m.get('reason')}"

    @add("AC-FR006-03 stale data is never approved automatically")
    def _() -> tuple[bool, str]:
        ms = _moves(s("s15_check"))
        ok = bool(ms) and all(m.get("status") == "pending" and
                              "Delivery data is older than the check date." in (m.get("reason") or []) for m in ms)
        return ok, f"moves {[(m.get('status'), m.get('reason')) for m in ms]}"

    @add("AC-FR007-01 the 15 Aug check: budgets_at_check and the exact summary line")
    def _() -> tuple[bool, str]:
        chk = s("s01_check") or {}
        bac = {k: _num(v) for k, v in (chk.get("budgets_at_check") or {}).items()}
        want = "Streaming TV behind, Display ahead, Audio on track — move $7,788 from Streaming TV to Display"
        ok = bac == {"CTV": 75000.0, "DISPLAY": 45000.0, "AUDIO": 30000.0} and chk.get("summary") == want
        return ok, f"budgets_at_check {bac}; summary {chk.get('summary')!r}"

    @add("AC-FR007-02 a newer check expires an earlier pending move, history 'expired' by system")
    def _() -> tuple[bool, str]:
        mv, hist = s("s03_move_after") or {}, s("s03_history") or {}
        ev = [e for e in hist.get("events") or [] if e.get("kind") == "expired"]
        ok = mv.get("status") == "expired" and any(e.get("by") == "system" for e in ev)
        return ok, f"status {mv.get('status')}, expired events {[(e.get('by')) for e in ev]}"

    @add("AC-FR007-03 unknown campaign")
    def _() -> tuple[bool, str]:
        return _err(s("s19_unknown_campaign"), "campaign_not_found", "Campaign not found: CMP-NOPE")

    @add("AC-FR007-04 re-running with identical content returns the same ids")
    def _() -> tuple[bool, str]:
        a, b = s("s01_check") or {}, s("s01_check_again") or {}
        ida = [m.get("move_id") for m in _moves(a)]
        idb = [m.get("move_id") for m in _moves(b)]
        return bool(a) and a.get("check_id") == b.get("check_id") and ida == idb, \
            f"check ids {a.get('check_id')} / {b.get('check_id')}"

    @add("AC-FR007-05 after the file changed, a re-run stores a new check with CTV to DISPLAY 6000.00")
    def _() -> tuple[bool, str]:
        a, b = s("s04_check") or {}, s("s04_check_rerun") or {}
        ok = bool(b) and a.get("check_id") != b.get("check_id") and _mv(b) == [("CTV", "DISPLAY", 6000.0)]
        return ok, f"check ids {a.get('check_id')} / {b.get('check_id')}; moves {_mv(b)}"

    @add("AC-FR007-06 a draft campaign cannot be checked")
    def _() -> tuple[bool, str]:
        return _err(s("s19_draft"), "campaign_not_active",
                    "Campaign CMP-DRAFT is draft; the desk only checks active campaigns or campaigns on hold.")

    @add("AC-FR008-01 approve with a note: approved, decided_by 'A. Dubuc', override_reason null")
    def _() -> tuple[bool, str]:
        m = s("s01_approve") or {}
        ok = m.get("status") == "approved" and m.get("decided_by") == "A. Dubuc" and \
            m.get("note") == "Display is winning" and m.get("override_reason") is None
        return ok, f"status {m.get('status')}, by {m.get('decided_by')}, note {m.get('note')!r}"

    @add("AC-FR008-02 reject with a reason leaves the budgets unchanged")
    def _() -> tuple[bool, str]:
        m = s("s02_reject") or {}
        b = _budgets(s("s02_campaign_after_reject"))
        ok = m.get("status") == "rejected" and m.get("rejection_reason") == "New podcast deal starts 5 Sep" and \
            {k: v[0] for k, v in b.items()} == {"CTV": 75000.0, "DISPLAY": 45000.0, "AUDIO": 30000.0}
        return ok, f"status {m.get('status')}, reason {m.get('rejection_reason')!r}, budgets {b}"

    @add("AC-FR008-03 a blocked move needs an override reason")
    def _() -> tuple[bool, str]:
        return _err(s("s05_approve_no_override"), "override_reason_required",
                    "This move is blocked by results; give an override reason to approve it anyway.")

    @add("AC-FR008-04 approval after the data changed is refused with numbers_changed and the move expires")
    def _() -> tuple[bool, str]:
        ok, obs = _err(s("s04_approve"), "numbers_changed",
                       "The numbers behind this move have changed. Run the check for 2026-08-15 again and decide on the new proposal.")
        st = (s("s04_move_after") or {}).get("status")
        return ok and st == "expired", f"{obs}; move status {st}"

    @add("AC-FR008-05 an approved move cannot be rejected")
    def _() -> tuple[bool, str]:
        return _err(s("s01_reject_approved"), "not_decidable", "This move is approved and can't be decided.")

    @add("AC-FR008-06 both moves of one check can be approved: 64615.39 / 52788.46 / 32596.15")
    def _() -> tuple[bool, str]:
        a, b = s("s09_approve_0") or {}, s("s09_approve_1") or {}
        bud = _budgets(s("s09_campaign_after"))
        ok = a.get("status") == "approved" and b.get("status") == "approved" and \
            bud == {"CTV": (64615.39, 43.08), "DISPLAY": (52788.46, 35.19), "AUDIO": (32596.15, 21.73)}
        return ok, f"statuses {a.get('status')}/{b.get('status')}, budgets {bud}"

    @add("AC-FR008-07 rejecting with a blank reason is refused")
    def _() -> tuple[bool, str]:
        return _err(s("s02_reject_blank"), "reason_required", "A reason is required to reject a move.")

    @add("AC-FR009-01 defaults when nothing is set")
    def _() -> tuple[bool, str]:
        r = s("s16_defaults") or {}
        want = {"warning_pct": 10, "critical_pct": 25, "max_over_target_pct": 25, "min_move": 100.0, "max_move_pct": 30,
                "auto_approve": False, "auto_max_per_move": 6000.0, "auto_max_per_day": 10000.0,
                "auto_max_per_campaign": 20000.0}
        got = {k: r.get(k) for k in want}
        chans = r.get("channels") or {}
        ok = all(_num(got[k]) == _num(v) if not isinstance(v, bool) else got[k] is v for k, v in want.items()) and \
            all(chans.get(c) == {"target_cpa": None, "floor": None, "locked": False} for c in ("CTV", "DISPLAY", "AUDIO")) \
            and r.get("last_changed_by") is None
        return ok, f"{got}; channels {chans}"

    @add("AC-FR009-02 saving a CTV floor records 'CTV.floor: none → 60,000.00' by A. Dubuc")
    def _() -> tuple[bool, str]:
        r, h = s("s16_after_floor") or {}, s("s16_history") or {}
        ev = [e for e in h.get("events") or [] if e.get("kind") == "rules_changed"]
        ok = _num(((r.get("channels") or {}).get("CTV") or {}).get("floor")) == 60000.0 and \
            r.get("last_changed_by") == "A. Dubuc" and len(ev) == 1 and ev[0].get("by") == "A. Dubuc" and \
            ev[0].get("text") == "CTV.floor: none → 60,000.00"
        return ok, f"floor {((r.get('channels') or {}).get('CTV') or {}).get('floor')}, events {[(e.get('by'), e.get('text')) for e in ev]}"

    @add("AC-FR009-03 a warning level not below the critical level is refused")
    def _() -> tuple[bool, str]:
        return _err(s("s16_bad_warning"), "invalid_rule", "The warning level (30%) must be lower than the critical level (25%).")

    @add("AC-FR009-04 an unknown channel key is refused")
    def _() -> tuple[bool, str]:
        return _err(s("s16_bad_channel"), "invalid_rule", '"RADIO" is not a channel; use CTV, DISPLAY or AUDIO.')

    @add("AC-FR010-01 applying the 15 Aug move: budgets, percentages, instruction text, applied event")
    def _() -> tuple[bool, str]:
        m = s("s01_approve") or {}
        b = _budgets(s("s01_campaign_after_approve"))
        ev = [e for e in (s("s01_events_after_approve") or []) if e.get("event_type") == "pacing.reallocation_applied"]
        instr = ("In your buying platform: lower Acme Spring Launch Streaming TV by $7,788.46 (to $67,211.54) and raise "
                 "Acme Spring Launch Display by $7,788.46 (to $52,788.46). Total stays $150,000.00.")
        camp = s("s01_campaign_after_approve") or {}
        ok = b == {"CTV": (67211.54, 44.81), "DISPLAY": (52788.46, 35.19), "AUDIO": (30000.0, 20.0)} and \
            m.get("instruction_text") == instr and len(ev) == 1 and _num(camp.get("total_budget")) == 150000.0 and \
            (camp.get("flight_start"), camp.get("flight_end")) == ("2026-07-01", "2026-09-30")
        return ok, f"budgets {b}; applied events {len(ev)}; instruction {m.get('instruction_text')!r}"

    @add("AC-FR010-02 the next check paces against the new split")
    def _() -> tuple[bool, str]:
        bac = {k: _num(v) for k, v in ((s("s01_check_next_day") or {}).get("budgets_at_check") or {}).items()}
        return bac == {"CTV": 67211.54, "DISPLAY": 52788.46, "AUDIO": 30000.0}, f"budgets_at_check {bac}"

    @add("AC-FR011-01 Beta Fall Push: +30.00%, on hold, daily cuts 1335.17 / 1147.59, projected 30000.00 over")
    def _() -> tuple[bool, str]:
        chk = s("s17_check") or {}
        o = chk.get("overspend") or {}
        rows = {c.get("channel"): c for c in o.get("channels") or []}
        d, a = rows.get("DISPLAY") or {}, rows.get("AUDIO") or {}
        ok = (chk.get("days_elapsed"), chk.get("flight_length")) == (14, 29) and \
            _num(chk.get("campaign_deviation_pct")) == 30.0 and s("s17_status_after_check") == "pacing_hold" and \
            (_num(d.get("daily_now")), _num(d.get("daily_to_land")), _num(d.get("remaining_budget")), d.get("remaining_days")) == (2855.17, 1335.17, 20027.58, 15) and \
            (_num(a.get("daily_now")), _num(a.get("daily_to_land")), _num(a.get("remaining_budget")), a.get("remaining_days")) == (1627.59, 1147.59, 17213.8, 15) and \
            _num(o.get("projected_over_budget")) == 30000.0
        return ok, f"deviation {chk.get('campaign_deviation_pct')}, status {s('s17_status_after_check')}, overspend {o}"

    @add("AC-FR011-02 mark handled returns the campaign to active, recorded by A. Dubuc")
    def _() -> tuple[bool, str]:
        h = s("s17_history") or {}
        ev = [e for e in h.get("events") or [] if e.get("kind") == "overspend_handled"]
        ok = s("s17_status_after_handled") == "active" and (s("s17_handled") or {}).get("status") == "active" and \
            any(e.get("by") == "A. Dubuc" and e.get("text") == "Bids cut in the platform" for e in ev)
        return ok, f"status {s('s17_status_after_handled')}, events {[(e.get('by'), e.get('text')) for e in ev]}"

    @add("AC-FR011-03 approving a move while on hold is refused")
    def _() -> tuple[bool, str]:
        return _err(s("s18_approve_on_hold"), "campaign_on_hold",
                    "This campaign is on hold for overspending; handle the overspend first.")

    @add("AC-FR011-04 mark handled on a campaign not on hold")
    def _() -> tuple[bool, str]:
        return _err(s("s17_handled_again"), "not_on_hold", "Campaign BD-S17 is not on hold.")

    @add("AC-FR011-05 a second check while on hold keeps the alert")
    def _() -> tuple[bool, str]:
        chk = s("s17_check_again") or {}
        return s("s17_status_after_second") == "pacing_hold" and chk.get("overspend") is not None, \
            f"status {s('s17_status_after_second')}, overspend present {chk.get('overspend') is not None}"

    @add("AC-FR012-01 an in-process decision records the key label 'A. Dubuc'")
    def _() -> tuple[bool, str]:
        return (s("s01_approve") or {}).get("decided_by") == "A. Dubuc", f"decided_by {(s('s01_approve') or {}).get('decided_by')}"

    @add("AC-FR012-02 a decision without identity is refused; reads still work")
    def _() -> tuple[bool, str]:
        ok, obs = _err(s("s21_no_identity"), "identity_required", "A personal access key is required to record this decision.")
        reads = isinstance(s("s21_history_without_identity"), dict) and "events" in (s("s21_history_without_identity") or {})
        return ok and reads, f"{obs}; history readable {reads}"

    @add("AC-FR012-04 the deprecated environment key is not an identity")
    def _() -> tuple[bool, str]:
        return _err(s("s21_legacy"), "identity_required", "A personal access key is required to record this decision.")

    @add("AC-FR013-01 mark done records A. Dubuc and a time")
    def _() -> tuple[bool, str]:
        m = s("s01_done") or {}
        return m.get("done_by") == "A. Dubuc" and bool(m.get("done_at")), f"done_by {m.get('done_by')}, done_at {m.get('done_at')}"

    @add("AC-FR013-02 a rejected move cannot be marked done")
    def _() -> tuple[bool, str]:
        return _err(s("s02_done_rejected"), "not_approved", "Only an approved move can be marked done; this one is rejected.")

    @add("AC-FR013-03 marking done twice")
    def _() -> tuple[bool, str]:
        return _err(s("s01_done_again"), "already_done")

    @add("AC-FR014-01 history newest first: done, approved, proposed, check; splits and moved total")
    def _() -> tuple[bool, str]:
        h = s("s01_history") or {}
        kinds = [e.get("kind") for e in (h.get("events") or [])][:4]
        bys = [e.get("by") for e in (h.get("events") or [])][:2]
        num = lambda d: {k: _num(v) for k, v in (d or {}).items()}  # noqa: E731
        ok = kinds == ["done", "approved", "proposed", "check"] and bys == ["A. Dubuc", "A. Dubuc"] and \
            num(h.get("original_split")) == {"CTV": 75000.0, "DISPLAY": 45000.0, "AUDIO": 30000.0} and \
            num(h.get("current_split")) == {"CTV": 67211.54, "DISPLAY": 52788.46, "AUDIO": 30000.0} and \
            _num(h.get("moved_total")) == 7788.46
        return ok, f"kinds {kinds}, by {bys}, moved {h.get('moved_total')}"

    @add("AC-FR014-02 history of an unknown campaign")
    def _() -> tuple[bool, str]:
        return _err(s("s19_history_unknown"), "campaign_not_found", "Campaign not found: CMP-NOPE")

    @add("AC-FR015-01 the next day's smaller repeat (7293.96) is suppressed with the exact sentence")
    def _() -> tuple[bool, str]:
        chk = s("s02_check_next_day")
        m = (_moves(chk) or [{}])[0]
        sent = "Rejected on 15 Aug (7,788.46); proposed again from 9,346.15."
        ok = _mv(chk) == [("CTV", "DISPLAY", 7293.96)] and m.get("status") == "suppressed" and sent in (m.get("reason") or [])
        return ok, f"moves {_mv(chk)}, status {m.get('status')}, reasons {m.get('reason')}"

    @add("AC-FR015-04 asking for a move that doesn't exist")
    def _() -> tuple[bool, str]:
        mid = "00000000-0000-4000-8000-000000000000"
        return _err(s("s19_unknown_move"), "move_not_found", f"Move not found: {mid}")

    @add("AC-FR021-01 the change's own seed reproduces the 15 Aug worked example")
    def _() -> tuple[bool, str]:
        chk = s("s22_check")
        if not chk:
            return False, _why(sec, "s22_seed") + "; " + _why(sec, "s22_check")
        ok = _mv(chk) == [("CTV", "DISPLAY", 7788.46)] and \
            {n: _num(_ch(chk, n).get("cpa")) for n in ("CTV", "DISPLAY", "AUDIO")} == {"CTV": 48.1, "DISPLAY": 39.2, "AUDIO": 52.75}
        return ok, f"moves {_mv(chk)}"

    @add("AC-FR021-02 seeding again after an approval changes nothing")
    def _() -> tuple[bool, str]:
        v = s("s22_reseed_unchanged")
        return v is True, f"unchanged: {v if v is not None else _why(sec, 's22_reseed_unchanged')}"

    @add("NFR-SEC-03 no outbound network attempt during the run")
    def _() -> tuple[bool, str]:
        n = sec.get("_network_attempts")
        return n == [], f"attempts {n}"

    return out
