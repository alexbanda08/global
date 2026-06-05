# Positioned Maker-Arb — Corrected Economics + Plan (2026-05-29)

> Reopens the maker-arb question. My earlier "retire" verdict
> (`MAKER_WALLET_REEVALUATION_2026_05_29.md`) was based on an ATOMIC sum<$1 scan +
> a 0.9975 merge assumption + dismissing rebates — **all three now corrected in the
> maker-arb's favor.** The sequential positioned-arb has NOT yet been properly tested.

## Two economics conflicts — RESOLVED from real on-chain data (wallet 0x89b5cdaa)
1. **MERGE is exactly 1:1.** 270,341 shares merged → $270,341 USDC. `$/share = 1.00000`.
   **No 0.25% protocol fee.** Our engine subtracted 0.9975 (a phantom $0.05 "gas") —
   wrong. Profit per completed pair = **$1 − (leg1_cost + leg2_cost)**, clean. Every
   prior maker-arb backtest understated by ~$0.05/pair (size 20 → ~$1/slug).
2. **Maker rebates real + material:** $79,757 over the cached window (~$1k/day,
   ~18% of this wallet's net). Open to everyone, automatic, on crypto up-down. The
   per-share rate is obscured by the 3,500-event API cap, but the magnitude is
   confirmed. (Use as upside; pin the exact rate from the live TV dashboard payouts.)

## Rewards programs (research, docs.polymarket.com)
- **Program 1 — Liquidity Rewards** (big funded pool, quadratic spread-score × size,
  two-sided Q_min): **$5M April-2026 pool is SPORTS/ESPORTS ONLY.** Crypto up-down
  "coming soon" — monitor `GET clob.polymarket.com/rewards/markets/current`. Not a
  lever yet, but a large future upside if crypto pools open.
- **Program 2 — Maker Rebates** (20% of taker fee the maker's liquidity generates):
  active on crypto, open to all — this is 0x89b5cdaa's $79.7k.

## Why ACC-M lost and how positioned-arb fixes it (technique research)
- **ACC-M posted BOTH legs simultaneously** at sum<$1. An informed taker lifts ONLY
  the wrong leg (the side about to lose), so you're handed a guaranteed-loss single
  leg. Simultaneous two-sided quoting has **negative EV in the presence of any
  informed flow** — that IS our −$6.6k.
- **Positioned (sequential) leg-in:** post leg 1; once it fills at a known price,
  post leg 2 ONLY at a price that keeps `sum < budget`; complete → MERGE for $1.
  You decide the 2nd leg WITH the information of how flow behaved after leg 1.
- Controls (from docs + A-S inventory theory): (a) post only the side you're short;
  (b) hard gate `leg1+leg2 < ~0.96`; (c) inventory-skew the 2nd-leg bid; (d) pull all
  quotes 60-120s before resolution (GTD orders); (e) optionally hedge a stuck leg on
  Binance perps.
- **Edge = completed_pairs × ($1 − sum) + 2×rebate − stuck_legs × adverse_loss.**
  Completion rate is the whole game; ~80%+ needed. Stuck legs are adversely selected
  (negative EV), so the flatten/hedge discipline matters.

## Headroom (canonical L25, native 10Hz, May 22-26)
Cheap pairs are ALWAYS reachable: `min(UP_ask)+min(DN_ask)` < $0.9975 in **100%** of
slugs (median min-sum ~$0.40; realistic p10-sum ~$0.53). The opportunity exists; the
binding constraint is COMPLETION (catching the 2nd leg cheap before resolution).

## 🚨 DECISIVE TEST RESULT — positioned-arb LOSES, even fully corrected
`positioned_leg_in_backtest.py` + `positioned_leg_in_flatten.py` (native-10Hz L25,
May 22-26, merge=$1, rebates credited, sequential leg-in):

| policy | pooled comp-rate | pooled pnl/share | best cell |
|---|---:|---:|---:|
| leg-in, hold stuck to resolution | 76-83% | **−$0.030** | −$0.0225 (BTC 15m) |
| leg-in, FLATTEN stuck at bid | 76-83% | **−$0.031** | −$0.0222 |

**Negative in EVERY cell, EVERY param (L1∈{0.45,0.50}, BUDGET∈{0.94,0.97}), both
policies.** Flattening doesn't help (stuck-leg bid already collapsed to ~0.05-0.20).

**Root cause (structural, unavoidable):** a symmetric resting-bid maker is adversely
selected — leg1 fills on the side the market is moving AGAINST (the likely loser).
You then lose **~$0.32-0.47 on the ~17-24% of stuck legs**, whether you hold or
flatten. The completed pairs earn only **$1−BUDGET = $0.03-0.06** each. Math:
`0.80 × $0.05 − 0.20 × $0.40 = −$0.04/trade`. Free merge (+$0.0025) and rebates
(+$0.007/pair) are an order of magnitude too small to close the gap.

**Why the wallets escape it:** they are NOT symmetric makers. 0x89b5cdaa buys DOWN
3.4× more than UP (797 Up / 2703 Down fills) — it's **directionally TILTED**, layering
a directional view (which side wins) on top of the merge mechanic. The market-neutral
positioned-arb we keep building is precisely the adversely-selected counterparty that
funds the directional players + HFT takers.

## FINAL VERDICT
Tested every lever you raised — free merge (verified 1:1), real maker rebates,
sequential (not simultaneous) leg-in, completion discipline, stuck-leg flattening.
**The positioned maker-arb is net-negative (−$0.03/share) on our data because of
irreducible maker adverse selection.** To make it work you must add the one thing the
profitable wallets have and we don't: a **directional edge** (pick the winning leg) —
which is priced-in for us beyond sub-60s (`STRATEGY_REEVALUATION_2026_05_29.md`), or
**sub-100ms pick-off speed** (colo + relay). Neither is reachable on the current
infra. **Retire the symmetric maker-arb sleeves.** The only live path to this market
is the directional/latency game, not market-making.

## Artifacts
- Real-data resolution: 0x89b5cdaa activity (cache/_pm_portfolio/0x89b5cdaa/)
- Headroom: `strategy_lab/maker_arb_audit/positioned_arb_headroom.py` + `_results/positioned_arb_headroom.csv`
- Research: rewards program + positioned-arb technique (this session's agents)
