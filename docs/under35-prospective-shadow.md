# Under 3.5: prospective probability validation

The live site already supported Under 3.5 as a scored market, query shortcut and bookmaker-market filter. This change makes it prominent and adds a **separate forward-only research stream** for testing the previously validated temperature-calibrated model against the original forecasts.

## What runs

After `scripts/refresh.py` has issued the day's original immutable `data/snapshots/YYYY-MM-DD.json`, `scripts/shadow_under35.py`:

1. Reads the **already-frozen** V1 probabilities. It never fits or recalculates V1.
2. For games with a known local kickoff that is still in the future, uses the locked validation-only over-3.5 temperature of **1.2** and computes `P(shadow Under 3.5) = 1 - temperature_scale(P(original Over 3.5), 1.2)`.
3. Saves the original and calibrated Under 3.5 values together, before kickoff, to `data/shadow_under35/snapshots/YYYY-MM-DD.json`; records timestamps and the source-snapshot SHA-256.
4. **Never rewrites an existing shadow snapshot**, and never creates one for earlier dates. Prospective minimum date: **30 October 2026**, subject to deployment and an eligible pre-kickoff refresh.
5. Later grades both probabilities for *the same match* against the final verified score in `data/settlements.json`. The mutable `data/shadow_under35/performance.json` reports calibration gap, Brier score, log loss, per-league results, and probability-first cohorts (55, 60, 65, 70, 75, 80%).
6. Once at least 30 matches over five dates have settled, reports an **exploratory paired match-day bootstrap** interval for the difference in Brier score.

The dashboard displays an Under 3.5 watchlist ordered by the original uncalibrated probability, and a distinct forward-performance panel. The Odds & Edge section continues to sort by **original model probability first**, with edge only breaking ties, and now has a direct Under 3.5 filter shortcut.

## What this does NOT do

- It does **not** modify `refresh.py`, original frozen forecasts, previously archived bookie quotes or settled priced selections.
- It does **not** replace any live probability with the calibrated shadow probability.
- It does **not** use bookmaker odds as forecast inputs, fabricate missing Under 3.5 bookmaker markets, or assign profit/ROI to unpriced predictions.
- It does **not** backfill previous days with retrospectively generated model projections.
- A shadow at 70% is **not guaranteed** to win seven games out of ten. These probabilities remain experimental.

The calibration temperature (1.2) comes from the earlier **February–May 2026 validation interval**. The historical August–October 2026 model comparisons were already inspected; they are **not a fresh independent holdout**. New games collected after this implementation are the actual prospective evaluation sample.

## Interpretation and promotion

Retain live V1 unchanged while gathering at least 100 independently frozen and settled prospective Under 3.5 fixtures. Before contemplating promotion, inspect Brier and log loss, calibration by league, match-day clustered confidence intervals, stability over successive months, and separate probability-first cohorts. Even 100 matches may be insufficient for a statistically clear improvement; **do not auto-promote** on a sample-size trigger. A promotion requires an explicit separate code change and review.

Verify locally with:

```bash
python3 -m unittest discover -s tests -v
node tests/test_board_queries.js
python3 scripts/shadow_under35.py
```

The first two commands need no external services; the third reads local frozen and settled data and produces only dedicated shadow output. The daily GitHub Action automatically runs this after the existing verified-results refresh once deployed to `main`.
