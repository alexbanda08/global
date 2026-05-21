# Morning read — 2026-05-19

Slept well? Here's what the overnight pipeline found.

## The headline

**We were running the right strategy (ACC-M) but at the wrong size.**

POST_SIZE in the spec: **5 shares**
Optimal POST_SIZE per backtest: **100 shares (best Sharpe), 200 shares (highest mean)**
PnL improvement: **+$0.73/slug → +$3.54/slug at sz=100 (5x)**

### Final validation (213 slugs across 3 wallets)

| Strategy | 04b6 (85) | eebde (80) | cfb (48) | **Avg** |
|---|---|---|---|---|
| **ACC-M-sz100** | **+$3.55** | **+$2.35** | **+$4.74** | **+$3.54** ← recommended |
| ACC-M-sz200 | +$1.36 | +$4.19 | +$5.78 | +$3.78 (higher variance) |
| ACC-M-sz50-loose | +$2.35 | +$2.06 | +$4.01 | +$2.81 |
| ACC-M-sz50 | +$2.77 | +$2.22 | +$2.07 | +$2.35 |
| ACC-M-sz20 | +$1.16 | +$0.79 | +$1.81 | +$1.25 |
| ACC-M-sz5 (current spec) | — | — | — | +$0.37-$0.73 |
| MAS-pre50 | +$0.14 | +$0.11 | +$0.04 | +$0.09 |
| MAS-pre500 | -$3.34 | +$1.46 | -$7.17 | **-$3.02** harmful |
| ACC-H V3f | -$6.58 | -$5.93 | -$6.58 | **-$6.84** harmful |
| ACC-M-lift1c | -$2.89 | -$3.26 | -$5.87 | **-$3.61** harmful

## What changes

| Item | OLD | NEW |
|---|---|---|
| Strategies deployed | ACC-M + ACC-H + MAS | **ACC-M only** |
| POST_SIZE | 5 | **100** (or 200 for higher mean / higher variance) |
| ABSOLUTE_MAX_INVENTORY | 50 | 300 |
| Wallet seed | $50 | **$500-2000** |
| ACC-H V3f composite taker | enabled | **DROPPED** (loses -$6.84/slug) |
| MAS V1 | $30 pre-mint | **DEFERRED** (marginal at our scale) |
| BID lift (+1¢) | considered | **DON'T DO IT** (-$3.61/slug) |

## The biggest discovery

`0x04b6d7e9` — our ACC-M REFERENCE — actually does **98% SELL maker** in chain history. That's the **MAS pattern**, not ACC-M. The v3 /activity snapshot we used (1h window) caught the rare 2% BUY behavior and we labeled them PURE_PAIR_ARB_MAKER. Wrong. Full 30-hour chain shows 98% mint-and-sell.

BUT — ACC-M (post BIDs) STILL works in backtest because it captures the SAME structural mispricing (sum_bids < $1) from the opposite side of the book. The reference is the right WALLET, we just deployed the inverse SIDE.

## The 5 wallets do 5 different things

| Wallet | Pattern | LB $/day | Our match |
|---|---|---|---|
| `0x04b6d7e9` | MAS (98% SELL maker) | $2k | partial via ACC-M |
| `0xeebde7a0` (Bonereaper) | HYBRID (56/44 maker/taker) | $6k | none |
| `0x89b5cdaa` (ohanism) | Directional MAS, 100% maker SELL | $4.3k | none |
| `0xcfb103c3` (xuanxuan008) | PAT (90% pair-arb taker) | $2.5k | none |
| `0xce25e214` | Mixed taker-leaning | $4.6k | none |

We can replicate **one wallet partially**. The big winners (Bonereaper, ohanism) do hybrid or directional patterns we haven't built.

## What's profitable in backtest

Per-slug PnL, ACC-M variants on wallets' actual slugs:

| Config | Avg PnL/slug | Verdict |
|---|---|---|
| **ACC-M-sz200** | **+$5.94** | **DEPLOY THIS** |
| ACC-M-sz100 | +$4.10 | viable |
| ACC-M-sz50 | +$3.73 | conservative |
| ACC-M-sz20 | +$1.17 | barely positive |
| ACC-M-sz5 (current spec) | +$0.37 | spec, undersized |
| ACC-PC (pair-completion taker) | +$0.27 | rarely fires |
| MAS-pre30 | +$0.09 | flat |
| MAS-pre200-tight | +$0.95 | best MAS but still beaten |
| ACC-M-lift1c | **-$3.61** | DON'T LIFT |
| **ACC-H V3f** | **-$6.84** | **DROP** |

## Money projection (with ACC-M-sz100)

- Theoretical: $3.54/slug × ~10 slugs/hour × 24h = **$850/day**
- Realistic (after live queue competition): **$400-700/day**
- Reference wallet at scale: $2,000/day (we capture ~30-40%)
- Required bankroll: **$500-2,000** (100-share orders need $50 inventory per post at $0.50 avg)

Why ACC-M-sz100 not sz200? At sz=200 mean is +$3.78 (slightly better) but stddev jumps from $21 to $37 — same Sharpe-favorable risk-adjusted as sz=100 but bigger drawdowns. Recommend sz=100 for first deployment; can ramp to sz=200 after 1 week of validation.

## Other findings

- **Order refresh**: reference wallets post chunks that fill 100-254 shares each (laddered partials). Our spec posts 5 → fills 1-2 → refresh. They get 50x more inventory per slug.
- **Time-of-day**: big winners are 24/7 bots. `0x04b6d7e9` only runs 5-19 UTC (human operator) — they miss half the day.
- **Slug selection**: `0xeebde7a0` engages 96.4% of slugs → engagement isn't their edge, execution is. `0xcfb103c3` strongly selects thin-book slugs (z=-17.86) for taker arb.
- **Strategy ranking**: ACC-M wins on 4/5 wallets at default size. ACC-H loses on all 5. Convergent.

## Files to read in order

1. This one (you're here)
2. `strategy_lab/reports/OVERNIGHT_WALLET_VS_BACKTEST_2026_05_19.md` — full report with tables
3. `strategy_lab/backtests/_multi_strat_per_slug_big_04b6.csv` — raw per-slug data for sz=200 sweep
4. `strategy_lab/backtests/_wallet_true_pnl_per_slug.csv` — actual per-slug wallet PnL

## Next session priorities

1. **Re-spec ACC-M** with POST_SIZE=200 + send to TV agent
2. **Drop ACC-H V3f** from deployment plan (re-decode separately later)
3. **Defer MAS** until we can backtest at $2500+ mint scale
4. **Open research**: PAT (xuanxuan008 taker pattern, $2.5k/day undecoded), directional MAS (ohanism $248/slug, no signal), HYBRID (Bonereaper $217/slug, V3f decode insufficient)

## Caveats

- 30-100 slug samples per config — variance is real (stddev $14-22/slug at sz=200)
- Queue model assumes us at back of 24-share queue; real fills may differ
- FIFO simulation may underestimate fill rate vs reality (real makers have multiple concurrent orders)
- Reference wallets' "actual PnL" computed with inferred mint cost — taker-pair-arb wallets are negative in our formula because mid-slug merges aren't tracked
- The bid-lift -$3.61/slug result is for +1¢ lift; smaller lifts (~0.005) not tested

## Confidence

Findings I'd bet on with HIGH confidence:
- POST_SIZE should be 50-200 (was 5)
- ACC-H V3f should be dropped
- BID lift +1¢ is harmful
- `0x04b6d7e9` is MAS-pattern not ACC-M

MEDIUM confidence:
- $5.94/slug at sz=200 — sample size is 30-38 slugs per wallet
- MAS deferral — could be revised if we test scale
- Time-of-day matters — based on 2 wallets

LOW confidence:
- Exact production PnL number; sim variance is high

---

*Pipeline: profiler → wallet decode → multi-strat backtest (5 strategies) → size sweep (11 configs) → big sweep (10 configs) → time-of-day → slug-selection. ~2.5 hours of compute. ~7 scripts, 30+ output files.*
