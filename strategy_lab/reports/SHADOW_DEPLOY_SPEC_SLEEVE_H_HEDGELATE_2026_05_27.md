# Shadow Deploy Spec — HEDGE_LATE Variant Sleeve — 2026-05-27

**New sleeve:** `poly_sniper_v5_btc_15m_ema50_ema800_off600_down_H`
**Type:** A/B variant of V5 #12 with HEDGE_LATE exit policy active
**Status:** SPEC — for shadow eval alongside parent (HOLD)

> ⚠ Naming: operator wrote `/H` — a slash breaks sleeve_id usage in file paths, task names, and JSONL keys. Use **`_H`** suffix instead: `poly_sniper_v5_btc_15m_ema50_ema800_off600_down_H`.

---

## 1. Why this sleeve

Exit-policy research (`EXIT_POLICY_RESEARCH_2026_05_27.md`) found the parent sleeve `btc_15m_ema50_ema800_off600_down` is the **ONLY sleeve in the 56-fleet where HEDGE_LATE beats HOLD**:

| Policy | WR% | $/tr | Total $ | Δ vs HOLD |
|---|---:|---:|---:|---:|
| HOLD (parent) | 77.9% | +$2.315 | +$460.63 | — |
| **HEDGE_LATE (this sleeve)** | 76.9% | **+$2.709** | +$539.16 | **+$0.395** |

Hypothesis: 15m slots (900s window) have a long adversarial-drift tail that HEDGE_LATE cuts before resolution; 5m slots don't. Deploy this as a sibling to measure the edge live.

---

## 2. Sleeve definition

Identical to parent EXCEPT `exit_policy` and `sleeve_id`:

```
sleeve_id     = poly_sniper_v5_btc_15m_ema50_ema800_off600_down_H
parent        = poly_sniper_v5_btc_15m_ema50_ema800_off600_down
asset         = BTC
tf            = 15m
direction     = DOWN
offsets       = (600,)
window_s      = 900
spread_filter = 0.020
exit_policy   = HEDGE_LATE          # ← the only difference vs parent
gates (all must pass):
  g_dir_down(direction)
  g_tr_above_ema50(direction="DOWN", asset="BTC")
  g_tr_above_ema800(direction="DOWN", asset="BTC")
```

Parent continues to run with `exit_policy=HOLD`. Both fire on the SAME slugs (same gates) — clean A/B: identical entries, different exits.

---

## 3. HEDGE_LATE mechanics (exact)

At `hedge_check_us = slot_start_us + (window_s - 60) * 1_000_000` (= 840s into the 15m window, 60s before slot_end):

1. Read current book for the HELD token (DOWN token, since direction=DOWN) via `paper.get_orderbook_snapshot(token_id)` (3-tier, same as fills).
2. Walk the BIDS for the held `fill_shares` → compute `current_sell_vwap`.
3. **If `current_sell_vwap < fill_vwap × 0.7`** (position is deep underwater, ~30%+ loss):
   - SELL now at `current_sell_vwap` (realized partial-loss exit).
   - PnL = `(current_sell_vwap - fill_vwap) × fill_shares` minus fees (LegacyConfig: 2% on profit only; loss leg untaxed).
   - Mark `exit_type = "hedge_late_cut"`.
   - DO NOT schedule slot-end resolution for this fire (already closed).
4. **Else** (position healthy):
   - Hold to slot_end → normal resolution path (identical to HOLD).
   - Mark `exit_type = "hold_to_resolve"`.

Threshold `0.7` and check-offset `window_s - 60` are the values validated in the exit research. Keep them parametrized:

```
hedge_late_loss_ratio   = 0.70      # sell if sell_vwap < fill_vwap × this
hedge_late_check_lead_s = 60        # seconds before slot_end to check
```

---

## 4. Controller changes required

Current sniper_v5 only does HOLD-to-resolve (`_resolve_at_slot_end`). HEDGE_LATE needs a new mid-slot task.

### 4a. `SniperV5Sleeve` — add `exit_policy` field

```python
@dataclass(frozen=True, slots=True)
class SniperV5Sleeve:
    ...
    exit_policy: str = "HOLD"        # "HOLD" | "HEDGE_LATE"
    hedge_late_loss_ratio: float = 0.70
    hedge_late_check_lead_s: int = 60
```

All 77 existing sleeves default to `"HOLD"` — no behavior change for them.

### 4b. Loop — schedule hedge-check task for HEDGE_LATE sleeves

In `poly_sniper_v5_loop.py`, after a fire is placed (in `_fire_at_offset`, where `_resolve_at_slot_end` is currently spawned):

```python
for fr in results:
    if fr.all_gates_passed and fr.fill_vwap is not None:
        if sleeve.exit_policy == "HEDGE_LATE":
            asyncio.create_task(
                _hedge_late_then_resolve(
                    controller, sleeve, slot, fr, oracle_resolve,
                ),
                name=f"sniper_v5.hedge.{sleeve.sleeve_id}.{slot.slug}.{fr.direction}",
            )
        else:
            asyncio.create_task(
                _resolve_at_slot_end(controller, sleeve, slot, fr, oracle_resolve),
                name=f"sniper_v5.resolve.{sleeve.sleeve_id}.{slot.slug}.{offset_s}.{fr.direction}",
            )
```

### 4c. New task `_hedge_late_then_resolve`

```python
async def _hedge_late_then_resolve(controller, sleeve, slot, fr, oracle_resolve):
    """Sleep to slot_end - lead_s, check book, conditionally cut; else resolve normally."""
    window_s = 300 if slot.tf == "5m" else 900
    check_us = slot.slot_start_us + (window_s - sleeve.hedge_late_check_lead_s) * 1_000_000
    now_us = int(time.time() * 1_000_000)
    delay_s = (check_us - now_us) / 1_000_000
    if delay_s > 0:
        try:
            await asyncio.sleep(delay_s)
        except asyncio.CancelledError:
            return
    # Controller decides: cut now, or fall through to slot-end resolve.
    cut = await controller.maybe_hedge_late_cut(sleeve, slot, fr)
    if cut:
        return                       # position closed early; no resolution event
    # Healthy → normal resolution
    await _resolve_at_slot_end(controller, sleeve, slot, fr, oracle_resolve)
```

### 4d. Controller `maybe_hedge_late_cut`

```python
async def maybe_hedge_late_cut(self, sleeve, slot, fr) -> bool:
    """Returns True if position was cut early (no further resolution needed)."""
    token_id = slot.token_id_dn if fr.direction == "DOWN" else slot.token_id_up
    try:
        book = await self._book_snapshot_fn(int(token_id))
    except Exception:
        return False                 # can't read book → fall through to HOLD
    bids = book.get("bids") or []
    if not bids:
        return False                 # no bids to sell into → HOLD to resolve
    # Walk bids for fr.fill_shares to get realistic sell vwap
    sell_vwap = self._walk_bids_for_shares(bids, fr.fill_shares)
    if sell_vwap is None:
        return False
    if sell_vwap < fr.fill_vwap * sleeve.hedge_late_loss_ratio:
        # Cut: realize the partial loss now
        pnl = (sell_vwap - fr.fill_vwap) * fr.fill_shares
        # LegacyConfig: 2% only on profit; here it's a loss so no fee
        fr.pnl_usd = pnl if pnl <= 0 else pnl * 0.98
        fr.exit_type = "hedge_late_cut"
        fr.hedge_sell_vwap = sell_vwap
        self._emit_resolved(fr, slot, outcome=None)   # log as resolved-by-hedge
        return True
    return False                     # healthy → HOLD
```

### 4e. `FireResult` — add fields

```python
exit_type: str | None = None         # "hold_to_resolve" | "hedge_late_cut"
hedge_sell_vwap: float | None = None
```

### 4f. Shadow log — add fields
Add `exit_type` and `hedge_sell_vwap` to JSONL on resolved events. For HOLD sleeves `exit_type="hold_to_resolve"`, `hedge_sell_vwap=null`.

---

## 5. Acceptance criteria

1. ✅ Sleeve `poly_sniper_v5_btc_15m_ema50_ema800_off600_down_H` appears in `SNIPER_V5_SLEEVES` (roster → 78)
2. ✅ Parent and `_H` fire on the SAME slugs (identical gates) — verify in JSONL
3. ✅ `_H` resolved events carry `exit_type` ∈ {`hold_to_resolve`, `hedge_late_cut`}
4. ✅ When `exit_type=hedge_late_cut`, `hedge_sell_vwap` populated and resolved before slot_end
5. ✅ All other 77 sleeves still `exit_type=hold_to_resolve` (no regression)
6. ✅ Unit test: hedge cut fires when sell_vwap < fill_vwap×0.7, holds otherwise

---

## 6. Monitoring (operator)

A/B compare after 14d shadow:
- `_H` total PnL vs parent total PnL on the same slug set
- Backtest projected +$0.395/tr edge — confirm or refute live
- If `_H` underperforms parent live, kill `_H` (HEDGE_LATE backtest edge was thin: +$0.395/tr on n=199)
- Track `hedge_late_cut` rate — how often does the 0.7 threshold actually trigger?

---

## 7. Files
- `/opt/tradingvenue/backend/app/strategies/polymarket/sniper_v5_sleeves.py` — add `exit_policy` field + new sleeve entry
- `/opt/tradingvenue/backend/app/engine/poly_sniper_v5_loop.py` — branch HEDGE_LATE → `_hedge_late_then_resolve`
- `/opt/tradingvenue/backend/app/controllers/polymarket_sniper_v5.py` — `maybe_hedge_late_cut` + `_walk_bids_for_shares` + FireResult fields
- `/opt/tradingvenue/backend/app/strategies/polymarket/sniper_v5_shadow_log.py` — `exit_type` + `hedge_sell_vwap` fields

Cross-ref: `strategy_lab/reports/HANDOFF_SLEEVE_btc_15m_ema50_ema800_off600_down_2026_05_27.md`, `EXIT_POLICY_RESEARCH_2026_05_27.md`

## END
