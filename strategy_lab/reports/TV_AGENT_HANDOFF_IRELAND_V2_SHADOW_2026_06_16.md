# TV RUST AGENT HAND-OFF — Ireland V2 sum-pair $0 shadow bring-up
**2026-06-16 · TVRUST (Rust) ONLY · goal: get the V2 oscillation-harvest sleeve firing PAPER ($0) on Ireland `:8444` to settle the one open question (the live fill model). No Python Tradingvenue changes.**

This supersedes the V2 parts of `TV_AGENT_SPEC_TVRUST_SUMPAIR_OSC_SLEEVE_2026_06_16.md` with the corrections found after the L25 de-corruption + depth re-checks. Implement in this order.

---

## 0. Why a shadow (the one thing that's unresolved)
V2 (buy each leg on its own Binance→Poly lag-dip, hold the matched pair, scalp-exit the residual) is **fill-model-fragile** and offline can't settle it:
- **Level-0 partial-at-best fill** (take only what's resting at the best ask, up to $5; partial if thin — the model the validated +0.52/slug used, and the model the **live, profitable** deployed scalp uses): **+0.52/slug**.
- **Forced full-$5 book-walk** (sweep deeper levels to fill the whole clip at thin lag-dip moments): **−0.70/slug** (verified on corrected depth).

The shadow's job is to measure the **real** fill + PnL at $0 risk. **So the sleeve must record BOTH fills and let the data decide.**

---

## STEP 1 — Parse-fix (execution-critical, do FIRST)
Full spec: `TV_AGENT_SPEC_TVRUST_PRICE_CHANGE_PARSE_FIX_2026_06_16.md`. Summary: TVRUST's `poly_book.rs` parses `price_change` with key `changes` + a message-level `asset_id`, but the live frame is **`price_changes[]` with a per-change `asset_id`** → it currently produces ~0 deltas → the live book only updates on ~1 Hz full snapshots → **stale**. Fix: read `price_changes` (fall back to `changes`), route/enrich each change by its own `asset_id`, group→one `PriceChange` event per asset_id. **Without this, the shadow fills against a stale book and the numbers are meaningless.** Verify the book goes delta-fresh before Step 3.

---

## STEP 2 — Build the V2 sleeve (`sumpair_osc.rs`) — CORRECTED
A stateful per-window accumulator (twin of `poly_ladder.rs`, lighter), spawned by env flag. Reuses the deployed scalp's machinery (signal, fill, +60s exit, chainlink settle).

### 2.1 Strategy (exact)
- **Markets:** BTC/ETH **5m** only. (SOL dropped — straddles 0. 15m straddles 0.)
- **Signal (reuse the deployed scalp lag signal, causal):** every `DECISION_STEP_S=5` from slot_start+5 to slot_end−65, compute Binance **bar-END** return over `LOOKBACK_S=5` (`asof` with `ends=bar_start+1e6`; **never bar-start = look-ahead**). If `|ret|·1e4 ≥ THR_BPS=3`: ret>0 → buy **Up**, ret<0 → buy **Down**.
- **Entry — 🔴 FILL MODEL (the correction):** fill **level-0 partial-at-best**, EXACTLY like the deployed `shadow_scalp_exit_btc_5m_d3_v1` (the Python `entry_fill` on `ask0/asksz0`): take up to `CLIP_USD=$5` from the **best ask only** at decision+**85 ms**; if best-ask size < $5, fill **PARTIAL** (only what's there) — **do NOT sweep deeper levels to force a full $5.** Require entry vwap `ev < 0.55`.
  - **⚠️ Do NOT use a full-ladder book-walk** (`paper_fill_vwap`-style sweep). A forced $5 walk is the −0.70 regime. The validated edge + the live scalp both fill level-0-partial.
- **Accumulate** both sides across the window, **`MAX_CLIPS_PER_SIDE = 1` (FIRM)**. The multi-clip "upside" was a corruption artifact (collapsed to ~0 on corrected depth) — **do not raise above 1** without a fresh validated study.
- **Settlement:** matched pair `min(sh_up,sh_dn)` HELD to chainlink (winner redeems $1). **Residual** (heavier side − matched) **scalp-EXIT at +60 s** on the book (`bp[:,0]`, like the deployed scalp) — do NOT hold the residual.
- **Fee:** winner-only `0.07·p·(1−p)` on the winning leg, $0 on loser/redeem. Never fee maker/redeem legs.

### 2.2 Code surfaces
- NEW `crates/tv-engine/src/loops/sumpair_osc.rs` (~200 lines): `LadderConfig`-style `from_env`, the 5 s decision loop, per-window `sh_up/sh_dn/vwap` accumulators, reset on slug change. Reuse: the scalp Binance bar-END signal (`Vwap15mStore::close_asof`), the level-0 entry fill (the scalp's, NOT the ladder walk), the +60 s exit, chainlink settle, `insert_event`.
- `loops/mod.rs` + `main.rs` spawn block gated by `TV_SUMPAIR_OSC_ENABLED`, reusing the live `book_state`/`gamma`/`sink` (own isolated reads; never touch the sniper hot path).

### 2.3 Config
```
TV_SUMPAIR_OSC_ENABLED=true
TV_SUMPAIR_OSC_LIVE_ENABLED=false     # false = $0 shadow — START HERE, do not flip without the gate below
TV_SUMPAIR_OSC_COINS=BTC,ETH
TV_SUMPAIR_OSC_TF=5m
TV_SUMPAIR_OSC_THR_BPS=3
TV_SUMPAIR_OSC_EV_GATE=0.55
TV_SUMPAIR_OSC_CLIP_USD=5
TV_SUMPAIR_OSC_MAX_CLIPS_PER_SIDE=1   # FIRM. multi-clip upside was a corruption artifact.
TV_SUMPAIR_OSC_DECISION_STEP_S=5
TV_SUMPAIR_OSC_LOOKBACK_S=5
TV_SUMPAIR_OSC_RESIDUAL_EXIT_S=60
```

### 2.4 Telemetry — log BOTH fill models (this is how the shadow settles the question)
Per fire, `insert_event(kind='sumpair_osc', ...)`:
`{slug, coin, side, binance_ret_at_fire, best_ask, best_ask_size, intended_usd=5,
  filled_usd_level0, ev_level0,            // partial-at-best (the +0.52 model)
  filled_usd_walk,   ev_walk,              // would-be full-$5 walk (the −0.70 model) — record for comparison, do NOT trade it
  partial_frac = filled_usd_level0/5 }`
Per slug at window end: `{nclip_up, nclip_dn, matched_sh, paircost, locked_pnl, residual_sh, residual_exit_pnl, residual_hold_pnl(virtual), net_pnl_level0, net_pnl_walk, both_filled}`.
**`partial_frac`, `paircost`, and `net_pnl_level0` vs `net_pnl_walk` are THE numbers** — they reveal whether the cheap level-0 fills are real or whether you'd have to walk (and lose).

---

## STEP 3 — Deploy the $0 shadow (+ watchdog)
- **🔴 Deploy `tv-watchdog` first.** It's built (R7) but NOT on the Ireland box. No live arm of anything until the kill-path is running (independent creds, read-only pool, consumes `trading.events(kind='kill_switch_requested')`).
- Build + deploy TVRUST with Step 1 + Step 2; set `TV_SUMPAIR_OSC_ENABLED=true`, `TV_SUMPAIR_OSC_LIVE_ENABLED=false`. Verify `sumpair_osc` rows land in `tradingvenue_rust.trading.events` on BTC/ETH 5m windows.
- Flag unset / live false ⇒ the 5 live sleeves stay byte-identical; zero capital risk.

---

## Promotion gates (pre-registered) + honest caveat
- **Caveat:** offline says fill-fragile (+0.52 partial / −0.70 walk). **Treat the shadow as a confirm/kill test, not a greenlight.** If `partial_frac` is low (level-0 too thin → you'd have to walk) and `net_pnl_walk` is negative, V2 is dead — file it.
- **Stage 1 ($1 live)** only after the shadow shows, over **≥200 fires / ≥4 wk on the live wallet**: paircost median ≤ 0.98 AND matched-pair `locked_pnl` CI>0 AND the realistic-fill net (whichever model the live fills match) > 0 AND watchdog up. Else file dead.

## Do NOT
- ❌ Book-walk / sweep a forced $5 (use level-0 partial-at-best). ❌ Raise MAX_CLIPS above 1. ❌ Flip `LIVE_ENABLED` or arm capital before the gate + watchdog. ❌ Touch Python Tradingvenue. ❌ Use the deep L25 ladder for fills (the sleeve is level-0 only; deep levels were corrupted — irrelevant here since we don't walk).

## Provenance
Validation: `SUMPAIR_SIGNAL_GATED_2026_06_13.md`. Fill-model finding + corrections: `DEPTH_RECHECK_2026_06_16.md` §0, `project_sumpair_arb_dead` memory. Parse-fix: `TV_AGENT_SPEC_TVRUST_PRICE_CHANGE_PARSE_FIX_2026_06_16.md`. L25 corruption context: `L25_LEVEL_CORRUPTION_2026_06_16.md`.
