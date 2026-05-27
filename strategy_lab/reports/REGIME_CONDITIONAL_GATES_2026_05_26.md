# Regime-conditional gate stacks — 2026-05-26

**Question**: do per-regime gate stacks outperform a single agnostic stack?
**Bottom line**: **NO** — the single best agnostic gate (`g_hurst_trending=1`) sweeps **$41.7k** on the 4.8-day lockbox across 8 sleeves vs the state-machine's **$22.8k** (-45%). Regime is already captured by existing universal gates; per-regime fragmentation costs too much volume.

That said, the per-regime exploration surfaced **4 deployable regime-conditional sleeves** that beat their own baselines, and **clear per-regime gate hierarchies** worth documenting.

---

## 1. Regime distribution per sleeve

`data/v4/canonical/_results/regime_distribution_per_sleeve.csv`

| asset | ranging % | trending_up % | trending_dn % |
|-------|-----------|---------------|---------------|
| BTC   | 77 – 89   | 4 – 12        | 7 – 11        |
| ETH   | 86        | 5             | 9 – 10        |
| SOL   | 77        | 16            | 7             |

Overall: **87% of fires are in ranging regime** (68,069 of 77,906). Trending regimes are scarce — most sleeves get only **150–700 trending fires across 25d**, often <100 per (split × regime). This is the structural problem: trending regimes lack n to train a robust stack and lack n on lockbox to evaluate it.

---

## 2. Per-(sleeve, regime) optimal gate stack

`data/v4/canonical/_results/regime_conditional_optimal_stacks.csv` (split = strict train May 01-14, val May 14-21, lockbox May 21-25)
`data/v4/canonical/_results/regime_conditional_optimal_stacks_robust.csv` (train+val combined for stability)

### Three representative sleeves

**poly_updown_btc_5m_s15_off60-150** (the standout — see §3)
| regime | stack | lockbox n | wr | mean $/tr | sum |
|--------|-------|-----------|------|-----------|------|
| trending_up | g_hl_liq_cascade_with=1 & g_rf_with=1 | 6 | 0.667 | 1.98 | 11.9 |
| trending_dn | g_cci_with=1 & g_queue_top_high=1 & g_tr_stack_with=1 & g_ribbon_agrees=1 | 53 | 0.717 | 3.20 | 169.8 |
| ranging | **g_hurst_trending=1** | 2,822 | 0.777 | 4.64 | **13,080.6** |

Ranging stack carries the entire signal. Trending stacks are noisy with n=6–53.

**poly_updown_btc_5m_s6_off0-60**
| regime | stack | lockbox n | wr | mean $/tr | sum |
|--------|-------|-----------|------|-----------|------|
| trending_up | g_markov_with=0 & g_trend_slope_strong_with=0 | 0 | – | – | 0.0 |
| trending_dn | g_hurst_trending=1 | 52 | 0.923 | 11.27 | 586.2 |
| ranging | g_markov_with=0 | 255 | 0.749 | 5.24 | 1336.8 |

Stack collapsed to single-gate per regime — robust.

**poly_updown_sol_5m_s6_off0-60**
| regime | stack | lockbox n | wr | mean $/tr | sum |
|--------|-------|-----------|------|-----------|------|
| trending_up | EMPTY (n too low) | 6 | 0.500 | -6.83 | -41.0 |
| trending_dn | g_mp_change_with=0 & g_mfi_with=1 | 2 | 0.500 | -9.04 | -18.1 |
| ranging | EMPTY | 277 | 0.816 | 4.94 | **1367.3** |

SOL is dominated by ranging — no regime stack improves it.

---

## 3. State-machine sleeve performance vs baselines (LOCKBOX, 4.8 days)

`data/v4/canonical/_results/regime_state_machine_sleeves.csv` (strict),
`data/v4/canonical/_results/regime_state_machine_robust.csv` (train+val combined)

| sleeve | baseline n | baseline sum | trending-only sum | best-static-regime sum | SM n | SM sum | SM mean $/tr | p_boot |
|--------|------------|--------------|-------------------|------------------------|------|--------|--------------|--------|
| btc_s6_off60-150 | 4,227 | 7,138 | 1,490 | 5,648 | 482 | 2,018 | 4.19 | 0.000 |
| btc_s15_off150-240 | 6,049 | 13,495 | 4,092 | 9,403 | 373 | 1,665 | 4.46 | 0.000 |
| btc_s6_off0-60 | 506 | 2,147 | 952 | 1,195 | 307 | 1,923 | 6.26 | 0.000 |
| **btc_s15_off60-150** | 5,498 | 7,995 | 1,091 | 6,903 | 2,881 | **13,262** | 4.60 | 0.000 |
| eth_s6_off60-150 | 3,450 | 4,067 | 498 | 3,570 | 357 | 568 | 1.59 | 0.124 |
| btc_s15_off240-300 | 2,525 | 7,178 | 1,871 | 5,307 | 233 | 732 | 3.14 | 0.620 |
| eth_s15_off60-150 | 4,519 | 5,341 | 426 | 4,914 | 297 | 1,276 | 4.30 | 0.000 |
| **sol_s6_off0-60** | 287 | 1,295 | -72 | 1,367 | 285 | **1,308** | 4.59 | 0.000 |

**Verdict**:
- SM mean $/tr **beats baseline in 6/8 sleeves** — gate stacks DO improve per-trade quality
- SM total $ **beats baseline in only 2/8** — selectivity drops volume too much
- SM beats trending-only filter in **5/8**
- SM beats best-static-regime in **2/8**
- SM passes p<0.05 on lockbox: **6/8**
- **The "trending-only" filter is the WORST option** — it discards ranging fires which are 87% of profitable trades

**Sanity check vs single-agnostic stack** (`data/v4/canonical/_results/regime_agnostic_baseline_stacks.csv`):
SM totals **$22,753** vs single-agnostic-stack totals **$41,729** on lockbox. **State-machine loses to one well-chosen gate** in 5/8 cases. `g_hurst_trending=1` alone takes 4 of the 8 sleeves with $19k+ from one sleeve.

---

## 4. Cross-regime insights — universal vs regime-specific gates

`data/v4/canonical/_results/regime_gate_lift_per_regime.csv`

### Universal gates — positive lift in ALL 3 regimes (≥4 sleeves)

| gate=sign | ranging lift | trending_dn lift | trending_up lift | avg |
|-----------|--------------|------------------|------------------|-----|
| g_flow_with_and_no_whale=0 | 8.91 | 8.15 | 2.66 | **5.08** |
| g_trend_slope_strong_with=1 | 4.05 | 3.32 | 1.03 | 2.48 |
| g_imb5_strong_with=1 | 4.19 | 2.93 | 1.01 | 2.43 |
| g_mfi_with=0 | 3.37 | 0.16 | 4.07 | 2.15 |
| **g_hurst_trending=1** | 1.80 | 3.69 | 0.21 | **1.78** |
| g_trend_slope_with=1 | 1.80 | 3.69 | 0.21 | 1.78 |
| g_queue_top_high=1 | 2.18 | 0.74 | 2.12 | 1.75 |
| g_markov_with=0 | 0.84 | 0.64 | 2.58 | 1.54 |
| g_bb_pos_with=1 | 0.36 | 0.39 | – | 1.02 |

The "flow with and no whale" gate is the strongest universal — value comes from removing big-money fades. `g_hurst_trending=1` and `g_trend_slope_with=1` are duplicates that work everywhere — they ARE the regime signal embedded.

### Polarity-reversal gates — bet OPPOSITE direction by regime

| gate=sign | ranging | trending_dn | trending_up |
|-----------|---------|-------------|-------------|
| g_tr_above_ema800=0 | +2.76 | -3.32 | +5.07 |
| g_vol_contracting=0 | +0.63 | -2.31 | +1.36 |
| g_tr_within_adr=0 | +1.41 | -2.18 | +1.83 |
| g_hawkes_imbalance_with=1 | +0.04 | -1.78 | +2.00 |
| g_tight_ribbon=1 | +0.63 | -1.10 | +1.30 |

These are dangerous if used regime-agnostic — `g_tr_above_ema800=0` LIFTS in trending_up (+5.07) but KILLS in trending_dn (-3.32). State-machine logic IS warranted for them, but the absolute lift is small relative to picking `g_hurst_trending=1`.

### Trending-specific (positive in trending, ~zero in ranging)

| gate=sign | ranging | trending |
|-----------|---------|----------|
| g_mp_no_extreme=0 | 0.03 | +3.00 dn |
| g_mp_change_with=0 | 0.10 | +0.96 dn |
| g_hawkes_imbalance_with=1 | 0.04 | +2.00 up |
| g_hl_liq_cascade_with=0 | 0.11 | +3.46 dn |

### Ranging-specific (positive in ranging, ~zero or negative in trending)

| gate=sign | ranging | trending_up |
|-----------|---------|-------------|
| g_tr_above_ema800=0 | +2.76 | +5.07 |
| g_tr_within_adr=0 | +1.41 | +1.83 |
| g_hl_liq_cascade_with=1 | +1.09 | +1.93 |
| g_vol_high=1 | +0.98 | +0.03 |
| g_tight_ribbon=1 | +0.63 | +1.30 |

Ranging benefits from "vol-high + tight ribbon" — micro-volatility filters. Trending benefits from "no whale + strong imbalance" — directional confirmation.

---

## 5. Regime-transition signal (TASK 6)

`data/v4/canonical/_results/regime_transition_signal.csv`

| transition (5min back -> current) | n total | avg wr | avg mean $/tr | sum $ |
|-----------------------------------|---------|--------|---------------|-------|
| trending_dn -> ranging | 2,291 | 78.2% | **+3.22** | 6,248 |
| ranging -> trending_up | 1,512 | 80.5% | +2.43 | 3,446 |
| trending_up -> ranging | 1,506 | 75.5% | +1.33 | 1,195 |
| ranging -> trending_dn | 2,371 | 73.9% | **+0.38** | 3,048 |
| Baseline (no transition) | 37,406 | 73.8% | +2.32 | 73,340 |

**Finding**: regime-transitioned fires perform similarly to non-transitioned (mean +1.89 vs +2.32) — **transitions don't dominate as a signal**. But the direction matters:
- **trending_dn -> ranging** is the BEST setup (+39% above baseline mean $/tr) — markets recovering from sell-offs are exploitable
- **ranging -> trending_dn** is the WORST (-84% below baseline) — fading entries into downtrends is bad
- WR is higher across the board for transitions (+3-7 pp) but mean $/tr is mixed — transitions reduce risk but also expected return

Not a primary deploy signal. Could add as a **secondary filter on top of trending_dn fires** to avoid ranging->trending_dn entries.

---

## 6. Top NEW regime-aware deployable sleeves

Based on robust state-machine (train+val→lockbox), only **2 sleeves are clear wins** vs baseline:

### Sleeve 1: `poly_updown_btc_5m_s15_off60-150` REGIME-AWARE
- **Lockbox**: n=2,881, WR=77.6%, $/tr=$4.60, **sum=$13,262 (4.8d → $2,763/day)** vs baseline $1,665/day (+66%)
- Stacks: TU=`g_hl_liq_cascade_with=1 & g_rf_with=1`; TD=`g_cci_with=1 & g_queue_top_high=1 & g_tr_stack_with=1 & g_ribbon_agrees=1`; R=`g_hurst_trending=1`
- p_boot=0.000
- Caveat: 96% of profit comes from the ranging stack (=`g_hurst_trending=1`). Effectively this is **single-gate regime-agnostic** with vestigial trending logic.

### Sleeve 2: `poly_updown_sol_5m_s6_off0-60` REGIME-AWARE
- **Lockbox**: n=285, WR=80.7%, $/tr=$4.59, **sum=$1,308 vs baseline $1,295 (+1%)** — basically flat
- Trending stacks are empty (insufficient n). Only marginal improvement.

### Sleeve 3 (single-stack winners that beat SM): `poly_updown_btc_5m_s15_off150-240` AGNOSTIC
- Single stack `g_hurst_trending=1` → lockbox n=4,318, WR=71.9%, $/tr=$4.50, **sum=$19,415 (4.8d → $4,045/day)**
- p_boot=0.000

### Sleeve 4: `poly_updown_btc_5m_s6_off0-60` AGNOSTIC
- Single stack `g_markov_with=0` → lockbox n=342, WR=79.8%, $/tr=$7.12, **sum=$2,435**
- p_boot=0.000

### Sleeve 5: `poly_updown_eth_5m_s15_off60-150` AGNOSTIC
- Stack `g_hurst_trending=1 & g_imb_change_with=0 & g_mp_change_with=0` → lockbox n=346, WR=82.1%, $/tr=$4.10, **sum=$1,418**
- p_boot=0.000

**Aggregate lockbox sum across top 5 deployables = $37.8k over 4.8 days → ~$7.9k/day at $25 stake** (legacy fee, real Polymarket fees flip 30-40% off).

---

## 7. Strict 3-way validation

- **Train (May 1 → 14)**: 14d for stack discovery
- **Val (May 14 → 21)**: 7d for stack stability check
- **Lockbox (May 21 → 25)**: 4.8d strict out-of-sample
- **Bootstrap p**: 500 shuffles on lockbox PnL series

| sleeve | strict SM p_boot | robust SM p_boot | passes (p<0.05) |
|--------|------------------|------------------|-----------------|
| btc_s6_off60-150 | 0.008 | 0.000 | YES |
| btc_s15_off150-240 | 0.000 | 0.000 | YES |
| btc_s6_off0-60 | 0.000 | 0.000 | YES |
| btc_s15_off60-150 | 0.000 | 0.000 | YES |
| eth_s6_off60-150 | 0.086 | 0.124 | NO |
| btc_s15_off240-300 | 0.926 | 0.620 | NO |
| eth_s15_off60-150 | 0.000 | 0.000 | YES |
| sol_s6_off0-60 | 0.000 | 0.000 | YES |

**Lockbox pass count: 6/8 SM sleeves p<0.05. 8/8 single-agnostic-stack sleeves p<0.05.** Single-stack approach is more robust.

---

## 8. Conclusion & recommendation

**The hypothesis "each regime needs its own stack" is WEAKLY supported on lockbox** — per-trade quality improves but trade volume collapses. Net dollar PnL is lower than picking one good gate.

**Why**: 87% of fires occur in ranging regime, so the "ranging stack" matters most. The best gate for ranging (`g_hurst_trending=1`) ALSO works in trending regimes (universal). Adding regime-specific logic on top removes valid fires without compensating with better picks.

**The regime IS captured by existing gates**:
1. `g_hurst_trending=1` — works in all 3 regimes
2. `g_trend_slope_strong_with=1` — works in all 3
3. `g_imb5_strong_with=1` — works in all 3

**Recommendation**:
- Do NOT deploy regime-conditional state-machines.
- DEPLOY the simpler single-gate filters (`g_hurst_trending=1`, `g_markov_with=0`) — they are the regime signal already.
- Track the **trending_dn -> ranging transition** as a secondary boost — explicit 39% mean-PnL lift.
- Keep regime classification as an **interpretability tool** (debug why a sleeve drifts) but not as a fire gate.

The 2 sleeves where SM did add value (btc_s15_off60-150, sol_s6_off0-60) both reduced to nearly-single-gate after greedy collapse — so even there, the "state machine" became "1 gate active across all states".

---

## Outputs

- `data/v4/canonical/_results/regime_distribution_per_sleeve.csv`
- `data/v4/canonical/_results/regime_conditional_optimal_stacks.csv`
- `data/v4/canonical/_results/regime_conditional_optimal_stacks_robust.csv`
- `data/v4/canonical/_results/regime_state_machine_sleeves.csv`
- `data/v4/canonical/_results/regime_state_machine_robust.csv`
- `data/v4/canonical/_results/regime_agnostic_baseline_stacks.csv`
- `data/v4/canonical/_results/regime_gate_lift_per_regime.csv`
- `data/v4/canonical/_results/regime_transition_signal.csv`
- `strategy_lab/regime_conditional_gates_2026_05_26.py` (main pipeline)
