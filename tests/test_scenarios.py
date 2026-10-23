import unittest

from demo_lab import scenarios as S


class ScenarioMath(unittest.TestCase):
    def setUp(self):
        self.c = S.load_campaign()
        self.cfg = S.load_pacing_scenarios()

    def test_budget_pct_is_0_to_100_scale_and_sums_to_100(self):
        pcts = [ch["budget_pct"] for ch in self.c["channels"]]
        self.assertEqual(sum(pcts), 100)
        self.assertEqual(S.channel_budgets(self.c), {"CTV": 75000.0, "DISPLAY": 45000.0, "AUDIO": 30000.0})

    def test_flight_is_91_days_and_expected_total_matches_engine_convention(self):
        f = S.flight_fraction(self.c["flight_start"], self.c["flight_end"], self.cfg["as_of"])
        self.assertAlmostEqual(f, 45 / 91, places=12)
        self.assertEqual(S.linear_expected(150000, self.c["flight_start"], self.c["flight_end"], self.cfg["as_of"]),
                         74175.82)

    def test_every_scenario_percentage_is_exact(self):
        for sc in self.cfg["scenarios"]:
            nums = S.scenario_numbers(self.c, sc, self.cfg["as_of"])
            for ch, row in nums.items():
                if sc["pace"] is None:
                    self.assertIsNone(row["spend"])
                    continue
                with self.subTest(scenario=sc["id"], channel=ch):
                    self.assertEqual(S.pacing_pct(row["spend"], row["expected_spend"]), float(sc["pace"][ch]))
                    self.assertEqual(row["spend"], round(row["spend"], 2))

    def test_ctv_cant_spend_numbers(self):
        sc = next(s for s in self.cfg["scenarios"] if s["id"] == "ctv_cant_spend")
        n = S.scenario_numbers(self.c, sc, self.cfg["as_of"])
        self.assertEqual(n["CTV"]["expected_spend"], 37087.91)
        self.assertEqual(n["CTV"]["spend"], 26703.30)
        self.assertEqual(n["DISPLAY"]["spend"], 30041.21)
        self.assertEqual(n["AUDIO"]["spend"], n["AUDIO"]["expected_spend"])

    def test_feed_shape_matches_contract(self):
        sc = self.cfg["scenarios"][0]
        feed = S.build_feed(self.c, sc, "CMP-X", self.cfg)
        self.assertIsInstance(feed, list)
        f = feed[0]
        self.assertEqual(set(f), {"campaign_id", "as_of", "channels", "deals"})
        self.assertEqual(f["campaign_id"], "CMP-X")
        self.assertEqual(f["as_of"], "2026-08-15T00:00:00Z")
        for ch in ("CTV", "DISPLAY", "AUDIO"):
            self.assertEqual(set(f["channels"][ch]), {"spend", "impressions", "effective_cpm", "fill_rate"})
        for d in f["deals"]:
            self.assertEqual(set(d), {"deal_id", "allocated_budget", "spend"})

    def test_no_delivery_scenario_writes_empty_feed(self):
        sc = next(s for s in self.cfg["scenarios"] if s["id"] == "no_delivery_yet")
        self.assertEqual(S.build_feed(self.c, sc, "CMP-X", self.cfg), [])

    def test_five_named_scenarios(self):
        self.assertEqual([s["id"] for s in self.cfg["scenarios"]],
                         ["ctv_cant_spend", "audio_over", "all_on_pace", "two_behind_one_ahead", "no_delivery_yet"])


if __name__ == "__main__":
    unittest.main()
