# Polymarket LP-reward farming — strategy types & the scoring math (2026-06-03)

Follow-up to `POLYMARKET_LP_REWARDS_RESEARCH_2026_06_03.md`. Focus: the *types* of farming strategies, and
a reality-check on the "park orders wide in a stale low-liquidity market so they never fill" idea.

## The exact scoring math (official docs) — this dictates every strategy
Per-order position score:
```
S(v, s) = ((v − s) / v)²  · b
   v = max_incentive_spread (market's max distance from midpoint that still scores; orders beyond v = 0)
   s = your order's spread from the size-cutoff-adjusted midpoint
   b = in-game multiplier (live sports in-play boost; 1 otherwise)
```
Size enters via the book sums:
```
Qone = Σ S(v,spread)·BidSize   (bid depth, both m and complement m')
Qtwo = Σ S(v,spread)·AskSize   (ask depth)
Qmin (midpoint ∈ [0.10,0.90]) = max( min(Qone,Qtwo), max(Qone/c, Qtwo/c) )   c = 3.0
Qmin (midpoint <0.10 or >0.90) = min(Qone,Qtwo)        ← two-sided REQUIRED at extremes
Qnormal = Qmin / Σ(all makers' Qmin)   ← your share, per sample
```
- **Sampling: every minute, random**; 10,080 samples/week epoch. Your epoch score = Σ Qnormal; pool paid
  pro-rata to epoch score. Paid daily 00:00 UTC, **$1/market/day floor**.
- `min_incentive_size` + `max_incentive_spread` are per-market, fetchable via CLOB/Markets API.

### ⚠️ The hard truth about "park wide, never fill"
The score is **quadratic in closeness**: at the max-spread edge (`s = v`) → score **0**; at half the max
spread (`s = v/2`) → only **0.25** of max. So orders parked wide to dodge fills earn **almost nothing**, AND
they're diluted by tighter competitors in the `Qnormal` denominator. **You cannot meaningfully farm without
quoting tight, and tight = fillable.** Fill risk is intrinsic, not avoidable. The literal "stale market +
wide orders + never fill" plan ≈ $0 (won't clear the $1 floor) + locked capital. Reframe the goal as:
**quote tight in markets that rarely MOVE, so the tight orders seldom fill and gap risk is low.**

## The real strategy types (ranked by how farmable)

### 1. Slow / long-dated calm-market farming  ← the correct version of your idea
Pick **low-volatility, long-horizon (≥14 days to resolution), no-imminent-catalyst** markets (distant
elections, slow-moving politics, macro). Price barely moves → you can sit **tight** (high quadratic score)
while fills stay rare and any fill mean-reverts. This is the canonical "passive farmer" setup. Realistic
yield from a practitioner's 2-week run: **~10% annualized**, conditional on no black-swan gap.

### 2. Low-competition / high-pool selection  ← where the actual edge is
Rewards split by `Qnormal` share, so **your return = pool ÷ competing depth**. Sort the Rewards page by pool
size; favor **fat reward pool + thin competition**. Early entry on a newly-incentivized market or a low-LP
market lets moderate capital capture a large % of the pool. Crowded markets = thin per-LP returns.

### 3. Sponsored-pool hunting (stacking)
Sponsored USDC **stacks** on native rewards (and multiple sponsors stack). Hunt markets with active
sponsorships → higher $/day for the same quoting effort. Same low-competition selection logic.

### 4. Two-sided tight quoting (avoid the ⅓ penalty)
Always post **both bid and ask** inside `max_incentive_spread`. In [0.10,0.90] single-sided still scores but
is divided by **c=3** (`max(Qone/c,Qtwo/c)`); at price extremes (<0.10 / >0.90) two-sided is **mandatory**.
Two-sided ≈ delta-neutral *until* one side fills unhedged → then you hold directional inventory.

### 5. Spread-width tuning (the yield↔fill dial), per-market by volatility
Tighter `s` → higher score + higher fill rate; wider `s` → fewer fills + sharply lower score. Calm market →
quote tight; approaching a catalyst → widen or pull. There's no free lunch; you're picking a point on the
quadratic.

### 6. Active re-centering / cancel-replace automation
Midpoint drifts → cancel and re-post to stay tight and inside `max_spread`, and **pull before adverse fills**.
Per-minute random sampling means you must be resting **at snapshot moments** — needs a CLOB-API bot
(authenticated order mgmt + monitoring). This is what separates real farmers from manual dabblers.

### 7. Min-size qualification to cap exposure
Post at/just above `min_incentive_size` to qualify while minimizing $ at risk per fill — but lower size →
lower `Qmin` → smaller share. Trade-off between exposure and yield; only works where pool/competition is
favorable enough to still clear $1/day.

### 8. Gamma-aware / hedged farming (advanced)
Every tight quote = **selling gamma/tail risk**. Options: hedge one-sided fills on another venue or the
complementary market, or run it as a genuine MM book. The "delta-neutral farming" label is marketing — it
breaks the instant you get a one-sided fill on a gapping market.

### ❌ Anti-patterns (don't)
- Wide "never-fill" parking → ~0 score (covered above).
- One-sided quoting in the penalty band → ⅓ score for full inventory risk.
- Spraying tiny size across many markets → fail the $1/market floor everywhere.
- Self-trading / spoofing to fake depth → explicitly "discouraged" (penalized/clawed back).

## Economics & reality checks
- **~10% annualized** is a realistic target for the calm-market passive setup (practitioner postmortem);
  not a money printer.
- **Capital floor:** below ~$5k the $1/market/day floors + competition make it uneconomic.
- **Opportunity cost:** pUSD is locked in resting orders — can't be deployed elsewhere.
- Order-queue / survival-analysis fill-avoidance modeling was tried and judged **impractical** on Polymarket
  (can't gather enough probe data; cost > incremental reward) outside a serious HFT stack.
- Consensus: rewards are now a **thin bonus on top of real trading edge**, not standalone alpha — unless you
  have independent edge, treat as a bonus.

## Relevance to us
This is the execution/maker lane the handoffs flagged as the only non-directional opportunity left. Our
mint-and-sell/maker line was survivorship-corrected negative, so before any capital: build a **CLOB-API
quoting bot** (fetch `max_incentive_spread`/`min_incentive_size` per market via Markets API), backtest the
fill-vs-reward trade-off on our L25 book history, and **validate `Qnormal` share + the $1 floor + actual
fill PnL on a tiny live account** in 2–3 low-competition calm markets. Yield ceiling (~10% APR) means it's a
capital-utilization play, not a high-edge one.

## Next steps I can do
- Pull the **live Rewards table via Markets API** (every market's pool $/day, `max_incentive_spread`,
  `min_incentive_size`, current competition) and rank best low-competition / high-pool / slow markets to farm now.
- Spec the CLOB-API quoting + re-center + pull-before-fill bot.

## Sources
- [Liquidity Rewards (scoring formula) — Polymarket Docs](https://docs.polymarket.com/market-makers/liquidity-rewards)
- [Reward Farming Guide — startpolymarket.com](https://startpolymarket.com/strategies/reward-farming/)
- [Two-Week LP Rewards Postmortem — Medium/wanguolin](https://medium.com/@wanguolin/my-two-week-deep-dive-into-polymarket-liquidity-rewards-a-technical-postmortem-88d3a954a058)
- [The Hidden Yield Layer — Medium/Mountain Movers (May 2026)](https://medium.com/mountain-movers/the-hidden-yield-layer-on-polymarket-how-maker-rebates-holding-rewards-and-liquidity-incentives-e2e41972dcb7)
- [Complete Guide to Polymarket LP Farming — Bravado](https://www.bravadotrade.com/blog/polymarket-lp-farming)
- [How to Liquidity Farm on Polymarket — Guru Polymarket](https://gurupolymarket.com/en/tutorials/how-to-liquidity-farm-on-polymarket/)
