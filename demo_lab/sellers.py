"""Simulated sellers (pure Python, standard library only).

Each round the seller answers p' = max(F, p - k * (p - offer)), rounded to
cents, and accepts (at the buyer's offer) when offer >= p'. A
"floor-accepting" seller also accepts any offer >= F. A "stubborn" seller
uses k = 0 for its first ``stubborn_rounds`` replies after the opening,
then ``k_after``. Simulated sellers. Not evidence about real sellers.
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass
from typing import Any

from .scenarios import load_json


@dataclass
class SellerParams:
    personality: str
    list_price: float
    floor: float
    k: float
    accept_at_floor: bool = False
    stubborn_rounds: int = 0
    k_after: float | None = None


class SellerModel:
    """Stateful seller for one negotiation."""

    def __init__(self, params: SellerParams) -> None:
        self.params = params
        self.price: float | None = None
        self.replies = 0
        self.accepted_by_buyer = False
        self.declined_by_buyer = False

    def _k(self) -> float:
        p = self.params
        if p.stubborn_rounds and self.replies <= p.stubborn_rounds:
            return 0.0
        if p.stubborn_rounds and p.k_after is not None:
            return p.k_after
        return p.k

    def respond(self, offer: float) -> tuple[str, float]:
        """Return (action, price): action is "counter" or "accept"."""
        p = self.params
        offer = round(float(offer), 2)
        if self.price is None:
            self.price = p.list_price
            self.replies = 1
            if offer >= p.list_price:
                self.price = offer
                return "accept", offer
            return "counter", p.list_price
        k = self._k()
        self.replies += 1
        new_price = round(max(p.floor, self.price - k * (self.price - offer)), 2)
        if offer >= new_price or (p.accept_at_floor and offer >= p.floor):
            self.price = offer
            return "accept", offer
        self.price = new_price
        return "counter", new_price


def load_config() -> dict[str, Any]:
    cfg = load_json("sellers.json")
    cfg.pop("_note", None)
    return cfg


def base_params(personality: dict[str, Any], rng: random.Random | None = None) -> SellerParams:
    """Exact parameters for a named personality (random one drawn from rng)."""
    if "random" in personality:
        r = rng or random.Random(0)
        spec = personality["random"]
        lp = round(r.uniform(*spec["list_price"]), 2)
        fl = round(lp * r.uniform(*spec["floor_frac"]), 2)
        k = round(r.uniform(*spec["k"]), 3)
        return SellerParams(personality["id"], lp, fl, k)
    return SellerParams(
        personality=personality["id"],
        list_price=float(personality["list_price"]),
        floor=float(personality["floor"]),
        k=float(personality["k"]),
        accept_at_floor=bool(personality.get("accept_at_floor", False)),
        stubborn_rounds=int(personality.get("stubborn_rounds", 0)),
        k_after=personality.get("k_after"),
    )


def tournament_deals(cfg: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Deterministic deal list: personalities round-robin, seeded jitter on named ones."""
    cfg = cfg or load_config()
    t = cfg["tournament"]
    rng = random.Random(t["seed"])
    j = float(t["jitter"])
    pers = cfg["personalities"]
    deals = []
    for i in range(int(t["deals"])):
        per = pers[i % len(pers)]
        if "random" in per:
            sp = base_params(per, rng)
        else:
            sp = base_params(per)
            sp.list_price = round(sp.list_price * rng.uniform(1 - j, 1 + j), 2)
            sp.floor = round(min(sp.list_price, sp.floor * rng.uniform(1 - j, 1 + j)), 2)
            if sp.k:
                sp.k = round(max(0.0, sp.k + rng.uniform(-0.02, 0.02)), 3)
            if sp.k_after:
                sp.k_after = round(max(0.0, sp.k_after + rng.uniform(-0.05, 0.05)), 3)
        deals.append({"deal_id": f"SIM-{i + 1:03d}", "params": asdict(sp)})
    return deals


def showcase_params(cfg: dict[str, Any] | None = None) -> list[SellerParams]:
    """One exact-parameter seller per personality (random drawn from the tournament seed)."""
    cfg = cfg or load_config()
    rng = random.Random(cfg["tournament"]["seed"])
    return [base_params(p, rng) for p in cfg["personalities"]]


def params_from_dict(d: dict[str, Any]) -> SellerParams:
    return SellerParams(**d)


def reference_simple_loop(params: SellerParams, target=20.0, max_cpm=30.0, step=2.0, max_rounds=6,
                          max_seller_rounds=20) -> dict[str, Any]:
    """Pure replica of baseline auto_negotiate + SimpleThresholdStrategy.

    Used only by the lab's own tests to pin seller behaviour; the real run
    always goes through buyer-agent's NegotiationClient.auto_negotiate.
    """
    s = SellerModel(params)
    rounds = []
    offer = target
    action, price = s.respond(offer)
    rounds.append((offer, price, action))
    if action == "accept" or price <= max_cpm:
        return {"outcome": "accepted", "final": price, "rounds": rounds}
    prev = None
    while True:
        rc = len(rounds)
        if rc >= max_rounds or (prev is not None and rc > 0 and price >= prev):
            return {"outcome": "walked_away", "final": None, "rounds": rounds}
        offer = min(rounds[-1][0] + step, max_cpm)
        prev = price
        action, price = s.respond(offer)
        if action == "counter" and len(rounds) + 1 >= max_seller_rounds:
            action = "reject"
        rounds.append((offer, price, action))
        if action == "accept" or price <= max_cpm:
            return {"outcome": "accepted", "final": price, "rounds": rounds}
        if action == "reject":
            return {"outcome": "walked_away", "final": None, "rounds": rounds}
