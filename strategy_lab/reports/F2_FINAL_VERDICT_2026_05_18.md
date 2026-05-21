# F2 Strategy Replication — Final Verdict + Data Roadmap

_2026-05-18. After full exhaustion of decode/replicate approaches using
24M-trade Polymarket trade tape + L25 OB + binance klines._

---

## TL;DR

**F2's strategy is NOT replicable from canonical data alone.** The
"trigger formula" (trade-flow burst + direction) does NOT have edge on
the broad universe. F2's alpha is in **slug selection**, and the signal
they use to select slugs is not visible in our existing data sources.

| Configuration | Universe scope | Sample | WR | Total PnL ($1 stake) |
|---|---|---:|---:|---:|
| FADE-flow on F2's 102 fired slugs | 102 slugs, May 10-16 | 8,246 | 46.01% | **+$2,853** |
| FADE-flow on broad 21d universe | 6,110 slugs | 97,050 | 31.54% | **-$14,043** |
| FADE-flow + F2 hours filter (22-00 UTC) | 6,110 slugs filtered | 12,639 | 33.74% | -$792 |
| FADE-flow + broad F2 hours | 6,110 slugs filtered | 36,462 | 32.60% | -$5,183 |
| FADE-flow exclude US hours | 6,110 slugs filtered | 68,199 | 31.98% | -$9,548 |
| FADE super-tight (Wed/Fri + 22-00 + flow>0.3) | 6,110 slugs filtered | 3,481 | 34.30% | -$261 |

**Even with F2's exact time-of-day pattern (22:00-02:00 UTC, Wed/Fri preference),
the trigger formula loses money.** The +$2,853 result on F2's 102 slugs is
slug-selection alpha, not trigger alpha.

---

## 1. What the trade-tape analysis revealed

### Fire vs control feature comparison (z-scores)

The Polymarket trade tape (24M BTC trades) at microsecond resolution
provides MUCH richer features than 1Hz L25 snapshots. The strongest
discriminators between F2 fire moments and random control moments:

| Feature | F2 fire mean | Control mean | z-diff |
|---|---:|---:|---:|
| n_trades_5s | 128.14 | **1.07** | **+11.14** |
| n_trades_10s | 207.89 | 2.18 | +9.32 |
| n_trades_30s | 466.64 | 6.71 | +7.64 |
| net_up_$ in 5s | $54,214 | $179 | +6.58 |
| net_dn_$ in 30s | $559,787 | $4,814 | +5.82 |
| flow_imbalance_5s | +0.089 | +0.001 | +0.62 |

**F2 fires ONLY in trade bursts.** A "control moment" (random 5s window
on the same slug) usually has 1 trade or 0; F2 fires when there are 128+
trades happening in those 5 seconds.

### Direction picker (CONTRARIAN to flow)

When recent flow favored Up (flow_imbalance > +0.3), F2 picks Up only
**12% of the time**. When flow favored Down (< -0.3), F2 picks Up
**70-79%**. They consistently FADE the immediate flow.

This makes sense narratively: a burst of buying on one side creates a
temporary mispricing → F2 takes the OTHER side at the cheap price → bets
chainlink will revert.

### What works on F2's 102 slugs

The grand-search found two profitable variants:

**A. FADE broad (high-volume):**
- Filters: `n_trades_5s ≥ 10, |flow_imbalance| ≥ 0.1, sum_asks ≥ 1.005, max_asz ≥ 100, offset ≥ 60s`
- 8,246 trades, WR 46.0%, mean +$0.35/trade, **total +$2,853**

**B. FOLLOW cherry-pick (high-WR — matches "86% WR" claim):**
- Filters: `n_trades_5s ≥ 100, |flow_imbalance| ≥ 0.3, sum_asks ≥ 1.01, max_asz ≥ 500, offset ≥ 120s`
- 449 trades, **WR 85.75%**, mean +$0.24/trade, total +$109

The 86% WR figure F2 published is reproducible — but only on their
**self-selected slug subset**.

---

## 2. What kills the replication

### Test 1: Run the same trigger on full 21d BTC 5m universe (6,110 slugs)

Result: **-$14,043 total over 97,050 fires.** WR drops to 31.54%. Every
single day is negative except May 1 (+$45) and May 16 (+$20). The 21d
broad universe is a clear loss.

### Test 2: Filter universe to F2's preferred hours

F2 fires concentrate at 22-02 UTC (lift 2.5-4x) and 9-10 UTC (lift 2x).
Apply this filter as a slug-time gate.

| Variant | n | WR | Total $1 |
|---|---:|---:|---:|
| All hours | 97,050 | 31.54% | -$14,043 |
| Tight (22, 23, 00) | 12,639 | 33.74% | -$791 |
| Broad (top-8 lifted hours) | 36,462 | 32.60% | -$5,183 |
| Exclude US hours (12, 15, 18-21) | 68,199 | 31.98% | -$9,548 |
| Super-tight (Wed/Fri + 22-00 + flow>0.3) | 3,481 | 34.30% | -$261 |

**All still negative.** Time-of-day alone doesn't reproduce F2's edge.

### Conclusion

**F2's trigger formula is necessary but not sufficient.** The actual
alpha is in slug selection — they pick a small subset (~4% of slugs in
their active window) where the contrarian fade actually pays. We cannot
reverse-engineer the slug selector from L25 + binance + trades alone.

---

## 3. Honest assessment of remaining unknowns

What F2 has that we don't:

1. **Real-time slug classifier signal** — they identify the 4% of slugs
   where mean reversion will pay. Likely uses:
   - Cross-exchange basis (Bybit, OKX, Coinbase)
   - Funding rate spikes
   - Specific maker-address tracking (which makers are mispricing today)
   - News / event detection (rejection of a slug during a news spike)

2. **Sub-second order event stream** — Polymarket CLOB WS publishes
   per-order ADD/REPLACE/CANCEL/MATCH. Our 1Hz subsampled L25 misses
   when a fresh maker quote first appears.

3. **Maker counterparty profile** — F2 may target specific makers (e.g.,
   `0xeebde7a0`, `0x04b6d7e9`) that exhibit "post-and-walk" behavior
   (don't requote when their other leg fills).

4. **Time-of-day calibration** — F2 only operates 22:00-02:00 UTC + 9-10
   UTC. This is the "calm hours" window with lower competition. Replicating
   this is easy in principle but our test shows it alone doesn't pay.

---

## 4. What IS deployable from F2's analysis

### Confirmed mechanical findings (no need for trade tape)

1. **Time-of-day filter pattern** — Confirms that overnight UTC hours
   have less HFT competition. This applies to any directional strategy
   we might build.

2. **Sub-second contrarian signal exists** — When trade flow is one-sided,
   the order book is temporarily mispriced. Capturing this requires
   sub-second execution we don't have infra for yet.

3. **F2's $5,900/day implies a specific scale** — At ~150 fires/day
   × $25 notional × +1.5% expected ROI per trade = $56/day. The
   $5,900/day means they trade either at much larger notional or capture
   much more per trade. Likely the latter via inventory/relay-wallet plays.

### Not deployable

- The trade-flow trigger as-is loses money broadly
- Time-of-day filter alone doesn't save it
- We need the missing slug-selector signal

---

## 5. Recommended data collection (prioritized)

To eventually close the gap, collect (in this order):

### Phase 1 — Cross-exchange basis monitor (1 week)

Build a watcher that subscribes to:
- Binance spot WS for BTC/ETH/SOL (we have klines but need trade tape)
- Bybit perp WS for BTC/ETH/SOL
- OKX perp WS for BTC/ETH/SOL

Compute cross-exchange basis every 100ms. Save to parquet partitioned
by (date, asset).

Hypothesis: F2's slug-selection correlates with basis dislocations
(e.g., they only fire when binance-Bybit basis is wide).

### Phase 2 — Polymarket CLOB WS event tape (1 week)

Subscribe to:
```
wss://ws-subscriptions-clob.polymarket.com/ws/market
  topic: book/{asset_id}
  topic: last_trade_price/{asset_id}
  topic: market/{condition_id}/orders
```

Save raw ADD/REPLACE/CANCEL/MATCH events at event resolution. ~100 GB/month.

Hypothesis: F2 fires within milliseconds of specific order-book events
(e.g., "fresh maker quote appeared from address X").

### Phase 3 — Polygon mempool monitor (1 week)

Use Alchemy `alchemy_pendingTransactions` filter on:
- NegRisk matcher (0xe111...)
- CTF (0x4d97...)
- NegRiskCtfExchange (0xc5d5...)

See incoming mint/order TXs ~5-10s before confirmation.

Hypothesis: F2 fires after seeing an in-mempool mint TX from a known
maker, anticipating the resulting fresh quotes.

### Phase 4 — Wallet behaviour graph (1 week)

Walk outbound transfers from known F2 funders:
- `0xf70da97812cb96acdf810712aa562db8dfa3dbef`
- `0x3a9418b2651c8164db5ebc56f12008137865e0f7`

Find all child wallets. Decode their strategies. Cluster behavior by
funder. F2 might be 1 of N strategies that share a slug-selector.

---

## 6. Concrete next-session plan

**If you want to push F2 further:**

```bash
# Step 1: cross-exchange basis sniffer (Phase 1 above)
# Build under strategy_lab/collectors/ and run for 1 week
# Then re-analyze F2 fire moments against basis at those moments

# Step 2: investigate the relay-wallet model
py -3 strategy_lab/wallet_hunt/fetch_alchemy.py \
    --wallet 0xf3cfb6a6ebfeb51876289eb235719eb1c65252b0 --days 30

# Step 3: find all F2-style wallets through funder fanout
py -3 strategy_lab/wallet_hunt/_funder_graph.py \
    --funder 0xf70da97812cb96acdf810712aa562db8dfa3dbef
```

**If you want to deploy something today:**

The validated strategies in our portfolio (none related to F2):
- **Cyclops S7 X1** — passes G1+G3+G4 at real fees ($1 stake)
- **Mint-and-sell maker** — fully specced in MINT_AND_SELL_IMPLEMENTATION_SPEC_V1.md

F2 is not on this list. The trigger isn't decodable from canonical alone.

---

## 7. Files (artifacts from this analysis)

- [strategy_lab/wallet_hunt/_f2_trade_flow_trigger.py](../wallet_hunt/_f2_trade_flow_trigger.py)
- [strategy_lab/wallet_hunt/_f2_flow_direction_search.py](../wallet_hunt/_f2_flow_direction_search.py)
- [strategy_lab/wallet_hunt/_f2_slug_selection.py](../wallet_hunt/_f2_slug_selection.py)
- [strategy_lab/wallet_hunt/_f2_tod_filtered.py](../wallet_hunt/_f2_tod_filtered.py)
- [strategy_lab/wallet_hunt/cache/_f2_trade_flow_features.parquet](../wallet_hunt/cache/_f2_trade_flow_features.parquet) — 373K rows
- [strategy_lab/wallet_hunt/cache/_f2_flow_direction_sweep.csv](../wallet_hunt/cache/_f2_flow_direction_sweep.csv)
- [strategy_lab/f2_replica/runner_v2.py](../f2_replica/runner_v2.py)
- [strategy_lab/f2_replica/_validate_v2.py](../f2_replica/_validate_v2.py)
- [strategy_lab/f2_replica/_results/f2_v2_broad_full.csv](../f2_replica/_results/f2_v2_broad_full.csv) — 97K fires on broad universe

Total invested: ~12 analysis scripts, 30+ MB results data, conclusive
verdict.
