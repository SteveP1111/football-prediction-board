"""Offline authentication, quota, privacy and odds-collector tests. No real API calls."""
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "fetch_odds", Path(__file__).resolve().parents[1] / "scripts" / "fetch_odds.py"
)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)

SPORTS_RESPONSE = [{"key": key, "active": True} for key in mod.SPORTS]
EVENT = {
    "id": "fixture123",
    "commence_time": "2026-11-01T15:00:00Z",
    "home_team": "Home",
    "away_team": "Away",
    "bookmakers": [{"key": "example", "markets": [
        {"key": "h2h", "outcomes": [{"name": "Home", "price": 2.1}]}
    ]}],
}


class OddsTests(unittest.TestCase):
    def test_correct_championship_key(self):
        self.assertIn("soccer_efl_champ", mod.SPORTS)
        self.assertNotIn("soccer_england_championship", mod.SPORTS)

    def test_requires_secret(self):
        with patch.dict(os.environ, {}, clear=True), patch("sys.argv", ["fetch_odds.py"]):
            with self.assertRaises(SystemExit) as error:
                mod.main()
        self.assertIn("not available", str(error.exception))

    def test_preflight_is_only_free_sports_endpoint(self):
        with patch.object(mod, "fetch", return_value=(SPORTS_RESPONSE, {"remaining": "100"})) as fetch:
            active, remaining = mod.preflight("fake-key")
        self.assertEqual(active, set(mod.SPORTS))
        self.assertEqual(remaining, 100)
        fetch.assert_called_once_with("/sports/", "fake-key")

    def test_budget_prevents_paid_calls(self):
        calls = []
        def fake_fetch(path, key, params=None):
            calls.append(path)
            return SPORTS_RESPONSE, {"remaining": "1"}
        with patch.object(mod, "fetch", side_effect=fake_fetch):
            with self.assertRaisesRegex(RuntimeError, "Insufficient remaining"):
                mod.collect("fake-key", [mod.SPORTS[0]], max_credits=2)
        self.assertEqual(calls, ["/sports/"])

    def test_explicit_budget_limit_prevents_paid_calls(self):
        calls = []
        def fake_fetch(path, key, params=None):
            calls.append(path)
            return SPORTS_RESPONSE, {"remaining": "100"}
        with patch.object(mod, "fetch", side_effect=fake_fetch):
            with self.assertRaisesRegex(RuntimeError, "exceed the explicit"):
                mod.collect("fake-key", [mod.SPORTS[0], mod.SPORTS[1]], max_credits=2)
        self.assertEqual(calls, ["/sports/"])

    def test_collect_does_not_save_by_default(self):
        calls = []
        def fake_fetch(path, key, params=None):
            calls.append(path)
            if path == "/sports/":
                return SPORTS_RESPONSE, {"remaining": "100"}
            return [EVENT], {"remaining": "98"}
        with tempfile.TemporaryDirectory() as d, patch.object(mod, "ROOT", Path(d)):
            with patch.object(mod, "fetch", side_effect=fake_fetch):
                matches = mod.collect("fake-key", [mod.SPORTS[0]], 2)
            self.assertEqual(len(matches), 1)
            self.assertFalse((Path(d) / "private_odds").exists())
        self.assertEqual(len(calls), 2)

    def test_save_explicitly_never_serialises_key(self):
        def fake_fetch(path, key, params=None):
            if path == "/sports/":
                return SPORTS_RESPONSE, {"remaining": "100"}
            return [EVENT], {"remaining": "98"}
        with tempfile.TemporaryDirectory() as d, patch.object(mod, "ROOT", Path(d)):
            with patch.object(mod, "fetch", side_effect=fake_fetch):
                mod.collect("fake-test-secret", [mod.SPORTS[0]], 2, save=True)
            files = list((Path(d) / "private_odds").glob("*.json"))
            self.assertEqual(len(files), 1)
            content = files[0].read_text()
            self.assertNotIn("fake-test-secret", content)
            self.assertEqual(len(json.loads(content)["fixtures"]), 1)

    def test_missing_quota_headers_fail_closed(self):
        with patch.object(mod, "fetch", return_value=(SPORTS_RESPONSE, {"remaining": None})):
            with self.assertRaisesRegex(RuntimeError, "quota headers"):
                mod.preflight("fake-key")

    def test_http_error_is_sanitised(self):
        secret_url = "https://api.the-odds-api.com/v4/sports/?apiKey=VERY_SECRET"
        error = urllib.error.HTTPError(secret_url, 401, "Unauthorized", {}, None)
        with patch.object(mod.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(RuntimeError) as caught:
                mod.fetch("/sports/", "VERY_SECRET")
        self.assertEqual(str(caught.exception), "Odds API returned HTTP status 401")
        self.assertNotIn("VERY_SECRET", str(caught.exception))

    def test_invalid_event_does_not_get_saved(self):
        def fake_fetch(path, key, params=None):
            return (SPORTS_RESPONSE if path == "/sports/" else [{"bad": "schema"}],
                    {"remaining": "100"})
        with tempfile.TemporaryDirectory() as d, patch.object(mod, "ROOT", Path(d)):
            with patch.object(mod, "fetch", side_effect=fake_fetch):
                with self.assertRaisesRegex(RuntimeError, "Invalid event schema"):
                    mod.collect("fake-key", [mod.SPORTS[0]], 2, save=True)
            self.assertFalse((Path(d) / "private_odds").exists())


    def test_optional_btts_and_alternate_totals_are_merged_only_for_matching_future_event(self):
        local = datetime(2099, 10, 24, 12, 30, tzinfo=ZoneInfo("Europe/London"))
        kickoff = local.astimezone(timezone.utc).isoformat()
        future = {
            "id": "next-match123", "sport": "soccer_epl",
            "home_team": "Aston Villa", "away_team": "Manchester City",
            "commence_time": kickoff,
            "bookmakers": [{"key": "example", "title": "Example", "markets": [
                {"key": "h2h", "outcomes": []}]}],
        }
        snap = {"status": "frozen-prekickoff", "games": [{
            "id": "2099-10-24|E0|aston villa|manchester city",
            "date": "2099-10-24", "kickoff": "12:30", "division": "E0",
            "homeKey": "aston villa", "awayKey": "manchester city",
        }]}
        paths = []
        def fake_fetch(path, key, params=None):
            paths.append(path)
            if path == "/sports/":
                return SPORTS_RESPONSE, {"remaining": "100"}
            if path.endswith("/odds/"):
                return [future], {"remaining": "98"}
            self.assertIn("/events/next-match123/odds", path)
            return {"id": "next-match123", "home_team": "Aston Villa",
                    "away_team": "Manchester City", "bookmakers": [{
                        "key": "example", "title": "Example", "markets": [
                            {"key": "btts", "outcomes": [{"name": "Yes", "price": 1.8}]},
                            {"key": "alternate_totals", "outcomes": [{"name": "Over", "point": 3.5, "price": 2.9}]}]}]}, {"remaining": "96"}
        with patch.object(mod, "fetch", side_effect=fake_fetch):
            data = mod.collect("fake-key", ["soccer_epl"], 4, extra_markets=("btts", "alternate_totals"),
                               extra_events=1, frozen_snapshot=snap)
        market_keys = [m["key"] for m in data[0]["bookmakers"][0]["markets"]]
        self.assertEqual(market_keys, ["h2h", "btts", "alternate_totals"])
        self.assertEqual(len(paths), 3)

    def test_extra_markets_budget_fails_before_paid_requests(self):
        calls = []
        def fake_fetch(path, key, params=None):
            calls.append(path)
            return SPORTS_RESPONSE, {"remaining": "100"}
        with patch.object(mod, "fetch", side_effect=fake_fetch):
            with self.assertRaisesRegex(RuntimeError, "exceed the explicit"):
                mod.collect("fake-key", ["soccer_epl"], 3,
                            extra_markets=("btts", "alternate_totals"), extra_events=1,
                            frozen_snapshot={"status": "frozen-prekickoff", "games": []})
        self.assertEqual(calls, ["/sports/"])

    def test_extra_event_matches_required_for_chargeable_event_call(self):
        payload = dict(EVENT, sport="soccer_epl", id="valid-event123",
                       home_team="Unmatched Club", away_team="Other Club")
        requests = []
        def fake_fetch(path, key, params=None):
            requests.append(path)
            return (SPORTS_RESPONSE if path == "/sports/" else [payload]), {"remaining": "100"}
        with patch.object(mod, "fetch", side_effect=fake_fetch):
            mod.collect("fake-key", ["soccer_epl"], 4, extra_markets=("btts",),
                        extra_events=1, frozen_snapshot={"status": "frozen-prekickoff", "games": []})
        self.assertEqual(len(requests), 2)


if __name__ == "__main__":
    unittest.main()
