# Ireland maker-ladder experiment — FULL line-by-line decode + strategy handoff
**2026-06-30. Supersedes `IRELAND_LADDER_RACER_6DAY_2026_06_29.md` (that was a 6-day sub-slice with two misreads — see §7).**
Source: `vps_ireland` (85.137.174.152) → `tradingvenue_rust` Postgres, `trading.events`. Raw dumps + scripts in `strategy_lab/directional/_ireland_6day/`. PAPER ($0 capital) throughout.

---

## 1. TL;DR — what we have and the verdict
- **The strategy is a two-sided passive MAKER LADDER on BTC-15m Polymarket** (the b945 design): rest bids on BOTH Up and Down, get filled by taker sell-flow, **lock a near-risk-free arb whenever the two fills sum to < $1**, hold the matched pair to chainlink resolution, leave the unpaired remainder ("residual") as directional exposure.
- **13.4 days, 1,161 windows, 98% traded.** The matched-pair PnL is **+$1,611 locked, OUTCOME-INDEPENDENT** (= real money, not a directional bet) — `+$120/day on $5 clips`. The offline NO-GO blocker (pair fraction ceilinged at 0.29) is **BEATEN live: pair_frac 0.80.**
- **The ONE unmeasured number is the residual PnL** (10,634 directional shares held to resolution; the side's entry-vwap and outcome are not logged). Bounded estimate: roughly **−$1,150 … +$960**, most-likely **~neutral**. So TRUE net is very likely **still clearly positive**, but the magnitude is unconfirmed until we log it.
- **CAN WE IMPLEMENT IT (live capital)?** The mechanism works and is paper-positive. **Not yet** — three gates first: (G1) log + confirm residual PnL keeps net > 0; (G2) deploy the watchdog kill-path; (G3) decide the pvs>1 windows (33% of windows lock a *loss* — gateable). Details §8. After that it's a small but real BTC-15m maker book.

---

## 2. What this data IS (plain English + data dictionary)
The Ireland box runs the **TVRUST (Rust) engine** in PAPER mode with several sleeves writing telemetry to one `trading.events` table (cols: `at`, `sleeve_id`, `kind`, `data` jsonb). Sleeves on the box (last 13d):

| sleeve_id | what it is | rows of interest |
|---|---|---|
| **`poly_ladder_btc_15m`** | **THE EXPERIMENT** — the maker ladder | 1,161 `ladder_summary` + 518k each `ladder_tick`/`feed_quality`/`tick_latency` |
| `poly_sniper_v5_btc_15m…` | unrelated directional sniper (paper) | 629 resolve (`outcome: null` — useless) |
| `shadow_scalp_exit_btc_5m_d3_v1` | the deployed scalp shadow | 383 resolve |
| `kalshi_sniper…` / `kalshi_scalp…` | Kalshi paper sleeves | 260 / 72 resolve |
| `poly_sniper_v5_eth_5m…V10` | ETH cloud/hurst sniper | 64 resolve |

**The ladder telemetry (the only thing this handoff is about) = 4 event kinds:**

- **`ladder_summary`** — ONE row per 15-min window (the per-window P&L card). Fields:
  - `slug`/`condition_id`/`asset`/`tf` — which BTC-15m market.
  - `filled_up_sh`, `filled_dn_sh` — shares we got filled on each side (as maker).
  - `paired_sh` = `min(filled_up, filled_dn)` — the matched, hedged shares.
  - `residual_sh` = `|filled_up − filled_dn|` — the **unhedged remainder** on the heavier side.
  - `residual_side` — which side the residual is on (`up`/`dn`/`none`).
  - `pvs` = **paired vwap sum** = (avg up price + avg dn price) for the matched pair. **pvs < 1 ⇒ the pair is profitable** (bought both for < $1, one pays $1).
  - `pair_frac` = paired_sh / max(filled_up,filled_dn) — how much of our fills got hedged.
  - `flow_capture` = our fills as a fraction of total taker sell-flow in the window.
  - `market_sell_total_sh` — total taker SELL flow that hit the book this window (the pie we fish from).
  - `paired_pnl_locked_usd` = `paired_sh × (1 − pvs)` — **outcome-independent locked arb** (verified corr 1.000).
  - `rebate_usd` — maker rebate income.
  - `net_paired_estimate_usd` = `paired_pnl_locked + rebate` (verified exact). **Does NOT include the residual.**
  - `maker_pct`/`taker_pct`/`taker_completions` — execution mix (100% maker, 0 taker here).
  - `skipped_reason` — `null` (traded), `warmup_fail`, or `no_book`.
- **`ladder_tick`** — the per-tick (~every ~2.5s) live ladder STATE: `resting_up/dn`, `best_bid_up/dn`, `paused_up/dn`, running `filled_*`/`pair_frac`/`flow_capture`, `t_remaining_frac`. ~450 ticks/window. This is the intra-window movie.
- **`feed_quality`** — per-tick health of the 4-connection WS RACER: `n_conns`, `warmup_pass`, `book_age_up/dn_ms`, `dedup_first_wins`, `level_updates_applied`, `rejected_delta`, `culled`, `recorder_dropped`, per-conn jitter.
- **`tick_latency`** — per-tick hot-path latency: `hop=recv_to_apply`, `p50_us`, `p95_us`, `max_us`, `n` (samples in the interval).

So: **this is a 13-day, $0-risk live measurement of whether a two-sided maker book can profitably capture Polymarket taker flow on BTC-15m, with full feed-quality + latency instrumentation.** It is the live test the offline sims could not settle.

---

## 3. The strategy mechanics (poly_ladder_btc_15m)
1. **Subscribe early** via a 4-connection WS racer (first-wins dedup) so the book is warm at window open — this is the infra moat that the offline sim (which joined the FIFO queue at +60s) could not model.
2. **Rest two-sided bids** (a "ladder") on Up and Down around the favorite band.
3. **Get hit by taker sell-flow.** Each window ~4,245 shares of taker sells cross the book; we passively absorb a slice as maker (fee $0, + rebate).
4. **Lock the pair:** when we hold matched Up+Down shares bought for sum < $1, that pair is a near-risk-free arb (one side redeems $1 at resolution). Hold both legs to chainlink settle.
5. **Residual:** the excess on the heavier side is unhedged directional risk, intended to be scalp-exited (the b945 "−$29k drag" component). **In this build the residual's exit/PnL is NOT logged** — it just reports the share count.

---

## 4. Results — line by line (1,138 traded windows)
```
metric                   mean      median     p10      p90      min      max       SUM
pair_frac               0.7993    0.8751    0.5185   0.9782   0.000    1.0000      —      ← beats offline 0.29 NO-GO
pvs (paired vwap sum)   0.9557    0.9665    0.8382   1.0666   0.490    1.4345      —      ← <1 = arb; p90>1 = some lose
flow_capture            0.0170    0.0162    0.0055   0.0300   0.000    0.0784      —      ← only 1.7% of flow (b945=11.5%)
filled_up_sh           35.05     29.44     10.0     68.0      0       198.4    39,889
filled_dn_sh           34.31     28.32     10.0     67.6      0       201.9    39,050
paired_sh              30.01     24.33      5.2     61.8      0       189.3    34,153
residual_sh             9.34      6.46      1.69    17.88     0       128.7    10,634     ← directional, PnL UNLOGGED
maker_pct               1.00 (100% maker, taker_completions = 0 everywhere)
market_sell_total_sh 4,244.9   3,730.6   1,969.5  7,082.1  793.9  18,486.7  4.83M       ← the flow pie
rebate_usd              0.104     0.088     0.023    0.203   0.0005   0.5815     118.41
paired_pnl_locked_usd   1.312     0.625    -1.355    4.851   -9.178   29.95    1,492.86   ← OUTCOME-INDEPENDENT
net_paired_estimate_usd 1.416     0.715    -1.290    5.056   -8.899   30.53    1,611.27   ← = paired + rebate
```
- **residual_side:** up 635 / dn 499 (net-LONG BTC via the residual → residual PnL carries a BTC-direction beta over Jun 16–30).
- **pair_frac buckets:** 829 windows in (0.75,0.99], 27 at ~1.0, only 54 at ≤0.25 → strong pairing the norm.
- **33% of windows lock a pvs>1 pair (a real loss):** 361/1,089 windows had pvs>1 (worst 1.434); paired_pnl<0 in 361 windows summing **−$442**. Winners dominate → net still +$1,611. **So it's positive-EV-on-average, NOT riskless every window.**

**Per-day (traded windows):** steady. net_paired/day ranged ~$80–193 over the full days; pair_frac 0.73–0.83; pvs 0.93–0.98; flow_capture 1.5–2.2%. No decay or blow-up across 13 days. (Jun 16, 28–30 are partial days.)

**Feed-quality (per-window, 1,169):** 4 conns always; **98.7% warmup-pass at the window level**; `dedup_first_wins` 15.7M (racer collapsed 15.7M duplicate frames); `level_updates_applied` **468M** (≈405/s — the delta stream IS being consumed → book is delta-fresh); `rejected_delta` 448k total (the >15¢ outlier gate); `recorder_dropped` 0; `culled` 1,956. `book_age` median ~72s on traded windows — **almost certainly a keyframe-age / idle-inclusive metric, NOT real staleness** (468M live level-updates + healthy pvs contradict a 72s-stale book); worth confirming the metric definition.

**Latency (`recv_to_apply`, 191k non-idle samples):** **p50 61.6µs, p95 123µs, max 228ms** (one outlier). The Rust hot path is sub-100µs. **Latency is not a constraint.**

---

## 5. Why the +$1,611 is REAL money (the locked-arb decomposition)
Verified exactly (corr 1.000, fee residual $0.0000):
```
paired_pnl_locked  =  paired_sh × (1 − pvs)        ← you own X Up + X Dn, paid pvs·X, redeem $1·X. Profit independent of WHO wins.
net_paired_estimate = paired_pnl_locked + rebate
```
Because you hold **both** legs of the matched pair to resolution, the matched-pair PnL does **not** depend on the BTC outcome — it only depends on whether you got both fills for a combined price under $1. That is a genuine, repeatable **execution arb**, and it printed **+$1,611 over 13 days of paper**. The skill is purely in getting resting bids filled cheap on both sides; the racer/early-placement is what makes the fills happen (offline you couldn't, hence 0.29 → NO-GO; live 0.80).

---

## 6. The one unknown: the residual (this is the whole ballgame for go-live)
The residual = 10,634 unhedged shares (9.34/window) held directionally to resolution. We log the **share count and side** but **not the entry vwap or the win/loss** → PnL unmeasurable from current telemetry (the box's other sleeves log `outcome: null`, so no backfill path). Sensitivity (winner-only 0.07·p fee):
```
                    P(residual_side wins):   45%             50%             55%
residual entry_vwap 0.45            $  -83 (-0.07/w)  $ +440 (+0.39/w)  $ +962 (+0.85/w)
                    0.48 (≈pvs/2)   $ -403 (-0.35/w)  $ +120 (+0.11/w)  $ +642 (+0.56/w)   ← most-likely row
                    0.50            $ -615 (-0.54/w)  $  -93 (-0.08/w)  $ +429 (+0.38/w)
                    0.55            $-1146 (-1.01/w)  $ -624 (-0.55/w)  $ -101 (-0.09/w)
```
**Most-likely** (residual bought near the observed ~0.48 side-price, BTC-15m outcomes ~coin-flip): residual ≈ **neutral-to-slightly-positive** → **TRUE net ≈ +$1,600 ± a few hundred, still clearly positive.** **Worst plausible** (we systematically buy the favorite rich at 0.55 and it mean-reverts to 45% wins): residual ≈ **−$1,150**, which would roughly halve the gain but NOT flip it negative. The residual cannot, on these numbers, plausibly turn the whole strategy negative — but it must be measured before capital.

---

## 7. Corrections to the 6-day report (`…RACER_6DAY_2026_06_29.md`)
That report queried a 6-day sub-slice and made two misreads now corrected by the full pull:
1. **"warmup_pass ≈ 20% (80% of windows fail)"** — WRONG. That was the *tick-level* rate (early ticks each window fail warmup until the book is ready, then flip to pass). **At the window level 98.7% pass and 98% trade.** Coverage is fine.
2. **"+$623 paired, true net unknown, residual could cancel it"** — the +$623 was the 6-day slice; full 13.4d = **+$1,611**. And "paired" is **outcome-independent locked arb**, not a fragile directional number — the residual is a *separate, smaller* exposure that (per §6) most-likely cannot cancel the paired gain. Reframe: the paired arb is the edge; the residual is a bounded side-risk.
Everything else (pair_frac 0.80 beats offline, flow_capture low, latency excellent, residual-PnL-unlogged is the #1 fix) stands.

---

## 8. Can we implement it? — go-live gates
**Mechanism: validated (paper).** Pair_frac 0.80, locked arb +$120/day, latency ready, racer working, 0 recorder drops. **Before ANY capital:**
- **G1 — measure the residual.** Add to `ladder_summary`: `filled_up_vwap`, `filled_dn_vwap`, the chainlink `outcome`, and computed `residual_pnl_usd` (held-to-resolution). Run ≥1 week. **Gate: net_paired + residual_pnl + rebate, bootstrap CI > 0.** This is the single deciding number.
- **G2 — watchdog.** Deploy `tv-watchdog` (kill-path, independent creds, consumes `kill_switch_requested`) on the Ireland box BEFORE flipping any live arm. No live without it.
- **G3 — pvs>1 gate (free EV).** 33% of windows lock a pvs>1 *loss* (−$442 total). Test refusing to complete a pair when the running sum ≥ ~0.99 (leave it as residual / re-quote) — could lift locked net toward ~+$2,050, at the cost of more residual. Pre-register and measure.
- **Then:** Stage-1 $1–5 live on BTC-15m only, judged by the LIVE wallet (not paper), ≥200 windows, same gates.

**Scale levers (after go-live):** flow_capture is only **1.7%** vs b945's 11.5% → the book is too thin/few-levels. Denser multi-level EV-layered quoting is the 5–10× lever, capacity-bounded by the ~4,245 sh/window flow and by keeping pvs<1 as you add size. Naive ceiling ~$1–2k/day; real capacity less.

**Hard constraints (unchanged):** BTC-15m only (ETH/SOL/5m straddle 0 / untested here). Never fee maker/redeem legs. Everything in TVRUST (Rust); Python Tradingvenue frozen. Storedata (delta collection) and TV (execution) stay separate.

---

## 9. Immediate next steps (priority)
1. **TV agent:** add the G1 residual telemetry to `poly_ladder.rs` `ladder_summary` (4 fields above) → redeploy paper → 1wk. *(This is the unlock; nothing else decides go-live.)*
2. **Me (research):** once G1 data accrues, compute true-net bootstrap CI; test the G3 pvs≥0.99 gate offline on the `ladder_tick` tape we already have.
3. **TV agent:** confirm `tv-watchdog` is deployed on Ireland (G2).
4. **Verify** the `book_age` 72s metric definition (keyframe-age vs true staleness) and the 448k `rejected_delta` gate isn't eating real moves.
5. Independent of this: the `orderbook_deltas_v2` write regression on VPS3 storedata is still open (`STOREDATA_DELTA_WRITE_REGRESSION_2026_06_29.md`) — blocks the *offline* Phase-2 maker sim, not this live ladder.

**Bottom line:** the maker ladder's core edge (two-sided sum<1 capture) is **live-validated and paper-positive (+$1,611/13d, outcome-independent)** — the offline NO-GO is overturned. One telemetry fix (residual PnL) stands between "very likely profitable" and "confirmed deploy."
