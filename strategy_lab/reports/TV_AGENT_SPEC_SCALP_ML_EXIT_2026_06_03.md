# TV Agent Spec — ML dynamic-exit scalp shadow arm (`shadow_scalp_mlexit_*`) — 2026-06-03

## Why
The fixed +60s scalp exit leaves money on the table: a learned online exit policy beats it by **+$0.90/tr on
the broad lockbox (t=2.29, bootstrap CI [+0.14,+2.21] EXCLUDES 0 — out-of-sample)**, and the oracle best-exit
ceiling is +$18.5/tr so there is real headroom. Model + validation: `EXIT_TIMING_MODEL_2026_06_03.md`. Deploy
as a SHADOW arm that runs the **same entries** as the existing scalp but swaps the fixed exit for the model,
logging both PnLs so we A/B it on identical fires.

⚠️ Shadow only, no capital. The lift is proven on the BROAD universe; on the narrow deployed cell (δ≥5,vwap<0.55)
the lockbox is too thin (n=17) to confirm yet — that's exactly what this shadow arm accumulates.

## Artifacts (provided — load these, do not retrain)
In `strategy_lab/directional/_results/`:
- `ml_exit_model_2026_06_03.json` — native XGBoost booster. Load: `xgboost.Booster(); booster.load_model(path)`.
  (tradingvenue `.venv` already has xgboost? if not, `pip install xgboost` — pure-python inference <2ms.)
- `ml_exit_calibrator_2026_06_03.json` — isotonic calibration as `{"x":[...],"y":[...]}`. Apply with
  `p_cal = numpy.interp(p_raw, x, y)`. **No sklearn dependency.**
- `ml_exit_contract_2026_06_03.json` — feature order, threshold, checkpoints, missing-value defaults. **The
  feature vector MUST be built in this exact order.**

## Entry (unchanged — reuse the existing scalp entry)
Identical to the deployed scalp sleeves: lag-taker fire, `entry_band` per arm (see sleeves below), $25 (or $5
for d3), δ≥5 (or δ≥3), BTC+ETH, fire at the lag-taker offset. **Do not change entry logic** — only the exit.

## Exit policy (the change): ML online HOLD-vs-SELL
Replace `exit_policy=SCALP_EXIT` (fixed +60 / TP0.65 / stop−0.10) with `exit_policy=ML_EXIT`:

Poll the held token's book every ~5s. At each **checkpoint** in `{30,45,60,75,90,120}s` after `fire_us`
(use the poll nearest each checkpoint; `elapsed` is a model feature so exact timing is fine):
1. Build the feature vector (order from the contract):
   - `cur` = bid_vwap to SELL the held `shares` now (L25 bid-walk of held token, 10Hz book).
   - `profit` = `cur − entry_vwap`.
   - `mom` = `cur − cur_at_previous_checkpoint` (first checkpoint: `cur − entry_vwap`).
   - `elapsed` = seconds since `fire_us` (the checkpoint, e.g. 30/45/...).
   - `entry_vwap`, `delta_bps` = from entry.
   - `a_BTC` = 1 if BTC else 0;  `tf_15m` = 1 if 15m else 0.
   - `ps` = physics `speed_abs`, `pd_` = `dist_abs`, `pds` = `d_speed`, `pmar` = `margin` — **physics-at-ENTRY**
     (compute once at `fire_us` via `physics_signal.physics_at` on Chainlink RTDS; reuse for every checkpoint).
     If physics unavailable, substitute the contract `missing_defaults`.
2. `p_raw = booster.predict(DMatrix([features]))`; `p_hold = numpy.interp(p_raw, cal.x, cal.y)`.
3. **If `p_hold < threshold (0.60)` → SELL the held shares on the book now (FAK/IOC, the existing scalp sell
   path).** Else continue to the next checkpoint.
4. If no checkpoint triggers a sell by 120s → **hold to resolution** (no forced late sell).

Reuse the existing scalp sell primitive (bid-walk, FAK). Latency/min_book_events same as the scalp.

## Sleeves to add (shadow, paper_only)
Mirror the firing cells (skip the cells that don't fire). Run BOTH a gated and a control arm so we A/B the ML
exit against the fixed exit on the same fires:

| sleeve_id | asset | tf | δ | $ | entry_band | exit |
|---|---|---|---|---|---|---|
| `shadow_scalp_mlexit_btc_5m_v1` | BTC | 5m | ≥5 | 25 | (0,0.55) | ML_EXIT |
| `shadow_scalp_mlexit_btc_5m_d3_v1` | BTC | 5m | ≥3 | 5 | (0,0.55) | ML_EXIT |
| `shadow_scalp_mlexit_eth_5m_d3_v1` | ETH | 5m | ≥3 | 5 | (0,0.55) | ML_EXIT |
| `shadow_scalp_mlexit_btc_5m_control_v1` | BTC | 5m | ≥5 | 25 | None | ML_EXIT |
| `shadow_scalp_mlexit_btc_5m_d3_control_v1` | BTC | 5m | ≥3 | 5 | None | ML_EXIT |
| `shadow_scalp_mlexit_eth_5m_d3_control_v1` | ETH | 5m | ≥3 | 5 | None | ML_EXIT |

(The control arms — no vwap gate — generate the broad-universe fires where the lift is proven; include them.
15m/eth_5m cells are omitted: they essentially don't fire the `<0.55` gate live. Add them later if desired.)

## Logging (critical — this is an A/B, log both PnLs per fire)
On each `poly_updown_scalp_exit` event for these sleeves add to `data`:
- `exit_type="ml_exit"`, `ml_p_hold` (the calibrated prob that triggered the sell), `ml_exit_dt` (seconds
  from fire to sell, or 999 if held to resolution), `ml_features` (the vector that fired the sell).
- `fixed60_counterfactual_pnl` — what the SAME fire would have paid under the fixed +60s exit (compute the
  +60s bid-sell counterfactual exactly as the existing scalp does). This is the head-to-head we judge on.
- keep the existing `scalp_hold_counterfactual` (hold-to-resolution PnL).
- `model_version="ml_exit_2026_06_03"`.

## Acceptance / verification
1. Unit: feed a synthetic path where bid keeps rising → model holds (p_hold high) → sells late/holds; a path
   that spikes then fades → model sells near the peak. Confirm feature order matches the contract.
2. Unit: physics unavailable → uses `missing_defaults`, still produces a decision.
3. Live canary: confirm `shadow_scalp_mlexit_*` emit `exit_type="ml_exit"` with `ml_p_hold`, `ml_exit_dt`, and
   `fixed60_counterfactual_pnl` populated. Inference adds <5ms.
4. Weekly judge: per sleeve, mean(ml_exit pnl) − mean(fixed60_counterfactual_pnl), bootstrap CI. **Graduation =
   ML beats fixed60 with CI>0 over ≥200 forward fires** (then consider promoting ML_EXIT to the live scalp).

## Risks / notes
- Pure A/B vs the fixed exit on identical fires → zero added directional risk; worst case ML ≈ fixed.
- The model was trained on 10Hz-cached BTC+ETH fires; live books are the same WS-mirror source. Re-verify the
  `cur` (bid-walk) definition matches the cache's `sell_at_bid_partial` ($25/$5 held shares).
- Next model rev: add the cross-feature MICROSTRUCTURE features (mp_skew/imb5/hawkes — AUC 0.78 on price
  movement) which were NOT in this cache and should widen the lift. This v1 uses path+physics features only.

## Source
`EXIT_TIMING_MODEL_2026_06_03.md` (validation), `exit_timing_model_2026_06_03.py`,
`export_ml_exit_model_2026_06_03.py` (artifact builder), cache `scalp_hedge_physics_cache_2026_06_03.parquet`.
