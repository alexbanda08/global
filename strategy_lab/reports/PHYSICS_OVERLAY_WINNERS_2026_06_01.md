# Physics Overlay on Winning Sleeves — 2026-06-01

**Question:** Does adding a physics gate (dist_abs>=40, d_speed>=0, WEAK_COMBO veto) as a filter improve our already-profitable live sleeves?

**Target sleeves tested:**
- `poly_sniper_v5_eth_5m_l_ema50_hurst_grandparent_v8` (78 fires, 73.1% WR, +$71.93)
- `poly_sniper_v5_eth_5m_bb_mp_hurst_band_v6` (107 fires, 72.9% WR, +$50.31)
- `poly_sniper_v5_eth_5m_cloud_ribbon_mp_hurst_v6` (84 fires, 72.6% WR, +$13.82)
- `poly_sniper_v5_btc_15m_ema50_ema800_off600_down` (58 fires, 79.3% WR, +$35.56)

**Data source:** `fires_resolved_all.parquet` with correct fire offsets (ETH 5m = 60s after slot_start, BTC 15m = 600s after slot_start). Total: 327 fires after slug/chainlink lookup (3 skipped).

**Fee model:** legacy 2%-on-profit-only (LegacyConfig), consistent with production.

---

## Critical Data Issue Discovered

`all_sleeve_fires.parquet` stores `fire_us = slot_end_us` (the resolution timestamp, not the actual fire time). Physics features computed from this file read the **settlement price**, which trivially predicts the outcome — an oracle, not a gate. All subsequent analysis uses `fires_resolved_all.parquet` with the correct `fire_offset_s` field, giving time-to-end of 240s for ETH 5m and 300s for BTC 15m.

---

## Gate Results

### ETH 5m — dist_abs range: $0.00–$5.28, median $0.5 (ETH ~$2000 => max 0.26% from strike)

| Gate | Kept | WR (base) | WR (kept) | delta_WR | Net PnL (base) | Net PnL (kept) | delta_PnL |
|------|------|-----------|-----------|----------|----------------|----------------|-----------|
| **grandparent_v8** (base: 78 fires, 73.1% WR, $71.93) |
| dist_abs>=40 | 0/78 | — | — | — | — | — | — |
| dist_pct>=0.05% ($1+) | 16/78 (21%) | 73.1% | **93.8%** | +20.7% | $71.93 | $17.03 | -$54.90 |
| d_speed>=0 | 47/78 (60%) | 73.1% | 74.5% | +1.4% | $71.93 | $40.20 | -$31.73 |
| physics_aligned | 60/78 (77%) | 73.1% | 75.0% | +1.9% | $71.93 | $29.64 | -$42.29 |
| **bb_mp_hurst_band_v6** (base: 107 fires, 72.9% WR, $50.31) |
| dist_abs>=40 | 0/107 | — | — | — | — | — | — |
| dist_pct>=0.05% ($1+) | 21/107 (20%) | 72.9% | 66.7% | -6.2% | $50.31 | -$9.72 | -$60.03 |
| d_speed>=0 | 54/107 (50%) | 72.9% | 70.4% | -2.5% | $50.31 | $18.63 | -$31.68 |
| physics_aligned | 103/107 (96%) | 72.9% | 72.8% | -0.1% | $50.31 | $43.28 | -$7.04 |
| **cloud_ribbon_mp_hurst_v6** (base: 84 fires, 72.6% WR, $13.82) |
| dist_abs>=40 | 0/84 | — | — | — | — | — | — |
| dist_pct>=0.05% ($1+) | 27/84 (32%) | 72.6% | 66.7% | -6.0% | $13.82 | -$21.54 | -$35.36 |
| d_speed>=0 | 37/84 (44%) | 72.6% | 70.3% | -2.3% | $13.82 | -$1.39 | -$15.21 |
| physics_aligned | 82/84 (98%) | 72.6% | 73.2% | +0.6% | $13.82 | $15.35 | +$1.53 |

### BTC 15m — dist_abs range: $2–$334, median $54 (BTC ~$75k => median 0.07%)

| Gate | Kept | WR (base) | WR (kept) | delta_WR | Net PnL (base) | Net PnL (kept) | delta_PnL |
|------|------|-----------|-----------|----------|----------------|----------------|-----------|
| **btc_15m_ema50_ema800_off600_down** (base: 58 fires, 79.3% WR, $35.56) |
| dist_abs>=40 | 34/58 (59%) | 79.3% | **94.1%** | +14.8% | $35.56 | $21.65 | -$13.91 |
| dist_pct>=0.05% ($38+) | 36/58 (62%) | 79.3% | **91.7%** | +12.4% | $35.56 | $16.90 | -$18.66 |
| d_speed>=0 | 20/58 (34%) | 79.3% | 80.0% | +0.7% | $35.56 | $14.04 | -$21.52 |
| speed_away<0 (toward) | 16/58 (28%) | 79.3% | 56.2% | **-23.1%** | $35.56 | $16.91 | -$18.65 |
| physics_aligned | 48/58 (83%) | 79.3% | 85.4% | +6.1% | $35.56 | $3.72 | -$31.84 |

---

## Findings

### 1. Physics gates do NOT improve net PnL on any sleeve

Every gate that raises WR for the kept subset cuts too many profitable fires. The net PnL (dollars returned) falls for every gate on every sleeve. The one partial exception is `eth_5m_cloud_ribbon_mp_hurst_v6 + physics_aligned` which adds +$1.53 on n=82 (from n=84), but the 2 extra vetoed fires were losers by coincidence — not a signal.

### 2. dist_abs>=40 is completely wrong for ETH

ETH was trading $2000-2050 during the test window. At 60 seconds into a 5-minute slot, `dist_abs` is in the range $0.00–$5.28 (median $0.49). The BTC-tuned threshold of $40 blocks 100% of ETH fires. The correct ETH analogue would be dist_abs >= $1 (= 0.05%), which keeps 16–27% of fires. Even that normalized gate is inconsistent: it helps `grandparent_v8` (+20.7% WR) but hurts `bb_mp_hurst` (-6.2% WR).

### 3. WEAK_COMBO also inapplicable to ETH

The WEAK_COMBO veto (`dist<30 AND speed_away<10`) blocks all ETH fires because dist is always under $6 and speed_away is always positive at the 60s fire point (price has been moving away from strike for 60 seconds, so speed_away > 0 always). At the 60s mark, essentially all ETH fires have speed_away > 0 — the "toward strike" subset (speed_away < 0) is completely empty. The gate is structurally inapplicable.

### 4. BTC 15m dist_abs>=40 looks promising but destroys dollar PnL

For `btc_15m_ema50_ema800_off600_down`, `dist_abs>=40` lifts WR from 79.3% to 94.1% (n=34, +14.8pp). However:
- Net PnL falls from $35.56 to $21.65 (losing $13.91)
- The vetoed 24 fires had 58.3% WR but contributed $13.91 — they are not bad trades at 58.3%
- At legacy 2%-fee, 58.3% WR on $25-notional bets is near-breakeven but slightly positive
- **Verdict:** Raising selectivity at the cost of net dollars collected is only useful if fire rate is not the constraint (i.e., there are too many fires to fill all). For 58 fires over ~5 days, that is not the current problem.

### 5. `d_speed>=0` (momentum acceleration) has no consistent benefit

At the 60s fire point (240s before slot end), d_speed varies but shows no consistent directional relationship with outcome for these sleeves. On ETH it's slightly negative (-1% to -2.5% WR on kept subset for two of three ETH sleeves). On BTC 15m (fire at 600s, 300s to go) it's neutral (+0.7% WR on kept subset but cuts 66% of fires). Not useful.

### 6. Direction alignment (physics continuation bet vs sleeve direction)

These sleeves are **continuation-aligned** at fire time (price above strike and sleeve bets Up, or price below strike and sleeve bets Down) in 74–98% of fires. This is structural: the hurst family fires early in the window when continuation is still dominant at the price level. The misaligned fires (18–24% for ETH, 17% for BTC 15m) have *better* PnL per fire in some cases (e.g., btc_15m misaligned: $3.18/fire vs $0.08/fire aligned), likely because misaligned fires are contrarian bets at higher prices where the market hasn't yet priced the reversal. This is not actionable as a filter — too few misaligned fires to draw conclusions.

---

## Verdict

**Physics is NOT a useful overlay on these sleeves.**

Three structural reasons:

1. **ETH scale mismatch:** All BTC-tuned physics thresholds (dist_abs>=40, NOT_WEAK_COMBO) are completely inapplicable to ETH. Normalized versions (dist_pct) are inconsistent across the three ETH sleeves.

2. **Fire timing mismatch:** These sleeves fire early in the window (60s into 5min = 80% remaining, 600s into 15min = 33% remaining). At those points, the physics features carry structural biases: speed_away > 0 for nearly all fires (price still trending from slot open), dist_abs small (market is tight). The original physics enriched parquet fires at 60s-before-slot-end with very different market conditions.

3. **Net PnL tradeoff unfavorable:** Every gate that improves WR does so by cutting profitable fires (the vetoed fires have positive expected PnL at the base 72–79% WR). At $25 notional with legacy fees, WR >= 57% is profitable. Cutting fires with WR 58–72% is counterproductive.

**Actionable conclusion:** Do not add physics gates to these sleeves. If physics is useful at all for ETH, it would require re-tuning the thresholds on ETH-native price scale and testing on a larger sample. The 5-day window here (327 fires) is too small to tune reliable gates anyway.

---

## Methodology notes

- Physics features computed via `strategy_lab/physics/physics_signal.physics_at()` using chainlink RTDS stream for each asset
- `d_speed` = speed(fire_us) minus speed(fire_us - 30s), where speed = 60s change in $/min
- Correct fire_us = slot_start_us + fire_offset_s * 1e6 (from fires_resolved_all.parquet)
- `all_sleeve_fires.parquet` fire_us = slot_end_us — would give lookahead oracle; excluded
- Fee model: legacy 2%-on-profit-only (LegacyConfig), matching production behavior per 2026-05-22 verification
- Window: May 27 – June 1 (~5 days), 327 fires total; BTC 15m = 58 fires, ETH 5m = 269 fires
