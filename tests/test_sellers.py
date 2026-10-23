import unittest

from demo_lab import sellers as SL


class SellerDeterminism(unittest.TestCase):
    def test_tournament_is_deterministic_and_sized(self):
        a, b = SL.tournament_deals(), SL.tournament_deals()
        self.assertEqual(a, b)
        self.assertEqual(len(a), 200)
        self.assertEqual(len({d["deal_id"] for d in a}), 200)

    def test_all_six_personalities_appear(self):
        seen = {d["params"]["personality"] for d in SL.tournament_deals()}
        self.assertEqual(seen, {"proportional_conceder", "firm", "floor_accepting", "wall",
                                "stubborn_then_caves", "seeded_random"})

    def test_random_params_within_spec(self):
        for d in SL.tournament_deals():
            p = d["params"]
            if p["personality"] == "seeded_random":
                self.assertTrue(28 <= p["list_price"] <= 45)
                self.assertTrue(0.6 * p["list_price"] - 0.01 <= p["floor"] <= 0.9 * p["list_price"] + 0.01)
                self.assertTrue(0 <= p["k"] <= 0.5)

    def test_same_offers_same_replies(self):
        params = SL.showcase_params()
        for sp in params:
            r1 = [SL.SellerModel(sp).respond(20)]
            s1, s2 = SL.SellerModel(sp), SL.SellerModel(sp)
            t1 = [s1.respond(o) for o in (20, 22, 24, 26, 28, 30)]
            t2 = [s2.respond(o) for o in (20, 22, 24, 26, 28, 30)]
            self.assertEqual(t1, t2)
            self.assertEqual(r1[0], t1[0])

    def test_seller_never_counters_below_floor(self):
        for d in SL.tournament_deals():
            sp = SL.params_from_dict(d["params"])
            s = SL.SellerModel(sp)
            for o in (20, 22, 24, 26, 28, 30):
                act, price = s.respond(o)
                if act == "counter":
                    self.assertGreaterEqual(price, sp.floor)
                if act == "accept":
                    break


class SellerModels(unittest.TestCase):
    """Pinned against a pure replica of baseline auto_negotiate + SimpleThresholdStrategy(20,30,2,6)."""

    def by_id(self, pid):
        return next(p for p in SL.showcase_params() if p.personality == pid)

    def test_conceder_closes_at_28_80_in_four_rounds(self):
        r = SL.reference_simple_loop(self.by_id("proportional_conceder"))
        self.assertEqual(r["outcome"], "accepted")
        self.assertEqual(r["final"], 28.80)
        self.assertEqual([x[1] for x in r["rounds"]], [40.0, 33.7, 30.31, 28.8])

    def test_wall_and_floor_and_stubborn_walk_after_two_rounds(self):
        for pid in ("wall", "floor_accepting", "stubborn_then_caves"):
            r = SL.reference_simple_loop(self.by_id(pid))
            self.assertEqual((r["outcome"], len(r["rounds"])), ("walked_away", 2), pid)

    def test_firm_walks_at_round_cap(self):
        r = SL.reference_simple_loop(self.by_id("firm"))
        self.assertEqual((r["outcome"], len(r["rounds"])), ("walked_away", 6))

    def test_floor_accepting_takes_26(self):
        s = SL.SellerModel(self.by_id("floor_accepting"))
        s.respond(20)
        self.assertEqual(s.respond(25.99), ("counter", 32.0))
        self.assertEqual(s.respond(26.0), ("accept", 26.0))

    def test_stubborn_holds_three_replies_then_concedes_half(self):
        s = SL.SellerModel(self.by_id("stubborn_then_caves"))
        self.assertEqual(s.respond(20), ("counter", 36.0))
        self.assertEqual([s.respond(o) for o in (22, 22, 22)], [("counter", 36.0)] * 3)
        self.assertEqual(s.respond(22), ("counter", 29.0))

    def test_seller_round_cap(self):
        sp = SL.SellerParams("x", 40.0, 39.0, 0.001)
        r = SL.reference_simple_loop(sp, max_rounds=99, max_seller_rounds=20)
        self.assertLessEqual(len(r["rounds"]), 20)


if __name__ == "__main__":
    unittest.main()
