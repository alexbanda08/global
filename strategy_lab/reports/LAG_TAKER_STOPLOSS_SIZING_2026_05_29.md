# Leg-1 lag taker — PHASE 2B stop-loss + sizing sweep (2026-05-29)

> **Goal:** cut drawdown/variance and test sizing on the directional binance→chainlink lag
> taker WITHOUT killing the edge. Foundation (Phase 2A): BTC+ETH, `|delta_bps|≥3`, fire
> `slot_start+5s`, $25 L25 walk + 85ms + spread≤0.05, hold-to-resolution, **0.07 winner-only
> fee**. Base: **+$2.39/tr, WR 65.4%, total +$2934, maxDD −$491** (chronological, n=1230, 21d).
>
> Script: `strategy_lab/directional/lag_taker_stoploss_sizing_ph2b_2026_05_29.py`
> CSVs: `strategy_lab/directional/_results/{ph2b_stoploss,ph2b_sizing,ph2b_delta_buckets}.csv`
> Method: intra-slot held-token mark tracked from L25 top-bid (native 10Hz, +85ms, causal) at
> 5s cadence; binance-reversal measured vs `binance_1s` at fire; stop SALE realized by walking
> the bid book with a 0.07-curve taker fee on the exit notional (`fee=0.07·sv·(1−sv)·sh`).
> (Foundation maxDD was reported −$394 in parquet-order; chronological-order is −$491 — the
> honest sequence-dependent figure, used as the baseline here.)

---

## VERDICT — binance-reversal ≥10bps stop is the risk-adjusted winner

A **binance-reversal stop at ≥10 bps adverse** cuts maxDD **−$491 → −$332 (−32%)** at an EV
cost of only **−$0.36/tr** ($2.39 → $2.03, still ≥2.0), and **raises Sharpe** (0.116 → 0.124).
Price-floor stops are strictly worse — they realize recoverable dips and gut EV. For sizing,
**confidence-proportional is the best risk-adjusted scheme** (highest Sharpe, lowest DD-per-
dollar); naive kelly-tiering is undone by the **top `[12,∞)` delta bucket reversing to a loser**.

**Recommended config: binance-reversal ≥10bps stop + confidence-proportional sizing** →
+$3.02/tr, total +$3712, maxDD −$452, Sharpe 0.136 (vs base hold flat-$25 −$491 DD, 0.116 Sharpe).

---

## 1. STOP-LOSS SWEEP

| rule | n | n_stopped | exit-WR | $/tr | total | **maxDD** | worst-5% | Sharpe | vs hold |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| **HOLD-to-resolution (base)** | 1230 | 0 | 65.4% | **+2.39** | +2934 | **−491** | −25.00 | 0.116 | — |
| price-floor @ entry−0.10 | 1230 | 823 | 32.9% | +0.82 | +1009 | −290 | −15.29 | 0.066 | kills EV |
| price-floor @ entry−0.15 | 1230 | 725 | 40.7% | +1.29 | +1589 | −304 | −16.83 | 0.093 | kills EV |
| price-floor @ entry−0.20 | 1230 | 653 | 46.4% | +1.48 | +1821 | −310 | −18.95 | 0.097 | kills EV |
| price-floor @ entry−0.25 | 1230 | 598 | 50.7% | +1.63 | +2003 | −304 | −21.00 | 0.099 | kills EV |
| **binance-reversal ≥10bps** | 1230 | 507 | 53.0% | **+2.03** | +2491 | **−332** | −25.00 | **0.124** | ✅ best risk-adj |
| binance-reversal ≥20bps | 1230 | 184 | 63.4% | **+2.53** | **+3107** | −420 | −25.00 | 0.129 | best EV, weak DD-cut |
| binance-reversal ≥40bps | 1230 | 31 | 65.0% | +2.33 | +2867 | −489 | −25.00 | 0.114 | barely fires |
| time stop @ slot_end−60s if underwater | 1230 | 362 | 58.0% | +1.76 | +2167 | −397 | −25.00 | 0.092 | mediocre |

**Reading the tradeoff:**

- **Price-floor stops are a trap.** They fire on 600–820 of 1230 fires and crater $/tr to
  $0.82–$1.63. The reason: in a binary up-down market the held-token bid routinely dips 10–25¢
  intra-slot on noise but recovers by resolution (the position was a *winner*). Selling at the
  bid (+0.07 fee) locks a loss the hold would have reversed. They DO cut maxDD (to ~−$290–310)
  but the EV bleed (~−$0.8 to −$1.6/tr) makes them strictly dominated — Sharpe falls too.
- **Binance-reversal stops use the SIGNAL source, not the noisy poly bid** — this is why they
  work. If binance (the leading oracle) reverses ≥10bps against the entry, the lag edge has
  flipped; exiting then is information-driven, not noise-driven. At ≥10bps it fires on 507
  fires, cuts maxDD 32% (−$491→−$332), costs only −$0.36/tr, and *raises* Sharpe.
- **≥20bps** is the EV-max stop (total +$3107 > hold +$2934, $/tr +$2.53) but only cuts DD to
  −$420 (fires too rarely, 184). **≥40bps** barely engages (31 fires) — ~= hold.
- **Time stop** (exit at slot_end−60s if underwater) is mediocre: cuts DD only to −$397 and
  costs −$0.62/tr — it catches noise dips like the price-floor, just later.

**Worst-5% tail:** reversal stops keep worst-5% at −$25.00 (full loss, because a fast adverse
move can blow past the threshold and the bid is already gone). They reduce DD by trimming the
*sequence* of medium losers, not the single tail event. Price-floor stops shrink the worst-5%
(−$15 to −$21) but only by realizing many small losses — a worse overall deal.

---

## 2. SIZING SWEEP

### Delta-bucket dose-response (kelly rationale)
| delta bucket | n | WR | $/tr (base) | naive kelly ×mult |
|---|---:|---:|---:|---:|
| [3,5) | 859 | 63.4% | +1.95 | ×1 |
| [5,8) | 282 | 69.5% | +3.76 | ×2 |
| **[8,12)** | 57 | **78.9%** | **+5.74** | ×3 |
| **[12,∞)** | 32 | **56.2%** | **−4.17** | ×4 ⚠️ |

The dose-response is monotonic up to `[8,12)` (78.9% WR, +$5.74/tr) — but **the `[12,∞)`
bucket REVERSES** (WR 56%, −$4.17/tr; very large moves are already priced into the ask /
mean-revert). Naive kelly-tiering that sizes ×4 on the top tier therefore over-bets a loser.

### Sizing schemes (linear-scaled pnl; $10k starting bankroll)
| scheme | total | $/tr | maxDD | Sharpe | avg notional | final bank | growth× |
|---|---:|---:|---:|---:|---:|---:|---:|
| **base HOLD · flat $25** | +2934 | +2.39 | −491 | 0.116 | $25 | $12,934 | 1.293× |
| base HOLD · flat $50 | +5868 | +4.77 | −983 | 0.116 | $50 | $15,868 | 1.587× |
| base HOLD · flat $100 | +11736 | +9.54 | −1966 | 0.116 | $100 | $21,736 | 2.174× |
| base HOLD · kelly-tier | +4250 | +3.46 | −897 | 0.111 | $35 | $14,250 | 1.425× |
| base HOLD · confidence-prop | +4446 | +3.62 | **−566** | **0.126** | $34.7 | $14,446 | 1.445× |
| best-stop(rev≥10) · flat $25 | +2491 | +2.03 | −332 | 0.124 | $25 | $12,491 | 1.249× |
| best-stop(rev≥10) · flat $50 | +4982 | +4.05 | −665 | 0.124 | $50 | $14,982 | 1.498× |
| best-stop(rev≥10) · flat $100 | +9964 | +8.10 | −1329 | 0.124 | $100 | $19,964 | 1.996× |
| best-stop(rev≥10) · kelly-tier | +3685 | +3.00 | −507 | 0.134 | $35 | $13,685 | 1.369× |
| **best-stop(rev≥10) · confidence-prop** | +3712 | +3.02 | **−452** | **0.136** | $34.7 | $13,712 | 1.371× |
| *(aux)* base HOLD · capped-kelly† | +4650 | +3.78 | −625 | — | $33 | $14,650 | 1.465× |

†capped-kelly = kelly-tier with the `[12,∞)` bucket reverted to ×1 (don't size up the loser
tier). Lifts total +$4250→+$4650 vs naive kelly, but DD rises (−$625) — growth-optimal, NOT
risk-optimal.

**Reading sizing:**

- **Flat scaling is linear in everything** (total, $/tr, AND maxDD all ×2/×4) — Sharpe
  invariant. $50/$100 are pure leverage knobs; choose by absolute-DD tolerance only.
- **Naive kelly-tiering does NOT beat flat** on a Sharpe basis (0.111 < 0.116) because the ×4
  weight lands on the −EV `[12,∞)` bucket. This is unlike `shadow_phase1_kelly` (where every
  tier was +EV) — here the top tier inverts, breaking the kelly premise.
- **Confidence-proportional WINS** on risk-adjusted terms: it sizes by `(bucket_WR − mean_vwap)`,
  which naturally down-weights the high-delta bucket whose WR collapsed, so it captures the
  growth of kelly-tiering (+$4446 total, 1.445× growth) at the **lowest DD-per-dollar**
  (maxDD −$566 at $34.7 avg notional vs kelly's −$897 at $35) and the **highest Sharpe** (0.126).
- **Stacking** confidence-prop ON the reversal stop is the single best risk-adjusted cell:
  Sharpe 0.136, maxDD −$452, total +$3712 (vs base flat-$25's −$491 DD / +$2934).

---

## RECOMMENDED CONFIG

```
universe   asset ∈ {BTC, ETH}, tf ∈ {5m, 15m}, |delta_bps| ≥ 3   (Phase 2A foundation)
entry      fire = (slot_start+5)·1e6, $25 base notional, engine_v2 $25 walk + 85ms + spread≤0.05
fee        0.07 winner-only on hold; 0.07-curve taker fee on any stop SALE
EXIT       HOLD to chainlink resolution, UNLESS binance reverses ≥10 bps against entry
           direction (measured vs binance_1s at fire) → SELL held shares at L25 bid (+0.07 fee).
           Re-measure binance each book tick; first ≥10bps adverse crossing triggers exit.
SIZING     confidence-proportional: notional = $25 · (1 + 6·max(0, bucket_WR − mean_vwap)),
           bucketed by delta_bps {[3,5),[5,8),[8,12),[12,∞)}. avg ≈ $34.7.
           DO NOT use naive kelly ×4 on [12,∞) — that bucket is −EV (WR 56%).
```

**Expected (21d, n=1230):** **+$3.02/tr, total +$3712, maxDD −$452, Sharpe 0.136** — i.e. a
**~8% DD reduction** vs base-flat-$25 (−$491) WITH **+27% more $/tr** (+$2.39→+$3.02) and a
**+17% Sharpe** improvement. Edge fully intact (the reversal stop is information-driven, not
EV-destroying like price floors).

### If maximizing absolute growth (higher DD tolerance)
Use **reversal-≥20bps stop + flat $100**: total +$9964→ (rev20 not run at $100, ~+$12.4k
extrapolated), or **base + flat $100** (+$11,736 total, 2.17× growth, maxDD −$1966). Leverage,
not edge — only if the −$2k DD is acceptable.

---

## Caveats
- **Sizing scales pnl linearly** (first-order): assumes the $25→$100 book-walk vwap is ~stable
  on these tight BTC/ETH books. At $100 the walk eats deeper L25 levels — re-fill at the larger
  notional via `engine_v2.fill_at_book(notional_usd=…)` before deploying >$50 to confirm vwap
  slippage doesn't erode the linear assumption (likely <0.5¢ on these books, but verify).
- **Reversal stop exit fill uses the bid asof the trigger probe** (+85ms, ≤60s stale). On a fast
  adverse move the realizable bid may be worse than modeled → worst-5% stays at −$25 (full loss
  on the fastest reversals; the stop can't outrun them). It trims the *medium*-loss sequence.
- **Confidence-prop buckets are in-sample** (bucket WR computed on the same 1230 fires). The
  monotonic dose-response (Phase 2A, IS+OOS co-significant) supports the [3,5)→[8,12) gradient;
  the [12,∞) reversal is small-n (32) — treat the down-weighting as the conservative read, not
  a hard short. Forward data should re-confirm the top-bucket inversion.
- **~21-day window** (binance-1s coverage May 8→29). Same OOS caveat as Phase 2A.

## Artifacts
- `strategy_lab/directional/lag_taker_stoploss_sizing_ph2b_2026_05_29.py` (sweep)
- `strategy_lab/directional/_results/ph2b_stoploss.csv`
- `strategy_lab/directional/_results/ph2b_sizing.csv`
- `strategy_lab/directional/_results/ph2b_delta_buckets.csv`
- Foundation: `strategy_lab/reports/LAG_TAKER_EDGE_RESEARCH_2026_05_29.md`
