# Project context — root

**🟢🧭 LATEST SESSION HANDOFF 2026-06-12→16 — READ FIRST: `strategy_lab/reports/HANDOFF_2026_06_16_SESSION_AUDIT_SUMPAIR_OFI.md`.** Done: (1) **5-lens strategy audit** (`STRATEGY_AUDIT_5LENS_2026_06_12.md`) — momalign "OOS" is contaminated (tail-split, not disjoint), cloud_vwap_v7 FAILS Bonferroni, dead maker-exit still on the live $1 sleeve. (2) **⭐ FOUND+FIXED a ~1s lookahead in every scalp driver** (bar-START asof on klines_1s) — backtest was ~41% inflated; **corrected-causal OOS scalp = +0.91/tr ALL / +1.47 CLEAN (still CI>0)**; STOP still dead, TOD holds; live unaffected (production anchors causally). Patched the 3 main drivers; **microprice/maker_sim/trailing drivers STILL on bar-START — finish the patch.** (3) **Scalp capacity per market** (`SCALP_CAPACITY_PROSPECT_2026_06_13.md`): ~$2.9k/mo OOS, ~$1.5–2k working capital, MaxDD ~$2–2.5k, exit-bound, BTC-5m=44% of profit. (4) **Sum-pair/b945 arb campaign CLOSED offline:** taker DEAD (`sumpair_arb_t1`, dips revert <100ms), short-side DEAD (`sumpair_short_t3`, latency-confirmed 6 markets), **V2 oscillation-harvest = the one real thin edge** (BTC/ETH 5m, scalp-residual, +$0.40/slug 1-clip floor→+$1.77 multi-clip; depth-realism done `SUMPAIR_V2_DEPTH_REALISM_2026_06_14.md`; live $0 shadow `TV_AGENT_SPEC_SUMPAIR_OSC_HARVEST` ready). (5) **OFI gate DEAD** (`SCALP_OFI_GATE_RESULT_2026_06_16.md`) — scalp edge is INVERSELY related to flow intensity; don't gate on flow/CVD. (6) **Pyth Lazer reachable ~50ms** (`pyth_lazer/`, collector not yet ported). (7) **TVRUST gap-check vs new 0xSurferX article** (`TVRUST/docs/ARTICLE_2066506_GAP_CHECK_2026_06_16.md`): ladder A1/A2 config mistakes flagged (Q=20→5, taker-completion off), NOT applied. **Committed+pushed `8258e90` (Lazer key scrubbed, graphify-out/ gitignored).** OPEN: deploy V2/monitor $0 shadows + idle TV specs (operator); TVRUST A1/A2 fixes; finish lookahead patch; HL Donchian promotion (~early July); Poly×Kalshi arb executor. Memories: `project_5lens_audit_2026_06_12`, `project_sumpair_arb_dead`, `project_scalp_ofi_gate_dead`, `project_synthetic_book_marginal`.

**🟢🔬 Wallet 0xce25e214 FULLY DECODED 2026-06-12 (`strategy_lab/reports/WALLET_CE25E214_DECODE_2026_06_12.md`).** Sign-flip RESOLVED: wallet is a **CONFIRMED WINNER** (+$300,397 all-time, $6,986/day lifetime, $2,856/day 30d, `pseudonym: Agile-Spacing`). Legacy −$295k decode was WRONG — `cash_pnl_legacy_alchemy` dropped all REDEEM events (80–90% of income for hold-to-resolution strategies). **Strategy: TAKER PAIR-ARB + RESOLUTION HOLD** — buys BOTH Up+Down tokens as taker in same window (99.5% of slugs paired), holds to resolution. No directional signal (ML side-decode AUC 0.470 = coin flip). Entry timing: 78% fire in first 60s. Overround: median sum_ask 1.041 (+4.1%), only 35% of slugs have sum_ask < 1.0; profits from resolution arithmetic on winner leg. 486 slugs/day across BTC/ETH/SOL/XRP 5m+15m. Per-slug PnL: $5.88/slug (30d implied), $7.31/slug (Jun 12 partial), $31.29/slug (May 15-16 high-vol day, CI95[21,41], t=6.16). MAKER_REBATE $5k total (minor). **DEPLOY: NO** (taker fees ~1.7% vs ~4% available edge; prior Mint-and-sell V2 showed survivorship bias; need strict sum_ask < 0.97 gate pre-registered test before pursuing). Scripts: `wallet_hunt/_ce25_fetch_alchemy.py`, `_ce25_ml_decode.py`. Data: `cache/0xce25e214/{fills,per_leg_chain,ml_features}.parquet`.

**🟢🚀 HYPERLIQUID research → V52/XSM shadow-deploy session 2026-06-11 (READ `strategy_lab/reports/HANDOFF_2026_06_11_HL_V52_XSM_SHADOW_DEPLOY.md`).** Separate stack from the Polymarket canonical pipeline below. Ported the indicator/logic library to **Hyperliquid PERPETUAL futures** (perp-native: continuous PnL, funding, leverage, ATR/signal-flip/trailing exits — NOT binary). New research dir `strategy_lab/hl_research_2026_05_26/` (perp engine `hl_engine.py` + `perp_exit_rules.py`, 24 feature panels, 6 strategy families → `MASTER_TABLE_PERP.{csv,md}` 3,929 cells, `PAPER_DEPLOY_CANDIDATES_PERP.md`, `HL_DEPLOY_SPEC.pdf`). **Winners:** D1 basis-carry (HL-vs-Binance spot-perp), A1 ETH-4h Donchian (OOS Sharpe 3.32, beats BH 5.6×), ETH-4h breakout cluster; funding CONTRARIAN > momentum. **Rejected:** mean-reversion, ML prob-trading (fees>edge), 2-venue arb, all <4h non-carry. **V52+V24-XSM audited (NO bugs; "flat" was 32-44d STALE HL data + 2026 weak regime, now refreshed)** + optimized (`v52_v24_audit/`): new **STF_BTC_V45** sleeve (2026 Sh +3.61), **FUND_Z<2** gate (V41 sleeves), **ATR_NOTOPVOL** gate (volume sleeves). **SHADOW LIVE (paper, $0) at `shadow_v52/`** — hourly Windows task `V52Shadow` runs tick (refresh HL data → 9 V52 sleeves → XSM basket → 10 sleeve cards → 6-card TV feed `_tv_cards_feed.json`). V52=9 per-coin sleeves (46 paper fires/60d, mostly flat in weak regime); XSM=correctly FLAT (defensive filter breadth 1/9). **OPEN (VPS3): production TV dashboard `SHADOW (6)` HL cards show `bundle: none` — VPS3 engine has no HL loop. Spec handed off: `strategy_lab/reports/TV_DEPLOY_SPEC_HL_V52_XSM_SHADOW_2026_06_09.md` (port `shadow_v52/` into a new `hl_perp_loop`).** **Data fact corrections:** Binance `data/binance/parquet/{SYM}/{TF}/` = 8.6y BTC/ETH (NOT 12mo); HL canonical = 4 coins/106d (NOT 2.3y). Promotion gates before HL capital: ≥4wk shadow, Sharpe>1.2, funding reconciles ±5%.

**🟢 Canonical refresh 2026-06-15 ~14:31 UTC (Jun 11→Jun 15, ~4.5 days, `migration_2026_06_11/*` re-run).** Window now Apr 22 → Jun 15 14:31. Max-ts: klines_1m 13:49 (668,588) / klines_1s 13:50 (71.45M) / chainlink_rtds 13:52 (12.39M) / resolutions 12:55 (59,308) / resolutions_from_rtds 12:55 (54,491) / trades btc 44.79M·eth 11.79M·sol 5.23M (13:48) / trading_events_30d 2.92M / cex_futures klines 694,796·**ticker 120.56M**·trades 40.80M·liq 14,155 (14:26-14:31) / **L25 btc 86.03M·eth 16.29M·sol 7.57M (13:50-13:57)**. All ZSTD (writers emit zstd). C: 24GB free. **⚠️ pull-script fix: REMOVED `ORDER BY` from the futures `\copy`s** — the ticker sort was stuck >33 min (huge 4.5-day delta, disk sort); without it the whole futures pull ran in ~5 min (ticker 7.35M rows in 52s). The merge anti-join + loaders sort on read, so server-side ORDER BY is pure waste. (non-L25/L25 pulls still have ORDER BY but they're small/fast; drop there too next time.) **HL ALSO refreshed 2026-06-15 ~18:55 (`migration_2026_06_11/pull_hl.sh` + `merge_hl.py`):** klines 407,295 (→18:53) / liquidations_full 5.40M (→18:52) / funding 13,056 (→Jun14 23:00) / metrics 262,444 (→18:55) / **trades_30d 41.44M (32d rolling, 979MB — HL trade volume grew ~3×)**. All from VPS3 `hyperliquid_*_v2`, full-replace (trades = 32d window), ZSTD. Gotcha: the 1.2GB trades gz truncated on first scp (840/1167MB) → re-download; DuckDB CSV-sniff fails on a truncated gz (verify `gzip -t` after scp). Procedure: bump T_START in the 3 `pull_*.sh`, run pulls on vps3, scp .gz → `refresh_2026_06_11/raw/`, `merge_efficient.py` then `l25_merge_safe.py`, delete refresh dir + vps3 /tmp dumps (NOT the postgres DB).

**🟢🚀 Canonical refresh 2026-06-11 ~06:21 UTC — NEW EFFICIENT PIPELINE (`migration_2026_06_11/*`).** Topped off every collector Jun 8→Jun 11 (~3 days). **Window now Apr 22 → Jun 11 06:21.** Max-ts: klines_1m 05:59 (644,927) / klines_1s 06:00 (70.32M) / chainlink_rtds 04:17 (11.49M, feed lags ~2h) / resolutions 04:55 (55,139) / resolutions_from_rtds 03:50 (51,031) / trades btc 44.71M·eth 11.77M·sol 5.22M (06:01) / trading_events_30d 2.38M / cex_futures klines 504,560·ticker 89.44M·trades 33.72M·liq 12,454 (06:04-06:21) / **L25 btc 83.62M (7.97GB,06:04)·eth 15.79M·sol 7.29M (06:06)**. **⏱️ ~18 min total (was 1-2h).** The win: **download was already incremental** (delta `\copy` via T_START); the cost was the pandas full-file merge. New `merge_efficient.py` = **DuckDB streaming merge reading the .gz deltas directly** (no pandas convert): per table, ANTI JOIN canon vs the small delta on the dedup key + UNION delta, **NO global ORDER BY** (loaders sort on read) → memory-light, no OOM (klines_1s 69M+672k in 23s; futures ticker 69M→89M in 36s). L25 stays pyarrow-streaming (`l25_merge_safe.py`, max_seen dedup) with **tmp on D: + cross-drive safe swap** (C: too tight for BTC's 8GB rewrite; only BTC needs ~9min). Shrink-guard (`total>=before`) aborts before any replace. Pulls: minimal ~3.5h overlap (T_START Jun 8 12:00), not the old hardcoded 4-day. Refresh dir + vps3 /tmp + D: tmp DELETED. HL NOT refreshed (still May 27/16 — separate pipeline). **Next refresh: bump T_START in the 3 `pull_*.sh` + re-run `merge_efficient.py` then `l25_merge_safe.py`.**

**🟢 Canonical recompressed SNAPPY→ZSTD 2026-06-11 (`migration_2026_06_11/recompress_zstd.py` + `recompress_btc_l25.py`).** All big canonical DATA parquets are now ZSTD (lossless, loaders auto-detect codec, decompress still fast). **Total canonical 31.0GB → 24.5GB (saved 6.5GB); C: 7.8GB→14GB free.** Best wins on text/int data (trades btc 1735→979MB, futures ticker 1416→875, klines_1s 2003→1291, trading_events 338→134); L25 float books compress poorly (~15-20%: l25/btc 7971→6549, backfill/btc 5470→4721). Only 3 small `_results/*` research artifacts stay SNAPPY (not source). **The refresh writers (`merge_efficient.py`, `l25_merge_safe.py`) now emit ZSTD** so future refreshes stay compact. Gotcha: don't run two recompress scripts concurrently (file-lock collision on the same parquet); DuckDB COPY chokes on the 97.9M-row wide L25 → use the pyarrow-streaming path for those.

**🟢 Canonical refresh 2026-06-08 ~16:51 UTC (top-off Jun4→Jun8, all collectors incl L25 + futures)** (`migration_2026_06_08/*`, cloned from 06_04, T_START Jun4 00:00). **Window now Apr 22 → Jun 8 16:51 (~47 days).** Max-ts: klines_1m 15:37 (630,731) / klines_1s 15:38 (69.65M) / chainlink_rtds 15:38 (10.97M) / resolutions 14:50 (53,056) / trades btc 44.64M·eth 11.75M·sol 5.21M / trading_events_30d 2.03M / cex_futures klines 390,894·ticker 69.20M·trades 27.81M·liq 10,879 / **L25 btc 82.45M (8.23GB,16:23)·eth 15.49M·sol 7.11M (16:28)**. Refresh dir + vps3 /tmp DELETED (single-source invariant). ⚠️ **Disk now 7.6GB free (97%) — BTC L25 merge needs ~8GB .tmp; CLEAR SPACE before next refresh.** Gotchas: disk hit 100% mid-L25-merge (cleared .tmp, retried); `merge_nonl25` OOMs on the 69M-row 1s-kline sort (run trades/events targeted separately); futures liquidations needed a manual \copy re-run.

**🔴🔬 RESEARCH SESSION 2026-06-08 — momo "profit" PROVEN FICTITIOUS + full sleeve audit + metric/RF-bug fixes.** READ `strategy_lab/reports/MOMO_LIVE_FILL_PLACEHOLDER_PROOF_2026_06_08.md`.
- **🚨 momo/momo_v2 HOLD live shadow PnL is FAKE.** The paper sleeve booked every entry at a **~0.50 placeholder**, not the real fill. Triangulated vs ACTUAL executed Polymarket trades: `corr(live_entry, real_traded)=0.12` (≈0) while `corr(L25_book, real_traded)=0.95` — live "bought DOWN at 0.46" when the token really traded 0.92. Fake-cheap 0.50 on winners manufactured the entire "+$3–4/tr." After the bug was fixed mid-June (real entries 0.65–0.9) live went NEGATIVE (−1.79/tr). **Every momo shadow PnL booked in the placeholder era is fictitious — re-baseline off the real fill; entry_price must = real book ask.**
- **The L25 book walk IS the correct fill engine** (validated corr 0.95 vs real trades, 1s freshness). git forensics: the momo anchor was ALWAYS **W+120 (120s into the current window), never changed** (created 2026-05-05 `3a3053f9` "Binance-latency arb"); the earlier "backtest" used a buggy `ws_s=suffix−900` (fired 13min pre-open, fake vwap 0.49). CORRECTED all-data backtest (real fill ~0.73–0.77): Feb21–Mar24 +$1.79/tr (WR 79.6% vs 74.4% breakeven, t=1.53 ns) · Apr22–Jun8 −$0.28/tr (WR 76.5% vs 78%) = **favorite-longshot on the breakeven knife-edge, NOT a robust edge.** `MOMO_HOLD_F7_BACKTEST_VS_LIVE_2026_06_08.md`.
- **🚨 SLEEVE-PnL METRIC:** rank on the TV **dashboard dedup metric** (`sleeves.py` `_RESOLUTION_DEDUP_ROW_NUMBER` + exclude `fill_method='synthetic'`), NOT raw `events.pnl_usd` (phantom legacy resolver row ~60s later double-counts). Proof: lagv2 +$1681 raw → **−$195** deduped.
- **RF-gate UP-bias** (`RF_GATE_UP_BIAS_AUDIT_2026_06_08.md`): Range Filter (`g_1h_rf_with`/`g_rf_with`) lags reversals → `btc_5m_l_1hrf_imb5_rf/ribbon` bet **77% UP into a −13.7% week** (1h-trend UP only 33%). RF sleeves regime-fragile; imb5 BTC = traps.
- **FULL 2-MONTH SLEEVE AUDIT** (17-agent sonnet workflow, `SLEEVE_BT_VS_LIVE_AUDIT_2026_06_08.md`): 155 live shadow sleeves → 76 KILL. **Only survivors: scalp-exit family + the ETH 5m cloud/hurst sniper cluster** (`cloud_vwap_hurstmp_v7`, `ema50_hurst_grandparent_v8`); thin + decaying (recent t<1). `V10`=`v8`+`g_sms_no_liquidity_above` adds nothing (−26% volume, same $/tr).
- **Kalshi scalp DEAD** (market lists ~+30s after open, born fair → open-only lag edge inaccessible; mid-window lag NULL). **Same-market merge = no uplift** (consensus flat; the ETH cloud∧hurst merge spec INVALID — its +0.62 was a loose-dedup artifact, real = flat +0.007). `NEW_EDGE_RESEARCH_2026_06_08.md`, `SAME_MARKET_MERGE_SCAN_2026_06_08.md`.
- **GROUND-TRUTH RULE held hard** — operator's "13min-pre-open can't be at midpoint" hunch cracked the momo fake-fill. Verify every live PnL vs actual executed trades / the dedup metric, never raw events or shadow entry_price.

**🟢 1s-klines: DOGE/BNB extended to Apr 21 2026-06-05d** (`telonex/backfill_klines_1s_doge_bnb_apr.py` + `_fix1921.py`): DOGE+BNB Binance-spot 1s now **Jan 1 → Apr 21 2026** (9,590,400 rows each, every second, 0 gaps verified) — abuts their poly markets + aliplayer BBO (Apr 6-21), unlocking the 2 new-coin scalp OOS tests. klines_1s.parquet now **67.38M rows**. (Note: the `_apr.py` cap const was Apr 19 not Apr 22; `_fix1921.py` patched the missing 3 days.) **HYPE 1s NOT obtainable free for Apr 6-21:** HL API has no 1s interval (422) + shallow history; open HF datasets stop ≤Mar/Dec 2025; `gionuibk/hyperliquidL2Book-v2` is gated (403, request access); HL S3 archive `s3://hyperliquid-archive/market_data/<date>/<hr>/l2Book/HYPE.lz4` EXISTS (403=requester-pays) → L2-book→1s-mid buildable with AWS creds (~$1 egress). We already have HYPE **1m** (`hyperliquid_klines.parquet`, Jan 30→May 27).

**🟢 1s-klines backfill DONE 2026-06-05c** (`telonex/backfill_klines_1s.py`): backfilled `canonical/klines_1s.parquet` with Binance Vision 1s spot klines for the Polymarket gap **Jan 1 → Apr 6 2026** (abuts existing Apr 7+), **all 6 Binance coins BTC/ETH/SOL/XRP/BNB/DOGE** (HYPE not on Binance). **15.0M → 64.78M rows (+49.77M; file 1.8GB on C:)**, 8,294,400 rows/coin (every second, zero gaps), no nulls/dups. **New 1s coverage:** BTC/ETH/SOL = **Jan 1 → now** (vision Jan1-May6 + live WS May7+, contiguous); **XRP/BNB/DOGE = Jan 1 → Apr 6 only** (vision; NOT collected live — so no 1s for these 3 in the Apr 22+ production poly window unless extended). Source col `binance-vision`, `period_id='1SEC'`; `time_open_us/time_close_us/taker_buy_base/taker_buy_quote` left NULL to match existing vision rows. Vision 1s history goes back to 2017-08 (BTC/ETH), 2020-08 (SOL) — extend further any time via the same script. Raw wiped (single-source invariant).

**🟢 HF aliplayer follow-up DONE 2026-06-05b (READ `telonex/HF_BACKFILL_SESSION_2026_06_05b.md`).** Worked the 4-task list. **(1) ✅** Appended aliplayer `markets.parquet` resolutions (Apr 6-21, all 7 coins) → `resolutions_hf.parquet` now **64,728 rows** incl **BNB 4,295 / DOGE 4,403 / HYPE 4,082**. **(4) ✅** Fixed `1970-01-01` trades bug — cleaned ~648k epoch-0 rows from `canonical_bbo_trades` (btc/eth/sol/xrp) + hardened `aliplayer_convert_duck.py` & `load_trades_hf`. **(2) ❌ HARD LIMIT** + **(3) ❌ NO OVERLAP:** 🚨 **the aliplayer dataset is FROZEN — `lastModified 2026-04-26`, data ends Apr 21. The "auto-updates every 3h" claim was WRONG.** Existing `canonical_bbo` (Mar 30→Apr 21) is already its full extent; production starts Apr 22+ → zero overlap, can't extend or cross-validate vs production. Internal BBO↔resolution check confirms correct joins but thin BNB/DOGE/HYPE books. **No free source fills:** Mar 24-30 gap, Apr 21-22 seam, ongoing BBO for BNB/DOGE/HYPE/XRP after Apr 21. HF token (read) stored locally in `telonex/.hf_token` (gitignored) — `export HF_TOKEN=$(cat telonex/.hf_token)`.

**HF Polymarket backfill DONE 2026-06-05** (`telonex/*`): ingested 3 free HuggingFace datasets (trentmkelly + bmoney1321 + aliplayer1), converted, cross-backfilled (real-resolution > settle-derived; full-depth > BBO), merged into canonical, **wiped all raw** (single-source invariant). New canonical layers: **`orderbook_l25_backfill/{btc,eth}` (97.9M rows each, 10Hz full-depth, Feb 21→Mar 24) + `{sol,xrp}` (0.85M, Mar 1-13)**; **`D:\global_data\canonical_bbo\{btc,eth,sol,bnb,xrp,doge,hype}` — 4.4B BBO rows / 17GB / ~200Hz event-driven, Mar 30→Apr 21** (the 7-coin top-of-book for microstructure edges; BTC alone 2.6B rows — ALWAYS filter); `trades_polymarket_hf/{btc,eth}` (42M, Feb-Mar); **`resolutions_hf.parquet` (64,728 REAL outcomes — bmoney Jan 2→Mar 24 btc/eth/sol/xrp + aliplayer Apr 6→21 all 7 coins incl BNB/DOGE/HYPE; updated 06-05b)**. Coverage chains: Jan 2→Mar 24 (full L25) → Mar 30→Apr 21 (BBO) → Apr 22→now (production). New loaders in `load.py`: `load_orderbook_l25_backfill / load_orderbook_bbo(coin,timeframe=,columns=,...) / load_resolutions_hf / load_trades_hf`. BBO lives on **D:** (17GB), loaders point there. **Provider research** (`telonex/DATA_PROVIDERS_RESEARCH.md`): no L2 book exists anywhere pre-Aug/Oct-2025; PolyHistorical $17/mo > Telonex $79 for crypto-up/down; Tardis.dev for deep CEX liquidations. **Telonex API mapped** (`telonex/TELONEX_ANALYSIS.md`).

**Full refresh 2026-06-04 21:42 UTC (non-L25 + L25 + cross-exchange futures, all incremental)** (`migration_2026_06_04/*`): delta top-off of every collector (T_START Jun 1 00:00, ~9h overlap, no gap). Futures now top-off incrementally (append+dedup) since canonical has the prior ingest. **Max-ts (~Jun 4 20:54-21:42 UTC):** klines_1m=20:54 (610,055), klines_1s=20:55 (15.02M), chainlink_rtds=20:55 (10.09M), resolutions=19:55 / resolutions_from_rtds=19:55 (46,055), trades BTC=20:54 (44.61M)/ETH=20:54 (11.74M)/SOL=20:54 (5.21M), trading_events_30d (rolling). **L25: btc 80.31M (7.61GB, 810rg, max 20:57), eth 14.97M (1.65GB, 21:00), sol 6.80M (714MB, 21:05).** **Futures (4 ex × 6 perp): cex_futures_klines 225,720 (max 21:06), cex_futures_ticker 38.47M (627MB, funding/OI/mark, max 21:06), cex_futures_trades 14.65M (516MB, max 21:29), cex_futures_liquidations 6,185 gate+okx (max 21:42).** NOTE futures are high-frequency — the 3.5-day delta was ticker 31.1M + trades 13.6M raw rows (~780MB gz). New scripts: `migration_2026_06_04/{pull_futures_delta_2026_06_04.sh, merge_futures_to_canonical.py}` (futures delta+append-dedup, vs the 06-01 full-pull). Window Apr 22 → Jun 4 21:06 (~43 days). Sanitized: deleted `refresh_2026_06_04/` + orphaned `refresh_2026_06_03/` (1.3GB leftover) + VPS3 /tmp (0 refresh dirs, no stray .tmp). HL klines/liqs still May 27.

**Prior full refresh 2026-06-01 09:11 UTC (non-L25 + L25 + NEW cross-exchange futures)** (`migration_2026_06_01/*`): standard delta top-off of the existing stack (T_START May 31 00:00, ~14h overlap) PLUS first-ingest of the new VPS3 futures collectors (bitget/bybit/gate/okx perp). **Existing stack max-ts (all ~Jun 1 08:55-09:07 UTC):** klines_1m=09:02 (590,933), klines_1s=09:03 (14.11M), chainlink_rtds=09:03 (9.28M), resolutions=08:55 / resolutions_from_rtds=08:55 (42,301), trades BTC=09:03 (42.79M)/ETH=09:04 (11.26M)/SOL=09:04 (4.97M), trading_events_30d=09:04 (1,417,786). **L25: btc 75.16M (7.04GB, max 09:04), eth 14.03M (1.53GB, 09:07), sol 6.31M (658MB, 09:07).** Window Apr 22 → Jun 1 09:07 (~40 days). **NEW canonical futures files** (4 exchanges × 6 perp syms BNB/BTC/DOGE/ETH/SOL/XRP): `cex_futures_klines.parquet` (72,648 rows, 1MIN/5MIN/15MIN, since May 25), `cex_futures_ticker.parquet` (10.17M rows — mark/index/last/**funding_rate**/**open_interest**, since May 30 22:11 — this is the live replacement for the dead binance_metrics), `cex_futures_trades.parquet` (1.77M rows, trade_id forced str), `cex_futures_liquidations.parquet` (856 rows, gate+okx only — bybit/bitget collectors empty; book table also empty/skipped). Loaders added to `load.py`: `load_cex_futures_{klines,ticker,trades,liquidations}(exchange=, symbol_id=)`. First ingest = full pull (no prior local copy to delta); future refreshes top-off incrementally. Sanitized: deleted `refresh_2026_06_01/` + VPS3 /tmp (0 refresh dirs, no stray .tmp). HL klines/liqs still May 27.

**Prior full refresh 2026-05-31 14:29 UTC (non-L25 + L25)** (`migration_2026_05_31/*`): topped off chainlink RTDS + resolutions + binance klines (1m/1s) + polymarket trades + trading.events + L25 books from VPS3 (T_START May 29 00:00 for all, ~13h overlap, no gap). L25 merged via `merge_l25_topoff.py` (streams existing-canonical + delta → temp → atomic replace; ParquetWriter row_group_size=200_000, metadata==writer-kept verified no truncation). Sanitized: deleted `refresh_2026_05_31/` + VPS3 /tmp (single-source invariant; 0 refresh dirs, no stray .tmp/__pycache__). **Now-current max-ts (all ~May 31 14:15-14:29 UTC):** resolutions/resolutions_from_rtds=14:15 (41,482 rtds rows), chainlink_rtds=14:19 (9.10M), klines_1m=14:18 (586,664), klines_1s=14:19 (13.91M), trades BTC=14:20 (41.94M)/ETH=14:21 (11.03M)/SOL=14:21 (4.87M), trading_events_30d=14:21 (1,308,042). **L25 single file per asset: btc 73.94M (6.93GB, 749 rg), eth 13.82M (1.50GB, 141 rg), sol 6.21M (647MB, 64 rg) — all max May 31 14:23-14:29.** Window now Apr 22 → May 31 14:29 (~39 days). Pipeline same as 05-29 (6 scripts: pull_l25_topoff + pull_delta_nonl25 + convert_l25_topoff + convert_nonl25 + merge_l25_topoff + merge_nonl25_to_canonical). HL klines/liqs NOT refreshed this round (still May 27 full-pull — use `migration_2026_05_26/pull_hl_full.sh` if needed). Note: gotcha-safe path used — `nohup` + `.done` marker so SSH drops don't kill the server-side `\copy`.

**Prior full refresh 2026-05-29 13:17 UTC** (`migration_2026_05_29/*`): same pipeline; superseded by 05-31 above.

**Non-L25 top-off 2026-05-28 20:04 UTC** (`migration_2026_05_28/{pull_delta_nonl25,convert_nonl25,merge_nonl25_to_canonical}.py/.sh`): pulled chainlink RTDS + resolutions + binance klines (1m/1s) + polymarket trades + trading.events 30d from VPS3 storedata, merged into canonical, deleted `refresh_2026_05_28/` (single-source invariant). Now-current max-ts: resolutions/resolutions_from_rtds=May 28 19:55 (38,488 rtds rows), chainlink_rtds=20:03 (8.44M rows), klines_1m=20:01, klines_1s=20:02 (13.19M rows), trades_polymarket BTC=20:03/ETH=20:04/SOL=20:04, trading_events_30d=20:04 (1,039,500 rows). **L25 books NOT refreshed this round** (still May 26 — top off separately via `migration_2026_05_27/pull_l25_topoff*` if needed). 🚨 **Maker-arb correction:** the canonical refresh enabled settling the right-censored maker-arb residual slugs → **the maker-arb "edge" was survivorship bias** (directional losers never get a REDEEM event, so "settled-only inv=0" excluded them and read +$4.44/slug; uncensored truth is −$0.41 to −$3.63/slug, all sleeves net-negative). **Do NOT deploy maker-arb live.** See `strategy_lab/reports/MAKER_ARB_CENSORING_REVERSAL_2026_05_28.md`.

**Last data refresh:** 2026-05-27 13:35 UTC (full 24h top-off across every collector + L25 re-consolidation + HL full re-pull). **Single-source dedup pass 2026-05-27**: freed ~26 GB total. Two rounds:
1. Data dedup (~20 GB): all `data/v4/refresh_*/cache/` deltas (now in canonical), `refresh_*/raw/*.csv.gz` (already converted), scratch CSVs, `canonical/klines_1s/binance_1s_28d.parquet` (duplicate), `canonical/binance_metrics.parquet` (source permanently dead — VPS3 geoblocked). `load_binance_metrics` now raises `FileNotFoundError`. `load_orderbook_l25_streaming` simplified — canonical is the only source.
2. Cruft cleanup (~6 GB): all `.log` files (260 files, 5 GB), all `__pycache__/` + `.pyc` (40 dirs, 157 files), `strategy_lab/_archive/`, `strategy_lab/results/` (315 MB Phase 5 backtests from Apr 17), `strategy_lab/data/polymarket/{btc,eth,sol}_book_depth_v3.csv` + `*_trajectories_v3.csv` (superseded by canonical L25), `migration_ireland_shadow_2026_05_21/` (one-shot audit from May 21, reports already in strategy_lab/reports/), `_v1_original` parquets superseded by `_v2_fixed`, 21 empty dirs. Note: `book_depth_v3` removal may break ~5 old `strategy_lab/meta_classifier/*.py` scripts that referenced it — those scripts predate the canonical pipeline; port to `load_orderbook_l25_streaming` if revived.

Disk now: 29 GB free, 88% used (was 100% full pre-dedup). Repo total: 22 GB. **Window:** Apr 22 → May 27 13:35 UTC (~35.0 days for polymarket/binance/L25 stack; HL klines extend back to 2026-01-30, HL liqs back to 2025-05-25 — full year). Pipelines: `migration_2026_05_25/`, `migration_2026_05_26/`, plus `migration_2026_05_27/{pull_l25_topoff_2026_05_27.sh, pull_delta_nonl25_2026_05_27.sh, convert_l25_topoff.py, convert_nonl25.py, merge_nonl25_to_canonical.py, consolidate_l25_to_canonical.py, verify_all.py}` (HL refresh reuses `migration_2026_05_26/pull_hl_full.sh` + `convert_hl_to_canonical.py`). **All sources current through 2026-05-27 13:25-13:35 UTC.** L25 consolidated: BTC 67.14M / 6.27 GB / 751 row groups; ETH 12.57M / 1.36 GB / 146 row groups; SOL 5.63M / 586 MB / 68 row groups (writer-kept == metadata rows verified, no truncation). Non-L25 max-ts: klines_1m=13:31, klines_1s=13:32, chainlink_rtds=13:32, resolutions=13:25, resolutions_from_rtds=13:25 (37,039 rows post-rebuild), trades_polymarket BTC=13:32 / ETH=13:33 / SOL=13:33, trading_events_30d=13:33 (910,763 events, May 6 → May 27). HL klines=264,675 rows / max 13:34. HL liquidations_full=5,275,626 rows / max 13:35. The retired 30d-rolling-snapshot file `hyperliquid_liquidations_30d.parquet` is gone — `load_hyperliquid_liquidations` now filters the full file at read time. HL trades was NOT refreshed this round (still 30d rolling at 2026-05-16 — pull via the same column-fixed pipeline if needed). **L25 is now a single parquet per asset at `canonical/orderbook_l25/{btc,eth,sol}.parquet`** (BTC 6.16 GB / 65.99M rows; ETH 1.33 GB / 12.34M rows; SOL 575 MB / 5.53M rows), built via `ParquetWriter` with `row_group_size=200_000` (writer-kept == metadata.num_rows verified). `load_orderbook_l25_streaming` reads from the consolidated file (refresh_*/cache/ kept as audit + fallback). Non-L25 max-ts: klines_1m=17:35, klines_1s=17:36, chainlink_rtds=17:36, resolutions=17:25, resolutions_from_rtds=17:25 (36,157 rows post-rebuild), trades_polymarket BTC=17:36 / ETH=17:36 / SOL=17:37, trading_events_30d=17:37 (894,112 events, May 6 → May 26). `binance_metrics_v2` excluded permanently: VPS3 is geoblocked from Binance futures (collector dead since ~2026-04-26); spot klines unaffected. Full refresh playbook documented in `data/v4/canonical/README.md` (the old `build.py --step` interface is deprecated — use `migration_<TAG>/*` scripts).

**🟢🔬 Most recent session handoff (b945 SUM-ARB decode + Pyth Lazer + maker queue-sim + PnL audit, 2026-06-12):** `strategy_lab/reports/HANDOFF_2026_06_12_B945_MAKER_LAZER.md` — **READ THIS FIRST.** Wallet `0xb945945d` (@l5zn1bwom8etsk, the "6 edges" article author, **+$21,742 LB canonical — CORRECTED 2026-06-12; prior +$15.7k "chain-true" was wrong formula, see `B945_PNL_AUDIT_2026_06_12.md`**) fully decoded: **NO entry signal** (ML over 67k fills: open-side AUC 0.53 = coin flip; delta-CONTRARIAN; opens every market in first ~2min) → **he is a passive two-sided MAKER** (rebates $3,645/47 events = 16.8% of lifetime PnL). Pair-lock mechanic dead both ways (dominated with our signal; ruin without). **Queue-aware maker shadow sim BUILT** (`wallet_hunt/_maker_queue_bt.py`, FIFO lower bound + proportional upper — **OVERTURNS the "maker 0% fills" rule for resting-bid regime: 72-76% fill**, but ALL quoting policies ≤0: faithful join-bid −0.05/win SIG-NEG, favorite-band flat, ladders −0.24..−0.41 SIG-NEG) → **live $100 maker probe SUPERSEDED**; one pre-registered variant left = **oracle-gated quoting** (quote only when |rtds_ret5| elevated — his model-D signature). Flow map banked: favorite band 0.55-0.97 markout +2.4¢ / cheap 0.1-0.3 −2.5¢ / sellers uninformed; $2,150/win sell-flow hits bids. **PYTH LAZER (free key) = settlement-value preview: ≤1.3bp from the Chainlink value, LEADS RTDS 1.3-1.8s, 50ms cadence** (`CHAINLINK_FEED_RESEARCH_2026_06_12.md`; Hermes lags 3s, Arbitrum feeds disqualified; **Binance still leads direction 3-7s but 5.6-6.3bp off the value → complementary**); storedata collector RUNNING; **lazer-δ A/B shadow spec live with TV agent** (`TV_AGENT_SPEC_SCALP_LAZER_DELTA_AB_2026_06_12.md` — AMENDED: same-source δ both legs, lazer px − lazer strike latched at slot boundary, because live lazer↔binance basis −6bp = 2× the 3bp threshold). `rs_panel/` is NOT a Rust engine (Python RS backtest). **NEXT SESSION (operator prompt in handoff §F): (1) oracle-gated maker sim variant, (2) per-trade forensic walk of his fresh 3,500 data-api trades vs RTDS/Binance/L25/Lazer feeds through his article's lens.** GROUND-TRUTH RULE applies.

**Prior session handoff (SCALP / retro / infra):** `strategy_lab/reports/HANDOFF_2026_06_11_RETRO_BUGFIX_NEWLENSES.md` — read second. Longest forensic session. **(1)** Scalp new-edge hunt — 7 trials, 0 new edges (mid-window/FVG/cross-asset/regime/trailing/two-sided-arb dead; `SCALP_NEW_EDGE_HUNT_2026_06_09.md`). **(2) MASTER RETRO AUDIT** of 696 reports (`RETRO_MASTER_AUDIT_2026_06_10.md` + `_retro_2026_06_10/01..06`) found a **scalp-harness bug family**: outcome-as-price exit fallback (`1.0 if won else 0.0`), exit-size ignored, BBO `size==0` artifact phantom-skipping ~40% of entries, engine_v2 loser-fee overcharge; + Mar30–Apr21 OOS window is **BURNED** (re-read ≥6×; no fresh offline OOS exists — Feb–Mar timing-fix hypothesis REFUTED). **(3)** Fixed all → corrected harness `strategy_lab/directional/scalp_fill_lib_2026_06_10.py` (use for ANY scalp test; size==0=artifact→carry-forward; never the old fallback). **(4) BUG-FIX RERUN** (`BUGFIX_RERUN_RESULTS_2026_06_10.md`): **STOP +0.88→−2.8 SIG-NEG (FLIPS DEAD)**, **maker-exit +0.42→−0.07 ns (DEAD)**, core scalp edge **STRONGER** (+1.85 vs +0.93; zero false KILLs). **(5) STOP REMOVED both hosts** (Ireland `1746efc`, VPS3 `6eaa154f`) → **FINAL scalp exit = PURE +60s time sell (TP off, stop off); entry unchanged.** **(6) New lenses dead/parked:** Wang-Transform (52M trades → markets ~perfectly calibrated ≤1.5¢; λ_late real-in-prints not-takeable), Microprice (parked), oracle-snipe (DEAD as taker), **maker-with-rebate (DEAD — 0% conservative fills; rebate WAS modeled — DO NOT re-open)**. **(7) Gate-soften:** BNB/DOGE scalp spread→0.12 (`eff02cd2`), XRP stays 0.05, δ floor stays 3; live spread float-fix (`5437e9e4`). **(8) VPS3 host fixes** (`96c4b786`): F2 killed 2 look-ahead-dead sleeves, F3 t+60 markov, Kalshi A/B, sell_leg_fee. **PENDING:** apply `TV_AGENT_SPEC_SCALP_DISABLE_MAKER_EXIT_2026_06_11.md` (15m sleeves both hosts still run maker-exit). **NEXT:** ≥200 live fires on corrected config (only true OOS; judge by live CI not backtest) · **E4 Kalshi ask-depth export** · **Hyperliquid perps** (fresh; own 4-exch+HL liq data; hftbacktest installed). **GROUND-TRUTH RULE applies.**

**Parallel session handoff (momalign scalp + edge-gap map — adds to, partly superseded by, 06-11):** `strategy_lab/reports/HANDOFF_2026_06_09_SCALP_MOMALIGN_EDGEGAP.md`. **NEW & not in 06-11:** (1) **momentum-alignment scalp gate** `g_lag_momentum_align(BTC,30)` (lag-sign==30s-binance-momentum-sign) on the BTC-5m lag scalp at offsets 30/60 — pre-registered single hypothesis, disjoint-**OOS +$4.24/tr CI[1.85,6.52]** (pure +45s), 91% slug-disjoint from the deployed +5s scalp (additive); spec `TV_AGENT_SPEC_SCALP_MOMALIGN_BTC5M_2026_06_09.md` (deploy shadow+live $1; ⚠️ **PURE time-sell, NO stop** — my "+0.73 stop" used the flagged outcome-fallback harness; 06-11 corrected = stop DEAD). (2) **`EDGE_GAP_ANALYSIS_2026_06_09.md`** — 10-agent research map of ALL approaches tried + 12 ranked gaps + dead-end rules; bottleneck is OPERATIONAL. (3) **Gap exec:** queue-aware **maker-exit = DEAD** (fill-model artifact, agrees w/ 06-11); **Poly×Kalshi 15m deep-dip arb DEPTH = PASSED** (88% of dips fillable ≥$5, median ~$30 → real capacity, structural arb, NEXT live action). (4) **ribbon_v8 deprecated+committed** deploy/vps3 `a7c60553` (3 layers). (5) **1s vwap_store "bug" RETRACTED** — scalp fires live on Ireland (8 fills/24h); `TV_AGENT_SPEC_SCALP_ORACLE_LAG_IRELAND_1S_STORE_2026_06_08.md` marked RESOLVED. **Exit-policy/maker-exit findings here are superseded by 06-11; momalign gate + Kalshi-depth + edge-gap map are net-new.**

**Parallel session handoff (DIRECTIONAL fleet — read second):** `strategy_lab/reports/HANDOFF_2026_06_11_CLOUDVWAP_SELECTION.md` — **READ THIS FIRST.** Deep operator-driven quant audit of the directional sniper fleet. **HEADLINE: `cloud_vwap_hurstmp_v7` is the best new ETH-5m sleeve** (gates cloud+entry_vwap_band+hurst_mp, off 60) — shadow OOS $/tr +0.367, WR 67%, **DSR 0.94** (only ETH-5m candidate passing deflation/25-trials), CI95 [+0.06,+0.68], most outlier-robust (10% of PnL from top-2; ex-top2 +0.333); at $1 net of $0.011 tx +0.062/tr, +$3.6/day, MaxDD −$13.87 (lower than the live v8's −$21.90). **TWO SPECS WRITTEN, NOT YET APPLIED:** (1) `TV_AGENT_SPEC_DEPLOY_CLOUD_VWAP_V7_LIVE_2026_06_09.md` (add to Ireland allowlist; $1 already global, no code), (2) `TV_AGENT_SPEC_CLOUDVWAP_V7_COINFLIP_FILTER_2026_06_09.md` (operator chose **0.49-0.51**: additive gate `g_entry_vwap_not_coinflip` skips book-walk vwap∈(0.49,0.51), removes only losers → $/tr +0.379, Calmar 2.94→3.26). **METHODOLOGY BANKED:** (a) the in-sample universe BACKTEST is OVERFIT — adjacency test (in-sample tail vs shadow head, same regime) shows 82→67% WR / +1.5→+0.1 $/tr, v6c3 FLIPS negative; proper full re-run = −62..−90% deterioration CI-sig on 5/6. (b) the **SHADOW is the trustworthy forward number** (prod gates + live feed + real books; skips empty/sparse like live; pnl_usd == 0.07 curve == backtest accounting, 260/260 reconcile); offline gate reproduction is strictly worse (klines recompute gave 47.8% vs faithful 82%). (c) **ex-top2 outlier robustness MANDATORY** (hlcascade50k 278%-in-2-trades = negative without them; tr200_off120 80%). (d) at $1 the $0.011 tx kills thin-edge sleeves. (e) ml4t DSR: `deflated_sharpe_ratio_from_statistics(observed_sharpe,n_samples,n_trials,variance_trials,skewness,excess_kurtosis).dsr`, n_trials=25. **ENGINE PARITY:** VPS3(`deploy/vps3`) ≠ Ireland(`deploy/ireland`) branches; V10 `g_sms` gate logic DIFFERS (VPS3 fixed ~74% pass, Ireland old/broken); cloud_vwap_v7's 3 gates byte-IDENTICAL; cloud_vwap live entered 3 slugs (lost −$3) the paper twin rejected = feed-snapshot direction-flip at the cloud boundary (same fire_us, opposite dir) — NOT an impl difference; v8 base wiring spec-true on VPS3; ⚠️ Ireland duplicate-resolution logging bug (1 slug→106 rows). **KALSHI pre-subscribe DISCOVERY (operator, validated; data agent implementing):** the "+30s no book" wall was OBSERVABILITY (subscribe-late), NOT missing liquidity (validated: median depth 239@+10-30s, 340@+30-60s); `GET /markets?status=unopened` → pre-subscribe orderbook_delta → warm book at open → unblocks early-offset 15m sleeves (ETH `trstack_vwap_offearly` family; SOL all negative). **CYCLOPS wallet** `0xf69af0b9…` decoded (BTC-5m $3 favorite-hold, −$198 lifetime; cluster = funder `0x2e1e827f` + sibling `0x886a78bfd`, small/losing; NOT the F1 treasury — retracted). **NEXT #1: apply the 2 cloud_vwap_v7 specs (same restart, both hosts), judge by live wallet n≥100.** Scripts in `migration_2026_06_08/` + `strategy_lab/directional/eth5m_*_2026_06_09.py`. **GROUND-TRUTH RULE held — operator corrected several premature conclusions (window-mismatch parity artifact, v8-not-V10-is-live, backtest overfit). Trust shadow/live wallet + ex-top2 + DSR, never the in-sample backtest.**

**Prior session handoff:** `strategy_lab/reports/HANDOFF_2026_06_06_OOS_KALSHI_AUDIT.md` — Scalp went OOS-validated on **5 coins** (BTC/ETH/SOL/DOGE/XRP, clean disjoint-window Mar30–Apr21, all gated CI>0 — §D-2 deflation gate CLEARED), via new 1s backfill + aliplayer BBO (`load_orderbook_bbo`). Time-of-day gate (exclude {12,17} UTC / 22–02 boost) also OOS-confirmed. NEW **Kalshi** data → canonical (`kalshi_markets/orderbook.parquet` + `load_kalshi_*`): **real Poly×Kalshi deep-dip arb** (set-cost<0.95 → net +2.7¢/set CI[+1.1,+4.2]; <0.90 → +6.6¢/set; 96% settlement agreement; profit drifts to Poly) — 🔴 GATED on unverified Kalshi ask-DEPTH. Two-host live audit: scalp spec-true on Ireland (live $1, btc_5m_d3) + VPS3 (full shadow fleet incl. new TOD/multi-coin sleeves), BUT 🔴 **live TP@0.65 LEAKS edge → TP stays OFF** (caps runners). ⚠️⚠️ **STOP SAGA — FINAL UPDATE 2026-06-10:** the 06-09 correction ("stop = validated edge +0.88, keep") was itself based on a BUGGY harness (outcome-as-price exit fallback + exit-size ignored). The **corrected-harness rerun REVERSES it: stop paired ON−OFF = −2.8/−3.2 SIG-NEGATIVE on every coin set**, and the maker-exit (+0.42) also flips dead, while the core open-scalp edge survives STRONGER (pooled +1.85 vs +0.93). See `BUGFIX_RERUN_RESULTS_2026_06_10.md` + `RETRO_MASTER_AUDIT_2026_06_10.md`. **RESOLVED 2026-06-11 (operator decision): stop REMOVED on ALL scalp sleeves, BOTH hosts (Ireland `1746efc`, VPS3 `6eaa154f`). Final scalp exit = PURE +60s TIME SELL (TP off, stop off). Entry config unchanged.** **NEXT #1: test maker-EXIT-with-taker-fallback** (exit-side selection is FAVORABLE, unlike the dead maker-entry). All else (meta-label, oracle-determinism[underpowered], cross-timeframe, favorite-longshot, maker-entry) efficient/dead. **GROUND-TRUTH RULE applies.** Prior: `HANDOFF_2026_06_04_ML4T_DSR.md` — Threw everything at a *predictive* edge (ML, 8.8y Binance history, GPU deep nets/LSTM, 4.8M indicator combos, 387k scalp selectors, Kronos, kline→poly) and **formally proved with Deflated Sharpe that the ONLY real edge is the intra-window EXIT-SCALP (execution, not prediction)**: it passes DSR (pre-registered, prob 1.0, sig); the 387k scalp selectors DIE under realistic-variance DSR (0/20 conservative); 415 GPU architectures fail to beat the poly price (0/415); Kronos (real-poly OOS 52.9%, archived), GPU-LSTM (acc≈0.50), 4.8M-combo indicator sweep (only a weak daily-trend cluster, not poly) — all efficient/noise at scale. **ml4t toolkit (engineer/diagnostic/models) installed + validated on Py3.14 = go-forward rigor layer (DSR/PBO/CPCV).** NEXT: CPCV + meta-label the exit-scalp; different-window OOS (`validate_oos.py` + 6-month API w/ books+trades+klines); ≥200 live shadow fires; deploy 6 pending TV specs (425-retry, DISAGR-HAWKES sleeve, scalp +60→+45, entry_vwap band, Kalshi FOK→IOC, bleeder disables). Assets: 8.8y spot + 6y futures klines in `strategy_lab/autoresearch/_data/binance_vision[_deriv]/`; canonical → Jun 4 21:42; torch cu126/CUDA(RTX 3060)+vectorbt+ml4t all working on Py3.14. **GROUND-TRUTH RULE still applies.**

**Prior session handoff:** `strategy_lab/reports/HANDOFF_2026_06_03_SCALP_DEPLOY.md` — Found + validated + DEPLOYED the prior session's one real edge: the **intra-window EXIT-SCALP** — buy the lag-taker token cheap (`entry_vwap<0.55`) and **SELL on the book at +60s instead of holding to resolution** (sidesteps the priced-in trap). Survives walk-forward (+$2.98/tr t=6.33), direction permutation (p=0), and the worst-case fee (bootstrap CI [+1.63,+3.46] excludes 0). Now **16 shadow sleeves on VPS3** (`shadow_scalp_exit_{btc,eth}_{5m,15m}[_d3]_{v1,control_v1}`, δ≥5 @ $25 + δ≥3 @ $5). 🔴 KEY OPEN: the offline FORWARD window is still flat-negative (n<76) → needs **≥200 live forward fires + bootstrap CI>0 before any real capital**. Also this session: 215-sleeve fleet audit (net −$25.4k; 4 EDGE @ t≥2; 25 bleeders to KILL incl INV_NIGHT ×6); **LAGV2 always-UP bug FIXED** (50/50 live); Kalshi 409 → FOK-to-IOC fixed; the new-edge swarm killed 65 candidates (B1 VPIN/C4 CVD = priced-in trap, **WR≠edge**). **PARALLEL session handoff** (per-host live↔shadow parity divergence, RealisticConfig, judge-by-live-wallet): `strategy_lab/reports/HANDOFF_2026_06_03.md`. **GROUND-TRUTH RULE:** verify against actual event fields / live wallet before concluding (multiple mid-session conclusions were overturned). Prior: `HANDOFF_2026_06_01_AUDIT_LAGTAKER_FORENSICS.md`.
Prior handoff: `HANDOFF_2026_05_22_MOMO_F7_MARKOV.md` (5 deploy sleeves at production parity).

---

## 🚀 Currently deployable strategies (2026-05-18)

> ⚠️ **RIGOR-STALE WARNING (retro audit 2026-06-10, `strategy_lab/reports/RETRO_MASTER_AUDIT_2026_06_10.md` — READ IT):**
> the two "deploy-ready" entries below predate the project's rigor layer (DSR/PBO, fill-haircut, 0.07 fee curve,
> survivorship checks). **Cyclops S7 X1** (n=36, E0-era) never re-passed a modern fill/fee/DSR test. **Mint-and-sell V2**
> is positive only on a post-hoc subset with an unexplained 200×–10,000× wallet-PnL gap. Treat BOTH as unvalidated
> hypotheses, NOT deploy-ready. The retro also found the exit-scalp's OOS window is burned + an outcome-leak bug in the
> scalp exit-fallback (`1.0 if won else 0.0`) → magnitude claims need the E1 re-validation package before scaling.

Three strategy lines are in different states. **DO NOT confuse versions:**

### ✅ Deploy-ready

**1. Cyclops S7 X1 — BTC 5m sleeve-active composite**
- Location: `cyclops/` package (full code) + `cyclops/PAPER_DEPLOY_SPEC.md`
- Spec: `strategy_lab/reports/CYCLOPS_CLONE_SPEC_2026_05_16.md` + `cyclops/README.md`
- Triggers when: Cyclops S7 fires (trend+levels coherent, momentum abstain, vwap≥0.30) AND any VPS3 BTC 5m sleeve also fired on same slug.
- Validated: **G1+G3+G4 PASS** at $1 stake on 21d (n=36, WR 80.6%, +$0.244/trade, p=0.002, G4 lower CI=+$0.022 with real fees).
- BTC 5m only — does NOT generalize to ETH/SOL or 15m.
- Best paper-deploy target right now. See [`cyclops/_results/MASTER_TABLE_REAL_FEES.txt`](cyclops/_results/MASTER_TABLE_REAL_FEES.txt).

**2. Mint-and-sell maker V2** (under deep-dive next session)
- Spec: `strategy_lab/reports/MINT_AND_SELL_V2_FULL_REPLICATION_2026_05_16.md`
- Implementation spec: `strategy_lab/reports/MINT_AND_SELL_IMPLEMENTATION_SPEC_V1.md` (now 1,479 lines — §8.5/8.6/8.7 added 2026-05-17 cover worked-example, mid-slug MTM, and a drop-in `PaperLedger` reference class).
- 🚨 **V1 has known flaws** — do NOT deploy `MINT_AND_SELL_LIVE_SPEC_2026_05_16.md` (legacy 2%-fee model; wrong fee math).
- V2 uses corrected fee curve (`0.07 × p × (1-p)` + maker rebate as income), $2.5 notional, $1.005 sum_asks entry.
- Per-fire view is breakeven-to-slightly-negative; **slug-level aggregation flips positive** in the BOTH_SIDES_PARTIALS regime (n=9-113 slugs per cell, mean +$0.04 to +$0.41/slug).
- Polymarket CLOB **hosted on AWS eu-west-2 (London)** — Ireland VPS is near-optimal RTT (<2ms). US East = 130ms (uncompetitive). Verified 2026-05-17.
- Backtest engines: `strategy_lab/wallet_hunt/replicate/{mint_and_sell_scan_v2.py, partial_fill_policy_compare_v2.py, slug_level_aggregation.py}`.

### ⏸ Validated insights, not auto-deployable

**3. F2 cluster (0xa0a50783 + 0x9dae874a)** — directional CLOB taker, $5,900/day per wallet
- Decoded fully in `strategy_lab/reports/F2_FINAL_VERDICT_2026_05_18.md`
- Found: 86% WR config exists on F2's 102 slugs (n=449, FOLLOW + cherry-pick filters). But the trigger formula loses -$14k on the broad 21d universe — F2 has a slug-selection signal we cannot reverse-engineer from canonical data.
- Direction picker IS reproducible: F2 fires contrarian to recent 5s flow_imbalance (12% Up-pick when buyers favored Up).
- Time-of-day pattern: 22:00-02:00 UTC + 9-10 UTC, AVOIDS 12-21 UTC (US hours).
- **Gap**: requires Polymarket CLOB WS event tape + cross-exchange basis to decode the slug-selector. Data-collection roadmap in §5 of the verdict report. Not deployable until those are built.

### 🔬 Background research available

- 9-wallet catalog: `strategy_lab/reports/WALLET_CATALOG_2026_05_17.md` + `WALLET_STRATEGIES_DECODED_2026_05_17.md`
- F1 treasury (`0xf70da97812cb96acdf810712aa562db8dfa3dbef`) seeded 4+ strategy variants including the $254k/day HFT scalper `0xb27bc932` (uses relay wallet `0xf3cfb6a6...` for inventory exit — needs decode).
- Master catalog: `strategy_lab/wallet_hunt/cache/_master_catalog.csv`

---

## ⚠️ READ THIS FIRST: canonical dataset

**All backtests / analyses must read data through `data/v4/canonical/load.py`.**

Stop using `data/v4/refresh_2026_05_*` directly — those have inconsistent schemas, mixed
binance/chainlink-resolved outcomes, and led to multiple session bugs (the `binance-klines-1m`
contamination that inflated baseline PnL by ~$14k, the slug-ws semantic confusion, etc.).

```python
import sys; sys.path.insert(0, "data/v4/canonical")
from load import (
    load_resolutions,           # chainlink-only, ~12-18k markets
    load_klines, load_klines_asof,
    load_chainlink_rtds, load_chainlink_asof,
    load_orderbook_l25_streaming,   # filter by slugs to bound memory
    load_tier1_entries,
    load_trades, asof_strict,
)
```

See `data/v4/canonical/README.md` for full schema, conventions, and refresh instructions.

## Conventions agents must respect

- **Timestamps are UTC microseconds** (`*_us` cols, `slot_start_us`, `timestamp_us`). Seconds-suffix `*_s` columns are also UTC. Never localize, never CET.
- **Slug suffix** (`int(slug.rsplit('-',1)[1])`) = the slot's `slot_start` in seconds. **NOT `ws_s`.** It IS the strike-read time / window start for outcome resolution.
- 🚨 **`ws_s` ≠ `slot_start`** (production controller's signal anchor — see
  `strategy_lab/reports/SESSION_HANDOFF_2026_05_10_WS_S_CONVENTION.md`).
  Production anchors `ret_2m` and `fire_us` on `ws_s = slot_start - window_s`
  (the **PREVIOUS** slot's start). Use the helpers in `data/v4/canonical/load.py`:
  `slug_to_ws_s(slug, tf)`, `add_ws_s(df)`, `ret_2m_at_ws(end_us, prices, ws_s)`,
  and `fire_us = (ws_s + 120) * 1_000_000`. Anchoring on `slot_start` instead =
  lookahead → backtest hit rate inflates 25–40 pp (~85% vs ~50% live).
- 🚨 **F7 RSI anchor = `ws_s = slot_start − window_s`** — VERIFIED 2026-05-21 via
  `_match_live_f7_v2.py` against 1,331 production fires from `fires_with_gates.csv`,
  using **version-aware ws_s derivation** (v1 fires at ws_s+120, v2 at ws_s+60):
    - rsi_at_ws_s:       **94.67%** match ✓ THIS IS THE ANCHOR (per source code)
    - rsi_at_fire_us:    92.41% (works for v2 because fire is only 60s from ws_s)
    - rsi_at_slot_start: 83.70% (post-fire)
  Source-of-truth: `/opt/tradingvenue/backend/app/engine/poly_updown_loop.py`
  function `build_bar_context_t_plus_120/60`: fetches 15 closes at offsets
  `[-840, -780, ..., -60, 0]` from `ws_s`; the LAST close is at `ws_s`.
  Production RSI is **simple-mean Wilder** (NOT exponential), confirmed by source
  comment in `rsi.py`. My implementation matches.
  An earlier verifier (`_match_live_f7.py`, NOT v2) was version-unaware — subtracted
  120 from all fires; that biased v2 fires' "ws_s" by 60s and falsely concluded
  fire_us was the live anchor. The CORRECT verifier is `_match_live_f7_v2.py`.
  Post-hoc analysis scripts that join external CEX kline data to poly resolutions
  MUST anchor at ws_s (NOT at_ts of resolution events). Requires klines fresher
  than the F7 window being scored.
- **Outcome resolution = Chainlink Data Streams.** Never derive Up/Down from binance close. Either use `outcome` flag from canonical resolutions (already chainlink-derived) or compute from `chainlink_rtds.parquet` strike vs settlement.
- **Binance is the SIGNAL source**, matching production momo controller. Coinbase / Kraken / OKX are alternative venues for ablation tests.
- **`asof_strict(end_us, prices, target_us)`** returns close of bar that ENDED at-or-before `target_us`. Causal. Use this for all kline lookups.
- **L25 entry walk** is the production fill model. `book_walk_fill(prices, sizes, $25)` from `strategy_lab/book_walk.py`.
- 🚨 **L25 LOAD CONVENTION — `subsample_1hz=False` MANDATORY for backtests** (2026-05-27): always load L25 at NATIVE 10Hz. Production live engine reads WS BookMirror at every update (~10/sec). Subsampling to 1Hz in backtest creates a "luck of the sample" bias — backtest catches tight-book moments and ignores intermediate thin gaps, while live engine hits whatever the book is at the exact `fire_us` moment. VERIFIED 2026-05-27: V5 live deploy with 1184 evals had 0 placements because cross-token spreads averaged 31% in live data, while backtest (1Hz-subsampled, same-token bid-ask filter) placed thousands of fires. **ALWAYS** call `load_orderbook_l25_streaming(asset, slugs=set(...), subsample_1hz=False, ...)`. Default in code is `subsample_1hz=True` for memory reasons; OVERRIDE it explicitly.
- 🚨 **SPREAD METRIC — backtest must match live `cross-token` definition** (2026-05-27): live controller `polymarket_sniper_v5.py:_compute_spread` uses `abs(up_vwap - (1 - dn_vwap))` (cross-token arb-consistency on $5/$25-walked vwaps). Backtest `engine_v2.fill_at_book` line 234 uses `ask0 - bid0` (same-token bid-ask on the buy side only). These DIVERGE: live's cross-token check fails 99%+ of fires on real books where UP+DOWN vwaps sum to ~1.30 (median per 1184 V5 live evals). For any backtest comparison to live PnL, replicate the live cross-token spread filter, NOT the same-token bid-ask. TV PR pending: live may be patched to also use bid-ask; until then assume cross-token is the production behavior.
- 🚨 **Use `engine_v2.py` for any NEW backtest** — single live-mimic primitive that combines latency + real Polymarket fees + sparse-book filter + strict-asof book lookup. Don't roll your own anymore.
  ```python
  from strategy_lab.engine_v2 import LiveMimicConfig, fill_at_book, hold_pnl, sell_pnl
  cfg = LiveMimicConfig()        # canonical Polymarket fee curve + 85ms latency + min_book_events=25
  # cfg = LegacyConfig()         # OLD 2%-on-profit — NOT production; use LiveMimicConfig (0.07 curve, winner-only)
  # Load L25 at NATIVE 10Hz — do NOT use subsample_1hz=True default:
  books = load_orderbook_l25_streaming(asset.lower(), slugs=set(...), subsample_1hz=False, ...)
  fill = fill_at_book(books, slug, "Up", fire_us, cfg=cfg, spread_filter=0.02)
  pnl  = hold_pnl(fill, won=won, cfg=cfg)
  ```
  Real Polymarket fee at vwap=0.69, 48% hit costs ~$0.43/trade extra vs legacy. See `strategy_lab/reports/HANDOFF_2026_05_16_LIVE_MIMIC_GAPS.md` and `strategy_lab/engine_v2.py` smoke output.
- 🚨 **Polymarket fee model used by production = `0.07 × p × (1−p)` curve, WINNER-ONLY**
  (`p = entry_vwap`). **CORRECTED + OPERATOR-CONFIRMED 2026-06-03** — this SUPERSEDES the
  earlier "2%-on-profit" claim, which was WRONG. Proven against LIVE `poly_updown_resolution`:
  - LOST trades: `pnl_usd = -entry_qty × entry_price` exactly (**no fee on the losing leg**).
  - WON trades: `pnl_usd = entry_qty × (1 − entry_price) × (1 − 0.07 × entry_price)`.
  - WORKED EXAMPLE (live, 2026-06-03, SOL momo_v2 won): entry=0.509, qty=50 → pnl **+23.675**.
    0.07-curve → `24.55 × (1 − 0.07·0.509) = 23.674` ✓.  2%-on-profit → `24.06` ✗.
    Loss example: entry=0.508, qty=50 → `−25.40 = −qty·price` (no fee) ✓.
  For ANY backtest use the **0.07 curve** (`engine_v2.LiveMimicConfig`, or the explicit
  winner-only `pnl_07`: `won → shares·(1−vwap)·(1−0.07·vwap); lost → −shares·vwap`), NOT
  `LegacyConfig`. ⚠️ Verify LiveMimicConfig applies the fee WINNER-ONLY — live charges $0 on
  losers; if it double-charges the losing leg it is slightly too harsh, so prefer the
  explicit `pnl_07` winner-only formula above.
- **Maker side**: makers pay $0 + receive a rebate as INCOME on limit fills via
  `rebate = C × feeRate × p × (1 − p) × rebate_share`. Since the taker fee here is the live
  `0.07 × p × (1−p)` curve (NOT 0), `feeRate` is active — re-validate the rebate share on the
  Polymarket account dashboard before relying on mint-and-sell rebate income.
- **PnL accounting (CORRECTED 2026-06-03)**: trust the **0.07-curve winner-only** numbers,
  NOT legacy 2%-on-profit. The earlier "2026-05-22 verification" that endorsed 2%-on-profit
  was wrong (live resolution events match the 0.07 curve — see worked example above).
  Reports priced at legacy 2% slightly OVERSTATE winning-trade PnL (~$0.36–0.43/win at
  typical vwaps) — re-baseline before comparing to live shadow PnL.
- **Outcome truth — two sources both work**:
  - `outcome` column (chainlink-derived) — present in canonical, default.
  - `clob_winner` column (Polymarket actual settlement) — opt in via `load_resolutions(..., with_clob_winner=True)`. Cache at `data/v4/canonical/clob_resolutions_cache.parquet`. So far 300/300 agreement with chainlink on tested rows. For backtests whose payoff IS what Polymarket pays out, this is the right truth; chainlink stays as an audit channel.
- **Live-WS vs REST staleness — RESOLVED 2026-05-21**: production tradingvenue
  is on **WS-only book reads (Tier-1 WS BookMirror)** per Phase 18.6 Wave 1.
  Live logs verified 2026-05-21 22:55 UTC: every `paper.book_fetched` event has
  `source: "ws_mirror"` from `wss://ws-subscriptions-clob.polymarket.com/ws/market`.
  CLOB REST is now Tier-2 fallback (only when WS mirror is empty for a token);
  Storedata DB is Tier-3 disaster-fallback with CRITICAL alert. Historical
  REST-WS gap of $0.19-0.32 (see `MOMO_REST_LAG_VS_MICROSTRUCTURE.md`) no longer
  affects live PnL. Our canonical L25 backtests now use the same book truth as
  production — apples-to-apples comparison is possible.
- 🔬 **Wallet-strategy decoder is built** — pulls full chain history for any Polymarket wallet via Alchemy `getAssetTransfers`, computes cash PnL + open positions, decodes trigger conditions by joining each fire to L25 book / binance klines / chainlink RTDS at the exact second. See `strategy_lab/wallet_hunt/` and **`strategy_lab/reports/HANDOFF_WALLET_DECODER_2026_05_16.md`** for usage. Already decoded: **mint-and-sell strategy** is the trigger behind all 3 profitable up-down wallets we've found so far ($10k–$344k/day, identical signature). The live-deploy spec is at `strategy_lab/reports/MINT_AND_SELL_LIVE_SPEC_2026_05_16.md`.
- 🚨 **`mint_and_sell_scan.py` legacy bug**: treated maker fee as "80% of taker fee" instead of `fee=$0 + rebate income`. PnL estimates from that scanner are understated ~30-50%. Use the canonical formula above. Fix pending.

## Repo layout (top-level dirs of interest)

- `data/v4/canonical/` ← **read from here** (6.6 GB, Apr 22 - May 15)
- `data/v4/refresh_2026_05_12/` ← latest pull, scratch CSVs (3.5 GB)
- `data/v4/refresh_2026_05_06/` ← L25 baseline cache, referenced by build.py (9.8 GB, kept for rebuilds)
- `strategy_lab/` ← all backtests + analysis scripts
- `strategy_lab/reports/DATA_INVENTORY_2026_05_15.md` ← **next-session quick-start + full inventory**
- `migration_2026_05_12/local_pull.sh` ← dual-VPS pull script (latest)
- `migration_2026_05_12/pull_l25_vps3.sh` ← L25 history pull
- `.planning/phases/` ← phase artifacts (gsd-style)

### Stale / known-issue data sources
- `data/v4/canonical/trades_polymarket/` ← **STALE Apr 22 - May 6** (no fresh delta puller yet). If strategy uses trades, limit window accordingly.

## Active data infrastructure

- VPS2 (Contabo IPv6): polymarket collector (orderbook, trades, resolutions), coinbase/kraken/okx klines
- VPS3 (185.190.143.7): tradingvenue engine + binance klines (live spot-ws + vision history) + chainlink RTDS oracle + production `trading.events`
- Resolution-engine fix is owned by **storedata agent** (their plan: VPS2/VPS3 chainlink merge, derive re-run, TV events cross-check, chained-strike check, UMA decoder, unified v3 view). Until that lands, canonical filters out binance-resolved rows.

---

<!-- KARPATHY-GUIDELINES:start (source: github.com/multica-ai/andrej-karpathy-skills) -->
## Behavioral Guidelines (Karpathy-Inspired)

Behavioral guidelines to reduce common LLM coding mistakes. Merge with the project-specific instructions above. **Tradeoff:** these bias toward caution over speed. For trivial tasks, use judgment.

### 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.
<!-- KARPATHY-GUIDELINES:end -->

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
