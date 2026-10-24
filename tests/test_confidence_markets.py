"""Verified exact fixture aliases and quota-aware high-confidence extra-market selection."""
import json
import sys
import unittest
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from edge_comparison import (
    canonical, event_key, fixture_key, fixture_kickoff,
    parse_utc, select_confident_event_markets,
)
from fetch_odds import collect, SPORTS

FUTURE_DAY = "2099-10-24"
FUTURE_KICKOFF = "2099-10-24T11:30:00Z"
REFERENCE = "2026-10-24T00:30:00Z"


def fixture(home="Aston Villa", away="Man City", probability_btts=.64,
            over35=.2, date=FUTURE_DAY, kickoff="12:30", division="E0"):
    return {
        "id": f"{date}|{division}|{canonical(home)}|{canonical(away)}",
        "date": date, "division": division, "home": home, "away": away,
        "homeKey": home.lower(), "awayKey": away.lower(), "kickoff": kickoff,
        "scoreline": {"model": "INDEPENDENT_SCORELINE_V1_GITHUB",
                      "markets": {"btts": probability_btts, "no_btts": 1-probability_btts,
                                  "over35": over35}}
    }


def model(*fixtures):
    return {"date": FUTURE_DAY, "status": "frozen-prekickoff",
            "capturedAt": REFERENCE, "games": list(fixtures)}


def provider(home="Aston Villa", away="Manchester City", event_id="odds_event_001",
             kickoff=FUTURE_KICKOFF, markets=None):
    return {
        "id": event_id, "sport": "soccer_epl", "home_team": home,
        "away_team": away, "commence_time": kickoff,
        "bookmakers": [{"key": "sample", "title": "Sample",
                        "markets": list(markets or [])}]
    }


class ClubMatchingRegressionTests(unittest.TestCase):
    def test_all_38_current_provider_fixtures_match_existing_frozen_snapshot(self):
        snap = json.loads((ROOT / "data/snapshots/2026-10-24.json").read_text(encoding="utf-8"))
        source = json.loads((ROOT / "tests/fixtures/provider_events_2026-10-24.json").read_text(encoding="utf-8"))
        lookup = {}
        for f in snap["games"]:
            k = fixture_key(f)
            lookup.setdefault(k, []).append(f)
        totals = Counter()
        matched = set()
        for sport, matches in source["competitions"].items():
            for match in matches:
                ev = {
                    "sport": sport, "home_team": match["home"],
                    "away_team": match["away"], "commence_time": match["kickoff"],
                }
                key = event_key(ev)
                candidates = lookup.get(key, [])
                self.assertEqual(len(candidates), 1, f"Unmatched or ambiguous provider event: {sport} {match}")
                f = candidates[0]
                difference = abs((fixture_kickoff(f) - parse_utc(ev["commence_time"])).total_seconds())
                self.assertLessEqual(difference, 90 * 60, f"Kick-off mismatch: {match}")
                self.assertNotIn(f["id"], matched)
                matched.add(f["id"])
                totals[f["division"]] += 1
        self.assertEqual(dict(totals), {"E0": 4, "E1": 11, "E2": 12, "E3": 11})
        self.assertEqual(len(matched), 38)

    def test_verified_aliases_and_no_false_match(self):
        pairs = [
            ("Lincoln", "Lincoln City"),
            ("Preston", "Preston North End"),
            ("Wigan", "Wigan Athletic"),
            ("Wycombe", "Wycombe Wanderers"),
            ("Mansfield", "Mansfield Town"),
            ("Bromley", "Bromley FC"),
            ("Peterboro", "Peterborough United"),
            ("Doncaster", "Doncaster Rovers"),
            ("Stockport", "Stockport County FC"),
            ("Bradford", "Bradford City"),
            ("Bristol Rvs", "Bristol Rovers"),
            ("Swindon", "Swindon Town"),
            ("Oldham", "Oldham Athletic"),
            ("Chesterfield", "Chesterfield FC"),
            ("Exeter", "Exeter City"),
            ("York", "York City"),
        ]
        for first, second in pairs:
            with self.subTest(club=first):
                self.assertEqual(canonical(first), canonical(second))
        self.assertNotEqual(canonical("Lincoln"), canonical("Leicester"))
        self.assertNotEqual(canonical("Bromley"), canonical("Barnet"))
        self.assertNotEqual(canonical("Bradford"), canonical("Blackpool"))


class ConfidenceSelectionTests(unittest.TestCase):
    def test_requests_only_qualifying_unpriced_market_types(self):
        f = fixture(probability_btts=.64, over35=.20)
        event = provider(markets=[{"key":"h2h","outcomes":[]}])
        selected = select_confident_event_markets(
            model(f), [event], datetime(2026, 10, 24, 1, tzinfo=timezone.utc))
        self.assertEqual({x["market"] for x in selected}, {"btts", "alternate_totals"})
        self.assertEqual({x["selection"] for x in selected}, {"btts", "under35"})

    def test_standard_3_5_quote_prevents_duplicate_alternate_request(self):
        f = fixture(probability_btts=.53, over35=.18)
        ev = provider(markets=[
            {"key":"totals","outcomes":[
                {"name":"Under","point":3.5,"price":1.48},
                {"name":"Over","point":3.5,"price":2.9}
            ]}])
        self.assertEqual(select_confident_event_markets(model(f),[ev],
                         datetime(2026,10,24,1,tzinfo=timezone.utc)), [])

    def test_low_confidence_skips_btts_and_alternates(self):
        f = fixture(probability_btts=.52, over35=.49)
        selected = select_confident_event_markets(
            model(f), [provider()], datetime(2026,10,24,1,tzinfo=timezone.utc))
        self.assertEqual(selected, [])

    def test_exact_fifty_five_percent_confidence_cutoff(self):
        now=datetime(2026,10,24,1,tzinfo=timezone.utc)
        qualifies=select_confident_event_markets(
            model(fixture(probability_btts=.55,over35=.45)),[provider()],now)
        self.assertEqual({q["market"] for q in qualifies},{"btts","alternate_totals"})
        below=select_confident_event_markets(
            model(fixture(probability_btts=.54,over35=.46)),[provider()],now)
        self.assertEqual(below,[])

    def test_over_three_point_five_at_fifty_five_percent_qualifies(self):
        now=datetime(2026,10,24,1,tzinfo=timezone.utc)
        selected=select_confident_event_markets(
            model(fixture(probability_btts=.50,over35=.55)),[provider()],now)
        self.assertEqual([q["market"] for q in selected],["alternate_totals"])
        self.assertEqual(selected[0]["selection"],"over35")

    def test_no_extra_credit_when_standard_totals_already_cover_under_three_point_five(self):
        now=datetime(2026,10,24,1,tzinfo=timezone.utc)
        ev=provider(markets=[{"key":"totals","outcomes":[
            {"name":"Under","point":2.5,"price":2.0},
            {"name":"Over","point":2.5,"price":1.9},
            {"name":"Under","point":3.5,"price":1.4}]}])
        selected=select_confident_event_markets(
            model(fixture(probability_btts=.51,over35=.20)),[ev],now)
        self.assertEqual(selected,[])

    def test_frozen_source_league_team_and_kickoff_must_agree(self):
        f = fixture(probability_btts=.68,over35=.18)
        now=datetime(2026,10,24,1,tzinfo=timezone.utc)
        for ev in [
            provider(away="Manchester United"),
            provider(home="Manchester City",away="Aston Villa"),
            dict(provider(),sport="soccer_efl_champ"),
            provider(kickoff="2099-10-24T15:30:00Z"),
        ]:
            self.assertEqual(select_confident_event_markets(model(f),[ev],now),[])

    def test_ambiguous_provider_events_rejected(self):
        f = fixture()
        events=[provider(event_id="valid_a"),provider(event_id="valid_b")]
        self.assertEqual(select_confident_event_markets(
            model(f),events,datetime(2026,10,24,1,tzinfo=timezone.utc)),[])

    def test_current_quote_of_btts_already_present_is_not_requested_again(self):
        f=fixture(probability_btts=.68,over35=.49)
        ev=provider(markets=[{"key":"btts","outcomes":[
            {"name":"Yes","price":1.8},{"name":"No","price":2.0}]}])
        selected=select_confident_event_markets(model(f),[ev],datetime(2026,10,24,1,tzinfo=timezone.utc))
        self.assertEqual(selected,[])

    def test_four_slots_split_between_btts_and_totals(self):
        teams = [
            ("Aston Villa","Man City","Manchester City"),
            ("Arsenal","Everton","Everton"),
            ("Chelsea","Tottenham","Tottenham Hotspur"),
            ("Fulham","Newcastle","Newcastle United"),
            ("Brentford","Liverpool","Liverpool"),
        ]
        fixtures=[fixture(a,b,probability_btts=.64+i*.01,over35=.10+i*.01)
                  for i,(a,b,_) in enumerate(teams)]
        events=[provider(a,d,event_id=f"event000{i}") for i,(a,b,d) in enumerate(teams)]
        selected=select_confident_event_markets(
            model(*fixtures),events,datetime(2026,10,24,1,tzinfo=timezone.utc),max_requests=4)
        self.assertEqual(len(selected),4)
        self.assertEqual(Counter(x["market"] for x in selected),
                         Counter({"btts":2,"alternate_totals":2}))
        self.assertEqual(selected,sorted(selected,key=lambda x:
                         (-x["modelProbability"],x["fixtureId"],x["market"])))

    def test_extra_credit_budget_only_consumed_if_qualified(self):
        calls=[]
        mock_event=provider()
        def fake_fetch(path,key,params=None):
            calls.append((path,params))
            if path=="/sports/":
                return [{"key":s,"active":True} for s in SPORTS],{"remaining":"480"}
            if path.endswith("/odds/"):
                return [mock_event],{"remaining":"478"}
            raise AssertionError("No event-specific request should occur without high confidence")
        no_qualifiers=model(fixture(probability_btts=.51,over35=.49))
        usage={}
        with patch("fetch_odds.fetch",side_effect=fake_fetch):
            result=collect("dummy",["soccer_epl"],6,
                           frozen_snapshot=no_qualifiers,
                           confidence_extra_calls=4,usage=usage,reserve_credits=100)
        self.assertEqual(len(result),1)
        self.assertEqual(len(calls),2)
        self.assertEqual(usage["confidenceQualifyingRequests"],0)
        self.assertEqual(usage["spentCredits"],2)

    def test_one_credit_btts_only_request_is_recorded(self):
        calls=[]
        mock_event=provider()
        def fake_fetch(path,key,params=None):
            calls.append((path,params))
            if path=="/sports/":
                return [{"key":s,"active":True} for s in SPORTS],{"remaining":"480"}
            if path.endswith("/odds/"):
                return [mock_event],{"remaining":"478"}
            self.assertTrue(path.endswith("/events/odds_event_001/odds"))
            self.assertEqual(params["markets"],"btts")
            return {"id":"odds_event_001","home_team":"Aston Villa","away_team":"Manchester City",
                    "bookmakers":[{"key":"sample","title":"Sample",
                                   "markets":[{"key":"btts","outcomes":[
                                       {"name":"Yes","price":1.8},{"name":"No","price":2.05}]}]}]}, {"remaining":"477"}
        usage={}
        with patch("fetch_odds.fetch",side_effect=fake_fetch):
            result=collect("dummy",["soccer_epl"],6,
                           frozen_snapshot=model(fixture(probability_btts=.62,over35=.49)),
                           confidence_extra_calls=4,usage=usage,reserve_credits=100)
        self.assertEqual(len(calls),3)
        self.assertEqual(usage["spentCredits"],3)
        self.assertEqual(usage["confidenceRequestsExecuted"],1)
        self.assertEqual([m["key"] for m in result[0]["bookmakers"][0]["markets"]],["btts"])

if __name__=="__main__":
    unittest.main()
