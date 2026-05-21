# Diagnostic — eth_5m_momo_v2 + F7 regression

_Window: post-F7 deploy (2026-05-20 19:57 UTC) through 2026-05-21 15:36 UTC (~20h)._
_Source: `strategy_lab/monitoring/_logs/vps3/momo_resolutions_36h.csv` (2,269 resolutions parsed)._

## Headline (replaces yesterday's "concern")

The "**eth_5m_v2 + F7 collapsed to 6.67% WR on n=45**" line in `NEXT_SESSION_PICKUP_2026_05_21.md` over-counts. Each slug emits **3 resolution rows** (one per HEDGE/HOLD/SELL policy clone), so n=45 events ≈ **15 unique slugs**. Statistical power is ~3× weaker than the headline implies.

Within that, only **5 unique slugs** were v2-only fires; 6 were v1-only; 1 overlapped. The two gates pick **almost entirely different slugs** on eth_5m, so this isn't "F7 doesn't lift v2" — it's "v2's gate selects a structurally different slug population from v1."

## Per-cell breakdown (post-F7 window, apples-to-apples)

|                       | v1 baseline | v1 + F7  | v2 baseline | v2 + F7  |
|-----------------------|------------:|---------:|------------:|---------:|
| n (events)            | 62          | 142      | 54          | 236      |
| WR                    | 53.2%       | **64.1%**| 38.9%       | 43.2%    |
| Sum PnL               | +$130.91    | **+$763.75** | −$345.61  | −$562.86 |
| $/event               | +$2.11      | **+$5.38**| −$6.40      | −$2.39   |

Conclusion: **F7 lift is real and large on v1**. On v2, F7 nudges WR (38.9% → 43.2%) and per-trade loss (−$6.40 → −$2.39) but doesn't reach breakeven. The v2 gate is structurally selecting losing fires that even an RSI confirmation cannot rescue.

## Slug-level pairing on eth_5m + F7

| Bucket            | n unique slugs | WR    | Sum PnL |
|-------------------|---------------:|------:|--------:|
| v1 only           | 6              | 50.0% | +$25.17 |
| v2 only           | 5              | 0.0% DOWN, 50% UP | −$30.70 |
| both v1 and v2    | 1              | 0.0%  | −$50.74 (both legs lost) |

v1 caught the winning DOWN slug at 09:40:33 (entry $0.500 → +$24.50 per leg × 3 policies = +$73.50). v2 fired DOWN on a DIFFERENT slug at 09:41:36 (entry $0.483 → −$1.78 per leg). Distinct slugs, not just timing offset.

## What this means for the deploy decision

1. **v1 + F7** is a clear winner — promote / keep firing it.
2. **v2 + F7** is not a regression of the SAME signal — it's a different signal that loses. Treat v2 as its own gate that needs investigation, not as a "fix F7 for v2" problem.
3. **Don't kill v2 yet on n=15 slugs** — 4 days of clean data needed before retiring it.

## Why v1 and v2 pick different slugs — gate logic

From `data/v4/canonical/_momo_v1v2_backtest.py:6-7` (canonical spec):

| Variant | `ret_2m` formula                        | Fire offset | Window shape |
|---------|-----------------------------------------|-------------|--------------|
| **v1**  | `log(close@(ws+120) / close@ws)`        | `ws + 120s` | forward-only |
| **v2**  | `log(close@(ws+60)  / close@(ws-60))`   | `ws + 60s`  | centered     |

Both gate when `|ret_2m| ≥ q90(rolling 14d)`; signal = sign(ret_2m). The cells diverge in two ways:

1. **v2 fires 60s earlier** — closer to peak-impulse, less time for exhaustion-vs-continuation to resolve before entry.
2. **v2 uses a centered window** — includes 60s of pre-anchor data, so the signal mixes "before" and "after" anchor moves. v1 sees only the forward 120s.

Hypothesis for eth_5m specifically: ETH 5m impulses often mean-revert within the next 60s. v1's extra-60s-wait acts as a tacit "continuation filter" — by ws+120 the reverting fires have fallen below threshold and never fire. v2 fires on those reversion-prone signals, then loses.

Consistent with the data: v1 caught two winning slugs (09:15:44 UP, 09:40:33 DOWN) where v2 never fired. v2 fired on 5 different DOWN slugs that all (or nearly all) reverted.

## Next-session action plan

**This week (clean data accumulating):**

1. Wait for 48h post-fix (≈2026-05-23 18:25 UTC) before computing definitive F7 lift numbers.
2. Pull fresh `momo_resolutions` from VPS3 + Ireland CSVs.
3. Re-run this slug-pairing analysis with n≥30 unique eth_5m slugs.

**If v2+F7 still net-negative after ≥30 slugs:**

- Don't promote v2+F7 cells on eth_5m. Keep firing for research, but rely on v1+F7 lift.
- Test: does same pattern hold for sol_5m_v2 (currently mixed) and btc_5m_v2 (still losing)?

**If v2+F7 swings back to neutral/positive:**

- The 20h sample was small. Continue paper.

**Not yet worth doing:**

- Producing a TV-agent spec to disable v2+F7 cells. v2 sleeves still emit clean signals usable for ensemble research (e.g., "v2 fires AND v1 fires" intersection might be sharper than v1 alone).

## Sources

- `strategy_lab/monitoring/_logs/vps3/momo_resolutions_36h.csv`
- `strategy_lab/monitoring/_scratch_eth5m_v2_diag.py` (per-fire dump)
- `strategy_lab/monitoring/_scratch_eth5m_v1_vs_v2_timing.py` (slug pairing)

## Caveats

- `strike_price` and `settlement_price` are NaN in the resolutions JSON. Could not compute realized move % per fire. Would need to join with `trading_events_30d.parquet` or `data/v4/canonical/resolutions_polymarket_clob.parquet` to do that.
- 20h post-F7 window only. Conclusions for cells with n<10 unique slugs are anecdotal.
- "Slugs where only v2 fired" includes slugs where v1's signal was below threshold OR v1's F7 rejected — can't distinguish from this dataset alone.
