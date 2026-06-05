# HANDOFF → TV Engine Agent: Shadow Sleeves Not Firing (2026-05-29)

**Audience:** the tradingvenue engine maintainer/agent (works on `/opt/tradingvenue`, VPS3 `185.190.143.7`).
**Scope:** ~70 paper "shadow" sleeves (poly_sniper_v5_*, shadow_poly_updown_*, *_vwap_*) showed
idle / zero fires for 1–4 days. Read-only diagnosis is complete. This doc lists ONLY the
confirmed bugs + exact fixes + verification. Everything else is correct-by-design (see §5).

**Engine:** systemd `tv-engine` → `/opt/tradingvenue/.venv/bin/python -m backend.app.engine.main`.
Logs: `journalctl -u tv-engine`. DB: `sudo -u postgres psql -d storedata`. Shadow eval log:
`/var/log/tradingvenue/sniper_v5/<UTC-date>.jsonl` (the §7 per-eval record — your best debugging surface).

> **State note:** during diagnosis `pyarrow 24.0.0` got installed into `.venv` but the engine was
> NOT restarted, so it has NOT taken effect (v9 still logs `n_assets_loaded: 0`). Treat pyarrow as
> "present in venv but not in pyproject and not yet live." No other VPS state was changed.

---

## 0. Fix summary

| # | Bug | File / location | Impact | Effort | Priority |
|---|---|---|---|---|---|
| 1 | v9 data layer loads 0 rows: pyarrow not in deps **+** canonical parquets absent on VPS3 | venv deps + `/opt/tradingvenue/data/v4/canonical/` (missing) + `sniper_v5_v9_data.py` | 10 `_v9` sleeves can NEVER fire | M | **P0** |
| 2 | S6 precondition query uses wrong column (`payload`→`data`) + dead `LIKE` pattern | `controllers/polymarket_sniper_v5.py:1305-1316` | sleeve 01 (`*_ts_mpskew_s6_0_60`) can never fire | S | **P1** |
| 3 | OverlayFilterStrategy silently skips → named overlay sleeves invisible on dashboard | `strategies/polymarket/shadow9.py` `OverlayFilterStrategy` (~L465) | fairedge500/cvd30/cvd_macd/m5v look idle (telemetry only) | S | **P2** |
| 4 | Stale docstring documents old cross-token spread formula | `controllers/polymarket_sniper_v5.py:24-33` | misleading only | XS | P3 |

---

## 1. FIX P0 — v9 data layer dead (10 sleeves)

### Symptom
Every ~5 min in `journalctl -u tv-engine`:
```
sniper_v5_v9_data.trades_load_failed   {asset: btc/eth/sol, error: "Unable to find a usable engine; ... Missing optional dependency 'pyarrow'"}
sniper_v5_v9_data.hl_load_failed       {path: .../hyperliquid_liquidations_full.parquet}
sniper_v5_v9_data.refresh_complete     {n_assets_loaded: 0, hl_proxy_rows: 0}
```

### Root cause (TWO independent faults, both must be fixed)
**(a) `pyarrow` not in engine deps.** `pyproject.toml` pins `pandas~=2.2` but no `pyarrow`/`fastparquet`,
so every `pd.read_parquet()` in `V9DataStore._load_trades` / `_load_hl_short_proxy`
(`strategies/polymarket/sniper_v5_v9_data.py:110,141`) raises `ImportError`-equivalent.

**(b) The canonical parquets do not exist on VPS3.** Verified:
```
$ ls /opt/tradingvenue/data/v4/canonical/trades_polymarket/   → No such file or directory
$ ls /opt/tradingvenue/data/v4/canonical/hyperliquid_liquidations_full.parquet → No such file or directory
```
`V9DataStore` (`sniper_v5_v9_data.py:47-52`) reads from, per its design docstring (L24-28),
"STOREDATA artifacts written by separate Storedata jobs … tv-engine READS them read-only."
**That writer job was never set up on VPS3**, so the files are absent → `get_asset_trades()` returns
`None` → V9 gates `g_b1_poly_flow_aligned`, `g_b2_*`, `g_b3_*`, `g_a2_hl_short_cascade` hit their
`if df is None: return False` guard → **silent no-fire by design.**

### Blocked sleeves (all 10 `_v9`)
`poly_sniper_v5_btc_5m_a2_hlcascade100k_v9`, `…_up_a2_hlcascade50k_v9`,
`…_down_b2_contrarian2k_v9`, `…_up_b2_contrarian2k_v9`, `…_sol_5m_b1_polyflow_aligned_v9`,
`…_sol_5m_down_b1_500_v9`, `…_down_b1_flow250_v9`, `…_b3_abs500_v9`, `…_b1_120s_250_v9`,
`…_b3_abs500_no_opp_v9`.
(`hlcascade*` need the HL liquidations proxy; `polyflow/flow250/abs500/contrarian/b1_*` need
the polymarket trades parquet.)

### Fix
1. **Add pyarrow to deps** so it survives venv rebuilds:
   - `pyproject.toml` → add `"pyarrow>=14.0"` to the runtime dependencies, then
     `uv sync` (or `uv pip install --python /opt/tradingvenue/.venv/bin/python pyarrow`).
2. **Provide the canonical parquets on VPS3 at `/opt/tradingvenue/data/v4/canonical/`** with a
   RECURRING writer (the `refresh_loop` re-reads every 300s, so a one-time copy goes stale).
   Source data already lives in this VPS's `storedata` Postgres:
   - `trades_polymarket/{btc,eth,sol}.parquet` ← `storedata.public.trades_v2` filtered
     `slug LIKE '{asset}-updown-%'`. Required columns the gates consume: `timestamp_us, slug,
     outcome, price, size, side` (same schema as the repo's `data/v4/canonical/trades_polymarket/*`).
   - `hyperliquid_liquidations_full.parquet` ← `storedata.public.hyperliquid_liquidations_v2`.
     **Must include columns** `source, method, dir, size, price` — the proxy filter
     (`sniper_v5_v9_data.py:142-148`) selects `source=='hl-s3-fills' & method=='market' &
     dir in ('Close Short','Open Long')` and computes `notional = size*price`.
   - Recommended: a small systemd timer / cron on VPS3 dumping these 4 files every 5–10 min
     (psql `\copy` → parquet via a tiny pandas script, or DuckDB `COPY ... TO ... (FORMAT PARQUET)`).
     Keep cadence ≤ the 300s refresh so v9 gates see current-window flow.
3. **Restart:** `sudo systemctl restart tv-engine`.

### Verify
- `journalctl -u tv-engine -f | grep refresh_complete` → expect `n_assets_loaded: 3` and
  `hl_proxy_rows: >0`.
- Within a few slug cycles, grep the shadow log for v9 sleeve fires:
  `grep polyflow_aligned /var/log/tradingvenue/sniper_v5/$(date -u +%F).jsonl | grep -c '"decision":"placed"'`
  (decision/field name per your §7 schema).
- ⚠️ If files are present but STALE (writer not recurring), v9 gates evaluate on old flow → wrong
  signals. Confirm the writer cadence is live.

---

## 2. FIX P1 — S6 precondition query (sleeve 01)

### Symptom
`{"event":"poly_sniper_v5.s6_check_failed","slug":"btc-updown-5m-…","level":"warning"}` ~2×/slug
(286×/12h). Sleeve `poly_sniper_v5_btc_5m_ts_mpskew_s6_0_60` never fires.

### Root cause — `controllers/polymarket_sniper_v5.py`, `_check_s6_fired` (L1292-1317)
```sql
-- CURRENT (broken):
SELECT 1 FROM trading.events
WHERE kind = 'poly_updown_signal'
  AND payload->>'sleeve_id' LIKE 'poly_updown_%_sniper'   -- (a) wrong column, (b) pattern matches nothing
  AND payload->>'slug' = $1                                -- wrong column
  AND (payload->>'window_start_unix')::int = $2            -- wrong column
LIMIT 1
```
Two faults:
- **(a) Wrong column:** `trading.events` has a `data` (jsonb) column, NOT `payload`. The query throws
  `column "payload" does not exist`; the surrounding `except Exception` (L1318) swallows it and logs
  `s6_check_failed` → returns `False` every call.
- **(b) Dead pattern:** `LIKE 'poly_updown_%_sniper'` matches **zero** real `sleeve_id`s. Actual ids look
  like `poly_updown_sol_5m_momo_v2_HOLD_f7`. So even after the column fix, sleeve 01 stays silent.

### Fix
1. Change `payload->>` → `data->>` on all three lines (1310-1312).
2. **Before** committing the pattern, confirm the real JSON field names AND the intended S6 source.
   Inspect a live row:
   ```sql
   SELECT data FROM trading.events WHERE kind='poly_updown_signal' ORDER BY at DESC LIMIT 1;
   ```
   Verify the keys `sleeve_id`, `slug`, and the window key actually exist and are named
   `window_start_unix` (it may be `ws_s` / `slot_start_unix` — adjust `$2` key accordingly).
3. Replace the `LIKE` pattern with the actual production Cyclops S6/S7 sleeve_id that sleeve 01 is
   meant to key off (per the sniper-v5 spec, sleeve 01 = "fire only if the S6/S7 production sleeve
   already fired this slug"). Find candidates:
   ```sql
   SELECT DISTINCT data->>'sleeve_id' FROM trading.events
   WHERE kind='poly_updown_signal' AND data->>'sleeve_id' LIKE 'poly_updown_btc_5m%';
   ```

### Verify
- `journalctl -u tv-engine --since "10 min ago" | grep -c s6_check_failed` → should drop to 0.
- Sleeve 01 emits `placed` events in the shadow log when its S6 source fires + gates pass.

---

## 3. FIX P2 — Overlay sleeves invisible (telemetry only)

### Symptom
`shadow_poly_updown_*_fairedge500`, `_fairedge500_cvd30`, `_cvd_macd`, `_m5v` show 0 rows in
`trading.events` over 5 days → dashboard shows permanent idle. **Trading is not broken** — the
*base* controller evaluates; the overlay's skips just aren't recorded under the overlay's id.

### Root cause — `strategies/polymarket/shadow9.py`, `OverlayFilterStrategy` (~L465)
When `_gate_passes(direction, aux)` (L496) returns `False`, the strategy returns `NONE` WITHOUT
emitting an audit/shadow row under its `_audit_sleeve_id_override`. So the named overlay sleeve
never writes a `no_signal`/skip record — it looks dead even though it evaluated.

### Fix
In `OverlayFilterStrategy`'s signal path, on the gate-fail branch (and on base-`NONE`), emit a
skip audit row tagged with the overlay's `_audit_sleeve_id_override` (mirror how the base controller
writes `poly_updown_signal` rows with `reason="overlay_gate_fail"` / the gate name). This restores
dashboard visibility; it does not change trading behavior.

> NOTE: the overlay GATE itself is also genuinely strict (`fair_edge_bp>500` rarely true — live values
> are typically negative on UP, ~+600 on BTC DOWN). That's a RULE, not a bug — see §5. The fix here is
> only to make the abstains visible.

### Verify
- After the fix, `SELECT data->>'sleeve_id', count(*) FROM trading.events WHERE kind='poly_updown_signal'
  AND data->>'sleeve_id' LIKE '%fairedge500%' GROUP BY 1;` → rows appear (mostly `no_signal`).

---

## 4. FIX P3 — Stale docstring (cosmetic)
`controllers/polymarket_sniper_v5.py:24-33` eval-flow docstring step 4 still reads
`spread = abs(up_vwap - (1 - dn_vwap))` (old cross-token formula). The live code is already correct
(same-token `ask0-bid0` via `controllers/_sniper_spread.py`, since 2026-05-27). Update the comment to
match, so future devs don't reintroduce the cross-token bug.

---

## 5. DO NOT "FIX" THESE — correct by design (verified)

- **Spread gate is already correct.** Same-token `ask0-bid0`, thresholds BTC/ETH 0.02, SOL 0.025
  (`sniper_v5_sleeves.py:173-182`). On 2026-05-28 it accounted for only 17.8% of sniper skips
  (16,181 / 90,801 evals); directional **gates** accounted for 82.2%. The old cross-token formula
  (the one that caused 1184 evals → 0 placements) was already fixed 2026-05-27.
- **momo / momo_v2 ARE firing** — 218 + 188 placements in 2 days under `poly_updown_{sym}_{tf}_momo*_HOLD_f7`
  (resolver logs confirm PnL). Their 93–95% `no_signal` = `|ret_2m| < q90 threshold` in a low-vol
  regime. Working as designed.
- **Sniper v6/v7/v8/vL (sleeves 02-08) low fire rate is a RULE.** 90,801 evals/day, 82% rejected by
  multi-gate AND (top: `g_grandparent_trend_with(BTC)` 8506, `g_parent_15m_slope_with(BTC)` 6904,
  `g_f7_rsi_with(SOL)` 4470). These rarely co-satisfy in 1–4 days of quiet tape. Correct selective behavior.
- **vwap_continuation low fire rate is a RULE** — `abs(vwap_dev_bps)` < `thr_min` in 84% of evals
  (median dev ≈ 2–3 bps vs 5–30 bps thresholds). If you WANT more fires for shadow assessment, lower
  `thr_min` to 1–3 bps or make it a rolling percentile (engine `main.py` `_VWAP_CONT_SLEEVES_SPEC`).
  That's a tuning choice, **not** a bug fix — revalidate PnL before trusting.

**Independent backtest cross-check (33 days, all 6 markets, full gate battery):** the BTC/ETH/SOL
up-down PRICE is an efficient estimator of the outcome — no momentum/flow/oracle signal beat it
out-of-sample. So strict directional gates SHOULD abstain most of the time. The low fire rate on the
v6/v7/v8/vL + vwap families is largely *correct conservatism*, not breakage. The real breakage is the
3 bugs above (v9 data, S6, overlay telemetry).

---

## 6. Suggested order & post-fix watch
1. P0 v9 (parquet writer + pyarrow dep + restart) — unblocks 10 sleeves.
2. P1 S6 (column + pattern, verify json keys) — unblocks sleeve 01.
3. P2 overlay telemetry — restores dashboard truth for ~4 sleeves.
4. P3 docstring.
5. Let it run 24–48h. Re-pull `/var/log/tradingvenue/sniper_v5/<date>.jsonl`; per-sleeve:
   `decision` distribution + `skip_reason` histogram. Expect v9 + sleeve-01 to start placing;
   v6/v7/v8/vL + vwap to remain selective (RULE). Decide separately whether to loosen any gate.

### Key evidence locations (for your own verification)
- Shadow eval log (§7, per-eval): `/var/log/tradingvenue/sniper_v5/2026-05-{27,28,29}.jsonl` (~90k evals/day).
- Signal pipeline: `trading.events` kind=`poly_updown_signal` (165k/2d) — `data` jsonb has the decision/reason.
- Engine warnings: `journalctl -u tv-engine | grep -E "s6_check_failed|v9_data"`.
- Source files referenced: `controllers/polymarket_sniper_v5.py`, `strategies/polymarket/{shadow9.py,
  sniper_v5_v9_data.py,sniper_v5_sleeves.py}`, `controllers/_sniper_spread.py`, `engine/main.py`.
