#!/usr/bin/env python3
"""Safely join immutable, independently generated forecasts to The Odds API prices.

No network access. Reads JSON supplied as arguments. Prices never feed the model.
Only league + two canonical team names + kick-off match within 90 minutes can join.
Missing/stale/ambiguous events are excluded, never guessed or relabelled.
"""
import argparse
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

LONDON = ZoneInfo("Europe/London")
SPORT_DIVISION = {
    "soccer_epl": "E0",
    "soccer_efl_champ": "E1",
    "soccer_england_league1": "E2",
    "soccer_england_league2": "E3",
}
DIVISION_SPORT = {v: k for k, v in SPORT_DIVISION.items()}
MARKET_TITLES = {
    "home_win": "Home win", "draw": "Draw", "away_win": "Away win",
    "btts": "BTTS Yes", "no_btts": "BTTS No",
    "over25": "Over 2.5", "under25": "Under 2.5",
    "over35": "Over 3.5", "under35": "Under 3.5",
}
# Explicitly reviewed whole-club aliases only. No approximate name similarity.
TEAM_ALIASES = {
    "arsenal fc": "arsenal", "afc bournemouth": "bournemouth",
    "bournemouth afc": "bournemouth", "brighton hove albion": "brighton and hove albion",
    "brighton and hove albion": "brighton and hove albion", "brighton": "brighton and hove albion",
    "manchester city": "manchester city", "man city": "manchester city",
    "manchester united": "manchester united", "man utd": "manchester united",
    "man united": "manchester united", "manchester utd": "manchester united",
    "nottingham forest": "nottm forest", "nottm forest": "nottm forest",
    "newcastle united": "newcastle", "newcastle utd": "newcastle",
    "newcastle": "newcastle", "tottenham hotspur": "tottenham", "tottenham": "tottenham",
    "west ham united": "west ham", "west ham": "west ham",
    "wolverhampton wanderers": "wolverhampton wanderers",
    "wolverhampton": "wolverhampton wanderers", "wolves": "wolverhampton wanderers",
    "leicester city": "leicester", "leicester": "leicester",
    "norwich city": "norwich", "norwich": "norwich",
    "swansea city": "swansea", "swansea": "swansea",
    "cardiff city": "cardiff", "cardiff": "cardiff",
    "hull city": "hull", "hull": "hull",
    "stoke city": "stoke", "stoke": "stoke",
    "derby county": "derby", "derby": "derby",
    "ipswich town": "ipswich town", "ipswich": "ipswich town",
    "luton town": "luton town", "luton": "luton town",
    "queens park rangers": "queens park rangers", "qpr": "queens park rangers",
    "sheffield wednesday": "sheffield wednesday", "sheffield wed": "sheffield wednesday",
    "sheffield weds": "sheffield wednesday",
    "sheffield united": "sheffield united", "sheffield utd": "sheffield united",
    "bolton wanderers": "bolton", "bolton": "bolton",
    "blackburn rovers": "blackburn rovers", "blackburn": "blackburn rovers",
    "west bromwich albion": "west bromwich albion", "west brom": "west bromwich albion",
    "bristol rovers": "bristol rovers", "bristol rvs": "bristol rovers",
    "bristol city": "bristol city", "bristol c": "bristol city",
    "peterborough united": "peterborough", "peterborough": "peterborough",
    "huddersfield town": "huddersfield town", "huddersfield": "huddersfield town",
    "stockport county": "stockport county", "stockport": "stockport county",
    "milton keynes dons": "milton keynes dons", "mk dons": "milton keynes dons",
    "afc wimbledon": "afc wimbledon", "wimbledon": "afc wimbledon",
    "cambridge united": "cambridge united", "cambridge": "cambridge united",
    "newport county": "newport county", "newport": "newport county",
    "colchester united": "colchester united", "colchester": "colchester united",
    "grimsby town": "grimsby town", "grimsby": "grimsby town",
    "salford city": "salford city", "salford": "salford city",
    "accrington stanley": "accrington stanley", "accrington": "accrington stanley",
    "burton albion": "burton", "burton": "burton",
    "northampton town": "northampton town", "northampton": "northampton town",
    "shrewsbury town": "shrewsbury town", "shrewsbury": "shrewsbury town",
    "oxford united": "oxford united", "oxford utd": "oxford united",
    "rotherham united": "rotherham united", "rotherham": "rotherham united",
    "plymouth argyle": "plymouth argyle", "plymouth": "plymouth argyle",
    "tranmere rovers": "tranmere rovers", "tranmere": "tranmere rovers",
    "crewe alexandra": "crewe", "crewe": "crewe",
    "birmingham city": "birmingham", "birmingham": "birmingham",
    "coventry city": "coventry", "coventry": "coventry",
    "portsmouth fc": "portsmouth", "portsmouth": "portsmouth",
    "charlton athletic": "charlton", "charlton": "charlton",
    "reading fc": "reading", "reading": "reading",
    "wrexham afc": "wrexham", "wrexham": "wrexham",
    "sunderland afc": "sunderland", "sunderland": "sunderland",
    "notts county": "notts county", "notts co": "notts county",
    "leyton orient": "leyton orient", "orient": "leyton orient",
}

def canonical(name):
    if not isinstance(name, str):
        return ""
    value = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    value = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    return TEAM_ALIASES.get(value, value)


def parse_utc(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except ValueError:
        return None


def fixture_kickoff(fixture):
    try:
        day = str(fixture["date"])
        hhmm = str(fixture["kickoff"])
        if not re.fullmatch(r"\d{2}:\d{2}", hhmm):
            return None
        return datetime.fromisoformat(day + "T" + hhmm).replace(tzinfo=LONDON).astimezone(timezone.utc)
    except (KeyError, ValueError, TypeError):
        return None


def probability(fixture, key):
    market = (fixture.get("scoreline") or {}).get("markets") or {}
    raw = (1.0 - market["over35"]) if key == "under35" and "over35" in market else market.get(key)
    if isinstance(raw, bool) or not isinstance(raw, (float, int)) or not math.isfinite(raw):
        return None
    return float(raw) if 0 <= raw <= 1 else None


def event_key(event):
    div = SPORT_DIVISION.get(event.get("sport"))
    home = canonical(event.get("home_team"))
    away = canonical(event.get("away_team"))
    start = parse_utc(event.get("commence_time"))
    if not div or not home or not away or not start or home == away:
        return None
    return (div, home, away, start.astimezone(LONDON).date().isoformat())


def fixture_key(fixture):
    home = canonical(fixture.get("homeKey") or fixture.get("home"))
    away = canonical(fixture.get("awayKey") or fixture.get("away"))
    if not home or not away or home == away:
        return None
    return (fixture.get("division"), home, away, fixture.get("date"))


def decimal_price(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) and 1.01 <= value <= 1000 else None


def outcome_key(market_key, outcome, event):
    name = str(outcome.get("name") or "").casefold().strip()
    if market_key == "h2h":
        if name in ("draw", "tie", "x"):
            return "draw"
        if canonical(name) == canonical(event.get("home_team")):
            return "home_win"
        if canonical(name) == canonical(event.get("away_team")):
            return "away_win"
    elif market_key in ("totals", "alternate_totals"):
        point = outcome.get("point")
        if isinstance(point, bool) or not isinstance(point, (int, float)) or point not in (2.5, 3.5):
            return None
        if name not in ("over", "under"):
            return None
        return name + ("25" if point == 2.5 else "35")
    elif market_key == "btts":
        if name == "yes":
            return "btts"
        if name == "no":
            return "no_btts"
    return None


def assess(snapshot, odds, max_age_hours=24):
    if not isinstance(snapshot, dict) or not isinstance(odds, dict):
        raise ValueError("Expected JSON snapshot and odds objects")
    if snapshot.get("status") != "frozen-prekickoff":
        raise ValueError("Only original frozen-prekickoff forecasts may be compared")
    retrieved = parse_utc(odds.get("retrieved_at_utc"))
    captured = parse_utc(snapshot.get("capturedAt"))
    if not retrieved or not captured or retrieved < captured:
        raise ValueError("Invalid or out-of-order capture timestamps")
    events = odds.get("fixtures")
    fixtures = snapshot.get("games")
    if not isinstance(events, list) or not isinstance(fixtures, list):
        raise ValueError("Expected fixture arrays")
    if not 0 < max_age_hours <= 72:
        raise ValueError("Invalid maximum odds age")

    forecast_lookup = defaultdict(list)
    for f in fixtures:
        key = fixture_key(f)
        if key:
            forecast_lookup[key].append(f)

    matching = {}
    reasons = Counter()
    seen_event_ids = set()
    for event in events:
        if not isinstance(event, dict):
            reasons["invalid_event"] += 1
            continue
        eid = event.get("id")
        if not isinstance(eid, str) or not eid or eid in seen_event_ids:
            reasons["invalid_or_duplicate_id"] += 1
            continue
        seen_event_ids.add(eid)
        key = event_key(event)
        if not key:
            reasons["unsupported_league_or_bad_event"] += 1
            continue
        candidates = forecast_lookup.get(key, [])
        if len(candidates) != 1:
            reasons["unmatched_or_ambiguous_name"] += 1
            continue
        f = candidates[0]
        fkickoff = fixture_kickoff(f)
        ekickoff = parse_utc(event.get("commence_time"))
        if not fkickoff:
            reasons["unknown_forecast_kickoff"] += 1
            continue
        if abs((fkickoff - ekickoff).total_seconds()) > 90 * 60:
            reasons["kickoff_conflict"] += 1
            continue
        if not (captured < fkickoff and retrieved < min(fkickoff, ekickoff)):
            reasons["already_started_or_not_pre_match"] += 1
            continue
        if f["id"] in matching:
            # Two odds events mapping to the same forecast is ambiguous; exclude both.
            matching[f["id"]] = None
            reasons["duplicate_fixture_mapping"] += 1
        else:
            matching[f["id"]] = (f, event)

    prices = []
    for fixture_id, matched in sorted(matching.items()):
        if matched is None:
            continue
        fixture, event = matched
        best = {}
        offered = defaultdict(set)
        books = event.get("bookmakers")
        if not isinstance(books, list):
            reasons["invalid_bookmaker_list"] += 1
            continue
        for book in books:
            if not isinstance(book, dict) or not isinstance(book.get("markets"), list):
                continue
            bookmaker_key = str(book.get("key") or "")
            bookmaker = str(book.get("title") or bookmaker_key).strip()
            if not bookmaker_key or not bookmaker:
                continue
            for market in book["markets"]:
                if not isinstance(market, dict) or market.get("key") not in ("h2h", "totals", "alternate_totals", "btts"):
                    continue
                mkey = market["key"]
                updated = parse_utc(market.get("last_update"))
                if updated:
                    age = (retrieved - updated).total_seconds()
                    if age < -300 or age > max_age_hours * 3600 or updated >= fixture_kickoff(fixture):
                        reasons["stale_or_postkickoff_market"] += 1
                        continue
                elif market.get("last_update") is not None:
                    reasons["invalid_market_timestamp"] += 1
                    continue
                outcomes = market.get("outcomes")
                if not isinstance(outcomes, list):
                    continue
                interpreted = [outcome_key(mkey, o, event) for o in outcomes if isinstance(o, dict)]
                # Reject soccer two-way h2h markets; they are not 1X2.
                if mkey == "h2h" and set(interpreted) != {"home_win", "draw", "away_win"}:
                    reasons["incomplete_1x2"] += 1
                    continue
                for outcome in outcomes:
                    if not isinstance(outcome, dict):
                        continue
                    key = outcome_key(mkey, outcome, event)
                    if not key:
                        continue
                    model_p = probability(fixture, key)
                    offered_price = decimal_price(outcome.get("price"))
                    if model_p is None or offered_price is None:
                        continue
                    offered[key].add(bookmaker_key)
                    item = {
                        "fixtureId": fixture_id,
                        "date": fixture["date"],
                        "division": fixture["division"],
                        "league": fixture.get("league"),
                        "home": fixture.get("home"),
                        "away": fixture.get("away"),
                        "kickoff": fixture.get("kickoff"),
                        "kickoffUtc": fixture_kickoff(fixture).isoformat(),
                        "eventId": event["id"],
                        "market": key,
                        "marketLabel": MARKET_TITLES[key],
                        "modelProbability": round(model_p, 5),
                        "odds": round(offered_price, 3),
                        "impliedProbability": round(1.0 / offered_price, 5),
                        "edgePp": round(100 * (model_p - 1.0 / offered_price), 2),
                        "expectedRoiPct": round(100 * (model_p * offered_price - 1), 2),
                        "bookmaker": bookmaker,
                        "bookmakerKey": bookmaker_key,
                        "marketUpdatedAtUtc": updated.isoformat() if updated else None,
                        "source": "The Odds API",
                        "model": (fixture.get("scoreline") or {}).get("model"),
                        "calibrated": bool((fixture.get("scoreline") or {}).get("calibrated")),
                    }
                    current = best.get(key)
                    if current is None or (item["odds"], -len(bookmaker), bookmaker.casefold()) > (
                        current["odds"], -len(current["bookmaker"]), current["bookmaker"].casefold()
                    ):
                        best[key] = item
        for key, item in best.items():
            item["bookmakersCompared"] = len(offered[key])
            item["positiveEdge"] = item["edgePp"] > 0
            prices.append(item)

    prices.sort(key=lambda x: (-int(x["positiveEdge"]), -x["modelProbability"],
                               -x["edgePp"], x["fixtureId"], x["market"]))
    matched_count = sum(value is not None for value in matching.values())
    return {
        "schemaVersion": 1,
        "status": "compared" if prices else "no-comparable-markets",
        "forecastDate": snapshot.get("date"),
        "forecastCapturedAt": snapshot.get("capturedAt"),
        "oddsRetrievedAtUtc": odds.get("retrieved_at_utc"),
        "provider": "The Odds API",
        "model": snapshot.get("model"),
        "calibrated": False,
        "ranking": "positive-edge-first, then model probability descending, edge as tiebreak",
        "bettingNote": "Experimental uncalibrated model. Theoretical edge does not imply betting profit; bookmaker odds are time-sensitive.",
        "summary": {
            "oddsEvents": len(events),
            "forecastFixtures": len(fixtures),
            "matchedFixtures": matched_count,
            "unmatchedForecasts": len(fixtures) - matched_count,
            "marketsPriced": len(prices),
            "positiveEdges": sum(bool(p["positiveEdge"]) for p in prices),
            "unmatchedReasons": dict(sorted(reasons.items())),
        },
        "picks": prices,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--odds", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    snap = json.loads(args.snapshot.read_text(encoding="utf-8"))
    odds = json.loads(args.odds.read_text(encoding="utf-8"))
    report = assess(snap, odds)
    print("Fixture matches:", report["summary"]["matchedFixtures"],
          "priced markets:", report["summary"]["marketsPriced"],
          "positive theoretical edges:", report["summary"]["positiveEdges"])
    print("Unmatched breakdown:", json.dumps(report["summary"]["unmatchedReasons"], sort_keys=True))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as output:
            json.dump(report, output, indent=2, ensure_ascii=False)
        print("Saved comparison summary (no secret or full bookmaker feed):", args.output)


if __name__ == "__main__":
    main()
