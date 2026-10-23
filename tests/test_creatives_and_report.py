import json
import unittest

from demo_lab import creatives as C
from demo_lab import report as R


class Fixtures(unittest.TestCase):
    def test_valid_vast_parses_to_contract_keys(self):
        fx = next(f for f in C.load_manifest()["fixtures"] if f["id"] == "ctv_valid_30s")
        self.assertEqual(C.format_spec_for(fx), {"vast_version": "4.2", "duration_sec": 30, "mime_type": "video/mp4",
                                                 "width": 1920, "height": 1080, "bitrate_kbps": 15000,
                                                 "channel": "CTV", "slot": "video_30s"})

    def test_each_fixture_differs_from_valid_in_one_way(self):
        by = {f["id"]: C.format_spec_for(f) for f in C.load_manifest()["fixtures"]}
        self.assertEqual(by["ctv_too_long_45s"]["duration_sec"], 45)
        self.assertEqual(by["ctv_vast20"]["vast_version"], "2.0")
        self.assertEqual((by["ctv_wrong_size"]["width"], by["ctv_wrong_size"]["height"]), (640, 480))
        self.assertNotIn("duration_sec", by["ctv_missing_duration"])
        self.assertEqual(by["audio_64kbps"]["bitrate_kbps"], 64)
        self.assertEqual((by["display_300x600"]["width"], by["display_300x600"]["height"]), (300, 600))
        self.assertEqual(len(by), 9)
        good = [f["id"] for f in C.load_manifest()["fixtures"] if not f["expected_problem"]]
        self.assertEqual(good, ["ctv_valid_30s", "display_valid_300x250", "audio_valid_30s"])

    def test_all_valid_case_has_only_good_ads(self):
        m = C.load_manifest()
        fx = {f["id"]: f for f in m["fixtures"]}
        case = next(c for c in m["cases"] if c["id"] == "all_valid")
        self.assertTrue(all(fx[f]["expected_problem"] is None for f in case["fixtures"]))
        self.assertEqual({fx[f]["channel"] for f in case["fixtures"]}, {"CTV", "DISPLAY", "AUDIO"})

    def test_headline_case_has_three(self):
        case = next(c for c in C.load_manifest()["cases"] if c["id"] == "headline_three")
        self.assertEqual(case["fixtures"], ["ctv_valid_30s", "ctv_too_long_45s", "ctv_vast20"])


class ReportRobustness(unittest.TestCase):
    ENVELOPES = [
        {"status": "not_available", "reason": "nope", "raw": None},
        {"status": "error", "reason": "boom", "raw": None},
        {"status": "ok", "raw": {"pacing_status": "no_data", "channel_pacing": []}},
        {"status": "ok", "raw": {"error": "Campaign not found: x"}},
        {},
    ]

    def test_every_change_renders_with_nothing(self):
        for ch in R.PAGES:
            for before, after in ((None, None), ({}, None), ({"result": None}, {"_missing": "x"}),
                                  ({"result": {"status": "error", "reason": "x"}}, None)):
                html = R.render(ch, before, after)
                self.assertIn("<!doctype html>", html)

    def test_pacing_envelope_combinations(self):
        for e1 in self.ENVELOPES:
            for e2 in self.ENVELOPES:
                doc = {"result": {"scenarios": [{"id": "s", "title": "t", "run_pacing_check": e1, "check_pacing": e2}]}}
                self.assertIn("<!doctype html>", R.render("pacing", doc, doc))

    def test_negotiation_envelope_combinations(self):
        for e in self.ENVELOPES:
            doc = {"result": {"personalities": [{"id": "wall", "title": "Wall"}],
                              "strategies": {"simple": e, "adaptive": e}}}
            self.assertIn("<!doctype html>", R.render("negotiation", doc, doc))

    def test_creatives_odd_rows(self):
        doc = {"result": {"cases": [{"id": "headline_three", "assets": [{"product_reasons": "not json"}, {}]},
                                    {"id": "x", "status": "error", "reason": "bad"}]}}
        self.assertIn("<!doctype html>", R.render("creatives", doc, None))

    def test_html_is_escaped(self):
        doc = {"result": {"cases": [{"id": "x", "title": "<script>alert(1)</script>", "assets": []}]}}
        self.assertNotIn("<script>alert", R.render("creatives", doc, None))


if __name__ == "__main__":
    unittest.main()
