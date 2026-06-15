# TV AGENT SPEC — Scalp sleeves never fire LIVE on Ireland (1s vwap_store stale on live-only box)

> ## ✅ RESOLVED / RETRACTED 2026-06-09 — DO NOT ACT ON THIS SPEC.
> Live ground truth on Ireland 2026-06-09: `g_oracle_lag_with` passes throughout the day and the live scalp
> trades — `shadow_scalp_exit_btc_5m_d3_v1_LIVE` placed **8 live fills / 24h** (15m: 4), with normal post-gate
> `entry_vwap_out_of_band` skips. The 1s `vwap_store` is **live and advancing**; the scalp fires live.
> The 100%-`g_oracle_lag=False` state captured on 06-08 was transient/since-resolved (or a mis-diagnosis).
> **No 1s-store fix is needed.** Kept for history only.

---


> **UPDATE 2026-06-08 (deep debug pass — root cause PROVEN, status: NOT FIXED).**
> Engine still on the 14:23 UTC boot; both scalp sleeves remain 0 placements / 100% `g_oracle_lag=False`.
>
> **Ground-truth proof it's a bug, not low base rate:** fetched authoritative Binance 1s klines and
> computed the *true* intra-window 5s return `(px@slot+5 / px@slot − 1)·1e4` at Ireland's **576 actual
> scalp eval slots** (last 2 days). The move was in the gate's **[3,12] bps band 17.5% (101/576)** of
> the time, median |bps| 0.96. Ireland's gate returned **False on 100%** → the gate's 1s price input is
> dead. (`strategy_lab/wallet_hunt/_groundtruth_oraclelag.py`.)
>
> **Ruled OUT by code+runtime analysis:**
> - *Gate logic* — `g_oracle_lag_with` correct; passes ~11% gate-rate on VPS3 (same code).
> - *`close_at` / `push`* — read both deploys; `close_at` reverse-scan returns `entry[1]`=close, **identical** logic on both boxes (Ireland 5-tuple vs VPS3 6-tuple push, but close index unchanged).
> - *Module-global mismatch* — `main.py set_feed_instance` and controller `get_feed_instance` both bind the **same** `backend.app.data.bars._FEED_INSTANCE`; feed IS bound, not None.
> - *Binance delivery* — direct WS probe **from Ireland** (`_ws_1s_probe.py`) received 6 closed `@kline_1s` bars in seconds (BTC/ETH/SOL). The box CAN get 1s.
> - *Config* — `_vwap_1s=True` (sniper_v5 enabled); seed ran (`panel_seed_1s_complete vwap_store:true handlers_1s:4`); URL subscribes `@kline_1s`; feed connected, 0 reconnects, 1m bars flow (off600/eth V10 fire live).
>
> **PROVEN root cause:** the engine's long-lived feed connection is **not advancing `vwap_store` with live 1s bars** — the store is frozen at the boot REST seed (~14:24). `close_at(slot_start)` and `close_at(slot_start+5s)` therefore return the *same stale bar* → `price_delta_bps ≈ 0` → never in [3,12] → gate False on 100%. With `vwap_store.max_bars=960` (16 min) a live store could not produce 0% over 1396 evals; only a frozen store does. The `DATA_STALENESS_S=120` watchdog **cannot** catch this because 1m bars keep `_mark_ws_msg()` alive (it's a 1s-only stall).
>
> **Why VPS3 works:** it's the binance-collector host; its connection genuinely streams 1s → live store → ~11% gate-pass.
>
> **Fix (revised, see §3):** the 1s sub-stream is subscribed but not delivered on the engine's long-lived connection. Add a **1s-specific** data-staleness watchdog (independent of 1m), and/or re-assert the `@kline_1s` subscription / split 1s onto its own WS connection so a silent 1s-only stall forces reconnect. Confirm with the §4 instrumentation (store newest-bar age + `ft_bps`).

**Date:** 2026-06-08
**Box:** Ireland (live-only) — `tv-engine.service`
**Severity:** P1 — both live scalp sleeves are silent on Ireland (0 live fires); the edge we're trying to forward-validate is not accruing live fires.
**Class:** same family as the already-shipped `TV_FIX_LIVEONLY_RTDS_2026_06_08` + `TV_FIX_1S_STREAM_DECOUPLE_2026_06_08` — a live-only-box feed-wiring gap. This is the next instance.

---

## 1. Symptom (measured)

Sleeves: `shadow_scalp_exit_btc_15m_d3_v1`, `shadow_scalp_exit_btc_5m_d3_v1` (both LIVE-allowlisted on Ireland, `TV_POLY_SNIPER_V5_LIVE_ALLOWLIST`, $1 notional).

`trading.events` (kind `poly_updown_signal`), last 2 days, Ireland:

| sleeve | sleeve_fire_eval | sleeve_fire_placed |
|---|---|---|
| `shadow_scalp_exit_btc_15m_d3_v1` | 222 | **0** |
| `shadow_scalp_exit_btc_5m_d3_v1` | 1174 | **0** |

**100%** of Ireland evals skip with `skip_reason = "g_oracle_lag_with(3.0,12.0)=False"`.

Same sleeve on VPS3 (shadow box), same 3-day window: gate passes ~3% → **18 `sleeve_fire_placed`**. So the sleeve/gate/params are fine — the **gate input differs by box**.

Live execution on Ireland is healthy: the 1-minute-panel live sleeve `poly_sniper_v5_btc_15m_ema50_ema800_off600_down` places real fills (`poly_sniper_v5.live_fill` logged 14:25/14:40 UTC). **Only the sleeves that depend on the 1-second return store are dead.**

---

## 2. Root cause

`g_oracle_lag_with` (`backend/app/strategies/polymarket/sniper_v5_gates.py:805`) passes iff `|oracle_lag.price_delta_bps| ∈ [lo,hi]` and `sign(bps)` matches direction.

Despite the name, `price_delta_bps` is the **intra-window binance return**, not a chainlink basis (per `TV_AGENT_FIX_LAGV2_SIGNAL_2026_06_01`). It is built in `backend/app/controllers/polymarket_sniper_v5.py`:

```
_binance_lag_snapshot(asset, slot_start_us, fire_us):
    px_open = _binance_close_at(asset, slot_start_us)   # 1s close at slot open
    px_fire = _binance_close_at(asset, fire_us)          # 1s close at slot_start+5s
    -> price_delta_bps = (px_fire/px_open - 1) * 1e4

_binance_close_at(asset, ts_us):
    feed = get_feed_instance(); store = feed.vwap_store
    return store.close_at(asset, ts_us)   # None if store unbound / no bar <= ts
```

The gate therefore reads the engine's in-memory **binance 1-second `vwap_store`**.

**On Ireland the 1s `vwap_store` is seeded but not advancing.** Boot log shows `binance_feed.panel_seed_1s_complete {"vwap_store": true, ...}` (120 min seed) but the **live 1s bars are not reaching the store the gate reads**. Consequence: for a fire at `slot_start+5s`, `close_at(slot_start)` and `close_at(fire)` resolve to the **same stale bar** → `price_delta_bps ≈ 0` → never in `[3,12]` → gate False on **every** eval.

**Why we're confident it's "store stale", not "low base rate":**
- Ireland pass rate is **exactly 0%** of 222+1174 evals, vs VPS3's ~3%. A live store with a real 5s return would land in band occasionally.
- Discriminator: every Ireland live sleeve that **does** fire uses **1-minute** panels (ema50/ema800); every sleeve that depends on the **1-second** store is dead. The 1m feed is healthy; the 1s store is effectively frozen for the gate.

Config is **not** the blocker: `main.py:~1428` sets `_vwap_1s = VWAP_CONT_ENABLED or SNIPER_V5_ENABLED` → **True** on Ireland (`TV_POLY_SNIPER_V5_ENABLED=true`), and `BinanceMarketDataFeed(enable_1s_stream=True)` is constructed + `binance_feed.ready_bound` logs. So the 1s stream is *requested*; the live 1s bars just aren't advancing `vwap_store` on the **live-only spawn branch** (`main.py:~2900-3010`, the `_run_only_kill` / `live_only_spawn` path).

---

## 3. Fix

**Goal:** on the live-only box, the binance 1s WS stream must continuously advance the `vwap_store` that `_binance_close_at` reads, exactly as it does on the full (`else`) branch / VPS3.

1. **Audit the live-only spawn branch** (`backend/app/engine/main.py`, the `if _run_ids:` / `poly_sniper_v5.live_only_spawn` block) and compare against the full `else` branch for binance-feed wiring. The full branch registers the 1s handlers and keeps the 1s WS stream pumping into `vwap_store`; verify the live-only branch does the **same** for:
   - the live 1s WS subscription actually being **started** (not just `enable_1s_stream=True` on construction),
   - `set_feed_instance()` pointing `get_feed_instance().vwap_store` at the **same** store the live 1s handler appends to,
   - the 1s handler loop not being skipped/short-circuited when `PANELS_ONLY`/live-only is set.
2. If the live-only branch seeds the store but never attaches the live-append path, wire it (mirror `TV_FIX_1S_STREAM_DECOUPLE_2026_06_08`).
3. Confirm the binance **1s** WS subscription (not just the 1m kline stream) is connected on Ireland — the boot `binance_feed.ws_connected` does not distinguish 1s vs 1m. If the 1s sub is rate-limited/geoblocked/silent, fall back to deriving 1s closes from the RTDS `crypto_prices` WS that's already connected on Ireland (`polymarket_rtds`, `_binance_prices`), or from the 1m stream interpolation is NOT acceptable (need true sub-bar moves).

---

## 4. Confirming instrumentation (do this first — 1 line, low risk)

`ft_bps` is already computed in `polymarket_sniper_v5.py` (~line 735) for any sleeve carrying an oracle-lag gate, but it is **only persisted for the fast_taker family** (`oracle_lag_bps`) and **dropped on the SCALP_EXIT eval-skip path**. Add it to the scalp `sleeve_fire_eval` event `data`:

- Persist `ft_bps` (and `px_open`, `px_fire`, and `vwap_store_newest_bar_age_s`) onto the `sleeve_fire_eval` payload for SCALP_EXIT sleeves.

**Expected reads:**
- If `ft_bps ≈ 0` on ~all Ireland evals AND `vwap_store_newest_bar_age_s` grows unbounded → **store stale confirmed** → §3 fix.
- If `ft_bps` is real and varied but rarely in `[3,12]` → genuinely low base rate (then it's not a bug, just thin live cadence — revisit the gate band for live).

---

## 5. Acceptance criteria

1. On Ireland, `vwap_store_newest_bar_age_s` for BTC stays `< 3 s` continuously (store is live).
2. On Ireland, `ft_bps` on scalp evals is non-zero and varies fire-to-fire (matches VPS3 distribution).
3. `shadow_scalp_exit_btc_5m_d3_v1` + `shadow_scalp_exit_btc_15m_d3_v1` produce `sleeve_fire_placed` (live $1) on Ireland at a rate comparable to VPS3's gate-pass rate (~few % of evals), with **no regression** to the 1m-panel live sleeves (`off600`, eth V10) or the Kalshi EMA gates.
4. No increase in `binance_feed` reconnects / WS errors.

---

## 6. Scope / guardrails

- Live-only box only; do not change VPS3 (shadow) behaviour.
- Do not widen the `[3,12]` band or touch gate logic — the gate is correct (proven on VPS3). The fix is **feed wiring**, not signal tuning.
- $1 live notional unchanged. The scalp exit policy (TP/stop vs +60) is a separate open item — out of scope here.

---

## 7. Reference (exact locations)

- Gate: `backend/app/strategies/polymarket/sniper_v5_gates.py:805` `g_oracle_lag_with`
- Snapshot + store read: `backend/app/controllers/polymarket_sniper_v5.py` `_binance_lag_snapshot`, `_binance_close_at`, `_BinanceLagSnapshot` (~lines 140-185); `ft_bps` compute ~lines 695-740
- Live-only spawn branch: `backend/app/engine/main.py` `poly_sniper_v5.live_only_spawn` (~2900-3010)
- 1s stream construction: `backend/app/engine/main.py:~1428` `_vwap_1s` / `enable_1s_stream`; 1s handler registration ~2434 `register_1s_handler`
- Sleeve defs: `backend/app/strategies/polymarket/sniper_v5_sleeves.py` (`shadow_scalp_exit_btc_{5m,15m}_d3_v1`, `exit_policy="SCALP_EXIT"`, gate `g_oracle_lag_with(3.0,12.0)`, `offsets=(5,)`, `entry_band=(0.0,0.55)`)
- Allowlist: `/etc/tv/tradingvenue.env` `TV_POLY_SNIPER_V5_LIVE_ALLOWLIST`
