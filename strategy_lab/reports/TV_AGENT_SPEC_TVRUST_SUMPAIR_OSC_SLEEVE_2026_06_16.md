# TV AGENT SPEC — TVRUST `sumpair_osc` sleeve (signal-gated oscillation-harvest, Rust client)
**2026-06-16 · for the TVRUST engine agent · Rust ONLY · $0 shadow first.**

> **Scope:** implement in the **Rust client (TVRUST)**. **Do NOT touch Python Tradingvenue** (port later for parity).
> This is the Rust port of the validated `TV_AGENT_SPEC_SUMPAIR_OSC_HARVEST_2026_06_14.md` (which predates the
> all-Rust decision). Economics/validation live in that doc + `SUMPAIR_V2_DEPTH_REALISM_2026_06_14.md`; this
> spec is the TVRUST wiring. It is **our own taker-lag edge — independent of the b945 maker/delta thread** —
> so it needs **no new data** and can fire today while the delta tape accrues.

## 1. What it is (the proven edge)
Buy BOTH legs of a crypto Up/Down market, each on its OWN Binance→Poly lag-dip, so the time-averaged pair cost < $1; hold the matched pair to resolution; scalp-exit the unpaired residual at +60s. Validated offline:
- pair-hold + **scalp-residual** is the deployable form (NOT hold-residual): median −$5→−$0.35, win 38%→44%, **mean +0.40/slug @ 1 clip (CI [+0.26,+0.55]), ~+1.8 multi-clip**; markout confirms genuine lag.
- **BTC/ETH 5m only** (SOL straddles 0 — drop). Survives causality / 85 ms latency / chainlink settle.

## 2. Reuse the deployed scalp's machinery (it all exists in TVRUST)
The live sleeve `shadow_scalp_exit_btc_5m_d3_v1` already has every primitive:
| need | reuse |
|---|---|
| Binance **bar-END** lag signal (5s lookback, causal) | the scalp's signal via `Vwap15mStore::close_asof` (1s feed; STATUS: "1s feeds the scalp oracle-lag") — **bar-END, never bar-start** |
| book-walk **$5 clip** entry fill (vwap) | `paper_fill_vwap(...)` (`tv-engine/src/loops/sniper_v5.rs:42`) |
| **+60s** sell exit | the scalp's time-exit path (TP/stop OFF) |
| chainlink settlement | the poly resolver (`resolve` events → outcome/won/pnl_usd) |
| event logging | `tv_persistence::insert_event(kind, sleeve_id, data)` |

## 3. What's NEW (the only added machinery): a stateful per-window accumulator
Like the ladder, this is NOT a single-shot `SniperV5Sleeve` — it accumulates across the window. Add a light loop:
- **`crates/tv-engine/src/loops/sumpair_osc.rs`** (NEW, ~200 lines), spawned by env flag (twin of the `poly_ladder` spawn). Per active BTC/ETH **5m** window:
  - decision tick every `DECISION_STEP_S` (5s) from slot_start+5s to slot_end−65s.
  - compute Binance bar-END return over `LOOKBACK_S` (5s); if `|ret|·1e4 ≥ THR_BPS`(3): the side Binance moved toward is lag-cheap (ret>0→Up, ret<0→Down).
  - book-walk a `$CLIP_USD`(5) clip on that side's ask at decision+**85 ms**; require entry vwap `< EV_GATE`(0.55); fill ≤ real depth.
  - accumulate per side up to `MAX_CLIPS_PER_SIDE` (**1** — the validated floor; raise later only with evidence).
  - track `sh_up, sh_dn, vwap_up, vwap_dn`; reset on slug change (own `current_slug`, like the ladder).
  - at slot end: **matched pair = min(sh_up, sh_dn) HELD to chainlink** (winner redeems $1); **residual (heavier side − matched) = SCALP-EXIT at +`RESIDUAL_EXIT_S`(60)** on the book (do NOT hold residual — it's a −$1.19/slug drag).
- Fee: winner-only `0.07·p·(1−p)` on the winning leg, $0 on loser, fee-free redeem. **Never fee the maker/redeem legs.**

## 4. Config (`tv-config`, `TV_*` env)
```
TV_SUMPAIR_OSC_ENABLED=true
TV_SUMPAIR_OSC_LIVE_ENABLED=false      # false = $0 shadow (paper) — START HERE
TV_SUMPAIR_OSC_COINS=BTC,ETH           # SOL dropped (straddles 0)
TV_SUMPAIR_OSC_TF=5m
TV_SUMPAIR_OSC_THR_BPS=3
TV_SUMPAIR_OSC_EV_GATE=0.55
TV_SUMPAIR_OSC_CLIP_USD=5
TV_SUMPAIR_OSC_MAX_CLIPS_PER_SIDE=1
TV_SUMPAIR_OSC_DECISION_STEP_S=5
TV_SUMPAIR_OSC_LOOKBACK_S=5
TV_SUMPAIR_OSC_RESIDUAL_EXIT_S=60
```
Flag unset ⇒ never spawned (5 live sleeves byte-identical). Like the ladder, run its OWN isolated book/feed reads — never touch the sniper's shared hot path.

## 5. Telemetry (kind `sumpair_osc`, reuse `insert_event`)
Per fired slug: `{slug, coin, tf, nclip_up, nclip_dn, ev_up, ev_dn, matched_sh, paircost(=ev_up+ev_dn), locked_pnl, residual_sh, residual_exit_pnl, residual_hold_pnl(virtual), net_pnl, both_filled, binance_ret_at_fire}`. **`paircost (<1?)` and matched-pair `locked_pnl` are THE numbers.** Also log the virtual hold-residual alongside the scalp-exit residual so we re-confirm the exit choice live.

## 6. Guardrails (do NOT repeat past bugs)
- **Bar-END signal only** (bar-start = look-ahead; killed prior scalp drivers).
- **85 ms latency** on every fill. **Real depth** (no size==0→infinite).
- **Chainlink settlement** on all gated slugs (never engine-redeem = censoring trap).
- **5m only; BTC/ETH only.** Hold matched pair only; **scalp-exit residual** (don't hold).
- Judge by the **live wallet CI**, not the backtest (the OOS window is burned).

## 7. Staged rollout / DoD
- **Stage 0 — $0 shadow:** real lag signal + real book-walk paper fills, both sides, accumulate, settle to chainlink; `sumpair_osc` rows land in `tradingvenue_rust.trading.events`; paircost + locked_pnl visible. **DoD:** loop runs on `:8444`, ≥1 BTC/ETH 5m window/decision-tick firing, telemetry flowing.
- **Stage 1 — $1 live** only after ≥200 fires with live paircost median <1 AND matched-pair locked PnL CI>0 on the live wallet. Watchdog must be deployed first.
- **Promotion gate (pre-registered):** live paircost median ≤0.98 AND matched-pair net/slug CI>0 AND residual-scalp ≥ residual-hold AND ≥200 fires/≥4wk. Else file dead.

## 8. Provenance
Economics + validation: `SUMPAIR_SIGNAL_GATED_2026_06_13.md`, `SUMPAIR_V2_DEPTH_REALISM_2026_06_14.md`, `TV_AGENT_SPEC_SUMPAIR_OSC_HARVEST_2026_06_14.md`. Reuse surfaces: `tv-engine/src/loops/{sniper_v5.rs,poly_ladder.rs}`, `tv-features` (Vwap15mStore), `tv-persistence` (insert_event).
