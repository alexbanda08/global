# TV Agent — Maker-arb implementation bug fix guide

**Date**: 2026-05-20
**Scope**: shadow mode only (no live money). Focus on **implementation correctness**, not strategy tuning.
**Verdict**: code is structurally sound (no algorithmic bugs). The issues are **observability + state-handling gaps** that make the shadow data unusable for proper validation.

---

## TL;DR — 10 bugs to fix, prioritized

| # | Severity | Bug | File | One-line fix |
|---|---|---|---|---|
| 1 | **HIGH** | `slug_pnl_so_far` column always empty | `shadow_log.py:286-292` | Compute + write running PnL in `_row_from_decision` |
| 2 | **HIGH** | `cash_recovered` column always empty | `shadow_log.py:286-292` | Add `row["cash_recovered"] = str(slug_state.cash_recovered)` (after adding the field to SlugState) |
| 3 | **HIGH** | `slug_offset_s` column always empty | `shadow_log.py:286-292` | Compute `(decision.ts_us - slug_active_ts_us) / 1_000_000` |
| 4 | **HIGH** | No `action="FILL"` row emitted on synthetic fill | `poly_maker_fill_sim.py:_emit_post_fill` + `_emit_take_fill` | After driving `strategy.on_order_fill`, call `shadow_log.log(fill_as_decision)` |
| 5 | **MEDIUM** | `fill_simulated=1` only set on TAKE rows, not POST rows that filled | `poly_maker_fill_sim.py:_emit_post_fill` | Same fix as #4 |
| 6 | **MEDIUM** | Aggressor=None fallback over-decrements queues | `poly_maker_fill_sim.py:_on_trade_print_impl:894-898` | Infer aggressor from `tp.price` vs current book mid; never fall through both sides |
| 7 | **MEDIUM** | `take_empty_book` advances rate-limit state before checking book | `acc_m.py:_pat_decisions` + `acc_h.py` / `acc_pc.py` PAT-like fires | Check book depth BEFORE incrementing `state.n_pat_fires` / `state.last_pat_fire_us` |
| 8 | **MEDIUM** | `sleeve_id` not in CSV → can't filter per-cell | `shadow_log.py:SHADOW_LOG_COLUMNS` | Add `sleeve_id` column, plumb through from loop |
| 9 | **MEDIUM** | Cold-start retry hardcoded to 10; silently orphans | `poly_maker_fill_sim.py:_OrderState` + retry loop | Make configurable via `tv_poly_maker_fill_sim_cold_start_max_retries` |
| 10 | **LOW** | Per-slug state lost on engine restart | `poly_maker_loop.py:startup` | Recover SlugState from `trading.events` since last `SlugActive` |

---

## Bug 1 — `slug_pnl_so_far` column always empty

### Evidence
```bash
# Confirmed via:
py -3 -X utf8 -c "import pandas as pd; df = pd.read_csv('acc-m_2026-05-20.csv'); \
    print(df.slug_pnl_so_far.notna().sum())"
# → 0 (out of 3,290 rows)
```

The column is declared in `SHADOW_LOG_COLUMNS` (line 73) but `_row_from_decision` (lines 271-293) never assigns to it.

### Root cause
`shadow_log.py:_row_from_decision` populates `inv_up`, `inv_dn`, `cash_spent`, `cash_received`, `rebates`, `taker_fees` from `slug_state` — but skips `slug_pnl_so_far`, `slug_offset_s`, and `cash_recovered`.

### Fix
In `backend/app/strategies/polymarket/maker/shadow_log.py`, after line 292:

```python
        if slug_state is not None:
            row["inv_up"] = str(slug_state.inv_up)
            row["inv_dn"] = str(slug_state.inv_dn)
            row["cash_spent"] = str(slug_state.cash_spent)
            row["cash_received"] = str(slug_state.cash_received)
            row["rebates"] = str(slug_state.rebates_received)
            row["taker_fees"] = str(slug_state.taker_fees_paid)
+           row["cash_recovered"] = str(slug_state.cash_recovered)  # bug #2
+           # bug #1: running PnL = cash_in - cash_out, computed from state
+           pnl = (
+               slug_state.cash_received
+               + slug_state.cash_recovered
+               + slug_state.rebates_received
+               - slug_state.cash_spent
+               - slug_state.taker_fees_paid
+           )
+           row["slug_pnl_so_far"] = str(pnl)
+           # bug #3: offset from slug-active timestamp
+           if slug_state.slug_active_ts_us > 0:
+               row["slug_offset_s"] = str(
+                   (decision.ts_us - slug_state.slug_active_ts_us) / 1_000_000
+               )
```

### Prerequisites
- Add `cash_recovered: Decimal = Decimal("0")` field to `SlugState` in `types.py`
- Update strategies that emit MERGE/REDEEM decisions to credit `cash_recovered` (currently the merge_decisions in acc_m.py just decrements inv but doesn't track the recovered cash; the fill_sim's `_observe_merge` should credit it via the synthetic fill path — verify on read)

### Test
```python
def test_shadow_log_writes_slug_pnl_so_far():
    state = SlugState(...)
    state.cash_spent = Decimal("10")
    state.cash_received = Decimal("3")
    state.cash_recovered = Decimal("5")
    state.rebates_received = Decimal("0.1")
    state.taker_fees_paid = Decimal("0.2")
    row = logger._row_from_decision(decision, sim_fill=False, slug_state=state)
    assert row["slug_pnl_so_far"] == "-2.1"  # 3 + 5 + 0.1 - 10 - 0.2
```

---

## Bug 2 — `cash_recovered` column always empty

Same root cause as #1. Fixed by the same patch (line `+ row["cash_recovered"] = ...`).

### Prerequisite
`SlugState.cash_recovered` field must exist. Search for it:

```bash
ssh vps_ireland 'grep -n cash_recovered /opt/tradingvenue/backend/app/strategies/polymarket/maker/types.py'
```

If absent, add to `SlugState`:
```python
cash_recovered: Decimal = Decimal("0")  # USDC recovered from MERGE + REDEEM
```

And update `fill_sim._observe_merge` and `_observe_redeem` to credit it through the synthetic fill that drives `strategy.on_order_fill`.

---

## Bug 3 — `slug_offset_s` column always empty

Same root cause as #1. Fixed by the same patch (line `+ row["slug_offset_s"] = ...`).

Requires `SlugState.slug_active_ts_us` to be set on `on_slug_active`. Verified set in `acc_m.py:176` — should be set in all strategies. Confirm in `mas.py`, `acc_h.py`, `acc_pc.py`, `pat_shadow.py`.

---

## Bug 4 — No `action="FILL"` row emitted on synthetic fill

### Evidence
```bash
py -3 -X utf8 -c "import pandas as pd; df = pd.read_csv('acc-m_2026-05-20.csv'); \
    print(df.action.value_counts())"
# Output:
#   POST_BID    1599
#   CANCEL      1546
#   TAKE         140
#   REDEEM         5
# (No FILL.)
```

But `poly_maker_fill_sim.stop` engine logs report `n_fills: 2494`. **Fills happen, state mutates, but no audit-trail row is written.** Result: CSV shows POST_BID with `inv_up=0`, then the NEXT row may show `inv_up=20`, but you can't see WHEN the fill happened, at what price, with what fees.

### Root cause
`_emit_post_fill` (poly_maker_fill_sim.py:964) builds a synthetic `OrderFill` and calls `strategy.on_order_fill(fill)` to mutate state. But it does NOT log the fill to the shadow CSV.

### Fix
After driving `strategy.on_order_fill(fill)` in `_emit_post_fill`:

```python
def _emit_post_fill(self, order: _OrderState) -> None:
    ...
    fill = _OrderFill(
        ts_us=now_us, slug=order.slug, order_id=order.order_id,
        side=order.side, price=effective_price, size=order.size,
    )
    strategy.on_order_fill(fill)
    self._stats["n_fills"] += 1

+   # AUDIT: write a FILL row to shadow CSV so we can see when fills happened
+   fill_decision = _Decision(
+       ts_us=now_us,
+       strategy=strategy.code,
+       slug=order.slug,
+       asset=order.asset,
+       tf=order.tf,
+       action="FILL",
+       side=order.side,
+       price=effective_price,
+       size=order.size,
+       order_id=order.order_id,
+       trigger_reason=f"sim_post_filled@{effective_price}",
+   )
+   self._shadow_log.log(
+       fill_decision,
+       sim_fill=True,
+       slug_state=strategy.slug_states.get(order.slug),
+   )
```

Same pattern in `_emit_take_fill` (currently emits with `trigger_reason="sim_take_vwap_filled=N"` but the row's `action` is `"TAKE"` — should be `"FILL"` to distinguish the order intent (TAKE) from the actual fill).

Decision: actually keep `action=TAKE` for the TAKE row (the order intent) AND emit a SEPARATE row with `action=FILL` after the take fills. Two-row pattern matches what the spec comment at line 967 calls "Two-row CSV pattern (RESEARCH Pattern 2)".

### Plumbing
`MakerFillSimulator.__init__` needs a reference to each strategy's `AsyncShadowLogger`. Pass it in via `poly_maker_loop`'s startup wiring.

### Test
```python
def test_post_fill_emits_csv_row():
    sim = MakerFillSimulator(shadow_loggers={"ACC-M": mock_logger}, ...)
    sim._observe_post(decision_post_bid)
    # Trigger a fill via a trade print that exhausts the queue
    sim.on_trade_print(trade_at_or_below_bid_price)
    # Now the fill should have happened
    assert mock_logger.log.called
    last_call = mock_logger.log.call_args
    assert last_call.kwargs["decision"].action == "FILL"
    assert last_call.kwargs["sim_fill"] is True
```

---

## Bug 5 — `fill_simulated=1` only on TAKE rows, not POST rows

### Evidence
```bash
py -3 -X utf8 -c "import pandas as pd; df = pd.read_csv('acc-m_2026-05-20.csv'); \
    print(df.groupby('action').fill_simulated.value_counts())"
# Output: fill_simulated=1 only on TAKE rows
```

### Root cause + fix
Same as bug #4. When the fix in #4 lands, the new `FILL` rows will have `fill_simulated=1` set correctly via `sim_fill=True`.

### Side note
The current POST_BID rows have `fill_simulated=0` — which is CORRECT for the decision itself (the post isn't filled at decision time). The misleading bit is that you can't tell from the POST_BID row whether the post LATER filled. Once bug #4 is fixed (separate FILL rows), this confusion goes away.

---

## Bug 6 — Aggressor=None fallback over-decrements queues

### Evidence
`poly_maker_fill_sim.py:_on_trade_print_impl:894-898`:

```python
agg = getattr(tp, "aggressor", None)
if agg == "buy" and order.action != "POST_ASK":
    continue
if agg == "sell" and order.action != "POST_BID":
    continue
# agg is None or unknown → both sides decrement if price matches (fallback)
```

When `tp.aggressor` is `None`, BOTH the BID and ASK queues decrement on the SAME trade print — which over-counts queue exhaustion compared to real CLOB matching (where a single trade hits ONE side based on aggressor).

### Root cause
TradePrint normalization upstream sometimes doesn't infer aggressor. The fill_sim's loose fallback compensates but at the cost of model accuracy.

### Fix
Infer aggressor from the trade price vs the current book mid:

```python
def _infer_aggressor(self, tp: "TradePrint", token_id: str) -> str | None:
    book = self._book_mirror.get(token_id) if self._book_mirror else None
    if book is None or not book.get("bids") or not book.get("asks"):
        return None
    best_bid = Decimal(book["bids"][0]["price"])
    best_ask = Decimal(book["asks"][0]["price"])
    mid = (best_bid + best_ask) / Decimal(2)
    if tp.price >= mid:
        return "buy"   # print at/above mid → BUY aggressor lifted ask
    return "sell"      # print at/below mid → SELL aggressor hit bid
```

Replace the fallback in `_on_trade_print_impl`:

```python
agg = getattr(tp, "aggressor", None)
if agg is None:
    agg = self._infer_aggressor(tp, order.token_id)
if agg == "buy" and order.action != "POST_ASK":
    continue
if agg == "sell" and order.action != "POST_BID":
    continue
# If still None (no book) → skip safely instead of dual-decrementing
if agg is None:
    continue
```

### Test
```python
def test_aggressor_inferred_when_missing():
    sim._book_mirror["tk1"] = {"bids": [{"price": "0.40"}], "asks": [{"price": "0.41"}]}
    tp = TradePrint(slug="...", price=Decimal("0.41"), size=Decimal("10"), aggressor=None)
    assert sim._infer_aggressor(tp, "tk1") == "buy"  # at-ask
    tp2 = TradePrint(slug="...", price=Decimal("0.40"), size=Decimal("10"), aggressor=None)
    assert sim._infer_aggressor(tp2, "tk1") == "sell"
```

---

## Bug 7 — `take_empty_book` advances rate-limit state before checking book

### Evidence
journalctl 2026-05-20T21:25:02 — `poly_maker_fill_sim.take_empty_book` warning for `btc-updown-5m-1779312000, side=dn`. The TAKE fired (state advanced) but the book was empty when fill_sim tried to walk it.

### Root cause
In `acc_m.py:_pat_decisions:700-701`:

```python
# State update — fires increment together; record timestamp.
state.n_pat_fires += 1
state.last_pat_fire_us = ts_us
```

These mutations happen BEFORE the decision is dispatched to fill_sim. If the fill_sim later finds an empty book and drops the take, the rate-limit state has already been advanced — meaning the strategy waits the full `pat_min_s_between_fires` window before retrying, even though the previous attempt was a no-op.

### Fix
Move state-mutation AFTER all gates pass + after the decision is built — but BEFORE returning. Actually the current order is fine for the strategy (the strategy doesn't know fill_sim will fail). The cleanest fix is **on the fill_sim side**: when `_walk_take_vwap` finds empty book, emit a `TAKE_FAILED` callback to the strategy so it can reset rate-limit state.

Alternative (cheaper): have the strategy use a `pending_pat_fire_us` field that's only promoted to `last_pat_fire_us` once the fill is confirmed. This requires bidirectional comm — heavier than needed.

**Simplest fix** (recommended): the empty-book is rare and the cost is "we skip ~1 PAT opportunity ~once per day". Just log the warning + accept the lossy rate-limit advance. **Mark as DEFER** unless data shows this happening > 1/h.

---

## Bug 8 — `sleeve_id` not in CSV → can't filter per-cell

### Evidence
The CSV has `strategy` column = `"ACC-M"`, but multiple cells (btc_5m, btc_15m, eth_5m, ...) share the same strategy code. Operator can't tell which cell a row belongs to without parsing the slug.

Currently sleeve_id is embedded in the **filename** (`acc-m_2026-05-19.csv`) but the strategy code is generic. Multi-cell runs collapse into one CSV.

### Fix
Add `sleeve_id` to `SHADOW_LOG_COLUMNS`:

```python
SHADOW_LOG_COLUMNS: list[str] = [
    "ts_us",
+   "sleeve_id",
    "strategy",
    ...
]
```

Pass `sleeve_id` into `AsyncShadowLogger`:

```python
class AsyncShadowLogger:
    def __init__(self, strategy_code: str, sleeve_id: str, ...):
        ...
        self._sleeve_id = sleeve_id

    def _row_from_decision(self, ...):
        row["sleeve_id"] = self._sleeve_id
        ...
```

The maker_loop already knows the sleeve_id per strategy instance — plumb it through during startup.

### Backward-compat
Adding a column at the start would break stream-parse contracts. Per the docstring "Add new columns ONLY at the end (append-only); never reorder." So append `sleeve_id` to the END of `SHADOW_LOG_COLUMNS`.

---

## Bug 9 — Cold-start retry hardcoded to 10; silently orphans

### Evidence
`poly_maker_fill_sim.py:_on_trade_print_impl:880`:

```python
elif order.cold_start_retry_count >= 10:
    order.cold_start_orphan = True
```

If BookMirror hasn't populated the book within 10 trade prints (~0.8s for BTC 5m), the order is silently orphaned — it can never fill, but stays "open" from the strategy's perspective.

Currently engine stats show `n_skipped_cold_start: 0` so this isn't actively biting, but a slow boot could surface it.

### Fix
Make the threshold configurable + emit a metric when orphaning happens:

```python
# In _OrderState init:
self.cold_start_max_retries = int(
    getattr(settings, "tv_poly_maker_fill_sim_cold_start_max_retries", 10)
)

# In _on_trade_print_impl:
elif order.cold_start_retry_count >= order.cold_start_max_retries:
    order.cold_start_orphan = True
    self._stats["n_skipped_cold_start"] += 1
    log.warning(
        "poly_maker_fill_sim.cold_start_orphan",
        slug=tp.slug, order_id=order_id,
        retries=order.cold_start_retry_count,
        max_retries=order.cold_start_max_retries,
    )
+   # Tell the strategy this order is dead so it can free up the dedup slot
+   strategy = self._lookup_strategy(order.slug)
+   if strategy is not None and hasattr(strategy, "slug_states"):
+       state = strategy.slug_states.get(order.slug)
+       if state is not None and order.order_id in state.open_orders:
+           del state.open_orders[order.order_id]
```

---

## Bug 10 — Per-slug state lost on engine restart

### Evidence
2026-05-20 engine restarted at least 5 times (archive backups). Each restart wipes `slug_states` in every strategy. Slugs in mid-lifecycle continue receiving L25 updates and trade prints but the strategy has no record of the inventory it accumulated before the restart.

### Impact in shadow
Mild — synthetic fills resume, but the PnL is partial.

### Impact in live (future)
**Severe** — real positions on-chain don't get cleaned up; strategy doesn't redeem winning shares; bot leaks USDC.

### Fix
On engine startup, before opening WS subscriptions:

1. Query `trading.events` for all `poly_maker_*` events since the last engine stop:
   ```sql
   SELECT * FROM trading.events
   WHERE kind LIKE 'poly_maker_%'
     AND at > (SELECT max(at) FROM trading.events WHERE kind = 'poly_maker_loop.stopping')
     AND at > now() - interval '24 hours'
   ORDER BY at;
   ```
2. Replay them through each strategy's event handlers in order.
3. Reach the "now" point with restored state.

For shadow mode this isn't urgent. For live (Phase 33+), it's mandatory.

**DEFER** to Phase 33; document the assumption in current shadow data interpretation.

---

## What's NOT a bug (just tuning / by-design)

These showed up in the audit but are **operator decisions**, not implementation problems:

- `pat-shadow` with `pat_max_pair_cost=1.02` losing $307/slug — deliberate research probe, document the loss curve
- `acc-h` firing 2,691 TAKEs/day — Rule B threshold needs tightening, not a code bug
- Engine restart loop today — TV agent was patching, expected during active development
- 5 of 17 slugs reaching REDEEM — engine restarts during slugs, not a code bug
- DB `writer_health` warnings about `orderbook_snapshots_v2` missing — Ireland VPS uses storedata on VPS3; the local probe is non-fatal noise

---

## Verification plan after fixes

### Per-bug unit tests
Each bug above has a `test_*` snippet. Add to:
- `backend/tests/unit/strategies/maker/test_shadow_log.py` (bugs #1, #2, #3, #8)
- `backend/tests/unit/engine/test_poly_maker_fill_sim.py` (bugs #4, #5, #6, #7, #9)

### Integration test
Run a 1-hour shadow session against a recorded L25 + trade stream. Verify:

```bash
# 1. slug_pnl_so_far is populated on every row that has slug_state
test "$(awk -F, 'NR>1 && $20 != "" {n++} END{print n}' acc-m_TODAY.csv)" -gt 0

# 2. FILL rows appear in CSV
test "$(awk -F, 'NR>1 && $6 == "FILL" {n++} END{print n}' acc-m_TODAY.csv)" -gt 0

# 3. fill_simulated=1 on POST/TAKE that filled
test "$(awk -F, 'NR>1 && $6 == "FILL" && $12 == "1" {n++} END{print n}' acc-m_TODAY.csv)" -gt 0

# 4. sleeve_id column present + populated
head -1 acc-m_TODAY.csv | grep -q sleeve_id

# 5. cash_recovered populated on at least some rows (after a MERGE/REDEEM)
test "$(awk -F, 'NR>1 && $17 != "" && $17 != "0" {n++} END{print n}' acc-m_TODAY.csv)" -gt 0

# 6. slug_offset_s monotonic per slug
py -c "import pandas as pd; df = pd.read_csv('acc-m_TODAY.csv'); \
    bad = df.groupby('slug').apply(lambda g: g.slug_offset_s.is_monotonic_increasing); \
    assert bad.all(), 'Non-monotonic slug_offset_s in some slugs'"
```

### Operator-level sanity check
After 1h of shadow with the fixes:

```bash
ssh vps_ireland 'tail -100 /var/log/tv/maker/acc-m_2026-05-20.csv | head -20'
```

Should see:
- `sleeve_id` column populated like `poly_maker_acc_m_btc_5m_shadow`
- `slug_pnl_so_far` populated and varying per slug
- `FILL` rows interleaved with `POST_BID`, `CANCEL`, `TAKE`
- `cash_recovered` non-zero after MERGE/REDEEM events

---

## Deployment order

1. **Bugs #1, #2, #3** (shadow_log column fixes) — pure additive, no behavioral change. Ship first.
2. **Bug #8** (sleeve_id column) — additive but breaks any consumer that hardcoded column count. Coordinate with dashboard team if applicable.
3. **Bug #4, #5** (FILL row emission) — observability gain. Validates other bug fixes by giving us a per-fill audit trail.
4. **Bug #6** (aggressor inference) — improves fill realism. Test against historical data first to ensure fill rate doesn't drop too aggressively.
5. **Bug #9** (configurable cold-start retry) — safety net for future regressions.
6. **Bugs #7, #10** — DEFER. #7 is rare-edge-case; #10 needs Phase 33 live-mode planning.

Each fix should ship as its own PR with the corresponding test. Total estimated effort: **1-2 days** for bugs 1-9; bug 10 is a separate Phase 33 task.

---

## Files to change

| File | Bugs touched |
|---|---|
| `backend/app/strategies/polymarket/maker/types.py` | #2 (add cash_recovered field) |
| `backend/app/strategies/polymarket/maker/shadow_log.py` | #1, #2, #3, #8 |
| `backend/app/engine/poly_maker_fill_sim.py` | #4, #5, #6, #9 |
| `backend/app/engine/poly_maker_loop.py` | #8 (plumb sleeve_id) |
| `backend/app/strategies/polymarket/maker/acc_m.py` | #2 (credit cash_recovered on merge) |
| `backend/app/strategies/polymarket/maker/mas.py` | #2 (credit cash_recovered on redeem) |
| `backend/tests/unit/strategies/maker/test_shadow_log.py` | new tests for #1-3, #8 |
| `backend/tests/unit/engine/test_poly_maker_fill_sim.py` | new tests for #4-6, #9 |

---

## Bottom line for TV agent

**The strategies are correctly implemented.** Don't touch the strategy decision logic.

**The shadow data is unusable for validation right now** because:
- PnL column is always blank (#1)
- Fills don't have audit rows (#4)
- Can't tell which cell a row belongs to (#8)

Ship fixes #1, #2, #3, #4, #5, #8 first (1 day's work). After 24h of clean shadow data, the operator can run any analysis script (including the F7 RSI overlay) against meaningful numbers. Without these fixes, every "what's our PnL?" question requires manual reconstruction from cash_spent / cash_received / etc. across multiple rows.

Bugs #6, #7, #9, #10 are nice-to-haves but the maker suite is functional without them.

No live money is at risk. Take your time on the fixes, but **prioritize observability**.
