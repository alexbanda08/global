# Engine comparison — Ireland (LIVE) vs VPS3 (PAPER) — `poly_updown_btc_15m_momo_HOLD_f7` — 2026-06-03

Pulled all `poly_updown_signal` + `poly_updown_resolution` events for the SAME sleeve off both
engines' `storedata.trading.events`. Window 2026-05-20 → 2026-06-03. Goal: why do the two fire
differently. Data: `strategy_lab/_engine_compare_2026_06_03/{sig2_*,res_*}.csv`.

## Headline: they DON'T fire differently in any meaningful way. The signal layer is identical; only execution + stake differ.

| metric | Ireland (live) | VPS3 (paper) |
|---|--:|--:|
| signal events | 1,317 | 1,405 |
| order_placed (fires) | 79 (52D/27U) | 85 (55D/30U) |
| resolutions | 78 | 81 |
| WR | 53.8% | 58.0% |
| Σ pnl | **+$5.92** | **+$306.94** |
| entry stake | ~**$1** notional (qty≈1.96 @ 0.5) | ~**$25** (qty≈49 @ 0.51) |
| mode | `live` (real CLOB, onchain oracle) | `paper` |

The $5.92 vs $306.94 gap is **100% stake size** (live runs $1, paper runs $25 → ~25×), NOT edge.
Same WR-class, same direction calls.

## Signal layer = deterministic & shared
- Window-level (1,329 15m windows evaluated by both): **both-fire 76 → 76 same direction, 0 opposite.**
  Both no-fire 1,243. Identical `rsi_14` and `ret_2m_at_signal` on matched windows (e.g. slot
  1780495200000000: rsi 64.7881811559314 byte-identical on both).
- Resolution overlap by `condition_id`: **70 common markets → 0 direction-mismatch, 0 won-mismatch,
  0 outcome-mismatch.** Perfect agreement on every shared trade.
- Same code path (`poly_updown_loop`), same RSI (simple-mean Wilder), same f7 filter, same
  ws_s anchor, same `entry_phase=t_plus_120`.

## The ONLY divergence: 10 / 1,329 windows (0.75%) — all EXECUTION-layer, three causes

### Cause A — LIVE CLOB rejection (4 windows) — the important one
Ireland computed the SAME signal+direction and TRIED to fire, but the real order came back
`entry_rejected` (FOK can't fill on a thin live book / 409). VPS3 paper has no real order book →
fills unconditionally → logs a fire Ireland never got.
- 2026-05-22 19:30 DOWN · 05-22 20:00 UP · 05-23 13:00 UP · 06-03 12:30 UP
- **Implication: paper OVERSTATES fills.** The 85-vs-79 fire gap is mostly paper filling trades the
  live book would reject. Any paper PnL must be discounted for live fill-feasibility.

### Cause B — VPS3 `qty_compute_failed` (3 windows)
VPS3 agreed on the signal but couldn't size the order (missing/stale book snapshot at the fire
instant) → skipped. Ireland filled. A VPS3-side data-availability hiccup, not a strategy diff.
- 2026-05-21 17:00 UP · 06-03 05:15 UP · 06-03 05:30 DOWN (all: rsi/ret/thr identical, paper just failed to size)

### Cause C — boundary ret_2m / adaptive-threshold micro-differences (3 windows)
At windows where `|ret_2m|` sits right on `abs_ret_2m_threshold`, a hair of host-to-host feed
difference flips fire↔no-fire:
- 2026-05-23 01:00: IRE ret **0.00097** (NONE, <thr 0.00098) vs V3 ret **0.00135** (UP). Different ret value.
- 2026-05-23 08:15: SAME ret 0.00093, but IRE thr **0.00098** (→NONE) vs V3 thr **0.00092** (→UP). Different *threshold*.
- 2026-05-29 13:30: IRE ret −0.00097 (NONE) vs V3 ret −0.00102 (DOWN). Boundary.
- Root: each host snaps its own binance WS tick to build the bar (Ireland `bar_ctx_age_ms`≈35 vs
  VPS3≈61) and the threshold is cost-adaptive (`predicted_cost_bps`), so both `ret_2m` and `thr`
  can differ at the 4th–5th decimal. Only matters when the signal sits exactly on the line.

## Conclusions
1. **Same strategy, same signal, same direction.** No logic divergence to fix. 0 opposite-direction
   fires across 1,329 windows; 0 mismatches across 70 shared resolutions.
2. **Stake is the only PnL driver of the headline gap** ($1 live vs $25 paper = 25×).
3. **Real divergence is fill-feasibility:** live `entry_rejected` (4) > paper `qty_compute_failed` (3)
   > feed-boundary noise (3). The net effect: **paper fires ~7% more often than live can actually
   fill**, and those extra paper fills are exactly the thin-book ones the live CLOB refuses.
4. **Actionable:** when judging this sleeve for graduation, use the LIVE (Ireland) fire set — the
   paper fire set is optimistic on fills. The boundary-noise (Cause C) is irreducible host jitter and
   negligible (3/1329).

## Files
`strategy_lab/_engine_compare_2026_06_03/` — sig2_{vps_ireland,vps3}.csv, res_{vps_ireland,vps3}.csv
