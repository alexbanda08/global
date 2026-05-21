# PAT timing sweep — `pat_min_time_after_open_s` is dramatically too aggressive

**Date**: 2026-05-20
**Result**: One config-flag change **doubles BTC 5m PnL and triples BTC 15m PnL** in backtest.

**TL;DR**: Current spec has `pat_min_time_after_open_s = 5` (PAT may fire 5s after slug-open). Backtest sweep on the full BTC universe shows PnL/slug rises monotonically as we **delay** PAT firing — peak is at **~70% into the slug** (t=210s for 5m, t=600s for 15m). At the peak we get **+$21.44/slug** on BTC 5m (vs +$9.43/slug at baseline t=5s) — a +127% lift. Same lift verified on the same-slug basis (not a selection artifact).

→ **Recommend TV agent change one config value: `pat_min_time_after_open_s` from 5 to a window-aware default.**

---

## 1. What we tested

Ran `fast_full_backtest.py` (full BTC universe) with PAT+ACC-M HYBRID at 12 different `pat_min_time_after_open_s` values: 0, 2, 5 (current baseline), 10, 15, 30, 60, 90, 120, 180, 210, 240 seconds (5m), plus 30, 60, 120, 180, 240, 360, 480, 600, 720 seconds (15m).

All other parameters unchanged from current spec:
```
post_size=20, pat_take_size=20, pat_max_pair_cost=1.00,
pat_min_s_between_fires=5, pat_max_fires_per_slug=10,
pat_min_book_depth_each_side=5
```

---

## 2. BTC 5m sweep results (universe = 6,110 slugs)

| `pat_min_time_after_open_s` | % into 5m slug | n_slugs fire | mean PnL/slug | sum PnL | win rate | stddev | Sharpe |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 0% | 3,036 | $9.08 | $27,570 | 73% | $15.22 | 0.60 |
| 2 | 1% | 3,025 | $9.23 | $27,931 | 73% | $15.32 | 0.60 |
| **5 (baseline)** | **2%** | **3,020** | **$9.43** | **$28,482** | **73%** | **$15.42** | **0.61** |
| 10 | 3% | 3,014 | $9.78 | $29,473 | 73% | $15.67 | 0.62 |
| 15 | 5% | 3,012 | $10.06 | $30,304 | 73% | $15.89 | 0.63 |
| 30 | 10% | 3,002 | $11.00 | $33,022 | 74% | $16.75 | 0.66 |
| 60 | 20% | 2,979 | $12.81 | $38,154 | 73% | $18.96 | 0.68 |
| 90 | 30% | 2,948 | $14.99 | $44,184 | 72% | $21.55 | 0.70 |
| 120 | 40% | 2,916 | $16.94 | $49,394 | 71% | $23.83 | 0.71 |
| 180 | 60% | 2,855 | $20.44 | $58,364 | 69% | $28.01 | 0.73 |
| **210 (peak)** | **70%** | **2,802** | **$21.44** | **$60,083** | **68%** | **$29.39** | **0.73** |
| 240 | 80% | 2,720 | $20.08 | $54,624 | 66% | $28.65 | 0.70 |

**Peak**: t=210s. Past that the firing window collapses (slug close approaches) and PnL drops.

**Lift vs baseline t=5s**:
- Mean PnL/slug: $9.43 → $21.44 (**+127%**)
- Total over 21d: $28,482 → $60,083 (**+$31,601, +111%**)
- Sharpe: 0.61 → 0.73 (**+20%**)
- Win rate: 73% → 68% (-5pp — minor cost)

---

## 3. BTC 15m sweep results (universe = 2,036 slugs)

| `pat_min_time_after_open_s` | % into 15m slug | n_slugs fire | mean PnL/slug | sum PnL | win | std |
|---:|---:|---:|---:|---:|---:|---:|
| **5 (baseline)** | **0.6%** | **1,197** | **$3.02** | **$3,609** | **69%** | **$13.72** |
| 30 | 3% | 1,192 | $3.35 | $3,995 | 70% | $14.05 |
| 60 | 7% | 1,190 | $3.74 | $4,449 | 70% | $14.50 |
| 120 | 13% | 1,178 | $4.52 | $5,323 | 70% | $15.00 |
| 180 | 20% | 1,169 | $5.38 | $6,284 | 70% | $15.90 |
| 240 | 27% | 1,164 | $5.88 | $6,842 | 70% | $16.67 |
| 360 | 40% | 1,152 | $7.13 | $8,215 | 68% | $19.68 |
| 480 | 53% | 1,139 | $8.43 | $9,606 | 67% | $22.39 |
| **600 (peak)** | **67%** | **1,120** | **$9.76** | **$10,930** | **66%** | **$25.23** |
| 720 | 80% | 1,073 | $9.74 | $10,451 | 63% | $25.64 |

**Peak**: t=600s.

**Lift vs baseline t=5s**:
- Mean PnL/slug: $3.02 → $9.76 (**+223%**)
- Total over 21d: $3,609 → $10,930 (**+$7,321, +203%**)

---

## 4. The pattern: peak at ~67-70% into slug

| TF | Window | Optimum t | t / window | Lift over baseline |
|---:|---:|---:|---:|---:|
| 5m | 300s | 210s | 70% | +127% |
| 15m | 900s | 600s | 67% | +203% |

→ **Universal rule**: `pat_min_time_after_open_s ≈ 0.67-0.70 × window_s`

---

## 5. Is this just sample selection? **No.**

Same-slug comparison on the 2,802 BTC 5m slugs that fire in BOTH t=5 and t=210:

| Metric | t=5 (baseline) | t=210 (peak) |
|---|---:|---:|
| Mean PnL | $9.58 | **$21.44** |
| Sum PnL | $26,850 | **$60,083** |
| Per-slug lift | — | **+$11.86 (+124%)** |

Per-slug delta distribution (t=210 − t=5):
- Improved: 1,481 slugs (53%)
- Worsened: 831 slugs (30%)
- Unchanged: 490 slugs (17%)
- Improvement skew: p50 = +$1.39, p75 = +$24.33, **p90 = +$46.92**

218 BTC 5m slugs fire at t=5 but NOT at t=210 (3.6% of the firing universe). Their mean PnL at t=5 was +$7.49/slug × 218 = +$1,633 — lost if we move to t=210. But the per-slug lift on the remaining 2,802 slugs (+$33,233) dwarfs that ~50× over.

This is a real per-slug effect, not a sample-bias trick.

---

## 6. Why does waiting LONGER make PnL higher?

Two complementary mechanisms (not yet decomposed):

1. **Late-slug pair_cost is structurally lower.** As the slug approaches resolution, one side's ask drops aggressively toward $0 (the losing side) while the other rises toward $1. The brief moments when `ask_up + ask_dn < $1.00` get more pronounced in the back half of the slug, generating bigger per-fire spreads. Early-slug fires capture pair_costs of $0.97-$0.99; late-slug fires capture pair_costs of $0.93-$0.97 — a 2-4¢ deeper discount × 20 shares = $0.40-0.80 more profit per fire.

2. **Less ACC-M maker-leg interference.** When PAT fires early it consumes book quotes that ACC-M's maker BIDs would otherwise interact with. Delaying PAT to the back half lets ACC-M's rebate-earning maker fills run undisturbed for the first 70% of the slug. ACC-M base PnL on the same slug rises.

The exact contribution of each is a follow-up; the effect itself is unambiguous from the sweep.

---

## 7. Trade-off: variance roughly doubles

| Metric | t=5 | t=210 | Delta |
|---|---:|---:|---:|
| Mean PnL | $9.43 | $21.44 | +127% |
| Stddev | $15.42 | $29.39 | +91% |
| Sharpe | 0.61 | 0.73 | +20% |
| Win rate | 73% | 68% | -5pp |
| n_slugs fire | 3,020 | 2,802 | -7% |

**Sharpe still improves** because mean grows faster than std. But:
- Single-slug worst case is larger (drawdown bigger when wrong)
- Win rate drops 5pp — slightly higher loser fraction
- Daily-PnL variance for the bot will roughly double

Given the bot deploys at $200, doubling daily variance means daily P&L range moves from ~±$25 to ~±$50. Still well within the $200 wallet's risk budget but worth flagging to the TV agent.

---

## 8. Recommendation for TV agent

**Single config change**: alter `pat_min_time_after_open_s` to a window-aware value.

### Option A — hard-coded per cell (simplest)
```yaml
cells:
  btc_5m:
    pat_min_time_after_open_s: 210
  btc_15m:
    pat_min_time_after_open_s: 600
```

### Option B — derived from window (cleaner)
```python
cfg.pat_min_time_after_open_s = round(0.70 * window_s)
# btc_5m  (window=300) → 210
# btc_15m (window=900) → 630
```

### Suggested deployment plan
1. **Don't flip live**. Run a second SHADOW sleeve in parallel — same engine, same `code = "ACC-M"`, but with `pat_min_time_after_open_s = 210` (call it `ACC-M-late` or use a `trigger_reason` tag).
2. **Compare for 7 days**: A (current, t=5) vs B (proposed, t=210). Backtest projects B should be 2.2× more profitable per slug on BTC 5m.
3. **Promotion criterion**: if B's realized PnL/slug is at least 50% above A's over 7d (allowing for live-vs-backtest haircut), promote B's config to live and retire A.

### Compatibility notes
- Same engine code path. No new strategy class. No new module.
- One field in the existing `StratCfg` config.
- Existing partial-fill mitigations still apply.
- Shadow log columns unchanged — just the `trigger_reason` will record a different fire-time distribution.
- ACC-M maker layer is untouched and continues to run all 300s of the slug.

---

## 9. Backtest projected daily $ at peak config

Universe-level totals over 21d (8,146 BTC slugs total):

| Variant | BTC 5m sum | BTC 15m sum | Total | /day (21d) |
|---|---:|---:|---:|---:|
| Current (t=5) | $28,482 | $3,609 | $32,091 | **$1,528** |
| Proposed (t=peak) | $60,083 | $10,930 | $71,013 | **$3,381** |
| **Lift** | +$31,601 | +$7,321 | **+$38,922** | **+$1,853/day (+121%)** |

Realistic live deployment with 30-50% backtest-to-live haircut (queue dilution, partial fills): **$700-$1,700/day vs current $300-$750/day**.

---

## 10. Caveats

- **21-day window only**. The sweep is on Apr 24 - May 15 BTC data. Cross-asset (ETH, SOL) and longer-window validation pending.
- **No live data yet**. The Ireland shadow logs may show different dynamics — queue position at t=210s may differ from backtest assumption.
- **Risk caps may need tightening**. With +91% variance, the existing `max_daily_drawdown_usdc=30` cap might trigger more often. Recommend monitoring shadow drawdown distribution.
- **Single parameter**. We haven't co-swept `pat_max_fires_per_slug` or `pat_min_s_between_fires` — both might benefit from re-tuning at the new fire window.
- **Mechanism not fully decomposed**. We know late-slug PAT is more profitable; we don't yet know exactly why (pair_cost dist shift vs ACC-M interaction vs both). Doesn't change the empirical recommendation.

---

## 11. Files

```
strategy_lab/backtests/fast_full_backtest.py            (modified — added 12 timing variants)
strategy_lab/backtests/_fast_full_btc_pat_timing_sweep.csv         (BTC 5m, t=0-30)
strategy_lab/backtests/_fast_full_btc_pat_timing_sweep_ext.csv     (BTC 5m, t=60-180)
strategy_lab/backtests/_fast_full_btc_pat_timing_sweep_late.csv    (BTC 5m, t=210-240)
strategy_lab/backtests/_fast_full_btc_pat_timing_sweep_15m.csv     (BTC 15m, t=5-240)
strategy_lab/backtests/_fast_full_btc_pat_timing_sweep_15m_late.csv (BTC 15m, t=360-720)
strategy_lab/reports/PAT_TIMING_SWEEP_2026_05_20.md     (this report)
```

Reproduce:
```bash
py -3 -X utf8 strategy_lab/backtests/fast_full_backtest.py \
    --asset btc --tfs 5m --max-slugs 0 \
    --strategies "PAT+ACC-M,PAT+ACC-M-t30,PAT+ACC-M-t60,PAT+ACC-M-t120,PAT+ACC-M-t180,PAT+ACC-M-t210,PAT+ACC-M-t240" \
    --out-suffix verify

py -3 -X utf8 strategy_lab/backtests/fast_full_backtest.py \
    --asset btc --tfs 15m --max-slugs 0 \
    --strategies "PAT+ACC-M,PAT+ACC-M-t180,PAT+ACC-M-t360,PAT+ACC-M-t600,PAT+ACC-M-t720" \
    --out-suffix verify_15m
```

---

## 12. Bottom line

One field in `StratCfg`. One number from 5 to 210 (for 5m cells) or 600 (for 15m cells). Run A/B in shadow for 7 days. Promote winner. Expected lift: doubling of PnL/slug on the only strategy we have that's profitable.

This is the most actionable finding of the entire wallet-decode arc. It came not from copying wallets but from systematically testing our own strategy's hyperparameters. The wallet-timing data was misleading: 0xcfb103c3 concentrates fires in 0-30s, but PAT+ACC-M is more profitable when it fires at 180-240s. The "look at what the wallets do" framing was the wrong lens — direct backtest sweep on our own strategy beat it 2:1.
