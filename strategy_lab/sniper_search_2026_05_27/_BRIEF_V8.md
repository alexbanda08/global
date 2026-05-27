# Sniper Search Brief V8 — 2026-05-27

V8 round: **"2-asset confluence ensembles + TOD specialization + offset=0 fires + USE ALL DATA"**.

Supersedes V7 brief where they conflict. Read this BEFORE V8 work. Refer to V5, V6, V7 briefs for inherited gate libraries.

---

## 0. ⚠ OPERATOR DIRECTIVE — USE ALL DATA

V7 agents inadvertently capped at ~28d (legacy convention). **V8 MUST use the full 32.7-day window** (Apr 24 → May 26 2026) for any sleeve whose required panels cover it. Don't artificially split into 22d when 32.7d is available.

### Split rules for V8

- v3 fires cover **32.66d**
- Sleeves using ONLY v3-embedded features + microprice (31.7d) + regime_v2_fixed (28d) → use the FULL panel intersection (up to 28d effective)
- Sleeves using 1s-derived gates (TA/RF/TR/hawkes/vpin/LM, 22.1d coverage) → still use full 22.1d
- **CRITICAL**: Report `n_full`, `WR_full`, `$/tr_full` alongside `lockbox` metrics. Project to 32.7d using whichever is more conservative (lower of the two).
- 3-way split: `train = first 60% of available` / `val = next 20%` / `lockbox = last 20%`. No fixed day counts.

### Projection convention for V8

```
proj_32d  = $/tr_lockbox * (n_lockbox / days_lockbox) * 32.66
proj_full = $/tr_full * (n_full / days_full) * 32.66      # if n_full available
proj_honest = min(proj_32d, proj_full)
```

Report all three. Operator decides which to trust.

---

## 1. What V7 settled

- **Path A weighted ensembles** — FAILED universally (0 survivors)
- **Path B 2-leg straddle** — DEAD (Polymarket up-down prices arbitrage-priced)
- **Path D slot-end OFI 15m** — DEAD (regime flip). 5m disputed.
- **Path C cross-asset (single-asset trigger)** — UNIVERSAL WINNER (5 of 6 markets)
- **Path F 15m parent regime** — STRONG (BTC 5m, ETH 5m, especially `g_parent15m_ranging`)
- **Path H hurst variants** — ASYMMETRIC (BTC/ETH want trending, SOL wants reverting)
- **Path I pre-window** — works only on ETH 15m

V8 BUILDS ON these wins:
- More cross-asset compositions (2-asset confluence, not just 1)
- TOD specialization expansion (V7 only had `g_hod_european_morning` for SOL 15m)
- Offset=0 fires (V7 couldn't test — not in v3 build)
- Multi-timeframe confluence (parent regime worked; extend to 1h grandparent)

---

## 2. V8 explore — new dimensions

### Path J — 2-asset confluence ensembles
NOT "fire when ANY cross-asset signal triggers" but "fire when MULTIPLE assets confirm at once".

```python
g_2asset_confluence_btc_eth_up(direction, fire_us):
  btc_trend_up = (regime_panel_5m[BTC].trend_slope_30m > 0) at fire_us
  eth_trend_up = (regime_panel_5m[ETH].trend_slope_30m > 0) at fire_us
  return btc_trend_up AND eth_trend_up AND direction == "UP"

g_2asset_xa_unanimity(direction, fire_us, target_asset):
  # All 3 assets agree via RF + microprice + trend_slope simultaneously
  signals = []
  for asset in ["BTC", "ETH", "SOL"]:
    rf  = range_filter_1s[asset].rf_dir at (fire_us - 1_000_000)
    ts  = trend_slope_30m(asset, "5m", fire_us)
    mp  = microprice_panel[asset+"_proxy"] at fire_us  # need cross-asset microprice mapping
    sig = +1 if (rf == 1 and ts > 0) else -1 if (rf == -1 and ts < 0) else 0
    signals.append(sig)
  if all(s == +1 for s in signals) and direction == "UP":   return True
  if all(s == -1 for s in signals) and direction == "DOWN": return True
  return False
```

Test 2-asset and 3-asset variants. **Hypothesis**: 3-asset unanimity is rare but highest-conviction.

### Path K — Time-of-day systematic specialization

V6/V7 only had `g_hod_european_morning` (SOL 15m). V8 builds 4 TOD buckets per asset and finds bucket-specialized sleeves:

```python
hod_buckets = {
  "asia_morning":      [0, 1, 2, 3, 4, 5, 6],      # 00-07 UTC
  "european_morning":  [7, 8, 9, 10, 11, 12],      # 07-13 UTC
  "us_afternoon":      [13, 14, 15, 16, 17, 18],   # 13-19 UTC
  "us_evening":        [19, 20, 21, 22, 23],       # 19-24 UTC
}

# For each market, sweep gate stacks WITHIN each TOD bucket
# Find sleeves where edge is concentrated in 1-2 TOD buckets
```

Expected outcome: some V7 winning gate stacks may have huge edge ONLY in specific TOD bucket. Split them.

### Path L — Multi-timeframe confluence (5m + 15m parent + 1h grandparent)

Extend Path F (15m parent regime) to add 1h grandparent:

```python
g_grandparent_1h_trend_with(direction, fire_us, asset):
  # 1h regime panel (need to build from binance 1h)
  ts = asof_bar_end(asset, "1h", fire_us - 1_000_000)
  label = regime_panel_1h[asset].regime_label at ts
  return (label == "trending_up" and direction == "UP") or \
         (label == "trending_dn" and direction == "DOWN")

# Stack: 5m fire AND 15m parent regime aligned AND 1h grandparent aligned
```

### Path M — Offset=0 fires (NEW universe)

Build `oos_fires_{ASSET}_{TF}_v8.parquet` with offsets:
- 5m: {0, 15, 30, 45, 60, 90, 120, 150, 180, 210, 240, 270}
- 15m: {0, 30, 60, 120, 240, 360, 480, 600, 720, 840}

Test if offset=0 (immediate fire at slot_start) gives better entry vwap and higher $/tr than offset=30 or 60.

V7 research showed +$14-17/won going from offset 270 → offset 30. Offset 0 may add +$2-4 more.

### Path N — Binance perp funding/OI gates

For 5m markets, integrate binance perp funding rate + open interest:

```python
g_funding_extreme_with(direction, fire_us, asset):
  # Funding rate at the most recent 8h funding window before fire
  funding = binance_perp_funding[asset] at (most_recent_window <= fire_us)
  # Positive funding = longs paying shorts = crowded longs = bearish bias
  # Negative funding = shorts paying longs = crowded shorts = bullish bias
  if funding > 0.001 and direction == "DOWN": return True   # contrarian
  if funding < -0.001 and direction == "UP":  return True
  return False

g_oi_spike_with(direction, fire_us, asset):
  # OI increase > 5% in last 1h matching direction signals new positioning
  oi_now = binance_perp_oi[asset] at fire_us
  oi_1h  = binance_perp_oi[asset] at (fire_us - 3600 * 1_000_000)
  oi_chg = (oi_now - oi_1h) / oi_1h
  price_chg = (binance_close[asset] at fire_us - binance_close[asset] at (fire_us - 3600 * 1_000_000)) / oi_1h
  if oi_chg > 0.05 and price_chg > 0 and direction == "UP": return True
  if oi_chg > 0.05 and price_chg < 0 and direction == "DOWN": return True
  return False
```

CAVEAT: per CLAUDE.md `binance_metrics_v2 excluded permanently: VPS3 is geoblocked from Binance futures`. Need to check if binance_perp_funding is loadable from canonical OR if HL liquidations/funding panels can substitute (HL panels exist).

### Path O — HL (Hyperliquid) gates already in canonical

```python
g_hl_funding_extreme_with(direction, fire_us, asset):
  # HL funding rate (from hl_funding panel)
  ts = asof_bar_end("HL_funding", asset, fire_us - 1_000_000)
  funding = load_hyperliquid_funding(asset).funding_rate at ts
  # Same contrarian logic as binance variant
  ...

g_hl_liq_cascade_with(direction, fire_us, asset):
  # Already in V5 library. Test more aggressively in V8.

g_hl_oi_with(direction, fire_us, asset):
  # HL open interest change
  ...
```

### Path P — Liquidity shock detection

```python
g_book_depth_shock(direction, fire_us, slug):
  # Sudden L25 depth drop in last 5s before fire signals incoming move
  depth_now  = L25[slug].cum_depth_usd at fire_us
  depth_5s   = L25[slug].cum_depth_usd at (fire_us - 5_000_000)
  return depth_now < depth_5s * 0.7   # depth dropped >30% in 5s
```

### Path Q — Cross-tf confluence (5m + 15m same direction)

For 5m markets, only fire if 15m fire on SAME slug-time-asset also signals same direction. Use v3 15m fires as auxiliary signal.

---

## 3. V8 target profile (relaxed further if needed)

| Metric | Target |
|---|---|
| n / 32.7d | 30-2000 |
| WR on lockbox | ≥65% (≥55% if $/tr ≥ $10) |
| $/tr at $25 stake | ≥$4 |
| Max DD at $25 stake | ≤$500 |
| Max loss streak | ≤14 |
| Bootstrap p (lockbox) | ≤0.05 |
| Stability (no negative train/val $/tr) | OK or flag |

**Primary objective**: maximize `min(proj_32d, proj_full)` (honest projection).

## 4. NEW data path additions

- Offset=0 fires (when built): `data/v4/canonical/_results/_full_window_v8_2026_05_27/oos_fires_{ASSET}_{TF}_v8.parquet`
- HL panels (already exist): `hl_funding_*.parquet`, `hl_liquidations_*.parquet`, `hl_oi_*.parquet` (per market)
- 1h regime panel (need to build): `regime_panel_1h.parquet`
- Binance perp funding: check canonical for `binance_funding_*.parquet` or HL substitute

## 5. Output spec (V8)

Per agent, write to `strategy_lab/sniper_search_2026_05_27/{market_slug}_v8/`:

1. `top_5_candidates_v8.csv` — INCLUDE columns:
   `n_train, n_val, n_lockbox, n_full, wr_train, wr_val, wr_lockbox, wr_full, dpt_25_train, dpt_25_val, dpt_25_lockbox, dpt_25_full, max_dd_25, loss_streak, sharpe, bootstrap_p_lockbox, proj_32d, proj_full, proj_honest`

2. `SNIPER_{MARKET}_V8_REPORT.md`:
   - Top 3-5 candidates with full per-split metrics
   - Per-path findings (which V8 paths worked)
   - Comparison vs V7 best
   - TOD specialization findings (which buckets best)
   - 2-asset confluence findings

3. Cumulative PnL PNGs per top sleeve

4. Code in `scripts/`

### Return (<300 words):
- # candidates meeting V8 profile
- Best sleeve gate stack + honest projection (32.7d)
- Which V8 path won
- TOD specialization revealed?
- Top failure
- Confidence

---

## 6. Per-market V8 priorities

| Market | V8 paths to explore |
|---|---|
| BTC 5m | J (2-asset), K (TOD), M (offset=0), L (1h grandparent), O (HL funding) |
| ETH 5m | J (2-asset), K (TOD), Q (5m+15m confluence), M (offset=0) |
| SOL 5m | J (2-asset BTC+ETH→SOL), K (TOD), Q (5m+15m), O (HL liq cascade — SOL specific) |
| BTC 15m | K (TOD ⭐ — V6/V7 didn't crack it via gates; maybe TOD is key), L (1h grandparent), P (liq shock) |
| ETH 15m | J (2-asset), K (TOD), L (1h grandparent), M (offset=0) |
| SOL 15m | J (2-asset BTC+ETH→SOL deeper), K (TOD), O (HL funding for SOL) |

## 7. Conventions (UNCHANGED)

- ws_s anchor for pre-window
- engine_v2.LegacyConfig fee
- L25 walk + spread filter
- chainlink outcome
- bug-fixed panels
- causal asof at fire_us-1_000_000 or ws_s*1_000_000

## 8. What NOT to do

Same as V7 §7 (don't test Kelly, $250, 2-leg straddle, slot-end OFI for 15m without revalidation, plain weighted ensembles).

Plus: **don't artificially cap at 28d**. USE THE FULL DATA.
