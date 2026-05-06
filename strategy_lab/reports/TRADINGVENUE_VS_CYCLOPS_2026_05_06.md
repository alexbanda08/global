# Tradingvenue vs Cyclops — Architecture Comparison

**Date:** 2026-05-06
**Purpose:** Compare our Tradingvenue stack against the Cyclops 4-layer confluence bot to identify gaps, opportunities, and where we're already ahead.

---

## TL;DR

| Dimension | Tradingvenue | Cyclops | Verdict |
|---|---|---|---|
| Signal sophistication | 1 base signal (`sig_ret5m`) with progressive filter stacks (V3 → V4) | 4 independent confirmation layers (STRUCTURE/FLOW/TRIGGER/GUARD) | **Cyclops ahead** — feature richness |
| Order-flow microstructure | Phase 7 (imbalance) only, Phase 9 (trade flow) deferred | Full FLOW layer: CVD, aggressor, OB imbalance, Coinbase Premium | **Cyclops ahead** — but we have the raw data |
| Pattern memory | None | 240-segment similarity bank | **Cyclops ahead** — entirely missing on our side |
| Market regime | macro_2of3 / hour blocklist / ret_1h gate (V3.2) | Explicit regime classifier (TREND/SIDEWAYS/UNCERTAINTY) with hysteresis | **Cyclops slightly ahead** |
| Tiered sizing | Fixed $1/trade per sleeve | GOLD/SILVER/BRONZE → quality-weighted Kelly | **Cyclops ahead** for adaptive sizing (our Kelly test failed but on single-feature signal) |
| Triggers (FVG, OFI, liq magnets) | None | Layer 3 entry triggers | **Cyclops ahead** — gap |
| Extreme-price filter (38-62¢) | Spread filter only | Hard 0.35-0.65 cutoff | Worth testing |
| Dead-market filter | None | 90s + <$5 BTC blocks | Worth testing |
| Smart counter-trend | None — fires on direction of \|ret_5m\| burst | Allows mean reversion, blocks continuation | **Major gap** — matches our SOL inversion finding |
| **Risk infrastructure** | **9-rail framework + watchdog + dead-man + 3-layer kill** | Filters baked into entry logic | **WE WIN — production-grade** |
| **Multi-venue** | HL perps + Polymarket + Kalshi | Polymarket only | **WE WIN — cross-venue diversification** |
| Supervisor / oversight | Claude Agent SDK supervisor (4th systemd unit) | Telegram notifications only | **WE WIN — autonomous oversight** |
| Backtest infrastructure | Production-faithful framework (95-100% dir match), 21 sleeves, shadow-vs-backtest auditing | Not described | **WE WIN — quant rigor** |
| Code maturity | 22-phase GSD roadmap, .planning/ artifacts, 4805 LOC engine, 11 risk rails | "3 days of work" v118-v124 with rapid iteration / rollbacks | **WE WIN — discipline** |

**Net assessment:** We have the better engineering foundation (risk, oversight, multi-venue, backtest rigor). Cyclops has the better SIGNAL (feature richness, pattern memory, smart filters). The right move is to LIFT Cyclops's signal ideas onto our infrastructure — not the reverse.

---

## 1. Project structure side-by-side

### Tradingvenue (us)

```
Tradingvenue/
├── backend/app/
│   ├── api/                 ← FastAPI HTTP/WS, kill endpoints, supervisor APIs
│   ├── controllers/         ← polymarket_updown.py (2647 LOC), hyperliquid_*, v52/* (8 files)
│   ├── engine/              ← bar_engine, poly_updown_loop, risk_guardrails, snapshot_writer (4805 LOC)
│   │   └── rails/           ← 11 risk rails (per-position SL, sleeve DD, portfolio DD 15/25/30, funding, outage, concentration, correlation, abs day loss)
│   ├── strategies/
│   │   ├── polymarket/      ← updown_5m, updown_15m, inverse, base
│   │   ├── hyperliquid/     ← bbbreak_ls, cci_extreme_rev, htf_donchian, regime_filter, v24_xsm
│   │   ├── kalshi/          ← (skeleton)
│   │   └── v52/             ← blender, exits, regime, signals, sizing
│   ├── venues/              ← hyperliquid client (46k LOC), polymarket py-clob-client-v2
│   ├── executors/           ← order placement state machine
│   ├── supervisor/          ← Claude Agent SDK supervisor
│   └── watchdog/            ← independent kill layer with separate creds
├── .planning/               ← 22-phase GSD roadmap, REQ-IDs, STATE.md
├── docs/                    ← runbooks, contracts, kill runbook, rails doc
├── infra/                   ← systemd units, caddy, journald, backup
└── frontend/                ← Next.js UI

global/                       ← The strategy lab (separate from production)
├── strategy_lab/            ← backtest framework, V3 patches, anti-edge analyzer
├── data/v4/                 ← shadow trades, refresh data, Binance klines
└── data/                    ← BTCUSDT, hyperliquid, coinapi
```

### Cyclops (described)

```
Cyclops/
├── PressureEngine            ← buy/sell pressure aggregator → UP/DOWN/SKIP direction
├── HeatmapEngine             ← 5-channel heatmap (OB pressure, CVD, liq wall, Coinbase Prem, trade aggr)
├── BTCPatternMemory          ← 240 historical segments + similarity score
├── Layers
│   ├── STRUCTURE             ← BTC trend + memory + S/R levels
│   ├── FLOW                  ← CVD, aggressor, OB imbalance, Polymarket momentum
│   ├── TRIGGER               ← liquidation magnet, FVG, OFI
│   └── GUARD                 ← overextension, fake impulse, choppiness, price anomaly
├── Tier classifier           ← GOLD (4/4) / SILVER (S+F) / BRONZE (F+T) / SKIP
├── Smart Kelly sizer         ← edge × confidence × time × momentum × regime
└── Filters
    ├── Extreme price (0.35-0.65)
    ├── Dead market (90s/$5)
    ├── Smart counter-trend
    └── Min time / overextension / choppiness / freshness / slippage / min edge
```

---

## 2. Signal architecture comparison

### Our `sig_ret5m` family (V3 → V4)

```python
# strategies/polymarket/updown_15m.py — 96 LOC
def signal(bars, config, aux):
    if aux["ret_5m"] is None: return NONE
    if mode == "sniper" and abs(ret_5m) < threshold: return NONE
    return UP if ret_5m > 0 else DOWN
```

**Filters layered upstream in `controllers/polymarket_updown.py` (2647 LOC):**
- Per-asset quantile: BTC q90 / ETH q95 / SOL q85
- Per-asset spread filter: BTC 2% / SOL 2.5%
- V3.1: asymmetric quantile (q92 UP / q85 DN for SOL)
- V3.1: regime gate (`ret_1h` sign vs threshold)
- V3.2: macro_2of3 (≥2 of {ret_5m, ret_15m, ret_1h} match direction; SOL exempt)
- V3.2: hour blocklist {1, 16, 22} (audit pending — hour 16 actually winner)
- V3.2: liquidations-quiet gate
- V3.3: V3.2 + multi-horizon AND filter for SOL
- V4: V3.1 quantile + V3.2 gates + MH stack
- HYBRID branch-2 mid-window hedge (opposite-side entry on N bps adversity)

**Strength:** Single, well-tested base thesis (Binance 5m latency leakage to Polymarket). Filters are progressive, controllable via env flags.
**Weakness:** ONE feature axis. No microstructure, no pattern memory, no liquidity/flow signals.

### Cyclops 4-layer confluence

```python
if s_align and f_align and t_active and s_conf >= 0.50 and f_str >= 0.50:
    return {"tier": "GOLD", "fair_prob": 0.72, "size_pct": 0.020}
if s_align and f_align and s_conf >= 0.30 and f_str >= 0.40:
    return {"tier": "SILVER", "fair_prob": 0.64, "size_pct": 0.015}
if f_align and t_active and f_str >= 0.40:
    return {"tier": "BRONZE", "fair_prob": 0.54, "size_pct": 0.010}
```

- **STRUCTURE:** BTC trend, S/R, pattern memory similarity score
- **FLOW:** CVD, aggressor, multi-exchange OB imbalance, Polymarket-internal momentum
- **TRIGGER:** liquidation magnet, FVG, OFI
- **GUARD:** overextension, fake impulse, choppiness, anomaly

**Strength:** Multiple INDEPENDENT confirmation axes. Each layer can fail without killing the trade if others compensate (BRONZE = FLOW+TRIGGER without STRUCTURE).
**Weakness:** Each layer is a moving target. Filter changes have wide blast radius. The 3-day version sprint (v118 → v124, with rollback at v122) suggests instability under tight feedback loops.

---

## 3. Data sources

| Data | Tradingvenue uses | Cyclops uses | We have it? |
|---|---|---|---|
| Binance spot 1m closes | ✓ (sig_ret5m core) | (BTC trend) | ✓ via storedata `binance_klines_v2` (binance-spot-ws on VPS3) |
| Polymarket orderbook L2 snapshots | minimal (entry price only) | central to FLOW layer | ✓ `orderbook_snapshots_v2` 16M+ rows |
| Polymarket trade prints | none (Phase 9 deferred) | central | ✓ `trades_v2` 16.8M rows on VPS2 |
| Multi-exchange OB | none | yes (Coinbase, Binance, Bybit) | ✗ only Binance + HL collected |
| CVD (cumulative volume delta) | none | central | derivable from `trades_v2` |
| Liquidation feeds | none in production (gate disabled) | central (TRIGGER) | ✓ but disabled |
| Coinbase Premium | none | one of 5 heatmap channels | ✗ |
| Pattern memory | none | 240-segment bank | ✗ |
| Funding rates | rail_06 only (alert), not signal | none mentioned | ✓ |
| Derivatives Z-scores | lab-only (META_CLASSIFIER tested, rejected) | none | ✓ |

**Takeaway:** We've COLLECTED most of what Cyclops uses. We just haven't BUILT the FLOW engine on top of it.

---

## 4. Risk & oversight

| Layer | Tradingvenue | Cyclops |
|---|---|---|
| Per-position SL | rail_01 hard rail | min edge 1.5-2% pre-trade |
| Sleeve DD | rail_02 24h | none mentioned |
| Portfolio DD | rail_03 (15%) / rail_04 (25%) / rail_05 (30% kill) | none |
| Funding spike | rail_06 | n/a (no perps) |
| Exchange outage | rail_07 | n/a |
| Concentration | rail_08 | n/a |
| Correlation | rail_09 | n/a |
| Abs day loss | rail_11 | none |
| Kill paths | 3 layered (UI + watchdog + webhook + dead-man) | manual |
| Independent watchdog | tv-watchdog with separate venue creds | none |
| Dead-man enforcer | yes (vacation mode) | none |
| Supervisor | Claude Agent SDK 24/7 | Telegram alerts |
| Backup/restore drill | Phase 16 dedicated | none |

**This is where we DOMINATE.** Cyclops is a fast-iterating signal bot. We're a $100k+ capital production platform with safety-critical engineering.

---

## 5. Concrete idea transplant — Cyclops → Tradingvenue

These are signal-side ideas worth lifting onto our infra. Rated by **expected impact × ease of implementation**.

### 🔴 HIGH impact / MEDIUM effort

**A. FLOW engine (Phase 9 unblock)**
- We have `trades_v2` (16.8M rows) and `orderbook_snapshots_v2`. Build a feature pipeline:
  - CVD over rolling 1m / 5m windows
  - Aggressor ratio (taker buys / total)
  - Top-of-book imbalance (already partially in Phase 7)
- Add as `aux["flow_*"]` features alongside `aux["ret_5m"]`.
- Use as either: (a) replacement for V3.2 macro_2of3, (b) additional V3.2.5 sleeve, (c) UNION strategy with V3 (analogous to V3+Phase 7 UNION which we already validated).

**B. Smart counter-trend (mean reversion vs continuation split)**
- This DIRECTLY matches our SOL inversion finding (89% inverse hit on V3-family).
- Logic: if BTC moved ≥$10 from market start AND velocity > $3/min in same direction → BLOCK that direction (continuation).
- If BTC moved ≥$10 from start but velocity REVERSED → ALLOW (mean reversion).
- Already validated by our own data: SOL signals are mean-reversion candidates, not momentum-continuation.

**C. Extreme-price filter (0.35-0.65 working zone)**
- Cyclops: blocks entries at <0.35 or >0.65.
- We have `entry_price` in shadow data — easy to backtest a band gate.
- Likely improves PnL by killing low-edge late entries (we already partially saw this in V5 LATE rejection).

### 🟡 MEDIUM impact / MEDIUM effort

**D. Tiered fair-prob system (GOLD/SILVER/BRONZE)**
- Replace binary fire with a probability-weighted system:
  - GOLD = V4 fires AND FLOW agrees AND no GUARD blocks → fair_prob 0.72 → size 2x
  - SILVER = V3 fires AND FLOW agrees → fair_prob 0.64 → size 1x
  - BRONZE = FLOW + TRIGGER without V3 → fair_prob 0.54 → size 0.5x
  - SKIP otherwise
- Sizes vary by tier. Current "fixed $1" loses information about confidence.
- Note: our Kelly test rejected pure Kelly on a SINGLE-feature signal. Tiered Kelly on a CONFLUENCE signal is a different beast.

**E. Dead-market filter**
- 90s post-market-open + <$5 BTC move → block entry.
- Cheap to implement (controller already has timestamp + ret_5m magnitude).
- Needs validation: does our shadow data show low-velocity bars are actually losing?

**F. Market regime classifier**
- We have macro_2of3 + hour gate + ret_1h regime. Cyclops has an explicit classifier with hysteresis.
- Worth implementing: regime = strong_trend / moderate_trend / sideways / uncertain based on rolling vol + autocorrelation. Use to gate variant choice (e.g. V3.3 multi-horizon only in trend regime; V3 base in sideways).

### 🟢 LOW impact / HIGH effort

**G. Pattern memory (240-segment bank with similarity score)**
- Powerful but complex. Requires per-bar feature vector + retrieval + Bayesian update.
- Ours is a 5-min binary market — pattern memory is more useful on continuous trading (HL perps), less on binary settlement.
- **Defer.** Maybe useful on the v52 HL strategies, not on Polymarket UpDown.

**H. Liquidation magnet trigger**
- Cyclops uses liquidation level proximity as a trigger.
- We have liquidation data but the V3.2 liq_quiet gate is currently DISABLED in env (per code).
- Low priority — small subset of bars affected.

### ❌ DON'T DO

**I. Multi-exchange OB aggregation**
- Cyclops aggregates Coinbase + Binance + Bybit OB. We'd need new collectors.
- Storedata is one-VPS, geoblock-constrained. The marginal info from cross-exchange is small for a 5m horizon.

**J. Telegram-only oversight**
- We have a Claude Agent SDK supervisor. Don't downgrade.

---

## 6. What Cyclops should learn from us (if they asked)

1. **Wire kill paths through 3 layers.** Their entry filters won't save them when an exchange outage holds positions open. Our `rail_07_exchange_outage.py` is sample code.
2. **Add a watchdog with independent venue credentials.** Their bot is one process — single point of failure.
3. **Don't roll back filter changes mid-week (v122).** That's what backtest infrastructure is for. Validate offline before promoting.
4. **Define a contract with the data layer.** They scrape APIs ad-hoc. Storedata-style co-resident DB consumer pattern would buy them stability.
5. **Rolling 14d quantile for thresholds, not fixed.** Their min-edge of 1.5-2% is probably a tunable threshold; ours is rolling so it auto-adapts to vol regime.

---

## 7. Recommended next steps

| Priority | Action | Owner | Effort |
|---|---|---|---|
| 1 | Build FLOW engine (CVD + aggressor + OB imbalance) on top of `trades_v2` + `orderbook_snapshots_v2`. Add as `aux["flow_*"]`. | LAB | 3-5 days |
| 2 | Backtest smart counter-trend split (mean reversion allow / continuation block) on SOL family. Should match our 89% inverse finding. | LAB | 1-2 days |
| 3 | Backtest extreme-price filter (0.35-0.65) on shadow data. | LAB | half day |
| 4 | Design tiered confluence sleeve: V3 + FLOW + EXTREME-PRICE → GOLD/SILVER/BRONZE classifier with size scaling. | LAB | 2-3 days |
| 5 | Implement dead-market filter and backtest. | LAB | half day |
| 6 | Defer pattern memory and multi-exchange OB. | — | — |

If FLOW engine + counter-trend split + extreme-price + tiered sizing all validate, we'd have something better than Cyclops PLUS our existing risk infrastructure — which is the actual moat.

---

## 8. Files

- This report: `strategy_lab/reports/TRADINGVENUE_VS_CYCLOPS_2026_05_06.md`
- TV controller (PROD reference): `data/v4/refresh_2026_05_02/polymarket_updown_PROD_2026_05_05.py`
- TV planning roadmap: `Tradingvenue/.planning/ROADMAP.md` (22 phases)
- TV risk rails: `Tradingvenue/backend/app/engine/rails/` (11 rails)
- Companion: `strategy_lab/reports/COMBINED_V3_PHASE7.md` (existing UNION baseline)
- Companion: `strategy_lab/reports/ANTI_EDGE_FINDINGS.md` (existing inversion finding — matches Cyclops smart counter-trend)
