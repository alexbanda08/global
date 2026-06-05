# TV-Agent fix spec — `l_1hrf_imb5` gate-1 mismatch (2026-06-03)

## Sleeves (BTC 5m, sniper_v5, direction BOTH)
- `poly_sniper_v5_btc_5m_l_1hrf_imb5_rf_v8`
- `poly_sniper_v5_btc_5m_l_1hrf_imb5_ribbon_v8`

## The bug
The sleeve name encodes 3 gates: **1hrf** + **imb5** + **rf/ribbon**. But the live wiring
(`backend/app/strategies/polymarket/sniper_v5_sleeves.py`, ~L864-878) has gate-1 set to the
**grandparent trend-slope** gate, not a 1h range-filter:

```python
sleeve_id="poly_sniper_v5_btc_5m_l_1hrf_imb5_rf_v8",
gates=(
    GateRef(g_grandparent_trend_with, (("asset","BTC"),), "g_grandparent_trend_with(BTC)"),  # ← should be the 1h RF gate ("1hrf")
    GateRef(g_imb5_strong_with, (), "g_imb5_strong_with"),                                    # ok (imb5)
    GateRef(g_rf_with, (("asset","BTC"),), "g_rf_with(BTC)"),                                 # ok (rf)
),
```
`g_grandparent_trend_with` is a 5m→higher-tf trend-slope gate, NOT the 1-hour range-filter the
name/validated config intended. `ribbon_v8` has the same gate-1, only the 3rd gate differs.

## Live impact (current, 7d, real money)
| sleeve | n | WR | PnL |
|---|---:|---:|---:|
| `l_1hrf_imb5_rf_v8` | 2634 | 74.3% | **−$911** |
| `l_1hrf_imb5_ribbon_v8` | 2062 | 77.9% | **−$362** |

Both bleed despite high WR → entries are too expensive (breakeven WR at these entry vwaps
> the 74-78% achieved). They've been negative since the 2026-05-29 fidelity audit flagged this.

## Step 1 — confirm the intended gate-1 (do NOT blind-swap)
Before changing anything, confirm what the *validated* config used:
- `git log -p`/blame `sniper_v5_sleeves.py` around these sleeves — was gate-1 ever `g_1h_rf_with`
  (or a `g_rf_with` with a 1h-timeframe arg) and later changed to `g_grandparent_trend_with`?
- Cross-check the backtest/spec that justified deploying these (search `strategy_lab/sniper_search_2026_05_27/btc_5m*` + the deploy spec) for the exact gate list it scored.
- If a 1h-range-filter gate function exists (`g_1h_rf_with`, or `g_rf_with(asset, tf="1h")`), that
  is the intended gate-1. If it does NOT exist, the "1hrf" was never implemented → see Step 3.

## Step 2 — the fix
Replace gate-1 `g_grandparent_trend_with(BTC)` with the **1h range-filter gate** the validated
config used, on BOTH sleeves (rf_v8 + ribbon_v8). Keep gates 2 (imb5) and 3 (rf/ribbon) as-is.

## Step 3 — guard the entry price (the real driver of the loss)
The losses are a payoff-asymmetry: 74-78% WR but expensive favorite entries. Even with the
correct gate, add the existing entry-vwap cap so it can't buy over-priced favorites:
- Append `GateRef(g_entry_vwap_in_band, ...)` (already in `sniper_v5_gates.py` ~L1350) — cap entry
  vwap (e.g. `≤ 0.80`) so breakeven WR stays under the achieved WR. Tune the cap on backtest.

## Step 4 — deploy safely (these are live-negative NOW)
1. **Stop the live capital on both sleeves immediately** (set to shadow / disable) — they are
   bleeding ~$1.3k/7d on the wrong gate.
2. Register the corrected config as a **SHADOW A/B** (`shadow_..._gatefix`) alongside, OR run the
   corrected version in shadow until validated.
3. Backtest the corrected gate-1 (+ entry-vwap cap) on canonical Apr24→Jun1 — **0.07-curve
   winner-only fee** (`won: shares·(1−vwap)·(1−0.07·vwap); lost: −shares·vwap`), native-10Hz L25.

## Acceptance criteria (promote corrected → live)
- Backtest net PnL > 0 with the 0.07 curve, binom_p < 0.05, OOS (60/40) positive both halves.
- ≥7d shadow: WR above breakeven for the realized entry-vwap distribution, net PnL > 0.
- Until then, the current live sleeves stay **stopped** (do not keep running the −EV config).

## Files
- `backend/app/strategies/polymarket/sniper_v5_sleeves.py` (the 2 sleeve defs)
- `backend/app/strategies/polymarket/sniper_v5_gates.py` (gate fns: 1h-RF gate + `g_entry_vwap_in_band`)
- Evidence: `strategy_lab/reports/FIDELITY_LIVE_A2_sniperv5_sleeves_2026_06_01.md`, `REAUDIT_4SLEEVES_MASTER_2026_06_03.md`
