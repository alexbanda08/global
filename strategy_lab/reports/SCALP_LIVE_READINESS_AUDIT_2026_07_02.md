# Scalp live-readiness audit — logic, fidelity, fire gap, wallet, minimum capital
**2026-07-02. 4-agent (sonnet) gather + synthesis. Sources: VPS3 Python production source (`/opt/tradingvenue`), both hosts' event DBs, journalctl, the 77-exit shadow tape, `SCALP_CAPACITY_PROSPECT_2026_06_13.md`. Raw dumps: `strategy_lab/directional/_ireland_6day/_wf/`.**

## 1. The strategy as actually implemented (source-verified, file:line in agent dump)
- **Signal/entry (btc_5m_d3):** at slot_start+5s, compute Binance intra-window return anchored at **slot_start** (causal): `g_oracle_lag_with(3.0,12.0)` passes iff **3 ≤ |δ| ≤ 12 bps** AND sign matches direction (the 12bp cap is load-bearing — bigger moves are priced-in). Then: same-token **spread ≤ 0.05**, **≥25 book events in 60s** (freshness), walk the L25 asks for the stake → **entry band: walked vwap < 0.55**, one-shot-per-slug.
- **Stake:** shadow **$5** (`notional_usd_override` on d3_v1); live **$1 global** (`TV_POLY_SNIPER_V5_LIVE_NOTIONAL_USD=1.0`), **hard-capped $2.00** (`SNIPER_V5_LIVE_MAX_NOTIONAL`, polymarket_sniper_v5.py:97). Shares = stake-sized ask-walk (≤25 levels, pro-rata last level).
- **Exit:** TP and STOP are **hardcoded off** (locals `tp_on=False`, `stop_on=False`) — pure +60s deadline; walks **bids** for the full position, partial-tolerant; empty book → fallback hold-to-resolution.
- **PnL:** `(sell_vwap − fill_vwap)·shares − 0.07·sell_vwap·(1−sell_vwap)·shares` — **sell-leg fee charged unconditionally** (patched 2026-06-10; the "$0 proxy" docstring is stale). Fallback-hold path uses the standard winner-only curve.

## 2. Is the shadow computing PnL exactly like live? — graded verdict
| dimension | verdict | evidence |
|---|---|---|
| arithmetic | ✅ exact | all 77 exits: `pnl == (exit−entry)·sh − fee`, maxdiff 1.8e-15 |
| config fidelity | ✅ exact | stake $5.000000 all 77; band <0.55 all (max 0.54); \|δ\|≥3 all; trigger 100% time60; no dups |
| sell realism | ✅ good | 73/77 sell at best bid, 4/77 walk **deeper** (never better); depth 919–14,413 vs ~10 sh needed |
| fees | 🟡 conservative? | sell fee $10.97 total (~$0.14/tr) charged unconditionally — if the venue doesn't charge taker-sell on these markets, shadow UNDERSTATES PnL; unverifiable until a real live sell exists (§3) |
| latency | 🟡 optimistic | shadow fill walks the book at **0 ms** (no 85ms model in the production controller) — small optimism; live entry books only the venue ack, so live data will price this |
| entry fill assumption | 🟡 optimistic | shadow always "gets" the fire; live can miss/partial — the classic gap only live fires can measure |
| telemetry completeness | 🟡 gap | 2/79 fires have **no exit event at all** (fallback-holds untracked); `poly_fee_settled` = simulated GAS stream (~$0.02/order, sim_ prefixed — over-modeling, CLOB is relayer-gasless) |

**Net: the shadow is honest-to-conservative. The +0.783/tr (n=77, net of the $0.14/tr sell fee) is a fair number.**

## 3. 🔴 THE CRITICAL FINDING — the LIVE path never sells
`_scalp_exit_then_resolve` / `maybe_scalp_exit` has **no live-order branch in taker mode**. Live positions get: **real $1 entry (venue-acked)** → **SIMULATED +60s book-walk "sell" (paper)** → the logged live PnL is a real-entry/synthetic-exit hybrid → **the real tokens stay in the wallet and ride to resolution** (hence the 17 `poly_redeemed` on-chain events). 

**Consequences:**
1. The 9 "live" exits (+0.048/tr) are not real round-trips — real cash economics were hold-to-resolution, i.e. **live money has been running the strategy WITHOUT its edge** (the edge IS the exit).
2. This also quietly consumed the bankroll: entries spend USDC, winners redeem at resolution (capital cycles slowly), losers burn — consistent with the wallet bleeding to $1.77.
3. **Funding the wallet today would buy more favorite-hold, not the scalp. The live taker SELL must be implemented before any deposit.**

## 4. Fire-rate gap — two sequential causes (both confirmed)
1. **Jun 26 → now: wallet empty — operator's diagnosis CONFIRMED.** Balance frozen at exactly **$1.7716** across 76+ CLOB rejections (`not enough balance / allowance`), hitting all 3 live sleeves. Orders request ~$1.83–2.25 because the marketable-limit at 0.99 requires **collateral ≈ shares × 0.99 ≈ 2× the $1 notional at vwap≈0.5**. Last successful live fire: Jun 17 16:26 UTC.
2. **Jun 11–25 (wallet still funded): host gate divergence.** Same gate, same cadence (~576 signals/day both hosts): VPS3 passed all-gates 79×, Ireland ~0× (post-Jun-17). Both hosts run independent WS book mirrors → host-specific book/feed variance at rare-event rates. *Caveat: the agent's 0-pass count conflicts with the 9 actual pre-Jun-17 fires (fired rows may log skip_reason differently) — needs a small follow-up, second-order.*
3. **Observability hole:** balance rejections live ONLY in journalctl — zero `trading.events` rows → DB dashboards showed "not firing" with no reason. Persist order rejections as events.

## 5. Minimum capital to live-test (agent-computed from the real tape, + my collateral correction)
Facts: 4.3 fires/day, **max concurrent = 1** (no two fires within 60s in 77), MaxDD $8.42 (trade-level, $5 clips), WR 64.9%, avg win +$1.87 / avg loss −$1.24.
- **$1 clips: not viable** — ~2 shares at vwap≈0.5 is at/below the ~5-share venue minimum; the rejections show even $1 orders demand ~$2+ collateral. This alone argues the $1 probe era was mis-sized.
- **$5 clips (the validated size): fund ~$100–150.** Breakdown: collateral per open order ≈ $10–11 (0.99-limit × shares) + DD buffer 2×$8.42×1.75 + $50 float. Expected ~+$101/mo; the goal isn't profit, it's the **≥200-fire gate (~45–50 days)** — bootstrap says if the tape distribution holds, CI>0 at N=200 with ~100% probability (thin-sample caveat).
- **$25 clips: ~$250–300.** Depth-safe (uses 0.5–0.6% of exit depth; capacity ceiling for BTC-5m is ~$800/fire). Expected ~+$505/mo. **Only after the 200-fire gate at $5.**

## 6. Improvements (ranked)
1. **Implement the live taker SELL at +60s** (mirror `_walk_bids_for_shares` as a real marketable-limit sell, venue-acked, fail→hold fallback). ⚠️ Python Tradingvenue is operator-frozen — either grant a one-patch exception (small, surgical: one branch in `maybe_scalp_exit`) or wait for the TVRUST scalp port (needs its own live executor). **Blocking for any deposit.**
2. **Raise `SNIPER_V5_LIVE_MAX_NOTIONAL` $2→$5+ and set live notional $5** so live matches the validated shadow size and clears venue minimums. Trim the live allowlist to `btc_5m_d3` alone for the test (clean wallet math; 15m_d3/momalign live shadows are negative-at-tiny-n anyway).
3. **Persist order rejections/balance errors as `trading.events`** (kind `poly_order_rejected`) — the empty wallet was invisible for 6 days.
4. Fix the 2/79 untracked fallback-holds (emit a hold event); drop the sim-gas stream or mark it excluded from PnL.
5. Verify the sell-leg fee against the first real live sells (if venue charges $0, shadow gains ~+$0.14/tr).
6. Follow up the Ireland-vs-VPS3 gate divergence (compare book-mirror freshness at fire moments) — matters because live runs on Ireland but the validated tape is VPS3's.

## 7. Bottom line
- **Strategy logic + shadow implementation: sound.** Config exactly as validated, arithmetic exact, fills honest-to-conservative. The +0.783/tr CI[+0.36,+1.21] stands as the best estimate.
- **Live implementation: NOT the strategy** — entry real, exit simulated, edge never captured, wallet drained to $1.77 doing hold-to-resolution at $1 clips that flirt with venue minimums.
- **Plan:** (1) live-sell patch, (2) $5 notional + cap raise + allowlist trim + rejection telemetry, (3) fund **$150**, (4) run to ≥200 fires (~7 weeks), judge on live CI vs the shadow tape, (5) scale to $25 (~$300 bankroll) only on pass.
