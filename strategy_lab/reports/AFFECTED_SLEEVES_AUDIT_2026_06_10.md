# Affected-sleeve list — retro-audit problems mapped to the live/shadow fleet — 2026-06-10

Ground truth pulled 2026-06-10/11: Ireland `trading.events` (3d), VPS3 `trading.events` (3d, ~190 active sleeves),
live engine code on both hosts (`sniper_v5_sleeves.py`, `sniper_kalshi_sleeves.py`, `poly_updown_loop.py`,
`config.py`), env. Problem codes from `RETRO_MASTER_AUDIT_2026_06_10.md` (C1–C10) + the 06-01 fix specs (F1–F6)
+ the 06-02 bleeder kill list (A3).

**Verified FIXED (no action):** F1 lagv2 signal (50/50 since 06-04) · TP-off/stop-on on Poly scalp BOTH hosts
(`scalp_tp_enabled=False / scalp_stop_enabled=True` defaults confirmed in code) · `l_1hrf_imb5_ribbon_v8` retired
06-08 · phase1_kelly + a25_merge gone · F6 committed.

---

## 1 — REAL MONEY (Ireland live) — every live sleeve is affected by something

| Sleeve (live $) | Problem |
|---|---|
| `shadow_scalp_exit_btc_5m_d3_v1_LIVE` | **C1+C2+C4+C5**: its offline validation (magnitude +$2–5/tr) is tainted — outcome-leak exit fallback, burned OOS window, pseudo-prereg DSR, no sell-leg size cap. Config itself correct (TP off, stop on ✓). Also trades real $ before the ≥200-fire gate. Judge ONLY by realized live PnL until E1 re-validation. |
| `shadow_scalp_exit_btc_15m_d3_v1_LIVE` | Same as above. |
| `shadow_scalp_momalign_btc_5m_v1_LIVE` | Same C1/C2 taint (momalign variant validated with the same harness + burned window), n live = 6 fires only. |
| `poly_sniper_v5_btc_15m_ema50_ema800_off600_down_LIVE` | **C3**: never passed a deflated test; band [0.15,0.93] derived on the in-sample GA panel. Evidence grade B. One of the "edge 4" — strongest of the directional set, but magnitude unverified. |
| `poly_sniper_v5_eth_5m_l_ema50_hurst_grandparent_v8_LIVE` | **C3** + audit found it ≈ breakeven live after fill haircut (shadow +$62 → live +$1.1). Never deflated. |
| `poly_sniper_v5_eth_5m_l_ema50_hurst_grandparent_V10_LIVE` | **C3** + V10 gates (`sms_no_liq` etc.) are in-sample only. Last events 06-09 — confirm if intentionally retired. |
| `poly_sniper_v5_eth_5m_cloud_vwap_hurstmp_v7_LIVE` | **C3**: deployed 06-09 (spec `TV_AGENT_SPEC_DEPLOY_CLOUD_VWAP_V7_LIVE`) with no trial-counted DSR — post-rigor deploy that skipped the rigor. |
| `kalshi_sniper_btc_15m_ema50_ema800_off600_down` (Ireland Kalshi) | Per 06-02 forensics: **kalshi_paper (simulated, NOT real orders)** + **band not enforced on the Kalshi fill price** (15/59 out-of-band) + settles on Kalshi index, not Chainlink. Confirm current paper-vs-real status before trusting its PnL. |

## 2 — VPS3: confirmed-DEAD sleeves still firing (F2 kill NEVER executed — `tv_poly_sniper_v5_kill` is EMPTY, verified in config.py:509 + env)

| Sleeve | Problem |
|---|---|
| `poly_sniper_v5_btc_5m_q_parent15mslope_ts_imb5_v8` | **Confirmed look-ahead original, full-period 51% WR, −$930.** Still the single BIGGEST firer in the fleet (18,629 events/3d). On the F2 kill list since 06-01; kill env never set. |
| `poly_sniper_v5_btc_5m_ts_mpskew_any_off30` | Same: confirmed look-ahead original, −$93 full-period. 2,246 events/3d. F2 kill never executed. |

## 3 — VPS3: F3 fade-markov fix NEVER applied (verified: `poly_updown_loop.py:985` still `markov_regime_w20_5m_va=None` with the original "not in scope" comment)

| Sleeve | Problem |
|---|---|
| `shadow_poly_updown_sol_15m_fade_momo_v2` | m5v gate permanently False → fades EVERY momo_v2 signal incl. the winners = the anti-edge (38% WR documented). Fix specced 06-01, never landed. |
| `shadow_poly_updown_eth_15m_sniper_m5v`, `shadow_poly_updown_sol_5m_momo_v1_m5v` | ⚠️ Gate on m5v — if they evaluate at t+60 their m5v gate is also dead (t+120 path is fine). VERIFY which builder they use. |
| `shadow_poly_updown_{btc_5m,eth_15m,sol_5m}_fade_sniper` | Fade family siblings — verify whether they share the dead m5v guard; if yes, same anti-edge mechanics. |

## 4 — VPS3: 06-02 bleeder kill list (A3, −$19.8k bucket) — still firing

| Sleeve | Problem |
|---|---|
| `poly_sniper_v5_btc_5m_l_1hrf_imb5_rf_v8` | The named "trap-at-scale" bleeder (76% WR, −$611, t=−4.7). Still firing 16,890 events/3d. A gate fix was specced 06-03 (`TV_AGENT_FIX_L1HRF_IMB5_GATE`) — verify if applied and whether post-fix PnL justifies keeping; otherwise kill. |
| `poly_updown_btc_15m_volume_INV_NIGHT` | INV_NIGHT family = worst bleeder bucket (−$10k/6 sleeves). 5 of 6 retired; this one still fired through 06-10. |
| `poly_updown_{btc_15m,eth_15m}_sniper_hod`, `poly_updown_sol_5m_sniper_hod` | sniper_hod was on the F5 disable list (06-01). Still firing. |
| `poly_updown_*_momo_v2_HOLD_f7` ×6 + `momo_HOLD_f7` ×4 (btc/eth/sol, 5m/15m) | momo_v2_HOLD was on the F5 disable list. Still firing on all markets. |

## 5 — VPS3: entire scalp A/B fleet — validation tainted (C1/C2/C5), config OK

All **54** `shadow_scalp_exit_{btc,eth,sol,doge,xrp,bnb}_{5m,15m}[_d3][_tod2][_notp][_control]_v1` +
`shadow_scalp_momalign_btc_5m_{v1,control_v1}` + `kalshi_scalp_exit_btc_15m_d3_{v1,notp_v1}`:
- **Not a code bug** — the live TP-off/stop-on config is right. The problem is their offline baseline expectation
  (+$1.7–2.5/tr gated) is inflated by C1 (outcome-leak fallback), C2 (burned OOS), C5 (no sell-size cap). Their
  realized shadow $/tr will likely come in BELOW the backtest — do not interpret that as "edge decayed"; the
  baseline was too high. Judge by live CI vs 0, not vs backtest.
- `_tod2` variants: the TOD gate was partly validated on the burned window → MEDIUM trust, owes a trial-counted DSR.
- **Kalshi `_v1` vs `_notp_v1` A/B is meaningless as coded**: both inherit `scalp_tp_enabled=False` from the
  dataclass defaults (verified in `sniper_kalshi_sleeves.py:135-175` — neither sets the flag) → identical exit
  configs. Either set `scalp_tp_enabled=True` on the `_v1` twin or retire the redundant pair.
- Shadow `sell_leg_fee=0.0` still optimistic (06-06 item, unfixed).

## 6 — VPS3: all ~90 GA directional sniper sleeves — C3 (no deflated test exists)

Families: `poly_sniper_v5_{btc,eth,sol}_{5m,15m}_*` v6/v7/v8/v9/V10/vL (incl. the remaining "edge 4" members
`btc_15m_mpskew_trstack_off600_down`, `btc_15m_ts_trstack_off600_down`), all `poly_updown_*` momo/vwap/hod
variants, `shadow_sniper_eth_5m_cloud_AND_hurst_v1`, `shadow_disagr_hawkes_sol_5m_dn`, fairedge/cvd_macd
shadows. Problem: selected from a 10³–10⁴ config search judged on raw t-stats over single windows; the GA panels
were their own training data. They are legitimate as a **shadow A/B forward test** (that IS the honest experiment)
— but none has standing to go live on backtest evidence, and fleet-level "4 edge sleeves at t≥2" is exactly what
multiple testing manufactures. Rank them only on the TV dashboard dedup metric (not raw `events.pnl_usd`).

`shadow_oracle_settle_*` ×6: fine — underpowered selector accruing power by design.
`ALL_15m_S4_prewindow` (+ kalshi twin): fires via `reason=order_placed`, never sets `all_gates_passed` →
**invisible to all_gates_passed-based dashboards** — known blindspot, unfixed.
`poly_fast_taker_*` ×6: F1 fixed ✓ — monitoring item only (AC-4 WR rebuild toward ~65% needs n≥100; currently ~43-54%).

---

## Action shortlist (in order)
1. **Execute F2 now** — set `TV_POLY_SNIPER_V5_KILL=poly_sniper_v5_btc_5m_q_parent15mslope_ts_imb5_v8,poly_sniper_v5_btc_5m_ts_mpskew_any_off30` + restart. Two confirmed-dead sleeves are 20% of fleet event volume.
2. **Apply F3** (markov at t+60) or disable the fade/m5v sleeves; verify fade_sniper + the 2 `*_m5v` sleeves' builder.
3. **Sweep the A3 stragglers**: INV_NIGHT ×1, sniper_hod ×3, momo(_v2)_HOLD_f7 ×10, decide on `l_1hrf_imb5_rf_v8` post-gate-fix.
4. **Fix the Kalshi notp A/B** (identical twins) + set shadow `sell_leg_fee` to the real curve.
5. **E1 re-validation** (from the retro) before any scalp size-up; until then judge all scalp sleeves by live CI only.
6. Confirm intent: V10_LIVE silent since 06-09; Ireland Kalshi paper-vs-real status.
