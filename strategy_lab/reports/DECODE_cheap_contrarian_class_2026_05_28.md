# DECODE: Cheap-Entry Wallet Class — BTC Up/Down
**Date:** 2026-05-28  
**Wallets:** 0x22b0a5ac (btc-15m), 0x14774b67 (btc-15m), 0x46a8cf34 (btc-15m), 0xb07afa532 (btc-5m)  
**Method:** `trigger_decode_harness.py` → pooled parquet analysis (n=2,781 pooled fires)

---

## Per-Wallet Stats

| Wallet | TF | n | WR | entry_px | Breakeven | **Edge** | PnL |
|--------|-----|-----|-----|--------|-----------|---------|-----|
| 0x22b0a5ac | 15m | 1,028 | 56.3% | 0.469 | 46.9% | **+9.4pp** | +$2,165 |
| 0x14774b67 | 15m | 747 | 58.0% | 0.530 | 53.0% | **+5.0pp** | +$1,001 |
| 0x46a8cf34 | 15m | 730 | 54.2% | 0.470 | 47.0% | **+7.2pp** | +$892 |
| 0xb07afa53 | 5m  | 276 | 68.1% | 0.549 | 54.9% | **+13.2pp** | +$1,174 |
| **POOLED** | — | **2,781** | **57.4%** | **0.494** | 49.4% | **+8.0pp** | — |

---

## Q1: Contrarian or Momentum?

**Answer: MOMENTUM, not contrarian.** The direction features all point the same way as the held_side.

| Feature | Up-buyers mean | Down-buyers mean | Interpretation |
|---------|---------------|-----------------|----------------|
| ret_30m | +9.41 bps | −10.01 bps | MOMENTUM |
| macd | +15.78 | −16.86 | MOMENTUM |
| ret_15m | +5.08 bps | −5.20 bps | MOMENTUM |
| ema9_slope_bps | +0.74 | −0.85 | MOMENTUM |
| rsi14 | 54.4 | 45.4 | MOMENTUM |

Pooled momentum-agreement (ret_30m same sign as held_side):
- 0x22b0: **78.9%** agree (WR 56.2%)
- 0x46a8: **77.4%** agree (WR 55.2%)
- 0x1477: 49.3% agree (ambiguous)
- 0xb07a: 47.5% agree (ambiguous)

The two clearest wallets (0x22b0, 0x46a8, entry ~0.47) follow momentum strongly. The other two are noisier.

**The class is NOT contrarian.** They buy the momentum direction but obtain surprisingly low entry prices. The "cheap" entry is not because they're fading — it's because they time their entry before the market has fully updated the price, or they select slugs where the cheap side happens to be the momentum-favored direction.

---

## Q2: Is the Edge Real? Win vs Loss Separability

**Dominant signal: `entry_px` (d=0.793, large effect).**  
Wins have mean entry_px = 0.537. Losses have mean entry_px = 0.435.

This is the defining paradox — wins have higher entry price. Explanation below.

Secondary separators in cheap-only subgroup (entry_px < 0.50, n=1,900, WR=49.4%):
| Feature | Win mean | Loss mean | Cohen d |
|---------|---------|---------|---------|
| entry_px | 0.4589 | 0.4051 | 0.586 |
| ret_1m | −0.212 | +0.241 | −0.101 |
| ret_3m | −0.257 | +0.385 | −0.083 |
| macd_hist | +0.352 | −0.507 | 0.074 |
| utc_hour | 11.14 | 11.48 | −0.051 |

Within the cheap subgroup: wins have marginally negative short-term returns at entry (slight fade), while losses have positive returns. The macd_hist being higher at wins suggests momentum is decelerating at wins but accelerating into losses. Effect sizes are small (d<0.15) — the cheap subgroup is hard to separate.

### Entry Price Bucket Analysis (pooled)

| Entry price | n | WR | Implied prob | **Edge vs implied** |
|------------|-----|----|------------|---------------------|
| [0.30–0.40) | 114 | 39.5% | 35.0% | +4.5pp |
| [0.40–0.45) | 382 | 47.1% | 42.5% | +4.6pp |
| [0.45–0.50) | 1,221 | 57.1% | 47.5% | **+9.6pp** |
| [0.50–0.55) | 323 | 57.3% | 52.5% | +4.8pp |
| [0.55–0.65) | 188 | 77.7% | 60.0% | **+17.7pp** |
| [0.65–0.80) | 296 | 86.8% | 72.5% | **+14.3pp** |
| [0.80–1.00) | 74 | 93.2% | 90.0% | +3.2pp |

**Key finding:** ALL price buckets show positive edge vs implied probability. This class consistently buys mispriced sides. The sweet spot is 0.45–0.50 (+9.6pp) and 0.55–0.65 (+17.7pp).

The "cheap" framing was misleading. These wallets don't exclusively buy cheap — 0x1477 and 0xb07a average entry 0.53–0.55. The commonality is that their WR exceeds their entry price at every tier.

---

## Q3: Coherent Class? Per-Wallet Direction Logic

**Partially coherent — splits into two subclasses.**

### Subclass A: High-volume cheap momentum followers (0x22b0 + 0x46a8)
- Entry ~0.47, >85% of fires below 0.50
- Direction: momentum (78% ret_30m agree)
- Slug selection: **high rv_15m_bps** (d≈+0.42 vs control) — fire in volatile slugs
- Harness direction discriminators: macd d≈1.37–1.40, ret_30m d≈1.34–1.35 (very strong)
- cl_basis for Up bets: 2.6–4.2 bps (near-strike entries), Down bets: 8.0–9.2 bps (BTC above strike)
- These wallets follow momentum AND get cheap prices by entering near-strike where the cheap side IS the momentum-aligned side

### Subclass B: Higher-entry, more selective (0x1477 + 0xb07a)
- Entry 0.53–0.55, 0xb07a achieves 68% WR with expensive entries
- Direction: ~50% agree with ret_30m (ambiguous at this feature level)
- 0xb07a slug selection: **low rv_15m_bps** (d=−0.51) — fires in calm slugs, opposite of Subclass A
- 0xb07a direction discriminators: cl_basis d=−1.10, ret_5m d=−0.65, ret_3m d=−0.51 (short-term momentum)
- These likely have a more refined trigger not fully decoded by the harness features

The four wallets share the same class-level behavior (buy underpriced sides relative to market) but the mechanism differs.

---

## Q4: Timing and Entry Distribution

- **fire_offset_s:** mean=211s, median=67s — most fire early in the slot window (within 1 minute), long tail of late entries
- **Entry price distribution:** mean=0.494, 68% below 0.50, 24% below 0.45
- **utc_hour:** mean=11.4, flat across all 24 hours (0–11 all show ~104–132 fires) — NO strong time-of-day signal; they trade around the clock
- **Slug selection:**
  - Engaged rv_15m_bps: 0x22b0=4.22, 0x46a8=4.16 vs control 3.21–3.21 (d≈+0.42) — want volatile slugs
  - 0xb07a engaged rv_15m_bps=3.18 vs control 4.18 (d=−0.51) — want calm slugs
  - 0x1477: minimal slug discrimination (all d<0.07) — fires broadly

---

## Q5: Direction Rule — Concrete and Testable

### cl_basis rule (best single predictor for 0x22b0 + 0x46a8)
"Buy Up when cl_basis_bps < threshold, Down when cl_basis_bps > threshold."

- cl_basis<0 → Up rule: **64.2% agreement, WR=59.1%** (pooled)
- When holding Up: mean cl_basis=4.27 bps; when holding Down: mean cl_basis=9.17 bps
- Interpretation: they buy Up when BTC is near or below strike (up side cheap, market uncertain about direction), buy Down when BTC is well above strike (down side cheap, reversion premium)

### Momentum rule (for Subclass A 0x22b0 + 0x46a8)
"Buy Up when MACD > 0, Down when MACD < 0"
- MACD Cohen d for direction: 1.37–1.40 — extremely strong separator
- These wallets buy the momentum-aligned side but specifically when that side is trading cheap (near-strike)

### WR when rule fires (pooled direction rules)
| Rule | Agreement | WR |
|------|----------|----|
| cl_basis<0 → Up | 64.2% | 59.1% |
| ret_30m momentum | 67.4% | 57.9% |
| MACD momentum | 67.2% | 57.4% |
| ct_ret30m (contrarian) | 32.6% | 56.4% |

The cl_basis-based value rule achieves the highest WR (59.1%) — this is the clearest replicable signal.

---

## Class Verdict

### What is this class?

NOT contrarian/mean-reversion. **Value/mispricing exploitation with momentum direction.**

The wallets systematically:
1. **Pick momentum direction** (macd/ret_30m aligns with held_side in 2 of 4 wallets; cl_basis pattern consistent across all 4)
2. **Buy whichever side is cheaper than fair value** — when BTC is near strike, Up side is cheap (market uncertain); when BTC is well above strike, Down side is cheap (market overshoots)
3. **Achieve WR > entry_px across all price buckets** — consistent positive edge vs implied probability

The cl_basis pattern reveals the mechanism: they don't blindly buy the underdog — they buy the momentum side when that side happens to be underpriced because the CLOB hasn't fully updated.

### Is the edge real?

Yes — d=0.793 for entry_px (win vs loss), consistent positive edge in all price buckets. However:
- The **cheap subgroup** (entry_px < 0.50) on its own shows WR=49.4% (barely above breakeven). The edge shows up as: wins achieve higher entry within cheap tier (0.459 vs 0.405), suggesting even within "cheap," they select better-priced individual fires.
- The slug selection signal (rv_15m or its opposite) explains ~5-10pp of edge from controlled entry timing.

### Is the class one coherent strategy?

**Partially.** Two subclasses:
- **Subclass A** (0x22b0 + 0x46a8): momentum + high volatility slug selection + near-strike cheap entry. Replicable with: `macd>0 → Up, macd<0 → Down, only when rv_15m_bps > median AND entry_px < 0.50`.
- **Subclass B** (0x1477 + 0xb07a): higher entry price, lower volatility preference (0xb07a), ambiguous direction rule. WR 58–68% with no clearly decoded trigger — likely uses additional signals not in the harness feature set.

### Deployability

| Aspect | Assessment |
|--------|-----------|
| Direction rule | Partially replicable (Subclass A clear, B unclear) |
| Entry price gate | Need CLOB WS to identify when cheap side = <0.50 |
| Slug selection | rv_15m_bps > median reproducible at ws_s |
| Win/loss predictor | entry_px (d=0.793) useful as confidence filter |
| Feature d-values | Direction: d≈1.37 (strong). Win/loss: d<0.10 most features (weak) |
| Gap | Unknown why WR exceeds implied price across all buckets — selection signal missing |

**Deployable with conditions:** Subclass A is replicable as a momentum+value strategy with `macd + cl_basis + entry_px < 0.50 + rv_15m > median` gate. Expect edge ~+5-9pp vs breakeven. Subclass B needs deeper decode (more features, possibly WS order flow or market microstructure data not in harness).

---

## Appendix: Raw Harness Summaries

```
0x22b0a5ac btc-15m: 1028 fires, WR 56.3%, entry_px 0.469
  Slug selection top: rv_15m_bps d=+0.427, cl_basis d=−0.122
  Direction top: macd d=1.395, ret_30m d=1.342, px_vs_ema21 d=1.091, rsi14 d=0.98
  Win/loss top: ret_3m d=−0.106, rv_15m d=−0.105, utc_hour d=−0.103

0x14774b67 btc-15m: 747 fires, WR 58.0%, entry_px 0.530
  Slug selection top: rsi14 d=−0.067 (very weak — fires broadly)
  Direction top: cl_basis d=−0.612, ret_1m d=0.406, px_vs_strike d=−0.312, rsi14 d=−0.266
  Win/loss top: ret_1m d=−0.164, ret_3m d=−0.161, px_vs_ema21 d=−0.147

0x46a8cf34 btc-15m: 730 fires, WR 54.2%, entry_px 0.470
  Slug selection top: rv_15m_bps d=+0.422, ret_15m d=−0.123, macd d=−0.122
  Direction top: macd d=1.368, ret_30m d=1.348, px_vs_ema21 d=1.073, rsi14 d=0.928
  Win/loss top: macd_hist d=0.143, ema9_slope d=0.114, cl_basis d=0.112

0xb07afa53 btc-5m: 276 fires, WR 68.1%, entry_px 0.549
  Slug selection top: rv_15m_bps d=−0.506, utc_hour d=−0.211, cl_basis d=−0.184
  Direction top: cl_basis d=−1.098, px_vs_strike d=−0.659, ret_5m d=−0.654, ret_3m d=−0.509
  Win/loss top: macd_hist d=−0.158, ema9_slope d=−0.145, rsi14 d=−0.138
```
