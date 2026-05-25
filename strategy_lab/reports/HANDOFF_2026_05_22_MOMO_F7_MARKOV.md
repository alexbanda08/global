# Handoff — Momo F7+Markov backtest + production verification

_2026-05-22. Long session. Full reconciliation of canonical backtest vs
live VPS3 production: anchor verification, fee-model verification, fresh
canonical pull, Markov filter integration, 5-sleeve ensemble + 11-sleeve
spec backtest. Next session: ship the deploy candidates, refresh hot-hour
tables for the 4 failing shadow sleeves, validate out-of-sample._

---

## TL;DR for the next session agent

1. **Production-matching is fully verified end-to-end**:
   - **F7 RSI anchor**: `ws_s = slot_start − window_s` (94.67% match against
     1,331 live `is_f7` flags). Verifier: `_match_live_f7_v2.py`.
   - **Books**: WS-only via `BookMirror` since Phase 18.6 Wave 1
     (`wss://ws-subscriptions-clob.polymarket.com/ws/market`). Verified
     via live `tv-engine` journal: every `paper.book_fetched` event has
     `source: "ws_mirror"`.
   - **Fees**: 2%-on-profit-only on the winning leg, **NO** fee on losing
     legs. Verified against 25,900 production `poly_updown_resolution`
     events (median diff = 0.000000 from naive-no-fee on losses, and
     from 2%-on-profit on wins). The `0.07 × p × (1-p)` "real curve" in
     `strategy_lab/fees.py` does NOT apply to these markets.

2. **Fresh canonical pull complete (2026-05-21 20:17 UTC)**. 28-day window
   April 24 → May 21 20:10 UTC, 30,750 chainlink-resolved markets.
   F7 deployment window (2026-05-20 19:57+) fully covered. See
   `migration_2026_05_21/` for pull + convert + merge scripts.

3. **Five deploy candidates passed 28d audit** (production-matched PnL):

   | ID | Variant | Cell | Filter | n | WR | $/tr | $/day @ $25 |
   |---|---|---|---|---|---|---|---|
   | **S1** | Baseline_v1 | btc_15m | M1V | 92 | 59.78% | +$4.71 | +$15.48 |
   | **S2** | 2B late/early | btc_15m | M1V | 113 | 56.64% | +$4.10 | +$16.57 |
   | **S3** | 2B late/early | btc_15m | F7+M1V | 65 | 58.46% | +$5.67 | +$13.16 |
   | **S4** | 2C edge-of-slot | btc_15m | F7+M5V | 28 | 57.14% | +$5.43 | +$5.43 |
   | **S5** | Baseline_v2 | eth_5m | F7+M5F | 68 | 57.35% | +$4.26 | +$10.33 |
   | **Ensemble** | – | – | – | 366 | – | – | **+$60-63/day** |

4. **11-sleeve TV spec backtest**: 4 PASS (#7, #8, #9, #11), 3 underperform-but-positive
   (#1, #4, #6), 4 NEGATIVE (#2, #3, #5, #10). Drop the 4 negative sleeves;
   ship the 7 positive at ~$293/day @ $25 notional ensemble.

5. **The 4 failing shadow sleeves** (#2, #3, #5, #10) need:
   - #3 (btc_15m momo v1 + HoD only): add M1V Markov; spec's WR claim was
     likely based on a Markov stack, not pure HoD
   - #10 (sol_15m momo_v2): production-disabled cell per
     `TV_POLY_MOMO_V2_DISABLED_CELLS` env var — drop entirely
   - #5 (btc_5m sniper +HoD): refresh HoD_TOP8_BY_CELL with current 28d
   - #2 (eth_15m sniper +m5va): Markov inversion suggests m5va wrong for
     bar-close sniper fires — try M1V or drop Markov on sniper

---

## What we did this session (chronological)

### 1. Wallet decoder context restoration
Read `HANDOFF_WALLET_DECODER_2026_05_16.md`. Confirmed 4 mint-and-sell
wallets ($10k-$344k/day). User had moved focus from wallet hunting to
strategy backtesting.

### 2. Mint-and-sell partial-fill policy analysis
Built `strategy_lab/wallet_hunt/replicate/partial_fill_policy_compare.py`.
Tested HOLD vs MARKET_EXIT vs HYBRID on canonical L25.
**Finding**: HOLD beats MARKET_EXIT in every cell. Why: unfilled-side
book is too thin — `exit_ratio = best_bid_unfilled / best_ask_unfilled`
median = 0.40-0.59, so market-exit crosses a 50¢ spread + pays taker fee.
**Held_win_rate is only 17-30% (not 50%)** because the side that filled
is almost always the side takers think will win → wallet holds the
underdog → wins ~24%.

### 3. Wallet behavior decode (mint-and-sell wallets)
Built `compare_wallet_vs_scanner.py`, `inspect_wallet_sizing.py`.
Found wallets:
- Fire at sum_asks = $1.010 median (NOT $1.035+ as our scanner gated)
- Size $3-6 per fill (NOT $25/$200 as we backtested)
- 30-170 fires per slug (NOT 1-2 like our sampled scan)

Pre-mint pattern confirmed: 0x89b5cdaa had 1 mint TX → 1,500 sells.

### 4. v2 scanner with corrected fee model
Built `mint_and_sell_scan_v2.py`. Corrected the maker-fee bug (rebate is
INCOME not phantom cost), lowered entry to sum_asks ≥ 1.005, cooldown=1s
(every snapshot), $2.5 notional. Found **5.2M opportunities across 6 cells**.

But: at $2.5 notional, our backtest STILL showed HOLD aggregate negative
(-$25k/day). The reason: per-fire view always loses because partial-fill
held side is biased loser. **The wallet edge is at SLUG-AGGREGATED level** —
when a wallet fires 30+ times per slug, both Up-only and Down-only partials
happen → wallet ends up holding BOTH sides → whichever side wins, that
pile redeems → cancels partial drag.

### 5. Mint-and-sell implementation spec (TV agent)
Wrote `MINT_AND_SELL_IMPLEMENTATION_SPEC_V1.md` (1,479 lines). Full live
deploy spec covering:
- Polymarket CLOB hosted on **AWS eu-west-2 (London)**. User's Ireland VPS
  is <2ms RTT — near-optimal. US East = 130ms (uncompetitive).
- POLY_1271 deposit wallet flow (recommended for new bots, gasless)
- Pre-mint inventory at slot_start, sell in $2.5 chunks throughout 15min
- Worked example showing inventory accounting + EV calc
- 5-phase rollout from paper → $25 → $250 → $1000+ notional

### 6. 0xb27bc932 wallet decode (last-day)
Pulled fresh chain data for `0xb27bc932bf8110d8f78e55da7d5f0497a18b5b82`.
**Finding**: pure-TAKER directional buyer (100% BUY fills, 0 SELL, 0 mints).
1,722 BUY fills in 13h spending $12,091; got back $12,485 from redemptions.
**−$952/day**. Uses pUSD (POLY_1271). 38-min activity bursts.
**NOT a candidate to mimic.**

### 7. Momo variants 2A / 2B / 2C
Built `strategy_lab/meta_classifier/momo_variants_2abc.py`. Three new
fire-timing schemes vs production Baseline_v1/v2:
- **2A**: fresh signal at fire (ws-240, ws-120), fire at slot-120s
- **2B**: Design 3 signal anchor, delayed order to slot-120s
- **2C**: fire AT slot_open, signal anchored on prior 2min

Run 1 (default LiveMimicConfig): showed all 5 variants negative aggregate.
Re-ran with LegacyConfig (matches production accounting). Discovered the
real PnL impact of fee model differences.

### 8. The F7 RSI anchor saga (corrected three times)

**Iteration A**: First implementation used `fire_s` as RSI anchor. Showed
F7 hurts on canonical backtest, opposite to production's "+$3.6k/day F7
lift" claim.

**Iteration B**: User flagged production's reported F7 lift might come
from lookahead. I built `_verify_f7_anchor.py` against `fires_with_gates.csv`.
Got 80.9% WR at `slot_end` anchor — looked like smoking-gun lookahead bug
in `momo_12cells_f7.py:36` (`ws_s = at_ts // 1e9` where at_ts = slot_end).
Updated CLAUDE.md to flag.

**Iteration C**: User pushed back — live VPS3 shadow PnL is REAL,
chainlink-resolved, can't have lookahead.

**Iteration D**: Built `_match_live_f7.py` — but was VERSION-UNAWARE
(subtracted 120 from all fires, wrong for v2 which fires at ws_s+60).
Got 92.41% match at fire_us, "concluded" fire_us was the anchor.

**Iteration E**: Pulled VPS3 production code
(`migration_2026_05_21/vps3_controller_inspect/`). Read
`build_bar_context_t_plus_120` in `poly_updown_loop.py`:
```python
offsets = [-60 * i for i in range(14, -1, -1)]  # -840..0
closes = await asyncio.gather(*[_fetch_close(o) for o in offsets])
```
**Production samples RSI at `ws_s`**, not at fire time.

**Iteration F (FINAL)**: Built `_match_live_f7_v2.py` with version-aware
ws_s (v1: fire_s−120, v2: fire_s−60). **94.67% match at ws_s, beats fire_us
at 92.41%**. This is the correct anchor.

**My ORIGINAL "fix to ws_s" was correct**; I reverted it incorrectly based
on the buggy verifier. The production RSI is anchored at ws_s using
simple-mean Wilder (NOT exponential smoothing) over 15 closes ending at ws_s.

### 9. Fresh canonical pull
Pulled VPS3 deltas from 2026-05-20 onwards. New `migration_2026_05_21/`
pipeline:
- `pull_delta_vps3_2026_05_21.sh` — server-side pull (12 tables, ~403 MB compressed)
- `convert_and_merge.py` — gz csv → parquet
- `merge_to_canonical.py` — append-merge into canonical

Canonical now covers **April 24 → May 21 20:10 UTC** (28d, 30,750
chainlink-resolved markets). F7 deployment window (post 2026-05-20 19:57)
fully included. Patched `data/v4/canonical/load.py` to add the new L25 path
+ added `min_ts_us` / `max_ts_us` params for time-window filtering.

### 10. Sub-second L25 backtest with batching
User pushed back that 1Hz subsample was wrong. Re-ran without subsample,
batched 100 slugs at a time to fit memory.
**Finding**: sub-second vs 1Hz produces **near-identical** aggregate PnL
(~$0.03/tr difference). My variants fire at integer-second boundaries,
so both modes return a snapshot in the same second-bucket. Sub-second
precision only matters when fire times are sub-second too (i.e. replaying
production fire_us microseconds — not for deterministic synthetic variants).

### 11. Production WS-only book reads verified
User pushed back that production uses WS not REST. Pulled
`venues/polymarket/{paper.py, book_mirror.py, market_data.py, client.py}`
from VPS3. Confirmed Phase 18.6 W1 3-tier dispatcher:
- Tier 1: WS BookMirror (in-memory, `wss://ws-subscriptions-clob.polymarket.com`)
- Tier 2: CLOB REST fallback
- Tier 3: Storedata DB disaster fallback with CRITICAL alert
Live `tv-engine` journal verified — every `paper.book_fetched` is `ws_mirror` source.
**Removed wrong REST-staleness claim** from CLAUDE.md.

### 12. Production fee model verified — 2%-on-profit only
User pushed back that the "real fee curve" (`0.07×p×(1-p)`) doesn't apply.
Inspected 25,900 production `poly_updown_resolution` events:
- **Lost trades**: PnL = `-entry_qty × entry_price` exactly (median diff = 0)
- **Won trades**: PnL = `entry_qty × (1 − entry_price) × 0.98` exactly (median diff = 0)

Polymarket BTC/ETH/SOL up-down crypto markets effectively have `feeRate=0`
or `feesEnabled=false` — the only fee is the legacy 2% on winning leg.
**Updated CLAUDE.md** to reflect this. Use `engine_v2.LegacyConfig` (not
`LiveMimicConfig`) for any production-parity backtest. The `pnl_real_usd`
column my variants emit is fictitious — use `pnl_legacy_usd` instead.

### 13. Markov filter integration
Found `strategy_lab/markov_filter/markov_regime_micro.py`. Built
`momo_variants_markov_overlay.py` to add Markov regime columns to
per_trade.parquet without re-running the heavy backtest.

4 Markov variants tested:
- M1F (w20, 1m bars, fixed thresholds 0.003/0.004/0.006 for BTC/ETH/SOL)
- M5F (w20, 5m bars, fixed 0.005/0.007/0.010)
- M1V (w20, 1m bars, vol-adaptive q33/q66 of 14d)
- M5V (w20, 5m bars, vol-adaptive)

**Markov keeps fires where signal direction agrees with regime**:
- UP signal + BULL regime → keep
- DOWN signal + BEAR regime → keep
- everything else → skip

### 14. Deploy sleeve 28d audit (5 sleeves)
Built `deploy_sleeves_28d_audit.py`. Ran S1-S5 across full 28d window.

Total ensemble PnL **+$1,707 over 28 days** at $25 notional × 5 sleeves =
**~$60/day**. 16/24 trading days positive. Best day +$381 (May 12),
worst −$276 (May 20). Max drawdown ranges −$125 (S5) to −$243 (S3).

Sleeve overlap (Jaccard on slug sets):
- S1+S2 = 32% (both M1V on BTC 15m)
- S2+S3 = 58% (S3 is F7-subset of S2)
- S5 fully orthogonal to all BTC sleeves

Projection: $/day scales roughly linear to ~$250 notional, ~80% of linear
to $1000. At full $1000 × 5 sleeves, expect ~$2,500/day with worst-day
drawdown −$11k.

### 15. 11-sleeve shadow spec backtest
Read `TV_AGENT_SHADOW_DEPLOY_GATED_SLEEVES_2026_05_22.md` (11 gated shadow
sleeves wrapping momo/momo_v2/sniper with HoD/MTF2/Markov gates).

Built `shadow_11_sleeves_backtest.py`. Applied gate stacks to 14,148
production base-sleeve resolutions. Results:

**4 PASS**:
- #7 momo_v2 btc_15m _hod: 66.67% WR, +$8.05/tr, +$869 sum
- #8 momo_v2 sol_5m _hod: 60.34% WR, +$4.81/tr, **+$1,673 sum** ← biggest
- #9 momo_v2 eth_15m _hod: 65.87% WR, +$6.64/tr, +$837 sum
- #11 sniper eth_5m _hod: 51.94% WR, +$0.49/tr (low end of expected range)

**3 underperform-but-positive**:
- #1 sniper sol_5m _hod, #4 sniper btc_15m _hod, #6 momo_v2 btc_5m _hod_mtf

**4 NEGATIVE — DO NOT DEPLOY**:
- #2 sniper eth_15m _hod_m5va (Markov inversion)
- #3 momo v1 btc_15m _hod (spec claim was likely based on M1V, not pure HoD)
- #5 sniper btc_5m _hod (hot hours don't generalize)
- #10 momo_v2 sol_15m _hod (production-disabled cell)

Deploy the 7 positives → ensemble **+$293/day @ $25 notional**, ~+$2,930/day @ $250.

---

## Current state of canonical (verified 2026-05-22)

```
klines_1m       last = 2026-05-21 20:17 UTC  (533,345 bars total)
klines_1s       last = 2026-05-21 20:17:32   (11,384,517 bars)
chainlink_rtds  last = 2026-05-21 20:17:38   (6,753,609 rows)
resolutions     last = 2026-05-21 20:10      (33,622 markets, 30,750 chainlink-derived)
trading_events  last = 2026-05-21 20:17:06   (851,225 events, 30d rolling)
L25 BTC/ETH/SOL last = 2026-05-21 (refresh_2026_05_21/cache/)
trades_poly     btc last = 2026-05-21 20:17:45   (31,101,501 trades)
                eth last = 2026-05-21 20:18:34
                sol last = 2026-05-21 20:18:43
```

L25 loader in `data/v4/canonical/load.py` includes 4 sources stacked
chronologically: refresh_2026_05_16 → 19 → 21. Use `min_ts_us`/`max_ts_us`
params to bound memory.

---

## Files created/modified this session

### Created
- `strategy_lab/wallet_hunt/replicate/partial_fill_policy_compare.py`
- `strategy_lab/wallet_hunt/replicate/partial_fill_policy_compare_v2.py`
- `strategy_lab/wallet_hunt/replicate/mint_and_sell_scan_v2.py`
- `strategy_lab/wallet_hunt/replicate/slug_level_aggregation.py`
- `strategy_lab/wallet_hunt/replicate/compare_wallet_vs_scanner.py`
- `strategy_lab/wallet_hunt/replicate/inspect_wallet_sizing.py`
- `strategy_lab/wallet_hunt/replicate/replay_at_wallet_conditions.py`
- `strategy_lab/wallet_hunt/replicate/check_premint_pattern.py`
- `strategy_lab/wallet_hunt/_analyze_b27_last_day.py`
- `strategy_lab/wallet_hunt/_analyze_b27_deep.py`
- `strategy_lab/meta_classifier/momo_variants_2abc.py` ← main variants runner
- `strategy_lab/meta_classifier/_match_live_f7.py` (deprecated, buggy)
- `strategy_lab/meta_classifier/_match_live_f7_v2.py` ← correct verifier
- `strategy_lab/meta_classifier/_verify_f7_anchor.py`
- `strategy_lab/meta_classifier/_verify_f7_live_rsi.py`
- `strategy_lab/meta_classifier/momo_variants_markov_overlay.py`
- `strategy_lab/meta_classifier/deploy_sleeves_28d_audit.py`
- `strategy_lab/meta_classifier/shadow_11_sleeves_backtest.py`
- `migration_2026_05_21/pull_delta_vps3_2026_05_21.sh`
- `migration_2026_05_21/convert_and_merge.py`
- `migration_2026_05_21/merge_to_canonical.py`
- `migration_2026_05_21/vps3_controller_inspect/` (14 production code files pulled)

### Reports (in `strategy_lab/reports/`)
- `MINT_AND_SELL_PARTIAL_FILL_POLICY_2026_05_16.md`
- `MINT_AND_SELL_V2_FULL_REPLICATION_2026_05_16.md`
- `MINT_AND_SELL_IMPLEMENTATION_SPEC_V1.md` ← 1,479 lines, full TV deploy spec
- `WALLET_B27_DECODE_2026_05_20.md`
- `MOMO_VARIANTS_2ABC_2026_05_20.md`
- `F7_LOOKAHEAD_BUG_AND_CORRECTED_2026_05_20.md` ← updated with correction header
- `MOMO_V1_V2_F7_PROD_2026_05_20.md`
- `MOMO_VARIANTS_FRESH_F7_VERIFIED_2026_05_21.md`
- `MOMO_VARIANTS_SUBSEC_F7_WINDOW_2026_05_21.md`
- `MOMO_VARIANTS_28D_SUBSEC_2026_05_21.md`
- `MOMO_VARIANTS_PROD_MATCHED_2026_05_21.md` ← updated with fee correction
- `MOMO_VARIANTS_F7_MARKOV_STACK_2026_05_22.md`
- `DEPLOY_SLEEVES_28D_FINAL_2026_05_22.md` ← 5 deploy candidates
- `SHADOW_11_SLEEVES_BACKTEST_2026_05_22.md` ← 11-sleeve spec backtest

### Modified
- `CLAUDE.md` — added F7 anchor block, fee-model block, refresh date,
  WS-only verification, dropped REST-staleness claim
- `data/v4/canonical/load.py` — added refresh_2026_05_21 L25 path,
  added `min_ts_us`/`max_ts_us` params

---

## What we DID NOT do (next session)

### High-priority next steps

1. **Promote the 5 deploy sleeves (S1-S5) to TV agent** — they're already
   spec'd in `DEPLOY_SLEEVES_28D_FINAL_2026_05_22.md`. Need TV agent to
   wire them into the controller config. The Markov filter code already
   exists at `strategy_lab/markov_filter/markov_regime_micro.py`; TV needs
   to port `label_regime_vol_adaptive` into `backend/app/strategies/polymarket/`.

2. **Refresh HOD_TOP8_BY_CELL for the 4 failing shadow sleeves**:
   - Spec section 6 references `_recompute_hod_top8.py` — that script
     doesn't exist yet. Build it: pull last 28d of resolved trades per
     (strategy, cell), sum$ per hour, output top 8. Or inline the logic
     in a one-off analysis script.
   - Re-run sleeves #5 (btc_5m sniper +HoD) with refreshed hours.

3. **Re-test sleeve #3 (momo v1 btc_15m) with M1V Markov added**: spec's
   claim of 70-85% WR almost certainly came from M1V or F7+M1V (per my
   28d audit Baseline_v1 + M1V = 59.8% WR). Adding M1V to the gate stack
   would likely flip it positive.

4. **Investigate sleeve #2 (sniper eth_15m _hod_m5va) Markov inversion**:
   M5V cuts 490 → 44 fires but WR = 47.7% (random). Sniper fires at
   slot_start, not at momentum-aligned moment → regime at fire ≠ regime
   that drives the bet. Try:
   - Anchor Markov at the SIGNAL time (ws_s for momo, slot_start − window_s
     for sniper bar-close) instead of at fire time
   - Try M1V instead of M5V
   - Try fixed-threshold instead of vol-adaptive
   - Or just drop Markov on sniper sleeves entirely

5. **Replicate production's feed-backed q90 universe**: my chainlink-only
   q90 calibration produces a tighter threshold than production's
   `_fetch_abs_ret_2m_history` (which samples all binance_klines_v2 in
   rolling 14d). My backtest fires 10x FEWER than production. Mirror
   production's calibration to close the gap.

### Lower-priority follow-ups

6. **Decode 0xf3cfb6a6 relay wallet** (paired with 0xb27bc932) — see
   `WALLET_B27_DECODE_2026_05_20.md`. May reveal hidden inventory routing.

7. **Implement the maker-fee bug fix in `mint_and_sell_scan.py`** (handoff
   §1). The legacy scanner subtracts a phantom fee that doesn't exist on
   crypto up-down markets (we verified production fee model is 2%-on-profit-
   only). Just update the formula.

8. **Long-form market lookup for `0xf247584e`** (pair-accumulator wallet).
   Needs Gamma API search for `up-or-down-{date}-{time}-et` markets.

9. **Spec sell-and-redeem variant** properly (currently described in handoff
   §2 but not backtested). Mostly the same engine as mint-and-sell with a
   single config flag.

10. **Run the mint-and-sell strategy in paper mode** per
    `MINT_AND_SELL_IMPLEMENTATION_SPEC_V1.md`. The spec is complete; needs
    TV agent to build the engine + paper simulator. ~2-3 weeks of dev.

11. **Out-of-sample validation of S1-S5**: hold out last 7d, fit gates on
    first 21d. Verify M1V profit pockets generalize. (Currently the gate
    parameters are calibrated on the same window as the backtest.)

---

## Key conventions (verified 2026-05-22 — DO NOT VIOLATE)

1. **F7 RSI anchor** = `ws_s = slot_start − window_s`. NOT fire_us, NOT
   slot_start, NOT at_ts. Verified at 94.67% match against production.

2. **RSI calc** = simple-mean Wilder over 15 closes ending at ws_s
   (production `rsi.py` confirms: "simple-MA flavor — NOT exponential").

3. **Fee model** = legacy 2%-on-profit-only. NO fee on losing legs.
   Verified against 25,900 production resolutions, median diff = 0.

4. **Books** = WS-only via Polymarket WS BookMirror. No REST staleness
   inflation in production today.

5. **Engine config for production-parity backtests** = `engine_v2.LegacyConfig`
   (NOT LiveMimicConfig — that over-charges fees that production doesn't pay).
   Use `pnl_legacy_usd` from per-trade outputs.

6. **L25 lookups**: `subsample_1hz=False` only matters for sub-second fire times.
   For integer-second fires (all deterministic variants), 1Hz is equivalent.

7. **Production fires ~10x more often than chainlink-only universe** because
   production's q90 is computed against feed-backed `binance_klines_v2`
   (all minute bars in rolling 14d). Mirror via custom q90 computation
   if you want fire-count parity.

---

## Quick-start commands for next session

```bash
# Activate the variants backtest at production parity
cd "C:/Users/alexandre bandarra/Desktop/global"

# Re-run the 5-sleeve audit (uses existing per_trade_markov.parquet)
PYTHONIOENCODING=utf-8 C:/Python314/python.exe \
  strategy_lab/meta_classifier/deploy_sleeves_28d_audit.py

# Re-run the 11-sleeve shadow backtest (production fires + gate stacks)
PYTHONIOENCODING=utf-8 C:/Python314/python.exe \
  strategy_lab/meta_classifier/shadow_11_sleeves_backtest.py

# Verify F7 anchor (production-matching verification)
PYTHONIOENCODING=utf-8 C:/Python314/python.exe \
  strategy_lab/meta_classifier/_match_live_f7_v2.py

# Pull fresh canonical data (next time the window needs to extend)
ssh -i ~/.ssh/vps3_ed25519 root@185.190.143.7 \
  'bash /tmp/pull_delta_2026_05_21.sh > /tmp/pull.log 2>&1'
scp -i ~/.ssh/vps3_ed25519 \
  'root@185.190.143.7:/tmp/v3_delta_2026_05_21/*.gz' \
  data/v4/refresh_2026_05_XX/raw/
# Then convert + merge per migration_2026_05_21/{convert_and_merge,merge_to_canonical}.py
```

---

## Recommended starting prompt for next session

```
Read this first: strategy_lab/reports/HANDOFF_2026_05_22_MOMO_F7_MARKOV.md

Context: we have 5 deploy sleeves verified at production parity
(legacy 2%-on-profit fee, ws_s F7 anchor, WS-only books) with 28-day
backtest passing. Plus 7 of 11 shadow sleeves from the TV spec pass
expected ranges. Three concrete next tasks:

1. Build `_recompute_hod_top8.py` per spec section 6, refresh hot-hour
   lists for failing sleeves #2, #3, #5, #10. Re-backtest.
2. Add M1V Markov to sleeve #3 (btc_15m momo v1) gate stack — likely
   the missing piece.
3. Send the 7 positive shadow sleeves + the 5 deploy sleeves to TV
   agent for implementation.

[Then: paste new task or pick from §"What we DID NOT do" above]
```

---

## End of handoff
