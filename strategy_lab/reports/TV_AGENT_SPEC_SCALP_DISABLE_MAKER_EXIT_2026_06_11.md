# TV-AGENT SPEC — Disable the scalp MAKER exit on ALL 15m scalp sleeves → pure taker +60 (2026-06-11)

**Type:** parameter change on scalp sleeves, BOTH hosts (VPS3 shadow + Ireland incl. the $1 LIVE sleeve).
**Why:** the maker-exit's supporting evidence is DEAD. The corrected-harness rerun
(`BUGFIX_RERUN_RESULTS_2026_06_10.md`) reversed `MAKER_EXIT_SIM_2026_06_06`'s +$0.42 CI[+0.02,+0.82] to
**−$0.073 ns** (CLEAN +0.32 ns) — the old positive came from the same harness bugs that manufactured the stop's
+0.88 (outcome-as-price fallback + exit-size ignored). With the evidence gone, the 15m sleeves must revert to the
validated **pure taker +60s time exit** (TP off, stop off — stop already removed 2026-06-11, commits Ireland
`1746efc` / VPS3 `6eaa154f`). This also restores live↔shadow twin parity (the live×shadow audit
`SCALP_BTC15M_LIVE_VS_SHADOW_AUDIT_2026_06_11.md` found the exit-policy mismatch is one of the main divergence
sources).

**Current state (verified on hosts 2026-06-11):**
- The sleeve dataclass has `scalp_exit_mode: str` — `"taker"` | `"maker_fixed"` (post-only SELL at
  `scalp_maker_tp=0.60`, taker-+60 fallback, repost 5s) | `"maker_peg"`.
- **VPS3** `backend/app/strategies/polymarket/sniper_v5_sleeves.py`:
  - line ~1775 (generator): `scalp_exit_mode="maker_fixed" if _tf == "15m" else "taker"` → puts maker on EVERY
    generated 15m scalp sleeve.
  - explicit `scalp_exit_mode="maker_fixed", scalp_maker_tp=0.60` blocks on at least
    `shadow_scalp_exit_btc_15m_d3_notp_v1` (~line 1817) — sweep the whole file for ALL occurrences.
  - Sleeves with actual `scalp_maker_lift` fills so far: `shadow_scalp_exit_btc_15m_d3_{v1,notp_v1,control_v1}`,
    `shadow_scalp_exit_eth_15m_d3_{v1,control_v1}` (n=2–21 each).
- **IRELAND** same file: dataclass default is `"taker"`, but the **LIVE** sleeve `shadow_scalp_exit_btc_15m_d3_v1`
  (~line 1740, `live_notional_usd_override=$1`, in `TV_POLY_SNIPER_V5_LIVE_ALLOWLIST`) has explicit
  `scalp_exit_mode="maker_fixed", scalp_maker_tp=0.60`. It has never filled a maker lift (always fell back to
  taker +60), but the config is live — remove it.
- Kalshi sleeves: no maker mode (already taker) — no change.

## Change (both hosts)
In `backend/app/strategies/polymarket/sniper_v5_sleeves.py`:
1. Generator (VPS3 ~1775): `scalp_exit_mode="maker_fixed" if _tf == "15m" else "taker"` →
   `scalp_exit_mode="taker",  # 2026-06-11: maker-exit evidence reversed by corrected harness — pure taker +60 on all tfs`
2. EVERY explicit `scalp_exit_mode="maker_fixed"` on a scalp sleeve → `scalp_exit_mode="taker"`; delete the
   accompanying `scalp_maker_tp=0.60` line (or leave it — it's inert with mode=taker; prefer delete for clarity).
   Sweep with grep: `grep -n 'maker_fixed\|maker_peg' .../sniper_v5_sleeves.py` — after the edit the only hits
   should be the dataclass docstring/field definitions.
3. Update the stale comment block above Ireland's live 15m sleeve (~1726–1731): it still says "the protective
   stop@-0.10 stays on" and describes the maker TP — rewrite to: "exit = pure taker +60s time sell (TP off, stop
   off 2026-06-11, maker-exit off 2026-06-11 — corrected-harness reversals)."
4. Do NOT touch: entry config (offsets, gates, entry_band, spread_filter), notional overrides, one_shot,
   `scalp_exit_offset_s=60`, the TOD-gated `_tod2` variants' hour gates, the Kalshi sleeves.

## Deploy
- Backup each edited file as `.bak-nomaker-20260611` first. `python -m py_compile` before restart.
- VPS3: `sudo systemctl restart tv-engine`; Ireland: same. Verify `systemctl is-active` + no errors in
  `journalctl -u tv-engine --since "2 min ago" -p err`.
- Commit on each host (snapshot style): `fix(scalp): disable maker-exit on all 15m scalp sleeves — corrected-harness
  reversal; pure taker +60 everywhere`.

## Acceptance
1. `grep -c 'scalp_exit_mode="maker_fixed"' sniper_v5_sleeves.py` == 0 on BOTH hosts (excluding docstring).
2. After ≥24h: zero NEW `scalp_maker_lift` exit events in `trading.events` (both hosts):
   `select count(*) from trading.events where data->>'exit_type'='scalp_maker_lift' and at > <deploy_ts>;` == 0.
3. 15m scalp exits show ONLY `scalp_time60` triggers (no `scalp_stop`, no `scalp_tp065`, no `scalp_maker_lift`).
4. Fire counts/entries unchanged vs pre-deploy (entry config untouched).

## Context for the future
If the maker-exit idea is revisited, it must be re-validated FROM SCRATCH on the corrected harness
(`scalp_fill_lib_2026_06_10.py`) with a queue-aware fill model AND the rebate term modeled explicitly (see the
separate maker-rebate research thread, `_retro_2026_06_10/06_WHITESPACE.md` E3) — not by citing
`MAKER_EXIT_SIM_2026_06_06` or `SCALP_EXIT_CONFIG_BY_TF_2026_06_06`, which are tainted by the harness bugs.

## END
