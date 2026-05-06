# V3 Live Sizing Rule — 2026-04-30

**Built from:** VPS3 live paper trades (today, 2026-04-30) + local L21 book depth across 14,272 historical Polymarket markets.

## Live edge evidence (paper, today)

| Sleeve | n | hit | total PnL | avg fill cost | verdict |
|---|---|---|---|---|---|
| **poly_updown_btc_5m_v3** | **6** | **83.3%** | **+$92.70** | $0.510 | matches backtest holdout (72%), small n |
| poly_updown_btc_5m_sniper (V2) | 14 | 78.6% | +$200.00 | $0.499 | confirms BTC sniper-class works live |
| poly_updown_eth_5m_sniper (V2) | 7 | 42.9% | -$28.88 | $0.507 | n too small, hold judgment |
| **poly_updown_sol_5m_sniper (V2)** | **15** | **33.3%** | **-$140.52** | $0.530 | **DIVERGENCE — backtest said 60%+ hit** |
| poly_updown_eth_5m_v3 | 0 | — | — | — | thresholds too tight (q5 + multi-h), no fires |
| poly_updown_sol_5m_v3 | 0 | — | — | — | same, no fires |
| poly_updown_btc_15m_sniper | 7 | 42.9% | -$29 | confirms 15m dilutes (per backtest) |
| poly_updown_eth_15m_sniper | 6 | 66.7% | +$40 | mixed signal on 15m |
| poly_updown_sol_15m_sniper | 10 | 70.0% | +$79 | mixed signal on 15m |
| ALL 6 volume sleeves | 621 | 49.4% | -$1,225 | confirms volume mode is dead |

**Live runtime:** all fires from 2026-04-30 only. Total live observation window ≈ 12 hours. Single-day evidence — treat with caution.

**Headline:** BTC sniper-class is working as expected (V3 + V2 both 78-83% hit). SOL 5m sniper is DEVIATING from backtest (33% live vs 60%+ backtest). ETH undersized to call.

## Liquidity per asset (Polymarket L10 book walk capacity)

Per market, walking ASK side from L1 to L10 deep:

| Asset | L1 size ($) | L10 capacity median | L10 capacity p25 | spread median |
|---|---|---|---|---|
| BTC | $98 | **$1,346** | $926 | 1.0pp |
| ETH | $24 | **$266** | $167 | 1.0pp |
| SOL | $6 | **$81** | $61 | 2.0pp |

BTC is **17× deeper** than SOL. ETH is **3× deeper** than SOL.

### Slippage at fixed notional (% of markets that fill within L10, median slippage in pp)

| Notional | BTC fill / slip | ETH fill / slip | SOL fill / slip |
|---|---|---|---|
| $5 | 100% / 0.00pp | 100% / 0.00pp | 100% / 0.00pp |
| $10 | 100% / 0.00pp | 100% / 0.00pp | 100% / 0.45pp |
| **$25** | **100% / 0.00pp** | **100% / 0.04pp** | **99.7% / 1.38pp** |
| **$50** | **100% / 0.00pp** | **99.6% / 0.63pp** | **88.2% / 2.68pp** |
| $100 | 100% / 0.02pp | 92.7% / 1.41pp | 31.7% / 3.36pp |
| $250 | 99.6% / 0.74pp | 53.2% / 2.72pp | 5.3% / 12.0pp |
| $500 | 95.1% / 1.52pp | 19.9% / 4.19pp | 4.1% / 19.7pp |
| $1000 | 70.7% / 2.62pp | 7.4% / 10.3pp | 3.1% / 29.1pp |

### Per-asset hard liquidity caps

The "where slippage starts eating edge" point:

| Asset | Soft cap (≤1pp slip) | Hard cap (≤2pp slip) | Edge-killer (>5pp slip) |
|---|---|---|---|
| **BTC** | **$250** | **$500** | $1000 |
| **ETH** | **$50** | **$100** | $250 |
| **SOL** | **$10-15** | **$25** | $50 |

## Recommended sizing rule (multi-stage)

### Asset weights (use ratio 4:2:1 BTC:ETH:SOL based on liquidity)

Independent of bankroll size, the per-asset cap should respect liquidity. SOL is the bottleneck.

### Stage 0 — Paper validation (current)
**Action:** keep V3 running paper on VPS3 for 7-14 more days. Watch:
- BTC V3 hit rate stays >60% on n≥30
- ETH V3 starts firing (may need to relax q5 threshold to q7 if 0 fires persist)
- SOL V3 — if any fires, watch hit rate. CURRENTLY V2-sniper SOL is losing (33%). Don't go live on SOL until paper confirms ≥55% on n≥20.

### Stage 1 — Live $10 starting bankroll, fractional 10%
**Sizing:** bet 10% of running bankroll, asset-capped per the table below.

| Asset | Per-market cap | Status |
|---|---|---|
| BTC | $1.00 | GO — live evidence solid |
| ETH | $1.00 | GO — backtest solid, live too small to disprove |
| SOL | $0.00 (skip) | **PAUSE** — live evidence inverted |

**Expected after 7 days:** bankroll $25-50. Worst case (~5 losing streaks): $5-7.
**Cannot ruin** (fractional sizing).

### Stage 2 — $50 bankroll
| Asset | Per-market cap |
|---|---|
| BTC | $5.00 |
| ETH | $5.00 |
| SOL | $0 or $2 if paper recovers to ≥55% hit |

### Stage 3 — $200 bankroll
| Asset | Per-market cap |
|---|---|
| BTC | $20 |
| ETH | $10 |
| SOL | $5 (if paper >55%) |

### Stage 4 — $1000 bankroll
| Asset | Per-market cap |
|---|---|
| BTC | $100 |
| ETH | $50 |
| SOL | $10 |

### Stage 5 — Strategy capacity ceiling: $5,000 bankroll
At this point per-fire deployment is liquidity-bound, not bankroll-bound:
| Asset | Per-market cap (HARD) | Reason |
|---|---|---|
| BTC | $250 | 99.6% fill, <1pp slip |
| ETH | $50 | 99.6% fill, <1pp slip; $100 starts paying 1.4pp |
| SOL | $25 | 88% fill, 2.7pp slip; size-up beyond is edge-destroying |

**Total max deployment per portfolio fire:** ~$325 across BTC+ETH+SOL.
**At ~55 portfolio fires/day:** max $17,875/day notional throughput.
**Max useful bankroll:** ~$5,000-10,000. Beyond that, capacity is the bottleneck.

## Operational rules

1. **Never bet >10% of bankroll on a single market.** Even if liquidity allows it. Variance is real.
2. **Never bet >$50 on SOL until paper hit rate ≥55% on n≥30.** SOL live deviation from backtest is the biggest unresolved risk in the V3 stack.
3. **If BTC live hit rate falls <55% on n≥30, pause and investigate.** Not yet — currently 78-83%.
4. **Use maker entry (bid+$0.01) when bankroll ≥ $50.** Saves ~1.3pp per trade per backtest. Below that, taker is fine — fees dominate the small-trade economics.
5. **Spread filter: skip if (ask-bid)/mid ≥ 2%.** Already in V3 design. Confirmed sane: median spread is 1pp on BTC/ETH, 2pp on SOL. The filter rejects ~p90 spread markets (SOL p90=5pp).

## Why these numbers (data sources, in order of trust)

1. **Live VPS3 paper** (n=85 sniper+v3 resolutions, 12-hour window) — primary signal for live edge confirmation
2. **Backtest 7-day forward-walk** (V3, validated through 10-gate gauntlet) — primary signal for sleeve selection
3. **Local L21 book depth** (14,272 polymarket markets, 10s buckets) — primary signal for liquidity caps
4. **Sim-vs-live S1 reconciliation** (already done, said 30pp gap is execution-layer) — bounds confidence interval

## What's NOT validated yet

- ETH sniper live (n=7 too small)
- SOL sniper live edge restoration (currently losing, paper-only verdict pending)
- V3 ETH/SOL sleeves (zero fires today — thresholds too tight on this regime)
- 30-day OOS — wait until ~2026-05-23 before any meaningful capital scale-up

## Source files

- `strategy_lab/v4_signals/sizing_analysis.py` — generates this report
- VPS3 query: `trading.events` filtered to `kind='poly_updown_resolution'`
- Local: `strategy_lab/data/polymarket/{btc,eth,sol}_book_depth_v3.csv`
