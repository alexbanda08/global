# TV Agent Spec — `poly_fast_taker` shadow sleeve (2026-05-29)

> Implement a NEW shadow sleeve on the Ireland engine that trades the validated
> **binance→chainlink lag** directional edge. Shadow-only first (no real orders);
> log to CSV like the maker sleeves; settle at resolution via the existing E1 path.
> Backtest target to reproduce in shadow: **OOS +$1.31 per $25 fire, WR ~63%, ~59
> fires/day** across btc/eth/sol × 5m/15m (binance-1s window ~May 7-29, native 10Hz,
> 2%-on-winning-profit fee). Full evidence: `strategy_lab/reports/LATENCY_EDGE_FINDING_2026_05_29.md`.

## 0. What the edge IS (so the implementation matches the backtest exactly)
Polymarket BTC/ETH/SOL up-down markets resolve on Chainlink Data Streams, which **lags
Binance spot by ~5-20s**. Right after a binance move, the resting Polymarket ask on the
**leading side** (the side binance moved toward) is still **stale-cheap**. We TAKE it and
hold to resolution. The edge decays to ~0 by 45-60s, so we must fire **early (~5-10s into
the window)** and only on **strong moves (≥3 bps)**.

## 1. Anchor + fire rule (CRITICAL — do NOT use the momo `ws_s` anchor)
- **Anchor = `slot_start`** = the slug suffix = `int(slug.rsplit('-',1)[1])`. This is
  INTRA-window. (The momo/F7 controller `controllers/polymarket_updown.py` anchors on
  `ws_s = slot_start − window_s`; this sleeve is DIFFERENT — do not reuse that anchor.)
- At/after `slot_start`, capture the binance reference price `px0 = binance_spot(slot_start)`
  (asof the slot-open second; use the live binance feed `feeds/binance_market_data.py`).
- On each binance update (event-driven; do NOT throttle to the 100ms maker poll), compute
  `ret = binance_spot(now)/px0 − 1`.
- **FIRE when ALL of:**
  - `(now − slot_start) ∈ [TV_FT_OFFSET_MIN_S, TV_FT_OFFSET_MAX_S]` (default 3s … 12s),
  - `abs(ret) * 1e4 >= TV_FT_RET_BPS` (default **3.0** bps),
  - this slug has not already fired (one-shot per slug),
  - (shadow fill passes the book/spread gate below).
- **Direction:** `side = "Up" if ret > 0 else "Down"` (the binance-leading side).

## 2. Shadow fill model (mirror the backtest = `engine_v2.fill_at_book`)
Use the live WS BookMirror (`venues/polymarket/book_mirror.py`) snapshot for the chosen
token at fire time:
- **Latency:** look up the book at `fire_ts + TV_FT_LATENCY_MS` (default 85ms).
- **Min liquidity / staleness:** require a fresh book (reject if the mirror's last update is
  older than ~1s, or fewer than `TV_FT_MIN_BOOK_EVENTS`=25 updates seen this slug).
- **Spread filter:** reject if `ask0 − bid0 > TV_FT_SPREAD` (default **0.05**) — same-token
  bid-ask (this is a directional taker; the cross-token check is NOT relevant here).
- **Book-walk:** walk the ask levels to fill `TV_FT_NOTIONAL_USD` (default **$25**); record
  `vwap, shares, usd`. If under-filled (book too thin for half the notional) → skip (no fire).
- This is exactly `fill_at_book(books, slug, side, fire_us, cfg=LiveMimicConfig, side="buy",
  spread_filter=0.05, notional_usd=25)` from the backtest — reuse that primitive if shared,
  else replicate level-walk semantics.

## 3. Hold + settle (reuse the E1 settlement path)
- HOLD the position to chainlink resolution (no exit by default).
- At resolution: **won → pnl = shares × (1 − vwap) × 0.98** (2%-on-winning-profit, production
  model); **lost → pnl = − shares × vwap**. (Do NOT charge a per-fill taker fee — crypto
  up-down feeRate≈0; the 2% applies only to the winning leg at resolution.)
- Let the existing `fill_sim.settle_slug` / settlement path realize it so the dashboard +
  CSV are consistent with the maker sleeves (E1 fix already live).

## 4. OPTIONAL overlays (config-gated; default OFF — they reduce variance, not return)
- **Stop-loss** `TV_FT_STOP` (default 0.0 = off; suggested 0.15-0.20): if the held side's best
  bid drops to `≤ vwap − TV_FT_STOP`, sell at that bid (shadow: walk bid levels). Raises the
  backtest t-stat 2.28→~3.8 at flat mean — use only for reliability, not EV.
- **Do NOT implement the binance-reversal hedge** — verified it does NOT add return (the
  other side reprices before you can hedge cheap; pair cost ~$1.09). Skip it.

## 5. Config (`/etc/tv/tradingvenue.env`)
```
TV_FT_ENABLED=true
TV_FT_CELLS=btc_5m,eth_5m,sol_5m,btc_15m,eth_15m,sol_15m
TV_FT_RET_BPS=3.0
TV_FT_OFFSET_MIN_S=3
TV_FT_OFFSET_MAX_S=12
TV_FT_NOTIONAL_USD=25
TV_FT_SPREAD=0.05
TV_FT_LATENCY_MS=85
TV_FT_MIN_BOOK_EVENTS=25
TV_FT_STOP=0.0          # 0 = off; 0.15-0.20 to enable stop-loss
TV_POLY_FAST_TAKER_KILL=   # e.g. "fast_taker:sol_15m" to kill a cell
```

## 6. Logging (CSV, mirror the maker sleeve format)
- File: `/var/log/tv/fast_taker/{sleeve}_{date}.csv`, sleeve_id `poly_fast_taker_{asset}_{tf}_shadow`.
- Columns (superset of the maker schema for tooling compatibility):
  `ts_us, strategy, slug, asset, tf, action(FIRE|FILL|SKIP|SETTLE), side, price(vwap),
  size(shares), notional, fill_simulated, px0, px_fire, ret_bps, offset_s, ask0, bid0,
  spread, entry_vwap, outcome, won, pnl, skip_reason, sleeve_id`.
- Log a SKIP row (with `skip_reason ∈ {spread,thin_book,stale,no_signal_in_window}`) whenever
  the gate fires but the fill is rejected — needed to measure live fill-rate vs the backtest's
  65-91%.

## 7. Acceptance / verification (after a few days of shadow)
- **Fire rate** ≈ backtest: ~59 fires/day at 3bps across the 6 cells (scale by active hours).
- **Fill rate** 65-91% (most fires fill; spread filter rejects the rest).
- **WR ≈ 63%** on filled fires; **mean pnl ≈ +$1.0-1.3 per $25 fire** (allow for the OOS CI
  [−0.24,+1.44] — confirm it stays positive and the t-stat builds toward >2 as n grows).
- **Anchor sanity:** confirm fires land 3-12s AFTER slot_start (not at ws_s).
- Cross-check a sample of shadow fires against `strategy_lab/directional/latency_threshold_sweep.py`
  on the same slugs/timestamps — shadow vwap should match the canonical L25 book-walk within ~1 tick.

## 8. Risks / gotchas (from the research)
- **In-sample window is only ~3 weeks** (binance-1s coverage) and **3bps was sweep-selected** —
  the shadow run IS the out-of-sample test. Treat the first 1-2 weeks as validation, not proof.
- Edge window is **5-20s, NOT sub-100ms** — react event-driven on the binance tick, but you do
  NOT need colo to start (Ireland <2ms to CLOB is fine). Firing late (>20s) kills the edge.
- **Binance feed is the signal** — ensure the live binance 1s feed latency is low (<1s); if the
  feed lags, the `ret` is stale and the edge degrades.
- Taker-rebate program (live 2026-05-28, crypto weight 2.3) will REDUCE realized cost vs the
  2%-on-profit model — track actual rebates as upside; don't bake them into the gate.
- Capital for a future live test: pUSD on Polygon; CTF redeem is gasless; start at $25/fire.

## 9. Rollout
1. Ship shadow-only (`TV_FT_ENABLED=true`, no real orders). Run ≥1 week.
2. Verify §7. If WR/mean/fill-rate match the backtest and the t-stat builds → micro-live at
   $25/fire on ONE cell (suggest btc_5m, highest fire count), one wallet, with the kill switch.
3. Scale notional/cells only after a positive live week.

## Source-of-truth backtest (reproduce these numbers)
`strategy_lab/directional/latency_threshold_sweep.py` (3bps significance),
`realistic_latency_validation.py` ($25 fill economics), `latency_walkforward.py` (IS/OOS),
`hedge_realistic.py` (why no hedge). Data: canonical `load.py`, native 10Hz, fresh to May 29.
