# Physics Signal — ETH Generalization Test (2026-06-01)

**Question:** Does the BTC physics-continuation edge generalize to ETH 5m/15m markets?

**Method:** Mirrored `build_enriched_physics.py` for ETH, restricted to last 14 days
(2026-05-19 to 2026-06-01). Same bet definition: continuation (side ETH is on vs chainlink
strike at fire_us = slot_end − 60s). Outcome = chainlink resolution. L25 entry via
`fill_at_book(notional=$25, LiveMimicConfig)`. Fees: `pnl_curve` = 0.07·p·(1−p)
winner-only; `pnl_legacy` = 2%-on-profit winner-only.

**Data:** `strategy_lab/physics/_results/physics_fires_eth_14d.parquet`
(4,864 total fires, 3,369 valid L25 fills, 69% fill rate).

---

## Overall (all valid fills)

| | ETH 14d | BTC 38d |
|---|---|---|
| n | 3,369 | 11,210 |
| Window | May 19 – Jun 1 | Apr 24 – Jun 1 |
| WR | 85.4% | 81.6% |
| Implied (entry_vwap) | 0.842 | 0.815 |
| GAP (WR − implied) | +1.2 pp | +0.1 pp |
| net PnL/fire (curve) | +$0.499 | −$0.257 |
| net PnL/fire (legacy) | +$0.687 | −$0.027 |

By timeframe:
- ETH 5m: n=2,900, WR=84.9%, implied=0.841, gap=+0.8pp, curve=+$0.345/fire
- ETH 15m: n=469, WR=88.7%, implied=0.850, gap=+3.6pp, curve=+$1.452/fire

---

## BTC-analog filter segments (thresholds scaled by ETH/BTC price ratio ~1/45)

BTC uses dollar thresholds ($40 dist, $30/$10 WEAK_COMBO). ETH price is ~$2,050–2,150
during this window, so BTC thresholds are rescaled proportionally.

| Segment | ETH WR | ETH impl | ETH gap | ETH curve/fire | ETH n | BTC curve/fire | BTC n |
|---|---|---|---|---|---|---|---|
| All valid | 85.4% | 0.842 | +1.2 pp | +$0.499 | 3,369 | −$0.257 | 11,210 |
| dist_abs >= 1.0 (BTC-equiv $40) | 96.0% | 0.949 | +1.1 pp | +$0.407 | 1,531 | +$0.161 | 3,661 |
| WEAK_COMBO scaled kept | 89.6% | 0.886 | +1.0 pp | +$0.518 | 2,538 | −$0.026 | 6,794 |
| + d_speed >= 0 | 89.4% | 0.885 | +0.9 pp | +$0.425 | 1,296 | +$0.118 | 3,343 |
| + entry_vwap <= 0.85 | 71.5% | 0.686 | +3.0 pp | +$1.817 | 316 | +$0.535 | 890 |

WEAK_COMBO scaled: skip if dist_abs < 0.66 AND speed_away < 0.22 (BTC: dist<30, speed_away<10,
scaled by 2100/95000 ≈ 0.022).

95% CIs on curve PnL/fire (ETH):
- All valid: [+$0.029, +$0.969]
- dist >= 1.0: [+$0.051, +$0.762]
- WEAK_COMBO kept: [+$0.022, +$1.015]
- WC + d_speed >= 0: [−$0.239, +$1.089]
- WC + d_speed + vwap <= 0.85: [−$0.666, +$4.299]

---

## Key finding: the dist-filter pattern DOES appear in ETH

The scaled dist_abs >= 1.0 filter (BTC-equivalent of >= $40) produces WR=96% vs implied=94.9%
(+1.1 pp gap) in ETH, compared to WR=96.1% vs implied=95.3% (+0.8 pp gap) in BTC.
The direction and magnitude of the gap are consistent. The curve PnL/fire is higher in ETH
(+$0.407) than BTC (+$0.161) in this window.

The WEAK_COMBO + d_speed >= 0 combination also shows similar gap sizes:
ETH = +0.9 pp (curve +$0.425), BTC = +1.0 pp (curve +$0.118). The gap sizes match but
ETH curve PnL is higher, driven by different entry_vwap distribution.

---

## Critical caveat: ETH all-baseline is already +EV (+1.2 pp gap)

Unlike BTC where the unfiltered baseline has ~0 gap (market is efficient on average),
ETH shows a systematic +1.2 pp gap across ALL fires in the 14-day window. This makes
it impossible to isolate whether the dist-filter adds incremental alpha on ETH, or
whether ALL ETH continuation bets were outperforming in this specific period.

Weekly breakdown:
- Week 21 (May 19-25): n=1,561, WR=85.7%, gap=+1.4pp, curve=+$0.593/fire
- Week 22 (May 26-Jun 1): n=1,722, WR=85.5%, gap=+1.4pp, curve=+$0.560/fire
- Week 23 (Jun 1, partial): n=86, WR=77.9%, gap=−6.4pp, curve=−$2.43/fire

The positive gap in weeks 21-22 is consistent across both weeks. The Jun-1 partial
day shows a reversal (−6.4pp gap). This could reflect: (a) mean reversion, (b) a
volatility-regime change, or (c) sampling noise from only 86 fires.

---

## Structural note: dist_abs scale matters

BTC dist_abs values range from $0 to $385 (median $27, p75=$47). ETH dist_abs values
range from $0 to $11 (median $0.89, p75=$1.51). Applying the BTC threshold of $40
literally to ETH yields zero rows. The correct comparison requires proportional scaling.

At the scaled threshold:
- BTC: 32.7% of fires have dist_abs >= $40 (above median)
- ETH: 45.5% of fires have dist_abs >= $1.0 (captures similar "far from strike" set)

The per-percentage-of-price breakdown confirms the same qualitative pattern:
higher dist_pct = higher WR = higher implied = lower or similar gap. This is consistent
with the "favorite-longshot law": deep favorites are accurately priced, near-strike
is where mispricing can appear.

---

## Low-implied anomaly (ETH-specific)

ETH has 77 fires where entry_vwap <= 0.50 (market implies only 39% continuation probability).
These show WR=66.2% vs implied=39.2% (+27 pp gap), with massive curve PnL (+$22.85/fire).
The z-score is 5.02 (p < 0.0001 vs implied). However n=77 over 14 days is too small
for deployment conclusions — this bucket needs more data. On BTC, this bucket is rare
(deep-against-grain ETH is near-strike where market prices near 50/50, but ETH actually
continues 66% — could be a structural ETH market-making artifact or luck over 14d).

---

## Conclusions

1. **The dist-filter edge DOES generalize directionally to ETH.** The scaled dist_abs >= 1.0
   (BTC-equivalent) shows the same pattern: WR matches implied at high confidence (~96%/94.9%),
   gap = +1.1 pp, curve PnL = +$0.41/fire. This is consistent with BTC's +0.16/fire at $40.

2. **The WEAK_COMBO + d_speed pattern also generalizes directionally** with similar gap size
   (+0.9 vs +1.0 pp). ETH curve PnL is higher (+$0.42 vs +$0.12) possibly reflecting
   a favorable period rather than a structural difference.

3. **The 14-day ETH window is insufficiently long** for a clean test. The unfiltered
   baseline gap (+1.2 pp) inflates all ETH numbers vs BTC's ~0 pp baseline. A proper test
   needs 30+ days of ETH data to match the BTC window.

4. **Under legacy 2%-on-profit fee (production), ALL ETH segments are positive**, including
   the unfiltered baseline (+$0.69/fire). Under the 0.07-curve fee, the unfiltered baseline
   is also positive (+$0.50/fire). This is atypical vs BTC.

5. **Deployment assessment:** ETH physics fires are currently +EV under both fee models in this
   window, but the short lookback and positive baseline shift make it unclear whether the
   dist-filter specifically adds alpha vs riding a broader ETH continuation regime. Do NOT
   deploy ETH physics until a 30+ day enrichment confirms the signal holds out-of-sample.

---

## Files

- ETH enriched parquet: `strategy_lab/physics/_results/physics_fires_eth_14d.parquet`
- Build script: `strategy_lab/physics/build_eth_physics_14d.py`
- BTC reference: `strategy_lab/physics/_results/physics_fires_enriched.parquet`
