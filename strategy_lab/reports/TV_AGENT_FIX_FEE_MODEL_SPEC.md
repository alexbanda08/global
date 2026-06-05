# TV Agent Fix — Fee Calculator Model

**Date**: 2026-05-28
**Severity**: HIGH (biggest source of shadow-vs-live PnL deviation, ~$63/day)
**Files**: `strategies/polymarket/maker/base.py`, `engine/poly_maker_fill_sim.py`, `core/config.py`
**Effort**: 1 step verification + ~20 lines code

## 1. The problem

The shadow engine charges taker fee = `0.07 × p × (1 − p)` per share on every TAKE fill (`base.taker_fee()`).

But per CLAUDE.md — verified against **25,900 production `poly_updown_resolution` events** — the live BTC/ETH/SOL up-down markets do NOT use that curve. They charge **2%-on-profit-only**:

- **LOST leg**: `pnl = −entry_qty × entry_price` exactly. **No fee on losses.**
- **WON leg**: `pnl = entry_qty × (1 − entry_price) × 0.98`. **2% on the winning-leg profit only.**

So either `feeRate = 0` on these markets, or `feesEnabled = false` at the contract level. The `0.07 × p × (1-p)` curve is from Polymarket's general docs — it does NOT apply here.

**Effect**: shadow over-charges taker fees by ~$370 over a 2-day window → shadow PnL is **understated** (conservative). Real live PnL is BETTER than shadow shows. We want shadow to be EXACT, not conservatively wrong.

## 2. Step 1 — VERIFY before changing (do this first)

Do NOT flip the model blind. Confirm what production actually charges TODAY.

On VPS3 (production momo wallet), pull a sample of recent resolved fills:

```sql
-- On VPS3 storedata DB
SELECT
    sleeve_id, signal, outcome,
    entry_qty, entry_price, pnl_usd
FROM trading.events
WHERE kind = 'poly_updown_resolution'
  AND at > NOW() - INTERVAL '7 days'
  AND entry_qty > 0
LIMIT 200;
```

For each row, compare `pnl_usd` against two models:

```python
# Model A — 2%-on-profit-only (the claim)
pnl_A = entry_qty * (1 - entry_price) * 0.98 if won else -entry_qty * entry_price

# Model B — 0.07 curve on every fill
fee = 0.07 * entry_price * (1 - entry_price) * entry_qty
pnl_B = (entry_qty * (1 - entry_price) - fee) if won else (-entry_qty * entry_price - fee)
```

Whichever model's `pnl_*` matches the observed `pnl_usd` (median abs diff ≈ 0) is the live truth.

**Expected**: Model A (2%-on-profit) matches per CLAUDE.md's prior verification. If it does → proceed to Step 2 with `legacy_2pct`. If Model B matches → no change needed, shadow is already right.

## 3. Step 2 — make the fee model selectable

Add a config selector so the model can be switched without code surgery, and default to the verified one.

### 3.1 `core/config.py`

```python
class Settings(BaseSettings):
    # ... existing ...

    # Fee model for maker-arb taker fills + redemption.
    #   "curve"        = 0.07 × p × (1-p) per share on every fill (Polymarket general docs)
    #   "legacy_2pct"  = 2% on winning-leg profit only, $0 on losses (VERIFIED live on
    #                    BTC/ETH/SOL up-down per 25,900 resolution events)
    #   "zero"         = no fee (if feeRate truly 0)
    tv_poly_maker_fee_model: str = "legacy_2pct"   # set after Step 1 verification
```

### 3.2 `strategies/polymarket/maker/base.py`

Replace the single hardcoded `taker_fee` with a model-aware version:

```python
def taker_fee(p: Decimal, *, model: str = "curve") -> Decimal:
    """Per-share taker fee.

    model="curve"       → 0.07 × p × (1-p)            (general docs)
    model="legacy_2pct" → 0 here; fee is taken at RESOLUTION on the
                          winning leg only (see resolution_fee()).
    model="zero"        → 0
    """
    if model == "zero" or model == "legacy_2pct":
        return Decimal(0)
    return _TAKER_FEE_RATE * p * (Decimal(1) - p)


def resolution_fee(entry_price: Decimal, qty: Decimal, won: bool, *, model: str) -> Decimal:
    """Fee charged AT RESOLUTION (only for legacy_2pct model).

    legacy_2pct: won leg pays 2% of profit = 0.02 × qty × (1 - entry_price).
                 lost leg pays $0.
    curve / zero: $0 here (fee already taken per-fill or not at all).
    """
    if model != "legacy_2pct":
        return Decimal(0)
    if not won:
        return Decimal(0)
    return Decimal("0.02") * qty * (Decimal(1) - entry_price)
```

### 3.3 `engine/poly_maker_fill_sim.py`

Two edits:

**(a) `_apply_bps_deltas` taker branch** — pass the model through:

```python
from backend.app.strategies.polymarket.maker.base import taker_fee
model = getattr(self._settings, "tv_poly_maker_fee_model", "curve")
fee_per_share = taker_fee(fill_price, model=model)   # 0 if legacy_2pct
slug_state.taker_fees_paid += fee_per_share * fill_size
```

**(b) `_observe_redeem`** — apply the 2%-on-profit fee at resolution when model is legacy_2pct:

```python
from backend.app.strategies.polymarket.maker.base import resolution_fee
model = getattr(self._settings, "tv_poly_maker_fee_model", "curve")
# winner_shares × $1 redemption already credited above.
# Now subtract the 2%-on-profit fee on the won leg.
# entry_price for the winning side = avg cost basis of that side's inventory.
res_fee = resolution_fee(avg_entry_price_winner, size, won=True, model=model)
slug_state.taker_fees_paid += res_fee
```

(You need `avg_entry_price_winner` = cash_spent-on-winning-side / winning-shares. If not already tracked per side, approximate with the slug's overall avg fill price — the difference is immaterial for the 2% rate.)

## 4. Maker rebate under legacy_2pct

If the market charges 2%-on-profit-only with `feeRate ≈ 0`, then **maker rebates are also ≈ 0** (rebate is a fraction of feeRate). Under `legacy_2pct`:

```python
def maker_rebate(t_fee: Decimal, *, model: str = "curve") -> Decimal:
    if model in ("zero", "legacy_2pct"):
        return Decimal(0)
    return _MAKER_REBATE_SHARE * t_fee
```

So `legacy_2pct` → no per-fill taker fee, no rebate, but a 2%-on-profit fee at resolution. This matches the verified production economics.

**Verify rebate reality separately**: check the Polymarket account dashboard for actual monthly maker-rebate payouts. If $0, `legacy_2pct` (no rebate) is correct. If non-zero, the rebate program IS active and needs its own handling.

## 5. Test

```python
def test_legacy_2pct_no_perfill_fee():
    assert taker_fee(Decimal("0.5"), model="legacy_2pct") == Decimal(0)

def test_legacy_2pct_resolution_fee_on_win():
    # 20 shares bought at 0.60, won → fee = 0.02 × 20 × (1-0.60) = 0.16
    assert resolution_fee(Decimal("0.60"), Decimal("20"), won=True, model="legacy_2pct") == Decimal("0.16")

def test_legacy_2pct_no_fee_on_loss():
    assert resolution_fee(Decimal("0.60"), Decimal("20"), won=False, model="legacy_2pct") == Decimal(0)

def test_curve_unchanged():
    # backward-compat: curve model still works
    assert taker_fee(Decimal("0.5"), model="curve") == Decimal("0.0175")
```

## 6. Smoke test after deploy

1. Set `TV_POLY_MAKER_FEE_MODEL=legacy_2pct` (after Step 1 confirms it).
2. Restart `tv-engine.service`.
3. Pull a fresh slug CSV. Verify:
   - TAKE rows have `taker_fees` increment = 0 (no per-fill fee under legacy_2pct)
   - REDEEM rows show a fee = `0.02 × winning_shares × (1 − avg_entry)` on won slugs, $0 on lost slugs.
4. Compare a resolved slug's shadow PnL to the same slug's hand-computed legacy_2pct PnL. Should match within $0.01.
5. Sleeve-level: shadow PnL should rise by ~the over-charged amount (the prior over-statement is removed) → shadow numbers go UP toward true live.

## 7. Rollout checklist

- [ ] **Step 1**: run the SQL + comparison on VPS3. Confirm which model matches `pnl_usd`.
- [ ] Add `tv_poly_maker_fee_model` config (default to verified model)
- [ ] Make `taker_fee` + `maker_rebate` model-aware in base.py
- [ ] Add `resolution_fee` in base.py
- [ ] Wire taker branch + `_observe_redeem` in fill_sim
- [ ] Add 4 unit tests
- [ ] Verify maker rebate reality (account dashboard)
- [ ] Set env var, restart, smoke test
- [ ] Re-run shadow audit — confirm shadow PnL now matches hand-computed legacy_2pct per slug

## 8. Why this matters

This is the single biggest source of shadow-vs-live PnL deviation (~$63/day, currently making shadow look WORSE than reality). Fixing it makes the shadow engine's PnL **exact** instead of conservatively biased — which is what we need before sizing live capital based on shadow numbers.

Backward-compatible: `model="curve"` preserves current behavior. Default flips only after Step 1 verification.

## 9. References

- Engine audit: `strategy_lab/reports/ENGINE_CORRECTNESS_AUDIT_2026_05_28.md` §4
- Fee/gas sub-report: `migration_ireland_audit_2026_05_28/engine_audit/fee_gas_cost_audit.md`
- CLAUDE.md fee-model verification (25,900 resolution events, 2026-05-22)
- Canonical fee module: `strategy_lab/fees.py`
