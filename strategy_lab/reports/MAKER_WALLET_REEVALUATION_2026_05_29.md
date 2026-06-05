# Maker-Arb Wallet Re-Evaluation — Why the Source Wallets Profit and Our Sleeves Don't (2026-05-29)

> Correct target this time: the ORIGINAL maker / market-maker / mint-and-sell
> wallets that ACC-M, MAS, PAT were reverse-engineered from (NOT the directional
> takers — those are a separate, priced-in game, see `STRATEGY_REEVALUATION_2026_05_29.md`).
> Goal: re-analyze the source wallets, their current trades, and find what makes
> THEIR maker activity profit that our replication misses.

## The source wallets + what they actually are
From `WALLET_STRATEGIES_DECODED_2026_05_17.md` (the founding decode) + the
decoder-fix correction (`DECODER_FIX_RESULT_2026_05_21.md`, lb-api = truth):

| wallet | role / template for | lb-api lifetime | maker-rebate % income | the real edge |
|---|---|---:|---:|---|
| 0xb27bc932 | HFT 2-sided scalper (+relay 0xf3cfb6a6) | +$568,928 | 3.6% | **speed**: sub-cent scalp, **HOLD PnL = −$0.36/$** (loses if held). NOT maker-arb. |
| 0xeebde7a0 | HFT mint-and-sell (PAT template) | +$825,721 | 0.7% | speed + volume; "no clear spread edge" per decoder |
| 0x89b5cdaa | dominant maker (MAS / multi-asset template) | +$530,088 | **9.5%** | maker **rebates** + binance-directional merges |
| 0x04b6d7e9 | paired-bid maker hold-to-expiry (ACC-M template) | +$215,949 | 1.1% | corrected; was a buggy −$29.8k in the decoder |
| 0xcfb103c3 | (was "failed scalper") | +$144,050 | 0% | directional taker, not maker |

**Fresh re-pull + income decomposition (2026-05-29) — corrects the rebate hypothesis:**
- **Profit is REDEEM-dominant (58-98% of inflow), not rebates.** MAKER_REBATE is
  0.7-9.5% of inflow (only 0x89b5cdaa meaningful at 9.5% ≈ ~15% of net). Rebates are
  NOT the edge — these are directional players who also post some limits.
- **MERGE is 28-76% of inflow** (0xeebde7a0 $1.72M, 0xcfb103c3 $1.14M from MERGE).
  This is the real arb: **buy both sides when UP+DOWN sum < $1.00, then MERGE for $1**
  — capturing the sub-$1 sum discount at ENTRY (not a spread/expiry play).
- **100% crypto up-down** — these wallets profit ON btc/eth/sol-updown, not elsewhere.
- Still active+profitable NOW: 0xeebde7a0 $16.5k/day ($92k/7d), 0x89b5cdaa $7.5k/day,
  0xcfb103c3 $91k/30d, 0x04b6d7e9 $28k/7d. 0xb27bc932 flat last 7d (−$207, fading/paused).

## The decisive realization
**None of these wallets profit from the pure maker-arb MECHANIC (paired bids →
merge → hold residual) that our ACC-M/MAS/PAT sleeves implement.** Their profit
comes from edge sources our replication does NOT capture:

1. **HFT speed scalping (0xb27bc932, 0xeebde7a0).** They are 2-sided TAKERS that
   pick off mispriced maker quotes at sub-second cadence (520 fills in 329s on one
   slug) and offload to a relay wallet (0xf3cfb6a6) that merges/redeems. HOLD PnL is
   NEGATIVE — the entire edge is speed + price-improvement, requiring colo + a relay
   wallet. The founding doc explicitly: **"NOT reproducible without colo."**
   **🔑 These takers are the COUNTERPARTY to makers like us — they pick off our
   sleeves' quotes. We are on the losing side of their game. That IS our adverse
   selection.**
2. **🔑 Sum-discount MERGE arb (the real maker edge).** MERGE is 28-76% of their
   inflow: they BUY both sides when `up_ask + dn_ask < $1.00`, then MERGE the pair for
   $1 — locking `$1 − sum` risk-free. This is a SPEED/SELECTION play: they grab the
   fleeting sum<$1 moments (likely as fast TAKERS of both legs, atomic, no residual).
   **Our sleeves POST passive bids at sum_bids<$1 and hope both fill — but adverse
   selection fills only the wrong side, leaving a losing directional residual.** We
   replicated the *intent* (sum<$1) with the wrong *execution* (passive maker vs fast
   taker), so we rarely complete the cheap pair and instead carry the −EV leftover.
   The censoring audit confirmed our observed books were sum_asks ~$1.01 — i.e., no
   arb available when we looked passively.
3. **Maker rebates are NOT the edge** (corrected): 0.7-9.5% of inflow, mostly noise.
   Don't chase the rewards-program lever — the decomposition kills that hypothesis.
4. **Directional accuracy on the residual** (REDEEM-dominant inflow): when they don't
   complete a pair, their leftover leg wins more than random — the binance-lead signal,
   which my broad test (`STRATEGY_REEVALUATION_2026_05_29.md`) showed is ~priced-in
   without sub-60s speed.

## Our sleeves — verified net-negative (the May-21 flags, now resolved)
`DECODER_FIX_RESULT_2026_05_21.md` §190 flagged four claims as UNVERIFIED:
"ACC-M true cash −$1.02/slug", "0x04b6d7e9 is paired-bid maker not sell-side",
"MAS structurally negative — re-verify with rebate income", "PAT structurally
dead — re-audit after canonical fee model". **All now verified this session:**
- The shadow engine's missing REDEEM income + loser-mark bug were the E1 fix
  (`ENGINE_FIX_VERIFICATION_2026_05_29.md`) — engine PnL is now honest.
- With honest accounting + REDEEM income credited + real settlement, the backfill
  (`MAKER_ARB_BACKFILL_REAL_PNL_2026_05_29.md`) shows **every maker sleeve
  net-negative, −$6,599/5d.** The censoring reversal proved the prior "+$4.44/slug"
  was survivorship bias.
- So the May-21 suspicions are confirmed: ACC-M/MAS/PAT are net-negative even with
  rebate-income and correct settlement — because the markets have no maker-arb
  spread edge at our scale, and the HFT takers adverse-select our residual.

## Answer: can we make the maker-arb sleeves profit like the wallets?
The wallets' real maker edge is the **sum<$1.00 MERGE arb captured by FAST TAKING
both legs** (+ directional accuracy on the residual). Our sleeves replicated the
intent with the wrong execution (passive bids → adverse selection → losing residual).
So the right question is no longer "tune the maker sleeves" — it's **"does a fast
take-both-and-merge arb exist in our data, and can we capture it?"**

Concrete options, honest ranking:
1. **🎯 DECISIVE TEST (do first, cheap): scan canonical L25 for `up_ask+dn_ask < $1`.**
   At NATIVE 10Hz (subsample_1hz=False), measure how often `best_ask_up + best_ask_dn
   + merge_cost(0.25%+gas) < $1.00`, the size available, and the $/day a take-both-then-
   MERGE would capture. This is **market-neutral, atomic, no adverse selection, no
   directional risk** — exactly what the wallets do. If the gap exists with frequency
   × size > fees, THIS is the reproducible edge and the sleeves should be rebuilt as a
   **taker-both-legs arb** (not passive makers). If sum is ~always ≥ $1.005 in our
   books (as the censoring audit hinted), the arb is gone before we can reach it →
   it's a latency game we lose.
2. **If (1) shows arb but it's fleeting (sub-second):** it's a speed play — needs the
   fastest taker on the book (colo near Polymarket CLOB, eu-west-2/London; Ireland RTT
   <2ms helps). Quantify the decay: how long does sum<$1 persist? That sets the
   latency budget.
3. **Drop passive-maker posting entirely.** The passive paired-bid design (ACC-M/MAS/
   PAT) is structurally adverse-selected — retire it. Replace with the taker-arb from
   (1) if it exists.
4. **Retire maker-arb** if (1) shows no capturable sum<$1 gap — the premise has no
   reproducible edge for us.

Note: maker liquidity REBATES are NOT the lever (decomposition: 0.7-9.5% of inflow,
mostly noise). Do not pursue a rewards-farming angle.

## 🎯 DECISIVE TEST RESULT — the sum<$1 arb exists but is UNREACHABLE
`strategy_lab/maker_arb_audit/sum_discount_arb_scan.py` on native-10Hz L25 (May 22-26):

| cell | % slugs w/ arb | % of book-time arb available | cap/slug (gross, pre-gas, size≤50) |
|---|---:|---:|---:|
| BTC 5m | 8.3% | 0.004% | $0.15 |
| BTC 15m | 18.1% | 0.019% | $0.13 |
| ETH 5m | 12.6% | 0.037% | $0.08 |
| ETH 15m | 19.0% | 0.132% | $0.29 |
| SOL 5m | 11.6% | 0.107% | $0.05 |
| SOL 15m | 13.5% | 0.118% | $0.09 |

**Total ~$625 over 5,533 slugs / ~5 days ≈ $125/day GROSS — the absolute ceiling**
assuming you win EVERY race at full size. Reality:
- The book sum is **≥ $0.9975 for 99.87-99.996% of the time.** The arb is a ~0.1s
  blip (one 10Hz tick) you must take BOTH legs of before the quote moves.
- That's a **sub-100ms latency race against the co-located HFT scalpers** (0xb27bc932)
  who are exactly who captures it. From a general VPS we lose that race almost always.
- Net of gas (~$0.05/merge), losing most races, and realistic fill rates → the
  realizable number is **effectively zero or negative.** A PASSIVE maker (our sleeves)
  captures NONE of it — by definition you can't post a resting bid that fills both
  sides inside a 0.1s window; you get adverse-selected instead (the −$6.6k we see).

**This empirically closes the question: the maker-arb premise has no reachable edge
for us.** The arb that makes the wallets money is real but lives in a latency tier we
can't enter without colocation + a relay wallet — and even fully captured it caps at
~$125/day, not worth the infra build.

## Bottom line
The maker-arb sleeves were reverse-engineered from profitable up-down makers, but
the decomposition shows their edge is **capturing the sum<$1.00 discount by fast-
TAKING both legs and MERGING** (28-76% of inflow) — NOT passive maker-rebate farming
(0.7-9.5%, noise) and NOT a bid-ask spread. Our sleeves copied the intent with the
wrong execution (passive bids → adverse-selected residual) and lose −$6.6k/5d on the
now-honest engine. **The decisive L25 scan is now DONE (above): the sum<$1 arb exists
for only 0.004-0.13% of book-time, caps at ~$125/day GROSS even if you win every
sub-100ms race, and is captured by colocated HFT bots — unreachable for us. A passive
maker captures none of it. VERDICT: retire ACC-M / MAS / PAT — the maker-arb premise
has no reachable edge for our infrastructure.** (If you ever build colo + a relay
wallet, revisit; until then, stop.)

## Artifacts / evidence
- `WALLET_STRATEGIES_DECODED_2026_05_17.md` (founding decode), `WALLET_CATALOG_2026_05_17.md`
- `wallet_hunt/DECODER_FIX_RESULT_2026_05_21.md` (lb-api truth + §190 flags)
- `wallet_hunt/cache/_decoder_summary.csv`, `_master_catalog.csv`, `_cash_pnl_summary.csv`
- This session: `ENGINE_FIX_VERIFICATION_2026_05_29.md`, `MAKER_ARB_BACKFILL_REAL_PNL_2026_05_29.md`, `MAKER_ARB_CENSORING_REVERSAL_2026_05_28.md`
- Fresh maker-wallet income decomposition: [running — will append rebate% + source split]
