# Strategy Landscape + Whitespace — what's done, what's deployed, what to start (2026-05-31)

Combines the full tried-strategy catalog (`STRATEGY_CATALOG_2026_05_31.md`) + the live sleeve
inventory (`SLEEVE_INVENTORY_VPS3_2026_05_31.md`). Answers: what can we still pursue.

## State in one screen
- **~164 sleeves deployed on VPS3, ALL paper/shadow, zero live capital.** Engine bugs from the
  earlier audit (pyarrow / S6 / overlay telemetry) are now FIXED.
- **The directional-signal space is exhaustively mapped and mostly CLOSED.** One validated edge:
  **oracle-lag taker (clbasis_rel / FAST_TAKER_LAGV2)** — and it is ALREADY DEPLOYED (4 shadow sleeves,
  firing). Everything else directional is dead or fragile.
- **The maker / pair-arb / merge-arb / queue space is CLOSED** (survivorship-corrected negative; the live
  `fast_taker_a25_merge_*` shadow sleeves are bleeding −$2.6k/−$7.6k paper → confirms it).
- So "more wallet decoding / more directional signals / more maker-arb variants" = **diminishing-to-zero**.
  The real whitespace is (A) AMPLIFY the one validated edge, (B) a couple of genuinely-orthogonal untested
  signals, (C) system-level (sizing/fleet/live-promotion).

## Tried → verdict (condensed)
| bucket | verdict |
|---|---|
| oracle-lag taker (clbasis/LAGV2) btc-5m | **VALIDATED + DEPLOYED (shadow)** |
| oracle-lag eth-15m off60 | PARTIAL/FRAGILE (paper) |
| momentum / RSI-MACD / favorite / underdog / flow / fade / multivariate-ML | DEAD (priced-out) |
| maker pair-arb / no-chase merge-arb / maker queue-latency / complete-set lock / sum<$1 atomic | CLOSED (negative, survivorship-corrected) |
| oracle-snipe late-slot taker | INFRA-GATED (needs CL WS + maker; taker-version −EV by construction) |
| Cyclops S7 X1 composite | VALIDATED, shadow-deployed (n=36, fragile) |

## Deployed sleeves — current paper PnL signal (7d)
- **LAGV2 (the validated edge): firing but THIN** — 1–7 resolutions/7d/sleeve, net ~flat-to-slightly-neg
  (btc_5m −$175, btc_15m −$25, eth_5m −$7, eth_15m +$42). Very selective gates → low n → not yet
  conclusive live. **Action: let it accumulate; it's the one thing worth watching.**
- Paper PnL leaders: `btc_15m_momo_HOLD_f7` +$236, `eth_15m_momo_v2_HOLD_f7` +$235 — but these are the
  priced-out momentum family (paper-positive on a short window = the same illusion the gates reject; do NOT
  promote without the full battery).
- Maker-merge sleeves bleeding (−$2.6k/−$7.6k) — consistent with maker-arb CLOSED.

## ✅ TESTED 2026-05-31 (both negative — signal space further exhausted)
- **A1 Multi-venue lead-lag → NO UPGRADE.** Binance-1s already leads Chainlink (+2s, corr 0.577) and is the
  best leg. HL-perp/OKX are only 1MIN bars → coarse, fat-tailed, fail gates. Consensus just filters binance
  fires down (−n, −PnL, no WR gain). Keep binance-1s. (`MULTIVENUE_LEADLAG_2026_05_31.md`.) Re-testable ONLY
  if HL **1s tick** data is collected (perp-lead hypothesis untestable at 1MIN).
- **B5 BSM/N(d2) fair-value → PRICED-OUT.** At 5–15min horizons N(d2) collapses to sign(spot−strike) (σ√τ
  tiny) = px_vs_strike momentum in disguise (72–82% agree); 19/20 cells fail G1; lone pass is a SOL-trend
  artifact. The CLOB price is a better estimator than BSM. (`BSM_FAIRVALUE_2026_05_31.md`.)

**Conclusion after these two: the search for a NEW directional signal is exhausted.** Every fresh idea
(multi-venue, BSM, momentum, flow, ML, favorite, fade) lands on the same wall — the CLOB price is efficient.
The remaining value is NOT more signal hunting; it is (1) optimally CONFIGURING + SIZING + PROMOTING the one
validated edge (oracle-lag/LAGV2), and (2) INFRA that amplifies it (lower-latency CL feed, HL 1s ticks).

## 🟢 WHITESPACE — re-ranked after 2026-05-31 results

### A. Amplify the ONE validated edge (oracle-lag) — highest EV, data on hand
1. **Multi-venue lead-lag** ⭐ — we only used **Binance spot vs Chainlink**. The collector already has
   Coinbase/Kraken/OKX spot + Hyperliquid perp on VPS3. Test whether a FASTER venue (or perp premium / a
   cross-venue consensus) leads Chainlink EARLIER/STRONGER than binance spot → a bigger, earlier lag signal
   feeding LAGV2. Pure backtest with data we already have. **Could materially lift the only edge we have.**
2. **Chainlink Data Streams WS direct** — the lag edge is latency-bound; we read CL via the RTDS DB. Wiring
   the CL Data Streams WS feed directly on Ireland = lower latency = larger captured lag. Infra hardening
   that directly grows the validated edge. (Infra-gated: need CL DS API access.)
3. **LAGV2 broad-band re-validation under harsh costs** — confirm the 22/day 3–12bps band (vs my 2/day
   tail) passes HIGH-fee + $0.01-tx + block-bootstrap + Bonferroni with its refinement gates. Decides
   whether to run the 22/day or the 2/day version live. (Backtest, ready now.)
4. **HL liquidation-cascade conditioning** — do LAGV2 fires immediately after a large Hyperliquid liq
   cascade have higher WR (forced-flow move the oracle hasn't caught)? The v9 sleeves attempted this but
   were data-starved. Needs an HL liqs refresh (stale at May-27), then a conditioned-WR backtest.

### B. Orthogonal untested signal (new angle, not oracle-lag)
5. **BSM / N(d2) fair-value** ⭐ — the up-down is literally a binary option. Compute theoretical win-prob
   from CL spot + realized/implied vol + time-to-expiry (BSM N(d2)); trade when the CLOB price deviates
   from fair by > threshold. Tier-A-promising in research, NEVER backtested. A genuinely different signal
   from oracle-lag — the one untested directional idea with theoretical backing.

### C. System-level (turn the edge into a business)
6. **Confidence-proportional sizing** (LAGV2 v2, deferred) — size by (bucket-WR − entry_px). Beats flat
   + naive Kelly in the spec; lifts $/day on the same edge. Backtest + add to the sleeve.
7. **Live-promotion path** — define the go/no-go to move LAGV2 from shadow to small live capital
   (n≥200 filled, WR≥60%, rolling-WR not decaying), per the spec's acceptance criteria.
8. **More cells/assets** — XRP/DOGE up-down + 1h/1m TFs were never scanned for the oracle-lag edge.

### Explicitly DO NOT retry (mapped dead-ends)
momentum/favorite/underdog/flow/fade/multivariate-ML (priced-out); maker pair-arb / merge-arb / no-chase /
queue-latency / complete-set lock / sum<$1 atomic (negative, survivorship-corrected); generic wallet
decoding (buckets saturated — all roads lead to oracle-lag or execution edges we can't reproduce).

## Recommended START order
1. **Multi-venue lead-lag backtest** (A1) — data on hand, directly amplifies the only edge. Do first.
2. **BSM/N(d2) fair-value backtest** (B5) — the one orthogonal untested directional signal.
3. **LAGV2 broad-band harsh-cost re-validation** (A3) — pick the live config (22/day vs 2/day).
4. Then: HL-cascade conditioning (needs refresh), confidence sizing, live-promotion gate.
