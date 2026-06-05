# Engine Audit C — Maker / Merge-Arb Backtest Engines (2026-05-29)

Scope: `strategy_lab/maker_arb_audit/_nochase_mergearb_longwin_2026_05_29.py`,
`strategy_lab/maker_arb_audit/positioned_leg_in_flatten.py`,
`strategy_lab/backtests/fast_full_backtest.py`,
`migration_ireland_recheck_2026_05_29/source/engine/poly_maker_fill_sim.py`.
Reference: `strategy_lab/reports/MAKER_ARB_CENSORING_REVERSAL_2026_05_28.md`,
`strategy_lab/reports/NOCHASE_MERGEARB_VERDICT_2026_05_29.md`.

---

## 1. Survivorship / Censoring — BUG ALREADY FIXED ✓

**Prior bug (confirmed in `MAKER_ARB_CENSORING_REVERSAL_2026_05_28.md`):**
Ireland shadow engine books a REDEEM event only for directional winners (inventory
returns to 0). Directional losers hold worthless tokens that expire silently — no
REDEEM is logged, `inv > 0` persists in every snapshot. The old `clean_settled_audit`
counted only `inv=0` rows, which selected all 32 winners (+$6.80/slug) and excluded
all 26 losers (−$8.05/slug), yielding the false +$4.44 "edge". **Verified on
`acc_h_v2_btc_15m`: 26/26 recovered residual slugs were losers; uncensored truth
= −$0.41/slug.** The bias is structural — re-pulling fresher Ireland CSVs reproduces
it because losers never settle in the log.

**`_nochase_mergearb_longwin_2026_05_29.py` — BUG ABSENT ✓.**
This script is a *local canonical backtest*, not a replay of Ireland shadow logs.
Outcome truth comes from `load_resolutions()` (chainlink-derived) and is applied
explicitly at the per-slug level:

```python
# Line 122-125 — stuck/hold arm:
won = won_up[slug] if leg1 == "up" else (not won_up[slug])
per_slug_hold.append((1.0 if won else 0.0) - L1 + REBATE)
# stuck/flatten arm:
per_slug_flat.append(bf - L1 + REBATE)
```

Every resolved slug in the window is included regardless of Ireland log state.
Both "hold" (directional residual settled by chainlink) and "flatten" (sell back
at bid) branches are computed and compared. **The censoring bug that infected the
shadow engine analysis does not exist in this script.** This is the decisive
corrected test.

`positioned_leg_in_flatten.py` — identical structure, same conclusion.

`fast_full_backtest.py` `finalize_slug()` (line 392–433) — also clean:
```python
if state.outcome_truth == "Up":
    if state.up.inv > 0:
        state.leftover_redeemed = state.up.inv * 1.0
        state.cash_recovered += state.leftover_redeemed
```
Losing-side inventory is left unredeemed (correctly worth $0). The outcome truth
is read from canonical resolutions, not Ireland logs. No censoring bias.

---

## 2. Maker Fill Realism — OPTIMISTIC (documented, bounded)

### `_nochase_mergearb_longwin` — simplest model, most generous

Fill rule (line 104–105):
```python
t_up = first_cross(ts, au, L1, t_before=flat)   # first L25 tick where ask <= L1
```
A "fill" is declared the **instant** the best ask first touches the L1 bid price.
**No queue model, no partial fills, no latency.** This is maximally optimistic:
- In reality, a resting bid at 0.50 sits behind all earlier orders at that price.
  The ask crossing 0.50 does not guarantee a fill; a large queue ahead could absorb
  the aggressor before reaching our order.
- The script acknowledges this on line 35–37 of the verdict:
  > "This is generous to the strategy: instant maker fills the moment the ask touches
  > the price (no queue, no partials)."
- Adverse selection is therefore **under-modeled**: fills in this script represent
  the best-case subset of real fills. In live execution, many of those "crosses"
  would not result in fills (queue ahead), and the ones that do fill are more
  adversely selected than the average cross (you only fill when the aggressor has
  enough size to exhaust the queue ahead — typically a large, informed order).

**Quantified optimism:** the Ireland shadow engine audit (Bug Map E8–E12) estimated
10–25% fill-rate over-count from the no-partials assumption alone. For the
no-chase script, the no-queue model likely over-counts fills even more (Ireland at
least initializes `initial_queue` from live book depth; this script uses zero).

### `poly_maker_fill_sim.py` (Ireland live engine) — more realistic but still gaps

- Queue model: `initial_queue = depth_at_price` at POST time; decremented by
  correct-side trade prints via FIFO. ✓
- Fill trigger: queue drains to 0 AND book is live-crossed at check time. ✓
- Partial fills: **gap** — when queue drains, fills the FULL `order.size` regardless
  of aggressor order size. Estimated 10–25% fill-rate overstatement (E8).
- Adverse selection: flat BPS haircut, default-off (`tv_poly_maker_adv_sel_bps=0`),
  bids-only (E9). Not symmetric — does not penalize being filled on the losing side.
- Zero published depth edge case: if no orders exist at the posted price when we
  POST, `initial_queue=0` → first matching trade triggers a full fill (effectively
  assumes front-of-queue) (E10).
- `fast_full_backtest.py` `handle_trade()` (line 363–379): same queue-ahead
  decrement + fill-on-drain pattern as Ireland. Same partial-fill gap.

**Net assessment:** both engines over-count fills by 10–25% and under-penalize
adverse selection. For the no-chase script (most generous model), real-world
fill rates are likely materially lower than the 63–88% completion rate reported.
This makes the already-negative result **more negative in practice**.

---

## 3. Look-ahead — NONE FOUND ✓

`_nochase_mergearb_longwin`:
- `first_cross(ts, ask, thr, t_before=flat)` uses only past/current L25 ticks up
  to `flat = (ss + WIN[tf] - FLATTEN) * 1_000_000` (a future cutoff, not a future
  price). The `t_before` guard ensures the fill timestamp precedes the flatten
  deadline — causal.
- `bid_asof(ts, bid, t)`: `searchsorted(ts, t, side="right") - 1` — strictly
  causal, returns last bid at-or-before time `t`. ✓
- `won_up` lookup uses `load_resolutions()` outcome known post-resolution — only
  consumed in `finalize_slug`, never during the within-slot fill decision. ✓

`fast_full_backtest.py`:
- `outcome_truth` stored in `SlugState` at initialization but accessed only in
  `finalize_slug()` (line 392–433), not during `handle_l25` or `handle_trade`. ✓
- L25 streaming is row-group ordered (time-ordered within slug). ✓
- Book state (best_bid, best_ask) reflects only events processed so far. ✓

**No lookahead found in either local engine.**

---

## 4. Tx / Merge Cost Model — MISSING in nochase script

| Cost | `_nochase_mergearb_longwin` | `fast_full_backtest` / Ireland |
|---|---|---|
| CLOB place/cancel gas | ✗ not modeled | ✓ $0 (meta-tx, correct) |
| MINT gas | ✗ not applicable (no MINT) | ✗ missing (E12) |
| MERGE gas | ✗ not modeled | ✓ $0.05/event (Ireland) |
| REDEEM gas | ✗ not modeled | ✗ missing (E12) |
| Polymarket taker fee | ✗ not applicable (maker only) | ✓ `0.07×p×(1-p)` or 2%-on-profit |
| Maker rebate | REBATE=0.0035 applied as income | ✓ via `poly_maker_rebate_per_share` |

**Critical: rebate is incorrect.** Per CLAUDE.md (verified against 25,900 production
resolution events), `feeRate≈0` on BTC/ETH/SOL up-down markets → **no rebate actually
accrues.** The nochase script credits `REBATE=0.0035` per leg filled, which is false.
The verdict report acknowledges: "Strip the rebate and it's ~$0.007/slug worse still."

**Critical: no on-chain tx cost.** For each slug with any activity:
- Leg1 fill: 1 Polygon CLOB fill tx — ~$0.005–$0.01
- Leg2 fill (completed): 1 more fill tx — ~$0.005–$0.01
- Merge (completed): 1 CTF merge tx — ~$0.005–$0.01 (Ireland uses $0.05 which
  includes the 0.25% merge fee; pure gas is $0.005–$0.01)
- Stuck/flatten: leg1 fill + 1 taker sell — ~$0.01–$0.02

Using $0.01/event (conservative mid-range):
- Completed slug: 3 events × $0.01 = **$0.03**
- Stuck/flatten slug: 2 events × $0.01 = **$0.02**

---

## 5. Corrected-Cost Re-Run — Analytical Derivation

The nochase script records `pnl_flatten` using:
- Completed: `(1 − budget) + 2 × 0.0035`
- Stuck: `bid@flatten − 0.50 + 0.0035`

Corrections applied:
- Remove rebate (`REBATE=0.0035 → 0`, per `feeRate≈0` on these markets)
- Add $0.01 tx cost per fill event and per merge/redeem

Per-slug delta:
- Completed slug: `−0.037` (−0.007 rebate removed, −0.030 tx cost for 3 events)
- Stuck slug: `−0.0235` (−0.0035 rebate removed, −0.020 tx cost for 2 events)
- Net delta = `comp_frac × (−0.037) + stuck_frac × (−0.0235)`

### Corrected results (n=10,565, May 20→29, all asset×tf cells pooled):

| budget | comp% | pnl_flat orig | pnl_flat corrected | delta | CI-low (est) |
|---|---:|---:|---:|---:|---:|
| 0.90 | ~67% | −$0.0332 | **−$0.0657** | −$0.0325 | ≈ −$0.072 |
| 0.93 | ~72% | −$0.0366 | **−$0.0699** | −$0.0332 | ≈ −$0.076 |
| 0.94 | ~76% | −$0.0317 | **−$0.0654** | −$0.0337 | ≈ −$0.071 |
| 0.97 | ~83% | −$0.0315 | **−$0.0661** | −$0.0346 | ≈ −$0.072 |

Original 95% CI widths were ≈±0.005 (bootstrap, n=10,565). Corrected CI-low
estimates shift by the same delta as the mean. All budgets remain **entirely
below zero**; the corrected CI-low is approximately **−$0.07/slug**.

### Per-cell breakdown (corrected pnl_flatten):

| asset | tf | budget | n | comp% | orig | corrected |
|---|---|---:|---:|---:|---:|---:|
| BTC | 5m | 0.90 | 2,646 | 65.0% | −0.0296 | **−0.0619** |
| BTC | 5m | 0.97 | 2,646 | 81.5% | −0.0306 | **−0.0651** |
| BTC | 15m | 0.90 | 877 | 74.5% | −0.0265 | **−0.0601** |
| BTC | 15m | 0.97 | 877 | 88.1% | −0.0203 | **−0.0557** |
| ETH | 5m | 0.90 | 2,645 | 66.7% | −0.0289 | **−0.0614** |
| ETH | 15m | 0.93 | 876 | 77.7% | −0.0385 | **−0.0725** |
| SOL | 5m | 0.90 | 2,644 | 62.9% | −0.0386 | **−0.0706** |
| SOL | 15m | 0.90 | 877 | 70.2% | −0.0496 | **−0.0826** |

Every cell negative before correction. Every cell more negative after correction.
The worst performer (SOL 15m) reaches −$0.083/slug corrected.

---

## 6. Summary of Bugs Found

| # | Engine | Bug | Severity | Direction |
|---|---|---|---|---|
| C-01 | `_nochase` / `positioned_leg` | REBATE=0.0035 credited but `feeRate≈0` → no real rebate | **HIGH** | Overstates PnL ~$0.007/slug |
| C-02 | `_nochase` / `positioned_leg` | No on-chain tx cost (fill + merge/redeem gas) | **HIGH** | Overstates PnL ~$0.020–$0.037/slug |
| C-03 | `_nochase` / `positioned_leg` | Instant fill on first ask-touch (no queue, no partials) | **HIGH** | Optimistic fill rate; more adverse selection in reality |
| C-04 | `fast_full_backtest` | Same instant fill model (queue-ahead decrement but no partial fill cap) | **MED** | 10–25% fill-rate overstatement |
| C-05 | `fast_full_backtest` / Ireland | Rebate credited but rebate≈0 on these markets | **MED** | Overstates PnL |
| C-06 | Ireland `poly_maker_fill_sim` | No partial fills on queue-drain (E8) | **MED** | 10–25% over-fill |
| C-07 | Ireland `poly_maker_fill_sim` | Adverse-sel haircut default-off, bids-only (E9) | **MED** | Under-penalizes adverse selection |
| C-08 | Ireland `poly_maker_fill_sim` | Zero-depth → front-of-queue assumption (E10) | **MED** | Optimistic on thin books |
| C-09 | `fast_full_backtest` / Ireland | MINT + REDEEM gas not modeled (E12) | **LOW** | ~$22/day understatement |

**No survivorship/censoring bug in `_nochase_mergearb_longwin` or
`fast_full_backtest` — both use canonical chainlink outcomes applied to all slugs.**
The censoring reversal applied to Ireland shadow logs only, and was already
corrected by the `MAKER_ARB_CENSORING_REVERSAL_2026_05_28.md` analysis.

---

## 7. Verdict: Maker-Arb Line Remains Closed

**The corrected-cost re-run makes the no-chase verdict substantially worse.**
Pooled corrected pnl_flatten ≈ −$0.066/slug (vs −$0.033 original), with the
95% CI entirely below −$0.06. The $0.033/slug correction comes from:
- ~$0.007 rebate removal (rebate doesn't exist on these markets)
- ~$0.026 on-chain tx gas (filled~optimistically at 2–3 events per slug × $0.01)

These costs are irreducible — every fill and every merge/redeem requires an
on-chain CTF transaction.

**All three forms of maker-arb now show net-negative under corrected accounting:**

| Form | Result |
|---|---|
| Production sleeves (acc_h variants) | −$0.41 to −$3.63/slug (censoring reversal) |
| No-chase merge-arb (original, best case) | −$0.032/slug |
| No-chase merge-arb (corrected: no rebate + $0.01/tx) | **−$0.066/slug, CI [−$0.07, −$0.06]** |

**The "maker-arb CLOSED" conclusion is not only verified to be bug-free on the
survivorship dimension — it is strengthened once the two missing costs (gas tx
and zero-rebate reality) are applied.** Adding gas makes the strategy
approximately twice as negative per slug as reported.

The only remaining model-side flattery is the optimistic fill model (instant
fill on first ask-touch, no queue). In live execution, real fill rates would be
lower and adverse selection would be worse than modeled, pushing the result
further negative still.

**Do not reopen maker-arb without a sub-50ms fill execution advantage or a
slug-selection edge that predicts which 12–37% will get stuck and which side
they will lose on. Neither is available from Ireland VPS on the current stack.**

---

*Audit performed 2026-05-30. Script:
`strategy_lab/maker_arb_audit/_nochase_mergearb_longwin_2026_05_29.py`.
CSV: `strategy_lab/maker_arb_audit/_results/_nochase_mergearb_longwin.csv`.*
