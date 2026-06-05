# Favorite-Longshot Edge on Polymarket Up/Down — REAL IN PRINT-SPACE, DIES ON FILLS

**Date:** 2026-06-04 · Spun out of the F2 fade follow-up (operator's "fade the dislocation" instinct).
**Scripts:** `favorite_longshot_2026_06_04.py` (print calibration) · `favorite_fill_revalidate_2026_06_04.py` (L25 fills)
**FINAL VERDICT:** The favorite-longshot bias is **real and well-powered in trade-PRINT space** (+0.5–1.0%/share,
slug-block CI excludes 0, millions of trades), **but it is an EXECUTION MIRAGE**: re-tested on L25 with realistic
ask-walk fills (engine_v2 LiveMimicConfig, $25, 85ms, 0.07 fee), every cell's slug-block CI **includes 0**
(best +$0.098/tr, CI [−0.48,+0.63]). You can't buy at the print — you walk the ask (entry→~0.92) and the thin
edge evaporates. The cross-token spread was NOT the killer (tight near settlement); slippage + variance is.
**Not deployable.** Print≠fill, just as WR≠edge. (Original print-space analysis retained below.)

## Method
- Whole BTC+ETH+SOL **trade tape** (50.4M buy-trades on resolved slugs). Each buy = pay `price` now, receive
  $1 iff that token wins (causal — `outcome` resolves later). `win = (trade.outcome == resolution.outcome)`.
- Per-share PnL, real Polymarket fee (winner-only 0.07 curve): `won → (1-p)(1-0.07p) ; lost → -p`.
- Significance via **slug-block bootstrap** (resample slugs, not trades — one outcome event per slug; trades
  within a slug are not independent). DSR was computed but is **mis-specified here** (treats per-trade as daily);
  the slug-block CI is the correct test.

## Calibration (classic favorite-longshot shape)
- **Longshots underdeliver**: p<0.10 realized 0.033 vs price 0.042 (BTC) — overpriced, lose to buy.
- **Mid (0.40–0.60): significantly negative** after fee (CI [−0.0022,−0.0003]) — pure fee drag, no edge.
- **Favorites overdeliver**: high-price realized > price (BTC 0.85→0.864, 0.74→0.759). Underpriced.
- Pooled tradeable buckets (slug-block CI):
  - longshots p<0.40: EV −0.0036 (CI [−0.0073,+0.0001])
  - mid 0.40–0.60: EV −0.0012 (CI [−0.0022,−0.0003]) — sig negative
  - favorites p≥0.60: EV +0.0018 (CI [−0.0011,+0.0047]) — positive, ns
  - **strong fav p≥0.75: EV +0.00348 (CI [+0.00089,+0.00605]) — sig positive**

## The tradeable structure — edge vs time-to-settlement (p≥0.75)
| ttl to settle | n trades | slugs | wr | price | EV/share | slug-block CI |
|---|---|---|---|---|---|---|
| 0–15s   | 1.89M | 22,324 | 0.930 | 0.940 | **−0.0132** | [−0.0166,−0.0098] |
| 15–30s  | 1.32M | 24,291 | 0.947 | 0.933 | **+0.0102** | [+0.0067,+0.0136] |
| 30–60s  | 2.46M | 30,415 | 0.943 | 0.929 | **+0.0095** | [+0.0063,+0.0126] |
| 60–120s | 3.68M | 34,469 | 0.925 | 0.915 | **+0.0053** | [+0.0017,+0.0088] |
| 120–300s| 5.27M | 35,491 | 0.877 | 0.867 | +0.0038 | [−0.0010,+0.0087] |
| 300s+   | 1.53M |  9,466 | 0.868 | 0.858 | +0.0036 | [−0.0045,+0.0119] |

- **Edge lives in the 15–120s convergence window** (CI excludes 0; strongest 15–60s ≈ +1%/bet). The favorite
  is slightly *underpriced* there — the book hasn't fully converged to the ~94% realized rate.
- **Last 15s is NEGATIVE** (CI excludes 0): the market *overpays* for near-certainty. Do not chase.
- **>120s: washes out** (CI includes 0) — too early, outcome genuinely uncertain.

## Why this is different from everything else killed this session
It is a **price-level/microstructure convergence inefficiency**, not a predictive/selection signal. It is
well-powered (millions of trades, 30k+ independent slug-events), declustered, causal, and survives slug-block
bootstrap on the favorite side in a specific time window. The favorite-longshot bias is a documented
prediction-market phenomenon; here it is measurable and (apparently) tradeable in the 15–120s band.

## Caveats before any capital (the real gates)
1. **Trade-print ≠ achievable fill.** Prices here are executed prints; a live buy pays the **L25 ask** (worse).
   The CLAUDE.md cross-token-spread warning (live cross-token spreads ~31% on V5) could erase a 0.5–1% edge.
   → Re-run on `load_orderbook_l25_streaming` ask-walk at the 15–120s anchor, native 10Hz, with the live
   cross-token spread filter. This is the make-or-break test.
2. **Thin per-bet ROI** (~0.5–1% of a ~$0.93 stake) → needs volume + reliable fills; turnover-sensitive.
3. **Size/liquidity** at the favorite ask in the 15–120s window — confirm depth supports $5–25 stakes.
4. Confirm the fee is winner-only in the live engine (CLAUDE.md flag).

## Fill-realistic revalidation — DONE, edge does NOT survive (`favorite_fill_revalidate_2026_06_04.py`)
Sampled ~480 slugs/asset (1440 total), anchor ttl=60s, L25 native 10Hz, engine_v2 LiveMimicConfig ($25,
85ms latency, 0.07 winner-only fee), favorite = $25 ask-vwap ≥0.75, hold to resolution, live cross-token
spread `|up_vwap−(1−dn_vwap)|`.
| cell | n | won | fav_vwap | $/tr | slug CI |
|---|---|---|---|---|---|
| strong fav, no spread filter | 815 | 0.902 | 0.916 | **−0.552** | [−1.147,+0.021] |
| strong fav + xspread≤0.05 | 610 | 0.931 | 0.922 | +0.098 | [−0.480,+0.631] |
| strong fav + xspread≤0.02 | 265 | 0.917 | 0.918 | −0.189 | [−1.174,+0.739] |
| any fav≥0.60 + xspread≤0.05 | 713 | 0.893 | 0.886 | +0.008 | [−0.687,+0.709] |
- Cross-token spread near settlement is tight (BTC 0.015 / ETH 0.030 / SOL 0.059 median) — NOT the V5 killer.
- Killer = **ask-walk slippage** (entry pushed to ~0.92) + **hold-to-resolution variance** (−$25 losses vs ~$2 wins).
- Every CI includes 0 at n≈600–800. The print-space edge is not achievable at the touch.
- Could the edge exist at larger sample? CI ±0.5 on a ~+$0.1 point estimate → would need ~25× more slugs
  (~12k, heavy L25 load) to resolve, AND the slippage is structural (entry already at 0.92). Not worth the
  compute for a point estimate sitting on 0. **Closed as not-deployable.**

## Origin
- `F2_BASIS_OOS_2026_06_04.md` (fade addendum).

## Files
- `strategy_lab/autoresearch/favorite_longshot_2026_06_04.py`
- Inputs: canonical `load_trades` (BTC/ETH/SOL), `load_resolutions`. Window Apr 22 → Jun 4.
- Origin: `F2_BASIS_OOS_2026_06_04.md` (fade addendum).
