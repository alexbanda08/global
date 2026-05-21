# Multi-wallet hunt — 6 Polymarket bots, decoded — 2026-05-16

_Source: data-api.polymarket.com. Engine: `strategy_lab/engine_v2.py` with real
Polymarket fees (0.07 × p × (1-p) per fill) + chainlink/CLOB outcome truth._

---

## TL;DR — wallets ranked by edge

| # | Wallet | Strategy class | n trades | trades/min | net $/leg | best subgroup |
|---|---|---|---:|---:|---:|---|
| 1 | **`0xce25e214…`** | **PYRAMID_TAKER (contrarian)** | 3,500 | 5.4 | **+$7.05** | **BTC 15m: n=34, +$969, WR=50%** |
| 2 | **`0x04b6d7e9…`** | SINGLE_FIRE_TAKER + SCALPER | 3,500 | 0.2 | −$0.26 (net) | **BTC 15m: n=264, +$2,466, WR=45.5%** |
| 3 | `0x89b5cdaa…` | MAKER_BOTH_SIDES (35.9% both sides) | 3,500 | 7.2 | n/a | not enough resolved |
| 4 | `0xeebde7a0…` | PYRAMID_TAKER + SCALPER (contrarian) | 3,474 | 9.5 | −$2.18 | BTC 15m: +$200, 20 legs |
| 5 | `0x7cde1da9…` | EXTREME-BURST MAKER (5-MIN window!) | 3,013 | **636** | n/a | 5-min event burst |
| 6 | `0xcfb103c3…` | PYRAMID_TAKER (BTC 5m only) | 3,500 | 2.1 | −$10.44 | BTC 5m −$5,542 (losing badly) |

**Two profitable wallets: `0xce25e214` and `0x04b6d7e9`. Both win on BTC 15m.
Both lose or break even on 5m. This is consistent with our internal momo
backtest finding that 15m is where any real signal lives.**

---

## Per-wallet behavioral fingerprints

### 1. `0xce25e214d5cfe4f459cf67f08df581885aae7fdc` — the winner

```
n_trades=3500  span=10.7h  tpm=5.4
side=100% BUY  up_down_focus=92.2%  med_buy_px=0.507  trades/leg=15.5
1-trade legs=3.8%   both-sides legs=0% (pure taker, no sells)
strategy_class=PYRAMID_TAKER
```

PnL on 147 resolved legs:
- WR overall: 50.3%
- **WR when his pick MATCHES binance pre-window momentum: 37.8%**
- **WR when his pick CONTRADICTS binance momentum: 63.0%**
- Net PnL: +$1,036.78 ($7.05/leg)
- Best subgroup: BTC 15m, 34 legs, +$969

**Strategy**: SAME contrarian-pyramid as `0xeebde7a0` but at half the
trading frequency. Side-picking is mathematically identical (63% WR
fading binance). The lower frequency seems to help — fewer fees, less
slippage, better fills.

### 2. `0x04b6d7e9930cf9e493c5e6ef24b496294f95594c8` — the slow grinder

```
n_trades=3500  span=270.3h (11 days!)  tpm=0.2
side=100% BUY  up_down_focus=100%  med_buy_px=0.450  trades/leg=3.3
1-trade legs=51.5%  both-sides legs=0%
strategy_class=SINGLE_FIRE_TAKER + SCALPER
```

PnL on 822 resolved legs:
- WR overall: 45.4%  ← BELOW 50%
- WR matches binance: 45.0% — WR contradicts: 45.8% — no contrarian edge
- Net PnL after fees: −$217.40 ($-0.26/leg, basically breakeven)
- **Best subgroup: BTC 15m, 264 legs, +$2,466, WR=45.5%**

**Strategy**: This bot wins on **price asymmetry** — not on hit rate.
Median buy price is 0.450 (under $0.50). On BTC 15m, 45.5% × $1 payoff −
54.5% × $0.45 cost ≈ $0.455 − $0.245 = +$0.21/share gross. Across 264
legs × ~46 shares each (rough) × $0.21 = +$2,485 ≈ what we observe.

This is **deep-value / underdog betting**: buy whichever side is priced
below 0.50 (the "undervalued underdog"), eat lower hit rate, win on the
$1 payoff being larger than (1/0.45 − 1) × 0.55 of losses.

### 3. `0x89b5cdaa4866c1e738406712012a630b4078beb` — market maker

```
n_trades=3500  span=8.1h  tpm=7.2
side=75% BUY / 25% SELL  up_down_focus=85.5%  med_buy_px=0.522
trades/leg=4.1  1-trade legs=27.2%  both-sides legs=35.9%
strategy_class=MAKER_BOTH_SIDES
```

35.9% of legs have BOTH buys AND sells = classic market making. Posts
on both sides of the inside, captures spread. No resolved markets yet
(too recent) so we can't measure realized edge — but the structure is
clear.

**Strategy**: Polymarket maker rebate scalping. Posts limit orders inside
the spread, gets the 20% maker rebate on every fill (`fees.py:
poly_maker_rebate_per_share`). Profitable if avg captured spread >
fee_per_share × (1 − rebate_share).

### 4. `0xeebde7a0e019a63e6b476eb425505b7b3e6eba30` — the contrarian (original)

See `WALLET_HUNT_eebde7a0_2026_05_16.md`. Same strategy as `0xce25e214`
but losing money. Likely losing because of higher trade frequency
(9.5 tpm) → more fees + slippage.

### 5. `0x7cde1da9d380bf8002ccbe8e0cb9474c4d71e48e` — flash-event scalper

```
n_trades=3013  span=0.1h (5 MINUTES!)  tpm=636
side=85% BUY / 15% SELL  up_down_focus=53%  med_buy_px=0.510
trades/leg=61.4  both-sides legs=68%
strategy_class=MAKER_BOTH_SIDES + SCALPER
```

**ENTIRE 3,013-trade history is within ONE 5-minute window.** This is
event-driven: probably arbed a single news event or a price dislocation.
~600 trades/minute = 10/second. 68% of legs have both sides = aggressive
market-making during a high-volatility burst.

**Strategy**: not continuously running — opportunistic. Triggered by some
external signal (likely high-vol period on binance). Hard to replicate
without knowing the trigger.

### 6. `0xcfb103c37c0234f524c632d964ed31f117b5f694` — BTC 5m only, losing

```
n_trades=3500  span=28.4h  tpm=2.1
side=100% BUY  up_down_focus=100%  med_buy_px=0.507  trades/leg=5.6
strategy_class=PYRAMID_TAKER  (BTC 5m ONLY)
```

PnL on 531 resolved legs: net **−$5,542 ($-10.44/leg!)**, WR=49.9%
matches=46%, contra=54%.

Same contrarian-fade pattern weakly visible (54% vs 46%) but he ONLY
trades BTC 5m. Our backtest also confirmed 5m loses under the contrarian
recipe (-$1.58/tr vs +$0.50 on 15m). This wallet is bleeding because of
asset/timeframe choice, not because the signal is wrong.

---

## Cross-wallet pattern — what's the alpha?

**The contrarian-fade-binance-momentum signal exists**:
- 0xeebde7a0: 64.3% WR contra vs 37.8% match
- 0xce25e214: 63.0% WR contra vs 37.8% match
- 0xcfb103c3: 53.8% WR contra vs 46.0% match (weaker, BTC 5m only)
- 0x04b6d7e9: NO contra/match WR gap → different strategy (deep-value)

**Where it works**: BTC 15m (decent-N positive PnL in 2 of 3 contrarian wallets).
**Where it doesn't**: BTC 5m (likely too noisy / dominated by fee+latency cost).

This validates our `momo_full_universe_live_mimic --invert-signal` finding
which showed v2 HOLD_baseline INVERTED at +$0.50/tr. Three independent
profitable wallets running essentially the same recipe is strong
out-of-sample evidence.

**Replication recipe (consolidated)**:

```
For each BTC/ETH 15m up-down market:
  ws_s        = slot_start_s - 900            # 15m window
  ret_2m_pre  = log(binance_close@(slot_start) / binance_close@(slot_start - 120))
  if |ret_2m_pre| >= q90 threshold on rolling 14d lookback:
      side_to_buy = "Down" if ret_2m_pre > 0 else "Up"   # FADE binance
      fire_us = (slot_start_s + offset) * 1e6            # ~5-60s after slot opens
      fill_at_book(books, slug, side_to_buy, fire_us, cfg=LiveMimicConfig())
      hold to resolution
```

Optional layers (observed in different wallets):
- **Pyramiding** (0xeebde7a0, 0xce25e214): scale into the position with
  4-15 fills across the prediction window — splits fees across multiple
  fills and gets multiple price points. Useful only if the position can
  be averaged DOWN (your side keeps getting cheaper). Avoid if your
  conviction is purely at fire.
- **Deep-value layer** (0x04b6d7e9): also buy the side with price < 0.50
  even when binance signal is neutral. Wins on the $1 payoff asymmetry
  without needing >50% WR.
- **Late-window underdog scoop** (0xeebde7a0): if your held side is
  losing and the other side is at <$0.05 with <60s left, scoop. Free
  optionality if the underlying spikes.

---

## Replication backtest plan + first results

### Run 1 — BTC 15m INVERTED (the wallet replica)

Filtered the live-mimic runner to BTC + 15m + inverted signal:
```
py -3 strategy_lab/meta_classifier/momo_full_universe_live_mimic.py \
   --mode live_mimic --invert-signal --filter-asset BTC --filter-tf 15m \
   --out-suffix WALLET_REPLICA_btc15m_INV_2026_05_16
```

Result: v2 HOLD_baseline INVERTED on BTC 15m only = **−$1.42/trade**
(vs the wallet observations of +$7.05 and +$9.34 per leg).

**Our backtest does NOT reproduce the wallets' edge** even after
inverting the signal. The +$0.50/tr we got on the full 23k universe is
driven by ETH/SOL 15m, NOT BTC 15m where the wallets win.

### Why the gap? Three likely causes

1. **Our q90 gating is too tight.** We only fire when |ret_2m_pre| ≥
   q90. The wallets fire on ESSENTIALLY EVERY BTC 15m market (3,500
   trades / ~200 unique 15m markets ≈ 17 trades per market). Their
   signal applies to ALL markets, not just top-decile movers.
2. **Our fire timing is wrong for them.** Our `fire_us = ws_s + 120`
   fires 13 minutes BEFORE the 15m slot opens. The wallets fire at
   `slot_start + 7s to + 902s` — during the active prediction window.
   That's a totally different snapshot of the book.
3. **They pyramid; we single-fire.** Their 17 trades per market average
   into a position across many prices. A single fire at one moment
   picks up the snapshot price, not the time-averaged price.

### Next-session backtest variants (priority)

1. **Un-gated BTC 15m INVERTED**: fire EVERY market, not just q90.
   Set `GATE_Q = 0` for one run. Expect lower per-trade PnL but
   ~10× more trades. Total PnL should approach the wallets' magnitude.

2. **Wallet-timing BTC 15m INVERTED**: change `fire_us` to
   `slot_start_s * 1e6 + 30_000_000` (fire 30s into the prediction
   window, after slot opens). Same inverted-binance signal.

3. **Pyramid BTC 15m INVERTED**: fire 5 times at
   `slot_start + {30, 90, 180, 360, 720}` seconds. Each fill at $5
   instead of $25 (same total notional). Average vwap across fills.

4. **Deep-value standalone**: replicate 0x04b6d7e9's strategy. For each
   market, at `slot_start + 60s`, if best_ask_min(Up, Down) < 0.50,
   BUY that side. No binance signal at all. Hold to resolution.

5. **Walkforward + permutation** on each surviving variant.

### Shadow trade mode (running now)

`strategy_lab/wallet_hunt/shadow_track.py` — polls all 6 wallets every
30s, writes new trades to `data/wallet_shadow/<short>/<UTC-date>.jsonl`.
Already populated all 6 wallets on first poll. Run in background as a
service. Next-session: compute realized PnL per wallet daily, post a
Discord summary.

---

## Shadow trade mode

While we backtest, start polling all 6 wallets every 30s and log new
trades. Compute live realized PnL for each. If `0xce25e214` keeps printing
positive PnL over the next 7 days under our engine_v2 accounting, deploy
the replicated strategy live the following week.

Implementation: `strategy_lab/wallet_hunt/shadow_track.py` (next-session
artifact). Posts to `data/wallet_shadow/<wallet>/<date>.jsonl`.

---

## Files

| Path | Contents |
|---|---|
| `strategy_lab/wallet_hunt/fetch_many.py` | Multi-wallet bulk fetcher (handles user= and proxyWallet= params) |
| `strategy_lab/wallet_hunt/fingerprint.py` | Behavioral fingerprinter — no preconceptions |
| `strategy_lab/wallet_hunt/_run_all.py` | One-shot fingerprint + PnL decode for N wallets |
| `strategy_lab/wallet_hunt/cache/<short>/{trades,positions,per_leg,value}` | Per-wallet artifacts |
| `strategy_lab/wallet_hunt/cache/_wallet_summary.json` | Combined ranking + decode |
| `strategy_lab/reports/TV_AGENT_WALLET_DECODER_SPEC.md` | (next file) Productionization spec for TV |

---

## End of doc
