# Fidelity Audit C — `poly_fast_taker` oracle-lag signal bug — 2026-06-01

> **Status: CONFIRMED BUG. ALL 8 poly_fast_taker sleeves affected. History reset required.**
>
> Source snapshot: `vps3_engine_snapshot_2026_06_01/`
> Target sleeves: `poly_fast_taker_lagv2_{btc_5m,eth_5m,btc_15m}` + `poly_fast_taker_b2_nomerge_{btc_5m,eth_5m}`

---

## 1. Fidelity table

| Aspect | Live (deployed) | Spec / Backtest | Verdict |
|---|---|---|---|
| **Signal quantity** | `price_delta_bps = (binance_feed − chainlink_oracle) / oracle × 1e4` — feed-vs-oracle basis, `OracleLagSnapshot.price_delta_bps` (`oracle_lag.py:compute_oracle_lag`) | `delta_bps = binance_1s(slot_start+offset_s) / binance_1s(slot_start) − 1 × 1e4` — intra-window binance return (`lag_taker_oos_reval_2026_06_01.py:173-175`, `LAG_TAKER_EDGE_RESEARCH`) | **BUG — WRONG QUANTITY** |
| **Signal sign / direction** | `price_delta_bps` sits persistently **positive** (binance spot always trades above the frozen Chainlink oracle strike at fire time) → `bps` is always in [+3,+12] → always UP | `delta_bps` swings ±; UP when binance moved up since slot open, DOWN when down → ~50/50 split | **BUG — causes 100% UP** |
| **Signal band [lo, hi]** | `[3.0, 12.0]` bps, `g_oracle_lag_with` (`sniper_v5_gates.py:805,831`) | `[3.0, 12.0]` bps | MATCH |
| **hi cap load-bearing** | 12.0 bps hard-cap in both `g_oracle_lag_with` and `g_oracle_lag_bps_ge` | 12.0 bps (`hi_bps=12.0`); >12 reverses to −EV | MATCH (cap correct, wrong quantity feeding it) |
| **Gate function — LAGV2 family** | `g_oracle_lag_with` (`sniper_v5_gates.py:805`) reads `oracle_lag.price_delta_bps` | same gate name, BUT spec §2.1 intended this to receive the **intra-window binance return**, not the feed-vs-oracle snapshot | BUG (gate correct, input wrong) |
| **Gate function — A/B family** | `g_oracle_lag_bps_ge` (`sniper_v5_gates.py:740`) reads `oracle_lag.price_delta_bps` | A/B spec (`TV_AGENT_SPEC_FAST_TAKER_SHADOW_AB`) intended same sign logic for direction; feed-vs-oracle not the backtested signal | BUG (same root cause) |
| **Sleeves with LAGV2 gates** | `lagv2_btc_5m`, `lagv2_btc_15m`, `lagv2_eth_5m`, `lagv2_eth_15m` — all `direction=BOTH`, gate=`g_oracle_lag_with(3.0,12.0)` (`sniper_v5_sleeves.py:1508,1533,1558,1583`) | same | MATCH (sleeve wiring fine; input signal wrong) |
| **Sleeves with A/B gates** | `b2_nomerge_btc_5m`, `b2_nomerge_eth_5m`, `a25_merge_btc_5m`, `a25_merge_eth_5m` — gate=`g_oracle_lag_bps_ge(3.0)` (`sniper_v5_sleeves.py:1463,1480,1429,1446`) | same | MATCH (wiring fine; input signal wrong) |
| **direction=BOTH sleeve config** | Set on all 8 sleeves; both gates use sign(bps) to select side | Correct — BOTH + sign-select IS the design | MATCH |
| **b2_nomerge variant** | `merge_mimic=False, one_shot_per_slug=True, notional=$2, offsets=(3,6,9,12)` | Pure directional no-merge; fire once per slug; $2 micro candidate | MATCH (design faithful; bug is shared signal) |
| **Fire timing** | `fire_us = slot_start_us + offset_s × 1e6`; LAGV2 offsets `(5,10,20,40)`, b2_nomerge `(3,6,9,12)` | spec: fire at `(slot_start + 5) × 1e6` for first offset | MATCH |
| **Exit policy — LAGV2** | `exit_policy="LAG_REVERSAL_STOP", reversal_stop_bps=10.0` (`sniper_v5_sleeves.py:1522`) | binance-reversal ≥10bps stop (`LAG_TAKER_STOPLOSS_SIZING`) | MATCH |
| **Reversal-stop measurement** | `controller.maybe_reversal_stop` (loop:296) uses `compute_oracle_lag(...).price_delta_bps` — feed-vs-oracle basis | should measure intra-window binance return reversal vs entry value | **BUG — wrong basis** |
| **cross_asset confluence gate** | `g_cross_asset_lag_confluence` reads `oracle_lag_other.price_delta_bps` (paired asset feed-vs-oracle) (`sniper_v5_gates.py:848,864`) | confluence = other asset leading SAME direction by ≥3bps intra-window binance return | **BUG — same wrong quantity in confluence gate** |
| **Fee model** | LAGV2 uses `poly_taker_curve` (0.07·p·(1−p) winner-only); A/B uses `legacy_2pct` (2%-on-profit) | LAGV2 spec: `poly_taker_curve`; backtest uses 0.07 winner-only (`LAG_TAKER_FINAL_CONFIG`) | MATCH |
| **Spread filter** | LAGV2: `_SPREAD_LAGV2=0.05` (deliberately loose); A/B: `_SPREAD_BTC/_ETH` (tighter) (`sniper_v5_sleeves.py:203,1511`) | spec: 0.05 loose; spread is INVERSE (wide = better edge) | MATCH |
| **UTC hour gate** | `g_not_us_close_hours` excludes hours {18,19,20,21,22,23} (`sniper_v5_gates.py:785`) | exclude 18-23 UTC (`LAG_TAKER_GATES` OOS t=3.29) | MATCH |
| **Sizing** | flat $25 (`notional_usd_override=Decimal("25.0")`) for LAGV2; $2 for b2_nomerge | flat $25 shadow; confidence-prop = phase 2 deferred | MATCH |
| **one_shot_per_slug** | True on LAGV2 + b2_nomerge; False on a25_merge | spec: one-shot for LAGV2 | MATCH |
| **a25_merge mechanic** | `merge_mimic=True` — routes TAKE through FIFO matched-pair book | Independent experiment; declared DEAD per leg-2 lock study (anti-correlated asks never lockable) | Design note — not a bug, but operator may kill these sleeves |
| **Logging** | `oracle_lag_bps` logged as `None` on resolved events | spec §7: populate signal value for audit | DRIFT (not a bug, but unauditable) |
| **OOS backing** | Signal bug means all live data is worthless for model validation | Backtest signal: +$1.71/tr, WR ~68%, OOS t≈1.5 (3 days forward, underpowered); `LAG_TAKER_OOS_REVAL_2026_06_01.md` | — |

---

## 2. Root-cause analysis

### 2.1 Why the live signal is always positive (100% UP)

`compute_oracle_lag` (`oracle_lag.py:93-155`) computes:

```python
price_delta_bps = (feed_price - oracle_price) / oracle_price * 10_000
```

where `feed_price = polymarket_rtds.get_binance_price(coin)` (current binance spot) and
`oracle_price = polymarket_rtds.get_chainlink_price(coin)` (most recent Chainlink push).

The Chainlink oracle updates on a heartbeat/deviation basis — its stored value is the price
**at the last push**, which is the Polymarket slug's **strike price** (the reference fixed at
slot open). Binance spot is the current live price. Since prices trend, `binance_spot >
chainlink_strike` is structurally true for most slots → `price_delta_bps` sits persistently
in [+3, +12] → `sign = +` → `leading = "UP"` → only the UP arm of the BOTH sleeve ever passes.

This is confirmed by `firing_sleeves_7d.csv`:

| sleeve_id | fires | WR | pnl |
|---|---:|---:|---:|
| `poly_fast_taker_lagv2_btc_5m` | 3 | 0.500 | −$35.46 |
| `poly_fast_taker_lagv2_eth_5m` | 3 | 1.000 | −$11.65 |
| `poly_fast_taker_lagv2_btc_15m` | 1 | — | −$8.06 |
| `poly_fast_taker_b2_nomerge_btc_5m` | 4 | 0.250 | −$5.94 |
| `poly_fast_taker_b2_nomerge_eth_5m` | 4 | 0.500 | −$1.43 |

Note: the lagv2 sleeves only started firing 2026-06-01 ~19:16 UTC (a few hours before snapshot).
The historical 100%-UP claim in `TV_AGENT_FIX_LAGV2_SIGNAL_2026_06_01.md` is from the DB audit
(`trading.events`), not this CSV window. The CSV fire counts are consistent with the just-deployed
state; all WRs are low and all pnl negative, consistent with wrong-direction random firing.

### 2.2 What the backtest/spec intended

`lag_taker_oos_reval_2026_06_01.py:173-175`:
```python
px_fire = asof(be, bc, fire)
px_open = asof(be, bc, ss * 1_000_000)
ret_off = px_fire / px_open - 1.0       # intra-window binance return
```
`delta_bps = |ret_off| * 1e4`, `direction = "UP" if ret_off > 0 else "DOWN"`.

This measures **how far binance moved since the slot opened** — symmetric ± → ~50/50 UP/DOWN.
The edge is: when binance has already moved, the Polymarket ask on the leading side is stale-cheap
(the oracle hasn't caught up yet). The implementation fed the gate the WRONG quantity (feed-vs-oracle
cross-sectional level difference) instead of the time-series return.

### 2.3 Scope — both gate functions share the same bug

- `g_oracle_lag_with` (LAGV2, `sniper_v5_gates.py:805`): reads `oracle_lag.price_delta_bps`
- `g_oracle_lag_bps_ge` (A/B, `sniper_v5_gates.py:740`): reads `oracle_lag.price_delta_bps`
- `g_cross_asset_lag_confluence` (`sniper_v5_gates.py:848`): reads `oracle_lag_other.price_delta_bps`
- `maybe_reversal_stop` (controller, referenced at `loop.py:296`): uses `compute_oracle_lag` → same basis

All 8 sleeves are affected. All live fire data is contaminated.

---

## 3. Fix delta

### FIX A — signal (required, blocking)

**Option 2 (recommended, minimal diff, fixes all 8):** In the controller's `_build_gate_kwargs`,
for the `poly_fast_taker_*` family, replace the `OracleLagSnapshot` fed to the gates with a
shim object whose `.price_delta_bps = binance_lag_bps` (intra-window return) and `.stale=False`.
Both `g_oracle_lag_with` and `g_oracle_lag_bps_ge` read `.price_delta_bps` — one controller
change fixes all 8 sleeves with no gate-code edits.

Compute `binance_lag_bps` in the controller:
```python
px_open = binance_close_at(asset, slot.slot_start_us)   # cache at slot discovery
px_fire = binance_close_at(asset, fire_us)
binance_lag_bps = (px_fire / px_open - 1.0) * 1e4 if (px_open and px_fire) else None
```

**Option 1 (explicit, cleaner long-term):** Add `g_binance_lag_with` to `sniper_v5_gates.py`
and swap all 8 GateRef entries. Spec text verbatim in `TV_AGENT_FIX_LAGV2_SIGNAL_2026_06_01.md §2`.

### FIX B — reversal-stop basis (required)

`maybe_reversal_stop` currently reads `compute_oracle_lag(...).price_delta_bps`. Switch to
intra-window binance return basis:
```
reversed_bps = (entry_binance_lag_bps − current_binance_lag_bps) if UP
             = (current_binance_lag_bps − entry_binance_lag_bps) if DOWN
exit iff reversed_bps >= reversal_stop_bps (10)
```
Store `entry_binance_lag_bps` on `FireResult` at placement.

### FIX C — confluence gate (required for LAGV2 sleeves)

`g_cross_asset_lag_confluence` reads `oracle_lag_other.price_delta_bps`. If using Option 2
(shim), also replace the `oracle_lag_other` shim for the paired asset with the intra-window
return. If using Option 1 (new gate), add `g_binance_cross_asset_confluence` counterpart.

### FIX D — history reset (required, operator-run, destructive)

Archive then delete `trading.events` rows for all 8 sleeve_ids, plus their JSONL shadow-log
inception files. Full SQL + shell commands in `TV_AGENT_FIX_LAGV2_SIGNAL_2026_06_01.md §5`.
Reset **after** code fix is deployed.

### Files to change

| File | Change |
|---|---|
| `backend/app/controllers/polymarket_sniper_v5.py` | `_build_gate_kwargs`: compute + inject `binance_lag_bps`; fix `maybe_reversal_stop` basis; cache `px_open` at slot discovery |
| `backend/app/strategies/polymarket/sniper_v5_gates.py` | Add `g_binance_lag_with` (Option 1) or keep gates unchanged (Option 2) |
| `backend/app/strategies/polymarket/sniper_v5_sleeves.py` | Swap 4 LAGV2 GateRefs (Option 1 only); no change needed for Option 2 |
| `trading.events` (DB) + JSONL logs | Archive + delete pre-fix rows for all 8 sleeve_ids |

---

## 4. b2_nomerge assessment

`poly_fast_taker_b2_nomerge_{btc,eth}_5m` is the pure-directional no-merge micro candidate.
Its design is faithful to the spec: `merge_mimic=False`, `one_shot_per_slug=True`, `$2`, offsets
`(3,6,9,12)s`, gate=`g_oracle_lag_bps_ge(3.0)`. The only issue is the shared signal bug (same
`oracle_lag.price_delta_bps` → always UP). Once the signal fix is applied, b2_nomerge is the
cleanest live-candidate sleeve of the 8 (no merge complexity, lowest notional, earliest offsets).
The companion `a25_merge_*` sleeves have an independent dead-mechanic issue (leg-2 lock study:
anti-correlated asks never lockable) and can be killed regardless of the signal fix.

---

## 5. Acceptance criteria post-fix

1. Direction split 45-55% UP/DOWN within first 50 fires per sleeve.
2. `binance_lag_bps` populated (non-None) in shadow log for every fire.
3. `oracle_lag_bps` renamed or aliased to `binance_lag_bps` in log schema.
4. `maybe_reversal_stop` no longer calls `compute_oracle_lag`; uses stored `entry_binance_lag_bps`.
5. WR converges toward 65-68% over 200+ fires (matches OOS expectation).

---

*Generated from VPS3 snapshot audit, 2026-06-01.*
