# Session Handoff — 2026-05-09 — Slug-WS Anchor Breakthrough

**Last touched:** 2026-05-09 ~22:30 UTC
**Owner:** alexandre.bandarra
**Status:** Major investigation in progress. Backtest fundamentally broken. Production behavior may be correct.

## UPDATE 2026-05-09 ~23:00 UTC — Phase 1+2 COMPLETE

**Phase 1 confirmed via audit `at` vs slug_ws lag analysis (n=300):**

| sleeve | tf | median lag (ws-at) | matches |
|---|---|---:|---|
| v1 | 5m | 175s | strike+120 of 5m market (= ws-180) ✓ |
| v2 | 5m | 234s | strike+60 (= ws-240) ✓ |
| v1 | 15m | 776s | strike+120 of 15m (= ws-780) ✓ |
| v2 | 15m | 836s | strike+60 of 15m (= ws-840) ✓ |

Stdev 2-3s across all cells. **slug-ws-as-END-time is definitive**, but...

**Phase 2 brute force (300 audit rows × 22×22 anchor offsets × 2 sources × 2 asof types) found PRODUCTION'S EXACT signal anchors (100% match within 1e-7):**

| sleeve | tf | absolute offsets | semantic |
|---|---|---|---|
| **v1** | **5m** | `(ws-300, ws-180)` strict | first 2 min of market |
| **v1** | **15m** | `(ws-900, ws-780)` strict | first 2 min of 15m market |
| **v2** | **5m** | `(ws-360, ws-240)` strict | 2 min centered on strike |
| **v2** | **15m** | `(ws-960, ws-840)` strict | 2 min centered on strike of 15m |

These are computed via `log(close@(ws+off1) / close@(ws+off0))` using strict end-time-indexed asof on **VPS3 binance-spot-ws klines** (in `data/v4/refresh_2026_05_09/vps3_binance_klines.csv`, 52K rows).

**Production's ret_2m IS computed correctly per spec.** The "lookahead bug" theory was wrong — my backtest had the bug, not production.

**Phase 2b oddity (unresolved):** outcome anchor `(strike, end)` = `(ws-window, ws)` only gives 48% agreement on the 13K resolved markets. The empirical winner from earlier sanity tests is `(ws-60, ws+window-60)` at 79.8% (VPS3 klines) or 95.8% (VPS2 OKX klines). The semantics here remain unclear — chainlink price feeds differ from Binance spot — but for PNL backtesting we use the production `outcome` field directly so this doesn't matter.



**Production fires at `ws-240` for 5m markets** (= "t+60 of market lifetime" anchored at strike=ws-300), confirmed by audit `at` timestamps being 232 seconds BEFORE slug-ws.

**The 17-day backtest's +$13.54/trade and 85% hit rate are bogus** — they were computed using `ret_2m = log(close@(ws+60) / close@(ws-60))` which captured the 2-minute price move RIGHT AT RESOLUTION (massive lookahead leak).

Production HOLD's actual performance: **+$0.35/trade, 52% hit rate** — which is what a real momo q90 gate gives WITHOUT leakage.

**Read this report first:** `strategy_lab/reports/MOMO_BREAKTHROUGH_SLUG_WS_END_TIME_2026_05_09.md`

## What to do next (4-phase plan)

### Phase 1 — Confirm slug-ws semantics (1 hour)
1. Pull 50+ momo audit rows with their `at` timestamps for 5m and 15m markets
2. Compute `(ws_unix - at_unix)` per row
3. **Expected pattern:**
   - 5m markets: `ws - at ≈ 240s` (production fires at ws-240)
   - 15m markets: `ws - at ≈ 840s` (production fires at ws-840)
4. If 5-min stdev < 5s on each tf, slug-ws-as-END-time is confirmed.

**Sample audit data to start from:** `data/v4/shadow_trades_2026_05_09/momo_orders_for_anchor.csv` (300 rows)

### Phase 2 — Find the actual production anchor (2 hours)
1. Pull VPS3 `binance-spot-ws` 1MIN klines for last 14 days × BTC/ETH/SOL:
   ```bash
   ssh -i ~/.ssh/vps3_ed25519 root@185.190.143.7 "..."
   # COPY (SELECT symbol_id, time_period_start_us, price_close FROM binance_klines_v2
   #       WHERE source='binance-spot-ws' AND period_id='1MIN'
   #       AND symbol_id IN ('BINANCE_SPOT_BTC_USDT','BINANCE_SPOT_ETH_USDT','BINANCE_SPOT_SOL_USDT')
   #       AND time_period_start_us > extract(epoch from now() - interval '14 days')*1000000)
   #      TO STDOUT CSV HEADER
   ```
2. For each of 300 audit rows in `momo_orders_for_anchor.csv`, compute `log(close@(ws+a) / close@(ws+b))` for ALL `(a, b)` pairs in `{-300, -240, -180, -120, -60, 0, 60, 120, 180, 240, 300}` (11×11 = 121 candidates × 2 sources = 242 configs).
3. Find the (a, b) pair with lowest mean absolute residual to `ret_2m_at_signal` across 300 rows.
4. **Validation criterion:** if best (a, b) gives < 1e-6 absolute diff on >90% of rows, that's the anchor. Otherwise dig further (try 1SEC bars, different sources).

**Existing brute-force script (incomplete — uses VPS2 klines, needs VPS3):** `strategy_lab/meta_classifier/_brute_force_anchor.py`

**Already verified for ws=1778343300:** anchor `(a=-180, b=+120)` (5-minute window) = +0.001719 matches production's +0.001720.

### Phase 3 — Rebuild backtest universe with confirmed anchors (1 hour) [READY TO EXECUTE]
1. Update `strategy_lab/meta_classifier/momo_full_universe_validation.py`:
   - **Use VPS3 klines** (`data/v4/refresh_2026_05_09/vps3_binance_klines.csv`) NOT VPS2 (Binance stale since Apr 29)
   - **Signal anchor for v1 5m:** `log(close@(ws-180)/close@(ws-300))` strict end-strict asof
   - **Signal anchor for v1 15m:** `log(close@(ws-780)/close@(ws-900))`
   - **Signal anchor for v2 5m:** `log(close@(ws-240)/close@(ws-360))`
   - **Signal anchor for v2 15m:** `log(close@(ws-840)/close@(ws-960))`
   - **L25 entry book lookup:** at production fire time = `ws-180` (v1 5m), `ws-240` (v2 5m), `ws-780` (v1 15m), `ws-840` (v2 15m)
   - **Outcome:** use production `outcome` field (chainlink-recorded truth)
2. Apply q90 gate per (asset, tf, day) on |ret_2m|
3. Walk top-25 ASKs at fire time for $25
4. HOLD pnl = (won ? shares×$1 : 0) − usd_paid − fee
5. Re-run on 17-day window. Target: backtest within 30% of production HOLD (+$0.35/trade)

### Phase 4 — Re-evaluate exit-policy variants (1 hour)
1. Run `strategy_lab/meta_classifier/momo_exit_policy_explore.py` (15 variants) with the corrected anchor
2. Variant ranking will likely change — may flip "HOLD wins" verdict
3. If HEDGE_3bp / STOP_HEDGE_0.5x outperforms HOLD on the corrected backtest, write deploy spec for momo_v3 sleeves
4. If HOLD still wins, slim production to HOLD-only

---

## Critical files (read order)

### Reports — recent breakthrough
1. **`strategy_lab/reports/MOMO_BREAKTHROUGH_SLUG_WS_END_TIME_2026_05_09.md`** ← START HERE
2. `strategy_lab/reports/MOMO_ANCHOR_DIAGNOSIS_2026_05_09.md` — what diagnosis steps led to breakthrough
3. `strategy_lab/reports/MOMO_HOLD_PROD_VS_BACKTEST_2026_05_09.md` — production HOLD shows 97% haircut
4. `strategy_lab/reports/MOMO_FULL_UNIVERSE_VALIDATION_2026_05_09.md` — **NOW INVALIDATED** by breakthrough

### Reports — earlier work this session (still useful for context)
- `MOMO_POST_PATCH_VS_BACKTEST_2026_05_09.md` — WS patch raised HEDGE/SELL fire rates
- `MOMO_LIVE_VS_BACKTEST_2026_05_08.md` — first-time diagnostic, 236 missed exits
- `MOMO_EXIT_POLICY_EXPLORE_2026_05_09.md` — 15 exit variants on 7d window (HOLD lost there)
- `MOMO_PARTIAL_FILL_BACKTEST_2026_05_09.md` — partial-fill doesn't help much
- `MOMO_HEDGE_SELL_INVESTIGATION_2026_05_06.md` — original HEDGE/SELL bug

### Specs (DO NOT SHIP — based on broken backtest)
- `TV_AGENT_MOMO_V2_SLEEVES_IMPLEMENTATION.md` — already shipped, 18 sleeves running
- `TV_AGENT_MOMO_V3_PARTIAL_SLEEVES_IMPLEMENTATION.md` — drafted but DON'T SHIP
- `TV_AGENT_FIX_HEDGE_SELL_EXIT_WS_2026_05_09.md` — TV agent already deployed this; book_mirror.py is live

### Backtest engines
1. **`strategy_lab/meta_classifier/momo_full_universe_validation.py`** — full universe + walkforward + perm. Needs anchor fix.
2. `strategy_lab/meta_classifier/momo_exit_policy_explore.py` — 15-variant sweep
3. `strategy_lab/meta_classifier/momo_partial_fill_backtest.py` — partial-fill HEDGE/SELL
4. `strategy_lab/meta_classifier/momo_live_vs_backtest_diagnose.py` — per-trade exit prediction vs production
5. `strategy_lab/meta_classifier/momo_ws_walkforward_perm.py` — walkforward + DIRECTION_PERM
6. `strategy_lab/meta_classifier/momo_ws_three_policies_sweep.py` — full 3-policy sweep

### Diagnostic scripts (use as templates)
- `strategy_lab/meta_classifier/_diagnose_anchor.py` — fixed-set anchor diagnostic
- `strategy_lab/meta_classifier/_brute_force_anchor.py` — 1156-config search (uses VPS2 OKX, needs VPS3 Binance)
- `strategy_lab/meta_classifier/_compare_post_patch_vs_backtest.py` — post-patch shadow vs backtest
- `strategy_lab/meta_classifier/_compare_hold_prod_vs_backtest.py` — HOLD-only comparison
- `strategy_lab/meta_classifier/_pull_delta_may6_may9.py` — pull markets/resolutions/klines/L25 from VPS

---

## Data on disk

### Production audit data (latest from VPS3)
- `data/v4/shadow_trades_2026_05_09/momo_v1v2_live.csv` — 851 momo+momo_v2 resolutions, 7d window
- `data/v4/shadow_trades_2026_05_09/momo_post_patch_12h.csv` — 223 resolutions in last 12h post-WS-patch
- `data/v4/shadow_trades_2026_05_09/momo_hold_full.csv` — **355 HOLD-only resolutions, 67h window** (HOLD doesn't depend on WS patch, full data)
- `data/v4/shadow_trades_2026_05_09/momo_orders_for_anchor.csv` — 300 audit rows w/ `ret_2m_at_signal` for anchor diagnosis

### Reference data (from VPS2 — Binance feed STALE since Apr 29)
- `data/v4/refresh_2026_05_06/markets_full.csv` — 9934 markets through May 6
- `data/v4/refresh_2026_05_06/market_resolutions_full.csv` — 16030 resolutions
- `data/v4/refresh_2026_05_06/klines_full.csv` — 73K 1m bars (Binance through Apr 29, OKX through May 9)
- `data/v4/refresh_2026_05_06/cache/{btc,eth,sol}_orderbook_L25.parquet` — L25 books through ~May 6 (BTC 2.7G, ETH 592M, SOL 249M)
- `data/v4/refresh_2026_05_09/markets_full.csv` — fresher markets, May 9
- `data/v4/refresh_2026_05_09/market_resolutions_full.csv` — fresher resolutions
- `data/v4/refresh_2026_05_09/klines_full.csv` — **STALE Binance through Apr 29**, OKX current. Need to pull VPS3 binance-spot-ws fresh.

### Backtest results (stale, computed with broken anchor)
- `data/v4/refresh_2026_05_09/full_universe/per_trade.csv` — 14K rows, will need recompute
- `data/v4/refresh_2026_05_09/full_universe/summary.csv`
- `data/v4/refresh_2026_05_09/full_universe/walkforward.csv`
- `data/v4/refresh_2026_05_09/full_universe/permutation.csv`

---

## Production state on VPS3

### Active sleeves (36 total)
- 18 momo v1 (HOLD/HEDGE/SELL × BTC/ETH/SOL × 5m/15m), deployed May 6 00:28 UTC
- 18 momo_v2 (same matrix, fire offset = ws+60 instead of ws+120), deployed May 7 ~14:00 UTC

### Patches deployed by TV agent
- ✅ ContextVar bug fix (May 6) — bar_ctx isolation across concurrent tasks
- ✅ asof end-time-indexed fix (claimed)
- ✅ WS book_mirror for HEDGE/SELL exit-side fetch (deployed ~May 9 19:00 UTC)
  - `book_mirror.py` exists in `/opt/tradingvenue/backend/app/venues/polymarket/`
  - Env flag `TV_POLY_BOOK_MIRROR=true` set
  - Post-patch fire rates: HEDGE 18%→55-71%, SELL 1.7%→10.3%
  - **HEDGE may be over-firing** vs backtest's 14% prediction — TBD if this is correct after anchor fix

### Production performance summary (last 67h)
- 355 HOLD trades, **+$0.35/trade**, 52% hit rate
- v1 HOLD: -$0.19/trade, v2 HOLD: +$0.95/trade (v2 outperforms by $1.14)
- Per-cell winners: BTC_15m_v1 (+$12.22), ETH_15m_v1 (+$10.04) approach reasonable, SOL/5m cells mostly negative
- Daily: May 7 -$0.64, May 8 +$2.70, May 9 -$4.45

---

## Open mysteries (need investigation)

### 1. Sign disagreement on some audit rows
For ws=1778339700, production logged `ret_2m_at_signal = -0.001620` but BTC/ETH/SOL all moved UP that minute. Either:
- Production has a sign-flip bug
- Production uses a non-spot reference (perp price? Polymarket book mid?)
- Audit timestamp `at` decouples from actual fire time (queue/retry)

**To verify:** find 10+ rows with sign disagreement, look for a pattern.

### 2. v2's 60s offset vs v1's 120s offset behavior
Production v2 uses ws+60 fire (per spec), v1 uses ws+120. But under new slug-ws=END interpretation:
- v1 fires at ws-180 (= strike+120 of 5m market = t+120 of market lifetime)
- v2 fires at ws-240 (= strike+60 = t+60 of market lifetime)

Need to verify what ws-? production v1 actually fires at by checking 50+ v1 audit rows.

### 3. Outcome anchor for 95.8% sanity test
Earlier sanity test showed `(ws-60, ws+window-60)` = 95.8% outcome agreement. With slug-ws=END interpretation, that anchor doesn't make sense. Need to redo sanity with the corrected interpretation:
- Strike at ws-300 (5m) or ws-900 (15m)
- Resolution at ws

The outcome should match `close@(ws-300) vs close@ws` for 5m. Run the sanity test again.

### 4. Why some rows match anchor (ws-180, ws+120) but others don't
Need 300-row brute force on VPS3-Binance to see if it's:
- (a) Same anchor for all rows but my data was wrong on some
- (b) Different anchors per (asset, tf) — e.g., 5m uses one, 15m uses another
- (c) Production has heterogeneous code paths

---

## Production patches still needed

### From earlier prior reports (still valid)
1. **Verify lookahead bug fix** in production `fetch_close_asof` (TV_AGENT_AUDIT_ASOF_LOOKAHEAD.md)
2. **HEDGE rev_bp may need lowering from 5bp → 3bp** — TBD after corrected backtest
3. **Dynamic sizing cap on SOL_5m** (NEXT_SESSION §5)

### New patches identified this session
4. **Verify production's actual `ret_2m_at_signal` formula** matches the documented spec — currently doesn't match for some rows
5. **Audit code may have a sign bug** in some path (some negative ret_2m where assets actually went up)

---

## Anti-patterns / pitfalls

1. **Don't trust the 17-day backtest +$13.54/trade.** It has lookahead leak.
2. **Don't ship momo_v3 partial-fill spec.** Built on broken backtest.
3. **Don't slim sleeves to HOLD-only.** "HOLD wins" was a backtest artifact.
4. **Don't use VPS2's Binance kline data for anything after Apr 29.** It's geo-blocked. Use OKX (still live on VPS2) OR pull from VPS3 directly.
5. **Don't compute ret_2m with anchor (ws-60, ws+60) on the slug-ws-as-bar-close interpretation.** It's a leaky lookahead under the actual semantics.
6. **`df.at` clashes with pandas `.at` indexer.** Use `df["at"]` instead.
7. **psql `\copy` must be on a single line** — multi-line breaks the meta-command.
8. **psql heredoc with `<<-SQL` requires `'"'"'` for single-quoting SQL strings** through SSH bash.
9. **VPS2 BTC L25 delta CSV (3 days) is 1.1+ GB** — scp over IPv6 timed out at 600s. Compress server-side OR pull per-asset.
10. **Pandas float32 sort can OOM** — load L25 in chunks per (mid, outcome) instead of bulk DataFrame.

---

## Session decisions made

| decision | reasoning | status |
|---|---|---|
| Use HOLD-only data for production validation | HOLD doesn't need WS patch, full 67h comparable | ✅ done |
| Run brute force on 1156 anchor configs | rule out simple anchor bugs | ✅ done — 0 matches found |
| Pull production audit rows for ret_2m_at_signal | reverse-engineer production's actual computation | ✅ done — 300 rows |
| Verify VPS3 vs VPS2 klines | rule out data source mismatch | ✅ done — VPS2 stale Binance, OKX current |
| **Realize slug-ws is END time** | audit `at` is 232s BEFORE slug-ws, impossible if ws is bar-close | ✅ **breakthrough** |
| **DON'T ship momo_v3 spec** | depends on broken backtest | ⏸ paused |
| **DON'T slim to HOLD-only** | "HOLD wins" was leak artifact | ⏸ paused |

---

## Quick commands for next session

### Pull VPS3 Binance klines (for Phase 2)
```bash
ssh -i ~/.ssh/vps3_ed25519 root@185.190.143.7 'set -a; source /etc/tv/tv-ro.env; set +a; export PGPASSWORD="$TV_RO_PWD_PLAIN"; psql -h 127.0.0.1 -U tradingvenue_ro -d storedata <<-SQL
\copy (SELECT symbol_id, time_period_start_us, price_close FROM binance_klines_v2 WHERE source='"'"'binance-spot-ws'"'"' AND period_id='"'"'1MIN'"'"' AND symbol_id IN ('"'"'BINANCE_SPOT_BTC_USDT'"'"','"'"'BINANCE_SPOT_ETH_USDT'"'"','"'"'BINANCE_SPOT_SOL_USDT'"'"') AND time_period_start_us > extract(epoch from now() - interval '"'"'14 days'"'"')*1000000) TO /tmp/vps3_binance_klines.csv CSV HEADER
SQL'
scp -i ~/.ssh/vps3_ed25519 root@185.190.143.7:/tmp/vps3_binance_klines.csv "/c/Users/alexandre bandarra/Desktop/global/data/v4/refresh_2026_05_09/vps3_binance_klines.csv"
```

### Sanity-check slug-ws=END (Phase 1 quick start)
```python
# Read momo_v1v2_live.csv, compute (ws_unix - at_unix) for each row, group by tf, summary stats.
import pandas as pd, re
df = pd.read_csv("data/v4/shadow_trades_2026_05_09/momo_v1v2_live.csv")
df["at_us"] = pd.to_datetime(df["at"], utc=True).astype("int64") // 1000
m = pd.read_csv("data/v4/refresh_2026_05_09/markets_full.csv", dtype={"condition_id": str})[["condition_id","slug"]]
df = df.merge(m, on="condition_id", how="left").dropna(subset=["slug"])
df["ws"] = df.slug.str.extract(r"-(\d+)$")[0].astype("int64")
df["lag_s"] = df["ws"] - (df.at_us // 1_000_000)
print(df.groupby("tf").lag_s.describe())
# Expected: 5m → ~240s, 15m → ~840s
```

---

## Strategy invariants (still true regardless of anchor)

1. **Polymarket UpDown markets settle binary on Chainlink** at the resolution moment
2. **Top-decile q90 |ret_2m| selection IS predictive** of binary outcome — but the magnitude depends on anchor
3. **HOLD policy = simplest, no exit-policy intervention** — pnl is purely entry vs settlement
4. **HEDGE_HOLD = buy opposite-side ASKs to lock in payoff** — limits both upside and downside
5. **SELL_BID = exit own held side at bid** — locks in current value, partial recovery
6. **The strategy is a directional bet** — q90 gate selects markets where signal is strong; signal direction matches gate sign

---

*End of handoff. Read `MOMO_BREAKTHROUGH_SLUG_WS_END_TIME_2026_05_09.md` next.*
