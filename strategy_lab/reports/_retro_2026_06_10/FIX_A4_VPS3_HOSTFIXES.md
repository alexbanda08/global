# FIX A4 — VPS3 SHADOW engine host fixes (retro audit 2026-06-10)

**Host:** VPS3 (185.190.143.7), service `tv-engine.service` (paper/shadow box). Ireland (live $) NOT touched.
**Applied/restarted:** 2026-06-11 ~02:44 CEST (00:44 UTC). Engine PID 815067.
**Commit (VPS3, `/opt/tradingvenue`):** `96c4b786` — `fix(shadow): F2 kill set + F3 t60 markov + kalshi scalp A/B + sell_leg_fee (retro audit 2026-06-10)`
**Backups:** every edited file copied to `*.bak-fix-20260610` before editing.

---

## FIX 1 — F2 kill set (config / env)

**Finding (deviation from task brief):** `TV_POLY_SNIPER_V5_KILL` was **NOT empty** — it already held 5 ids
(`poly_fast_taker_a25_merge_btc_5m`, `…_eth_5m`, `poly_sniper_v5_btc_5m_slotend_ofi_ts_v7`,
`poly_sniper_v5_sol_5m_a2_hlcascade25k_v9`, `poly_sniper_v5_sol_5m_up_a2_hlcascade15k_v9`).
The engine reads env from **`/etc/tv/tradingvenue.env`** (systemd `EnvironmentFile=`), not a repo `.env`/pydantic file —
there is no `/opt/tradingvenue/backend/.env`.

**Decision:** APPENDED the 2 target ids rather than replacing (replacing would have un-killed 5 already-dead sleeves = regression).
Intent of the brief ("add the F2 kills") is preserved; the literal `SET=` would have been destructive.

- File: `/etc/tv/tradingvenue.env` line 146 (backup: `/etc/tv/tradingvenue.env.bak-fix-20260610`)
- Appended: `,poly_sniper_v5_btc_5m_q_parent15mslope_ts_imb5_v8,poly_sniper_v5_btc_5m_ts_mpskew_any_off30`
- Env now has **7** kill ids.

**On `kill_set_size`:** the brief expected `=2`, but that assumed an empty env. The runtime kill set
(`main.py:2854-2888`) = env CSV (7) **∪** ML_EXIT roster sleeves **∪** `TV_POLY_DEPRECATED_SLEEVES` (~90 ids).
Observed log: **`kill_set_size: 99`** — expected given the union. The meaningful check is that the 2 new ids
are in the set and stop firing (verified below), not the literal count.

**Verification:** the 2 target ids exist in the live roster (`sniper_v5_sleeves.py`, 2 matches) and were absent from the
kill env before the edit. After restart, over a 12-minute window (02:44:32 → 02:56:02) both emitted **0 new
`poly_updown_signal`** events; control (other `poly_sniper_v5_btc_5m%` sleeves) emitted **141** signals in the same
window (engine actively firing → targeted suppression confirmed). The only post-restart events for the two ids were
`poly_updown_resolution` (settlements of positions opened before the kill took effect) — expected.

---

## FIX 2 — F3 fade markov at t+60 (code)

**File:** `backend/app/engine/poly_updown_loop.py` (backup `.bak-fix-20260610`).
The t+60 BarContext builder (`build_bar_context_t_plus_60`) hardcoded `markov_regime_w20_5m_va=None`
→ FadeCompanion's `m5v_pass` was always `False` (regime None → not int → False) → **fade fired on every signal**.
Mirrored the t+120 reference (`_m5v_t120 = _compute_m5v_regime(get_feed_instance(), sym_upper, ws_s)`).

Diff (source lines, `.bak` hunks excluded):
```
+    # FIX (shadow-audit F3, applied 2026-06-10): compute 5m Markov regime so the
+    # t+60 fade m5v gate functions (was always-False -> fade fired on every signal).
+    from backend.app.data.bars import get_feed_instance as _get_feed_m5v_t60
+    _m5v_t60 = _compute_m5v_regime(_get_feed_m5v_t60(), sym_upper, ws_s)
...
-        # markov_5m left None here on purpose: the t+60 fade_momo_v2 sleeves
-        # gate on it and are currently firing — not in scope to change.
-        markov_regime_w20_5m_va=None,
+        # FIX (shadow-audit F3, applied 2026-06-10): compute 5m Markov regime so the
+        # t+60 fade m5v gate functions (was always-False -> fade fired on every signal).
+        markov_regime_w20_5m_va=_m5v_t60,
```
`python -m py_compile` OK. Base momo_v2 ignores the field (additive-safe).

### Which listed sleeves were affected (phase mapping)

Authoritative family→builder map at `poly_updown_loop.py:1717-1723`:
`fade_sniper / overlay_sniper → bar_close` · `overlay_momo → t+120` · `fade_momo_v2 / overlay_momo_v2 → t+60`.
The 3 builders that set `markov_regime_w20_5m_va`: bar_close `_m5v_bc` (line ~489, already populated),
t+120 `_m5v_t120` (line ~753, already populated), t+60 (line ~990, **was None → now `_m5v_t60`**).

| Sleeve | family | phase | status |
|---|---|---|---|
| `shadow_poly_updown_sol_15m_fade_momo_v2` | fade_momo_v2 | **t+60** | **FIXED by F3** |
| `shadow_poly_updown_btc_5m_fade_sniper` | fade_sniper | bar_close | already fine |
| `shadow_poly_updown_eth_15m_fade_sniper` | fade_sniper | bar_close | already fine |
| `shadow_poly_updown_sol_5m_fade_sniper` | fade_sniper | bar_close | already fine |
| `shadow_poly_updown_eth_15m_sniper_m5v` | overlay_sniper | bar_close | already fine |
| `shadow_poly_updown_sol_5m_momo_v1_m5v` | overlay_momo | t+120 | already fine |

So among the listed sleeves, **only `shadow_poly_updown_sol_15m_fade_momo_v2`** (the sole `fade_momo_v2` entry) had the
dead gate; the rest evaluated in builders that already populated the regime. (FadeCompanion class at
`strategies/polymarket/shadow9.py:434`, m5v gate ~517-551.)

---

## FIX 3 — Kalshi scalp A/B twins (config)

**File:** `backend/app/strategies/kalshi/sniper_kalshi_sleeves.py` (root-owned; edited via `sudo`; backup `.bak-fix-20260610`).
`kalshi_scalp_exit_btc_15m_d3_v1` and `…_notp_v1` both omitted `scalp_tp_enabled` → both inherited default `False`
(`SniperV5Sleeve.scalp_tp_enabled: bool = False`) → identical configs → meaningless A/B.
Added `scalp_tp_enabled=True` to the `_v1` sleeve only (line 148, inside block 131–154); `_notp_v1` keeps the default
(TP OFF, mirrors live). `scalp_stop_enabled` defaults `True` for both. `python -m py_compile` OK.

```
+        scalp_tp_enabled=True,     # A/B reference: TP ON (the old config) — twin _notp_v1 keeps TP OFF (default) to mirror live; stop ON for both
```

---

## FIX 4 — shadow scalp sell-leg fee (code)

**File:** `backend/app/controllers/polymarket_sniper_v5.py:1399` (backup `.bak-fix-20260610`).
Change was trivially safe (local constant consumed immediately in the next line's PnL and logged). Set the sell-leg
(taker) fee to the live Polymarket per-share curve `0.07*p*(1-p)` at the sell vwap × shares.

```
-        sell_leg_fee = 0.0  # offline proxy $0; LOG it (gate §7.2 verifies live)
+        # FIX (shadow-audit F4, 2026-06-10): charge the live taker fee on the
+        # SELL leg (was 0.0 = optimistic). Polymarket per-share fee curve
+        # 0.07*p*(1-p) at the sell vwap, times shares. Mirrors entry-side.
+        sell_leg_fee = 0.07 * sell_vwap * (1.0 - sell_vwap) * fr.fill_shares
```
`pnl = (sell_vwap - fr.fill_vwap) * fr.fill_shares - sell_leg_fee` (unchanged) now nets the exit fee.
Logged as `sell_leg_fee_charged` / surfaced in `scalp_exit`. `python -m py_compile` OK.

---

## Restart + health verification

- `sudo systemctl restart tv-engine.service` → `systemctl is-active` = **active** (PID 815067, 02:44:32 CEST).
- `py_compile` clean on all edited files + `main.py` + `config.py`.
- Journal since restart: **0 tracebacks / Python errors** from the new PID. (Pre-existing benign noise only:
  `book_mirror.disconnected` ws-keepalive auto-reconnect, `binance_liquidations_v2` collector-staleness alert — unrelated.)
- `kill_set_size: 99` logged by the sniper_v5 loop (`sniper_v5.loop_started`, `…spawned`).
- Killed-sleeve signal suppression: **0 new `poly_updown_signal`** over 12 min; control fleet 141 signals same window.

## Notes / caveats

- The VPS3 working tree is "committed-snapshot style" and was already dirty: the commit `96c4b786` swept up many
  pre-existing untracked/modified files (`frontend-out/*`, `*.tgz` backups, several `.bak-coinflip*`/`.bak-predeploy*`
  files, and a prior-uncommitted `+4` to `sniper_v5_sleeves.py` / a `g_entry_vwap_not_coinflip` edit). **None of those
  were introduced this session** — my 4 changes are isolated to the 3 source files above + the env file (env is outside
  the repo tree, so not in the commit). My `.bak-fix-20260610` of `poly_updown_loop.py` contains no coinflip reference,
  confirming clean isolation.
- `/etc/tv/tradingvenue.env` is outside `/opt/tradingvenue`; its change is NOT in git (backup at
  `/etc/tv/tradingvenue.env.bak-fix-20260610`).
