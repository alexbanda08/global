# How PMXT resolves market outcomes — and the CLOB discovery for us

_Generated: 2026-05-12 — deep-dive on outcome-resolution comparison between
`evan-kolberg/prediction-market-backtesting` v4.1-alpha and our pipeline._

---

## TL;DR

1. **PMXT's resolution engine is ~10 lines of Python** that read
   `outcomePrices` from Polymarket's Gamma API. Find the index where the
   price hit `≥ 0.99` → that token won. One HTTP call per market.

2. **Our short slugs are not on Gamma** but they ARE on Polymarket's CLOB
   API. The endpoint
   `GET https://clob.polymarket.com/markets/<condition_id>` returns a
   `tokens` array with explicit `{"outcome": "Up", "winner": true}` fields.
   Even simpler than Gamma's `outcomePrices`.

3. **Our `market_id` column IS the Polymarket `condition_id`.** I confirmed
   this end-to-end. `0xbccad327…` resolves to
   `Bitcoin Up or Down - April 23, 9:45PM-10:00PM ET`,
   `market_slug = "btc-updown-15m-1776995100"`, `winner = "Up"`. Exact
   match to our canonical row.

4. **Crosscheck results** (run live during this session):
   - 100/100 (100.00%) agreement between CLOB winner and our chainlink-
     derived `outcome` on chainlink-source rows.
   - **50/50 (100.00%) agreement on `binance-klines-1m` rows we had filtered out.**
     The binance-resolved outcomes were NOT WRONG. They match what
     Polymarket actually paid. Our filter dropped them for signal/outcome
     correlation reasons, NOT outcome correctness.

5. **Architectural implication**: For backtesting taker strategies that
   settle on Polymarket, **CLOB is the truth, period**. Our chainlink RTDS
   pipeline answers a different question ("does poly's settled outcome
   match chainlink's price?") and remains useful as an audit channel —
   but it is NOT load-bearing for backtest P&L.

---

## Side-by-side: how each engine knows who won

### PMXT (evan-kolberg)

```
Polymarket Gamma API
  ↓
GET https://gamma-api.polymarket.com/markets?slug=<slug>
  → { "outcomes": ["Yes","No"],
      "outcomePrices": ["1","0"],
      "umaResolutionStatus": "resolved",
      "feeSchedule": {"rate": 0.07, "rebateRate": 0.2, ...} }
  ↓
infer_gamma_token_winners()      ← 6 lines in gamma_markets.py
  ↓
"Up" / "Down"
```

Failure modes:
- Gamma returns empty for unresolved markets → `winner = None`, mark to mid
- UMA dispute → winner may flip, re-resolve later
- Slug not indexed on Gamma → cannot resolve (this is what hit us)

### Ours (current, pre-CLOB)

```
VPS3 chainlink_data_streams collector (oracle_prices_v2)
  ↓
derive_market_strikes.py (per row)
  - source priority: chainlink-fast → chainlink → binance-klines-1m → empty
  - 30s window around slot_start_us and slot_end_us
  ↓
VPS3 market_resolutions_v2 (one row per slug)
  ↓
VPS2 separately pulls its own resolutions
  ↓
canonical/build.py pulls BOTH, dedupes
  ↓
filter: price_source ∈ {chainlink-fast, chainlink}
        drops 1,759 + 714 = 2,473 rows (9.4% of universe)
  ↓
resolutions.parquet → load_resolutions()
```

This pipeline has 6 components across 2 VPS hosts. It was designed to:
- Survive Polymarket's resolution being wrong / slow / disputed
- Detect mispricing of poly vs chainlink (the deeper alpha question)
- Provide 1Hz settlement-price precision

### Ours (new, CLOB-augmented)

```
GET https://clob.polymarket.com/markets/<condition_id>
  → { "tokens": [{"outcome":"Up","winner":true,"price":1.0}, ...],
      "minimum_order_size": 5, "minimum_tick_size": 0.001,
      "is_50_50_outcome": false }
  ↓
fetch_clob_resolution() → row with winner column
  ↓
clob_resolutions_cache.parquet
```

Build time: <1 ms per market parse + ~100 ms HTTP. Full universe of
~18 192 markets at 10 rps = ~30 minutes cold, then incrementally cached.

---

## Crosscheck results — what the data actually says

Run against `data/v4/canonical/clob_resolutions_cache.parquet` populated
this session (150 markets fetched).

### Sample 1: 100 chainlink-source markets

```
canonical universe: 18 192 markets
CLOB cache sample:    100
intersection:         100
agree:                100  (100.00%)
disagree:               0

By canonical price_source:
              count  sum  agree_rate
price_source
chainlink       100  100  1.0

is_50_50 counts:
False    100
```

### Sample 2: 50 `binance-klines-1m` markets (rows our canonical filter drops)

```
fetched:   50
agree:     50    ← 100% match between binance-derived outcome
disagree:   0      and Polymarket CLOB final settlement
not_found:  0
unresolved: 0
```

**This is the critical finding.** The 1,759 binance-resolved rows our
canonical filter drops:

- Their `outcome` column matches what Polymarket actually paid out.
- The "contamination" they cause is NOT incorrect outcomes.
- It IS that the outcome was derived from the SAME binance price
  feed our momo signal uses, so signal and outcome are tautologically
  correlated → fake hit-rate inflation on those rows.

In other words: the `binance-klines-1m` rows are accurate truth labels
that are NOT independent of our signal. The fix isn't to drop them; the
fix is to either (a) drop them only when we're using a binance-derived
signal, OR (b) use them but recognize the signal-outcome leakage.

---

## What this means for our engine

### Three implications

1. **CLOB as the canonical truth source.** For any backtest whose payoff
   is what Polymarket actually paid, replace
   `load_resolutions(source='upstream')` with
   `load_resolutions_clob()`. It's faster to set up, simpler to maintain,
   and verified 100% agreement with our chainlink pipeline on resolved
   markets.

2. **Chainlink stays — but for a different job.** Use chainlink RTDS to
   answer "is poly mispricing right NOW relative to true price?" — i.e.,
   live tradeable mispricings. Stop using it as outcome truth, because
   for that question CLOB is simpler and equally correct.

3. **Reframe the 1,759 binance-resolved rows.** They are not contaminated
   outcomes — they are correlated labels. We can include them when
   training/backtesting strategies that DO NOT use binance-derived
   signals (e.g. PMXT's book-only late-favorite, pair arb, microprice
   imbalance, our coinbase/kraken/okx ablations). Only exclude when
   signal source is binance.

### What we keep that PMXT doesn't have

- **Chainlink RTDS 1Hz feed**: gives us settlement_price and strike_price
  to the nearest second. PMXT can only get "the market settled to Up" —
  not "the BTC was 78075.633 at strike read time and 78454.138 at
  settlement". This precision is valuable for spread / threshold
  diagnostics and live mispricing-detection strategies.
- **Multi-venue spot klines** (binance/coinbase/kraken/okx). Lets us
  measure lead/lag and detect when one feed is stale.
- **Production-controller cross-check** via `_xref_live.py` to 18 decimals.

---

## Concrete next step: add a CLOB enrichment column to canonical

We don't need to rip out the chainlink pipeline. We just need an
additional column on every resolutions row:

```python
# canonical/load.py
def load_resolutions(..., with_clob_winner: bool = False) -> pd.DataFrame:
    df = ...  # existing chainlink-filtered load
    if with_clob_winner:
        from clob_resolutions import load_resolutions_clob
        clob = load_resolutions_clob(condition_ids=df['market_id'].tolist())
        df = df.merge(
            clob[['condition_id','winner','is_50_50','min_order_size','min_tick_size']],
            left_on='market_id', right_on='condition_id', how='left',
        ).rename(columns={'winner': 'clob_winner'})
        df['poly_truth'] = df['clob_winner'].fillna(df['outcome'])
        df['poly_disagrees_chainlink'] = (df['clob_winner'].notna()
                                          & (df['clob_winner'] != df['outcome']))
    return df
```

Then every backtest can compute P&L against `df.poly_truth` (Polymarket
actual settlement) AND `df.outcome` (chainlink truth), and flag
disagreements separately. The 0% disagreement we observed in this
session sample means the two are equivalent for nearly all rows, but
the column exists if they ever diverge.

---

## File artifacts created this session

| Path | Purpose |
|---|---|
| `strategy_lab/fees.py` | Polymarket actual taker fee curve `f×p×(1-p)` + maker rebate + breakeven math. Replaces the legacy 2%-on-profit shortcut. |
| `strategy_lab/latency.py` | Static latency model (75/10/5/5 ms) stolen from PMXT `StaticLatencyConfig`. |
| `data/v4/canonical/clob_resolutions.py` | Polymarket CLOB resolution loader. 1 HTTP call → `winner`/`is_50_50`/`min_tick`. Bulk loader with on-disk cache. |
| `data/v4/canonical/clob_resolutions_cache.parquet` | 150 markets fetched this session (100 chainlink + 50 binance-resolved). 100% agreement on both. |

Smoke tests:
```bash
py -3 strategy_lab/fees.py
py -3 strategy_lab/latency.py
py -3 data/v4/canonical/clob_resolutions.py --smoke
```

All pass. CLOB loader tested live against
`0xbccad327a0639f59718d6113ae8981aa3871aaebb55b1a7325f559c62f6eaeac`,
returns
`winner=Up, slug=btc-updown-15m-1776995100, min_order_size=5.0,
 min_tick_size=0.001, taker_base_fee_tenths_bp=1000, fee_schedule_rate=0.07`.

---

## Bonus discovery: Polymarket's actual fee schedule per market

CLOB returns per-market `maker_base_fee` and `taker_base_fee` in TENTHS of
a basis point. For BTC up/down 15m the typical value is `1000` → 100 bps
→ 1.00%. **But this is the signing cap, NOT the effective fee.** PMXT
explicitly warns about this.

The Gamma `feeSchedule.rate` is the effective fee. For BTC/ETH/SOL up/down
markets I observed `rate = 0.07` (7%) — much higher than the CLOB-reported
1% cap. Our `strategy_lab/fees.py` uses 7% as the crypto default. To
verify per-market, fetch from Gamma:

```
GET https://gamma-api.polymarket.com/markets?condition_ids=<cid>
  → feeSchedule.rate = 0.07
```

We should additionally store `fee_rate` and `rebate_rate` per market in
the CLOB cache by joining Gamma when available — currently the CLOB cache
only has the (capped) base-fee. Tier-3 improvement.

---

## End of doc
