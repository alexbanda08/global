# CORRECTION — `qty_compute_failed` is a documented strategy gate, NOT a code bug

_This file originally claimed the asymmetric `qty_compute_failed` rejection on eth_5m_v2 / btc_15m_v2 was an implementation bug. **That conclusion was wrong.** This is the corrected version._

## The retraction

I previously labeled the `_compute_qty_shares` 86%-UP / 47%-DOWN rejection rate on eth_5m_v2 as a "code bug." Operator pushed back asking me to verify against the strategy spec. I did, and found:

**`_compute_qty_shares` is a documented Phase 18.1 D-12 safeguard, shipped 2026-04-28** (4 weeks ago). The [0.05, 0.95] guard exists by design and is correctly implemented.

Source: VPS3 `/opt/tradingvenue/.planning/RESUME.md`, D-12 entry:

> **D-12 (notional sizing)**: Controller's `notional_usd=Decimal("25")` was being passed as `qty` to executor — interpreted as 25 SHARES not $25 USD. New `_compute_qty_shares` reads best_ask, divides notional, **refuses degenerate books (best_ask outside [0.05, 0.95])**. Now bets are ~$25 actual notional.

## What the gate does and why it's correct

```python
QTY_MIN_PRICE = Decimal("0.05")    # below = market too one-sided
QTY_MAX_PRICE = Decimal("0.95")    # above = opposite leg almost-resolved
...
if best_ask < self.QTY_MIN_PRICE or best_ask > self.QTY_MAX_PRICE:
    return None    # audit row: reason="qty_compute_failed"
```

Refuses bets where the held side's best_ask is degenerate:

| Condition | Why refuse |
|---|---|
| `best_ask < 0.05` | $25 / 0.05 = 500 shares. Token too cheap = market thinks side is losing. Worst-case downside is full $25 stake — high risk per dollar bet. |
| `best_ask > 0.95` | $25 / 0.95 ≈ 26 shares × $0.05 upside each = max $1.30 gross on a $25 stake (with full loss possible). Terrible R/R. |

**Both clamps are correct risk-management.** Removing them would let the engine bet on dead/near-resolved markets where the EV math is bad regardless of signal direction.

## Why the production behavior LOOKS like a bug but isn't

In the 23.5h post-F7 window, ETH and BTC trended strongly. On the eth_5m_v2 + F7 sleeve specifically:

```
reason                DOWN   UP
order_placed           33    9
qty_compute_failed     30   57
intended fires         63   66 (balanced; matches clean spec)
admitted fires         33    9 (skewed 79/21)
WR on admitted         3 of 33 won = 9%
```

What happens, step by step:

1. **Momo_v2 emits ~50/50 UP and DOWN signals**, both passing F7 (RSI alignment). Verified — clean spec recompute shows 15 UP / 15 DOWN F7-passing on the same window.
2. **Up token best_ask exceeds 0.95** during the trend up (market correctly prices Up token near $1 because Up will likely win at slot_end).
3. **qty_compute correctly refuses 86% of UP fires** (per Phase 18.1 D-12 design — best_ask > 0.95 is bad R/R).
4. **Down token best_ask stays in range** (Down side is the cheap leg but not extreme).
5. **qty_compute correctly admits DOWN fires** (best_ask in [0.05, 0.95]).
6. **The admitted DOWN fires are momo's reads on brief downward retracements** within the larger uptrend.
7. **The trend resumes up after each retrace → all DOWN fires lose.**

Every component is doing its job. The combined output looks catastrophic because the filter exposes a strategy weakness: momo_v2 on eth_5m doesn't have predictive edge for sustained moves in a strongly-trending regime.

## What I verified along the way

| Check | Result |
|---|---|
| Production `ret_2m_at_signal` vs clean recompute | 60/60 fires match, sign 100% consistent |
| Production `rsi_14` vs clean RSI | 228/228 fires match exactly |
| Production `outcome` vs canonical chainlink | 72/72 resolutions match |
| F7 gate code (`f7_gate.py`) | spec-compliant |
| `_resolve_token_id` UP→idx0 / DOWN→idx1 | spec-compliant |
| `_compute_qty_shares` [0.05, 0.95] clamp | spec-compliant (Phase 18.1 D-12) |
| `_build_signal_aux` momo_v2 branch | spec-compliant |

**No code-level bug found.** Every audited piece of the pipeline matches its documented specification.

## Why earlier reports flagged this as "real implementation bug"

Three earlier reports flagged `qty_compute_failed` on eth_5m_momo_v2_HOLD as a separate bug lead:

- `ETH_5M_V3_V4_DIAGNOSIS_2026_05_11.md`
- `TV_AGENT_V3_FAMILY_DIFFERENTIATION_SPEC_2026_05_11.md`
- `DATA_INVENTORY_2026_05_15.md`

Those reports observed 24 `qty_compute_failed` events on the HOLD-policy sleeve over 7 days and labeled it a bug to file — but they didn't trace it to root cause. The actual root cause is the same as today's: regime-specific asymmetric rejection by a deliberately-designed gate. The repeated "bug" label across reports was due to the same misinterpretation, propagated.

## What is actually the issue

**Not a code bug. A strategy/regime issue.** The momo_v2 + F7 sleeves on eth_5m and btc_15m don't have predictive edge in strongly-trending regimes because:

- F7 admits both directions (RSI-aligned)
- qty_compute correctly filters out the expensive side (a feature, not a bug)
- The cheap side fires are momo's reads on retracements that don't sustain
- All retraces resolve in the trend direction → all fires lose

**The asymmetric fire distribution is REVEALED by the qty_compute gate but originates in the momo signal's inability to distinguish "sustained move" from "noise retrace" in trending regimes.**

## Recommendations (corrected — no code change)

### 1. Disable affected sleeves until edge is regime-conditioned

These sleeves underperform in trending regimes; the bias is real even though the components are correct:

```yaml
disable_sleeves:
  - poly_updown_eth_5m_momo_v2_HOLD_f7
  - poly_updown_eth_5m_momo_v2_HEDGE_f7
  - poly_updown_eth_5m_momo_v2_SELL_f7
  - poly_updown_btc_15m_momo_v2_HOLD_f7
  - poly_updown_btc_15m_momo_v2_HEDGE_f7
  - poly_updown_btc_15m_momo_v2_SELL_f7
```

This is a **deploy decision**, not a code fix. Keep the qty_compute gate as-is.

### 2. DO NOT modify `_compute_qty_shares`

The [0.05, 0.95] clamp is correct. Raising QTY_MAX_PRICE would let in fires with worse R/R (paying $0.97 to win $1.00 = 3% gross before fees). The original Phase 18.1 design is sound.

### 3. (Optional) Add directional balance audit

Emit a per-(asset, tf, version) metric: `(qty_compute_failed_UP / qty_compute_failed_DOWN)` ratio over rolling 1h. Alert when ratio exceeds 3:1, indicating regime asymmetry. **This is an observability addition, not a fix.**

```sql
-- Run on a schedule; alert when ratio > 3
SELECT
  REGEXP_REPLACE(sleeve_id, '_(HOLD|HEDGE|SELL)(_f7)?$', '') AS sleeve_group,
  SUM((data->>'reason' = 'qty_compute_failed' AND data->>'signal' = 'UP')::int) AS up_rejected,
  SUM((data->>'reason' = 'qty_compute_failed' AND data->>'signal' = 'DOWN')::int) AS down_rejected,
  ROUND(
    NULLIF(SUM((data->>'reason' = 'qty_compute_failed' AND data->>'signal' = 'UP')::int)::numeric, 0)
    / NULLIF(SUM((data->>'reason' = 'qty_compute_failed' AND data->>'signal' = 'DOWN')::int), 0),
    2
  ) AS up_to_down_reject_ratio
FROM trading.events
WHERE kind = 'poly_updown_signal'
  AND sleeve_id LIKE '%momo_v2%'
  AND at >= NOW() - INTERVAL '1 hour'
GROUP BY 1;
```

### 4. (Optional) Regime detector at the strategy level

Add a higher-timeframe trend filter that disables momo when 1h or 4h absolute return exceeds a threshold. The current F7 (1-minute RSI alignment) catches micro-direction but not sustained trends. **This is a NEW STRATEGY DESIGN**, not a fix to existing code.

Example sketch:

```python
# In _build_signal_aux for momo_v2:
ret_1h = aux.get("ret_1h_for_regime")
if ret_1h is not None and abs(ret_1h) > 0.015:  # >1.5% in 1h
    # Strong trend regime — momo retracement fires likely to lose
    aux["regime_skip"] = True

# In MomoV2Strategy.signal():
if aux.get("regime_skip"):
    return "NONE"
```

This would mitigate the trending-regime weakness directly. Requires new aux field + plumbing through BarContext + threshold tuning. Larger change.

## Re-stating the actual bug count

**Confirmed code bugs in production momo / momo_v2 / F7 stack: 0.**

The earlier "5% WR / 18% WR" production catastrophes I called "confirmed bugs" are **regime artifacts** of a correctly-implemented strategy interacting with a correctly-implemented risk gate during a strongly-trending 23.5h window. Outside trending regimes (14-day baseline), eth_5m_v2 sits at 43% WR (mild loss, not catastrophic) and btc_15m_v2 sits at 59% WR (profitable).

## Lessons for me

1. **Don't conclude "bug" without checking the spec.** "Asymmetric rejection" was suspicious but I should have found Phase 18.1 D-12 BEFORE writing a code-fix spec.
2. **Production audit logs aren't ground truth for spec compliance** — they show outcomes, not whether the outcomes are intended.
3. **Older reports flagging the same symptom aren't evidence of a bug** — they could all be observing the same regime artifact and miscalling it.
4. **The clean backtest correctly showed ~50% WR without the filter.** The right interpretation was "the strategy is neutral on canonical data and the filter makes the trending-regime weakness visible," NOT "the filter introduces a bug."

## Files that need to be updated as a result

- `strategy_lab/reports/TV_AGENT_FIX_MOMO_V2_BUGS_2026_05_21.md` — needs same retraction. The 4 "Actions" in that file should drop the audit step (no `_build_signal_aux` bug exists); the disable-list recommendation is still valid as a deploy decision.
- `strategy_lab/reports/CLEAN_BACKTEST_V2_BUG_CONFIRMED_2026_05_21.md` — title is misleading; clean backtest confirmed spec-compliance, not a bug.
- `strategy_lab/reports/CLEAN_BACKTEST_PHASE_B_FINAL_2026_05_21.md` — "V2 bugs definitively confirmed" framing is wrong; the actual finding is "production V2 + F7 underperforms in trending regimes due to expected qty_compute filter behavior."
- Older reports flagging `qty_compute_failed` as "real implementation error" (`ETH_5M_V3_V4_DIAGNOSIS_2026_05_11`, `TV_AGENT_V3_FAMILY_DIFFERENTIATION_SPEC_2026_05_11`, `DATA_INVENTORY_2026_05_15`) — pre-existing misidentification, not my doing, but the same correction applies.

## TL;DR for TV agent

**No code change needed.** The `_compute_qty_shares` [0.05, 0.95] clamp is the Phase 18.1 D-12 safeguard working as designed. The eth_5m_v2_f7 / btc_15m_v2_f7 catastrophic WR is a regime artifact of a correctly-implemented strategy. Recommended actions:

1. Disable the 6 affected sleeves (deploy decision)
2. Add the optional directional-balance audit metric (observability)
3. Consider a higher-timeframe regime filter in a future strategy iteration (new feature, not a fix)

Apologies for the earlier mislabeling.
