# "Mastering Polymarket LP Rewards: Spread, Penalties, and Yield" — MuddyRC

Source: X article by @MuddyRC (self-described Top 0.1% Polymarket trader), 2026-04-15.
Tweet: https://x.com/MuddyRC/status/2044462166107938966 (links X article 2043440249708199936).
Pulled via X syndication / fxtwitter API (page is JS-gated). Full text below (lightly condensed).

## Intro
A lot of people try to provide liquidity on Polymarket and end up getting **rekt**. It looks easy: place
dozens of limit orders, wait for rewards. Then the yield is lower than expected, you get **filled on toxic
orders**, and end with negative PnL. This happens because most people don't understand the underlying
mechanics.

## 1. Liquidity Score — tight spread is king
- Each market has its own fixed reward pool. The system scores all users and splits rewards by **relative
  score share**. Higher score = bigger share. (Orders must be above the market's **min share threshold** to count.)
- Formula: **S(v, s) = ((v − s)/v)² · b**
  - S = score, v = max eligible spread (wider = zero), s = your spread from mid, b = in-game multiplier (pre-game = 1).
- **Quadratic decay**: rewards drop off a cliff as you move off mid. At v=2¢, an order 1¢ away loses ~80%.
  Tightening 2¢→1¢ at v=3 **quadruples** your score (0.11 → 0.44).

## 2. The penalty function — the hidden trap
- For mid-price in [0.10, 0.90]: **Q_min = max( min(Q1, Q2), max(Q1/c, Q2/c) )**, Q1/Q2 = each side's score,
  **c = 3**.
  - Perfectly two-sided → take the **min** of the two sides.
  - Strictly one-sided → score slashed to **a third** (÷3).
- **The secret most miss:** unless you keep a perfectly balanced book, you may be **better off going 100%
  one-sided** — especially when you have a preferred side. Quoting only the side you want saves you from
  toxic fills on the wrong side.

## 3. 50/50 vs one-sided (example: $1000, market 0.1–0.9, v=3)
- **50/50 split** → maximizes absolute yield (no penalty). Use in highly liquid markets where you don't care
  which side fills.
- **100% one-sided** → only ÷3 penalty, but you only get filled on the side you want. Use when you have a
  preferred side.
- **70/30 split** → worst of both worlds (penalized like one-sided AND you still eat unwanted fills).
- "Don't get caught in the middle."
- At extreme odds (outside [0.10, 0.90]) one-sided scores **zero** → you MUST be two-sided.

## 4. Key takeaways
- LPing is a math game.
- Keep spreads **razor-thin** to beat the quadratic decay.
- Either commit to **perfect 50/50** or go **100% one-sided** — avoid anything in between.

## Our notes
- Confirms our independent finding: "low liquidity / high reward" markets are uncontested because the fills
  are toxic (no price discovery). The empty-book gems are a trap.
- Actionable for us: even a WEAK directional lean lets us farm **one-sided** — collect ÷3 rewards AND only
  fill the side we'd want. Turns our (dead) directional research into a fill-selection tool.
