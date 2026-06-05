# SILENT FORENSICS — 5 VWAP-continuation poly_updown sleeves (0 fires in 5d18h)

_2026-06-01. READ-ONLY VPS3 forensics. All 5 `vwap_*` shadow sleeves emit a
`poly_updown_signal` event every slot (~1620–1632 each) but `signal=NONE`,
`reason=no_signal` on **100%** of them → 0 placements, 0 resolutions._

## VERDICT: BUG (whole family). Single root cause.

**`_build_signal_aux()` in `backend/app/controllers/polymarket_updown.py` has
NO `vwap_continuation` branch.** It special-cases `momo` (L1330),
`momo_v2` (L1377), `vwap_kelly_ensemble`/`prewindow_*` (L1438), then falls
through to the generic v3/sniper aux builder (L1492+). For a
`vwap_continuation` controller the strategy therefore receives the
**v3/sniper aux dict**, which:

- does NOT set `bar_ctx_phase = "t_plus_{offset}"` (key is absent → `None`)
- does NOT set `vwap_dev_bps`, `markov_regime_w20_1m_va`,
  `rsi_14_for_signal`, or `cross_asset_devs`.

`VwapContinuationStrategy.signal()` (vwap_continuation.py L81–84) gates first
on phase: `if aux.get("bar_ctx_phase") != expected_phase: return "NONE"`.
`None != "t_plus_240"` → **NONE on every slot, before any threshold/gate is
ever evaluated.**

### Why the events still look healthy
The audit payload is built by a SEPARATE code path (`polymarket_updown.py`
L4786 `if self.strategy_mode == "vwap_continuation"`), which reads
`vwap_dev_bps` / `markov_regime_w20_1m_va` / `rsi_14_for_signal` /
`cross_asset_devs` directly from `self._bar_ctx_active` (the real BarContext
built by `build_bar_context_t_plus_n`). So the **logged** aux is correct and
fully populated — but the strategy never saw it. The dispatch wiring
(`_fire_t_plus_n_boundary` → `on_bar_close(..., bar_ctx=ctx)` →
`_bar_ctx_active`) is correct; the only broken link is aux construction.

### Smoking gun (recorded event that mathematically MUST fire)
`poly_updown_btc_5m_vwap_off240_m1v`, latest band+gate-passing slot:
```
vwap_dev_bps = 9.645   (band 5–10 → PASS, dev>0 → UP)
markov_regime_w20_1m_va = 2  (Bull → UP gate PASS; off240 has no other gate)
→ signal MUST = "UP";  recorded: signal=NONE, reason=no_signal
```
Across 374 band-passing off240 slots, 209 also satisfy the M1V gate
(101 UP+Bull, 108 DOWN+Bear). Every one recorded NONE.

### Spec trap that caused it
`TV_AGENT_VWAP_CONTINUATION_FULL_SPEC_2026_05_23.md` §7 states the controller
"just needs to: (1) Accept the new aux fields in the BarContext (no-op — they
flow through). (2) Audit the new aux fields." Step 1 is NOT a no-op — aux must
be explicitly assembled in `_build_signal_aux`. Implementer wired the audit
(step 2) but not the aux passthrough (step 1).

## Per-sleeve table

| sleeve | offset / band (bps) | gates | backtest n/28d | expected fires 5.75d | live fires | band-pass slots (of ~1620) | verdict |
|---|---|---|---|---|---|---|---|
| poly_updown_btc_5m_vwap_off240_m1v | 240 / 5–10 | m1v | 546 | ~112 | 0 | 374 (209 also pass m1v) | **BUG** |
| poly_updown_btc_5m_vwap_off60_f7_cross | 60 / 10–15 | f7 + cross_full | 164 | ~34 | 0 | 75 | **BUG** |
| poly_updown_btc_5m_vwap_off90_cross | 90 / 10–15 | cross_full | 221 | ~45 | 0 | 94 | **BUG** |
| poly_updown_eth_5m_vwap_off210_f7_m1v | 210 / 10–15 | f7 + m1v | 188 | ~39 | 0 | 148 | **BUG** |
| poly_updown_sol_5m_vwap_off60 | 60 / 20–30 | (none) | 64 | ~13 | 0 | 35 | **BUG** |

Band-pass counts (374/75/94/148/35) confirm the BarContext `vwap_dev_bps` is
computed correctly and frequently inside each sleeve's band — the data is fine.
The break is downstream, at aux assembly. Even the no-gate SOL sleeve (35
band-pass slots, only the band to satisfy) fired 0 — proving the block is the
phase gate, not the M1V/F7/cross gates.

## Root cause (one line)
Missing `vwap_continuation` branch in `_build_signal_aux` → `signal()` gets a
v3/sniper aux with no `bar_ctx_phase`/vwap fields → phase gate returns NONE on
100% of slots (audit reads the real BarContext separately, masking the bug).

## Fix (not applied — read-only)
Add a `vwap_continuation` branch to `_build_signal_aux` that returns:
`bar_ctx_phase = self._bar_ctx_active.phase` (i.e. `f"t_plus_{offset}"`),
plus `vwap_dev_bps`, `vwap_15m_anchored`, `markov_regime_w20_1m_va`,
`rsi_14_for_signal`, `cross_asset_devs` from `self._bar_ctx_active`. Mirror the
audit block at L4786. Expect ~13–112 fires/sleeve over a 5.75d shadow window
once wired.

## Evidence files
- Live strategy: `/opt/tradingvenue/backend/app/strategies/polymarket/vwap_continuation.py` (phase gate L81–84)
- Aux bug: `/opt/tradingvenue/backend/app/controllers/polymarket_updown.py` `_build_signal_aux` L1285–1650 (no vwap branch); audit enrich L4786–4810
- Sleeve spec: `/opt/tradingvenue/backend/app/engine/main.py` `_VWAP_CONT_SLEEVES_SPEC` L132–141; spawn L1820–1870
- BarContext builder (correct): `poly_updown_loop.py` `build_bar_context_t_plus_n` L1010–1216; dispatch `_fire_t_plus_n_boundary` L1795–1855
- Backtest n/28d: `strategy_lab/reports/TV_AGENT_VWAP_CONTINUATION_FULL_SPEC_2026_05_23.md` §2 roster (L58–62), §7 spec trap (L463–466)
