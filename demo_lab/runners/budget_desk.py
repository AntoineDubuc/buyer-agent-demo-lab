"""Budget Move Desk runner: runs INSIDE a buyer-agent interpreter.

Each scenario gets its own campaign id and its own delivery file, written by
the lab (budget_desk_data), so scenarios never disturb each other. Every call
goes through the change's agent tools in-process, exactly as an AI assistant
would call them. Every answer is recorded under a step name; the criteria in
budget_desk_criteria read those steps. A missing tool or setting is recorded,
never raised.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .. import budget_desk_data as D
from .. import common

TOOLS = ("run_budget_desk_check", "list_budget_moves", "get_move", "approve_budget_move", "reject_budget_move",
         "mark_move_done", "mark_overspend_handled", "get_budget_rules", "set_budget_rules", "get_budget_history",
         "list_budget_desk_campaigns")
MAIN_TOOLS_SAMPLE = ("check_pacing", "approve_or_reject", "get_pacing_report", "list_pending_approvals")


class Run:
    def __init__(self, mcp: Any, names: set[str], store: Any, workdir: Path) -> None:
        self.mcp, self.names, self.store, self.workdir = mcp, names, store, workdir
        self.steps: dict[str, Any] = {}

    async def call(self, step: str, tool: str, **args: Any) -> Any:
        env = await common.call_tool(self.mcp, self.names, tool, args)
        self.steps[step] = env
        return env.get("raw") if env.get("status") == "ok" else None

    def note(self, step: str, value: Any) -> None:
        self.steps[step] = common.ok(value)

    def campaign(self, cid: str, spec: dict[str, Any] | None = None, **overrides: Any) -> None:
        rec = D.campaign_record(spec or D.ACME, cid)
        rec.update(overrides)
        self.store.save_campaign(**rec)

    def file(self, name: str, rows: list[dict[str, Any]] | str) -> Path:
        path = self.workdir / f"delivery_{name}.json"
        path.write_text(rows if isinstance(rows, str) else json.dumps(rows, indent=1), encoding="utf-8")
        os.environ["PACING_DELIVERY_FILE"] = str(path)
        return path

    def campaign_row(self, cid: str) -> dict[str, Any]:
        return self.store.get_campaign(cid) or {}

    def events(self, cid: str) -> list[dict[str, Any]]:
        try:
            return self.store.get_campaign_events(cid, limit=500)
        except Exception as exc:  # noqa: BLE001
            return [{"error": str(exc)}]


def _first_move(check: Any) -> dict[str, Any]:
    moves = (check or {}).get("moves") or []
    return moves[0] if moves else {}


def _mint_key(label: str) -> str | None:
    try:
        from ad_buyer.auth.factory import get_operator_key_service
        from ad_buyer.models.api_key import OperatorApiKeyCreateRequest

        svc = get_operator_key_service(os.environ["DATABASE_URL"])
        return svc.create_operator_key(OperatorApiKeyCreateRequest(label=label)).api_key
    except Exception:  # noqa: BLE001
        return None


def _refresh_settings() -> None:
    try:
        from ad_buyer.config.settings import get_settings

        get_settings.cache_clear()
    except Exception:  # noqa: BLE001
        pass


async def scenarios(r: Run, key: str | None) -> None:  # noqa: PLR0915 - one linear script, by design
    acme_base = D.acme_rows

    # ---- S01: the 15 Aug worked example, approve, done, next day ------------------------------
    c = "BD-S01"
    r.campaign(c)
    r.file("s01", acme_base(c) + [{"campaign_id": c, "date": "2026-08-15", "channels": {"CTV": {"spend": 1000.0}}}])
    chk = await r.call("s01_check", "run_budget_desk_check", campaign_id=c, as_of="2026-08-15")
    await r.call("s01_check_again", "run_budget_desk_check", campaign_id=c, as_of="2026-08-15")
    mv = _first_move(chk).get("move_id")
    if mv:
        await r.call("s01_approve", "approve_budget_move", move_id=mv, note="Display is winning")
        r.note("s01_campaign_after_approve", r.campaign_row(c))
        r.note("s01_events_after_approve", r.events(c))
        await r.call("s01_reject_approved", "reject_budget_move", move_id=mv, reason="x")
        await r.call("s01_done", "mark_move_done", move_id=mv)
        await r.call("s01_done_again", "mark_move_done", move_id=mv)
        await r.call("s01_history", "get_budget_history", campaign_id=c)
        await r.call("s01_check_next_day", "run_budget_desk_check", campaign_id=c, as_of="2026-08-16")

    # ---- S02: reject, then the next day's smaller repeat is suppressed ------------------------
    c = "BD-S02"
    r.campaign(c)
    r.file("s02", acme_base(c) + [{"campaign_id": c, "date": "2026-08-15", "channels": {"CTV": {"spend": 1000.0}}}])
    chk = await r.call("s02_check", "run_budget_desk_check", campaign_id=c, as_of="2026-08-15")
    mv = _first_move(chk).get("move_id")
    if mv:
        await r.call("s02_reject_blank", "reject_budget_move", move_id=mv, reason="  ")
        await r.call("s02_reject", "reject_budget_move", move_id=mv, reason="New podcast deal starts 5 Sep")
        r.note("s02_campaign_after_reject", r.campaign_row(c))
        await r.call("s02_done_rejected", "mark_move_done", move_id=mv)
        await r.call("s02_check_next_day", "run_budget_desk_check", campaign_id=c, as_of="2026-08-16")

    # ---- S03: a newer check expires an earlier pending move -----------------------------------
    c = "BD-S03"
    r.campaign(c)
    r.file("s03", acme_base(c))
    chk = await r.call("s03_check", "run_budget_desk_check", campaign_id=c, as_of="2026-08-15")
    await r.call("s03_check_next_day", "run_budget_desk_check", campaign_id=c, as_of="2026-08-16")
    mv = _first_move(chk).get("move_id")
    if mv:
        await r.call("s03_move_after", "get_move", move_id=mv)
        await r.call("s03_history", "get_budget_history", campaign_id=c)

    # ---- S04: numbers change after the check ----------------------------------------------------
    c = "BD-S04"
    r.campaign(c)
    r.file("s04", acme_base(c))
    chk = await r.call("s04_check", "run_budget_desk_check", campaign_id=c, as_of="2026-08-15")
    mv = _first_move(chk).get("move_id")
    r.file("s04", acme_base(c, to_date={"DISPLAY": "28252.75"}))
    if mv:
        await r.call("s04_approve", "approve_budget_move", move_id=mv)
        await r.call("s04_move_after", "get_move", move_id=mv)
    await r.call("s04_check_rerun", "run_budget_desk_check", campaign_id=c, as_of="2026-08-15")

    # ---- S05: blocked by results ---------------------------------------------------------------
    c = "BD-S05"
    r.campaign(c)
    r.file("s05", acme_base(c, window_spend={"DISPLAY": "11460.00"}))
    chk = await r.call("s05_check", "run_budget_desk_check", campaign_id=c, as_of="2026-08-15")
    mv = _first_move(chk).get("move_id")
    if mv:
        await r.call("s05_approve_no_override", "approve_budget_move", move_id=mv)

    # ---- S06: unknown results with automatic approval on --------------------------------------
    c = "BD-S06"
    r.campaign(c)
    r.file("s06", acme_base(c, window_conv={"DISPLAY": 40}))
    await r.call("s06_rules", "set_budget_rules", campaign_id=c,
                 changes={"auto_approve": True, "auto_max_per_move": 10000.00,
                          "channels": {k: {"target_cpa": v} for k, v in D.ACME_TARGETS.items()}})
    await r.call("s06_check", "run_budget_desk_check", campaign_id=c, as_of="2026-08-15")

    # ---- S07: fewer than 50 conversions --------------------------------------------------------
    c = "BD-S07"
    r.campaign(c)
    r.file("s07", acme_base(c, window_conv={"DISPLAY": 49}))
    await r.call("s07_check", "run_budget_desk_check", campaign_id=c, as_of="2026-08-15")

    # ---- S08: no target for AUDIO --------------------------------------------------------------
    c = "BD-S08"
    r.campaign(c)
    r.file("s08", acme_base(c))
    await r.call("s08_rules", "set_budget_rules", campaign_id=c,
                 changes={"channels": {"CTV": {"target_cpa": 50.00}, "DISPLAY": {"target_cpa": 45.00},
                                       "AUDIO": {"target_cpa": None}}})
    await r.call("s08_check", "run_budget_desk_check", campaign_id=c, as_of="2026-08-15")

    # ---- S09: one source, two targets; approve both ---------------------------------------------
    c = "BD-S09"
    r.campaign(c)
    r.file("s09", acme_base(c, to_date={"AUDIO": "18835.16"}))
    chk = await r.call("s09_check", "run_budget_desk_check", campaign_id=c, as_of="2026-08-15")
    for i, m in enumerate((chk or {}).get("moves") or []):
        await r.call(f"s09_approve_{i}", "approve_budget_move", move_id=m.get("move_id"))
    r.note("s09_campaign_after", r.campaign_row(c))

    # ---- S10: two targets and a floor ----------------------------------------------------------
    c = "BD-S10"
    r.campaign(c)
    r.file("s10", acme_base(c, to_date={"AUDIO": "18835.16"}))
    await r.call("s10_rules", "set_budget_rules", campaign_id=c, changes={"channels": {"CTV": {"floor": 70000.00}}})
    await r.call("s10_check", "run_budget_desk_check", campaign_id=c, as_of="2026-08-15")

    # ---- S11: locked source; S12: floor leaves less than the minimum ---------------------------
    for c, step, changes in (("BD-S11", "s11", {"channels": {"CTV": {"locked": True}}}),
                             ("BD-S12", "s12", {"channels": {"CTV": {"floor": 74950.00}}})):
        r.campaign(c)
        r.file(step, acme_base(c))
        await r.call(f"{step}_rules", "set_budget_rules", campaign_id=c, changes=changes)
        await r.call(f"{step}_check", "run_budget_desk_check", campaign_id=c, as_of="2026-08-15")

    # ---- S13-S15: automatic approval ------------------------------------------------------------
    auto = {"auto_approve": True, "auto_max_per_move": 6000.00, "auto_max_per_day": 10000.00,
            "auto_max_per_campaign": 20000.00,
            "channels": {"CTV": {"floor": 70000.00, "target_cpa": 50.00}, "DISPLAY": {"target_cpa": 45.00},
                         "AUDIO": {"target_cpa": 55.00}}}
    for c, step, extra, rows_kw in (("BD-S13", "s13", {}, {}),
                                    ("BD-S14", "s14", {"auto_max_per_day": 4000.00}, {}),
                                    ("BD-S15", "s15", {}, {"last_day": "2026-08-12"})):
        r.campaign(c)
        r.file(step, acme_base(c, **rows_kw))
        await r.call(f"{step}_rules", "set_budget_rules", campaign_id=c, changes={**auto, **extra})
        await r.call(f"{step}_check", "run_budget_desk_check", campaign_id=c, as_of="2026-08-15")
        r.note(f"{step}_campaign_after", r.campaign_row(c))

    # ---- S16: rules defaults, save, validation ------------------------------------------------
    c = "BD-S16"
    r.campaign(c)
    await r.call("s16_defaults", "get_budget_rules", campaign_id=c)
    await r.call("s16_set_floor", "set_budget_rules", campaign_id=c, changes={"channels": {"CTV": {"floor": 60000.00}}})
    await r.call("s16_after_floor", "get_budget_rules", campaign_id=c)
    await r.call("s16_history", "get_budget_history", campaign_id=c)
    await r.call("s16_bad_warning", "set_budget_rules", campaign_id=c, changes={"warning_pct": 30})
    await r.call("s16_bad_channel", "set_budget_rules", campaign_id=c, changes={"channels": {"RADIO": {"floor": 1}}})

    # ---- S17: Beta Fall Push overspends; hold; still on hold; handled ---------------------------
    c = "BD-S17"
    r.campaign(c, D.BETA)
    rows = D.beta_rows(c)
    r.file("s17", rows)
    await r.call("s17_check", "run_budget_desk_check", campaign_id=c, as_of="2026-09-15")
    r.note("s17_status_after_check", r.campaign_row(c).get("status"))
    r.file("s17", rows + [{"campaign_id": c, "date": "2026-09-15",
                           "channels": {"DISPLAY": {"spend": 2855.17}, "AUDIO": {"spend": 1627.59}}}])
    await r.call("s17_check_again", "run_budget_desk_check", campaign_id=c, as_of="2026-09-15")
    r.note("s17_status_after_second", r.campaign_row(c).get("status"))
    await r.call("s17_handled", "mark_overspend_handled", campaign_id=c, note="Bids cut in the platform")
    r.note("s17_status_after_handled", r.campaign_row(c).get("status"))
    await r.call("s17_history", "get_budget_history", campaign_id=c)
    await r.call("s17_handled_again", "mark_overspend_handled", campaign_id=c)

    # ---- S18: approving a pending move while the campaign is on hold ---------------------------
    c = "BD-S18"
    r.campaign(c)
    r.file("s18", acme_base(c))
    chk = await r.call("s18_check", "run_budget_desk_check", campaign_id=c, as_of="2026-08-15")
    mv = _first_move(chk).get("move_id")
    if mv:
        r.store.update_campaign_status(c, "pacing_hold")
        await r.call("s18_approve_on_hold", "approve_budget_move", move_id=mv)

    # ---- S19: errors, statuses, boundary, no data --------------------------------------------
    await r.call("s19_unknown_campaign", "run_budget_desk_check", campaign_id="CMP-NOPE", as_of="2026-08-15")
    await r.call("s19_history_unknown", "get_budget_history", campaign_id="CMP-NOPE")
    await r.call("s19_unknown_move", "get_move", move_id="00000000-0000-4000-8000-000000000000")
    await r.call("s19_bad_date", "run_budget_desk_check", campaign_id="BD-S01", as_of="15/08/2026")
    r.campaign("CMP-DRAFT", status="draft")
    r.file("s19_draft", acme_base("CMP-DRAFT"))
    await r.call("s19_draft", "run_budget_desk_check", campaign_id="CMP-DRAFT", as_of="2026-08-15")
    c = "BD-NODATA"
    r.campaign(c)
    r.file("s19_nodata", acme_base("BD-S01"))
    await r.call("s19_no_data", "run_budget_desk_check", campaign_id=c, as_of="2026-07-10")
    await r.call("s19_no_data_history", "get_budget_history", campaign_id=c)
    c = "BD-EDGE"
    r.campaign(c, {**D.ACME, "total_budget": 9100.0, "budgets": {"CTV": 9100.0, "DISPLAY": 0.0, "AUDIO": 0.0}})
    days = [r_["date"] for r_ in acme_base(c)][:45]
    r.file("s19_edge", [{"campaign_id": c, "date": d, "channels": {"CTV": {"spend": 90.0}}} for d in days])
    await r.call("s19_boundary", "run_budget_desk_check", campaign_id=c, as_of="2026-08-15")

    # ---- S20: delivery-file errors -----------------------------------------------------------------
    bad = r.workdir / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    os.environ["PACING_DELIVERY_FILE"] = str(bad)
    r.note("s20_bad_path", str(bad))
    await r.call("s20_unreadable", "run_budget_desk_check", campaign_id="BD-S01", as_of="2026-08-15")
    dup = acme_base("BD-S01")
    r.file("s20_dup", dup + [dict(next(x for x in dup if x["date"] == "2026-08-01"))])
    await r.call("s20_duplicate", "run_budget_desk_check", campaign_id="BD-S01", as_of="2026-08-15")
    os.environ["PACING_DELIVERY_FILE"] = ""
    await r.call("s20_missing", "run_budget_desk_check", campaign_id="BD-S01", as_of="2026-08-15")

    # ---- S21: identity ---------------------------------------------------------------------------
    c = "BD-S21"
    r.campaign(c)
    r.file("s21", acme_base(c))
    chk = await r.call("s21_check", "run_budget_desk_check", campaign_id=c, as_of="2026-08-15")
    mv = _first_move(chk).get("move_id")
    os.environ["BUYER_OPERATOR_KEY"] = ""
    _refresh_settings()
    if mv:
        await r.call("s21_no_identity", "approve_budget_move", move_id=mv)
    await r.call("s21_history_without_identity", "get_budget_history", campaign_id="BD-S01")
    legacy = "lab-legacy-env-key-0000000000000000"
    os.environ["API_KEY"] = legacy
    os.environ["BUYER_OPERATOR_KEY"] = legacy
    _refresh_settings()
    if mv:
        await r.call("s21_legacy", "approve_budget_move", move_id=mv)
    os.environ.pop("API_KEY", None)
    os.environ["BUYER_OPERATOR_KEY"] = key or ""
    _refresh_settings()

    # ---- S22: the change's own seed reproduces the worked example, and is idempotent ------------
    try:
        from ad_buyer.pacing.budget_desk.seed import seed_budget_desk
    except Exception as exc:  # noqa: BLE001
        r.steps["s22_seed"] = common.not_available(f"seed_budget_desk is not importable: {exc}")
        return
    seed_file = r.workdir / "delivery_seed.json"
    try:
        seed_budget_desk(os.environ["DATABASE_URL"], str(seed_file))
        r.note("s22_seed", "ok")
    except Exception as exc:  # noqa: BLE001
        r.steps["s22_seed"] = common.error(exc)
        return
    os.environ["PACING_DELIVERY_FILE"] = str(seed_file)
    chk = await r.call("s22_check", "run_budget_desk_check", campaign_id="CMP-ACME-SPRING", as_of="2026-08-15")
    mv = _first_move(chk).get("move_id")
    if mv:
        await r.call("s22_approve", "approve_budget_move", move_id=mv)
    before = (seed_file.read_bytes(), r.campaign_row("CMP-ACME-SPRING").get("channels"))
    try:
        seed_budget_desk(os.environ["DATABASE_URL"], str(seed_file))
        after = (seed_file.read_bytes(), r.campaign_row("CMP-ACME-SPRING").get("channels"))
        r.note("s22_reseed_unchanged", before == after)
    except Exception as exc:  # noqa: BLE001
        r.steps["s22_reseed_unchanged"] = common.error(exc)


async def run(workdir: Path) -> dict[str, Any]:
    from ad_buyer.interfaces.mcp_server import mcp
    from ad_buyer.storage.campaign_store import CampaignStore

    names = await common.list_tool_names(mcp)
    capabilities = {t: t in names for t in TOOLS}
    capabilities.update({f"main_tool:{t}": t in names for t in MAIN_TOOLS_SAMPLE})
    store = CampaignStore(os.environ["DATABASE_URL"])
    store.connect()
    key = _mint_key("A. Dubuc")
    os.environ["BUYER_OPERATOR_KEY"] = key or ""
    _refresh_settings()
    r = Run(mcp, names, store, workdir)
    try:
        if not all(capabilities[t] for t in TOOLS):
            missing = [t for t in TOOLS if not capabilities[t]]
            return {"capabilities": capabilities, "key_minted": key is not None, "steps": {},
                    "skipped": f"tools missing: {', '.join(missing)}"}
        await scenarios(r, key)
    finally:
        store.disconnect()
        for var in ("PACING_DELIVERY_FILE", "BUYER_OPERATOR_KEY"):
            os.environ.pop(var, None)
    return {"capabilities": capabilities, "key_minted": key is not None, "steps": r.steps}
