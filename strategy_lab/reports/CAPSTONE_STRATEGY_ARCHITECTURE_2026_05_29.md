# Capstone — Engine Audit, Validated Strategy Set, Architecture & Fleet Model (2026-05-29)

Four parallel engine audits (look-ahead / overfit / transaction-cost / survivorship), all engines
re-run under a harsher cost model (HIGH Polymarket taker fee `0.07·p·(1−p)` per share on every fill
**+ $0.01/trade gas**), uncensored chainlink settlement, validators stress-tested (block bootstrap +
Bonferroni). This is the bug-checked, cost-corrected ground truth.

## TL;DR
- **Engines are now sound.** 2 real bugs fixed in the core engine; directional pipeline clean
  (no look-ahead, no survivorship, not cherry-picked); maker engine's survivorship-fix is correct
  but its maker-fill assumption is over-optimistic (documented); validators verified.
- **Exactly ONE strategy survives everything: `clbasis_rel` on btc-5m** (extreme Binance-vs-Chainlink
  oracle divergence). Under HIGH fee + 1¢ tx: **+$5.95/trade, G4 CI-lo +$2.55 (IID) / +$4.26 (block),
  plateau 0.933, G3 p=0.0005 (survives Bonferroni over 66 cells).** ~2 fires/day. THE deployable edge.
- **Maker / pair-arb / merge-arb: CLOSED.** Uncensored + 1¢ tx + merge gas → −$0.066/slug (CI<0),
  ~2× worse than before; and the maker-fill assumption is generous, so reality is worse still.
- **Everything else** (momentum / favorite / underdog / fade / flow / oracle-snipe-as-taker):
  priced-out — dies under realistic costs. Confirms the efficient-market capstone.

## 1. Engine audit results (the trust foundation)
| engine | audit | bugs | verdict |
|---|---|---|---|
| `engine_v2.py` + fees/latency/book_walk | A | `min_book_events` never enforced (FIXED); `sell_pnl_partial` missing (FIXED); no look-ahead; book_walk clean | sound; **`RealisticConfig` added** (poly_taker_curve + 85ms latency + min_book_events=25 + **tx_cost_usd=0.01**) |
| `directional_scan.py` + `eval_strategies.py` | B | none — signals strictly causal asof; all fires settled uncensored vs chainlink; thresholds not cherry-picked | sound; added `settle_realistic()` + `--cost-model` |
| maker: `_nochase_mergearb_longwin`, `fast_full_backtest`, `poly_maker_fill_sim` | C | survivorship-fix CORRECT (local canonical settle); **maker-fill assumption over-optimistic (instant fill on touch, no queue)** | results trustworthy as an UPPER bound; real maker PnL ≤ reported |
| `cyclops/validate/*` (G2/G3/G4) | D | gates sound; IID bootstrap valid here (neg autocorr); minor stale FEE_RATE banner | trustworthy; block-bootstrap + Bonferroni confirm clbasis_rel |

EV sanity (vwap 0.69, hit 48%): Legacy −$7.70/trade → RealisticConfig −$8.14 (−$0.43 fee, −$0.01 tx).

## 2. Validated strategy set (post all corrections)

### ✅ DEPLOYABLE — `clbasis_rel` btc-5m (the one survivor)
- **Signal:** `cl_basis_bps = (binance_1s_px − chainlink_RTDS_px)/chainlink · 1e4`. Compute its
  deviation from a trailing-median baseline (window≈200 slugs, causal/shifted). Fire when
  `|dev| > ~3 bps`: dev>+thr → buy **Up**, dev<−thr → buy **Down**. (Binance has led the slow
  Chainlink settlement oracle by an unusual amount → the chainlink-keyed resolution will catch up.)
- **Why it survives:** it's the only signal that beats the (efficient) up-down price OOS, and only at
  the EXTREME tail. Realistic-cost stats (btc-5m, 33d): mean **+$5.95/trade**, WR ~86%, n≈64,
  G1+G2+G3+G4+plateau all PASS; block-bootstrap CI-lo +$4.26; Bonferroni-safe (p=0.0005).
- **Frequency:** ~2 profitable fires/day (rare by construction). The twins 0x3c58ef42/0xd9dea316 run
  exactly this and concentrate UTC 00–08.
- **Status:** real, thin. Forward-test in shadow before sizing; kill-switch if G3 p≥0.05 or G4 CI-lo≤0
  on accumulating live n.

### ❌ CLOSED — maker / pair-arb / merge-arb
Multiple wallets profit at it lifetime, but our uncensored backtest (settling the directional residual,
not matched-pairs-only) is **−$0.066/slug** with 1¢ tx + merge gas, CI entirely <0; and the maker-fill
model is optimistic so reality is worse. The "pair_sum<1 → risk-free" per-wallet number is the censored
measure the 2026-05-28 reversal already debunked. Do NOT deploy without a genuine queue/latency edge.

### ❌ DEAD — momentum / favorite / underdog / fade-momentum / flow
All sit at WR ≈ entry-price (market efficiently prices them); net-negative after high fee + 1¢ tx.
0 of 35 non-clbasis cells pass G1+G4 under realistic costs.

### ⚠️ Oracle-snipe (late-slot) — infra-gated, taker-version closed
CL RTDS at T−30s predicts the outcome ~87%, but entry is ~0.986 → breakeven WR 98.6% >> 87% →
**negative as a taker by construction.** Only viable as a MAKER resting at ~0.985 that gets hit before
the price converges — an unmodellable queue/latency edge (see Audit C optimism caveat). Needs the live
CL RTDS WS feed to even attempt; not validated.

## 3. Deployment architecture (for clbasis_rel btc-5m)
```
 [Binance spot 1s WS] ─┐
                       ├─► cl_basis = (bin_px − cl_px)/cl_px·1e4  ─► dev = cl_basis − trailing_median
 [Chainlink RTDS WS] ──┘                                              │
                                                                      ▼  |dev|>thr at fire (slot_start+offset)
 [Polymarket CLOB WS book mirror] ──► fill side (Up if dev>+thr) ──► place (taker walk OR maker rest)
                                                                      │
                                                                      ▼ hold to chainlink resolution
                                                                  settle ($1 win / $0 lose), −fee −$0.01 tx
```
- **Feeds required (all already collected by the VPS3 storedata collector):** Binance 1s klines,
  Chainlink RTDS oracle, Polymarket L25 book (WS mirror). Ireland VPS = execution (near-optimal RTT
  to Polymarket CLOB on AWS eu-west-2, <2ms).
- **Execution:** taker walk is fine at ~$25 (edge is +$5.95/trade even with high fee+tx). Latency
  matters (signal is a lag-arb) — fire fast; the engine models 85ms.
- **Cadence/risk:** ~2/day btc-5m; concentrate UTC 00–08; per-fire stake small; rolling G3/G4
  kill-switch. Use `engine_v2.RealisticConfig` for any further backtest (now the canonical config).

## 4. Fleet model (observed + ours)
- **Observed operators run FLEETS of single-purpose wallets:**
  - **F1 treasury `0xf70da97812cb96acdf810712aa562db8dfa3dbef`** → pair-arb (0x251c1a28) + momentum
    (0xa5b17799 via relay 0xf3cfb6a6). The $254k/day HFT cluster.
  - **F2 treasury `0x3a9418…`** → mixed: pair-arb (0xa6896d11) + cl_basis directional (0x951bd740) +
    variance (0xdd3c4d67), all created 2026-05-23.
  - ⚠️ `0xe111180000…` is the Polymarket relay/deposit contract, NOT a fleet (false positive).
- **Our fleet model (minimal, edge-honest):** ONE strategy arm = clbasis_rel, run on btc-5m. A "fleet"
  here buys (a) diversification of inventory across wallets to reduce per-wallet exposure / rate limits,
  (b) parallel shadow arms per cell (eth-15m/sol-15m) each independently gate-validated before funding —
  do NOT assume the btc-5m edge transfers (it did NOT pass on other cells). Treasury→arm→relay structure
  mirrors F1/F2: one funder, per-strategy proxy wallets, a relay for inventory exit.

## 5. Infra requirements (ref `INFRA_ROADMAP_2026_05_29.md`, `INFRA_BUILD_RESEARCH_2026_05_29.md`)
- Live: Binance 1s WS + Chainlink RTDS WS + Polymarket CLOB WS book mirror, co-located on Ireland VPS.
- The collector already captures all three to storedata — the gap is the LIVE low-latency path (not
  the historical parquets) and the cl_basis-deviation compute in the hot loop.
- Backtest: always `engine_v2.RealisticConfig` (high fee + 1¢ tx + latency + sparse-book filter);
  always settle uncensored vs chainlink; native-10Hz L25 (subsample_1hz=False).

## 6. Multi-cell transfer + maker-queue probe — RESULTS (2026-05-29)
- **clbasis_rel eth-15m: PARTIAL / fragile.** Best (thr3/off60/px[0.60,0.88]): n=33, WR 84.8%,
  +$6.94/trade realistic, G1–G4 pass (block CI-lo +$2.40), survives BH correction — **but plateau FAILS
  (0.51)**: the edge exists ONLY at offset 60s and reverses at other offsets. Cautious PAPER-only; need
  n≥40 live. (`CLBASIS_ETH15_SOL15_VALIDATION_2026_05_29.md`)
- **clbasis_rel sol-15m: NOT CONFIRMED.** Best cell n=13 (too thin), plateau fails, fails Bonferroni.
- **btc-5m is special:** 5m fires ~12× more often than 15m → n=64 + robust across ALL offsets. The 15m
  cl_basis signal fires too rarely for confidence.
- **Maker queue/latency edge: NO EDGE — DO NOT BUILD.** (`MAKER_QUEUE_LATENCY_PROBE_2026_05_29.md`)
  Resting a maker bid on the clbasis-favored side is **adverse-selected away**: WR drops 50.4%→44.7%
  (optimistic) / 40.3% (conservative); PnL −$3.65 to −$6.11/fill; all gates fail. LOST slugs attract
  **1.33× more sell flow** at the bid (you get filled precisely when wrong); fills arrive at 4s median
  lag = INFORMED flow, not slow retail → no latency advantage to exploit. F1's $254k/day HFT is therefore
  NOT generic maker-queue; it relies on an undecodable slug-selector or a cross-market hedge anchor we lack.

## 7. Honest bottom line
After bug-auditing every engine, applying the harshest realistic costs, validating across cells, and
probing the maker-queue angle, the COMPLETE picture is: **one robust edge (clbasis_rel btc-5m), one
fragile maybe (clbasis eth-15m, off60 only), and everything else dead** — maker/pair-arb/merge-arb closed
(−$0.066/slug + gas), maker-queue adverse-selected away, momentum/favorite/underdog/fade/flow priced-out.
The market is efficient w.r.t. every signal in our data; the lone survivor is a thin oracle-lag tail
(~$12–13/day per $25 on btc-5m). Realistic growth = shadow-deploy btc-5m + cautious eth-15m-off60 paper;
there is NO justified case to build live maker/queue infra. Capital-scale level-market MM (the $935k whale,
$500k+ capital) is the only larger game and is out of scope for our budget.

## Artifacts
- Engine audits: `ENGINE_AUDIT_{A_core,B_directional,C_maker,D_validators}_2026_05_29.md`
- Corrected results: `data/v4/canonical/_results/dir_eval_results_realistic.csv` + plateau json
- Engine: `strategy_lab/engine_v2.py` (RealisticConfig + tx_cost + min_book_events fix)
- Priors: `EFFICIENT_MARKET_FINDING_2026_05_28.md`, `WALLET_HUNT_SYNTHESIS_2026_05_29.md`,
  `NOCHASE_MERGEARB_VERDICT_2026_05_29.md`, `MAKER_ARB_CENSORING_REVERSAL_2026_05_28.md`
