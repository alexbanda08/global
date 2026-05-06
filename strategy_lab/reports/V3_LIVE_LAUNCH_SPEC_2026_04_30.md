# V3 Live Launch Spec — Real Money, Small

**Date:** 2026-04-30
**Status:** ready for TV agent to deploy live mode
**Mode:** small live with strict caps + kill switches

## Constraint discovered

**Polymarket CLOB minimum order = $1.00 (price × shares).** Your initial spec was $0.50-$0.80/trade — that's below the platform floor and won't fill. Adjusted plan uses $1.00 as the minimum tick, which forces:
- $5 bankroll → $1/trade is 20% per trade (full Kelly, can ruin in 5-trade losing streak)
- $10 bankroll → $1/trade is 10% per trade (half Kelly, ruin-safe in any reasonable streak)

**Going with $10 starting bankroll** as the safest first-real-money launch.

---

## Launch configuration

### Sleeves to enable LIVE (real money)

| Sleeve | Live mode? | Reason |
|---|---|---|
| `poly_updown_btc_5m_v3` | **YES** | 83% live hit (n=6), matches backtest, BTC liquidity is 17× SOL |
| `poly_updown_btc_5m_sniper` (V2) | YES | 79% live hit (n=14), running anyway, larger fire count helps build sample faster |
| `poly_updown_eth_5m_v3` | NO (paper) | 0 fires today, threshold needs relaxation. Paper-only until first 20 fires |
| `poly_updown_eth_5m_sniper` (V2) | **YES** | Backtest 65% holdout. Live n=7 too small to disprove. Modest size |
| `poly_updown_sol_5m_v3` | NO (paper) | 0 fires today |
| `poly_updown_sol_5m_sniper` (V2) | **NO — pause live** | Live 33% hit on n=15 — diverged from backtest. Paper-only until ≥55% on n≥30 |
| Any 15m sleeve | NO | Backtest said 15m dilutes; live is mixed |
| Any volume mode | NO | Confirmed dead, -$1,225 across 621 trades |

### Per-asset sizing

Bankroll-aware fractional sizing, capped:

| Asset | Per-trade rule | Live this stage |
|---|---|---|
| BTC | **min($1, 10% of bankroll, $5)** | $1 fixed |
| ETH | **min($1, 10% of bankroll, $5)** | $1 fixed |
| SOL | $0 (paper-only) | skip live |

At $10 starting bankroll: every trade is **$1 fixed** (the platform min). Fractional doesn't kick in until bankroll ≥$10/0.10 = $100. So this stage is effectively flat $1/trade.

### Daily fire-rate expectation

From live data today:
- BTC V3 fires ~6× / 12 hrs ≈ **12-15 fires/day**
- BTC V2 sniper fires ~14× / 12 hrs ≈ **28-30 fires/day**
- ETH V2 sniper fires ~7× / 12 hrs ≈ **14-15 fires/day**

**Total daily fires (BTC + ETH live): ~55 trades/day**

### Expected outcome (7 days, $10 bankroll)

Assuming live edge holds at ~70% hit rate (mix of V3 + V2 sniper):
- Daily fires: ~55
- Daily PnL @ $1/trade: ~+$15 / day (using realistic L10 fills, ~28% ROI per trade × 0.5 win-loss = ~+$0.27/trade × 55)
- **End-of-week bankroll projection: ~$110**

If edge halves (50% hit rate, signal degraded):
- Daily fires: ~55
- Daily PnL: -$2 to -$3 / day (close to breakeven minus fees)
- End-of-week: ~$0-5 (worst case touches ruin if streak is bad)

If edge fully fails (40% hit rate):
- Daily PnL: -$8 / day
- End-of-week bankroll: $0 (ruin)
- **Loss capped at $10** because we don't size up

---

## Kill switches (HARD STOP — TV agent must auto-pause)

The system must auto-pause live mode if ANY of these trip:

| Condition | Window | Action |
|---|---|---|
| Hit rate < 40% on n ≥ 30 | rolling 24h | PAUSE all sleeves, page operator |
| Daily PnL < -$3 | rolling 24h | PAUSE, manual review |
| Bankroll < $3 | any time | PAUSE, do not auto-resize |
| Any sleeve fires >100 trades/day | 24h | PAUSE, abnormal volume |
| Spread >5% on >30% of trades | rolling 1h | INVESTIGATE — book health degraded |

---

## Daily operator checklist (5 min/day)

```sql
-- run on VPS3 each morning
SELECT
  sleeve_id,
  COUNT(*) FILTER (WHERE at > NOW() - INTERVAL '24 hours') AS n_24h,
  AVG(CASE WHEN (data->>'won')::boolean THEN 1.0 ELSE 0.0 END)
    FILTER (WHERE at > NOW() - INTERVAL '24 hours') AS hit_24h,
  ROUND(SUM((data->>'pnl_usd')::numeric)
    FILTER (WHERE at > NOW() - INTERVAL '24 hours'), 2) AS pnl_24h
FROM trading.events
WHERE kind='poly_updown_resolution'
  AND data->>'mode' = 'live'
GROUP BY sleeve_id
ORDER BY pnl_24h DESC NULLS LAST;
```

Flag for review if any sleeve hit < 55% on n ≥ 20.

---

## Scale-up triggers

Move to next stage WHEN AND ONLY WHEN ALL conditions met:

### Stage 2: $50 bankroll → $5/trade
Triggers (must hold ALL):
- Bankroll reaches $50
- Live BTC hit rate ≥ 65% on n ≥ 50
- Live ETH hit rate ≥ 55% on n ≥ 30
- No kill switch tripped in last 7 days

### Stage 3: $200 bankroll → $20 BTC / $10 ETH / $5 SOL
Triggers:
- Bankroll reaches $200
- Stage 2 conditions still hold
- SOL paper hit rate ≥ 55% on n ≥ 30 (gate to enable SOL live)

### Stage 4: $1000 bankroll → $100 / $50 / $10
Triggers:
- Bankroll reaches $1000
- 30-day live track record with cumulative hit rate ≥ 60%
- 30-day Sharpe ≥ 1.5

### Stage 5: capacity ceiling at $5,000 bankroll
Beyond this, ETH/SOL liquidity becomes the binding constraint per fire. Don't size up further — diversify into a new sleeve class instead (V4-A multi-venue, V4-C LLM news, etc.).

---

## What the TV agent needs to do

1. **Switch mode flag on selected sleeves from `paper` → `live`** in engine config:
   - `poly_updown_btc_5m_v3` → live
   - `poly_updown_btc_5m_sniper` → live
   - `poly_updown_eth_5m_sniper` → live
   - All others stay paper
2. **Set per-trade notional to $1.00** for live sleeves (env var or config table)
3. **Wire wallet:** confirm Polymarket-funded USDC wallet has ≥$15 balance ($10 bankroll + $5 buffer for stuck orders)
4. **Wire kill switches** per the table above (auto-pause logic)
5. **Add monitoring query** to existing operator dashboard (or cron a daily summary email)

Estimated TV-agent effort: **2-3 hours** (single PR, env tweak, kill-switch wiring, smoke test).

---

## Honest expectations

This is real money. At $10 starting:

- **Best case:** $10 → $100-150 in 7 days, validating the edge in live with real fills, real fees, real slippage. Then proceed to Stage 2.
- **Median case:** $10 → $30-60 in 7 days. Live edge slightly worse than backtest (sim-vs-live gap), confirms strategy works at small scale.
- **Worst case:** $10 → $0-5 in 7 days. Edge has degraded since backtest sample. Pause, investigate, no further capital deployed.

You cannot lose more than $10. Stake is fixed, fractional rule kicks in if bankroll grows >$10. If bankroll falls below $3, kill switch pauses live trading.

The goal of stage 1 is **NOT to make money. It's to validate that backtest → sim → live transfer holds at the smallest possible real-money scale.** The data from 7 days of $1 trades is more valuable than the PnL.

---

## Source files

- Backtest evidence: `strategy_lab/reports/RESEARCH_DEEP_DIVE_2026_04_29.md`
- Live evidence (what I just pulled): VPS3 `trading.events` filtered to today
- Liquidity caps: `strategy_lab/reports/SIZING_RULE_2026_04_30.md`
- Sim-vs-live calibration: `strategy_lab/reports/SIM_VS_LIVE_RECONCILIATION.md` (V3 unchanged)
- TV deploy guide: `strategy_lab/reports/polymarket/01_deployable/TV_STRATEGY_V3_PORTFOLIO_DEPLOY_GUIDE.md` (V3 portfolio, paper version — needs the live-mode flip)
