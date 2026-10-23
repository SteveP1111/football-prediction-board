#!/usr/bin/env python3
"""Read-only odds collector. Never changes existing forecast snapshots."""
import json, os, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPORTS = ["soccer_epl", "soccer_england_championship", "soccer_england_league1", "soccer_england_league2"]
BASE = "https://api.the-odds-api.com/v4/sports/"
def collect():
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        raise SystemExit("ODDS_API_KEY not configured")
    all_games = []
    for sport in SPORTS:
        params = urllib.parse.urlencode({"apiKey": key, "regions": "uk", "markets": "h2h,totals", "oddsFormat": "decimal"})
        url = BASE + sport + "/odds/?" + params
        # Do not log the authenticated URL or exception containing it.
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "FootballEdgeResearch/1.0"}), timeout=20) as response:
                games = json.load(response)
                remaining = response.headers.get("x-requests-remaining")
                used = response.headers.get("x-requests-used")
        except Exception:
            raise SystemExit("Odds provider request failed for " + sport + "; credentials and API details withheld")
        for game in games:
            all_games.append({"sport": sport, "id": game.get("id"), "commence_time": game.get("commence_time"), "home_team": game.get("home_team"), "away_team": game.get("away_team"), "bookmakers": game.get("bookmakers", [])})
        print(f"{sport}: {len(games)} fixtures; credits remaining: {remaining}; used: {used}")
    now = datetime.now(timezone.utc).isoformat()
    output = ROOT / "data" / "odds" / (datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ") + ".json")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise SystemExit("Refusing to overwrite existing odds snapshot")
    output.write_text(json.dumps({"retrieved_at_utc": now, "provider": "The Odds API", "regions": "uk", "markets_requested": ["h2h", "totals"], "price_type": "provider_response_not_independently_verified", "fixtures": all_games}, indent=2), encoding="utf-8")
    print(f"Saved {len(all_games)} fixtures to {output.relative_to(ROOT)}")
if __name__ == "__main__":
    collect()
