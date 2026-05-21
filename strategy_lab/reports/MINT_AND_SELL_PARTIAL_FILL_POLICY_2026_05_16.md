# Mint-and-Sell — Partial-Fill Exit Policy Analysis

_2026-05-16. Answers the question raised in session: "if >50% of fires only
get 1 leg, can we improve PnL by market-selling the unfilled leg at 60s
instead of holding to settlement?"_

**TL;DR — Market-exit makes things strictly worse.** Across all 6 cells
(BTC/ETH/SOL × 5m/15m), market-selling the unfilled leg at fire+60s costs
$1-4/op MORE than just holding. The reason: when only one leg fills, the
unfilled side's book is extremely thin (mean `best_bid / best_ask = 0.40-0.59`).
Crossing that spread + paying taker fee bleeds harder than the directional
variance of holding does.

---

## The economic question

Mint-and-sell fires when `sum_asks > $1` on a Polymarket up-down market.
We mint $N of pairs ($1 each) and post limit SELL on both legs at their
respective `best_ask`. Three outcomes within 60s:

| Outcome | BTC 15m freq | What happens |
|---|---|---|
| BOTH legs fill | 37.3% | Lock in `(sum_asks − 1) × N` profit + 2× maker rebate |
| ONE leg fills | 57.9% | Naked on the unfilled side; today we HOLD to settlement |
| NEITHER fills | 4.8% | `mergePositions(N)` recovers mint, gas-only loss |

The session question: when ONE leg fills, can we improve by market-selling
the unfilled leg at the prevailing `best_bid` at fire+60s?

## Three policies tested

For each opportunity we evaluate:

- **HOLD** — current strategy; hold unfilled leg to chainlink resolution
- **MARKET_EXIT** — at fire+60s, market-sell unfilled leg at `best_bid`,
  pay taker fee on that leg
- **HYBRID** — market-exit IFF `best_bid_unfilled / best_ask_unfilled ≥ 0.97`
  (tight book); otherwise hold

PnL formulas (notional `N`, `n_pairs = N`):

```
BOTH fills:
  pnl = n × (ask_up + ask_dn) + reb_up + reb_dn − n × $1

ONE fills (e.g. Up filled, Down held):
  pnl_HOLD       = n × ask_up + reb_up + (n × $1 if Down wins else 0) − n
  pnl_MKT_EXIT   = n × ask_up + reb_up + n × bid_dn(t=fire+60s)
                   − n × taker_fee(bid_dn) − n
  pnl_HYBRID     = pnl_MKT_EXIT if bid_dn/ask_dn ≥ 0.97 else pnl_HOLD

NEITHER fills:
  pnl = 0 (merge recovery, gas negligible)
```

Outcome truth: canonical `outcome` column (chainlink-derived).
Fee model: corrected per session — maker pays $0 + receives 20% rebate
(positive income); taker pays full `0.07 × p × (1−p)`. Per `strategy_lab/fees.py`.

## Results — consolidated across 6 cells

Notional = $200, sample = 800 opportunities/cell (4,800 total), window = 21 days.

| Policy | Total PnL | Mean/op | Std/op | Sample-extrap $/day |
|---|---|---|---|---|
| HOLD | −$36,378 | −$7.58 | $54 | −$1,732 |
| **MARKET_EXIT** | **−$44,531** | **−$9.28** | **$22** | **−$2,121** |
| HYBRID | −$37,161 | −$7.74 | $54 | −$1,770 |

MARKET_EXIT trades variance (std $54 → $22) for $1.70/op extra loss in
the mean. HYBRID is statistically indistinguishable from HOLD because
only 1.6-6.8% of partials have tight enough books to trigger the exit.

Per-cell:

| Cell | n | %BOTH | held_WR | exit_ratio | HOLD $/day | MKT_EXIT $/day | HYBRID $/day |
|---|---|---|---|---|---|---|---|
| btc_5m | 800 | 47.0% | 17.6% | 0.42 | −$209 | −$293 | −$210 |
| btc_15m | 800 | 37.0% | 27.9% | 0.57 | −$199 | −$326 | −$209 |
| eth_5m | 800 | 48.4% | 17.4% | 0.40 | −$294 | −$343 | −$300 |
| eth_15m | 800 | 33.2% | 28.3% | 0.58 | −$296 | −$312 | −$301 |
| sol_5m | 800 | 34.0% | 19.5% | 0.41 | −$421 | −$487 | −$425 |
| sol_15m | 800 | 20.8% | 28.8% | 0.59 | −$313 | −$355 | −$324 |

`held_WR` = win rate of held side on partial fills. `exit_ratio` = mean
`best_bid_unfilled / best_ask_unfilled` at fire+60s.

## Three load-bearing insights

### 1. `held_win_rate ≈ 17-29%`, never close to 50%

When only ONE leg fills, the leg that filled is almost always the
**likely-winning side** (whichever side the market thinks will win attracts
the most impatient takers). We're left holding the **less-likely side**,
which is correctly priced to lose more often than win.

Across cells: 5m markets have ~18% held_WR; 15m markets have ~28%. Shorter
timeframes are noisier (more extreme asymmetry between sides), so 5m
partial fills are even worse for HOLD.

This makes HOLD a **known-negative-EV** bet on partial fires.

### 2. `exit_ratio ≈ 0.40-0.59` — books are extremely thin on the unfilled side

When one leg's bid never crossed your ask, that side's book is sparse
(otherwise the bid would have moved). The `best_bid` you'd exit at is
roughly **half** the `best_ask` you posted. That's a 50¢ spread on a $0.50
share — catastrophic for a market exit.

Only 1.6-6.8% of partials have `bid/ask ≥ 0.97` (HYBRID threshold). So
selectivity doesn't save us.

### 3. Edge-bucket breakdown — there is no regime where MARKET_EXIT wins decisively

Looking at the 0.5-1¢ edge bucket on the 15m markets, HOLD is actually
**positive** in 2 of 3 cells (eth_15m: +$1.07/op, sol_15m: +$2.95/op).
This is the sweet spot — modest sum_asks > $1, market relatively balanced,
partial fills closer to 50/50.

At the wide-edge end (`> 5¢` bucket), MARKET_EXIT does beat HOLD (e.g.
−$10.99 vs −$19.79 on BTC 15m). But the right action at extreme sum_asks
**isn't to fire and exit, it's to NOT FIRE in the first place**. Extreme
sum_asks correlate with asymmetric pricing, where partial-fill economics
are systematically bad.

## Implications for strategy

1. **Do NOT add a market-exit policy** to the TV agent's mint-and-sell
   engine. The unfilled side's book is too thin to exit profitably.

2. **The strategy's positive EV depends entirely on BOTH-fill economics**
   being big enough to overcome partial-fill drag. Wallets that profit at
   $10k–$344k/day are presumably:
   - Firing at lower sum_asks (~$1.010 median per handoff) where the
     scanner currently filters out due to the maker-fee bug
   - Maybe sizing smaller per fire so partial-fill variance averages out
     across more samples
   - Possibly entry-filtering by side balance / book depth

3. **Action items for TV agent**:
   - Stick with the spec'd HOLD-on-partial behavior
   - DO NOT implement the "market-sell at +60s" fallback I suspected might help
   - Consider adding a side-balance entry filter — e.g. don't fire when
     `max(ask_up, ask_dn) > 0.80`. This skips the asymmetric regime where
     partials are most punishing
   - Still pending: fix the maker-fee bug (handoff §1) so the scanner
     stops rejecting profitable sub-$1.035 fires

4. **Better hypothesis to test next**: an *entry-filter* improvement vs an
   *exit-policy* improvement. Specifically:
   - Filter A: only fire when `min(ask_up, ask_dn) ≥ 0.20` (balanced market)
   - Filter B: only fire when `bid_up + bid_dn > 0.95` (both legs have
     real bid support → partial fill less likely)
   - Filter C: only fire when sum_asks ∈ [1.005, 1.025] (matches observed
     wallet behavior, avoids asymmetric extreme-edge regime)

   Re-run the existing scan with these filters and measure all 3 policies.
   Expected: HOLD with Filter C lifts toward positive territory, market-exit
   still loses.

## Files

- Backtest script: `strategy_lab/wallet_hunt/replicate/partial_fill_policy_compare.py`
- Per-cell results: `data/v4/canonical/_results/mint_and_sell_<cell>_2026_05_16/policy_compare.parquet`
- Consolidated: `data/v4/canonical/_results/_policy_compare_consolidated.csv`
- Run log: `data/v4/canonical/_results/_policy_compare_run.log`

## Caveats

1. **Sample-extrapolation $/day** is misleading. We're sampling 800/cell
   from 26k-83k opportunities then scaling 21d/800. Real numbers depend on
   capital constraints and how many simultaneous fires you can support.
2. **The absolute PnL is negative for all policies** because the scanner's
   entry threshold is ~$1.035 (per the maker-fee bug, handoff §1). The
   wallets fire at $1.010 median where rebate-as-income flips them positive.
   The policy COMPARISON is the load-bearing finding; the absolute numbers
   need the fee-model fix to match observed wallet PnL.
3. **`held_win_rate` is computed against chainlink-derived `outcome`** —
   matches the real market settlement to within 300/300 wallet rows tested
   per handoff. No survivorship bias.
4. **No latency model** on the market-exit leg. Real exit would suffer an
   additional ~85ms slippage; we assumed instantaneous fill at the visible
   bid. Real numbers for MARKET_EXIT would be slightly worse than reported.
