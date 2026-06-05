# 5-Wallet Strategy Decode — 2026-05-29

> User-flagged wallets: `0xeebde7a0` ("best strategy"), `0x0fe40e88` + `0x4ee29e4e`
> ("maker hedge arb"), `0xa42f127d` ("promising"), `0x143732d8` ("multi-safe, one
> side each"). Decoded trade-by-trade from the Polymarket data-api `/activity` tape
> (TRADE+MERGE+SPLIT+REDEEM+REBATE), canonical L25/resolutions, on-chain transfers,
> and CLOB price-history. PnL = lb-api `/profit` (ground truth).

---

## 0. Headline

| Wallet | Pseudonym | **What it actually is** | lb PnL all / 30d / 7d | Markets | Replicable for us? |
|---|---|---|---|---|---|
| `0xeebde7a0` | — | **Directional intraday TAKER, conviction-sized** (merge = collateral recycling) | **$825k / $253k / $92k** | btc/eth/sol updown 5m/15m/4h | ✅ **YES — same family as our live oracle-lag candidate** |
| `0x0fe40e88` | gobblewobble | **Directional momentum TAKER, buy-the-dip on the favored side** of DAILY up-down | $408k / +$16k / **−$3k** | daily up-down + target-price | ⚠️ partial — different market (daily), no books in our data |
| `0xa42f127d` | 5f5a | **Two-sided SPORTS market maker** (tennis binaries) | $141k / +$16k / **+$8k** | ATP tennis, crypto price | ❌ no — sports MM, out of domain |
| `0x4ee29e4e` | IH2P | **Neg-risk / complement basket arb** on "BTC price/above $X" | $237k / +$3k / **−$3k** | price-threshold + buckets | ⚠️ partial — neg-risk, not intraday |
| `0x143732d8` | — | **Neg-risk NO-basket arb** (sports + daily up-down), one-sided per market | $38k / **−$9k** / −$0.2k | enhanced-games sports + updown | ❌ no — losing; multi-safe unconfirmed |

**Three corrections to prior labels / assumptions:**
1. **None of these is a market-neutral maker-arb.** All five have `maker_rebate_share < 0.005` → they are **TAKERS** (or makers on markets where rebates aren't paid), not passive rebate-earning makers. The classifier labels "PURE_PAIR_ARB_MAKER" etc. were keyed on the 100%-BUY + merge/redeem footprint, which **also** describes directional buy-and-hold.
2. **`0xeebde7a0` is NOT "mint-sell"** (SPLIT = 0, it never mints) and **NOT complement arb** (pair sum-cost median 1.025 > $1). It is **directional**, exactly as the May-18 V3 "buy-dip" decode found.
3. **The profitable up-down edge is DIRECTIONAL, not neutral** — reinforcing the handoff verdict and the literature survey's "directional-tilted" conclusion.

**Data constraint:** our canonical L25 is **intraday-only** (`btc-updown-5m-{epoch}`, 0 daily markets). Only `0xeebde7a0` trades markets we have books for. The other four trade **daily up-down / price-threshold / sports** markets — decoded from their event tape + own fill prices + CLOB price-history (no L25 depth available for those markets, anywhere).

---

## 1. `0xeebde7a0` — the best one. Directional intraday taker w/ collateral recycling

**This is the standout and it is CURRENTLY working: $825,721 lifetime, $253k/30d, $92k/7d, $16.5k/day.** Open inventory only $1,680 → fully flat (everything resolves intraday).

### Mechanic (from data-api tape + canonical books)
- **Markets:** btc/eth/sol up-down **5m (1530) / 15m (1387) / 4h (147)** — intraday, in our L25.
- **100% BUY**, balanced across outcomes (Up 1818 / Down 1656). **SPLIT = 0** (never mints). **MERGE 3500 + REDEEM 3500** (both API-capped → very high volume).
- Per slug it buys **both** Up and Down 81.8% of the time, but **$-skewed 75/25** toward one side.
- **MERGE is not the profit** — pair sum-cost median is **1.025 > $1** (merging a complete set bought for 1.025 *loses* 2.5¢). MERGE collapses the matched/hedged portion back to $1 to **recycle collateral** so capital can be redeployed into the next fire. **REDEEM collects the directional residual.**

### The edge (joined to canonical resolutions, 88-slug sample)
- **Dominant-side (by $) hit-rate = 61.4%** (matches the V3 decode's ~61% WR).
- **$-weighted hit-rate = 83.6%** — i.e. the **big bets win 84%**. This is a **conviction-sizing** edge, not naive direction (net-share direction wins only 50%).
- Avg dominant-side entry: **0.721 when it wins** (n=54) vs **0.436 when it loses** (n=34) — it pays up for high-conviction winners and keeps losers small/cheap.
- Avg dominant stake ≈ $442/slug; thousands of slugs/week × capital recycled via merge → the $92k/7d.

### Verdict
`0xeebde7a0` = **HFT directional intraday taker** on the same binance-lead / oracle-lag signal family as our identified live candidate (`TV_AGENT_SPEC_POLY_FAST_TAKER`), executed at scale with **merge-based collateral recycling** for capital efficiency. **Most directly relevant and replicable** of the five — it validates the directional-taker thesis with a live, currently-profitable example. The exact trigger is the V3 composite (`disc_capture OR pm_drop_5s>0.02 OR offset∈[0,60] OR (buy_vol_60s>50 AND pm_drop_5s>0) OR hour==15`, ~79% coverage) — see `EEBDE7A0_TAKER_TRIGGER_V3_2026_05_18.md`. **The merge-recycling trick is the one new thing to copy** if we want to run it capital-efficiently.

---

## 2. `0x0fe40e88` (gobblewobble) — directional buy-the-dip on the winning side (DAILY)

**$408,299 lifetime, +$16k/30d, but −$3.0k/7d (losing this week).** $321k open inventory (held complete daily positions awaiting redemption). Volume $27.8M → 1.47% margin. `maker_rebate_share = 0.0005` → **TAKER**.

### Mechanic (trade-by-trade, daily up-down)
NOT pair-arb (the "PURE_PAIR_ARB_MAKER" label is wrong). On **22 converged daily up-down markets**:
- **Directional hit-rate 86.4% (94.1% $-weighted)**, median **88.7% one-sided** skew.
- Avg dominant entry **0.838 when winner** (n=19) vs **0.249 when loser** (n=3) — big conviction on near-certain winners, tiny cheap longshots on losers.
- Complete-set pair-cost median **1.058 > $1** → confirms not arb.
- Est **+$60k** holding only the dominant side to $1 across 22 markets.

### Worked example — `bitcoin-up-or-down-on-may-18-2026` (CLOB price-history overlay)
Down-token mid: ~0.50 (May 16–17) → **dipped to 0.435** (May 17 19:30) → 0.775 (May 18 02:20) → 0.915 (09:10) → **1.000** (resolved Down). gobblewobble **bought Down heavily at 0.38–0.53 during the dip** (May 17 21:00–23:00), then kept adding all the way to **0.97**, holding to $1 redemption. Classic **buy-the-dip on the side the underlying favors, scale in with conviction**.

### Verdict
A **directional momentum/dip-buyer on daily crypto up-down** — same directional DNA as eebde7a0 but on the slow (daily) market with a longer fill window. Edge = picking the winning side early (binance-lead) and sizing up. **Partly relevant** (validates directional-tilt) but on a market we have no books for, and **recently negative** — the daily edge looks like it's compressing.

---

## 3. `0xa42f127d` (5f5a) — two-sided SPORTS market maker

**$141k lifetime, +$16k/30d, +$7.8k/7d (the only consistently-positive-recent wallet).** Highest volume of the four ($72.9M) → thinnest margin (0.19%). Small open inventory ($11k).

### Mechanic
- Top markets are **ATP tennis** binaries (`atp-fonseca-djokovic`, `atp-borges-rublev`, …), 2 outcomes (player A / player B).
- On its top market: **338 SELL / 293 BUY** → genuinely **two-sided** (posts both bids and asks). REDEEM-heavy (holds some to settlement). `maker_rebate_share = 0.003` (low, but it IS quoting both sides).
- = **classic market making**: quote both sides of liquid sports binaries, capture the spread + occasional rebate, manage inventory, redeem residual at settlement.

### Verdict
**Sports market-maker, not crypto, not arb.** Out of our domain (we have no sports feeds/books). Notable only as the example that **spread-capture MM works on liquid binaries when you quote both sides** — but it needs a different (sports) data stack. Not actionable for us.

---

## 4. `0x4ee29e4e` (IH2P) — neg-risk / complement basket arb on price markets

**$237k lifetime, +$2.6k/30d, −$3.2k/7d.** Volume $36.6M (0.65% margin), open $49k. `maker_rebate_share = 0.0002` → **TAKER**. Tape: TRADE 3500, MERGE 3500+, REDEEM 3500+, **SPLIT = 1** (essentially never mints).

### Mechanic
- Markets: **"bitcoin-price-on-{date}"** (multi-bucket neg-risk) + **"bitcoin-above-$X"** (binary Yes/No). Top binary `bitcoin-above-74k-on-may-29`: 139 BUY-only.
- Buys legs on the book then **MERGE** (collapse complete sets → $1) / **REDEEM** (hold to resolution). No minting → it sources complete sets by buying both/all legs cheap on the CLOB.
- On the few captured binary markets, pair sum-cost median **0.887 (75% < $1)** → genuine **complement/neg-risk basket arb** (buy the set for < $1, redeem/merge for $1).

### Verdict
**Neg-risk / complement basket arbitrage** on crypto price-threshold and price-bucket markets — the "buy a complete (or NO-) basket below $1, collect $1" play from the literature survey (Pred #3, Stat #3). Real but **low-margin and recently flat/negative** (0.65% gross, −$3k/7d). On daily/bucket markets we don't have books for. **Partially relevant** as a template for neg-risk basket arb, but the intraday version of this is exactly what we already killed to adverse selection.

---

## 5. `0x143732d8` — neg-risk NO-basket, one-sided per market (multi-safe: unconfirmed)

**Weakest: $37.7k lifetime but −$9.3k/30d (losing), −$0.2k/7d.** Volume $12.8M (0.29% margin), open $8.4k. `maker_rebate_share = 0.0011` → **TAKER**. Tape: SPLIT 167 (some minting), MERGE 303, REDEEM 2876, **3497 BUY / 3 SELL**.

### Mechanic
- Markets: **enhanced-games sports** (multi-outcome, 1835 trades) + **daily up-down** (btc/eth/hype/xrp) + some price markets.
- Overwhelmingly buys **"No" (2292)** across multi-outcome markets → **neg-risk NO-basket arb** (buy NO on the mutually-exclusive outcomes; all-but-one pay $1).
- **One-sided in 92.4% of markets** (buys a single outcome per market). On daily up-down: 26 markets Up-only, 22 Down-only, 12 both.

### Multi-safe hypothesis ("one safe fires Up, another Down") — RESOLVED
Full-history on-chain trace (394k transfers, 2025-11-13 → 2026-05-29) settles it:
- **Controlling EOA = `0xf70da97812cb96acdf810712aa562db8dfa3dbef` — the F1 treasury.** It made
  the seed deposits (2026-03-30: $58, $15, $2,916), is the top USDC inflow ($7.9k) AND the top
  outflow ($35.4k swept back). So `0x143732d8` is a **treasury-funded strategy wallet**.
- **It is part of a FLEET, not a 2-safe up/down pair.** The same F1 treasury funds
  `0xeebde7a0` (the $826k directional taker), `0x0fe40e88` (gobblewobble, $408k directional
  daily), `0xb27bc932` ($569k HFT taker), `0x89b5cdaa` ($530k mixed taker/seller). See §6.1.
- **The "one fires Up, another fires Down on the same slug" pattern is NOT supported.**
  Direct test (gobblewobble vs 143732d8): only 2 shared slugs in the captured tapes, and on
  both they took the **same** side — zero strictly-opposite-side overlap. The fleet segregates
  by **STRATEGY** (each Safe runs a different approach), not by **side** of one market. The
  92.4% one-sidedness is just this wallet's neg-risk-NO-basket nature, not a paired sibling.

### Verdict
**Neg-risk NO-basket arbitrageur on sports + daily up-down, currently losing.** Multi-safe structure plausible but not proven. Lowest priority of the five.

---

## 6. Cross-cutting conclusions

1. **The profitable crypto up-down edge is DIRECTIONAL** (`eebde7a0` $825k, `gobblewobble` $408k), not market-neutral. Both pick the favored side (binance-lead / buy-the-dip) and size by conviction. This **triple-confirms** the handoff verdict and the literature survey: pursue the **directional taker / directional-tilted** line, not symmetric maker-arb.
2. **`eebde7a0` is the blueprint** — it runs our exact candidate edge (fast directional intraday taker) live and profitably, adding one trick worth copying: **MERGE complete/hedged sets to recycle collateral** instead of holding capital idle.
3. **None are rebate makers** (`maker_rebate_share < 0.005`). Rebate harvesting is not their income — don't model it as the edge.
4. **The arb wallets (IH2P, 143732d8) run neg-risk / complement BASKET arb on daily/bucket/sports markets**, where the fill window is long and books deep — the same structure dies intraday (our killed sleeves). Margins are thin (0.19–0.65%) and **recently negative**, i.e. the passive-arb edge is compressing even on slow markets.
5. **`5f5a` proves two-sided MM works on liquid sports binaries** — but that's a separate (sports) venture, not crypto.
6. **Replicability ranking for us:** `eebde7a0` (high — direct) ≫ `gobblewobble` (medium — directional, different market) > `IH2P`/`143732d8` (low — neg-risk, thin/negative) > `5f5a` (out of domain).

### 6.1 The F1 treasury fleet (new this session)
The on-chain trace of `0x143732d8` surfaced that **three of the five flagged wallets are one
operation** — the **F1 treasury `0xf70da97812cb96acdf810712aa562db8dfa3dbef`** funds and sweeps
a diversified fleet of single-strategy Safes:

| Safe | Strategy | lb PnL all | Seeded |
|---|---|---:|---|
| `0xeebde7a0` | directional intraday taker (crown jewel) | $826k | 2026-03-25 |
| `0xb27bc932` | HFT directional CLOB taker | $569k | 2026-03-03 |
| `0x89b5cdaa` | mixed CLOB taker/seller | $530k | 2026-02-22 |
| `0x0fe40e88` (gobblewobble) | directional daily up-down | $408k | 2025-12-10 |
| `0x143732d8` | neg-risk basket (sports + updown) | $38k | 2026-03-30 |

- **`0x4ee29e4e` (IH2P) and `0xa42f127d` (5f5a) are NOT F1** — independent operators.
- **Structure = strategy diversification, not side-hedging.** F1 runs a *book* of prediction-
  market strategies (HFT, directional intraday, directional daily, neg-risk basket), each
  isolated in its own Safe, all capitalized and harvested by the treasury. This is how a serious
  prop shop operates the space — and the **directional takers (`eebde7a0`, `b27bc932`,
  `gobblewobble`) carry the PnL**; the neg-risk basket (`143732d8`) is a small, fading sideline.
- **Implication:** the operator with the deepest edge on these markets has concluded the money
  is in **directional/HFT taking**, exactly the line we're pursuing. The neg-risk/maker-arb
  wallets are the low-earning tail of even the best fleet.

## 7. Recommended next steps
1. **Fold the `eebde7a0` findings into the `poly_fast_taker` build** — specifically (a) conviction-based position sizing (big size only on high-confidence fires, since $-weighted WR 84% ≫ raw 61%), and (b) **merge-based collateral recycling** to run it capital-efficiently. This is the single most valuable takeaway.
2. **If pursuing directional-tilted maker** (literature A2): `gobblewobble`'s daily buy-the-dip is the template — post bids on the binance-favored side during dips, hold to resolution.
3. **Optional:** full-history funder trace on `0x143732d8` to settle the multi-safe question; and pull `eebde7a0` fresh L25 fills to re-verify the 84% $-weighted WR out-of-sample. Low urgency.
4. **Do not** chase the neg-risk basket arb (IH2P/143732d8) intraday — it's the killed-sleeve structure; the daily version is thin and fading.

## 8. Artifacts
- `strategy_lab/wallet_hunt/_decode_maker_wallets_2026_05_29.py`, `_decode_directional_v2_2026_05_29.py`, `_probe_overlap_2026_05_29.py`
- `strategy_lab/wallet_hunt/cache/_maker_decode_2026_05_29/{<short>_per_market.parquet,_dirmarkets.parquet,_summary.json}`
- `strategy_lab/wallet_hunt/cache/_pm_portfolio/<addr>/activity_*.json` (full event tapes)
- `strategy_lab/wallet_hunt/cache/0x143732d8/alchemy_transfers.parquet` (7d on-chain)
- Prior eebde7a0 decode: `EEBDE7A0_TAKER_TRIGGER_{DECODED,V2,V3}_2026_05_18.md`
