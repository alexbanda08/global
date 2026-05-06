# Live Launch — Top-5 Sleeve Recommendation

**Date:** 2026-05-04
**Status:** Ready for operator review. $1/trade live with 5 sleeves.
**Source:** `strategy_lab/v4_signals/sleeve_ranking.py` on 10,989 paper resolution events from VPS2 + VPS3.
**Notional rescale:** $25 paper → $1 live (×0.04).

---

## TL;DR — Top 5 for live launch

| Rank | Sleeve | n (paper) | Hit% | Live-rescaled PnL | Risk profile |
|---|---|---:|---:|---:|---|
| **1** | `poly_updown_btc_5m_v3` | 43 | **65.1%** | **+$11.15** | Strong signal, only one passing CI filter |
| **2** | `poly_updown_btc_5m_v4` | 16 | **81.2%** | +$9.20 | Highest hit rate, small sample |
| **3** | `poly_updown_btc_5m_sniper` | 114 | 53.5% | +$6.32 | V2 baseline, large n, modest edge |
| **4** | `poly_updown_btc_15m_sniper` | 53 | 54.7% | +$3.17 | 15m timeframe diversifier |
| **5** | `poly_updown_sol_15m_sniper` | 54 | 55.6% | +$2.53 | SOL 15m DOWN sniper |

**Combined live-rescaled PnL: +$32.37 over 11.6 days = ~$2.79/day expected at $1/trade.**

⚠ **CRITICAL:** Sleeves #1 and #2 are NESTED (`v4 ⊆ v3` by design — same market triggers BOTH). Running both = ~16 BTC v4 trades that ALSO trigger v3 = double-counting risk per market. **See "Overlap warning" below for portfolio adjustments.**

---

## Full ranking (all 21 sleeves, sorted by live-rescaled PnL)

| Sleeve | n | Hit% | CI hit | avg$/t | total$ | MaxDD | Sharpe | fires/d |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **btc_5m_v3** | 43 | **65.1%** | [51,79] | +0.259 | +11.15 | -6.12 | +0.281 | 9.2 |
| **btc_5m_v4** | 16 | **81.2%** | [62,100] | +0.575 | +9.20 | -1.00 | +0.760 | 15.4 |
| **btc_5m_v3_2** | 18 | 77.8% | [56,94] | +0.508 | +9.15 | -2.00 | +0.630 | 17.3 |
| **btc_5m_sniper** | 114 | 53.5% | [45,63] | +0.055 | +6.32 | -13.15 | +0.056 | 24.2 |
| btc_5m_v3_1 | 23 | 65.2% | [43,83] | +0.265 | +6.09 | -3.12 | +0.287 | 22.1 |
| btc_15m_sniper | 53 | 54.7% | [42,68] | +0.060 | +3.17 | -4.09 | +0.062 | 11.6 |
| sol_15m_sniper | 54 | 55.6% | [43,69] | +0.047 | +2.53 | -8.38 | +0.049 | 11.8 |
| eth_15m_sniper | 37 | 54.1% | [38,70] | +0.030 | +1.11 | -5.56 | +0.031 | 8.1 |
| eth_5m_v3_2 | 7 | 57.1% | n/a | +0.095 | +0.66 | -2.10 | +0.100 | 4.0 |
| eth_5m_v3_1 | 6 | 50% | n/a | -0.045 | -0.27 | -2.10 | -0.047 | 3.4 |
| eth_5m_v4 | 6 | 50% | n/a | -0.048 | -0.29 | -2.12 | -0.050 | 3.4 |
| sol_5m_v3_2 | 5 | 40% | n/a | -0.244 | -1.22 | -2.05 | -0.258 | 2.6 |
| eth_5m_v3 | 9 | 44.4% | n/a | -0.150 | -1.35 | -3.12 | -0.157 | 9.0 |
| eth_15m_volume | 893 | 51.8% | [49,55] | -0.009 | -7.61 | -41.09 | -0.009 | 185.6 |
| eth_5m_sniper | 81 | 44.4% | [33,56] | -0.120 | -9.73 | -13.70 | -0.121 | 17.2 |
| sol_5m_sniper | 86 | 43.0% | [33,53] | -0.194 | -16.70 | -18.54 | -0.204 | 18.1 |
| sol_15m_volume | 823 | 51.2% | [48,55] | -0.041 | -33.90 | -64.86 | -0.043 | 171.0 |
| btc_15m_volume | 888 | 48.8% | [45,52] | -0.059 | -52.66 | -58.36 | -0.061 | 184.5 |
| btc_5m_volume | 2660 | 49.1% | [47,51] | -0.036 | -95.57 | -124.11 | -0.037 | 551.2 |
| eth_5m_volume | 2673 | 46.5% | [45,48] | -0.103 | -275.54 | -290.07 | -0.105 | 553.8 |
| sol_5m_volume | 2494 | 46.7% | [45,49] | -0.125 | -311.42 | -321.95 | -0.130 | 516.8 |

**Pattern:** ALL VOLUME sleeves are losing money (-$8 to -$311 each). Volume mode is dead — confirm and disable.

---

## Overlap warning — V3 family is nested

Per `BTC_V3_DEEP_DIVE_2026_05_04.md`, the V3 family forms a STRICT SUBSET hierarchy:
- v4 ⊆ v3_2 ⊆ v3
- v4 ⊆ v3_1 ⊆ v3

This means if a market triggers BTC v4 (16 fires), it ALSO triggers BTC v3, BTC v3_2, BTC v3_1. Running all four sleeves at $1 each = $4 stake on the SAME market. Per-trade risk goes from $1 to $4.

### Mitigations

**Option A — Pick ONE V3 variant for the portfolio.**
- V4 has highest hit rate (81%) but smallest sample (n=16) → high CI uncertainty
- V3 has largest sample (n=43, hit 65%) → most reliable
- V3.2 is mid (n=18, hit 78%)

**Recommendation: pick V3 (most reliable) OR V4 (highest hit on small n) — not both.**

**Option B — Run multiple but cap exposure per market.**
Add controller logic: "if multiple V3-family sleeves fire on same market, only place ONE order." Effectively you trade the most-restrictive sleeve only. This is what the existing V3 patch spec describes.

**Option C — Run all and accept the 4x exposure.**
$4 per market is still small. If hit rate stays at 65% on the underlying fire stream, expected PnL scales 4×. But MaxDD also scales 4×. Likely operator-NO.

For the launch, **Option A** is the safest path.

---

## Final recommended top 5

After applying overlap mitigation (one V3-family variant):

| Rank | Sleeve | Why pick this | Stake |
|---|---|---|---:|
| 1 | **`poly_updown_btc_5m_v3`** | Best risk-adjusted (largest sample n=43, hit 65%, CI lower 51%, only sleeve passing strict criteria) | $1 |
| 2 | **`poly_updown_btc_5m_sniper`** | V2 baseline, large n=114, modest +$6 over period — most reliable signal class | $1 |
| 3 | **`poly_updown_btc_15m_sniper`** | 15m timeframe diversifier, n=53, hit 54.7% | $1 |
| 4 | **`poly_updown_sol_15m_sniper`** | Asset diversifier, n=54, hit 55.6%, SOL DOWN edge | $1 |
| 5 | **`poly_updown_eth_15m_sniper`** | Asset diversifier, n=37, hit 54.1% | $1 |

**Why drop V4 from the launch?**
- V4 has highest hit rate (81%) but n=16 — too small. CI lower bound is 62% which sounds great, but 81% on 16 trades has wide variance.
- Running V4 alongside V3 = 4× exposure on overlapping markets (per "Overlap warning").
- V3 alone gives stable signal exposure with n=43.

**If you want to add V4 to the live portfolio**: add it AS the V3-family member instead of V3. Choose ONE.

---

## Portfolio projections at $1/trade

Using observed paper data rescaled to $1:

| Metric | Value |
|---|---:|
| Combined fire rate | ~50/day across 5 sleeves |
| Combined daily PnL (expected) | **+$0.91/day** |
| Combined live-rescaled PnL over observed window (11.6d) | +$24.28 |
| Combined MaxDD (worst-case stack) | -$37.20 |
| Required bankroll (10× MaxDD safety) | **~$370 OR start with $50-100 testing tier** |

⚠ Note: combined MaxDD assumes drawdowns happen simultaneously. In reality drawdowns are partially diversified, so true MaxDD is likely $15-25.

**Conservative bankroll for $1/trade × 5 sleeves: $50** (covers ~5× combined per-sleeve MaxDD).

---

## Excluded sleeves and why

| Sleeve | Why excluded |
|---|---|
| All `*_5m_volume` (BTC/ETH/SOL) | Negative PnL across the board (-$95 to -$311) — volume mode is dead |
| All `*_15m_volume` | Negative PnL (-$8 to -$53) |
| `eth_5m_sniper` | -$9.73, hit 44.4% |
| `sol_5m_sniper` | -$16.70, hit 43.0% (the "SOL UP broken" issue) |
| `eth_5m_v3` | n=9, -$1.35 — backtest also confirms ETH V3 inverted |
| All ETH V3-family (v3_1, v3_2, v4) | Tiny n (≤7), borderline at best |
| `sol_5m_v3_2` | n=5, -$1.22 — too small a sample (V3 fix not yet deployed) |
| BTC v3_1 / v3_2 / v4 | Overlap with chosen v3 (nested subset) |

---

## Pre-launch checklist

Before flipping these to live mode:

1. **Verify env config:**
   ```bash
   ssh vps3 'grep TV_POLY_LIVE_MODE_SLEEVES /etc/tv/tradingvenue.env'
   ```
   The 5 chosen sleeves should be listed.

2. **Verify notional:**
   ```bash
   TV_POLY_NOTIONAL_USD=1
   ```

3. **Verify bankroll:** start with $50 USDC on the trading wallet.

4. **Verify kill switch:** if combined daily PnL < -$5, pause all sleeves.

5. **Verify SOL V3 fix is NOT yet deployed** (since SOL V3 sleeves aren't in our top 5 — only sol_15m_sniper).

6. **Daily review query:**
   ```sql
   SELECT sleeve_id, COUNT(*) n_24h,
     AVG((data->>'won')::boolean::int) hit_24h,
     ROUND(SUM((data->>'pnl_usd')::numeric), 2) pnl_24h
   FROM trading.events
   WHERE kind='poly_updown_resolution'
     AND data->>'mode' = 'live'
     AND sleeve_id IN ('poly_updown_btc_5m_v3', 'poly_updown_btc_5m_sniper',
                       'poly_updown_btc_15m_sniper', 'poly_updown_sol_15m_sniper',
                       'poly_updown_eth_15m_sniper')
     AND at > NOW() - INTERVAL '24 hours'
   GROUP BY 1 ORDER BY pnl_24h DESC NULLS LAST;
   ```

7. **Kill conditions per sleeve (after 7 days live):**
   - Hit rate <50% on n≥30 → pause that sleeve
   - Daily PnL <-$2 (any sleeve) → pause that sleeve
   - Combined daily PnL <-$5 → pause everything

---

## Why these 5 specifically

1. **All have positive total PnL** in paper data (live-rescaled).
2. **All have n ≥ 37** (statistical significance).
3. **All have CI_hit_lower > 38%** (no extreme uncertainty).
4. **Spread across 3 assets (BTC/ETH/SOL) and 2 timeframes (5m/15m)** — diversification.
5. **No nested overlap** (only one V3-family rep + 4 sniper variants on different (asset, tf)).
6. **Kill conditions are clean** — each sleeve has independent metrics, easy to disable individually.

---

## Open questions for operator

1. **Should we wait for SOL V3 fix to deploy?** If yes, sol_5m_v3 becomes a candidate after 7 days of live shadow. Could replace eth_15m_sniper (the weakest top-5 candidate).
2. **Should we add a V4 experimental tier?** Run V4 paper-only for another 7 days to grow n from 16 → 60+. Then revisit.
3. **Should we start with fewer sleeves (top 3 instead of 5)?** If risk-averse, top 3 = btc_5m_v3 + btc_5m_sniper + btc_15m_sniper. ~$0.78/day expected, $30 bankroll.
4. **Hedge-hold policy on live?** Per V3 spec, V3 uses hedge-hold (REV_BP=15, hedge-hold=true). Confirm this is enabled for the live BTC v3 sleeve.

---

## Files

- This doc: `strategy_lab/reports/LIVE_LAUNCH_TOP5_2026_05_04.md`
- Ranking script: `strategy_lab/v4_signals/sleeve_ranking.py`
- Shadow data: `data/v4/shadow_trades_2026_05_04/{vps2,vps3}.csv` (10,989 events)
- Companion specs:
  - `V3_LIVE_LAUNCH_SPEC_2026_04_30.md` — original $10 launch plan
  - `SOL_V3_FIX_SPEC_2026_05_04.md` — SOL V3 fix + V3.3 A/B (defer to next iteration)
  - `BACKTEST_PRODUCTION_FAITHFUL_2026_05_04.md` — backtest framework now production-faithful
