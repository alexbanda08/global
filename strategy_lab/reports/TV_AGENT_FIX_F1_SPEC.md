# TV Agent Fix Spec — F1: Book canonical fees + rebates per fill

**Standalone extract of F1 from `TV_AGENT_FIX_SPEC_2026_05_21.md`** so it can ship as a single PR.

**Severity**: HIGH. Files touched: 2. Lines changed: ~30. Estimated effort: 1 dev-hour + tests.

## 1. Why this matters

Right now the shadow engine writes `taker_fees = $0` and `rebates = $0` (except MAS, which double-books rebates) on every fill across all 5 maker-arb sleeves. The console PnL formula (`api/maker_sleeves.py:529-534`) reads `+ rebates − taker_fees` — so when those columns are 0, console PnL is over-stated by exactly the missing fees.

Empirical over-statement (May 20-21, 25.5 h shadow window):

| sleeve | unbooked fees | unbooked rebates | net over-statement |
|---|---:|---:|---:|
| poly_acc_m_btc_5m_shadow | $162.45 | $56.73 | $105.72 |
| poly_acc_h_btc_5m_shadow | $181.63 | $106.77 | $74.86 |
| poly_acc_h_btc_15m_shadow | $48.03 | $17.98 | $30.05 |
| poly_acc_pc_btc_15m_shadow | $44.06 | $33.97 | $10.09 |
| poly_pat_shadow_btc_5m_shadow | $812.77 | $162.21 | $650.56 |

This is the only systematic bias between console PnL and honest PnL today. After F1 lands, console = honest.

## 2. Canonical formula (LOCKED — do not modify)

    fee_per_share    = feeRate × p × (1 − p)
    rebate_per_share = rebate_share × fee_per_share

Constants for crypto up-down (BTC/ETH/SOL 5m/15m markets, the only universe we run):
- `feeRate` = 0.07 (from `_TAKER_FEE_RATE = Decimal("0.07")` in `strategies/polymarket/maker/base.py:55`)
- `rebate_share` = 0.20 (from `_MAKER_REBATE_SHARE = Decimal("0.20")` in `strategies/polymarket/maker/base.py:59`)

Worked examples (verification):

    p = 0.50, C = 20 shares: fee = 20 × 0.07 × 0.50 × 0.50 = $0.350
    p = 0.85, C = 20 shares: fee = 20 × 0.07 × 0.85 × 0.15 = $0.179
    p = 0.95, C = 20 shares: fee = 20 × 0.07 × 0.95 × 0.05 = $0.067
    Maker rebate at p=0.5, C=20 shares: 0.20 × 0.350 = $0.070

Source of truth: `strategy_lab/fees.py` (canonical), `strategies/polymarket/maker/base.py:78-89` (engine).

## 3. Edit F1.A — `engine/poly_maker_fill_sim.py` lines 776-806

Replace `_apply_bps_deltas` so it ALWAYS applies the canonical formula. The bps env vars (`tv_poly_taker_fee_bps`, `tv_poly_maker_rebate_bps`) stay as an additive override layer (default 0 → unchanged operator UX).

### Before

```python
def _apply_bps_deltas(
    self,
    slug_state: Any,
    fill_price: Decimal,
    fill_size: Decimal,
    is_maker: bool,
) -> None:
    """D-11: additive bps deltas on top of strategy's formula-based rebate.
    ...
    """
    if slug_state is None:
        return
    if is_maker:
        bps = int(getattr(self._settings, "tv_poly_maker_rebate_bps", 0))
        if bps == 0:
            return
        delta = fill_price * fill_size * Decimal(bps) / Decimal(10_000)
        slug_state.rebates_received += delta
    else:
        bps = int(getattr(self._settings, "tv_poly_taker_fee_bps", 0))
        if bps == 0:
            return
        delta = fill_price * fill_size * Decimal(bps) / Decimal(10_000)
        slug_state.taker_fees_paid += delta
```

### After

```python
def _apply_bps_deltas(
    self,
    slug_state: Any,
    fill_price: Decimal,
    fill_size: Decimal,
    is_maker: bool,
) -> None:
    """Book canonical Polymarket fees + rebates per fill.

    Canonical formula (strategy_lab/fees.py, base.py:78-89):
        fee_per_share    = feeRate × p × (1 − p)       [feeRate = 0.07 crypto]
        rebate_per_share = 0.20 × fee_per_share

    All TAKE fills pay the taker fee. All POST_BID/POST_ASK fills
    (is_maker=True) receive the rebate as INCOME. MINT / MERGE / REDEEM
    do NOT pass through here (chain-side primitives — no CLOB fee).

    The env vars `tv_poly_taker_fee_bps` / `tv_poly_maker_rebate_bps` act
    as an additive override layer on top of the canonical curve. Default
    0 → canonical only, which is the production case.
    """
    if slug_state is None:
        return

    # Import at call time to avoid a module-init cycle.
    from backend.app.strategies.polymarket.maker.base import (
        maker_rebate,
        taker_fee,
    )

    fee_per_share = taker_fee(fill_price)             # 0.07 * p * (1-p)
    if is_maker:
        slug_state.rebates_received += maker_rebate(fee_per_share) * fill_size
        bps = int(getattr(self._settings, "tv_poly_maker_rebate_bps", 0))
        if bps:
            slug_state.rebates_received += (
                fill_price * fill_size * Decimal(bps) / Decimal(10_000)
            )
    else:
        slug_state.taker_fees_paid += fee_per_share * fill_size
        bps = int(getattr(self._settings, "tv_poly_taker_fee_bps", 0))
        if bps:
            slug_state.taker_fees_paid += (
                fill_price * fill_size * Decimal(bps) / Decimal(10_000)
            )
```

## 4. Edit F1.B — `strategies/polymarket/maker/mas.py` lines 416-423

MAS currently books rebates AND taker fees internally. After F1.A lands, the fill simulator does this centrally. Keeping MAS's path would double-book.

### Before

```python
        state.cash_received += evt.price * evt.size
        if evt.is_maker:
            # Maker rebate accounting — 20% of the equivalent taker fee.
            state.rebates_received += maker_rebate(taker_fee(evt.price)) * evt.size
        else:
            # Defensive: a non-maker fill on an ASK shouldn't normally
            # occur (we're the resting order), but if it does, accumulate
            # the taker fee for accounting symmetry with ACC-M.
            state.taker_fees_paid += taker_fee(evt.price) * evt.size
```

### After

```python
        state.cash_received += evt.price * evt.size
        # Fees + rebates are booked centrally by MakerFillSimulator
        # (_apply_bps_deltas in engine/poly_maker_fill_sim.py).
```

Also drop the now-unused `taker_fee` / `maker_rebate` imports near the top of mas.py.

## 5. Unit tests (must pass)

Add to `tests/engine/test_poly_maker_fill_sim.py` (or whichever fixture is closest):

```python
def test_take_fill_books_canonical_taker_fee():
    """TAKE on a fresh slug at p=0.5, size=20 → fee = 0.07 × 0.5 × 0.5 × 20 = 0.35"""
    sim._apply_bps_deltas(slug_state, Decimal("0.5"), Decimal("20"), is_maker=False)
    assert slug_state.taker_fees_paid == Decimal("0.35")
    assert slug_state.rebates_received == Decimal("0")

def test_post_fill_books_canonical_maker_rebate():
    """FILL at p=0.5, size=20 → rebate = 0.20 × 0.07 × 0.5 × 0.5 × 20 = 0.07"""
    sim._apply_bps_deltas(slug_state, Decimal("0.5"), Decimal("20"), is_maker=True)
    assert slug_state.rebates_received == Decimal("0.07")
    assert slug_state.taker_fees_paid == Decimal("0")

def test_take_fill_at_p_0_85():
    """fee = 0.07 × 0.85 × 0.15 × 20 = 0.1785"""
    sim._apply_bps_deltas(slug_state, Decimal("0.85"), Decimal("20"), is_maker=False)
    assert slug_state.taker_fees_paid == Decimal("0.1785")

def test_bps_override_adds_on_top_of_canonical():
    """If tv_poly_taker_fee_bps=50 (5 bps), canonical + 5bps both apply."""
    sim._settings.tv_poly_taker_fee_bps = 50
    sim._apply_bps_deltas(slug_state, Decimal("0.5"), Decimal("20"), is_maker=False)
    expected = Decimal("0.35") + Decimal("0.5") * Decimal("20") * Decimal("50") / Decimal("10000")
    # = 0.35 + 0.05 = 0.40
    assert slug_state.taker_fees_paid == expected
```

## 6. End-to-end smoke test

After deploy + restart `tv-engine.service`:

1. Wait for one fresh ACC-M slug with at least 1 TAKE row + 1 FILL row.
2. Pull the slug's CSV rows from `/var/log/tv/maker/acc-m_<date>.csv`.
3. Verify `taker_fees` column equals `sum(0.07 * p * (1-p) * size for each TAKE row)`.
4. Verify `rebates` column equals `sum(0.014 * p * (1-p) * size for each FILL row)` (0.014 = 0.20 × 0.07).
5. Verify the dashboard's `pnl_so_far` for that sleeve drops by approximately `(unbooked_fees − unbooked_rebates)` relative to pre-fix value.

Expected drop on 6-hour soak:
- ACC-M btc 5m: pnl_so_far drops ~$25-$30
- ACC-H btc 5m: pnl_so_far drops ~$15-$20
- ACC-H btc 15m: pnl_so_far drops ~$6-$8
- ACC-PC btc 15m: pnl_so_far drops ~$2-$3
- MAS btc 5m: pnl_so_far drops ~$0-$2 (rebates were being double-booked → after fix it's correct + small drop)
- PAT-SHADOW: pnl_so_far drops ~$160-$200

## 7. Rollout checklist

- [ ] Read this file end-to-end.
- [ ] Apply F1.A in `engine/poly_maker_fill_sim.py`.
- [ ] Apply F1.B in `strategies/polymarket/maker/mas.py` (remove duplicate).
- [ ] Add the 4 unit tests, run pytest, all pass.
- [ ] Restart `tv-engine.service`.
- [ ] Wait 6 hours.
- [ ] Run the smoke test (§6) on at least one slug per sleeve.
- [ ] Confirm dashboard PnL dropped within expected ranges.
- [ ] **HARD GATE for live promotion**: confirm ACC-M btc 5m HONEST cash PnL ≥ +$1.00/slug over a fresh 24h window after fix. If not, ACC-M's prior "+$2.20/slug honest" was mark-propped and the strategy isn't live-ready.

## 8. Backward compatibility

- The bps env vars stay functional as an additive layer. Operators who have `tv_poly_taker_fee_bps` or `tv_poly_maker_rebate_bps` set in `/etc/tv/tradingvenue.env` continue to add those bps on top of the canonical curve. Default 0 = no behavior change vs the new canonical baseline.
- No config schema change. No env var rename. No DB migration.

## 9. References

- Formula source: `strategy_lab/fees.py` (canonical)
- Engine helpers: `strategies/polymarket/maker/base.py:78-89`
- Console PnL reader: `api/maker_sleeves.py:529-534`
- Parent fix spec: `strategy_lab/reports/TV_AGENT_FIX_SPEC_2026_05_21.md` (this F1 is §1 of the parent)
