# Polymarket LP / liquidity-rewards farming — fresh research (2026-06-03)

## What the program is
- You earn by **posting limit (maker) orders near the market midpoint** — **orders do NOT need to fill**.
  You're paid just for keeping competitive quotes in the book. (Distinct from **maker rebates**, which only
  pay when your order executes.)
- Rewards paid **daily at 00:00 UTC** to maker addresses. **Min payout $1/market/day** (below = unpaid).
- Each market has its OWN params: **total daily reward pool, max spread (how far from mid still scores),
  min order size**. View them in that market's order book / rewards page.

## How scoring works (the farmable mechanics)
- **Quadratic spread penalty:** score falls off quadratically with distance from the adjusted midpoint →
  tight quotes near mid earn vastly more than wide ones. Sitting at the edge of max-spread earns ~nothing.
- **Two-sided strongly favored:** score uses `min(Q_yes, Q_no)` of your bid/ask depth. One-sided liquidity
  is rewarded at a **reduced rate (÷ c)**; in extreme-probability markets two-sided is **required**.
- **Share, not flat:** your payout = your score / total score on that market × pool. More competitors →
  thinner slice. Returns have **compressed** as the meta matured.
- Methodology ≈ a port of **dYdX's LP rewards** adapted to binary contracts (separate books, no staking,
  per-market isolated pools).

## Extra layer — Sponsored rewards
- Anyone can **sponsor** a market: deposit USDC into a contract that auto-distributes to LPs (e.g. $500/10d
  = $50/day). **Sponsorships STACK** with native rewards → LPs earn the combined pool. Hunt markets with
  active sponsorships for higher yield.
- 2026 scale: Polymarket put **>$5M** into liquidity incentives in a single month (Apr 2026), heavy on
  sports/esports, split Pre-game vs Live pools, pro-rata across eligible markets per game.

## Farming playbook (actionable)
1. **Target high-pool, low-competition markets.** Yield = pool ÷ competing depth. Check each market's
   order-book rewards panel; prefer sponsored + sports/esports pools (biggest money in 2026).
2. **Quote tight & two-sided** near mid (post both bid and ask above min size, inside max spread, as close to
   mid as risk tolerance allows) — quadratic scoring means the tight two-sided quote dominates.
3. **Manage fill/directional risk** — the best-scoring quotes are the most likely to get hit; a fill is a
   real position. Re-center as mid moves; hedge or accept inventory.
4. **Watch the $1 floor** — don't spread tiny size across many markets; concentrate to clear $1/market/day.
5. **Time around events** for sports (Pre vs Live pools reset per game).

## Reality check (important)
- **Not free money.** Top-scoring orders fill most → carry directional risk. Practitioners report yields
  **compressed**; LP rewards are now a **thin bonus on real market-making edge**, not a standalone printer.
- Relevance to us: this is the **maker/execution angle** the handoffs flagged as the only non-directional
  lane left (directional edge = efficient-market dead). But our mint-and-sell/maker line was
  survivorship-corrected negative — re-validate the **rebate share + reward pool math on a live account**
  before committing capital.

## Still to pull (if wanted)
Exact scoring formula + variable names (Qmin, c, b, max_spread bands, `v` order-utility function, in/out
parameters) from the official docs — `docs.polymarket.com/market-makers/liquidity-rewards` and the legacy
`liquidity-mining-and-trading-rewards` page. Say the word and I'll fetch + index the precise math.

## Sources
- [Liquidity Rewards — Polymarket Help Center](https://help.polymarket.com/en/articles/13364466-liquidity-rewards)
- [Liquidity Rewards — Polymarket Docs](https://docs.polymarket.com/market-makers/liquidity-rewards)
- [Sponsor Market Rewards — Help Center](https://help.polymarket.com/en/articles/13755867-sponsor-market-rewards)
- [Liquidity Mining & Trading Rewards (legacy docs)](https://legacy-docs.polymarket.com/liquidity-mining-and-trading-rewards)
- [Polymarket Reward Farming Guide — startpolymarket.com](https://startpolymarket.com/strategies/reward-farming/)
- [Sponsor Rewards explained — TradeInformer](https://tradeinformer.com/broker-news/what-are-sponsor-rewards-on-polymarket-and-how-do-they-work)
- [Two-Week Deep Dive into LP Rewards (technical postmortem) — Medium/wanguolin](https://medium.com/@wanguolin/my-two-week-deep-dive-into-polymarket-liquidity-rewards-a-technical-postmortem-88d3a954a058)
- [The Hidden Yield Layer on Polymarket — Medium/Mountain Movers (May 2026)](https://medium.com/mountain-movers/the-hidden-yield-layer-on-polymarket-how-maker-rebates-holding-rewards-and-liquidity-incentives-e2e41972dcb7)
- [Polymarket Market Making: Earn Passive Income as LP — vpn07](https://vpn07.com/en/blog/2026-polymarket-market-making-liquidity-rewards-passive-income.html)
