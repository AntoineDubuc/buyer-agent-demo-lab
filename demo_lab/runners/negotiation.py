"""Negotiation runner: runs INSIDE a buyer-agent interpreter.

SimulatedSellerClient subclasses buyer-agent's NegotiationClient and
overrides only the four network methods (start_negotiation, counter_offer,
accept, decline) with in-memory sellers, building NegotiationSession /
NegotiationRound the same way client.py does. auto_negotiate itself is the
product's own, untouched. Simulated sellers. Not evidence about real sellers.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from .. import common, headlines
from ..sellers import SellerModel, load_config, params_from_dict, showcase_params, tournament_deals


def make_client_class():
    from ad_buyer.negotiation.client import NegotiationClient
    from ad_buyer.negotiation.models import NegotiationRound, NegotiationSession

    class SimulatedSellerClient(NegotiationClient):
        """In-memory seller; one SellerModel per proposal_id."""

        def __init__(self, sellers: dict[str, SellerModel], max_seller_rounds: int = 20) -> None:
            super().__init__()
            self._sellers = sellers
            self._max_rounds = max_seller_rounds

        async def start_negotiation(self, seller_url, proposal_id, initial_price, strategy,
                                    negotiation_enabled=True, quote_id=None):
            if not negotiation_enabled:
                raise ValueError(f"Negotiation is not enabled on package for proposal {proposal_id}.")
            action, price = self._sellers[proposal_id].respond(initial_price)
            session = NegotiationSession(proposal_id=proposal_id, seller_url=seller_url,
                                         negotiation_id=f"neg-{proposal_id}", current_seller_price=price,
                                         our_last_offer=initial_price, quote_id=quote_id, rounds=[])
            session.rounds.append(NegotiationRound(round_number=1, buyer_price=initial_price,
                                                   seller_price=price, action=action))
            return session

        async def counter_offer(self, session, price):
            seller = self._sellers[session.proposal_id]
            action, sprice = seller.respond(price)
            n = len(session.rounds) + 1
            if action == "counter" and n >= self._max_rounds:
                action = "reject"  # hard cap: auto_negotiate has no round cap of its own
            rnd = NegotiationRound(round_number=n, buyer_price=price, seller_price=sprice, action=action)
            session.current_seller_price = rnd.seller_price
            session.our_last_offer = price
            session.rounds.append(rnd)
            return rnd

        async def accept(self, session):
            self._sellers[session.proposal_id].accepted_by_buyer = True
            return {"status": "accepted", "negotiation_id": session.negotiation_id,
                    "price": session.current_seller_price}

        async def decline(self, session):
            self._sellers[session.proposal_id].declined_by_buyer = True

    return SimulatedSellerClient


def _rounds(result: Any) -> list[dict[str, Any]]:
    return [{"round": r.round_number, "buyer": r.buyer_price, "seller": r.seller_price, "action": r.action}
            for r in result.rounds]


async def _one(client: Any, strategy: Any, proposal_id: str, seconds: float) -> dict[str, Any]:
    try:
        res = await asyncio.wait_for(client.auto_negotiate("sim://seller", proposal_id, strategy), seconds)
    except asyncio.TimeoutError:
        return {"outcome": "error", "reason": f"wall-time cap ({seconds}s) hit", "final_price": None, "rounds": []}
    except NotImplementedError as exc:
        return {"outcome": "error", "reason": f"error: not implemented ({exc})", "final_price": None,
                "rounds": [], "not_implemented": True}
    except Exception as exc:  # noqa: BLE001
        return {"outcome": "error", "reason": f"{type(exc).__name__}: {exc}", "final_price": None, "rounds": []}
    return {"outcome": res.outcome.value, "final_price": res.final_price, "rounds_count": res.rounds_count,
            "rounds": _rounds(res)}


def _summarise(rows: list[dict[str, Any]], personalities: list[dict[str, Any]]) -> dict[str, Any]:
    per = {}
    for p in personalities:
        mine = [r for r in rows if r["personality"] == p["id"]]
        won = [r for r in mine if r["outcome"] == "accepted"]
        per[p["id"]] = {
            "title": p["title"], "deals": len(mine), "won": len(won),
            "walked": sum(1 for r in mine if r["outcome"] == "walked_away"),
            "errors": sum(1 for r in mine if r["outcome"] == "error"),
            "avg_final_cpm": round(sum(r["final_price"] for r in won) / len(won), 2) if won else None,
            "avg_rounds": round(sum(len(r["rounds"]) for r in mine) / len(mine), 2) if mine else None,
        }
    won = [r for r in rows if r["outcome"] == "accepted"]
    return {"per_personality": per, "total": {
        "deals": len(rows), "won": len(won),
        "avg_final_cpm": round(sum(r["final_price"] for r in won) / len(won), 2) if won else None,
        "avg_rounds": round(sum(len(r["rounds"]) for r in rows) / len(rows), 2) if rows else None,
        "errors": sum(1 for r in rows if r["outcome"] == "error")}}


async def run_strategy(name: str, strategy: Any, cfg: dict[str, Any]) -> dict[str, Any]:
    Client = make_client_class()
    caps = cfg["caps"]
    pers = {p["id"]: p for p in cfg["personalities"]}

    # Showcase: one exact-parameter seller per personality, full transcript.
    showcase = []
    for sp in showcase_params(cfg):
        pid = f"SHOW-{sp.personality}"
        client = Client({pid: SellerModel(sp)}, caps["max_seller_rounds"])
        r = await _one(client, strategy, pid, caps["per_deal_seconds"])
        showcase.append({"personality": sp.personality, "title": pers[sp.personality]["title"],
                         "plain": pers[sp.personality]["plain"], "seller": vars(sp), **r})
        if r.get("not_implemented"):
            return common.error("error: not implemented", strategy=name, reason_detail=r["reason"],
                                showcase=showcase)

    # Tournament: seeded deals, same list for every strategy and every version.
    deals = tournament_deals(cfg)
    rows = []
    started = time.monotonic()
    truncated = False
    for d in deals:
        if time.monotonic() - started > caps["per_strategy_seconds"]:
            truncated = True
            break
        sp = params_from_dict(d["params"])
        client = Client({d["deal_id"]: SellerModel(sp)}, caps["max_seller_rounds"])
        r = await _one(client, strategy, d["deal_id"], caps["per_deal_seconds"])
        rows.append({"deal_id": d["deal_id"], "personality": sp.personality, "seller": d["params"],
                     "outcome": r["outcome"], "final_price": r["final_price"], "rounds": r["rounds"],
                     "reason": r.get("reason", "")})
    summary = _summarise(rows, cfg["personalities"])
    return common.ok(None, strategy=name, showcase=showcase, summary=summary, truncated=truncated,
                     deals=[{k: v for k, v in r.items() if k != "seller"} for r in rows])


def _load_adaptive() -> tuple[Any, dict[str, Any]]:
    """Return (class or None, detection info)."""
    info: dict[str, Any] = {}
    try:
        from ad_buyer.negotiation.strategies import AdaptiveStrategy  # contract path

        info["import_path"] = "ad_buyer.negotiation.strategies"
        return AdaptiveStrategy, info
    except ImportError as exc:
        info["package_export"] = f"not exported: {exc}"
    try:
        from ad_buyer.negotiation.strategies.adaptive import AdaptiveStrategy

        info["import_path"] = "ad_buyer.negotiation.strategies.adaptive"
        return AdaptiveStrategy, info
    except ImportError as exc:
        info["module"] = f"not importable: {exc}"
        return None, info


async def run() -> dict[str, Any]:
    cfg = load_config()
    try:
        from ad_buyer.negotiation.strategies import SimpleThresholdStrategy
    except Exception as exc:  # noqa: BLE001
        return {"strategies": {"simple": common.error(exc)}}
    b = cfg["buyer"]
    strategies: dict[str, Any] = {}
    try:
        strategies["simple"] = await run_strategy(
            "simple", SimpleThresholdStrategy(b["target_cpm"], b["max_cpm"], b["concession_step"], b["max_rounds"]),
            cfg)
    except Exception as exc:  # noqa: BLE001
        strategies["simple"] = common.error(exc)

    cls, info = _load_adaptive()
    if cls is None:
        strategies["adaptive"] = common.not_available("AdaptiveStrategy does not exist in this version",
                                                      detection=info)
    else:
        try:
            inst = cls()
        except TypeError as exc:
            strategies["adaptive"] = common.not_available(f"AdaptiveStrategy() needs arguments: {exc}",
                                                          detection=info)
        except Exception as exc:  # noqa: BLE001
            strategies["adaptive"] = common.error(exc, detection=info)
        else:
            try:
                res = await run_strategy("adaptive", inst, cfg)
            except Exception as exc:  # noqa: BLE001
                res = common.error(exc)
            res["detection"] = info
            strategies["adaptive"] = res
    out = {"buyer": b, "tournament": cfg["tournament"], "caps": cfg["caps"],
           "personalities": cfg["personalities"], "strategies": strategies}
    out["headline"] = headlines.negotiation(out)
    return out
