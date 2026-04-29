# 17 — Expansion Plan: Closing the Pine / Pool Gap

**Date:** 2026-04-24
**Pine inventory:** 81 shipped Pine scripts in [strategy_lab/pine/](../../strategy_lab/pine/)
**Current pool:** 28 cells (see report 15)
**Gap:** **53 shipped Pine strategies not in the portfolio-hunt pool.**

## Pine-script inventory by family (81 total)

| Family | Coins covered (Pine) | Currently in pool? |
|---|---|:---:|
| **V4C/V22/V23 RangeKalman L+S** | BTC (2h), ETH (1h V17), SOL (2h), AVAX (4h) | ❌ — all missing |
| **V2B/V3E Volume Breakout** | SOL, generic | ❌ |
| **V3B ETH ADX Gate** | ETH | ❌ |
| **V22 Keltner+ADX L+S** | TON | ❌ (no TON data) |
| **V23 BBBreak L+S** | ETH, SOL, LINK, DOGE, INJ, SUI, BTC | ⚠️ partial (ETH, SOL, DOGE, BTC) |
| **V24 Regime Router 2h** | ETH | ❌ (no 2h data) |
| **V24 RSIBBScalp 15m** | LINK, DOGE, TON | ❌ (15m) |
| **V25 MTFConf 1h / 30m** | AVAX, SOL, SUI | ❌ (1h/30m) |
| **V25 Seasonal 30m/1h** | DOGE, AVAX | ❌ |
| **V26 ATR Squeeze / Liq Sweep** | AVAX, TON | ❌ |
| **V27 HTF Donchian 4h** | BTC, ETH, SOL, DOGE, SUI | ⚠️ only DOGE/SOL as `HTFD_*` (V34 variant) |
| **V29 Lateral_BB_Fade** | BTC, ETH, SOL, LINK, AVAX, INJ, SUI | ⚠️ have 3/7 |
| **V29 Trend_Grade_MTF** | INJ, LINK, AVAX, TON | ❌ entire family |
| **V29 Regime Switch** | BTC, ETH, SUI | ⚠️ have 2/3 (no SUI) |
| **V30 CCI / STF / TTM / VWZ / CRSI** | 5 coins each | ✅ mostly covered |
| **V34 BBBreak / Donchian 4h** | AVAX, TON, LINK | ⚠️ partial (only via existing BB_*) |

## The biggest gaps (by shipped-but-not-tested value)

### 1. V22 RangeKalman L+S — **the documented per-asset winners**
Reports V22_FINAL_WINNERS.md claim:
- BTC 2h alpha=0.07 rng_len=300 → CAGR **+85%** Sharpe 1.62
- ETH 1h rng_len=400 rng_mult=2.5 → CAGR **+97%** Sharpe 1.64
- SOL 2h rng_len=250 → CAGR **+105%** Sharpe 1.73

**None tested yet.** Blocker: 2h data missing. **Fix:** resample 1h→2h on the fly (`df.resample('2h').agg(OHLCV)`). Python function lives in `strategies_v4.py::v4c_range_kalman` — need to map the V22 kwarg names to actual signature.

### 2. V27 HTF Donchian 4h — **used in V28 P2 reference**
V28 P2 = SUI + SOL + ETH V27 Donchian = Sharpe 1.97 / CAGR 156%. I have `sig_htf_donchian_ls` (from V34) on DOGE/SOL, but V27 uses a different specific config (likely shorter lookback + tighter filter). Worth adding V27-specific on all 5 coins.

### 3. V29 Lateral_BB_Fade — **"2024+ regime is lateral" winner**
Passes OOS on 7 coins per V29_FINAL_REGIME report, with **OOS Sharpe > IS Sharpe on every one.** That's an unusual signature suggesting genuine regime shift. I have BTC/ETH/SOL — **missing LINK, AVAX, INJ, SUI**. Adding these could push portfolio min-year metrics further up (V29 says SOL+ETH Lateral as third sleeve = +124% min-year blend).

### 4. V29 Trend_Grade_MTF — **new family entirely**
Grades trend quality 0-4, enters only when grade ≥ threshold. Passes OOS on INJ, LINK, AVAX, TON. **Zero coverage** in my pool.

### 5. V38/V39 SMC family — **Smart Money Concepts (8 signal types)**
`sig_bos`, `sig_choch`, `sig_fvg`, `sig_fvg_fade`, `sig_liquidity`, `sig_ob`, `sig_order_block`, `sig_smc_confluence`, `sig_bos_continuation`, `sig_choch_reversal`, `sig_fvg_entry`, `sig_liquidity_sweep_fade`, `sig_ob_touch`, `sig_fvg_fill_fade`. I scanned these (they appear in `legacy_scan.json`) but haven't pulled any into the pool. Entire SMC family = 12+ potential cells.

### 6. V23 BBBreak on AVAX, INJ, SUI, LINK — **V28 P2 ingredient**
I have BB on BTC/ETH/SOL/DOGE. Missing: AVAX BB (not in legacy scan?), LINK BB, INJ BB, SUI BB. Worth adding — they're the V23 portfolio core.

## Data-blocked cells

Can't run until fetcher adds the parquet:

- **SUI** (all SUI_*) — blocks SUI BBBreak, SUI V27 Donchian, SUI V29 LateralBB, SUI V29 RegimeSwitch, SUI V30 CCI/TTM/STF, SUI V25 MTFConf
- **TON** (all TON_*) — blocks TON Keltner+ADX (V22 winner), TON V24 Scalp, TON V26 LiqSweep, TON V29 TrendGrade, TON V30 all 4 families, TON V34 BB+Donchian
- **Non-native 2h** — blocks V22 RK BTC/SOL (need 1h→2h resample)
- **Non-native 30m** — blocks SUI MTFConf 30m, DOGE Seasonal 30m (can resample from 15m)
- **Non-native 1h on AVAX** — have AVAX 4h and below, need to confirm 1h available

## Proposed expansion — 4 phases

### Phase A (quick wins, ~1 turn)
Add cells that use existing parquet + already-scanned functions:

| Family | Cells to add |
|---|---|
| V29 Lateral_BB_Fade | AVAX, INJ, LINK (sig_lateral_bb_fade) — 3 cells |
| V29 Trend_Grade_MTF | INJ, LINK, AVAX (sig_trend_grade) — 3 cells |
| V30 VWZ | BTC, SOL, AVAX, LINK — 4 cells (have ETH/DOGE/INJ only) |
| V30 TTM | ETH, LINK, INJ — 3 cells (have BTC/SOL/AVAX/DOGE) |
| V30 STF | DOGE — 1 cell |
| V30 CCI | DOGE — 1 cell |
| V27 Donchian via V34 `sig_htf_donchian_ls` | BTC, ETH, AVAX, LINK, INJ — 5 cells |

**Subtotal: ~20 new cells** — pool grows from 28 → ~48. Runtime: ~5 min for equity curves + a few seconds per combo. Combo count: C(48,2)+C(48,3)+C(48,4) = 1128 + 17296 + 194580 = ~213k combos. Ranker handles it in ~2 min.

### Phase B (medium, ~1 turn)
Add SMC family + V23 BB gaps:

- `sig_bos_continuation`, `sig_choch_reversal`, `sig_fvg_entry`, `sig_ob_touch`, `sig_smc_confluence` on BTC/ETH/SOL/AVAX/LINK — **25 cells**
- V23 BBBreak on AVAX, INJ, LINK — **3 cells** (need to check if `sig_bbbreak` module has V23-tuned params — probably default works)

**Subtotal: ~28 more cells** → pool ~76. Large combo space; may want to restrict to size ≤ 3 sleeves for the hunt.

### Phase C (infrastructure)
Unblock the data-dependent cells:

1. **Fetch SUI + TON** from Binance (parquet), partition the same way as existing coins. Fetcher script exists: `fetch_binance_multi.py`. Single command.
2. **Resample 2h on the fly** inside engine.load or a wrapper — enables V22 RK winners.
3. **Resample 30m** for V24/V25 scalp/seasonal families.

Each is ~0.5 turns. Total ~1-2 turns.

### Phase D (quality + tuning)
Once the pool is comprehensive (~80-100 cells):

1. **Run canonical portfolio hunt** over the expanded pool (size 2/3/4/5).
2. **Apply per-year consistency gate pre-hunt** — drop cells with fewer than 5/6 positive years from consideration. Shrinks the useful pool and makes hunt results more robust.
3. **Re-audit the new top-3 portfolios** through the canonical 5-test battery.
4. **Target:** find an 8/8 portfolio (no failing gates) via better diversification.

## Recommended next move

**Phase A** — highest leverage, lowest risk, no new infrastructure. I'll extend `run_portfolio_hunt.py` with ~20 new cells, rerun equity builds, rerun ranker. Expected outcome:

- Pool expands 28 → ~48 cells
- Blend space grows ~10×
- V29 Lateral_BB_Fade additions should unlock new high-Sharpe blends (per V29 report's OOS > IS pattern)
- V27 Donchian cross-coin will likely replace one of STF_SOL / STF_AVAX in some top blends

Say **"phase A"** to execute. Or **"phase B"** to skip to SMC + BB expansion. Or **"fetch SUI TON"** if you want to unblock the V22 RangeKalman winners and the V28-reference SUI BBBreak first.

## Files reviewed

- [strategy_lab/pine/](../../strategy_lab/pine/) — 81 Pine scripts
- [strategy_lab/legacy_scan.json](../../strategy_lab/legacy_scan.json) — 112 scanner-discovered signal functions
- Current pool: [docs/research/phase5_results/perps_portfolio_cells.csv](phase5_results/perps_portfolio_cells.csv)
