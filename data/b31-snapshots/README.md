# Frozen B3.1 overlays

Optional official established-model selections, created by the separate exact nightly comparator rather than by the GitHub scoreline model.

Each YYYY-MM-DD.json should have this schema:

{
  "date": "2026-10-18",
  "status": "frozen-prekickoff",
  "capturedAt": "2026-10-17T22:40:00+01:00",
  "model": "B3.1-model-b-lineage",
  "fixtures": [
    {
      "id": "2026-10-18|E0|canonical home team|canonical away team",
      "qualifiers": [
        {"key": "BTTS", "score": 67.42, "likelihood": 61.2, "confidence": 73}
      ]
    }
  ]
}

Source must be the verified original pre-kickoff B3.1 snapshot. Never infer or manufacture an overlay from the experimental Scoreline Model. If the source is missing, omit that day's file. A file should be created only BEFORE fixture kickoff and should remain immutable thereafter. The isolated GitHub Action settles these markets against the final results separately from independent model probabilities.

Division codes: E0 Premier League, E1 Championship, E2 League One, E3 League Two, EC National League.

Team identity keys must match football/scripts/refresh.py canon(name). Never publish personal account data, paid API credentials, betting odds or private raw sources in this public repository.
