# VPS3 audit — Phase 34 shadow sleeves implementation

_2026-05-22. SSH-based audit of `/opt/tradingvenue/backend/` against the
spec `TV_AGENT_SHADOW_DEPLOY_GATED_SLEEVES_2026_05_22.md`. All 11 sleeves
are running but **sleeve #2 has a blocking bug** — the Markov regime gate
is never satisfied because the regime label is never computed._

## Audit at a glance

| Area | Status | Detail |
|---|:--:|---|
| Files created per spec §8 | ✅ | `gates.py`, `markov.py`, `polymarket_updown.py` (modified), `poly_updown_loop.py` (modified). YAML config inlined as Python tuple in `main.py` (deviation, see below). |
| `HOD_TOP8_BY_CELL` constant | ⚠️ | Present, all 11 cells. **Uses the OLD list** — derived from at_ts hour, not fire_us hour per spec §2.1. My today's refresh shows ALL 18 cells need update. |
| `hod_passes` / `mtf2_passes` / `markov_passes` | ✅ | All three pure functions match spec semantics exactly. |
| `label_regime_vol_adaptive` | ✅ | Implementation matches spec §2.3 (tertile classifier, warmup=-1, q33/q66). |
| Controller gate block (post-signal, pre-place) | ✅ | Runs in order, emits `gate_*_skip` audit reasons with full `gate_decisions` payload. |
| Aux fields `ret_15m_for_mtf` / `ret_1h_for_mtf` | ✅ | Computed in both t+60 and t+120 builders from binance closes. |
| Aux field `markov_regime_w20_5m_va` | 🔴 | **HARDCODED TO `None`** in both builders. Controller-side "lazy compute" promised in the spec was never written. |
| 11 sleeves registered | ✅ | Confirmed via journal — `n=11` since 08:30 today after operator-directed consolidation. |
| Tests for the gate stack | 🔴 | Test file `test_polymarket_updown_shadow.py` only covers legacy `_audit_shadow_*` functions. No test asserts Markov regime ≠ -1 under any condition. **This is how BUG #1 slipped.** |
| `TV_POLY_SHADOW_GATED_ENABLED` env | ✅ | `true` in `/etc/tv/tradingvenue.env`, verified in the running engine PID's `/proc/$PID/environ`. |
| tv-engine service health | ✅ | Active since 10:28 CEST, last bar_context built at 18:07 UTC. |

## Production fires last 14h (per shadow sleeve)

| # | sleeve_id | signals | gate_hod_skip | gate_markov_skip | order_placed | resolutions |
|--:|---|--:|--:|--:|--:|--:|
| 1 | poly_updown_sol_5m_sniper_hod         | 120 | 9 | – | 7 | 7 |
| **2** | **poly_updown_eth_15m_sniper_hod_m5va** | **39** | **4** | **2** | **0** | **0** |
| 3 | poly_updown_btc_15m_momo_hod          | 39 | 1 | – | 0 | 0 |
| 4 | poly_updown_btc_15m_sniper_hod        | 42 | 2 | – | 4 | 4 |
| 5 | poly_updown_btc_5m_sniper_hod         | 119 | 7 | – | 4 | 4 |
| 6 | poly_updown_btc_5m_momo_v2_hod_mtf    | 116 | 4 | – | 0 | 0 |
| 7 | poly_updown_btc_15m_momo_v2_hod       | 39 | 0 | – | 0 | 0 |
| 8 | poly_updown_sol_5m_momo_v2_hod        | 116 | 3 | – | 4 | 4 |
| 9 | poly_updown_eth_15m_momo_v2_hod       | 39 | 1 | – | 0 | 0 |
| 10 | poly_updown_sol_15m_momo_v2_hod      | 39 | 1 | – | 0 | 0 |
| 11 | poly_updown_eth_5m_sniper_hod        | 120 | 6 | – | 5 | 5 |

`no_signal` (base strategy returned NONE) is the dominant skip reason
for all sleeves — that's normal, only ~5-15% of bars carry an UP/DOWN
signal. **The cells that matter are gate_*_skip and order_placed.**

## 🔴 Bug #1 — Markov regime never computed (blocks sleeve #2)

### Evidence
Live `gate_decisions` payload from sleeve #2 (sniper eth_15m _hod_m5va):

```json
{
  "reason": "gate_markov_skip",
  "gate_decisions": {
    "hod":  {"hour": 14, "pass": true,  "allowed": [0, 6, 7, 9, 13, 14, 19, 22]},
    "m5va": {"pass": false, "regime": -1}
  }
}
```

2 of 2 fires that passed HoD got `regime=-1` and were skipped. **Sleeve
#2 will never fire under the current implementation.**

### Root cause (two compounding bugs)

**1a. Loop builders hardcode the aux field:**

```python
# poly_updown_loop.py: build_bar_context_t_plus_120 (line ~566)
return BarContext(
    ...
    ret_15m_for_mtf=_ret_15m_mtf,     # ✅ computed
    ret_1h_for_mtf=_ret_1h_mtf,       # ✅ computed
    markov_regime_w20_5m_va=None,     # 🔴 hardcoded None
)
```

Same pattern at line ~780 in `build_bar_context_t_plus_60`. The comment
above says:

> Markov regime computed lazily by the controller's gate block (with
> per-(sym, ws_s) cache) — too costly to fetch 14d of 5MIN closes here
> every boundary.

**But the lazy compute was never written.** Grepping the controller
for `_markov_cache`, `_fetch_markov`, `label_regime_vol_adaptive`
returns zero matches in the gate-block path. The controller reads:

```python
_regime_val = getattr(_bctx, "markov_regime_w20_5m_va", None)
_regime = int(_regime_val) if _regime_val is not None else -1
```

So `None → -1 → gate_markov_skip` every time.

**1b. Sniper's bar_close BarContext doesn't run the t+60/t+120 builders:**
Even if 1a were fixed by populating the aux in the builders, sleeve #2
is `sniper`, which fires at `phase="bar_close"`. The bar_close
BarContext is built by a different code path that never sees the aux
init at all — both `ret_15m_for_mtf` and `markov_regime_w20_5m_va` are
`None` by dataclass default.

### Fix

Two options:

**Option A (minimal)**: Add `markov_regime_w20_5m_va` compute in the
controller's gate block. Look up the 5MIN binance closes from
`BinanceMarketDataFeed`, call `label_regime_vol_adaptive`, cache per
`(symbol, ws_s)`. This is what the spec called for.

**Option B (drop the gate per backtest evidence)**: Today's v2
backtest confirms the Markov gate is counterproductive on sniper
sleeves. The handoff finding:

> Drop Markov entirely on sleeve #2. `hod_only` (refreshed): 73.64% WR,
> +$745 sum (n=129). Beats all Markov variants. — `SHADOW_11_SLEEVES_V2_2026_05_22.md`

The simpler fix: change sleeve #2's `gate_stack` from `("hod", "m5va")`
to `("hod",)` in `_SHADOW_GATED_SLEEVES_SPEC` in `engine_main.py` and
restart `tv-engine`. No new code, no Markov compute required.

**Recommended: Option B.** Skip the engineering work for a gate the
backtest already says to drop.

## 🔴 Bug #2 — sniper sleeves can't ever use mtf2 or m5va aux

Same root cause as 1b. Spec §2.2 said:

> For sniper which fires at `slot_start`, anchor at `slot_start`.

But the implementation only wired the aux compute into the t+60 / t+120
builders. The bar_close BarContext doesn't have the MTF closes fetched.
Today no sniper sleeve uses mtf2 (only sleeve #6 uses it, and that's
momo_v2). But if a future sleeve adds `mtf2` to a sniper, it will
silently fail-closed.

**Fix**: either (a) populate the MTF/Markov aux in the bar_close
builder when a shadow sleeve in that cell needs it, or (b) document
that sniper cells can't use mtf2/m5va gates and enforce it at config
load.

## ⚠️ Bug #3 — HoD constant is stale (uses old at_ts-derived hours)

Production has, e.g., `("sniper", "eth_15m"): (0, 6, 7, 9, 13, 14, 19, 22)`
matching the OLD constant. My today's refresh
(`_recompute_hod_top8.py --window-days 28`) produced
`[0, 6, 12, 14, 16, 18, 19, 22]` from fire-time hours per spec §2.1.
All 18 cells need updating.

**Impact (from today's v2 backtest)**:
ensemble PnL **$2,949 → $15,900 (5.4×)** when swapped, 11/11 sleeves
positive (was 7/11). Two sleeves (#5, #10) flip from negative to positive
on the HoD refresh alone.

**Fix**: paste the new constant from
`strategy_lab/markov_filter/_results/hod_refresh/2026_05_22/new_hod_top8.json`
into `backend/app/strategies/polymarket/gates.py::HOD_TOP8_BY_CELL` and
restart `tv-engine`. Per spec §6 the refresh is operator-gated; this is
the first operator-approved refresh.

## 🔴 Bug #4 — no test coverage for the gate stack

`test_polymarket_updown_shadow.py` (385 lines) tests:

- `_audit_shadow_simulated` row shape
- `_audit_shadow_paper_resolved` paired exit row
- `_audit_shadow_counterfactual` row
- sleeve_id canonical form across modes
- pool-error swallowing for shadow audits

**It does not test:**

- That `gate_decisions` payload is written on `gate_*_skip` rows
- That `markov_passes(regime=-1)` returns False (spec §2.3 fail-closed)
- That `m5va` gate ever returns regime != -1 with a real BarContext
- That the integration end-to-end works (signal → gate block → audit)
- That `HOD_TOP8_BY_CELL` is consistent with the spec's table

If even ONE integration test with a populated 5MIN feed had been
written, BUG #1 would have surfaced before deploy.

**Fix**: add three tests:

1. Unit test: `markov_passes("UP", -1) is False` and similar.
2. Unit test: `label_regime_vol_adaptive(closes, returns_14d)` returns
   the right int for a synthetic input.
3. Integration test: spin up a controller with `gate_stack=("hod","m5va")`,
   feed a real BarContext through (with stub `BinanceMarketDataFeed`),
   assert `gate_decisions["m5va"]["regime"] in {0, 1, 2}` (NOT -1).

## ✅ Things that DO work

- 11-sleeve consolidation per operator directive (08:30 today): 33 → 11
  independent controllers. Confirmed via journal `n=11` events.
- Gate block executes in spec-defined order (hod → mtf2 → m5va) with
  per-gate audit writes.
- `decision_label_*` produce the spec-mandated audit strings
  (`skip_hod_hour=14_allowed=[...]`, `skip_markov_disagree_up_regime=1`,
  etc.).
- Boot wiring reads `TV_POLY_SHADOW_GATED_ENABLED` and spawns the
  shadow controllers; master scheduler tracks them as siblings.
- HoD skip rates are within expected ranges (3-10% of UP/DOWN signals
  per sleeve), consistent with the spec's top-8-of-24 selectivity.
- 4 sleeves are confirmed firing and resolving in the last 14h:
  #1, #4, #5, #8, #11.
- Audit row payload includes `gate_stack` and full `gate_decisions`
  per spec §4.

## Recommended actions (in order)

1. **Update `HOD_TOP8_BY_CELL` constant** to the refreshed (fire-time)
   list. Restart `tv-engine`. Expected to make sleeves #5 and #10 begin
   firing in the new hot hours and push WR up across all sleeves.

2. **Change sleeve #2's gate_stack** from `("hod", "m5va")` to
   `("hod",)` in `_SHADOW_GATED_SLEEVES_SPEC`. Per today's backtest
   this is also the better strategy choice (WR 73.6%, +$745 sum vs
   currently-blocked 0). Rename the sleeve_id from
   `poly_updown_eth_15m_sniper_hod_m5va` to
   `poly_updown_eth_15m_sniper_hod` and re-deploy.

3. **Update sleeve #3's gate_stack** to add `m1va` (the v2 backtest
   winner — 90.16% WR, +$20.73/tr). This requires writing the M1V
   compute + caching in the controller (or populating M1V regime in
   the t+120 builder where momo v1 dispatches). Bigger change than #1
   or #2, but the prize is large.

4. **Add the three missing tests** (Bug #4).

5. **Decide on Bug #2 long-term**: either remove `mtf2` from being
   selectable on sniper cells, or write the bar_close MTF aux populator.

## Files audited

Local copies for reference (pulled via scp this session):

- [`migration_2026_05_21/vps3_shadow_audit/gates.py`](migration_2026_05_21/vps3_shadow_audit/gates.py)
- [`migration_2026_05_21/vps3_shadow_audit/markov.py`](migration_2026_05_21/vps3_shadow_audit/markov.py)
- [`migration_2026_05_21/vps3_shadow_audit/polymarket_updown.py`](migration_2026_05_21/vps3_shadow_audit/polymarket_updown.py) (4690 lines)
- [`migration_2026_05_21/vps3_shadow_audit/poly_updown_loop.py`](migration_2026_05_21/vps3_shadow_audit/poly_updown_loop.py) (1218 lines)
- [`migration_2026_05_21/vps3_shadow_audit/engine_main.py`](migration_2026_05_21/vps3_shadow_audit/engine_main.py)
- [`migration_2026_05_21/vps3_shadow_audit/test_polymarket_updown_shadow.py`](migration_2026_05_21/vps3_shadow_audit/test_polymarket_updown_shadow.py)

## End of audit
