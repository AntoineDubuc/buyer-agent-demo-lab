"""Pure scenario data and math (standard library only, no buyer-agent imports).

Expected spend follows the buyer-agent engine's linear rule
(``PacingEngine.calculate_expected_spend``): expected = allocated *
elapsed / flight duration, with dates read as midnight UTC and rounded to
cents. Spend is then pace% x expected, rounded to cents, and the result is
checked so that round(spend / expected * 100, 2) equals the pace exactly.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent / "data"


def load_json(name: str) -> Any:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


def load_campaign() -> dict[str, Any]:
    c = load_json("campaign.json")
    c.pop("_note", None)
    return c


def load_pacing_scenarios() -> dict[str, Any]:
    return load_json("pacing_scenarios.json")


def parse_utc(value: str) -> datetime:
    """Parse '2026-07-01' or '2026-08-15T00:00:00Z' as an aware UTC datetime."""
    v = value.strip()
    if len(v) == 10:
        return datetime.strptime(v, "%Y-%m-%d").replace(tzinfo=UTC)
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    dt = datetime.fromisoformat(v)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def channel_budgets(campaign: dict[str, Any]) -> dict[str, float]:
    """Allocated budget per channel: budget_amount, else total * pct / 100 (CONTRACTS)."""
    total = float(campaign["total_budget"])
    out: dict[str, float] = {}
    for ch in campaign["channels"]:
        amt = ch.get("budget_amount")
        out[ch["channel"]] = round(float(amt) if amt is not None else total * float(ch["budget_pct"]) / 100.0, 2)
    return out


def flight_fraction(flight_start: str, flight_end: str, as_of: str) -> float:
    start, end, now = parse_utc(flight_start), parse_utc(flight_end), parse_utc(as_of)
    if now <= start:
        return 0.0
    if now >= end:
        return 1.0
    return (now - start).total_seconds() / (end - start).total_seconds()


def linear_expected(allocated: float, flight_start: str, flight_end: str, as_of: str) -> float:
    return round(allocated * flight_fraction(flight_start, flight_end, as_of), 2)


def pacing_pct(spend: float, expected: float) -> float:
    if expected <= 0:
        return 0.0
    return round(spend / expected * 100.0, 2)


def spend_for_pace(pace_pct: float, expected: float) -> float:
    """Smallest cent amount whose pacing_pct rounds to exactly pace_pct."""
    spend = round(expected * pace_pct / 100.0, 2)
    # Nudge by a cent if rounding lands off-target (never needed for the shipped data,
    # but keeps the guarantee for any new scenario).
    for delta in (0.0, 0.01, -0.01, 0.02, -0.02):
        cand = round(spend + delta, 2)
        if pacing_pct(cand, expected) == round(float(pace_pct), 2):
            return cand
    raise ValueError(f"cannot hit pace {pace_pct}% exactly on expected {expected}")


def scenario_numbers(campaign: dict[str, Any], scenario: dict[str, Any], as_of: str) -> dict[str, Any]:
    """Per-channel allocated / expected / spend / pace for one scenario (None pace = no delivery)."""
    budgets = channel_budgets(campaign)
    rows = {}
    for ch, alloc in budgets.items():
        exp = linear_expected(alloc, campaign["flight_start"], campaign["flight_end"], as_of)
        pace = None if scenario.get("pace") is None else float(scenario["pace"][ch])
        spend = None if pace is None else spend_for_pace(pace, exp)
        rows[ch] = {"allocated_budget": alloc, "expected_spend": exp, "spend": spend, "pace_pct": pace}
    return rows


def build_feed(campaign: dict[str, Any], scenario: dict[str, Any], campaign_id: str,
               cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Delivery file content in the CONTRACTS format. No delivery -> empty list."""
    as_of = cfg["as_of"]
    if scenario.get("pace") is None:
        return []
    nums = scenario_numbers(campaign, scenario, as_of)
    channels = {}
    deals = []
    for ch, row in nums.items():
        cpm = float(cfg["cpm"][ch])
        channels[ch] = {
            "spend": row["spend"],
            "impressions": int(round(row["spend"] / cpm * 1000)),
            "effective_cpm": cpm,
            "fill_rate": float(cfg["fill_rate"][ch]),
        }
        deals.append({"deal_id": f"DEAL-{ch}-01", "allocated_budget": row["allocated_budget"], "spend": row["spend"]})
    return [{"campaign_id": campaign_id, "as_of": as_of, "channels": channels, "deals": deals}]
