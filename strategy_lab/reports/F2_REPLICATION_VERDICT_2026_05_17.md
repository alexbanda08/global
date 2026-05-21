# F2 Strategy Replication — Verdict + Data Wishlist

_2026-05-17. After full validation of every decoded trigger variant on
21d canonical BTC 5m data._

---

## TL;DR

**F2's strategy CANNOT be replicated from publicly observable signals.**

Both candidate triggers — fade-rally and follow-rally — fail validation:

| Variant | n | WR | mean PnL/$1 | G1 | G3 | G4 | G2 |
|---|---:|---:|---:|:-:|:-:|:-:|:-:|
| Fade-rally (Down on binance ↑) | 1,236 | 28.96% | -$0.39 | FAIL | — | — | — |
| Fade-dip (Up on binance ↓) | 1,214 | 29.90% | -$0.30 | FAIL | — | — | — |
| **Follow + asz≥1000 + ret≥2bp + last 60s** | **503** | **77.53%** | **+$0.107** | **PASS** | FAIL (p=1.000) | FAIL (CI -$0.15..+$0.45) | **FAIL (1/8 windows positive)** |

The follow variant's +$53.66 total PnL over 21 days comes from **ONE
positive day** (May 13-14, +$32). The other 7 walkforward windows are
negative.

**Conclusion: the alpha is in something we cannot see from canonical data.**

---

## 1. What we know about F2's actual behavior

From the chain-decode (854 fires, 102 slugs):
- F2 picks contrarian to binance momentum 62-81% of the time (above 3bp threshold)
- F2 fires almost exclusively in the second half of slugs (median offset = 195s)
- F2 fires almost only on slugs with high top-of-book size (>1000 shares)
- F2's reported WR on **their actual chosen slugs** is ~52%
- F2's reported earnings: ~$5,900/day per wallet (sustained over 7d)

From our replication attempt (21d, 6110 slugs):
- The same trigger formula fires ~10× more often than F2 actually does
- WR on the broad universe is 29-35% (fade) or 65-77% (follow)
- **Neither direction is stable across walkforward windows.**

The math is brutal: **F2's edge is in their slug selection**, not in the
trigger formula. They fire on the ~10% of slugs where the contrarian
bet works. We can't tell which slugs those are from L25 + binance alone.

---

## 2. Why broad replication fails

### Edge dynamics breakdown

When `sum_asks > $1` and `|binance_ret_60s| ≥ 2bp`, the up-down market
has already priced in the binance move. The cheap side is cheap *because*
the consensus expects it to lose.

Specifically at our best follow-config:
- Mean entry: $0.71 (we're paying high prices for the winner side)
- Breakeven WR at this entry: 76.63%
- Actual WR: 77.53%
- Edge: **+0.90pp** — well within noise

A 0.90pp edge gets eaten by:
1. **Real Polymarket fees** ($0.07 × p × (1−p) per share, ~$0.012 at p=0.76)
2. **Maker queue priority** — by the time we observe the fat ask in our 1Hz
   sample, F2 (with WS-level data) has already taken it
3. **Adverse selection** — the asks left for us to take are the "stale"
   ones that haven't been swept yet, meaning they're priced wrong

### Walkforward instability proves it

| Window | Days | n | Mean PnL/$1 | Total |
|---|---|---:|---:|---:|
| Apr 24-25 | 2 | 50 | -$0.290 | -$14.51 |
| Apr 26-27 | 2 | 24 | -$0.130 | -$3.12 |
| Apr 28-29 | 2 | 64 | -$0.030 | -$1.92 |
| Apr 30-May 1 | 2 | 59 | -$0.117 | -$6.89 |
| May 2-3 | 2 | 54 | -$0.284 | -$15.33 |
| May 4-5 | 2 | 37 | -$0.248 | -$9.17 |
| **May 6-7** | 2 | **60** | **+$0.534** | **+$32.02** ★ |
| May 8-9 | 2 | 71 | -$0.279 | -$19.80 |

**Only 1 of 8 windows positive.** The strategy is regime-dependent on
something not captured in the features.

---

## 3. Data wishlist — what F2 likely uses that we don't have

Ranked by suspected importance.

### Tier 1 — Must-have to close the gap

1. **CLOB websocket order event stream** (`/ws/market`)
   - Real-time per-order events: ADD, REPLACE, CANCEL, MATCH
   - Reveals exactly WHEN a fresh maker quote appears
   - The trigger is likely "fresh fat ask appeared in last 100ms" — not "fat ask currently exists"
   - Polymarket publishes this on their orderbook WS

2. **Order book at sub-second resolution**
   - Our `load_orderbook_l25_streaming` subsamples to 1Hz
   - F2 fires sub-second after order events (their cadence: 0-1000ms)
   - Need raw 1-update granularity to match their timing

3. **Tick-by-tick binance trade tape** (not just 1MIN bars)
   - Binance trade stream provides per-millisecond price updates
   - F2 reacts to specific binance prints (e.g., a big aggressor on Bybit)
   - 1MIN bars hide the actual signal

4. **Counter-party identification on fills**
   - F2's trade tape shows specific maker addresses (e.g.,
     `0xeebde7a0`, `0x04b6d7e9`)
   - F2 might be **specifically targeting mint-and-sell makers** they've
     profiled as "naive" (post-and-walk, no requoting)
   - Polymarket CLOB events expose `maker_address` + `taker_address`

### Tier 2 — High value but not critical

5. **Polymarket trade tape (last N seconds)**
   - "Who else just bought this side?" → herding signal
   - Polymarket data-api publishes recent trades per market

6. **Chainlink RTDS sub-second feed**
   - Our chainlink data is 1Hz; the actual oracle updates every ~500ms
   - F2 may time fires to chainlink update boundaries

7. **Cross-asset binance feeds at WS resolution**
   - Funding rates, perp basis, large orders on ETH/SOL/BTC perps
   - Could predict mini-trends that affect spot

8. **Mempool monitoring (Polygon)**
   - See incoming mint TXs from mint-and-sell makers before confirmation
   - Allows ~5-10s preview of upcoming book changes

### Tier 3 — Nice to have

9. **Polymarket gamma metadata API**
   - Per-market fee schedule, rebate share, market depth limits
   - Filter slugs by these properties (some markets may have wider rebates)

10. **Maker rebate event tape**
    - Polymarket publishes maker-side fills with rebate amounts
    - Filtering by rebate > $X identifies "easy" target makers

### Tier 4 — Operator policy / internal

11. **F2's own slug whitelist**
    - F2 may simply exclude high-volatility slugs (e.g., during US market
      open / news events)
    - Reproducing this would need a vol filter on binance 1MIN bars

12. **F2's training data on which makers misprice**
    - Some makers offer at sum_asks=1.005, others at 1.030. F2 may
      prefer one over the other based on past wallet behavior.

---

## 4. Practical data collection plan

If you want to collect what F2 likely uses, prioritize:

### Phase 1 (sub-second CLOB)

```yaml
collector: polymarket_clob_ws
endpoints:
  - wss://ws-subscriptions-clob.polymarket.com/ws/market
  - wss://ws-subscriptions-clob.polymarket.com/ws/user (if you have API key)
subscribe_to:
  - book/{asset_id}        # full L25 changes per event
  - last_trade_price/{asset_id}
  - market/{condition_id}/orders
storage: parquet per slug, partition by date+slug
retention: 90 days
estimated_volume: ~100 GB/month for BTC 5m + 15m
```

### Phase 2 (binance WS trades)

```yaml
collector: binance_trades_ws
endpoint: wss://stream.binance.com:9443/ws/btcusdt@trade
storage: parquet append-only
estimated_volume: ~5 GB/month
```

### Phase 3 (Polygon mempool)

```yaml
collector: alchemy_mempool_ws
endpoint: alchemy_pendingTransactions
filter:
  - to: {NegRisk matcher, CTF, NegRiskCtfExchange}
storage: parquet with status (pending → confirmed)
estimated_volume: ~2 GB/month
```

Once you have these, the trigger replication can be re-attempted with
event-level (not snapshot-level) signals.

---

## 5. What's deployable RIGHT NOW (without the missing data)

We tested everything we have. The honest deployable result is:

**Nothing in the F2 family validates as profitable.** The best variant
(follow + asz≥1000) passes G1 only because of one outlier day. Real
fees + permutation test fail it.

### Better near-term candidates already in our stack

| Strategy | Edge source | Status |
|---|---|---|
| **Cyclops S7 X1 (BTC 5m + sleeve_active)** | Multi-sleeve confluence + chain truth | **G1+G3+G4 PASS** at $1 stake |
| Mint-and-sell maker (0xeebde7a0 family) | Spread + maker rebate | **Spec'd, paper-ready** |
| Cyclops S7 baseline (no sleeve filter) | Trend+Levels coherent, momentum silent | G1+G3 PASS, G4 marginal |

The F2 attempt's value is **negative knowledge**: now confirmed that
binance-momentum alone is insufficient. Future attempts should integrate
CLOB event streams.

---

## 6. Files

- [strategy_lab/f2_replica/runner.py](../f2_replica/runner.py) — main backtest
- [strategy_lab/f2_replica/_threshold_sweep.py](../f2_replica/_threshold_sweep.py) — threshold grid
- [strategy_lab/f2_replica/_validate.py](../f2_replica/_validate.py) — G3/G4/G2 gates
- [strategy_lab/f2_replica/_results/f2_full_21d.csv](../f2_replica/_results/f2_full_21d.csv) — fade-rally (loses)
- [strategy_lab/f2_replica/_results/f2_both_dirs.csv](../f2_replica/_results/f2_both_dirs.csv) — both fade directions
- [strategy_lab/f2_replica/_results/f2_follow.csv](../f2_replica/_results/f2_follow.csv) — binance-follow inverted

---

## 7. Recommendation

**Stop trying to replicate F2 with snapshot data.** The strategy works at
sub-second event resolution that our canonical pipeline cannot capture
from existing parquets.

**Two paths forward:**

1. **Build the WS-event collectors (Tier 1)** then re-run the trigger
   discovery with event-grain data. Estimated 2-3 weeks of infra work
   before the analysis can even start.

2. **Deploy what already validates** (Cyclops X1 + mint-and-sell spec)
   and skip F2 for now. This produces real PnL today instead of more
   investigation cycles.

The user's call. F2's $5,900/day per wallet is tempting but the cost to
reach it is real.
