import unittest

from demo_lab import acceptance as A
from demo_lab import report as R
from demo_lab import sellers as SL


def ch(name, status, dev=0.0):
    return {"channel": name, "status": status, "deviation_pct": dev}


def ok(raw):
    return {"status": "ok", "raw": raw}


def pacing_doc(recs=None, unknown=None):
    cant = {"channel_pacing": [ch("CTV", "behind", -28), ch("DISPLAY", "ahead", 35), ch("AUDIO", "on_track")],
            "recommendations": recs if recs is not None else
            [{"source_channel": "CTV", "target_channel": "DISPLAY", "amount": 7788.46}]}
    quiet = {"channel_pacing": [ch("CTV", "on_track"), ch("DISPLAY", "on_track"), ch("AUDIO", "on_track")],
             "recommendations": []}
    audio = {"channel_pacing": [ch("CTV", "on_track"), ch("DISPLAY", "on_track"), ch("AUDIO", "ahead")],
             "recommendations": []}
    two = {"channel_pacing": [ch("CTV", "behind"), ch("DISPLAY", "ahead"), ch("AUDIO", "behind")],
           "recommendations": [{"source_channel": "CTV", "target_channel": "DISPLAY", "amount": 6675.83}]}
    return {"result": {
        "capabilities": {"run_pacing_check_tool": True},
        "probes": {"unknown_campaign_run_pacing_check": ok(unknown or {"error": "Campaign not found: X"})},
        "scenarios": [
            {"id": "ctv_cant_spend", "run_pacing_check": ok(cant), "check_pacing": ok(cant)},
            {"id": "audio_over", "run_pacing_check": ok(audio)},
            {"id": "all_on_pace", "run_pacing_check": ok(quiet)},
            {"id": "two_behind_one_ahead", "run_pacing_check": ok(two),
             "input": {"DISPLAY": {"spend": 28928.58, "expected_spend": 22252.75}}},
            {"id": "no_delivery_yet", "run_pacing_check": ok({"status": "no_delivery_data"})},
        ]}}


class Pacing(unittest.TestCase):
    def test_good_result_passes_every_criterion(self):
        checks = A.evaluate("pacing", pacing_doc())
        self.assertTrue(A.passed(checks), [c.line() for c in checks if not c.ok])

    def test_two_moves_fails(self):
        recs = [{"source_channel": "CTV", "target_channel": "DISPLAY", "amount": 1},
                {"source_channel": "AUDIO", "target_channel": "DISPLAY", "amount": 1}]
        self.assertFalse(A.passed(A.evaluate("pacing", pacing_doc(recs=recs))))

    def test_zero_amount_fails(self):
        recs = [{"source_channel": "CTV", "target_channel": "DISPLAY", "amount": 0}]
        self.assertFalse(A.passed(A.evaluate("pacing", pacing_doc(recs=recs))))

    def test_missing_tool_fails_without_crashing(self):
        doc = {"result": {"capabilities": {}, "scenarios": [
            {"id": "ctv_cant_spend", "run_pacing_check": {"status": "not_available", "reason": "nope"}}]}}
        checks = A.evaluate("pacing", doc)
        self.assertFalse(any(c.ok for c in checks))
        self.assertTrue(all(c.line().startswith("FAIL  ") for c in checks))

    def test_garbage_never_crashes(self):
        for doc in (None, {}, {"result": None}, {"result": {"scenarios": [1, None, "x"]}},
                    {"result": {"status": "error", "reason": "boom"}}):
            for change in A.CHANGES:
                self.assertFalse(A.passed(A.evaluate(change, doc)))


def asset(fixture, status, reasons, problem=None, name=None):
    return {"fixture": fixture, "asset_name": name or fixture, "product_status": status,
            "product_reasons": reasons, "lab_expected_problem": problem}


class Creatives(unittest.TestCase):
    def doc(self, reason45="This ad is 45 seconds; the slot is 30 seconds.", good_ready=True):
        head = {"id": "headline_three", "final_status": "booking", "became_ready": False,
                "mark_ready": {"raised": True, "message": "fix: long ad: ...; old ad: ..."},
                "assets": [asset("ctv_valid_30s", "valid", []),
                           asset("ctv_too_long_45s", "invalid", [reason45], "p", "long ad"),
                           asset("ctv_vast20", "invalid", ["Needs VAST 4.x"], "p", "old ad")]}
        seven = {"id": "seven_fixtures", "final_status": "booking", "became_ready": False,
                 "assets": [asset("ctv_valid_30s", "valid", [])]
                 + [asset(f"bad{i}", "invalid", ["why"], "p") for i in range(6)]}
        good = {"id": "all_valid", "final_status": "ready" if good_ready else "booking", "became_ready": good_ready,
                "assets": [asset("ctv_valid_30s", "valid", [])]}
        return {"result": {"capabilities": {"validate_campaign_creatives_tool": True},
                           "cases": [head, seven, good]}}

    def test_good_result_passes(self):
        checks = A.evaluate("creatives", self.doc())
        self.assertTrue(A.passed(checks), [c.line() for c in checks if not c.ok])

    def test_reason_must_mention_both_numbers(self):
        self.assertFalse(A.passed(A.evaluate("creatives", self.doc(reason45="Too long."))))

    def test_gate_that_blocks_good_campaigns_fails(self):
        self.assertFalse(A.passed(A.evaluate("creatives", self.doc(good_ready=False))))


class Negotiation(unittest.TestCase):
    def env_from_reference(self):
        deals = []
        for d in SL.tournament_deals():
            r = SL.reference_simple_loop(SL.params_from_dict(d["params"]))
            deals.append({"deal_id": d["deal_id"], "personality": d["params"]["personality"],
                          "outcome": r["outcome"], "final_price": r["final"],
                          "rounds": [{"buyer": o, "seller": p} for o, p, _ in r["rounds"]]})
        return {"status": "ok", "deals": deals}

    def test_reference_simple_matches_itself_and_adaptive_missing_fails(self):
        doc = {"result": {"buyer": {"target_cpm": 20.0, "max_cpm": 30.0, "concession_step": 2.0, "max_rounds": 6},
                          "strategies": {"simple": self.env_from_reference(),
                                         "adaptive": {"status": "not_available", "reason": "missing"}}}}
        by = {c.criterion: c for c in A.evaluate("negotiation", doc)}
        self.assertTrue(by["today's negotiator (Simple) matches the lab's reference loop deal-for-deal"].ok)
        self.assertFalse(A.passed(list(by.values())))

    def test_tampered_simple_fails_regression(self):
        env = self.env_from_reference()
        env["deals"][0]["final_price"] = 12.34
        doc = {"result": {"strategies": {"simple": env}}}
        by = {c.criterion: c for c in A.evaluate("negotiation", doc)}
        self.assertFalse(by["today's negotiator (Simple) matches the lab's reference loop deal-for-deal"].ok)


class PageTable(unittest.TestCase):
    def test_every_page_shows_the_acceptance_table(self):
        html = R.render("pacing", pacing_doc(), pacing_doc())
        self.assertIn("Acceptance check", html)
        self.assertIn("PASS", html)
        for change in A.CHANGES:
            if change not in R.PAGES:  # budget-desk is pass/fail only; it has no before/after page
                continue
            self.assertIn("Acceptance check", R.render(change, {"result": {}}, None))


if __name__ == "__main__":
    unittest.main()
