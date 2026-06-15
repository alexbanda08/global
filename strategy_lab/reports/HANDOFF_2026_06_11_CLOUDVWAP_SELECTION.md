# Session Handoff — 2026-06-11 — ETH-5m sleeve selection (cloud_vwap_v7) + rigor + Kalshi pre-subscribe

**READ FIRST.** This session was a deep, operator-driven quant audit that produced one
deploy-ready new sleeve (`cloud_vwap_v7`), two TV-agent specs, a corrected methodology, a wallet
decode, and a validated Kalshi infra discovery. NOTE: the scalp stop-removal work (06-10/06-11,
`project_scalp_exit_config`) was done by OTHER agents in parallel — not this session; see that
memory for the final scalp config (pure +60, TP off, STOP off).

## A. THE HEADLINE DELIVERABLE — `cloud_vwap_hurstmp_v7` is the best new ETH-5m sleeve
Searched all 25+ ETH-5m shadow sleeves (VPS3), ranked rigorously. **`cloud_vwap_v7`** wins:
- Gates: `g_tr_above_cloud` + `g_entry_vwap_in_band` + `g_hurst_mp_trend_with`, ETH 5m BOTH, off 60.
- Shadow OOS (May29→Jun09, fee 0.07 verified == backtest): **$/tr +0.367, WR 67%, DSR 0.94**
  (only ETH-5m candidate passing deflation for 25 trials), CI95 [+0.06,+0.68], **most
  outlier-robust** (only 10% of PnL from top-2 trades; ex-top2 +0.333).
- **$1-stake net of $0.011 tx: +0.062/tr, +$3.6/day, MaxDD −$13.87** (lower DD than the live v8's −$21.90).
- Diversifies from v8 (~50% own slugs).
- TWO SPECS WRITTEN (ready to apply, both reversible, apply on BOTH hosts to keep shadow==live):
  1. `TV_AGENT_SPEC_DEPLOY_CLOUD_VWAP_V7_LIVE_2026_06_09.md` — add to Ireland live allowlist ($1;
     sleeve exists, global live notional already $1, no code/override needed).
  2. `TV_AGENT_SPEC_CLOUDVWAP_V7_COINFLIP_FILTER_2026_06_09.md` — **OPERATOR CHOSE 0.49-0.51**:
     new additive gate `g_entry_vwap_not_coinflip` skips fires with book-walk vwap ∈ (0.49,0.51)
     (pure coinflip pocket, −0.79/tr, n=7). Removes only losers → $/tr +0.367→+0.379, total +$5.5,
     Calmar 2.94→3.26. **Do NOT widen** (wider bands cut profitable fires; Calmar is overfit-sensitive
     to the exact edge — 0.40-0.60 gave 2.89, 0.41-0.59 gave 3.97 from a 0.01 shift = fitting noise).
- NOT YET APPLIED — awaiting operator/TV-agent to apply both specs (suggest same restart).

## B. METHODOLOGY CORRECTIONS BANKED (the durable lessons)
1. **The backtest (in-sample universe) is OVERFIT — do NOT use it to rank/judge.** Adjacency test
   (in-sample tail May21-26 vs shadow head May27-Jun1, ADJACENT days = same regime): WR drops
   82→67%, $/tr +1.5 → +0.1 (v6c3 FLIPS negative). Even the proper full re-run (`eth5m_full_period_proper_2026_06_09.py`)
   shows −62% to −90% deterioration, CI-significant on 5/6 sleeves. **The universe is the GA TRAINING set.**
2. **The SHADOW is the trustworthy forward number** (production gates + live feed + real books;
   skips empty/sparse book like live — NOT synthetic). Verified: shadow `pnl_usd` == the 0.07
   winner-only curve, 260/260 reconcile == the backtest accounting. Offline gate reproduction is
   strictly worse (the from-scratch klines recompute gave WR 47.8% vs the faithful 82%).
3. **Outlier robustness (ex-top2) is mandatory.** `a2_hlcascade50k_v9` had 278% of profit in 2
   longshot trades (negative without them); `tr200_off120` 80%. Filter: drop sleeves with >40% of
   PnL in top-2. Clean survivors: cloud_vwap_v7 (10%), v8 (17%), cloud_ribbon_v6 (14%).
4. **At $1 stake the $0.011/trade tx cost kills thin-edge/high-volume sleeves** (e.g.
   `ema50_parent15m` net ≈ +0.0005/tr after outliers+tx). Only cloud_vwap_v7 + v8 clear it robustly.
5. ml4t DSR signature: `deflated_sharpe_ratio_from_statistics(observed_sharpe, n_samples, n_trials,
   variance_trials, skewness, excess_kurtosis)` → `.dsr`. n_trials=25 (fleet sweep). Scripts in
   `migration_2026_06_08/` use it.

## C. PORTFOLIO / DIVERSIFICATION findings
- v6c3_parent15mrang_v7 ⊂ cloud_ribbon_v6 (74% Jaccard, +0.75 corr) — REDUNDANT, never run both.
- cloud_ribbon_V10 = the only low-overlap one but DSR 0.07 (unproven, n=121) + only 3-4% NEW slugs.
- **NO SOL-5m sleeve is profitable/robust** (all negative). SOL is out.
- Best robust diversifier with NEW slugs = `ema50_hurst_parent15mrang_v7` (28% new) — but thin edge,
  dies on tx at $1. Operator decided: add ONLY cloud_vwap_v7 (1 sleeve), not a 3-sleeve portfolio.

## D. ENGINE PARITY findings (`ENGINE_PARITY_DIFF_2026_06_08.md`)
- VPS3 (`deploy/vps3`) and Ireland (`deploy/ireland`) run DIFFERENT git branches w/ per-host patches.
- V10 `g_sms_no_liquidity_above` gate DIFFERS in logic: VPS3 = FIXED (~74% pass, matches backtest),
  Ireland = OLD (~broken). cloud_vwap_v7's 3 gates are byte-IDENTICAL across hosts (verified).
- **cloud_vwap_v7 live-vs-shadow flips:** live entered 3 slugs (all lost −$3) that the paper twin
  rejected — same fire_us, OPPOSITE direction. Cause = the live and paper paths read the Binance
  feed INDEPENDENTLY at fire_us; at the cloud boundary (close≈cloud) they pick opposite directions.
  Implementation is identical; it's a feed-snapshot parity flip on marginal slugs. Operator declined
  the snapshot-share fix (shadows on VPS3, live on Ireland — cross-host). Boundary flips are small noise.
- v8 base wiring AUDITED on VPS3 shadow: perfectly spec-true (ETH 5m, off 60, 3 gates, l25_walk,
  spread 0.02, no synthetic) — `SCALP_FWD_FIRES_STATUS`-style audit, 357/357 placed all-gates-passed.
- ⚠️ Found a DUPLICATE-RESOLUTION logging bug on Ireland (one V10 slug → 106 resolution rows).

## E. KALSHI — pre-subscribe DISCOVERY (operator, validated; data agent implementing)
- **The "+30s no Kalshi book" wall was an OBSERVABILITY artifact, NOT missing liquidity.** Validated
  on `kalshi_orderbook.parquet`: median depth 239 @ +10-30s, 340 @ +30-60s, 100% markets quoted.
  Old data subscribed AFTER open → missed the warmup. `GET /markets?series_ticker=&status=unopened`
  returns upcoming markets pre-open (public) → subscribe `orderbook_delta` before open → warm book.
- **Unblocks early-offset 15m sleeves on Kalshi.** Memory `project_kalshi_scalp_deprecated` CORRECTED.
- 15m Kalshi sleeve search: only `btc_15m_ema50_ema800_off600_down` passed the old offset≥60 filter
  (favorite-continuation, +5pp edge over breakeven, already live on Kalshi per operator). NO clean
  ETH/SOL 15m at offset≥60 (ETH good ones are all offset-30 "offearly"; SOL all negative). With
  pre-subscribe, the ETH offearly family (`eth_15m_trstack_vwap_offearly` n=235 robust) becomes the
  candidate — validate fill on the new pre-subscribed Kalshi book at +30s.

## F. WALLET — Cyclops decode (`CYCLOPS_WALLET_GRAPH_2026_06_08.md`)
- `0xf69af0b9af9c92a342b682e5dee262dbc39e7b5c` = "Cyclops.exe", BTC-5m ~$3 favorite hold-to-resolution.
- Last 4d: 78 buys, −$16.36, WR ~79% (longshot-favorite, still bleeding). Lifetime −$198.
- On-chain graph: NOT the "F1 treasury" (that's a shared 827-cp onramp — retracted). Real cluster =
  funder EOA `0x2e1e827f` (gas+USDC, 0 trades) + sibling bot `0x886a78bfd` (btc-5m, abandoned). Small,
  losing. Root above the funder = shared onramp/1inch (untraceable).

## G. NEXT STEPS (recommended)
1. **Apply the 2 cloud_vwap_v7 specs** (deploy live $1 + the 0.49-0.51 coinflip filter), same restart,
   both hosts. Then judge by the LIVE wallet at n≥100 (expect live<shadow; wide-book execution gap).
2. **Kalshi:** once pre-subscribed book lands, re-run `kalshi_book_timeline.py` + validate
   `eth_15m_trstack_vwap_offearly` fill at +30s on the real Kalshi book.
3. Fix the Ireland duplicate-resolution logging bug (one slug → 106 rows).
4. (optional) Quantify live stop slippage / the g_sms-fix-to-Ireland for V10 — lower priority.

## H. KEY FILES THIS SESSION (all in strategy_lab/reports/ unless noted)
Specs: `TV_AGENT_SPEC_DEPLOY_CLOUD_VWAP_V7_LIVE_2026_06_09.md`,
`TV_AGENT_SPEC_CLOUDVWAP_V7_COINFLIP_FILTER_2026_06_09.md`.
Analysis: `ETH5M_V8_V10_RERUN_2026_06_08.md`, `V10_SHADOW_VS_LIVE_PARITY_2026_06_08.md`,
`ENGINE_PARITY_DIFF_2026_06_08.md`, `SCALP_FWD_FIRES_STATUS_2026_06_08.md`,
`CYCLOPS_WALLET_GRAPH_2026_06_08.md`.
Scripts: `migration_2026_06_08/` (all the sleeve/portfolio/robustness/DSR/Kalshi scripts),
`strategy_lab/directional/eth5m_full_period_proper_2026_06_09.py` (the proper backtest-vs-shadow),
`strategy_lab/directional/eth5m_candidates_backtest_2026_06_09.py`.
GROUND-TRUTH RULE held throughout — operator corrected several of my premature conclusions
(window-mismatch parity artifact, v8-not-V10-is-live, backtest overfit, tx-cost on thin sleeves,
outlier contamination). Trust shadow/live wallet + ex-top2 + DSR, never the in-sample backtest.
