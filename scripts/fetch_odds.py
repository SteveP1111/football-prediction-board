#!/usr/bin/env python3
"""Quota-aware Odds API integration smoke test.

Default mode checks authentication and available sports at ZERO quota cost.
Chargeable bookmaker requests require explicit --mode collect.
No credentials, authenticated URLs, or bookmaker payloads are written to logs.
"""
import argparse
import json
import os
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


def collect(key, selected, max_credits, save=False):
    active, remaining = preflight(key)
    if any(sport not in active for sport in selected):
        raise RuntimeError("A requested competition is not currently active")
    upper_bound = len(selected) * MAX_COST_PER_SPORT
    if upper_bound > max_credits:
        raise RuntimeError("Requested markets exceed the explicit credit budget")
    if remaining < upper_bound:
        raise RuntimeError("Insufficient remaining credits for the maximum planned cost")

    games = []
    for sport in selected:
        # Budget is checked before every chargeable request, not just once.
        if remaining < MAX_COST_PER_SPORT:
            raise RuntimeError("Remaining credits too low; stopped before next request")
        payload, headers = fetch(
            "/sports/" + sport + "/odds/",
            key,
            {"regions": REGION, "markets": ",".join(MARKETS), "oddsFormat": "decimal"},
        )
        if not isinstance(payload, list):
            raise RuntimeError("Unexpected bookmaker odds response")
        remaining = quota_remaining(headers)
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
    args = parser.parse_args()
    if args.max_credits < 1 or args.max_credits > 8:
        parser.error("credit limit must be between 1 and 8")
    if args.save and args.mode != "collect":
        parser.error("--save requires --mode collect")
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        raise SystemExit("ODDS_API_KEY secret is not available to this job")
    try:
        if args.mode == "preflight":
            preflight(key)
        else:
            collect(key, args.sport or [SPORTS[0]], args.max_credits, args.save)
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from None


if __name__ == "__main__":
    main()
