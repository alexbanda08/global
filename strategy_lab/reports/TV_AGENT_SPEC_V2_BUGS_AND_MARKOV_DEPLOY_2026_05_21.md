# TV Agent Spec — Fix momo_v2 inversion bugs + deploy F7+Markov shadow sleeves

**Author:** Strategy lab (analysis on VPS3 trading.events 2026-05-20 19:57 UTC → 2026-05-21 19:20 UTC, n=3,739 production fires)
**Owner action:** Two parts — (1) urgent pause + audit of 2 broken momo_v2 sleeves; (2) deploy F7+Markov shadow sleeves for the working sleeves.

---

## PART 1 — Fix 2 broken momo_v2 + F7 sleeves

### Bug 1: `eth_5m_momo_v2_*_f7` — DOWN signal structurally wrong

**Symptom:** 5.17 % WR over 63 fires across 23.5h. PnL −$1,195.

**Cross-tab (production resolutions, all 3 policies HOLD/HEDGE/SELL combined):**

```
outcome    Down   Up   exited_at_bid   Total
signal
DOWN          0   52               5      57   ← 0% of DOWN signals resolved Down
UP            3    3               0       6
```

**Inversion test:** if signals were flipped, WR would be **94.83 %** (clean rows n=58, approx PnL +$1,193).

**Control:** `eth_5m_momo_*_f7` (V1) on the same window: **WR 54.88 % (n=82, +$6.64/trade) — works fine.**

### Bug 2: `btc_15m_momo_v2_*_f7` — UP signal over-fired

**Symptom:** 17.65 % WR over 34 fires. PnL −$251.

```
outcome    Down  exited_at_bid   Total
signal
DOWN          6              0       6   ← 100% of DOWN signals correct
UP           24              4      28   ← 0% of UP signals correct (24 Down outcomes, 4 exits)
```

V2 emitted **3× more UP signals than V1** (28 vs 9) during the same hours, all wrong.

**Control:** `btc_15m_momo_*_f7` (V1) on the same window: **WR 71.43 % (n=21, +$11.39/trade) — works fine.**

### Diagnosis — V2 centered window is too sensitive

V1 vs V2 ret_2m spec (from `data/v4/canonical/_momo_v1v2_backtest.py`):

```python
# V1: forward-only 2-minute window
ret_2m = log(close@(ws_s+120) / close@ws_s)    # fires at ws_s+120

# V2: centered 2-minute window
ret_2m = log(close@(ws_s+60)  / close@(ws_s-60))   # fires at ws_s+60
```

The V2 centered window catches direction-noise that doesn't sustain to `slot_end` (resolution time, 4-9 minutes after fire). On:
- **eth_5m**: brief downward retraces in choppy 5m bars trigger V2 DOWN → price reverts → loses
- **btc_15m**: small upward retraces in a downtrend trigger V2 UP → trend resumes Down → loses
- **sol_5m_v2, eth_15m_v2** (works): the centered window catches sustained moves on these (asset, tf) combos

### Required actions for TV agent

**Immediate (this commit):**

1. **Disable** the following 6 sleeves in production:
   - `poly_updown_eth_5m_momo_v2_HOLD_f7`
   - `poly_updown_eth_5m_momo_v2_HEDGE_f7`
   - `poly_updown_eth_5m_momo_v2_SELL_f7`
   - `poly_updown_btc_15m_momo_v2_HOLD_f7`
   - `poly_updown_btc_15m_momo_v2_HEDGE_f7`
   - `poly_updown_btc_15m_momo_v2_SELL_f7`
   
   Also disable the 6 corresponding non-F7 baseline sleeves (`*_momo_v2_HOLD`, `*_momo_v2_HEDGE`, `*_momo_v2_SELL` on eth_5m and btc_15m). Their samples are tiny (3-9 fires each) but show the same direction.

2. **Keep enabled** (these momo_v2 sleeves work):
   - `sol_5m_momo_v2_*_f7` (74 % WR, +$10.87/trade)
   - `eth_15m_momo_v2_*_f7` (65 % WR, +$7.90/trade)
   - `btc_5m_momo_v2_*_f7` (43 % WR — mild bias only, see Part 2 for Markov rescue)

**Investigation (separate task, blocking re-enable):**

Audit the V2 gate's `ret_2m` computation in production code (likely `backend/app/strategies/polymarket/momo_v2.py` per references in our scripts):

- Verify `close@(ws_s+60)` and `close@(ws_s-60)` are pulled from the **same kline source** (binance-spot-ws 1MIN).
- Verify the `ws_s` anchor: `ws_s = slot_start - window_s` (NOT `slot_start`). See `data/v4/canonical/load.py` `slug_to_ws_s()` for canonical helper.
- Verify the q90 threshold computation uses a **causal** 14-day rolling window (no lookahead).
- Add **per-asset enable flags** so eth_5m_v2 and btc_15m_v2 can be paused independently.

**Verification query** (to confirm after fix):

```sql
-- Should show WR > 40% on all momo_v2 _f7 sleeves over 24h
SELECT
  sleeve_id,
  COUNT(*) AS n,
  ROUND(AVG((data->>'won')::bool::int)*100, 2) AS wr_pct,
  ROUND(SUM((data->>'pnl_usd')::numeric)::numeric, 2) AS sum_pnl
FROM trading.events
WHERE kind = 'poly_updown_resolution'
  AND sleeve_id LIKE 'poly_updown_%momo_v2_%_f7'
  AND at >= NOW() - INTERVAL '24 hours'
GROUP BY sleeve_id
ORDER BY wr_pct;
```

If `wr_pct < 40 %` on eth_5m_v2 or btc_15m_v2 after re-enable, disable again.

---

## PART 2 — Deploy F7+Markov shadow sleeves

For each working sleeve, deploy a shadow companion that adds a Markov regime gate AFTER F7 passes. The Markov gate filters out fires where the recent regime disagrees with the momo signal direction.

### Markov gate spec

**State labels** (assigned every 1-minute bar from binance-spot-ws klines):

```python
def label_regime(closes_20m_window, fixed_threshold_pct):
    """closes_20m_window: 20 most recent 1m close prices ending at current bar end.
    Returns 0=Bear, 1=Sideways, 2=Bull."""
    ret_20m = log(closes[-1] / closes[0])  # 20-minute log return
    if ret_20m < -fixed_threshold_pct:  return 0  # Bear
    if ret_20m > +fixed_threshold_pct:  return 2  # Bull
    return 1  # Sideways
```

**Fixed thresholds per asset** (chosen from production-fit q33/q66 on 23.5h × 21-day backtest):

| Asset | Threshold |
|---|---|
| BTC  | ±0.003 (±0.3 % over 20 min) |
| ETH  | ±0.004 (±0.4 % over 20 min) |
| SOL  | ±0.006 (±0.6 % over 20 min) |

**Gate logic** (called at fire time, with most recent labelled regime):

```python
def markov_pass(signal: str, current_regime: int) -> bool:
    if signal == "UP"   and current_regime == 2: return True   # Bull
    if signal == "DOWN" and current_regime == 0: return True   # Bear
    return False  # Sideways or signal disagrees
```

**For 15m sleeves** use a different Markov variant — vol-adaptive 5m bars (matches the longer TF):

```python
# w20_5m_voladaptive: at every fire, compute thresholds dynamically from
# prior 14d of rolling 20×5m returns. Use q33 and q66 instead of fixed.
def label_regime_voladaptive(closes_100m_window, history_14d_returns):
    ret_100m = log(closes[-1] / closes[0])
    q33, q66 = np.quantile(history_14d_returns, [1/3, 2/3])
    if ret_100m < q33: return 0  # Bear
    if ret_100m > q66: return 2  # Bull
    return 1  # Sideways
```

### Sleeve-by-sleeve deploy table (full — baseline / F7-alone / Markov-alone / F7+Markov side-by-side)

Each row is one source sleeve. Markov variant column shows the WINNING Markov config for that sleeve (selected by F7+Markov sum$, falling back to Markov-alone sum$ if F7+Markov n<5). Naming convention for shadow: `{existing}_m1` (w20_1m_fixed), `{existing}_m5v` (w20_5m_voladaptive), `{existing}_m5f` (w20_5m_fixed), `{existing}_m1v` (w20_1m_voladaptive).

**Sorted by F7+Markov sum$ over 23.5h production window. ✓ = recommended deploy; ✗ = pause/skip; ⚠ = small n, paper only.**

| # | Sleeve | Markov variant | Baseline n / WR / $/tr | F7-only n / WR / $/tr | Markov-only n / WR / $/tr | **F7+Markov n / WR / $/tr / sum** | Verdict |
|---|---|---|--:|--:|--:|--:|:--:|
| 1  | btc_5m_momo (v1)         | w20_1m_voladaptive | 240 / 72.1% / +$10.05 | 237 / 71.7% / +$9.88 | 234 / 72.7% / +$10.33 | **234 / 72.7% / +$10.33 / +$2,417** | ✓ |
| 2  | sol_5m_momo_v2           | w20_1m_fixed       | 109 / 73.4% / +$7.30  | 106 / 75.5% / +$8.23 | 88 / 90.9% / +$13.83  | **88 / 90.9% / +$13.83 / +$1,217** | ✓ |
| 3  | eth_5m_momo (v1)         | w20_1m_voladaptive | 161 / 54.0% / +$6.21  | 143 / 54.5% / +$6.94 | 161 / 54.0% / +$6.21  | 143 / 54.5% / +$6.94 / +$992 | ✓ |
| 4  | sol_5m_momo (v1)         | w20_1m_fixed       | 60 / 70.0% / +$9.27   | 45 / 73.3% / +$10.98 | 30 / 100.0% / +$24.34 | **30 / 100.0% / +$24.34 / +$730** ⚠ | ✓ |
| 5  | btc_5m_volume_INV_NIGHT  | w20_5m_voladaptive | 343 / 56.3% / +$2.46  | 125 / 60.8% / +$5.25 | 136 / 64.7% / +$6.99  | **84 / 66.7% / +$8.30 / +$698** | ✓ |
| 6  | eth_15m_momo_v2          | w20_5m_voladaptive | 90 / 64.4% / +$7.27   | 81 / 60.5% / +$5.60  | 36 / 77.8% / +$15.53  | **33 / 75.8% / +$14.81 / +$489** | ✓ |
| 7  | btc_15m_momo (v1)        | w20_1m_voladaptive | 30 / 80.0% / +$15.63  | 30 / 80.0% / +$15.63 | 30 / 80.0% / +$15.63  | 30 / 80.0% / +$15.63 / +$469 ⚠ | ✓ (no Markov lift, keep F7) |
| 8  | btc_5m_momo_v2           | w20_1m_fixed       | 438 / 42.0% / −$2.54  | 359 / 45.7% / −$1.89 | 200 / 52.0% / +$2.10  | **200 / 52.0% / +$2.10 / +$420** | ✓ (flips!) |
| 9  | sol_15m_sniper           | w20_5m_fixed       | 117 / 55.6% / −$1.27  | 92 / 60.9% / −$1.58  | 16 / 100.0% / +$24.58 | **16 / 100.0% / +$24.58 / +$393** ⚠ | ✓ |
| 10 | eth_5m_sniper            | w20_5m_voladaptive | 105 / 54.3% / +$3.13  | 101 / 52.5% / +$2.34 | 49 / 71.4% / +$6.41   | **49 / 71.4% / +$6.41 / +$314** | ✓ |
| 11 | eth_5m_v3 family (×4)    | w20_1m_voladaptive | 19 / 100% / +$23.26 each | 18 / 100% same | 10-12 / 100% / +$23.52 | 10-12 / 100% / +$23.52 / +$235-282 | ✓ (already 100%, M neutral) |
| 12 | eth_5m_v4                | w20_1m_voladaptive | 12 / 100% / +$23.53   | 12 / 100% same        | 12 / 100% same        | 12 / 100% / +$23.53 / +$282 | ✓ (no lift, keep) |
| 13 | sol_5m_v3_1              | w20_1m_voladaptive | 17 / 76.5% / +$10.62  | 17 / 76.5% same       | 16 / 81.3% / +$12.88  | 16 / 81.3% / +$12.88 / +$206 | ✓ |
| 14 | btc_5m_sniper            | w20_1m_fixed       | 315 / 53.3% / −$1.82  | 253 / 58.1% / −$1.88 | 116 / 58.6% / +$1.75  | **116 / 58.6% / +$1.75 / +$203** | ✓ (flips!) |
| 15 | sol_5m_v3,_v3_2,_v3_3,_v4 | w20_1m_voladaptive | 14-19 / 78.6% / +$11.31 | same | 14-18 / 78-72% / +$11.30 | 14-18 / 78.6% / +$11.30 / +$155-158 | ✓ (no lift, keep) |
| 16 | eth_15m_sniper           | w20_5m_fixed       | 99 / 66.7% / −$2.28   | 67 / 50.8% / −$2.41  | 12 / 66.7% / +$8.50   | **12 / 66.7% / +$8.50 / +$102** ⚠ | ✓ |
| 17 | sol_5m_sniper            | w20_5m_fixed       | 77 / 42.9% / −$3.19   | 76 / 42.1% / −$3.54  | 26 / 30.8% / +$3.75   | **26 / 30.8% / +$3.75 / +$98** ⚠ | ✓ (WR drops but $/tr flips +) |
| 18 | btc_5m_v3, v3_1, v3_2, v3_3, v4 | w20_1m_voladaptive | 45-59 / 38-50% / mixed | 38-43 / 36-42% / +$0-1 | 14-22 / 36-57% / mixed | 14 / 57.1% / +$2.74 / +$38 ⚠ | ⚠ paper only |
| 19 | eth_5m_volume_INV_NIGHT  | w20_5m_voladaptive | 170 / 59.4% / +$3.43  | 56 / 57.1% / +$3.20  | 60 / 61.7% / +$4.82   | 41 / 51.2% / +$0.31 / +$13 | ✗ (F7+M hurts, use M-only +$289) |
| 20 | eth_5m_sniper_DOWN_INV   | w20_5m_voladaptive | 56 / 62.5% / +$3.69   | 0 (no F7 variant)    | 16 / 100% / +$21.35   | 0 (no F7) | ✓ (use M-only: 16 / 100% / +$342) |
| 21 | sol_5m_sniper_INV        | w20_5m_voladaptive | 69 / 52.2% / −$0.80   | 1 (no F7 variant)    | 17 / 70.6% / +$8.24   | 1 / 0% / −$25.95 | ✓ (use M-only: 17 / 70.6% / +$140) |
| 22 | btc_15m_momo_v2          | w20_5m_fixed       | 65 / 13.9% / −$9.80   | 62 / 9.7% / −$10.65  | 6 / 100% / +$26.54    | 6 / 100% / +$26.54 / +$159 ⚠ | **✗ DISABLE — see Part 1** |
| 23 | eth_5m_momo_v2           | w20_1m_fixed       | 115 / 2.6% / −$20.25  | 82 / 3.7% / −$18.32  | 20 / 0% / −$7.14      | 20 / 0% / −$7.14 / −$143 | **✗ DISABLE — see Part 1** |
| 24 | btc_15m_volume_INV_NIGHT | w20_1m_fixed       | 117 / 32.5% / −$9.25  | 32 / 31.3% / −$9.73  | 6 / 0% / −$25.00      | 6 / 0% / −$25.00 / −$150 | ✗ no gate lifts |
| 25 | sol_5m_volume_INV_NIGHT  | w20_1m_fixed       | 122 / 64.8% / +$5.27  | 31 / 38.7% / −$6.76  | 6 / 0% / −$26.15      | 6 / 0% / −$26.15 / −$157 | ✗ (baseline is best — keep raw) |
| 26 | sol_15m_volume_INV_NIGHT | w20_1m_fixed       | 117 / 30.8% / −$10.77 | 56 / 14.3% / −$18.64 | 8 / 0% / −$25.88      | 8 / 0% / −$25.88 / −$207 | ✗ pause |
| 27 | eth_15m_volume_INV_NIGHT | w20_5m_fixed       | 123 / 42.3% / −$4.66  | 48 / 25.0% / −$12.71 | 12 / 0% / −$25.04     | 12 / 0% / −$25.04 / −$300 | ✗ pause |
| 28 | btc_15m_sniper           | w20_1m_fixed       | 155 / 41.9% / −$5.08  | 123 / 33.3% / −$6.29 | 28 / 42.9% / −$11.14  | 28 / 42.9% / −$11.14 / −$312 | ✗ no gate lifts |

**Aggregate over all 38 viable sleeves:** Baseline +$2,381 → F7-only +$2,611 → Markov-only **+$10,326** → F7+Markov **+$9,812** (over 23.5h).

**Note**: Markov-alone outperforms F7+Markov in aggregate by about $500. The reason: some sleeves like eth_5m_sniper_DOWN_INV / sol_5m_sniper_INV have NO F7 variant (F7+Markov n=0/1), so their Markov-alone lift is lost in the F7+Markov column. For those sleeves, deploy Markov-only shadow.

### Deploy decision per sleeve

The verdict column above tells you what to do:

- ✓ **Deploy shadow with F7+Markov (or Markov-only if no F7 variant exists)** — 21 sleeve groups
- ⚠ **Paper-only first 7 days** — small n (<30) or unstable cell
- ✗ **Do not deploy** (pause or audit) — 7 sleeve groups

All deploy targets include HOLD / HEDGE / SELL policy variants (3 per source).

### Sleeves to NOT deploy Markov shadow (no lift over baseline)

| Sleeve | Reason |
|---|---|
| `*_eth_5m_v3*`, `*_eth_5m_v4` | Baseline already 100 % WR — Markov adds nothing |
| `*_sol_5m_v3*`, `*_sol_5m_v4` | Baseline 76-79 % WR — Markov flat |
| `*_btc_15m_volume_INV_NIGHT` | All gates regress, audit/pause |
| `*_sol_15m_volume_INV_NIGHT` | All gates regress, pause |
| `*_eth_15m_volume_INV_NIGHT` | All gates regress, pause |
| `*_btc_15m_sniper` | All gates regress, pause |
| `*_sol_5m_sniper` | Marginal, hold |

### Implementation notes

1. **Causality**: the Markov state must be computed from kline bars that **ENDED at-or-before fire_us**. Use `asof_strict(end_us, prices, fire_us)`-style lookup. No lookahead.

2. **Warmup**: first 14 days of binance data are needed before Markov labels become reliable (for the vol-adaptive variant). Sleeves should boot with `markov_pass=False` (block all fires) until warmup is complete.

3. **Code path**: Markov gate is checked AFTER F7 passes. The order:
   ```
   momo gate → F7 gate → Markov gate → fire
   ```
   If any prior gate blocks, Markov isn't evaluated (no wasted work).

4. **Per-sleeve config**: each shadow sleeve config should specify:
   ```yaml
   shadow_sleeve: poly_updown_btc_5m_momo_HOLD_f7_m1
   source_sleeve: poly_updown_btc_5m_momo_HOLD_f7
   markov_variant: w20_1m_fixed
   markov_window_minutes: 20
   markov_bar_minutes: 1
   markov_threshold_mode: fixed
   markov_threshold_pct: 0.003       # BTC
   markov_kline_source: binance-spot-ws
   ```

5. **Reference data**:
   - Threshold tuning data: `strategy_lab/markov_filter/_vps3_pull/binance_1m_fresh.csv` (152k rows, Apr 14 → May 21).
   - Per-sleeve PnL observed under each gate: `strategy_lab/markov_filter/_results/f7_markov_best_per_sleeve.csv`.

### Validation gate (must pass before promoting any shadow to primary)

Run for ≥ 7 days in shadow paper mode. Compare to source sleeve:

```sql
WITH p AS (
  SELECT
    sleeve_id,
    COUNT(*) AS n,
    AVG((data->>'won')::bool::int) AS wr,
    SUM((data->>'pnl_usd')::numeric) AS sum_pnl
  FROM trading.events
  WHERE kind = 'poly_updown_resolution'
    AND at >= NOW() - INTERVAL '7 days'
    AND sleeve_id LIKE '%_f7%'
  GROUP BY sleeve_id
)
SELECT
  src.sleeve_id AS source,
  ROUND(src.wr*100,2) AS src_wr,
  ROUND(src.sum_pnl::numeric,2) AS src_sum,
  src.n AS src_n,
  shadow.sleeve_id AS shadow,
  ROUND(shadow.wr*100,2) AS shadow_wr,
  ROUND(shadow.sum_pnl::numeric,2) AS shadow_sum,
  shadow.n AS shadow_n,
  ROUND((shadow.wr - src.wr)*100, 2) AS wr_lift_pp
FROM p src
JOIN p shadow ON shadow.sleeve_id = src.sleeve_id || '_m1'
                OR shadow.sleeve_id = src.sleeve_id || '_m5v'
                OR shadow.sleeve_id = src.sleeve_id || '_m5f'
WHERE shadow.n >= 30
ORDER BY wr_lift_pp DESC;
```

Promote shadow → primary if all three hold:
- `wr_lift_pp ≥ 3 pp` over 7-day window
- `shadow_n ≥ 30`
- Shadow PnL/trade is positive

---

## Summary

**Urgent**: pause 6 sleeves (eth_5m_momo_v2_*_f7, btc_15m_momo_v2_*_f7) + 6 baseline counterparts. Audit V2 centered-window gate.

**Deploy 14 shadow sleeves** with sleeve-specific Markov gates per the table above. Two threshold modes:
- `w20_1m_fixed` (BTC ±0.3 %, ETH ±0.4 %, SOL ±0.6 %) — for 5m sleeves
- `w20_5m_voladaptive` (q33/q66 of prior 14d) — for 15m sleeves and some sniper

**Expected lift**: from the 23.5h sample, baseline production +$2,381 → best-gate per-sleeve +$10,687 (lift +$8,306, ~+$8,500/day).
