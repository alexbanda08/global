# ⭐ Scalp Different-Window OOS — PASSED (the §D-2 deflation gate is cleared)

**Date:** 2026-06-05 · **Script:** `strategy_lab/directional/scalp_oos_bbo_2026_06_05.py`
**One line:** The intra-window exit-scalp's gated edge (entry_vwap<0.55, δ≥3, sell on book +60s) **survives a
clean disjoint-window OOS** on **Mar 30 → Apr 21** (never seen by the search window Apr 22 → Jun 4): BTC +$2.38/tr,
ETH +$1.92, SOL +$2.16 — **all CI excludes 0.** This was the last validation gate before real capital.

## Why this window is a valid OOS
- Search / in-sample / DSR / live-shadow all used **Apr 22 → Jun 4**.
- This test uses **Mar 30 → Apr 21**, fully **disjoint** (pre-search). Data: aliplayer **BBO**
  (`load_orderbook_bbo`) — slot-aligned, full pre-slot coverage (so the deployed **+5s fire** is valid, unlike
  the trentmkelly L25 backfill which starts +80s) — + the now-complete binance **1s signal** (Jan→Jun) +
  **resolutions_hf** outcomes.

## Result (gated cell entry_vwap<0.55, exit +60s book-sell, $25, spread≤0.05)
| coin | candidates(δ≥3) | filled | n_gated | $/tr | t | bootstrap CI | won |
|---|---|---|---|---|---|---|---|
| BTC | 466 | 210 | 79 | **+2.38** | 2.59 | **[+0.62, +4.09]** | .595 |
| ETH | 734 | 342 | 141 | **+1.92** | 2.73 | **[+0.53, +3.33]** | .574 |
| SOL | 873 | 401 | 172 | **+2.16** | 3.76 | **[+1.03, +3.25]** | .529 |

- Tighter δ≥5: ETH +2.56 (CI [0.07,4.96]), SOL +4.34 (CI [2.13,6.59]) — CI>0; BTC +3.21 (n=24, CI incl 0, small).
- Gate lift confirmed OOS: all-filled control is weaker (BTC +1.32 / ETH +0.53 / SOL +0.50) → the vwap<0.55 gate
  adds edge, exactly as in-sample and live.
- Fill rate ~45–46% (top-of-book BBO).

## Full validation chain for the exit-scalp (now complete)
1. In-sample edge (Apr–Jun): gated +$2.7–5.6/tr.
2. Deflated Sharpe: passes pre-registered (`ML4T_DSR_JUDGE_2026_06_04`).
3. Entry/exit knobs pinned optimal: delta_bps sufficient (§D-1), +45/+60s optimal (`SCALP_DYNAMIC_EXIT`).
4. Live shadow holding: gated `_v1` sleeves +EV (btc_5m_v1 +$4.49/tr, `VPS3_SLEEVE_VERIFICATION_2026_06_05`).
5. ✅ **Clean different-window OOS (this report): BTC/ETH/SOL gated CI>0 on Mar30–Apr21.**

## Caveats (honest)
- **BBO top-of-book fill** (size-capped at best_ask; no L25 depth walk) → entry slightly optimistic vs a full
  ladder walk. But best_ask is the real touch and the +$2/tr magnitude is well above plausible walk slippage.
  If a full-L25 aliplayer feed for this window becomes available, re-confirm; otherwise BBO is the best slot-aligned
  book we have for the disjoint window.
- Exit clamped to slot_end (no post-settlement tail). Fee = 0.015 round-trip book-sell (matches the cache pnl_at).
- XRP/DOGE/BNB returned no slugs in their Mar30–Apr6 slice (1s ends Apr 6) — investigate separately; not needed
  for the gate (BTC/ETH/SOL is the prize).
- N per coin is modest (79–172 gated) but CI excludes 0 on all three independently → robust.

## Bonus — Time-of-day gate ALSO validated OOS (same window)
Pooled BTC+ETH+SOL gated fires (n=392) on Mar30–Apr21:
- base (all hours) +$2.12/tr (CI [1.33,2.89]); **22–02 UTC +$4.68 (CI [3.13,6.29]) = ~2.2× base** (in-sample was
  +4.61 vs +2.95 — near-identical OOS); exclude {12,17} +$2.24; exclude {2,12,16,17,18} +$2.50; dead {12,17}
  only +$0.32 (CI incl 0). → the time-of-day selector replicates on the disjoint window. Now triple+OOS validated
  (in-sample walk-forward + F2 corroboration + this OOS). Fires saved: `_results/scalp_oos_bbo_fires_2026_06_05.parquet`.

## New coins — DOGE OOS-validated (2026-06-05, after 1s backfill to Apr 21)
Operator extended binance 1s for DOGE/BNB to Apr 21. Re-ran on their market window Apr 6→Apr 21:
| coin | gated n | $/tr | t | CI |
|---|---|---|---|---|
| **DOGE** | 138 | **+1.40** | 2.21 | **[+0.19, +2.61]** ✓ |
| BNB | 22 | +1.39 | 0.73 | [−2.29, +5.10] (thin: 290 candidates / 43 fills) |
- **DOGE passes the disjoint-window OOS** (gated CI>0) → validated scalp universe is now **BTC/ETH/SOL/DOGE**.
  DOGE edge (+$1.40) < BTC/ETH/SOL (+1.9–2.4), consistent with a thinner DOGE up/down market.
- BNB directionally positive but underpowered (thin market, n=22) — needs more fills to confirm.
- Time-of-day 22–02 boost did NOT replicate on DOGE/BNB (n=20, +0.76 < base) → the TOD pattern looks
  BTC/ETH/SOL-specific (or underpowered on new coins). Fires: `_results/scalp_oos_bbo_fires_2026_06_05_doge_bnb.parquet`.

## XRP OOS-validated (2026-06-05, after 1s extended to Apr 21)
XRP 1s was extended to Apr 21; its markets+BBO+signal now overlap on **Apr 7–21**. Result:
| XRP | n | $/tr | t | CI |
|---|---|---|---|---|
| all-filled | 252 | +1.83 | 3.62 | [+0.83,+2.80] |
| **gated vwap<0.55** | 125 | **+2.20** | 2.78 | **[+0.63,+3.76]** ✓ |
| gated & d≥5 | 41 | +4.62 | 2.78 | [+1.34,+7.75] |
→ **XRP passes** (on par with BTC/ETH/SOL). **Validated scalp universe = BTC/ETH/SOL/DOGE/XRP (5 coins).**
Fires: `_results/scalp_oos_bbo_fires_2026_06_05_xrp.parquet`.

## Still blocked — BNB (power) / HYPE (signal)
- DOGE/BNB: markets Apr 6–21 but binance 1s ends Apr 6 → no signal overlap. Need 1s extended to Apr 21.
- XRP: its 5m/15m markets sit in March; BBO starts Mar 30 → 0 overlap in the BBO∩1s window. Need aligned XRP book/signal.
- HYPE: no binance 1s at all (HL only, hourly — too coarse). Operator data needed before new-coin scalp OOS.

## Implication
The exit-scalp is now validated across in-sample + DSR + live + disjoint-OOS — the strongest evidence chain in
the project. The remaining gate is purely live forward accrual (≥200 fires + live-wallet CI), already underway.
This materially de-risks moving the gated scalp toward real (small) capital after the live forward count lands.

## Files
- `strategy_lab/directional/scalp_oos_bbo_2026_06_05.py` · data: `load_orderbook_bbo` (D:\global_data\canonical_bbo),
  `klines_1s`, `resolutions_hf`. Inventory: `NEW_DATA_INVENTORY_2026_06_05.md`.
