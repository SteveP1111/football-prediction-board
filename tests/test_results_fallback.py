"""Offline tests for verified full-time fallback: two sources, no odds/backfill."""
import json
import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import refresh
from results_fallback import (
    parse_espn, parse_footballwebpages, reconcile,
    get_confirmed_fallback, verified_id, public_get,
)


def fixture(day="2026-10-31", league="E0", home="Man City", away="Brighton"):
    return {"id": verified_id(day, league, home, away, refresh.canon),
            "date": day, "division": league, "home": home, "away": away}


def event(day="2026-10-31", home="Manchester City", away="Brighton & Hove Albion",
          home_score="0", away_score="1", completed=True):
    return {
        "date": day + "T15:00:00Z",
        "competitions": [{
            "status": {"type": {"completed": completed, "name": "STATUS_FINAL" if completed else "STATUS_IN_PROGRESS"}},
            "competitors": [
                {"homeAway": "home", "team": {"displayName": home}, "score": home_score},
                {"homeAway": "away", "team": {"displayName": away}, "score": away_score},
            ],
        }],
    }


def html_rows(league_name, rows):
    table = "".join(
        "<tr><td>" + state + "</td><td><a>" + home +
        "</a></td><td>" + str(hg) + "</td><td>" + str(ag) +
        "</td><td><a>" + away + "</a></td></tr>"
        for state, home, hg, ag, away in rows)
    return "<html><h2>" + league_name + "</h2><table><tbody>" + table + "</tbody></table></html>"


class ResultFallbackTests(unittest.TestCase):
    def test_espn_requires_final_date_and_explicit_home_away(self):
        final = event()
        tests = [final,
                 event(home_score="1", away_score="2", completed=False),
                 event(day="2026-11-01"),
                 event(home_score="nan")]
        results = parse_espn({"events": tests}, "E0", "2026-10-31", refresh.canon)
        self.assertEqual(results, {fixture()["id"]: (0, 1)})

    def test_wrong_competition_and_unverified_score_do_not_match(self):
        self.assertNotEqual(
            verified_id("2026-10-31", "E1", "Man City", "Brighton", refresh.canon),
            fixture()["id"])
        self.assertNotEqual(
            verified_id("2026-10-31", "E0", "Man Utd", "Brighton", refresh.canon),
            fixture()["id"])
        self.assertEqual(parse_espn({"events": [event(completed=False)]},
                                    "E0", "2026-10-31", refresh.canon), {})

    def test_webpages_ft_only_and_exact_competition(self):
        html = (
            html_rows("Premier League", [
                ("FT", "Manchester City", 0, 1, "Brighton & Hove Albion"),
                ("HT", "Chelsea", 1, 0, "Manchester United")])
            + html_rows("Scottish Championship", [
                ("FT", "Rangers", 2, 1, "Celtic")])
        )
        results = parse_footballwebpages(html, "2026-10-31", refresh.canon)
        self.assertEqual(results, {fixture()["id"]: (0, 1)})

    def test_conflicting_provider_results_never_grades(self):
        f = fixture()
        day = date(2026, 11, 2)
        urls = []
        def fetch(url):
            urls.append(url)
            if "espn" in url:
                return json.dumps({"events": [event(away_score="2")]})
            return html_rows("Premier League", [
                ("FT", "Manchester City", 0, 1, "Brighton & Hove Albion")])
        pending, audit = get_confirmed_fallback([f], {}, {}, day,
                                                 refresh.canon, fetcher=fetch)
        self.assertEqual(pending, {})
        self.assertEqual(audit["fullyConfirmed"], 0)
        self.assertEqual(audit["unconfirmed"], 1)
        self.assertEqual(audit["conflicts"][0]["fixtureId"], f["id"])
        self.assertEqual(len(urls), 2)

    def test_two_independent_final_scores_settle_exactly_once(self):
        f = fixture()
        def fetch(url):
            if "espn" in url:
                return json.dumps({"events": [event()]})
            return html_rows("Premier League", [
                ("FT", "Manchester City", 0, 1, "Brighton & Hove Albion")])
        scores, audit = get_confirmed_fallback(
            [f], {}, {}, date(2026, 11, 2), refresh.canon, fetcher=fetch)
        self.assertEqual(scores[f["id"]]["score"], (0, 1))
        self.assertEqual(len(scores[f["id"]]["sources"]), 2)
        merged, accepted = reconcile({}, scores, {})
        self.assertEqual(merged[f["id"]], (0, 1))
        self.assertEqual(len(accepted), 1)
        self.assertEqual(audit["fullyConfirmed"], 1)

    def test_postponed_or_unconfirmed_fixtures_are_pending(self):
        f = fixture()
        def fetch(url):
            if "espn" in url:
                return json.dumps({"events": [event(completed=False)]})
            return html_rows("Premier League", [
                ("HT", "Manchester City", 0, 1, "Brighton & Hove Albion")])
        scores, audit = get_confirmed_fallback(
            [f], {}, {}, date(2026, 11, 2), refresh.canon, fetcher=fetch)
        self.assertFalse(scores)
        self.assertEqual(audit["unconfirmed"], 1)

    def test_primary_csv_and_existing_settlements_not_rewritten(self):
        f = fixture()
        evidence = {"score": (0, 1), "sources": ["espn", "footballwebpages"]}
        with self.assertRaisesRegex(ValueError, "primary"):
            reconcile({f["id"]: (2, 0)}, {f["id"]: evidence}, {})
        with self.assertRaisesRegex(ValueError, "previously settled"):
            reconcile({}, {f["id"]: evidence}, {f["id"]: {"score": "2-0"}})
        primary = {f["id"]: (0, 1)}
        before = dict(primary)
        merged, accepted = reconcile(primary, {f["id"]: evidence}, {})
        self.assertEqual(before, primary)
        self.assertEqual(merged, primary)
        self.assertEqual(accepted, {})

    def test_future_or_today_or_old_or_already_settled_not_fetched(self):
        tests = [fixture(day="2026-11-02"), fixture(day="2026-11-03"),
                 fixture(day="2026-10-01"), fixture(day="2026-10-31")]
        called = []
        def fetch(url):
            called.append(url)
            raise RuntimeError("Should not fetch")
        prior = {tests[-1]["id"]: {"score": "0-1"}}
        scores, report = get_confirmed_fallback(
            tests, {}, prior, date(2026, 11, 2), refresh.canon, fetcher=fetch)
        self.assertEqual(called, [])
        self.assertEqual(scores, {})
        self.assertEqual(report["attemptedDates"], [])

    def test_partial_source_failure_is_not_a_verified_result(self):
        f = fixture()
        def fetch(url):
            if "espn" in url:
                raise TimeoutError("No provider access")
            return html_rows("Premier League", [
                ("FT", "Manchester City", 0, 1, "Brighton & Hove Albion")])
        scores, audit = get_confirmed_fallback(
            [f], {}, {}, date(2026, 11, 2), refresh.canon, fetcher=fetch)
        self.assertFalse(scores)
        self.assertEqual(len(audit["sourceErrors"]), 1)
        self.assertEqual(audit["unconfirmed"], 1)

    def test_url_allowlist_blocks_untrusted_hosts(self):
        with self.assertRaises(ValueError):
            public_get("https://example.com/match?sensitive=abc")


if __name__ == "__main__":
    unittest.main()
