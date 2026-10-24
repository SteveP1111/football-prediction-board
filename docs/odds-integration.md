# The Odds API and Football Edge Finder

Audited integration, tested 24 October 2026. Changes are held in the feature branch until approved and merged. The independent forecast generation remains separate. Nothing here is a profitable-bet guarantee.

## Verified facts

- Correct repository: `SteveP1111/football-prediction-board`.
- The repository's `ODDS_API_KEY` secret authenticated to The Odds API. The preflight `/v4/sports/` did not spend credits.
- Active competitions: `soccer_epl`, `soccer_efl_champ`, `soccer_england_league1` and `soccer_england_league2`. National League is not integrated with this bookmaker API. On 24 October 2026 the free provider event-list endpoint was used to verify explicit aliases for the fourteen initially unmatched supported fixtures; all 38 supported fixtures then matched **38/38** by exact league, teams and kick-off time. Existing published odds snapshots are immutable and must not be backfilled; corrected matching takes effect on the next eligible daily collection.
- Free event-list diagnostic: **4 exact matches** against frozen 24 October Premier League forecasts; **9 Championship**, **5 League One**, **6 League Two** (coverage, not paid odds).
- Live bounded EPL request used **4 credits**, from 496 to **492 remaining**. Returned 20 odds events, of which 4 joined a forecast. Result: 26 priced fixture-market combinations, 13 positive theoretical edges. `h2h`, `totals`, `btts` and `alternate_totals` were observed.
- Auditable completed run: https://github.com/SteveP1111/football-prediction-board/actions/runs/40044100044
- Tested 24 October report is in `data/edges/snapshots/2026-10-24T001609Z.json` and `data/edges/latest.json` **only on this development branch**. The branch has an older independent `data/latest.json`; production workflows must always use the current `main` snapshot, NOT its development copy.

## Security and quotas

The key is only provided to explicit `workflow_dispatch` preflight/coverage/collect jobs via GitHub Actions secrets. Pull-request tests never access the key. No scheduled or push-based paid requests remain. The workflow has `contents: read`, and the checkout does not retain credentials. The API client suppresses URLs containing the token from errors and logs.

The collector defaults to **zero-cost preflight**. `--mode collect` is explicitly required for odds. Each standard EPL `h2h,totals` request uses up to two credits for the UK region, while opt-in additional event markets require an explicit extra-market list, an event count limit, a frozen forecast and a corresponding credit budget. The collector checks the remaining quota before requests. Event-market coverage is not guaranteed. API account quotas can reset; never assume the number of remaining credits is fixed.

Provider response data is not stored by the smoke workflow. Optional raw collection with `--save` writes to ignored `private_odds/` outside `data/`; no raw odds are deployed to GitHub Pages. The dated example stores **only reduced match/market summaries** (including bookmaker names and prices), which are publicly readable because this repository is public. Verify any provider licence restrictions before enabling regular public publication.

## Safeguards in `scripts/edge_comparison.py`

- Uses the model's frozen `capturedAt` from `main`, never recomputes probabilities with bookmaker data.
- Matches exact league, both normalised team names and local match date, then requires kick-off difference no greater than 90 minutes.
- Rejects missing/TBC kick-off, duplicate bookmaker events mapping to one fixture, missing/invalid prices, in-play prices, stale updates and old model snapshots.
- 1X2 prices require all three outcomes, so two-way winner markets are not misread as regulation-time three-way markets.
- Supports BTTS Yes/No and 2.5/3.5 Over/Under lines, including available alternative totals. Under 3.5 probability derives from `1 - model Over 3.5`.
- Chooses the highest available decimal price per selection, identifies its bookmaker and how many bookmakers were compared, and preserves the capture timestamp.
- Computes implied probability as `1 / decimal_odds`, theoretical edge as `100 × (model_probability - implied_probability)`, theoretical ROI as `100 × (model_probability × odds - 1)`. These are *not* expected guaranteed profits. Exchange commission, stake limits and execution are excluded.
- Ranks positive edges first; then highest model probability, with edge as a tie-breaker. Never reports a selection with missing bookmaker data as positive edge.

The experimental Scoreline Model is not calibrated. Its estimated chances must not be conflated with the established B3.1 record or treated as verified win probabilities.

## Testing and deployment

`python3 -m unittest discover -s tests -v` tests original forecast behaviour and the new odds module using mocks. The PR workflow also compiles Python scripts and validates the site's inline JavaScript. No tests consume API credits.

The development website adds an **Odds & Edge** tab reading `data/edges/latest.json`. It shows league/market and positive-only filters, model probability, captured bookmaker price, implied probability, percentage-point edge, theoretical ROI and the bookmaker. It hides a report whose date is not the currently shown forecast and defaults to future matches only. If no audited odds exist, it shows an explicit empty state.

To create a new audited comparison, obtain the latest frozen `data/latest.json` from `main` and run the manual collect workflow (when installed on the default branch). Manual requests are restricted to EPL plus a single future matched event's optional BTTS/alternative totals and at most **4 credits**. The earlier smoke workflow does not publish new reports. The production `Publish Football Odds` workflow does so after merge, once per UK day when fresh frozen forecasts and sufficient credits exist.

The new production workflow is designed to run on successful `Daily English Football Predictions` completion, with a 09:33 UTC daily fallback and an optional manual trigger. It preserves immutable day-based previews and a request receipt before billable calls. A second run on the same UK date does not spend additional credits. It recalculates £10 hypothetical settlement results from independent verified score data without overwriting historical odds. Production writes only under `data/edges/` and pages redeploys on successful odds workflow completion. Additional BTTS and 3.5-goal totals are now selected using frozen model confidence: BTTS Yes or No **at least 60%**, Over or Under 3.5 **at least 70%**. The collector first checks all bookmaker quotes from each league-wide 1X2/totals batch, and does not request an outcome already priced. Up to **four individual extra-market calls** are allowed, with an initial balance of two BTTS and two 3.5-goal enquiries where qualified. Fewer calls are made when fewer outcomes qualify. This avoids wasting extra credits on the earliest fixtures.

The hard paid quota is **12 credits per UK day** with at least **100 credits reserved** in the provider account after the planned request set. Four active leagues use at most 8 credits for `h2h,totals`, with up to 4 credits for four *single-market* confidence-selected event requests. Some days cost less because only leagues with frozen upcoming fixtures are requested. Daily requests are not attempted when the frozen model snapshot is stale, unverified or entirely kicked off. Errors result in an immutable daily attempted-request receipt and do not permit automatic recharging. Account allowance and credit reset cadence should be checked periodically against the provider dashboard.

The Odds API's terms updated 31 August 2026 expressly permit public display in analytical websites, storage, and derived calculations; they prohibit repackaging data as a standalone raw feed. Accordingly this project publishes curated per-selection analytical summaries, not raw bookmaker data. See https://the-odds-api.com/terms-and-conditions.html.

Rollout requires successful PR checks and a working main-branch deployment. No retrospective odds are invented; users should interpret uncalibrated theoretical edges cautiously. Exchange quotes may involve commission and stake/liquidity limits.
