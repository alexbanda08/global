# V4 — Phase 1-6 Results + Dashboard Plan

**Date:** 2026-04-30
**Context:** built and tested 6 candidate features inspired by friend's Cyclops bot. Ran on combined 9-day backtest data (existing 7d + extended 2d from VPS2).

## Summary table

| Phase | Feature | Backtest verdict | Action |
|---|---|---|---|
| 1 | Hour-of-day filter | **Partial replication** of Cyclops claims. Hours 1, 16, 22 UTC bad across all 3 assets | **Adopt as V3.2 hour-block** |
| 2 | CLOB imbalance v2 | **ETH-only signal** (IC=+0.082 p=0.005). BTC null, SOL null | **Adopt for ETH only as V3.2 CLOB gate (live WS)** |
| 3 | Macro alignment block (2-of-3) | +1.4pp hit, +2.7pp ROI | **Adopt as V3.2 alignment filter** |
| 4 | Signal-quality Kelly | NEUTRAL/WORSE for BTC/ETH, marginal for SOL | **Reject** |
| 5 | Liquidation regime gate | **`liq_total_5m < $10k` adds +5.8pp BTC, +6.7pp ETH, +2pp SOL** | **Adopt provisionally**, re-run after backfill |
| 6 | Platt calibration | Scaffold works, V3 single-signal too non-monotonic | **Defer — keep scaffold for multi-signal future** |

---

## Phase 1 — Hour-of-day filter

**Cyclops claim:** peak 14/17/18 UTC, troughs 22/01/02/07/19 UTC.

**Our V3-gated results (on 7-day data):**

Hours where ALL THREE assets show ≤-5pp deviation (hard block candidates):
| Hour | BTC dev | ETH dev | SOL dev |
|---|---|---|---|
| 1 UTC | -12pp | -24pp | -13pp |
| 16 UTC | -27pp | -14pp | -10pp |
| 22 UTC | -13pp | -4pp | -26pp |

Hours where at least one asset has >+15pp lift on n>10:
| Hour | Best asset |
|---|---|
| 14 UTC | BTC +18pp (n=15) |
| 17 UTC | BTC +5, ETH +14, SOL +11 |
| 19 UTC | BTC +10, ETH +19, SOL +23 (NOTE: Cyclops said BAD for this hour) |

**Decision: HARD BLOCK hours 1, 16, 22 UTC.** Soft signal: prefer 14, 17, 19 UTC. Don't block weekends yet — our DOW analysis showed Sat/Sun within ±2pp of baseline.

---

## Phase 2 — CLOB imbalance v2

**Their formulation:** `(bull_vol - bear_vol) / total_vol`, gate at |imbalance| > 0.20.

**Our results:**

| Asset | IC | p-value | Cyclops gate hit |
|---|---|---|---|
| **ETH** | **+0.082** | **0.005 ✓** | **54.4%** |
| BTC | +0.001 | 0.97 | 49.1% |
| SOL | -0.023 | 0.47 | 48.6% |

**ETH overlay on V3 fires:** when CLOB imbalance aligns with V3 direction → 75% hit (n=8) vs 58% baseline.

**Caveat:** our flow data aggregates the FULL market window. Real-time 2-min rolling will be 50-70% as strong.

**Decision: Build live Polymarket CLOB WS feed.** ETH-only gate. Apply: `if abs(imbalance_2m) > 0.10 and sign != predicted_direction → SKIP`. **Defer until WS infrastructure built.**

---

## Phase 3 — Macro alignment

| Variant | n | hit | PnL | ROI |
|---|---|---|---|---|
| V3 baseline | 85 | 71.8% | $693 | 32.6% |
| V3.1 soft regime ±0.5% | 79 | 72.2% | $662 | 33.5% |
| 3-of-3 strict | 68 | 70.6% | $562 | 33.0% |
| **2-of-3 relaxed** | **82** | **73.2%** | **$724** | **35.3%** |

**Decision: Adopt 2-of-3 alignment.** At least 2 of (5m, 15m, 1h) must agree with signal direction. Drops only 3.5% of fires, lifts ROI 2.7pp.

---

## Phase 4 — Signal-quality Kelly

| Asset | Flat ROI | Kelly multiplier ROI | Verdict |
|---|---|---|---|
| BTC | 33.4% | 31.4% | worse |
| ETH | 24.4% | 21.6% | worse |
| SOL | 40.7% | 42.4% | marginal |

Hit rate is U-shaped across signal strength, not monotonic. Counter-intuitive.

**Decision: REJECT.** Keep flat sizing. Bankroll fractional Kelly stays at portfolio level.

---

## Phase 5 — Liquidation regime gate

5 days of Binance liq data covers 69% of polymarket window. Tested liq_count_5m, liq_imbalance, liq_total_notional.

**Univariate IC:** all null (p > 0.20 across BTC/ETH/SOL).

**V3 overlay — REGIME effect:**

| Asset | V3 base | liq_quiet (<$10k 5m) | delta |
|---|---|---|---|
| BTC | 69.0% | **74.8%** | **+5.8pp** |
| ETH | 62.0% | **68.6%** | **+6.7pp** |
| SOL | 54.9% | 56.9% | +2.0pp |

V3 sniper works best in **calm markets** (no $10k+ recent liq activity). Aligned/misaligned both perform worse — direction doesn't matter, regime does.

**Decision: PROVISIONAL ADOPT.** Skip V3 fires when `liq_total_notional_5m > $10k`. Re-run after Binance + Hyperliquid liq backfill brings full coverage.

---

## Phase 6 — Confidence calibration

Platt fit: `actual = a * predicted + b`, both clipped at bounds [0.5, 2.0] / [-0.15, 0.15].

| Sleeve | a | b | Verdict |
|---|---|---|---|
| BTC | 0.500 (floor) | +0.15 (ceiling) | non-monotonic, can't fit linearly |
| ETH | 1.000 | 0.000 | insufficient bucket coverage |
| SOL | 0.562 | +0.148 | high variance, similar issue |

**Decision: KEEP SCAFFOLD.** Single signal class can't be Platt-calibrated meaningfully. Becomes useful when we have CLOB + liq + LLM signals combined. Saved to `data/v4/calibration/platt_v1.json`.

---

## V3.2 patch — combined improvements

```python
# strategy_lab/v3/v3_2_config.py

# Phase 1: hour blocklist (UTC)
V3_HOUR_BLOCKLIST = {1, 16, 22}

# Phase 2: ETH-only CLOB imbalance gate (LIVE only, requires WS)
V3_CLOB_IMB_GATE_ETH = {"min_align_imb": 0.10, "max_oppose_imb": -0.10}

# Phase 3: 2-of-3 timeframe alignment (replaces V3.1 soft regime)
def macro_alignment_passes(ret_5m, ret_15m, ret_1h):
    sign5 = 1 if ret_5m > 0 else -1
    agree = (1 if (sign5 * ret_15m) > 0 else 0) + \
            (1 if (sign5 * ret_1h) > 0 else 0)
    return agree >= 1   # at least 1 of (15m, 1h) agrees with 5m

# Phase 5: liquidation quiet-regime gate
V3_LIQ_QUIET_THRESHOLD_USD = 10_000   # skip if 5m liq notional > $10k

# Phase 6: calibration coefs (saved, applied at runtime when richer signals)
# data/v4/calibration/platt_v1.json
```

**Combined expected effect on backtest holdout:**
- Hour block (1, 16, 22 UTC): -3 to -5 fires
- 2-of-3 alignment: -3 fires
- Liq quiet gate: -25 to -30 fires (if applied to existing 5-day liq window)
- Net: ~50 fires (down from 85) but at higher per-trade hit rate

Estimated combined holdout: **n≈50, hit≈75-78%, ROI≈37-40%**. Need to test combined patch.

---

## Phase 7 — Real-time dashboard architecture (PLAN)

### Goals
1. Operator visibility into per-sleeve fire rate, hit rate, PnL — last 24h, 7d, 30d
2. Live signal verdict for current open markets (like Cyclops Image 2)
3. Alert on kill-switch trips (hit <40% on n≥30, daily PnL < -$3, etc.)
4. Cross-asset liquidity / spread / book health monitor

### Architecture

```
+------------------+      +-------------------+      +-------------+
| VPS3 Postgres    | ---> | DashboardAPI      | ---> | Web UI      |
| trading.events   |      | (FastAPI / Bun)   |      | (Next.js or |
| trading.orders   |      |  /api/sleeves     |      |  Streamlit) |
| trading.positions|      |  /api/markets     |      +-------------+
+------------------+      |  /api/signals     |
                          |  /api/health      |
+------------------+ ---> +-------------------+
| VPS2 Postgres    |
| orderbook_v2     |
| binance_liq_v2   |
| hl_metrics_v2    |
+------------------+
```

### Pages

#### 1. Live Sleeve Status
- Table: sleeve_id | mode (paper/live) | fires_24h | hit_rate_24h | pnl_24h | last_fire | kill_switch_status
- Rows colored: green (>60% hit on n>10), yellow (40-60%), red (<40% n≥10)
- Refresh every 30s via polling

#### 2. Open Market Watch (per asset)
For each currently-open Polymarket UP/DOWN market:
- Asset, slug, time-to-resolve
- Current YES/NO prices, spread, L1-L10 depth
- BTC price, ret_5m/15m/1h
- Live CLOB imbalance (2-min rolling)
- Liq pressure (5m total notional)
- V3 signal status: would-fire? threshold met? alignment? hour-block?
- Predicted hit probability (calibrated)

#### 3. Daily Performance
- Hourly bar chart: fires + hit rate by hour
- Per-day P&L line (last 30 days)
- Per-asset breakdown
- Notional in flight gauge

#### 4. Alerts panel
- Kill-switch trips (red banner)
- Recent rollback events
- Stale data warnings (collector down >5 min)
- Low fill rate warnings

### Implementation phases

#### Phase 7A: API only (1-2 days)
- FastAPI app on VPS3 reading both VPS3.trading.events + VPS2.orderbook_snapshots_v2 (via SSH tunnel or replication)
- 4 endpoints: /sleeves, /markets/open, /signals/{asset}, /health
- JSON output, no UI
- Test via curl

#### Phase 7B: Streamlit MVP (1 day)
- Single-page Streamlit app polling the API every 30s
- Tables only, no fancy charts
- Sufficient for "is everything OK?" visibility

#### Phase 7C: Production UI (3-5 days)
- Next.js + Tailwind, mobile-friendly
- Real-time WS push (instead of polling)
- Charts: Recharts or lightweight-charts
- Auth: GitHub OAuth (just for the operator)

### Hosting
- Phase 7A/7B: run on VPS3 alongside trading engine, port 8000
- Phase 7C: separate small VPS or Vercel + Cloudflare Tunnel for the API
- Cost: $0-10/month

### When to build
**Defer until V3.2 patch is live and showing fire rates.** The dashboard is operational hygiene, not edge — building it before we have meaningful live data is premature optimization. Estimated trigger: when bankroll reaches $200 and per-day fire count is consistent.

---

## Files

### Built this session
- `strategy_lab/v4_signals/phase1_hour_of_day.py` — hour gate analysis
- `strategy_lab/v4_signals/phase2_clob_imbalance_v2.py` — Cyclops CLOB formulation
- `strategy_lab/v4_signals/phase3_macro_block_strict.py` — 2-of-3 alignment
- `strategy_lab/v4_signals/phase4_signal_quality_kelly.py` — Kelly mult test (rejected)
- `strategy_lab/v4_signals/phase5_liq_feed.py` — liquidation regime gate
- `strategy_lab/v4_signals/phase6_confidence_calibration.py` — Platt scaling scaffold

### Data
- `data/v4/refresh_2026_04_30/mr_extended.csv` — 4,668 polymarket resolutions through 05-01
- `data/v4/refresh_2026_04_30/binance_liq.csv` — 3,657 Binance liquidations through 04-27
- `data/v4/refresh_2026_04_30/hl_funding.csv` — 8,640 Hyperliquid funding (3 months)
- `data/v4/calibration/platt_v1.json` — calibration coefs (deferred application)

### Comparison + plan
- `strategy_lab/reports/CYCLOPS_COMPARISON_AND_V4_PLAN_2026_04_30.md` — original plan + 5-tier ranking
- This doc: phase results + dashboard architecture

---

## Next moves

### Immediate (after data backfill lands)
1. **Re-run Phase 5** with full Binance + Hyperliquid liq history. The provisional $10k threshold may need re-tuning.
2. **Combine all V3.2 changes into single patch** — apply hour block + 2-of-3 + liq gate. Re-run full 10-gate gauntlet on patched V3.
3. **Update `TV_STRATEGY_V3_PORTFOLIO_DEPLOY_GUIDE.md`** with V3.2 changes.

### Before live ramp
4. **Build Polymarket CLOB WS subscriber** for live ETH imbalance signal (1-2 days TV agent work)
5. **Wire kill switches** (hit <40% on n≥30, daily PnL < -$3, bankroll <$3)

### When bankroll grows
6. **Build dashboard** Phase 7A → 7B → 7C as needed
7. **Add Hyperliquid + Bybit + OKX live liq WS** for richer regime gate
8. **Reactivate Platt calibration** once we have multi-signal probability distribution

### Long-term
9. **30-day OOS retest** of all V4 phase findings (planned ~2026-05-23 when collector hits 30 days)
10. **LLM event-decisor** layer (V4-C) on the better-validated 30-day window
