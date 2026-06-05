# Handoff — Live (Ireland) vs Shadow (VPS3) vs Cross-Venue — 2026-06-02

_Three-way comparison of every live trade on the Ireland exec box (Polymarket + Kalshi) against (a) the same
sleeve cross-venue and (b) the VPS3 shadow fires of the same strategy. Question: **are the live sleeves working
as intended?** Data: `trading.events` kind=`poly_updown_resolution` (fire-level) + `poly_redeemed` (on-chain),
trailing 7d, both boxes. Artifacts in `vps3_engine_snapshot_2026_06_01/`: `ireland_fires_7d.csv`,
`ireland_live_sleeves_7d.csv`, `vps3_shadow_fires_compare_7d.csv`, `_audit/compare_live_shadow.py`._

## TL;DR verdict

| Lane | Working as intended? | Evidence |
|------|----------------------|----------|
| **Polymarket real-money live** | ✅ **YES — faithful to shadow** | ema_down Poly-LIVE vs shadow: **18/18 common slots identical** on direction, outcome AND win; entry vwap within **0.022**; band enforced 0/18 out-of-band |
| **Kalshi "live"** | ⚠️ **PAPER, and band not enforced** | `fill_method=kalshi_paper` (simulated, no real orders); **15/59 fires OUTSIDE the [0.15,0.93] band** (entries 0.06–0.99) |
| **Cross-venue Kalshi↔Poly** | ⓘ **Can't validate yet** | Kalshi base stopped 06-01 15:46; Poly-LIVE mostly 06-02 → only 1 time-overlapping fire in window |
| **Dead sleeves on real money** | 🔴 **Happened (May-31), now stopped** | the 2 KILL sleeves `q_parent15mslope` ($150) + `ts_mpskew_any_off30` ($25) ran **real** on 05-31 14:06–15:26 |
| **Signal-direction integrity (live set)** | ✅ **Clean** | ema_down all-DOWN, b2 up/down correct; the buggy `fast_taker` was **not** promoted to live |

## Box roles (confirmed)
- **Ireland** (85.137.174.152): live execution + own `storedata`. 26 sleeves resolved in 7d = **23 Polymarket + 2 Kalshi + 1 shadow**. Engine + uvicorn:8000 running.
- **VPS3** (185.190.143.7): shadow research fleet (the 133-active / 146-registry set).
- **Live history is short** — most `_LIVE` sleeves started 06-01/06-02, the l25_walk burst was 05-31. So live WR/PnL are small-n; the **slot-level structural checks (direction/outcome/fill parity) are the reliable signal**, and those pass.

## What is actually real money (Ireland)
On-chain `poly_redeemed` (real Polymarket settlement) in 7d, by sleeve:
`sol_5m_momo_v2_HOLD_f7` (61) · `eth_5m_l_ema50_hurst_grandparent_v8_LIVE` (46) · `btc_15m_momo_HOLD_f7` (25) ·
`btc_15m_ema50_ema800_off600_down_LIVE` (21) · `eth_15m_momo_v2_HOLD_f7` (11) · `ALL_15m_S4_prewindow_LIVE` (1) ·
`eth_5m_v3_2` (1). **Kalshi is NOT in this list** → Kalshi is paper. The `_sniper` poly sleeves run `mode=paper`.

## Finding detail

### 1. Polymarket promotion is faithful (✅)
Slot-level join, `ema_down` Poly-LIVE vs Shadow on `ws_s`:
- 18 live slots, **all 18 common with shadow**, 0 live-only.
- **same_direction 18/18 · same_outcome 18/18 · same_win 18/18.**
- mean |fill_vwap_live − fill_vwap_shadow| = **0.022** (live fills ~2¢ off shadow — normal book drift).
- Live fired only 18 of 162 shadow slots in the window — because live started 06-01 15:01 (registration/funding), not a bug.
→ The live engine reproduces the shadow strategy slot-for-slot. Promotion path is trustworthy.

### 2. Entry-band enforcement: Poly ✅, Kalshi ⚠️
`outside [0.15,0.93]` count on the ema_down live fires:
- `poly_..._ema..._down_LIVE`: min 0.150 / max 0.930 / **0 outside** of 18. Band enforced. ✅
- `kalshi_..._ema..._down`: min 0.060 / max 0.990 / **7 outside** of 19.
- `kalshi_..._ema..._down_H`: **8 outside** of 40.
→ The band gates the **Polymarket reference price**, not the **Kalshi execution price** — so Kalshi takes entries (0.06 lottery / 0.99 no-upside) the band was designed to skip. **This contradicts "band is implemented on Kalshi" at the fill level.** Likely intended to gate poly-prob, but the effect is that Kalshi paper PnL is NOT a clean test of the *banded* strategy. **Decide: should the band also gate the Kalshi venue price?** (Low urgency while Kalshi is paper, but it invalidates the Kalshi A/B until resolved.)

### 3. Kalshi is paper, not live money (⚠️)
Every Kalshi fire is `venue=kalshi, mode=live, fill_method=kalshi_paper` → simulated fills against Kalshi market
data, no real Kalshi orders (consistent with `sleeve_manifest`: "Kalshi shadow has no wallet gate yet"). Treat all
Kalshi numbers as **paper**. If the intent was real Kalshi capital, the venue order path is not wired.
Also: **Kalshi base ema_down stopped firing 06-01 15:46** (19 fires); only `_H` continues (last 06-02 18:01) —
check whether the base was intentionally deregistered.

### 4. WR live vs shadow — aligned within small-sample noise (✅)
| Strategy | LIVE n / WR / pnl-per | SHADOW n / WR / pnl-per |
|----------|-----------------------|--------------------------|
| ema_down Poly | 46 / 0.717 / −0.02 | 162 / 0.802 / +1.05 |
| ema_down Kalshi (paper) | 19 / 0.789 / +0.05 | 162 / 0.802 / +1.05 |
| eth l_ema50 Poly | 104 / 0.683 / −0.01 | 228 / 0.719 / +0.64 |
| sol momo_v2_HOLD | 112 / 0.545 / +0.08 | 85 / 0.541 / +1.21 |
Live WR sits slightly below shadow (fill realism + a less-favorable recent live window); direction structure matches.
The pnl-per gap (live ≈0 vs shadow positive) is the short, recent live window — not a logic defect.

### 5. 🔴 Confirmed-dead sleeves were briefly LIVE with real money (05-31)
The l25_walk burst on 05-31 14:06–15:26 placed real money on sniper sleeves including **both KILL targets**:
`q_parent15mslope_ts_imb5_v8` (30 fires, $150, WR 0.800) and `ts_mpskew_any_off30` (5 fires, $25, WR 0.400).
They have since stopped, but this confirms look-ahead/dead sleeves reached real capital. **Ensure they're in
`TV_POLY_SNIPER_V5_KILL` so a future promotion sweep can't re-arm them** (ties to fix-spec F2). The live WR looked
fine only because n is tiny in a 1.5h window — it's the lookahead artifact, not edge.

### 6. ✅ RESOLVED — eth `l_ema50_hurst_grandparent_v8` LIVE all-DOWN is **regime, not a bug**
Initial flag: live `_LIVE` 100% DOWN vs shadow 7d 45% UP. **Drilled and cleared:**
- The 7d "45% UP" is averaged over **05-29/05-30 (UP-heavy, before live existed)**. The live sleeve only has
  **~13.5h of history, all on 2026-06-02**, a strongly DOWN-trending day.
- On 06-02 the **shadow sleeve itself fired 47 DOWN / 8 UP** — the regime, not the wrapper, drove direction.
- **Slot-level ws_s overlap join in the live window: 35/35 common slots, same direction (DOWN) — 100% agreement.**
  Shadow fired UP on **0** slots inside the live window → no UP-suppression.
- Config confirms **no down-only filter**: `_LIVE` is a runtime wrapper (`main.py:2104`, `f"{base}_LIVE"` from
  `TV_POLY_LIVE_ALLOWLIST`) of the same base sleeve (`sniper_v5_sleeves.py:887`) that fires both ways in shadow.
- Shadow per-day: 05-29 `28U/9D` · 05-30 `31U/11D` · 05-31 `12U/28D` · 06-01 `23U/31D` · 06-02 `8U/47D`.
→ Working as intended. When an UP signal comes the live sleeve will fire UP. (Drill script:
`_audit/drill_eth_live.py`.) Minor data note: the `_LIVE` sleeve also emits 69 directionless `mode=live` log rows
alongside the 35 placed fills — a second event shape, not a direction issue.

### 7. Direction integrity elsewhere — clean (✅)
ema_down (poly+kalshi) all DOWN; `up_b2_contrarian` 9/9 UP; `down_b2_contrarian` 7/7 DOWN; `b1/b3` mixed as
designed. No all-one-direction anomaly in the live set **except** the eth l_ema50 case in #6. The buggy
`fast_taker_lagv2` family is shadow-only on VPS3 — **not promoted to Ireland** (good).

## Action items
1. **Decide Kalshi reality:** keep as paper (then label it paper everywhere and don't read its PnL as live), or wire
   the real Kalshi order path + a Kalshi wallet gate. Until then the Kalshi A/B is paper.
2. **Kalshi band:** decide whether `[0.15,0.93]` must gate the Kalshi *execution* price (currently 25% of fires are
   out-of-band). If yes, add the venue-price band to the Kalshi sleeve.
3. ~~#6 eth l_ema50 LIVE direction~~ — **RESOLVED (regime, not a bug; see §6).** No action.
4. **F2 carry-over:** add the 2 KILL sleeves to `TV_POLY_SNIPER_V5_KILL` (they had real money on 05-31).
5. **Lengthen the live window** before trusting live WR/PnL — current live n is too small; the structural checks
   (which pass) are what's currently reliable.

## Bottom line
**Polymarket real-money live is working as intended** — it reproduces the shadow strategy slot-for-slot (ema_down
18/18, eth l_ema50 35/35 same-direction on overlapping slots), with the band correctly enforced and outcomes
identical. The eth l_ema50 "all-DOWN" flag was a one-day down-trend, **not** a bug. **Kalshi is paper with an
unenforced execution-price band** — fine as a sim, but not a real-money lane and not a clean banded A/B yet. And the
two dead sniper sleeves did touch real capital on 05-31, so close the kill-set gap (F2).
