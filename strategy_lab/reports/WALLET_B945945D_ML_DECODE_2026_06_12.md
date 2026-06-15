# ML DECODE — wallet `0xb945945d` (@l5zn1bwom8etsk) — FINAL: there is NO entry signal; he is a passive two-sided MAKER

_2026-06-12. Pipeline: `wallet_hunt/_b945_build_tape.py` (chain fill-tape reconstruction: 144,589 fills,
88.4% token coverage via CLOB-by-condition lookup) → `_b945_ml_decode.py` (67,198 in-scope BTC-15m fills
Apr 22+ × 23,724 matched controls × 22 features: RTDS delta/returns, Binance 1s returns, L25 both-token
books, time-in-window, inventory state; HistGradientBoosting, TIME-split train/test) →
`_b945_side_decode.py` (side decode + rules) + fill-price-vs-book classification.
Feature cache: `cache/0xb945945d/ml_features.parquet`._

## 1. What the models found

| Model | AUC (test) | Driver | Reading |
|---|---|---|---|
| A: any-fire vs control | 0.737 | off (time), up_mid, \|rtds_ret5\| | fires more late-window, at mid prices, when oracle is MOVING (U-shaped in either direction) |
| B: leg1 open vs control | 0.932 | off alone (+0.38; next feature +0.005) | **opening is time-deterministic: he opens EVERY market in the first ~2 min. No signal in when.** |
| C: leg1 SIDE (Up/Dn) | **0.532 ± 0.035 (5-fold)** | nothing | **NO directional signal at open. Coin flip.** |
| D: hedge fire vs control | 0.731 | off, up_mid, \|rtds_ret5\| | hedge intensity rises late + when oracle moves; avoids extremes |

Side rules (sign-agreement accuracy): best single feature `rtds_ret5` = **0.541–0.555** (noise-level);
`delta` = **0.460 on all fills — he buys AGAINST the oracle** (the lagging side); buys-cheaper-side = 0.55;
net residual P(long Up) = 0.526 ≈ coin flip; residual side vs late delta agreement **0.402 — his leftover
exposure is the LOSING side** (incomplete hedges), not a bet.

## 2. Fill-price vs book (66,859 fills with book state)
At-or-below own bid **47.6%** · inside spread 4.2% · at ask 18.0% · rest blurred by Polygon block-time
(±2s) — median distance +0.7¢ above bid / −0.8¢ below ask. With $3,622.57 in MAKER_REBATE (≈2.4M shares
≈ his entire volume at pool-prorated ~0.0015/sh) the conclusion is firm: **the overwhelming majority of
his fills are RESTING LIMIT BIDS.** His article corroborates: "standing bid in the queue", FIFO
queue-position obsession, CPU pinning = maker queue racing.

## 3. THE DECODED STRUCTURE (complete)
```
Passive two-sided bid MAKER on both tokens of every btc-updown-15m window:
 1. Open every market in the first ~2 min with a tiny clip (no side signal — coin flip).
 2. All window long, rest bids on BOTH tokens, re-quoting as price moves; fills arrive
    disproportionately on the LAGGING/dipping side (delta-contrarian by construction —
    that's whose bid gets hit). ~82 fills/market, $5 median clips, ~$726/market.
 3. Quote intensity rises when the oracle is MOVING (either direction — that's when takers
    cross spreads) and late-window; avoid extreme prices (<0.10 / >0.97 mids).
 4. Never sell. Pairs complete across time at blended ~0.94; hold everything to redeem.
 5. Income = bid-ask spread capture (~1-2¢/fill × ~2.4M shares) + maker rebates ($3.6k
    = 18% of lifetime PnL) + pair-completion lock; residual = hedging noise, not alpha.
```
**Why our replications lost:** both used TAKER fills at the ask. His entire edge ≈ buying at the bid
instead of the ask (1–2¢/fill × volume ≈ his $24.79/slug) + rebate. There is NO signal to extract —
"EV layering / Chainlink CVD fusion" in the article is marketing for "I quote everywhere and watch the
oracle to manage quotes."

## 4. Consequences for us
- The ML hunt is CLOSED with a definitive negative on signal: nothing to port into our sleeves.
- Replicating him = running a passive CLOB maker (both-token bids, full window, hold-to-redeem).
  ⚠️ Our banked rule "maker dead on Poly" came from the 06-11 sims (scalp maker-ENTRY + late favored
  bids, conservative price-through fills = 0%). His tape PROVES resting-bid fills happen at scale in
  THIS regime (both tokens, all window) — offline we structurally cannot model queue position, so the
  only honest test is a **live micro-maker probe (~$50–100, $1 bids both tokens, 1 week)** measuring
  realized fill rate + spread capture vs his benchmark (~82 fills/mkt, +3.1%/slug on deployed).
- His moat is operational (queue position, uptime, requoting latency — the article's CPU section),
  not informational. Competing means competing on infrastructure, in a niche currently paying the
  operator ~$230/day lifetime (~$590/day recent).
- GROUND-TRUTH note: chain block-time limits fill-price classification precision (±2s); the maker
  conclusion rests on the triangulation (rebates + price-vs-book + zero-signal + his own article).

Artifacts: `cache/0xb945945d/{fill_tape,token_lookup_ext,ml_features}.parquet`,
scripts `_b945_build_tape.py`, `_b945_ml_decode.py`, `_b945_side_decode.py`.
Prior: `PAIRLOCK_BT_RESULTS_2026_06_12.md` (both replication backtests), `SPEC_B945_EVLAYER_PAIRLOCK_2026_06_11.md`.
