# TV Agent Fix Spec — Maker-Arb Shadow Engine (2026-05-21)

**Scope**: Polymarket maker-arb shadow engine on Ireland VPS.
**Affected sleeves**: ACC-M, ACC-H, ACC-PC, MAS, PAT-SHADOW.
**Goal**: bring shadow-mode PnL to live-quality accuracy so promote/kill
decisions are made on numbers we can trust.
**Author**: claude (analysis only — no code changes applied)
**Reproducers**: `migration_ireland_shadow_2026_05_21/audit_*.py`,
`fill_sim_audit.md`

## 0. TL;DR for the TV agent

Implement four fixes in order. Each has exact file paths + before/after
diffs + a unit test. After all four land, ACC-M btc 5m's honest PnL stays
positive (~+$1.20-$1.90/slug), ACC-H btc 5m flips marginal-to-negative
(promote-block), ACC-PC stays in the noise band, MAS stays flat, PAT-SHADOW
stays structurally negative (as designed).

| # | Severity | Title | Files touched | Lines |
|---|---|---|---|---:|
| F1 | HIGH | Book canonical taker fee + maker rebate on every fill | `engine/poly_maker_fill_sim.py`, `strategies/.../mas.py` | ~30 |
| F2 | HIGH | Close phantom-fill race (CANCEL vs in-flight trade print) | `engine/poly_maker_fill_sim.py` | ~10 |
| F3 | HIGH | Strict-cross fill trigger + queue-depth respect | `engine/poly_maker_fill_sim.py` `_check_fill` + `_on_trade_print_impl` | ~25 |
| F4 | MEDIUM | Add 85ms latency floor + sparse-book gate to maker fills | `engine/poly_maker_fill_sim.py` `_emit_post_fill` | ~15 |
| F5 | MEDIUM | Dedupe multi-fill emissions for the same order_id | `engine/poly_maker_fill_sim.py` `_on_trade_print_impl` | ~8 |
| F6 | LOW | Strip undocumented PAT-overlay from ACC-H **or** document it in spec | `strategies/.../acc_h.py` + spec | doc |
| F7 | LOW | Disable V3f rule C (never fires) and re-evaluate rule B on btc 5m | `strategies/.../acc_h.py` + spec | config |

**Not a bug — do not fix**: PAT-SHADOW emits zero REDEEM events by design.
It TAKEs both sides equally; MERGE consumes paired inventory mid-slug; no
winner residual to redeem at resolution. The reported -$1,305.83 console
PnL is genuine taker-fee bleed net of MERGE proceeds. PAT is structurally
break-even-to-negative on its own and should be evaluated as an overlay
contribution to ACC-M, not standalone.

## 1. FIX F1 — Book canonical taker fee + maker rebate on every fill (HIGH)

### Symptom

CSV column `taker_fees` reads `$0.00` across ALL 9,375 TAKE events on ACC-H,
1,857 on ACC-M, etc. CSV column `rebates` reads `$0.00` on every strategy
except MAS (which books rebates internally). Console PnL formula reads
`+ rebates − taker_fees` — so PnL is over-stated by the unbooked side.

### Root cause

`engine/poly_maker_fill_sim.py:776-806` `_apply_bps_deltas` only adds to
`slug_state.taker_fees_paid` / `rebates_received` when the env vars
`tv_poly_taker_fee_bps` / `tv_poly_maker_rebate_bps` are non-zero. They
default to 0 and are NOT set in `/etc/tv/tradingvenue.env`. So the bps
adder is a no-op. The canonical fee/rebate formula in
`strategies/polymarket/maker/base.py:78-89` (`taker_fee()` and
`maker_rebate()`) is used for trade GATING (e.g. `pair_cost = ba_up + ba_dn
+ fee_up + fee_dn` in `acc_m.py:694`) but never written into slug_state.

### Canonical formula (locked)

    fee_per_share    = feeRate × p × (1 − p)
    rebate_per_share = rebate_share × fee_per_share

`feeRate = 0.07` for crypto up-down markets. `rebate_share = 0.20`. Source:
`strategy_lab/fees.py`. Engine helpers: `base.taker_fee(p)` (line 84),
`base.maker_rebate(t_fee)` (line 87).

### Edit F1.A — `engine/poly_maker_fill_sim.py` lines 776-806

Replace the body of `_apply_bps_deltas` so it ALWAYS applies the canonical
formula, with the bps env vars staying as an optional additive override
(default 0 → unchanged operator UX).

**Before** (lines 776-806):

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

**After**:

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
    as an *additive override* layer on top of the canonical curve. Default
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

### Edit F1.B — `strategies/polymarket/maker/mas.py` lines 416-423

MAS currently books rebates AND taker fees internally. After F1.A lands,
the fill simulator does this centrally. Keeping MAS's path would
double-book. Remove the duplicate:

**Before**:

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

**After**:

```python
        state.cash_received += evt.price * evt.size
        # Fees + rebates are booked centrally by MakerFillSimulator
        # (_apply_bps_deltas in engine/poly_maker_fill_sim.py).
```

Also drop the now-unused `taker_fee` / `maker_rebate` imports near the
top of mas.py.

### Acceptance tests

```python
def test_take_fill_books_canonical_taker_fee():
    # TAKE on fresh slug at p=0.5, size=20 → fee = 0.07 × 0.5 × 0.5 × 20 = 0.35
    sim._apply_bps_deltas(slug_state, Decimal("0.5"), Decimal("20"), is_maker=False)
    assert slug_state.taker_fees_paid == Decimal("0.35")
    assert slug_state.rebates_received == Decimal("0")

def test_post_fill_books_canonical_maker_rebate():
    # FILL at p=0.5, size=20 → rebate = 0.20 × 0.07 × 0.5 × 0.5 × 20 = 0.07
    sim._apply_bps_deltas(slug_state, Decimal("0.5"), Decimal("20"), is_maker=True)
    assert slug_state.rebates_received == Decimal("0.07")
    assert slug_state.taker_fees_paid == Decimal("0")

def test_take_fill_books_fee_at_p_0_85():
    # fee = 0.07 × 0.85 × 0.15 × 20 = 0.1785
    sim._apply_bps_deltas(slug_state, Decimal("0.85"), Decimal("20"), is_maker=False)
    assert slug_state.taker_fees_paid == Decimal("0.1785")
```

E2E smoke: after a strategy emits one TAKE @ p=0.70 size=10, the latest
CSV row's `taker_fees` column must equal `0.07 × 0.70 × 0.30 × 10 = 0.147`
(pre-fix value: 0.000).

### PnL impact

The per-sleeve over-statement we currently absorb (computed in
`migration_ireland_shadow_2026_05_21/console_repro.csv`):

| sleeve | unbooked fees | unbooked rebates | net over-statement |
|---|---:|---:|---:|
| poly_acc_m_btc_5m_shadow | $162.45 | $56.73 | $105.72 |
| poly_acc_h_btc_5m_shadow | $181.63 | $106.77 | $74.86 |
| poly_acc_h_btc_15m_shadow | $48.03 | $17.98 | $30.05 |
| poly_acc_pc_btc_15m_shadow | $44.06 | $33.97 | $10.09 |
| poly_pat_shadow_btc_5m_shadow | $812.77 | $162.21 | $650.56 |

After F1, console = honest PnL.

## 2. FIX F2 — Close phantom-fill race (HIGH)

### Symptom

494 of 1,739 FILL events on May 21 (28.4 %) follow a CANCEL on the same
`order_id` with `CANCEL_ts < FILL_ts`. Per sleeve: ACC-M 154, ACC-H 340.
A CANCEL that arrived BEFORE the simulator emitted the FILL should have
removed the resting order from the book — but the simulator awarded the
fill anyway because the cancel didn't reach the trade-print handler in
time.

### Root cause

`engine/poly_maker_fill_sim.py` lines ~1069-1087 has a strategy-side guard
that drops fills if the strategy has already issued a cancel Decision. But
the sim-side race between `_observe_cancel` (line 381) and trade-print
arrival in `_on_trade_print_impl` is unguarded. When a trade print arrives
between `observe(cancel_decision)` returning and the cancel actually
removing the order from `_open_orders_by_token`, the trade print can still
match the order and emit a FILL.

### Fix

Edit `engine/poly_maker_fill_sim.py` `_observe_cancel` (line ~381) to
IMMEDIATELY remove the order from `_open_orders_by_token` AND set a
short-lived `_cancelled_until` timestamp on the order_id. Then in
`_on_trade_print_impl`, skip orders whose order_id is in
`_cancelled_until` and whose cancel ts was before the trade-print ts.

(Exact line numbers depend on the file — TV agent: grep for
`_open_orders_by_token` and `_on_trade_print_impl`. The guard pattern:

```python
# In _observe_cancel:
self._open_orders_by_token[token_id].pop(order_id, None)
self._cancelled_until[order_id] = decision.ts_us

# In _on_trade_print_impl, before matching:
if order_id in self._cancelled_until:
    if trade_print.ts_us >= self._cancelled_until[order_id]:
        continue  # cancel landed before the trade — no fill
```
)

### Acceptance test

```python
def test_cancel_before_trade_print_blocks_fill():
    # POST BID @0.50 size=20, then CANCEL at t=100, then trade print at t=110
    sim.observe(post_decision)
    sim.observe(cancel_decision, ts_us=100)
    sim.on_trade_print(slug, side="up", price=Decimal("0.50"), size=Decimal("5"), ts_us=110)
    assert len(emitted_fills) == 0
```

### PnL impact

The 28.4 % phantom-fill rate over-states maker fill volume. Removing them
drops ACC-M fill rate from 3.22 % to ~2.30 % and ACC-H from 9.35 % to
~6.70 %. Estimated PnL correction: -$0.30 to -$0.80 per slug per sleeve.

## 3. FIX F3 — Strict-cross trigger + queue-depth respect (HIGH)

### Symptom

`_check_fill` uses `<=` for buy-side fills (touch counts as a cross). Real
CLOBs require a strict cross: a BID at 0.50 only fills when the trade
price is < 0.50. The off-by-one inflates fill rate by ~5-10 %.

Additionally, `_on_trade_print_impl` subtracts the full trade size from
our queue position regardless of how much depth is ahead of us in the
book. Real-world: if we're ranked 5th in a queue of 100 shares ahead, a
20-share trade doesn't fill us — it consumes the 20 shares from positions
1-2. The simulator treats us as if we're always at position 1.

### Fix

Change `_check_fill` from `<=` to `<` for BID-side triggers and `>` for
ASK-side triggers.

For queue-position, introduce a per-order `queue_depth_ahead_us` populated
on POST (from the L25 snapshot at post time: sum of size at our price
level that arrived before us). Subtract trade size from `queue_depth_ahead`
FIRST; only fill when `queue_depth_ahead <= 0`.

(This is the bigger of the two — TV agent: design a queue tracker on the
order object, initialize from L25 depth at post time, update on every
trade print at or through our price level.)

### Acceptance tests

```python
def test_strict_cross_buy_no_fill_on_touch():
    sim.observe(post_bid_at_0_50)
    sim.on_trade_print(slug, side="up", price=Decimal("0.50"), size=Decimal("5"))
    assert len(emitted_fills) == 0  # touch is not a cross

def test_strict_cross_buy_fills_below():
    sim.observe(post_bid_at_0_50)
    sim.on_trade_print(slug, side="up", price=Decimal("0.49"), size=Decimal("5"))
    assert len(emitted_fills) == 1

def test_queue_depth_blocks_fill_until_consumed():
    # Post a BID at p=0.50 with 20 shares ahead of us
    sim.observe(post_decision_with_queue_depth_ahead=Decimal("20"))
    # Trade print of 15 — consumes 15 of the 20 ahead, we don't fill yet
    sim.on_trade_print(slug, side="up", price=Decimal("0.49"), size=Decimal("15"))
    assert len(emitted_fills) == 0
    # Next trade print of 10 — consumes 5 ahead then fills us 5
    sim.on_trade_print(slug, side="up", price=Decimal("0.49"), size=Decimal("10"))
    assert len(emitted_fills) == 1
    assert emitted_fills[0].size == Decimal("5")
```

### PnL impact

Combined with F2, expect fill rate to drop ~30-40 % and PnL to drop by
$0.50-$1.20/slug on the maker side. ACC-M btc 5m honest PnL +$2.20/slug
likely lands at +$1.00-$1.40/slug after F2+F3.

## 4. FIX F4 — Add 85 ms latency floor + sparse-book gate to maker fills (MEDIUM)

### Symptom

Median POST→FILL latency in current shadow data is 11.5 ms, with 55 fills
under 85 ms. Real CLOB ack RTT from Ireland to AWS eu-west-2 is ≥ 50 ms.
And `engine_v2` has a `min_book_events=25` sparse-book filter to drop
fills that occur during low-activity windows — this simulator has neither.

### Fix

In `_emit_post_fill`:
- Reject the fill if `trade_print.ts_us - post_decision.ts_us < 85_000`
  microseconds (configurable via `tv_poly_maker_min_post_to_fill_us`,
  default 85_000).
- Reject the fill if `book_event_count(slug, window=last_3s) < 25`
  (configurable via `tv_poly_maker_min_book_events`, default 25).

### Acceptance test

```python
def test_fill_blocked_during_latency_window():
    sim.observe(post_decision, ts_us=1000_000)
    sim.on_trade_print(slug, side="up", price=Decimal("0.49"),
                       size=Decimal("5"), ts_us=1050_000)  # 50 ms after post
    assert len(emitted_fills) == 0  # under 85 ms

def test_fill_allowed_after_latency_window():
    sim.observe(post_decision, ts_us=1000_000)
    sim.on_trade_print(slug, side="up", price=Decimal("0.49"),
                       size=Decimal("5"), ts_us=1100_000)  # 100 ms after post
    assert len(emitted_fills) == 1
```

## 5. FIX F5 — Dedupe multi-fill emissions per order_id (MEDIUM)

### Symptom

36 order_ids emit 2 FILL rows each (ACC-M 4, ACC-H 32). A single resting
BID at size 20 can only fill ONCE — subsequent trades at the same price
should consume the next-in-queue order, not our (already-filled) order.

### Fix

In `_on_trade_print_impl`, after emitting a FILL for an order_id, remove
that order from `_open_orders_by_token` so the next trade print can't
match it.

### Acceptance test

```python
def test_filled_order_removed_from_book():
    sim.observe(post_bid_at_0_50_size_20)
    # First trade fills us
    sim.on_trade_print(slug, side="up", price=Decimal("0.49"), size=Decimal("20"))
    assert len(emitted_fills) == 1
    # Second trade at the same price must NOT re-fill us
    sim.on_trade_print(slug, side="up", price=Decimal("0.49"), size=Decimal("20"))
    assert len(emitted_fills) == 1  # still 1
```

## 6. FIX F6 — ACC-H inherits an undocumented PAT taker overlay (LOW)

### Symptom

Spec doc `TV_DEPLOY_SPEC_ACC_H_SHADOW_2026_05_19.md` describes ACC-H as
"ACC-M maker BIDs + V3f composite taker". The live engine actually emits
"ACC-M maker BIDs + ACC-M PAT takes + V3f composite takes". The inherited
PAT takes are 3.6× more frequent than V3f takes (1,382 vs 391 TAKE rows in
25h shadow data).

### Decision required

Either:
- **Document the inherited PAT path in TV_DEPLOY_SPEC_ACC_H_*.md** so live
  vs backtest is apples-to-apples; OR
- **Disable the PAT path in ACC-H** (override `_pat_take_decisions` to
  return [] in acc_h.py) so ACC-H matches the spec.

The audit shows PAT carries +$3.77/slug on btc 15m maker-only-cohort
(net positive contribution) and -$2.66/slug on btc 5m (net negative).
PAT is the load-bearing trigger for ACC-H's surprise sign flip on 15m,
not V3f.

### Recommendation

**Document the path** (do not disable). PAT is most of the actual alpha
on btc 15m. Update the spec to call out the three-layer trigger stack:

1. ACC-M maker BIDs (POST_BID, primary)
2. ACC-M PAT takes (TAKE @ pair_cost gate, inherited from ACC-M REV)
3. V3f composite takes (TAKE @ rules A/B/C/D, ACC-H's contribution)

## 7. FIX F7 — V3f rule decisions (LOW)

### Findings from `audit_acc_h_decomp.py`

| rule | fires | cohort | live $/slug excess vs maker baseline |
|---|---:|---|---:|
| A discount | 70 | btc_5m | -$3.67 |
| A discount | 2 | btc_15m | +$2.41 |
| B sharp drop | 301 | btc_5m | -$3.01 |
| B sharp drop | 18 | btc_15m | +$1.74 |
| C dislocation | **0** | both | **never fires** |
| D buy_pressure_dip | 10 | btc_5m | +$6.28 |

### Recommendation

- **Disable rule C** entirely. It hasn't fired once in 25 h. Either the
  threshold (`abs(sum_asks-1) > 0.005`) is too tight or the gate
  `state.n_fills == 0` is incompatible with the maker layer that always
  fires first. Remove from `acc_h.py` until re-tuned.
- **Suspend rule B on btc 5m**. 301 fires, mean −$3.01/slug excess,
  contributes -$102 over the window. Either retune the sharp_drop
  threshold (currently too lenient on 5m) or guard by `tf == "15m"`.
- **Keep rules A and D**. A is small but +$2.41/slug on 15m. D fires 10
  times total with +$6.28/slug — too small a sample to tune, leave alone.

## 8. PAT-SHADOW — not a bug, do not fix

PAT-SHADOW emits zero REDEEM events because its trigger structure pairs
takes by design: TAKE up size=N + TAKE dn size=N → MERGE consumes paired
inventory mid-slug → `inv_up == inv_dn == 0` at resolution → ACC-M's
inherited `on_slug_resolved` correctly emits no REDEEM (no winner-side
residual).

Console PnL -$1,305.83 is REAL: total taker_fees paid (currently $0 in
log, will be ~$813 after F1) minus MERGE proceeds (cash_recovered ≈
$pairs − gas). After F1 fee booking lands, PAT will report something like
`-$1,300 (cash) + $813 (newly booked fees) = -$2,100`. PAT is structurally
break-even-to-negative on its own. Evaluate it ONLY as the inherited
overlay inside ACC-M / ACC-H, not standalone.

## 9. Order of operations + verification

1. Land F1 first (single highest-impact, single-file). Verify on Ireland:
   - Run `audit_08_console_repro.py` after re-deploy + 6 h soak. Console
     PnL must equal honest PnL within $1/sleeve.
2. Land F2 + F3 + F5 together (related fill-trigger fixes). Verify:
   - Run `audit_fill_sim.py` after re-deploy. Phantom-fill rate < 1 %.
     Multi-fill duplicates = 0.
3. Land F4 (latency + sparse-book). Verify median POST→FILL ≥ 85 ms.
4. Land F6 (doc) + F7 (config) together as the "ACC-H tuning" patch.

Once F1-F5 land, re-run the 25 h shadow window. ACC-M btc 5m's honest
PnL/slug should land in [+$1.00, +$1.40] (currently +$2.20 — pro-strategy
overstated). If it does, ACC-M btc 5m remains the strongest live-promote
candidate at the wallet template's expected edge. If it lands negative,
the wallet template's edge isn't materializing in our regime and PAT is
the only carrier.

## 10. Files referenced (absolute paths)

- `migration_ireland_shadow_2026_05_21/source_code/engine/poly_maker_fill_sim.py`
- `migration_ireland_shadow_2026_05_21/source_code/engine/poly_maker_loop.py`
- `migration_ireland_shadow_2026_05_21/source_code/engine/main.py`
- `migration_ireland_shadow_2026_05_21/source_code/strategies/polymarket/maker/{acc_m,acc_h,acc_pc,mas,pat_shadow,base,types}.py`
- `migration_ireland_shadow_2026_05_21/source_code/api/maker_sleeves.py`
- `migration_ireland_shadow_2026_05_21/fill_sim_audit.md` (fill-sim deep-dive)
- `migration_ireland_shadow_2026_05_21/audit_acc_h_decomp.py` (ACC-H rule-by-rule)
- `migration_ireland_shadow_2026_05_21/audit_08_console_repro.py` (console reproducer)
- `strategy_lab/reports/SHADOW_AUDIT_2026_05_21.md` (parent audit)
- `strategy_lab/fees.py` (canonical fee model)
