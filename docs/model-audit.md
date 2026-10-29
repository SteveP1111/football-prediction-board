# Phase 1–2 probability audit (experimental scoreline model)

This research compares pre-match probabilities **without changing live forecasts, historical frozen predictions, bookmaker quotations, or the B3.1 archive**.

## Under 3.5 goals

**Under 3.5 wins if the two teams score 0, 1, 2 or 3 goals in total.** Four or more goals loses. It is the exact complement of Over 3.5, so `P(Under 3.5) = 1 - P(Over 3.5)`. We must never use independently fitted probabilities for each side that fail to sum to 100%.

- **Phase 1:** `scripts/phase1_calibration.py` analyses original settled probabilities grouped by model version and league, with Brier score, log loss, and 10 percentage point bands. Where an original Under 3.5 probability was absent but the original Over 3.5 forecast existed, its exact mathematical complement can be analysed, without modifying the frozen record. That arithmetic is not a new retrospective forecast.
- **Phase 2:** `scripts/phase2_compare.py` includes Under 3.5 and Over 3.5 across the original Poisson baseline, venue-strength adjustment, Dixon–Coles, shared-tempo overdispersion, validation-trained calibrated baseline, and simple league-frequency benchmark. It reports Brier score, log loss, calibration gap, comparisons by league, and day-clustered paired intervals against the original model.
- **Probability-first cohorts:** `under35Research` in the output contains prediction cutoffs at 55%, 60%, 65%, 70%, 75% and 80%, plus observed wins/losses, mean forecast, outcome rate, and calibration bands. These are retrospective, unpriced model cohorts, **not settled betting picks**.

To reproduce:

```bash
python3 -m unittest discover -s tests -v
python3 scripts/phase1_calibration.py
python3 scripts/phase2_compare.py
```

Outputs are `data/phase1_calibration.json` and `data/phase2_comparison.json`. The isolated GitHub Actions workflow uploads both reports as a run artifact; it does not commit them to the live-data directory.

## Interpretation safeguards

- The historical backtest is an **experimental replay** using past match results, not the originally frozen live selections. It must never be mixed with the archived positive-edge betting results.
- 2025/26 February–May serves as an earlier calibration/validation interval, while 2026/27 August–October is a subsequent diagnostic holdout. Because the latter period has already been inspected to propose model changes, later iterations must use **new, unseen fixtures** for independent confirmation.
- A simple frequency baseline is included: improved probability scores should also beat a naive league-rate forecast.
- Over/Under 3.5 are mathematically complementary, so apparent improvements to both are one result, not two independent successes.
- The original V1 model is **uncalibrated**. A modelled 70% does not guarantee a true 70% chance.
- Under 3.5 probabilities above an arbitrary threshold are not proof of positive value. **Only timestamped, frozen bookmaker odds** could support a historical theoretical return calculation, subject to executable-price uncertainty.
- National League match forecasts are analysed, but the live Odds API feed covers only the four Football-Data league betting competitions.
- Too-few-observation calibration bins are marked accordingly; do not use them to set automatic gambling rules.
