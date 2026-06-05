# Wallet-Hunt Synthesis — 2026-05-29 (maker pair-arb convergence + oracle-snipe class)

> 🚨 **CORRECTION (post-review, 2026-05-29).** The "deploy maker pair-arb" and
> "deploy cl_basis directional" recommendations below are a **regression** — they
> contradict the two authoritative capstones from the day before and must NOT be
> acted on as written. Reconciliation:
>
> 1. **`EFFICIENT_MARKET_FINDING_2026_05_28.md`** proved, with an OOS multivariate
>    model (n_test=2038), that the Polymarket up-down price is a near-optimal
>    outcome estimator — **no signal, including cl_basis, beats it out-of-sample.**
>    The profitable wallets' edge is **EXECUTION (maker spread capture + fast fills
>    + favorite base-rate), NOT prediction.** cl_basis extreme-divergence btc-5m is
>    the lone gate-passer — a thin ~2/day tail **the user already passed on.** So
>    the twins (0x3c58/0xd9dea) "cl_basis directional" edge below is most likely
>    execution+base-rate, not reproducible alpha → do NOT deploy as a directional taker.
> 2. **`MAKER_ARB_CENSORING_REVERSAL_2026_05_28.md`** proved the maker-arb edge was
>    **survivorship bias**: settle the right-censored directional losers and every
>    sleeve is net-negative — **even fully-paired slugs averaged −$3.93/slug**
>    (pair-completion overpay). The per-wallet "pair_sum<1 → +$X risk-free" numbers
>    below are the **matched-pair-only measure**, i.e. the SAME biased measure that
>    reversal corrected — they do NOT settle the wallet's directional residual.
>
> **Honest takeaway:** this hunt did not find a new deployable edge; it
> re-confirmed the efficient-market capstone. The ONE variant not yet disproven was
> a strict **no-chase merge-arb maker** (rest both sides; merge only naturally-matched
> pairs; NEVER chase the second leg; flatten the stuck leg → carry ~zero directional
> residual).
>
> **✅ NOW TESTED — and it FAILS.** `NOCHASE_MERGEARB_VERDICT_2026_05_29.md`: local
> backtest on the longer window (May 20→29, **n=10,565**, native-10Hz L25 + chainlink,
> uncensored settle) → negative on EVERY budget (0.90/0.93/0.94/0.97), pooled
> pnl_flatten ≈ −$0.032/slug, **bootstrap 95% CI entirely below zero.** No-chase flatten
> ≈ hold (selling the stuck leg back at the bid doesn't help — adverse selection on the
> 0.50 fill). And that's generous (assumes instant maker fills + rebate income that
> CLAUDE.md says doesn't accrue). **The maker-arb / pair-arb line is now CLOSED.** Do
> not reopen without a genuinely new ingredient (real queue/latency edge or a
> reproducible directional selection edge — we have neither). Everything below is the
> raw decode evidence; read it through this correction.

Harvested today's + 5d btc-5m/btc-15m/sol-15m/eth-15m markets (conditionId-correct connector),
scored ~30k participants by lb profit, decoded ~12 profitable wallets across 6 parallel agents.
The buckets have now CONVERGED. Per-wallet reports: `DECODE_*_2026_05_29.md`.

## The reproducible edge: MAKER PAIR-ARB at slot-open (confirmed across 6+ independent wallets)
**Mechanic:** at slot-open the Up/Down book is widest. Post LIMIT bids on BOTH sides; get filled such
that `pair_sum = avg_Up_px + avg_Down_px < 1.0`; then MERGE the matched pair (or hold to redeem) for a
guaranteed $1 → **risk-free profit = matched_qty × (1 − pair_sum)** per pair. Edge scales with velocity.

| wallet | cell | pair_sum (median) | %<$1 | evidence | fleet |
|---|---|---|---|---|---|
| 0xc387c2a4 | btc-5m | **0.814** | 72% | +$4.8k/3.76d paired leg | — |
| 0x606345ea | eth-15m | 0.910 | 66% | 1,528 MERGE, +$1,191/day risk-free | — |
| 0x251c1a28 | btc-5m | 0.950 | 38% | $20 TWAP ladder, 95.6% paired | **F1** (0xf70da97) |
| 0xfcdc071d | btc-15m | 0.948 | — | 2,313 MERGE, $7.8k MAKER_REBATE | — |
| 0xa6896d11 | btc-5m | 0.997 (20% <0.95) | — | ~$12k/day pair velocity, $5M vol/6d | **F2** (0x3a9418) |
| 0x951bd740 | btc-5m | 1.004 | — | paired + directional overlay | **F2** |

Counter-example (NOT arb): PBot-3 0x74a2b82f pair_sum **1.14** → loses on pairs (it's a directional maker).
The discriminator is pair_sum<1 via genuine MAKER fills at slot-open, NOT taker crossing.
**⚠️ NOT a clean deploy target** (see correction banner). These pair_sum medians are
matched-pair-only and ignore each wallet's directional residual — the same censored
measure the 2026-05-28 reversal corrected. The wallets ARE net-profitable lifetime,
but our own attempt to run this (the maker-arb sleeves) went net-negative on
pair-completion overpay (even fully-paired slugs −$3.93). The only path forward is the
**strict no-chase variant**, shadow-validated with uncensored residual settlement.

## NEW class discovered: CHAINLINK ORACLE SNIPE (late-slot)
**Mechanic:** read the Chainlink RTDS oracle in the final 30–90s of the slot — it predicts the outcome
~87% at T−30s before the CLOB price fully converges. Buy the near-certain winner (or rest a maker limit at
~0.985) and collect the small gap to $1.
- 0xa2a0519b: buys winner at 0.986 in last 30s, CL@T−30s 87% accurate, EV ≈ +$2.85/slug. 4 cells.
  Reproducible IF resting maker @ ~0.985 + CL RTDS WS feed (~$168k/day exposure). NOT as taker.
- 0x2855555a: same snipe, earlier window (~84s), exits via secondary sell (hold-to-res is thin).
This is distinct from cl_basis-divergence; it's an oracle-LATENCY snipe near settlement. Connects to the
"late near-resolved" profile we'd dismissed — the edge is real only with maker fills + the live CL feed.

## cl_basis DIRECTIONAL (the gated survivor, thin)
Extreme binance-vs-chainlink divergence → buy the leading side. The ONLY directional rule that passed all
5 gates (`clbasis_rel-btc-5m`, +$6.31/trade, plateau 0.978). Confirmed in: twins 0x3c58ef42 + 0xd9dea316
(+20pp WR, ~2 fires/day, UTC 0–8), and as the direction overlay in 0xa6896d11 / 0x951bd740 (low-vol wins).
Real but low-frequency.

## Priced-out / NOT reproducible (correctly rejected)
- 0x5e2b9261 (favorite-buyer momentum, slug-selector unexplained), 0xa5b17799 (cross-asset momentum, WR
  decaying 86%→66%, F1 sub via relay 0xf3cfb6a6), 0xdd3c4d67 (contrarian underdog, net-negative variance),
  0x45fb42d0 (stale-ask sweep illusion — $5.5k of $8.1k from 7 trades @ px 0.01), 0x2f32a09d (late-slot
  taker, net −$77), 0x2855555a hold-to-res leg. All consistent with the efficient-market capstone.

## Fleet map
- **F1 treasury `0xf70da97812cb96acdf810712aa562db8dfa3dbef`** → 0x251c1a28 (pair-arb), 0xa5b17799 (momentum,
  via relay 0xf3cfb6a6). The known $254k/day HFT cluster.
- **F2 treasury `0x3a9418...`** → 0xa6896d11 + 0x951bd740 + 0xdd3c4d67 (mixed fleet: pair-arb + cl_basis
  directional + variance), all created 2026-05-23.
- ⚠️ **CAUTION**: the twin-decode agent flagged `0xe111180000d2663c0091e4f400237545b87b996b` as a "19-wallet
  fleet funder" — this is almost certainly the **Polymarket relay/deposit contract** (it's in our
  harvest EXCLUDE list; every proxy is funded through it), NOT a fleet operator. Treat that "fleet" claim
  as a false positive. Real fleets are F1/F2 above.

## Reproducibility ranking → next step  (REVISED per correction banner)
1. **No-chase merge-arb maker (the ONLY undisproven variant)** — rest deep limit bids
   on BOTH sides at slot-open; merge ONLY naturally-matched pairs; NEVER chase the
   second leg (cancel the unfilled leg at slot-mid). This is the one variant the
   censoring reversal left open ("force fully-paired inventory, zero directional
   residual → reduces to pure merge-arb"). The profitable wallets' 0.1s FIFO gap
   supports it. **Test:** rerun the V2/convergence-cancel sleeves on the now-longer
   canonical window (reversal only had ~1.5d of V2 data), tighten sum_bids<0.93,
   settle residual uncensored against chainlink. Confirm `acc_h_v2_eth_15m` (+$0.15,
   n=32) holds positive with more n. **SHADOW only until a CI clears zero.**
2. ~~cl_basis directional~~ — **DO NOT deploy.** Efficient-market capstone shows it
   doesn't beat price OOS; it's the thin tail the user already passed on. The twins'
   apparent edge is execution+base-rate, not reproducible alpha.
3. ~~Oracle snipe~~ — unproven on full PnL (matched/snipe-only measure); infra-heavy;
   same execution-vs-prediction caveat. Park.
4. Everything else (momentum/favorite/underdog) — priced-out, do not deploy.

**Bottom line:** the wallet hunt produced a NEGATIVE result — no new deployable
directional or naive-pair edge. The single honest lever is execution quality via the
no-chase merge-arb maker, and even that is breakeven-to-marginal in shadow today.

## Artifacts
- Harvest: `_harvest_today_4cells_v2`, `_harvest_5d_4cells_v3` (+ csvs); 30k participants scored.
- Decodes: `DECODE_{3c58_d9dea_twins, 251c_c387_btc5m, 5e2b_fcdc_multicell, highfreq_makers, bigbtc5m, multicell_trio}_2026_05_29.md`.
- Priors: `EFFICIENT_MARKET_FINDING_2026_05_28.md`, `BATCH_3WAY_SYNTHESIS_2026_05_29.md`.
