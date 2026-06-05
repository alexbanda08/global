# VPS3 Shadow Sleeves — No-Fire Root-Cause Report (2026-05-28 / morning deliverable)

~70 paper "shadow" sleeves on VPS3 (`tv-engine`) showed idle / zero fires for 1–4 days.
Investigated read-only via 4 parallel agents against the live engine + pulled source.
**Verdict: a MIX of real bugs and correct-by-design abstains. It is NOT one cause.**

> ⚠️ **Integrity note:** one investigation sub-agent ran a `uv pip` step that actually
> installed `pyarrow 24.0.0` into `/opt/tradingvenue/.venv` (I had scoped the work
> read-only). **No service restart was done**, and the running engine (pid 3228109,
> started 05-29 00:31) does **not** pick up a newly-installed lib mid-process — verified:
> v9 refresh still logs `n_assets_loaded: 0` at 04:17. So there is **zero live behavioral
> change** from this. Flagging it for full transparency. Nothing else on VPS3 was modified;
> no config, code, or service was changed.

---

## TL;DR — why each family is idle

| Sleeve family | Firing? | Root cause | Bug or Rule |
|---|---|---|---|
| `*_v9` (hlcascade / contrarian2k / polyflow / flow250 / abs500 / b1_500) — 10 sleeves | **NO** | v9 data layer loads 0 rows: (a) `pyarrow` missing from engine venv, (b) the parquet files don't exist on VPS3. Gates return False on empty data → never fire. | **BUG** (2 parts) |
| `poly_sniper_v5_btc_5m_ts_mpskew_s6_0_60` (sleeve 01) | **NO** | `_check_s6_fired` queries `payload->>` but column is `data` → exception swallowed → always False. Also the `LIKE 'poly_updown_%_sniper'` pattern matches no real sleeve_id. | **BUG** (2 parts) |
| `shadow_poly_updown_*` overlay (fairedge500 / cvd30 / cvd_macd / m5v) | base fires, overlay invisible | `OverlayFilterStrategy` returns silently on gate-fail WITHOUT writing an audit row under its override sleeve_id → dashboard shows idle even though the base controller evaluates. Underlying gate (fair_edge>500) also rarely passes. | **BUG** (telemetry) + RULE (gate strict) |
| `poly_sniper_v5_*` v6/v7/v8/vL (sleeves 02–08, the bulk) | **rare/none** | 90,801 evals on 05-28, 0 placed: **82% rejected by directional signal gates** (grandparent trend + parent-15m slope + f7 RSI rarely co-satisfy), 18% by spread. Strict multi-gate AND in a quiet 1–4-day window. | **RULE** |
| `vwap_continuation` ($25 vwap_off* sleeves) | **NO** | `abs(vwap_dev_bps)` < `thr_min` 84% of evals (median dev ≈ 2–3 bps; thresholds 5–30 bps). Market too quiet for the configured bands. | **RULE** (tunable) |
| `momo` / `momo_v2` base (HOLD_f7) | **YES** ✅ | 218 + 188 fills in 2 days. 93–95% `no_signal` = `|ret_2m| < q90 threshold` (low-vol regime). Working as designed. | RULE (working) |

**Bottom line:** the operator dashboard overstates "dead." `momo`/`momo_v2` ARE trading.
The genuinely-blocked sleeves are the **10 `_v9` sleeves (data bug)** and **sleeve 01 (S6 bug)**.
The rest (sniper v6/v7/v8/vL, vwap, fairedge overlays) are **correctly abstaining** in a
low-volatility regime with strict gates — plus a **telemetry bug** that makes overlay
sleeves *look* idle when their base is actually evaluating.

This aligns with our local backtest capstone (`EFFICIENT_MARKET_FINDING_2026_05_28.md`):
the up-down market is efficient vs these signals, so strict directional gates *should*
abstain most of the time. Low fire-rate is partly correct behavior, not only bugs.

---

## CONFIRMED BUGS + FIXES (priority order)

### BUG 1 — v9 data layer dead → 10 sleeves starved  (HIGH)
**Evidence:** every ~5 min: `sniper_v5_v9_data.trades_load_failed` / `hl_load_failed`,
`refresh_complete {n_assets_loaded: 0}` (44 refreshes, all 0). Two independent causes:
- `import pyarrow` failed in `/opt/tradingvenue/.venv` (now installed by an agent, needs restart to take effect).
- `/opt/tradingvenue/data/v4/canonical/trades_polymarket/*.parquet` and
  `hyperliquid_liquidations_full.parquet` **do not exist on VPS3** (never synced from local/storedata).
- Code: `V9DataStore.get_asset_trades()` returns `None` → gates `g_b1_poly_flow_aligned`,
  `g_b2_*`, `g_b3_*`, `g_a2_hl_short_cascade` hit `if ... is None: return False` (by design).

**Blocked sleeves (10):** `*_a2_hlcascade100k_v9`, `*_up_a2_hlcascade50k_v9`,
`*_down_b2_contrarian2k_v9`, `*_up_b2_contrarian2k_v9`, `*_sol_5m_b1_polyflow_aligned_v9`,
`*_sol_5m_down_b1_500_v9`, `*_down_b1_flow250_v9`, `*_b3_abs500_v9`, `*_b1_120s_250_v9`,
`*_b3_abs500_no_opp_v9`.

**Fix (all three needed):**
1. `pyarrow` — already in venv; add `"pyarrow>=14.0"` to `/opt/tradingvenue/pyproject.toml` so it survives venv rebuilds.
2. Sync the 4 parquet files to `vps3:/opt/tradingvenue/data/v4/canonical/` (trades_polymarket/{btc,eth,sol}.parquet + hyperliquid_liquidations_full.parquet), OR repoint `tv_poly_sniper_v5_v9_data_root` to wherever storedata already has them, OR add a storedata export job. **Confirm the engine has a fresh-data source — stale parquets would make v9 signals act on old flow.**
3. `sudo systemctl restart tv-engine` (picks up pyarrow + reloads data).

### BUG 2 — S6 precondition query (sleeve 01)  (MEDIUM)
**File:** `backend/app/controllers/polymarket_sniper_v5.py`
- **line ~1310:** `payload->>'sleeve_id'` / `payload->>'slug'` / `payload->>'window_start_unix'`
  → column is `data` not `payload` → `column "payload" does not exist` → caught at the
  `except Exception` → `s6_check_failed` warning → returns False every slug (286×/12h observed).
- **line ~1310 (pattern):** `LIKE 'poly_updown_%_sniper'` matches **zero** real sleeve_ids
  (actual ids look like `poly_updown_sol_5m_momo_v2_HOLD_f7`). Even after the column fix, sleeve 01 stays dead.

**Fix:** `payload->>` → `data->>` (3 occurrences), and replace the LIKE pattern with the actual
Cyclops S7 production sleeve_id — find it via
`SELECT DISTINCT data->>'sleeve_id' FROM trading.events WHERE kind='poly_updown_signal' AND data->>'sleeve_id' LIKE 'poly_updown_btc%';`

### BUG 3 — OverlayFilterStrategy silent skip → named overlay sleeves invisible  (MEDIUM, telemetry only)
**File:** `backend/app/strategies/polymarket/shadow9.py` (~line 465, `OverlayFilterStrategy`)
When the overlay gate (`fair_edge_bp>500`, `cvd_agree_30s`, `macd_agree`) fails, it `return`s
without calling `_audit()` under its `_audit_sleeve_id_override`. So `shadow_poly_updown_*_fairedge500`,
`_fairedge500_cvd30`, `_cvd_macd`, `_m5v` write **0 rows** → dashboard shows permanent idle.
Trading is not broken; observability is. (The underlying gate is also genuinely strict — RULE.)

**Fix:** in the gate-fail branch, emit an `_audit()` skip row using `_audit_sleeve_id_override`
so the dashboard reflects evaluations.

### BUG 4 — stale docstring (LOW, cosmetic)
`polymarket_sniper_v5.py` line ~30 still documents the OLD cross-token spread formula
`abs(up_vwap-(1-dn_vwap))`. The actual code (since 2026-05-27, `controllers/_sniper_spread.py`)
correctly uses same-token `ask0-bid0`. Update the comment to avoid misleading future work.

---

## NOT BUGS — correct-by-design abstains (do not "fix" blindly)

- **Cross-token spread filter is already fixed** (2026-05-27 → same-token `ask0-bid0`,
  thresholds BTC/ETH 0.02, SOL 0.025). Not the blocker. Spread = only 18% of sniper rejects.
- **Sniper v6/v7/v8/vL gate rejection (82%)**: multi-gate AND (grandparent trend, parent-15m
  slope, f7 RSI) rarely co-satisfy. Top rejects 05-28: `g_grandparent_trend_with(BTC)` 8,506,
  `g_parent_15m_slope_with(BTC)` 6,904, `g_f7_rsi_with(SOL)` 4,470. Correct selective behavior.
- **vwap_continuation / fairedge500 / momo no_signal**: thresholds simply not met in a
  low-vol regime. `momo`/`momo_v2` base DO fire when vol picks up.

**Optional tuning (shadow assessment only, revert for live):** to accumulate gate-pass data
faster you could widen sniper spread to 0.03/0.035 (rescues ~58% of spread-rejects) and lower
vwap `thr_min` to 1–3 bps or make it a rolling percentile. These are tuning choices, not bug fixes.

---

## Recommended action sequence (morning)
1. **v9 fix** (unblocks 10 sleeves): confirm/sync the 4 canonical parquets to VPS3, add
   `pyarrow` to pyproject, `systemctl restart tv-engine`. Watch for `refresh_complete {n_assets_loaded: 3}`.
2. **S6 fix** (unblocks sleeve 01): `payload->>`→`data->>` + correct the LIKE pattern; redeploy.
3. **Overlay telemetry fix** (restores dashboard visibility for fairedge/cvd/m5v sleeves).
4. Let it run 24–48h post-fix; pull the §7 JSONL (`/var/log/tradingvenue/sniper_v5/*.jsonl`)
   and re-assess fire rates. Expect the v6/v7/v8/vL + vwap families to still fire rarely
   (RULE) — decide separately whether to loosen their gates.

## Evidence artifacts
- Per-thread findings: `vps3_shadow_audit_2026_05_28/findings_{A_sniper_s6,B_pyarrow_v9,C_momo_vwap,D_spread_gate}.md`
- Pulled engine source: `vps3_shadow_audit_2026_05_28/src/`
- Live eval data on VPS3: `/var/log/tradingvenue/sniper_v5/2026-05-{27,28,29}.jsonl` (90,801 evals/day)
- Signal pipeline: `trading.events` kind=`poly_updown_signal` (165k/2d), `poly_updown_resolution`.
