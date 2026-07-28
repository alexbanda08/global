# TV RUST AGENT SPEC — WINDOW LIVE-CHART + POSITION INFOGRAPH (dashboard Windows page core)
**2026-07-29 · TVRUST · vps_ireland · This is the centerpiece of the Windows page from `TV_AGENT_SPEC_STRAT_DASHBOARD_V1_2026_07_28.md` — build it first, before the rest of Windows/A-B. Target look: Polymarket's 5m event chart (smooth real-time probability line) with OUR orders drawn on it.**

## 0. What we verified exists (build on this, no engine changes needed for v1)
`ladder_tick` (~1.2/s/sleeve) already carries: `best_bid_up/dn`, `resting_up/dn` (our quote levels), cumulative `filled_up/dn_sh`, `pair_frac`, `pvs`, `market_sell_up/dn_sh`, `t_remaining_frac`, `paused_up/dn`, book ages. `ladder_summary` at settle: vwaps, paired/residual, rebate, net. Live sleeve additionally emits real `order_*` lifecycle events. `stale_pause/stale_cancel/ladder_rcg_flatten/arm_flip` exist for annotations.

## 1. Backend
1. `GET /strat/window-live/{sleeve}/{slug}` — snapshot: full tick series so far for that window (downsampled ≤1Hz) + current derived state (below). For CLOSED windows same endpoint = replay data (chart works for history too).
2. `/ws/strat` channel `chart:{sleeve}` — on subscribe: snapshot; then ≤1Hz appends. Payload per point: `{t, up_px, dn_px, mid_up, resting_up, resting_dn, filled_up_sh, filled_dn_sh, paused, flags}` where `mid_up = (best_bid_up + (1 − best_bid_dn))/2` (v1 proxy; see §4).
3. **Derived state (server-side, recompute per tick, THE INFOGRAPH):**
   - `open_orders`: per side — resting price × clip sh (paper: from resting_*; live: venue-truth order list) + paused flag.
   - `filled`: per side — sh, vwap, cost.
   - `paired_sh` + `locked_pair_pnl = paired_sh × (1 − pvs_pair)` (winner-fee-adjusted per the no-mergePositions ruling).
   - `residual`: side, sh, cost, `mark_pnl = sh × best_bid_side − cost` (mark-to-book at current bid).
   - `rebate_est` = maker-filled notional × rebate rate assumption (same const as summary).
   - `net_now = locked_pair_pnl + residual_mark_pnl + rebate_est − fees_paid` — THE number, big, green/red.
   - plus: pvs, pair_frac, flow_capture, t_remaining, window cap usage ($ used vs cap).
4. Perf: serve from a small in-memory ring buffer per active window (fed by the same 1s tail loop), NOT per-request SQL over `ladder_tick`; closed-window replay may hit SQL. Ring buffer also insulates the dashboard from the events partitioning work.

## 2. Frontend (Windows page → active-window card expands to this)
- **Chart (lightweight-charts or uPlot, smooth area style like Polymarket):** X = window time (00:00→05:00/15:00), Y = price 0–1. Series: `mid_up` main line (green above 0.50, red below, soft gradient fill — the Polymarket look); dashed 0.50 strike line; **step-lines for our `resting_up` and `resting_dn`** (distinct colors, gaps when paused/cancelled); **fill markers** (▲ up-token buy, ▼ dn-token buy) sized by clip at the fill tick, tooltip = price×sh; annotation flags for stale_pause/stale_cancel/rcg_flatten/backstop; live vertical "now" cursor with countdown.
- **Infograph panel beside/below the chart (phone: below):** net_now (big), then rows: open orders (per side, price×sh, paused badge) · filled (sh@vwap per side) · paired (sh + locked $) · residual (side, sh, mark $) · rebate est · caps used · pvs / pair_frac / flow-capture badges. All updating with the WS tick.
- **Sleeve selector** (v3, c2, rcg, c2rcg, 15m v3, live twin when armed) + market tabs (btc-5m / btc-15m / eth-5m). **Live twin overlay mode:** when armed, draw live fills as solid markers and paper twin fills as hollow markers on the SAME chart — the capture-ratio made visible.
- **History:** any window row in the Windows table opens the same component in replay mode (static chart + final infograph + settle outcome banner).
- Mobile: chart full-width, 44px targets, infograph collapses to the top-4 numbers with expand.

## 3. Acceptance
1. Screen recording (or 3 timestamped screenshots ≤10s apart) of a LIVE btc-5m window: line moving, resting step-lines visible, a fill marker appearing, net_now changing.
2. Same window after settle in replay mode with outcome banner.
3. Phone screenshot (390px) of chart + collapsed infograph.
4. WS payload sample + ring-buffer memory bound stated (≤ ~50MB all sleeves).
5. No engine restart used for any of this (tv-api + frontend only).

## 4. ORACLE price underlay (IN SCOPE — operator requirement, and it must be the ORACLE, not Binance)
The window resolves on the Chainlink oracle print. Binance leads it by 3–7s and sits ~6bp off the settlement value — drawing Binance would show the WRONG winner on knife-edge windows. So the price pane must use the SAME oracle source Polymarket's own event page charts:
1. Open a live btc-updown event page, capture from the network tab the price-history/stream endpoint its chart uses (Polymarket exposes the oracle price feed publicly to render that chart — take exactly that API/WS, it is the resolution-truth series as displayed to every trader).
2. tv-api subscribes/polls it (read-only, public, no auth, no venue coupling) and republishes on the `chart:{sleeve}` WS channel alongside the book ticks.
3. **Layout: two stacked panes, Polymarket-style.** Top pane: oracle price line vs the window STRIKE (horizontal line at the window-open oracle print; green/red fill above/below strike). Bottom pane (taller): the Up-probability line + our resting/fill overlay per §2. Shared X axis/cursor.
4. Fallback ONLY if the public endpoint proves unusable: read-only relay of `oracle_prices_v2` from VPS3 storedata (our own Chainlink RTDS collector, ~2.8/s) — flag before building it (cross-host dependency, non-critical path only).
5. NEVER substitute a Binance/CEX price in this pane. If the oracle feed is unavailable, show the pane empty with a "feed down" badge rather than a wrong line.

## 5. Small engine add (rides the NEXT scheduled restart — do NOT restart for it)
Add `best_ask_up/dn` to `ladder_tick` so `mid` becomes exact instead of the two-bid proxy; switch the chart source when available. Flag in report when it lands.

## Out of scope
Candles/volume bars (line only), order MODIFICATION from the chart (buttons stay on Live page per ARMCTL spec).
