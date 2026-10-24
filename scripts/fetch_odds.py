#!/usr/bin/env python3
"""Quota-aware Odds API integration smoke test.

Default mode checks authentication and available sports at ZERO quota cost.
Chargeable bookmaker requests require explicit --mode collect.
No credentials, authenticated URLs, or bookmaker payloads are written to logs.
"""
import argparse
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPORTS = (
    "soccer_epl",
    "soccer_efl_champ",
    "soccer_england_league1",
    "soccer_england_league2",
)
BASE = "https://api.the-odds-api.com/v4"
REGION = "uk"
MARKETS = ("h2h", "totals")
MAX_COST_PER_SPORT = len(MARKETS)  # One region; excludes unavailable markets.


def fetch(path, key, params=None):
    arguments = {"apiKey": key}
    arguments.update(params or {})
    url = BASE + path + "?" + urllib.parse.urlencode(arguments)
    request = urllib.request.Request(
        url, headers={"User-Agent": "FootballPredictionBoardOddsAudit/1.0"}
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.load(response)
            headers = {
                "remaining": response.headers.get("x-requests-remaining"),
                "used": response.headers.get("x-requests-used"),
                "last": response.headers.get("x-requests-last"),
            }
    except urllib.error.HTTPError as exc:
        # HTTPError messages can contain the full authenticated URL.
        raise RuntimeError("Odds API returned HTTP status " + str(exc.code)) from None
    except Exception:
        # Do not propagate underlying URL, network or token details to public logs.
        raise RuntimeError("Odds API network or response validation failed") from None
    return payload, headers


def quota_remaining(headers):
    try:
        amount = int(headers["remaining"])
        if amount < 0:
            raise ValueError("negative quota")
        return amount
    except (TypeError, ValueError, KeyError):
        raise RuntimeError("Missing or invalid quota headers; stopping safely") from None


def preflight(key):
    # The Odds API explicitly documents this endpoint as zero usage credits.
    sports, headers = fetch("/sports/", key)
    if not isinstance(sports, list):
        raise RuntimeError("Unexpected sports response")
    active = {s.get("key") for s in sports
              if isinstance(s, dict) and s.get("active")}
    remaining = quota_remaining(headers)
    for sport in SPORTS:
        print(sport + ": " + ("active" if sport in active else "not currently listed as active"))
    print("Authentication verified; credits remaining: " + str(remaining))
    print("Preflight endpoint cost: 0 credits")
    return active, remaining


def collect(key, selected, max_credits, save=False, extra_markets=(), extra_events=0, frozen_snapshot=None, usage=None, reserve_credits=0, confidence_extra_calls=0):
    active, remaining = preflight(key)
    start_remaining = remaining
    if usage is not None:
        usage.update(startRemaining=remaining, endRemaining=remaining, spentCredits=0,
                     requestedSports=list(selected), plannedMaxCredits=max_credits)
    if any(sport not in active for sport in selected):
        raise RuntimeError("A requested competition is not currently active")
    if extra_markets and (not frozen_snapshot or frozen_snapshot.get("status") != "frozen-prekickoff"):
        raise RuntimeError("Event markets require an immutable pre-match forecast snapshot")
    if extra_markets and not 0 < extra_events <= 3:
        raise RuntimeError("Event markets require an explicit limit of 1 to 3 matched events")
    if not isinstance(confidence_extra_calls, int) or not 0 <= confidence_extra_calls <= 4:
        raise RuntimeError("Extra-market request cap must be between zero and four")
    if confidence_extra_calls and (extra_markets or extra_events):
        raise RuntimeError("Cannot combine legacy event extras and confidence-targeted requests")
    if confidence_extra_calls and (not frozen_snapshot or frozen_snapshot.get("status") != "frozen-prekickoff"):
        raise RuntimeError("Confidence-targeted requests require frozen model forecasts")
    upper_bound = len(selected) * MAX_COST_PER_SPORT + len(extra_markets) * extra_events + confidence_extra_calls
    if upper_bound > max_credits:
        raise RuntimeError("Requested markets exceed the explicit credit budget")
    if remaining < upper_bound:
        raise RuntimeError("Insufficient remaining credits for the maximum planned cost")
    if remaining - upper_bound < reserve_credits:
        raise RuntimeError("Credit reserve threshold reached; collecting no paid odds")

    games = []
    for sport in selected:
        # Budget is checked before every chargeable request, not just once.
        if remaining < MAX_COST_PER_SPORT or remaining - MAX_COST_PER_SPORT < reserve_credits:
            raise RuntimeError("Remaining credits too low; stopped before next request")
        payload, headers = fetch(
            "/sports/" + sport + "/odds/",
            key,
            {"regions": REGION, "markets": ",".join(MARKETS), "oddsFormat": "decimal"},
        )
        if not isinstance(payload, list):
            raise RuntimeError("Unexpected bookmaker odds response")
        remaining = quota_remaining(headers)
        if usage is not None:
            usage.update(endRemaining=remaining, spentCredits=max(0, start_remaining-remaining))
        if (start_remaining - remaining) > max_credits:
            raise RuntimeError("Odds API usage exceeded the run budget; halting further calls")
        for game in payload:
            if not isinstance(game, dict) or not all(
                isinstance(game.get(field), str)
                for field in ("id", "home_team", "away_team", "commence_time")
            ) or not isinstance(game.get("bookmakers"), list):
                raise RuntimeError("Invalid event schema in bookmaker response")
            games.append({
                "sport": sport,
                "id": game["id"],
                "commence_time": game["commence_time"],
                "home_team": game["home_team"],
                "away_team": game["away_team"],
                "bookmakers": game["bookmakers"],
            })
        offered_markets = sorted({
            market.get("key")
            for match in payload
            for book in match.get("bookmakers", [])
            for market in book.get("markets", [])
            if isinstance(market, dict) and market.get("key") in MARKETS
        })
        print(sport + ": " + str(len(payload)) + " fixtures; offered markets: " +
              (", ".join(offered_markets) or "none") +
              "; credits remaining: " + str(remaining))

    if extra_markets:
        from edge_comparison import canonical, event_key, fixture_key, fixture_kickoff, parse_utc
        from collections import defaultdict
        lookups = defaultdict(list)
        for fixture in frozen_snapshot.get("games", []):
            k = fixture_key(fixture)
            if k:
                lookups[k].append(fixture)
        candidates = []
        now = datetime.now(timezone.utc)
        for event in games:
            k = event_key(event)
            options = lookups.get(k, []) if k else []
            if len(options) != 1:
                continue
            fixture = options[0]
            start = parse_utc(event.get("commence_time"))
            expected = fixture_kickoff(fixture)
            if not start or not expected or start <= now or expected <= now:
                continue
            if abs((expected-start).total_seconds()) > 90 * 60:
                continue
            eid = event.get("id", "")
            if not isinstance(eid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{3,128}", eid):
                continue
            candidates.append(event)
        for event in sorted(candidates, key=lambda item: item["commence_time"])[:extra_events]:
            upper = len(extra_markets)
            if remaining < upper or remaining - upper < reserve_credits:
                raise RuntimeError("Credits insufficient for event markets; stopping safely")
            payload, headers = fetch(
                "/sports/" + event["sport"] + "/events/" + event["id"] + "/odds",
                key,
                {"regions": REGION, "markets": ",".join(extra_markets), "oddsFormat": "decimal"},
            )
            remaining = quota_remaining(headers)
            if usage is not None:
                usage.update(endRemaining=remaining, spentCredits=max(0, start_remaining-remaining))
            if (start_remaining - remaining) > max_credits:
                raise RuntimeError("Odds API usage exceeded the run budget; halting further calls")
            if not isinstance(payload, dict) or payload.get("id") != event["id"]:
                raise RuntimeError("Event-market response identity mismatch")
            if canonical(payload.get("home_team")) != canonical(event.get("home_team")) or (
                canonical(payload.get("away_team")) != canonical(event.get("away_team"))
            ):
                raise RuntimeError("Event-market team identity mismatch")
            bookmakers = payload.get("bookmakers")
            if not isinstance(bookmakers, list):
                raise RuntimeError("Malformed event bookmaker list")
            known = {b.get("key"): b for b in event["bookmakers"] if isinstance(b, dict)}
            added = set()
            for book in bookmakers:
                if not isinstance(book, dict) or not book.get("key"):
                    continue
                existing = known.get(book["key"])
                if existing is None:
                    existing = {"key": book["key"], "title": book.get("title", book["key"]), "markets": []}
                    event["bookmakers"].append(existing)
                    known[book["key"]] = existing
                if not isinstance(book.get("markets"), list):
                    continue
                for market in book["markets"]:
                    if not isinstance(market, dict) or market.get("key") not in extra_markets:
                        continue
                    if not any(m.get("key") == market["key"] for m in existing.get("markets", [])):
                        existing.setdefault("markets", []).append(market)
                        added.add(market["key"])
            print("Event-market lookup:", event["sport"], "offered:", ",".join(sorted(added)) or "none",
                  "; credits remaining:", remaining)

    if confidence_extra_calls:
        from edge_comparison import canonical, select_confident_event_markets
        targets = select_confident_event_markets(
            frozen_snapshot, games, datetime.now(timezone.utc),
            max_requests=confidence_extra_calls,
        )
        if usage is not None:
            usage["confidenceQualifyingRequests"] = len(targets)
            usage["confidenceSelectionPolicy"] = "BTTS 60%+, Over/Under 3.5 70%+; skip already-priced outcomes"
        print("High-confidence event markets selected:", len(targets),
              "of allowed", confidence_extra_calls)
        indexed = {e["id"]: e for e in games}
        for target in targets:
            event = indexed.get(target["eventId"])
            if not event or event.get("sport") != target["sport"]:
                raise RuntimeError("Target event identity changed after selection")
            eid = target["eventId"]
            market_key = target["market"]
            if not isinstance(eid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{3,128}", eid):
                raise RuntimeError("Event id is not safe for a provider request")
            if market_key not in ("btts", "alternate_totals"):
                raise RuntimeError("Unsupported targeted bookmaker market")
            if remaining < 1 or remaining - 1 < reserve_credits:
                raise RuntimeError("API allowance reserve prevents an extra-market request")
            if (start_remaining - remaining + 1) > max_credits:
                raise RuntimeError("Daily budget prevents another extra-market request")
            payload, headers = fetch(
                "/sports/" + event["sport"] + "/events/" + eid + "/odds",
                key, {"regions": REGION, "markets": market_key, "oddsFormat": "decimal"},
            )
            remaining = quota_remaining(headers)
            if usage is not None:
                usage.update(endRemaining=remaining, spentCredits=max(0, start_remaining-remaining))
                usage["confidenceRequestsExecuted"] = usage.get("confidenceRequestsExecuted", 0) + 1
            if (start_remaining - remaining) > max_credits:
                raise RuntimeError("Odds API usage exceeded the run budget")
            if not isinstance(payload, dict) or payload.get("id") != eid:
                raise RuntimeError("Targeted market response identity mismatch")
            if (canonical(payload.get("home_team")) != canonical(event.get("home_team")) or
                    canonical(payload.get("away_team")) != canonical(event.get("away_team"))):
                raise RuntimeError("Targeted market response team identity mismatch")
            if not isinstance(payload.get("bookmakers"), list):
                raise RuntimeError("Targeted market response lacks valid bookmakers")
            existing_books = {b.get("key"): b for b in event["bookmakers"]
                              if isinstance(b, dict) and b.get("key")}
            offered = False
            for book in payload["bookmakers"]:
                if not isinstance(book, dict) or not book.get("key") or not isinstance(book.get("markets"), list):
                    continue
                current = existing_books.get(book["key"])
                if current is None:
                    current = {"key": book["key"], "title": book.get("title", book["key"]), "markets": []}
                    event["bookmakers"].append(current)
                    existing_books[book["key"]] = current
                if not isinstance(current.get("markets"), list):
                    continue
                for market in book["markets"]:
                    if not isinstance(market, dict) or market.get("key") != market_key:
                        continue
                    # Do not duplicate a market that appeared in the batch feed.
                    if not any(m.get("key") == market_key for m in current["markets"] if isinstance(m, dict)):
                        current["markets"].append(market)
                    offered = True
            print("Confidence request:", market_key, "model probability",
                  target["modelProbability"], "fixture", target["fixtureId"],
                  "offered:", offered, "; credits remaining:", remaining)

    if save:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%S%fZ")
        output = ROOT / "private_odds" / (stamp + ".json")
        output.parent.mkdir(parents=True, exist_ok=True)
        content = {
            "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
            "provider": "The Odds API",
            "regions": REGION,
            "markets_requested": list(MARKETS),
            "price_type": "provider_response_not_independently_verified",
            "fixtures": games,
        }
        with output.open("x", encoding="utf-8") as stream:
            json.dump(content, stream, indent=2)
        print("Saved local odds snapshot: " + str(output.relative_to(ROOT)))
    else:
        print("Smoke test complete. Raw odds were NOT saved, published or uploaded.")
    return games


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("preflight", "collect"), default="preflight")
    parser.add_argument("--sport", action="append", choices=SPORTS)
    parser.add_argument("--max-credits", type=int, default=2)
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--extra-market", choices=("btts", "alternate_totals"), action="append")
    parser.add_argument("--extra-events", type=int, default=0)
    parser.add_argument("--compare-snapshot", type=Path, help="Locally assess collected odds against frozen model forecasts")
    parser.add_argument("--comparison-output", type=Path, help="Write anonymised selection summary, not full bookmaker feed")
    parser.add_argument("--print-comparison-json", action="store_true", help="Print public bookmaker comparison JSON to audit log")
    args = parser.parse_args()
    if args.max_credits < 1 or args.max_credits > 24:
        parser.error("credit limit must be between 1 and 24")
    if args.save and args.mode != "collect":
        parser.error("--save requires --mode collect")
    if args.comparison_output and not args.compare_snapshot:
        parser.error("--comparison-output requires --compare-snapshot")
    if args.compare_snapshot and args.mode != "collect":
        parser.error("--compare-snapshot requires --mode collect")
    if args.print_comparison_json and not args.compare_snapshot:
        parser.error("--print-comparison-json requires --compare-snapshot")
    if args.extra_market and not args.compare_snapshot:
        parser.error("Event markets require --compare-snapshot to restrict requests to matching fixtures")
    if args.extra_market and not 0 < args.extra_events <= 3:
        parser.error("Use --extra-events 1 to 3 explicitly for event markets")
    if args.extra_events and not args.extra_market:
        parser.error("--extra-events requires --extra-market")
    if args.comparison_output and args.comparison_output.resolve().is_relative_to((ROOT / "data").resolve()):
        parser.error("Do not publish previews under public data/ before review")
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        raise SystemExit("ODDS_API_KEY secret is not available to this job")
    try:
        if args.mode == "preflight":
            preflight(key)
        else:
            forecasts = json.loads(args.compare_snapshot.read_text(encoding="utf-8")) if args.compare_snapshot else None
            games = collect(key, args.sport or [SPORTS[0]], args.max_credits, args.save,
                            tuple(dict.fromkeys(args.extra_market or ())), args.extra_events, forecasts)
            if args.compare_snapshot:
                from edge_comparison import assess
                comparison = assess(forecasts, {
                    "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
                    "fixtures": games,
                })
                stats = comparison["summary"]
                print("Live edge comparison: matched fixtures =", stats["matchedFixtures"],
                      "priced markets =", stats["marketsPriced"],
                      "positive theoretical edges =", stats["positiveEdges"])
                print("Excluded matches:", json.dumps(stats["unmatchedReasons"], sort_keys=True))
                if args.print_comparison_json:
                    print("EDGE_REPORT_JSON=" + json.dumps(comparison, separators=(",", ":"), ensure_ascii=True))
                if args.comparison_output:
                    args.comparison_output.parent.mkdir(parents=True, exist_ok=True)
                    with args.comparison_output.open("x", encoding="utf-8") as output:
                        json.dump(comparison, output, indent=2)
                    print("Saved PRIVATE comparison preview:", args.comparison_output)
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from None


if __name__ == "__main__":
    main()
