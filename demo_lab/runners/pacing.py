"""Pacing runner: runs INSIDE a buyer-agent interpreter.

Per scenario: create the campaign via CampaignStore, walk it to ACTIVE with
the store's own transitions, write the delivery feed, point
PACING_DELIVERY_FILE at it, then call run_pacing_check (if it exists) and
check_pacing. Every capability is feature-detected.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .. import common, headlines, scenarios
from ..creatives import format_spec_for, load_manifest


def _brief_for_store(campaign: dict[str, Any]) -> dict[str, Any]:
    budgets = scenarios.channel_budgets(campaign)
    channels = [dict(ch, budget_amount=budgets[ch["channel"]]) for ch in campaign["channels"]]
    return {
        "advertiser_id": campaign["advertiser_id"],
        "campaign_name": campaign["campaign_name"],
        "total_budget": float(campaign["total_budget"]),
        "currency": campaign["currency"],
        "flight_start": campaign["flight_start"],
        "flight_end": campaign["flight_end"],
        "channels": json.dumps(channels),
    }


def validate_brief(campaign: dict[str, Any]) -> dict[str, Any]:
    """Check the sample brief against the product's own CampaignBrief model."""
    try:
        from ad_buyer.models.campaign_brief import CampaignBrief
    except Exception as exc:  # noqa: BLE001
        return common.not_available(f"CampaignBrief not importable: {exc}")
    try:
        b = CampaignBrief(**campaign)
        return common.ok({"channels": [
            {"channel": c.channel.value, "budget_pct": c.budget_pct, "budget_amount": c.budget_amount,
             "format_prefs": c.format_prefs} for c in b.channels]})
    except Exception as exc:  # noqa: BLE001
        return common.error(exc)


async def _maybe_validate_creatives(mcp: Any, names: set[str], store: Any, cid: str) -> dict[str, Any]:
    if "validate_campaign_creatives" in names:
        return await common.call_tool(mcp, names, "validate_campaign_creatives", {"campaign_id": cid})
    if hasattr(store, "validate_campaign_creatives"):
        try:
            return common.ok(store.validate_campaign_creatives(cid))
        except Exception as exc:  # noqa: BLE001
            return common.error(exc)
    return common.not_available("no creative validation in this version")


async def walk_to_active(mcp: Any, names: set[str], store: Any, cid: str) -> dict[str, Any]:
    """DRAFT -> PLANNING -> BOOKING -> READY -> ACTIVE using the store's transitions.

    Valid setup creatives are attached first so a version with a creative
    gate can still reach READY. If a transition is refused anyway, fall back
    to a direct status write and record that the fallback was used.
    """
    steps: list[dict[str, Any]] = []
    manifest = load_manifest()
    for name in ("start_planning", "start_booking"):
        try:
            getattr(store, name)(cid)
            steps.append({"step": name, "status": "ok"})
        except Exception as exc:  # noqa: BLE001
            steps.append({"step": name, **common.error(exc)})
    for fx in manifest["setup_fixtures"]:
        store.save_creative_asset(campaign_id=cid, asset_name=fx["asset_name"], asset_type=fx["asset_type"],
                                  format_spec=json.dumps(format_spec_for(fx)), validation_status="pending")
    v = await _maybe_validate_creatives(mcp, names, store, cid)
    steps.append({"step": "validate_campaign_creatives", "status": v["status"], "reason": v.get("reason", "")})
    for name in ("mark_ready", "activate_campaign"):
        try:
            getattr(store, name)(cid)
            steps.append({"step": name, "status": "ok"})
        except Exception as exc:  # noqa: BLE001
            steps.append({"step": name, **common.error(exc)})
    status = (store.get_campaign(cid) or {}).get("status")
    fallback = False
    if status != "active":
        store.update_campaign_status(cid, "active")
        fallback = True
        status = (store.get_campaign(cid) or {}).get("status")
    return {"final_status": status, "fallback_direct_status_write": fallback, "steps": steps}


async def run(workdir: Path) -> dict[str, Any]:
    from ad_buyer.config.settings import Settings
    from ad_buyer.interfaces.mcp_server import mcp
    from ad_buyer.storage.campaign_store import CampaignStore

    campaign = scenarios.load_campaign()
    cfg = scenarios.load_pacing_scenarios()
    names = await common.list_tool_names(mcp)
    try:
        has_setting = hasattr(Settings(), "pacing_delivery_file")
    except Exception:  # noqa: BLE001
        has_setting = False
    capabilities = {
        "run_pacing_check_tool": "run_pacing_check" in names,
        "create_campaign_tool": "create_campaign" in names,
        "check_pacing_tool": "check_pacing" in names,
        "setting_pacing_delivery_file": has_setting,
    }
    probe_unknown = await common.call_tool(mcp, names, "check_pacing", {"campaign_id": "CMP-DOES-NOT-EXIST"})
    probe_unknown_run = await common.call_tool(mcp, names, "run_pacing_check",
                                               {"campaign_id": "CMP-DOES-NOT-EXIST", "as_of": cfg["as_of"]})

    store = CampaignStore(os.environ["DATABASE_URL"])
    store.connect()
    out = []
    try:
        for sc in cfg["scenarios"]:
            row: dict[str, Any] = {"id": sc["id"], "title": sc["title"], "description": sc["description"],
                                   "expect_after": sc["expect_after"],
                                   "input": scenarios.scenario_numbers(campaign, sc, cfg["as_of"])}
            try:
                cid = store.create_campaign(_brief_for_store(campaign))
                row["campaign_id"] = cid
                row["setup"] = await walk_to_active(mcp, names, store, cid)
                feed = scenarios.build_feed(campaign, sc, cid, cfg)
                feed_path = workdir / f"delivery_{sc['id']}.json"
                feed_path.write_text(json.dumps(feed, indent=2), encoding="utf-8")
                os.environ["PACING_DELIVERY_FILE"] = str(feed_path)
                row["feed"] = feed
                row["run_pacing_check"] = await common.call_tool(
                    mcp, names, "run_pacing_check", {"campaign_id": cid, "as_of": cfg["as_of"]})
                row["check_pacing"] = await common.call_tool(mcp, names, "check_pacing", {"campaign_id": cid})
                row["status"] = "ok"
            except Exception as exc:  # noqa: BLE001
                row.update(common.error(exc))
            row["headline"] = headlines.pacing(row)
            out.append(row)
    finally:
        store.disconnect()
        os.environ.pop("PACING_DELIVERY_FILE", None)
    return {"capabilities": capabilities, "as_of": cfg["as_of"],
            "brief_check": validate_brief(campaign),
            "probes": {"unknown_campaign_check_pacing": probe_unknown,
                       "unknown_campaign_run_pacing_check": probe_unknown_run},
            "scenarios": out}
