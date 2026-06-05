# Strategy Literature Survey — Synthesis & Decision Map (2026-05-29)

> **What this is.** Cross-references the four parallel web-research catalogs into one
> deduplicated, infra-mapped ranking. Built before resuming the maker-arb / directional
> work to make sure we're not missing a documented edge class.
> **Source reports** (full detail, ~2000 lines combined):
> - `ARB_RESEARCH_PREDICTION_MARKET_2026_05_29.md` (16 strategies)
> - `ARB_RESEARCH_MARKET_MAKING_2026_05_29.md` (14 strategies)
> - `ARB_RESEARCH_STATARB_POSITIONED_2026_05_29.md` (14 strategies)
> - `ARB_RESEARCH_LATENCY_HFT_2026_05_29.md` (10 strategies)

---

## 0. Bottom line
The external literature **independently confirms our own conclusions** and adds three
actionable extensions. No documented strategy class reachable at our infra was missed.

- **Oracle-lag directional taker is the real edge** — it ranked #1 in 3 of 4 domains and
  is independently replicated by an open-source bot (61.4% WR) and two 2026 arXiv papers.
- **The directional-tilted maker has formal academic backing** (Cartea-Wang: "when alpha
  is strong, post only one side") — symmetric MM is *provably* suboptimal once you hold a
  signal, which is exactly why our symmetric sleeves died.
- **Three genuinely NEW candidates** surfaced: (1) model-fair-value-vs-Poly-price relative
  value via N(d2); (2) Chainlink Data Streams WS as a direct ground-truth signal (replacing
  the Binance proxy); (3) cross-exchange lead-lag (CME/perp futures → spot) as a 1–10s
  pre-signal feeding the taker.
- **Everything we already killed, the literature agrees is dead** at our infra (symmetric
  maker-arb, sum<$1 atomic take-both, positioned/sequential leg-in, sub-100ms races).

---

## 1. Master ranked table (deduplicated across all four domains)

| Rank | Strategy | Class | Verdict | Latency reachable? | Source report(s) |
|---|---|---|---|---|---|
| 1 | **Oracle-lag directional taker** (Binance→Chainlink stale-ask pick-off) | Latency | **WORKING — build/paper now** | ✅ 5–60s | all 4 |
| 2 | **Directional-tilted / one-sided maker** (post only on binance-favored side) | MM | **BUILD — strongest new maker avenue** | ✅ seconds | MM #1,#4,#5 |
| 3 | **Model fair value vs Poly price** (N(d2)/BSM implied prob deviation) | StatArb | **NEW — scoped test** | ✅ seconds | Pred #16, Stat #2 |
| 4 | **Chainlink Data Streams WS as direct signal** (replace Binance proxy) | Latency | **HARDENING — high value** | ✅ sub-second | Lat #2,#10 |
| 5 | **Adverse-selection gating** (VPIN / 60s OFI toxicity filter) | MM | **OVERLAY — for both taker & maker** | ✅ seconds | MM #3 |
| 6 | **Cross-exchange lead-lag pre-signal** (CME/perp futures → Binance spot) | Latency | **OVERLAY — earlier trigger** | ✅ 1–30s | Lat #3, Stat #4 |
| 7 | **Mint-sell-hold at sum_asks > $1.005** (directional, NOT passive) | Pred | **PARTIAL — V2 spec exists** | ✅ seconds | Pred #5 |
| 8 | **Cross-slug term-structure** (1m/5m/15m no-arb consistency) | StatArb | **PARTIAL — confirming filter** | ✅ seconds | Stat #5 |
| 9 | **Cross-asset combinatorial** (BTC vs ETH slug divergence vs corr) | Pred/Stat | **PARTIAL — confirming filter** | ✅ <1s | Pred #7, Stat #6 |
| 10 | **Time-of-day gating** (edge larger 22:00–10:00 UTC, avoid US hours) | Latency | **OVERLAY — free win** | ✅ n/a | Lat §10 |
| 11 | **Maker rebate harvesting** (Program-2, ~$0.003–0.0034/contract) | MM | **FLOOR income only** | ✅ n/a | MM #8 |
| 12 | **Intra-slug microstructure mean-reversion** (book-refill after spike) | StatArb | **SPECULATIVE — untested** | ⚠️ sub-second | Stat #2 |
| — | Sum<$1 atomic take-both arb | Pred | **DEAD** (0.004–0.13% book-time, needs colo) | ❌ sub-100ms | Pred #2 |
| — | Symmetric market-neutral maker-arb (paired bids) | MM/Pred | **DEAD** (adverse selection) | n/a | Pred #11, MM #13, Stat #13 |
| — | Positioned / sequential leg-in maker-arb | StatArb | **DEAD** (−$0.03/sh, Glosten-Milgrom) | n/a | Stat #14 |
| — | ETF creation/redemption ↔ mint/merge | StatArb | **DEAD at our infra** (thin books, no persistent sum≠$1) | n/a | Stat #3 |
| — | Neg-risk NO-basket / Dutch-book / cross-platform | Pred | **N/A** (wrong market type / jurisdiction) | n/a | Pred #3,#4,#12 |
| — | AMM-vs-CLOB, Augur invalid-outcome | Pred | **N/A** (Polymarket is CLOB-only) | n/a | Pred #9,#10 |
| — | Pairs/cointegration, vol-arb, funding-carry, basis, index, merger arb | StatArb | **N/A / weak** (no short, no futures leg, slugs independent) | n/a | Stat #1,#7,#4,#11,#10,#12 |
| — | Cross-exchange CEX↔CEX latency, MEV sandwich, microwave/colo | Latency | **DEAD** (sub-ms race, lose) | ❌ sub-ms | Lat #7,#8,#9,#10 |

---

## 2. Tier A — build / paper this milestone

### A1. Oracle-lag directional taker (the edge)
Already our working candidate (`TV_AGENT_SPEC_POLY_FAST_TAKER_2026_05_29.md`). The
literature is overwhelmingly confirmatory:
- **Open-source replication:** `JonathanPetersonn/oracle-lag-sniper` (GitHub) — 8,876
  resolved markets, 5,017 trades, **61.4% WR, profitable 20/24 days**, 60/40 date hold-out
  also 60.7%. Matches our OOS 63% WR almost exactly. The edge is real and others are on it.
- **Published timing:** the resting CLOB book takes **~55s on average to reprice** after a
  Chainlink update — that's the window. Our +$1.31/$25, t=2.28 sits inside it.
- **Papers:** PolySwarm (arXiv:2604.03888) models this as a "latency-arb module";
  the structural lag is inherent to Chainlink's pull-oracle design.
- **Action:** proceed with the shadow sleeve (handoff priority #1). Add the A4–A6 overlays
  below as it matures.

### A2. Directional-tilted / one-sided maker (the maker pivot)
This is the bridge the handoff flagged ("post bids only on the binance-favored side"), and
the literature gives it a name and a proof:
- **Cartea-Wang (2020):** *"When the alpha signal is positive, the strategy tends not to
  post sell limit orders to avoid adverse selection costs."* Post only the side you'd
  willingly hold to resolution.
- **Fodra-Labadie (2012):** non-symmetric limit orders for non-martingale mid-prices yield
  **>15% PnL improvement** over symmetric MM; risk-aversion `η` should scale with
  time-to-resolution.
- **Avellaneda-Stoikov signal-augmented reservation price:**
  `r = s + α·signal − q·γ·σ²·(T−t)` — for binary, treat wrong-side inventory as
  catastrophic (large `γ`).
- **Why our symmetric sleeves died, formally:** Glosten-Milgrom — a resting symmetric bid
  fills leg-1 on the side the market is moving *against*; you ARE the informed-trader the
  spread is priced against. One-sided quoting on the side you already believe in removes
  that leg.
- **Action:** design a directional-tilted maker sleeve = oracle-lag signal gates which side
  to quote; capture maker rebate + dodge the adverse-selected loser. **Untested — this is
  the highest-value NEW maker experiment.**

### A3. Model fair value vs Poly price (N(d2) relative value) — NEW
- From Binance spot + realized vol + time-to-expiry, compute risk-neutral P(Up) =
  cash-or-nothing **N(d2)** (BSM). Trade when the Poly ask deviates from model fair value
  beyond fees.
- PolySwarm independently uses a log-normal pricing model on Polymarket with positive
  backtested returns.
- **Relationship to A1:** this is a *generalization* of the oracle-lag taker — instead of
  a raw bps-move threshold, fire on `|model_P − poly_P|`. Could subsume the threshold sweep
  and remove the 3bps sweep-selection caveat. **Worth a scoped backtest on the same
  binance-1s window.**

---

## 3. Tier B — overlays & confirming filters (cheap, stack onto A1/A2)

- **A4. Chainlink Data Streams WS as direct signal** — subscribe to the signed, sub-second
  Data Streams report (the *exact* price that settles the slot) instead of using Binance as
  a proxy. Removes the Binance→Chainlink basis uncertainty and 1–5s of inference lag; turns
  the signal from predictive to ground-truth. **Best single hardening idea.** Infra lift:
  Chainlink Data Streams API access on the Ireland box.
- **A5. Adverse-selection gating (VPIN / OFI)** — monitor 60s taker imbalance on the Poly
  token; when >80% one-directional, faster oracle-arbers are present → pause maker quoting /
  widen taker threshold. Protects both A1 and A2.
- **A6. Cross-exchange lead-lag pre-signal** — CME BTC futures / Binance perp lead spot by
  1–30s (Frino 2025; Bitwise/CME). Perp premium + funding direction are already on our WS and
  can fire the taker 1–10s earlier.
- **A7. Time-of-day gate** — edge is larger 22:00–10:00 UTC; US hours (12:00–21:00) need a
  higher bps threshold. Free filter, matches our F2 time-of-day finding.

---

## 4. Tier C — confirmed dead / out of reach (do NOT re-test)
- Sum<$1 atomic take-both arb — needs sub-100ms colo; ~$125/day ceiling. (UCLA NBA paper
  found only 7 valid episodes across 173 games, median 3.6s — confirms rarity.)
- Symmetric market-neutral maker-arb, positioned/sequential leg-in — adverse selection;
  Glosten-Milgrom explains why structurally.
- ETF↔mint/merge structural arb — real isomorphism but no persistent sum≠$1 beyond fees on
  our books; revives only if books deepen or fees drop.
- Neg-risk basket, Dutch-book, cross-platform (Kalshi/sportsbook), AMM-vs-CLOB, Augur — wrong
  market type or jurisdiction.
- Pairs/cointegration, vol-arb, funding-carry, basis/cash-and-carry, index arb, merger arb —
  no short-sell of Poly shares, no futures leg, slugs resolve independently.
- CEX↔CEX latency, MEV sandwich, microwave/colo — sub-ms races we lose.

---

## 5. Notable external validations & surprises
- **We are not alone on the oracle-lag edge.** An open-source bot replicates it at 61.4% WR.
  Implication: the edge is real but **will crowd/compress** — move on A1 with urgency, and
  the A4 Data-Streams signal upgrade is partly a "stay ahead of the crowd" move.
- **Public WS trade-direction is only ~59% accurate** vs on-chain ground truth (Dubach,
  arXiv:2604.24366). Validates relying on on-chain `trading.events` for backtest truth, not
  order-book-feed inference.
- **GMX v1 lost ~10% of protocol profits to oracle front-runners** before patching — the
  same mechanism we exploit, on the LP side. Confirms oracle-lag is a durable, documented
  value leak, not a fluke of Polymarket.
- **Maker rebates are tiny** (~$0.003/contract) — a floor on a directional-tilted maker, not
  a standalone reason to make markets. Matches our earlier finding.

---

## 6. Recommended next actions (ties to handoff §7)
1. **Proceed with A1** — implement + paper the `poly_fast_taker` shadow sleeve
   (handoff #1). No literature blocker; strong external confirmation.
2. **Spike A3 (model fair value)** on the existing binance-1s window — cheap backtest, may
   replace the bps threshold and kill the sweep-selection caveat.
3. **Design A2 (directional-tilted maker)** — the only live maker avenue; now backed by
   Cartea-Wang / Fodra-Labadie. Scope it next to the taker since both consume the same signal.
4. **Scope A4 (Chainlink Data Streams WS)** access on Ireland — the highest-value hardening,
   also a crowding hedge.
5. Park A5/A6/A7 as overlays to add once A1 has fresh OOS trades.

Colo/relay (handoff #3) stays **deprioritized** — the literature confirms ~$125/day ceiling
for the only edge it unlocks (sum<$1), not worth the infra lift.
