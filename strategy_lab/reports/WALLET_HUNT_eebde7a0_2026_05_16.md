# Wallet hunt — `0xeebde7a0e019a63e6b476eb425505b7b3e6eba30` (Polymarket bot)

_Generated: 2026-05-16. Source: data-api.polymarket.com, ~6h of trade history._

---

## TL;DR

1. **High-frequency bot, BUY-only, pyramids into one side per market**, scaling
   across the entire 5/15-min prediction window. 3,474 trades over 6 hours
   (~10 trades/min). 84% of activity is BTC/ETH/SOL up-down 5m/15m markets.
   100% of legs are buy-only — no market-making behavior.

2. **THE strategy signature: he is a contrarian. He FADES binance momentum.**
   On 87 resolved legs in our 6h sample:
   - When his pick agrees with binance pre-window momentum → **37.8% WR**
   - When his pick disagrees with binance momentum → **64.3% WR**
   - This is the exact INVERSE of our momo strategy.

3. **Current PnL is negative**:
   - −$190 net on the 87 resolved legs (−$2.18/leg with real Polymarket fees)
   - −$3,077 unrealized on 34 open positions
   - Current portfolio value: $1,680 (down from ~$5,500 cost basis)
   - **5m loses (-$7.31/leg), 15m wins (+$11.29/leg)** — strategy works on
     15m but the 5m volume drags it negative

4. **Why we care**: 64% WR on 42 contrarian legs is the strongest edge signal
   we've seen against our momo direction. Even acknowledging small-N, this
   sample is consistent with the **REST-lag artifact** finding from
   `MOMO_REST_LAG_VS_MICROSTRUCTURE.md` — momo's signal direction may
   ACTUALLY be inverted vs the right play once you correct for stale REST
   prices and look at WS-truth post-resolution.

5. **Replication candidate**: build `momo_INV_15m` — exact same anchors
   (`ws_s = slot_start - window_s`, `fire_us = ws_s + 120`) and gating
   (q90 |ret_2m|), but FIRE THE OPPOSITE SIDE. Re-run under live-mimic.
   If the corrected backtest shows positive expectancy, deploy as a shadow
   sleeve immediately.

---

## What we pulled

| Endpoint | Result |
|---|---|
| `data-api.polymarket.com/trades?user=<wallet>` | 3,474 trades (capped at 3500 offset; only most recent 6h) |
| `data-api.polymarket.com/positions?user=<wallet>` | 34 open positions, total $1,680 current value |
| `data-api.polymarket.com/value?user=<wallet>` | $1,680.44 |
| `data-api.polymarket.com/activity?user=<wallet>` | 3,500 activity rows |

Files written: `strategy_lab/wallet_hunt/cache/0xeebde7a0_{trades,positions,activity,per_leg,per_leg_resolved}.parquet`

## Activity profile

| Stat | Value |
|---|---|
| Trades | 3,474 |
| Time span | 6.1 hours |
| Trades/min | 9.5 |
| Unique conditionIds (up-down) | 121 |
| (market, outcome) legs | 221 |
| Avg trades per 5m leg | 9.6 |
| Avg trades per 15m leg | 22.7 |
| Median inter-trade gap (within leg) | 1.5 s |
| Side distribution | BUY 3,474 / SELL 0 |
| Price range | $0.001 — $0.99 |
| USD notional per trade (median) | $6.93 |
| USD notional per trade (max) | $2,972 |
| 84% of trades = up-down 5m/15m | yes |

## Intra-market behavior (microscope)

Example leg: `btc-updown-15m-1778904000 / Up` — 55 BUY trades:
- First trade at offset +7s (right after slot_start = strike read time)
- Last trade at offset +902s (15 min later, end of window)
- Buys throughout the entire window
- Price during accumulation drifts widely: $0.51 → $0.73 → $0.20 → $0.45 → $0.024
- **Final trade: 101.63 shares @ $0.024** — late-cycle "underdog scoop"

This is NOT mean-reversion (buys both at peaks and at dips); not pure
momentum (buys across the whole price range). It looks like a
**value-averaging / cost-basis averaging accumulator** with a final
**deep-value scoop** if the position has moved against him.

## Side-picking decode

The bot picks ONE side per market (Up or Down) and only buys that. Of 87
resolved legs:

| Hypothesis | Match rate | Win rate when matched | When NOT matched |
|---|---:|---:|---:|
| H1: follows binance pre-window momentum (ret_2m over [slot_start-120, slot_start]) | 45/87 (51.7%) | **37.8%** | **64.3%** |

**The fading-binance pattern is the strongest signal in the dataset.**

Interpretation: he bets AGAINST the side that just rallied on binance — a
mean-reversion / fade-the-news / "binance momentum is already priced into
Polymarket so go the other way" thesis. Whether this is intentional or
emergent doesn't matter — the win rate gap is 26 percentage points across
87 legs.

## Performance (with real Polymarket fees, our engine_v2 fee curve)

| Slice | n | Won % | Net PnL | $/leg |
|---|---:|---:|---:|---:|
| All resolved | 87 | 50.6% | −$189.79 | −$2.18 |
| 5m markets | 63 | 47.6% | −$460.64 | −$7.31 |
| **15m markets** | **24** | **58.3%** | **+$270.85** | **+$11.29** |
| BTC only | 80 | 50.0% | −$216.95 | −$2.71 |
| ETH only | 7 | 57.1% | +$27.15 | +$3.88 |

Plus 34 unresolved positions at cost basis $4,758, current value $1,680 →
unrealized −$3,077.

The bot loses on 5m and wins on 15m. Same conclusion our momo full-universe
backtest hit: 15m gives the underlying signal time to play out cleanly.

## Timing analysis

Per-leg average trade offset: 151s for winners, 155s for losers (within
~5s). Timing doesn't differentiate winners from losers — it's the side
PICK that decides PnL, not when within the window the buys happen.

## Differences from our momo strategy

| Aspect | Our momo | This bot |
|---|---|---|
| Fire count per market | 1 (at ws_s+120) | 9-23 (entire window, median 1.5s gap) |
| Side picked | matches binance ret_2m direction | OPPOSITE of binance ret_2m direction |
| Notional | $25 single fill | Pyramids across multiple sizes, $7 median |
| Outcome on test sample | corrected backtest: ~50% WR, slight loss | observed: 64% WR on contrarian / 38% on momo-aligned |
| Late-game underdog scoop | not present | yes — picks up cheap losers at end of window |

## Replication plan

### Phase A — Sanity check the contrarian signal (1 hour) — ✅ DONE

Ran `momo_full_universe_live_mimic.py --invert-signal --mode live_mimic`
on the full 23k market universe. Results in
`data/v4/canonical/_results/full_universe_INV_live_mimic_2026_05_16/`.

**Verdict: CONFIRMED on v2 anchors.** Inverting the signal flips v2 from
clearly losing to clearly winning, both before and after real fees:

| Version | Variant | Momo direction $/tr (live-mimic) | INVERTED $/tr (live-mimic) | Delta |
|---|---|---:|---:|---:|
| **v2** | **HOLD_baseline** | **−$2.74** | **+$0.50** | **+$3.25** |
| v2 | HYBRID_3bp | −$2.74 | +$0.50 | +$3.25 |
| v2 | HYBRID_5bp | −$2.74 | +$0.50 | +$3.25 |
| v2 | STOP_HEDGE_0.5x | −$2.74 | +$0.50 | +$3.25 |
| v2 | STOP_SELL_0.5x | −$2.74 | +$0.50 | +$3.25 |
| v2 | STOP_HEDGE_0.7x | −$2.70 | +$0.48 | +$3.18 |
| v2 | STOP_SELL_0.7x | −$2.68 | +$0.48 | +$3.16 |
| v2 | SELL_3bp | −$2.74 | −$1.22 | +$1.52 |
| v2 | HEDGE_3bp | −$2.98 | −$1.26 | +$1.72 |
| v2 | HEDGE_7bp | −$3.21 | −$1.18 | +$2.02 |
| v1 | HOLD_baseline | −$1.58 | −$0.48 | +$1.09 |
| v1 | STOP_HEDGE_0.7x | −$1.55 | −$0.47 | +$1.08 |

**Best inverted variants** (positive EV):
- v2 HOLD_baseline / HYBRID / STOP_HEDGE_0.5x → **+$0.50/trade, total +$367 over 734 trades**
- All clustered around the same number because the trigger never fires under
  contrarian-direction (his side rarely "goes adverse" in the rev_bp sense
  because we're already on the losing-momentum side, which mean-reverts)

**v1 inverted is better than momo-direction but not yet positive** — −$0.48/tr.
The v2 anchor (`ret over [ws_s-60, ws_s+60]`) captures the right signal to
fade; v1 anchor (`ret over [ws_s, ws_s+120]`) does not. The v2 window
straddles `slot_start` itself — that's exactly the moment Polymarket prices
incorporate the binance move, and the fade plays out over the next 5-15 min.

```python
# Reproducer
py -3 strategy_lab/meta_classifier/momo_full_universe_live_mimic.py \
    --mode live_mimic --invert-signal \
    --out-suffix INV_live_mimic_<date>
```

### Phase B — Replicate the "fade ret_2m" strategy (~3 hours)

If Phase A confirms, build `strategy_lab/meta_classifier/momo_INV_canonical.py`:

```python
from engine_v2 import LiveMimicConfig, fill_at_book, hold_pnl
cfg = LiveMimicConfig()

# Per market:
ws_s = slug_to_ws_s(slug, tf)
ret_2m = ret_2m_at_ws(end_us_binance, prices, ws_s)
# Gate: top-decile |ret_2m| per (asset, tf, day) on 14d lookback (same as momo)
if abs(ret_2m) >= q90_thresh:
    # FADE the binance direction
    held = "Down" if ret_2m > 0 else "Up"
    fill = fill_at_book(books, slug, held, fire_us=(ws_s+120)*1e6,
                        cfg=cfg, spread_filter=0.02)
    pnl = hold_pnl(fill, won=(held == clob_winner), cfg=cfg)
```

Compare hit rate + PnL vs our momo direction across the full 23,553 market
universe.

### Phase C — Replicate the pyramid strategy (~1 day)

If Phase B confirms positive PnL, build the multi-fill pyramid version:

- Same `ws_s + 120` initial fire
- Add 5-10 more buys over the next 15 minutes (for 15m markets)
- Use 1.5s median gap, ~$7 median size per fill
- BONUS: add late-window underdog scoop if cheap-side ask < $0.05 in
  final 60s of window

### Phase D — Track this wallet in real time (~half day)

Build `strategy_lab/wallet_hunt/track_live.py` that polls
`/trades?user=<wallet>&limit=50&end_time=<now>` every 30 seconds and
streams new fills to a local log. Validates the strategy keeps working as
predicted; gives us a real-world benchmark.

---

## Open questions

1. **What's his real win rate on 15m?** 24 resolved legs is small N. We
   should re-validate against the canonical universe (23k markets) — our
   `momo_INV` backtest covers far more.

2. **Why does he lose on 5m?** Best guesses:
   - 5m REST/WS lag (he fires off REST too?) → bigger relative impact than 15m
   - 5m fee weight is higher (fewer shares but same fee curve impact)
   - 5m signal is just noise

3. **Is the contrarian thesis structural or random?** Test: re-run on a
   different 6h window for the same wallet (fetch later in time). If the
   same 64% / 38% split shows up, it's structural.

4. **Where does the deep-value scoop fit?** The 100-share @ $0.024 trade at
   end of window suggests a separate signal — maybe "if my held position
   is losing AND the OTHER side is at a steep premium, scoop it cheap as
   a hedge". Worth backtesting separately.

5. **Does the bot also trade other markets?** 16% of trades aren't BTC/ETH/SOL
   updown — what are they? Could be elections, sports, etc. — those legs
   might be where his real edge lives.

---

## Files referenced

| Path | What |
|---|---|
| `strategy_lab/wallet_hunt/fetch_wallet.py` | Bulk-fetch trades + positions + activity |
| `strategy_lab/wallet_hunt/analyze_wallet.py` | First-pass analysis: distribution + timing |
| `strategy_lab/wallet_hunt/deep_dive.py` | Per-leg aggregation + strategy classification |
| `strategy_lab/wallet_hunt/strategy_decode.py` | Side-picking decode + true PnL with engine_v2 fees |
| `strategy_lab/wallet_hunt/cache/0xeebde7a0_trades.parquet` | 3,474 trades |
| `strategy_lab/wallet_hunt/cache/0xeebde7a0_positions.parquet` | 34 open positions |
| `strategy_lab/wallet_hunt/cache/0xeebde7a0_per_leg.parquet` | 221 (market, outcome) legs |
| `strategy_lab/wallet_hunt/cache/0xeebde7a0_per_leg_resolved.parquet` | 87 resolved legs with CLOB winner + side-decode |

---

## End of doc
