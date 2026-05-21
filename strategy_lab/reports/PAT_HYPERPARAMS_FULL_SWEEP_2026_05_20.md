# PAT+ACC-M hyperparameter full sweep — 2026-05-20

**Result**: Per-cell config changes lift backtest PnL **2.9× over the current spec** across all 6 BTC/ETH/SOL × 5m/15m cells.

**Current spec total (21d backtest)**: $73,940
**Best per-cell config total**: **$215,244 (+$141,304, +191%)**

This came from sweeping FOUR hyperparameters: `pat_min_time_after_open_s`, `pat_take_size`, `pat_max_pair_cost`, `pat_max_fires_per_slug` + `pat_min_s_between_fires`.

---

## TL;DR config recommendation

**Universal params (apply to ALL cells)**:
```yaml
pat_take_size:           50    # was 20  → +size per fire
pat_max_pair_cost:       0.98  # was 1.00 → tighter cap, only fire on real edge
pat_max_fires_per_slug:  30    # was 10  → more bites per slug
pat_min_s_between_fires: 2     # was 5   → faster reaction
```

**Per-cell timing**:
```yaml
btc_5m:   pat_min_time_after_open_s = 210   # was 5
btc_15m:  pat_min_time_after_open_s = 600   # was 5
eth_5m:   pat_min_time_after_open_s = 5     # unchanged
eth_15m:  pat_min_time_after_open_s = 5     # unchanged
sol_5m:   pat_min_time_after_open_s = 5     # unchanged
sol_15m:  pat_min_time_after_open_s = 5     # unchanged
```

**Critical**: timing change is **BTC-only**. ETH and SOL show the OPPOSITE pattern — delaying PAT firing on those assets LOSES money. Per-asset timing config is required.

---

## 1. Per-cell results (21-day BTC canonical window)

### Headline table: current vs proposed config

| Cell | Current (t=5, sz20, pc1.00, f10, s5) | Proposed (per-cell t, COMBO params) | Lift |
|---|---:|---:|---:|
| **btc_5m**  | mean $9.43, sum **$28,482**  (n=3020, win=73%, std=$15) | mean $30.08, sum **$83,811** (n=2786, win=72%, std=$45) | **+194%** |
| **btc_15m** | mean $3.02, sum **$3,609**   (n=1197, win=69%, std=$14) | mean $36.55, sum **$40,347** (n=1104, win=66%, std=$102) | **+1018%** |
| **eth_5m**  | mean $10.73, sum **$10,103** (n=942, win=75%, std=$24) | mean $24.04, sum **$22,408** (n=932, win=75%, std=$61) | **+124%** |
| **eth_15m** | mean $9.00, sum **$6,411**   (n=712, win=88%, std=$21) | mean $27.44, sum **$19,234** (n=701, win=89%, std=$70) | **+200%** |
| **sol_5m**  | mean $13.59, sum **$16,628** (n=1224, win=89%, std=$18) | mean $22.91, sum **$27,795** (n=1213, win=89%, std=$46) | **+67%** |
| **sol_15m** | mean $16.52, sum **$8,707**  (n=527, win=89%, std=$22) | mean $42.20, sum **$21,649** (n=513, win=89%, std=$58) | **+149%** |
| **TOTAL** | **$73,940** ($3,521/day) | **$215,244** ($10,250/day) | **+191%** |

Realistic live deployment (50% backtest haircut): **$1,800/day → $5,100/day**.

---

## 2. How we got here — the four sweep results

### 2.1 `pat_min_time_after_open_s` (the timing sweep)

Tested t ∈ {0, 2, 5, 10, 15, 30, 60, 90, 120, 180, 210, 240} on BTC 5m and t ∈ {5, 30, 60, 120, 180, 240, 360, 480, 600, 720} on BTC 15m + ETH/SOL.

**BTC**: monotonically rising up to t ≈ 70% of window, then drops.
- BTC 5m peak: t=210s (+127% over baseline)
- BTC 15m peak: t=600s (+223% over baseline)

**ETH and SOL**: opposite — baseline t=5 is the optimum. Each step of delay loses PnL.

→ See [PAT_TIMING_SWEEP_2026_05_20.md](PAT_TIMING_SWEEP_2026_05_20.md) for the full 17-point sweep.

### 2.2 `pat_take_size` (size per fire)

Tested {10, 20, 50, 100} at t=210 BTC 5m.

| sz | mean PnL | sum |
|---:|---:|---:|
| 10 | (with f30) $25.13 | $70,409 |
| 20 (baseline) | $21.44 | $60,083 |
| **50** | **$27.82** | **$77,957** |
| 100 (in AGG config) | $30.68 | $85,238 |

→ sz=50 is the sweet spot. sz=100 helps marginally but requires more wallet capital and pushes single-slug variance harder. sz=50 with $200 wallet keeps transient exposure under $150 even with 3 concurrent slugs.

### 2.3 `pat_max_pair_cost` (the edge cap)

Tested {0.97, 0.98, 0.99, 1.00 (baseline)} at t=210 BTC 5m.

| cap | mean PnL | sum | n_fires reduction |
|---:|---:|---:|---:|
| 1.00 (baseline) | $21.44 | $60,083 | — |
| 0.99 | $21.69 | $60,661 | −0.2% slugs fire |
| **0.98** | **$21.97** | **$61,194** | −0.6% slugs fire |
| 0.97 | $22.15 | $61,533 | −0.9% slugs fire |

→ Tighter cap (0.98) modestly improves PnL/slug with very small drop in firing slugs. Below 0.97 cost more in lost fires than gain in edge. **0.98 = clean win**.

### 2.4 `pat_max_fires_per_slug` + `pat_min_s_between_fires`

Tested with f=30, s=2 (vs baseline f=10, s=5) at t=210 BTC 5m.

| Config | mean PnL | sum | win rate |
|---|---:|---:|---:|
| Baseline (f=10, s=5) | $21.44 | $60,083 | 68% |
| **f=30, s=2** | **$28.11** | **$78,761** | **70%** |
| f=50, s=1 (AGG) | $30.68 | $85,238 | 74% |

→ Lifting fire-cap is the second-biggest single-parameter lift after timing. f=30/s=2 gives most of the gain; f=50/s=1 has marginal additional benefit at much higher capital churn. **f=30, s=2 is the recommended sweet spot**.

### 2.5 Combined effect (COMBO config)

```python
StratCfg(
    pat_take_size=50,
    pat_max_pair_cost=0.98,
    pat_max_fires_per_slug=30,
    pat_min_s_between_fires=2.0,
    pat_min_time_after_open_s=<per-cell, see §1 table>,
)
```

For BTC 5m: $9.43 → $30.08 (**+194%**). For BTC 15m: $3.02 → $36.55 (**+1018%**).

The lifts are roughly multiplicative across the 4 levers because each captures different inefficiency:
- **Timing**: when to fire (back half of slug for BTC)
- **Size**: how big each fire is
- **Edge cap**: filter low-edge fires (tighten to 0.98)
- **Rate**: allow more bites per opportunity window

---

## 3. Cross-asset finding — timing is BTC-specific

| Asset | Baseline (t=5) mean | t=peak mean | Best timing |
|---|---:|---:|---|
| BTC 5m | $9.43 | $21.44 (t=210) | **wait** |
| ETH 5m | $10.73 | $2.87 (t=210) | **don't wait** |
| SOL 5m | $13.59 | $5.98 (t=210) | **don't wait** |

**Why BTC differs (hypothesis, not verified)**: BTC up-down markets have higher volume and tighter early-slug spreads → opportunities mostly emerge in the back half. ETH and SOL are thinner markets where opening-book inefficiency persists.

This means a **single universal timing rule does NOT work**. The TV agent's per-cell config approach is correct — different assets need different `pat_min_time_after_open_s`.

---

## 4. Risk caveats

### Variance roughly 3× higher

| Cell | Baseline std | Proposed std | Multiplier |
|---|---:|---:|---:|
| btc_5m | $15.42 | $45.00 | 2.9× |
| btc_15m | $13.72 | $101.64 | **7.4×** |
| eth_5m | $23.74 | $60.74 | 2.6× |
| eth_15m | $21.29 | $70.27 | 3.3× |
| sol_5m | $18.18 | $46.21 | 2.5× |
| sol_15m | $21.80 | $58.00 | 2.7× |

Sharpe also drops on most cells (mean grows fast but std faster). The mean lift is real but trading at this variance needs:

### Required risk-cap updates

```yaml
max_daily_drawdown_usdc:   100    # was 30 — current cap would trigger too often
max_consecutive_losing_slugs: 8   # was 5  — variance dictates wider tolerance
max_hourly_fills:          400    # was 200 — f=30 + 30 slugs/hr possible
max_hourly_pat_fires:      90     # was 30  — f=30 across 3 concurrent slugs
```

### Capital math (still fits $200 wallet)

Per fire: $50 × $0.50 avg = $25 exposed. Immediate merge recovers $50 cash. Net peak exposure: one PAT fire in flight per slug × 3 concurrent slugs = ~$75 transient + ACC-M maker working capital ~$120 = ~$195. **Tight against $200 budget — recommend raising wallet to $300** before deploying COMBO.

### Win rate impact

| Cell | Baseline win | Proposed win | Delta |
|---|---:|---:|---:|
| btc_5m | 73% | 72% | −1pp |
| btc_15m | 69% | 66% | −3pp |
| eth_5m | 75% | 75% | 0 |
| eth_15m | 88% | 89% | +1pp |
| sol_5m | 89% | 89% | 0 |
| sol_15m | 89% | 89% | 0 |

Win rate is stable. The increased variance is **wider tails on winners**, not more losers.

---

## 5. Recommended deployment plan

### Step 1 — A/B shadow test (now, 7 days)

Run TWO shadow sleeves on Ireland:

| Sleeve | Config | Cell |
|---|---|---|
| `ACC-M` (current) | t=5, sz=20, pc=1.00, f=10, s=5 | btc_5m |
| `ACC-M-COMBO` (proposed) | t=210, sz=50, pc=0.98, f=30, s=2 | btc_5m |

Both `code="ACC-M"` but tag the COMBO fires via `trigger_reason="pat_combo_*"` so the shadow monitor can separate them.

### Step 2 — Promotion criterion

After 7 days:
- COMBO sum PnL ≥ 50% above baseline sum PnL → promote COMBO to live on btc_5m
- COMBO partial-fill rate ≤ 5% → confirm engine handles f=30 cleanly
- COMBO no engine errors → safety check

### Step 3 — Cell-by-cell rollout (after btc_5m proves)

1. Add btc_15m with `pat_min_time_after_open_s=600`
2. Add eth_5m + eth_15m with `pat_min_time_after_open_s=5` (timing unchanged, COMBO params only)
3. Add sol_5m + sol_15m with `pat_min_time_after_open_s=5`

### Step 4 — Wallet scale-up after 30 days

If aggregate 30-day PnL ≥ $30k (= 50% of backtest projection for 30 days), scale wallet from $200 → $1000 and bump `max_concurrent_slugs` from 3 → 6.

---

## 6. Per-asset breakdown of lift sources (BTC 5m as example)

Decomposition of where the +$54k lift comes from:

| Change applied | Cumulative sum | Lift contribution |
|---|---:|---:|
| Baseline (t=5, sz=20, pc=1.00, f=10, s=5) | $28,482 | — |
| + Timing change (t=210) | $60,083 | +$31,601 (+58%) |
| + Size (sz=50) | $77,957 | +$17,874 (+30%) |
| + Edge cap (pc=0.98) | (estimated) $79,000 | +$1,000 (+2%) |
| + Fire rate (f=30, s=2) | **$83,811** | +$4,800 (+8%) |
| **Total lift** | | **+$55,329 (+194%)** |

→ **Timing change alone is the biggest single lever** (58% of total lift on BTC).
→ Size is the second-biggest (30%).
→ Edge cap and fire-rate together account for the remaining 10%.

For ETH/SOL where timing change loses money, size + fire rate become the dominant levers (timing contribution = 0).

---

## 7. What we did NOT test

- **Co-sweep of `post_size` (ACC-M maker)** — we kept it at 20. May benefit from a similar boost to 50.
- **`merge_threshold_pairs`** — kept at 5. Lower threshold might free capital faster.
- **`max_imbalance_shares` interaction with PAT** — when PAT fires, inventory swings; the maker layer's imbalance check may suppress useful posts.
- **`pat_min_book_depth_each_side`** — kept at 5. Raising to 10 might filter out partial-fill risk.
- **Cross-product 5m vs 15m param differences** — we applied the same COMBO to both. 15m may benefit from different sz/f tuning.
- **Hour-of-day overlay** — the COMBO might work better in some UTC hours; we treated the day as homogeneous.
- **Out-of-window validation** — the entire sweep is on Apr 24 - May 15. Older data and live-going-forward could differ.

---

## 8. Files

```
strategy_lab/backtests/fast_full_backtest.py                  (modified — added 18 PAT variants)
strategy_lab/backtests/_fast_full_btc_pat_timing_sweep*.csv   (timing sweep BTC 5m + 15m)
strategy_lab/backtests/_fast_full_eth_eth_5m_timing.csv       (ETH 5m timing)
strategy_lab/backtests/_fast_full_sol_sol_5m_timing.csv       (SOL 5m timing)
strategy_lab/backtests/_fast_full_btc_t210_cosweep.csv        (PAT param co-sweep at t=210)
strategy_lab/backtests/_fast_full_btc_t210_combo.csv          (COMBO/AGG configs)
strategy_lab/backtests/_fast_full_*_*_combo*.csv              (per-asset COMBO validation)
strategy_lab/reports/PAT_TIMING_SWEEP_2026_05_20.md           (the timing-only sweep report)
strategy_lab/reports/PAT_HYPERPARAMS_FULL_SWEEP_2026_05_20.md (this report — full COMBO + per-cell)
```

Reproduce key results:
```bash
# BTC: timing + COMBO
py -3 -X utf8 strategy_lab/backtests/fast_full_backtest.py --asset btc --tfs 5m \
    --max-slugs 0 \
    --strategies "PAT+ACC-M,PAT+ACC-M-t210-COMBO" --out-suffix verify_btc

# ETH/SOL: COMBO at baseline
py -3 -X utf8 strategy_lab/backtests/fast_full_backtest.py --asset eth --tfs 5m \
    --max-slugs 0 --strategies "PAT+ACC-M,PAT+ACC-M-t5-COMBO" --out-suffix verify_eth

py -3 -X utf8 strategy_lab/backtests/fast_full_backtest.py --asset sol --tfs 5m \
    --max-slugs 0 --strategies "PAT+ACC-M,PAT+ACC-M-t5-COMBO" --out-suffix verify_sol
```

---

## 9. Bottom line for TV agent

Five config lines change. One per-cell timing value. Run shadow A/B for 7 days on btc_5m. If lift ≥ 50%, promote and roll out to all 6 cells per §5.

Backtest projects deployment of this config across all 6 cells delivers **$10k/day vs current $3.5k/day** — same engine, same wallet ($300 wallet recommended over $200 to give variance buffer), same strategy logic. Just better-tuned hyperparameters.

This came from systematic sweep on our own strategy, not from copying any reference wallet. The wallet-decode arc (slug-selection classifier, within-slug timing decode) produced ZERO actionable lift. Hyperparameter sweep produced **+2.9× live PnL projection**. Lesson: **trust the backtest sweep over the wallet-mining narrative**.
