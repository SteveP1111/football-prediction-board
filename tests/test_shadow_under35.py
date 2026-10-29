import json
import tempfile
import unittest
from datetime import datetime, date
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.shadow_under35 import (
    CONFIG, START_DATE, compare, immutable_shadow, metrics,
    paired_day_interval, run, temperature_scale, verified_under35,
)

TZ=ZoneInfo("Europe/London")


def forecast(day="2026-10-30", captured="2026-10-30T08:00:00+00:00", kickoff="15:00"):
    return {
        "date":day,"capturedAt":captured,"model":CONFIG["liveModel"],
        "games":[{
            "id":f"{day}|E0|fixture-a|fixture-b",
            "date":day,"home":"Fixture A","away":"Fixture B",
            "division":"E0","kickoff":kickoff,
            "scoreline":{"markets":{"under35":.6,"over35":.4}},
        }]
    }


class ForwardUnder35Tests(unittest.TestCase):
    def test_temperature_is_bounded_and_returns_identical_half(self):
        self.assertAlmostEqual(temperature_scale(.5,1.2),.5)
        self.assertGreater(temperature_scale(.1,1.2),.1)
        self.assertLess(temperature_scale(.9,1.2),.9)
        for bad in (-.1,1.1,float("nan"),True):
            with self.assertRaises(ValueError):
                temperature_scale(bad,1.2)

    def test_freezes_original_and_shadow_without_mutating_original(self):
        original=forecast()
        saved=json.dumps(original,sort_keys=True)
        at=datetime(2026,10,30,9,0,tzinfo=TZ)
        shadow=immutable_shadow(original,at,"a"*64)
        self.assertEqual(saved,json.dumps(original,sort_keys=True))
        self.assertEqual(shadow["status"],"frozen-prekickoff")
        self.assertEqual(len(shadow["games"]),1)
        predicted=shadow["games"][0]
        self.assertAlmostEqual(predicted["originalUnder35"],.6)
        self.assertAlmostEqual(predicted["shadowUnder35"],1-temperature_scale(.4,1.2),places=7)
        self.assertNotEqual(predicted["originalUnder35"],predicted["shadowUnder35"])

    def test_blocks_post_kickoff_and_historical_backfill(self):
        at=datetime(2026,10,30,16,0,tzinfo=TZ)
        self.assertIsNone(immutable_shadow(forecast(),at,"a"*64))
        self.assertIsNone(immutable_shadow(forecast(day="2026-10-29"),datetime(2026,10,29,9,tzinfo=TZ),"a"*64))
        self.assertIsNone(immutable_shadow(forecast(kickoff="TBC"),datetime(2026,10,30,9,tzinfo=TZ),"a"*64))
        self.assertIsNone(immutable_shadow(forecast(captured="2026-10-30T16:00:00+00:00"),datetime(2026,10,30,17,tzinfo=TZ),"a"*64))

    def test_invalid_source_probabilities_rejected(self):
        original=forecast()
        original["games"][0]["scoreline"]["markets"]["under35"]=.8
        with self.assertRaises(ValueError):
            immutable_shadow(original,datetime(2026,10,30,9,tzinfo=TZ),"a"*64)

    def test_grade_exactly_three_goals_but_not_four(self):
        for score,expected in (("0-0",1),("3-0",1),("2-1",1),("3-1",0),("2-2",0)):
            record={"date":"2026-10-30","score":score}
            self.assertEqual(verified_under35(record,"2026-10-30"),expected)
        self.assertIsNone(verified_under35({"date":"2026-10-30","score":"TBC"},"2026-10-30"))
        self.assertIsNone(verified_under35({"date":"2026-10-31","score":"2-1"},"2026-10-30"))
        with self.assertRaises(ValueError):
            verified_under35({"date":"2026-10-30","score":"2-1","outcomes":{"under35":False}},"2026-10-30")

    def test_no_file_is_ever_rewritten_and_new_scores_settle(self):
        with tempfile.TemporaryDirectory() as base:
            root=Path(base)
            source=root/"data"/"snapshots"/"2026-10-30.json"
            source.parent.mkdir(parents=True)
            source.write_text(json.dumps(forecast()))
            results=root/"data"/"settlements.json"
            results.write_text("{}")
            first=run(root,datetime(2026,10,30,9,tzinfo=TZ))
            shadow=root/"data"/"shadow_under35"/"snapshots"/"2026-10-30.json"
            saved=shadow.read_bytes()
            self.assertEqual(first["frozenFixtures"],1)
            self.assertEqual(first["pendingFixtures"],1)
            source.write_text(json.dumps(forecast(kickoff="11:00")))
            second=run(root,datetime(2026,10,30,10,tzinfo=TZ))
            self.assertEqual(shadow.read_bytes(),saved)
            self.assertEqual(second["frozenFixtures"],1)
            results.write_text(json.dumps({
                "2026-10-30|E0|fixture-a|fixture-b":{
                    "date":"2026-10-30","score":"2-1","outcomes":{"under35":True}
                }
            }))
            third=run(root,datetime(2026,10,31,9,tzinfo=TZ))
            self.assertEqual(third["settledFixtures"],1)
            self.assertEqual(third["models"]["V1 original"]["wins"],1)
            self.assertEqual(third["byThreshold"]["55%"]["V1 original"]["n"],1)
            self.assertEqual(third["pairedBrierDelta"]["status"],"insufficient-data")

    def test_duplicate_fixture_rejected(self):
        frozen=immutable_shadow(forecast(),datetime(2026,10,30,9,tzinfo=TZ),"a"*64)
        with self.assertRaises(ValueError):
            compare([frozen,frozen],{})


if __name__=="__main__":
    unittest.main()
