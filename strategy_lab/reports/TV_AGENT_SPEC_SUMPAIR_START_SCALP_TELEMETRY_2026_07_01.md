# TV RUST AGENT SPEC — start the sumpair_osc V2 shadow + make the scalp twin measure the real edge
**2026-07-01 · TVRUST (Rust) ONLY · Ireland box · everything PAPER ($0). Python Tradingvenue frozen. Separate from (does not replace) the ladder-v3 residual spec.**

Findings driving this: `IRELAND_RUST_IMPL_AUDIT_2026_07_01.md`. Two decision-critical shadows are broken/idle: (1) `sumpair_osc` is code-complete but never enabled; (2) the scalp twin's telemetry books hold-to-resolution PnL and ignores the entry band on the paper path — its numbers don't measure the exit-scalp edge at all.

---

## PART 1 — Enable the `sumpair_osc` V2 shadow (zero code, env only)
The sleeve is built (`crates/tv-engine/src/loops/sumpair_osc.rs`, spawn-gated in `main.rs:672`). It was just never switched on. Add to `/etc/tv/tvrust.env`:
```
TV_SUMPAIR_OSC_ENABLED=true
TV_SUMPAIR_OSC_LIVE_ENABLED=false     # FIRM — $0 shadow only
TV_SUMPAIR_OSC_COINS=BTC,ETH
TV_SUMPAIR_OSC_TF=5m
TV_SUMPAIR_OSC_THR_BPS=3
TV_SUMPAIR_OSC_EV_GATE=0.55
TV_SUMPAIR_OSC_CLIP_USD=5
TV_SUMPAIR_OSC_MAX_CLIPS_PER_SIDE=1   # FIRM — multi-clip was a corruption artifact
TV_SUMPAIR_OSC_DECISION_STEP_S=5
TV_SUMPAIR_OSC_LOOKBACK_S=5
TV_SUMPAIR_OSC_RESIDUAL_EXIT_S=60
```
Restart, then **verify**: `kind='sumpair_osc'` rows landing in `trading.events` on BTC/ETH 5m windows, with BOTH fill models populated per the handoff telemetry (`filled_usd_level0/ev_level0` AND `filled_usd_walk/ev_walk`, `partial_frac`, per-slug `paircost/locked_pnl/net_pnl_level0/net_pnl_walk`). Full semantics: `TV_AGENT_HANDOFF_IRELAND_V2_SHADOW_2026_06_16.md` §2. If any of those fields are missing from the implementation, add them — they are the entire point of the shadow (it settles the +0.52-level-0 vs −0.70-walk fill-model question).
Guardrails: never flip `LIVE_ENABLED`; never raise MAX_CLIPS; level-0 partial-at-best fills only (no forced $5 walk).

## PART 2 — Fix the scalp-twin measurement (3 defects, source-located)
Target sleeves: the `shadow_scalp_exit_*` family (all 16), `ExitPolicy::ScalpExit`.

### 2.1 Enforce `entry_band` on the PAPER fire path
Today the band `(0.0, 0.55)` is checked only on the live path (`crates/tv-engine/src/controllers/sniper.rs:1364`) — paper fires fill regardless (observed median fill 0.63; 95% out-of-band). Add the same guard to the paper fire path, on the paper `est_vwap` (the `paper_fill_vwap` result): out-of-band ⇒ emit `fire_skip {reason:"entry_band"}` (mirror `kalshi.rs:703` semantics), no fire. Control sleeves (`entry_band=None`) unaffected.

### 2.2 Make the exit measurable — emit the sell result + exit-aware PnL
The `ScalpExit` sell loop is spawned (`sniper.rs:1418`) but its outcome reaches no event, and `resolver.rs` books `slot_resolution_pnl` (hold math) for every sleeve — losses log exactly −stake. Fix:
- **New event `kind='scalp_exit'`**, emitted by the sell loop when it completes (or gives up): `{slug, sleeve_id, direction, entry_vwap, entry_sh, exit_at_us, sell_vwap, sell_filled_sh, sell_source (book|fallback_none), pnl_exit_usd = (sell_vwap − entry_vwap)·sell_filled_sh}`. No resolution fee on a pre-resolution sell; no fee on the sell leg.
- **Exit-aware resolve:** for ScalpExit sleeves, the `resolve` event must report the sleeve's REAL PnL: if the position was sold, `pnl_usd = pnl_exit_usd` (+ hold PnL on any unsold remainder); keep the pure hold number too as `pnl_hold_virtual_usd` for comparison. If the sell never executed (no book), fall back to hold PnL and set `exit_fallback=true`. Losses must stop logging exactly −stake whenever a sell happened.
- If the paper sell loop itself is a stub (never actually computes a sell against the book), implement it: at `fire+60s`, sell at **best bid, partial-at-best** (mirror of the entry's level-0 convention), carry unsold remainder to resolution.

### 2.3 Sync exit knobs to the operator-final config
The port carries pre-2026-06-11 knobs (`sleeves.rs:1401` — tp 0.65, stop 0.10). Production-final is **PURE +60s time sell: TP OFF, STOP OFF** (both hosts, operator decision 2026-06-11). Disable tp/stop for all ScalpExit sleeves; entry config unchanged.

### 2.4 Acceptance (Part 2)
- New fires: 100% of non-control scalp fires have entry `ev < 0.55`; out-of-band attempts appear as `fire_skip entry_band`.
- Every scalp fire is followed by a `scalp_exit` event; `resolve.pnl_usd` reflects the sell (losses no longer cluster at exactly −stake); `pnl_hold_virtual_usd` present.
- tp/stop confirmed off in the running config (log the effective knobs once at spawn).

## PART 3 — Minor telemetry patches (same deploy)
1. `kalshi_scalp_exit_btc_15m_d3_v1`: all resolves log `pnl_usd = NULL` — wire the PnL (same exit-aware rules as 2.2; Kalshi fee model, not Polymarket's).
2. Ladder v2 `pair_gate_bound_sh` never increments — wire the counter (shares whose pairing the `TV_LADDER_PAIR_MAX_SUM` cap prevented).
3. **Endgame feed staleness (investigate, don't blind-change):** active-window book_age is 54–150 ms early/mid window but degrades to 0.9→2.7 s over the last 3 deciles, exactly when price runs to 0/1. Prime suspect: the >15¢ delta reject gate (42.6 k rejects). Check whether the gate rejects legitimate end-of-window moves; if so, make the threshold time-aware (e.g., widen or disable in the final 2 minutes) — this must be fixed before any T−60s logic (v3 residual backstop) can trust the book.

## Do NOT
❌ Flip any `LIVE_ENABLED` / arm capital (watchdog still not deployed — that remains the live prerequisite). ❌ Touch the ladder quoting logic (separate v3 spec owns it). ❌ Touch Python Tradingvenue or storedata. ❌ Change scalp entry signal/sizing — only band enforcement, exit telemetry, knob sync.

## Provenance
Audit + source locations: `IRELAND_RUST_IMPL_AUDIT_2026_07_01.md`. sumpair semantics: `TV_AGENT_HANDOFF_IRELAND_V2_SHADOW_2026_06_16.md`. Scalp final exit config: `project_scalp_exit_config` (PURE +60s, 2026-06-11). Fee rules: winner-only `0.07·p·(1−p)` on held-to-resolution wins only; $0 on sells/losers/maker/redeem.
