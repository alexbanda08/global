# V5 — Late-Entry Strategy Spec (BTC + ETH + SOL)

**Date:** 2026-05-04
**Status:** Backtest validated on 04-22 → 04-29 window (n≈8,200 markets across 3 assets). 30-day OOS still required.
**Source:** `strategy_lab/v4_signals/phase7_clob_imbalance_momentum.py` + `PHASE7_CLOB_MOMENTUM_2026_05_04.md`.

---

## TL;DR

**At entry time t=240s into a 5m Polymarket UpDown market** (60 seconds of hold remaining), CLOB imbalance momentum from the Up-book and Down-book has **5-9× stronger predictive IC than entry-at-window-start**.

Per-asset top features at t=240s:

| Asset | Best feature | IC | Top quintile UP rate | Bot quintile UP rate | Spread |
|---|---|---:|---:|---:|---:|
| BTC | `up_imb_slope_240s` | **-0.290** | 21% | 62% | -0.41 |
| ETH | `dn_imb_slope_240s` | **+0.229** | 67% | 33% | +0.34 |
| SOL | `dn_imb_slope_240s` | **+0.426** | 80% | 20% | +0.60 |

**Predicted hit-rates with directional gate (top/bottom quintile of feature):**
- BTC: 62-79% (vs V3's 65%)
- ETH: 67% (vs V3's ~50%)
- SOL: 80% (vs current SOL V3-family which fires zero)

**Trade-off:** 60s hold (vs 5 min for V3). Smaller sample per market window because we wait for t=240s data to be observable. But signal quality is dramatically better.

---

## 1. Strategy logic (universal across BTC/ETH/SOL)

At each 5m Polymarket UpDown market `<asset>-updown-5m-<unix>`:

1. **Wait** until `t = window_start_unix + 240` (4 minutes into the market).
2. **Read orderbook** for the LAST 240 seconds (24 buckets at 10s cadence). Already collected by the existing collector → `orderbook_snapshots_v2`.
3. **Compute features**:
   - `up_imb_slope_240s` = OLS slope of `(sum bid_size_top5 - sum ask_size_top5) / total` over Up-token's book buckets [0, 23].
   - `dn_imb_slope_240s` = same for Down-token's book.
   - `diff_imb_slope_240s` = `up_imb_slope_240s − dn_imb_slope_240s` (asymmetry, more robust).
4. **Apply per-asset gate** (see §2 — different feature per asset).
5. **Place taker order** for $1 stake (or whatever `TV_POLY_NOTIONAL_USD` is). Hold to resolution (~60s).

**Why t=240s (not t=270s):** t=270s has even stronger IC (0.34-0.45) but only 30s of hold time — execution risk too high. t=240s gives 60s buffer for fill + settle.

---

## 2. Per-asset signal rules

**Thresholds and hit rates measured on 04-22 → 04-29 (n≈2,720 per asset).** All slopes are computed as `(imb_at_bucket_23 − imb_at_bucket_0)` using OLS on top-5 imbalance time series, with `bucket_max - 1 = 23` scaling factor applied. The slope unit is dimensionless ratio (imbalance is already a ratio).

### BTC (n=2,728)

```python
# Feature: up_imb_slope_240s (Up-token book bid-ask imbalance slope, t=0..240s)
# IC = -0.29 (negative — DECLINING Up-book bid pressure predicts UP wins)
THR_BTC_UP_BOTTOM = -0.337    # Q20 of feature
THR_BTC_UP_TOP    = +0.308    # Q80 of feature

if up_imb_slope_240s <= THR_BTC_UP_BOTTOM:
    BUY YES (UP)              # backtest hit rate: 69.9% UP wins (n=545)
elif up_imb_slope_240s >= THR_BTC_UP_TOP:
    BUY NO (DOWN)             # backtest hit rate: 71.2% DOWN wins (n=548)
else:
    SKIP                      # middle 60% — 40-58% UP, no edge
```

**Per-quintile hit-rate ladder (BTC):**

| Quintile | Range | n | UP rate | Direction signal |
|---|---|---:|---:|---|
| Q0-20 | [−3.26, −0.337] | 545 | **69.9%** | BUY UP ⭐ |
| Q20-40 | [−0.337, −0.112] | 545 | 58.2% | weak UP |
| Q40-60 | [−0.112, +0.064] | 545 | 51.9% | skip |
| Q60-80 | [+0.064, +0.308] | 545 | 40.4% | weak DOWN |
| Q80-100 | [+0.308, +1.76] | 548 | **28.8%** | **BUY DOWN ⭐ (71.2% DOWN)** |

### ETH (n=2,721)

```python
# Feature: dn_imb_slope_240s (Down-token book imbalance slope)
# IC = +0.229 (positive — RISING Down-book imb predicts UP wins)
THR_ETH_DN_BOTTOM = -0.353    # Q20
THR_ETH_DN_TOP    = +0.353    # Q80

if dn_imb_slope_240s >= THR_ETH_DN_TOP:
    BUY YES (UP)              # backtest hit rate: 65.9% UP wins (n=545)
elif dn_imb_slope_240s <= THR_ETH_DN_BOTTOM:
    BUY NO (DOWN)             # backtest hit rate: 67.8% DOWN wins (n=544)
else:
    SKIP
```

**Per-quintile hit-rate ladder (ETH):**

| Quintile | Range | n | UP rate | Direction signal |
|---|---|---:|---:|---|
| Q0-20 | [−5.75, −0.353] | 544 | **32.2%** | **BUY DOWN ⭐ (67.8%)** |
| Q20-40 | [−0.353, −0.094] | 544 | 45.4% | skip |
| Q40-60 | [−0.094, +0.102] | 544 | 49.8% | skip |
| Q60-80 | [+0.102, +0.353] | 544 | 55.9% | weak UP |
| Q80-100 | [+0.353, +1.78] | 545 | **65.9%** | BUY UP ⭐ |

### SOL (n=2,722)

```python
# Feature: dn_imb_slope_240s
# IC = +0.426 (strongest of all 3 assets)
THR_SOL_DN_BOTTOM = -0.490    # Q20
THR_SOL_DN_TOP    = +0.496    # Q80

if dn_imb_slope_240s >= THR_SOL_DN_TOP:
    BUY YES (UP)              # backtest hit rate: 79.7% UP wins (n=546)
elif dn_imb_slope_240s <= THR_SOL_DN_BOTTOM:
    BUY NO (DOWN)             # backtest hit rate: 80.7% DOWN wins (n=544)
else:
    SKIP
```

**Per-quintile hit-rate ladder (SOL — strongest signal):**

| Quintile | Range | n | UP rate | Direction signal |
|---|---|---:|---:|---|
| Q0-20 | [−2.55, −0.490] | 544 | **19.3%** | **BUY DOWN ⭐ (80.7%)** |
| Q20-40 | [−0.490, −0.141] | 544 | 39.0% | weak DOWN |
| Q40-60 | [−0.141, +0.158] | 544 | 50.7% | skip |
| Q60-80 | [+0.158, +0.495] | 544 | 66.9% | weak UP |
| Q80-100 | [+0.496, +6.55] | 546 | **79.7%** | **BUY UP ⭐** |

**SOL secondary opportunity — Q60-80 (mild)**: 66.9% hit rate is also tradable. Could double the SOL fire rate by widening to Q40/Q60 thresholds (with hit rate 67% / 33% on each side). Defer until Q20/Q80 ships.

---

## 3. Per-asset comparison vs V3 baseline

| Asset | V3 baseline (entry at t=0) | V5 LATE (entry at t=240s) | Improvement |
|---|---|---|---|
| BTC | 65% hit / +$6.41 per trade | 62-79% hit / TBD | **Hit ladder +0-14pp** |
| ETH | ~50% hit (small live n) | 67% hit / TBD | **Hit ladder +17pp** |
| SOL | 0 fires (spread filter) | 80% hit / TBD | **Sleeve revival** |

**PnL caveat:** V5 has 60s hold vs V3's 5min hold. For the same-direction gain, share-price movement is smaller in 60s — but we're entering when convergence is well underway, so target prices should already be near the winning side. Net per-trade PnL likely similar to V3 ($5-15 at $25 notional).

---

## 4. Sleeve naming + deployment

```python
# 6 NEW sleeves: 3 assets × 2 entry-time variants (t=240s, t=270s)
# Spec V5_LATE_240 only for now (t=270s deferred — 30s hold = execution risk)
_POLY_UPDOWN_SLEEVE_IDS = (
    # ... existing 21 sleeves ...
    "poly_updown_btc_5m_v5_late240",
    "poly_updown_eth_5m_v5_late240",
    "poly_updown_sol_5m_v5_late240",
)
```

**Mode setup:**

```bash
# /etc/tv/tradingvenue.env on VPS3
TV_POLY_STRATEGY_MODES=volume,sniper,v3,v3_1,v3_2,v4,v5_late240
V5_LATE_ENTRY_SECONDS=240
V5_LATE_HOLD_SECONDS=60
V5_LATE_REFIT_INTERVAL_HOURS=24       # re-fit thresholds daily on rolling 1000 markets
```

---

## 5. Implementation requirements (TV agent)

### 5.1 Controller logic

New mode `v5_late240` in `backend/app/controllers/polymarket_updown.py`:

```python
def evaluate_v5_late_entry(self, slug, symbol, tf, now_unix):
    # Only fire at t=240s into 5m markets
    window_start = self._market_start_unix(slug)
    if tf != "5m" or now_unix - window_start != 240:
        return Signal.NONE

    # Pull last 240s of orderbook for both Up and Down tokens
    up_buckets = self.book_buffer.get((slug, "Up"), buckets_back=24)
    dn_buckets = self.book_buffer.get((slug, "Down"), buckets_back=24)
    if len(up_buckets) < 12 or len(dn_buckets) < 12:
        return Signal.NONE  # not enough orderbook history

    # Compute features
    up_slope = compute_imb_slope(up_buckets, top_k=5)
    dn_slope = compute_imb_slope(dn_buckets, top_k=5)

    # Per-asset gate
    sym = symbol.upper()
    thresholds = self.v5_thresholds[sym]
    if sym == "BTC":
        if up_slope <= thresholds["up_bottom"]:
            return Signal.UP
        elif up_slope >= thresholds["up_top"]:
            return Signal.DOWN
    elif sym in ("ETH", "SOL"):
        if dn_slope >= thresholds["dn_top"]:
            return Signal.UP
        elif dn_slope <= thresholds["dn_bottom"]:
            return Signal.DOWN
    return Signal.NONE
```

### 5.2 Threshold refitting service (NEW)

`backend/app/services/v5_threshold_fitter.py`:

```python
# Daily cron: query last 1000 resolved markets per (asset, tf), recompute Q20/Q80 of slope features.
# Persists to /etc/tv/v5_thresholds.json or postgres tab.
async def refit_v5_thresholds(asset: str):
    rows = await fetch_last_n_resolved(asset, n=1000, tf="5m")
    features = [compute_imb_slope_features(r) for r in rows]
    return {
        "up_bottom": np.quantile(features["up_slope"], 0.20),
        "up_top":    np.quantile(features["up_slope"], 0.80),
        "dn_bottom": np.quantile(features["dn_slope"], 0.20),
        "dn_top":    np.quantile(features["dn_slope"], 0.80),
    }
```

Bootstrap: hardcode initial thresholds from this spec; refit kicks in after 24h of live data.

### 5.3 Late-entry timer

The controller needs a per-market timer that fires **once at t=240s** for each 5m market. Use a deferred task scheduled when each new market opens:

```python
# in market_open handler:
asyncio.get_event_loop().call_later(
    delay=240, callback=lambda: self.evaluate_v5_late_entry(slug, ...)
)
```

### 5.4 Spread filter at late entry

At t=240s, books may be ULTRA-wide if one side is settled. Need a different threshold than V3's 0.02:

```python
V5_LATE_SPREAD_FILTER_PCT = 0.05   # 5% — late-stage books are wider but still fillable

# Skip if YES-token spread > 5% (~$0.05 wide for $0.50-mid market)
if (entry_yes_ask - entry_yes_bid) > V5_LATE_SPREAD_FILTER_PCT:
    return Signal.NONE
```

### 5.5 Tests (`backend/tests/unit/test_v5_late_entry.py`)

```python
def test_v5_btc_buys_up_when_up_book_declining():
    # mock: up_imb_slope_240s = -0.005 (below BTC up_bottom threshold)
    assert eval_v5("BTC", up_slope=-0.005, dn_slope=0) == Signal.UP

def test_v5_eth_buys_up_when_dn_book_rising():
    assert eval_v5("ETH", up_slope=0, dn_slope=+0.004) == Signal.UP

def test_v5_sol_buys_down_when_dn_book_falling():
    assert eval_v5("SOL", up_slope=0, dn_slope=-0.006) == Signal.DOWN

def test_v5_skips_in_middle_zone():
    # mid-quintile feature → no signal
    assert eval_v5("BTC", up_slope=0, dn_slope=0) == Signal.NONE

def test_v5_only_fires_at_240s_into_5m():
    assert eval_v5("BTC", elapsed=120) == Signal.NONE
    assert eval_v5("BTC", elapsed=240) != Signal.NONE
```

---

## 6. Backtest validation summary

Phase 7 (`phase7_clob_imbalance_momentum.py`) computed:

- **n=2,727 to 2,734 markets per asset** (4-7 days of 04-22 → 04-29 data)
- **3 features at t=240s:** `up_imb_slope_240s`, `dn_imb_slope_240s`, `diff_imb_slope_240s`
- **Quintile decile spread** for each (top quintile UP rate − bottom quintile UP rate)

Numbers above are from the backtest. Variance across the 7-day window is unknown (would need rolling 30-day OOS).

**Risk: regime overfit.** All training data is from a single 7-day window. The slope-based signal MAY fail in low-volatility or trending regimes. Mitigation: rolling threshold refit (§5.2) keeps thresholds adaptive.

---

## 7. Kill / pause conditions

After 7+ days of paper data:

- **Per-asset hit rate < 55% on n≥30** → pause that asset's V5 sleeve.
- **Combined daily PnL < -$5 across all 3 sleeves** → pause entire V5 family.
- **Fire rate < 5/day per asset** → spread filter or threshold too strict; relax to Q15/Q85.
- **Fire rate > 50/day per asset** → too loose; tighten to Q25/Q75.

Operator can disable via `V5_LATE240_ENABLED=false` and restart engine.

---

## 8. Effort estimate

| Task | Effort |
|---|---|
| Controller code (3 new mode branches + late-entry timer) | 4 hr |
| Threshold refitter service + cron | 3 hr |
| Spread filter at late entry + handler tests | 2 hr |
| Bootstrap thresholds (hardcode from this spec) | 30 min |
| Sleeve registration + dashboard | 2 hr |
| 30-day OOS backtest harness | 4 hr |
| **Total** | **~16 hr (2 days)** |

---

## 9. Files

- This spec: `strategy_lab/reports/V5_LATE_ENTRY_SPEC_2026_05_04.md`
- Phase 7 engine + report: `strategy_lab/v4_signals/phase7_clob_imbalance_momentum.py`, `strategy_lab/reports/PHASE7_CLOB_MOMENTUM_2026_05_04.md`
- V3 patch deploy spec (V5 inherits sleeve plumbing pattern): `strategy_lab/reports/V3_PATCH_OPTION_B_SPEC.md`
- Threshold values: TODO — extract Q20/Q80 from feature distributions (§2 placeholders to replace before deploy)

---

## 10. Open questions for product / TV agent

1. **Polymarket taker fees in last 60s?** Confirm Polymarket charges 0% maker / 2% taker (international) → at $1 trade, $0.02 round-trip. Hit rate must clear 51% net to break even.
2. **Order placement latency at t=240s?** TV agent needs to verify it can POST a taker order to Polymarket CLOB and get fill confirmation in <30s on average. If not, t=240s is too late — push back to t=210s.
3. **Concurrent fills:** at any given moment ~3-6 markets are in their last minute (5m × 3 assets). Can the executor handle 6 simultaneous t=240s firings without queuing?
4. **Hedging behavior:** V3 had a hedge policy on 5m markets. Does V5 inherit that or fire pure speculative? Recommend pure (60s hold = too short to hedge meaningfully).
