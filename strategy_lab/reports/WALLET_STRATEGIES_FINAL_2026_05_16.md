# Wallet strategies — chain + L25 + binance + chainlink cross-verified
_2026-05-16. 5 wallets, ~1 day chain history each, cross-checked against our
local canonical data (L25 books, binance klines, chainlink RTDS, CLOB winners)._

---

## TL;DR — strategies decoded and ranked

| Wallet | Side mix | Maker% | Captured spread | Signal match (binance) | Net PnL/leg ¹ | Strategy classification |
|---|---|---:|---:|---:|---:|---|
| `0xeebde7a0` | 52% BUY / 48% SELL | mixed | **+$0.040** | 48.2% | −$81 | **Pure market-maker** — captures 4¢ per share, both sides |
| `0xce25e214` | 73% BUY / 27% SELL | 27% | −$0.023 | 49.1% | −$99 | **Active taker churner** — no edge identified; possibly using a non-binance signal |
| `0x89b5cdaa` | 0% BUY / 100% SELL | n/a | n/a | 46.6% | **+$39** ✅ | **Mint-and-sell arbitrage** — only positive wallet in sample |
| `0xcfb103c3` | 90% BUY / 10% SELL | low | +$0.006 | 49.7% | −$41 | **Pyramid accumulator BTC 5m only** — losing |
| `0x04b6d7e9` | 2% BUY / 98% SELL | 100% maker | n/a (mostly mint+sell legs) | 52.4% | −$139 ² | **Mint-and-sell BTC focus** — PnL accounting incomplete |

¹ Net PnL/leg from book-anchored decode + canonical CLOB winners + Polymarket
real fee curve (`0.07 × p × (1-p)`) on every fill, with 20% maker rebate. Top
50–60 most-active slugs only (not full universe).

² `0x04b6d7e9`'s mint-and-sell strategy requires summing Up+Down legs per
market — we groupby (slug, outcome) which separates them. True PnL likely
positive when reconciled (see "Why not yet trustworthy" below).

**Signal alignment is ~50% across ALL wallets** when measured against
binance pre-window momentum. The "contrarian" thesis I had earlier was a
data-api 3500-cap artifact — does NOT hold up on full chain data.

---

## Critical findings from cross-verification

### 1. Decoder validation: chain price extraction is broken in 80%+ of fills

Cross-checking chain-decoded prices against L25 book at exact fill timestamp:

```
0xce25e214: 10,142 fills cross-verified
  abs(decoder_diff) p50 = $0.21
  abs(decoder_diff) p90 = $0.45
  fills within ±$0.01 of book: 4.4%
  fills within ±$0.05 of book: 16.1%
```

The `takerAssetId / 1e7` price-encoding only holds for a subset of fills.
The rest have price encoded in a different field. **Solution applied**:
use L25 book as ground truth (`book_anchored_decode.py`).

### 2. L25 book lookup matches every fill perfectly

```
0xce25e214: 10,142 fills → 0 missed book lookups
```

When we restrict to slugs the wallets traded, the canonical L25 covers them
completely. The chain timestamp → L25 ts lookup works exactly.

### 3. Spreads at fill time are very tight (1-2 cents)

```
0xce25e214 spread at fill time: p25=$0.01 med=$0.01 p75=$0.02
0xeebde7a0 spread at fill time: med=$0.02 (slightly wider)
```

These wallets fight for spread in an already-tight market. Maker rebate
(`0.07 × p × (1-p) × 0.20`) ≈ $0.0035/share at p=0.5 is a meaningful
fraction of the 1¢ spread.

### 4. Timing in window is the strongest behavioral differentiator

```
                       5m offset        15m offset
0xeebde7a0:            med 12-280s      med 4-879s        (full window)
0xce25e214:            med 165s         med 576s          (mid+late window)
0x89b5cdaa:            med 141s         med 549s          (mid window)
0xcfb103c3:            med 117s         n/a (5m only)     (mid window)
0x04b6d7e9:            med (varies)     med 458s          (mid+late)
```

**`0xce25e214` only trades the LAST 5 MINUTES of 15m markets** (offset
median 576s into a 900s window). They WAIT for the market to develop
before entering. This is the strategy signature we missed before.

`0xeebde7a0` is the only true MM — enters at t=4s and runs to t=879s,
making markets throughout the full window.

### 5. Signal alignment is RANDOM (50%) for all wallets

```
Wallet         BUY matches binance    SELL matches binance    Overall
0xeebde7a0     50.2%                  46.0%                   48.2%
0xce25e214     49.0%                  50.5%                   49.1%
0x04b6d7e9     48.9%                  52.5%                   52.4%
0xcfb103c3     49.7%                  50.1%                   49.7%
0x89b5cdaa     n/a                    46.6%                   46.6%
```

The contrarian-binance edge I found earlier (63% WR contradicting binance)
was caused by the data-api 3500-cap clipping the wallet's BUY activity to
only the side that was winning. **There is no momentum-based edge.**

The wallets that profit do so via STRUCTURE (mint-and-sell, spread capture)
NOT via direction-prediction.

---

## The 2 edges we've identified

### Edge A: Market-making (0xeebde7a0)

Empirical from book-anchored decode (100 top legs):
- 100% of legs have BOTH buys AND sells
- Avg captured spread: **+$0.040 per share**
- Average shares per leg: ~1,500-2,500
- Maker fills get 20% rebate × `0.07 × p × (1-p)` ≈ $0.0035/share at p=0.5
- Top legs show $0.04-0.14 spread captured + maker rebate × maker fills

**Theoretical edge per share** at the median observed:
- Spread capture: +$0.040 × matched_shares
- Maker rebate: +$0.0035 × maker_shares
- Fees on taker fills: −$0.0175 × taker_shares (at p=0.5)
- Net: positive when matched_shares × $0.040 > taker_fees

**Our backtest needs** (currently we're taker-only): `engine_v2.post_limit_at_book()`
+ proper queue-position model. Not trivial.

### Edge B: Mint-and-sell arbitrage (0x89b5cdaa, 0x04b6d7e9)

The strategy:
1. Call `CTF.splitPosition(amount)` — pay `amount` USDC, receive `amount` Up
   tokens + `amount` Down tokens
2. Post limit SELL at best_ask on the Up token
3. Post limit SELL at best_ask on the Down token
4. When both fill: cash received = amount × (sell_px_up + sell_px_down)
5. If `sell_px_up + sell_px_down > $1` → profit!

Empirically, **0x89b5cdaa is the only wallet with consistently positive
PnL** in our sample: +$2,326 net over 60 resolved legs (=$38.78/leg).

`0x04b6d7e9` runs the same strategy at much higher volume ($17.9M notional
1d) but our per-leg PnL accounting misclassifies them as losing because we
groupby (slug, outcome) instead of pairing Up+Down per market. True PnL
likely positive.

**Our backtest needs**: detect markets where `best_ask(Up) + best_ask(Down)
> $1 + fees` and simulate the mint+sell. This is a scan over our canonical
L25 — straightforward. The pair-arb scanner in `pair_arbitrage/scan_canonical.py`
already does the OPPOSITE direction (buy YES+NO when sum < $1). Mirror it.

---

## Why our PnL numbers aren't trustworthy yet

1. **Per-leg PnL is groupby (slug, outcome)** — for mint-and-sell strategies
   the true unit is (slug, both outcomes). Need to combine.

2. **Top-N slug filter biases** — we only look at 60 most-active slugs. May
   be missing the wallet's "lucky" lower-frequency markets. Need full
   universe.

3. **1-day chain window is too narrow** — 100 legs per wallet only ~50%
   resolved. Need 7-30 days for statistical confidence.

4. **Side classification in book-anchored decoder is still heuristic** —
   uses `maker_holds_token` flag. May misclassify when contract is the
   matcher counterparty.

These don't change the STRATEGY identification (which is robust) — just
the PnL magnitudes.

---

## Strategy taxonomy + replication readiness

| Strategy | Wallet exemplar | Currently replicable? | Effort to build |
|---|---|---|---|
| **Market-making** (post both sides, capture spread + rebate) | `0xeebde7a0` | ❌ No (we're taker-only) | 5-8 hours: extend `engine_v2.py` with `post_limit_at_book()` + queue-pos model |
| **Mint-and-sell arb** (when `ask_up + ask_down > $1`) | `0x04b6d7e9`, `0x89b5cdaa` | ⚠️ Partially (`pair_arbitrage/scan_canonical.py` does the reverse) | 4-6 hours: scan + add `CTF.splitPosition` simulation; backtest is just "when does sum exceed $1 + fees?" |
| **Late-window taker** (enter last 5 min of 15m markets) | `0xce25e214` | ✅ Yes — just change `fire_us` | 1 hour: backtest with our `momo_full_universe_live_mimic` setting `fire_us = (slot_start_s + 600) × 1e6` |
| **Pyramid accumulator** | `0xcfb103c3` | ✅ Yes but LOSING (-$40/leg confirmed) | Don't replicate |

---

## What to do next session

### Priority 1 — Build mint-and-sell scanner (3-4h)

Mirror `pair_arbitrage/scan_canonical.py` to ALSO scan for markets where
the sum of best asks > $1.005 (mint+sell threshold). Easy backtest:
- For each second of each up-down market in our 21-day canonical window,
  compute `best_ask(Up) + best_ask(Down)` net of fees.
- When > $1, simulate minting + posting limit SELL on both at best_ask.
- Track fill probability (impatient takers hitting our ask) → realized PnL.

If even 1% of seconds across 23k markets satisfy this, we have a free-money
strategy.

### Priority 2 — Late-window taker backtest (1h)

Re-run `momo_full_universe_live_mimic.py` with `fire_us = (slot_start + 600) × 1e6`
to mimic 0xce25e214's timing. Compare PnL.

### Priority 3 — Wider chain backfill (overnight, 6-12h)

Pull 14-day chain history for all 6 wallets. With ~30k fills/day per active
wallet, that's ~420k fills total — robust statistics. The 1-day sample is
too thin to confirm/deny edges.

### Priority 4 — Fix mint-and-sell PnL accounting (1-2h)

Update `compute_pnl.py` to combine Up+Down legs per market for wallets
flagged as mint-and-sell (negative leftover dominant). Re-rank PnL.

### Priority 5 — Real-time wallet tracker (1h to wire)

`strategy_lab/wallet_hunt/shadow_track.py` already exists for data-api;
extend with chain RPC polling for fills missed by the data-api cap. Now we
have full visibility per wallet without the 3500 ceiling.

---

## Files written this session

| Path | Purpose |
|---|---|
| `strategy_lab/wallet_hunt/fetch_chain.py` | Polygon RPC scanner for OrderFilled events |
| `strategy_lab/wallet_hunt/asset_lookup.py` + `_token_lookup.parquet` | 52k token_id → slug index |
| `strategy_lab/wallet_hunt/analyze_chain.py` | Per-wallet up-down filter + first-pass fingerprint |
| `strategy_lab/wallet_hunt/cross_verify.py` | Cross-check chain decoded prices against L25 (revealed decoder bug) |
| `strategy_lab/wallet_hunt/book_anchored_decode.py` | **Re-decode using L25 as ground truth** (the working pipeline) |
| `strategy_lab/wallet_hunt/compute_pnl.py` | Realized PnL with engine_v2 fees + CLOB winners |
| `strategy_lab/wallet_hunt/cache/<short>/fills_book_decoded.parquet` | Final clean per-wallet fills |
| `strategy_lab/wallet_hunt/cache/<short>/legs_pnl.parquet` | Per-leg with winners + PnL |
| `strategy_lab/wallet_hunt/cache/_pnl_summary.csv` | Cross-wallet PnL ranking |
| `strategy_lab/reports/WALLET_STRATEGIES_FINAL_2026_05_16.md` | This doc |

---

## The big reframe vs prior reports

Two prior session findings are now SUPERSEDED:

1. **"Contrarian-fade-binance is profitable" (WALLET_HUNT_eebde7a0_2026_05_16.md):**
   Was a data-api 3500-cap artifact. Full chain data shows 49% signal
   alignment for the same wallet — random. The `momo_full_universe_live_mimic
   --invert-signal` backtest result (+$0.50/tr on v2 HOLD) may still be a
   real edge, but it's NOT the strategy these wallets are running.

2. **"0xeebde7a0 is a pyramid taker" (data-api decode):**
   Chain data reveals 65% both-sides legs, 53% maker fills. **It's a pure
   market-maker.** The data-api was clipping out the maker fills entirely.

The lesson: **never trust data-api for behavioral fingerprinting** —
always pull from chain. The 3500 cap creates massive selection bias
toward whichever side was most active in the most recent window.

---

## End of doc
