"""Production publishing gates, one-attempt receipts, expiry and quota tests."""
import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("publish_edges", ROOT / "scripts" / "publish_edges.py")
pub = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pub)

NOW = datetime(2026, 10, 24, 8, 0, tzinfo=timezone.utc)
PRED = {
    "date": "2026-10-24", "capturedAt": "2026-10-24T07:00:00Z",
    "status": "frozen-prekickoff", "model": "INDEPENDENT_SCORELINE_V1_GITHUB",
    "games": [
        {"id": "2026-10-24|E0|arsenal|everton",
         "date": "2026-10-24", "division": "E0", "home": "Arsenal",
         "homeKey": "arsenal", "away": "Everton", "awayKey": "everton",
         "kickoff": "15:00", "scoreline": {"markets": {"home_win": .55}}},
    ],
}
REPORT = {
    "schemaVersion": 1, "status": "compared", "forecastDate": "2026-10-24",
    "summary": {"matchedFixtures": 1, "marketsPriced": 1, "positiveEdges": 1},
    "picks": [{"market": "home_win", "odds": 2.0, "positiveEdge": True}],
}


def prepare(root, snapshot=PRED):
    file = root / "data" / "latest.json"
    file.parent.mkdir(parents=True)
    file.write_text(json.dumps(snapshot))


class PublishTests(unittest.TestCase):
    def test_frozen_current_date_only(self):
        self.assertEqual(len(pub.eligible_games(PRED, NOW)), 1)
        for invalid in [
            dict(PRED, status="no-frozen-matches"),
            dict(PRED, date="2026-10-23"),
            dict(PRED, capturedAt="2026-10-24T10:00:00Z"),
        ]:
            self.assertEqual(pub.eligible_games(invalid, NOW), [])
        past = json.loads(json.dumps(PRED))
        past["games"][0]["kickoff"] = "09:10"  # 08:10 UTC, within 15 minutes.
        self.assertEqual(pub.eligible_games(past, NOW), [])

    def test_four_leagues_twelve_credit_ceiling(self):
        fixtures = [dict(PRED["games"][0], division=div) for div in ("E0","E1","E2","E3")]
        sports, extra, cap = pub.choose_spend(fixtures)
        self.assertEqual(len(sports), 4)
        self.assertEqual(extra, 2)
        self.assertEqual(cap, 12)

    def test_dry_run_never_uses_secret(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            prepare(root)
            with patch.object(pub, "recalculate", return_value=False), \
                 patch.object(pub, "preflight") as preflight:
                self.assertEqual(pub.publish(root, NOW, dry_run=True), "dry-run")
                preflight.assert_not_called()
            self.assertFalse((root / "data" / "edges" / "usage").exists())

    def test_reserve_blocks_requests_before_receipt(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            prepare(root)
            with patch.object(pub, "recalculate", return_value=False), \
                 patch.dict(pub.os.environ, {"ODDS_API_KEY": "TEST_ONLY"}), \
                 patch.object(pub, "preflight", return_value=({"soccer_epl"}, 103)), \
                 patch.object(pub, "collect") as collect:
                self.assertEqual(pub.publish(root, NOW), "quota-reserved")
                collect.assert_not_called()
            self.assertFalse((root / "data" / "edges" / "usage").exists())

    def test_successful_snapshot_only_once_per_day(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            prepare(root)
            def fake_collect(*args, **kwargs):
                kwargs["usage"].update(endRemaining=492, spentCredits=4)
                return [{"id":"example"}]
            with patch.object(pub, "recalculate", return_value=False), \
                 patch.dict(pub.os.environ, {"ODDS_API_KEY": "TEST_ONLY"}), \
                 patch.object(pub, "preflight", return_value=({"soccer_epl"}, 496)), \
                 patch.object(pub, "collect", side_effect=fake_collect) as collect, \
                 patch.object(pub, "assess", return_value=dict(REPORT)):
                self.assertEqual(pub.publish(root, NOW), "published")
                self.assertEqual(pub.publish(root, NOW), "already-attempted")
                collect.assert_called_once()
            usage=json.loads((root/"data/edges/usage/2026-10-24.json").read_text())
            self.assertEqual(usage["status"], "complete")
            self.assertEqual(usage["spentCredits"], 4)
            latest=json.loads((root/"data/edges/latest.json").read_text())
            self.assertEqual(latest["developmentPreview"], False)
            self.assertTrue((root/"data/edges/snapshots/2026-10-24.json").exists())

    def test_failed_call_receipt_prevents_repeat_charges(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            prepare(root)
            def failure(*args, **kwargs):
                kwargs["usage"].update(endRemaining=494,spentCredits=2)
                raise RuntimeError("provider rejected optional market")
            with patch.object(pub, "recalculate", return_value=False), \
                 patch.dict(pub.os.environ, {"ODDS_API_KEY": "TEST_ONLY"}), \
                 patch.object(pub, "preflight", return_value=({"soccer_epl"}, 496)), \
                 patch.object(pub, "collect", side_effect=failure) as collect:
                with self.assertRaises(RuntimeError):
                    pub.publish(root, NOW)
                self.assertEqual(pub.publish(root, NOW), "already-attempted")
                collect.assert_called_once()
            usage=json.loads((root/"data/edges/usage/2026-10-24.json").read_text())
            self.assertEqual(usage["status"], "failed")
            self.assertEqual(usage["spentCredits"], 2)
            self.assertFalse((root/"data/edges/latest.json").exists())


if __name__ == "__main__":
    unittest.main()
