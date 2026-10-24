#!/usr/bin/env python3
"""Zero-credit fixture coverage diagnostic. Never requests bookmaker prices."""
import argparse
import json
import os
from collections import Counter
from datetime import datetime
from pathlib import Path

from edge_comparison import SPORT_DIVISION, event_key, fixture_key, fixture_kickoff, parse_utc
from fetch_odds import ROOT, fetch, quota_remaining

def run():
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, default=ROOT / "data/latest.json")
    args = parser.parse_args()
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        raise SystemExit("ODDS_API_KEY not configured")
    snap = json.loads(args.snapshot.read_text(encoding="utf-8"))
    fixtures = snap.get("games", [])
    print("MODEL SOURCE DATE:", snap.get("date"), "CAPTURE:", snap.get("capturedAt"), "STATUS:", snap.get("status"))
    lookups = {fixture_key(f): f for f in fixtures if fixture_key(f)}
    for sport in SPORT_DIVISION:
        payload, headers = fetch("/sports/" + sport + "/events", key)
        if not isinstance(payload, list):
            raise RuntimeError("Invalid event list response")
        remaining = quota_remaining(headers)
        counts = Counter()
        matchlist = []
        starts = []
        local_days = []
        for event in payload:
            if not isinstance(event, dict):
                continue
            event = dict(event, sport=sport)
            k = event_key(event)
            start = parse_utc(event.get("commence_time"))
            if start:
                starts.append(start.isoformat())
                local_days.append(start.astimezone(__import__("zoneinfo").ZoneInfo("Europe/London")).date().isoformat())
            if k in lookups:
                f = lookups[k]
                expected = fixture_kickoff(f)
                if expected and start and abs((start-expected).total_seconds()) <= 5400:
                    matchlist.append(f["id"])
                else:
                    counts["different_kickoff"] += 1
            elif k and k[3] == snap.get("date"):
                counts["same_date_other_teams"] += 1
            else:
                counts["other_date_or_unsupported"] += 1
        models = [f for f in fixtures if f.get("division") == SPORT_DIVISION[sport]]
        print(sport, "model fixtures:", len(models), "API events:", len(payload),
              "exact matches:", len(matchlist),
              "API first date:", min(starts, default="none")[:10],
              "API last date:", max(starts, default="none")[:10],
              "first London date:", min(local_days, default="none"),
              "reasons:", json.dumps(counts, sort_keys=True),
              "credits remaining:", remaining)
        if sport == "soccer_epl":
            print("Premier League model today:", " | ".join(f["home"]+" v "+f["away"] for f in models))
            same_day = [e["home_team"]+" v "+e["away_team"]
                        for e in payload if isinstance(e, dict) and
                        event_key(dict(e, sport=sport)) and
                        event_key(dict(e, sport=sport))[3] == snap.get("date")]
            print("API same-day Premier League events:", " | ".join(same_day[:12]) or "none")
    print("Fixture coverage inspection complete. No bookmaker prices requested.")

if __name__ == "__main__":
    try:
        run()
    except RuntimeError as e:
        raise SystemExit(str(e)) from None
