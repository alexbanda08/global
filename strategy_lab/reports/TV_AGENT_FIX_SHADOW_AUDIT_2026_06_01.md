# TV-Agent Fix Spec — Shadow Sleeve Audit Remediation (2026-06-01)

_Derived from `SHADOW_SLEEVE_AUDIT_2026_06_01.md` (154-sleeve live-vs-spec-vs-backtest audit). Targets the
**confirmed live bugs + the real-money discrepancy**. All line refs are against the VPS3 working tree
`/opt/tradingvenue/backend/app/...` (mirrored locally in `vps3_engine_snapshot_2026_06_01/`). **⚠ The engine is
running an UNCOMMITTED working tree — last commit `3a2ff3a9` (May 29). 30+ files are modified. Every fix below
lands in that working tree; commit them all when done (closes handoff open-item #3).**_

## ⚠ Scope correction (post-operator review, 2026-06-01)

- **F4 (Kalshi band) WITHDRAWN — false positive.** The live Kalshi ema_down runs on the **Ireland exec box**
  (live/real-money) and the `[0.15,0.93]` band is already implemented there. VPS3 (audited here) hosts the
  **shadow** fleet + storedata; its Kalshi config is the shadow-side copy. **Live real-money sleeves run on
  Ireland and were NOT in this audit** — if a live-code audit is wanted, snapshot the Ireland engine separately.
- **Count: 154 → de-scope to the active shadow fleet.** The 154 came from *distinct sleeve_ids with a
  resolution event in the last 7 days*. **133** fired in the last 24–48h (the live-active set); operator
  registry = **146** (registered sleeves, incl. registered-but-quiet). **21 sleeves were over-included** — all
  retired: 20× `poly_updown_*_momo_*_{SELL,HEDGE}_f7` exit-companions (last fired **2026-05-27**) +
  `poly_sniper_v5_sol_5m_depth_up_hod_session` (last 05-28). These carry **no action items**.
- **All 14 fix-item sleeves (F1/F2/F3/F5) confirmed ACTIVE in the last 24h** — the corrections above do not
  change F1/F2/F3/F5/F6.

## Priority summary (F4 removed)

| # | Pri | Type | Sleeves | Mechanism |
|---|-----|------|---------|-----------|
| F1 | 🔴 P0 | code | 5× `poly_fast_taker_*` (active) | apply existing `TV_AGENT_FIX_LAGV2_SIGNAL_2026_06_01.md` + reset history |
| F2 | 🔴 P0 | **config only** | 2× dead BTC-5m sniper (active) | add to `TV_POLY_SNIPER_V5_KILL` env |
| F3 | 🔴 P0 | code | 3× `*_fade_momo_v2` (active) | populate `markov_regime` at t+60 (1-line wiring) |
| ~~F4~~ | — | ~~Kalshi band~~ | — | **WITHDRAWN — already live on Ireland (see scope correction)** |
| F5 | 🟠 P1 | review | `btc_5m_sniper_hod`, `eth_5m_momo_v2_HOLD_f7`, `*_v4` | shadow-only: never promote; disable only where a spec mandated it (momo_v2_HOLD) |
| F6 | 🟡 P2 | hygiene | — | commit the working tree; reconcile fee model |

Out of scope here (data-infra / lab, not a TV-agent code fix): hlcascade collectors (bybit+bitget empty),
SOL universe panel build, HL-liq staleness, INV_NIGHT cell-structure re-derivation. See audit §C.

---

## F1 — fast_taker signal inversion (CRITICAL, 5 sleeves)

**Sleeves:** `poly_fast_taker_lagv2_{btc_5m,eth_5m,btc_15m}`, `poly_fast_taker_b2_nomerge_{btc_5m,eth_5m}`.
**Root cause (CONFIRMED):** the trigger reads the **feed-vs-oracle basis** (`g_oracle_lag_bps_ge`,
persistently positive) instead of the **binance intra-window return** → all sleeves fire ~100% UP.
**Action:** a fix spec already exists — implement `strategy_lab/reports/TV_AGENT_FIX_LAGV2_SIGNAL_2026_06_01.md`
verbatim, then **reset the sleeves' fire/resolution history** (the all-UP fires poison any A/B). Confirm the
`b2_nomerge` variant is covered by that spec (same `g_oracle_lag_bps_ge` root) — if not, apply the same signal
swap to its gate.
**Verify:** after deploy, fired `direction` should split ~UP/DOWN per the binance return, not 100% UP.

---

## F2 — KILL 2 confirmed-dead sniper sleeves (CRITICAL, config only)

**Sleeves:** `poly_sniper_v5_btc_5m_q_parent15mslope_ts_imb5_v8` (**2,371 fires/7d!**) and
`poly_sniper_v5_btc_5m_ts_mpskew_any_off30` (274).
**Root cause (CONFIRMED):** both are look-ahead originals; full-period OOS WR = 51% (dead). The handoff already
flagged them as KILLs but **they are not in the kill set** and keep firing.
**Mechanism:** the sniper-v5 kill set is env-driven — `settings.tv_poly_sniper_v5_kill` (comma-separated
sleeve_ids) parsed into `_sniper_v5_kill_set` at `engine/main.py:2547`. No code change.
**Action:** append both sleeve_ids to the `TV_POLY_SNIPER_V5_KILL` env var (in the engine's `.env` / systemd
unit) and restart the engine.
**Verify:** `main.py` logs `kill_set_size=`; confirm it increased by 2 and the two sleeves emit 0 new
`poly_updown_signal` events.

---

## F3 — fade_momo_v2 dead m5v gate (P0, 3 sleeves)

**Sleeves:** `shadow_poly_updown_{btc_5m,sol_5m,sol_15m}_fade_momo_v2`.
**Root cause (CONFIRMED, traced end-to-end):**
- `FadeCompanionStrategy` (`strategies/polymarket/shadow9.py:517-551`) reads
  `regime = bctx.markov_regime_w20_5m_va`; if `None`/non-int → `m5v_pass = False` (line 526). Its guard
  `if hod_pass and m5v_pass: return "NONE"` (line 536) is the only thing that stops a fade.
- fade_momo_v2 fires at **t+60**, and the t+60 BarContext **hardcodes `markov_regime_w20_5m_va=None`**
  (`engine/poly_updown_loop.py:921`, with a comment admitting it was "left None … not in scope to change").
- ⇒ `m5v_pass` is **always False** ⇒ the guard never trips ⇒ the fade fires the contrarian on **every**
  momo_v2 signal, including the ones production would have taken (and won). That is the anti-edge
  (BTC 48.1% / SOL5m 47.9% / SOL15m 38.0% WR).

**Fix (mirror the already-correct t+120 path).** The t+120 builder computes the regime via
`_compute_m5v_regime(...)` (`poly_updown_loop.py:649`, assigned at `:688`). Do the same in the t+60 builder:

In `_build_bar_context_t_plus_60` (the block that builds the `BarContext` returned ~line 885), near the existing
t60 feature compute (~line 866), add:
```python
from backend.app.data.bars import get_feed_instance as _get_feed_m5v_t60
_m5v_t60 = _compute_m5v_regime(_get_feed_m5v_t60(), sym_upper, ws_s)
```
then change the BarContext kwarg (line 921) from:
```python
        # markov_5m left None here on purpose: the t+60 fade_momo_v2 sleeves
        # gate on it and are currently firing — not in scope to change.
        markov_regime_w20_5m_va=None,
```
to:
```python
        # FIX (shadow-audit 2026-06-01): compute 5m Markov regime so the t+60
        # fade_momo_v2 m5v gate actually functions (was always-False → fade
        # fired on every momo_v2 signal, negating the HoD/regime filter).
        markov_regime_w20_5m_va=_m5v_t60,
```
**Additive-safety:** base `momo_v2` ignores this field (per the existing comment), so only the fade/m5v sleeves
change behavior. **Verify:** `controller._fade_decisions` should now show `m5v_pass: true` on some fires;
fade fire-rate should drop; WR should move toward/above 50%.
**Alternative (if not fixing now):** disable the 3 `*_fade_momo_v2` via `TV_POLY_DEPRECATED_SLEEVES` (they are
net-negative as-is). Prefer the fix — it restores the validated design and keeps the A/B meaningful.

---

## F4 — Kalshi ema_down entry band — ✅ WITHDRAWN (already live on Ireland)

> **RESOLVED / false positive.** Operator confirms the `[0.15,0.93]` band IS implemented on the **live Ireland
> Kalshi sleeve**. The finding below was against the VPS3 *shadow-side* Kalshi config, which is the wrong box for
> the live sleeve. Retained only as a reference if the Ireland live engine is ever audited directly.

**Sleeve:** `kalshi_sniper_btc_15m_ema50_ema800_off600_down` (+ `_H`) — **LIVE on real money (Ireland)**.
**Root cause (CONFIRMED):** `TV_AGENT_SPEC_EMA_DOWN_V10_2026_06_01.md` deploys this sleeve **with band
`[0.15,0.93]`** (the validated edge: deepest-lottery <0.15 and no-upside ≥0.93 entries are −EV). The Kalshi
sleeve (`strategies/kalshi/sniper_kalshi_sleeves.py:58`) is a 1:1 port of the poly parent and carries **no
entry-vwap band gate** at all.
**Gate-bounds gap:** the existing primitives don't match — `g_entry_vwap_in_band` = `[0.20,0.80]`
(`sniper_v5_gates.py:1354`), `g_entry_vwap_in_band_narrow` = `[0.15,0.55]` (`:1367`). **Neither is `[0.15,0.93]`.**
**Fix:**
1. Add a band gate variant in `sniper_v5_gates.py` (next to the others):
```python
def g_entry_vwap_in_band_v10down(
    direction: str, fire_us: int, *, slug: str, book_mirror: Any,
    token_id_up: str, token_id_dn: str, **_kw: Any,
) -> bool:
    """ema_down V10 — book-walk vwap ∈ [0.15, 0.93] (drop deepest-lottery <0.15
    and no-upside favorites ≥0.93). Per EMA_DOWN_DEEPDIVE_2026_06_01.md."""
    v = _entry_vwap_for_dir(direction, slug, fire_us, 25.0, book_mirror, token_id_up, token_id_dn)
    return v is not None and 0.15 <= v <= 0.93
```
   (export it in `__all__`.) On Kalshi the entry-vwap source is the Kalshi book — ensure the band reads the
   Kalshi book-walk vwap, not a poly book.
2. Add `g_entry_vwap_in_band_v10down` to the gate list of the Kalshi `ema..._down` sleeve **and** `_H`.
3. **Apply the same band to the Poly V10 shadow A/B variant** so the same-venue A/B (poly parent no-band vs
   poly V10 band) is valid — confirm which poly sleeve_id is the V10 shadow and that it carries the band.
**Verify:** Kalshi fires with entry vwap <0.15 or >0.93 should drop to 0; compare banded vs parent per the
operator's A/B plan.

---

## F5 — disable spec-mandated-OFF sleeves still live (P1, config only)

**Sleeves & reason (all CONFIRMED still firing):**
- `poly_updown_btc_5m_sniper_hod` — explicitly **DO-NOT-DEPLOY** in its validating backtest; live WR 0.351 /
  −$436 (worst in fleet). *(Audit could not locate a positive spec for the sniper_hod family at all — treat the
  whole `*_sniper_hod` set as suspect; see audit family `updown_sniper_hod`.)*
- `poly_updown_eth_5m_momo_v2_HOLD_f7` — spec mandated **disable**; still active, WR 0.417 / −$280.
- `poly_updown_{btc,eth}_5m_v4` — `v4` = `v3_1` + V3.2 gates, but the value-add gate `liq_quiet` is
  **permanently disabled** (`liq_db=None`, `V3_2_LIQ_QUIET_ENABLED=false`) → v4 degenerates to ~v3_1. Either
  wire `liq_db` (re-enable `liq_quiet`) or retire `v4`.
**Mechanism:** poly-updown sleeves are disabled via the `TV_POLY_DEPRECATED_SLEEVES` CSV →
`_DEPRECATED_POLY_UPDOWN_SLEEVE_IDS` (consumed in `engine/main.py:1582/1650/1700/1749` and
`sleeve_manifest.py:287`). Add the sleeve_ids there and restart.
**Verify:** sleeves render in the dashboard "Deprecated" section and stop emitting signals.

---

## F6 — commit hygiene + fee-model reconciliation (P2, cross-cutting)

1. **Commit the working tree.** The engine runs uncommitted code (30+ modified files since May 29). Once F1–F5
   land, commit everything so the live behavior is reproducible and auditable (handoff open-item #3).
2. **Resolve the fee-model contradiction.** Audit found many backtests used **legacy 2%-on-profit** while the
   live engine + recent specs use the **0.07 curve** (`pnl_won=(1-vwap)·shares·(1-0.07·vwap)`, operator-confirmed
   2026-06-01). **CLAUDE.md still documents 2%-legacy as production** — these can't both be the baseline.
   Pick the source of truth, re-baseline every "expected WR/PnL" comparison on it, and correct CLAUDE.md.
   *(This bias affects almost every DISCREPANCY/data-gap finding's "expected" column.)*

---

## Note on the biggest loser (not a code fix — investigation)

`shadow_poly_updown_ALL_5m_phase1_kelly`: live WR **50.9% vs backtest 84.4%** (−$1,780/7d) — the most extreme
live≠backtest gap in the fleet. Audit's lead: most fires are the **1× Kelly tier (`fair_edge_bp<1000`, ~77% of
fires)** and the **S8 macd+rvol** sub-strategy that has no fair-edge floor → noise. The persistent edge is
`fair_edge_bp>1000` + ½-Kelly (the `fe1000_V10` variant, already running). Recommend: gate phase1_kelly on
`fair_edge_bp≥1000` (or retire the unfloored tiers) and re-measure — but validate in the lab first, not a blind
live edit.
