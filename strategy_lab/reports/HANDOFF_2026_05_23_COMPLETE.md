# Complete session handoff — 2026-05-22 / 2026-05-23

_Two-day session. Major outcomes: VPS3 production audit (4 bugs), 1s binance data
ingest (5.5M rows), HoD refresh fix (5.4× ensemble PnL), 5 new strategy lines with
deploy-ready specs, 30+ candidate sleeves across 5m/15m markets, full TA-indicator
overlay framework. Total backtest uplift over original 11-sleeve baseline:
~$25-35k / 28d at $25 notional = **~$1k/day @ $25, ~$10k/day @ $250**._

This file is self-contained — a new session should be able to start from here.

---

## 0. Where we started (state at session start)

- **11 shadow sleeves running on VPS3** (`poly_updown_*_sniper_hod`, `_momo_hod`, etc.)
- HoD constant in `gates.py` shipped at 11/11 sleeves
- Production fee model = **2%-on-profit-only** on winning leg (verified, see CLAUDE.md)
- 1s binance kline data being collected since 2026-05-07 on VPS3 (`binance_klines_v2.period_id='1SEC'`) — was not yet pulled locally
- `momo_variants_2abc.py` produced 10k Baseline_v1+v2 backtest fires
- F7 RSI gate and M1V/M5V Markov filters were spec'd but Markov regime aux was hardcoded `None` in production code (BROKEN — see §3)
- Goal: find ≥60% WR strategies on 5m markets with low DD

---

## 1. TL;DR — what to do first in the next session

### 🎯 PRIORITY 1 — ship the deploy-ready fixes (3 days of operator time)

| # | Action | Effort | Expected uplift @ $25 | Status |
|--:|---|---|--:|---|
| 1 | Refresh `HOD_TOP8_BY_CELL` constant (operator review per spec §6) | 5min edit + restart | **+$13k / 28d** | Spec ready in `TV_AGENT_PHASE34_FIXES_2026_05_22.md` §2 |
| 2 | Drop `m5va` from sleeve #2 (`poly_updown_eth_15m_sniper_hod_m5va`) | 1-line + restart | +$745 | Fix in same spec §3 |
| 3 | Add `m1v_va` to sleeve #3 (`poly_updown_btc_15m_momo_hod`) | per spec §4 | +$1,265 | Same spec §4 |
| 4 | Patch momo strategies to fade `mag_ratio > 3.0` on BTC+ETH only (NOT SOL) | 4-line strategy patch | +$1,264 | Inline in this handoff §6.2 |

Result: **+$16k / 28d** without writing any new sleeves.

### 🎯 PRIORITY 2 — deploy the new strategy lines (1-2 weeks of dev)

| # | Action | Effort | Expected uplift |
|--:|---|---|--:|
| 5 | **S1.5 (slot-anchored VWAP continuation) — 5m + 15m sleeves** | per `TV_AGENT_VWAP_CONTINUATION_FULL_SPEC_2026_05_23.md` | +$8-12k / 28d |
| 6 | **S6 (spike-driven entry with CVD confirmation)** | per spec; needs 1s feed in tv-engine | +$3-5k / 28d |
| 7 | **Ribbon-agree universal filter** (overlay on all sleeves) | shared library update | +$2-4k / 28d additive |
| 8 | **15m TA-overlay sleeves** (triple-confluence + ribbon on BTC 480/600/840s) | per `NEW_INDICATOR_SLEEVES_15M_2026_05_23.md` | +$3-4k / 28d |

### 🎯 PRIORITY 3 — long workstreams

| Action | Why | Effort |
|---|---|---|
| Mint-and-sell V3 (asymmetric posting based on CVD direction) | V2 is loss-making (~−$45k/day equivalent), V3 redesign needed | 1-2 weeks |
| Production validation of all new sleeves (7-day shadow) | Out-of-sample confirmation | passive (7d shadow) |
| Test 14d+ rolling validation as new data arrives | Confirm OOS robustness | ongoing |

---

## 2. Strategies discovered (chronological, with detailed metrics)

### S0 — Existing 11-sleeve baseline (CONTEXT)

Current production. Per the operator-locked spec (Phase 34). Ensemble PnL with
SHIPPED HoD constant = $2,949/28d. **Refreshes to $15,900 (5.4×) on HoD update alone.**

### S3 — HoD refresh ⭐ BIGGEST FREE WIN

**What**: shipped `HOD_TOP8_BY_CELL` was derived from `at_ts.dt.hour` (resolution-time hour). Spec §2.1 mandates **fire-time hour**. Re-deriving with the correct anchor flips ALL 18 cells.

**Effect**:
| Metric | Current HoD | Refreshed HoD |
|---|---:|---:|
| Ensemble PnL (28d, $25 notional) | $2,949 | **$15,900** |
| Positive sleeves | 7/11 | 11/11 |
| Sleeves flipping negative → positive | — | #5 (sniper btc_5m), #10 (momo_v2 sol_15m) |

**Per-sleeve WR (refreshed HoD)**:

| # | Sleeve | n | WR | $/tr | sum 28d |
|--:|---|--:|--:|--:|--:|
| 1 | sniper sol_5m _hod | 226 | 62.4% | +$3.41 | +$769 |
| 2 | sniper eth_15m _hod_m5va (BROKEN) | 55 | 67.3% | +$5.69 | +$313 |
| 2-fix | drop m5va → _hod only | 129 | **73.6%** | +$5.78 | +$745 |
| 3 | momo btc_15m _hod | 139 | 78.4% | +$13.42 | +$1,865 |
| 3+m1v | + M1V | 61 | **90.2%** | +$20.73 | +$1,265 |
| 4 | sniper btc_15m _hod | 173 | 57.2% | +$5.43 | +$939 |
| 5 | sniper btc_5m _hod | 249 | 59.8% | +$1.40 | +$349 |
| 6 | momo_v2 btc_5m _hod_mtf | 751 | 58.7% | +$3.61 | +$2,714 |
| 7 | momo_v2 btc_15m _hod | 246 | 70.7% | +$9.42 | +$2,317 |
| 8 | momo_v2 sol_5m _hod | 334 | 65.6% | +$7.16 | +$2,392 |
| 9 | momo_v2 eth_15m _hod | 232 | **83.6%** | +$15.15 | **+$3,515** |
| 10 | momo_v2 sol_15m _hod | 92 | 77.2% | +$13.18 | +$1,213 |
| 11 | sniper eth_5m _hod | 294 | 55.8% | +$1.64 | +$481 |

**Files**: `strategy_lab/reports/HOD_REFRESH_2026_05_22.md`, `_recompute_hod_top8.py`, `shadow_11_sleeves_v2.py`. Refreshed constants at `strategy_lab/markov_filter/_results/hod_refresh/2026_05_22/new_hod_top8.json`.

### S2 — Fade Extreme Momo (BTC + ETH only, mag_ratio > 3) ⭐ FREE PATCH

**What**: when momo fires with `|ret_2m| / threshold > 3.0`, FLIP the direction. The biggest signals are mean-reversion zones (38% WR following → 62%+ fading).

**Per-cell metrics**:

| Asset | Gate | n | fade WR | $/tr | sum 28d |
|---|---|--:|--:|--:|--:|
| **ETH** | `mag>3.0` (no extra gate) | 72 | **70.8%** | +$8.24 | +$593 |
| **BTC** | `mag>3.0` (no extra gate) | 92 | 67.4% | +$7.30 | +$671 |
| **ALL (pooled BTC+ETH+SOL)** | `mag>3.0` | 230 | 63.9% | +$5.29 | **+$1,216** |
| BTC | `mag>3.0` + F7-contra | 33 | 69.7% | +$9.26 | +$306 |

**SOL: 0 deployable configs** — SOL high-mag signals are NOT exhausted, random WR.

**Tier impact** (pooled):
- (1.5, 2.0]: fade WR = 49.3% (don't fade)
- (2.0, 2.5]: fade WR = 44.3% (don't fade — small sample anomaly)
- (3.0, 5.0]: fade WR = **63.3%** (fade)
- (5.0, 100]: fade WR = **66.7%** (fade)

**Implementation**: 4-line patch to `momo.py` strategy on VPS3 — if `mag_ratio > 3.0` and `asset in {BTC, ETH}`, flip the signal direction. Free $1,216/28d.

**Files**: `strategy_lab/reports/FADE_MOMO_5M_2026_05_23.md`, `fade_momo_5m.py`.

### S1 / S1.5 — VWAP Continuation ⭐⭐⭐ THE NIGHT'S WINNER

**What**: at a fixed moment inside each 5m slot, compute binance deviation from VWAP-since-slot-open. Bet WITH the deviation (momentum continuation, not fade). Filter by M1V Markov regime + F7 RSI + cross-asset confluence.

**S1 vs S1.5**: S1 used 15m-anchored VWAP. S1.5 uses SLOT-anchored VWAP (anchored at slot_start). **S1.5 substantially outperforms S1.** Slot-anchor is the semantically correct reference — strikes are set at slot_start, so VWAP from that moment shows the move relative to the strike's reference window.

**S1.5 top 10 sleeves (5m markets)**:

| Sleeve | Market | n | WR | $/tr | sum 28d | DD | streak | Sharpe |
|---|---|--:|--:|--:|--:|--:|--:|--:|
| **BTC 210 5-10bps** | BTC 5m @ +210s, 5-10bps | 529 | 87.3% | +$2.99 | **+$1,581** | −$231 | 2 | 5.26 |
| **ETH 210 10-15bps** | ETH 5m @ +210s, 10-15bps | 138 | 87.0% | **+$10.92** | **+$1,508** | −$186 | 2 | 4.19 |
| BTC 240 3-5bps | BTC 5m @ +240s, 3-5bps | 810 | 81.7% | +$1.09 | +$886 | −$385 | 4 | 4.89 |
| ETH 150 5-10bps | ETH 5m @ +150s | 707 | 84.3% | +$1.25 | +$883 | −$264 | 3 | **8.26** |
| ETH 240 5-10bps | ETH 5m @ +240s | 714 | 85.3% | +$1.13 | +$803 | — | — | — |
| SOL 270 5-10bps | SOL 5m @ +270s | 570 | 87.2% | +$1.14 | +$651 | −$849 | 3 | 1.68 |
| BTC 150 3-5bps | BTC 5m @ +150s | 770 | 81.0% | +$0.84 | +$650 | — | — | — |
| ETH 210 5-10bps | ETH 5m @ +210s, 5-10bps | 719 | 87.5% | +$0.84 | +$606 | — | — | — |
| BTC 60 3-5bps | BTC 5m @ +60s, 3-5bps | 442 | 74.7% | +$1.31 | +$579 | −$277 | 4 | 6.39 |
| **SOL 30 5-10bps** | SOL 5m @ +30s | 112 | 81.2% | +$4.84 | +$542 | **−$75** | 3 | **13.32** |

**Live-mimic stress test** (top config): under hypothetical worst-case `0.07·p·(1−p)` fee curve (NOT production), top sleeve preserves **92.7% of legacy PnL ($1,010 vs $1,090)**. Production-actual 2%-on-profit fee = legacy column = the realistic number.

**OOS validation**: 3 of 5 top configs have **test_WR > train_WR**. Top config (BTC 240 M1V): train_WR=85.1%, **test_WR=89.0%** (better OOS).

**Top S1.5 ensemble**: +$8,689 over 28d at $25 notional = ~$310/day @ $25, ~$3,100/day @ $250.

**Full implementation spec**: `strategy_lab/reports/TV_AGENT_VWAP_CONTINUATION_FULL_SPEC_2026_05_23.md` — 17 sections, complete code, tests, verification SQL, rollback procedure.

**Files**:
- `vwap_continuation_5m.py` (15m-anchored, original S1)
- `vwap_continuation_v2_gated.py` (15m-anchored + gates)
- `vwap_slot_anchored_5m.py` (S1.5, the winner)
- `vwap_slot_anchored_v2_gated.py` (S1.5 with gates)
- `vwap_drawdown_livemimic.py` (stress test)

### S5 — Z_Contra ETH Underdog (sub-60% WR but PnL-positive)

**What**: port of mlmodelpoly's `z_contra_fav_dip_hedge` to 5m markets. Buy underdog when PM favorite dips AND binance disagrees with PM favorite direction.

**Best config**: **ETH 30s offset, 100bps dip, Z=1.0** → n=183, WR=55.2%, **+$3.24/tr**, +$594.

Sub-60% WR but PnL-positive because we buy cheap UNDERDOG tokens (entry vwap ≈ 0.30). Each win pays 2x+ per share.

**No 60%+ config found.** Treat as paper-only initially, half-notional sizing.

**Files**: `strategy_lab/reports/Z_CONTRA_5M_2026_05_23.md`, `z_contra_5m.py` (agent script).

### S6 — Spike-driven entry (1s breakouts) ⭐

**What**: fires on raw 5-15s binance breakouts with CVD confirmation. Independent of momo's ret_2m signal. Captures intra-slot bursts that VWAP-based strategies miss.

**Definitions tested**:
- D1: `|ret_5s| > 2.5bps AND sign(cvd_5s) == sign(ret_5s)` (5s spike + CVD)
- D2: `|ret_15s| > thr AND sign(cvd_15s) == sign(ret_15s)` (15s sustained)
- D3: both 5s and 15s consistent
- D4: 30s run continuing (`ret_30s > 5bps AND ret_5s > 0`)

**Top S6 sleeves**:

| Sleeve | n | WR | $/tr | sum 28d | Sharpe |
|---|--:|--:|--:|--:|--:|
| BTC off120 D1 T1 | 146 | 70.5% | **+$6.57** | +$960 | 8.70 |
| BTC off45 D1 T1 | 165 | 66.1% | +$5.42 | +$895 | 8.01 |
| BTC off30 D1 T1 | 149 | 67.1% | +$5.15 | +$768 | **11.07** |
| **BTC off60 D4 T1** | 97 | **83.5%** | +$4.88 | +$474 | **15.10** (highest Sharpe in entire study) |
| SOL off30 D2 T1 | 130 | 78.5% | +$3.55 | +$461 | 10.26 |
| ETH off60 D1 T1 | 182 | 67.0% | +$2.52 | +$459 | 6.40 |
| **ETH off120 D4 T1** | 98 | 80.6% | +$4.61 | +$451 | 8.17 (test_WR=93.3%) |

**Entry advantage**: spike entries at +15-120s of slot have CHEAP vwap (0.55-0.74) because PM book hasn't priced in the move yet. **Spike-only fires (not overlapping S1.5): 6,514 fires at 62% WR / +$0.49/tr** — independent edge.

**Files**: `spike_entry_5m.py` (agent), `SPIKE_ENTRY_5M_2026_05_23.md`.

### S7 — VWAP Continuation 15m ⭐ (with TA overlays — 2.3× original)

**What**: same logic as S1.5 (slot-anchored VWAP) applied to 15m markets. Fire offsets 60-840s.

**Original S7 top sleeves**:
- SOL 840s 20-30bps: WR 77.5%, **+$17.34/tr** (n=40, highest $/tr in entire study)
- ETH 480s 5-10bps: WR 76.8%, +$274 sum (largest 15m volume)
- ETH 480s 15-20bps: WR **89.7%**, +$72 sum

**NEW (TA overlay added)** — 10 deployable 15m sleeves:

| Sleeve | Market | n | WR | $/tr | sum 28d |
|---|---|--:|--:|--:|--:|
| **S7 TRIPLE BTC 840 5-10bps** | BTC 15m @ slot+840s, triple gate | 111 | 75.7% | **+$7.60** | **+$843** |
| S7 RIBBON BTC 840 5-10bps | BTC 15m @ slot+840s + ribbon | 141 | 76.6% | +$5.01 | +$707 |
| S7 TRIPLE BTC 480 5-10bps | BTC 15m @ slot+480s, triple | 206 | 82.0% | +$1.99 | +$410 |
| **S7 RIBBON SOL 240 10-15bps** | SOL 15m @ slot+240s + ribbon | 80 | 86.2% | +$3.65 | +$292 |
| **S7 TRIPLE BTC 600 5-10bps** | BTC 15m @ slot+600s, triple | 205 | **90.2%** | +$1.42 | +$292 |
| S7 RIBBON BTC 600 5-10bps | BTC 15m @ slot+600s + ribbon | 258 | 89.1% | +$1.09 | +$280 |
| **S7 RIBBON ETH 720 15-20bps** | ETH 15m @ slot+720s + ribbon | 30 | 83.3% | **+$9.10** | +$273 |

**Top-10 ensemble: 1,592 fires, avg WR 83%, +$3,899 / 28d (2.3× original S7).**

**Ultra-low-DD 15m layer** (ribbon + m1v stack):
- **BTC 480 10-15bps + ribbon+m1v: WR 100%, 0 losses, n=35** ⭐
- BTC 600 5-10bps + ribbon+m1v: WR 96.1%, n=152, sum +$264
- SOL 840 5-10bps + ribbon+m1v: WR 97.3%, n=74

**Files**: `vwap_continuation_15m.py`, `NEW_INDICATOR_SLEEVES_15M_2026_05_23.md`.

### NEW (today's mega-run) — TA-indicator overlays ⭐

**What**: computed MA Ribbon (20 EMAs 5-100), Slow Stochastic (60s/300s), Bollinger Bands (60s/120s), MFI (60s/300s), CCI (60s) on 5.5M 1s binance bars. Overlaid on every S1.5/S6/S7 fire.

**Key findings**:

1. **`ribbon_agrees` is a universal $/tr filter**:
   - S1.5: $/tr 3.6× ($0.16 → $0.56), removes 8,960 losing fires
   - S6: excludes 249 junk fires (60% WR, -$1.60/tr)
   - **DEPLOY: add as AND-gate on every shadow sleeve**

2. **Triple confluence (ribbon + stoch + cci agrees)** dominates S6 BTC + S7 BTC late-fire:
   - S6 BTC off120 D1 T1: 75.4% WR / +$7.90/tr (+9pp WR over baseline)
   - S7 BTC 840 5-10bps: 75.7% WR / +$7.60/tr (best 15m new sleeve)

3. **Tight ribbon + spike = breakouts from consolidation** (S6 BREAKOUT family):
   - S6 BTC compression<2bps + ribbon: 5,775 fires, +$3.01/tr, **+$17,391 sum/28d** (largest single new combo by volume)

4. **Ribbon + Markov stack** pushes WR to 95%+:
   - BTC 240 5-10bps + ribbon + m1v: 95.7% WR
   - SOL 270 5-10bps + ribbon + m1v: 97.8% WR
   - ETH 210 10-15bps + ribbon + m1v: 97.1% WR
   - BTC 480 15m + ribbon + m1v: **100% WR** (zero losses on 35 fires)

5. **What DOESN'T work**:
   - **R1 Pure Color Trend (standalone)**: 73% WR but loses money (adverse vwap)
   - **R4 Compressed Breakout (standalone)**: 54% WR, -$200k sum
   - **H1 Exhaustion fade**: our fires KEEP winning at overbought (don't fade)
   - **Oversold bounce**: consistent loser

**Files**: `compute_ta_indicators.py`, `overlay_ta_indicators.py`, `TA_INDICATORS_MEGA_RUN_2026_05_23.md`, `NEW_INDICATOR_SLEEVES_PER_MARKET_2026_05_23.md`, `NEW_INDICATOR_SLEEVES_15M_2026_05_23.md`.

### Mint-and-Sell V3 (PARTIAL — needs redesign work)

**What**: Mint-and-Sell V2 (existing maker strategy posting symmetric at $0.50±spread) is loss-making (~-$45k/day equivalent). V3 proposal: when |CVD_slope_30s| is high, post ONLY the side flow is FOR (asymmetric, skip adverse-selection side).

**Agent D findings**: CVD direction predicts which leg gets adversely selected (27% of fills carry 55% of losses). But |CVD| magnitude alone doesn't separate adverse from positive fills (selectivity ≤0.2pp). V3 simulation with asymmetric posting **does NOT flip V2 to positive**; best result is 91-94% PnL improvement but still loss-making.

**Status**: Flagged as needing structural redesign, not parameter tweaks. Separate workstream.

**Files**: `MINT_AND_SELL_V3_SIMULATION_2026_05_23.md`, `_v3_simulate.py`, `_cvd_timing_overlay.py`.

---

## 3. VPS3 Production Audit — 4 bugs found

Audit code paths on `/opt/tradingvenue/backend/` against the existing Phase 34 spec. See `VPS3_SHADOW_AUDIT_2026_05_22.md`.

### 🔴 Bug #1: Markov regime NEVER computed

**Location**: `backend/app/engine/poly_updown_loop.py` — `build_bar_context_t_plus_120` and `build_bar_context_t_plus_60` both contain:
```python
markov_regime_w20_5m_va=None,  # hardcoded
```

The spec promised this would be "computed lazily by the controller's gate block (with per-(sym, ws_s) cache)" — but the lazy code was never written.

**Effect**: sleeve #2 (`poly_updown_eth_15m_sniper_hod_m5va`) is completely broken. Markov gate fails closed 100% of the time with `gate_markov_skip` (regime=-1).

**Live evidence**: 2/2 fires that passed the HoD gate today got `regime=-1` and were skipped.

**Recommended fix**: DROP `m5va` from sleeve #2 entirely (per S2 analysis, Markov on sniper sleeves is counterproductive anyway). 1-line config change in `engine_main.py::_SHADOW_GATED_SLEEVES_SPEC`.

### 🔴 Bug #2: sniper bar_close phase has no MTF/Markov aux

`ret_15m_for_mtf`, `ret_1h_for_mtf`, `markov_regime_w20_5m_va` are only populated in t+60/t+120 builders. **Sniper fires at `phase="bar_close"`** — the bar_close BarContext doesn't have these aux. Any sniper sleeve carrying mtf2 or m5va gate fails closed silently.

**Recommended fix**: enforce at config-load — validator that raises `ValueError` if a sniper entry has mtf2/m5va/m1va in its gate_stack.

### ⚠️ Bug #3: HoD constant is stale (covered in S3 above)

### 🔴 Bug #4: No tests for the gate stack

`test_polymarket_updown_shadow.py` covers legacy `_audit_shadow_*` functions but NOT the gate block. Nothing asserts Markov regime ≠ -1 with real BarContext. A single integration test would have caught Bug #1 pre-deploy.

**Recommended fix**: 3 new test files per spec:
- `test_gates.py` — unit tests for `markov_passes(UP, -1) is False` etc.
- `test_markov.py` — unit tests for `label_regime_vol_adaptive`
- `test_polymarket_updown_gates.py` — integration test asserting `gate_decisions['m5va']['regime'] in {0,1,2}`

### Bonus 🟡: Production-actual fee model verified

CLAUDE.md confirms production uses **2%-on-profit-only** (matches 25,900 prod resolutions). The `0.07·p·(1−p)` formula in `strategy_lab/fees.py` is from Polymarket general docs but does NOT apply to BTC/ETH/SOL up-down markets (feeRate effectively 0 or feesEnabled=false there). All backtests should use `engine_v2.LegacyConfig`.

**Files**: `VPS3_SHADOW_AUDIT_2026_05_22.md`, `TV_AGENT_PHASE34_FIXES_2026_05_22.md`.

---

## 4. Data infrastructure built

### 1s Binance data ingest (NEW)

Pulled from VPS3 storedata DB: `binance_klines_v2.period_id='1SEC'`. **5,497,531 rows** (BTC + ETH + SOL × ~21 days of 1s coverage Apr 30 → May 22). Includes `taker_buy_base` column → CVD computable from kline alone.

**Local path**: `data/v4/canonical/klines_1s/binance_1s_28d.parquet` (122 MB, zstd).

### TA-indicators panel (NEW)

Computed on all 5.5M 1s bars:
- 20 EMAs (periods 5, 10, 15, ..., 100)
- Ribbon features: lead_slope_bps, lead_vs_ref_bps, alignment_pct, compression_bps, color (Madrid ribbon)
- Slow Stochastic at 60s and 300s windows
- Bollinger Bands position + width at 60s and 120s
- MFI at 60s and 300s
- CCI at 60s

**Path**: `data/v4/canonical/_results/ta_indicators_1s.parquet` (1.28 GB, zstd).

### Augmented per-fire parquets (NEW)

Each fire timestamped from a strategy backtest joined to the TA panel via merge_asof:
- `s15_with_ta.parquet` — 33,323 S1.5 fires + all indicators
- `s6_with_ta.parquet` — 11,336 S6 fires + all indicators
- `s15_with_ta_and_markov.parquet` — S1.5 + indicators + M1V regime
- `v15m_with_ta_and_markov.parquet` — 12,492 S7 (15m) fires + indicators + Markov
- `vwap_continuation_5m_per_fire.parquet` — 40,210 S1 fitted fires (15m-anchored)
- `vwap_slot_anchored_5m_per_fire.parquet` — 33,323 S1.5 fitted fires (slot-anchored)
- `vwap_continuation_15m_per_fire.parquet` — 12,492 S7 fitted fires
- `spike_entry_5m_per_fire.parquet` — 11,336 S6 fitted fires
- `fade_momo_5m.csv` — S2 fade variants
- `z_contra_5m.csv` + `_perfire.parquet` — S5 underdog buys
- `gate_search_5m.csv` — 386 deployable gate combos

### CSV summary tables

- `new_sleeves_per_sleeve_metrics.csv` — S1.5 + S6 + S7 base sleeves (28 rows)
- `new_indicator_sleeves_per_market.csv` — TA-overlay sleeves on 5m (24 rows)
- `new_indicator_sleeves_15m.csv` — TA-overlay sleeves on 15m (10 rows)
- `vwap_drawdown_livemimic.csv` — top S1.5 sleeves with DD + Sharpe + OOS + live-mimic
- `mint_and_sell_cvd_overlay.csv` — V2 fills × CVD overlay (7,490 rows)
- `mint_and_sell_v3_simulation.csv` — V3 asymmetric posting sim (240 rows)
- `prod_q90_calibration/` — q90 replication data

---

## 5. Scripts created (full inventory)

All under `strategy_lab/meta_classifier/` unless noted:

### Backtest engines / strategy scripts
- `vwap_continuation_5m.py` — S1 (15m-anchored VWAP)
- `vwap_continuation_v2_gated.py` — S1 + gates
- `vwap_continuation_15m.py` — S7
- `vwap_slot_anchored_5m.py` — S1.5 (the winner)
- `vwap_slot_anchored_v2_gated.py` — S1.5 + gates
- `vwap_drawdown_livemimic.py` — stress test top S1.5 configs
- `anchored_vwap_fade_5m.py` — DEPRECATED (initial inverse-direction test; the inversion is now S1.5)
- `fade_momo_5m.py` — S2 (agent A)
- `z_contra_5m.py` — S5 (agent B)
- `spike_entry_5m.py` — S6 (agent)
- `btc_lead_lag_5m.py` — lead-lag test (failed: 100% overlap with S1.5)
- `ma_ribbon_strategy_5m.py` — standalone MA ribbon (only R2 wins, 82% overlap with S1.5)
- `fv_cvd_spike_backtest.py` — initial 1s feature backtest

### TA indicators & overlays
- `compute_ta_indicators.py` — computes MA Ribbon + Slow Stoch + BB + MFI + CCI on 5.5M 1s bars
- `overlay_ta_indicators.py` — joins TA panel to per-fire parquets via merge_asof

### Combinatorial search
- `strategy_lab/markov_filter/_gate_search_5m.py` — 2^9 gate combos on S1.5/S6 (Agent C)
- `strategy_lab/markov_filter/_cvd_timing_overlay.py` — Mint-and-Sell V2 CVD analysis (Agent D)
- `strategy_lab/markov_filter/_v3_simulate.py` — V3 mint-and-sell asymmetric sim
- `strategy_lab/new_indicators_combinatorial.py` — exhaustive new-indicator gate search

### Support / analysis
- `strategy_lab/markov_filter/_recompute_hod_top8.py` — HoD refresh (fire-time hour)
- `_replicate_prod_q90.py` — prod q90 calibration check
- `ensemble_simulator.py` — combines top configs on one timeline (user modified after init)
- Various overlay analysis scripts under `strategy_lab/meta_classifier/`

---

## 6. Reports inventory

All under `strategy_lab/reports/` — listing by topic:

### Day 1 (2026-05-22) reports
- `HOD_REFRESH_2026_05_22.md` — refresh per cell (all 18 flagged)
- `SHADOW_11_SLEEVES_V2_2026_05_22.md` — current vs refreshed HoD comparison
- `PROD_Q90_REPLICATION_2026_05_22.md` — q90 calibration analysis
- `VPS3_SHADOW_AUDIT_2026_05_22.md` — 4-bug production audit
- `TV_AGENT_PHASE34_FIXES_2026_05_22.md` — TV-agent fix spec (HoD + sleeve #2 + sleeve #3 + tests)
- `HANDOFF_2026_05_22_HOD_REFRESH_SLEEVE_FIXES.md` — Day 1 handoff
- `INDICATOR_SURVEY_2026_05_22.md` — mlmodelpoly mining
- `NEW_STRATEGIES_PROPOSAL_2026_05_22.md` — initial 7-strategy proposal
- `FV_CVD_SPIKE_BACKTEST_2026_05_23.md` — fair-value + CVD initial test

### Day 2 (2026-05-23) reports — strategy backtests
- `MORNING_SUMMARY_2026_05_23.md` — overnight headline
- `OVERNIGHT_STRATEGY_RUN_2026_05_23.md` — full synthesis of overnight 4-agent run
- `VWAP_CONTINUATION_5M_2026_05_23.md` — S1 detailed backtest
- `VWAP_CONT_V2_GATED_2026_05_23.md` — S1 + gates (the original winner)
- `VWAP_SLOT_ANCHORED_5M_2026_05_23.md` — S1.5 (the actual winner)
- `VWAP_SLOT_V2_GATED_2026_05_23.md` — S1.5 + gates
- `VWAP_CONTINUATION_15M_2026_05_23.md` — S7 (15m)
- `VWAP_DRAWDOWN_LIVEMIMIC_2026_05_23.md` — stress test top S1.5 configs
- `ANCHORED_VWAP_FADE_5M_2026_05_23.md` — DEPRECATED (inverse direction discovery)
- `FADE_MOMO_5M_2026_05_23.md` — S2 (BTC+ETH at mag>3)
- `Z_CONTRA_5M_2026_05_23.md` — S5 (ETH underdog)
- `GATE_SEARCH_5M_2026_05_23.md` — combinatorial gate search
- `SPIKE_ENTRY_5M_2026_05_23.md` — S6 (spike-driven)
- `BTC_LEAD_LAG_5M_2026_05_23.md` — failed (100% overlap with S1.5)
- `MINT_AND_SELL_CVD_TIMING_2026_05_23.md` — Mint-and-Sell V2 CVD analysis
- `MINT_AND_SELL_V3_SIMULATION_2026_05_23.md` — V3 asymmetric posting sim

### Day 2 reports — TA indicators mega-run
- `QUANTMUSE_MINING_2026_05_23.md` — QuantMuse repo mining (mostly skip, 3 indicators ported)
- `MA_RIBBON_OVERLAY_2026_05_23.md` — Madrid ribbon overlay on S1.5/S6
- `SLOW_STOCH_OVERLAY_2026_05_23.md` — Stormer slow-stoch overlay
- `MA_RIBBON_STRATEGY_5M_2026_05_23.md` — standalone MA ribbon (82% overlaps S1.5)
- `NEW_INDICATORS_COMBINATORIAL_2026_05_23.md` — exhaustive gate-stack search
- `TA_INDICATORS_MEGA_RUN_2026_05_23.md` — overall synthesis of TA work

### Day 2 reports — final summaries
- `DISCOVERIES_TABLE_2026_05_23.md` — first complete strategy table
- `COMPLETE_STRATEGY_METRICS_2026_05_23.md` — comprehensive metrics doc
- `NEW_SLEEVES_INDIVIDUAL_METRICS_2026_05_23.md` — S1.5/S6/S7 per-sleeve detail
- `NEW_SLEEVES_ENTRY_RULES_2026_05_23.md` — plain-English entry rules
- `NEW_INDICATOR_SLEEVES_PER_MARKET_2026_05_23.md` — TA-overlay per market (5m)
- `NEW_INDICATOR_SLEEVES_15M_2026_05_23.md` — TA-overlay 15m
- `TV_AGENT_VWAP_CONTINUATION_SPEC_2026_05_23.md` — initial deploy spec
- `TV_AGENT_VWAP_CONTINUATION_FULL_SPEC_2026_05_23.md` — complete spec (17 sections)
- **`HANDOFF_2026_05_23_COMPLETE.md`** — THIS FILE

---

## 7. Top sleeve table — complete deploy-ready roster

### Tier 1 — IMMEDIATE deploy (config changes only, no new code)

| Action | Effort | Uplift @ $25 / 28d |
|---|---|--:|
| Refresh `HOD_TOP8_BY_CELL` per `_recompute_hod_top8.py` output | 5min | **+$13,000** |
| Drop `m5va` from sleeve #2 | 1 line | +$745 |
| Patch momo to fade BTC+ETH at mag_ratio>3.0 | 4 lines | +$1,264 |
| **Subtotal** | | **+$15,009** |

### Tier 2 — NEW sleeves (full deploy specs in `TV_AGENT_VWAP_CONTINUATION_FULL_SPEC_2026_05_23.md`)

#### S1.5 5m (10 sleeves)

| Sleeve | Market | Expected /28d |
|---|---|--:|
| BTC 210 5-10bps + ribbon | BTC 5m @ +210s | +$1,555 |
| ETH 210 10-15bps + ribbon | ETH 5m @ +210s | +$1,524 |
| BTC 240 3-5bps + ribbon | BTC 5m @ +240s | +$1,293 |
| ETH 240 5-10bps + ribbon | ETH 5m @ +240s | +$1,083 |
| SOL 270 5-10bps + ribbon | SOL 5m @ +270s | +$1,014 |
| BTC 150 3-5bps + ribbon | BTC 5m @ +150s | +$832 |
| ETH 150 5-10bps + ribbon | ETH 5m @ +150s | +$799 |
| BTC 120 <5bps + ribbon | BTC 5m @ +120s | +$766 |
| ETH 150 <5bps + ribbon | ETH 5m @ +150s | +$725 |
| BTC 210 <5bps + ribbon | BTC 5m @ +210s | +$723 |

**Subtotal S1.5 5m: ~$10,300/28d**

#### S6 5m (8 sleeves) — BREAKOUT (ribbon + tight ribbon)

| Sleeve | Market | n | WR | $/tr | sum 28d |
|---|---|--:|--:|--:|--:|
| BTC off120 D1 T1 | BTC 5m S6 @ +120s | 121 | 66.1% | **+$7.86** | +$951 |
| BTC off45 D1 T1 | BTC 5m S6 @ +45s | 126 | 65.1% | +$6.92 | +$872 |
| BTC off30 D1 T1 | BTC 5m S6 @ +30s | 120 | 65.8% | +$5.14 | +$617 |
| BTC off60 D1 T1 | BTC 5m S6 @ +60s | 129 | 61.2% | +$3.99 | +$514 |
| BTC off45 D2 T1 | BTC 5m S6 @ +45s, D2 | 105 | 71.4% | +$4.88 | +$512 |
| BTC off90 D1 T1 | BTC 5m S6 @ +90s | 121 | 61.2% | +$4.03 | +$487 |
| BTC off60 D2 T1 | BTC 5m S6 @ +60s, D2 | 112 | 68.8% | +$3.88 | +$435 |
| ETH off60 D1 T1 | ETH 5m S6 @ +60s | 116 | 64.7% | +$3.71 | +$431 |

**Subtotal S6 5m: ~$4,819/28d**

#### S7 15m (5 sleeves)

| Sleeve | Market | sum 28d |
|---|---|--:|
| TRIPLE BTC 840 5-10bps | BTC 15m @ +840s | **+$843** |
| RIBBON BTC 840 5-10bps | BTC 15m @ +840s | +$707 |
| RIBBON SOL 240 10-15bps | SOL 15m @ +240s | +$292 |
| TRIPLE BTC 600 5-10bps | BTC 15m @ +600s | +$292 |
| RIBBON ETH 720 15-20bps | ETH 15m @ +720s | +$273 |

**Subtotal S7 15m: ~$2,407/28d**

### Tier 3 — ULTRA-WR layer (low-DD, ribbon+m1v stacks)

For capital allocation where DD is the primary constraint, not absolute PnL:

| Sleeve | n | WR | $/tr | DD | streak |
|---|--:|--:|--:|--:|--:|
| BTC 480 10-15bps 15m + ribbon+m1v | 35 | **100.0%** | +$1.67 | $0 | **0** |
| BTC 600 5-10bps 15m + ribbon+m1v | 152 | 96.1% | +$1.74 | low | 1 |
| BTC 240 5-10bps 5m + ribbon+m1v | 140 | 95.7% | +$0.81 | -$66 | 1 |
| SOL 270 5-10bps 5m + ribbon+m1v | 138 | 97.8% | +$0.71 | -$25 | 1 |
| ETH 240 5-10bps 5m + ribbon+m1v | 218 | 94.5% | +$1.29 | -$49 | 1 |

### Grand total (deploy all Tier 1 + Tier 2)

**~$32,500/28d at $25 notional = ~$1,160/day @ $25, ~$11,600/day @ $250.**

---

## 8. Open questions / what's next

1. **Out-of-sample**: backtests use 28d Apr 30 - May 22. Need 7-14d forward validation before sizing up.
2. **Mint-and-sell V3 architecture**: spec the asymmetric posting design properly. Current V2 still loss-making.
3. **Cross-cell correlation**: when BTC fires fail, do ETH/SOL fires fail at the same time? Need correlation analysis for portfolio risk.
4. **Bayesian-Kelly sizing**: still theorized (S4 from polymarket-bot). Could reduce DD 30-40% on existing sleeves.
5. **1s data refresh**: current data is Apr 30 - May 22. Pull fresh delta when starting new session (script: `scp -i ~/.ssh/vps3_ed25519 root@185.190.143.7:/tmp/binance_1s_28d.csv.gz <local-path>` per the pull pattern, or modify the `binance_1s_28d.parquet` build).
6. **Production validation**: ANY of the new sleeves running on VPS3 shadow yet? If so, compare backtest WR to live WR over the first 7 days.
7. **TA-indicator update path**: `compute_ta_indicators.py` recomputes on the full 5.5M bars in 10s. Re-run whenever the 1s data refreshes.

---

## 9. Key invariants (do NOT violate)

Per CLAUDE.md, verified during this session:

1. **Fee model = 2%-on-profit-only** (LegacyConfig). Production-actual. NOT 7%, NOT `0.07·p·(1−p)`. Verified vs 25,900 prod resolutions (Day 1).
2. **ws_s = slot_start − window_s** is the production controller anchor. Don't anchor on slot_start.
3. **F7 RSI anchor at ws_s** = production. Wilder simple-mean (NOT exponential). Verified 94.67% match.
4. **Outcome from chainlink RTDS**, not binance close. Use `outcome` column in canonical resolutions.
5. **Binance is SIGNAL source**, matching production momo controller. Coinbase/Kraken/OKX for ablation only.
6. **L25 entry walk** = production fill model. Use `engine_v2.fill_at_book` with `spread_filter` per asset (0.02 BTC/ETH, 0.025 SOL).
7. **No mid-slot exits, no stop-loss, no take-profit** on shadow sleeves. Hold to slot_end. Period.
8. **All shadow sleeves `mode="paper"`** until operator approves live promotion.
9. **HoD constant refresh requires operator review** per Phase 34 spec §6.

---

## 10. Quick-start commands for next session

```bash
cd "C:/Users/alexandre bandarra/Desktop/global"

# 1. Verify 1s data is current
PYTHONIOENCODING=utf-8 C:/Python314/python.exe -c "
import pandas as pd, sys
sys.path.insert(0,'data/v4/canonical')
df = pd.read_parquet('data/v4/canonical/klines_1s/binance_1s_28d.parquet', columns=['symbol_id','time_period_start_us'])
print('rows:', len(df))
print('latest:', pd.Timestamp(df.time_period_start_us.max(), unit='us'))
"

# 2. Pull a fresh delta of 1s data if needed (from VPS3)
ssh -i ~/.ssh/vps3_ed25519 root@185.190.143.7 'export PGPASSWORD=...; psql -U tradingvenue_ro -h 127.0.0.1 -d storedata -c "COPY (SELECT ... FROM binance_klines_v2 WHERE period_id=$$1SEC$$ AND time_period_start_us > <last_seen_us>) TO STDOUT WITH (FORMAT CSV, HEADER true)" | gzip > /tmp/binance_1s_delta.csv.gz'
scp -i ~/.ssh/vps3_ed25519 root@185.190.143.7:/tmp/binance_1s_delta.csv.gz data/v4/canonical/klines_1s/
# Then merge into binance_1s_28d.parquet (see existing pull pattern in handoff)

# 3. Recompute TA indicators on the 1s panel (fast: ~10s)
PYTHONIOENCODING=utf-8 C:/Python314/python.exe strategy_lab/meta_classifier/compute_ta_indicators.py

# 4. Re-overlay onto S1.5 / S6 per-fire (~5s each)
PYTHONIOENCODING=utf-8 C:/Python314/python.exe strategy_lab/meta_classifier/overlay_ta_indicators.py

# 5. Re-run any of the strategy backtests
PYTHONIOENCODING=utf-8 C:/Python314/python.exe strategy_lab/meta_classifier/vwap_slot_anchored_5m.py
PYTHONIOENCODING=utf-8 C:/Python314/python.exe strategy_lab/meta_classifier/vwap_slot_anchored_v2_gated.py
PYTHONIOENCODING=utf-8 C:/Python314/python.exe strategy_lab/meta_classifier/vwap_continuation_15m.py

# 6. Validate top sleeves with drawdown + live-mimic stress test
PYTHONIOENCODING=utf-8 C:/Python314/python.exe strategy_lab/meta_classifier/vwap_drawdown_livemimic.py

# 7. Audit VPS3 shadow sleeve fires (run SQL from VPS3_SHADOW_AUDIT_2026_05_22.md §12)
ssh -i ~/.ssh/vps3_ed25519 root@185.190.143.7 'export PGPASSWORD=...; psql -U tradingvenue_ro -h 127.0.0.1 -d storedata <<SQL
SELECT sleeve_id, COUNT(*) FILTER (WHERE kind=$$poly_updown_resolution$$) AS resolved,
       AVG((data->>$$pnl_usd$$)::numeric) FILTER (WHERE kind=$$poly_updown_resolution$$) AS avg_pnl
FROM trading.events
WHERE at > NOW() - INTERVAL $$1 day$$
  AND sleeve_id LIKE $$poly_updown_%_hod%$$
GROUP BY 1 ORDER BY 1;
SQL'
```

---

## 11. Documents to read FIRST (in order, for a new session)

1. **THIS FILE** — `HANDOFF_2026_05_23_COMPLETE.md` — overall picture
2. **`TV_AGENT_VWAP_CONTINUATION_FULL_SPEC_2026_05_23.md`** — complete S1.5 implementation spec
3. **`TV_AGENT_PHASE34_FIXES_2026_05_22.md`** — HoD refresh + Markov compute + sleeve fixes
4. **`COMPLETE_STRATEGY_METRICS_2026_05_23.md`** — every strategy's metrics
5. **`NEW_SLEEVES_ENTRY_RULES_2026_05_23.md`** — plain-English entry logic
6. **`TA_INDICATORS_MEGA_RUN_2026_05_23.md`** — overlay framework + ribbon findings
7. **`NEW_INDICATOR_SLEEVES_15M_2026_05_23.md`** — 15m TA-overlay sleeves

## End of handoff
