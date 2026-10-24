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

## Odds & Edge (live)

The **Odds & Edge** tab displays timestamped UK bookmaker prices compared against independently frozen model probabilities. It identifies best observed decimal prices, implied bookmaker probability, theoretical edge and theoretical ROI. These are **not** guaranteed executable prices or betting recommendations. Original forecasts are never trained or altered using odds. The Scoreline Model's probabilities remain uncalibrated; a positive theoretical edge is not proof of profit.

The [Publish Football Odds](../../actions/workflows/football-edges-publish.yml) workflow is triggered automatically after a successful `Daily English Football Predictions` refresh, has a 09:33 UTC daily fallback, and can be manually dispatched. It makes at most one paid collection attempt per UK calendar day, with a **12-credit daily maximum** and **100-credit account reserve**. The four supported betting feeds are Premier League, Championship, League One and League Two. National League forecasts remain available but have no connected odds feed.

Quoted 1X2 and totals markets are batched by league; event-specific BTTS and alternative totals are requested only for verified matching fixtures with confidence thresholds: **60% or greater** for BTTS Yes/No, **70% or greater** for Over/Under 3.5. A request is skipped if the selected outcome is already quoted in the batch data. The daily budget allows at most **four additional single-market requests**, balancing BTTS and goals markets where they qualify, and spends fewer credits when none qualify. No unquoted market is fabricated. The `ODDS_API_KEY` is held only in GitHub Secrets, never browser JavaScript or committed files. Public JSON contains reduced analytical summaries, not raw odds feeds.

A dated immutable archive lives under `data/edges/snapshots/YYYY-MM-DD.json`. `data/edges/latest.json` powers today's tab; `data/edges/usage/YYYY-MM-DD.json` records API spend and blocks repeat paid attempts. `scripts/edge_history.py` grades original quoted prices against verified final scores. Hypothetical performance uses £10 flat stakes on *recorded positive-edge selections*, with ROI, market and probability-band history. Multiple markets on one match are correlated, and exchange commissions are not deducted.

Operational and security details: [Odds integration](docs/odds-integration.md). The Odds API permits analytical UI display but prohibits redistribution as a standalone raw data service: https://the-odds-api.com/terms-and-conditions.html.


## Important distinction between models

- **Established B3.1**: the corrected historical performance through 15 October 2026 is retained in data/b31_historical.json. The original 17 October 2026 issued qualifiers are included in the imported frozen snapshot. This is the actual old model, not an imitation.
- **Experimental Scoreline Model**: the scheduled GitHub script currently calculates **only this independent model**, using its own regularised Poisson expected-goals approach.
- New B3.1 selections are **not yet calculated** in GitHub because the original full B3.1 predictor has not been faithfully ported and tested in a headless run. When a fresh snapshot is generated, its B3.1 status is explicitly 'not-calculated'. Do not present scoreline selections as established B3.1 selections.
- The GitHub scoreline runtime currently emits **raw, uncalibrated probabilities**. The earlier experimental Scoreline Lab calibration has not yet been ported. The model version is saved with each forecast for reliable later analysis.
- Predictions are exploratory research, not evidence of profitable betting.

## Publish the website

In [Settings > Pages](https://github.com/SteveP1111/football-prediction-board/settings/pages), choose:\n- **Source:** GitHub Actions\n- **Save if shown.** The `Publish Football Website` workflow deploys initially on push and again after each successful `Daily English Football Predictions` refresh, including when that refresh commits data using GitHub's bot token.

After a successful `Publish Football Website` deployment, GitHub Pages should serve https://stevep1111.github.io/football-prediction-board/ . Monitor the Pages workflow in repository Actions or Settings > Pages; treat the site as live only once deployment succeeds.

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
