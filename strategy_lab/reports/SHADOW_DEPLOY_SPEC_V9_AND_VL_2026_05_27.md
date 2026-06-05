# Shadow Deploy Spec — V9 + VL (Poly Flow + HL Cascade + Spread-Loose Variants) — 2026-05-27

**Status:** SPEC — candidate sleeves for shadow evaluation
**Combined batch size:** **21 new sleeves** (10 V9 + 11 VL)
**Author:** strategy-lab research agents (V9 sleeve search + spread-loosen sims)
**Date:** 2026-05-27

**Prerequisite reading:**
- `strategy_lab/reports/NEW_GATES_RESEARCH_2026_05_27.md` — gate findings (B1/B2/B3 poly flow, A2 HL cascade)
- `strategy_lab/reports/HL_GATES_REFINEMENT_2026_05_27.md` — HL threshold refinement
- `strategy_lab/reports/SHADOW_DEPLOY_SPEC_UNIFIED_V6_V7_V8_2026_05_27.md` — existing 56-sleeve roster
- `strategy_lab/reports/SPREAD_LOOSEN_SIM_*` — per-sleeve loosen impact (4 files: BTC 5m / ETH / SOL 5m / SOL 15m)

---

## 📋 Combined batch summary

| Round | Count | Purpose |
|---|---:|---|
| **V9** (new gates) | **10** | New sleeves using Polymarket flow + HL cascade gates |
| **VL** (spread-loose variants) | **11** | Copies of existing sleeves with looser spread_filter (A/B test) |
| **TOTAL** | **21** | Brings combined roster to 77 (was 56) |

V9 sleeves use NEW gates that need to be added to the TV gate library. VL sleeves use EXISTING gates only — they're just copies with a different `spread_filter` value.

---

## 0. Engine constants (UNCHANGED from V8/V9)

```
notional_default_usd  = 25.0     (operator at $5 ramp-start currently)
fee_model             = legacy_2pct_profit
spread_filter_btc     = 0.020
spread_filter_eth     = 0.020
spread_filter_sol     = 0.025
window_s_5m           = 300
window_s_15m          = 900
fill_engine           = L25_book_walk (via paper.get_orderbook_snapshot 3-tier)
fill_min_book_events  = 25
subsample_1hz         = False        # MANDATORY native 10Hz
hold_to               = slot_end_us
exit_policy           = HOLD_TO_SLOT_END
mode                  = paper
fill_time_veto        = g_book_supports_stake
```

---

## 1. Anchor conventions (UNCHANGED)

- `ws_s = slot_start_s - window_s`
- `fire_us = (ws_s + offset_s) × 1_000_000`
- Outcome truth: `outcome` column from `load_resolutions()`

---

## 2. New V9 gate functions

These 4 gate functions MUST be added to `/opt/tradingvenue/backend/app/strategies/polymarket/sniper_v5_gates.py` (or equivalent) before V9 sleeves can run. VL sleeves do NOT need new gates.

### 2.1 — B1: Polymarket Flow Aligned

```python
def g_b1_poly_flow_aligned(
    slug: str,
    fire_us: int,
    direction: str,           # "UP" or "DOWN"
    asset_trades: pd.DataFrame,    # canonical trades_polymarket/{asset}.parquet pre-loaded
    window_s: int = 60,
    thresh_shares: float = 500.0,
) -> bool:
    """Polymarket aggressor flow ALIGNED with direction in window pre-fire.

    Signal: large buy pressure on the same side as our bet = market
    participants confirming the move.

    Net flow = (outcome_buys - outcome_sells) for our direction, in shares.

    Asset-specific:
    - SOL: primary signal (+9.1pp lift at $500 threshold, n=788)
    - BTC: weaker (+2.6pp at $1k), prefer B2/B3
    - ETH: marginal, not recommended as primary
    """
    t_start = fire_us - window_s * 1_000_000
    w = asset_trades[
        (asset_trades['slug'] == slug) &
        (asset_trades['timestamp_us'] >= t_start) &
        (asset_trades['timestamp_us'] < fire_us)
    ]
    if len(w) == 0:
        return False
    direction_str = 'Up' if direction == 'UP' else 'Down'
    dir_trades = w[w['outcome'] == direction_str]
    net_flow = (
        dir_trades[dir_trades['side'] == 'buy']['size'].sum() -
        dir_trades[dir_trades['side'] == 'sell']['size'].sum()
    )
    return float(net_flow) > thresh_shares
```

### 2.2 — B2: Polymarket Flow Contrarian

```python
def g_b2_poly_flow_contrarian(
    slug: str,
    fire_us: int,
    direction: str,
    asset_trades: pd.DataFrame,
    window_s: int = 60,
    thresh_shares: float = 2000.0,
) -> bool:
    """Polymarket aggressor flow OPPOSING direction in window pre-fire.

    BTC: contrarian signal IS positive (+10.97pp aggregated, strongest for DOWN fires)
    SOL: contrarian is ANTI-signal (-18.5pp). DO NOT add as positive gate to SOL sleeves.
    ETH: mildly positive at $500 (+4.6pp)
    """
    t_start = fire_us - window_s * 1_000_000
    w = asset_trades[
        (asset_trades['slug'] == slug) &
        (asset_trades['timestamp_us'] >= t_start) &
        (asset_trades['timestamp_us'] < fire_us)
    ]
    if len(w) == 0:
        return False
    opp_str = 'Down' if direction == 'UP' else 'Up'
    opp_trades = w[w['outcome'] == opp_str]
    opp_flow = (
        opp_trades[opp_trades['side'] == 'buy']['size'].sum() -
        opp_trades[opp_trades['side'] == 'sell']['size'].sum()
    )
    return float(opp_flow) > thresh_shares
```

### 2.3 — B3: Polymarket Flow Absolute (direction-agnostic)

```python
def g_b3_poly_flow_abs(
    slug: str,
    fire_us: int,
    asset_trades: pd.DataFrame,
    window_s: int = 60,
    thresh_shares: float = 500.0,
) -> bool:
    """Any strong directional flow (either side) in window pre-fire.

    Signal: active price discovery → trend signals more reliable.
    SOL +13.7pp at $500; ALL +8.5pp at $2k.
    Direction-agnostic — combine with directional gates.
    """
    t_start = fire_us - window_s * 1_000_000
    w = asset_trades[
        (asset_trades['slug'] == slug) &
        (asset_trades['timestamp_us'] >= t_start) &
        (asset_trades['timestamp_us'] < fire_us)
    ]
    if len(w) == 0:
        return False
    up = w[w['outcome'] == 'Up']
    dn = w[w['outcome'] == 'Down']
    up_net = up[up['side']=='buy']['size'].sum() - up[up['side']=='sell']['size'].sum()
    dn_net = dn[dn['side']=='buy']['size'].sum() - dn[dn['side']=='sell']['size'].sum()
    return (abs(float(up_net)) + abs(float(dn_net))) > thresh_shares
```

### 2.4 — A2: HL Short Cascade (BTC only)

```python
def g_a2_hl_short_cascade(
    fire_us: int,
    asset_coin: str,           # "BTC"
    hl_short_proxy: pd.DataFrame,
    window_s: int = 300,
    thresh_usd: float = 100_000.0,
) -> bool:
    """Hyperliquid short liquidation cascade pre-fire → predicts UP.

    HL short proxy = rows where:
      (dir=='Close Short' AND source=='hl-s3-fills' AND method=='market') OR
      (dir=='Open Long' AND source=='hl-s3-fills' AND method=='market')
    Notional = size × price.

    Asset coverage:
    - BTC: well-populated, $100k threshold gives WR=95.7% (n=140, t=7.5)
    - SOL/ETH: insufficient HL data, do not use
    """
    asset_proxy = hl_short_proxy[hl_short_proxy['coin'] == asset_coin]
    t_start = fire_us - window_s * 1_000_000
    mask = (
        (asset_proxy['time_exchange_us'] >= t_start) &
        (asset_proxy['time_exchange_us'] < fire_us)
    )
    return float(asset_proxy.loc[mask, 'notional'].sum()) > thresh_usd
```

### 2.5 — Data preload requirements (one-time, at engine start)

```python
# At engine boot, before any V9 sleeve evaluates:

# Polymarket trades — used by B1/B2/B3
asset_trades_btc = pd.read_parquet("data/v4/canonical/trades_polymarket/btc.parquet")
asset_trades_eth = pd.read_parquet("data/v4/canonical/trades_polymarket/eth.parquet")
asset_trades_sol = pd.read_parquet("data/v4/canonical/trades_polymarket/sol.parquet")

# HL short cascade proxy — pre-filtered for fast lookup
hl_raw = pd.read_parquet("data/v4/canonical/hyperliquid_liquidations_full.parquet")
hl_short_proxy = hl_raw[
    (hl_raw['source'] == 'hl-s3-fills') &
    (hl_raw['method'] == 'market') &
    (hl_raw['dir'].isin(['Close Short', 'Open Long']))
].copy()
hl_short_proxy['notional'] = hl_short_proxy['size'] * hl_short_proxy['price']
```

These DataFrames should be injected into the controller at init alongside `book_mirror`. Use a polling refresh (every N minutes) to capture new trades/liquidations live — or wire up an incremental in-memory updater fed by the existing collectors.

---

## 3. V9 — 10 new sleeves (use new gates)

> Backtest fee model: LegacyConfig (2%-on-profit). All metrics from full V5/V6/V7 fire universe (18,270 fires, ~32 days Apr 24 → May 26). See `strategy_lab/reports/NEW_GATES_RESEARCH_2026_05_27.md` for per-gate signal quality.

### V9_01 — BTC_5M_A2_HLCASCADE100K_V9

```
sleeve_id       = poly_sniper_v5_btc_5m_a2_hlcascade100k_v9
asset           = BTC
tf              = 5m
direction       = BOTH
offsets         = (30,)             # standard 5m offsets, single-fire
spread_filter   = 0.020
gates           = [
    g_a2_hl_short_cascade(asset_coin="BTC", window_s=300, thresh_usd=100_000),
]
```
**Backtest**: n=140 / WR=95.7% / $/tr=+$5.28 / t=7.50 / proj_$23/day

### V9_02 — BTC_5M_UP_A2_HLCASCADE50K_V9

```
sleeve_id       = poly_sniper_v5_btc_5m_up_a2_hlcascade50k_v9
asset           = BTC
tf              = 5m
direction       = UP
offsets         = (30,)
spread_filter   = 0.020
gates           = [
    g_a2_hl_short_cascade(asset_coin="BTC", window_s=300, thresh_usd=50_000),
    g_dir_up,
]
```
**Backtest**: n=108 / WR=92.6% / $/tr=+$3.90 / t=4.24 / proj_$13/day

### V9_03 — BTC_5M_DOWN_B2_CONTRARIAN2K_V9 ★ TOP INCOME

```
sleeve_id       = poly_sniper_v5_btc_5m_down_b2_contrarian2k_v9
asset           = BTC
tf              = 5m
direction       = DOWN
offsets         = (30,)
spread_filter   = 0.020
gates           = [
    g_b2_poly_flow_contrarian(direction="DOWN", window_s=60, thresh_shares=2000),
    g_dir_down,
]
```
**Backtest**: n=2285 / WR=90.9% / **$/tr=+$7.10** / t=19.27 / proj_**$507/day**
⚠ Caveat: gate passes 52% of BTC 5m fires (loose threshold). Consider tightening to $5k in live if too many fires.

### V9_04 — BTC_5M_UP_B2_CONTRARIAN2K_V9

```
sleeve_id       = poly_sniper_v5_btc_5m_up_b2_contrarian2k_v9
asset           = BTC
tf              = 5m
direction       = UP
offsets         = (30,)
spread_filter   = 0.020
gates           = [
    g_b2_poly_flow_contrarian(direction="UP", window_s=60, thresh_shares=2000),
    g_dir_up,
]
```
**Backtest**: n=1755 / WR=88.6% / $/tr=+$3.94 / t=10.58 / proj_$216/day

### V9_05 — SOL_5M_B1_POLYFLOW_ALIGNED_V9

```
sleeve_id       = poly_sniper_v5_sol_5m_b1_polyflow_aligned_v9
asset           = SOL
tf              = 5m
direction       = BOTH
offsets         = (30, 60, 90)
spread_filter   = 0.025
gates           = [
    g_b1_poly_flow_aligned(direction, window_s=60, thresh_shares=500),
]
```
**Backtest**: n=788 / WR=85.2% / $/tr=+$7.91 / t=2.31 / proj_$195/day

### V9_06 — SOL_5M_DOWN_B1_500_V9

```
sleeve_id       = poly_sniper_v5_sol_5m_down_b1_500_v9
asset           = SOL
tf              = 5m
direction       = DOWN
offsets         = (30, 60, 90)
spread_filter   = 0.025
gates           = [
    g_b1_poly_flow_aligned(direction="DOWN", window_s=60, thresh_shares=500),
    g_dir_down,
]
```
**Backtest**: n=422 / WR=84.4% / **$/tr=+$12.83** / t=2.09 / proj_$169/day
⚠ Highest $/tr but t-stat borderline; monitor first 200 fires.

### V9_07 — SOL_5M_DOWN_B1_FLOW250_V9

```
sleeve_id       = poly_sniper_v5_sol_5m_down_b1_flow250_v9
asset           = SOL
tf              = 5m
direction       = DOWN
offsets         = (30, 60, 90)
spread_filter   = 0.025
gates           = [
    g_b1_poly_flow_aligned(direction="DOWN", window_s=60, thresh_shares=250),
    g_dir_down,
]
```
**Backtest**: n=1210 / WR=80.4% / $/tr=+$5.26 / t=2.41 / proj_$199/day

### V9_08 — SOL_5M_B3_ABS500_V9

```
sleeve_id       = poly_sniper_v5_sol_5m_b3_abs500_v9
asset           = SOL
tf              = 5m
direction       = BOTH
offsets         = (30, 60, 90)
spread_filter   = 0.025
gates           = [
    g_b3_poly_flow_abs(window_s=60, thresh_shares=500),
]
```
**Backtest**: n=1660 / WR=79.5% / $/tr=+$6.09 / t=2.90 / proj_$316/day

### V9_09 — SOL_5M_B1_120S_250_V9

```
sleeve_id       = poly_sniper_v5_sol_5m_b1_120s_250_v9
asset           = SOL
tf              = 5m
direction       = BOTH
offsets         = (30, 60, 90)
spread_filter   = 0.025
gates           = [
    g_b1_poly_flow_aligned(direction, window_s=120, thresh_shares=250),
]
```
**Backtest**: n=2965 / WR=80.1% / $/tr=+$4.46 / t=3.73 / proj_**$413/day**
Broadest-coverage SOL sleeve. 120s window smooths intrabar noise.

### V9_10 — SOL_5M_B3_ABS500_NO_OPP_V9

```
sleeve_id       = poly_sniper_v5_sol_5m_b3_abs500_no_opp_v9
asset           = SOL
tf              = 5m
direction       = BOTH
offsets         = (30, 60, 90)
spread_filter   = 0.025
gates           = [
    g_b3_poly_flow_abs(window_s=60, thresh_shares=500),
    NOT g_b2_poly_flow_contrarian(direction, window_s=60, thresh_shares=500),
]
```
**Backtest**: n=1306 / WR=81.5% / $/tr=+$1.14 / t=2.63 / proj_$46/day
**Status**: DEPLOY (monitor) — marginal $/tr. First 200 fires advisory.

---

## 4. VL — 11 spread-loose variants (use existing gates, looser filter)

VL sleeves are **COPIES of existing sleeves** with one change: `spread_filter` is loosened to the value indicated below. Per-sleeve backtest validates that the wider filter improves PnL on these specific sleeves (and ONLY these — most sleeves degrade when loosened; see SPREAD_LOOSEN_SIM_* reports).

> **Implementation pattern**: in `sniper_v5_sleeves.py`, copy the parent `SniperV5Sleeve(...)` definition, change `sleeve_id` to add `_vL` suffix, and change `spread_filter`. All other fields (asset, tf, direction, offsets, gates, notional_usd_override) remain IDENTICAL to the parent.

> **Coexistence with parent**: the parent sleeve continues to run with its original tight `spread_filter`. The `_vL` variant runs alongside as an A/B comparison. This lets us measure live whether the looser filter degrades vs the backtest projection.

### Asset/TF default filter loosening

| Asset | TF | Old default | VL value |
|---|---|---:|---:|
| ETH | 5m | 0.020 | **0.025** |
| ETH | 15m | 0.020 | **0.025** |
| SOL | 15m | 0.025 | **0.030** |

(BTC 5m and SOL 5m have ZERO VL sleeves — backtest disproved benefit.)

### ETH 5m VL variants (7 sleeves)

#### VL_01 — eth_5m_k_hurst_ts_cci_tod_euus_v8_vL ★ BIGGEST GAIN

```
sleeve_id       = poly_sniper_v5_eth_5m_k_hurst_ts_cci_tod_euus_v8_vL
parent          = poly_sniper_v5_eth_5m_k_hurst_ts_cci_tod_euus_v8
spread_filter   = 0.025                    (was 0.020 on parent)
all other fields = IDENTICAL to parent
```
**Backtest delta**: +101 fires, +$108 PnL, WR flat 81.3%

#### VL_02 — eth_5m_lq_ema50_hurst_grandparent_prev15m_v8_vL

```
sleeve_id       = poly_sniper_v5_eth_5m_lq_ema50_hurst_grandparent_prev15m_v8_vL
parent          = poly_sniper_v5_eth_5m_lq_ema50_hurst_grandparent_prev15m_v8
spread_filter   = 0.025
all other fields = IDENTICAL to parent
```
**Backtest delta**: +69 fires, +$47 PnL, WR flat 81.9%

#### VL_03 — eth_5m_ema50_hurst_parent15mrang_v7_vL

```
sleeve_id       = poly_sniper_v5_eth_5m_ema50_hurst_parent15mrang_v7_vL
parent          = poly_sniper_v5_eth_5m_ema50_hurst_parent15mrang_v7
spread_filter   = 0.025
all other fields = IDENTICAL to parent
```
**Backtest delta**: +25 fires, +$12 PnL, WR flat 79.7%

#### VL_04 — eth_5m_cloud_ribbon_mp_hurst_v6_vL

```
sleeve_id       = poly_sniper_v5_eth_5m_cloud_ribbon_mp_hurst_v6_vL
parent          = poly_sniper_v5_eth_5m_cloud_ribbon_mp_hurst_v6
spread_filter   = 0.025
all other fields = IDENTICAL to parent
```
**Backtest delta**: +18 fires, +$17 PnL, WR flat 81.7%

#### VL_05 — eth_5m_v6c3_parent15mrang_v7_vL

```
sleeve_id       = poly_sniper_v5_eth_5m_v6c3_parent15mrang_v7_vL
parent          = poly_sniper_v5_eth_5m_v6c3_parent15mrang_v7
spread_filter   = 0.025
all other fields = IDENTICAL to parent
```
**Backtest delta**: +16 fires, +$15 PnL, WR flat 81.8%

#### VL_06 — eth_5m_bb_mp_hurst_band_v6_vL

```
sleeve_id       = poly_sniper_v5_eth_5m_bb_mp_hurst_band_v6_vL
parent          = poly_sniper_v5_eth_5m_bb_mp_hurst_band_v6
spread_filter   = 0.025
all other fields = IDENTICAL to parent
```
**Backtest delta**: +7 fires, +$10 PnL, WR flat

#### VL_07 — eth_5m_cloud_vwap_hurstmp_v7_vL

```
sleeve_id       = poly_sniper_v5_eth_5m_cloud_vwap_hurstmp_v7_vL
parent          = poly_sniper_v5_eth_5m_cloud_vwap_hurstmp_v7
spread_filter   = 0.025
all other fields = IDENTICAL to parent
```
**Backtest delta**: +7 fires, +$10 PnL, WR flat

### ETH 15m VL variants (2 sleeves)

#### VL_08 — eth_15m_trstack_vwap_vol_offearly_vL

```
sleeve_id       = poly_sniper_v5_eth_15m_trstack_vwap_vol_offearly_vL
parent          = poly_sniper_v5_eth_15m_trstack_vwap_vol_offearly
spread_filter   = 0.025
all other fields = IDENTICAL to parent
```
**Backtest delta**: +3 PnL, small fire gain

#### VL_09 — eth_15m_trstack_vwap_vol_offearly_band_v6_vL

```
sleeve_id       = poly_sniper_v5_eth_15m_trstack_vwap_vol_offearly_band_v6_vL
parent          = poly_sniper_v5_eth_15m_trstack_vwap_vol_offearly_band_v6
spread_filter   = 0.025
all other fields = IDENTICAL to parent
```
**Backtest delta**: +3 PnL, small fire gain

### SOL 15m VL variants (2 sleeves)

#### VL_10 — sol_15m_trstack_vol_ribbon_ema_mid_vL

```
sleeve_id       = poly_sniper_v5_sol_15m_trstack_vol_ribbon_ema_mid_vL
parent          = poly_sniper_v5_sol_15m_trstack_vol_ribbon_ema_mid
spread_filter   = 0.030                    (was 0.025 on parent)
all other fields = IDENTICAL to parent
```
**Backtest delta**: +2 fires, +$7.61 PnL, WR +0.5pp

#### VL_11 — sol_15m_rfaged_trstack_late_vL

```
sleeve_id       = poly_sniper_v5_sol_15m_rfaged_trstack_late_vL
parent          = poly_sniper_v5_sol_15m_rfaged_trstack_late
spread_filter   = 0.030
all other fields = IDENTICAL to parent
```
**Backtest delta**: +2 fires, +$3.50 PnL, WR flat

---

## 5. Combined registry — 21 new sleeves

```
ID      sleeve_id                                                  asset  tf    spread   type        backtest
V9_01   poly_sniper_v5_btc_5m_a2_hlcascade100k_v9                  BTC    5m    0.020    NEW_GATE    n=140, WR=95.7%
V9_02   poly_sniper_v5_btc_5m_up_a2_hlcascade50k_v9                BTC    5m    0.020    NEW_GATE    n=108, WR=92.6%
V9_03   poly_sniper_v5_btc_5m_down_b2_contrarian2k_v9              BTC    5m    0.020    NEW_GATE    n=2285, WR=90.9% ★
V9_04   poly_sniper_v5_btc_5m_up_b2_contrarian2k_v9                BTC    5m    0.020    NEW_GATE    n=1755, WR=88.6% ★
V9_05   poly_sniper_v5_sol_5m_b1_polyflow_aligned_v9               SOL    5m    0.025    NEW_GATE    n=788, WR=85.2%
V9_06   poly_sniper_v5_sol_5m_down_b1_500_v9                       SOL    5m    0.025    NEW_GATE    n=422, $/tr=+12.83
V9_07   poly_sniper_v5_sol_5m_down_b1_flow250_v9                   SOL    5m    0.025    NEW_GATE    n=1210, WR=80.4%
V9_08   poly_sniper_v5_sol_5m_b3_abs500_v9                         SOL    5m    0.025    NEW_GATE    n=1660, WR=79.5%
V9_09   poly_sniper_v5_sol_5m_b1_120s_250_v9                       SOL    5m    0.025    NEW_GATE    n=2965, WR=80.1%
V9_10   poly_sniper_v5_sol_5m_b3_abs500_no_opp_v9                  SOL    5m    0.025    NEW_GATE    n=1306, monitor
VL_01   poly_sniper_v5_eth_5m_k_hurst_ts_cci_tod_euus_v8_vL        ETH    5m    0.025    LOOSEN_V8   +$108
VL_02   poly_sniper_v5_eth_5m_lq_ema50_hurst_grandparent_prev15m_v8_vL ETH 5m  0.025    LOOSEN_V8   +$47
VL_03   poly_sniper_v5_eth_5m_ema50_hurst_parent15mrang_v7_vL      ETH    5m    0.025    LOOSEN_V7   +$12
VL_04   poly_sniper_v5_eth_5m_cloud_ribbon_mp_hurst_v6_vL          ETH    5m    0.025    LOOSEN_V6   +$17
VL_05   poly_sniper_v5_eth_5m_v6c3_parent15mrang_v7_vL             ETH    5m    0.025    LOOSEN_V7   +$15
VL_06   poly_sniper_v5_eth_5m_bb_mp_hurst_band_v6_vL               ETH    5m    0.025    LOOSEN_V6   +$10
VL_07   poly_sniper_v5_eth_5m_cloud_vwap_hurstmp_v7_vL             ETH    5m    0.025    LOOSEN_V7   +$10
VL_08   poly_sniper_v5_eth_15m_trstack_vwap_vol_offearly_vL        ETH    15m   0.025    LOOSEN_V5   +$3
VL_09   poly_sniper_v5_eth_15m_trstack_vwap_vol_offearly_band_v6_vL ETH   15m   0.025    LOOSEN_V6   +$3
VL_10   poly_sniper_v5_sol_15m_trstack_vol_ribbon_ema_mid_vL       SOL    15m   0.030    LOOSEN_V5   +$7.61
VL_11   poly_sniper_v5_sol_15m_rfaged_trstack_late_vL              SOL    15m   0.030    LOOSEN_V5   +$3.50
```

**Total roster after deploy**: V5 (16) + V6 (14) + V7 (12) + V8 (14) + V9 (10) + VL (11) = **77 sleeves**

---

## 6. Implementation order

1. **First — V9 gate library**
   - Add 4 new gate functions to `sniper_v5_gates.py` (§2.1–2.4)
   - Add data preload at engine boot (§2.5)
   - Add gate routing entries in `_build_gate_kwargs` so they receive `asset_trades` + `hl_short_proxy` + `slug` + `direction` + `fire_us` at dispatch time
   - Add JSONL shadow log fields: `poly_flow_aligned_60s`, `poly_flow_contrarian_60s`, `hl_short_300s_usd`
   - Tests: unit-test each gate with mock data; verify SOL B2 returns True for opposing flow (so we know our NOT wrapper in V9_10 inverts correctly)

2. **Second — V9 sleeve definitions**
   - Add 10 `SniperV5Sleeve(...)` entries to `sniper_v5_sleeves.py` per §3
   - Use the `GateRef(g_b1_poly_flow_aligned, kwargs=(...), name="g_b1_poly_flow_aligned(SOL,500)")` pattern existing sleeves use
   - V9_10 needs the NOT wrapper for the inner `g_b2_poly_flow_contrarian` — implement as a small helper gate `g_b2_poly_flow_NOT_opposing` to keep the GateRef tuple flat

3. **Third — VL sleeve definitions**
   - For each VL_NN (11 total), add a new `SniperV5Sleeve(...)` entry to `sniper_v5_sleeves.py`
   - Copy the parent sleeve definition verbatim, change `sleeve_id` (add `_vL`) and `spread_filter` (per §4 table)
   - VL sleeves require ZERO new gate functions

4. **Fourth — refresh stale Polymarket trades data** (one-shot prerequisite)
   - Per V9 caveat: `trades_polymarket` is stale at May 6 for BTC/SOL per CLAUDE.md
   - Pull delta to current date BEFORE enabling V9 sleeves
   - Without this, B1/B2/B3 gates will see empty trade windows for post-May-6 fires and return False

5. **Fifth — deploy + monitor**
   - Engine restart picks up new sleeves automatically (loop iterates `SNIPER_V5_SLEEVES`)
   - $5 ramp-start stake (no change from current operator setting)
   - Monitor for 200 fires per V9 sleeve before any size-up decision
   - VL sleeves: monitor side-by-side with parent — if live WR for `_vL` drops > 3pp below parent, kill the variant

---

## 7. Caveats

### V9-specific
1. **B2 BTC contrarian (V9_03/V9_04)**: gate passes 52% of BTC fires at $2k threshold. If live volume is too high, tighten to $5k.
2. **A2 HL low volume**: V9_01/V9_02 produce ~3-4 fires/day. Wide CI; size cautiously.
3. **B1 SOL t-stats borderline**: V9_05 (t=2.31), V9_06 (t=2.09) — monitor first 200 fires.
4. **SOL B2 is anti-signal**: TV must NOT add `g_b2_poly_flow_contrarian` as positive gate to any SOL sleeve. Only the NOT-wrapped inverse in V9_10 is correct.
5. **Stale trades data**: refresh `trades_polymarket` delta before deploy.

### VL-specific
1. **Backtest uses LegacyConfig (2%-on-profit)** — production fee model. Numbers are honest.
2. **Marginal fires in (0.020, 0.025] band for ETH** show same WR as the main population — quality doesn't degrade when loosening for these sleeves. This is asset/sleeve-specific; SOL 5m and BTC 5m DO degrade (which is why we have ZERO VL sleeves for those assets).
3. **A/B comparison metric**: compare `_vL` total PnL vs parent total PnL after 14d shadow. If `_vL` underperforms parent, kill `_vL`.
4. **VL sleeves DON'T require V9 gate work** — they can deploy ahead of V9 if TV agent prefers staged rollout.

---

## 8. Acceptance criteria

After deploy:
1. ✅ 21 new sleeves appear in `SNIPER_V5_SLEEVES` tuple (10 V9 + 11 VL)
2. ✅ Engine restart logs `n_sleeves=77` in `poly_sniper_v5.loop_started`
3. ✅ JSONL events appear for all new sleeve IDs within 1 hour of restart
4. ✅ V9 events have new gate fields populated (`poly_flow_aligned_60s` etc.) in shadow log
5. ✅ VL events have `spread_filter` reflected in any spread-rejection skip_reason (e.g., `spread_bidask_too_wide_0.0280_>_0.0250` rather than `> 0.0200`)
6. ✅ No `synthetic` fill_method appears (relies on unified book-read fix being in place)
7. ✅ Backtest unit tests pass for each new gate

---

## 9. Files referenced

Production code (VPS3):
- `/opt/tradingvenue/backend/app/strategies/polymarket/sniper_v5_gates.py` — gate library (add 4 new gates)
- `/opt/tradingvenue/backend/app/strategies/polymarket/sniper_v5_sleeves.py` — sleeve definitions (add 21 entries)
- `/opt/tradingvenue/backend/app/controllers/polymarket_sniper_v5.py` — controller (`_build_gate_kwargs` routing)
- `/opt/tradingvenue/backend/app/strategies/polymarket/sniper_v5_shadow_log.py` — add new fields

Research:
- `strategy_lab/reports/NEW_GATES_RESEARCH_2026_05_27.md`
- `strategy_lab/reports/HL_GATES_REFINEMENT_2026_05_27.md`
- `strategy_lab/reports/SPREAD_LOOSEN_SIM_BTC_5M_2026_05_27.md`
- `strategy_lab/reports/SPREAD_LOOSEN_SIM_ETH_2026_05_27.md`
- `strategy_lab/reports/SPREAD_LOOSEN_SIM_SOL_5M_2026_05_27.md`
- `strategy_lab/reports/SPREAD_LOOSEN_SIM_SOL_15M_2026_05_27.md`

Prior deploy specs (for reference):
- `strategy_lab/reports/SHADOW_DEPLOY_SPEC_2026_05_27.md` (V5)
- `strategy_lab/reports/SHADOW_DEPLOY_SPEC_V6_SELECTED_2026_05_27.md`
- `strategy_lab/reports/SHADOW_DEPLOY_SPEC_V7_SELECTED_2026_05_27.md`
- `strategy_lab/reports/SHADOW_DEPLOY_SPEC_UNIFIED_V6_V7_V8_2026_05_27.md` (V8)
- `strategy_lab/reports/SHADOW_DEPLOY_SPEC_V9_SELECTED_2026_05_27.md` (V9 source — this doc supersedes for combined V9+VL)

---

## END
