"""BTTS forecast accuracy and priced-market coverage stay strictly separate."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from btts_history import build, recalculate


def fixture(i, yes=.62, division="E0"):
    return {
        "id": f"2026-10-31|{division}|home{i}|away{i}",
        "date": "2026-10-31", "division": division,
        "scoreline": {"markets": {"btts": yes, "no_btts": 1 - yes}},
    }


def snap(*games):
    return {"date": "2026-10-31", "status": "frozen-prekickoff",
            "games": list(games)}


def edge(*picks):
    return {"status": "compared", "picks": list(picks)}


def selection(g, market, odds=1.9):
    return {"fixtureId": g["id"], "market": market, "odds": odds}


class BttsHistoryTests(unittest.TestCase):
    def test_unpriced_forecasts_are_graded_by_side_league_band(self):
        yes_won = fixture(1, .63)
        no_won = fixture(2, .34, "E1")
        yes_lost = fixture(3, .71, "EC")
        pending = fixture(4, .58)
        results = {yes_won["id"]: {"score": "2-1"},
                   no_won["id"]: {"score": "0-2"},
                   yes_lost["id"]: {"score": "0-0"}}
        shots = [snap(yes_won, no_won, yes_lost, pending)]
        original = json.dumps(shots, sort_keys=True)
        report = build(shots, results, {"2026-10-31": edge(selection(yes_won, "btts"))})
        self.assertEqual(json.dumps(shots, sort_keys=True), original)
        self.assertEqual(report["summary"]["forecasts"], 4)
        self.assertEqual(report["summary"]["graded"], 3)
        self.assertEqual(report["summary"]["correct"], 2)
        self.assertEqual(report["summary"]["pending"], 1)
        self.assertEqual(report["byOutcome"]["Yes"]["graded"], 2)
        self.assertEqual(report["byOutcome"]["Yes"]["correct"], 1)
        self.assertEqual(report["byOutcome"]["No"]["correct"], 1)
        self.assertEqual(report["byLeague"]["EC"]["graded"], 1)
        self.assertEqual(report["byProbabilityBand"]["70–79.9%"]["correct"], 0)
        self.assertEqual(report["coverageByDay"]["2026-10-31"]["bttsQuotedFixtures"], 1)
        self.assertEqual(report["coverageByDay"]["2026-10-31"]["bttsQuotedOutcomes"], 1)
        self.assertNotIn("profitGbp", json.dumps(report))
        self.assertNotIn("roiPct", json.dumps(report))

    def test_low_coverage_requires_enough_matched_qualified_fixtures(self):
        matches = [fixture(i) for i in range(6)]
        prices = [selection(g, "home_win") for g in matches]
        prices += [selection(matches[0], "btts"), selection(matches[0], "no_btts")]
        result = build([snap(*matches)], {}, {"2026-10-31": edge(*prices)})
        coverage = result["coverageByDay"]["2026-10-31"]
        self.assertEqual(coverage["qualified55MatchedFixtures"], 6)
        self.assertEqual(coverage["bttsQuotedFixtures"], 1)
        self.assertEqual(coverage["bttsQuotedOutcomes"], 2)
        self.assertEqual(coverage["matchedCoveragePct"], 16.67)
        self.assertTrue(coverage["lowCoverageWarning"])

    def test_no_capture_is_not_zero_bookmaker_coverage(self):
        games = [fixture(i) for i in range(6)]
        report = build([snap(*games)], {}, {})
        coverage = report["coverageByDay"]["2026-10-31"]
        self.assertFalse(coverage["captureAvailable"])
        self.assertIsNone(coverage["bttsQuotedFixtures"])
        self.assertIsNone(coverage["matchedCoveragePct"])
        self.assertFalse(coverage["lowCoverageWarning"])

    def test_does_not_grade_unfrozen_or_invalid_scores(self):
        g = fixture(1)
        invalid = snap(g)
        invalid["status"] = "not-frozen"
        self.assertEqual(build([invalid], {g["id"]: {"score": "2-1"}}, {})["summary"]["graded"], 0)
        result = build([snap(g)], {g["id"]: {"score": "not final"}}, {})
        self.assertEqual(result["summary"]["pending"], 1)

    def test_derived_file_recalculation_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            archive = root / "data" / "snapshots"
            archive.mkdir(parents=True)
            g = fixture(1)
            original = snap(g)
            shot_path = archive / "2026-10-31.json"
            shot_path.write_text(json.dumps(original))
            (root / "data" / "settlements.json").write_text(
                json.dumps({g["id"]: {"score": "1-1"}}))
            self.assertTrue(recalculate(root))
            output = json.loads((root / "data" / "edges" / "btts_performance.json").read_text())
            self.assertEqual(output["summary"]["graded"], 1)
            self.assertFalse(recalculate(root))
            self.assertEqual(json.loads(shot_path.read_text()), original)


if __name__ == "__main__":
    unittest.main()
