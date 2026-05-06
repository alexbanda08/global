# NEXT SESSION — Start Here

**Last update:** 2026-05-05 18:45 UTC (V4 subset hierarchy bug deep-dive added)
**Replaces previous:** 2026-05-04 21:00 UTC version (kept for ref; new findings since merged)

---

## In one sentence

**SOL V3 fix IS deployed (V3/V3.1/V3.2/V3.3/V4 all firing); SOL V3 family appears INVERTED (89% inverse hit, n=18 — but only ~9 distinct markets ⇒ correlation-adjusted p≈0.5–2%, not the 0.07% I first claimed). BTC V4 emerging as winner (73.9%, n=23). V4 SUBSET HIERARCHY BUG IS REAL — root cause = independent per-controller `fetch_close_asof` calls at bar boundaries (race condition); fix = shared aux cache (Path A). Meta-classifier with Kronos REJECTED. Live launch HAS NOT FIRED.**

---

## State of the world (TL;DR)

| Thing | Status |
|---|---|
| **Backtest framework** — production-faithful (95-100% dir match) | ✅ DONE 2026-05-04 |
| **Top-5 sleeve selection + per-sleeve SL/TP** | ✅ DONE — see `LIVE_LAUNCH_TOP5_2026_05_04.md` + `TOP5_STOPS_OPTIMIZATION_2026_05_04.md` |
| **SOL V3 fix spec + V3.3 A/B sleeve** | ✅ READY for TV agent — see `SOL_V3_FIX_SPEC_2026_05_04.md` |
| **Anti-edge inverse sleeves (NEW)** | ✅ SPEC READY for TV agent — see `TV_AGENT_INVERSE_SLEEVES_IMPLEMENTATION.md` |
| **Combined V3 + Phase 7 UNION (NEW)** | ✅ ANALYSIS DONE — needs OOS validation + live signal pipeline build — see `COMBINED_V3_PHASE7.md` |
| **Meta-classifier with Kronos** | ❌ REJECTED (Kronos importance = 0, V3 alone wins) — see `META_CLASSIFIER_FULL_REPORT.md` |
| **Live launch (5 sleeves at $1)** | 🔴 NOT FIRED — 0 live trades observed across 10,378 events. Operator clarification needed. |
| **Phase 8 (residual IC)** | 🔵 deferred — UNION strategy makes this lower priority |
| **Phase 9 (trade flow imbalance)** | 🔵 NOT STARTED |
| **Rolling 14-day quantile** (production parity) | 🔵 NOT STARTED — current backtest uses fixed train fit |

---

## What's NEW since 2026-05-04 21:00 UTC

### 0a. ⭐ V4 SUBSET HIERARCHY BUG — root cause identified (2026-05-05 deep-dive § 8)

**Finding:** V4 ∩ V3 = 50% on SOL and 67% on ETH (should be 100% by design).

**Root cause:** 5 separate `StrategyController` instances (one per variant: v3/v3_1/v3_2/v3_3/v4) each call `fetch_close_asof(symbol_id, "1MIN", ws_s - 900, ...)` INDEPENDENTLY in their own `_compute_aux` methods (PROD code lines 776 and 813). At 5min bar boundaries the just-ingested 1m bar may or may not be in the database when each variant's call lands → divergent `ret_15m` → divergent multi-horizon AND filter outcome → variants diverge on the SAME window.

**Where:** `data/v4/refresh_2026_05_02/polymarket_updown_PROD_2026_05_05.py`
- Lines 776–801: V3 base MH fetch
- Lines 813–853: V3.1/V3.2/V3.3/V4 MH fetch
- Lines 887, 962–971: per-controller `_threshold_cache` (no cross-controller sharing)

**Consequences:**
- V4 ⊆ V3 contract VIOLATED ~50% of the time on SOL (smallest absolute returns most jitter-sensitive).
- A/B testing between variants is invalid — divergent fires aren't due to filter logic, they're due to timing.
- Confidence intervals on per-variant hit rates are too narrow — within-market correlation isn't fully accounted for.
- SOL inversion p-value claim weakens from 0.07% → ~0.5–2% after correlation adjustment.

**Fix (Path A — preferred):** add `SharedAuxCache` keyed by `(symbol, tf, ws_s)` shared across all 5 controllers. Compute `btc_now`/`ret_15m`/`ret_1h`/threshold ONCE per window. All variants read from cache.

**Full deep-dive:** `strategy_lab/reports/SOL_V3_FAMILY_DEEP_DIVE_2026_05_05.md` § 8 (8.1–8.8).

### 0b. ⭐⭐⭐ SOL V3-family appears INVERTED — but with weaker stats than first claimed

SOL V3 fix successfully deployed — all 5 variants fire (V3, V3.1, V3.2, V3.3, V4). **But forward direction is WRONG:**

| SOL Variant | n | Forward hit% | Inverse hit% | Inverse PnL ($1 stake) |
|---|---:|---:|---:|---:|
| v3 | 2 | 0% | **100%** | +$2.05 |
| v3_1 | 2 | 0% | **100%** | +$2.03 |
| v3_2 | 9 | 22% | **78%** | +$5.28 |
| v3_3 | 3 | 0% | **100%** | +$3.05 |
| v4 | 2 | 0% | **100%** | +$2.02 |
| **Total** | **18** | **11.1%** | **88.9%** | **+$14.43** |

P(≥16 of 18 | p=0.5) = 0.07% — **statistically significant despite small sample**.

This is consistent with prior `sol_5m_sniper` inversion (60.2% inverse hit, n=98). SOL's price action is retail-driven, mean-reverting — sniper-class signals (which V3 family inherits) systematically catch the END of moves not the start.

**ETH V3-family is NOT inverted** (50/50 hit). ETH has a different problem (asymmetric quantile may be wrong, see § 5 of deep-dive).

**BTC V3-family is correctly oriented** — V4 winning at 73.9% hit, +$9.93 PnL.

**Recommendation:** deploy SOL V3-family INVERSE sleeves (paper, then live) — see `SOL_V3_FAMILY_DEEP_DIVE_2026_05_05.md` § Recommendation.

### 1. ANTI-EDGE STRATEGIES discovered (lab agent, 2026-05-05)

Reverse-engineered the LOSING sleeves (volume + sol_5m_sniper + eth_5m_sniper DOWN). Found systematic anti-edge — INVERSING those signals is profitable:

| Strategy | Trades | Original Hit | Inverse Hit | PnL Recovery |
|---|---:|---:|---:|---:|
| 🥇 **ANTI-VOLUME-NIGHT** (volume sleeves UTC hours 1-5, 9-10) | ~350 | ~36% | **~64%** | ~$2,500 |
| 🥈 SOL_5M_SNIPER full inverse | 98 | 39.8% | **60.2%** | $627 |
| 🥉 ETH_5M_SNIPER DOWN-only inverse | 43 | 34.9% | **65.1%** | $337 |

**Mechanism for Strategy 1:** volume sleeves fire on transient bursts during low-liquidity hours (Asian session, London open). These bursts mean-revert because real flow comes from US/Europe. Volume signals at these hours are NOISE, not info.

**TV agent spec ready:** `strategy_lab/reports/TV_AGENT_INVERSE_SLEEVES_IMPLEMENTATION.md` (2026-05-05). Suggests `InverseDecorator` class wrapping existing strategies + 8 new sleeves with `_INV_NIGHT`/`_INV`/`_DOWN_INV` suffixes. Paper-only initially.

**Files:**
- `strategy_lab/reports/ANTI_EDGE_FINDINGS.md`
- `strategy_lab/reports/TV_AGENT_INVERSE_SLEEVES_IMPLEMENTATION.md`
- `strategy_lab/meta_classifier/anti_edge_analyzer.py`
- `strategy_lab/results/meta_classifier/anti_edge_breakdown.csv`
- `data/v4/shadow_trades_2026_05_05_live/losing_sleeves.csv` (6,111 trades)

### 2. COMBINED V3 × Phase 7 UNION strategy (lab agent, 2026-05-05)

Phase 7 was REJECTED in my session as standalone late-entry strategy. But **combined with V3 it's the new BTC champion.**

Tested V3 (`prob_stack ≥ 0.65`) and Phase 7 (`|imb_slope_2m| ≥ p95`) as orthogonal selection mechanisms. Only 5.2% overlap (28 of 534 markets) — confirmed orthogonal.

| Strategy | Bets | Hit Rate | ROI/bet | Total PnL ($1) |
|---|---:|---:|---:|---:|
| V3 baseline alone (`prob_stack ≥ 0.65`) | 330 | **63.6%** | +25.3% | $41.70 |
| Phase 7 alone (`|imb_slope_2m| ≥ p95`) | 232 | 59.9% | +17.8% | $20.68 |
| **UNION (V3 OR Phase 7)** ⭐ | **534** | **62.2%** | **+22.3%** | **$59.66** |
| **INTERSECTION (BOTH agree)** ⭐⭐ | **23** | **65.2%** | **+28.4%** | **$3.27** |

**+43% more PnL per session** than V3 alone. **Bet count UP +62% with only −1.4pp hit-rate dilution.**

**Recommendation:** deploy UNION as primary BTC strategy. Layer INTERSECTION as 2× boost when both fire and agree.

**Beats every HGB ensemble tested** — see "META_CLASSIFIER REJECTED" below.

**Files:**
- `strategy_lab/reports/COMBINED_V3_PHASE7.md`
- `strategy_lab/meta_classifier/combined_gate_v1.py`
- `strategy_lab/results/meta_classifier/combined_v3_phase7.csv` (4,673 markets × 17 cols)

### 3. META-CLASSIFIER (HGB ensemble) REJECTED

Tested V3 + Kronos + TA + DerivZScore in `HistGradientBoostingClassifier` with isotonic calibration + 3-fold time-series CV. **Conclusion: HGB ensemble UNDERPERFORMS V3 alone.**

| Approach | Bets | Hit Rate | ROI/bet |
|---|---:|---:|---:|
| Hand-crafted union (V3 + Phase 7) | **534** | **62.2%** | **+22.3%** |
| HGB E_full (with Kronos) | 1,073 | 57.2% | +12.4% |
| HGB E_full_no_kronos | 1,076 | 55.4% | +8.8% |
| HGB F_full+gate (with Kronos) | 160 | 60.6% | +19.3% |
| V3 alone | 330 | 63.6% | +25.3% |

**Kronos contributes ZERO importance.** `kr_pred_dir_5m` permutation importance = 0.0 (last of 60 features). Severe overconfidence (claims 70-90% confidence, observes 51-67%) → Kelly sizing destroys bankroll (-84% to -100% drawdowns).

**The simple union of two well-tested signals beats every HGB ensemble. Less is more.**

**Unexpected wins** for V3-next (deferred):
- 4 of top-14 features came from derivatives Z-score panel (`dz_z_top_lsr_sum`, `dz_z_taker_ratio`, `dz_z_oi_silent`, `dz_z_oi`)
- Continuous `ta_price_vs_ma200_pct` (rank 4) — binary `above_ma200` is useless (0.0005)
- `ta_adx_14` (rank 13) useful as continuous, not binary gate

**Files:**
- `strategy_lab/reports/META_CLASSIFIER_V1.md`
- `strategy_lab/reports/META_CLASSIFIER_NO_KRONOS.md`
- `strategy_lab/reports/META_CLASSIFIER_FULL_REPORT.md`
- `strategy_lab/meta_classifier/{train_eval,train_eval_no_kronos,build_dataset}.py`
- `strategy_lab/results/meta_classifier/{v1,v2,v3_no_kronos}_*.csv`

### 4. Shadow analysis update (2026-05-04 evening)

Confirmed in `SHADOW_ANALYSIS_2026_05_04.md`:

- **Live launch HAS NOT FIRED.** All 10,378 events have `mode=paper`. Operator clarification needed.
- **SOL V3 patch deployment is incomplete.** Only `sol_5m_v3_2` exists (5 fires, -$30). `sol_5m_v3 / v3_1 / v4` MISSING. Either TV agent didn't ship or sleeve mapping wrong.
- **DOWN ≫ UP claim WEAKENED.** Only SOL 15m sniper still shows it. ETH 5m sniper DOWN INVERTED (32.4% hit — basis for ETH inverse sleeve).
- **Volume sleeves bleeding −$17k** on ~7,000 paper fires. Largest losers: `sol_5m_volume` (-$7,570), `eth_5m_volume` (-$6,789).
- **SOL 15m volume UP edge COLLAPSED.** Was 64% UP / +$472 / n=237; now 53.1% UP / -$83.78 / n=358. Sample variance.
- **BTC v4 84.6% hit on n=13** — possibly survivorship bias. Investigate before promoting.

---

## Files created in this 2-session window (2026-05-04 + 2026-05-05)

### Reports (newest first)
- `strategy_lab/reports/ANTI_EDGE_FINDINGS.md` ⭐⭐ NEW 2026-05-05
- `strategy_lab/reports/TV_AGENT_INVERSE_SLEEVES_IMPLEMENTATION.md` ⭐ NEW 2026-05-05 — for TV agent
- `strategy_lab/reports/COMBINED_V3_PHASE7.md` ⭐⭐ NEW 2026-05-05
- `strategy_lab/reports/META_CLASSIFIER_FULL_REPORT.md` NEW 2026-05-05
- `strategy_lab/reports/META_CLASSIFIER_NO_KRONOS.md` NEW 2026-05-05
- `strategy_lab/reports/META_CLASSIFIER_V1.md` NEW 2026-05-05
- `strategy_lab/reports/SHADOW_ANALYSIS_2026_05_04.md` NEW 2026-05-04
- `strategy_lab/reports/TOP5_STOPS_OPTIMIZATION_2026_05_04.md` ⭐
- `strategy_lab/reports/LIVE_LAUNCH_TOP5_2026_05_04.md` ⭐
- `strategy_lab/reports/SOL_V3_FIX_SPEC_2026_05_04.md` ⭐
- `strategy_lab/reports/BACKTEST_PRODUCTION_FAITHFUL_2026_05_04.md`
- `strategy_lab/reports/BACKTEST_VS_SHADOW_AUDIT_2026_05_04.md`
- `strategy_lab/reports/V3_BACKTEST_FINDINGS_FULL_2026_05_04.md`
- `strategy_lab/reports/PHASE7_VALIDATION_FINDINGS_2026_05_04.md` (V5 LATE rejected — but UNION rescues Phase 7)
- `strategy_lab/reports/STRATEGY_IMPROVEMENT_RESEARCH_2026_05_04.md`
- `strategy_lab/reports/BTC_V3_DEEP_DIVE_2026_05_04.md`

### Code (newest first)
- `strategy_lab/meta_classifier/anti_edge_analyzer.py` NEW 2026-05-05
- `strategy_lab/meta_classifier/combined_gate_v1.py` NEW 2026-05-05
- `strategy_lab/meta_classifier/v4_phase7_crossref.py` NEW 2026-05-05
- `strategy_lab/meta_classifier/build_dataset.py` NEW 2026-05-05
- `strategy_lab/meta_classifier/train_eval.py` NEW 2026-05-05
- `strategy_lab/meta_classifier/train_eval_no_kronos.py` NEW 2026-05-05
- `strategy_lab/meta_classifier/refresh_and_analyze.sh` NEW 2026-05-05
- `strategy_lab/v4_signals/sleeve_replay_with_stops.py` ⭐
- `strategy_lab/v4_signals/sleeve_replay_with_kelly.py`
- `strategy_lab/v4_signals/sleeve_ranking.py`
- `strategy_lab/v4_signals/phase7_validation_v3_full.py` ⭐ (production-faithful)
- `strategy_lab/v4_signals/backtest_vs_shadow_audit.py`
- `strategy_lab/build_features_v3plus.py` NEW
- `strategy_lab/fetch_btc_5m_extend.py` NEW

### Data
- `data/v4/shadow_trades_2026_05_05_live/v3_v4_resolutions.csv` NEW 2026-05-05
- `data/v4/shadow_trades_2026_05_05_live/losing_sleeves.csv` NEW 2026-05-05 (6,111 trades for anti-edge)
- `data/v4/shadow_trades_2026_05_04/{vps2,vps3}.csv` (10,989 events, 2026-05-04)
- `data/v4/refresh_2026_05_02/{btc,eth,sol}_book_depth_v3_full.csv` (409 MB total)
- `data/v4/refresh_2026_05_02/{btc,eth,sol}_markets_minimal.csv`
- `data/v4/refresh_2026_05_02/binance_spot_1min_full.csv` (BINANCE-SPOT-WS only)
- `data/v4/refresh_2026_05_02/polymarket_updown_PROD.py` (production controller reference)
- `strategy_lab/results/meta_classifier/anti_edge_breakdown.csv`
- `strategy_lab/results/meta_classifier/combined_v3_phase7.csv` (4,673 × 17)
- `strategy_lab/results/meta_classifier/v{1,2,3_no_kronos}_*.csv` (ablation tables, predictions)

---

## What's still pending (priority order)

### 🔴 P0 — Operator clarification + TV agent execution

**1. CLARIFY: did live launch actually fire? (operator question)**
- All 10,378 events show `mode=paper`. 0 live trades observed.
- Either: live launch was deferred / `mode=live` filtered upstream / live trades use different `kind` / Polymarket trades not bridged to `trading.events`
- Block 1.5 minutes of operator time to verify.

**2. CLARIFY: SOL V3 patch deployment status**
- Per shadow analysis: only `sol_5m_v3_2` fires (5 trades). `sol_5m_v3 / v3_1 / v4` are MISSING.
- Did TV agent ship Fix A from `SOL_V3_FIX_SPEC_2026_05_04.md`?
- Is sleeve mapping correct? Or env config gating SOL?

**3. TV agent: deploy ANTI-EDGE INVERSE SLEEVES (paper mode)**
- Spec: `strategy_lab/reports/TV_AGENT_INVERSE_SLEEVES_IMPLEMENTATION.md`
- 8 new inverse sleeves (paper only): `*_volume_INV_NIGHT` (×6), `sol_5m_sniper_INV`, `eth_5m_sniper_DOWN_INV`
- Effort: ~1 day (InverseDecorator class + sleeve registration)
- Validation criteria embedded in spec; lab will check at week 1.

**4. TV agent: deploy SOL V3 fix (Fix A — per-asset spread filter)**
- File: `strategy_lab/reports/SOL_V3_FIX_SPEC_2026_05_04.md`
- Effort: ~1.5 hr (Fix A only) or ~5.5 hr (Fix A + V3.3 A/B sleeve)
- Effect: SOL V3 fires 0/day → 5-15/day with 60%+ hit rate

**5. TV agent: deploy per-sleeve stops for top-5 launch**
- File: `strategy_lab/reports/TOP5_STOPS_OPTIMIZATION_2026_05_04.md` § Implementation
- Env vars: `TV_POLY_STOP_LOSS_BTC_15M_SNIPER=0.50`, `TV_POLY_STOP_LOSS_SOL_15M_SNIPER=0.70`, `TV_POLY_TAKE_PROFIT_ETH_15M_SNIPER=0.70`
- Effort: ~1 day (intra-window monitor)
- Per shadow analysis BTC v4 caveat (84.6% hit on n=13 may be survivorship bias) — flag for re-validation before promoting V4 to live.

**6. Operator decision on live launch parameters**
- Confirm 5 sleeves to deploy
- Confirm bankroll: $50 starting, $1/trade fixed
- Confirm kill-switch thresholds

### 🟡 P1 — Lab work (after TV agent deploys)

**7. Build LIVE signal generator for COMBINED V3 + Phase 7 UNION**
- Per `COMBINED_V3_PHASE7.md` § 9
- Real-time V3 features + Phase 7 features from `orderbook_snapshots_v2`
- Output: signal at each new BTC 5m market open
- After OOS validation passes, this becomes the primary BTC strategy (replacing standalone V3)

**8. OOS validation of UNION strategy**
- Wait 7-14 days for fresh `mr_full.csv` resolutions
- Re-run on out-of-sample data
- Confirm 62% hit rate holds
- Currently tested on 5-day window — possibly optimistic.

**9. Real CLOB pricing on UNION**
- Currently assumes 0.50 mid entry; real Polymarket asks are 50-150bp worse
- Eats ~5-15bp from per-bet ROI
- Still expected positive at 62% hit but tighter margin

**10. Daily monitoring queries** (in LIVE_LAUNCH_TOP5_2026_05_04.md § Pre-launch checklist)

**11. After 7 days inverse-sleeves paper data: validate anti-edge hypothesis**
- Per TV_AGENT_INVERSE_SLEEVES_IMPLEMENTATION.md § Pass criteria
- If validated, consider promoting INVERSE sleeves to live (but lab agent recommends staying paper-only initially)

### 🟢 P2 — Future research (deferred)

**12. Investigate BTC V4 84.6% hit (survivorship bias check)**
- n=13 too small for confidence
- Check feature pipeline for leakage

**13. Add rolling 14-day quantile to backtest** — production parity (~10 lines)

**14. Add residual-IC analysis using V3-next features**
- Top-14 includes 4 derivatives Z-score features (`dz_z_top_lsr_sum`, etc.)
- `ta_price_vs_ma200_pct` continuous (rank 4)
- These could be added to V3 quantile signal (Phase 8 alternative)

**15. Phase 9 — Trade Flow Imbalance from `trades_v2`**
- 16.8M Polymarket trade prints on VPS2
- Test as residual signal

**16. ETH V3 inverted signal investigation** (already validated at 44% hit in BOTH backtest AND production — drop from V3 launch)

**17. 30-day OOS retest** (target: 2026-05-22 when collector reaches 30d)

---

## Critical knowledge for fresh session

### Current state of strategies

| Strategy | Best metric | Status |
|---|---|---|
| **V3 BTC alone** | 63.6% / +25.3% ROI / 330 bets | ✅ Production-tested, deployable as-is |
| **V3 + Phase 7 UNION** | 62.2% / +22.3% ROI / 534 bets / **+43% more PnL** | ⭐ Best BTC strategy, needs live signal pipeline |
| **V3 ∩ Phase 7 INTERSECTION** | 65.2% / +28.4% ROI / 23 bets | ⭐⭐ 2× boost when both fire |
| **Top-5 with stops** (BTC v3 + 4 snipers) | $26/period combined PnL | ✅ Spec ready for live launch |
| **ANTI-EDGE inverses** (3 strategies) | 60-65% inverse hit, +$3.5K recovery | ✅ Spec ready for paper deploy |
| **SOL V3 fix** | Restores 5-15 fires/day at ~60% hit | ✅ Spec ready, awaiting TV agent |
| **HGB Meta-classifier** | 56-57% hit | ❌ REJECTED — V3 alone wins |
| **Phase 7 alone (late entry)** | 59.9% / +17.8% / 232 bets | ⚠ Standalone OK, much better in UNION |
| **Kronos in any role** | 0 importance | ❌ REJECTED |
| **V5 LATE entry strategy** | -$13 to -$43 across assets | ❌ REJECTED in 2026-05-04 session |
| **Volume sleeves** | -$17K on 7K fires | ❌ DEAD — but their inverses are profitable! |
| **ETH V3** | 44% hit | ❌ DROP — losing in BOTH backtest and production |

### Production controller signal logic (memorize this)

Production code at `/opt/tradingvenue/backend/app/controllers/polymarket_updown.py` (copy at `data/v4/refresh_2026_05_02/polymarket_updown_PROD.py`):

```python
# signal_ts = bars[-1].bar_open of just-closed strategy 5MIN bar
# = polymarket_window_start - 300s
# (one strategy_tf period BEFORE the polymarket market opens)

ws_s = int(window_start_us) // 1_000_000
btc_now = await fetch_close_asof('BINANCE_SPOT_BTC_USDT', '1MIN', ws_s,
                                  source='binance-spot-ws')   # KLINE_SOURCE
btc_prior = await fetch_close_asof(symbol_id, '1MIN', ws_s - 300, ...)
ret_5m = math.log(btc_now / btc_prior)
```

**To replicate in backtest:**
- Use `binance_klines_v2` table on VPS3 with `source='binance-spot-ws'` filter
- For polymarket_window_start = ws, use signal_ts = ws - 300 (5m sleeves) or ws - 900 (15m sleeves)
- Use 1MIN bars only

### VPS access

```bash
ssh -i ~/.ssh/vps2_ed25519 "root@[2605:a140:2323:6975::1]"
ssh -i ~/.ssh/vps3_ed25519 root@185.190.143.7
```

VPS2 = collector + V1 control arm (Binance collector DEAD due to geoblock since 04-22).
VPS3 = strategy engine + dashboard + Binance spot collector (working — `binance-spot-ws` source).

### V3 family is nested

V4 ⊆ V3.2 ⊆ V3, V4 ⊆ V3.1 ⊆ V3 — running multiple V3-family sleeves = same market traded multiple times = exposure multiplied. **For live launch, pick ONE V3 variant.** We chose V3 (largest sample).

---

## Quick start commands for fresh session

```bash
cd "/c/Users/alexandre bandarra/Desktop/global"

# Refresh all sleeve shadow data
ssh -i ~/.ssh/vps3_ed25519 root@185.190.143.7 \
  "sudo -u postgres psql -d storedata -c \"COPY (SELECT at, sleeve_id, data->>'symbol' AS symbol, data->>'tf' AS tf, data->>'signal' AS signal, (data->>'won')::boolean AS won, data->>'mode' AS mode, (data->>'entry_price')::numeric AS entry_price, (data->>'pnl_usd')::numeric AS pnl_usd FROM trading.events WHERE kind='poly_updown_resolution' ORDER BY at) TO STDOUT WITH CSV HEADER\"" \
  > data/v4/shadow_trades_2026_05_05/vps3.csv

# Re-rank sleeves (top-5 selection)
py -X utf8 -m strategy_lab.v4_signals.sleeve_ranking

# Re-run top-5 backtest with stops
py -X utf8 -m strategy_lab.v4_signals.sleeve_replay_with_stops

# Re-run V3 production-faithful backtest
py -X utf8 -m strategy_lab.v4_signals.phase7_validation_v3_full

# Re-run anti-edge analyzer
cd strategy_lab/meta_classifier && bash refresh_and_analyze.sh

# Re-run V3 + Phase 7 UNION analyzer
py -X utf8 strategy_lab/meta_classifier/combined_gate_v1.py
```

---

## Critical reminders

1. **LIVE LAUNCH HAS NOT FIRED.** Verify with operator before assuming top-5 is producing real PnL.
2. **DO NOT pursue Kronos meta-classifier further.** Importance = 0, V3 alone wins.
3. **DO NOT use Kelly sizing with HGB ensemble.** Severe overconfidence → -84% to -100% drawdown.
4. **DO NOT layer SL=50%/TP=30% on V3 directly.** V3 has hedge-hold (rev_bp=15) in production. Re-validate first.
5. **DO NOT include ETH V3 in top-5.** 44% hit confirmed losing in BOTH backtest and production.
6. **DO NOT trust pre-2026-05-04-evening backtest results** — earlier `phase7_validation_v3_full.py` had offset bug + source filter bug. Only trust current state of that file. Verified 95-100% direction match.
7. **VPS2 binance collector is DEAD (geoblock).** Use VPS3 `binance-spot-ws` source. NOT `binance-vision`.
8. **Polymarket data started 2026-04-22.** Max sample window is 12.5+ days as of 2026-05-05.
9. **Production controller signal_ts = polymarket_window_start - 300** (NOT directly = window_start). One tf period back.
10. **Volume sleeves are PROFITABLE INVERTED** during overnight UTC hours. Anti-edge spec ready for TV agent.
11. **Top-5 selection unchanged from 2026-05-04** but BTC v4 (84.6% hit on n=13) flagged for survivorship-bias check before live promotion.

End of pointer doc. See specific reports for details:
- `BACKTEST_PRODUCTION_FAITHFUL_2026_05_04.md` for backtest framework
- `LIVE_LAUNCH_TOP5_2026_05_04.md` for top-5 selection
- `TOP5_STOPS_OPTIMIZATION_2026_05_04.md` for per-sleeve stops
- `SOL_V3_FIX_SPEC_2026_05_04.md` for SOL V3 fix
- `TV_AGENT_INVERSE_SLEEVES_IMPLEMENTATION.md` for anti-edge inverse sleeves
- `COMBINED_V3_PHASE7.md` for the new BTC champion strategy
- `META_CLASSIFIER_FULL_REPORT.md` for the rejected ensemble (don't redo this)
- `SHADOW_ANALYSIS_2026_05_04.md` for current sleeve performance
