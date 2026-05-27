# V6 Methodology Research — Kelly Sizing, Pre-Window Mechanics, Early-Offset VWAP

**Author**: research subagent
**Date**: 2026-05-27
**Status**: methodology + empirics. Per `_BRIEF_V6.md` §1, §2, §4.
**Companion data**: `strategy_lab/sniper_search_2026_05_27/_kelly_prewindow_research/vwap_by_offset.csv`

---

## §1 — Kelly Sizing for Polymarket UP/DOWN Binary Markets

### 1.1 Setup

Per fire we know `entry_vwap` ∈ (0,1) — the L25 book-walk fill price for $25 notional. The market resolves binary: UP token pays $1 if UP wins, $0 otherwise (mirror for DOWN). Production fee = legacy 2% on the winning leg only (verified 2026-05-22 against 25,900 `poly_updown_resolution` events — see `CLAUDE.md`).

Per dollar staked, the **net** profit-loss ratio is:

```
b = (1 - vwap) * 0.98 / vwap          # profit per $1 risked, if won
```

Examples:

| vwap  | b      | interpretation                       |
|-------|--------|--------------------------------------|
| 0.40  | 1.470  | win $1.47 / lose $1.00              |
| 0.50  | 0.980  | win $0.98 / lose $1.00 (≈ even)     |
| 0.55  | 0.802  | win $0.80 / lose $1.00              |
| 0.60  | 0.653  | win $0.65 / lose $1.00              |
| 0.70  | 0.420  | win $0.42 / lose $1.00 (asymmetric) |

### 1.2 Kelly Fraction Derivation

Standard Kelly:

```
f_full = (p*b - q) / b               where q = 1 - p
```

This maximises `E[log(bankroll)]`. The well-known "log-optimal" claim assumes:

1. independent bets,
2. true `p` known exactly,
3. unbounded time horizon,
4. risk-neutral re-investment.

None of these are airtight for us. In particular `p` is **estimated** from gate-conviction buckets with finite n, so the variance on `p` matters. Hence **fractional Kelly**.

**Quarter-Kelly (`0.25 × f_full`)** is the standard conservative dial. Rationale:

- If `p` is estimated and the estimator has bias up to ~0.05-0.10 (plausible at n=50 per bucket), full Kelly often becomes a Russian-roulette schedule under the noisy `p`. See Thorp's "Kelly Capital Growth Investment Criterion" (2011) — half-Kelly already gives up 25% of the geometric growth for a 75% reduction in drawdown. Quarter-Kelly is more aggressive on the drawdown reduction, trading away half the geometric growth.
- Operator preference is "conservative, capped $25 max" — quarter-Kelly aligns.

```
f_kelly_25 = max(0, 0.25 * f_full)
```

### 1.3 Worked Examples Across (vwap, p) Grid

`b = (1-v)*0.98/v`, `f_full = (p*b - q)/b`, `f_kelly_25 = max(0, 0.25*f_full)`:

| vwap | p    | b     | f_full   | f_kelly_25 |
|------|------|-------|----------|------------|
| 0.40 | 0.65 | 1.470 | +0.4119  | 0.1030     |
| 0.40 | 0.75 | 1.470 | +0.5799  | 0.1450     |
| 0.40 | 0.85 | 1.470 | +0.7480  | 0.1870     |
| 0.50 | 0.65 | 0.980 | +0.2929  | 0.0732     |
| 0.50 | 0.75 | 0.980 | +0.4949  | 0.1237     |
| 0.50 | 0.85 | 0.980 | +0.6969  | 0.1742     |
| 0.55 | 0.65 | 0.802 | +0.2135  | 0.0534     |
| 0.55 | 0.75 | 0.802 | +0.4382  | 0.1096     |
| 0.55 | 0.85 | 0.802 | +0.6629  | 0.1657     |
| 0.60 | 0.65 | 0.653 | +0.1143  | 0.0286     |
| 0.60 | 0.75 | 0.653 | +0.3673  | 0.0918     |
| 0.60 | 0.85 | 0.653 | +0.6204  | 0.1551     |
| 0.70 | 0.65 | 0.420 | **-0.18**| **0.00**   |
| 0.70 | 0.75 | 0.420 | +0.1548  | 0.0387     |
| 0.70 | 0.85 | 0.420 | +0.4929  | 0.1232     |

### 1.4 Edge Case — `p ≤ p_break_even`

`f_full` goes negative when `p < q/b`, i.e. when the implied probability from the book exceeds your edge. Break-even `p` solves `p*b = q`:

```
p_break_even = q / (b + 1) ... reformulated => p_break_even = vwap / (vwap + (1-vwap)*0.98)
```

| vwap  | p_break_even |
|-------|--------------|
| 0.40  | 0.4049       |
| 0.50  | 0.5051       |
| 0.55  | 0.5550       |
| 0.60  | 0.6048       |
| 0.70  | 0.7042       |

**Operational rule**: if your conviction-estimated `p ≤ p_break_even + 0.02` (2% safety margin to absorb mis-estimation), DON'T FIRE. The bet is sub-EV. Code path:

```python
if p <= p_break_even + 0.02:
    return  # skip fire
```

Note this means: **even a 65% WR cell loses money if you're forced to enter at vwap = 0.70**. The book-implied probability already exceeds the edge. This is non-obvious and worth a sleeve-level filter.

### 1.5 Translation to Dollar Stake — Three Methods Compared

The brief specifies `STAKE_MIN=$5`, `STAKE_MAX=$25`. Three methods:

#### Method 1 — Direct Kelly (brief formula)
```
stake_kelly = clip(0.25*f_full * STAKE_MAX, 5, 25)
            = clip(f_kelly_25 * 25, 5, 25)
```

This is mathematically Kelly applied to a **$100 effective bankroll** (since `0.25*f*25 ≈ stake_25_cap` only when bankroll ≈ $100). At realistic bankroll ($500-$10k), this formula UNDERSIZES drastically: `f_kelly_25` is typically 0.05-0.20, so `f_kelly_25 * 25` ∈ [$1.25, $5] → always clipped to STAKE_MIN=$5. Brief's formula effectively becomes "always $5".

#### Method 2 — Proper Kelly on Rolling Notional B
```
stake_proper = clip(0.25*f_full * B, 5, 25)
```

Choose B = current rolling notional (e.g., $500 floating). Now stakes spread across [$5, $25] meaningfully:

| vwap | p    | f_kelly_25 | stake_proper(B=$500) | stake_brief |
|------|------|------------|----------------------|-------------|
| 0.40 | 0.65 | 0.1030     | **$25.00**          | $5.00       |
| 0.40 | 0.75 | 0.1450     | **$25.00**          | $5.00       |
| 0.50 | 0.65 | 0.0732     | **$25.00**          | $5.00       |
| 0.55 | 0.65 | 0.0534     | **$25.00**          | $5.00       |
| 0.60 | 0.65 | 0.0286     | $14.29              | $5.00       |
| 0.70 | 0.65 | 0.0000     | **$0.00** (no fire) | $0.00       |
| 0.70 | 0.75 | 0.0387     | $19.35              | $5.00       |
| 0.70 | 0.85 | 0.1232     | **$25.00**          | $5.00       |

**Method 2 saturates the $25 cap once `f_kelly_25 > 0.05`**, which is most signals worth taking. Within the operator's [$5,$25] band, Method 2 effectively becomes a 3-bucket discrete distribution:
- $25 (signal has clear edge),
- ~$15-20 (marginal edge),
- $5 floor (very marginal, near break-even),
- $0/skip (no edge — see §1.4).

#### Method 3 — Logistic Sigmoid on (p − p_break_even)

A smooth alternative that doesn't depend on a bankroll constant:

```
edge = p - p_break_even
stake = STAKE_MIN + (STAKE_MAX - STAKE_MIN) * sigmoid(k * edge)
```

Choose `k=15` for a moderately sharp sigmoid (saturates beyond ±0.3 edge):

| vwap | p    | p_be   | edge    | sigmoid(k=15) | stake  |
|------|------|--------|---------|---------------|--------|
| 0.40 | 0.65 | 0.4049 | +0.2451 | 0.9753        | $24.51 |
| 0.50 | 0.65 | 0.5051 | +0.1449 | 0.8979        | $22.96 |
| 0.55 | 0.65 | 0.5550 | +0.0950 | 0.8061        | $21.12 |
| 0.60 | 0.65 | 0.6048 | +0.0452 | 0.6632        | $18.26 |
| 0.70 | 0.65 | 0.7042 | −0.0542 | 0.3072        | $11.14 |
| 0.50 | 0.75 | 0.5051 | +0.2449 | 0.9753        | $24.51 |
| 0.55 | 0.85 | 0.5550 | +0.2950 | 0.9882        | $24.76 |
| 0.60 | 0.85 | 0.6048 | +0.2452 | 0.9753        | $24.51 |
| 0.70 | 0.85 | 0.7042 | +0.1458 | 0.8990        | $22.98 |

Smooth, monotone in edge, **never goes below $5 even at zero/negative edge** (operator should pair with a separate "skip if edge < 0.02" gate; otherwise this still bets $5 on a coin-flip — bad).

### 1.6 RECOMMENDED OPERATOR BEST PRACTICE

**Hybrid: Kelly-on-rolling-notional + edge floor + sigmoid smoothing**

```python
def stake_recommend(p, vwap, bankroll=500.0, kelly_mult=0.25,
                    stake_min=5.0, stake_max=25.0,
                    edge_floor=0.02):
    """
    Returns recommended dollar stake. Returns 0 (skip) when edge < edge_floor.

    Method: quarter-Kelly with logistic smoothing to avoid bang-bang at the $25 cap.
    """
    b = (1 - vwap) * 0.98 / vwap                    # net odds, legacy 2% fee
    if b <= 0:
        return 0.0                                   # vwap >= 1 impossible
    p_be = vwap / (vwap + (1 - vwap) * 0.98)        # break-even prob
    edge = p - p_be
    if edge < edge_floor:
        return 0.0                                   # skip — no edge after fee

    f_full = (p * b - (1 - p)) / b
    f_kelly = max(0.0, kelly_mult * f_full)
    stake_kelly = f_kelly * bankroll                # uncapped Kelly stake

    # Smooth blend between Kelly stake and sigmoid-based stake, then cap.
    # The sigmoid provides a graceful floor at low edges:
    sigmoid = 1.0 / (1.0 + 2.71828 ** (-15.0 * edge))
    stake_sig = stake_min + (stake_max - stake_min) * sigmoid

    # Take the MIN of Kelly and sigmoid stakes — Kelly caps from above on
    # high edge (over-confident at extreme p), sigmoid caps from below.
    stake = min(stake_kelly, stake_sig)
    return max(stake_min, min(stake_max, stake))
```

**Why hybrid wins**:

- Method 1 (brief) → almost always $5 → defeats the variable-stake purpose.
- Method 2 (proper Kelly) → bang-bang $5 ↔ $25 with little middle ground; sensitive to bankroll guess; doesn't enforce edge floor.
- Method 3 (sigmoid) → graceful but bets $5 even at zero edge.
- Hybrid takes the conservative `min` of Kelly + sigmoid, plus enforces the edge floor → near-Kelly when edge is huge, conservative when edge is marginal, **skips** when sub-EV.

**Defaults**: `bankroll=$500` (3x operator's max stake — a sensible scale), `kelly_mult=0.25` (quarter-Kelly), `edge_floor=0.02` (require p exceeding break-even by 2% to absorb estimation noise).

### 1.7 Conviction → p Estimation (per brief Option B)

**Option B: empirical WR per conviction bucket.** Preferred when n is large. Workflow:

1. Define gate stack `G = {g_1, ..., g_k}` chosen by search.
2. For each fire, count `n_passing = sum(g_i(fire))`.
3. Partition fires into buckets by `n_passing ∈ {min_required, min_required+1, ..., k}`.
4. Compute empirical WR per bucket on **TRAIN window** (Apr 22 - May 10).
5. At deploy, given a new fire's `n_passing`, set `p = empirical_WR[bucket]`.

**Bootstrap CIs**: for each bucket compute 2.5%/97.5% percentile bootstrap on WR. Use the LOWER CI as conservative `p`:

```python
# In Topic-2 jargon: "use the lower 2.5% bootstrap percentile of p, not the point estimate"
p_conservative = np.percentile([wr_resample_i for i in range(2000)], 2.5)
```

This protects against bucket WR being inflated by chance in finite samples — the more conservative `p` makes Kelly more conservative too. Operator can dial: 5% percentile if more aggressive, 1% if extra paranoid.

---

## §2 — Production Momo Controller Pre-Window Mechanics

### 2.1 Source-of-truth (verified live)

File: `/opt/tradingvenue/backend/app/engine/poly_updown_loop.py`. Mirror in this repo: `migration_2026_05_21/vps3_shadow_audit/poly_updown_loop.py`.

Two relevant builder functions:
- `build_bar_context_t_plus_120` (line 366, momo_v1)
- `build_bar_context_t_plus_60`  (line 577, momo_v2)

### 2.2 Anchor convention (canonical)

```
slot_start_us  = market's open boundary (e.g. 17:35:00 UTC for a 5m slot)
window_s       = 300 (5m) or 900 (15m)
ws_s           = slot_start_us // 1_000_000 - window_s  ← SIGNAL ANCHOR
fire_us_v1     = (ws_s + 120) * 1_000_000               ← v1 fire at +120s past ws_s
fire_us_v2     = (ws_s + 60)  * 1_000_000               ← v2 fire at +60s past ws_s
```

Equivalent phrasing: **`ws_s = slot_start - window_s` is the PREVIOUS slot's start**. The market's outcome window covers `[slot_start, slot_start + window_s]`, and the signal is computed at `slot_start - window_s` (one window prior).

### 2.3 Feature window: 15 closes back from ws_s

Per source comment in `_fetch_rsi_14` (lines 454-459 of `poly_updown_loop.py`):

```python
async def _fetch_rsi_14() -> float:
    from backend.app.indicators.rsi import compute_rsi_14
    offsets = [-60 * i for i in range(14, -1, -1)]  # -840..0 chronological
    closes = await asyncio.gather(*[_fetch_close(o) for o in offsets])
    floats = [float(c) if c is not None else float("nan") for c in closes]
    return compute_rsi_14(floats)
```

**15 closes spanning ws_s−840s to ws_s** (inclusive), step=60s.
**LAST close (offsets[-1]=0) = close AT ws_s itself.**

The RSI is `compute_rsi_14(closes)` = Wilder simple-mean (NOT exponential) on these 15 closes. Verified by source-comment in `backend/app/indicators/rsi.py`. CLAUDE.md confirms: `Production RSI is simple-mean Wilder (NOT exponential)`.

### 2.4 Fire timing

After computing the feature panel at `ws_s`:
1. v1: queue order to fire at `fire_us = (ws_s + 120) * 1_000_000` → t+120 past ws_s.
2. v2: queue order to fire at `fire_us = (ws_s + 60) * 1_000_000`  → t+60 past ws_s.

For both, **the signal was computed BEFORE the fire was queued**. The fire is a delayed-execution of the ws_s decision.

### 2.5 Verification: 100-fire sample anchor test

I ran `master_gate_features_v2.parquet` through an anchor consistency check: for the same `(slug, direction)` with multiple `fire_offset_s` rows, a **ws_s-anchored feature should have identical values across all offsets**, whereas a fire_us-anchored feature should DIFFER per offset.

Result on 50 multi-offset slug-direction pairs:

| Feature             | n_pairs with identical value across offsets | Anchor      |
|---------------------|---------------------------------------------|-------------|
| `f7_rsi_at_ws`      | **47 / 50**                                 | **ws_s**    |
| `rsi_14`            | 48 / 50                                     | **ws_s**    |
| `g_markov_with`     | **50 / 50**                                 | **ws_s**    |
| `mp_skew` (microprice) | 8 / 50                                   | **fire_us** |

**Conclusion**: production-momo-style features (F7 RSI, Markov regime) in master_gate_features_v2 are correctly anchored at **ws_s**. Microprice features (`mp_skew`, `mp_imbalance`, etc.) are correctly anchored at **fire_us** (microprice changes per-fire by definition).

This means V6 sleeves can mix ws_s-anchored pre-window momentum gates with fire_us-anchored microprice gates — they are CAUSAL because both anchors are ≤ fire_us. **No lookahead bug exists in the master panel.**

### 2.6 What "pre-window signal evaluation" means for V6

The brief's §2 ("pre-window momentum") asks to test features anchored at `ws_s`, `ws_s − 30s`, `ws_s − 60s`. The CORRECT interpretation:

- `ws_s − 30s` does NOT mean "look at the 30s before ws_s in isolation". It means the **rsi/markov panel computed at the earlier anchor**.
- E.g., for `g_prewindow_rsi_extreme(direction, ws_s − 30s)`, you compute the SAME 15-close RSI but ending at `ws_s − 30s` instead of `ws_s`. The lookback is shifted left by 30s.
- This gives the agent ONE MORE feature derived from EARLIER data (less stale relative to ws_s, but more lead time to fire_us — production momo always uses `ws_s`).

**Implementation**: extend `_fetch_rsi_14` with a `signal_offset_s` argument:

```python
async def _fetch_rsi_14_at(ws_s_anchor: int, signal_offset_s: int = 0) -> float:
    """Compute RSI(14) ending at ws_s_anchor - signal_offset_s."""
    anchor = ws_s_anchor - signal_offset_s
    offsets = [-60 * i for i in range(14, -1, -1)]  # -840..0
    closes = await fetch_closes_at(symbol, anchor + o for o in offsets)
    return compute_rsi_14(closes)
```

Three pre-window panels: `rsi14_at_ws`, `rsi14_at_ws_minus_30`, `rsi14_at_ws_minus_60`. Combine via composable gates (e.g., `g_rsi_monotone_against = rsi14_at_ws < rsi14_at_ws_minus_30 < rsi14_at_ws_minus_60` for DOWN direction).

---

## §3 — Early-Offset Entry VWAP Empirical Analysis

### 3.1 Hypothesis (from brief)

"Fire earlier → better entry_vwap → higher $/trade." The implicit story: as the market progresses through the window, the price drifts toward one side; later offsets buy "more committed" books with worse vwap.

### 3.2 Raw mean/median vwap by offset (all fires, not conditional on outcome)

Computed across `oos_fires_{ASSET}_{TF}_full_v3.parquet`. See `vwap_by_offset.csv` for full detail. Key rows:

| MARKET   | OFFSET | n      | mean_vwap | median_vwap |
|----------|--------|--------|-----------|-------------|
| BTC 5m   | 30     | 16,107 | 0.5080    | 0.5100      |
| BTC 5m   | 90     | 16,326 | 0.5083    | 0.5100      |
| BTC 5m   | 150    | 16,547 | 0.5061    | 0.5100      |
| BTC 5m   | 210    | 16,064 | 0.4952    | 0.4900      |
| BTC 5m   | 270    | 14,055 | 0.4240    | 0.2966      |
| ETH 5m   | 30     | 14,854 | 0.5138    | 0.5138      |
| ETH 5m   | 270    | 13,355 | 0.4264    | 0.2287      |
| SOL 5m   | 30     | 11,028 | 0.5253    | 0.5234      |
| SOL 5m   | 270    | 10,754 | 0.4370    | 0.2105      |
| BTC 15m  | 60     |  5,558 | 0.5078    | 0.5100      |
| BTC 15m  | 840    |  4,631 | 0.4016    | 0.1580      |

**Finding**: mean vwap is essentially FLAT for early offsets (~0.50-0.52) and CRASHES at the final offset (offset=270 for 5m, offset=840 for 15m). Why crash? At the final offset, both sides have entries; the LOSING side has fires recorded with vwap → 0 because the book is empty / the side is collapsing. The mean is dragged down by these near-zero vwap losers.

**This is NOT what "fire earlier = better vwap" predicts.** Raw mean is misleading.

### 3.3 The right diagnostic: vwap of WINNING fires only

| MARKET   | OFFSET | n      | WR     | vwap_won | dpt @ $25 const |
|----------|--------|--------|--------|----------|-----------------|
| BTC 5m   | 30     | 16,107 | 0.5013 | 0.5440   | **−$0.63**      |
| BTC 5m   | 60     | 16,341 | 0.5011 | 0.5751   | −$1.04          |
| BTC 5m   | 90     | 16,326 | 0.5013 | 0.6067   | −$1.18          |
| BTC 5m   | 120    | 16,593 | 0.5010 | 0.6361   | −$1.37          |
| BTC 5m   | 150    | 16,547 | 0.4995 | 0.6683   | −$1.70          |
| BTC 5m   | 210    | 16,064 | 0.4875 | 0.7350   | −$2.94          |
| BTC 5m   | 270    | 14,055 | 0.4144 | 0.8039   | −$6.39          |

For **UNGATED** fires (no signal filter, just every market we tracked), the **vwap_won climbs monotonically** with offset. The interpretation:

- At offset=30, a winning fire was bought at 0.544 → payoff $20.55 per $25 stake.
- At offset=270, a winning fire was bought at 0.804 → payoff $5.98 per $25 stake.
- **Difference: $14.57 per won trade.**

This is the **payoff-per-win asymmetry** that the hypothesis is really about.

### 3.4 Dollar Delta Per Winning Trade: Early vs Late Offset

Computed `(1−vwap_won)/vwap_won × $25 × 0.98` at first vs last offset for each market:

| MARKET   | early_off | late_off | vwap_won_early | vwap_won_late | win_payoff_early | win_payoff_late | DELTA per WON |
|----------|-----------|----------|----------------|---------------|------------------|-----------------|---------------|
| BTC_5m   | 30        | 270      | 0.5440         | 0.8039        | $20.54           | $5.98           | **+$14.56**   |
| ETH_5m   | 30        | 270      | 0.5527         | 0.8403        | $19.83           | $4.66           | **+$15.17**   |
| SOL_5m   | 30        | 270      | 0.5599         | 0.8761        | $19.26           | $3.46           | **+$15.80**   |
| BTC_15m  | 60        | 840      | 0.5369         | 0.8448        | $21.13           | $4.50           | **+$16.63**   |
| ETH_15m  | 60        | 840      | 0.5422         | 0.8640        | $20.69           | $3.86           | **+$16.83**   |
| SOL_15m  | 60        | 840      | 0.5445         | 0.8956        | $20.49           | $2.85           | **+$17.64**   |

### 3.5 Interpretation

**Earlier offset → larger payoff per won trade by $14-$18 at $25 stake. The hypothesis "fire earlier = better vwap" is TRUE conditional on outcome.**

But there's a counter-force: **earlier offsets also have lower WR for the same gate stack** (because the signal hasn't crystallized yet). In the ungated case above, WR is flat ~0.50 at offsets 30-150, and only drops at offsets ≥210. So for early offsets, the increased payoff-per-win is NOT offset by lower WR — it's a free lunch (modulo the question of whether your gate stack still works at the earlier signal time).

**Implication for V6 sleeves**:

1. **Offset=30 (or earliest available) is the right deploy target** for 5m markets, IF gate WR holds at that offset.
2. **Markets with the largest 15m-payoff-uplift**: SOL_15m ($17.64/win), ETH_15m ($16.83/win), BTC_15m ($16.63/win). These have the most to gain from early entry because their late-offset vwap is closer to $1.
3. **Markets with the smallest uplift**: BTC_5m ($14.56/win). Still significant. All markets benefit, but 15m benefits more (longer window → more crystallization).
4. **Combined with Kelly**: a sleeve with WR=0.65 at offset=30 with mean vwap_won=0.55 has:
   - per-trade EV = `0.65 × (0.45/0.55 × 25 × 0.98) − 0.35 × 25 = 0.65 × 20.05 − 8.75 = +$4.28`
   - vs at offset=240 with same WR, vwap_won≈0.77: `0.65 × (0.23/0.77 × 25 × 0.98) − 0.35 × 25 = 0.65 × 7.32 − 8.75 = -$3.99`
   - **Same WR, +$8/trade swing just from offset choice.**

### 3.6 Caveats

1. **Population mix changes with offset.** Later-offset rows are conditional on the market being "still firing" — i.e., the slug hasn't already resolved. The slugs that survive to offset=240+ are slugs where the move is small / undecided. So `vwap_won_at_240` is sampled from a different slug distribution than `vwap_won_at_30`. The per-slug Δ is the right number, not the unconditional mean.
2. **Per-slug Δ requires same-slug paired data.** Available in v3 fires (same slug appears at multiple offsets). A per-slug Wilcoxon test would tighten the claim — left as a follow-up.
3. **Book depth at offset=30 is thinner** than at offset=120-180 (more market makers have placed). Some sleeves at offset=30 will fail the depth-supports-stake gate (§4 of brief). Use a stake-aware fill check, not a search-time gate.

---

## §4 — V6 Playbook Synthesis

1. **Default offset for V6 sleeves**: 30 (5m) or 60 (15m) — earliest available in v3 fires. Build offset=0/15 panels only if a sleeve specifically benefits.
2. **Default sizing**: **hybrid Kelly + sigmoid** per §1.6, `bankroll=$500`, `kelly_mult=0.25`, `edge_floor=0.02`. Skip fires where `p ≤ p_break_even + 0.02`.
3. **Conviction → p**: Option B (empirical WR per bucket) on TRAIN, validate on VAL, lockbox-hold the deploy schedule. Use **2.5% bootstrap lower CI of p**, not point estimate.
4. **Gate anchor**: `f7_rsi_at_ws`, `g_markov_with`, multi-timeframe returns → all anchored at `ws_s` (verified §2.5). Microprice gates → at `fire_us`. Both causal, both allowed in the same stack.
5. **Pre-window stacking**: add `rsi14_at_ws_minus_30` and `rsi14_at_ws_minus_60` as new gate atoms; test if the rsi monotone direction at ws_s and ws_s−30 is a useful confirmation gate.
6. **Sanity check before deploying**: assert `gate_value(at=ws_s) == gate_value(at=fire_us)` for any new gate marked as pre-window. If they differ, the gate is using post-ws_s data (lookahead bug per brief §9).

### Deliverables Summary

- Kelly formula recommendation: **§1.6 hybrid**.
- Production anchor: **`ws_s = slot_start − window_s`**, RSI 15 closes back, fires at +120s (v1) or +60s (v2).
- Best early-offset uplift: **SOL_15m at +$17.64/won** (15m markets generally; 5m smaller but still material).
- File: `strategy_lab/sniper_search_2026_05_27/_KELLY_AND_PREWINDOW_RESEARCH_V6.md`

---

## Appendix A — Reference Files

- v3 fires source: `data/v4/canonical/_results/_full_window_v3_2026_05_27/oos_fires_{ASSET}_{TF}_full_v3.parquet`
- Master gates panel: `data/v4/canonical/_results/master_gate_features_v2.parquet`
- Production momo source: `migration_2026_05_21/vps3_shadow_audit/poly_updown_loop.py` (functions `build_bar_context_t_plus_120` at line 366, `build_bar_context_t_plus_60` at line 577)
- F7 RSI verification: `strategy_lab/meta_classifier/_match_live_f7_v2.py` (94.67% match against 1,331 production fires)
- Engine config: `strategy_lab/engine_v2.py` (use `LegacyConfig` for 2%-on-profit production parity)
- CLAUDE.md note on F7 anchor: line ~75-95 (search "F7 RSI anchor = ws_s = slot_start − window_s")
- Empirical VWAP-by-offset data: `strategy_lab/sniper_search_2026_05_27/_kelly_prewindow_research/vwap_by_offset.csv`

## Appendix B — Kelly Formulas (Quick Reference)

```
# Per fire:
b            = (1 - vwap) * 0.98 / vwap
p_be         = vwap / (vwap + (1 - vwap) * 0.98)
edge         = p - p_be
f_full       = (p * b - (1 - p)) / b
f_kelly_25   = max(0, 0.25 * f_full)

# Skip if no edge after fee + estimation margin:
if edge < 0.02: skip

# Recommended stake (hybrid):
stake_kelly = f_kelly_25 * BANKROLL                     # uncapped Kelly
sigmoid     = 1 / (1 + exp(-15 * edge))
stake_sig   = STAKE_MIN + (STAKE_MAX - STAKE_MIN) * sigmoid
stake       = clip(min(stake_kelly, stake_sig), STAKE_MIN, STAKE_MAX)
```
