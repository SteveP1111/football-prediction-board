"""Offline deterministic tests for fixture matching, edge maths and bad data handling."""
import copy
import importlib.util
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "edge_comparison", Path(__file__).resolve().parents[1] / "scripts" / "edge_comparison.py"
)
edge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(edge)

CAPTURED = "2026-10-24T07:00:00+01:00"
RETRIEVED = "2026-10-24T09:00:00Z"

def game(division="E0", home="Aston Villa", away="Man City", kickoff="12:30"):
    return {
        "id": f"2026-10-24|{division}|{home}|{away}",
        "date": "2026-10-24", "division": division,
        "league": "Premier League" if division == "E0" else "Championship",
        "home": home, "away": away, "homeKey": home.lower(), "awayKey": away.lower(),
        "kickoff": kickoff,
        "scoreline": {
            "model": "INDEPENDENT_SCORELINE_V1_GITHUB", "calibrated": False,
            "markets": {"home_win": .60, "draw": .24, "away_win": .16,
                        "over25": .55, "under25": .45, "over35": .32,
                        "btts": .63, "no_btts": .37}
        }
    }

def snapshot(*fixtures):
    return {"date": "2026-10-24", "status": "frozen-prekickoff",
            "capturedAt": CAPTURED, "model": "INDEPENDENT_SCORELINE_V1_GITHUB",
            "games": list(fixtures or [game()])}

def book(name="TestUK", markets=None):
    return {"key": name.lower(), "title": name,
            "markets": markets if markets is not None else [
                {"key": "h2h", "last_update": "2026-10-24T08:55:00Z",
                 "outcomes": [{"name": "Aston Villa", "price": 2.0},
                              {"name": "Draw", "price": 3.6},
                              {"name": "Manchester City", "price": 5.5}]},
                {"key": "totals", "last_update": "2026-10-24T08:55:00Z",
                 "outcomes": [{"name": "Over", "point": 2.5, "price": 2.1},
                              {"name": "Under", "point": 2.5, "price": 1.8},
                              {"name": "Over", "point": 3.5, "price": 3.2},
                              {"name": "Under", "point": 3.5, "price": 1.45}]},
                {"key": "btts", "last_update": "2026-10-24T08:55:00Z",
                 "outcomes": [{"name": "Yes", "price": 1.8},
                              {"name": "No", "price": 2.0}]},
            ]}

def event(books=None, **overrides):
    item = {"id": "odds-id-123", "sport": "soccer_epl",
            "home_team": "Aston Villa", "away_team": "Manchester City",
            "commence_time": "2026-10-24T11:30:00Z",
            "bookmakers": books if books is not None else [book()]}
    item.update(overrides)
    return item

def odds(*events, captured=RETRIEVED):
    return {"retrieved_at_utc": captured, "fixtures": list(events)}


class EdgeTests(unittest.TestCase):
    def test_canonical_exact_aliases(self):
        for a, b in [("Man City", "Manchester City"),
                     ("Nottm Forest", "Nottingham Forest"),
                     ("Wolves", "Wolverhampton Wanderers"),
                     ("Ipswich", "Ipswich Town"),
                     ("West Ham", "West Ham United"),
                     ("MK Dons", "Milton Keynes Dons")]:
            self.assertEqual(edge.canonical(a), edge.canonical(b))
        self.assertNotEqual(edge.canonical("Manchester City"), edge.canonical("Manchester United"))

    def test_matching_odds_and_probability_first_ranking(self):
        report = edge.assess(snapshot(game()), odds(event()))
        self.assertEqual(report["summary"]["matchedFixtures"], 1)
        self.assertEqual(report["summary"]["marketsPriced"], 9)
        picks = {p["market"]: p for p in report["picks"]}
        self.assertEqual(picks["home_win"]["odds"], 2.0)
        self.assertAlmostEqual(picks["home_win"]["edgePp"], 10.0)
        self.assertAlmostEqual(picks["home_win"]["expectedRoiPct"], 20.0)
        self.assertAlmostEqual(picks["under35"]["modelProbability"], .68)
        self.assertEqual(picks["under35"]["edgePp"], -0.97)
        self.assertTrue(picks["home_win"]["positiveEdge"])
        self.assertFalse(picks["under25"]["positiveEdge"])
        self.assertEqual(report["picks"][0]["market"], "under35" if picks["under35"]["positiveEdge"] else "btts")

    def test_highest_odds_bookmaker_wins_and_keeps_count(self):
        higher = book("BetterUK")
        higher["markets"][0]["outcomes"][0]["price"] = 2.2
        report = edge.assess(snapshot(game()), odds(event([book(), higher])))
        p = next(x for x in report["picks"] if x["market"] == "home_win")
        self.assertEqual(p["bookmaker"], "BetterUK")
        self.assertEqual(p["bookmakersCompared"], 2)
        self.assertAlmostEqual(p["edgePp"], 14.55, places=2)

    def test_timestamps_reject_future_or_in_play(self):
        for captured in ("2026-10-24T11:31:00Z", "2026-10-24T12:31:00Z"):
            report = edge.assess(snapshot(game()), odds(event(), captured=captured))
            self.assertEqual(report["summary"]["matchedFixtures"], 0)

    def test_wrong_teams_league_or_kickoff_excluded(self):
        for alternate in [
            event(away_team="Manchester United"),
            event(sport="soccer_efl_champ"),
            event(commence_time="2026-10-24T15:00:00Z"),
            event(home_team="Manchester City", away_team="Aston Villa"),
        ]:
            report = edge.assess(snapshot(game()), odds(alternate))
            self.assertEqual(report["summary"]["marketsPriced"], 0)

    def test_ambiguous_duplicate_fixture_excluded(self):
        a = event()
        b = event(id="another-event-id")
        report = edge.assess(snapshot(game()), odds(a, b))
        self.assertEqual(report["summary"]["matchedFixtures"], 0)
        self.assertEqual(report["summary"]["marketsPriced"], 0)
        self.assertGreater(report["summary"]["unmatchedReasons"]["duplicate_fixture_mapping"], 0)

    def test_unknown_kickoff_excluded(self):
        report = edge.assess(snapshot(game(kickoff="TBC")), odds(event()))
        self.assertEqual(report["summary"]["marketsPriced"], 0)

    def test_reject_two_way_h2h_instead_of_fake_1x2(self):
        two_way = {"key": "h2h", "outcomes": [
            {"name": "Aston Villa", "price": 2.0},
            {"name": "Manchester City", "price": 1.9}]}
        report = edge.assess(snapshot(game()), odds(event([book(markets=[two_way])])))
        self.assertEqual(report["summary"]["marketsPriced"], 0)
        self.assertIn("incomplete_1x2", report["summary"]["unmatchedReasons"])

    def test_invalid_prices_and_unrecognised_goal_lines_excluded(self):
        markets = [{"key": "totals", "outcomes": [
            {"name": "Over", "point": 1.5, "price": 2.1},
            {"name": "Over", "point": 2.5, "price": True},
            {"name": "Under", "point": 3.5, "price": float("inf")},
            {"name": "Under", "point": 2.5, "price": 1.9}]}]
        report = edge.assess(snapshot(game()), odds(event([book(markets=markets)])))
        self.assertEqual([p["market"] for p in report["picks"]], ["under25"])

    def test_stale_market_rejected_and_no_past_odds_backfill(self):
        stale = book()
        for market in stale["markets"]:
            market["last_update"] = "2026-10-22T01:00:00Z"
        report = edge.assess(snapshot(game()), odds(event([stale])))
        self.assertEqual(report["summary"]["marketsPriced"], 0)
        self.assertIn("stale_or_postkickoff_market", report["summary"]["unmatchedReasons"])

    def test_frozen_forecasts_only(self):
        s = snapshot(game())
        s["status"] = "no-prekickoff-fixtures"
        with self.assertRaisesRegex(ValueError, "frozen-prekickoff"):
            edge.assess(s, odds(event()))

    def test_invalid_capture_order_rejected(self):
        s = snapshot(game())
        s["capturedAt"] = "2026-10-24T11:00:00Z"
        with self.assertRaisesRegex(ValueError, "out-of-order"):
            edge.assess(s, odds(event()))

    def test_no_api_key_or_raw_bookmakers_in_output(self):
        report = edge.assess(snapshot(game()), odds(event()))
        serialised = json.dumps(report)
        self.assertNotIn("apiKey", serialised)
        self.assertNotIn('"bookmakers":', serialised)
        self.assertIn("bookmaker", serialised)
        self.assertEqual(report["calibrated"], False)

    def test_championship_match_different_alias(self):
        fixture = game(division="E1", home="Wolves", away="Watford", kickoff="15:00")
        provider = event(sport="soccer_efl_champ",
                         home_team="Wolverhampton Wanderers", away_team="Watford",
                         commence_time="2026-10-24T14:00:00Z",
                         bookmakers=[book("Provider", markets=[{
                             "key": "btts", "outcomes": [
                                 {"name": "Yes", "price": 2.0},
                                 {"name": "No", "price": 1.8}
                             ]}])])
        report = edge.assess(snapshot(fixture), odds(provider))
        self.assertEqual(report["summary"]["matchedFixtures"], 1)
        self.assertEqual(report["summary"]["marketsPriced"], 2)


if __name__ == "__main__":
    unittest.main()
