# TV Agent — Maker-arb PnL bug: loser-residual not zeroed at REDEEM

**Severity**: HIGH — `slug_pnl_so_far` column is inflated by `loser_residual × $0.50` on every resolved slug.
**Scope**: 4 maker-arb strategies (acc_m, mas, acc_h, acc_pc). pat_shadow not affected (paired merges close inventory).
**Effort**: 4 small patches + 1 unit test. ~30 min.

---

## The bug

`shadow_log.py:307-317` computes mark-to-market on residual inventory at $0.50/share:

```python
paired   = min(slug_state.inv_up, slug_state.inv_dn)
residual = abs(slug_state.inv_up - slug_state.inv_dn)
mark     = paired * Decimal("1.0") + residual * Decimal("0.5")
pnl      = (cash_received + cash_recovered + rebates_received
            - cash_spent - taker_fees_paid + mark)
```

The `$0.50` mark assumes outcome is UNKNOWN. After REDEEM the outcome IS known — the loser side is worth $0, not $0.50.

But `on_slug_resolved` in each strategy only zeros the WINNER side (after REDEEM). The loser-side `inv_*` is left in state.

Result: `mark = loser_residual × $0.50` is still credited even though those shares are worthless.

### Concrete trace — MAS 15m

```
mint:        inv_up=30, inv_dn=30, cash_spent=30
no fills
on_slug_resolved(winner=up):
  REDEEM up size=30  → cash_recovered=30, inv_up=0
  (inv_dn STAYS = 30)  ← BUG

At REDEEM row:
  paired = min(0, 30) = 0
  residual = abs(0 - 30) = 30
  mark = 0 + 30 × 0.5 = $15        ← WRONG (loser shares are $0)
  pnl = 0 + 30 + 0 - 30 - 0 + 15 = +$15  ← reported

Real PnL:  0 + 30 - 30 + 0 = $0
```

Same pattern in acc_m / acc_h / acc_pc when their on_slug_resolved fires.

---

## The fix

Zero the loser-side inventory in each strategy's `on_slug_resolved` immediately after the REDEEM Decision is emitted for the winner.

### Patch 1 — `backend/app/strategies/polymarket/maker/acc_m.py`

In `on_slug_resolved`, after the existing winner-side REDEEM block:

```python
    if evt.winner == "up" and state.inv_up > 0:
        decisions.append(
            Decision(... action="REDEEM", side="up", size=state.inv_up, ...)
        )
+       state.cash_recovered += state.inv_up * Decimal("1.0")
+       state.inv_up = Decimal(0)
+       state.inv_dn = Decimal(0)    # loser residual worthless after resolution
    elif evt.winner == "dn" and state.inv_dn > 0:
        decisions.append(
            Decision(... action="REDEEM", side="dn", size=state.inv_dn, ...)
        )
+       state.cash_recovered += state.inv_dn * Decimal("1.0")
+       state.inv_dn = Decimal(0)
+       state.inv_up = Decimal(0)    # loser residual worthless after resolution
```

Note: also add `state.cash_recovered += redeemed × $1` if the strategy isn't already doing it. Currently it's done by `fill_sim._observe_redeem` via the synthetic fill — verify this is the case. If yes, only add the loser-side `inv = 0` lines (keep cash_recovered untouched here to avoid double-counting).

### Patch 2 — `backend/app/strategies/polymarket/maker/mas.py`

Same pattern. After the winner-side REDEEM Decision is emitted:

```python
+   state.inv_up = Decimal(0)
+   state.inv_dn = Decimal(0)
```

### Patch 3 — `backend/app/strategies/polymarket/maker/acc_h.py`

Same pattern.

### Patch 4 — `backend/app/strategies/polymarket/maker/acc_pc.py`

Same pattern.

### pat_shadow.py — NO change needed

pat_shadow merges every paired fire immediately, so `inv_up = inv_dn` always. At slug end, both sides are typically 0 or equal-and-merged. The mark formula correctly returns 0.

---

## Tests

Add to `backend/tests/unit/strategies/maker/test_resolution.py` (one test per strategy):

```python
def test_acc_m_zeros_loser_residual_on_resolved(acc_m, sample_state):
    # Seed: 30 paired + 5 extra on up (so winner=up has residual)
    sample_state.inv_up = Decimal("35")
    sample_state.inv_dn = Decimal("30")
    sample_state.cash_spent = Decimal("0")
    sample_state.cash_recovered = Decimal("0")
    acc_m.slug_states[sample_state.slug] = sample_state

    # Resolve as UP
    acc_m.on_slug_resolved(SlugResolved(
        slug=sample_state.slug, winner="up", ts_us=1_000_000
    ))

    # After resolution: BOTH sides cleared
    # (winner redeemed, loser worthless)
    assert sample_state.inv_up == Decimal(0)
    assert sample_state.inv_dn == Decimal(0)


def test_shadow_log_pnl_zero_for_mint_redeem_no_fills(logger, mas_state):
    """The MAS 15m case: mint + redeem with zero fills must produce ~$0 PnL,
    NOT +$15 from the residual mark."""
    mas_state.cash_spent = Decimal("30")
    mas_state.cash_recovered = Decimal("30")
    mas_state.inv_up = Decimal(0)        # winner redeemed
    mas_state.inv_dn = Decimal(0)        # loser cleared (post-fix)
    row = logger._row_from_decision(
        Decision(action="REDEEM", side="up", ...),
        sim_fill=True,
        slug_state=mas_state,
    )
    assert abs(float(row["slug_pnl_so_far"])) < 0.01
```

---

## Validation after deploy

Pull May 22 CSVs and check MAS 15m slugs that complete REDEEM:

```bash
py -3 -X utf8 -c "
import pandas as pd
df = pd.read_csv('mas_2026-05-22.csv')
last = df.sort_values('ts_us').drop_duplicates('slug', keep='last')
mas15 = last[last.tf=='15m']
# Slugs with no FILL events should now report PnL ~$0, not +$15
nofill = mas15[~mas15.slug.isin(df[df.action=='FILL'].slug.unique())]
assert (nofill.slug_pnl_so_far.astype(float).abs() < 0.5).all(), \
    'PnL still inflated on no-fill MAS 15m slugs'
"
```

Spot-check one acc_m REDEEM row:
- `inv_dn` (or `inv_up` if winner=dn) should be 0, not the original mint quantity
- `slug_pnl_so_far` should match `cash_received + cash_recovered + rebates - cash_spent - taker_fees` with mark=0

---

## Why this matters

Yesterday's report claimed "4 of 5 sleeves flipped positive" with the visibility patches. That claim is wrong — the visibility patches exposed cash credits correctly, but introduced this residual-mark bug.

Re-estimated post-fix May 21 numbers:

| sleeve | reported (with bug) | post-fix expected |
|---|---:|---:|
| acc-h | +$12 | −$80 to −$130 |
| acc-m | +$56 | −$60 to −$120 |
| acc-pc | +$28 | −$30 to −$70 |
| mas 5m | +$214 | $0 to −$60 |
| mas 15m | +$90 | ~$0 |
| pat-shadow | −$74 | −$74 (no change, no loser residual) |

After the fix, `slug_pnl_so_far` is trustworthy and matches the manual `cash_received + cash_recovered + rebates − cash_spent − taker_fees` formula.

---

## Files to touch

```
backend/app/strategies/polymarket/maker/acc_m.py
backend/app/strategies/polymarket/maker/acc_h.py
backend/app/strategies/polymarket/maker/acc_pc.py
backend/app/strategies/polymarket/maker/mas.py
backend/tests/unit/strategies/maker/test_resolution.py    (new — or extend existing)
```

No changes needed in `shadow_log.py` or `poly_maker_fill_sim.py`. The mark formula in shadow_log is correct *when* state reflects reality; the fix is to make state reflect reality.
