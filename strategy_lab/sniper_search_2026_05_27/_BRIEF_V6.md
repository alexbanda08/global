# Sniper Search Brief V6 — 2026-05-27

Round V6 = "relaxed bar + Kelly sizing + early/pre-window entries + composable gates".

Read this BEFORE doing any V6 work. Supersedes [_BRIEF.md](./_BRIEF.md) where they conflict.

---

## 0. What changed vs V5

V5 found 14+ deployable sleeves but constrained to: WR≥75%, LS≤6, n≥50, single $25 stake. Operator now relaxes constraints and adds variable sizing.

### V6 directives (from operator)

1. **Loss streak ≤ 14 is OK** if $/tr compensates (was ≤6 in V5).
2. **No $250 testing.** Max stake $25, opening ops at $5–$8. Drop `g_book_depth_supports_250`, `g_depth_250_strict` as gates.
3. **Kelly-style variable sizing**: per-fire conviction score → stake size in `[$5, $25]`. Higher conviction = bigger stake.
4. **Early or pre-window entries** are encouraged. Production momo family fires at `ws_s + window_s + 60` (offset=60). V6 should explore offset∈{0, 30, 60} AND pre-window signal evaluation at `ws_s`, `ws_s−30s`, `ws_s−60s` (fire executed at slot_start+0).
5. **Composable gate stacks**: 4–10 gates per stack is fine. Higher gate count → higher conviction → bigger stake.
6. **Higher $/tr is the primary objective.** Maximize `$/tr × sqrt(n)`, not pure WR.
7. **Per-market individual** (already V5 convention).
8. **Try NEW things**: weighted-gate ensembles, score-thresholded firing, asymmetric directional sleeves.

---

## 1. Kelly sizing — exact spec

Binary outcome market (UP token resolves to $1 or $0). Per fire, given:

- `entry_vwap` = L25 book-walk fill price (0 < vwap < 1)
- `p` = expected win probability from the sleeve's gate conviction score
- `payout_won = (1 - vwap) * shares * 0.98` (legacy 2% fee on profit)
- `payout_lost = -vwap * shares`

Per-share profit/loss ratio:
```
b = (1 - vwap) * 0.98 / vwap        # profit per dollar risked, if won
```

Full Kelly fraction:
```
f_full = (p * b - (1 - p)) / b      # fraction of bankroll to bet
```

V6 uses **0.25× fractional Kelly** (quarter-Kelly) to be conservative:
```
f_kelly_25 = max(0, 0.25 * f_full)
```

Translate to dollar stake within operator bounds:
```
STAKE_MIN = 5.0
STAKE_MAX = 25.0

# Direct stake from Kelly (capped to bounds)
stake_kelly = clip(f_kelly_25 * STAKE_MAX, STAKE_MIN, STAKE_MAX)

# Alternative: conviction-score linear interpolation (simpler, no payout-rate dependence)
stake_linear = STAKE_MIN + (STAKE_MAX - STAKE_MIN) * conviction_score   # conviction ∈ [0,1]
```

**Use `stake_kelly` for sleeves where the agent has computed `p` empirically per conviction bucket. Use `stake_linear` when conviction is a simple gate-count fraction.**

### Conviction score derivation

Three options, agent picks per sleeve:

**Option A — gate-count:**
```
conviction = (# extra gates passing beyond minimum required) / (# extra gates available)
```

**Option B — empirical WR per bucket:**
- During search, partition gated fires into conviction buckets by `# gates passing`
- Compute empirical WR per bucket
- At deploy: `p = empirical_WR[bucket(fire)]`

**Option C — weighted gate score:**
- Each gate has a precomputed weight = log(WR_with_gate / WR_without_gate)
- conviction = sum_passing_gate_weights / sum_all_gate_weights

Agents should document which option they used per sleeve. Option B is preferred when n is large.

---

## 2. Pre-window / early-entry mechanics

### How production momo does it (source-of-truth)

`/opt/tradingvenue/backend/app/engine/poly_updown_loop.py` function `build_bar_context_t_plus_120/60`:

1. At time `ws_s` (= `slot_start - window_s`), compute F7 RSI and other features using 15 closes back from `ws_s` (LAST close == close at `ws_s`).
2. Make UP/DOWN decision based on those features.
3. Queue order to fire at `fire_us = (ws_s + 60) * 1_000_000` for v2 sleeves OR `fire_us = (ws_s + 120) * 1_000_000` for v1 sleeves.

The SIGNAL is anchored at `ws_s` (one window before slot start). The FILL happens 60s or 120s after `ws_s`.

For V6: any sleeve that anchors signal at `ws_s` and fills at `offset_s ∈ {0, 30, 60}` is "pre-window signal + early-fire".

### Available offsets in v3 fires

Current v3 fires (`oos_fires_{ASSET}_{TF}_full_v3.parquet`) include:
- 5m: offsets {30, 60, 90, 120, 150, 180, 210, 240, 270}
- 15m: offsets {60, 120, 240, 360, 480, 600, 720, 840}

**Offset=0 was NOT built.** If you need it, build a small extension (1 market at a time) using `build_oos_one_asset_tf` from `strategy_lab/full_window_validation_v2.py` with offsets=[0,15,30] added. Otherwise: use offset=30 (earliest available) as the "early fire" proxy.

### Pre-window signal anchor

Compute gate values at:
- `ws_s` (signal time = slot_start − window_s)
- `ws_s − 30s` (one bar earlier for 5m, 2 bars earlier for 15m)
- `ws_s − 60s`

The CORRECT causal anchor for gate evaluation is at the chosen pre-window time, NOT at `fire_us`. Example for v3 fires at offset=30:
- `slot_start_us` from the row
- `ws_s = slot_start_us // 1e6 - window_s`
- `signal_ts_us = ws_s * 1_000_000` (anchored at ws_s)
- Asof-join feature panels at `signal_ts_us` (not at `fire_us`)

The fire still HAPPENS at offset=30, but the GATE EVALUATION uses `ws_s`-anchored features. This gives more lead time, less data, and matches production momo behavior.

---

## 3. Updated sniper target profile

| Metric | V5 (strict) | V6 (relaxed) |
|---|---|---|
| n / 32d | 50-500 | **30-2000** (don't cap; if WR holds, more trades better) |
| WR on lockbox | ≥75% | **≥65%** (lower OK if $/tr compensates) |
| $/tr @ $25 stake | ≥$3 | **≥$4** (higher bar, since fewer trades expected per stake$) |
| Max DD @ $25 stake | ≤$300 | **≤$500** (relaxed) |
| Max loss streak | ≤6 | **≤14** (relaxed per operator) |
| Bootstrap p (lockbox) | ≤0.05 | ≤0.05 (KEPT — statistical significance non-negotiable) |
| $250 viability | required for ETH/SOL | **DROPPED** entirely |
| Sharpe (daily approx) | ≥2.0 | ≥1.5 (relaxed) |

**Primary objective**: maximize `lockbox_$/tr × sqrt(lockbox_n)` (Sharpe-flavored expected dollar lift).
**Tiebreaker**: lower DD, fewer loss streaks.

---

## 4. NEW gate ideas to explore (composable building blocks)

These are HYPOTHESES — agents should test them and report which work.

### Early-vwap-improvement gates
- `g_early_vwap_better` = at offset=30, entry_vwap < median_vwap_at_offset_120 for same direction
- `g_book_thin_at_open` = L25 events in first 30s < 5 (thin book → easier mid-price fills)

### Pre-window momentum
- `g_prewindow_rsi_extreme(direction, ws_s)` = F7 RSI at ws_s in extreme zone matching direction
- `g_prewindow_m1v(direction, ws_s)` = M1V Markov state at ws_s matches BET direction
- `g_prewindow_xa_unanimity(direction, ws_s − 30s)` = all 3 asset RFs agree at ws_s−30s

### Microprice change pre-window
- `g_mp_change_500ms_with(direction, ws_s)` = microprice change in last 500ms before ws_s aligned with direction

### Composable depth-tradability (replaces $250 depth gates)
- `g_book_supports_stake(stake_usd)` = L25 cumulative depth on chosen side > 6 × stake_usd
  - For stake=$25: depth > $150
  - For stake=$5: depth > $30
- Use this in the FILL stage, not as a search-time gate. Just skip fire if depth fails for actual stake.

### Asymmetric direction
- For markets where UP signal is statistically stronger than DOWN (or vice versa), test UP-only or DOWN-only sleeves.
- BTC 15m V5 found DOWN-dominant. ETH 15m V5 found UP-dominant. Confirm pattern + extend.

### Time-of-day composable
- `g_hod_european_morning` = 07:00-11:00 UTC
- `g_hod_us_morning` = 13:00-17:00 UTC
- `g_hod_overnight` = 23:00-05:00 UTC
- Stack these conditionally.

### VWAP-position
- `g_entry_vwap_in_band(low, high)` = entry vwap ∈ [low, high]. E.g., `g_entry_vwap_in_band(0.10, 0.65)` to avoid lottery tickets AND avoid heavy favorites.

---

## 5. Search methodology — V6

### Phase 1: per-market discovery
Each per-market agent:
1. Load v3 fires for their (asset, tf)
2. Join all feature panels (causal asof at `ws_s` for pre-window OR at `fire_us - 1_000_000` for early-fire)
3. Build conviction-score table:
   - Run gate-search over composable atoms
   - For each surviving stack, compute conviction buckets via Option B (empirical WR per # gates passing)
   - Compute per-bucket Kelly-25 stake
4. Apply V6 sniper bar (§3 above)
5. Pick top 5 sleeves

### Phase 2: per-sleeve Kelly validation
For each top sleeve, output a stake table:

| conviction_score | empirical_p | recommended_stake | example_fire_outcome |
|---|---|---|---|
| 0.0 | 0.65 | $5 | hypothetical fire @ vwap=0.55, won → +$2.0 |
| 0.5 | 0.78 | $14 | ... |
| 1.0 | 0.89 | $25 | ... |

Plus a SIMULATED PnL using the variable-stake schedule vs constant $25 stake (to quantify Kelly uplift).

### Phase 3: per-market report
Same format as V5 (`SNIPER_{MARKET}_V6_REPORT.md` + `top_5_candidates_v6.csv` + cumulative PnL PNGs) but include:
- Kelly stake table per sleeve
- Conviction-bucket histogram
- Simulated variable-stake PnL vs constant $25 PnL

### Phase 4: cross-market correlation (aggregator)
After all 6 markets done, the aggregator (separate agent) runs slug-overlap and produces V6 deploy roster with stake schedule.

---

## 6. Data paths (same as V5)

- v3 fires: `data/v4/canonical/_results/_full_window_v3_2026_05_27/oos_fires_{ASSET}_{TF}_full_v3.parquet`
- Regime: `data/v4/canonical/_results/regime_panel_{TF}_v2_fixed.parquet`
- SMS: `data/v4/canonical/_results/sms_panel_{TF}_v2_fixed.parquet`
- Microprice: `data/v4/canonical/_results/microprice_panel.parquet`
- TA/RF/TR: `data/v4/canonical/_results/{ta_indicators_1s, range_filter_1s, traders_reality_1s}.parquet`
- Vol: `data/v4/canonical/_results/vol_hurst_at_fire_{5m,15m}.parquet`
- LM/Hawkes/VPIN/MP/Microstructure: see V5 brief §5
- Master gates (precomputed 37 gates): `data/v4/canonical/_results/master_gate_features_v2.parquet`
- F7 RSI per fire: in v3 fires as column `f7_rsi_at_ws` IF present, else compute from binance 1m
- Markov M1V: in master_gate_features_v2 as `g_markov_with` and `m1v_state`

---

## 7. Conventions (UNCHANGED from V5)

- ws_s = slot_start_us//1e6 - window_s
- Outcome: chainlink `outcome`
- Fee: `engine_v2.LegacyConfig` (2%-on-profit)
- L25 walk: `engine_v2.fill_at_book` with spread_filter (0.02 BTC/ETH, 0.025 SOL)
- Bug-fixed panels only (`*_v2_fixed`)
- No mid-slot exits, no SL/TP
- 3-way split chronological: train 18d / val 6d / lockbox 4d (or per-cohort adapt)

---

## 8. Output spec

Per agent, write to `strategy_lab/sniper_search_2026_05_27/{market_slug}_v6/`:

1. `top_5_candidates_v6.csv` — columns:
   `sleeve_id, anchor (ws_s|offset_NMs), gate_stack, conviction_method (A|B|C), n_train, n_val, n_lockbox, wr_train, wr_val, wr_lockbox, dpt_25_lockbox, sum_25_28d_const, sum_25_28d_kelly, max_dd_25, loss_streak, sharpe, bootstrap_p_lockbox`

2. `kelly_stake_table_{sleeve_id}.csv` per top sleeve — conviction buckets + stake recommendations

3. `SNIPER_{MARKET}_V6_REPORT.md` — sections:
   - Top 3-5 candidates with full metric tables
   - Kelly stake schedule per top sleeve
   - Variable-stake vs constant-$25 PnL comparison
   - **Pre-window vs early-fire vs late-fire analysis** (which timing won?)
   - Failed approaches (honest reporting)
   - Confidence per candidate (LOW/MED/HIGH)

4. `cumulative_pnl_kelly_vs_const_{sleeve_id}.png` — for each top candidate

5. Code in `scripts/`

### Concise return to orchestrator (<300 words):
- # candidates meeting V6 profile
- Best candidate's gate stack + Kelly stake range + projected 28d PnL (variable stake)
- Pre-window vs early-fire vs late-fire winner timing
- Top failure
- Confidence
- Report path

---

## 9. Quick test for "is my new gate causal"

Before adding ANY new gate (especially pre-window ones), run this sanity check:

```python
# For each fire, compute gate at ws_s AND at fire_us+epsilon (post-fire)
# A truly causal gate's prediction at ws_s should be EQUAL to its prediction at fire_us
# (since both use only data up to ws_s)
# If they differ → lookahead bug, gate is using future data
gate_at_ws = compute_gate(fires, panel, anchor='ws_s')
gate_at_fire = compute_gate(fires, panel, anchor='fire_us')
assert (gate_at_ws == gate_at_fire).all(), "LOOKAHEAD DETECTED — gate evaluation moved with time"
```

---

## 10. NOT to repeat (carry-forward from V5 lessons)

- Don't sum sleeve PnL without slug-overlap dedup (#1 bug across sessions)
- Don't use original (non-`_v2_fixed`) regime/sms panels
- Don't anchor on slot_start — use ws_s OR fire_us−1_000_000 epsilon
- Don't use `g_book_depth_supports_250` or `g_depth_250_strict` (operator dropped $250)
- Don't trust 22d backtests alone — lockbox must pass bootstrap p≤0.05
- Don't test PVSRA, MLOFI, VPIN-skip, LightGBM-primary, AS-uncertainty (confirmed -EV in V5)
- Don't anchor F7 RSI at fire_us — anchor at ws_s (V5 conv §7 in main BRIEF.md)
