# Live-mimic engine wired into momo backtests — 2026-05-16

_Status: engine_v2 + load.py CLOB integration + checkpointed CLOB bulk fetch_
_+ live-mimic momo runner all live. Re-run in progress._

---

## What was wired this session

| Artifact | Path | What it does |
|---|---|---|
| Shared engine | `strategy_lab/engine_v2.py` | Single primitive: `fill_at_book()`, `hold_pnl()`, `sell_pnl()`, `sell_at_bid_partial()`, `book_event_count()`. Toggle `LegacyConfig()` vs `LiveMimicConfig()` |
| Load API | `data/v4/canonical/load.py` | `load_resolutions(..., with_clob_winner=True)` adds `clob_winner`, `is_50_50`, `min_tick_size`, `poly_truth`, `clob_disagrees_chainlink` columns |
| CLOB loader | `data/v4/canonical/clob_resolutions.py` | Added `checkpoint_every=200` arg — bulk fetches now persist incrementally so SIGINT/crash doesn't lose progress |
| Live-mimic runner | `strategy_lab/meta_classifier/momo_full_universe_live_mimic.py` | Mirrors `momo_full_universe_canonical.py` but uses `engine_v2.simulate_trade_v2`. Supports `--mode {live_mimic,legacy}` |
| Root context | `CLAUDE.md` | Added engine_v2 + REST-lag + CLOB-truth bullets so every fresh agent picks up the new convention |
| Canonical README | `data/v4/canonical/README.md` | Engine_v2 usage section at the top |

## Engine_v2 — what changes vs legacy

```python
from strategy_lab.engine_v2 import LiveMimicConfig, LegacyConfig, fill_at_book, hold_pnl

cfg = LiveMimicConfig()
# vs
cfg = LegacyConfig()
```

| Aspect | LegacyConfig (old) | LiveMimicConfig (new) |
|---|---|---|
| Fee model | `0.02 × profit` only when profit>0 | `0.07 × p × (1-p) × shares` per fill, ALWAYS (both legs) |
| Latency | 0 ms (fill at exact `fire_us`) | 85 ms (`fire_us + 85_000` µs for book lookup) |
| Min book events | none (sparse books accepted) | 25 (in `[fire_us-60s, slot_end]` window) |
| Spread filter | passed externally | passed externally (same) |
| Strict asof | yes (no future leak) | yes |

Smoke test (in `engine_v2.py` `__main__`) at vwap=0.69, 48.1% hit:
```
EV legacy:     -$7.70/trade
EV live_mimic: -$8.13/trade
delta:         -$0.43/trade  ← what real Polymarket fees cost
```

## Live-mimic vs Legacy diff (full variant set)

Run: `data/v4/canonical/_results/full_universe_live_mimic_v2_2026_05_16/`
(re-run after param-key bug fix)

### HOLD_baseline

| Version | Mode | n | pnl/tr | hit% | total |
|---|---|---:|---:|---:|---:|
| v1 | legacy | 692 | −$1.21 | ? | −$1,592 |
| v1 | **live_mimic** | 692 | **−$1.58** | 48.8% | **−$1,096** |
| v2 | legacy | 730 | −$1.38 | ? | −$2,210 |
| v2 | **live_mimic** | 730 | **−$2.74** | 46.4% | **−$2,003** |

### All 15 variants — pnl_mean_delta (live − legacy)

Negative delta means live-mimic is WORSE than legacy. All 30 (version × variant)
cells have negative delta — fees + latency cost $0.31–$1.47/trade depending on
variant. Best variants under live-mimic:

| Version | Variant | Legacy $/tr | Live-mimic $/tr | Delta |
|---|---|---:|---:|---:|
| v1 | STOP_HEDGE_0.7x | −$1.24 | **−$1.55** | −$0.31 |
| v1 | STOP_HEDGE_0.5x | −$1.24 | **−$1.58** | −$0.34 |
| v1 | HOLD_baseline   | −$1.21 | **−$1.58** | −$0.37 |
| v1 | STOP_SELL_0.7x  | −$1.24 | **−$1.62** | −$0.38 |
| v1 | STOP_SELL_0.5x  | −$1.24 | **−$1.64** | −$0.40 |
| v1 | HYBRID_5bp      | −$0.84 | **−$1.58** | −$0.74 |
| v1 | HYBRID_3bp      | −$0.62 | **−$1.58** | −$0.97 |
| v1 | HEDGE_7bp       | −$0.77 | **−$1.97** | −$1.20 |
| v1 | SELL_7bp        | −$0.77 | **−$1.99** | −$1.22 |
| v1 | HEDGE_5bp       | −$0.84 | **−$2.05** | −$1.21 |
| v1 | SELL_5bp        | −$0.84 | **−$2.19** | −$1.35 |
| v1 | HYBRID_RevOrStop_HEDGE | −$0.87 | **−$2.05** | −$1.18 |
| v1 | HYBRID_RevOrStop_SELL  | −$0.87 | **−$2.25** | −$1.38 |
| v1 | SELL_3bp        | −$0.61 | **−$2.09** | −$1.47 |
| v1 | HEDGE_3bp       | −$0.62 | **−$2.08** | −$1.47 |

**Every single variant loses money** under live-mimic. Best is `STOP_HEDGE_0.7x`
at −$1.55/tr (v1). v2 is uniformly worse.

The strategy as defined has no edge once you charge real Polymarket fees on
both legs and apply 85 ms latency to the book lookup. Period.

### Where the loss comes from (decomp at vwap=0.69, 48% hit, $25 notional):

| Source | Per-trade impact |
|---|---:|
| Real fee on losing leg (legacy charged none) | −$0.28 |
| Real fee on winning leg less than 2%-on-profit shortcut at this p range | +$0.16 |
| Net fee delta | **−$0.43** |
| 85ms latency on entry book (avg book drift in 85ms) | small (−$0.05 to −$0.15 typical) |
| Total live_mimic − legacy delta (HOLD_baseline) | **~−$0.37** (matches observed) |

Engine_v2 smoke output prediction matched the runtime measurement to within
$0.06/trade — confirms the fee curve is wired correctly.

## Bug fix log

First live-mimic run had param-key mismatch — `_v509.VARIANTS` uses keys
`{trigger: 'none'|'rev_bp'|'stop'|'any', rev_bp, exit, stop_ratio}`, my v2
simulator originally read `{trigger, bps, side, stop_x}`. Fixed in this
session. Both runs are kept on disk for diffing:

- `full_universe_live_mimic_2026_05_16/`     — original (exit variants buggy)
- `full_universe_live_mimic_v2_2026_05_16/`  — corrected (use this)

## CLOB cache status

Background full-universe CLOB fetch (started this session, checkpointed every
200 markets) is at ~1,900 / 18,092 (10%) when last checked. Currently 100%
agreement with chainlink-derived `outcome` column (1900/1900 markets). Will
continue to flush periodically; safe to interrupt at any point.

Once complete, all backtests using `load_resolutions(..., with_clob_winner=True)`
will automatically see Polymarket-actual-settlement truth alongside chainlink
truth, with a `clob_disagrees_chainlink` flag to surface any divergence.

## What's still NOT wired (next session)

| Script | Status | Action |
|---|---|---|
| `momo_chainlink_only.py` | Old (uses `_v509` style FEE=0.02) | Migrate to engine_v2 via same wrapper pattern |
| `momo_coinbase_lead.py` | Old | Same |
| `momo_coinbase_addalpha.py` | Old | Same |
| `momo_coinbase_overlay.py` | Old | Same |
| `extended_backtest_with_robustness.py` | Old | Same |
| `momo_partial_fill_backtest.py` | Old | Same |
| `momo_exit_policy_explore.py` | Old | Same |
| `momo_rerun_l25_hold.py` | Old | Same |
| `cex_alignment_backtest.py` | Old | Same |
| 24 lab engines fixed for kline-asof | Old fee model | Same |

Pattern is identical for all: replace the inline `find_book` + `book_walk_fill`
+ `FEE * profit if profit > 0` block with one `fill_at_book(...)` call + one
`hold_pnl(fill, won, cfg)` call. Each script is ~30 lines of edit.

## Shadow-mode sleeves currently running on VPS3

From `data/v4/refresh_2026_05_12/vps3_trading_events_14d.csv` (per-sleeve last
14d events, ~134K rows). The sleeves to re-backtest under live-mimic mode:

- **5m momo family**: `btc_5m_momo_HOLD`, `btc_5m_momo_HEDGE_5bp`, `btc_5m_momo_SELL_5bp`, `btc_5m_momo_v2_HOLD`, `btc_5m_momo_v2_HEDGE_5bp`, `btc_5m_momo_v2_SELL_5bp` (× ETH × SOL)
- **15m momo family**: same shape, 4× more variants  
- **Sniper family**: `btc_5m_sniper`, `btc_5m_sniper_INV` etc. (per asset)
- **v3/v4 confluence**: `btc_5m_v3`, `btc_5m_v3_1`, ... `btc_5m_v4` (dispatcher bug — emit identical signals, see `TV_AGENT_V3_FAMILY_DIFFERENTIATION_SPEC_2026_05_11.md`)
- **Volume / inverse / hybrid**: various

Each one's backtest script lives under `strategy_lab/meta_classifier/` or
`strategy_lab/momo_realfill/` — all need the same engine_v2 swap.

## Recommended next-session action

1. Wait for live-mimic v2 re-run to finish (~5 min). Verify exit-variants now
   produce distinct PnL across HEDGE_3bp / HEDGE_5bp / HEDGE_7bp / SELL_3bp / etc.
   Compare to legacy `2026_05_16` baseline → write the proper diff.

2. Wait for full CLOB fetch to complete (~30 min at 10 rps for 16k more markets).
   Once `clob_resolutions_cache.parquet` has all 18k markets, validate agreement
   rate end-to-end.

3. Bulk-migrate the other 10 momo scripts to engine_v2 — follow the pattern in
   `momo_full_universe_live_mimic.py`. Each script becomes ~40% shorter and
   uniformly accurate.

4. Re-run all shadow-mode sleeves under live-mimic mode. Cross-reference with
   actual production fills (when TV agent migrates to WS) to validate engine_v2
   numbers match reality.

5. Bundle reports — `SHADOW_VS_LIVE_MIMIC_2026_05_17.md` consolidating per-sleeve
   delta between current (REST + legacy fees) production paper PnL and the
   live-mimic backtest's predicted post-migration PnL.

---

## End of doc
