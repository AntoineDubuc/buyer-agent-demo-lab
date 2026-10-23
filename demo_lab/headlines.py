"""Plain-language one-line headlines from result JSON (pure, tolerant of missing keys)."""

from __future__ import annotations

from typing import Any

CHANNEL_NAMES = {"CTV": "Streaming TV", "DISPLAY": "Display", "AUDIO": "Audio"}


def ch_name(c: Any) -> str:
    return CHANNEL_NAMES.get(str(c).upper(), str(c))


def money(x: Any) -> str:
    try:
        v = float(x)
        return f"${v:,.0f}" if v == int(v) else f"${v:,.2f}"
    except (TypeError, ValueError):
        return str(x)


def pacing_result(row: dict[str, Any]) -> tuple[str, Any]:
    """Pick the product answer to describe: run_pacing_check first, then check_pacing."""
    for key in ("run_pacing_check", "check_pacing"):
        env = row.get(key) or {}
        if env.get("status") == "ok":
            return key, env.get("raw") or {}
    return "", {}


def pacing(row: dict[str, Any]) -> str:
    if row.get("status") == "error":
        return f"The lab could not run this scenario ({row.get('reason', 'unknown error')})."
    src, res = pacing_result(row)
    if not src:
        return "The agent gave no pacing answer (no pacing tool responded)."
    if isinstance(res, dict) and res.get("error"):
        return f"The agent answered with an error: {res['error']}"
    if res.get("status") == "no_delivery_data":
        return "The agent says there is no delivery data yet and recommends nothing."
    if res.get("pacing_status") == "no_data" and not res.get("channel_pacing"):
        if row.get("feed"):
            return ("No answer: the agent reports \"no data\" for this campaign, even though delivery "
                    "numbers were supplied.")
        return "The agent reports \"no data\" - the same answer it gives whether or not delivery exists."
    parts = []
    for ch in res.get("channel_pacing") or []:
        st = ch.get("status", "")
        dev = ch.get("deviation_pct")
        name = ch_name(ch.get("channel"))
        if st in ("behind", "ahead") or (st or "").startswith("critical"):
            try:
                parts.append(f"{name} {abs(float(dev)):.0f}% {'behind' if float(dev) < 0 else 'ahead'}")
            except (TypeError, ValueError):
                parts.append(f"{name} {st}")
    recs = [r for r in (res.get("recommendations") or []) if isinstance(r, dict)]
    moves = []
    for r in recs:
        if r.get("source_channel") and r.get("target_channel"):
            moves.append(f"move {money(r.get('amount'))} from {ch_name(r['source_channel'])} "
                         f"to {ch_name(r['target_channel'])}")
    lead = ", ".join(parts) if parts else "All channels on track"
    tail = "recommends: " + "; ".join(moves) if moves else "no budget move recommended"
    return f"{lead} - {tail}."


def creatives(row: dict[str, Any]) -> str:
    if row.get("status") == "error":
        return f"The lab could not run this case ({row.get('reason', 'unknown error')})."
    assets = row.get("assets") or []
    n = len(assets)
    bad_lab = [a for a in assets if a.get("lab_expected_problem")]
    flagged = [a for a in assets if str(a.get("product_status") or "").lower() == "invalid"]
    ready = row.get("became_ready")
    example = ""
    if any(a.get("fixture") == "ctv_too_long_45s" for a in bad_lab):
        example = " (including a 45-second ad in a 30-second slot)"
    if ready and not flagged and not bad_lab:
        return f"All {n} ads are fine and the campaign reached READY."
    if ready and not flagged:
        return (f"Marked ready to launch with {len(bad_lab)} of {n} ads that break their slot{example} - "
                f"no warning, no reasons.")
    if not ready and (row.get("mark_ready") or {}).get("raised"):
        return f"Launch blocked: the agent flagged {len(flagged)} of {n} ads and said why for each."
    if ready and flagged:
        return f"Marked ready to launch, although the agent flagged {len(flagged)} of {n} ads."
    return f"Campaign status after the ready step: {row.get('final_status')}."


def _cpm(x: Any) -> str:
    try:
        return f"${float(x):.2f}"
    except (TypeError, ValueError):
        return "n/a"


def _won(env: dict[str, Any]) -> tuple[int, int, Any]:
    t = ((env.get("summary") or {}).get("total")) or {}
    return t.get("won", 0), t.get("deals", 0), t.get("avg_final_cpm")


def negotiation(out: dict[str, Any]) -> str:
    st = out.get("strategies") or {}
    simple = st.get("simple") or {}
    adaptive = st.get("adaptive") or {}
    if simple.get("status") != "ok":
        s_txt = f"Today's negotiator could not run ({simple.get('reason', 'unknown')})."
    else:
        w, d, cpm = _won(simple)
        per = (simple.get("summary") or {}).get("per_personality") or {}
        zero = [f'"{v["title"]}"' for v in per.values() if v.get("deals") and not v.get("won")]
        s_txt = f"Today's negotiator closed {w} of {d} simulated deals (avg {_cpm(cpm)} CPM)"
        s_txt += f" and closed none with the sellers {', '.join(zero)}." if zero else "."
    if adaptive.get("status") == "ok":
        w2, d2, cpm2 = _won(adaptive)
        a_txt = f" Adaptive negotiator closed {w2} of {d2} (avg {_cpm(cpm2)} CPM)."
    elif adaptive.get("status") == "not_available":
        a_txt = " Adaptive negotiator: not in this version."
    else:
        a_txt = f" Adaptive negotiator: {adaptive.get('reason', 'error')}."
    return s_txt + a_txt
