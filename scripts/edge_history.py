#!/usr/bin/env python3
"""Settle immutable bookmaker edge snapshots against verified football final results.

£10 hypothetical flat stake; only recorded positive-edge selections are
counted as model qualifiers in the primary P/L and ROI metrics. No bet placed.
Original odds, model probabilities and fixture outcomes are never rewritten.
"""
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EDGE = ROOT / "data" / "edges"
DAILY = EDGE / "snapshots"
STAKE_GBP = 10.0


def read_json(path, fallback):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else fallback


def band(prob):
    pct = float(prob) * 100
    if pct < 50:
        return "Under 50%"
    if pct < 60:
        return "50–59.9%"
    if pct < 70:
        return "60–69.9%"
    if pct < 80:
        return "70–79.9%"
    return "80%+"


def grade_pick(pick, final):
    """Requires a verified, settled score and a quoted decimal price."""
    score = final.get("score")
    if not isinstance(score, str):
        return None
    parts = score.split("-")
    if len(parts) != 2 or any(not p.isdigit() for p in parts):
        return None
    h, a = (int(x) for x in parts)
    if h < 0 or a < 0:
        return None
    market = pick["market"]
    outcomes = {
        "home_win": h > a, "draw": h == a, "away_win": h < a,
        "btts": h > 0 and a > 0, "no_btts": h == 0 or a == 0,
        "over25": h + a >= 3, "under25": h + a <= 2,
        "over35": h + a >= 4, "under35": h + a <= 3,
    }
    if market not in outcomes:
        return None
    odd = pick.get("odds")
    prob = pick.get("modelProbability")
    if (isinstance(odd, bool) or not isinstance(odd, (int, float)) or
            not math.isfinite(odd) or odd <= 1 or
            isinstance(prob, bool) or not isinstance(prob, (int, float)) or
            not math.isfinite(prob) or not 0 <= prob <= 1):
        return None
    won = outcomes[market]
    return {
        "date": pick["date"], "fixtureId": pick["fixtureId"],
        "home": pick["home"], "away": pick["away"], "market": market,
        "marketLabel": pick.get("marketLabel", market),
        "modelProbability": round(prob, 5), "probabilityBand": band(prob),
        "edgePp": pick["edgePp"], "positiveEdge": pick["positiveEdge"],
        "bookmaker": pick["bookmaker"], "odds": odd,
        "stakeGbp": STAKE_GBP, "profitGbp": round(STAKE_GBP * (odd - 1) if won else -STAKE_GBP, 2),
        "outcome": "Win" if won else "Loss", "finalScore": score,
    }


def summarize(items):
    def result(rows):
        n = len(rows)
        wins = sum(p["outcome"] == "Win" for p in rows)
        profit = round(sum(p["profitGbp"] for p in rows), 2)
        stake = STAKE_GBP * n
        return {
            "selections": n, "wins": wins, "losses": n - wins,
            "hitRatePct": round(100 * wins / n, 2) if n else None,
            "stakeGbp": round(stake, 2), "profitGbp": profit,
            "roiPct": round(100 * profit / stake, 2) if stake else None,
        }

    positive = [p for p in items if p["positiveEdge"]]
    confident = [p for p in positive if p["modelProbability"] >= .6]
    markets = sorted({p["market"] for p in positive})
    bands = ["Under 50%", "50–59.9%", "60–69.9%", "70–79.9%", "80%+"]
    daily = sorted({p["date"] for p in items})
    return {
        "stakePerPickGbp": STAKE_GBP,
        "primaryDefinition": "Recorded positive theoretical-edge selections only; £10 flat hypothetical stakes.",
        "allQuotedMarkets": result(items),
        "positiveEdges": result(positive),
        "positiveEdges60Plus": result(confident),
        "byMarket": {m: result([p for p in positive if p["market"] == m]) for m in markets},
        "byProbabilityBand": {b: result([p for p in positive if p["probabilityBand"] == b]) for b in bands},
        "byDay": {d: result([p for p in positive if p["date"] == d]) for d in daily},
    }


def build(snapshots, verified_results):
    records = {}
    pending = 0
    forecast_count = 0
    dates = []
    for shot in sorted(snapshots, key=lambda x: x.get("forecastDate", "")):
        date = shot.get("forecastDate")
        if (not isinstance(date, str) or not isinstance(shot.get("picks"), list) or
                shot.get("schemaVersion") != 1 or shot.get("status") not in ("compared", "no-comparable-markets")):
            raise ValueError("Malformed stored edge snapshot")
        dates.append(date)
        for pick in shot["picks"]:
            forecast_count += 1
            if pick.get("date") != date:
                raise ValueError("Stored pick does not belong to the saved forecast date")
            key = str(pick.get("fixtureId")) + "|" + str(pick.get("market"))
            if key in records:
                raise ValueError("Duplicate stored edge fixture/market; refusing to double count")
            final = verified_results.get(pick.get("fixtureId"))
            graded = grade_pick(pick, final) if isinstance(final, dict) else None
            if graded:
                records[key] = graded
            else:
                pending += 1
    rows = sorted(records.values(), key=lambda p: (p["date"], p["fixtureId"], p["market"]))
    return {
        "schemaVersion": 1, "updatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "snapshotDays": sorted(dates), "recordedSelections": forecast_count,
        "gradedSelections": len(rows), "pendingSelections": pending,
        "summary": summarize(rows), "rows": rows,
        "disclaimer": "Hypothetical £10 flat stakes; not actual bets. Exchange commission, limits and unavailable quoted prices are not deducted. Only settled records count.",
    }


def recalculate(root=ROOT):
    edge = root / "data" / "edges"
    settlements_path = root / "data" / "settlements.json"
    result = read_json(settlements_path, {})
    snapshots = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((edge / "snapshots").glob("????-??-??.json"))
    ]
    history = build(snapshots, result)
    summary = {key: value for key, value in history.items() if key != "rows"}
    written = False
    for name, document in (("settlements.json", history), ("performance.json", summary)):
        file = edge / name
        # Ignore generated timestamp changes when content is otherwise identical.
        prior = read_json(file, {})
        if prior:
            prior = dict(prior)
            prior.pop("updatedAtUtc", None)
            compare = dict(document)
            compare.pop("updatedAtUtc", None)
            if prior == compare:
                continue
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps(document, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                        encoding="utf-8")
        written = True
    primary = history["summary"]["positiveEdges"]
    print("Edge history:", len(snapshots), "dated snapshots;",
          history["gradedSelections"], "graded selections;",
          history["pendingSelections"], "pending;",
          "£10 hypothetical positive-edge P/L: £" + str(primary["profitGbp"]))
    return written


if __name__ == "__main__":
    recalculate()
