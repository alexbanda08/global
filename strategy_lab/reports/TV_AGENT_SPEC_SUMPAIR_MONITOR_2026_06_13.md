# TV AGENT SPEC — `sum_pair_monitor_v1` (paper $0, OBSERVE-ONLY, VPS3 shadow fleet)

> 🟡 **OBSERVE-ONLY — places ZERO real orders.** This is a measurement probe, not a trading sleeve.
> The taker sum-pair arb is already PROVEN DEAD offline (`SUMPAIR_ARB_VERDICT_AND_SHADOW_PLAN_2026_06_13.md` +
> `sumpair_arb_t1_2026_06_13.py`: every cell −5 to −11¢/pair SIG-NEG because the sub-$1 dip reverts in <100ms,
> before our 85ms order lands). The ONLY thing historical 10Hz data cannot resolve is **sub-100ms dip duration**
> and whether a **resting maker bid** gets hit during the dip. This sleeve measures exactly that, on the live WS
> book, at $0 risk. Do NOT promote to any real-money sleeve unless the §6 maker gates pass.

_2026-06-13. Source: paper 2508.03474 "Market Rebalancing Arbitrage" + 0xSurferX/Luoye "binary hedging".
Prior internal: ce25 DEPLOY-NO (its profit = winner-leg resolution recovery, not arb), b945 maker SIG-NEG
(adverse selection), LEG2 −0.9 lockstep repricing. Offline taker test = DEAD. This closes the last open door
(sub-100ms maker capture) with live evidence instead of capital._

## 0. One-line logic
For each active Up/Down market, watch the live WS book at full frequency. Whenever `ask_up + ask_dn` dips below
$1, RECORD the dip (duration, depth, revert) and run TWO virtual fills — a virtual taker (buy-both at detect+latency)
and a virtual resting maker (limit bid per leg, filled only when a real seller crosses it) — then book both to true
chainlink resolution with the winner-only fee. **No real orders are ever placed.**

## 1. Sleeve config
```
name:            sum_pair_monitor_v1
markets:         {btc,eth,sol}-updown-{5m,15m}   (L25 depth coins; add xrp/doge/bnb if WS books exist)
mode:            paper (shadow), $0, OBSERVE-ONLY — emits NO orders to the venue
stake (virtual): $25 notional per leg (book-walked vwap), 1 virtual pair per dip-episode per slug
book source:     Tier-1 WS BookMirror (ws_mirror), BOTH tokens subscribed, full event frequency
pre-subscribe:   GET /markets?status=unopened -> subscribe orderbook_delta BEFORE slot_start (warm book at open)
```

## 2. Module M1 — dip-event recorder (the core measurement; 10Hz history can't see this)
On every WS book update for the slug's Up+Down pair compute:
```
sum_top   = ask_up[0] + ask_dn[0]                      # top-of-book
sum_walk5 = vwap_up($5)  + vwap_dn($5)                 # engine_v2.book_walk_fill per leg
sum_walk25= vwap_up($25) + vwap_dn($25)
```
A **dip-episode** = a maximal run of consecutive updates with `sum_top < 1.00`. Per episode emit:
```
onset_ts_us, end_ts_us, duration_ms, min_sum_top, min_sum_walk25,
depth_at_min_up_usd, depth_at_min_dn_usd, n_updates_in_episode, rel_slot_start_s
```
This directly measures: do dips ever persist >100ms (taker-capturable) or are they all single-update (<100ms)?

## 3. Module M2 — virtual TAKER control (confirm/refute the −5¢ offline finding LIVE)
On the FIRST update of each episode where `sum_walk25 < θ` (θ sweep {0.99, 0.98, 0.97}):
- Record the book; then "fill" buy-both at the first WS frame ≥ detect_ts + LAT, for LAT ∈ {50, 85, 150} ms,
  walking $25 on each leg at that frame (`book_walk_fill`).
- `sum_fill = vwap_up + vwap_dn` at the realized frame. (Expected: ≈ overround 1.01 → negative, as offline.)
- One virtual taker pair per episode per θ per LAT. **No order sent.**

## 4. Module M3 — virtual RESTING-MAKER test (THE open question)
From slot open, maintain a virtual resting limit BID on EACH leg at:
```
bid_up = bid_dn = PAIR_TARGET / 2 = 0.4825           # PAIR_TARGET = 0.965 (below the 0.97 gate)
```
(v1 = symmetric; a v1.1 ablation may skew bids toward the cheaper leg.) A leg's virtual bid is **FILLED** when
the live book's best ASK on that leg ≤ your bid (a real seller crosses you) — record fill_ts, fill_px, and the
size available at that ask (capacity). Rules:
- Require BOTH legs filled within `T_hedge = 20s` of the first leg's fill → **completed pair** (locked).
- If only one leg fills within T_hedge → **single-leg residual**: apply Luoye management for realism — record what
  a `FLOOR_PRICE=0.05` exit / `LAST_MIN_STOP_LOSS` / hold-to-resolution would each yield (book all three; this is
  where adverse selection shows up — does the leg that filled tend to resolve $0?).
- **No order is ever actually placed**; "fill when best_ask ≤ bid" is the conservative crossing rule (assumes you
  are NOT at the front of the queue → only count a fill when price trades THROUGH your level, FIFO lower bound).

## 5. Settlement accounting (per slug, at slot resolution; emit dedup-safe rows)
True outcome from chainlink (`load_resolutions`). Winner leg pays $1, loser $0, **winner-only 0.07·p·(1−p) fee**,
REDEEM itself fee-free (same model as the scalp/pairlock specs):
```
taker_pnl[θ,LAT] = 1 − sum_fill − 0.07·p_win·(1−p_win)        # per 1-share pair (control)
maker_pnl        = matched × [(1−p_w)(1−0.07·p_w) − p_l]      # completed pairs (the real test)
maker_residual   = single-leg outcome under {floor, stop, hold} (3 variants)
```
Emit per slug: `dip_count, min_sum_top, min_sum_walk25, max_dip_duration_ms,
taker_pnl_{99,98,97}_{50,85,150}, maker_completed (bool), maker_both_fill_ms, maker_pnl, maker_residual_*,
p_win, outcome`. Rank PnL on the TV dashboard **dedup metric** (`sleeves.py _RESOLUTION_DEDUP_ROW_NUMBER`,
exclude `fill_method='synthetic'`), NEVER raw `events.pnl_usd`.

## 6. Promotion gates (pre-registered) — what each arm decides
- **Taker arm (M2):** expected CI < 0 at every θ/LAT (confirms the offline DEAD verdict on live data).
  → On confirmation, **close the taker sum-pair path permanently.** No further taker work.
- **Maker arm (M3):** escalate to a `$1 LIVE maker probe` ONLY if, over **≥4 weeks AND ≥200 dip-episodes**:
  1. both-legs-fill (completed) rate ≥ 30% of dip-episodes,
  2. completed-pair `maker_pnl` CI95 > 0 (dedup metric) after winner-only fee,
  3. **ex-top2 outlier-robust** (drop the 2 best slugs, edge survives),
  4. single-leg residual (M3 hold variant) NOT significantly net-negative (proves it's arb, not a hidden
     directional bet that adverse-selects against us — the b945 failure mode),
  5. dip-duration data (M1) shows the maker fills are NOT just the same <100ms transients re-labeled.
  → If ANY gate fails: **file sum-pair arb FULLY DEAD** (taker proven, maker refuted live) and stop.

## 7. Explicitly NOT in v1
No real orders (observe-only). No combinatorial/cross-market arb (N/A to single-condition crypto). No directional
signal (this is the pure-structure test; the directional version is the deployed scalp). No skewed maker bids, no
EV sizing, no sweeper. No promotion to capital without §6.

## 8. Engines / components to reuse
| Need | Reuse |
|---|---|
| Dual-token live book | production Tier-1 `ws_mirror` (subscribe Up+Down per slug) |
| $-stake walk / winner-only fee | `strategy_lab/engine_v2.py` `book_walk_fill` + `LiveMimicConfig` |
| Maker crossing-fill rule | NEW: `best_ask ≤ resting_bid` detector, FIFO lower bound (count only price-through) |
| Resolution truth | `load_resolutions` (chainlink) |
| Pre-subscribe warm book | Kalshi `status=unopened` pattern already in the engine |
| PnL metric | sleeve dedup metric; sink to `_tv_cards_feed.json` + a `sum_pair_dips.parquet` (the M1 event log) |
| Offline reference | `sumpair_arb_t1_2026_06_13.py` (taker arm should reproduce its −5¢ live) |

## 9. Bottom line
This sleeve costs $0 and resolves the only open question. Most-likely outcome: taker arm confirms DEAD, maker arm
fails gate 2 or 4 (adverse selection, per b945) → **sum-pair filed fully dead with live proof.** Upside case: maker
completed-pair PnL is robustly >0 → a genuinely new $1 maker edge. Either way, no capital is risked to find out.
```
```
