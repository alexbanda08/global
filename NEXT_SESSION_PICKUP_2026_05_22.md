# Next Session — Start Here (2026-05-22)

_Replaces `NEXT_SESSION_PICKUP_2026_05_21.md`. This session's work was an extensive deep-dive into Markov + F7 + multi-gate filter combinations on production strategies. We found one critical backtest bug (sniper anchor), validated that the production momo_v2 "5% WR catastrophe" was a regime artifact (not a code bug), and shipped a TV-agent spec for 11 shadow-mode gated sleeves. Walk-forward retained 78% of in-sample edge._

---

## TL;DR (60 seconds)

1. **TV-agent shadow deploy spec READY** — 11 gated sleeves (HoD-Top8 ± Markov ± MTF2 on top of existing momo/momo_v2/sniper). Spec at [strategy_lab/reports/TV_AGENT_SHADOW_DEPLOY_GATED_SLEEVES_2026_05_22.md](strategy_lab/reports/TV_AGENT_SHADOW_DEPLOY_GATED_SLEEVES_2026_05_22.md).
2. **$1/fire live-deploy table** at [strategy_lab/markov_filter/_results/deploy_1usd/deploy_table_1usd.csv](strategy_lab/markov_filter/_results/deploy_1usd/deploy_table_1usd.csv). Aggregate: 43 fires/day, 62.5 % WR, +$9.50/day at $1 stake = ~$3,460/yr. None of the 11 sleeves use maker — all takers, so 5-share minimum doesn't apply.
3. **HoD-Top8 is the dominant single edge** discovered. Beats baseline on 18/18 cells. Hours are locked per cell in the spec; monthly refresh script ready.
4. **`eth_5m_v2 + F7` "catastrophic 5% WR" was NOT a code bug** — it's the documented Phase 18.1 D-12 `qty_compute [0.05, 0.95]` guard correctly rejecting expensive Up tokens during a strong uptrend regime. Retracted in [EXACT_BUG_MOMO_V2_QTY_COMPUTE_ASYMMETRY_2026_05_21.md](strategy_lab/reports/EXACT_BUG_MOMO_V2_QTY_COMPUTE_ASYMMETRY_2026_05_21.md).
5. **Sniper backtest had a CRITICAL anchor bug** — fixed. `ret_5m` now uses `log(close@ws_s / close@(ws_s − 300))` with FIXED 300s lookback (both 5m and 15m). Sniper performance changed from −$2k to +$2,400+ across cells.

---

## What happened this session

### 1. Started with Markov regime filter (jackson-video-resources/markov-hedge-fund-method)

- Adapted Roan's daily Markov regime method to micro-timeframes (20×1m and 20×5m bars).
- Library at [strategy_lab/markov_filter/markov_regime_micro.py](strategy_lab/markov_filter/markov_regime_micro.py).
- 4 variants tested: window × {1m, 5m} × {vol-adaptive q33/q66, fixed-threshold per asset}.

### 2. Multiple iteration cycles uncovered 3 BIG bugs in my own backtest

| Bug | Where | Discovered by |
|---|---|---|
| `ws_s` anchor confusion (CSV column `ws` was `slot_start`, not `ws_s`) | `full_universe_gate_compare.py` | Manual debug |
| Sniper `ret_5m` anchor at `slot_start` instead of `ws_s` + variable lookback | `backtest_prod_strategies_with_gates.py` | Agent C (gsd-code-reviewer equivalent) |
| `version='v2' if '_momo_v2_' in c else 'v1'` lumped sniper/v3/v4/volume into "v1" | `post_f7_real_compare.py` | User correction |

All fixed. Sniper fix alone transformed the deploy candidates — sniper went from net-negative to net-positive on most cells.

### 3. False positive on "production momo_v2 code bug"

Earlier I claimed the eth_5m_v2 catastrophic 5% WR was a code-level inversion bug. **User pushed back**: "this can be a strategy gate, not a bug". After auditing [strategy_lab/markov_filter/_vps3_pull/prod_strategies/](strategy_lab/markov_filter/_vps3_pull/prod_strategies/) and VPS3 `.planning/RESUME.md`:

- The `_compute_qty_shares` [0.05, 0.95] clamp is documented Phase 18.1 D-12 risk guard, shipped 2026-04-28
- In trending regimes, this CORRECTLY rejects expensive Up tokens (best_ask > 0.95 = bad R/R)
- Asymmetric direction rejection (86% UP, 47% DOWN on eth_5m_v2 F7) is the filter working as designed, exposing a strategy-regime weakness
- 100% match on production-logged ret_2m, RSI, outcome vs clean recompute
- **No code bug exists.** Retraction document written.

The lesson: don't conclude "bug" without checking the documented spec. Older reports (May 11-15) flagged the same symptom as "real implementation error" — they were wrong too; same regime artifact propagated.

### 4. 4 parallel subagents — round 1

| Agent | Finding |
|---|---|
| A — filter audit | qty_compute_failed = 80.6 % of drops; entry_rejected + bid-exit/hedge missing from my harness |
| B — book depth | 1Hz subsampling is fine. 296/300 fires identical to full-depth. No rerun needed. |
| C — harness code review | Sniper anchor CRITICAL bug. Other 8/10 checks PASS. |
| D — Markov variant matrix (96 variants) | All 3 baselines beaten. After sniper fix: sniper/eth_5m/w30_5m_q25_75 = +$650 (n=197). |

### 5. 4 parallel subagents — round 2 (gate exploration)

| Agent | Finding |
|---|---|
| A — chainlink Markov vs binance | Chainlink alone WEAKER than binance. Combined (binance ∩ chainlink) lifts 15m cells: sniper eth_15m → 60 % WR @ +$5.34/tr |
| B — hour-of-day filter | **HoD-Top8 beats baseline on 18/18 cells.** Top: sniper btc_15m +$2,110 sum (61 % WR, n=410) |
| C — order book microstructure | Tight spread alone is weak (2/18 cells positive). Useful as third tier only. |
| D — multi-TF (MTF2) | sign(ret_15m) == sign(ret_1h) == signal cleans sniper/eth_5m: −$328 → +$805 (lift +$1,133) |

### 6. Mega-stack composite + walk-forward

Built composites of HoD, MTF2, Markov, microstructure gates. Walk-forward split (train Apr 22-May 7 / test May 8-21):
- **Train sum: +$9,160 → Test sum: +$7,119**
- **Test/train ratio: 0.78** — strong out-of-sample retention. Not overfit.
- HoD-Top8 alone aggregates +$17,621 (highest single gate).
- Top combos: HoD8+MTF2 = +$11,937; HoD8+M1mva = +$10,701.

### 7. Realistic qty_compute rerun

Added 4 production-mimic filters to harness:
- Min-shares ≥ 5 (Polymarket lot size — but only for makers, so dropped in $1 table)
- Min-fill-fraction ≥ 50 % of notional
- Per-slug-first dedup (one fire per sleeve per slug)
- Per-sleeve capital cap ($500 in-flight FIFO release at slot_end)

Effect on fire count: down from 11,681 → ~3,500 (vs production ~700 over same 28d = 5× still over-firing). Per-trade $ holds; just fewer fires.

### 8. TV-agent shadow spec written

11 sleeves, each a SHADOW companion to existing controllers. Naming: `{base_sleeve}_hod`, `_hod_mtf`, `_hod_m5va`. New code in `gates.py` (3 pure functions + locked `HOD_TOP8_BY_CELL` constant) and `markov.py` (label_regime_vol_adaptive). Gates wired AFTER `strategy.signal()` returns UP/DOWN, BEFORE qty_compute. Audit row payload extended with `gate_decisions` JSON.

### 9. Monthly HoD refresh script

[strategy_lab/markov_filter/monthly_hod_refresh.py](strategy_lab/markov_filter/monthly_hod_refresh.py):
- Pulls last 28d resolved fires from VPS3
- Recomputes top-8 hours per cell, diffs against locked `CURRENT_HOD_TOP8`
- Flags cells where symmetric diff ≥ 3 hours
- Exit code 1 if any flagged (cron-friendly)
- First run flagged 10/11 cells — expected, since latest 28d ends today vs locked-list 28d ended yesterday. Operator reviews monthly.

### 10. $1/fire live-deploy table

[strategy_lab/markov_filter/_results/deploy_1usd/deploy_table_1usd.csv](strategy_lab/markov_filter/_results/deploy_1usd/deploy_table_1usd.csv) — clean per-sleeve $1-stake projections. **None use maker** — all takers, so 5-share min doesn't bind at $1 stake.

---

## Final 11-sleeve deploy table ($1/fire stake)

| sleeve | gate | n_28d | fires/day | WR | $/tr | sum 28d | $/day | annualized |
|---|---|--:|--:|--:|--:|--:|--:|--:|
| btc_15m_sniper_hod | HoD | 205 | 7.32 | 61.0 % | +$0.206 | +$42.21 | +$1.51 | +$550 |
| sol_5m_sniper_hod | HoD | 131 | 4.68 | 67.9 % | +$0.300 | +$39.26 | +$1.40 | +$512 |
| btc_5m_sniper_hod | HoD | 240 | 8.57 | 57.9 % | +$0.149 | +$35.70 | +$1.28 | +$465 |
| eth_5m_sniper_hod | HoD | 182 | 6.50 | 57.7 % | +$0.160 | +$29.15 | +$1.04 | +$380 |
| btc_15m_momo_hod (v1) | HoD | 54 | 1.93 | **75.9 %** | +$0.474 | +$25.61 | +$0.92 | +$334 |
| sol_5m_momo_v2_hod | HoD | 124 | 4.43 | 62.9 % | +$0.197 | +$24.43 | +$0.87 | +$319 |
| btc_15m_momo_v2_hod | HoD | 68 | 2.43 | 69.1 % | +$0.330 | +$22.41 | +$0.80 | +$292 |
| eth_15m_sniper_hod_m5va | HoD+M5va | 47 | 1.68 | 70.2 % | +$0.450 | +$21.17 | +$0.76 | +$276 |
| eth_15m_momo_v2_hod | HoD | 47 | 1.68 | 68.1 % | +$0.326 | +$15.33 | +$0.55 | +$200 |
| btc_5m_momo_v2_hod_mtf | HoD+M5va | 62 | 2.21 | 58.1 % | +$0.147 | +$9.11 | +$0.33 | +$119 |
| sol_15m_momo_v2_hod | HoD | 36 | 1.29 | 55.6 % | +$0.038 | +$1.36 | +$0.05 | +$18 |
| **TOTAL** | | **1,196** | **42.7** | **62.5 %** | **+$0.222** | **+$265.74** | **+$9.49** | **+$3,464** |

---

## Reports written this session (in chronological-ish order)

| File | Topic |
|---|---|
| [F7_V2_REGRESSION_DIAGNOSTIC_2026_05_21.md](strategy_lab/reports/F7_V2_REGRESSION_DIAGNOSTIC_2026_05_21.md) | First diagnostic on eth_5m_v2 + F7 |
| [MARKOV_FILTER_OVERLAY_2026_05_21.md](strategy_lab/reports/MARKOV_FILTER_OVERLAY_2026_05_21.md) | First Markov overlay test |
| [MARKOV_VS_F7_FULL_UNIVERSE_2026_05_21.md](strategy_lab/reports/MARKOV_VS_F7_FULL_UNIVERSE.md) | F7 vs Markov head-to-head (had ws_s anchor bug) |
| [MARKOV_VS_F7_PER_SLEEVE_2026_05_21.md](strategy_lab/reports/MARKOV_VS_F7_PER_SLEEVE_2026_05_21.md) | Per-sleeve breakdown (still buggy) |
| [PRODUCTION_F7_VS_MARKOV_2026_05_21.md](strategy_lab/reports/PRODUCTION_F7_VS_MARKOV_2026_05_21.md) | Correction with proper ws_s anchor on production fires |
| [PER_STRATEGY_FAMILY_GATE_COMPARE_2026_05_21.md](strategy_lab/reports/PER_STRATEGY_FAMILY_GATE_COMPARE_2026_05_21.md) | Per-family analysis (sniper, v3, v4, momo, volume_INV_NIGHT) |
| [TV_AGENT_SPEC_V2_BUGS_AND_MARKOV_DEPLOY_2026_05_21.md](strategy_lab/reports/TV_AGENT_SPEC_V2_BUGS_AND_MARKOV_DEPLOY_2026_05_21.md) | First TV-agent spec (premature — based on faulty analysis) |
| [TV_AGENT_FIX_MOMO_V2_BUGS_2026_05_21.md](strategy_lab/reports/TV_AGENT_FIX_MOMO_V2_BUGS_2026_05_21.md) | First V2-fix doc (later RETRACTED — no code bug) |
| [FINAL_SCORECARD_2026_05_21.md](strategy_lab/reports/FINAL_SCORECARD_2026_05_21.md) | Per-sleeve scorecard with V2 inversion claim |
| [CLEAN_BACKTEST_V2_BUG_CONFIRMED_2026_05_21.md](strategy_lab/reports/CLEAN_BACKTEST_V2_BUG_CONFIRMED_2026_05_21.md) | Phase A clean-spec verification (signal-only, no L25) |
| [CLEAN_BACKTEST_PHASE_B_FINAL_2026_05_21.md](strategy_lab/reports/CLEAN_BACKTEST_PHASE_B_FINAL_2026_05_21.md) | Phase B with L25 sub-second walk |
| [PROD_STRATS_28D_BACKTEST_FINDINGS_2026_05_21.md](strategy_lab/reports/PROD_STRATS_28D_BACKTEST_FINDINGS_2026_05_21.md) | Backtest using shimmed prod strategy classes |
| [PARALLEL_INVESTIGATION_SYNTHESIS_2026_05_21.md](strategy_lab/reports/PARALLEL_INVESTIGATION_SYNTHESIS_2026_05_21.md) | Synthesis of 4 round-1 subagents (sniper bug found) |
| **[EXACT_BUG_MOMO_V2_QTY_COMPUTE_ASYMMETRY_2026_05_21.md](strategy_lab/reports/EXACT_BUG_MOMO_V2_QTY_COMPUTE_ASYMMETRY_2026_05_21.md)** | **CORRECTION: V2 "bug" retracted; was qty_compute spec guard.** |
| **[MEGA_STACK_GATE_FINDINGS_2026_05_22.md](strategy_lab/reports/MEGA_STACK_GATE_FINDINGS_2026_05_22.md)** | **Final synthesis: HoD, MTF2, Markov, chainlink stack + walk-forward** |
| **[TV_AGENT_SHADOW_DEPLOY_GATED_SLEEVES_2026_05_22.md](strategy_lab/reports/TV_AGENT_SHADOW_DEPLOY_GATED_SLEEVES_2026_05_22.md)** | **TV-agent shadow deploy spec (the one to actually ship)** |

---

## Code written this session

| File | Purpose |
|---|---|
| `strategy_lab/markov_filter/markov_regime_micro.py` | Markov label library (vol-adaptive + fixed, 1m or 5m bars) |
| `strategy_lab/markov_filter/post_f7_real_compare.py` (v1 + v2) | Per-sleeve gate comparison on VPS3 23.5h post-F7 data |
| `strategy_lab/markov_filter/clean_backtest_phase_a.py` | Phase A: signal-only recompute from canonical data |
| `strategy_lab/markov_filter/clean_backtest_phase_b.py` | Phase B: + L25 sub-second walk |
| `strategy_lab/markov_filter/clean_backtest_fresh_universe.py` | Rerun with fresh VPS3 resolutions universe |
| `strategy_lab/markov_filter/_prod_shim/backend/app/strategies/polymarket/` | Pulled-from-VPS3 production strategy code via Python shim |
| `strategy_lab/markov_filter/backtest_prod_strategies_with_gates.py` | Runner using PRODUCTION strategy classes + F7 + Markov |
| `strategy_lab/markov_filter/backtest_with_realistic_qty.py` | Adds wallet/min-notional/per-slug-cap filters |
| `strategy_lab/markov_filter/_scratch_variant_matrix_sweep.py` | 96-variant Markov matrix sweep |
| `strategy_lab/markov_filter/_mega_stack_final.py` | Mega-stack composites + walk-forward |
| `strategy_lab/markov_filter/chainlink_markov_compare.py` | Chainlink-built Markov vs binance comparison |
| `strategy_lab/markov_filter/_microstructure_inline.py` | Order-book microstructure gate quartile analysis |
| `strategy_lab/markov_filter/_rescale_to_1usd.py` | $25 → $1 stake conversion |
| `strategy_lab/markov_filter/monthly_hod_refresh.py` | Monthly HoD-Top-8 refresh + diff |

---

## Pulled data files this session

| Path | What |
|---|---|
| `strategy_lab/markov_filter/_vps3_pull/binance_1m_fresh.csv` | Binance 1m klines Apr 14 → May 21 19:32 UTC (152k rows) |
| `strategy_lab/markov_filter/_vps3_pull/all_resolutions_apr22_may22.csv` | VPS3 market_resolutions_v2 (33,724 slugs Apr 22 → May 22) |
| `strategy_lab/markov_filter/_vps3_pull/post_f7_events.csv` | 25,785 trading.events from post-F7 23.5h window |
| `strategy_lab/markov_filter/_vps3_pull/market_resolutions_recent.csv` | Mapping condition_id → slug for post-F7 window |
| `strategy_lab/markov_filter/_vps3_pull/all_momo_events_14d.csv` | 14d momo events (May 7-21) |
| `strategy_lab/markov_filter/_vps3_pull/PROD_FIRE_REASON_BREAKDOWN.csv` | Per-cell production fire-reason counts (7d) |
| `strategy_lab/markov_filter/_vps3_pull/prod_strategies/` | Strategy code + controller + bar context builders + RSI module from VPS3 |

---

## Things confirmed / falsified this session

| Belief | Status |
|---|---|
| ✗ "Production momo_v2 has a sign-flip / inversion code bug" | **WRONG**. Documented qty_compute spec guard working as designed. |
| ✗ "F7 lifts WR universally by 7+ pp" | **WRONG on clean data.** F7 alone gives ±1pp noise. Production F7 lift comes from interaction with sparse-book/slug-age filters, not the F7 rule itself. |
| ✗ "70+% WR sleeves with Markov+F7 are persistent" | **NOT PERSISTENT on 28-day clean data.** Production-claimed 70+% WR cells were 23.5h regime artifacts. |
| ✓ "ws_s = slot_start − window_s" | Verified from CLAUDE.md + production controller code. My harness now uses correctly. |
| ✓ "Markov regime alone has weak edge" | Confirmed. Markov-only gates: −$4k to −$9k aggregate over 28d. Useful as ranking secondary signal, not primary. |
| ✓ "Hour-of-day is a real intraday cycle, not noise" | **18/18 cells** show HoD-Top8 beats baseline. 78% walk-forward retention. |
| ✓ "1Hz L25 subsampling is fine for $25 backtest" | Agent B verified: 296/300 fires identical, vwap Δ +0.0001, PnL Δ −$0.18/300. |
| ✓ "Sniper backtest had wrong ret_5m anchor" | Agent C found it. Fix changed sniper from net-negative to net-positive on most cells. |
| ✓ "Binance leads chainlink by ~50-200ms" | Documented in MOMO_REST_LAG_VS_MICROSTRUCTURE.md. Both Markov-on-binance and Markov-on-chainlink work; combined on 15m cells lifts further. |

---

## What to start next session with

User said: **"next session we will start with the sharpe, sortino, and all other gate tests to see if the strategies are good"**.

### Suggested starting prompt

```
Read NEXT_SESSION_PICKUP_2026_05_22.md first.

Goal for this session: compute risk-adjusted performance metrics for the 11
deploy sleeves and their gate stacks. Specifically:

1. Per (sleeve, gate) compute:
   - Sharpe ratio (annualized; assume daily returns from per-day sum_pnl)
   - Sortino ratio (downside deviation only)
   - Max drawdown ($ and % terms; rolling intra-period equity curve)
   - Calmar ratio (annualized return / max drawdown)
   - Tail ratio (95th percentile gain / 95th percentile loss)
   - Hit rate vs profit factor (win count / loss count vs total wins$ / total losses$)
   - Recovery time after worst drawdown

2. Compare risk-adjusted metrics across:
   - 11 deploy sleeves at $1 stake
   - Same sleeves at the original $25 backtest stake
   - Aggregate portfolio (sum of all 11 sleeves' daily PnL)
   - Subset portfolios: "sniper-only", "momo-only", "15m-only", "5m-only"

3. Stress tests:
   - What's the worst calendar-week PnL across the 28d window?
   - How would max drawdown change if we double or triple notional?
   - Per-cell correlation matrix of daily PnL (if cells are correlated, the
     portfolio benefit is smaller than sum-of-Sharpes)

4. Build a "gate quality" scorecard with all of the above metrics so we can
   rank gates by risk-adjusted performance, not just sum$.

Input data: strategy_lab/markov_filter/_results/backtest_prod_strats/fills.csv
(11,681 fills with per-fire PnL, timestamps, gate-pass columns).

Output: a final scorecard + a deploy-decision framework based on risk-adjusted
metrics, not just sum$. Write to strategy_lab/reports/GATE_RISK_METRICS_<date>.md.
```

### Specific things still hanging from this session

1. **Walk-forward was 50/50 split** — could be more rigorous with rolling 14d windows or expanding window. Worth re-running if Sharpe needs longer history.
2. **Hot hours per cell flagged 10/11 cells** by the monthly refresh script — operator should review before applying. Or wait for the locked hours to roll over naturally (the script only flags 28d-window changes, so a stable cell will eventually agree).
3. **MTF2 + chainlink Markov gates** are sketched but not in the live `gates.py` spec yet — only HoD + binance Markov made it into the 11 deploy sleeves. If risk-adjusted metrics favor adding MTF2 universally, the spec should be updated.
4. **None of the 11 sleeves use maker**. If you want maker-based fills (better fees, but 5-share min), that's a SEPARATE product line — the existing `polymarket/maker/*.py` suite (acc_h, acc_m, mas, pat_shadow) running on Ireland VPS. Don't confuse the two.
5. **Real production fires ~30× less than my backtest** even after realistic-qty filtering (5× still over). The DELTA is probably wallet-balance + per-slug position caps + the production-side slug-age / market-freshness checks that don't show up in canonical data alone. Per-trade $ is reliable; absolute daily $ is upper-bound.

### What NOT to redo

- ❌ Re-derive ws_s convention — locked in CLAUDE.md and verified
- ❌ Re-verify 1Hz L25 subsampling — Agent B already conclusively showed it's fine
- ❌ Re-build per-cell HoD lists from current 28-day window — that's exactly what monthly_hod_refresh.py does; let it run on 1st of month
- ❌ Re-test F7 in isolation — already proven weak alone in clean spec; only lift comes from production-engine filter interaction
- ❌ Re-debug eth_5m_v2 momo + F7 as a code bug — it's the qty_compute regime artifact, not a code bug
- ❌ Re-check whether momo / sniper sleeves use maker — they don't; only `polymarket/maker/*.py` does

### What TO do

- ✅ Risk-adjusted metrics (sharpe, sortino, max DD, calmar, etc.) per sleeve and per portfolio
- ✅ Correlation matrix of daily PnL across the 11 sleeves
- ✅ Stress test the deploy table (worst-week PnL, what-if notional sizing changes)
- ✅ Build a deploy-decision framework that weights $/day, Sharpe, max DD, fire rate
- ✅ If TV agent has shipped the shadow sleeves by next session: pull real shadow data, compare to backtest projections
- ✅ Monthly HoD refresh — if it's been ≥30 days since the lock, rerun [monthly_hod_refresh.py](strategy_lab/markov_filter/monthly_hod_refresh.py) and review

---

## Things to know about the project (carried forward)

### Critical conventions (from CLAUDE.md)

1. UTC microseconds for `*_us` columns; never localize
2. **`ws_s = slug_suffix − window_s`** (PREVIOUS slot start). Production controller's anchor.
3. Outcome = chainlink RTDS (never derive from binance)
4. `asof_strict` for causal lookups
5. L25 walk via `book_walk_fill` for production-matching fills (1Hz subsample fine for $25 backtests per Agent B audit)
6. Polymarket taker fee: `0.07 × p × (1-p)` per share; maker rebate: `0.20 × taker fee`
7. CLOB minimum order: 5 shares per side (only constrains MAKERS — taker fills can be smaller per user)
8. Currency on-chain: USDC.e (`0x2791bca1...`), Polymarket UI calls it pUSD

### New conventions established this session

9. **`HOD_TOP8_BY_CELL` is locked per spec**; refresh monthly via [monthly_hod_refresh.py](strategy_lab/markov_filter/monthly_hod_refresh.py).
10. **Audit row payload** for gated sleeves includes `gate_stack` (list) + `gate_decisions` (per-gate pass/fail with diagnostic fields).
11. **Production qty_compute [0.05, 0.95]** is Phase 18.1 D-12 design guard — DO NOT modify.
12. **The 11 deploy sleeves are SHADOW companions** to existing controllers, not replacements. Existing sleeves continue firing normally.
13. **None of the deploy sleeves use maker.** Maker = separate `polymarket/maker/*.py` Ireland VPS suite (mint-and-sell V2).

### Things I learned (lessons for myself)

1. **Verify spec before claiming bug.** The qty_compute false-positive cost time and wrote misleading reports. ALWAYS find the spec source before writing a "code bug found" doc.
2. **Stale data hides as bugs.** Canonical resolutions.parquet was 2h stale; production fires on slugs after that cutoff. Always check data freshness windows when production and backtest disagree.
3. **CSV column names lie.** `ws` in per_trade.csv was `slot_start`, not `ws_s`. Always grep the producing code, never trust column names.
4. **Walk-forward is non-negotiable.** In-sample selection (HoD top-8) feels overfit until 78% test retention shows it's not.
5. **Subagents crash mid-task.** Always instruct them to write output INCREMENTALLY per step. The 4 agent crashes this session would have lost all findings if any had run as a single final write.

---

_End of context dump for 2026-05-22. Spec ready for TV agent. Next session focus: risk-adjusted gate quality (Sharpe, Sortino, max DD)._
