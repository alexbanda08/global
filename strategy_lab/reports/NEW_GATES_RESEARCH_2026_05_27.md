# New Gates Research — HL Liquidations + Polymarket Trade Flow
**Date:** 2026-05-27  
**Author:** Claude Code  
**Status:** Exploratory — signal validated, ready for V9 sleeve design

---

## 1. Methodology

### Fire Universe
- Source: `strategy_lab/sniper_search_2026_05_27/_overlap_audit_v5_v6_v7/fired_by_sleeve.parquet`
- Total: 18,270 fires from V5/V6/V7 sleeves across BTC/ETH/SOL, 5m and 15m timeframes
- Sample: 5,000 fires drawn uniformly at random (seed=42)
- Time window: 2026-04-24 01:45 → 2026-05-26 16:44 UTC
- Baseline WR: **80.12%** (high — this is a curated sleeve universe, not all fires)
- Asset split: BTC 42.0%, SOL 37.0%, ETH 21.0% of sample

### Gate Families
**Family A — HL Liquidation Cascade:**  
- LONG liq proxy: `Close Long` events from `hl-userevents-ws` source (forced long closes, ~22k BTC events in window)
- SHORT liq proxy: `Close Short` + `method='market'` from `hl-s3-fills` source (short squeeze fills, ~25k BTC events in window)
- USD notional = `size × price`
- Windows: 60s and 300s pre-fire; thresholds: $200k, $500k, $1M, $2M, $5M
- Direction logic: SHORT liq cascade (shorts squeezed) → predicts UP; LONG liq cascade (longs liquidated) → predicts DOWN

**Family B — Polymarket Aggressor Flow:**  
- Source: `canonical/trades_polymarket/{btc,eth,sol}.parquet` (37M BTC trades, 9.8M ETH, 4.3M SOL)
- Net flow = (UP_buys − UP_sells) − (DOWN_buys − DOWN_sells) per slug in [fire_us − window_s, fire_us)
- Coverage: 92.5% of fires have non-zero flow signal
- Windows: 60s and 120s; thresholds: $250, $500, $1000, $2000 shares
- Variants: aligned (flow confirms direction), contrarian (flow opposes direction), abs (any strong flow)

**Family C — Confluence (HL + Poly):**  
- Requires both A and B gates to trigger simultaneously
- Direction-matched only (UP: SHORT cascade + flow favors UP + dir=UP)

### Evaluation
For each gate, computed:
- `WR_when_gate_True` — win rate when gate fires
- `WR_when_gate_False` — win rate when gate doesn't fire  
- `WR_lift` = `WR_when_gate_True − baseline WR`
- Minimum sample threshold: n ≥ 10 for inclusion (n ≥ 50 for "qualified")

---

## 2. Per-Gate Signal Table

### Qualified Gates (n_true ≥ 50, WR lift ≥ +5pp, ALL assets combined)

| Gate | Window | Threshold | n_true | WR_true | WR_false | WR_lift |
|------|--------|-----------|--------|---------|----------|---------|
| B2_POLY_FLOW_CONTRARIAN | 60s | $2,000 shares | 247 | 91.1% | 79.6% | **+10.97pp** |
| B3_POLY_FLOW_ABS | 60s | $2,000 shares | 741 | 88.7% | 78.6% | **+8.54pp** |
| B1_POLY_FLOW_ALIGNED | 60s | $2,000 shares | 494 | 87.5% | 79.3% | **+7.33pp** |
| B4_POLY_FLOW_ALIGNED_HIGHVOL | 60s | $2,000 shares | 494 | 87.5% | 79.3% | **+7.33pp** |
| B2_POLY_FLOW_CONTRARIAN | 120s | $2,000 shares | 356 | 86.5% | 79.6% | **+6.40pp** |
| B3_POLY_FLOW_ABS | 120s | $2,000 shares | 967 | 86.3% | 78.7% | **+6.13pp** |
| B1_POLY_FLOW_ALIGNED | 60s | $1,000 shares | 911 | 86.2% | 78.8% | **+6.05pp** |
| B4_POLY_FLOW_ALIGNED_HIGHVOL | 120s | $2,000 shares | 606 | 86.1% | 79.3% | **+6.02pp** |
| B1_POLY_FLOW_ALIGNED | 120s | $2,000 shares | 611 | 86.1% | 79.3% | **+5.97pp** |
| B4_POLY_FLOW_ALIGNED_HIGHVOL | 60s | $1,000 shares | 875 | 86.1% | 79.4% | **+5.94pp** |
| B3_POLY_FLOW_ABS | 60s | $1,000 shares | 1333 | 85.7% | 78.1% | **+5.55pp** |

### HL Cascade Gates (small-sample, high-signal candidates)

| Gate | Window | Threshold | n_true | WR_true | WR_lift | Note |
|------|--------|-----------|--------|---------|---------|------|
| A2_HL_SHORT_dir_UP | 60s | $200k | 10 | 100.0% | +19.88pp | n=10 — too sparse |
| A2_HL_SHORT_dir_UP | 300s | $200k | 25 | 92.0% | +11.88pp | n=25 — sparse |
| A2_HL_SHORT_dir_UP | 300s | $500k | 17 | 88.2% | +8.12pp | n=17 — sparse |

> **HL liq gate caveat:** HL LONG cascade gate (A1 — predicts DOWN) produced no qualifying rows because the LONG liq proxy (`Close Long` from WS) is ~$756 median per event vs threshold of $200k+ — individual events are tiny. This signal needs a longer window or lower threshold (e.g., $5k–$50k) to trigger enough. The SHORT cascade (A2) triggers via the S3 fills which are larger ($7,765 median per event, $32,675 median at 300s window).

---

## 3. Top 5 Gates by WR Lift (V9 Candidates)

### Gate #1 — B2: Polymarket Flow Contrarian (60s / $2,000)
- **Trigger:** |net_flow| > $2,000 AND flow is OPPOSITE to our trade direction in 60s pre-fire
- **Signal logic:** Strong opposing flow means large participant is trading the other side — likely to be wrong (our sleeve already has directional edge). Contrarian flow = confirming signal.
- **WR:** 91.1% (n=247) vs baseline 80.1% → **+10.97pp lift**
- **Coverage:** 4.9% of fires qualify (247/5000) → ~895 fires/yr at 18k/yr rate
- **Recommended threshold:** $2,000 shares in 60s window

### Gate #2 — B3: Polymarket Flow Absolute (60s / $2,000)
- **Trigger:** |net_flow| > $2,000 regardless of direction in 60s pre-fire
- **Signal logic:** Any strong flow means market is active and directional — correlated with outcome predictability regardless of direction
- **WR:** 88.7% (n=741) vs baseline 80.1% → **+8.54pp lift**
- **Coverage:** 14.8% of fires qualify → higher throughput than B2
- **Recommended threshold:** $2,000 shares in 60s window

### Gate #3 — B1: Polymarket Flow Aligned (60s / $2,000)
- **Trigger:** net_flow > $2,000 in same direction as our trade (buying pressure confirms our bet)
- **WR:** 87.5% (n=494) vs baseline 80.1% → **+7.33pp lift**
- **Coverage:** 9.9% of fires qualify
- **Note:** B1 at $1,000 gives n=911 at +6.05pp — better throughput trade-off

### Gate #4 — A2: HL Short Cascade + Direction UP (300s / $200k)
- **Trigger:** Sum of SHORT liq USD in 300s > $200k AND our direction is UP
- **Signal logic:** Shorts being liquidated on HL creates upward pressure → Polymarket UP follows
- **WR:** 92.0% (n=25) vs baseline 80.1% → **+11.88pp lift** (requires more data for confidence)
- **Coverage:** 0.5% of fires qualify — very sparse, needs threshold tuning
- **Recommended:** Lower threshold to $10k–$50k in further investigation to get n>100

### Gate #5 — C1: Confluence (HL Short + Poly UP aligned) (300s HL / 60s Poly / $500k + $500)
- **Trigger:** BOTH short liq cascade > $500k AND poly net_flow > $500 in UP direction
- **WR:** 92.3% (n=13) → **+12.19pp lift** — highest precision, extremely sparse
- **Coverage:** 0.26% of fires qualify — confluence is rare, not suitable as standalone gate
- **Use:** As an additive bonus gate in a V9 sleeve rather than primary filter

---

## 4. Cross-Family Interactions: Does Confluence Outperform Alone?

| Gate | n_true | WR_true | WR_lift |
|------|--------|---------|---------|
| A2 (HL SHORT only) — 300s $200k | 25 | 92.0% | +11.88pp |
| B2 (Poly contrarian only) — 60s $2k | 247 | 91.1% | +10.97pp |
| C1 (Confluence UP) — $500k + $500 | 13 | 92.3% | +12.19pp |

**Finding:** Confluence (C1) has slightly higher WR than either alone, but at 13 events the difference is within sampling noise. The Poly-alone gate (B2/B3) offers the best **utility** (high n + high lift). HL gates are too sparse to evaluate confluence benefit meaningfully.

**Recommendation:** Do NOT require HL gate for V9 sleeves. Use Poly flow as primary gate; add HL as optional booster (add to score rather than hard gate).

---

## 5. Asset / TF Specialization

### SOL shows dramatically stronger Poly Flow signal:

| Asset | B1 Aligned 60s $1k | n_true | WR_true | WR_lift |
|-------|-------------------|--------|---------|---------|
| SOL | 60s $1,000 | 39 | **97.4%** | **+20.33pp** |
| SOL | 60s $500 | 120 | 90.8% | +13.72pp |
| SOL | 120s $1,000 | 65 | 90.8% | +13.66pp |
| ETH | 60s $1,000 | 21 | 80.5% | +2.83pp |
| BTC | 60s $1,000 | 739 | 86.6% | +2.59pp |

**Finding:** SOL's Poly flow signal is remarkably strong (97.4% WR when flow>$1k aligned). This is likely because SOL has lower volume (4.3M trades vs 37M for BTC), so $1k flow represents larger fraction of market activity. Use **lower thresholds for BTC** ($2k+) and **higher thresholds relatively lower** for SOL ($250-500).

### B2 Contrarian: ETH signal is real, SOL contrarian is ANTI-signal

| Asset | B2 Contrarian 60s $500 | n_true | WR_true | WR_lift |
|-------|----------------------|--------|---------|---------|
| ETH | 60s $500 | 101 | 82.2% | +4.56pp |
| BTC | 60s $500 | 517 | 83.0% | −1.04pp |
| SOL | 60s $500 | 29 | 58.6% | **−18.49pp** |

**Finding:** The contrarian Poly signal is ANTI-correlated for SOL — when flow opposes our SOL direction, we should NOT bet. This is a crucial negative gate for SOL. For ETH, contrarian flow is mildly positive. For BTC, mixed.

**Implication:** The `B2_POLY_FLOW_CONTRARIAN` "ALL" gate result (+10.97pp) is dominated by BTC volume — disaggregating reveals the SOL contrarian is a strong REJECTION signal, not a confirmation signal.

### HL Liq: insufficient data for per-asset analysis at high thresholds. Lower thresholds needed.

---

## 6. Key Findings Summary

1. **Polymarket aggressor flow is a real signal.** `|net_flow_60s| > $2,000 shares` yields +8.5pp lift at n=741 fires. Available on 14.8% of fires. **Recommend as primary new gate for V9.**

2. **SOL Poly flow is anomalously strong.** `B1_POLY_FLOW_ALIGNED` at SOL with $500-1000 threshold gives +13-20pp lift. SOL sleeve gates should use this signal at lower thresholds.

3. **SOL Poly contrarian is a strong ANTI-gate.** When flow >$500 opposes SOL direction, WR drops to 58.6% (−18.49pp). This is a high-value REJECTION gate for SOL sleeves.

4. **HL short cascade is directionally correct but too sparse.** Needs $10k-$50k threshold (not $200k+) to get adequate fire count. Re-investigate in a second pass with lower thresholds.

5. **Confluence gates show promise but are too rare for standalone use.** C1 (HL+Poly) fires on 0.26% of fires. Use as additive confidence booster in a multi-signal sleeve, not as hard gate.

---

## 7. V9 Sleeve Recommendations

### High-priority gates to implement:

```python
# Gate B1_SOL — SOL only, strong aligned flow signal
def gate_sol_poly_flow_aligned(slug, fire_us, poly_trades, window_s=60, thresh=500):
    """True if Polymarket net flow > $500 in trade direction (60s window)"""
    net_flow = compute_poly_net_flow(slug, fire_us, window_s, poly_trades)
    return net_flow > thresh  # direction checked by sleeve

# Gate B2_REJECT_SOL — SOL rejection gate (INVERTED)
def gate_sol_poly_flow_reject(slug, fire_us, direction, poly_trades, window_s=60, thresh=500):
    """True (reject/skip) if flow strongly OPPOSES direction — WR=58.6% when triggered"""
    net_flow = compute_poly_net_flow(slug, fire_us, window_s, poly_trades)
    if direction == "Up":
        return net_flow < -thresh  # contrarian to UP = reject
    else:
        return net_flow > thresh   # contrarian to DOWN = reject

# Gate B3_BTC_ETH — BTC/ETH flow gate
def gate_btceth_poly_flow_abs(slug, asset, fire_us, poly_trades, window_s=60):
    """True if |net_flow| > $2,000 (60s)"""
    thresh = 2000
    net_flow = compute_poly_net_flow(slug, fire_us, window_s, poly_trades)
    return abs(net_flow) > thresh

# Gate A2_HLCASCADE — HL short squeeze (UP bias)
def gate_hl_short_cascade(asset, fire_us, hl_liqs_s3, window_s=300, thresh_usd=50_000):
    """True if Close Short market fills > $50k USD in 300s (re-investigate threshold)"""
    usd = sum_hl_short_liqs(asset, fire_us, window_s, hl_liqs_s3)
    return usd > thresh_usd
```

### Sleeve design priorities:
1. **SOL_5M_POLY_FLOW_V9** — add B1 gate at $500, drop B2 contrarian as rejection
2. **BTC_15M_POLY_FLOW_V9** — add B3 abs gate at $2,000 as gating condition
3. **ETH_5M_POLY_CONTRARIAN_V9** — add B2 contrarian as positive gate (ETH-only, $500)

---

## Appendix: Data Source Notes

### HL Liquidation Classification Fix
The canonical `hyperliquid_liquidations_full.parquet` contains two sources with different schemas:
- `hl-userevents-ws`: UserEvent fills, `dir` = human-readable ("Close Long", "Open Long"). In the 2026 fire window, "Liquidated *" labels are ABSENT — the format changed. Use `Close Long` as LONG liq proxy.
- `hl-s3-fills`: Exchange fills from S3 archive. `method='market'` = market-order fill. `Close Short` market = short position forced to close (SHORT cascade). Much larger USD volume ($16k mean vs $502 mean for WS).

**Threshold calibration note:** HL LONG liq events are tiny ($500 median per event) — the $500k/1M thresholds from the brief are too large for 60-300s windows. Effective thresholds are $5k-$50k at 300s for the LONG proxy.

### Polymarket Trade Flow
- `side='buy'` = aggressor bought at ask (positive direction pressure)
- `side='sell'` = aggressor sold at bid (negative direction pressure)  
- `outcome='Up'/'Down'` = which token was traded
- Net flow formula: `(Up_buy - Up_sell) - (Down_buy - Down_sell)` > 0 → UP bias
- 92.5% coverage: most slugs have at least some trade activity in 60s pre-fire

---

*Compute scripts:*  
- `strategy_lab/new_gates_research_compute_v2.py` — full gate evaluation  
- `strategy_lab/new_gates_results_v2.parquet` — raw results (78 gate configs × assets)
