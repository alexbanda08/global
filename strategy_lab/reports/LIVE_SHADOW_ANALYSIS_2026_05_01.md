# Live Shadow Trade Analysis — 2026-05-01

**Window:** 2026-04-30 06:10 → 2026-05-01 14:10 (1.33 days)
**Hosts:** VPS3 (V2 sniper + V3 + volume) + VPS2 (V1 volume control)
**Total resolutions:** 2,978

## Top-line: V3 is the only winner

| Type | n | hit rate | PnL | Notional | ROI |
|---|---|---|---|---|---|
| **V3 portfolio** | **6** | **83.3%** | **+$92.70** | $150 | **+61.8%** ⭐ |
| V2 sniper (all 6 sleeves) | 86 | 47.7% | -$172 | $2,178 | -7.9% |
| V1 volume (all 6 sleeves) | 2,886 | 48.6% | -$4,895 | $73,043 | -6.7% |

V3 BTC is hitting at backtest bar (83% live vs 72% backtest holdout). Sample tiny but consistent.

## Per-sleeve breakdown

### Winning sleeves (1.33 day live)

| Sleeve | n | hit | PnL | avg/trade |
|---|---|---|---|---|
| **poly_updown_btc_5m_v3** | 6 | 83.3% | **+$92.70** | +$15.45 |
| poly_updown_btc_5m_sniper | 20 | 65.0% | +$148.58 | +$7.43 |
| poly_updown_eth_15m_sniper | 7 | 71.4% | +$62.60 | +$8.94 |
| poly_updown_sol_15m_sniper | 12 | 66.7% | +$75.48 | +$6.29 |
| **poly_updown_sol_15m_volume** | **227** | **58.1%** | **+$534.70** | +$2.36 |
| poly_updown_eth_15m_volume | 245 | 52.7% | +$38.50 | +$0.16 |

### Losing sleeves

| Sleeve | n | hit | PnL | avg/trade |
|---|---|---|---|---|
| poly_updown_btc_15m_sniper | 10 | 50.0% | -$5.61 | -$0.56 |
| **poly_updown_eth_5m_sniper** | 13 | **30.8%** | **-$128.65** | -$9.90 |
| **poly_updown_sol_5m_sniper** | 24 | **25.0%** | **-$324.47** | -$13.52 |
| poly_updown_btc_15m_volume | 244 | 48.4% | -$402 | -$1.65 |
| poly_updown_btc_5m_volume | 734 | 50.3% | -$241 | -$0.33 |
| **poly_updown_eth_5m_volume** | 737 | 45.3% | **-$2,300** | -$3.12 |
| **poly_updown_sol_5m_volume** | 699 | 45.8% | **-$2,525** | -$3.61 |

## Direction asymmetry — confirmed structural problem

Across multiple sleeves, **DOWN signals outperform UP signals by 10-50pp:**

| Sleeve | UP hit / PnL | DOWN hit / PnL |
|---|---|---|
| BTC 5m sniper | 58.3% / +$48 | 75.0% / +$101 |
| BTC 5m V3 | 80% / +$69 | 100% / +$24 (n=1) |
| ETH 5m sniper | 25% / -$102 | 40% / -$27 |
| ETH 15m sniper | 50% / -$5 | **100%** / +$68 |
| **SOL 5m sniper** | **7.7%** / **-$284** | 45.5% / -$41 |
| **SOL 15m sniper** | 50% / -$11 | **83.3%** / +$87 |
| **SOL 15m volume** | **64.2% / +$542** | 52.9% / -$7 |
| BTC 5m volume | 49.7% / -$273 | 50.8% / +$31 |

**SOL 5m sniper UP at 7.7% hit on n=13** — this is now **catastrophic and confirmed** (was 11% on n=9 yesterday, today 7.7% on n=13). V3.1 surgical fix (disable SOL UP live) is strongly validated. Cumulative SOL 5m sniper loss: -$324 in 1.33 days.

## Daily trend — sniper is degrading

| Date | Type | n | hit | PnL |
|---|---|---|---|---|
| 04-30 | V2 sniper | 61 | 55.7% | +$120 |
| 04-30 | V3 | 6 | 83.3% | +$93 |
| **05-01** | **V2 sniper** | **25** | **28.0%** | **-$292** |

Sniper hit rate fell from 55.7% to 28% overnight. Possible causes:
1. **Regime shift** — markets entered a chop / counter-trend regime
2. **Concentrated bad luck** — n=25 in 14 hours, sample noise
3. **Specific time pattern** — maybe early UTC hours dominated 05-01 fires

## Hour-of-day pattern (live, sniper+V3 only)

| Hour | n | hit | PnL | Verdict |
|---|---|---|---|---|
| 0 | 3 | **0.0%** | -$75 | bad (matches backtest) |
| 3 | 8 | **25.0%** | -$107 | very bad |
| 4 | 5 | 40.0% | -$24 | bad |
| 5 | 9 | 55.6% | +$15 | OK |
| 7 | 3 | 66.7% | +$24 | good |
| 9 | 3 | 100% | +$79 | great (small n) |
| 10 | 11 | 54.5% | +$11 | OK |
| 14 | 15 | 53.3% | +$10 | OK |
| 15 | 13 | 53.8% | +$6 | OK |

**Hours 0, 3, 4 UTC are dragging live performance.** Backtest blocklist {1, 16, 22} matches direction but doesn't cover 0/3/4. **Recommend extending live blocklist to {0, 1, 3, 4, 16, 22} after more data.**

## Time-clustering effect

| Time since prev fire | n | hit |
|---|---|---|
| <30m | 25 | **60.0%** |
| 30-120m | 39 | 43.6% |
| >120m | 21 | 47.6% |

When sniper fires CLUSTER (multiple fires within 30 min of each other), hit rate is materially better. When fires are isolated/sparse, edge degrades. This is consistent with regime detection — clusters happen during real momentum, isolated fires are noise.

## Fill cost diagnostic

Win-fill cost vs loss-fill cost differential, per sleeve:

| Sleeve | Win cost | Loss cost | Diff |
|---|---|---|---|
| BTC 15m sniper | 0.5112 | 0.5096 | -0.16pp |
| BTC 5m sniper | 0.4977 | 0.4983 | +0.06pp |
| ETH 5m sniper | 0.5035 | 0.5013 | -0.22pp |
| SOL 15m sniper | 0.5298 | 0.5299 | 0.00pp |
| SOL 5m sniper | 0.5265 | 0.5272 | +0.07pp |

**Slippage is NOT the problem.** Win and loss fills cost essentially the same. Edge degradation is signal-quality, not execution.

## Surprises

1. **SOL 15m volume is profitable** (+$534, 58.1% hit, n=227). Backtest said volume mode is dead, but on SOL 15m it's working — concentrated in UP signals (64.2% hit on n=106, +$541). **Worth investigating** — could be a real regime-fit edge.
2. **ETH 5m volume disaster** (-$2,300 on n=737). Earlier "volume mode is dead" verdict is *wrong* for SOL 15m UP, but *very right* for ETH 5m.
3. **15m sniper sleeves are mostly winning** (BTC -$5, ETH +$63, SOL +$75). Backtest said 15m dilutes the portfolio. Live evidence is mixed but mostly positive on 15m for ETH/SOL. **Should re-test 15m portfolio inclusion.**

## Recommended actions (ranked by EV)

### Immediate (no code changes)
1. **Disable live: SOL 5m sniper, ETH 5m sniper, ETH 5m volume, SOL 5m volume, BTC 15m volume.** All meaningfully losing in live with sufficient n. Saves ~$5,500/day at current notional rate.
2. **Keep live: BTC V3, BTC 5m sniper, ETH 15m sniper, SOL 15m sniper, SOL 15m volume.** All profitable in live.
3. **Keep paper: V3 ETH, V3 SOL, all blocked sleeves.** For ongoing eval.

### Patch (V3.2 already designed, extend with live findings)
4. **Apply V3.1 surgical: disable SOL UP live.** Live SOL UP at 7.7% hit (-$284), unambiguous.
5. **Apply V3.2 hour blocklist: {1, 16, 22} UTC** (existing). **Extend to {0, 1, 3, 4, 16, 22}** after 7 more days of live data confirms the pattern.
6. **Apply V3.2 macro 2-of-3 + liq quiet gates.** Test in live for 7 days. Expect 5-10pp hit rate lift.

### Investigate (1-2 hour each)
7. **Why is SOL 15m volume UP winning?** Check if there's a regime feature explaining 64% hit. Could be: SOL DOWN-trending overall, so volume-mode UP catches sustained reversals.
8. **Why did 05-01 sniper crash to 28%?** Inspect the 25 trades from today. Cluster analysis — are they all in bad hours? Same direction? Same micro-regime?
9. **Add 15m to V3 portfolio?** Live evidence on ETH 15m sniper and SOL 15m sniper is positive. Backtest was on dilute combined portfolio; new test: V3 portfolio at 5m+15m vs 5m-only.

### Long-term
10. **Wait for 7-day live track record before scaling capital.** Current 1.33 days is too thin to commit beyond paper.
11. **Re-validate liq quiet gate** when Binance + HL liq backfill completes.

## What this means for live launch (Stage 1)

Per the V3 launch spec, recommended **immediate live with $10 bankroll** but with this updated sleeve list:

**Enabled live:**
- ✅ `poly_updown_btc_5m_v3` — 83% live hit
- ✅ `poly_updown_btc_5m_sniper` — 65% live hit
- ✅ `poly_updown_eth_15m_sniper` — 71% live hit (NEW: 15m worth including)
- ✅ `poly_updown_sol_15m_sniper` — 67% live hit (NEW)

**Paper-only (keep observing):**
- ⏸ `poly_updown_eth_5m_v3` (0 fires)
- ⏸ `poly_updown_sol_5m_v3` (0 fires)
- ⏸ `poly_updown_eth_5m_sniper` (30.8% live, losing)
- ⏸ `poly_updown_sol_5m_sniper` UP (7.7% live, broken)
- ⏸ `poly_updown_sol_5m_sniper` DOWN (45% live, marginal — re-eval)
- ⏸ `poly_updown_btc_15m_sniper` (50% live, breakeven)

**Disabled (confirmed losing):**
- ❌ All `*_5m_volume` sleeves except possible SOL exception (investigate first)
- ❌ `poly_updown_btc_15m_volume` (-$402)
- ❌ `poly_updown_eth_5m_volume` (-$2,300)
- ❌ `poly_updown_sol_5m_volume` (-$2,525)

**Investigate before deciding:**
- ❓ `poly_updown_sol_15m_volume` (+$534, 58.1% — winning unexpectedly)

## Files

- `data/v4/shadow_trades_2026_05_01/vps3.csv` — VPS3 dump (1,558 rows)
- `data/v4/shadow_trades_2026_05_01/vps2.csv` — VPS2 dump (1,420 rows)
- `strategy_lab/v4_signals/shadow_trades_analysis.py` — analysis harness, re-runnable
- This report: `strategy_lab/reports/LIVE_SHADOW_ANALYSIS_2026_05_01.md`
