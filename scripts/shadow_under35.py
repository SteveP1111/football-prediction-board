#!/usr/bin/env python3
"""Prospective, immutable Under-3.5 calibration shadow. Live V1 forecasts are never modified.

This script runs AFTER scripts/refresh.py freezes the original daily predictions.
It records a separately timestamped, pre-kickoff comparison and later grades
it using only verified results already held in data/settlements.json.
"""
import hashlib
import json
import math
import random
import re
from collections import defaultdict
from datetime import datetime, date
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
LONDON = ZoneInfo("Europe/London")
START_DATE = date(2026, 10, 30)
CONFIG = {
    "schemaVersion": 1,
    "experiment": "UNDER35_PROSPECTIVE_V1_V4_TEMP_20261029",
    "liveModel": "INDEPENDENT_SCORELINE_V1_GITHUB",
    "shadowModel": "V4_VALIDATION_TEMPERATURE_U35",
    "calibrationOutcome": "over35",
    "over35Temperature": 1.2,
    "fittedOn": "2026-02-01 to 2026-05-31 (2025/26 validation only)",
    "prospectiveStart": START_DATE.isoformat(),
}
THRESHOLDS = (0.55, 0.60, 0.65, 0.70, 0.75, 0.80)


def temperature_scale(p, temperature):
    """Same log-odds temperature transformation as the Phase 2 validation."""
    if not (isinstance(p, (int, float)) and not isinstance(p, bool)
            and math.isfinite(p) and 0 <= p <= 1):
        raise ValueError("Invalid original market probability")
    if not (math.isfinite(temperature) and temperature > 0):
        raise ValueError("Temperature must be finite and positive")
    eps = 1e-6
    value = min(1 - eps, max(eps, p))
    logit = math.log(value / (1 - value)) / temperature
    return 1 / (1 + math.exp(-logit))


def time_from_iso(value):
    if not isinstance(value, str):
        raise ValueError("Missing capturedAt timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Forecast capture timestamps must include a time zone")
    return parsed


def immutable_shadow(snapshot, now, sha256):
    """Generate sidecar only for fixtures demonstrably before kickoff at BOTH captures."""
    stamp = time_from_iso(snapshot.get("capturedAt"))
    day = date.fromisoformat(snapshot["date"])
    if day < START_DATE or day != now.astimezone(LONDON).date():
        return None
    if snapshot.get("model") != CONFIG["liveModel"]:
        raise ValueError("Unexpected source model; refusing to compare model versions")
    if stamp > now:
        raise ValueError("Original snapshot is timestamped in the future")
    retained = []
    skipped = defaultdict(int)
    seen = set()
    for game in snapshot.get("games", []):
        fid = game.get("id")
        if not fid or fid in seen or game.get("date") != day.isoformat():
            raise ValueError("Invalid or duplicate frozen fixture ID")
        seen.add(fid)
        clock = str(game.get("kickoff") or "")
        if not re.fullmatch(r"\d{1,2}:\d{2}", clock):
            skipped["unknown-kickoff"] += 1
            continue
        hour, minute = map(int, clock.split(":"))
        if hour >= 24 or minute >= 60:
            skipped["invalid-kickoff"] += 1
            continue
        kickoff = datetime(day.year, day.month, day.day, hour, minute, tzinfo=LONDON)
        if stamp >= kickoff or now >= kickoff:
            skipped["not-prospectively-eligible"] += 1
            continue
        markets = (game.get("scoreline") or {}).get("markets") or {}
        original_over = markets.get("over35")
        original_under = markets.get("under35")
        if not (isinstance(original_over, (int, float)) and not isinstance(original_over, bool)
                and isinstance(original_under, (int, float)) and not isinstance(original_under, bool)
                and math.isfinite(original_over) and math.isfinite(original_under)
                and 0 <= original_over <= 1 and 0 <= original_under <= 1
                and abs(original_under + original_over - 1) <= 0.00005):
            raise ValueError("Missing/inconsistent frozen Under/Over 3.5 probabilities")
        adjusted_over = temperature_scale(original_over, CONFIG["over35Temperature"])
        retained.append({
            "fixtureId": fid,
            "date": day.isoformat(),
            "division": game.get("division"),
            "home": game.get("home"),
            "away": game.get("away"),
            "kickoffLocal": kickoff.isoformat(),
            "originalUnder35": original_under,
            "shadowUnder35": round(1 - adjusted_over, 8),
        })
    if not retained:
        return None
    return {
        "schemaVersion": 1, "experiment": CONFIG["experiment"],
        "sourceSnapshotDate": day.isoformat(),
        "originalCapturedAt": stamp.isoformat(),
        "shadowCapturedAt": now.isoformat(),
        "sourceSnapshotSha256": sha256,
        "calibration": CONFIG,
        "status": "frozen-prekickoff",
        "skippedFixtures": dict(skipped),
        "games": retained,
        "disclaimer": "Prospective experimental model comparison; no bookmaker prices, bets or model promotion.",
    }


def validate_shadow_provenance(shot, source_raw):
    """Fail closed if shadow was not captured before kickoff or source snapshot changed."""
    if shot.get("calibration") != CONFIG:
        raise ValueError("Shadow calibration version mismatch")
    if shot.get("sourceSnapshotSha256") != hashlib.sha256(source_raw).hexdigest():
        raise ValueError("Original immutable forecast hash differs from frozen shadow provenance")
    source=json.loads(source_raw)
    if source.get("date") != shot.get("sourceSnapshotDate") or source.get("model") != CONFIG["liveModel"]:
        raise ValueError("Shadow/source forecast date or model mismatch")
    original=time_from_iso(shot.get("originalCapturedAt"))
    shadow=time_from_iso(shot.get("shadowCapturedAt"))
    if original > shadow:
        raise ValueError("Shadow timestamp precedes original forecast")
    if abs((original - time_from_iso(source.get("capturedAt"))).total_seconds()) > 1:
        raise ValueError("Original capture timestamp no longer matches the frozen source")
    games={g["id"]:g for g in source.get("games",[])}
    for row in shot.get("games",[]):
        game=games.get(row.get("fixtureId"))
        if game is None:
            raise ValueError("Frozen shadow fixture is missing from original forecast")
        kickoff=time_from_iso(row.get("kickoffLocal"))
        if original >= kickoff or shadow >= kickoff:
            raise ValueError("Shadow contains a retrospective or non-prekickoff selection")
        p=(game.get("scoreline") or {}).get("markets") or {}
        if p.get("under35") != row.get("originalUnder35"):
            raise ValueError("Original Under 3.5 probability changed since shadow capture")
        if not math.isclose(
                row["shadowUnder35"],
                1-temperature_scale(p["over35"],CONFIG["over35Temperature"]),
                abs_tol=1e-8,rel_tol=0):
            raise ValueError("Shadow calibration differs from locked pre-kickoff transformation")


def verified_under35(result, expected_date):
    if not isinstance(result, dict) or result.get("date") != expected_date:
        return None
    value = result.get("score")
    if not isinstance(value, str) or not re.fullmatch(r"\d+-\d+", value):
        return None
    home, away = (int(n) for n in value.split("-"))
    if home < 0 or away < 0:
        return None
    # Ensure independently settled market outcome agrees with the verified score.
    outcome = (home + away < 4)
    reported = (result.get("outcomes") or {}).get("under35")
    if reported is not None and reported is not outcome:
        raise ValueError("Conflicting Under 3.5 result for "+str(result.get("date")))
    return int(outcome)


def metrics(rows, field):
    if not rows:
        return {"n": 0, "wins": 0, "strikeRatePct": None, "meanProbabilityPct": None,
                "calibrationGapPp": None, "brier": None, "logLoss": None}
    n = len(rows)
    wins = sum(r["won"] for r in rows)
    avg = sum(r[field] for r in rows) / n
    eps = 1e-12
    return {
        "n": n,
        "wins": wins,
        "strikeRatePct": round(100*wins/n, 2),
        "meanProbabilityPct": round(100*avg, 2),
        "calibrationGapPp": round(100*(wins/n - avg), 2),
        "brier": round(sum((r[field]-r["won"])**2 for r in rows)/n, 6),
        "logLoss": round(-sum(r["won"]*math.log(max(eps,r[field]))
                  + (1-r["won"])*math.log(max(eps,1-r[field])) for r in rows)/n, 6),
    }


def paired_day_interval(rows, samples=1200):
    if len(rows)<30 or len({r["date"] for r in rows})<5:
        return {"status":"insufficient-data", "minFixtures":30,"minMatchDays":5}
    days=defaultdict(list)
    for r in rows:
        delta=(r["shadowUnder35"]-r["won"])**2 - (r["originalUnder35"]-r["won"])**2
        days[r["date"]].append(delta)
    values=[days[d] for d in sorted(days)]
    rng=random.Random(20261029)
    differences=[]
    for _ in range(samples):
        selected=[values[rng.randrange(len(values))] for _ in values]
        differences.append(sum(sum(group) for group in selected)/sum(len(group) for group in selected))
    differences.sort()
    point=sum(sum(group) for group in values)/sum(len(group) for group in values)
    return {
        "status":"exploratory",
        "v4MinusV1Brier":round(point,6),
        "dateClusterBootstrap95":[round(differences[int(samples*0.025)],6),
                                  round(differences[int(samples*0.975)],6)],
        "explanation":"Negative favours shadow V4. Repeated matches and exploratory monitoring limit certainty.",
    }


def compare(snapshots, settlements):
    rows = []
    recorded = 0
    pending = 0
    dates = []
    seen = set()
    for shot in sorted(snapshots, key=lambda x:x["sourceSnapshotDate"]):
        if shot.get("schemaVersion")!=1 or shot.get("experiment")!=CONFIG["experiment"]:
            raise ValueError("Incompatible shadow snapshot")
        dates.append(shot["sourceSnapshotDate"])
        if shot["sourceSnapshotDate"]<START_DATE.isoformat():
            raise ValueError("Retroactively created shadow snapshot is prohibited")
        for game in shot["games"]:
            fid=game["fixtureId"]
            if fid in seen:
                raise ValueError("Duplicate prospective frozen fixture")
            seen.add(fid)
            recorded+=1
            y=verified_under35(settlements.get(fid), game["date"])
            if y is None:
                pending+=1
                continue
            rows.append({**game, "won":y})
    model_fields={"V1 original":"originalUnder35", "V4 calibrated shadow":"shadowUnder35"}
    return {
        "schemaVersion":1,
        "experiment":CONFIG["experiment"],
        "calibration":CONFIG,
        "firstFreezeDate":min(dates) if dates else None,
        "lastFreezeDate":max(dates) if dates else None,
        "snapshotDays":len(dates),
        "frozenFixtures":recorded,
        "settledFixtures":len(rows),
        "pendingFixtures":pending,
        "status":"collecting-prospective-evidence" if len(rows)<100 else "descriptive-comparison-available",
        "models":{label:metrics(rows,field) for label,field in model_fields.items()},
        "byDivision":{div:{name:metrics([r for r in rows if r["division"]==div],field)
                           for name,field in model_fields.items()}
                      for div in sorted({r["division"] for r in rows})},
        "byThreshold":{f"{int(threshold*100)}%":{
            name:metrics([r for r in rows if r[field]>=threshold],field)
            for name,field in model_fields.items()} for threshold in THRESHOLDS},
        "pairedBrierDelta":paired_day_interval(rows),
        "disclaimer":"Only original pre-kickoff forecasts and separately frozen pre-kickoff shadow estimates are compared. No executable bookmaker odds or estimated betting return. Do not auto-promote V4.",
    }


def run(root=ROOT, now=None):
    now = now or datetime.now(LONDON)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must include an explicit time zone")
    today=now.astimezone(LONDON).date().isoformat()
    source=root/"data"/"snapshots"/(today+".json")
    folder=root/"data"/"shadow_under35"/"snapshots"
    folder.mkdir(parents=True,exist_ok=True)
    frozen=folder/(today+".json")
    if source.exists() and not frozen.exists():
        raw=source.read_bytes()
        original=json.loads(raw)
        shot=immutable_shadow(original,now,hashlib.sha256(raw).hexdigest())
        if shot is not None:
            frozen.write_text(json.dumps(shot,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    shots=[]
    for file in sorted(folder.glob("????-??-??.json")):
        shot=json.loads(file.read_text(encoding="utf-8"))
        original=root/"data"/"snapshots"/(file.name)
        if not original.exists():
            raise ValueError("Frozen original forecast missing for "+file.name)
        validate_shadow_provenance(shot,original.read_bytes())
        shots.append(shot)
    results_path=root/"data"/"settlements.json"
    results=json.loads(results_path.read_text(encoding="utf-8")) if results_path.exists() else {}
    report=compare(shots, results)
    target=root/"data"/"shadow_under35"/"performance.json"
    prior=json.loads(target.read_text(encoding="utf-8")) if target.exists() else None
    if report!=prior:
        target.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print("Under 3.5 prospective shadow:",report["frozenFixtures"],"frozen;",report["settledFixtures"],"settled;",report["pendingFixtures"],"pending")
    return report


if __name__=="__main__":
    run()
