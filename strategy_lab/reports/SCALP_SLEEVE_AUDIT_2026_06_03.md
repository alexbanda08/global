# Scalp shadow-sleeve audit (16 sleeves) + per-cell exit timing — 2026-06-03

## Q1: Are the 5 silent sleeves misimplemented? → NO. The gate works correctly.

5 `_v1` sleeves fired 0× in 14h: `btc_15m_v1, eth_5m_v1, eth_15m_v1, btc_15m_d3_v1, eth_15m_d3_v1`.
Proof: the `_control_v1` twins (identical except NO vwap gate) fired, and the count of control fires with
`fill_vwap<0.55` EXACTLY equals each `_v1`'s fire count:

| cell | control fires | min fill_vwap | control <0.55 | `_v1` fired | match |
|---|--:|--:|--:|--:|:--:|
| btc_5m | 30 | 0.48 | 8 | 8 | ✓ |
| btc_5m_d3 | 42 | 0.51 | 6 | 6 | ✓ |
| eth_5m_d3 | 22 | 0.48 | 6 | 6 | ✓ |
| **btc_15m** | 10 | **0.56** | 0 | 0 | ✓ |
| **btc_15m_d3** | 11 | 0.56 | 0 | 0 | ✓ |
| **eth_5m** | 10 | **0.59** | 0 | 0 | ✓ |
| **eth_15m** | 2 | 0.65 | 0 | 0 | ✓ |
| **eth_15m_d3** | 2 | 0.61 | 0 | 0 | ✓ |

**Conclusion: the `entry_vwap<0.55` gate is implemented correctly.** The 5 sleeves are silent because NO fire
in those cells had `fill_vwap<0.55` in 14h. They are NOT broken — do not "fix" them.

### The real issue this surfaces (deployment, not a bug)
- **15m windows + eth_5m fill the lagging token at vwap ≥ 0.55 live** (15m min 0.56–0.65; eth_5m min 0.59).
  15m markets price the lagging side higher (more time → less mispriced); and live books carry a large
  cross-token spread (sample fire: up_vwap 0.498 + dn_vwap 0.843 = 1.34, cross-spread 0.34) so the side you
  buy tends to sit ≥0.55 more often than the backtest implied.
- **Workhorses = `btc_5m` + the d3/$5 variants.** Those generate ~all the real `_v1` fires. The 15m and eth_5m
  `_v1` cells will accrue the ≥200-forward-fire graduation gate VERY slowly — manage expectations / consider
  the d3 ($5, δ≥3) variant as the primary data generator.

## Q2: Which sleeves need +45 vs +60? → Mostly KEEP +60. Do NOT blanket-change to +45.

Per-cell exit sweep (cache, entry_vwap<0.55, fee=0.015, $/tr by exit time):

| cell | n | +30s | +45s | +60s | +75s | +90s | best |
|---|--:|--:|--:|--:|--:|--:|---|
| BTC_15m δ5 | 24 | +4.46 | +4.78 | **+4.85** | +4.74 | +3.58 | +60 |
| BTC_15m δ3 | 97 | +2.67 | +3.04 | **+3.13** | +2.92 | +2.07 | +60 |
| BTC_5m δ5 | 37 | +7.02 | +8.39 | +8.31 | +8.22 | **+8.66** | +60–90 (flat) |
| BTC_5m δ3 | 141 | +4.55 | +5.35 | **+5.81** | +5.26 | +5.11 | +60 |
| ETH_5m δ5 | 36 | +2.96 | +3.65 | **+3.82** | +3.44 | +2.83 | +60 |
| ETH_5m δ3 | 119 | +1.82 | +2.32 | **+2.63** | +2.42 | +1.87 | +60 |
| **ETH_15m δ5** | 21 | **+5.28** | +4.76 | +4.51 | +4.15 | +2.27 | **+30** |
| **ETH_15m δ3** | 41 | **+2.93** | +2.78 | +2.40 | +1.89 | +0.47 | **+30** |

**Correction to my earlier "+45 universal" call:** that was a pooled artifact. Per-cell, **+60s is actually
optimal or tied-best for BTC (5m+15m) and ETH_5m.** The +45-vs-+60 gap elsewhere is within noise (<$0.3/tr).
**The one real exception is ETH_15m, which wants an EARLY exit (+30s)** — its reprice decays fastest and by +60
it has lost ~$0.7/tr. But ETH_15m barely fires live (0 in 14h), so it's low-priority.

### Recommendation
1. **KEEP the deployed exit at +60s** for btc_5m, btc_15m, eth_5m (all v1 + d3). The +45 change is not worth it.
2. **ETH_15m → +30s** (optional, low priority — it rarely fires). 
3. Do NOT touch the gate or the silent sleeves — they are correct.
4. The meaningful exit upgrade is NOT a fixed-time tweak — it's the **ML dynamic-exit policy** (+$0.90/tr on the
   broad lockbox, CI excludes 0 — `EXIT_TIMING_MODEL_2026_06_03.md`). Deploy that as a shadow arm instead.

Data: live `trading.events` (VPS3, 14h), cache `scalp_hedge_physics_cache_2026_06_03.parquet`.
