# TV Fix Spec — `g_a2_hl_short_cascade` window 300s → 60s (+ physics-combo negative result)

**Owner:** TV agent (VPS3) · **Priority:** 🟡 medium (fix is real but edge is modest; feed repair is the blocker)
**Source validation:** `EDGE_VALIDATION_TIER1_2026_06_01.md` (Stage 1/5) + `_ga2_anchor_check_2026_06_01.py`
**Gate:** `vps3_engine_snapshot_2026_06_01/strategies/polymarket/sniper_v5_gates.py:2199` `g_a2_hl_short_cascade`

---

## TL;DR
The deployed `g_a2` reads a **300s** HL short-liq cascade window ending at `fire_us`, `thresh_usd=100_000`.
The cascade impulse **decays in ~60s** — the 300s window averages over the recovery and dilutes the
signal. Across every anchor tested, **60s ≥ 300s**. Change `window_s` default 300 → **60**. BUT:
1. The absolute directional edge is **modest** (~55–60% WR), not the docstring's 95.7%.
2. The docstring's **"95.7% WR (n=140, t=7.5)" is the priced-move trap** — it anchors at `fire_us`
   deep in the slot with a $100k threshold, which selects decisive moves the market already priced
   (same artifact that made Stage-3 VPIN 87% WR = **−$0.62/trade** in Stage 4). **WR is a trap-prone
   metric for this gate — validate the change on realized PnL, not WR.**
3. The HL feed is **stale (frozen at May 27)** and the bybit/bitget CEX-liq collectors are **empty**
   — the gate is starved. **Repair the feed first** (`HANDOFF_HURST_HLCASCADE_FIX_2026_06_01.md`),
   otherwise the window change is academic.

---

## Evidence — window × anchor sweep (BTC+ETH, Apr24→May27, directional WR vs base 49.86%)

Cascade = HL `Close Short`+`Open Long`, `method=market`, notional `>T` in `[anchor−W, anchor]` → predict UP.

| anchor (rel slot_start) | W | T | n | WR | lift | p |
|---|--:|--:|--:|--:|--:|--:|
| slot_start (pure leading) | **60** | 50k | 101 | **55.4%** | +5.6 | 0.13 |
| slot_start | 120 | 50k | 172 | 50.0% | +0.1 | 0.49 |
| slot_start | **300** | 50k | 422 | 52.4% | +2.5 | 0.15 |
| slot_start+60 | **60** | 100k | 113 | **60.2%** | +10.3 | **0.014** |
| slot_start+60 | 120 | 100k | 177 | 57.1% | +7.2 | 0.028 |
| slot_start+60 | **300** | 100k | 330 | 54.8% | +5.0 | 0.035 |

- **60s ≥ 300s at every anchor** → window fix supported.
- WR climbs as the read-window moves *into* the slug (slot_start → +60) — that is priced-move creep,
  not extra alpha (entry vwap rises with it).

**Fill test (Stage 5, slot_start+5s entry, real L25 + 0.07 fee):** casc60>10k → WR 54.5%, **vwap 0.512**
(NOT pre-moved — the one good property), **+$1.16/$25 but t=0.47**. Real sign, not significant.

---

## The fix (drop-in)

`sniper_v5_gates.py` `g_a2_hl_short_cascade` signature default:
```python
-    window_s: int | str = 300,
+    window_s: int | str = 60,     # impulse decays in ~60s; 300s dilutes (60s>=300s every anchor)
```
Keep `thresh_usd=100_000` for BTC (that's where the 60s signal is significant at the +60 anchor).
If `window_s`/`thresh_usd` are set per-sleeve in `sniper_v5_sleeves.py` / `sniper_v5_v9_data.py`,
change them there instead (and for the ETH/SOL provisional thresholds too: scale window, keep thresh).

**Do NOT just flip it in prod.** Ship as a **shadow A/B**:
- Variant A (control): current `window_s=300`.
- Variant B (test): `window_s=60`.
- Run both on the A2 sleeves, ≥2–4 weeks, **score on realized `poly_updown_resolution.pnl_usd`** (and
  entry vwap), not WR. Promote B only if its **per-fire PnL** beats A with adequate n.

---

## Prerequisites (blockers)
1. **Repair the HL liquidation feed** — frozen at 2026-05-27; the `hl_short_proxy` is stale/None →
   gate silently returns False. See `HANDOFF_HURST_HLCASCADE_FIX_2026_06_01.md` (bybit/bitget liq
   collectors empty, same root cause). Without a live feed the window change does nothing.
2. Confirm the production fee model on these contracts (legacy 2%-on-profit vs 0.07-curve) before any
   sizing — does not flip the sign, does change EV math.

## Acceptance criteria
- [ ] HL/CEX liq feed live (<5 min stale) for BTC (ETH/SOL if enabled).
- [ ] Shadow A/B deployed; B uses 60s window.
- [ ] After ≥300 A2 fires/variant: B per-fire **PnL** ≥ A (and ≥0), with entry vwap logged.
- [ ] If B fails on PnL despite higher WR → it was the priced-move trap; keep A or retire the gate.

---

## Physics-combo (tested, **negative** — don't wire physics into g_a2)
Per the user request, tested whether the physics continuation pocket (`dist_abs≥40 & vwap<0.95 &
spread≤0.02`, `PHYSICS_SIGNAL_SYNTHESIS_2026_06_01.md`, +$0.57/fire t=1.75) is **sharpened** by HL
liq-cascade confirmation (forced flow agreeing with the continuation side). Result (`physics_x_liqcascade_2026_06_01.py`):
- **Sparsity:** 795/847 pocket fires have **zero** HL liq in the trailing window → no overlap to gate on.
- In the tiny overlap the sign is **inverted/noisy** (+confirmed +$0.25 t=0.16 *worse* than base; −contradicted +$1.02 but n=23).
- **Does not fix the bad weeks** (wk19–20 reversals have 0–1 confirmed fires; wk21–22 have 0).
→ Physics and g_a2 are **independent thin edges that don't combine**. Keep separate; both remain
sub-significant and need more OOS days. Physics pocket's path to significance = passive OOS
accumulation (the `physics_ticks` collector in `HANDOFF_PHYSICS_TICK_COLLECTOR_2026_06_01.md`), not g_a2.

## Artifacts
- `strategy_lab/directional/_ga2_anchor_check_2026_06_01.py` (window×anchor sweep)
- `strategy_lab/directional/edge_val_stage5_a1fill_2026_06_01.py` + `_results/...parquet` (fill test)
- `strategy_lab/physics/physics_x_liqcascade_2026_06_01.py` + `_results/physics_x_liqcascade_2026_06_01.csv`
## END
