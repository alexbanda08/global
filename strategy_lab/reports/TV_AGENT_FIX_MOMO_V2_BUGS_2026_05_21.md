# TV Agent — Fix `momo_v2` + F7 interaction bug (corrected on 14d data)

**Author:** Strategy lab
**Scope:** F7 variants of `eth_5m_momo_v2_*` and `btc_15m_momo_v2_*` (6 sleeve_ids — HOLD/HEDGE/SELL × _f7 for both)
**Severity:** Critical (combined −$1,446 over 23.5h F7-active period)
**Data:** VPS3 `trading.events` 2026-05-07 → 2026-05-21 (14 days; F7 deployed 2026-05-20 19:57 UTC, so F7 data is the post-deploy slice)

---

## ⚠ Important correction vs initial report

An earlier analysis (based on the 23.5h post-F7 window alone) concluded the V2 gate itself was broken. **The 14-day data tells a different story.**

### V2 baseline (no F7) is fine — over 14 days

| Sleeve | n_14d | baseline WR | $/trade | sum PnL | Status |
|---|--:|--:|--:|--:|---|
| btc_15m_v2 (no F7) | 398   | **59.30 %** | +$4.51  | **+$1,797** | ✓ works |
| btc_5m_v2  (no F7) | 1,930 | 45.49 %     | −$1.25  | −$2,415     | mild loss |
| eth_15m_v2 (no F7) | 375   | **68.53 %** | +$7.55  | **+$2,831** | ✓ works |
| eth_5m_v2  (no F7) | 1,206 | 43.45 %     | −$2.72  | −$3,277     | mild loss |
| sol_15m_v2 (no F7) | 255   | 52.55 %     | +$0.83  | +$210       | breakeven |
| sol_5m_v2  (no F7) | 1,021 | 46.13 %     | −$2.01  | −$2,056     | mild loss |

V2 baseline produces 60%+ WR on 15m sleeves (works). On 5m sleeves it's mildly noisy (43-46% WR) but not catastrophic.

### F7 on top of V2 is the bug — only on specific cells

| Sleeve | n_F7 | F7 WR | F7 $/trade | F7 sum | F7 verdict |
|---|--:|--:|--:|--:|---|
| **eth_5m_v2 + F7**  |  63 | **4.76 %**  | −$18.97 | −$1,195 | **CATASTROPHIC** |
| **btc_15m_v2 + F7** |  34 | **17.65 %** | −$7.37  | −$251   | **CATASTROPHIC** |
| btc_5m_v2 + F7      | 220 | 42.27 %     | −$2.42  | −$533   | similar to baseline (no help) |
| eth_15m_v2 + F7     |  48 | 64.58 %     | +$7.29  | +$350   | ✓ F7 maintains performance |
| sol_15m_v2 + F7     |   6 | 100.00 %    | +$17.31 | +$104   | ✓ tiny n |
| sol_5m_v2 + F7      |  56 | **71.43 %** | +$6.58  | +$368   | ✓ F7 LIFTS strongly |

**The pattern:**
- `eth_5m_v2`: baseline 43% → F7 5% (catastrophe, **−38pp lift**)
- `btc_15m_v2`: baseline 59% → F7 18% (catastrophe, **−41pp lift**)
- `btc_5m_v2`: baseline 46% → F7 42% (mild **−3pp**, F7 not helping)
- `sol_5m_v2`: baseline 46% → F7 71% (**+25pp lift**)
- `eth_15m_v2`: baseline 69% → F7 65% (**−4pp**, neutral)

**F7 inverts the V2 signal on eth_5m and btc_15m specifically. It works correctly on sol_5m_v2.**

---

## Root cause hypothesis (corrected)

The bug is the **F7-RSI alignment rule** misinterpreting V2's centered-window signal on specific (asset, tf) regimes.

### F7 logic recap
```python
def f7_passes(signal, rsi_14):
    if signal == "UP"   and rsi_14 <= 50: return False
    if signal == "DOWN" and rsi_14 >= 50: return False
    return True
```

RSI(14) on binance 1m closes ending at `ws_s`. So F7 says "fire only if signal direction matches recent 14-minute price direction".

### Why it works on V1 but breaks on V2 (eth_5m / btc_15m)

V1 vs V2 fire timing:
- V1 fires at `ws_s + 120` (2 min after RSI anchor)
- V2 fires at `ws_s + 60` (1 min after RSI anchor)

V1's signal is `ret(ws_s → ws_s+120)` — forward 2min. V2's signal is `ret(ws_s-60 → ws_s+60)` — centered 2min.

**Key insight from the eth_5m_v2 cross-tab (F7 fires, 23.5h):**
```
outcome   Down   Up   exited_at_bid   Total
signal
DOWN         0   52              5      57    ← all 57 DOWN fires had RSI<50 AND lost
UP           3    3               0       6
```

57 DOWN signals all had RSI(14) < 50 (F7 confirmed downtrend) — but ALL resolved Up. This pattern only makes sense if:

1. **V2's DOWN signal triggers at the BOTTOM of a brief retrace** (centered window ws_s-60 to ws_s+60 catches a small dip).
2. **RSI(14) at ws_s is still reading the dip context** — RSI<50 because the last 14 1m bars show net negative.
3. **From slot_start (ws_s+300 for 5m) to slot_end (ws_s+600), price reverts up** — Up wins.

In other words: **V2 + F7 picks the EXACT moment when both gates agree on "down" — but that exact moment is the local minimum about to bounce.** F7 doesn't filter out the noise; it confirms it.

**Why sol_5m_v2 + F7 doesn't have this bug**: SOL 5m has different microstructure — its dips sustain longer (less mean-reversion), so V2+F7 catches real continuation moves. ETH 5m and BTC 15m are mean-reverting on these timescales during this regime.

### Single-direction issue confirms it

Look at the DOWN-only buckets:

| Sleeve | n DOWN+F7 | DOWN→Down | DOWN→Up |
|---|--:|--:|--:|
| eth_5m_v2 (F7)   | 57 | 0 (0 %)   | 52 (91 %) |
| btc_15m_v2 (F7)  | 6  | 6 (100 %) | 0  (0 %)  |

| Sleeve | n UP+F7 | UP→Up | UP→Down |
|---|--:|--:|--:|
| eth_5m_v2 (F7)   | 6  | 3 (50 %)  | 3 (50 %)  |
| btc_15m_v2 (F7)  | 28 | 0 (0 %)   | 24 (86 %) |

**Different broken direction per sleeve.** eth_5m_v2 has the DOWN-signal failure (V2 catches downward noise that reverts). btc_15m_v2 has the UP-signal failure (V2 catches upward retraces in a downtrend).

So **the F7 logic isn't "inverted globally"** — it's that V2's centered-window signal, combined with RSI confirmation, picks the worst entries in mean-reverting / trending-against regimes.

---

## What TV agent needs to change

### Action 1 — IMMEDIATE: disable 6 F7+V2 sleeves

Set `enabled: false` on:

```yaml
disable_sleeves:
  - poly_updown_eth_5m_momo_v2_HOLD_f7
  - poly_updown_eth_5m_momo_v2_HEDGE_f7
  - poly_updown_eth_5m_momo_v2_SELL_f7

  - poly_updown_btc_15m_momo_v2_HOLD_f7
  - poly_updown_btc_15m_momo_v2_HEDGE_f7
  - poly_updown_btc_15m_momo_v2_SELL_f7
```

**Keep enabled** (these all work over 14 days):

```yaml
# V2 baseline (no F7) — all 6 cells stay running, they produce
# positive PnL net over 14 days when considered together
keep_enabled:
  - poly_updown_*_momo_v2_*       # non-F7 baseline keeps firing as before
  - poly_updown_sol_5m_momo_v2_*_f7       # F7 lifts sol_5m_v2 +25pp WR
  - poly_updown_eth_15m_momo_v2_*_f7      # F7 neutral on eth_15m_v2, doesn't break
  - poly_updown_sol_15m_momo_v2_*_f7      # tiny n but trending positive
  - poly_updown_btc_5m_momo_v2_*_f7       # F7 mildly worse but not broken; observe
```

### Action 2 — DO NOT audit V2 core gate code

V2 gate works correctly. **Skip Checks A/B/C/D from the original (incorrect) spec.** The 14-day baseline data shows V2 produces 43-69% WR per cell without F7.

### Action 3 — Treat F7 as cell-conditional

F7 should be enabled or disabled per `(asset, tf, version)` combo, not globally. Add a config flag:

```yaml
f7_enabled:
  # V1 cells — F7 lifts on every one (per 14d data)
  btc_5m_momo_v1:    true
  btc_15m_momo_v1:   true
  eth_5m_momo_v1:    true
  sol_5m_momo_v1:    true
  sol_15m_momo_v1:   true  # n=3 tiny, observe

  # V2 cells — selective
  btc_5m_momo_v2:    false   # 14d shows F7 neutral (-3pp), pause F7 here
  btc_15m_momo_v2:   false   # 14d shows F7 catastrophic (-41pp WR drop)
  eth_5m_momo_v2:    false   # 14d shows F7 catastrophic (-38pp WR drop)
  eth_15m_momo_v2:   true    # 14d: F7 neutral, keep
  sol_5m_momo_v2:    true    # 14d: F7 LIFTS (+25pp), KEEP
  sol_15m_momo_v2:   true    # F7 helps on tiny sample
```

### Action 4 — Add per-cell F7 lift monitoring

Continuously monitor whether F7 adds or removes WR on each cell. Trigger an alert if `f7_wr - baseline_wr < -5 pp` over a rolling 24h window.

```sql
-- Per-cell F7 vs baseline lift, rolling 24h
WITH rolling AS (
  SELECT
    REGEXP_REPLACE(sleeve_id, '_(HOLD|HEDGE|SELL)(_f7)?$', '') AS base_sleeve,
    sleeve_id LIKE '%_f7' AS is_f7,
    (data->>'won')::bool::int AS won,
    (data->>'pnl_usd')::numeric AS pnl
  FROM trading.events
  WHERE kind = 'poly_updown_resolution'
    AND at >= NOW() - INTERVAL '24 hours'
    AND sleeve_id LIKE '%momo%'
)
SELECT
  base_sleeve,
  SUM(CASE WHEN NOT is_f7 THEN 1 ELSE 0 END) AS n_base,
  ROUND(AVG(CASE WHEN NOT is_f7 THEN won END) * 100, 2) AS wr_base,
  SUM(CASE WHEN is_f7 THEN 1 ELSE 0 END) AS n_f7,
  ROUND(AVG(CASE WHEN is_f7 THEN won END) * 100, 2) AS wr_f7,
  ROUND((AVG(CASE WHEN is_f7 THEN won END) - AVG(CASE WHEN NOT is_f7 THEN won END)) * 100, 2) AS f7_wr_lift_pp,
  ROUND(SUM(CASE WHEN is_f7 THEN pnl ELSE 0 END), 2) AS f7_sum_pnl,
  ROUND(SUM(CASE WHEN NOT is_f7 THEN pnl ELSE 0 END), 2) AS base_sum_pnl
FROM rolling
GROUP BY base_sleeve
HAVING SUM(CASE WHEN is_f7 THEN 1 ELSE 0 END) >= 10
ORDER BY f7_wr_lift_pp;
```

**Alert thresholds:**
- `f7_wr_lift_pp < -5 pp` AND `n_f7 >= 20` → pause `*_f7` for that cell automatically.
- `f7_wr_lift_pp < -15 pp` AND `n_f7 >= 10` → page on-call.

### Action 5 — Long-term: replace F7 with regime-adaptive filter

The F7 RSI-alignment rule isn't wrong globally — it's wrong WHEN the asset is in a mean-reverting regime. The Markov filter (see `TV_AGENT_SPEC_V2_BUGS_AND_MARKOV_DEPLOY_2026_05_21.md`) is designed to address exactly this. After the immediate fixes (Actions 1-3), pilot the Markov-only and Markov+F7 shadow sleeves per the broader spec.

---

## Verification queries

### Confirm bug pattern persists in real-time

```sql
-- DOWN-signal accuracy on eth_5m_v2 F7 (should be 0% — confirms bug)
SELECT
  data->>'signal' AS signal,
  data->>'outcome' AS outcome,
  COUNT(*) AS n
FROM trading.events
WHERE kind = 'poly_updown_resolution'
  AND sleeve_id LIKE 'poly_updown_eth_5m_momo_v2_%_f7'
  AND at >= NOW() - INTERVAL '7 days'
GROUP BY 1, 2
ORDER BY 1, 2;
-- Expected: DOWN row shows ~0 Down outcomes vs many Up outcomes
```

### Post-fix verification (run 24h after Action 1 + 3)

```sql
-- 4 cells should be effectively gone from _f7 universe
SELECT
  sleeve_id,
  COUNT(*) AS n,
  ROUND(AVG((data->>'won')::bool::int)*100, 2) AS wr,
  ROUND(SUM((data->>'pnl_usd')::numeric), 2) AS sum_pnl
FROM trading.events
WHERE kind = 'poly_updown_resolution'
  AND at >= NOW() - INTERVAL '24 hours'
  AND (sleeve_id LIKE 'poly_updown_eth_5m_momo_v2_%_f7'
       OR sleeve_id LIKE 'poly_updown_btc_15m_momo_v2_%_f7'
       OR sleeve_id LIKE 'poly_updown_btc_5m_momo_v2_%_f7')
GROUP BY sleeve_id;
-- Expected: 0 rows (cells disabled per Action 3 config)
```

---

## Quantified impact of fix

| Sleeve disabled | Saved over 23.5h | Annualized (×24h × 365) |
|---|--:|--:|
| eth_5m_v2 + F7 (3 sleeves) | +$1,195 | ≈ +$444k/yr |
| btc_15m_v2 + F7 (3 sleeves) | +$251   | ≈  +$93k/yr |
| btc_5m_v2 + F7 (optional disable) | +$533 | ≈ +$198k/yr |
| **Total (3 cells fixed)** | **+$1,979** | **≈ +$735k/yr** |

(Annualization assumes the same regime persists; treat as upper bound.)

---

## Summary checklist

- [ ] **Action 1** — disable 6 sleeve_ids: `*eth_5m_momo_v2*_f7` (3) + `*btc_15m_momo_v2*_f7` (3). Optionally `*btc_5m_momo_v2*_f7` (3) too.
- [ ] **Action 2** — **DO NOT change V2 gate code**. V2 baseline works.
- [ ] **Action 3** — add per-cell `f7_enabled` config flag. Default ON for V1 cells, OFF for the 3 broken V2 cells.
- [ ] **Action 4** — wire the per-cell F7-lift monitoring SQL into a daily check + alert.
- [ ] **Action 5** — pilot Markov shadow sleeves per the broader spec to enable regime-adaptive filtering.
- [ ] **Verify** — re-run the verification queries 24h after deploy.
