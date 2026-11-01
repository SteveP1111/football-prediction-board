#!/usr/bin/env python3
"""Prospective BTTS forecast accuracy, separate from bookmaker-priced betting results.

Reads immutable pre-kickoff forecasts and the independently verified result ledger.
No historical prediction, quote, or outcome is modified. One probability-first
BTTS Yes/No forecast is graded per fixture; no stake or ROI is calculated.
"""
import json
import math
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUPPORTED = {"E0", "E1", "E2", "E3"}
DIVISIONS = {"E0": "Premier League", "E1": "Championship",
             "E2": "League One", "E3": "League Two", "EC": "National League"}
BANDS = ("Under 50%", "50–59.9%", "60–69.9%", "70–79.9%", "80%+")


def band(prob):
    value = prob * 100
    if value < 50:
        return BANDS[0]
    if value < 60:
        return BANDS[1]
    if value < 70:
        return BANDS[2]
    if value < 80:
        return BANDS[3]
    return BANDS[4]


def valid_probability(value):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value) and 0 <= value <= 1)


def summarise(rows):
    settled = [x for x in rows if x["correct"] is not None]
    correct = sum(x["correct"] for x in settled)
    return {
        "forecasts": len(rows),
        "graded": len(settled),
        "pending": len(rows) - len(settled),
        "correct": correct,
        "accuracyPct": round(100 * correct / len(settled), 2) if settled else None,
    }


def build(forecasts, verified_results, edge_snapshots):
    """Build a derived audit; missing bookmaker capture is NOT zero bookmaker coverage."""
    rows, by_day, coverage = [], {}, {}
    seen = set()
    for shot in sorted(forecasts, key=lambda x: x.get("date", "")):
        if shot.get("status") != "frozen-prekickoff" or not isinstance(shot.get("games"), list):
            continue
        day = shot.get("date")
        if not isinstance(day, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            continue
        edge = edge_snapshots.get(day)
        captured = isinstance(edge, dict) and edge.get("status") in ("compared", "no-comparable-markets")
        price_picks = edge.get("picks", []) if captured else []
        priced = {p.get("fixtureId") for p in price_picks
                  if isinstance(p, dict) and p.get("market") in ("btts", "no_btts")
                  and isinstance(p.get("odds"), (int, float)) and not isinstance(p.get("odds"), bool)
                  and math.isfinite(p["odds"]) and p["odds"] > 1}
        matched = {p.get("fixtureId") for p in price_picks if isinstance(p, dict)}
        day_rows = []
        for fixture in shot["games"]:
            if not isinstance(fixture, dict) or fixture.get("date") != day:
                continue
            fid = fixture.get("id")
            if not isinstance(fid, str) or not fid or fid in seen:
                continue
            markets = (fixture.get("scoreline") or {}).get("markets") or {}
            yes, no = markets.get("btts"), markets.get("no_btts")
            if not valid_probability(yes) or not valid_probability(no):
                continue
            if abs(yes + no - 1) > 0.002:
                continue
            seen.add(fid)
            side = "Yes" if yes >= no else "No"
            chance = max(yes, no)
            result = verified_results.get(fid, {})
            score = result.get("score") if isinstance(result, dict) else None
            parsed = re.fullmatch(r"(\d+)-(\d+)", score) if isinstance(score, str) else None
            correct = None
            if parsed:
                both_scored = int(parsed.group(1)) > 0 and int(parsed.group(2)) > 0
                correct = (side == "Yes") == both_scored
            entry = {
                "date": day, "fixtureId": fid, "division": fixture.get("division"),
                "preferredOutcome": side, "probability": round(chance, 5),
                "probabilityBand": band(chance), "correct": correct,
                "quoted": fid in priced if captured else None,
            }
            day_rows.append(entry)
            rows.append(entry)
        by_day[day] = summarise(day_rows)
        supported = [x for x in day_rows if x["division"] in SUPPORTED]
        matched_supported = [x for x in supported if x["fixtureId"] in matched]
        qualified = [x for x in matched_supported if x["probability"] >= 0.55]
        quoted = [x for x in matched_supported if x["fixtureId"] in priced]
        coverage_pct = round(100 * len(quoted) / len(matched_supported), 2) if matched_supported and captured else None
        low = bool(captured and len(matched_supported) >= 5 and coverage_pct < 25)
        coverage[day] = {
            "captureAvailable": captured,
            "allLeagueForecasts": len(day_rows),
            "supportedLeagueForecasts": len(supported),
            "bookmakerMatchedFixtures": len(matched_supported) if captured else None,
            "qualified55MatchedFixtures": len(qualified) if captured else None,
            "bttsQuotedFixtures": len(quoted) if captured else None,
            "bttsQuotedOutcomes": sum(p.get("market") in ("btts", "no_btts")
                                      for p in price_picks if isinstance(p, dict)) if captured else None,
            "matchedCoveragePct": coverage_pct,
            "lowCoverageWarning": low,
            "warning": ("BTTS quotes cover fewer than 25% of bookmaker-matched fixtures."
                        if low else None),
        }
    settled = [x for x in rows if x["correct"] is not None]
    return {
        "schemaVersion": 1,
        "model": "original frozen experimental Scoreline Model",
        "definition": "Highest original BTTS Yes/No probability per fixture; ties favour Yes.",
        "note": "Forecast accuracy uses verified final scores even without bookmaker prices. No odds, stakes, ROI or profitable-edge conclusions are inferred.",
        "summary": summarise(rows),
        "byOutcome": {s: summarise([x for x in rows if x["preferredOutcome"] == s])
                      for s in ("Yes", "No")},
        "byLeague": {d: summarise([x for x in rows if x["division"] == d])
                     for d in DIVISIONS},
        "byProbabilityBand": {b: summarise([x for x in rows if x["probabilityBand"] == b])
                              for b in BANDS},
        "byDay": by_day,
        "coverageByDay": coverage,
        "mostRecentDay": max(by_day) if by_day else None,
        "settledForecasts": len(settled),
    }


def recalculate(root=ROOT):
    data = root / "data"
    archive = data / "edges"
    forecasts = [json.loads(path.read_text(encoding="utf-8"))
                 for path in sorted((data / "snapshots").glob("????-??-??.json"))]
    verified = json.loads((data / "settlements.json").read_text(encoding="utf-8")) if (data / "settlements.json").exists() else {}
    edge_snapshots = {path.stem: json.loads(path.read_text(encoding="utf-8"))
                      for path in sorted((archive / "snapshots").glob("????-??-??.json"))}
    report = build(forecasts, verified, edge_snapshots)
    target = archive / "btts_performance.json"
    old = json.loads(target.read_text(encoding="utf-8")) if target.exists() else None
    if old == report:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                         encoding="utf-8")
    temporary.replace(target)
    print("BTTS forecast audit:", report["summary"]["graded"], "settled;",
          report["summary"]["pending"], "pending; pricing evaluated separately.")
    return True


if __name__ == "__main__":
    recalculate()
