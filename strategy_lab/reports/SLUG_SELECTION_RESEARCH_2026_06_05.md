# Slug-Selection Research + Ranked Experiment Plan (2026-06-05)

Deep-research harness (107 agents, 25 sources, 110 claims → 17 confirmed / 8 killed) + internal oracle EDA.
Full raw report: workflow `wf_e46a900a-b92`. EDA: `oracle_determinism_eda_2026_06_05.py`.

## Headline
Literature confirms our prior: **direction prediction is dead; the slug-selection edge is execution/structure/
settlement-mechanics.** Strongest leads: (1) **oracle-determinism near settle**, (2) **cross-token price-sum
deviation**, (3) **liquidity is an INVERTED efficiency proxy**, (4) **reversal-state imbalance** (maker is
adversely selected — matches our maker-entry death), (5) **within-window/time-of-day timing**, (6) a
**cross-slug structural calibration** ranker (the F2-selector hunt). Everything scored with CPCV + Deflated Sharpe.

## CONFIRMED signals (cited)
- **Liquidity ≠ efficiency, often inverted** (Tetlock 2008, JFM): liquid binaries are *no better* calibrated and
  show *worse* resolution; informed flow harvests naive flow *when liquidity is high*. → high-volume slugs not safer.
- **Cross-token price-sum deviation** `|up_vwap+dn_vwap−1|` is a direct, direction-free mispricing flag (arXiv
  2508.03474; IMDEA >$40M PM arb). We already observe ~1.30 on real books. (FILTER to test net-of-fee, NOT free arb.)
- **Taker picks off stale makers; makers are adversely selected; viable maker = CONTRARIAN to imbalance**
  (Tetlock; Albers 2502.18625 live Binance perp; Bieganowski 2602.00776 flash-crash). Independently corroborates
  our maker-entry-dies finding. "Reversal states" (imbalance falsely predicts) = where contrarian pays.
- **Within-window timing matters** — crypto book liquidity has strong intraday/session patterns (MDPI JRFM 2025;
  "crypto trades at tea time"). Supports a UTC-hour + offset-in-window selector.
- **Chainlink settle oracle is a separate real-time RTDS channel** (`crypto_prices_chainlink`) distinct from the
  Binance signal feed (Polymarket dev docs) → oracle-vs-poly divergence selector near settle. 🔴 **load-bearing
  caveat:** RTDS-chainlink WS is lagged 100–500ms + ~1s gaps and is **NOT proven identical to the on-chain settle
  print** — validate fidelity vs actual settle outcomes FIRST.
- **FLB is non-uniform & predictable from ex-ante structural attributes** (Green-Lee-Rothschild; Le 2026 292M
  trades): which slugs are mispriced is rankable from structure (horizon, trade-size mix, naive-flow share) —
  the SELECTION principle, not fading (our fills killed fading).
- **DSR rigor mandatory** (Bailey-LdP): every selector → CPCV + Deflated Sharpe disclosing N/var/T/skew-kurt.

## KILLED in verification (do NOT pursue)
- Naive **CEX-implied (log-normal) latency arb on stale poly price** — 0-3 refuted.
- **Accuracy-declines-toward-close** timing — 0-3.
- **Kalshi <10c-loses-60% as a side-selector** — 1-2. **Noise-trader-share overpricing** — 1-2. **Wider-spread =
  weaker signal** — 1-2. **Order-book-variation predictable** — 0-3. **UMA (not Chainlink)** — 0-3 (our Chainlink setup is correct).

## RANKED testable experiments
1. **Oracle-determinism settlement selector** ⭐ (partially scoped — `oracle_determinism_eda_2026_06_05.py`).
   EDA already shows **12–20% of slugs are decided by Chainlink ≥99.3% at T-30/60s** (|dist|≥15bp).
   Steps: (a) **validate RTDS-chainlink vs actual settle outcome** (the load-bearing fidelity gap); (b) join the
   poly price of the oracle-implied winner at T-30/60s; (c) edge if `poly_price < realized_acc` (poly lags oracle);
   (d) **L25 ask-walk fill test** (the killer for FLB/favorite — must pass here too) + DSR. Mechanism: structural
   settlement, not prediction = where our edge lives.
2. **Cross-token price-sum deviation selector.** Compute `|up_vwap+dn_vwap−1|` on $5/$25-walked vwaps (live
   `_compute_spread` def), bin slugs, simulate complete-set / single-leg entry with engine_v2 LiveMimicConfig
   (real fee + ask-walk), DSR. Net-of-fee filter, not free arb.
3. **Liquidity-inversion test on the exit-scalp** (cheap; reuse existing fire universe). Bin gated scalp fires by
   L25 depth + CLOB volume; does net edge concentrate in LOW-liquidity slugs (Tetlock) or need depth to fill?
4. **Reversal-state imbalance filter.** Build a "reversal" detector (L25 imbalance that falsely predicts next move);
   meta-label the exit-scalp by reversal vs non-reversal; does edge concentrate in reversal states? (Albers).
5. **Within-window / time-of-day selector.** Bucket scalp net edge by UTC hour × offset-in-window; confirm/refute
   F2's 22:00–02:00 + 9–10 UTC prior; require walk-forward stability.
6. **Cross-slug structural calibration ranker (the F2-selector hunt).** Rank which slugs are mispriced from ex-ante
   structure (horizon 5m/15m/1h, trade-size mix, small/round-lot share, age/volume); test OOS ranking vs realized
   mispricing with CPCV + DSR. Open Q: does this reduce F2's ~4%-of-slugs pattern to a known structural signal?

## Dominant caveat
External validity: nearly all microstructure/maker cites are CEX-perp or sports binaries, not PM cross-token
oracle-settled crypto up/down — transferable *mechanisms to test*, not facts. Re-verify the 0.07 winner-only fee
+ cross-token spread vs the live wallet before sizing (GROUND-TRUTH RULE).

## Files
- This report · `oracle_determinism_eda_2026_06_05.py` · raw research `wf_e46a900a-b92.output`
