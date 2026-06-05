# Live LP-farm ranking + the empty-book trap (2026-06-03)

Pulled all live reward markets (CLOB `/sampling-markets`, 2,694 reward-active mid-price markets), enriched
with gamma liquidity/spread/volume, and **pulled real order books** for the top low-competition candidates.

## 🚨 The big finding: "low liquidity / high reward" is mostly a TRAP
The $11-liquidity / $59-day "gem" (ISM PMI) and nearly every top low-liq market have **empty order books**.
Book pull on the durable low-liq set: **Qexist = 0** (zero qualifying depth inside the 4.5¢ band) and bid-ask
spreads of **18–80¢**:
```
daily$  bid   ask   spread   question
105    0.53  0.71   18¢     NatGas hit LOW $3.00 in June
 40    0.17  0.90   73¢     Goldman Q2 IB fees ...
 40    0.09  0.76   67¢     BAC Q2 provision ...
 40    0.11  0.91   80¢     Morgan Stanley Q2 IB revenue ...
```
**Low liquidity = no price discovery, not a free pool.** If you post tight two-sided there you become the
**only market maker in an illiquid binary** → you get filled on one side at a price you're guessing, and it
settles to 0 or 1. The adverse-selection + resolution-gap risk is exactly **why these are uncontested** —
sophisticated farmers avoid them; the $40–105/day doesn't pay for the tail. The "100% share → full pool"
estimate is real only if you never get filled, which in a no-book binary you will.

**Reframe:** a good farm needs a **real tight book (price discovery exists → fair mid, near-fair/reversible
fills)** that's **not overcrowded** — not an empty book.

## ✅ HEALTHY farms (tight real book + active volume + slow), ranked
Filter: dte≥10, reward≥$10/day, mid-price 0.12–0.88, **gamma spread ≤ max_spread band** (real quotes inside
the qualifying zone), vol24h≥$200, liq≥$300. 232 markets. Full list: `cache/_lp_healthy_farms.csv`.

### Tier 1 — best risk-adjusted: long-dated CRYPTO TOKEN-LAUNCH markets
Slow (months→1.5yr runway), tight books (1–3¢), no single gap catalyst, moderate competition:
| daily$ | liq$ | spr¢ | dte | price | market |
|--:|--:|--:|--:|--:|---|
| 20 | 313 | 2 | **576** | 0.41 | 3jane launch a token by Dec 31 2026 |
| 40 | 1805 | 2 | 211 | 0.83 | Propr launch a token by Dec 31 2026 |
| 20 | 423 | 1 | 211 | 0.53 | Curvance launch a token by Dec 31 2026 |
| 20 | 484–645 | 3 | 119–576 | 0.59 | Slingshot launch a token (Sep26/Mar27/Dec27) |
| 40 | 2400 | 1 | **576** | 0.56 | Titan launch a token by Dec 31 2027 |
| 40 | 2408 | 1 | 211 | 0.51 | BULK launch a token by Dec 31 2026 |
Why: longest runway, no abrupt catalyst (launch news is gradual), real but thin competition → you hold a
meaningful share for weeks/months. Lowest gap risk of the whole field.

### Tier 2 — long-dated elections (bigger pools, more competition)
| daily$ | liq$ | spr¢ | dte | market |
|--:|--:|--:|--:|---|
| 101 | 4120 | 2 | 226 | Bola Tinubu — 2027 Nigerian Presidential |
| 98 | 4888 | 1 | 226 | Peter Obi — 2027 Nigerian Presidential |
| 132 | 6981 | 1 | 75 | Loranne Ausley — Tallahassee mayoral |
Slow, healthy books; competition (liq $4–7k) means you take a slice, but $100+/day pools.

### Tier 3 — fat pools but GAPPY (only with active pull-before-fill automation)
Commodity/index "hit $X in June" touch markets — biggest pools, but the underlying moves fast → fill/gap risk:
| daily$ | liq$ | dte | market |
|--:|--:|--:|---|
| **200** | 12–17k | 27 | WTI Crude hit HIGH $110 / $115 / LOW $85 in June |
| 119 | 6648 | 27 | SPY hit LOW $740 in June |
| 106 | 5516 | 27 | Silver hit LOW $70 in June |
| 93 | 3547 | 27 | Gold hit LOW $4,300 in June |
Also earnings-metric (bank Q2, Kroger Q1) — calm now, **gap hard on the earnings date** → pull before it.

## How to actually farm these (mechanics)
- Quote **two-sided, inside max_spread (mostly 4.5¢), above min_size (20–50 sh ≈ $10–25/side)**, near the
  **real** mid (only where a real mid exists — Tier 1/2).
- Reward ≈ your `Qmin` share × daily pool, sampled every minute → keep orders resting; re-center as mid drifts.
- Spread capital across **several Tier-1 token-launch markets** to stack $20–40/day pools at low gap risk.
- **Never** quote the empty-book Tier-trap markets without accepting you're the sole MM (sell-gamma into a binary).
- ⚠️ Units caveat: `/sampling-markets` `rewards_daily_rate` looks **base-only** (Lula-nomination $5/day here vs
  $68 on the rewards page) — it may exclude active **sponsorships**. Verify each target's live pool on its
  Rewards panel before sizing.

## Artifacts
- `cache/_lp_rewards_ranked.csv` (top 120 by reward), `cache/_lp_gems.csv` (low-liq, with trap), 
  `cache/_lp_healthy_farms.csv` (232 healthy farms — the actionable list).
- Scripts: `lp_rewards_rank.py`, `lp_book_analyze.py`, `lp_book_durable.py`, `lp_healthy_farms.py`.
