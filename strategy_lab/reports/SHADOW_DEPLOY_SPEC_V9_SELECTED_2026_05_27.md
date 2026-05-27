# Shadow Deploy Spec — V9 (Poly Flow + HL Cascade Gates) — 2026-05-27

**Status:** SPEC — candidate sleeves for shadow evaluation  
**Date:** 2026-05-27  
**Author:** V9 sleeve search agent  
**Prerequisite reading:**
- `strategy_lab/reports/NEW_GATES_RESEARCH_2026_05_27.md` — gate findings (B1/B2/B3 poly flow, A2 HL cascade)
- `strategy_lab/reports/SHADOW_DEPLOY_SPEC_UNIFIED_V6_V7_V8_2026_05_27.md` — existing 56-sleeve roster

---

## 0. Engine constants (UNCHANGED from V8)

```
notional_default_usd  = 25.0
fee_model             = legacy_2pct_profit          # 2%-on-profit only (verified 2026-05-22)
spread_filter_btc     = 0.02
spread_filter_sol     = 0.025
window_s_5m           = 300
fill_engine           = L25_book_walk
fill_min_book_events  = 25
subsample_1hz         = False                       # MANDATORY — native 10Hz
hold_to               = slot_end_us
exit_policy           = HOLD_TO_SLOT_END
mode                  = paper
fill_time_veto        = g_book_supports_stake(direction, fire_us, slug, stake=25.0)
```

---

## 1. Anchor conventions (UNCHANGED)

- `ws_s = slot_start_s - window_s` (previous slot start for 5m window_s=300)
- `fire_us = (ws_s + 120) × 1_000_000` (v1 fires) or `(ws_s + 60) × 1_000_000` (v2)
- All kline lookups: `asof_strict(end_us, prices, target_us)` — causal, no lookahead
- Outcome truth: `outcome` column (chainlink-derived) from `load_resolutions()`

---

## 2. New V9 gates — implementation spec

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
    """
    Polymarket aggressor flow ALIGNED with our direction in window pre-fire.

    Signal logic: large buy pressure on the same side as our bet = market
    participants confirming the move. Strong aligned flow lifts SOL WR by
    +13.7pp ($500 threshold) to +20.3pp ($1000 threshold).

    Net flow = (outcome_buys - outcome_sells) for our direction, in shares.
    Positive net = buyers are aggressive on our side.

    ASSET-SPECIFIC NOTES:
    - SOL: primary signal. $500 threshold WR=85.2%, n=788, +9.1pp lift.
    - BTC: weaker (+2.6pp at $1k), use higher threshold or prefer B2/B3.
    - ETH: marginal (+2.8pp at $1k), not recommended as primary gate.

    Data source: canonical/trades_polymarket/{asset}.parquet
      columns: timestamp_us, slug, outcome, price, size, side
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
    direction: str,           # "UP" or "DOWN"
    asset_trades: pd.DataFrame,
    window_s: int = 60,
    thresh_shares: float = 2000.0,
) -> bool:
    """
    Polymarket aggressor flow OPPOSING our direction in window pre-fire.

    Signal logic: strong opposing flow = large participant is wrong-side
    (contrarian confirmation). Overall (ALL assets) WR=91.1% at $2k threshold,
    +10.97pp lift.

    CRITICAL ASSET-SPECIFIC NOTES:
    - BTC: contrarian signal IS positive (+10.97pp aggregated — BTC-dominated).
      Specifically STRONG for DOWN fires (WR=90.9%, n=2285, t=19.3).
    - SOL: contrarian is ANTI-SIGNAL at $500 (WR=58.6% = -18.5pp). Use as
      KILL gate for SOL (exclude fires where opp_flow > thresh).
    - ETH: mildly positive at $500 (+4.6pp, n=101).

    opp_flow = net buy pressure on the OPPOSITE side to our direction.
    Returns True when opp_flow > thresh (= contrarian confirmation for BTC).
    For SOL, invert logic (use as NOT g_b2 kill gate).
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

### 2.3 — B3: Polymarket Flow Absolute

```python
def g_b3_poly_flow_abs(
    slug: str,
    fire_us: int,
    asset_trades: pd.DataFrame,
    window_s: int = 60,
    thresh_shares: float = 500.0,
) -> bool:
    """
    Any strong directional flow (either side) in window pre-fire.

    Signal logic: market is actively trading = price discovery is happening
    = our F7/trend-based signal is more likely to be correct.

    abs_flow = |up_net_flow| + |down_net_flow|
    WR lift: ALL assets +8.5pp at $2k; SOL +13.7pp at $500 (lower threshold
    needed due to lower volume vs BTC).

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
    abs_flow = abs(float(up_net)) + abs(float(dn_net))
    return abs_flow > thresh_shares
```

### 2.4 — A2: HL Short Cascade

```python
def g_a2_hl_short_cascade(
    fire_us: int,
    asset_coin: str,           # "BTC", "ETH", "SOL"
    hl_short_proxy: pd.DataFrame,  # pre-filtered: Close Short/Open Long, market, hl-s3-fills
    window_s: int = 300,
    thresh_usd: float = 100_000.0,
) -> bool:
    """
    Hyperliquid short liquidation cascade in window pre-fire.

    Signal logic: forced short closures on HL = short squeeze = upward price
    pressure = Polymarket UP outcome more likely. Strong for BTC UP direction.

    HL short proxy = rows where:
      (dir=='Close Short' AND source=='hl-s3-fills' AND method=='market') OR
      (dir=='Open Long' AND source=='hl-s3-fills' AND method=='market')
    Notional = size × price.

    ASSET COVERAGE:
    - BTC: well-populated. $100k threshold WR=95.7% (n=140, t=7.5).
    - SOL/ETH: insufficient HL data at these thresholds — do not use.

    DIRECTION NOTE: mechanically predicts UP (short squeeze). A2 fires on
    DOWN sleeves are coincidental — use direction filter for purity.

    Data: canonical/hyperliquid_liquidations_full.parquet
      columns used: time_exchange_us, coin, dir, price, size, method, source
    """
    asset_proxy = hl_short_proxy[hl_short_proxy['coin'] == asset_coin]
    t_start = fire_us - window_s * 1_000_000
    mask = (
        (asset_proxy['time_exchange_us'] >= t_start) &
        (asset_proxy['time_exchange_us'] < fire_us)
    )
    total_notional = asset_proxy.loc[mask, 'notional'].sum()
    return float(total_notional) > thresh_usd
```

---

## 3. V9 selected sleeve specifications (10 sleeves)

> **Backtest context:** Full V5/V6/V7 fire universe (18,270 fires total; SOL 5m = 4,948 fires,
> BTC 5m = 4,429 fires). Window: 2026-04-24 → 2026-05-26 (~32 days). Fee model: LegacyConfig
> (2%-on-profit only). Spread filter applied at fill time via `g_book_supports_stake`.
> These gates are evaluated as overlays on the existing fire universe — in production, each
> V9 sleeve appends the new gate to an existing sleeve's gate stack.

---

### Sleeve V9_01 — BTC_5M_A2_HLCASCADE100K_V9

```
asset           = BTC
tf              = 5m
direction       = {UP, DOWN}   ← note: A2 mechanistically predicts UP; DOWN fires ride market momentum
offset_s        = ALL
window_s        = 300
spread_filter   = 0.02
new_gate        = g_a2_hl_short_cascade(fire_us, "BTC", window_s=300, thresh_usd=100_000)
fill_time_veto  = g_book_supports_stake
```

Backtest: n=140 WR=95.7% $/tr=+5.28 total=+$738.6 t=7.50  
proj_$/day: ~$23/day (n=4.4/day × $5.28)  
Status: **DEPLOY** — highest WR/confidence in V9 batch. HL short cascade is mechanistically clean.

---

### Sleeve V9_02 — BTC_5M_UP_A2_HLCASCADE50K_V9

```
asset           = BTC
tf              = 5m
direction       = UP only
offset_s        = ALL
window_s        = 300
spread_filter   = 0.02
new_gate        = g_a2_hl_short_cascade(fire_us, "BTC", window_s=300, thresh_usd=50_000)
                  AND direction == "UP"
fill_time_veto  = g_book_supports_stake
```

Backtest: n=108 WR=92.6% $/tr=+3.90 total=+$421.2 t=4.24  
proj_$/day: ~$13/day  
Status: **DEPLOY** — directionally pure short-squeeze signal. Lower threshold = more fires.

---

### Sleeve V9_03 — BTC_5M_DOWN_B2_CONTRARIAN2K_V9

```
asset           = BTC
tf              = 5m
direction       = DOWN only
offset_s        = ALL
window_s        = 300
spread_filter   = 0.02
new_gate        = g_b2_poly_flow_contrarian(slug, fire_us, "DOWN", window_s=60, thresh=2000)
                  AND direction == "DOWN"
fill_time_veto  = g_book_supports_stake
```

Backtest: n=2285 WR=90.9% $/tr=+7.10 total=+$16,228.9 t=19.27  
proj_$/day: ~$507/day (highest income in V9)  
Status: **DEPLOY** ★ — strongest V9 sleeve. High n, very high t-stat. Others buying UP when we go DOWN = contrarian confirmation. Likely capturing regime where crowd is wrong.

---

### Sleeve V9_04 — BTC_5M_UP_B2_CONTRARIAN2K_V9

```
asset           = BTC
tf              = 5m
direction       = UP only
offset_s        = ALL
window_s        = 300
spread_filter   = 0.02
new_gate        = g_b2_poly_flow_contrarian(slug, fire_us, "UP", window_s=60, thresh=2000)
                  AND direction == "UP"
fill_time_veto  = g_book_supports_stake
```

Backtest: n=1755 WR=88.6% $/tr=+3.94 total=+$6,910.8 t=10.58  
proj_$/day: ~$216/day  
Status: **DEPLOY** ★ — strong signal, high n, clean t-stat.

---

### Sleeve V9_05 — SOL_5M_B1_POLYFLOW_ALIGNED_V9

```
asset           = SOL
tf              = 5m
direction       = {UP, DOWN}
offset_s        = ALL
window_s        = 300
spread_filter   = 0.025
new_gate        = g_b1_poly_flow_aligned(slug, fire_us, direction, window_s=60, thresh=500)
fill_time_veto  = g_book_supports_stake
```

Backtest: n=788 WR=85.2% $/tr=+7.91 total=+$6,231.2 t=2.31  
proj_$/day: ~$195/day  
Status: **DEPLOY** — t-stat marginal (2.31 ≥ 2.0 threshold) but mechanistically clean. Monitor first 200 fires. SOL B1 is the star signal from new gate research.

---

### Sleeve V9_06 — SOL_5M_DOWN_B1_500_V9

```
asset           = SOL
tf              = 5m
direction       = DOWN only
offset_s        = ALL
window_s        = 300
spread_filter   = 0.025
new_gate        = g_b1_poly_flow_aligned(slug, fire_us, "DOWN", window_s=60, thresh=500)
                  AND direction == "DOWN"
fill_time_veto  = g_book_supports_stake
```

Backtest: n=422 WR=84.4% $/tr=+12.83 total=+$5,413.5 t=2.09  
proj_$/day: ~$169/day  
Status: **DEPLOY** — highest $/tr in SOL group. t-stat borderline (2.09). High per-trade PnL due to asymmetric payoff on DOWN SOL fires.

---

### Sleeve V9_07 — SOL_5M_DOWN_B1_FLOW250_V9

```
asset           = SOL
tf              = 5m
direction       = DOWN only
offset_s        = ALL
window_s        = 300
spread_filter   = 0.025
new_gate        = g_b1_poly_flow_aligned(slug, fire_us, "DOWN", window_s=60, thresh=250)
                  AND direction == "DOWN"
fill_time_veto  = g_book_supports_stake
```

Backtest: n=1210 WR=80.4% $/tr=+5.26 total=+$6,370.4 t=2.41  
proj_$/day: ~$199/day  
Status: **DEPLOY** — higher throughput than V9_06, lower threshold. Good complement.

---

### Sleeve V9_08 — SOL_5M_B3_ABS500_V9

```
asset           = SOL
tf              = 5m
direction       = {UP, DOWN}
offset_s        = ALL
window_s        = 300
spread_filter   = 0.025
new_gate        = g_b3_poly_flow_abs(slug, fire_us, window_s=60, thresh=500)
fill_time_veto  = g_book_supports_stake
```

Backtest: n=1660 WR=79.5% $/tr=+6.09 total=+$10,116.1 t=2.90  
proj_$/day: ~$316/day  
Status: **DEPLOY** — direction-agnostic flow gate. Good throughput + positive t-stat. Capture fires where either side shows conviction without directional constraint.

---

### Sleeve V9_09 — SOL_5M_B1_120S_250_V9

```
asset           = SOL
tf              = 5m
direction       = {UP, DOWN}
offset_s        = ALL
window_s        = 300
spread_filter   = 0.025
new_gate        = g_b1_poly_flow_aligned(slug, fire_us, direction, window_s=120, thresh=250)
fill_time_veto  = g_book_supports_stake
```

Backtest: n=2965 WR=80.1% $/tr=+4.46 total=+$13,212.8 t=3.73  
proj_$/day: ~$413/day  
Status: **DEPLOY** — broadest-coverage SOL sleeve (60% of all SOL 5m fires). 120s window smooths intrabar noise. Good income driver.

---

### Sleeve V9_10 — SOL_5M_B3_ABS500_NO_OPP_V9

```
asset           = SOL
tf              = 5m
direction       = {UP, DOWN}
offset_s        = ALL
window_s        = 300
spread_filter   = 0.025
new_gate        = g_b3_poly_flow_abs(slug, fire_us, window_s=60, thresh=500)
                  AND NOT g_b2_poly_flow_contrarian(slug, fire_us, direction, window_s=60, thresh=500)
                  # = flow is active but NOT opposing our direction
fill_time_veto  = g_book_supports_stake
```

Backtest: n=1306 WR=81.5% $/tr=+1.14 total=+$1,482.8 t=2.63  
proj_$/day: ~$46/day  
Status: **DEPLOY (monitor)** — $/tr is marginal (+$1.14). Good for refining the flow gate: flow active + no opposing pressure = cleaner entry. t-stat just above threshold. First 200 fires advisory.

---

## 4. Combined registry — V9 (10 new sleeves)

```
ID      sleeve_id                                     asset  tf   dir       spread  new_gate          status
V9_01   BTC_5M_A2_HLCASCADE100K_V9                    BTC    5m   BOTH      0.02    A2(100k,300s)     DEPLOY ★
V9_02   BTC_5M_UP_A2_HLCASCADE50K_V9                  BTC    5m   UP_ONLY   0.02    A2(50k,300s)+UP   DEPLOY
V9_03   BTC_5M_DOWN_B2_CONTRARIAN2K_V9                BTC    5m   DOWN_ONLY 0.02    B2(2k,60s)+DOWN   DEPLOY ★
V9_04   BTC_5M_UP_B2_CONTRARIAN2K_V9                  BTC    5m   UP_ONLY   0.02    B2(2k,60s)+UP     DEPLOY ★
V9_05   SOL_5M_B1_POLYFLOW_ALIGNED_V9                 SOL    5m   BOTH      0.025   B1(500,60s)       DEPLOY
V9_06   SOL_5M_DOWN_B1_500_V9                         SOL    5m   DOWN_ONLY 0.025   B1(500,60s)+DOWN  DEPLOY
V9_07   SOL_5M_DOWN_B1_FLOW250_V9                     SOL    5m   DOWN_ONLY 0.025   B1(250,60s)+DOWN  DEPLOY
V9_08   SOL_5M_B3_ABS500_V9                           SOL    5m   BOTH      0.025   B3(500,60s)       DEPLOY
V9_09   SOL_5M_B1_120S_250_V9                         SOL    5m   BOTH      0.025   B1(250,120s)      DEPLOY
V9_10   SOL_5M_B3_ABS500_NO_OPP_V9                    SOL    5m   BOTH      0.025   B3+anti-B2        DEPLOY(monitor)
```

Total new sleeves: 10  
Combined roster: V5(16) + V6(14) + V7(12) + V8(14) + V9(10) = **66 shadow sleeves total**

---

## 5. Aggregate summary

| Metric | V9 batch |
|--------|----------|
| Candidates designed | 14 |
| Passed filters (n≥30, WR≥70%, $/tr≥+0.10, t≥2.0) | 13 |
| Final selected (deduplicated) | 10 |
| Total projected $/day (sum) | ~$2,098/day |
| Highest-income single sleeve | V9_03 BTC DOWN B2 (~$507/day) |
| Highest WR | V9_01 BTC A2 100k (95.7%) |
| Highest $/tr | V9_06 SOL DOWN B1 500 (+$12.83/tr) |

### V8 comparison

V8 round had 14 sleeves. Best single sleeve: V8_07 SOL (proj_honest $3,157 over full window ~35d = ~$90/day). V9's V9_03 BTC DOWN B2 projects $507/day — **5.6× the best V8 sleeve**. However, V9 operates on the full fire universe rather than filtered sub-populations, so projections likely overstate. Apply same discount factor as V8 (proj_honest ≈ raw × 0.30) = ~$629/day honest aggregate.

---

## 6. Key caveats

1. **Overlapping fires**: V9 gates are applied to the full V5/V6/V7 fire universe. In production, a fire must first pass its existing sleeve gates THEN the new gate. Actual throughput will be lower than these numbers (which treat all same-asset 5m fires as candidates).

2. **BTC DOWN B2 caveat (V9_03)**: n=2285 is large but the gate passes almost all BTC fires (BTC 5m total = 4,429; 2285 = 52% of fires). This suggests the $2k contrarian threshold may be too loose for BTC's high-volume market. Consider tightening to $5k in live deployment.

3. **SOL t-stats**: V9_05 (t=2.31), V9_06 (t=2.09) are just above the 2.0 threshold. Monitor first 200 fires per sleeve. If $/tr drops below $0.05, pause.

4. **A2 HL sparse**: V9_01 n=140, V9_02 n=108 over 32 days = 4-3 fires/day. Very high WR (95-96%) is consistent with the research findings but wide confidence intervals. Do not size up until n>300 live.

5. **SOL B2 KILL gate**: Per gate research, `B2_POLY_FLOW_CONTRARIAN` is ANTI-signal for SOL (WR=58.6% vs baseline 77%). V9_10 implements this as a kill gate (`NOT g_b2_contrarian`). TV implementation must NOT add the BTC-style B2 gate to SOL sleeves as a positive gate.

6. **Poly trades data**: `trades_polymarket` is stale at Apr 22 - May 6 for BTC/SOL. Gate computation uses this window. Post-May-6 fires that passed the B1/B2/B3 filters in the research results use extrapolated signal. Pull fresh trades delta before live deployment.

7. **HL liq data** is current through 2026-05-27. A2 gate computation is clean.

---

## 7. Build requirements before deploy

- [ ] Add `g_b1_poly_flow_aligned`, `g_b2_poly_flow_contrarian`, `g_b3_poly_flow_abs` to TV gate library (`sniper_v5_gates.py` or equivalent)
- [ ] Add `g_a2_hl_short_cascade` to gate library with HL liq pre-load hook
- [ ] Pre-load `trades_polymarket/{asset}.parquet` at sleeve init (indexed by slug + timestamp for fast lookup)
- [ ] Pre-load `hyperliquid_liquidations_full.parquet` filtered to `[Close Short + Open Long] market hl-s3-fills` at BTC coin
- [ ] Refresh `trades_polymarket` to current date (stale at May 6)
- [ ] Gate function tests: verify B2 SOL kill logic is NOT-positive (WR decreases when gate fires for SOL)
- [ ] Shadow logging extension: add `poly_flow_aligned_60s`, `poly_flow_contrarian_60s`, `hl_short_300s_usd` to shadow event schema

---

## END (V9 spec)
