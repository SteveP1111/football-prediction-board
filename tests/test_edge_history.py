"""Tests for immutable bookmaker settlement and £10 flat hypothetical P/L."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("edge_history", ROOT / "scripts" / "edge_history.py")
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def pick(fixture="2026-10-24|E0|villa|city", market="home_win",
         prob=.68, price=1.85, positive=True):
    return {
        "date": "2026-10-24", "fixtureId": fixture, "market": market,
        "marketLabel": market, "home": "Villa", "away": "City",
        "odds": price, "modelProbability": prob, "edgePp": 4.0,
        "positiveEdge": positive, "bookmaker": "Example",
    }


class SettlementTests(unittest.TestCase):
    def test_profit_for_win_loss_and_under35(self):
        final = {"score": "2-1"}
        a = mod.grade_pick(pick(), final)
        b = mod.grade_pick(pick(market="away_win", prob=.2), final)
        c = mod.grade_pick(pick(market="under35", prob=.7), final)
        self.assertEqual(a["profitGbp"], 8.5)
        self.assertEqual(b["profitGbp"], -10)
        self.assertEqual(c["profitGbp"], 8.5)

    def test_all_markets_graded_from_score(self):
        final = {"score": "2-1"}
        outcomes = {
            "home_win": "Win", "draw": "Loss", "away_win": "Loss",
            "btts": "Win", "no_btts": "Loss", "over25": "Win",
            "under25": "Loss", "over35": "Loss", "under35": "Win",
        }
        for name, expected in outcomes.items():
            with self.subTest(name=name):
                self.assertEqual(mod.grade_pick(pick(market=name), final)["outcome"], expected)

    def test_unknown_or_invalid_scores_never_graded(self):
        self.assertIsNone(mod.grade_pick(pick(), {}))
        self.assertIsNone(mod.grade_pick(pick(), {"score": "TBC"}))
        self.assertIsNone(mod.grade_pick(pick(), {"score": "2--1"}))

    def test_pending_and_confidence_bands_and_roi(self):
        snap = {
            "schemaVersion": 1, "status": "compared",
            "forecastDate": "2026-10-24", "picks": [
                pick(), pick(market="away_win", prob=.25, positive=False),
                pick(fixture="2026-10-24|E0|other|match", market="btts", prob=.61),
            ],
        }
        data = mod.build([snap], {"2026-10-24|E0|villa|city": {"score": "2-1"}})
        self.assertEqual(data["recordedSelections"], 3)
        self.assertEqual(data["pendingSelections"], 1)
        self.assertEqual(data["gradedSelections"], 2)
        positive = data["summary"]["positiveEdges"]
        self.assertEqual(positive["selections"], 1)
        self.assertEqual(positive["stakeGbp"], 10)
        self.assertEqual(positive["profitGbp"], 8.5)
        self.assertEqual(positive["roiPct"], 85)
        self.assertEqual(data["summary"]["positiveEdges60Plus"]["selections"], 1)
        self.assertEqual(data["summary"]["byProbabilityBand"]["60–69.9%"]["selections"], 1)

    def test_no_market_coverage_day_does_not_break_future_history(self):
        zero = {"schemaVersion": 1, "status": "no-comparable-markets",
                "forecastDate": "2026-10-25", "picks": []}
        report = mod.build([zero], {})
        self.assertEqual(report["recordedSelections"], 0)
        self.assertEqual(report["summary"]["positiveEdges"]["selections"], 0)
        self.assertEqual(report["snapshotDays"], ["2026-10-25"])

    def test_duplicate_stored_picks_fail_not_double_count(self):
        sample = pick()
        snap = {"schemaVersion": 1, "status": "compared",
                "forecastDate": "2026-10-24", "picks": [sample, sample]}
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            mod.build([snap], {"2026-10-24|E0|villa|city": {"score": "2-1"}})

    def test_recalculate_is_idempotent_and_preserves_prices(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            path = root / "data" / "edges" / "snapshots" / "2026-10-24.json"
            path.parent.mkdir(parents=True)
            sample = {"schemaVersion": 1, "status": "compared",
                      "forecastDate": "2026-10-24", "picks": [pick()]}
            path.write_text(json.dumps(sample))
            finals = root / "data" / "settlements.json"
            finals.write_text(json.dumps({"2026-10-24|E0|villa|city": {"score": "2-1"}}))
            self.assertTrue(mod.recalculate(root))
            first = (root / "data" / "edges" / "settlements.json").read_text()
            self.assertFalse(mod.recalculate(root))
            second = (root / "data" / "edges" / "settlements.json").read_text()
            self.assertEqual(first, second)
            self.assertEqual(json.loads(path.read_text()), sample)


if __name__ == "__main__":
    unittest.main()
