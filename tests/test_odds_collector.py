"""Offline checks for the isolated odds collector; no API credits used."""
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("fetch_odds", Path(__file__).resolve().parents[1] / "scripts" / "fetch_odds.py")
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)

class FakeResponse:
    headers = {"x-requests-remaining": "490", "x-requests-used": "10"}
    def __enter__(self): return self
    def __exit__(self, *args): return False

class OddsTests(unittest.TestCase):
    def test_requires_secret(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(SystemExit) as ctx: mod.collect()
            self.assertIn("not configured", str(ctx.exception))

    def test_four_leagues_and_snapshot(self):
        class Response(FakeResponse):
            def __init__(self, sport): self.sport = sport
            def read(self): return json.dumps([{"id": self.sport+"1", "commence_time": "2026-11-01T15:00:00Z", "home_team": "A", "away_team": "B", "bookmakers": []}]).encode()
        def fake_urlopen(req, timeout):
            sport = req.full_url.split("/sports/")[1].split("/")[0]
            return Response(sport)
        with tempfile.TemporaryDirectory() as d, patch.object(mod, "ROOT", Path(d)), patch.dict(os.environ, {"ODDS_API_KEY": "fake-test-secret"}), patch.object(mod.urllib.request, "urlopen", side_effect=fake_urlopen), patch.object(mod.json, "load", side_effect=lambda response: json.loads(response.read())):
            mod.collect()
            outputs = list((Path(d)/"data"/"odds").glob("*.json"))
            self.assertEqual(len(outputs), 1)
            result = json.loads(outputs[0].read_text())
            self.assertEqual(len(result["fixtures"]), 4)
            self.assertNotIn("fake-test-secret", outputs[0].read_text())
            self.assertEqual(set(x["sport"] for x in result["fixtures"]), set(mod.SPORTS))

if __name__ == "__main__": unittest.main()
