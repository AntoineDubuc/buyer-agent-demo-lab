"""Creative-gate runner: runs INSIDE a buyer-agent interpreter.

Per case: create the campaign, walk it to BOOKING, save the fixtures with
CampaignStore.save_creative_asset (baseline API, status "pending"), call
validate_campaign_creatives if it exists, then try mark_ready and record
whether READY happened, each asset's status and reasons.
"""

from __future__ import annotations

import json
import os
from typing import Any

from .. import common, headlines, scenarios
from ..creatives import format_spec_for, load_manifest
from .pacing import _brief_for_store, _maybe_validate_creatives


def _parse(v: Any) -> Any:
    if isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            return v
    return v


async def run() -> dict[str, Any]:
    from ad_buyer.interfaces.mcp_server import mcp
    from ad_buyer.storage.campaign_store import CampaignStore

    names = await common.list_tool_names(mcp)
    validator_module = True
    try:
        import importlib

        importlib.import_module("ad_buyer.creative.validator")
    except Exception:  # noqa: BLE001
        validator_module = False
    probe_store = CampaignStore(os.environ["DATABASE_URL"])
    capabilities = {
        "validate_campaign_creatives_tool": "validate_campaign_creatives" in names,
        "add_creative_tool": "add_creative" in names,
        "store_validate_campaign_creatives": hasattr(probe_store, "validate_campaign_creatives"),
        "validator_module": validator_module,
    }
    manifest = load_manifest()
    by_id = {f["id"]: f for f in manifest["fixtures"]}
    campaign = scenarios.load_campaign()
    store = CampaignStore(os.environ["DATABASE_URL"])
    store.connect()
    cases = []
    try:
        for case in manifest["cases"]:
            row: dict[str, Any] = {"id": case["id"], "title": case["title"], "description": case["description"],
                                   "expect_after": case.get("expect_after", "")}
            try:
                cid = store.create_campaign(_brief_for_store(campaign))
                store.start_planning(cid)
                store.start_booking(cid)
                row["campaign_id"] = cid
                row["status_before_ready"] = store.get_campaign(cid)["status"]
                ids = {}
                for fid in case["fixtures"]:
                    fx = by_id[fid]
                    spec = format_spec_for(fx)
                    aid = store.save_creative_asset(campaign_id=cid, asset_name=fx["asset_name"],
                                                    asset_type=fx["asset_type"], format_spec=json.dumps(spec),
                                                    validation_status="pending")
                    ids[aid] = {"fixture": fid, "format_spec": spec}
                row["validation_call"] = await _maybe_validate_creatives(mcp, names, store, cid)
                try:
                    store.mark_ready(cid)
                    row["mark_ready"] = {"status": "ok", "raised": False, "message": ""}
                except Exception as exc:  # noqa: BLE001
                    row["mark_ready"] = {"status": "ok", "raised": True, "exception": type(exc).__name__,
                                         "message": str(exc)}
                row["final_status"] = store.get_campaign(cid)["status"]
                row["became_ready"] = row["final_status"] == "ready"
                assets = []
                for a in store.list_creative_assets(campaign_id=cid):
                    info = ids.get(a["asset_id"], {})
                    fx = by_id.get(info.get("fixture"), {})
                    assets.append({
                        "asset_id": a["asset_id"], "fixture": info.get("fixture"), "asset_name": a["asset_name"],
                        "asset_type": a["asset_type"], "channel": fx.get("channel"), "slot": fx.get("slot"),
                        "format_spec": info.get("format_spec"),
                        "lab_expected_problem": fx.get("expected_problem"),
                        "product_status": a.get("validation_status"),
                        "product_reasons": _parse(a.get("validation_errors")),
                    })
                order = {f: i for i, f in enumerate(case["fixtures"])}
                assets.sort(key=lambda x: order.get(x["fixture"], 99))
                row["assets"] = assets
                rep = await common.call_tool(mcp, names, "get_campaign_report", {"campaign_id": cid})
                row["report_creative_summary"] = (
                    common.ok((rep.get("raw") or {}).get("creative_summary")) if rep["status"] == "ok" else rep)
                row["status"] = "ok"
            except Exception as exc:  # noqa: BLE001
                row.update(common.error(exc))
            row["headline"] = headlines.creatives(row)
            cases.append(row)
    finally:
        store.disconnect()
    return {"capabilities": capabilities, "cases": cases}
