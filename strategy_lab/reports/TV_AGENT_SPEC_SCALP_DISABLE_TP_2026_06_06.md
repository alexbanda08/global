# TV-AGENT SPEC — Disable scalp **TP only** (KEEP the stop), +60 s exit (2026-06-06, corrected 2026-06-09)

> 🛑 **CORRECTION 2026-06-09 — SUPERSEDES the original "disable TP+stop / pure +60" intent of this spec.**
> Only the **TP@0.65 leaks edge → disable the TP.** The **stop@(fill−0.10) is VALIDATED edge (+0.88/tr, SIG,
> confirmed 3×) → KEEP IT.** Authoritative current config = **TP OFF, STOP ON, +60 s** (`project_scalp_exit_config`
> memory + `SCALP_NEW_EDGE_HUNT_2026_06_09.md`). The original spec below would have disabled the stop too
> (`scalp_stop_delta → 1.0`) — **DO NOT do that.** The `SCALP_HEDGE_PHYSICS_SWEEP_2026_06_03` "+60 dominates
> stop salvage" claim was overturned by the later 3× stop-validation; trust the validated config.
> ➡️ **Net change to apply: set the TP off, leave `scalp_stop_delta` UNCHANGED.**

**Type:** parameter change on ALL live + shadow scalp sleeves (both hosts: Ireland + VPS3).
**Why:** the live scalp exit runs `scalp_tp_bid=0.65` (take-profit) + `scalp_stop_delta=0.10` (stop) on top of
the +60s deadline. Research shows the **TP** leaks edge (the stop does NOT — keep it, see correction above):
- `SCALP_DYNAMIC_EXIT_2026_06_04`: a take-profit caps the runners and **underperforms the +60 exit**
  (tested no-lookahead; TP cells all < fixed +60).
- `MAKER_EXIT_SIM_2026_06_06`: the apparent taker-TP win is a lookahead artifact; the valid baseline is +60.
**Validated optimum: +60 s time exit with the TP OFF and the STOP ON.**

## Exit TIME = +60s (verified 2026-06-06, paired bootstrap; +45 is NOT better)
Re-checked +45 vs +60 per cell (gated, paired bootstrap over fires): **every paired CI includes 0 → +45 and +60
are statistically TIED.** By MEAN, +60 is the argmax for BTC 5m (+4.54 vs +4.18), BTC 15m (+2.33 vs +2.05), and
ALL-pooled (+2.95 vs +2.71). +45 only edges ETH 5m and the δ≥5 cell by ~$0.003–0.004/tr = noise. The earlier
"+45 ≥ +60" note was based on a marginally tighter t-stat (shorter hold = less variance), NOT higher return.
**→ KEEP scalp_exit_offset_s = 60.** Do NOT switch to 45 (no evidence) and do NOT per-cell-tune the exit time
(that fits noise — all cells are tied 45–60). The ONLY change here is removing the TP/stop.

## Change
In `app/strategies/polymarket/sniper_v5_sleeves.py`, on every `shadow_scalp_exit_*` sleeve (the generator),
set the take-profit OFF while keeping the +60 deadline **AND the stop**:
- `scalp_tp_bid` → `Decimal("0.999")` (effectively never triggers — or add a sleeve flag `scalp_tp_enabled=False`)
- `scalp_stop_delta` → **LEAVE UNCHANGED at `0.10`** (the stop is validated edge — do NOT set it to 1.0). ⚠️ corrected 2026-06-09.
- KEEP `scalp_exit_offset_s = 60`; `scalp_poll_s` still needed so the stop poll runs (it is NOT deadline-only).
Equivalent: in `poly_sniper_v5_loop._scalp_exit_then_resolve` / `controller.maybe_scalp_exit`, gate the
`mode="poll"` TP/stop checks behind a `scalp_tp_enabled` flag (default False) so only the `mode="deadline"`
time-sell at +60 fires. Prefer a clean `scalp_tp_enabled: bool = False` field on `SniperV5Sleeve`.

## Scope
- **Ireland (live):** `shadow_scalp_exit_btc_5m_d3_v1` (Poly, + its `_LIVE`) AND **`kalshi_scalp_exit_btc_15m_d3_v1`**
  (Kalshi, also live $1) — both trade real $1 and both run the TP@0.65+stop. Apply the **TP-off** to BOTH.
  (Kalshi sleeve in `app/strategies/kalshi/sniper_kalshi_sleeves.py`: set `scalp_tp_bid=0.999` only; **leave
  `scalp_stop_delta=0.10` unchanged** — corrected 2026-06-09, keep the stop.)
- **VPS3 (shadow):** all `shadow_scalp_exit_*` (Poly) sleeves.
- Apply on both `deploy/ireland` and `deploy/vps3`.
- **Kalshi scalp = TAKER exit only** (do NOT add maker — `kalshi_scalp_maker_exit_2026_06_06.py` shows maker is
  WORSE on Kalshi: no maker rebate, tight spread, +120s/900s runway lets the taker exit beat a capped maker TP).
  The maker-exit upgrade (`TV_AGENT_SPEC_SCALP_MAKER_EXIT`) is **Polymarket-only**.

## Validation / acceptance
- After deploy, confirm scalp exits emit the `time60` deadline path and the `stop` path **but NOT the `tp` path**
  in `trading.events` (`kind='poly_updown_scalp_exit'`, check the trigger field in `data`). ⚠️ corrected
  2026-06-09: the **stop trigger SHOULD still fire** (validated edge) — only the `tp` trigger must be gone.
- Re-baseline shadow $/tr WITH the real taker sell fee (currently `sell_leg_fee=0.0` — set it to the live
  taker curve `0.07*p*(1-p)` so shadow PnL is honest).

## Follow-on (separate spec, after this)
Once the TP is off (stop kept), test + (if it holds OOS with a queue-aware fill) deploy the **maker-exit**: at +60 post a
maker SELL pegged to the ask (or trail), taker-cross if unfilled within a few seconds — favorable exit-side
selection + rebate (`MAKER_EXIT_SIM_2026_06_06.md`, +$0.42/tr upper-bound estimate).

## Files
- `SCALP_DYNAMIC_EXIT_2026_06_04.md`, `MAKER_EXIT_SIM_2026_06_06.md`, `SCALP_LIVE_AUDIT_2026_06_06.md`.
