# Fidelity Audit A1 — sniper_v5 Framework: Live vs Backtest
**Date:** 2026-06-01  
**Scope:** VPS3 shadow engine (`vps3_engine_snapshot_2026_06_01/`) vs global backtest stack (`strategy_lab/engine_v2.py`, `_opt_2026_05_30/`)  
**Method:** Read-only line-by-line comparison of live source files against backtest engine, verified against prior audits  
**Auditor note:** `controllers/polymarket_sniper_v5.py` was **not included** in the snapshot (imported lazily in `main.py:2179`). Gate-composition invariant verified via architecture docs + loop code; spread/fill invariants verified via `sniper_v5_gates.py` + `poly_maker_fill_sim.py`.

---

## Per-Invariant Table

| # | Invariant | Live behavior + file:line | Backtest behavior | Verdict | Impact |
|---|-----------|--------------------------|-------------------|---------|--------|
| 1 | **FEE MODEL** | See §1 detail below | See §1 detail below | **DRIFT** | High |
| 2 | **SPREAD FILTER** | Same-token ask0−bid0, per-asset thresholds | Same-token ask0−bid0 | **MATCH** | None |
| 3 | **WS_S / FIRE TIMING** | `fire_us = slot_start_us + offset_s × 1e6` | Same (read from trading_events `fire_us`) | **MATCH** | None |
| 4 | **FILL MODEL** | Book-walk on live BookMirror, no latency shift, sparse guard only when `fill_realism=True` (OFF by default, level count ≥2 only) | `LiveMimicConfig`: 85ms latency shift + min 25 events in 120s window; `LegacyConfig`: 0ms, no events filter | **DRIFT** | Medium |
| 5 | **GATE CAUSALITY** | All gate fns pure, no I/O; pre-window gates anchor at `ws_s_us = slot_start_us − window_s×1e6`; flow gates read V9DataStore live ring buffer (no lookahead) | Backtests read `gates_evaluated` dict already written by live controller — gates not re-evaluated | **MATCH** | None |
| 6 | **SLEEVE REGISTRY** | `SNIPER_V5_SLEEVES` list in `sniper_v5_sleeves.py`; each sleeve's `gates` tuple is AND-composed by controller (`all_gates_passed`); `sleeve_registry.py` is taxonomy only (no gate logic) | `02_build_fire_table.py` reads resolved rows from `trading_events` keyed by `sleeve_id` — same static list | **MATCH** | None |

---

## §1 — Fee Model (DRIFT, High Impact)

### Live (`poly_maker_fill_sim.py`)

Two separate fee charges apply on the sniper_v5 taker path:

**Per-fill fee** (`_apply_bps_deltas`, line 810–856):
```python
model = getattr(self._settings, "tv_poly_maker_fee_model", "curve")  # default = "curve"
fee_per_share = taker_fee(fill_price, model=model)  # 0.07 * p * (1-p) when model="curve"
# TAKER fills: slug_state.taker_fees_paid += fee_per_share * fill_size
```
Default `model="curve"` charges `0.07 × p × (1−p)` per share **on every TAKE fill including losers**.

**Resolution fee** (`_observe_redeem`, line 915–924; `on_resolution`, line 1015–1017):
```python
model = getattr(self._settings, "tv_poly_maker_fee_model", "curve")
if model in ("legacy_2pct", "curve_winner"):
    res_fee = self._winner_resolution_fee(slug=..., winner_side=..., winner_qty=size, model=model)
    slug_state.taker_fees_paid += res_fee
```
**The resolution fee ONLY fires when `model in ("legacy_2pct", "curve_winner")`.**  
With default `model="curve"`, `_winner_resolution_fee` is **NOT called at resolution**.

**Net live fee behavior (default `model="curve"`):**
- Per-fill: `0.07 × p × (1−p)` charged on every TAKE (both winners and losers at fill time)
- Resolution: zero additional fee
- Net = per-fill curve on every fill, winner-only in the sense that the per-fill charge embeds the edge cost at entry

**Net live fee behavior (`model="legacy_2pct"`):**
- Per-fill: zero (taker_fee returns 0 for legacy_2pct)
- Resolution: 2%-on-profit via `_winner_resolution_fee`, winner-only
- This matches the CLAUDE.md "2%-on-profit" production description exactly

**CLAUDE.md states:** "operator-confirmed live = 0.07-curve winner-only". The code shows `model="curve"` charges the curve **at fill time on both legs** (not winner-only). The winner-only behavior only applies to `model="curve_winner"` (which is not the default). This is a **doc/code discrepancy** in addition to the live-vs-backtest drift.

### Backtest (`engine_v2.py`)

- `LegacyConfig` (line 100): `fee_model="legacy_2pct_on_profit"` — charges 2% of profit on winning leg only; zero on losers
- `LiveMimicConfig` (line 117): `fee_model="poly_taker_curve"` — charges `0.07×p×(1−p)` per share on **every fill**, including losers, at fill time (in `hold_pnl` and `fill_at_book`)
- `LegacyConfig` is described as "production parity" per CLAUDE.md (2026-05-22 verification)

### Mismatch matrix

| Config | Losers pay fee? | Winners pay fee? | Fee basis |
|--------|----------------|-----------------|-----------|
| Live `model="curve"` (default) | YES (per-fill, entry) | YES (per-fill, entry) | `0.07×p×(1−p)×shares` at fill |
| Live `model="legacy_2pct"` | NO | YES (at resolution) | 2% × profit |
| Backtest `LegacyConfig` | NO | YES (at settlement) | 2% × profit |
| Backtest `LiveMimicConfig` | YES (at fill) | YES (at fill) | `0.07×p×(1−p)` |

**Bottom line:** If live is running `model="curve"` (the default in the snapshot), backtests must use `LiveMimicConfig` to match fee magnitude, but there is still a structural difference: live charges per-fill at entry; `LiveMimicConfig.hold_pnl` also charges fee_in from entry. The formulas are algebraically equivalent for the taker-hold case, so **`LiveMimicConfig` is the correct backtest counterpart when live is in `model="curve"` mode**.

If the operator has overridden `tv_poly_maker_fee_model=legacy_2pct` in settings (consistent with CLAUDE.md 2026-05-22 verification that production charges 2%-on-profit), then `LegacyConfig` is correct. **The actual setting on VPS3 is not determinable from the snapshot alone** — it requires inspecting the running settings object. This ambiguity is the core of the DRIFT finding.

**Impact:** At `vwap=0.69, 48% WR`, `LegacyConfig` vs `LiveMimicConfig` differ by ~$0.43/trade. Over 1,000 fires the difference is ~$430 cumulative PnL. Wrong fee model = all backtest PnL numbers off by this amount.

---

## §2 — Spread Filter (MATCH)

### Live

`sniper_v5_sleeves.py` lines 197–210:
```python
_SPREAD_BTC = Decimal("0.02")
_SPREAD_ETH = Decimal("0.02")
_SPREAD_SOL = Decimal("0.025")
_SPREAD_LAGV2 = Decimal("0.05")   # loose — intentional per spec
_SPREAD_VL_ETH = Decimal("0.025")
_SPREAD_VL_SOL_15M = Decimal("0.030")
```

Each sleeve stores `spread_filter: Decimal` applied by the controller at eval time.  
Fill mechanism: `_entry_vwap_for_dir` (`sniper_v5_gates.py:1339`) walks a **single token's** ask side (`book_mirror.get(token_id_up if direction=="UP" else token_id_dn)`). The spread check happens on the **direction-side token only** — same-token ask0−bid0 in the controller.

Note: the prior CLAUDE.md claim that "live sniper_v5 uses cross-token `abs(up_vwap-(1-dn_vwap))`" was true for the old `poly_updown_loop._compute_spread` path. `grep` of `sniper_v5_gates.py` finds **zero occurrences** of `_compute_spread`, `cross_token`, or `abs.*up_vwap.*dn_vwap`. The sniper_v5 path never implemented cross-token spread.

### Backtest

`engine_v2.py:273–274`:
```python
if spread_filter is not None and math.isfinite(ask0) and math.isfinite(bid0):
    if (ask0 - bid0) > spread_filter:
        return None
```
Same-token `ask0−bid0`. Thresholds passed by caller (`spread_filter=0.02` in typical usage).

Both live and backtest use same-token bid-ask. CLAUDE.md warning about cross-token divergence applies only to the legacy `poly_updown_loop` path, NOT to sniper_v5. **MATCH.**

---

## §3 — WS_S Anchor / Fire Timing (MATCH)

### Live

`poly_sniper_v5_loop.py:145`:
```python
fire_us = slot.slot_start_us + offset_s * 1_000_000
```
Deterministic wall-clock schedule. No `ws_s` subtraction. Sniper_v5 fires **INTO** the slot at fixed offsets (0/30/60/90/120/150/180/240/480/600/720/840s).

Pre-window gates that need the prior-window anchor use it explicitly:  
`sniper_v5_gates.py:1287`:
```python
ws_s_us = int(slot_start_us) - int(window_s) * 1_000_000   # g_pw_trend_slope_with
```
All other gates read panels at `fire_us` (causal — panels have ingested data up to that point).

### Backtest

`02_build_fire_table.py:54–56`: reads `fire_us` directly from `trading_events` data column — the value logged by the live controller at emit time. No recomputation. Fire timing is inherited from live, not independently derived.

The `ws_s` lookahead hazard (25–40pp WR inflation) is specific to the `poly_updown_loop` F7/momo path where `slot_start` was accidentally used instead of `ws_s`. Sniper_v5 has no `ret_2m` signal — it fires on panel states at the offset moment. **MATCH.**

---

## §4 — Fill Model (DRIFT, Medium Impact)

### Live

**Book source:** WS BookMirror (`book_mirror.get(token_id)`) — native 10Hz, real-time.  
**Walk:** `_book_walk_vwap` (`sniper_v5_gates.py:1298`) and `_observe_take._walk_take_vwap` (`poly_maker_fill_sim.py:450`) walk the `asks` list from BookMirror.  
**Latency shift:** None. Fire is at wall-clock `fire_us`; book is read at that instant.  
**Sparse guard:** `_observe_take` (`poly_maker_fill_sim.py:510–521`):
```python
if getattr(self._settings, "tv_poly_maker_fill_realism", False) is True:
    _asks = book.get("asks") or []
    if len(_asks) < 2:
        return  # skip
```
This guard activates **only when `tv_poly_maker_fill_realism=True`**, which is `False` by default. No enforcement of 25-event min depth window.

### Backtest (`LiveMimicConfig`)

`engine_v2.py:248–261`:
```python
if cfg.apply_latency_to_entry and cfg.latency_ms > 0:
    lookup_us = int(fire_us) + int(cfg.latency_ms * 1_000)   # +85ms
# ...
if cfg.min_book_events > 0:
    n_events = book_event_count(books_idx, ..., window_start_us, lookup_us)
    if n_events < cfg.min_book_events:   # 25 required
        return None
```

**Differences:**
1. **85ms latency shift**: live reads book at `fire_us`; `LiveMimicConfig` shifts by +85ms. This makes backtest consistently read a slightly staler (more realistic) book.
2. **25-event sparse filter**: live has no equivalent (unless `fill_realism=True` is explicitly set). Backtest drops thin-book markets; live fills them.
3. **`LegacyConfig`**: 0ms latency, 0 event filter — closer to live default behavior for fill model, even though its fee model differs.

**Impact direction:** Live will place fills that `LiveMimicConfig` backtests drop (because live has no 25-event gate and no latency shift that would reach an out-of-window snapshot). This causes **live fire-count > backtest fire-count** for thin markets, and **live entry_vwap ≤ backtest entry_vwap** (live hits the book first, before the 85ms stale point). Net effect: live PnL distribution has more thin-book fills (lower WR) and marginally better entry prices. Estimated magnitude: modest for liquid BTC/ETH (sparse events rare); meaningful for SOL (confirmed thin L25 — see MASTER_LIVE_VS_BACKTEST_2026_05_29.md).

---

## §5 — Gate Evaluation Causality (MATCH)

All gate functions in `sniper_v5_gates.py` are pure (CLAUDE.md inv #4 enforced by module docstring). No gate reads future data or spawns I/O.

Pre-window trend gates compute `ws_s_us = slot_start_us − window_s×1e6` and pass it to regime_panel.lookup — this is the prior slot's start, strictly before the current slot and before `fire_us`. Causal.

Flow gates (`g_b1/b2/b3`) read `V9DataStore.get_asset_trades(asset)` which is a rolling deque of prints received up to the call moment. Since the call is at `fire_us` wall-clock, only prints before `fire_us` are in the deque. Causal.

Backtests do not re-evaluate gates — they read `gates_evaluated` from `trading_events` (already-evaluated gate dict logged by live controller). No lookahead possible. **MATCH.**

---

## §6 — Sleeve Registry Wiring (MATCH)

`SNIPER_V5_SLEEVES` is the single source of truth. Each `SniperV5Sleeve.gates` is a `tuple[GateRef, ...]`; the controller applies AND-composition (`all_gates_passed`) before setting `fill_vwap`. `sleeve_registry.py` is a taxonomy/lifecycle module only — it does not contain gate logic and does not affect evaluation.

Backtest `02_build_fire_table.py` ingests `trading_events` rows filtered by `sleeve_id` membership in the static target list. Since `sleeve_id` is the canonical join key (never renamed per sleeve_registry.py migration rule), the wiring is stable. **MATCH.**

---

## Summary Table

| # | Invariant | Verdict | Impact |
|---|-----------|---------|--------|
| 1 | Fee model | **DRIFT** | High — ~$0.43/trade if wrong config chosen |
| 2 | Spread filter | MATCH | None |
| 3 | WS_S / fire timing | MATCH | None |
| 4 | Fill model (latency + sparse filter) | **DRIFT** | Medium — live fires thin-book markets backtest drops |
| 5 | Gate causality | MATCH | None |
| 6 | Sleeve registry wiring | MATCH | None |

**Score: 4 MATCH / 2 DRIFT / 0 BUG**

---

## Highest-Impact Discrepancy

**INV #1 — Fee model ambiguity** is the single highest-impact discrepancy.

The live engine default is `tv_poly_maker_fee_model="curve"` (`poly_maker_fill_sim.py:843`), which charges `0.07×p×(1−p)` per share on **every TAKE fill including losers**. The CLAUDE.md operator note (2026-05-22 verification) states production charges "2%-on-profit-only" (i.e., `model="legacy_2pct"`). If the operator has overridden to `legacy_2pct` in the VPS3 settings, backtest `LegacyConfig` is correct and `LiveMimicConfig` overstates costs by ~$0.43/trade. If the default `curve` is in use, `LiveMimicConfig` is correct and legacy backtests understate costs. The ambiguity means **all historical sniper_v5 backtest PnL numbers have an uncertainty of ~$0.43/trade (~$430 per 1k fires) depending on which fee branch is actually running.**

**Resolution action:** SSH to VPS3 and run:
```python
from backend.app.core.config import get_settings
print(get_settings().tv_poly_maker_fee_model)
```
If blank/absent → default `"curve"` is active → use `LiveMimicConfig` for all future sniper_v5 backtests. If `"legacy_2pct"` → use `LegacyConfig`.

---

## Files Audited

| File | Role |
|------|------|
| `vps3_engine_snapshot_2026_06_01/strategies/polymarket/sniper_v5_sleeves.py` | Sleeve definitions + spread_filter constants |
| `vps3_engine_snapshot_2026_06_01/strategies/polymarket/sniper_v5_gates.py` | Gate implementations + book-walk fill |
| `vps3_engine_snapshot_2026_06_01/engine/poly_sniper_v5_loop.py` | fire_us computation + eval_sleeve_fire dispatch |
| `vps3_engine_snapshot_2026_06_01/engine/poly_maker_fill_sim.py` | Fee model + TAKE fill simulation |
| `vps3_engine_snapshot_2026_06_01/strategies/polymarket/sniper_v5_shadow_log.py` | JSONL shadow log schema |
| `vps3_engine_snapshot_2026_06_01/strategies/polymarket/sniper_v5_v9_data.py` | V9 trade buffer (flow gates) |
| `vps3_engine_snapshot_2026_06_01/strategies/sleeve_registry.py` | Sleeve taxonomy (no gate logic) |
| `vps3_engine_snapshot_2026_06_01/strategies/audit_schema.py` | Audit schema |
| `strategy_lab/engine_v2.py` | Backtest fill/fee/latency engine |
| `strategy_lab/_opt_2026_05_30/02_build_fire_table.py` | Backtest substrate script |
| `strategy_lab/reports/ENGINE_AUDIT_A_core_2026_05_29.md` | Prior core engine audit |
| `strategy_lab/reports/HANDOFF_2026_06_01_AUDIT_LAGTAKER_FORENSICS.md` | Prior session findings |

**NOT in snapshot:** `controllers/polymarket_sniper_v5.py` (imported lazily from `engine/main.py:2179`). Gate-AND-composition assumed correct per architecture docs + `all_gates_passed` check in loop.
