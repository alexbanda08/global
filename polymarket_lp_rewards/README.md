# Polymarket LP-Rewards Farming — Research Hub

Self-contained research on farming Polymarket's **Liquidity Rewards Program** (pay-for-resting-orders,
separate from maker rebates). Started 2026-06-03. Come back here.

## Folder map
- `reports/` — the write-ups (read in this order):
  1. `POLYMARKET_LP_REWARDS_RESEARCH_2026_06_03.md` — program overview, payouts, sponsoring.
  2. `POLYMARKET_LP_FARMING_STRATEGY_TYPES_2026_06_03.md` — exact scoring math + strategy taxonomy + the
     "park wide / never fill" myth debunked.
  3. `LP_FARM_LIVE_RANKING_2026_06_03.md` — live market ranking, the empty-book trap, healthy-farm shortlist.
- `scripts/` — reproducible pullers/rankers (run with `py -3`):
  - `lp_rewards_rank.py` — pull CLOB `/sampling-markets`, enrich gamma, rank by reward/competition.
  - `lp_healthy_farms.py` — filter to REAL tight-book + slow + active (the actionable list).
  - `lp_book_analyze.py` / `lp_book_durable.py` — pull order books, compute qualifying depth.
  - `lp_tier1_calc.py` — capital → $/day calc for the token-launch farms.
- `data/` — outputs: `_lp_healthy_farms.csv` (232 healthy farms = main actionable list),
  `_lp_gems.csv`, `_lp_rewards_ranked.csv`.

## The mechanics (what you must know)
- You earn for **resting limit orders near the midpoint** — orders need NOT fill. Paid daily 00:00 UTC,
  **$1/market/day floor**. Per-market `max_incentive_spread` (v) + `min_incentive_size`.
- **Score (quadratic):** `S(v,s) = ((v − s)/v)² · b`. `v`=max spread (¢), `s`=your distance from mid, `b`=in-game
  multiplier (1 pre-game). Beyond `v` → 0. Closeness is everything: at v=2¢, 1¢ off mid loses ~80%.
- **Two-sided weighting:** `Qmin = max( min(Q_yes,Q_no), max(Q_yes/c, Q_no/c) )`, c=3. Single-sided is cut **÷3**;
  at price <0.10 or >0.90 two-sided is **mandatory**. Sampled every minute; pool paid pro-rata to your score share.

## Hard-won conclusions
1. **"Low liquidity / high reward" is mostly a TRAP.** Book pulls showed the top low-liq markets have
   empty books (Qexist=0, 18–80¢ bid-ask gaps). Low liquidity = no price discovery → you'd be the sole MM in
   an illiquid binary → toxic fills + resolution gap >> reward. That's *why* they're uncontested.
2. **A good farm = REAL tight book (price discovery), slow, not overcrowded.** You take a SHARE of the pool
   with low adverse selection — not 100% of an empty pool.
3. **MuddyRC rule (top trader): go perfect 50/50 OR 100% one-sided, never in between.** 50/50 = max yield in
   liquid markets you don't care about. One-sided = ÷3 score BUT you only fill the side you want (dodge toxic
   fills) — use when you have a directional lean. 70/30 is the worst of both. See `MUDDYRC_ARTICLE.md`.
4. **Yield ceiling ~10% APR**; needs ≥~$5k to clear floors; pUSD locked = opportunity cost; rewards are a
   "bonus on real edge," not standalone alpha.
5. **Units caveat:** `/sampling-markets` `rewards_daily_rate` looks **base-only** (may exclude sponsorships).
   Verify each pool on its live Rewards panel before sizing.

## Current best farm targets (2026-06-03, verify live before sizing)
Tier-1 = long-dated **crypto token-launch** markets (slow, tight books, months runway):
- **BULK Jun-30-2027** ($40/day, mid 0.755): $500 ≈ $26/day, $1000 ≈ $31.5/day.
- **Propr Dec-31-2026** ($40, mid 0.83), **Titan Dec-31-2027** ($40, mid 0.555, 576d runway).
- Cheap/thin **Slingshot** rows ($20 pool): $250 captures ~80% (~$16/day).
- ⚠️ These sit in multi-date EVENTS (e.g. "Will BULK launch a token by ___?" has 7 date rows). Farm the
  **mid-priced** rows (0.45–0.80); AVOID the extreme rows (e.g. BULK Jun-2026 @ 2¢ YES = forced two-sided,
  pin risk, near-resolution).

### How to place (example: BULK Jun-2027, mid 0.755, v=4.5¢, min 20 sh)
Two BUY limit orders, tight to mid (band 0.71–0.80):
```
BID YES @ 0.75   (N shares)            ← 0.5¢ below mid
BID NO  @ 0.24   (≡ ASK YES @ 0.76)    ← 0.5¢ above mid
```
Capital ≈ N dollars for N shares/side. Fills = position (long YES or long NO). If you lean YES → post only
the YES side (one-sided, ÷3 score, but only fill what you want).

## Next steps (open)
- Re-pull in a few hours to measure **competition creep** before committing.
- Spec a CLOB-API quoting bot (auth, re-center, pull-before-fill) — needed for per-minute presence.
- Validate `Qnormal` share + $1 floor + actual fill PnL on a tiny live account in 2–3 healthy farms.
