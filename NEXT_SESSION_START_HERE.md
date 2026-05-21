# NEXT SESSION — Start Here

> 🚨 **Most recent session (2026-05-19): read [`NEXT_SESSION_PICKUP_2026_05_19.md`](NEXT_SESSION_PICKUP_2026_05_19.md) FIRST.**
> Three production-ready maker-bot strategies (ACC-M, MAS, ACC-H) fully
> spec'd + Python-coded + handed off to TV agent for deployment on
> Ireland VPS. Shadow engine at `shadow_engine/`. Master TV handoff doc:
> `strategy_lab/reports/README_TV_AGENT_HANDOFF.md`.
>
> Prior pickup (2026-05-18) — Mint-and-Sell V2 deep-dive — superseded by
> the 3-strategy decode + build session above. Cyclops S7 X1 still
> paper-deploy-ready as a parallel option.

**Last data refresh:** 2026-05-16 (canonical re-built from VPS3 + VPS2 collectors)
**Window:** 2026-04-24 → 2026-05-15 (21 days, 23,553 chainlink-resolved markets)
**Canonical entry point:** `from data.v4.canonical.load import *`
**Status:** Full-universe backtest sober — see §"Recent benchmark" — only 2 cells carry positive expectancy at scale.

---

## In one sentence

**Production momo strategy is unprofitable on a full 21d chainlink-resolved universe (-$1.21/tr, n=2,909, 48.4% hit, walkforward 5/18 positive days, permutation p>0.07).** The 14d shadow positives (`btc_15m_momo_HOLD` +$10.73/tr n=23, etc.) collapse on the larger backtest sample. Only **`v1 sol_5m HOLD`** (+$1.45/tr n=227) and **`v1 btc_15m HYBRID_RevOrStop_SELL`** (+$3.19/tr n=97, p≈0.08) survive. Pursue new strategies on the canonical universe; don't trust small-n shadow signals.

---

## Where everything lives (`data/v4/`)

| Path | Size | Status | Purpose |
|---|---:|---|---|
| **`canonical/`** | **6.6 GB** | ✅ fresh 2026-05-16 | **read all data through `canonical/load.py`** |
| `refresh_2026_05_12/` | 3.5 GB | scratch CSVs from May 12 pull | trading.events 14d, server-side flow features, hl_liquidations, markets catalog |
| `refresh_2026_05_06/` | 9.8 GB | kept (canonical's L25 cache references early-window subset) | DO NOT delete — would break `build.py --step orderbook` re-runs |
| `tier1_entries/` | 30 MB | indirectly used (canonical has `tier1_entries_at_t120/`) | legacy path; prefer canonical |
| `derivatives_zscore/` | 208 MB | kept (V5 gauntlet alpha) | derivatives Z-score features, regime tagging |
| `oi/`, `funding/` | small | active for derivatives features | |
| `shadow_trades_2026_05_09/` | small | most recent shadow audit snapshot | sleeve-level deltas |
| `refresh_2026_05_16/` | 1.6 MB | current scratch | partial today's pull |

### Canonical sub-paths (the ones backtests actually load)

```
data/v4/canonical/
├── load.py                          # the API — import from here always
├── README.md                        # schema + conventions
├── build.py                         # rebuild canonical from raw refreshes
├── _test_ws_s.py                    # self-test the ws_s convention
├── chainlink_rtds.parquet           # 89.9 MB, 5.19M rows (1Hz oracle, 3 assets × 21d)
├── klines_1m.parquet                # 21.6 MB, multi-venue 1MIN bars
├── resolutions_from_rtds.parquet    # 2.6 MB, 23,553 markets (locally re-derived, chainlink-only)
├── clob_resolutions_cache.parquet   # CLOB-side resolutions (binance contamination filtered)
├── orderbook_l25/{btc,eth,sol}.parquet  # 5.4 GB total — full L25 OB streamed by slug
├── tier1_entries_at_t120/{btc,eth,sol}.parquet  # 10.4 MB — pre-joined entry book at ws+120s
├── trades_polymarket/{btc,eth,sol}.parquet      # ⚠️ STALE 2026-04-22 → 2026-05-06
└── _results/                        # backtest outputs (CSVs)
    └── full_universe_2026_05_16/    # latest full backtest
```

### Per-dataset time coverage

| dataset | window (UTC) | span |
|---|---|---:|
| **Backtest universe** (resolutions, chainlink-only) | **2026-04-24 01:40 → 2026-05-15 02:55** | **21.0 days** |
| Orderbook L25 (book at any time) | 2026-04-22 ~14:47 → 2026-05-15 ~01:45 | 22.5 days |
| Chainlink RTDS (1Hz oracle prices) | 2026-04-24 01:38 → 2026-05-15 03:30 | 21.1 days |
| Binance 1MIN klines (binance-spot-ws) | 2026-04-14 16:00 → 2026-05-15 03:01 | 30.5 days |
| Binance 1MIN klines (binance-vision archive) | 2026-04-05 03:03 → 2026-04-28 18:52 | 23.7 days |
| Coinbase 1MIN klines | 2026-04-08 00:56 → 2026-05-15 03:01 | 37.1 days |
| Kraken 1MIN klines | 2026-05-07 12:58 → 2026-05-15 03:01 | 7.6 days *(collector started May 7)* |
| OKX 1MIN klines | 2026-04-28 04:50 → 2026-05-15 03:01 | 16.9 days |
| Tier1 entries (entry book at ws+120s) | 2026-04-24 01:42 → 2026-05-15 02:57 | 21.0 days |
| ⚠️ **Polymarket trades** *(STALE — no fresh delta puller yet)* | 2026-04-22 12:08 → **2026-05-06 15:20** | 14.1 days (ends 10d ago) |
| VPS3 `trading.events` (sleeve audit) | last 14d through 2026-05-15 02:42 | 14 days |

### Resolutions per (asset, timeframe) — 23,553 markets total

- BTC 5m: 5,887 | BTC 15m: 1,964
- ETH 5m: 5,887 | ETH 15m: 1,964
- SOL 5m: 5,887 | SOL 15m: 1,964

---

## ⚠️ Critical conventions agents MUST respect

### 1. Timestamps are UTC microseconds

Columns: `*_us` (microseconds), `slot_start_us`, `timestamp_us`, `time_exchange_us`, `query_ts_us`. Seconds-suffix `*_s` columns are also UTC. **Never localize, never CET.**

### 2. `ws_s ≠ slot_start` — the slug-ws convention

🚨 **The most expensive bug in this codebase.** Get this wrong → hit rate inflates **25–40 pp** (≈ 85% on backtest vs ≈ 50% live).

```python
# Slug-to-time mapping
slug_suffix    = int(slug.rsplit("-", 1)[1])           # seconds
slot_start_us  = slug_suffix * 1_000_000
slot_end_us    = slot_start_us + window_s * 1_000_000  # window_s = 300 (5m) or 900 (15m)

# Production controller anchor (USE THIS)
ws_s    = slug_suffix - window_s                       # PREVIOUS slot's start
ret_2m  = log(close@(ws_s + 120) / close@(ws_s))       # 2-min PRE-strike momentum
fire_us = (ws_s + 120) * 1_000_000                     # production fire wall-clock
```

Use the helpers; don't re-derive:

```python
from load import slug_to_ws_s, add_ws_s, ret_2m_at_ws
ws_s = slug_to_ws_s(slug, timeframe)
ret  = ret_2m_at_ws(end_us, prices, ws_s)
```

Self-test: `py -3 -X utf8 data/v4/canonical/_test_ws_s.py` must print `=== ALL CHECKS PASSED ===`.

Reference: `strategy_lab/reports/SESSION_HANDOFF_2026_05_10_WS_S_CONVENTION.md`.

### 3. Outcome resolution = Chainlink Data Streams (NEVER derive from binance)

Use either:
- The `outcome` column on `load_resolutions()` (already chainlink-derived, binance-contaminated rows filtered out)
- OR compute from `load_chainlink_asof()` strike vs settlement

Never resolve a binary market by comparing binance close prices — multiple sleeves got bad hit rates from binance contamination in the catalog.

### 4. Binance is the SIGNAL source

Matches production momo controller. Coinbase / Kraken / OKX are alternative venues for ablation tests only. The signal anchor uses `BINANCE_SPOT_*_USDT` with `source='binance-spot-ws'`.

### 5. `asof_strict(end_us, prices, target_us)` — causal asof

Returns close of the bar that ENDED at-or-before `target_us`. End-time-indexed; cannot return a future-bar close. Use this for all 1MIN kline lookups in backtests.

```python
from load import asof_strict
price_at_ws = asof_strict(end_us, prices, target_us=ws_s * 1_000_000)
```

### 6. L25 walk = production fill model

Production fills lift the ask with $25 notional. Backtest must mirror:

```python
from strategy_lab.book_walk import book_walk_fill
vwap_e, shares_e, usd_e, levels_hit, under = book_walk_fill(ask_p, ask_s, notional_usd=25.0)
# under == True → book was thinner than $25; usd_e is what actually got filled
```

### 7. Fee model — 2% on profit only

Win: `pnl = shares * 1.0 - usd_e - max(0, (shares - usd_e)) * 0.02`
Loss: `pnl = -usd_e` (no fee on losses)

Hedge: 2% on the winning leg's profit only.

---

## Engine catalog — pick the right tool

### Tier A: Canonical engines (start here)

| Engine | Path | What it does |
|---|---|---|
| **`load.py`** | `data/v4/canonical/load.py` | the data API — every loader you need |
| **`build.py`** | `data/v4/canonical/build.py` | rebuilds canonical from raw refreshes; `--step` to target one part |
| **`momo_full_universe_canonical.py`** | `strategy_lab/meta_classifier/momo_full_universe_canonical.py` | **the current full-universe backtest** — 15 variants × 6 cells × walkforward × permutation |
| **`momo_full_universe_validation.py`** | `strategy_lab/meta_classifier/momo_full_universe_validation.py` | validates `momo_full_universe_canonical` output against shadow data |
| `clob_resolutions.py` | `data/v4/canonical/clob_resolutions.py` | builds the CLOB-side resolutions cache (filters binance contamination) |
| `_test_ws_s.py` | `data/v4/canonical/_test_ws_s.py` | run before any backtest to confirm ws_s convention holds |
| `_sanity.py` | `data/v4/canonical/_sanity.py` | sanity checks on canonical parquets |

### Tier B: Backtest variants + audits

| Engine | Path | What it does |
|---|---|---|
| `extended_backtest_with_robustness.py` | `strategy_lab/meta_classifier/extended_backtest_with_robustness.py` | older 18-cell backtest with permutation + walkforward (refresh_2026_05_02 dependent) |
| `momo_shadow_vs_backtest.py` | `strategy_lab/meta_classifier/momo_shadow_vs_backtest.py` | shadow data vs backtest reconciliation |
| `momo_partial_fill_backtest.py` | same dir | partial-fill simulator (book thinner than notional) |
| `momo_exit_policy_explore.py` | same dir | exit policy sweep (HOLD vs HEDGE vs SELL at various rev_bp) |
| `momo_coinbase_overlay.py` / `momo_coinbase_lead.py` | same dir | coinbase-as-signal-source ablation tests |
| `cex_alignment_*.py` | same dir | cex venue alignment / disagreement signal |
| `momo_live_vs_backtest_diagnose.py` | same dir | per-trade comparison live vs backtest |
| `permutation_strict.py` | same dir | strict sign-flip permutation (1000+ draws) |
| `momo_ws_walkforward_perm.py` | same dir | walkforward + perm combo on momo strategy |
| `v3_production_replay.py` | same dir | replay v3 strategy through production timestamps |

### Tier C: Realfill (L25 raw book) replay

| Engine | Path | What it does |
|---|---|---|
| `validate_with_real_book.py` | `strategy_lab/momo_realfill/validate_with_real_book.py` | replay each shadow fire against L25 raw book |
| `match_shadow_strict.py` | same dir | slug-by-slug match of shadow trades to backtest decisions, strict-asof |
| `compare_3way.py` | same dir | shadow vs backtest vs realfill triple comparison |
| `diagnose_5m_slippage.py` | same dir | slippage decomposition for 5m markets |
| `verify_lookahead_bug.py` | same dir | proves the asof-bar-open vs asof-bar-end lookahead difference |

### Tier D: Confluence layer experiments (deprecated for v1 deploy — see verdict)

| Engine | Path | What it does |
|---|---|---|
| `run_grand_backtest.py` | `strategy_lab/confluence/run_grand_backtest.py` | 4-layer (FLOW/STRUCT/TRIG/GUARD) → tier classifier → backtest |
| `run_struct_flow_backtest.py` | same dir | 2-layer (struct+flow only) simpler classifier |
| `validate_silver_alpha.py` | same dir | 5-gate validation battery (perm/walkforward/bootstrap/regression/realfill) |
| `silver_overview.py` | same dir | per-trade + monthly expectancy projection |
| `validate_layers.py` | same dir | sanity-check each layer parquet (schema + coverage) |

**Verdict on confluence (2026-05-07):** SILVER tier on SOL alpha vector was n=8, mechanical pass on 2/5 gates, breakeven hit rate 86%. Paper-only candidate; not ship-ready. See `strategy_lab/reports/SILVER_VALIDATION_FINAL_2026_05_07.md`. Strategy ideas section §I has a "revisit on canonical" item.

### Tier E: Feature builders (cached output in canonical or per-asset)

| Engine | Path | What it does |
|---|---|---|
| `confluence/flow/build_features.py` | `strategy_lab/confluence/flow/build_features.py` | builds FLOW per-(slug,outcome) features from L25 + trades |
| `confluence/structure/build_structure.py` | same package | builds STRUCTURE per-slug features from klines |
| `confluence/trigger/build_trigger.py` | same package | builds TRIGGER (liq_magnet, FVG, OFI) features |
| `confluence/guard/build_guards.py` | same package | builds GUARD blocks (extreme price, dead market, etc.) |
| `meta_classifier/pull_tier1_entries.py` | `strategy_lab/meta_classifier/` | pulls L25 entries at ws+120 per slug (legacy path; canonical has the parquet) |

### Tier F: Derivatives (V5 gauntlet — KEPT as alpha-flagged)

| Engine | Path | What it does |
|---|---|---|
| `gauntlet_v5.py` | `strategy_lab/v4_signals/derivatives_zscore/gauntlet_v5.py` | **V5 gauntlet — ETH deploy candidate** per `V5_GAUNTLET_VALIDATION.md` |
| `research_v5.py` | same dir | `run_combo()` — core compute backing the gauntlet |
| `compute_zscores.py` | same dir | builds the Z-score features |
| `strategy_4h_adaptive.py` | same dir | adaptive 4h strategy variant |
| `carry_overlay.py` | same dir | post-process: 5% idle-cash carry overlay (fixes G4 per-year-positive gate) |
| `regime_detector_v2.py` | same dir | regime tagging used by ensemble |

### Tier G: V3/Phase7 union (existing momo predecessor)

| Engine | Path | What it does |
|---|---|---|
| `v4_signals/phase7_clob_imbalance_momentum.py` | `strategy_lab/v4_signals/` | the active phase7 momentum signal |
| `v4_signals/phase7_validation.py` | same dir | validation harness |
| `v4_signals/backtest_vs_shadow_audit.py` | same dir | audit phase7 backtest vs production shadow |

### Tier H: Cleanup / archive

`strategy_lab/_archive/` holds 33 retired top-level builders moved here on 2026-05-07. Restorable via `mv` if needed.

---

## How to run a backtest that EXACTLY matches a live market

This is the canonical recipe. Mirrors production controller's signal → fire → fill → resolve loop.

### Step 0: Prelude — paste this at top of any backtest script

```python
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))

from load import (
    load_resolutions,                    # chainlink-only universe (23,553 markets)
    load_klines, load_klines_asof,        # binance + cex 1MIN bars
    load_chainlink_rtds, load_chainlink_asof,
    load_orderbook_l25_streaming,         # filter by slugs to bound memory
    load_tier1_entries,                   # pre-joined entry book at ws+120s
    load_trades,                          # ⚠️ stale through May 6 only
    asof_strict,                          # CAUSAL end-time-indexed asof
    slug_to_ws_s, add_ws_s, ret_2m_at_ws, # ws_s convention helpers
)
from book_walk import book_walk_fill      # production fill model
```

### Step 1: Verify environment

```python
import subprocess
subprocess.run(["py", "-3", "-X", "utf8",
                str(ROOT / "data" / "v4" / "canonical" / "_test_ws_s.py")],
               check=True)
# Must print "=== ALL CHECKS PASSED ==="
```

### Step 2: Load universe (chainlink-resolved markets only)

```python
res = load_resolutions()                                          # 23,553 markets, all assets / tfs
# Or filter:
res = load_resolutions(assets=["BTC"], timeframes=["5m"])         # 5,887 BTC 5m markets

# Add ws_s column (production anchor)
res = add_ws_s(res)
# res now has: slug, asset, timeframe, window_start_unix (slug suffix),
#              ws_s (= window_start_unix - window_s), outcome (Up/Down, chainlink-derived)
```

### Step 3: Compute signal (production-matching)

```python
end_us_btc, prices_btc = load_klines_asof("BTC", "binance-spot-ws", "1MIN")

def signal_for_row(row):
    ws_s = int(row.ws_s)
    p0 = asof_strict(end_us_btc, prices_btc, ws_s * 1_000_000)
    p2 = asof_strict(end_us_btc, prices_btc, (ws_s + 120) * 1_000_000)
    if not (np.isfinite(p0) and np.isfinite(p2) and p0 > 0):
        return np.nan, np.nan
    ret_2m = np.log(p2 / p0)
    return ret_2m, "Up" if ret_2m > 0 else "Down"

res[["ret_2m", "signal_dir"]] = res.apply(signal_for_row, axis=1, result_type="expand")
```

### Step 4: Gate (production fire rule = top decile per cell-day)

```python
res["day"] = res["ws_s"] // 86_400
gated = []
for (asset, tf), sub in res.groupby(["asset", "timeframe"]):
    sub = sub.sort_values("ws_s").reset_index(drop=True)
    sub["abs_ret"] = sub["ret_2m"].abs()
    for day, day_df in sub.groupby("day"):
        train = sub[(sub.day < day) & (sub.day >= day - 14)]
        if len(train) < 50:
            continue   # warmup
        thr = train.abs_ret.quantile(0.90)
        fires = day_df[day_df.abs_ret >= thr].copy()
        fires["thr_used"] = thr
        gated.append(fires)
gated = pd.concat(gated, ignore_index=True)
# `gated` is every market production would have fired on
```

### Step 5: Lookup entry book at ws+120 (production fire moment)

```python
tier1_btc = load_tier1_entries("btc")   # rows keyed by (slug, outcome)
# Each row has ask_price_0..24, ask_size_0..24, bid_price_0..24, bid_size_0..24
def entry_book(row):
    held = row.signal_dir
    book = tier1_btc[(tier1_btc.slug == row.slug) & (tier1_btc.outcome == held)]
    return book.iloc[0] if len(book) else None
```

### Step 6: Spread filter (production)

```python
SPREAD_FILTER = {"btc": 0.02, "eth": 0.02, "sol": 0.025}
def passes_spread(book, asset):
    return (book.ask_price_0 - book.bid_price_0) <= SPREAD_FILTER[asset]
```

### Step 7: Walk the book — fill at $25 notional

```python
ask_p = np.array([book[f"ask_price_{i}"] for i in range(25)])
ask_s = np.array([book[f"ask_size_{i}"]  for i in range(25)])
vwap_e, shares_e, usd_e, levels_hit, under = book_walk_fill(ask_p, ask_s, 25.0)
if under and usd_e < 25.0 * 0.5:
    # production skips: book too thin
    pass
```

### Step 8: Exit policy

```python
# HOLD (simplest, matches baseline)
def settle_hold(row, vwap_e, shares_e, usd_e):
    won = (row.signal_dir == row.outcome)
    if won:
        gross = shares_e * 1.0
        profit = gross - usd_e
        fee = profit * 0.02 if profit > 0 else 0.0
        return profit - fee
    return -usd_e
```

For HEDGE / SELL see `strategy_lab/meta_classifier/extended_backtest_with_robustness.py:simulate()` — the canonical implementation. Uses 10s bucket-book snapshots for exit monitoring.

### Step 9: Aggregate

```python
gated["pnl"] = gated.apply(lambda r: settle_hold(r, ...), axis=1)
print(f"n={len(gated)} hit={(gated.pnl>0).mean()*100:.1f}% "
      f"mean=${gated.pnl.mean():+.4f} total=${gated.pnl.sum():+.2f}")
```

### Step 10: Validate against production shadow

```python
shadow = pd.read_csv(ROOT / "data" / "v4" / "refresh_2026_05_12" / "vps3_trading_events_14d.csv")
# Filter to overlapping window + sleeve_id; compare per-slug PnL diff.
# Tooling: strategy_lab/meta_classifier/momo_shadow_vs_backtest.py
```

If per-slug PnL diff is > $0.10/tr on any slug, something is wrong — anchor, asof, spread filter, or fee. Reference: `MOMO_PHASE3_4_ANCHOR_LOOKAHEAD_FIXED_2026_05_09.md` (May 7 within $0.07/tr of production after fixing anchor + asof).

---

## Recent benchmark — full-universe momo on canonical (2026-05-16)

**Headline:** -$1.21/tr (n=2,909), 48.4% hit, HOLD across full 21d universe.

**HOLD per (version × asset × tf):**

| version | asset | tf | n | pnl_mean | hit% |
|---|---|---|---:|---:|---:|
| **v1** | **BTC** | **15m** | **97** | **+$2.37** | **55.7%** |
| **v1** | **SOL** | **5m** | **227** | **+$1.45** | **54.6%** |
| v1 | BTC | 5m | 593 | -$1.36 | 48.1% |
| v1 | ETH | 15m | 40 | -$6.61 | 37.5% |
| v1 | ETH | 5m | 331 | -$2.99 | 45.0% |
| v1 | SOL | 15m | 25 | -$3.50 | 44.0% |
| v2 | BTC | 15m | 136 | -$0.14 | 50.7% |
| v2 | BTC | 5m | 565 | -$1.27 | 48.1% |
| v2 | ETH | 15m | 75 | -$3.26 | 44.0% |
| v2 | ETH | 5m | 415 | -$0.60 | 49.9% |
| v2 | SOL | 15m | 70 | -$7.22 | 37.1% |
| v2 | SOL | 5m | 335 | -$1.42 | 48.7% |

**Walkforward:** every variant has negative `oos_pnl_total` across 18 trading days. Best: v1 SELL_3bp on BTC 15m with 6 of 18 days positive.

**Permutation (1000 sign-flip draws):** no cell achieves p<0.05. Best p≈0.08 on `v1 BTC 15m SELL_3bp / HEDGE_3bp / HYBRID_3bp` (n=97, observed +$278).

**Conclusion:** the q90 |ret_2m| gate on the 21d chainlink-resolved universe does NOT carry positive expectancy on Polymarket-CLOB walks at $25 notional. Strong shadow numbers from prior sessions are window effects on n=20-58.

Full output: `data/v4/canonical/_results/full_universe_2026_05_16/`
Source: `strategy_lab/reports/MOMO_FULL_UNIVERSE_2026_05_16.md`

---

## Open work / strategy ideas

### A. Deploy the two surviving cells; drop the rest
- `v1 sol_5m_momo_HOLD` (+$1.45/tr, n=227, hit 55%)
- `v1 btc_15m_momo_HYBRID_RevOrStop_SELL` (+$3.19/tr, n=97, hit 56%, p≈0.08)

### B. Spread filter sensitivity (never run)
Loosen from {BTC: 0.02, ETH: 0.02, SOL: 0.025} → {0.05, 0.05, 0.05}. Prior overlap analysis showed it would close ~$1.69/tr gap but won't flip sign. Worth running for completeness.

### C. v3 family dispatcher bug — NOT fixed
Sleeves `v3, v3_1, v3_2, v3_3, v4` emit byte-identical signals on BTC/ETH ~98% of the time despite having different config. **Spec is ready:** `strategy_lab/reports/TV_AGENT_V3_FAMILY_REVERIFICATION_2026_05_16.md` (today). Hand to TV agent.

### D. Sniper SOL direction inversion
`sol_5m_sniper` -$824 vs `sol_5m_sniper_INV` +$394 (237 trades each, mirror images). Investigate sniper signal code on VPS3 before disabling.

### E. Test if v2's anchors actually beat v1
v2 (`ws-360, ws-240` for 5m) loses worse than v1 across every cell. Either v2 has no edge over v1, or the gate is misaligned. Try v2-only universe with q95 gate.

### F. Trades data delta puller
Polymarket trades end 2026-05-06 (10 days stale). Add a trades-delta step to `migration_2026_05_12/local_pull.sh` step 7.

### G. Cross-venue cex alignment as a filter
`cex_alignment_*.py` engines exist but not yet stacked with momo. Test whether coinbase/kraken agreement gate improves win rate at the cost of fire rate.

### H. Hour-of-day / day-of-week effects
`volume_INV_NIGHT` fires 100% during night hours and is structurally a bleeder. Test whether inverting the FILTER (only-day version) is the real edge.

### I. Confluence revisit on canonical
The 2026-05-07 confluence work used `refresh_2026_05_06/`. Re-build FLOW/STRUCTURE/TRIGGER/GUARD on canonical, re-test SILVER on the 21d universe (much larger n than the original n=8).

### J. V5 derivatives gauntlet — ETH deploy candidate
`V5_GAUNTLET_VALIDATION.md` says v5 frontier ETH passes 6/8 gates. **TODO:** apply carry overlay (Tier F fix) and re-run final 2 gates; if pass, hand to TV agent for ETH 4h deploy.

---

## Known issues

1. **Polymarket trades data is STALE** (ends May 6, 10d ago). Strategy using trades → window Apr 22 - May 6 only.
2. **v3 family dispatcher bug** — see §C above.
3. **SPREAD_FILTER experiment never run** — see §B.
4. **`eth_5m_momo_v2_HOLD` has 24 `qty_compute_failed` events** in 7d — separate ticket.
5. **`sol_5m_sniper` inverted sign on SOL** — see §D.
6. **`refresh_2026_05_06/` (9.8 GB) still on disk** — canonical references its L25 cache for the early-window Apr 22 - May 6 baseline. **DO NOT delete** — would break `build.py --step orderbook` re-runs.
7. **Tier1 L25 server-side join (step 7 of local_pull.sh)** hung 25+ min on VPS3 last run — non-blocking but needs investigation.
8. **HL liquidations dir-label drift post-Feb 2026** — collector still filters to liquidations at insertion, but `dir` field is now HLP-vault perspective. `build_trigger.py` was fixed 2026-05-07 to accept all rows. For directional analysis (longs liquidated vs shorts), see translation table in `strategy_lab/confluence/trigger/liq_magnet.py`.

---

## VPS / data access reference

```bash
# VPS2 (Contabo IPv6) — markets catalog, cex klines, hl_liquidations
ssh -i ~/.ssh/vps2_ed25519 "root@[2605:a140:2323:6975::1]"

# VPS3 — orderbook 11GB, trades 3.2GB, binance 2GB, oracle 593MB, trading.events
ssh -i ~/.ssh/vps3_ed25519 root@185.190.143.7
```

- VPS3 production controller: `/opt/tradingvenue/backend/app/controllers/polymarket_updown.py`
- VPS3 paper executor: `/opt/tradingvenue/backend/app/venues/polymarket/paper.py`
- VPS3 .env: `/etc/tradingvenue/.env`
- VPS3 storedata DB: `psql -d storedata`

### Pull fresh data into canonical

```bash
# Full refresh (mirror VPS3 + VPS2)
bash migration_2026_05_12/local_pull.sh

# L25 history (separate pull)
bash migration_2026_05_12/pull_l25_vps3.sh

# Rebuild canonical from raw refreshes
py -3 -X utf8 data/v4/canonical/build.py
py -3 -X utf8 data/v4/canonical/build.py --step orderbook   # one step only
```

---

## Recommended starting prompt for next session

```
Read NEXT_SESSION_START_HERE.md first.

Canonical is fresh as of 2026-05-16 (Apr 24 → May 15 UTC, 23,553 chainlink-resolved
markets). Use `from data.v4.canonical.load import *` for all data loads.

Production convention: ws_s = slug_suffix - window_s (PREVIOUS slot). Never use
the slug suffix as ws_s directly — that's a 25-40pp hit-rate inflation bug.

Full-universe momo backtest shows the strategy is unprofitable except on 2 cells
(v1 SOL 5m HOLD, v1 BTC 15m HYBRID_RevOrStop_SELL). Pursue new strategies on the
canonical universe; small-n shadow positives don't survive.

[Your task / strategy idea here]
```

If running backtests, copy Step 0 prelude from §"How to run a backtest that EXACTLY matches a live market".

---

## Recent reports (this session + relevant earlier)

- `strategy_lab/reports/MOMO_FULL_UNIVERSE_2026_05_16.md` *(today — definitive full-universe verdict)*
- `strategy_lab/reports/TV_AGENT_V3_FAMILY_REVERIFICATION_2026_05_16.md` *(today — v3 family spec for TV agent)*
- `strategy_lab/reports/DATA_INVENTORY_2026_05_15.md` *(May 15 inventory baseline)*
- `strategy_lab/reports/SESSION_HANDOFF_2026_05_10_WS_S_CONVENTION.md` *(THE ws_s convention reference)*
- `strategy_lab/reports/MOMO_PHASE3_4_ANCHOR_LOOKAHEAD_FIXED_2026_05_09.md`
- `strategy_lab/reports/MOMO_CHAINLINK_ONLY_2026_05_09.md`
- `strategy_lab/reports/ALL_SHADOW_SLEEVES_TABLE_2026_05_11.md`
- `strategy_lab/reports/ETH_5M_V3_V4_DIAGNOSIS_2026_05_11.md`
- `strategy_lab/reports/SILVER_VALIDATION_FINAL_2026_05_07.md` *(confluence verdict — paper-only candidate)*
- `strategy_lab/reports/CYCLOPS_UPDATE_COMPARISON_2026_05_07.md`
- `strategy_lab/reports/TV_AGENT_SPEC_CONFLUENCE_SILVER_V1.md`
- `strategy_lab/reports/derivatives_zscore/V5_GAUNTLET_VALIDATION.md`
- `strategy_lab/reports/CLEANUP_EXECUTION_2026_05_07.md`

---

*End of context document. Generated 2026-05-16.*
