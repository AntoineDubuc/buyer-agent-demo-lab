import unittest
from decimal import Decimal

from demo_lab import acceptance as A
from demo_lab import budget_desk_data as D


class BudgetDeskData(unittest.TestCase):
    def test_acme_rows_reproduce_spend_to_date_before_15_aug(self):
        rows = D.acme_rows("X")
        got = D.spend_before(rows, "X", "2026-08-15")
        self.assertEqual(got, {"CTV": Decimal("26703.30"), "DISPLAY": Decimal("30041.21"), "AUDIO": Decimal("14835.16")})

    def test_window_spend_and_conversions_give_the_prd_cpa(self):
        rows = [r for r in D.acme_rows("X") if "2026-08-01" <= r["date"] <= "2026-08-14"]
        self.assertEqual(len(rows), 14)
        for ch, cpa in (("CTV", "48.10"), ("DISPLAY", "39.20"), ("AUDIO", "52.75")):
            spend = sum(Decimal(str(r["channels"][ch]["spend"])) for r in rows)
            conv = sum(r["channels"][ch]["conversions"] for r in rows)
            self.assertEqual(D.cents(spend / conv), Decimal(cpa), ch)

    def test_blocked_variant_keeps_spend_to_date_and_moves_the_window(self):
        rows = D.acme_rows("X", window_spend={"DISPLAY": "11460.00"})
        self.assertEqual(D.spend_before(rows, "X", "2026-08-15")["DISPLAY"], Decimal("30041.21"))
        win = [r for r in rows if r["date"] >= "2026-08-01"]
        spend = sum(Decimal(str(r["channels"]["DISPLAY"]["spend"])) for r in win)
        self.assertEqual(D.cents(spend / 200), Decimal("57.30"))

    def test_conversion_split_puts_the_remainder_on_14_aug(self):
        rows = [r for r in D.acme_rows("X") if r["date"] >= "2026-08-01"]
        self.assertEqual([r["channels"]["CTV"]["conversions"] for r in rows], [14] * 13 + [18])
        self.assertEqual([r["channels"]["AUDIO"]["conversions"] for r in rows], [7] * 13 + [9])

    def test_beta_rows_sum_to_the_prd_totals_and_have_no_conversions(self):
        rows = D.beta_rows("B")
        got = D.spend_before(rows, "B", "2026-09-15")
        self.assertEqual((got["DISPLAY"], got["AUDIO"]), (Decimal("39972.42"), Decimal("22786.20")))
        self.assertTrue(all("conversions" not in v for r in rows for v in r["channels"].values()))

    def test_no_row_on_or_after_flight_end(self):
        self.assertTrue(all(r["date"] < "2026-09-30" for r in D.acme_rows("X") + D.beta_rows("B")))


class BudgetDeskCriteria(unittest.TestCase):
    def test_missing_tools_fail_cleanly_with_one_line(self):
        doc = {"result": {"status": "ok", "capabilities": {"run_budget_desk_check": False}, "steps": {},
                          "skipped": "tools missing: run_budget_desk_check"}}
        checks = A.evaluate("budget-desk", doc)
        self.assertFalse(A.passed(checks))
        self.assertIn("tools missing", checks[-1].observed)

    def test_empty_steps_fail_every_criterion_without_crashing(self):
        doc = {"result": {"status": "ok", "capabilities": {"x": True}, "key_minted": True, "steps": {}},
               "network": {"outbound_attempts_blocked": []}}
        checks = A.evaluate("budget-desk", doc)
        self.assertGreater(len(checks), 50)
        self.assertFalse(A.passed(checks))


if __name__ == "__main__":
    unittest.main()
