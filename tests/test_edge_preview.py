"""Validate published development example against data contracts; no network used."""
import json
import math
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "data" / "edges" / "latest.json"


class StoredEdgeAuditTests(unittest.TestCase):
    def test_dated_audit_is_safe_and_consistent(self):
        report = json.loads(REPORT.read_text(encoding="utf-8"))
        raw = json.dumps(report)
        for unsafe in ("apiKey", "ODDS_API_KEY", "api.the-odds-api.com", "Bearer ", '"bookmakers":'):
            self.assertNotIn(unsafe, raw)
        self.assertIsInstance(report["developmentPreview"], bool)
        self.assertEqual(report["schemaVersion"], 1)
        self.assertRegex(report["forecastDate"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertGreater(report["summary"]["matchedFixtures"], 0)
        self.assertEqual(report["summary"]["marketsPriced"], len(report["picks"]))
        self.assertEqual(report["summary"]["positiveEdges"],
                         sum(item["positiveEdge"] for item in report["picks"]))

    def test_no_market_duplicate_and_pre_match_prices_only(self):
        report = json.loads(REPORT.read_text(encoding="utf-8"))
        seen = set()
        from datetime import datetime
        stamp = datetime.fromisoformat(report["oddsRetrievedAtUtc"].replace("Z", "+00:00"))
        for pick in report["picks"]:
            pair = (pick["fixtureId"], pick["market"])
            self.assertNotIn(pair, seen)
            seen.add(pair)
            self.assertGreater(datetime.fromisoformat(pick["kickoffUtc"]), stamp)
            self.assertTrue(math.isfinite(pick["odds"]))
            self.assertTrue(0 <= pick["modelProbability"] <= 1)
            self.assertGreater(pick["odds"], 1)
            self.assertAlmostEqual(pick["edgePp"],
                                   (pick["modelProbability"] - 1 / pick["odds"]) * 100,
                                   delta=0.011)
            self.assertEqual(pick["positiveEdge"], pick["edgePp"] > 0)

    def test_ranked_highest_probability_with_positive_edge_first(self):
        report = json.loads(REPORT.read_text(encoding="utf-8"))
        ranked = sorted(report["picks"], key=lambda p: (
            -int(p["positiveEdge"]), -p["modelProbability"], -p["edgePp"],
            p["fixtureId"], p["market"]
        ))
        self.assertEqual(report["picks"], ranked)


if __name__ == "__main__":
    unittest.main()
