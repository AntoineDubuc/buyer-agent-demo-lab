"""Budget Move Desk sample data, built by the lab itself (standard library only).

The lab writes its own campaigns and delivery rows so it never depends on the
change's seed to produce the numbers it checks. The rules follow the Part 1
PRD (FR-021): spend is split evenly per day, rounded down to cents, with the
remainder on the last day of each block; conversions likewise in whole units.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from typing import Any

CHANNELS = ("CTV", "DISPLAY", "AUDIO")

ACME = {
    "campaign_name": "Acme Spring Launch",
    "advertiser_id": "ADV-ACME",
    "total_budget": 150000.0,
    "flight_start": "2026-07-01",
    "flight_end": "2026-09-30",
    "budgets": {"CTV": 75000.0, "DISPLAY": 45000.0, "AUDIO": 30000.0},
}
BETA = {
    "campaign_name": "Beta Fall Push",
    "advertiser_id": "ADV-BETA",
    "total_budget": 100000.0,
    "flight_start": "2026-09-01",
    "flight_end": "2026-09-30",
    "budgets": {"CTV": 0.0, "DISPLAY": 60000.0, "AUDIO": 40000.0},
}

# "The Acme 15 Aug data": spend to date before 15 Aug, and the 1-14 Aug window.
ACME_TO_DATE = {"CTV": "26703.30", "DISPLAY": "30041.21", "AUDIO": "14835.16"}
ACME_WINDOW_SPEND = {"CTV": "9620.00", "DISPLAY": "7840.00", "AUDIO": "5275.00"}
ACME_WINDOW_CONV = {"CTV": 200, "DISPLAY": 200, "AUDIO": 100}
ACME_TARGETS = {"CTV": 50.00, "DISPLAY": 45.00, "AUDIO": 55.00}
BETA_TO_DATE = {"DISPLAY": "39972.42", "AUDIO": "22786.20"}

CENT = Decimal("0.01")


def cents(x: Decimal) -> Decimal:
    return x.quantize(CENT, ROUND_HALF_UP)


def _days(start: str, n: int) -> list[str]:
    d0 = date.fromisoformat(start)
    return [(d0 + timedelta(days=i)).isoformat() for i in range(n)]


def _split_money(total: str, n: int) -> list[Decimal]:
    t = Decimal(total)
    each = (t / n).quantize(CENT, ROUND_DOWN)
    parts = [each] * n
    parts[-1] = t - each * (n - 1)
    return parts


def _split_units(total: int, n: int) -> list[int]:
    each = total // n
    return [each] * (n - 1) + [total - each * (n - 1)]


def campaign_record(spec: dict[str, Any], campaign_id: str) -> dict[str, Any]:
    """Arguments for CampaignStore.save_campaign (status active)."""
    import json

    total = Decimal(str(spec["total_budget"]))
    channels = []
    for ch in CHANNELS:
        amt = Decimal(str(spec["budgets"][ch]))
        if amt == 0:
            continue
        pct = (amt / total * 100).quantize(CENT, ROUND_HALF_UP)
        channels.append({"channel": ch, "budget_pct": float(pct), "budget_amount": float(amt), "format_prefs": []})
    return {
        "campaign_id": campaign_id,
        "advertiser_id": spec["advertiser_id"],
        "campaign_name": spec["campaign_name"],
        "status": "active",
        "total_budget": spec["total_budget"],
        "currency": "USD",
        "flight_start": spec["flight_start"],
        "flight_end": spec["flight_end"],
        "channels": json.dumps(channels),
    }


def acme_rows(campaign_id: str, *, to_date: dict[str, str] | None = None,
              window_spend: dict[str, str] | None = None,
              window_conv: dict[str, int] | None = None,
              last_day: str = "2026-08-14") -> list[dict[str, Any]]:
    """Acme rows 1 Jul - 14 Aug (or truncated at ``last_day``), with optional overrides.

    Pre-window rows (1-31 Jul) carry spend = to_date - window spend and 0 conversions;
    window rows (1-14 Aug) carry the window spend and conversions.
    """
    to_date = {**ACME_TO_DATE, **(to_date or {})}
    window_spend = {**ACME_WINDOW_SPEND, **(window_spend or {})}
    window_conv = {**ACME_WINDOW_CONV, **(window_conv or {})}
    jul = _days("2026-07-01", 31)
    aug = _days("2026-08-01", 14)
    pre = {ch: _split_money(str(Decimal(to_date[ch]) - Decimal(window_spend[ch])), 31) for ch in CHANNELS}
    win = {ch: _split_money(window_spend[ch], 14) for ch in CHANNELS}
    conv = {ch: _split_units(window_conv[ch], 14) for ch in CHANNELS}
    rows = []
    for i, d in enumerate(jul):
        rows.append({"campaign_id": campaign_id, "date": d,
                     "channels": {ch: {"spend": float(pre[ch][i]), "conversions": 0} for ch in CHANNELS}})
    for i, d in enumerate(aug):
        rows.append({"campaign_id": campaign_id, "date": d,
                     "channels": {ch: {"spend": float(win[ch][i]), "conversions": conv[ch][i]} for ch in CHANNELS}})
    return [r for r in rows if r["date"] <= last_day]


def beta_rows(campaign_id: str) -> list[dict[str, Any]]:
    days = _days("2026-09-01", 14)
    parts = {ch: _split_money(BETA_TO_DATE[ch], 14) for ch in ("DISPLAY", "AUDIO")}
    return [{"campaign_id": campaign_id, "date": d,
             "channels": {ch: {"spend": float(parts[ch][i])} for ch in ("DISPLAY", "AUDIO")}}
            for i, d in enumerate(days)]


def spend_before(rows: list[dict[str, Any]], campaign_id: str, as_of: str) -> dict[str, Decimal]:
    """Reference reading of FR-001: spend to date per channel before ``as_of``."""
    out = {ch: Decimal("0") for ch in CHANNELS}
    for r in rows:
        if r["campaign_id"] == campaign_id and r["date"] < as_of:
            for ch, v in r["channels"].items():
                out[ch] += Decimal(str(v["spend"]))
    return {ch: cents(v) for ch, v in out.items()}
