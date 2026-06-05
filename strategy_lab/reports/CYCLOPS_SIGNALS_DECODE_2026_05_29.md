# Cyclops Signals Telegram Bot — Decode & Validation

**Date:** 2026-05-30 (data tag 2026_05_29) · **Asset:** BTC 5m Polymarket up-down
**Source data:** `strategy_lab/wallet_hunt/cyclops_signals.csv` (1,599 msgs: 227 SIGNAL, 141 WIN, 82 LOSS, 1,145 WATCHING, 4 chatter)
**Truth source:** chainlink `load_resolutions(assets=['BTC'], timeframes=['5m'])` (9,831 slots, Apr 24 → May 29)
**Scripts:** `strategy_lab/_cyclops_{decode_master,trigger_refine,ptb_dir_pin,final_checks}_2026_05_30.py`
**Clean parse:** `strategy_lab/wallet_hunt/cyclops_clean_2026_05_30.parquet` + `cyclops_features_2026_05_30.parquet`

---

## 1. WR reality — three numbers

| Measure | Record | WR | Notes |
|---|---|---|---|
| **Advertised** (last `Record` line) | 53W 9L | **85.5%** | What the bot brags. Resets/inflated. |
| **Message-tally** (its own WIN/LOSS posts) | 141W 82L | **63.2%** | Its own honesty rate on what it bothered to post. |
| **OUR chainlink truth** (227 SIGNALs, 163 matched) | 85W 78L | **52.1%** | Coin-flip. n=163; 64 signals predate/outside chainlink overlap. |

**Gap = 33 points** advertised vs reality. The 85% is fabricated — the visible `Record` counter resets and only climbs on win streaks (`0W 1L` appears mid-stream on May 14, then a fresh `53W 9L` later). Realized 63% is the bot's *own* WIN/LOSS tally, but it **mislabels 13.2%** of resolved slots vs chainlink (21/159: 14 fake WINs, 7 hidden LOSSes), and those mislabels cluster on near-strike ties (median |move| $13 vs $33 overall) because the bot settles on **binance close**, not chainlink. **No cherry-picking of which slots to report** (223/227 signals got a follow-up), but **systematic favorable-rounding of outcomes.** True edge on our truth: **52.1%, indistinguishable from random.**

## 2. Trigger decode

**Direction (UP/DOWN) — moderate confidence:** `direction = sign(BTC − strike)`. Reproduces the bot's call **67–72%** (141 non-tie signals). Equivalent rules (BTC>strike / PTB-green / displayed arrow) all collapse to the same 66% because they are the same feature. Momentum (chainlink r1m–r5m) reproduces only 54–59% — **worse** than strike-position, so it is NOT momentum-continuation or mean-reversion. The residual ~30% are contrarian fires (bot bets *against* BTC-vs-strike, even against its own displayed arrow 33/113 times) that correlate with **nothing reproducible** in canonical klines/chainlink/L25 — likely an internal live price-tick read at a different instant than the displayed value. Direction is **not reverse-engineerable past ~70%.**

**PTB indicator — HIGH confidence, fully decoded:** PTB is **NOT a momentum oscillator.** It is literally the distance of BTC from strike, bucketed:
> `ptb = sign(BTC − strike) × min( round(|BTC − strike| / 12), 5 )`  → **87% exact match**, monotone bucket table (ptb 1↔$10, 2↔$22, 3↔$39, 4↔$48). Red squares 🟥 = below strike, green 🟩 = above; arrow ▲/▼/≈ = same sign. So "momentum squares" is marketing; it just re-encodes BTC−strike.

**Confidence / multiplier — HIGH confidence:** `mult × entry = 0.997` (a flat ~0.3% vig) → mult is just the inverse of entry price, pure book payout, **carries no signal.** Confidence label tracks |BTC−strike|: High mean $21, Medium $10, Low $7 (dots are cosmetic: 5 dots span both High and Medium). Conf = "how far we already are from strike," nothing predictive.

**Watch-vs-fire gate — HIGH confidence:** All 1,145 WATCHING msgs show `Market Neutral, UP 50¢/DN 50¢`. The bot **fires only when the book leaves 50/50** (98% of SIGNALs have entry≠50; entry range 37–82¢). So the gate is purely **"is the Polymarket book pricing one side off 50?"** — it tails the book's own move, not an independent signal. Fire rate 227/1,372 = 16.5%.

## 3. Edge after fees

Median entry **53¢**. Per-signal EV on chainlink truth with real entry prices (n=163):

| Fee model | EV / $1 | Total (163) | Per $25 |
|---|---|---|---|
| Legacy 2%-on-profit (production) | **−$0.017** | −$2.73 | **−$0.42** |
| 0.07 taker curve (hypothetical) | −$0.029 | −$4.69 | −$0.72 |

At the *claimed* 63% it would be +$0.077/$1, but that WR is fake — on our truth it is **net-negative even on the favorable legacy fee model.** Essentially the bot buys whichever side just ticked off 50¢ and prints a ~50% WR minus vig minus fees.

**vs our strategies:** our lag-taker is **WR ~68%, +$3/$25**; sniper sleeves positive. Cyclops is **−$0.42/$25, WR 52%** — strictly dominated. It has no book-walk fill model, no ws_s anchor, no chainlink settlement; it is the naive "follow the displayed price away from 50" trade we already know loses after fees.

## 4. Verdict

**Not worth replicating — it is a weaker, mislabeled version of strategies we already have.** Decode is complete: direction = `sign(BTC−strike)` (~70% reproducible, residual unrecoverable), PTB = `|BTC−strike|` in $12 buckets (87%), conf = |BTC−strike| tier, mult = book payout, fire-gate = "book left 50/50." True WR 52% → negative EV after fees. The advertised 85% is fabricated and 13% of its WIN/LOSS labels are wrong (binance-close vs chainlink ties). Nothing here we don't already do better. Archive as a competitor-intel data point; do not deploy.
