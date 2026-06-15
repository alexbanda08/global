# 05 — DATA / FILL / FEE INFRASTRUCTURE AUDIT

**Date:** 2026-06-10
**Auditor role:** senior quant data engineer — trustworthiness of historical backtest results.
**Scope:** fee model, fill/latency primitive, L25 fidelity, spread metric, anchor convention,
outcome-source contamination, coverage gaps, data-acquisition ROI, refresh-pipeline integrity.

---

## 1. CONTAMINATION TABLE

Legend: **status** = is the bug fixed / live in current code? **re-base** = do still-relied-on
results need re-pricing/re-running?

| # | Issue | Introduced | Caught / fixed | Period of analyses contaminated | Reports / decisions that PREDATE the fix | Still-relied-on results to RE-BASE |
|---|---|---|---|---|---|---|
| 1 | **Fee model: legacy 2%-on-profit vs operator-confirmed `0.07·p·(1−p)` winner-only** | Inception. `LegacyConfig` (2%-on-profit) was the only model until `engine_v2` (2026-05-16). The CLAUDE.md "2026-05-22 verification" that *endorsed* 2% was itself WRONG; operator-confirmed correction landed 2026-06-03. | Curve added 2026-05-16; operator ground-truth (live `poly_updown_resolution`) 2026-06-03. | Every backtest priced at 2% (≈43 files still use `LegacyConfig` per Data-Window-Audit §6). Winning-trade PnL overstated **~$0.36–0.43/win** at typical vwaps. | All Round 1–7 panels (`oos_fires_*`, `master_gate_features_v2` — expose `pnl_legacy_usd` ONLY), Cyclops S7 G4 numbers, mint-and-sell V2 fee math, most pre-06-03 momo/scalp reports. | Any report comparing backtest $/trade to live shadow PnL. Winner side: re-price with `(1−p)(1−0.07p)`. Note 2% and 0.07-curve give *similar* winner numbers (~$0.36 gap), so **rankings mostly survive; absolute PnL does not.** |
| 2 | **L25 `subsample_1hz=True` default → luck-of-sample bias** | Loader default since canonical inception. | 2026-05-27 (V5 live: 1184 evals, **0 placements**; backtest placed thousands). | Any backtest that did NOT explicitly pass `subsample_1hz=False`. Microstructure/spread-sensitive fills are the worst hit. | All pre-05-27 L25 backtests using the loader default (V5 sniper family, momo full-universe fills, spread-filter sensitivity work). | Re-run spread-/fill-sensitive backtests at native 10 Hz. **Rule now: always `subsample_1hz=False`.** Outcome-only/feature-panel work unaffected. |
| 3 | **Spread metric divergence: live cross-token `abs(up_vwap−(1−dn_vwap))` vs backtest same-token `ask0−bid0`** | Inception (`engine_v2.fill_at_book` uses same-token `ask0−bid0`, line 273-275). | 2026-05-27 (`SPREAD_FIX_VERIFICATION`): cross-token blocks 79% of fires that same-token passes. | Every L25 backtest's *placement count* is inflated vs what live-cross-token would place. PnL per-fill OK; **fire frequency / throughput is not.** | V5 0-placement incident; any "fires/day" or capacity projection built on backtest placement counts (e.g. BACKTEST_VS_SHADOW_GAP fire-cliff math). | DECISION PENDING: TV may patch live to same-token bid-ask (verification says safe). Until patched, **treat backtest placement counts as upper bounds**, not live-achievable. |
| 4 | **`ws_s` vs `slot_start` anchor (lookahead)** | Pre-2026-05-09 pipelines anchored on `slot_start` → 2 min INSIDE window = lookahead. | 2026-05-09/05-10 (`SESSION_HANDOFF_..._WS_S_CONVENTION`); F7 RSI anchor re-verified 2026-05-21 (`_match_live_f7_v2`, 94.67% match at ws_s). | All pre-05-10 hit-rate / momo PnL anchored on slot_start: **hit rate inflated 25–40 pp** (~85% backtest vs ~50% live). | Phase-3/4 momo, any "85% hit rate" claim, pre-canonical meta_classifier scripts. | DISCARD any pre-05-10 hit-rate numbers anchored on slot_start. Canonical `slug_to_ws_s` helpers + `_test_ws_s.py` now enforce. **Also affects resolutions_hf Feb–Mar OOS** (issue #7) — that timing is *separately* broken. |
| 5 | **Binance-klines-resolved outcome contamination (+$14k)** | `market_resolutions_full.csv` mixed `price_source ∈ {chainlink, binance-klines-1m}`; 1,759 binance-resolved markets had `outcome` tautologically correlated with the binance-derived `ret_2m` signal. | 2026-05-09 (canonical filter = chainlink-only). | All baseline-PnL work that loaded the raw resolutions CSV before canonical (≈ pre-05-12). | Any "baseline PnL ~$X" from before chainlink-only filter; the inflated $14k baseline. | FIXED at source — canonical filters to chainlink-only. Pre-canonical baselines are **void**; do not cite. |
| 6 | **`trades_polymarket` staleness** | Delta puller lagged; canonical btc/eth/sol trades were stale **Apr 22 → May 6** as of 2026-05-15 inventory. | Flagged 2026-05-15 (DATA_INVENTORY) + 05-26 window audit. Now topped-off (btc 44.64M, max Jun 8). | Strategies that joined the poly trade tape May 6→May 15 window saw truncated/empty trades. | Any trade-tape-dependent feature panel built mid-May (microstructure_panel, range_filter_1s show 9–10d short-start). | Current `trades_polymarket` is fresh (Jun 8). HF trade tape (`trades_polymarket_hf`) is **BTC/ETH only, Feb 21→Mar 24** — do not assume SOL/new-coin trade tape exists for Feb–Mar. |
| 7 | **HF L25-backfill / `resolutions_hf` timing offset (+74–150s)** | HF backfill ingest (2026-06-05). `resolutions_hf` slot_start/slot_end are shifted **+74–150s** from the actual trades+book activity (which agree with each other). Both trades AND book start ~+137s late and run ~+95–226s past slot_end. NOT an "+80s book lag" — the *whole market activity* is shifted, per-market variable. | 2026-06-05 (`DATA_FIX_SPEC_RESOLUTIONS_HF_TIMING`, `NEW_DATA_INVENTORY`). UNFIXED. | Any scalp/OOS run on Feb–Mar backfill: firing at deployed +5s gives **0% fill** (book doesn't exist yet); SOL/XRP backfill 0% fill even re-anchored. | The "exploratory re-anchor" OOS (BTC gated +0.35 ns, ETH −2.58) — **CONFOUNDED, not a refutation** of the +5s scalp (wrong regime: edge lives early, decays late). | **BLOCKS the §D-2 different-window scalp OOS — the prize.** Do NOT treat the Feb–Mar exploratory negative as evidence. Need: true strike + settle time per slug (reconcile slug→slot mapping / condition_id metadata vs trades). |
| 8 | **aliplayer BBO frozen at Apr 21 (not auto-updating)** | HF dataset `lastModified 2026-04-26`; "auto-updates every 3h" claim was WRONG. | 2026-06-05b (`HF_BACKFILL_SESSION`). | Any plan assuming BBO would extend into the production window (Apr 22+). | The 5-coin scalp OOS framing that leaned on aliplayer BBO; cross-validation-vs-production plans. | **Zero overlap** with production (BBO ends Apr 21, production starts Apr 22). Cannot cross-validate BBO findings against live. BBO usable only as Mar 30→Apr 21 standalone window; BNB/DOGE/HYPE books thin. |
| 9 | **Maker-arb REDEEM right-censoring (survivorship bias)** | Shadow engine books REDEEM only for directional WINNER; LOSERS expire silently (no event, inventory never returns to 0) → "settled-only inv=0" excluded all losers. | 2026-05-28 (`MAKER_ARB_CENSORING_REVERSAL`). | Every maker-arb "edge" report before 05-28. ACC-H-V2 btc 15m read **+$4.44/slug**; uncensored truth **−$0.41/slug** (all sleeves net-negative). | `MAKER_ARB_CONTEXT_HANDOFF_2026_05_28` §2/§3, `CLEAN_SETTLED_AUDIT_2026_05_28`, "best sleeve to test live: ACC-H-V2" framing. | **DO NOT deploy any maker-arb.** Also: shadow `slug_pnl_so_far` / operator dashboard built on it **drifts permanently positive** (losers never booked). TV must book expiry-loss or settle open inventory vs chainlink. |
| 10 | **Sleeve PnL double-count: raw `events.pnl_usd` vs TV-dashboard dedup** | Raw `events.pnl_usd` double-counts/inflates. (memory: lagv2 +$1681 raw → −$195 dedup.) | Per memory `project_sleeve_pnl_metric`. | Any sleeve ranking / fleet audit using raw `events.pnl_usd`. | 215-sleeve fleet audit numbers, any "+$X/sleeve" from raw events. | **RANK on TV-dashboard dedup metric, never raw `events.pnl_usd`.** Re-rank prior fleet audits. |
| 11 | **Kalshi early-book "observability" (subscribe-late, not missing liquidity)** | Collector subscribed AFTER market open → "+30s no-book" looked like missing liquidity. | Per memory `project_kalshi_scalp_deprecated`: it's observability; pre-subscribe via `status=unopened` fixes it. | Any Kalshi early-offset analysis concluding "no early liquidity." | "Kalshi early-book empty / scalp deprecated" conclusions. | Early-offset 15m sleeves ARE Kalshi-tradeable once pre-subscribed. Re-collect with pre-subscribe before concluding on Kalshi depth. |
| 12 | **HL liqs stale (May 27) + binance_metrics dead (geoblocked)** | binance_metrics: VPS3 geoblocked from Binance futures ~2026-04-26 (collector dead). HL liqs/klines last full pull 2026-05-27. | binance_metrics deleted 2026-05-27 (`load_binance_metrics` raises). HL not refreshed since. | Any futures-OI/funding analysis via binance_metrics after Apr 26; any HL-liq analysis assuming freshness after May 27. | binance_metrics-dependent regime features. | binance_metrics **permanently dead** → use `cex_futures_ticker` (funding/OI, started ~May 30). HL liqs frozen at May 27 — re-pull if needed; `hyperliquid_liquidations_full.parquet` dated May 27. |

**Cross-cutting:** the most dangerous *active* contaminations today are **#7 (Feb–Mar OOS timing — blocks the only true different-window validation)** and **#3 (spread metric — placement counts not live-achievable).** #1/#4/#5/#9 are fixed-at-source but their *pre-fix reports are still cited* — treat any pre-fix absolute-PnL or hit-rate number as void.

---

## 2. engine_v2.py CODE-REVIEW VERDICT

File: `strategy_lab/engine_v2.py`. Reviewed `fill_commission_usd`, `fill_at_book`, `hold_pnl`,
configs.

### Fee model — winner-only vs both-legs
- **Winner side: CORRECT.** `hold_pnl(won=True, poly_taker_curve)` = `shares·(1−p) − fee_in` where
  `fee_in = shares·0.07·p·(1−p)`. Algebraically **identical** to the operator-confirmed live formula
  `qty·(1−p)·(1−0.07·p)`. Verified numerically (p=0.509, qty=50): both = **23.6753**, diff 0.00000. ✅
- **Loser side: OVERCHARGED.** `hold_pnl(won=False, poly_taker_curve)` (line 317-319) returns
  `−usd_in − fee_in`. Live charges **$0** on losers (`pnl = −qty·p` exactly). engine_v2 subtracts the
  entry fee on losers → **overcharge ≈ $0.87/losing-trade at p=0.509** (`shares·0.07·p·(1−p)`).
  This is the bug CLAUDE.md warns about. **Direction: conservatively pessimistic** — LiveMimic/Realistic
  backtests UNDERSTATE PnL. A strategy that passes under LiveMimic is real; one that fails marginally
  might actually be live-positive. The docstring (line 213) even says "ALWAYS charged" — so it's
  intentional-but-wrong vs the *actual* (post-06-03) live fee schedule.
  **FIX:** for production-faithful PnL, gate `fee_in` to winners only in `hold_pnl`'s loss branch
  (return `−usd_in − tx`), OR add an explicit winner-only `pnl_07` helper (CLAUDE.md already
  recommends the latter). The conservative stress-test intent of `RealisticConfig` can stay; but
  `LiveMimicConfig` should match live (winner-only) to be a true mimic — currently it does NOT.

### Latency 85ms
- `LiveMimicConfig.latency_ms = 85.0`, applied to entry AND exit (`apply_latency_to_entry/exit=True`).
  `fill_at_book` shifts lookup to `fire_us + 85_000µs` (line 248-251). Reasonable for Ireland→London
  CLOB RTT (<2 ms RTT per CLAUDE.md; 85 ms is decision→fill incl. processing). Direction is correct
  (later book = realistic). No bug. Static latency only — no jitter/distribution model (acceptable).

### min_book_events
- **Was a latent bug, FIXED 2026-05-30** (line 253-262): declared in config + set to 25 but never
  enforced; markets with <25 snapshots passed silently. Now counts events in a **120s look-back window
  ending at lookup_us**. ⚠️ Minor: the BUG-FIX comment says window is "ending at lookup_us (covers the
  slot duration)" but a 120s look-back from fire only covers pre-fire; for a 15m slot it does NOT cover
  the slot. For the scalp (fires near window start) it's fine; for hold-to-resolution it under-counts.
  Any backtest run **before 2026-05-30** had `min_book_events` effectively DISABLED even under
  LiveMimicConfig → those backtests included thin/illiquid markets that live would skip (optimistic).
  **Re-base pre-05-30 LiveMimic backtests.**

### fill_at_book spread filter semantics
- Uses **same-token `ask0 − bid0` > spread_filter** (line 273-275) — this is the backtest definition,
  which **diverges from live cross-token** (issue #3). Not a code bug, but a *fidelity gap*: the engine's
  placement decisions do not match live. Documented; decision pending on whether TV adopts same-token.
- Under-fill guard (line 282): drops if `shares<=0 or (under and usd < notional·0.5)` — sane.

### Remaining bugs / risks
1. **Loser fee overcharge** (above) — primary correctness gap vs live.
2. **Spread metric** = backtest semantics, not live (fidelity gap, placement-count inflation).
3. **min_book_events window** doesn't cover full slot for long timeframes (under-counts 15m).
4. **No exit-side fee asymmetry / maker rebate** in these primitives — maker strategies must not use
   `hold_pnl`/`sell_pnl` as-is (they model taker only).

**VERDICT:** engine_v2 is the right single primitive and its **winner-side fee is exactly live-correct**.
Its **loser-side fee is too harsh** (conservative — understates PnL, not overstates), so PnL that
*passes* under LiveMimic/Realistic is trustworthy; marginal *failures* deserve a winner-only re-check.
The pre-05-30 unenforced `min_book_events` and the same-token spread are the two fidelity caveats.

---

## 3. DATA COVERAGE MAP + GAPS (as of 2026-06-08 refresh)

| Layer | Coins | Frequency | Window | Notes / GAP |
|---|---|---|---|---|
| `resolutions.parquet` (chainlink) | BTC/ETH/SOL | per-market | **Apr 22 → Jun 8** | Production reference, clean. The trustworthy outcome source. |
| `resolutions_hf.parquet` | 6 coins (BTC/ETH/SOL/XRP/DOGE/BNB; +HYPE) | per-market | Jan 2 → Apr 21 | NOT chainlink (aliplayer/bmoney/trentmkelly settle). **Slot timing offset +74–150s (issue #7) — BLOCKS clean OOS.** |
| `orderbook_l25/{btc,eth,sol}` | BTC/ETH/SOL only | 10 Hz native | **Apr 22 → Jun 8** | Production L25. **GAP: no XRP/BNB/DOGE/HYPE L25 in production window.** Load `subsample_1hz=False`. |
| `orderbook_l25_backfill/{btc,eth}` | BTC/ETH | 10 Hz | Feb 21 → Mar 24 (98M each) | **+ timing offset (#7).** SOL/XRP only Mar 1–13 (~850k), 0% fill even re-anchored. |
| `canonical_bbo` (D:) | 7 coins | ~200 Hz event | **Mar 30 → Apr 21** (FROZEN) | aliplayer, **frozen, zero overlap with production** (#8). BNB/DOGE/HYPE books thin. BTC 2.6B rows — always filter. |
| `trades_polymarket/{btc,eth,sol}` | BTC/ETH/SOL | tick | Apr 22 → Jun 8 (fresh) | **GAP: no new-coin trade tape.** Was stale Apr22–May6 historically (#6, now fixed). |
| `trades_polymarket_hf/{btc,eth}` | BTC/ETH only | tick | Feb 21 → Mar 24 | **GAP: no SOL/new-coin Feb–Mar trade tape.** |
| `klines_1m` | 6 binance coins + cex venues | 1 min | long | Fine. |
| `klines_1s` | BTC/ETH/SOL: Jan 1→now; **XRP/BNB/DOGE: Jan 1→Apr 21 only** | 1 sec | see cells | **GAP: no 1s for XRP/BNB/DOGE in production window (Apr 22+)** → these 3 coins NOT scalp-testable live. No HYPE 1s at all (not on Binance). |
| `chainlink_rtds` | BTC/ETH/SOL | 1 Hz | Apr 22 → Jun 8 | Oracle. **GAP: no Feb–Mar RTDS** → blocks oracle-determinism OOS on backfill. |
| `kalshi_markets` + `kalshi_orderbook` | KX*15M series | snapshots | **~Jun 5 only (small: 72KB / 11.7MB)** | **GAP: only a few days. Depth GATED/unverified** (POLY×KALSHI arb gated on ask-DEPTH). Early-book was subscribe-late observability (#11), re-collect with pre-subscribe. |
| `cex_futures_ticker` (funding/OI/mark) | 4 ex × 6 perp | high-freq | **~May 30 → Jun 8** | Replacement for dead binance_metrics. **GAP: nothing before ~May 30.** |
| `cex_futures_klines/trades/liquidations` | 4 ex × 6 perp | high-freq | ~May 25–30 → Jun 8 | Liqs gate+okx only (bybit/bitget empty). Manual \copy re-run needed (pipeline fragility). |
| `hyperliquid_klines` | BTC/ETH/SOL/HYPE | **hourly** | Jan 30 → May 27 | **GAP: hourly too coarse for scalp; STALE since May 27.** |
| `hyperliquid_liquidations_full` | per-asset | tick | → **May 27 (STALE)** | #12 — frozen May 27. |
| `binance_metrics` | — | — | **DEAD** | Geoblocked; loader raises FileNotFoundError. Use cex_futures_ticker. |
| **CLOB WS event/trade tape (Polymarket)** | — | — | **ABSENT** | **Biggest structural gap.** No live CLOB WS order-event tape collected → cannot decode slug-selector signals (F2), cannot build queue-position truth for maker fills, cannot validate placement timing forward. |

**Biggest research-limiting gaps (today):** (a) Feb–Mar OOS timing offset (#7) — no *clean* disjoint-window
validation possible; (b) no production-window L25/trade tape for XRP/BNB/DOGE/HYPE (multi-coin scalp can't go
truly live-faithful for 4 coins); (c) Kalshi = ~few days + unverified depth; (d) no Poly CLOB WS event tape
going forward.

---

## 4. RANKED DATA ACQUISITIONS (most research unlocked per $/effort)

| Rank | Acquisition | Cost / effort | Unlocks | Why this rank |
|---|---|---|---|---|
| **1** | **Fix `resolutions_hf` slot-timing offset (#7)** — reconcile slug→slot/condition_id metadata vs trades/book; recompute true strike + settle per slug | $0, ~½ day of analysis (data already on disk) | The **§D-2 different-window scalp OOS** (BTC/ETH Feb–Mar, 98M L25 + 34M trades) — the deflation-proof validation we've been blocked on; favorite-longshot / cross-token / TOD cross-window OOS | Free, unblocks the single highest-value validation. No new data needed. **Do this first.** |
| **2** | **Poly CLOB WS event/trade tape — start collecting FORWARD** | Engineering (collector on VPS), ongoing | Queue-position truth (kills the optimistic maker assumption in BACKTEST_VS_SHADOW_GAP §2.1), slug-selector decode (F2 $5.9k/day), forward placement-timing validation, maker-exit edge (NEXT #1) | Structural gap; everything maker/queue-dependent is currently un-validatable. Compounds over time. |
| **3** | **Longer Kalshi collection + pre-subscribe (status=unopened) for depth** | Low eng (fix subscribe timing), ongoing | Verifies Poly×Kalshi deep-dip arb ask-DEPTH (currently GATED → +2.7¢/set CI[+1.1,+4.2]); makes early-offset 15m Kalshi-tradeable (#11) | A real, already-CI-positive arb is gated solely on depth we can fix for ~free. High EV. |
| **4** | **Binance 1s klines Feb 21 → Apr 7 (BTC/ETH/SOL) + XRP/BNB/DOGE production-window 1s** | $0 (Binance Vision free) + script time | (a) completes the scalp OOS lag anchor for Feb–Mar (pairs with #1); (b) makes XRP/BNB/DOGE scalp-testable in production window | Free, mechanical. Vision history goes to 2017. Pairs with #1 to fully unlock OOS. |
| **5** | **HL S3 requester-pays L2 book → 1s mid (HYPE Apr 6–21)** | ~$1 egress + AWS creds | HYPE 1s mid → HYPE scalp OOS (only missing coin) | Cheap but narrow (one coin, short window). HYPE has no Binance 1s alternative. |
| **6** | **chainlink RTDS Feb–Mar (BTC/ETH/SOL)** | re-pull from VPS3 if retained, else gap | Oracle-determinism OOS on the backfill window | Only matters if oracle-determinism is revived (currently underpowered/dead per handoff). |
| **7** | **Tardis.dev deep CEX liquidations** | Paid | Deeper liq-cascade features | Futures liq already partially covered by cex_futures (gate+okx). Marginal. |
| **8** | **PolyHistorical $17/mo** | $17/mo | Cheaper crypto-up/down history than Telonex $79 | Only if a gap needs filling that free HF sources can't; most book history pre-Aug-2025 doesn't exist anywhere. Low marginal value given current coverage. |

**Top-3 by EV:** #1 (free, unblocks the prize), #2 (structural, compounds), #3 (free-ish, unlocks a
CI-positive arb).

---

## 5. PIPELINE / SINGLE-SOURCE-INVARIANT RISKS

The single-source invariant (merge delta → DELETE refresh dir + VPS3 /tmp) is disciplined and keeps
the repo lean, but it makes the merge step a **single point of failure with no local backup**:

1. **Disk-full mid-L25-merge (recurring).** 06-08: disk hit **100% mid-merge**; BTC L25 `.tmp` needs
   ~8 GB and only **7.6 GB free (97% used)**. The merge writes a temp file = size of the consolidated
   parquet before atomic replace. **If the atomic replace is interrupted with the source already deleted,
   the canonical L25 could be lost.** RISK: HIGH. MITIGATION: enforce a pre-merge free-space check
   (≥ file_size × 1.2); keep the refresh dir until the atomic replace + row-count verify succeeds
   (don't delete-then-merge).
2. **OOM on the 69M-row 1s-kline sort.** `merge_nonl25` OOMs sorting the 1s klines → operators run
   trades/events targeted separately. RISK: MEDIUM (workaround exists but is manual = error-prone; a
   skipped target = silent staleness). MITIGATION: chunked/streaming merge for the 1s table; assert
   max-ts per table post-merge.
3. **Futures liquidations needed a manual `\copy` re-run.** The collector/merge for futures liqs is
   flaky (bybit/bitget empty; gate+okx only). RISK: MEDIUM. Partial coverage silently. MITIGATION:
   post-merge per-exchange row-count assertion; document that liqs ≠ all 4 exchanges.
4. **No local backup before delete.** The invariant trades safety for disk. With disk at 97%, a single
   bad merge has no rollback. RISK: HIGH given #1. MITIGATION: snapshot canonical L25 checksums +
   row-counts to a tiny manifest before each merge; only delete source after manifest verify.
5. **Manual max-ts / row-count verification is the only integrity gate.** `verify_all.py` exists but
   the playbook relies on the operator reading max-ts lines. RISK: MEDIUM. MITIGATION: make
   verify hard-fail the pipeline (non-zero exit) on any table whose max-ts didn't advance or row-count
   regressed.

**Integrity verdict:** data *content* is well-disciplined (chainlink-only, dedup precedence, writer-kept
== metadata row checks). The *process* risk is the delete-before-confirm pattern under chronic disk
pressure — one interrupted atomic L25 replace = unrecoverable. **Clear disk + add a pre-merge space
guard + keep-source-until-verified before the next refresh.**

---

## APPENDIX — quick trust verdict per result class

- **Outcome-only / feature panels** (chainlink resolutions): TRUSTWORTHY.
- **Pre-05-10 hit rates anchored on slot_start:** VOID (lookahead).
- **Pre-canonical (pre-05-09) baselines:** VOID (binance-resolved contamination).
- **Pre-05-30 LiveMimic backtests:** RE-CHECK (min_book_events was off).
- **L25 backtests not passing `subsample_1hz=False`:** RE-RUN for fill/spread realism.
- **2%-fee-priced winning PnL:** OVERSTATED ~$0.36–0.43/win — re-base absolutes (rankings mostly survive).
- **LiveMimic/Realistic PnL:** loser-fee too harsh → PnL is a *lower bound*; passes are real.
- **Backtest placement counts / fires-per-day:** UPPER BOUND (same-token spread vs live cross-token).
- **Maker-arb edges pre-05-28:** VOID (REDEEM censoring).
- **Raw `events.pnl_usd` sleeve rankings:** RE-RANK on TV dashboard dedup.
- **Feb–Mar HF backfill OOS:** BLOCKED (timing offset) — negatives are confounded, not refutations.
