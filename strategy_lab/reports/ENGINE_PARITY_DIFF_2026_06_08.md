# VPS3 shadow vs Ireland live — engine line-by-line parity (2026-06-08)

Hosts run DIFFERENT git branches: VPS3 `deploy/vps3` (00253293), Ireland `deploy/ireland`
(7e9fc7d). Diffed `controllers/polymarket_sniper_v5.py` (409 lines differ),
`engine/poly_sniper_v5_loop.py` (8), `strategies/polymarket/sniper_v5_gates.py` (559),
`sniper_v5_sleeves.py`. Files in `migration_2026_06_08/engine_diff/`.

## A. V10 sleeve gates (eth_5m_l_ema50_hurst_grandparent_V10)
| gate | VPS3 vs Ireland | implication |
|---|---|---|
| g_tr_above_ema50 | **IDENTICAL** | divergence = feed only |
| g_hurst_trending | **IDENTICAL** | divergence = feed only |
| g_grandparent_trend_with | **IDENTICAL** | divergence = feed only |
| **g_sms_no_liquidity_above** | **🔴 DIFFERENT LOGIC** | real spec bug (below) |

### 🔴 g_sms_no_liquidity_above is a DIFFERENT gate on the two hosts
- **VPS3 shadow** = FIXED (`TV_FIX_SMS_NO_LIQ_20BAR_2026_06_03`): pass iff bar's high/low is
  NOT within 0.05% of the trailing-20-bar extreme → **~74% pass (matches the backtest)**.
- **Ireland live** = OLD pre-fix: `sms_liquidity_count_above==0` over 100-bar fractal swings →
  "almost never 0 → **~1% pass**".

⇒ The live V10 sleeve's 4th gate behaves nothing like the shadow/backtest. **Ireland never got
the `TV_FIX_SMS_NO_LIQ_20BAR_2026_06_03` patch that VPS3 has.** This alone makes live V10 a
different strategy from shadow V10. This is THE spec difference.

## B. Fill path — corrects the "synthetic fire on no book" premise
Both hosts already have `TV_FIX_UNIFY_BOOK_READ_PATH_2026_05_27`:
- **Empty book (all tiers)** → SKIP `empty_book_all_tiers_failed` (NO synthetic). Same both.
- **Sparse book (<25 events/60s)** → SKIP `sparse_book_under_25_events`. Same both.
- **The synthetic 0.5-vwap placeholder is GONE on both.** VPS3 paper does NOT synthetic-fire on
  an empty book — it skips, exactly like live.

So the shadow≠live fire gap is NOT synthetic firing. It is:
1. **Paper L25-walk vs live real order.** Paper fills via an L25 bid/ask walk on whatever asks
   exist in its own book snapshot — succeeds on THIN/WIDE books (the 199 missed fires had
   cross_spread median **0.282**). The live path places a real marketable order that can't fill
   on a one-sided/wide book → skips.
2. **`cross_spread` is logged-not-gated on BOTH** (`cross_spread_old` in the snapshot). The
   placement gate is the bid-ask spread vs `spread_filter=0.02` (same-token), identical on both.
   So a fire with tight bid-ask but cross_spread 0.28 passes paper AND would pass live's gate —
   it's the live FILL that fails, not the gate.
3. **Per-host feed** flips the gate-input (ema50/hurst/grandparent) at boundaries → Ireland
   never signals 87 of the 199 (cross-host, not code).

## C. Scalp `shadow_scalp_exit_btc_5m_d3_v1` — corrects the "shadow=TP, live=time-only" premise
Checked both hosts' dataclass defaults + the btc_5m_d3_v1 instance + the exit decision code:
- **BOTH hosts: `scalp_tp_enabled=False`, `scalp_stop_enabled=True`, exit +60s.** No instance
  override on either. The exit decision code (`mode=poll`: TP gated behind tp_enabled=False →
  never; stop_on=True; deadline → `time60`) is the SAME on both.
- ⇒ **Shadow and live run the IDENTICAL scalp exit: TP OFF, STOP ON, time +60.** There is NO
  TP-vs-time-only difference. (The live `scalp_tp065` exits you saw earlier were pre-06-07,
  before the TP-disable was deployed; current code on both hosts has TP off.)
- The only shadow/live scalp difference is the same fill difference (paper L25-walk vs real
  order) — NOT the exit policy. And the validated config keeps the STOP (per
  `SCALP_EXIT_CONFIG_BY_TF_2026_06_06`, +0.88/tr SIG); "time-only" would drop the stop, which
  the research says NOT to do.

## D. Other engine diffs (non-blocking)
- `_compute_spread`/`_book_dense_enough`: cosmetic — Ireland hardcodes the 60s window; VPS3
  parametrizes `window_s` (DISAGR-HAWKES uses 120s). Ireland adds a live `UserFillMirror`
  subscribe before firing. Core spread gate identical.
- gates file: VPS3 has extra gates (DISAGR-HAWKES etc.) Ireland lacks — irrelevant to V10/scalp.

## D2. EMPIRICAL TEST — is g_sms actually the divergence cause? NO (2026-06-08)
Live-on window = V10 went live **2026-06-05 → 06-09** (~4d). Since g_sms is the ONLY gate
between v8 and V10, its effective pass-rate = V10_fires / v8_fires per host:

| | v8 fires | V10 fires | g_sms effective pass |
|---|--:|--:|--:|
| VPS3 shadow (placed) | 355 | 302 | **85%** (fixed gate cuts ~15%) |
| Ireland live (resolved) | 204 | 219 | **~100%** (old gate barely filters) |

- **g_sms is NOT the cause.** Its effect is the OPPOSITE of the gap — Ireland's old gate passes
  *more* (≈100%), VPS3's fixed gate passes *less* (85%). If g_sms drove the gap, Ireland would
  fire MORE, not fewer.
- **The divergence is upstream, at the v8 3-gate level:** Ireland fires **204 v8 vs VPS3 355
  (~57%)** BEFORE g_sms applies. Cause = (1) per-host Binance feed flipping ema50/hurst/
  grandparent + (2) live wide-book execution rejects (the 87-never-signaled + 112-exec split).
- ⇒ Fixing g_sms on Ireland would make live ≈ backtest on that gate, but would NOT close the
  shadow↔live fire gap (that's feed + execution).

## D3. ⚠️ CORRECTION — window-matched comparison (the earlier divergence was mostly artifact)
The first parity pass compared mismatched windows (VPS3 shadow ~5d vs live ~3d). v8_LIVE ran
Jun1→5 then was REPLACED by V10_LIVE, which only became active **Jun7** (Jun5–6 = 1–2 turn-on
fires). Re-doing the slug overlap on the MATCHED window **Jun7–09** (distinct slugs, 1/slug):

| | distinct slugs |
|---|--:|
| VPS3 shadow placed | 132 |
| Ireland live placed | 112 |
| fired on BOTH | **103** |
| VPS3-only | **29** |
| Ireland-only | 9 |

- **Shadow and live AGREE strongly** (103 common). The earlier "199 VPS3-only / shadow
  overstates +$62" (`V10_SHADOW_VS_LIVE_PARITY_2026_06_08.md`) was a **window-mismatch artifact**
  — most of VPS3's "extra" fires were Jun4–6, before V10_LIVE existed. **RETRACTED.**
- **Ireland's 218 resolutions = 112 real (1/slug) + a 106-dupe RESOLUTION-LOGGING BUG on ONE
  slug** (`resolutions_per_slug: 112×1, 1×106`). Not real trades — a duplicate-logging bug to fix.
- Genuine matched divergence is small (29 VPS3-only + 9 Ireland-only) and is feed + wide-book
  execution, with g_sms a minor secondary effect. NOT the large gap first reported.

## E. The real parity actions (NOT applied — need a decision)
1. **🔴 Ship the fixed g_sms to Ireland** — deploy `TV_FIX_SMS_NO_LIQ_20BAR_2026_06_03` to
   `deploy/ireland` so live V10 runs the same 4th gate as shadow/backtest. **Biggest spec gap.**
   (Ireland engine change → TV agent / git deploy.)
2. **Make VPS3 paper reject un-executable wide books** — add a `cross_spread` gate to the paper
   fill path (currently logged-not-gated). ⚠️ This partially REVERTS the deliberate
   `TV_FIX_UNIFY_BOOK_READ_PATH` decision (which chose bid-ask over cross-token). Debatable; it
   would make shadow PnL stop counting un-fillable fires. Recommend as a spec, not a silent edit.
3. The literal "don't synthetic-fire on no book" is **already true** — no change needed there.
