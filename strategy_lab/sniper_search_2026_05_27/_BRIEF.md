# Sniper Search Brief — 2026-05-27

Shared brief for per-market sniper search agents. Read this FIRST before doing any work.

---

## 1. Mission

Find SNIPER sleeves: trade LESS, win MORE, keep DD small. Course-correct from the
prior "shotgun" deploy roster (4,894 fires/32d, 36-trade losing streaks, $1,816 max DD)
to a sniper roster.

**Reference profile = BTC S15 hybrid_v1** (what every new sleeve should look like):
- n=1,753 (5.5/day, but we can go lower — see target)
- WR 86.3%, $/tr +$3.12
- Max DD only $269 at $25 stake
- Max loss streak only 6
- Sharpe 1.26

## 2. Target profile — EVERY new candidate MUST meet ALL of these

| Metric | Threshold |
|---|---|
| n / 32d | **50-500** (1.5-15/day) — STRICTLY n_cap 500 |
| WR on lockbox | **≥ 75%** |
| $/tr at $25 stake | **≥ $3** |
| Max DD at $25 stake | **≤ $300** |
| Max loss streak | **≤ 6** |
| Sharpe (daily approx) | **≥ 2.0** |
| Bootstrap p (lockbox, 1000-iter) | **≤ 0.05** |

If a candidate misses ANY threshold, report it as a near-miss but do NOT include in top 5.

## 3. User instruction — TREAT EACH MARKET INDIVIDUALLY

Do NOT try to find a single gate stack that works across markets. A sleeve that works
for SOL 15m and not BTC 15m is FINE. Per-market specialization is encouraged. Cross-market
correlation will be evaluated AFTER your work, by a separate aggregator agent.

You are free to test:
- Pre-window entries (fire BEFORE slot starts, ws_s anchor or ws_s-30s)
- Beginning of window (offset 0-60s, UNDER-tested previously)
- Mid-window (60-150s, 90-150s)
- Late window (120-300s, 150-240s)
- High-bar gate stacks (6-8 strict gates, deliberately push n down)

Priority: **better DD + better $/tr** over any other dimension. n can be small.

## 4. Conventions (DO NOT VIOLATE)

- **Timestamps**: UTC microseconds (`*_us` cols). Never localize.
- **ws_s anchor**: `ws_s = slot_start - window_s`. Use `slug_to_ws_s(slug, tf)` from `data/v4/canonical/load.py`. NOT slot_start.
- **F7 RSI anchor**: at ws_s, Wilder simple-mean (NOT exponential). See CLAUDE.md verification.
- **Causal lookup**: features at `fire_us` MUST use bars with `ts_us ≤ fire_us - 1_000_000` (1s epsilon for 1s panels). For 5m/15m panels, `ts_us` must be bar END (Bug #2 fixed in `_v2_fixed` panels).
- **Outcome truth**: chainlink `outcome` column from canonical resolutions. Never derive from binance close.
- **Fee model**: `engine_v2.LegacyConfig` (2%-on-profit-only, winning leg). Matches production.
- **L25 entry walk**: `engine_v2.fill_at_book(books_idx, slug, "UP"/"DOWN", fire_us, cfg, spread_filter)`.
  - `spread_filter=0.02` for BTC/ETH
  - `spread_filter=0.025` for SOL
- **No mid-slot exits, no SL, no TP** on shadow sleeves — hold to slot_end.
- **DD calc**: MUST use SLEEVE'S actual gated fires (not ungated). That was Bug #4.
- **Slug overlap**: do NOT need to worry about it for your individual market's candidates. Aggregator handles cross-market dedup.

## 5. Data paths (all relative to `C:\Users\alexandre bandarra\Desktop\global`)

### Fresh fire universe — USE THESE (33d coverage Apr 24 → May 26)
- OOS fires: `data/v4/canonical/_results/_full_window_v3_2026_05_27/oos_fires_{ASSET}_{TF}_full_v3.parquet`
  - `_full_v3.parquet` and `_v3_fixed.parquet` are BYTE-IDENTICAL (no filtering needed; offsets already canonical)
  - 5m grid: {30, 60, 90, 120, 150, 180, 210, 240, 270} (9 offsets, ~16k fires per offset for BTC)
  - 15m grid: {60, 120, 240, 360, 480, 600, 720, 840} (8 offsets, ~5k fires per offset for BTC)
- **SOL 15m EXISTS** in this v3 build (34,886 fires — was completely missing before)

### Fire counts per market (FULL 33d window)
| Asset/TF | Fires | Won.mean |
|---|---|---|
| BTC 5m | 144,061 | 48.7% |
| ETH 5m | 133,497 | 48.5% |
| SOL 5m | 101,500 | 48.3% |
| BTC 15m | 43,456 | 48.4% |
| ETH 15m | 39,546 | 48.6% |
| SOL 15m | 34,886 | 48.8% |

### Fields in v3 fires
`asset, slug, tf, slot_start_us, slot_end_us, ws_s, fire_offset_s, fire_us, strike_price, settle_price, outcome, direction, pnl_legacy_usd, won, entry_vwap` + TA/regime gates already joined (rf_*, ribbon_*, stoch_*, bb_*, mfi_*, cci_*, tr_*, plus computed gates).

### Bug-fixed feature panels (USE THESE — never the originals)
- Regime: `data/v4/canonical/_results/regime_panel_{TF}_v2_fixed.parquet` (covers Apr 28 → May 25, 28d)
- SMS: `data/v4/canonical/_results/sms_panel_{TF}_v2_fixed.parquet` (covers May 1 → May 22, 22d)

### ⚠️ PANEL COVERAGE REALITY (panel windows are NOT all 33d)
| Panel | Window | Days |
|---|---|---|
| microprice_panel | Apr 24 → May 25 | 31.7 ⭐ |
| regime_panel_*_v2_fixed | Apr 28 → May 25 | 28.0 |
| master_gate_features_v2 | May 1 → May 25 | 24.8 |
| vol_hurst_at_fire_{5m,15m} | Apr 30 → May 22 | 23.0 |
| microstructure_panel | Apr 30 → May 23 | 23.0 |
| ta_indicators_1s, range_filter_1s, traders_reality_1s | May 1 → May 23 | 22.1 |
| hawkes_panel, vpin_panel, lee_mykland_panel | May 1 → May 23 | 22.1 |
| sms_panel_*_v2_fixed | May 1 → May 22 | 22.0 |

Effective search window = INTERSECTION of fires + panels you use. If you use any 1s-derived
gate (TA, RF, TR, hawkes, vpin, LM), effective window is May 1 → May 22 = **~22d**.
If you stick to microprice + regime + master_gate_features, you get **24.8d**.

**Practical guidance**: design your gate stacks to use master_gate_features_v2 (precomputed
gates with 24.8d coverage) + microprice (31.7d) + regime_v2_fixed (28d) as the PRIMARY
features. Other panels are bonus. The fire universe gives 33d but you'll lose the tail
(May 23-26) and head (Apr 24-30) for any feature that doesn't cover it.

**3-way split** on whatever your effective window is:
- 22d intersection: train 14d / val 4d / lockbox 4d
- 24.8d intersection: train 15d / val 5d / lockbox 4.8d
- 28d intersection (regime-only stacks): train 18d / val 6d / lockbox 4d

### Clean feature panels (no fixes needed)
- Microprice: `data/v4/canonical/_results/microprice_panel.parquet` ⭐ 31.73d coverage
- Microstructure: `data/v4/canonical/_results/microstructure_panel.parquet`
- TA indicators 1s: `data/v4/canonical/_results/ta_indicators_1s.parquet`
- Range filter 1s: `data/v4/canonical/_results/range_filter_1s.parquet`
- Traders Reality 1s: `data/v4/canonical/_results/traders_reality_1s.parquet`
- Vol/Hurst: `data/v4/canonical/_results/vol_hurst_at_fire_5m.parquet` (5m only)
- Lee-Mykland: `data/v4/canonical/_results/lee_mykland_panel.parquet`
- Hawkes: `data/v4/canonical/_results/hawkes_panel.parquet`
- VPIN: `data/v4/canonical/_results/vpin_panel.parquet`
- Master gate features (37 gates × 77k fires): `data/v4/canonical/_results/master_gate_features_v2.parquet`
- Hybrid features (full 158-col matrix): `data/v4/canonical/_results/hybrid_features_{TF}.parquet`
- Per-fire joined: `data/v4/canonical/_results/{s15,s6,v15m}_joined_all.parquet`

### Canonical loaders
```python
import sys; sys.path.insert(0, "data/v4/canonical")
from load import (
    load_resolutions,            # chainlink-only
    load_klines_1s, load_klines, load_klines_asof,
    load_chainlink_rtds,
    load_orderbook_l25_streaming,  # filter by slugs to bound memory
    load_tier1_entries,
    slug_to_ws_s, add_ws_s, ret_2m_at_ws,
    asof_strict,
)
```

### Backtest engine
```python
from strategy_lab.engine_v2 import LegacyConfig, fill_at_book, hold_pnl, book_event_count
cfg = LegacyConfig()  # 2%-on-profit-only — matches production
fill = fill_at_book(books_idx, slug, "Up", fire_us, cfg=cfg, spread_filter=0.02)  # 0.025 for SOL
pnl = hold_pnl(fill, won=True, cfg=cfg)
```

## 6. Gate vocabulary (the atoms — see `strategy_lab/meta_classifier/hybrid_join_and_gates.py`)

### R1 base (16)
g_rf_with, g_ribbon_agrees, g_stoch_with, g_mfi_with, g_cci_with, g_bb_pos_with,
g_tr_above_ema50, g_tr_above_ema200, g_tr_above_ema800, g_tr_above_pp,
g_tr_stack_with, g_tr_within_adr, g_tight_ribbon, g_within_dev, g_dev_extreme, g_markov_with

### R3 (8)
g_vol_expanding, g_vol_high, g_vol_contracting, g_hurst_trending,
g_flow_with_and_no_whale, g_coinbase_basis_extreme_against,
g_hl_liq_cascade_with, g_book_slope_steep_against

### R4 (6) — `g_trend_slope_with` MUST be rebuilt from `_v2_fixed` regime panel
g_trend_slope_with ⚠️, g_trend_slope_strong_with, g_imb5_strong_with,
g_queue_top_high, g_imb_change_with, g_vwap_ge_50_le_85

### R5 (6)
g_mp_no_extreme ⭐ universal tradability, g_mp_change_with, g_mp_skew_with,
g_lm_high_stat, g_hawkes_imbalance_with, g_hy_cb_with_dir

### R7 recalibrated thresholds (use these as DEFAULTS)
- g_mp_no_extreme: 50 → 100-150 bps (looser)
- g_hawkes_imbalance_with: 0.3 → 0.1-0.2 (looser)
- g_hurst_trending: 0.55 → 0.50 (looser)
- g_vol_contracting: 0.7 → 0.85 (looser)

## 7. Approach paths — TEST ALL of these for your market

### Path A: Pre-window entries (ws_s anchor)
Build features at `ws_s` and `ws_s - 30s`. Specific candidates:
- F7 RSI extreme (< 30 or > 70) at ws_s + Markov M1V_va == 2 (bull regime)
- HoD constant + cross-asset RF unanimity at ws_s
- Pre-window dev_bps_vwap (binance VWAP over 60s before slot_start)
- L25 microprice skew on UP vs DOWN token at ws_s-30s
- Hawkes λ_imbalance over previous 300s

### Path B: Beginning of window (offset 0-60s)
R6 Agent LL found BTC S6 0-60s + 12 gates → WR 79.9%, $/tr +$8.03, n=219.
This was ONE cell, barely explored. Re-mine systematically.

### Path C: High-bar gate stacks (6-8 strict gates)
Stack the "rare" gates: g_dev_extreme + g_lm_high_stat + g_xa_all_with_bet +
g_hl_liq_cascade_with + g_tr_stack_full_with. Aim n=50-200, WR 85%+.

### Path D: Master combinatorial with n_cap≤500
Reuse `strategy_lab/master_combinatorial_2026_05_26/` logic but constrain:
```python
greedy_search(max_n=500, min_wr=0.75, min_dpt=3.0, max_loss_streak=6, max_dd=300)
```

### Path E: Per-offset bin sweep
Grid: offsets [0, 30, 60, 90, 120, 150, 180, 210, 240, 270, 300] for 5m.
For each offset bin, run combinatorial under sniper constraint.

## 8. Validation protocol

- **3-way split chronological**: train 20d / val 7d / lockbox 5d
- **Bootstrap p**: 1000 iterations of daily-clustered bootstrap on lockbox PnL
- **Surviving requirement**: all 7 metrics in §2 pass on LOCKBOX (not just full window)
- DD computed on the gated fires of THIS candidate (not ungated)
- Use `engine_v2.LegacyConfig` for fee model

## 9. Output (write to your working dir: `strategy_lab/sniper_search_2026_05_27/{market_slug}/`)

### Required files:
1. `top_5_candidates.csv` — columns:
   `sleeve_id, anchor (ws_s|offset_NMs), gate_stack, n_train, n_val, n_lockbox, wr_train, wr_val, wr_lockbox, dpt_25, sum_25_28d, max_dd_25, loss_streak, sharpe, bootstrap_p_lockbox`

2. `SNIPER_{MARKET}_REPORT.md` — sections:
   - Top 3-5 candidates with full metric tables
   - Per-day fire histogram (1.5-15/day band)
   - Cumulative PnL plot (saved as PNG)
   - Bootstrap distribution stats
   - **Failed approaches** (honest reporting — what didn't work and why)
   - Confidence: LOW/MED/HIGH per candidate

3. `cumulative_pnl_{candidate_id}.png` — for each top candidate

4. Code files: any new search scripts in `scripts/`

### Return to orchestrator (concise summary, <300 words):
- Market analyzed + # fires in universe
- # candidates meeting full sniper profile
- Best candidate metrics: gate stack + n + WR + $/tr + DD + loss streak + bootstrap p
- Top surprise/failure (1 line)
- Confidence rating
- Path to report file

## 10. What NOT to do (confirmed failures)

- Don't test PVSRA standalone (-37pp WR)
- Don't use MLOFI (RMSE claim doesn't transfer to Polymarket)
- Don't use VPIN as skip gate (wrong sign)
- Don't use LightGBM as primary (0/6 lockbox pass)
- Don't use Avellaneda-Stoikov uncertainty (overlaps vol_regime, wrong sign)
- Don't trust 22d backtests alone — always lockbox
- Don't sum sleeve PnL across overlapping slugs (#1 bug across prior sessions)
- Don't use the original (non-v2_fixed) regime / sms panels — leaky
- Don't anchor on slot_start — use ws_s

## 11. Reference reading (skim these for context if helpful)

- `CLAUDE.md` (root) — conventions
- `strategy_lab/reports/HANDOFF_2026_05_26_COMPLETE.md` — full prior session handoff
- `strategy_lab/reports/MASTER_DEPLOY_SPEC_2026_05_26.md` §A.5 — full gates spec
- `strategy_lab/meta_classifier/hybrid_join_and_gates.py` — gate definitions
- `strategy_lab/meta_classifier/hybrid_backtest.py` — `gate_search()`, `walk_forward_split()`
- `strategy_lab/master_combinatorial_2026_05_26/` — exhaustive gate search template
- `strategy_lab/overlap_audit_2026_05_26/` — slug-overlap methodology (for reference only)
