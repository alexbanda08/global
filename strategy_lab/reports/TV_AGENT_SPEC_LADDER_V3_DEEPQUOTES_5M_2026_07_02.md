# TV RUST AGENT SPEC — Ladder next iteration: DEEP QUOTES + BTC-5M mirror (+ keep residual mgmt)
**2026-07-02 · TVRUST (Rust) ONLY · Ireland · PAPER ($0). Python frozen. Storedata untouched.**

## Versioning / how this composes with what you already have
- This spec **adds to** the residual-management spec already delivered (maker-recycle + T−60s flatten backstop + `pair_gate_bound_sh` fix). 
- **If that v3 is NOT yet deployed:** fold THIS spec in and ship everything together as **v3** (sleeves `poly_ladder_btc_15m_v3`, `poly_ladder_btc_5m_v3`).
- **If v3 is already live:** ship this as **v4** (`_v4` sleeves). Never mix data across versions — new sleeve id per iteration, same 4 event kinds so the analysis pipeline runs unchanged.
- The other outstanding spec (`TV_AGENT_SPEC_SUMPAIR_START_SCALP_TELEMETRY_2026_07_01.md`: sumpair_osc enable + scalp exit/band fixes) is unchanged and still wanted — priority: this ladder iteration first, sumpair enable second (env-only, trivial), scalp fixes third.

## Why (one paragraph, evidence in `PAIRARB_LADDER_VS_CE25_HEADTOHEAD_2026_07_02.md`)
We fresh-decoded BOTH profitable pair-arb wallets (b945 = the design source, +$28.3k lifetime; Agile-Spacing, +$384.6k lifetime) against pre-fill books on the same days our v2 ladder ran. Identical inventory structure to ours, but: **their resting bids sit BELOW the touch (b945 median −3 ticks, p10 −9; ce25 median −1, p10 −5) — nobody profitable quotes at the touch.** Our at-touch quotes absorb informed window-scale sell flow → residual wins 14.1% vs 40% breakeven (−5.5σ) → v2 net −$0.91/win despite a healthy paired engine (+$1.51/win). Also: **b945 LOST on btc-15m this window (−$6.70/slug) and made all his profit on btc-5m (+$4.22/slug)** — we ran the hostile market only. Fix both.

## CHANGE A — quote depth: rest BELOW the touch, never at it
- New env: **`TV_LADDER_QUOTE_DEPTH_TICKS`** (integer ≥0, **default 2** = rest 2 ticks below the current best bid on each side; tick = 0.01, clamp to 0.001-tick zones near the extremes if applicable).
- Quoting rule per side: `my_bid = best_bid − DEPTH_TICKS·tick`, re-follow as the touch moves, but **NEVER join or improve the touch** (`my_bid < best_bid` always, except when `best_bid − depth < 0.01` → sit at 0.01 or pause the side).
- **Composition with the pair cap (unchanged G3 invariant):** effective bid = `min(best_bid − DEPTH_TICKS·tick, PAIR_MAX_SUM − filled_other_side_vwap)`. The pvs<0.99 invariant stays.
- Effect to expect (and verify): fewer fills, but fills arrive only when price spikes DOWN through our level = overshoot-selected — attacking the residual adverse-selection at the source, complementing (not replacing) the residual management.
- Optional if the sleeve factory makes it cheap: a second paper variant at depth 4 (`..._d4` suffix) on btc-15m only — paper sleeves simulate independently against the same tape, so they don't interfere; gives us the depth curve for free. Skip if it complicates the deploy.

## CHANGE B — add the BTC-5M mirror
- Second sleeve instance: **`poly_ladder_btc_5m_v3`** — same config/code, market `btc-updown-5m` (288 windows/day vs 96).
- Both profitable wallets currently print on 5m; keep the 15m sleeve running in parallel (same-days A/B: regime vs design).
- 5m timing sanity: window = 300s → the residual T−60s backstop and any warmup/lead constants must scale off window length, not hardcoded 900s. Verify warmup completes early enough on 5m to trade (v2 window-level warmup pass was 98.7% on 15m — confirm equivalent on 5m).

## KEEP (from the specs already delivered — do not drop)
1. G1 telemetry: `filled_up/dn_vwap`, `outcome`, `residual_entry_vwap`, `residual_pnl_usd`, `total_net_usd` (winner-only fee on held residual; $0 on maker/redeem).
2. Residual management: intra-window maker-recycle of the heavy side + T−60s taker-flatten backstop (T−60s on 15m; scale to T−45s on 5m), fallback hold if no book.
3. G3 pvs gate (`TV_LADDER_PAIR_MAX_SUM=0.99`) + fix the `pair_gate_bound_sh` counter (still 0 everywhere in v2).
4. Racer + latency + feed_quality telemetry unchanged.

## NEW TELEMETRY (verifies the deep-quote mechanism — the analysis depends on it)
Per `ladder_summary` add:
- `quote_depth_ticks` (config echo)
- `fill_below_touch_ticks_mean` per side: for each fill, (best_bid_at_fill − fill_price)/tick, averaged — **target ≥1–3 (b945 profile); if ~0 the depth isn't being applied.**
- `residual_recycled_sh`, `residual_flattened_sh`, `residual_backstop_cost_usd` (residual-mgmt accounting, if not already in the v3 build).

## Acceptance
1. Both sleeves (`btc_15m_v3`, `btc_5m_v3`) emitting `ladder_summary` with all G1 + new fields; no rows under the v2 sleeve id after cutover.
2. `fill_below_touch_ticks_mean` > 0 on traded windows (deep quoting demonstrably active); realized `pvs < 0.99`; `pair_gate_bound_sh` now counting.
3. `total_net_usd` = paired + rebate + residual_pnl (+ recycle/backstop terms) exact.
4. ~1 week paper accrual → research side computes: net CI per market, fill-selection comparison vs the b945/ce25 classified tapes, depth-2 vs depth-4 curve (if variant shipped).

## Do NOT
❌ No live arm (watchdog still undeployed — live prerequisite). ❌ Don't quote AT the touch under any config. ❌ Don't drop the 15m sleeve (we need the A/B). ❌ Don't touch scalp/sniper hot paths, Python Tradingvenue, or storedata. ❌ Don't reuse the v2 sleeve id.

## Provenance
Head-to-head + classifications: `PAIRARB_LADDER_VS_CE25_HEADTOHEAD_2026_07_02.md` (§3b ce25, §3c b945, §3d deltas). v2 results: `IRELAND_LADDER_V2_FIRST_RESULTS_2026_07_01.md`. Residual-mgmt + G1/G3 base: the v3 spec previously delivered + `TV_AGENT_SPEC_LADDER_V2_RESIDUAL_PVSGATE_FRESH_2026_06_30.md`. Fee rules: winner-only `0.07·p·(1−p)` on held-to-resolution wins; $0 maker/redeem.
