# Session Handoff — 2026-06-12 — b945 sum-arb decode campaign + Pyth Lazer feed + maker queue-sim

**READ THIS FIRST in the next session.** This session ran the full b945 ("sum-arb") decode campaign to
its current frontier, built a reusable queue-aware maker shadow sim, and landed the Pyth Lazer feed
work (benchmarks + collector + A/B spec with the TV agent). The next session starts with TWO tasks
(operator's exact prompt at the bottom): (1) the oracle-gated quoting variant in the queue sim,
(2) a one-by-one forensic walk of his freshest 3,500 data-api trades against the price feeds.

---

## A. THE WALLET (target of the campaign)
`0xb945945d5bcaf7b56834d4da8cdf8f8f94b2db68` = `@l5zn1bwom8etsk` — author of the "6 edges" article
(CPU pinning / EV layering / Chainlink-CVD fusion / drawdown maps / sweeper). 100% btc-updown-15m.
Self-funded $9,985 Mar 16 (from the pUSD deposit contract `0xf70da97812` — NOT a treasury; that
old "F1 treasury" clustering claim is INVALID, memory banked). **Lifetime PnL: +$21,742 (LB
canonical, fresh Jun-12 API — CORRECTED; prior +$15,749 "chain-true" and $20,661 LB were stale/wrong;
see `B945_PNL_AUDIT_2026_06_12.md`).** Self-funded $9,985; cross-wallet +$6,100 in / −$6,201 out
(net $0 capital transfers). ~156k buy-txs, ~2,041 settled slugs, WR 69%/slug, payoff ≈1.0, $5 median
clips, ~$726/slug deployed, growth via throughput (447→~20-27k fills/wk from Apr 21) never clip size.
**MAKER_REBATE $3,645 (47 events) = 16.8% of lifetime PnL** (was $3,622/46 events — 1 new event).

## B. RESULT CHAIN (all 2026-06-11/12, chronological — what's PROVEN)
1. **Pair-lock backtests** (`PAIRLOCK_BT_RESULTS_2026_06_12.md`): with our scalp signal → positive
   but STRICTLY DOMINATED by deployed +60s sell (paired −0.37..−0.58, CI<0). Without signal →
   ruin (−0.47..−0.63/mkt). Mechanic carries no alpha.
2. **ML decode** (`WALLET_B945945D_ML_DECODE_2026_06_12.md`): 67,198 fills × 23,724 controls × 22
   features. **NO entry signal exists** (open-side AUC 0.532; he's delta-CONTRARIAN 0.46 = buys the
   lagging side; residual anti-aligned with late oracle). Opens every market in first ~2min
   (time-deterministic). Fire intensity U-shaped in |rtds_ret5| (quotes more when oracle MOVING)
   and rises late-window. **He is a passive two-sided MAKER** (47.6% fills at/below own bid ±2s
   block smear; rebates ≈ his entire 2.4M-sh volume). Feature cache:
   `wallet_hunt/cache/0xb945945d/ml_features.parquet` (90,922 rows, has per-fill book/RTDS state).
3. **Flow/markout study** (`wallet_hunt/_maker_flow_study.py`, 340 windows): $2,150/window
   taker-sell flow hits bids (0% empty windows; ~234 prints/win); sellers UNINFORMED (+0.5¢ 60s
   markout); **band map: 0.55-0.97 = +2.4¢ (good), 0.1-0.3 = −2.5¢ (toxic)**; flow rises late
   ($210→$929 per bucket); queue med 143sh.
4. **Queue-aware maker shadow sim** (`MAKER_QUEUE_SHADOW_RESULTS_2026_06_12.md` ⭐): built
   FIFO-strict (lower bound) + proportional (upper) fill models on canonical trades+L25.
   **OVERTURNS the 06-11 "maker 0% fills" rule for the resting-bid regime** (fills 72-76% of
   windows). But economics: arm A (faithful b945, join-bid both tokens, track) **−0.05/win SIG-NEG
   both models**; arm B (favorite band) flat; arms C/D (static ladders −2/−4¢) −0.24..−0.41
   SIG-NEG (adverse selection; the "47% below-bid" was block-time smear, not a ladder).
   12 cells pre-registered. Sims: `wallet_hunt/_maker_queue_bt.py` + `_maker_ladder_bt.py`;
   artifacts `wallet_hunt/cache/_maker_queue_bt.parquet`, `_maker_ladder_bt.parquet`.
   **Live $100 probe spec SUPERSEDED** (`TV_AGENT_SPEC_MAKER_PROBE_BTC15M_2026_06_12.md` — do not
   run arms A/C/D live; FIFO lower bound already loses with fills present).
5. **Residual hypotheses for HIS profit:** (a) SELECTIVE quoting (model-D signature: quote only
   when |oracle move| elevated → liquidity into taker panics = wider effective spread); (b) queue
   priority from sub-second requote infra (his CPU article section); (c) fatter pool-prorated
   rebate at his volume. (a) is testable offline = NEXT SESSION TASK 1.

## C. DATA ASSETS for the wallet (all under `strategy_lab/wallet_hunt/cache/0xb945945d/`)
- `fill_tape.parquet` — 144,589 chain-reconstructed BUY fills Mar 28→Jun 10 (88.4% token coverage,
  built by `_b945_build_tape.py`; token lookup ext via CLOB-by-condition `token_lookup_ext.parquet`;
  NOTE gamma API does NOT index short-form serial markets — use CLOB `/markets/{condition_id}`,
  condition_id = canonical `resolutions.market_id`).
- `alchemy_transfers.parquet` — FULL chain history Mar 16→Jun 11 (fetch_alchemy.py now retries
  transient errors; USDCE era ≤Apr 28 then pUSD; conversions via `0xc011a7e12a` net out).
- `cache/_pm_portfolio/0xb945945d/activity_TRADE.json` — **data-api capped 3,500 most-recent trades
  (Jun 9-11)** + `activity_REDEEM.json` (stored 2,010; fresh Jun-12 has 2,041 = 31 new) +
  `activity_MAKER_REBATE.json` ($3,645/47 events fresh; was $3,622/46) + `positions.json` +
  `lb_profit.json` (fresh = **$21,742.20**; was stale $20,661). For NEXT SESSION task 2: refetch fresh
  via data-api (`https://data-api.polymarket.com/activity?user=0x...&type=TRADE&limit=...`,
  paginate; hard cap ~3,500) to get the newest trades with precise CLOB timestamps.
- Analysis scripts: `_b945_analyze{,2,3,4,5}.py`, `_b945_ml_decode.py`, `_b945_side_decode.py`.

## D. PYTH LAZER THREAD (landed this session, TV agent implementing)
- **Benchmarks** (`CHAINLINK_FEED_RESEARCH_2026_06_12.md`, 3 rounds + runner
  `strategy_lab/directional/_feed_latency_bench.py`): Polymarket RTDS
  (`wss://ws-live-data.polymarket.com`, topic `crypto_prices_chainlink`, free, 1Hz) = settlement
  truth; Pyth Hermes lags ~3s (watchdog only); Arbitrum push feeds disqualified (deviation-gated);
  **Pyth Lazer (free key in `PYTH_LAZER_TOKEN` env var, real_time 50ms,
  3 HA endpoints `wss://pyth-lazer-{0,1,2}.dourolabs.app/v1/stream`, Bearer auth, feeds BTC=1 ETH=2
  SOL=6) tracks the settlement value ≤1.3bp and LEADS RTDS by ~1.3-1.8s** on move detection.
  **Binance still leads direction by 3-7s but sits 5.6-6.3bp off the oracle value → COMPLEMENTARY:
  Binance = direction, Lazer = settlement-value preview.** Probe `pyth_lazer/probe_lazer.py` ✓;
  collector spec `pyth_lazer/COLLECTOR_SPEC.md`; storedata collector ALREADY RUNNING (operator).
- **A/B spec live with TV agent** (`TV_AGENT_SPEC_SCALP_LAZER_DELTA_AB_2026_06_12.md`): 3 sleeves
  per coin/tf (control rtds/binance-δ +5s; L1 lazer-δ +5s; L2 lazer-δ +3s), shadow $0, BTC/ETH/SOL.
  **AMENDED (key decision): each arm's δ must be SAME-SOURCE both legs** — TV agent measured live
  lazer↔binance basis ≈ −6bp (= our bench from the other side) which is 2× the 3bp δ-threshold →
  L-arms use lazer px − lazer strike (latched at slot boundary). Eval: n≥200/arm, paired per-slug
  diff, dedup metric; promotion CI>0 or equal+better fills+skip-stale<2%; kill if skip-stale>10%.

## E. ALSO THIS SESSION
- Strike-basis Q&A with TV agent: first answered "binance strike all arms", then REVERSED to
  pure-lazer endpoints when the −6bp basis measurement arrived (see D).
- `shadow_engine/` (repo root) = the May maker-arb event-replay engine (MAS/AccM strategies,
  trade-tape maker fill sim with proportional queue share) — its May failure was the CENSORING bug,
  not the engine; reusable. **`rs_panel/` is NOT a Rust engine** (Python relative-strength
  backtest) — no Rust engine exists in this repo despite the operator's recollection.
- Maker-flow/queue scripts run on canonical: trades_polymarket btc (44.7M rows, has `side` =
  taker side) × L25 top-of-book joins validated (105k prints classified, 30s freshness).

## F. NEXT SESSION — OPERATOR'S EXACT PROMPT (do these two)
1. **Oracle-gated quoting variant (free, same sim):** extend `_maker_queue_bt.py` — rest
   favorite-band ([0.55,0.97]) bids ONLY while |RTDS 5s move| is elevated (grid the gate, e.g.
   |rtds_ret5| ≥ {2,5,10} $ for BTC; join RTDS via `load_chainlink_rtds("BTC")` asof). This is the
   model-D signature = the last pre-registered variant before the thread is parked. Pre-register:
   count cells, FIFO+PROP both, full 4,729-window universe, report vs arm-B baseline.
2. **Per-trade forensic walk of his freshest tape:** refetch his last ~3,500 trades from the
   data-api (precise CLOB timestamps, maker/taker inference), then walk entries ONE BY ONE against
   the price feeds (RTDS 1Hz canonical; Binance 1s klines; our L25 books; optionally the live Lazer
   collector data if storedata has accumulated it) — through the lens of his article (EV layering,
   CVD fusion, drawdown map, sweeper). Goal: find what we haven't seen yet (e.g. quote timing vs
   oracle bursts, size laddering, level selection, cancel/replace cadence inferable from fill
   spacing). We have `ml_features.parquet` (book+RTDS state per fill) to accelerate; the new fetch
   adds the FRESHEST days at exchange-timestamp precision.
   **GROUND-TRUTH RULE applies** — verify every hypothesis against his actual fills/PnL, not vibes.

## G. KEY RULES BANKED/UPDATED THIS SESSION
- Maker "0% fills" rule: OVERTURNED for resting-bid-full-window regime (fills real; economics
  still ≤0 in all tested policies). The queue sim (FIFO lower bound) is the new standard tool.
- Same-source δ rule (D above) for any cross-feed signal arm.
- `0xf70da97812` = pUSD deposit contract, never clustering evidence (memory file exists).
- Markout band map: favorite 0.55-0.97 +2.4¢ / cheap 0.1-0.3 −2.5¢ / sellers uninformed overall.

---

## H. §F TASKS EXECUTED 2026-06-12 (follow-up session) — **B945 THREAD PARKED**

**Task 1 — oracle-gated quoting variant: ALL FLAT, thread parked.**
Pre-registered 6 cells (|rtds_ret5| ≥ {2,5,10}$ × FIFO/PROP), full 4,729-window universe
(`MAKER_ORACLEGATE_RESULTS_2026_06_12.md`, sim `wallet_hunt/_maker_queue_bt_oraclegate.py`,
artifact `wallet_hunt/cache/_maker_oraclegate_bt.parquet`). Gate fires 0.4–8.4% of windows
(n=17–397); every cell CI straddles 0 (best E5_fifo +0.149 [−0.061,+0.348]); paired diff vs
arm-B ≈ 0 (−0.026..+0.005). The model-D selective-quoting hypothesis is undetectable at
$1/1Hz-RTDS resolution. **No remaining pre-registered maker variants — do not re-open without
new data (e.g. accumulated Lazer collector feed).**

**Task 2 — fresh-tape forensic walk (3,500 trades Jun 10-12, 49 mkts):
`B945_FRESH_TAPE_FORENSICS_2026_06_12.md`.** Net-new mechanics: he is NOT a static resting-bid
maker but an **active EV-ladder price-following sweeper** — clip size ∝ price (Spearman 0.752;
~$0.34@2¢ → $27@97¢), sub-second cancel/replace in 100% of mkts (3.4 levels/s), 53% of final-3-min
fills at price extremes, RTDS-burst → 1.20× clips (p=0.018; Binance 5m NO effect — he watches the
oracle only), UP/DOWN legs independent (0% same-tx), 77.6% of mkts end >60% tilted.
**Ground-truth verification RETRACTED the one candidate edge:** late-window ≥0.90 sweeper =
favorite-longshot knife-edge — WR 86.5% vs breakeven 95.6% (entire CI below), −$1.96/fill,
−$320 total; one loss wipes 23 wins; ≥0.95 same shape (−$158). The ≥0.90 losses and the loser-
lottery wins come from the SAME 2 late-reversal slugs = two legs of his two-sided book, not
separable edges. Only his FULL book is robustly positive (+$0.38/fill, slug-cluster CI
[+0.02,+0.79]) — portfolio spread capture + EV-ladder sizing + rebates, already shown
unreplicable in the queue sim (arm A SIG-NEG). Outcomes via CLOB winner by conditionId
(49/49 joined; 2/2 agree with canonical). Artifacts: `wallet_hunt/_b945_forensic_{fetch,walk,
sweeper_gt}.py`, `wallet_hunt/cache/_pm_portfolio/0xb945945d/{activity_TRADE_2026_06_12.json,
fresh_tape_with_outcomes.parquet, fresh_tape_mkt_stats.parquet, clob_winners_fresh_2026_06_12.json}`.

**VERDICT: b945's profit = infrastructure (sub-second requote + queue priority + volume-scaled
rebates) on a fully two-sided EV-laddered book. No entry signal, no separable sub-edge, every
tested quoting policy ≤0 for us. THREAD PARKED. Remaining b945-adjacent live item = the Lazer-δ
A/B shadow (§D), owned by the TV agent.**
