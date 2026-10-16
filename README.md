# English Football Prediction Board

A standalone, public English football prediction website hosted with GitHub Pages.

**Website when Pages is enabled:** https://stevep1111.github.io/football-prediction-board/

The site covers the Premier League, Championship, League One, League Two, and National League. It has a natural-language style filter for "top 3 home wins", "best BTTS", "under 2.5", "over 3.5", and "0-0 predictions", plus market filters, frozen daily previews, full-time results and performance history.

## Automated refresh

[Daily English Football Predictions](../../actions/workflows/football-daily.yml) runs automatically twice a day and can be manually dispatched. All dates in data/snapshots/YYYY-MM-DD.json are **immutable**: once issued before kick-off, later scores cannot change their forecast probability. Settlement and grading are published separately.

The Python runner:
1. Retrieves verified prior/current season results for five divisions and current fixtures from Football-Data.co.uk.
2. Uses a single canonical team-name map and rejects score conflicts.
3. Derives an **independent** regularised Poisson scoreline distribution from pre-match historical goal data.
4. Freezes forecasts before kick-off only; never backfills forecasts once the game has begun.
5. Settles finished fixtures against the saved original forecasts.
6. Updates market probability performance (Brier scores), dated history and JSON data used by the website.
7. Commits changes only under data/. Failure to validate a source leaves the last published data in place.

No betting odds, private tokens, personal information or paid API feeds are used as model inputs.

## Important distinction between models

- **Established B3.1**: the corrected historical performance through 15 October 2026 is retained in data/b31_historical.json. The original 17 October 2026 issued qualifiers are included in the imported frozen snapshot. This is the actual old model, not an imitation.
- **Experimental Scoreline Model**: the scheduled GitHub script currently calculates **only this independent model**, using its own regularised Poisson expected-goals approach.
- New B3.1 selections are **not yet calculated** in GitHub because the original full B3.1 predictor has not been faithfully ported and tested in a headless run. When a fresh snapshot is generated, its B3.1 status is explicitly 'not-calculated'. Do not present scoreline selections as established B3.1 selections.
- The GitHub scoreline runtime currently emits **raw, uncalibrated probabilities**. The earlier experimental Scoreline Lab calibration has not yet been ported. The model version is saved with each forecast for reliable later analysis.
- Predictions are exploratory research, not evidence of profitable betting.

## Publish the website

In [Settings > Pages](../../settings/pages), choose:
- **Source:** Deploy from a branch
- **Branch:** main
- **Folder:** /(root)
- **Save**

GitHub Pages should then serve https://stevep1111.github.io/football-prediction-board/ . Check deployment status in repository Actions or Pages before treating that URL as operational.

This repository is **independent of** `nfl-prediction-board`. Copying the source did not change or disable any NFL files, data, or workflows.

## Run tests locally

```bash
python3 -m unittest discover -s tests -v
python3 scripts/refresh.py
python3 -m http.server 8000
```

Open http://localhost:8000/ . The scheduled refresh needs access to Football-Data.co.uk.

## Where everything lives

- index.html: searchable website
- scripts/refresh.py: daily data retrieval, forecasting, freezing, grading and history
- tests/test_forecast.py: model consistency tests
- .github/workflows/football-daily.yml: automatic schedule
- data/latest.json: newest available date's stored forecast or no-data status
- data/snapshots/: permanent daily forecast snapshots
- data/settlements.json: actual final scores and outcomes
- data/performance.json: graded market results and calibration
- data/b31_historical.json: preserved original B3.1 record

The first historical imported preview is 17 October 2026, with 39 matches and 21 B3.1 qualifying fixture-market combinations. Older B3.1 history is retained separately; it is **not** retroactively reconstructed from final results.
