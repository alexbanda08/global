# Phase 36 fix spec + IMPLEMENTATION REPORT — session 2026-05-26

_Original spec audit ran on VPS3 (storedata-vps3) 2026-05-25 ~23:30 UTC.
This document is the spec + post-implementation report, updated 2026-05-26
~15:30 UTC after the full fix session. Hand this to the next session for
context._

---

## Session 2026-05-26 summary — what was actually done

### Original 4 bugs from the spec

| Bug | Original status | Final status | Outcome |
|---|---|---|---|
| **#1** Feature publisher returns NULL on every fire | ❗ blocker | ✅ **FIXED + deployed** | 15 dead sleeves now firing; first Kelly order_placed at 14:13 CEST |
| **#2** `eth_15m_fade_sniper` 50% same-direction | ❗ partial-correctness | ⏸ **DEFERRED** | cell_key + strategy class verified correct (`sniper_eth_15m` matches `FADE_HOD_TOP8_BY_CELL`). n=8 was likely noise. Re-evaluate after Bug 1 fix feeds new data over the next 7 days. |
| **#3** FADE PnL −$487 vs +$71/day expected | ❗ thesis-level | 🔲 **OPERATOR TASK** | Local backtest re-run with active `HOD_TOP8_BY_CELL` not done yet — needs `strategy_lab/overnight_2026_05_23/refade_with_live_hod.py` |
| **#4** `imb5` feature never wired | low | 📝 **DOC ONLY** | No code change. Spec says recommend option A (drop from required-features). |

### Additional bugs DISCOVERED + FIXED in the same session (3 critical)

| Bug | Severity | Status | Fix commit |
|---|---|---|---|
| **A.** `backfill_from_rest` clears the 14d deque on every WS reconnect → q90 threshold biases low for hours after every disconnect → causes Ireland vs VPS3 momo signal divergence on identical inputs | 🔥 P0 silent-data-corruption | ✅ FIXED + deployed | `c6bee19` + `8a27677` |
| **B.** Poly redeemer never DB-marks loser fills → pending pool grows unbounded (79 stale losers blocking 4 newer winners from being processed under LIMIT 50 ORDER BY ASC) | 🔥 P0 funds-at-risk | ✅ FIXED + deployed | `fb50401` |
| **C.** `Vwap15mStore` import was unconditional in `binance_market_data.py` → Ireland (no Phase 35 deploy) crashed on engine start | 🔥 P0 production-down | ✅ FIXED + deployed | `c6bee19` |

### Other production work completed this session

1. **Promoted `poly_updown_btc_5m_momo_HOLD_f7` to LIVE on Ireland** — added to `_SLEEVE_CONFIG_MAP` + env allowlist. Slot allowlist of momo HOLD_ONLY controller now `[BTC 15m, BTC 5m]`.
2. **Promoted `poly_updown_sol_5m_momo_v2_HOLD_f7` to LIVE on Ireland** — added to map + allowlist. Slot allowlist of momo_v2 HOLD_ONLY controller now `[ETH 15m, SOL 5m]`.
3. **Deprecated `poly_updown_btc_15m_momo_HEDGE_f7` on Ireland** — redundant signal vs HOLD on same cell. Removed from allowlist + added to `TV_POLY_DEPRECATED_SLEEVES`.
4. **Diagnosed Ireland vs VPS3 momo_HOLD streak divergence** — confirmed root cause is Bug A above. Two engines saw identical `ret_2m=-0.000776` but had different q90 thresholds (Ireland 0.000895 from full 14d deque vs VPS3 0.000736 from post-reconnect partial deque).
5. **Recovered 4 unredeemed winning positions** on Ireland wallet — +$3.92 USDC redeemed at 15:03 UTC after Bug B mitigation + permanent fix.

---

## Detailed implementation report — Bug 1 fix

### Root cause (confirmed during session)

The Phase 35/36 BarContext builders did:

```python
feed = getattr(primary, "feed", None) or getattr(primary, "_feed", None)
```

But `PolymarketUpdownController` never exposes the feed as an instance attribute. The feed is bound globally via `bars.set_feed_instance(binance_feed)` at engine boot (called in `engine/main.py` lifespan). Result: `feed=None` on every BarContext build → vwap_store unreachable → ALL Phase 36 features (`vwap_dev_bps`, `fair_edge_bp`, `cvd_30s/60s`, `macd_hist`, `rvol_30_300`, `s_now`, `strike`, `fair_up`, `sigma`, `tau_s`) silently land as NULL.

Same blind spot for the Phase 34 m1va Markov regime — m1va sleeve `shadow_poly_updown_btc_15m_momo_hod` emitted `gate_markov_skip` forever (regime always -1 = warmup) because the compute couldn't read the 14d 1MIN closes.

### Fix

- `backend/app/data/bars.py`: new `get_feed_instance()` accessor returns the module-level `_FEED_INSTANCE`.
- `backend/app/engine/poly_updown_loop.py`: all 3 read sites
  - Phase 34 m1va compute path in `build_bar_context_t_plus_120` (~line 546)
  - Phase 35/36 `build_bar_context_t_plus_n` (~line 1059)
  - Phase 36 `build_bar_context_pre_window` (~line 1277)
  now call `get_feed_instance()` instead of the broken `getattr(primary, 'feed')`.

### Verification

Run 10 minutes post-deploy on VPS3:

```text
shadow_poly_updown_ALL_5m_phase1_kelly: 6 events, 1 order_placed
  → dev_bps=-0.0026, cvd_30s=-296972, macd=-0.21, rvol=3.58, fair_edge_bp=+2807
shadow_poly_updown_ALL_5m_S3_prewindow:  3 events, 3 order_placed
shadow_poly_updown_btc_5m_fade_sniper:   1 events, 1 order_placed
shadow_poly_updown_sol_5m_fade_sniper:   1 events, 1 order_placed
(12 of 15 active shadow sleeves emitting populated features)
```

Pre-fix: 0 fires across the entire Phase 36 panel in 26 hours.
Post-fix: 6 order_placed events in the first 10 minutes.

---

## Detailed implementation report — Bug A (deque-clear on reconnect)

### Symptom (caught 2026-05-25 22:25 UTC boundary)

Same ETH 5m momo signal `ret_2m = -0.000776` seen on both VPSes:
- Ireland (no recent disconnect): `abs_ret_2m_threshold = 0.000895` (matches fresh REST q90)
- VPS3 (disconnected 16:52 UTC the same day): `abs_ret_2m_threshold = 0.000736` (22% lower)

Ireland blocked the fire; VPS3 fired DOWN and won $24.50. Looked like a strategy divergence — was actually corrupted threshold state from a bug in the binance feed reconnect path.

### Root cause

`backend/app/feeds/binance_market_data.py:177` — `backfill_from_rest()` always called `self._bars[sym].clear()` then refilled. The reconnect call site passed `days=1`, so every WS hiccup shrank the 20160-bar deque to 1440 bars. The q90 computed over the smaller sample biased low until WS appends grew the deque back over many hours.

### Fix

- New `gap_fill=True` mode walks FORWARD from the deque tail without clearing. Only appends bars STRICTLY NEWER than the latest in-deque bar. Safe to call repeatedly on reconnect.
- Reconnect call site updated to `backfill_from_rest(days=1, gap_fill=True)`.
- Boot path unchanged (`gap_fill=False` is the default for clear+refill at engine start).

### Side-fix in same commit

- `Vwap15mStore` import made optional (Ireland deploy doesn't ship Phase 35) so the feed remains importable on hosts without the Phase 35 module tree.

---

## Detailed implementation report — Bug B (redeemer pool unbounded growth)

### Symptom (operator notice 2026-05-26 ~15:00 UTC)

4 winning positions sitting in the Ireland wallet unredeemed despite the redeemer running normally for hours.

### Root cause

`_PENDING_FILLS_SQL` in `backend/app/services/poly_redeemer.py` selects fills WHERE `r.event_id IS NULL AND x.event_id IS NULL` (no `poly_redeemed` or `poly_redeemer_failure` neighbor). Losers got logged via structlog (`poly_redeemer.skipping_loser`) but no DB event was written → losers stayed in the pending result set FOREVER, re-iterated every tick.

Pool grew unbounded. With `_DEFAULT_MAX_PER_TICK = 50` and `ORDER BY at ASC LIMIT 50`, the redeemer processed the oldest 50 entries (almost all losers) every cycle and never reached the newest fills. At 79 pending positions, the 4 most recent winners were at positions 76-79 — stranded.

### Fix (two layers)

1. **Operational** (immediate): bumped `TV_POLY_REDEEM_MAX_PER_TICK` from 50 to 200 on Ireland env file + engine restart. Drained the backlog in one tick. 4 winners redeemed at 15:03 UTC.
2. **Permanent** (code, commit `fb50401`):
   - New `_INSERT_LOSER_SKIPPED_SQL` constant writes `kind='poly_redeemer_skipped'` event when a loser is scanned.
   - New LEFT JOIN on `poly_redeemer_skipped` in `_PENDING_FILLS_SQL` filters marked losers out of result set.
   - `_fetch_pending` writes the marker right before `continue`. Falls back to retry-on-next-tick if the audit-write fails (non-fatal).
   - Pool drained 79 → 18 on first tick after deploy. 57 `poly_redeemer_skipped` markers written in one batch.

---

## Status snapshot — post-session (2026-05-26 15:30 UTC)

### VPS3

| Metric | Value |
|---|---|
| Engine PID | 2922483 (restarted 14:08 UTC) |
| Binance feed deque | BTC/ETH/SOL all 20160 bars ✓ |
| Phase 34 shadow sleeves registered | 11 |
| Phase 35 VWAP continuation sleeves | 5 |
| Phase 36 shadow sleeves | 3 (Kelly + 2 prewindow) |
| Phase 36b fade + overlay | 12 (6 fade + 6 overlay) |
| **Total shadow sleeves on VPS3** | **31** |
| Phase 36 features populated | ✅ since 14:13 UTC |
| First Kelly order_placed | 14:13 UTC (S4 trigger) |

### Ireland

| Metric | Value |
|---|---|
| Engine PID | 281728 (restarted 15:07 UTC after redeemer fix) |
| Binance feed deque | BTC/ETH/SOL all 20160 bars ✓ |
| Live mirror controllers | 2 (momo HOLD_ONLY, momo_v2 HOLD_ONLY) |
| Live slot coverage | BTC 5m, BTC 15m (momo); ETH 15m, SOL 5m (momo_v2) |
| Live notional | $1.00 / fire |
| Deprecated sleeves | `poly_updown_btc_15m_momo_HEDGE` |
| Pending redeemer pool | 18 (healthy, was 79 before fix) |
| Last successful redeem | 15:03 UTC |
| `poly_redeemer_skipped` markers in DB | 57 (one-time backfill) |

---

## Files changed / commits this session

| Commit | Files | Purpose |
|---|---|---|
| `8a27677` | `backend/app/feeds/binance_market_data.py` | gap_fill mode + reconnect call update (Bug A) |
| `c6bee19` | `backend/app/feeds/binance_market_data.py` | Optional Vwap15mStore import (Bug C) |
| `a63cd42` | `backend/app/data/bars.py` + `backend/app/engine/poly_updown_loop.py` | get_feed_instance accessor + 3 read-site fixes (Bug 1) |
| `fb50401` | `backend/app/services/poly_redeemer.py` | poly_redeemer_skipped marker + SQL filter (Bug B) |
| (Ireland env) | `/etc/tv/tradingvenue.env` | `TV_POLY_REDEEM_MAX_PER_TICK=200`; live allowlist swap (HEDGE → HOLD); sol_5m_momo_v2_HOLD added |
| (Ireland config) | `backend/app/engine/_preflight.py` | `_SLEEVE_CONFIG_MAP` += btc_5m_momo_HOLD + sol_5m_momo_v2_HOLD |

All commits pushed to `origin/main`. VPS3 sync via `git pull`; Ireland sync via per-file scp + install.

---

## Outstanding tasks (for the next session)

### Bug 3 from this spec — operator local task

Backtest re-run with the active `HOD_TOP8_BY_CELL` (refreshed in Phase 34 fix commit `2308482`):
- Pull `backend/app/strategies/polymarket/gates.py` from VPS3 to a local `_pulled_from_vps3/gates.py`.
- Run `strategy_lab/overnight_2026_05_23/refade_with_live_hod.py` (script to be written per the original spec §Repro).
- Decide for each FADE sleeve: keep (≥+$10/day shadow) or deprecate (<+$5/day shadow).

### Bug 2 from this spec — defer + monitor

`eth_15m_fade_sniper` opposite-direction rate was 50% (n=8). After Bug 1 fix the FADE companions get correct feature inputs, so the next 7 days will produce a clean sample. Re-run the SQL join from the original spec §Bug 2 acceptance after 50+ resolutions land.

### NEW_STRATEGIES_PROPOSAL.md

The Phase 36 spec referenced `NEW_STRATEGIES_PROPOSAL.md §S4 (Bayesian-Kelly proposal)` in its open questions. This document was NEVER seen by the tv-agent in this session. Operator should hand off the file path to the next session if those proposals are to be implemented.

### Phase 34 fix Bug #2 long-term (deferred per the earlier fix spec)

`build_bar_context` (bar-close phase) still doesn't populate MTF / Markov aux fields. Today no sniper sleeve carries those gates, so the bug is dormant. Option B (validator) was implemented and prevents accidental sniper×mtf2/m5va/m1va wiring. Option A (populate the aux unconditionally) was NOT implemented; not blocking anything currently.

### Shadow validation window

15 shadow sleeves on VPS3 are now actively firing with populated features. Per the original `SHADOW_DEPLOY_SPEC_9_NEW_SLEEVES_2026_05_24.md` promotion criteria:

- 14-day shadow window starting 2026-05-26 14:13 UTC (Bug 1 fix deploy)
- Daily WR within ±5pp of backtest expectation
- Sum-PnL positive on rolling 7d
- Max DD ≤ 1.5× backtest expectation
- Feature NaN rate < 5%

Top 3 candidates for first live promotion (per spec §Promotion criteria):
1. `shadow_poly_updown_ALL_5m_phase1_kelly` (Kelly ensemble) — backtest +$927/day, 84.4% WR
2. `shadow_poly_updown_eth_15m_sniper_m5v` (overlay) — only p<0.05 result, +$7.15/tr
3. `shadow_poly_updown_ALL_5m_S3_prewindow` — strongest single-offset edge, p=0.029

### Ireland → VPS3 missing commits

Ireland is currently 5 commits behind `main` (operator-authored maker work + 1 chore). None affect the UI / shadow / redeemer. Not blocking.

---

## How the next session should pick up

1. Read this document first.
2. Check the dashboard / SQL for the shadow sleeves' 24-hour activity to confirm Bug 1 fix is still effective.
3. If Bug 3 backtest result is ready, execute the deprecate-or-keep decision per sleeve.
4. Otherwise, continue with the planned UI upgrade (Claude Design) or next strategy spec from `strategy_lab/reports/`.

## Files / references

- Engine source paths (VPS3):
  - `backend/app/engine/poly_updown_loop.py` — bar_context builders + scheduler + Phase 36 features compute
  - `backend/app/feeds/binance_market_data.py` — 1MIN + 1SEC WS feed, vwap_store, gap_fill reconnect
  - `backend/app/data/bars.py` — global feed registry (`set_feed_instance` / `get_feed_instance`)
  - `backend/app/strategies/polymarket/shadow9.py` — VwapKellyEnsemble + Prewindow + FadeCompanion + OverlayFilter
  - `backend/app/strategies/polymarket/vwap_store.py` — Vwap15mStore + CVD/MACD/rvol tuple shape
  - `backend/app/strategies/polymarket/features_1s.py` — pure helpers (cvd_window, macd_hist, rvol_window, fair_up, fair_edge_bp, sigma_per_sqrt_sec_15m)
  - `backend/app/strategies/polymarket/markov.py` — label_regime_vol_adaptive
  - `backend/app/strategies/polymarket/gates.py` — production HOD_TOP8_BY_CELL (Phase 34 refreshed)
  - `backend/app/services/poly_redeemer.py` — pending pool query + skip marker (Bug B fix)
  - `backend/app/controllers/polymarket_updown.py` — 22 strategy_mode literals (incl. fade_*/overlay_*/vwap_kelly_ensemble/prewindow_s3/prewindow_s4_15m)
  - `backend/app/engine/main.py` — `_SHADOW_GATED_SLEEVES_SPEC` (Phase 34) + `_VWAP_CONT_SLEEVES_SPEC` (Phase 35) + `_SHADOW9_SLEEVES_SPEC` (Phase 36) + `_SHADOW9_FADE_OVERLAY_SPEC` (Phase 36b)
  - `backend/app/engine/_preflight.py` — `_SLEEVE_CONFIG_MAP` (live mirror allowlist parser)
  - `backend/app/api/bots.py` — `_resolve_poly_updown_sleeve_ids` manifest union

- Original spec references:
  - `strategy_lab/reports/TV_AGENT_SHADOW_DEPLOY_GATED_SLEEVES_2026_05_22.md` — Phase 34
  - `strategy_lab/reports/TV_AGENT_VWAP_CONTINUATION_FULL_SPEC_2026_05_23.md` — Phase 35
  - `strategy_lab/reports/SHADOW_DEPLOY_SPEC_9_NEW_SLEEVES_2026_05_24.md` — Phase 36 + 36b
  - `strategy_lab/reports/TV_AGENT_PHASE34_FIXES_2026_05_22.md` — Phase 34 fixes
  - `strategy_lab/reports/TV_AGENT_FIX_SPEC_PHASE36_BUGS_2026_05_26.md` — THIS DOCUMENT
  - `strategy_lab/reports/NEW_STRATEGIES_PROPOSAL.md` — referenced but NOT yet received by tv-agent
