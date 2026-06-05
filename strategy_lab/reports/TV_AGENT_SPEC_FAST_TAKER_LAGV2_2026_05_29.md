# TV Agent Spec — `FAST_TAKER_LAGV2` — directional oracle-lag taker (shadow) — 2026-05-29

> **For the TV agent (tradingvenue repo, VPS3).** Implement `FAST_TAKER_LAGV2` as **4 new paper-only / shadow sleeves** on the existing Phase-35 sniper-v5 framework. No live capital, no new loop — reuse the sniper-v5 controller, loop, `oracle_lag` signal, `paper.get_orderbook_snapshot` 3-tier book read, and the shadow logger.
>
> **Strategy in one line:** Binance leads Chainlink (the Polymarket up-down oracle) by ~5-20s. Right after a binance move the resting Polymarket ask on the **leading side** is stale-cheap. Take it early, hold to chainlink resolution. Exit early only if binance **reverses** before settlement. Pure directional — no hedge, no merge, no complete-set lock.
>
> **Evidence:** `LAG_TAKER_FINAL_CONFIG_2026_05_29.md` + its 4 phase reports (`LAG_TAKER_EDGE_RESEARCH`, `LAG_TAKER_GATES`, `LAG_TAKER_STOPLOSS_SIZING`, `LEG2_REPRICING_STUDY`, all 2026-05-29). Backtested on canonical data, 0.07 winner-only fee, native-10Hz L25 fills, IS/OOS split.

---

## 0. The edge (so the implementation matches the backtest)
- Signal = `oracle_lag.price_delta_bps = (binance_feed − chainlink_oracle)/oracle × 10_000` (signed; >0 ⇒ feed above oracle ⇒ buy **Up**; <0 ⇒ buy **Down**).
- Fire **early** in the slot (edge decays to ~0 by 45-60s) and only on **moderate moves** (`3 ≤ |bps| ≤ 12`).
- **Dose-response (the lag signature):** WR 63.3% @ ≥3bps → 67.7% @ ≥5bps. **CAP at 12bps** — beyond that the move is already priced and the edge **reverses** (WR 56%, −$4.17/tr).
- Backtest recommended config (BTC+ETH, gated, reversal-stop, 0.07 fee): **WR ~68%, +$3.0-3.4/$25 fire (+~13%/fire), ~22 fires/day, maxDD −$227, OOS t=2.78.**
- **15m is the cleaner cell** (lower noise); 5m higher volume. Deploy both. **SOL excluded** (net drag, thin book).

---

## 1. Reuse (do NOT build a new loop)
| Need | Existing module |
|---|---|
| Fire signal | `engine/oracle_lag.py` → `compute_oracle_lag(asset, now)` → `OracleLagSnapshot.price_delta_bps` (+ `_STALE_THRESHOLD_S=5.0`) |
| Sleeve descriptor + registry | `strategies/polymarket/sniper_v5_sleeves.py` (`SniperV5Sleeve`, `SNIPER_V5_SLEEVES`) + YAML mirror + `test_sleeves.py` parity |
| Controller / dispatch | `controllers/polymarket_sniper_v5.py` (`eval_sleeve_fire`, per-direction, gates BEFORE placement) + `engine/poly_sniper_v5_loop.py` (offset dispatch) |
| Book read / fill | `paper.get_orderbook_snapshot` (3-tier WS→CLOB→Storedata) via `controller._simulate_l25_walk` (per `TV_FIX_UNIFY_BOOK_READ_PATH_2026_05_27`) |
| Gates | `strategies/polymarket/sniper_v5_gates.py` (pure, direction-aware) |
| Exit-policy precedent | `exit_policy="HEDGE_LATE"` + `maybe_hedge_late_cut` + loop `_hedge_late_then_resolve` (mirror this for the reversal stop) |
| Resolution truth | `engine/poly_updown_resolver.py` (chainlink) |
| Shadow logging | `strategies/polymarket/sniper_v5_shadow_log.py` |

---

## 2. New gates (add to `sniper_v5_gates.py`, pure + direction-aware)

The controller evals each `direction ∈ _directions_for(sleeve.direction)` and a gate returns bool for THAT direction. So a `direction=BOTH` sleeve fires only the side whose gates pass → the oracle-lag gate is how we pick the leading side.

### 2.1 — `g_oracle_lag_with` (the fire signal + direction selector)
```python
def g_oracle_lag_with(direction, fire_us, *, asset, oracle_lag, lo_bps=3.0, hi_bps=12.0, **_kw) -> bool:
    """Pass iff the oracle-lag move is in [lo,hi] bps AND its sign matches `direction`.
    >0 ⇒ feed above oracle ⇒ leading side is Up; <0 ⇒ Down.
    The >hi cap is load-bearing: moves >12bps are already priced and REVERSE (−EV)."""
    snap = oracle_lag                       # OracleLagSnapshot for `asset` at fire_us
    if snap is None:
        return False
    bps = float(snap.price_delta_bps)
    if not (lo_bps <= abs(bps) <= hi_bps):
        return False
    leading = "UP" if bps > 0 else "DOWN"
    return direction == leading
```
- **Controller must inject `oracle_lag = compute_oracle_lag(asset, fire_us)`** into the runtime kwargs for this gate (route by gate-name family in `_build_gate_kwargs`). Honor `_STALE_THRESHOLD_S` — if the snapshot is stale, gate returns False.
- Default `lo_bps=3.0`, `hi_bps=12.0`.

### 2.2 — `g_not_us_close_hours` (time-of-day filter)
```python
def g_not_us_close_hours(direction, fire_us, *, exclude_hours_utc=(18,19,20,21,22,23), **_kw) -> bool:
    """Reject fires in 18-23 UTC (edge degrades there). OOS t=3.29 standalone."""
    hour = datetime.utcfromtimestamp(fire_us/1e6).hour
    return hour not in exclude_hours_utc
```

### 2.3 — `g_cross_asset_lag_confluence` (BTC↔ETH agree)
```python
def g_cross_asset_lag_confluence(direction, fire_us, *, asset, oracle_lag_other, conf_bps=3.0, **_kw) -> bool:
    """Pass iff the OTHER asset (BTC↔ETH) is leading the SAME direction by >= conf_bps
    in the overlapping window. Sharpens WR + cuts maxDD."""
    snap = oracle_lag_other                 # compute_oracle_lag(other_asset, fire_us)
    if snap is None:
        return False
    bps = float(snap.price_delta_bps)
    other_leading = "UP" if bps > 0 else "DOWN"
    return abs(bps) >= conf_bps and other_leading == direction
```
- Controller injects `oracle_lag_other` = the paired asset's snapshot (BTC↔ETH). (SOL not used.)

### 2.4 — `g_top_depth_ge_median` (book depth)
```python
def g_top_depth_ge_median(direction, fire_us, *, l25_snap, asset, tf, depth_median_usd, **_kw) -> bool:
    """Pass iff resting $ at the buy-side top level >= the per-(asset,tf) median.
    Most OOS-robust single gate (+$0.67/tr, OOS t=2.80)."""
    d = l25_snap.up_depth_usd if direction == "UP" else l25_snap.dn_depth_usd
    return d >= depth_median_usd.get((asset, tf), 0.0)
```
- Add `DEPTH_MEDIAN_USD` per-(asset,tf) constants to `sniper_v5_thresholds.py` (compute from the backtest window; values in the LAG_TAKER_GATES report).

> **Do NOT add a tighter spread gate or RSI/MACD/CCI gates** — backtest: spread-tightening is INVERSE (edge lives in dislocated wide books); 1s RSI/MACD/CCI are no-ops (~98% agree with the move — the move IS the signal).

---

## 3. New exit policy — `LAG_REVERSAL_STOP` (mirror the HEDGE_LATE wiring)

### 3.1 — `SniperV5Sleeve` field
`exit_policy` already exists ("HOLD" | "HEDGE_LATE"). Add a third value **`"LAG_REVERSAL_STOP"`** + params:
```python
exit_policy: str = "HOLD"               # + "LAG_REVERSAL_STOP"
reversal_stop_bps: float = 10.0         # exit if binance reverses >= this vs entry dir
reversal_poll_s: int = 5                # check cadence until slot_end
```

### 3.2 — Loop branch (`poly_sniper_v5_loop.py`)
In `_fire_at_offset`, alongside the existing `exit_policy == "HEDGE_LATE"` branch, add:
```python
elif getattr(sleeve, "exit_policy", "HOLD") == "LAG_REVERSAL_STOP":
    asyncio.create_task(_reversal_stop_then_resolve(controller, slot, sleeve, fr, oracle_resolve))
```
New `_reversal_stop_then_resolve`: poll every `reversal_stop_poll_s` until `slot_end_us`; each poll calls `controller.maybe_reversal_stop(sleeve, slot, fr)`. If it cuts → done (no resolution event). Else at slot_end fall through to `_resolve_at_slot_end`.

### 3.3 — Controller `maybe_reversal_stop`
```python
async def maybe_reversal_stop(self, sleeve, slot, fr) -> bool:
    """Exit early iff binance has reversed >= reversal_stop_bps against the entry
    direction since fire. Sell the held side at the L25 bid (0.07 fee on the sale)."""
    snap = compute_oracle_lag(slot.asset, now_us)     # current feed vs oracle
    moved = float(snap.price_delta_bps)
    # entry dir UP wanted feed>oracle; reversal = feed now below entry basis by >= bps
    reversed_bps = (fr.entry_delta_bps - moved) if fr.direction == "UP" else (moved - fr.entry_delta_bps)
    if reversed_bps < sleeve.reversal_stop_bps:
        return False
    book = await self._book_snapshot_fn(int(token_id_for(slot, fr.direction)))
    bids = book.get("bids") or []
    if not bids:
        return False                                   # can't exit → hold to resolution
    sell_vwap = self._walk_bids_for_shares(bids, fr.fill_shares)
    pnl = (sell_vwap - fr.fill_vwap) * fr.fill_shares
    fr.pnl_usd = pnl if pnl <= 0 else pnl * (1 - 0.07*sell_vwap)   # 0.07 curve on a winning sale
    fr.exit_type = "lag_reversal_cut"
    self._emit_resolved(fr, slot, outcome=None)
    return True
```
- `FireResult` gains `entry_delta_bps: float | None` (the `price_delta_bps` at fill, needed to measure reversal) and reuses `exit_type` / `hedge_sell_vwap`-style fields. Store `price_delta_bps` on the FireResult at placement.
- **Price-floor stops are explicitly NOT used** (backtest: they realize recoverable noise dips, gut $/tr). Only the binance-reversal (signal-driven) stop.

---

## 4. The 4 sleeves (add to `SNIPER_V5_SLEEVES` + YAML + test)

`direction: BOTH` → the controller evals both sides; `g_oracle_lag_with` passes only the leading side. Early offsets; one fire per qualifying early signal.

```yaml
- sleeve_id: poly_fast_taker_lagv2_btc_5m
  asset: BTC
  tf: 5m
  direction: BOTH
  offsets: [5, 10, 20, 40]          # early-weighted; edge decays by 45-60s
  spread_filter: 0.05               # LOOSE on purpose — edge lives in wide books; do NOT tighten
  paper_only: true
  mode: shadow
  notional_usd_override: 25.0       # flat for v1 shadow; confidence-prop sizing = phase 2 (§6)
  exit_policy: LAG_REVERSAL_STOP
  reversal_stop_bps: 10.0
  one_shot_per_slug: true           # fire ONCE on first qualifying early offset, then stop
  gates:
    - g_oracle_lag_with(lo_bps=3.0, hi_bps=12.0)
    - g_not_us_close_hours
    - g_cross_asset_lag_confluence(conf_bps=3.0)   # other = ETH
    - g_top_depth_ge_median
```
- `poly_fast_taker_lagv2_btc_15m` — identical, `tf: 15m` (the **cleaner** cell).
- `poly_fast_taker_lagv2_eth_5m` — `asset: ETH`, confluence other = BTC.
- `poly_fast_taker_lagv2_eth_15m` — `asset: ETH`, `tf: 15m`, confluence other = BTC.

> **New `SniperV5Sleeve` fields** (default-valued so the existing 78 sleeves are unaffected): `reversal_stop_bps: float = 10.0`, `reversal_poll_s: int = 5`, `one_shot_per_slug: bool = False`. Update the dataclass, YAML loader, and `test_sleeves.py` parity.
> **`one_shot_per_slug=True`** needs the controller to dedup fires per (sleeve, slug) after the first placement (the directional taker wants ONE entry, not one per offset). Verify this doesn't break the existing multi-offset sleeves (they default `False`).

---

## 5. Fee + fill (shadow)
- Fill via `_simulate_l25_walk` → `paper.get_orderbook_snapshot` 3-tier, native-10Hz, +85ms latency budget, walk asks for `notional` on the leading side. Honor `spread_filter` (same-token `ask0−bid0`, per `_sniper_spread.compute_spread`).
- **Fee = 0.07 winner-only curve** (the verified production fee): `pnl_won = (1−vwap)·shares·(1 − 0.07·vwap)`; `pnl_lost = −vwap·shares`. Same curve on a reversal-stop sale. (This is the controller's current HOLD-path fee — inherit it; do NOT use legacy 2%.)
- Outcome = `poly_updown_resolver` (chainlink), never binance close.
- Anchor = `slot_start + offset_s` (intra-window) — NOT the momo `ws_s` anchor.

---

## 6. Sizing — flat for v1, confidence-proportional for v2
- **v1 shadow**: flat `notional_usd_override = 25.0` (or $5 ramp-start, operator choice). Confirm WR/fill parity first.
- **v2 (after parity)**: confidence-proportional sizing — `notional = base × clip((bucket_WR(asset,tf,bps_tier) − entry_vwap) / k, 0.5, 4.0)`. Backtest: beats flat AND naive Kelly (Kelly over-bets the −EV >12bps tier; the 12bps CAP + confidence-prop both avoid it). Add a `sizing_mode: str = "flat"` field + a `confidence_prop` branch in the notional calc. Defer until v1 confirms the edge live.

---

## 7. Logging (`sniper_v5_shadow_log` + columns)
Per fire/fill/skip/reversal-cut/settle row, add: `price_delta_bps, price_delta_bps_other, side, offset_s, vwap, shares, notional, ask0, bid0, spread, top_depth_usd, entry_delta_bps, reversal_bps_at_exit, exit_type, outcome, won, pnl, skip_reason`. Tag each with `sleeve_id`.

---

## 8. Config (env)
```
TV_FTLAGV2_ENABLED=true
TV_FTLAGV2_LO_BPS=3.0
TV_FTLAGV2_HI_BPS=12.0            # hard cap — >12 reverses to -EV
TV_FTLAGV2_REVERSAL_BPS=10.0
TV_FTLAGV2_SPREAD=0.05            # loose by design
TV_FTLAGV2_LATENCY_MS=85
TV_FTLAGV2_EXCLUDE_HOURS_UTC=18,19,20,21,22,23
TV_FTLAGV2_FEE_MODEL=poly_taker_curve   # 0.07*p*(1-p) winner-only (verified prod fee)
TV_FTLAGV2_KILL=                 # e.g. poly_fast_taker_lagv2_eth_5m
```
All sleeves `paper_only=true / mode=shadow`. Live promotion deferred (Phase-35 policy).

---

## 9. Acceptance criteria
- **AC-1 fire/fill**: fires concentrate at early offsets (5-40s); fill rate 65-91% (spread filter + thin-book rejects the rest).
- **AC-2 direction**: only the leading side fires (verify `side` matches `sign(price_delta_bps)` in 100% of fires).
- **AC-3 cap**: zero fires with `|price_delta_bps| > 12` (the gate rejects them).
- **AC-4 WR**: filled-fire WR ≈ **68%** as n grows (allow OOS CI; must stay >60%, t builds >2).
- **AC-5 reversal stop**: `lag_reversal_cut` rows fire only when `reversal_bps_at_exit ≥ 10`; verify they cut losers early (worst-tail shrinks vs a HOLD-only twin).
- **AC-6 fill parity**: sampled fire vwap matches canonical replay within ≤0.01.
- **Go/no-go (before any live capital)**: ≥2 weeks shadow, n≥200 filled fires, WR ≥60%, mean pnl/fire >0 after the 0.07 fee, 7-day rolling WR not trending down (crowding check).

---

## 10. Deliverable checklist
1. Add 4 gates (`g_oracle_lag_with`, `g_not_us_close_hours`, `g_cross_asset_lag_confluence`, `g_top_depth_ge_median`) to `sniper_v5_gates.py`; route their runtime kwargs (`oracle_lag`, `oracle_lag_other`, `l25_snap`, `depth_median_usd`) in the controller `_build_gate_kwargs`.
2. Add `DEPTH_MEDIAN_USD` to `sniper_v5_thresholds.py`.
3. Add `exit_policy="LAG_REVERSAL_STOP"` + `maybe_reversal_stop` (controller) + `_reversal_stop_then_resolve` (loop); add `entry_delta_bps` to `FireResult`.
4. Add `SniperV5Sleeve` fields: `reversal_stop_bps`, `reversal_poll_s`, `one_shot_per_slug` (+ later `sizing_mode`).
5. Implement `one_shot_per_slug` dedup in the controller (per sleeve+slug).
6. Add the **4 sleeves** to `SNIPER_V5_SLEEVES` + YAML; update `test_sleeves.py` parity + a unit test per new gate.
7. Extend `sniper_v5_shadow_log` columns (§7).
8. Deploy paper-only/shadow; verify AC-1…AC-6 over the first days.

---

## 11. What is deliberately EXCLUDED (backtested dead ends — do not add)
- Complete-set lock / hedge / merge — DEAD (UP/DOWN asks anti-correlated −0.90, sum pinned ~1.01, 0% lockable at any latency).
- Price-floor stop-loss — realizes recoverable noise dips, −EV.
- Tighter spread filter — inverse (edge is in wide books).
- 1s RSI/MACD/CCI gates — no-ops.
- `|bps| > 12` fires — reverse to −EV.
- SOL — net drag, thin book.

## END
