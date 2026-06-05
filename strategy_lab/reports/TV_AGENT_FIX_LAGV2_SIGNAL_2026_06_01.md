# TV Agent Fix Spec — `poly_fast_taker_lagv2` wrong-signal (always-UP) bug + history reset — 2026-06-01

For the TV agent. The 4 `poly_fast_taker_lagv2_*` sleeves fire **UP on 100% of slots, never DOWN** → no directional edge → coin-flip WR (btc_15m 13% on n=15). Root cause: the live gate reads the **wrong signal**. This spec: the fix + how to reset the corrupted history so post-fix WR is clean.

**NOT a direction inversion** — do NOT flip UP↔DOWN. The fix is to restore the BACKTESTED signal.

## SCOPE — ALL 8 poly_fast_taker sleeves, 2 families, 2 gates, ONE root cause
Verified on VPS3 — every poly_fast_taker sleeve fires 100% UP / 0% DOWN. Two families share the identical feed-vs-oracle bug via two different gate functions:

| Family | Sleeves | Signal gate | Live (resolved) |
|---|---|---|---|
| **LAGV2** | `lagv2_btc_5m`, `lagv2_btc_15m`, `lagv2_eth_5m`, `lagv2_eth_15m` | `g_oracle_lag_with` | all UP, WR 13-57% |
| **A/B** | `a25_merge_btc_5m`, `a25_merge_eth_5m`, `b2_nomerge_btc_5m`, `b2_nomerge_eth_5m` | `g_oracle_lag_bps_ge` | all UP (602/594/702/264), WR 46-53% |

BOTH gates read `oracle_lag.price_delta_bps` (feed-vs-chainlink-oracle, pinned positive) → both always pick UP. **The fix below must be applied to BOTH gates (or, cleanest, at the controller that feeds both).** History reset (§5) covers all 8 sleeve_ids.

> Note: the A/B family was a merge-vs-no-merge experiment; the merge (`a25_merge`) mechanic is independently DEAD (leg-2 lock study — anti-correlated asks, never lockable). Operator may KILL the 2 `a25_merge` sleeves outright and only fix+keep the 2 `b2_nomerge` directional ones. The signal fix applies to whichever you keep.

---

## 1. What's broken

### Evidence
- Live: **95 resolved fires, ALL `direction=UP`, 0 DOWN** (across all 4 sleeves). `oracle_lag_bps` logged `None` on every one (a second, logging bug).
- Backtest fire universe: **Up 1819 / Down 1834 (~50/50)**, 68% WR. The signal is supposed to swing both ways.

### Root cause — wrong delta in the gate
The deployed gate `g_oracle_lag_with` (`sniper_v5_gates.py:805`) selects the side by `sign(oracle_lag.price_delta_bps)`, where the controller feeds:
```
price_delta_bps = (binance_feed − chainlink_oracle) / oracle × 1e4     # feed-vs-ORACLE basis
```
This is a **feed-vs-oracle basis**, NOT the backtested signal. On the live box it sits **persistently positive** (the chainlink oracle/strike reference reads below the live binance feed), so `bps` lands in the **[+3,+12] UP band every slot** and never the [−12,−3] DOWN band → **always UP**.

The BACKTEST (`lag_taker_foundation_2026_05_29.py`, `LAG_TAKER_EDGE_RESEARCH`) used a **different** signal:
```
delta_bps = binance_1s(slot_start + offset) / binance_1s(slot_start) − 1, × 1e4   # intra-window RETURN
leading   = Up if delta_bps>0 else Down
```
= how far binance moved **since the slot opened**. Swings symmetrically ± → fires UP and DOWN ~50/50 → 68% WR.

The two quantities are not equivalent. Spec `TV_AGENT_SPEC_FAST_TAKER_LAGV2_2026_05_29.md §2.1` substituted the binance-return for `price_delta_bps` ("the better signal, shadow will confirm") — shadow DISPROVED it. **Revert to the backtested signal.**

---

## 2. FIX A — use the intra-window binance return (the backtested signal)

### Signal definition (MUST match the backtest exactly)
```
px_open  = binance_close_at(slot_start)            # slot open price (binance 1s/1m)
px_fire  = binance_close_at(fire_us)               # price at fire (slot_start + offset_s)
delta_bps = (px_fire / px_open − 1) * 1e4
leading   = "UP" if delta_bps > 0 else "DOWN"
fire iff  3.0 <= abs(delta_bps) <= 12.0  AND  direction == leading
```
- `slot_start` = `int(slug.rsplit('-',1)[1])` (slot open unix seconds). `fire_us = (slot_start + offset_s) * 1e6`.
- `binance_close_at` reads the engine's binance feed (the same `binance_market_data` / 1s-bar source the engine already consumes — NOT chainlink, NOT the oracle).
- Keep the `[3,12]` band + the `12` cap (load-bearing: >12bps reverses to −EV).

### Implementation — two options (pick one)

**Option 1 (recommended, explicit): new gate + new signal kwarg.**
Add `g_binance_lag_with(direction, fire_us, *, slot_start_us, binance_lag_bps, lo_bps=3.0, hi_bps=12.0)`:
```python
def g_binance_lag_with(direction, fire_us, *, binance_lag_bps=None, lo_bps="3.0", hi_bps="12.0", **_kw) -> bool:
    """LAGV2 fire signal — intra-window binance return (slot_start→fire). Backtested signal.
    >0 ⇒ binance moved up since slot open ⇒ leading side UP; <0 ⇒ DOWN."""
    if binance_lag_bps is None:
        return False
    lo, hi = float(lo_bps), float(hi_bps)
    bps = float(binance_lag_bps)
    if not (lo <= abs(bps) <= hi):
        return False
    return direction == ("UP" if bps > 0 else "DOWN")
```
In the controller `_build_gate_kwargs` (where it currently calls `compute_oracle_lag`), compute and inject `binance_lag_bps` + `slot_start_us` for the `poly_fast_taker_lagv2_*` family:
```python
px_open = binance_close_at(asset, slot.slot_start_us)
px_fire = binance_close_at(asset, fire_us)
binance_lag_bps = (px_fire / px_open - 1.0) * 1e4 if (px_open and px_fire) else None
```
Swap the 4 sleeves' first GateRef from `g_oracle_lag_with(3.0,12.0)` → `g_binance_lag_with(3.0,12.0)`.

**Option 2 (minimal diff, covers BOTH gates at once — RECOMMENDED for the all-8 fix):**
In the controller `_build_gate_kwargs`, for the `poly_fast_taker_*` family, replace the `oracle_lag` snapshot fed to the gates with a small object whose `.price_delta_bps = binance_lag_bps` (intra-window return) and `.stale=False`. **Both `g_oracle_lag_with` (LAGV2) and `g_oracle_lag_bps_ge` (A/B) read `oracle_lag.price_delta_bps`, so this single controller change fixes ALL 8 sleeves with no gate-code edits.** Field name then lies (it's a binance return, not feed-vs-oracle) — rename later for clarity, but functionally correct.

> If you take Option 1 (explicit new gate) instead, you must add the binance-return gate to BOTH families — swap `g_oracle_lag_with` (4 LAGV2) AND `g_oracle_lag_bps_ge` (4 A/B). Option 2 avoids that by fixing the shared input.

> Confirm `binance_close_at(asset, ts)` exists or add it: read the binance 1s/1m close at-or-just-before `ts` from the engine's in-memory binance bar store (the feed driving `TV_BAR_SOURCE`). Cache `px_open` at slot discovery so it's not re-fetched per offset.

---

## 3. FIX B — reversal-stop on the SAME basis
`maybe_reversal_stop` (controller) currently measures the reversal via `compute_oracle_lag(...).price_delta_bps` (feed-vs-oracle). Switch it to the same **intra-window binance return** basis so "binance reversed ≥10bps against entry" is measured consistently:
```
reversed_bps = (entry_binance_lag_bps − current_binance_lag_bps)  if UP
             = (current_binance_lag_bps − entry_binance_lag_bps)  if DOWN
exit iff reversed_bps >= reversal_stop_bps (10)
```
Store `entry_binance_lag_bps` on the FireResult at placement.

---

## 4. FIX C — logging
`oracle_lag_bps` (renamed `binance_lag_bps`) is logged `None` on every resolved event — populate it (the signal value at fill) so direction/sign is auditable. Also log `slot_start_us`, `px_open`, `px_fire`. Per spec §7 the field list already exists — just wire the real value in.

---

## 5. RESTART HISTORY for the 4 sleeves (operator-run; destructive)
The prior always-UP fires pollute the dashboard WR. After deploying the fix, reset stats for the 4 sleeve_ids so they count only post-fix fires.

**5a. trading.events (DB — the dashboard WR source):** archive then delete the pre-fix rows.
```sql
-- archive first
CREATE TABLE IF NOT EXISTS trading.events_lagv2_prefix_archive AS
SELECT * FROM trading.events
WHERE sleeve_id IN (
  'poly_fast_taker_lagv2_btc_5m','poly_fast_taker_lagv2_btc_15m',
  'poly_fast_taker_lagv2_eth_5m','poly_fast_taker_lagv2_eth_15m',
  'poly_fast_taker_a25_merge_btc_5m','poly_fast_taker_a25_merge_eth_5m',
  'poly_fast_taker_b2_nomerge_btc_5m','poly_fast_taker_b2_nomerge_eth_5m');
-- then delete
DELETE FROM trading.events
WHERE sleeve_id IN (
  'poly_fast_taker_lagv2_btc_5m','poly_fast_taker_lagv2_btc_15m',
  'poly_fast_taker_lagv2_eth_5m','poly_fast_taker_lagv2_eth_15m',
  'poly_fast_taker_a25_merge_btc_5m','poly_fast_taker_a25_merge_eth_5m',
  'poly_fast_taker_b2_nomerge_btc_5m','poly_fast_taker_b2_nomerge_eth_5m');
```

**5b. sniper JSONL** (`/var/log/tradingvenue/sniper_v5/*.jsonl`): filter out the 4 sleeve_ids from each daily file (back up first):
```
for f in /var/log/tradingvenue/sniper_v5/*.jsonl; do
  cp "$f" "$f.bak.lagv2reset"
  grep -v 'poly_fast_taker_' "$f.bak.lagv2reset" > "$f"   # all 8 (lagv2 + a25_merge + b2_nomerge)
done
```

**5c. Dashboard run-since / inception:** reset each sleeve's RUN/inception timestamp to the post-fix deploy time (so "since inception" WR starts now). If the dashboard derives inception from the first event, 5a already handles it; if it's stored separately (sleeve_manifest / a deploy_ts), bump it to the restart time.

**5d.** Confirm no `_LIVE` twin / mirror caches these (they're paper/shadow, but check the dashboard cache + any rollup table).

---

## 6. Acceptance criteria (post-fix)
1. **Direction split ≈ 50/50** UP vs DOWN across new fires (was 100% UP). This is the #1 check — if still ~all-UP, the binance-return wiring is still wrong.
2. `binance_lag_bps` populated (non-None) on every fire; `sign(binance_lag_bps)` == direction on 100% of fires.
3. Zero fires with `|binance_lag_bps| > 12`.
4. WR rebuilds toward backtest (~65%) as n grows (allow OOS CI; needs n≥100).
5. Reversal-stop cuts only when binance-return reverses ≥10bps vs entry.
6. Dashboard shows 0 prior fires for the 4 sleeves after the history reset.

---

## 7. Files / checklist
1. `backend/app/strategies/polymarket/sniper_v5_gates.py` — add `g_binance_lag_with` (or repurpose `g_oracle_lag_with` per Option 2).
2. `backend/app/controllers/polymarket_sniper_v5.py` — `_build_gate_kwargs`: compute `binance_lag_bps` from binance close at slot_start vs fire (replace `compute_oracle_lag` for the lagv2 family); store `entry_binance_lag_bps`; fix `maybe_reversal_stop` basis; populate the log field.
3. `backend/app/strategies/polymarket/sniper_v5_sleeves.py` — swap the 4 lagv2 sleeves' first GateRef to the binance-return gate.
4. Add/confirm `binance_close_at(asset, ts)` against the engine's binance bar store; cache px_open at slot discovery.
5. Run the §5 history reset (DB + JSONL + inception) AFTER the code fix is deployed.
6. Verify AC-1 (50/50 split) within hours of restart.

## Note
The strategy idea is sound (binance leads chainlink ~5-20s; buy the side binance moved toward in the first 5s; 68% backtest). Only the live signal wiring was wrong — feed-vs-oracle (one-sided) instead of binance intra-window return (symmetric). Fix the signal, reset the history, re-validate the 50/50 split first.

## END
