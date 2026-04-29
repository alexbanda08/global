# Session Handoff — 2026-04-28

**Read this first in the next session. This supersedes SESSION_HANDOFF_2026_04_27.md.**

---

## TL;DR — Where we are

✅ **Polymarket strategy is live with TV.** Phase 18 implementation in progress (TV agent owns it).
✅ **9 candidate strategies tested in last session.** 4 validated, 5 dead. Full audit at `session/SESSION_SUMMARY_2026_04_27_strategies.md`.
✅ **Reports folder reorganized.** New layout: `polymarket/01_deployable | 02_analysis | 03_no_edge | dashboards | context_brief`.
✅ **Context docs updated.** This file + `polymarket/context_brief/POLYMARKET_CONTEXT_BRIEF.md` + `polymarket/context_brief/POLYMARKET_NEXT_EXPERIMENTS.md`.

🎯 **Next session focus:** Analyze the **AlphaPurify** repo (https://github.com/eliasswu/AlphaPurify) and compare it to our backtest engines (both Polymarket UpDown and Hyperliquid futures). Identify anything worth stealing. **Spec at `polymarket/context_brief/NEXT_TASK_ALPHAPURIFY_ANALYSIS.md`.**

---

## What's locked (don't redo)

| Decision | Value | Source |
|---|---|---|
| Primary signal | `sig_ret5m_q10` on 5m, `sig_ret5m_q20` on 15m | Forward-walk holdout validated 2026-04-27 |
| Exit rule | hedge-hold rev_bp=5 (always taker on hedge) | Locked baseline + maker-hedge tested negative |
| Entry — 5m | taker (market buy at ask) | Maker entry on 5m fails holdout |
| Entry — 15m | maker hybrid (limit at bid+1¢, 30s wait, fallback to taker) | Holdout +2.42pp lift on ETH/SOL/ALL |
| Cross-asset filter | BTC-confirmation on 5m ETH/SOL only | E6 forward-walk validated |
| Stake floor | $1/slot during pilot | Polymarket fractional shares supported |
| Redemption | `redeemPositions([1,2])` after resolution | TV implementing |
| Out of scope | mergePositions, NegRiskAdapter, ERC-1155 approvals, time-of-day filter | Hedge-hold supersedes; TOD overfit risk |

If a new strategy beats current matrix on holdout, fine to extend. Otherwise leave alone.

---

## Current TV deployment status

TV agent is mid-implementation. Last reported:
- Implementing 5-wave plan (18-01 strategy fill → 18-06 7-day live audit)
- Hit blocker on `condition_id` not populated for near-future markets in Storedata
- Resolution: fetch `condition_id` from Polymarket Gamma API live (don't depend on Storedata writer)

Once shadow validates:
- v1.1: enable maker-entry flag on 15m
- v1.2: enable cross-asset filter on 5m ETH/SOL
- v1.3: pilot spread filter on 5m × BTC (currently borderline holdout)

---

## Folder map (after 2026-04-28 reorganization)

```
strategy_lab/reports/
├── _README.md                          ← master index
├── _STRATEGY_FILTERS_EXPLAINED.md      ← plain-English filter reference
├── polymarket/
│   ├── _README.md                      ← polymarket folder index
│   ├── 01_deployable/                  ← TV-ready specs
│   │   ├── TV_STRATEGY_IMPLEMENTATION_GUIDE.md  ← PRIMARY SPEC for TV
│   │   ├── TV_SHADOW_MODE_READINESS.md
│   │   ├── POLYMARKET_E6_VERDICT.md
│   │   └── POLYMARKET_MAKER_ENTRY_VERDICT.md
│   ├── 02_analysis/                    ← 28 files: grids, sweeps, raw results
│   ├── 03_no_edge/                     ← 7 files: tested negative, DON'T REVISIT
│   ├── dashboards/                     ← 2 HTML files
│   └── context_brief/                  ← 4 files: project state + next-experiments queue
├── session/
│   ├── SESSION_HANDOFF_2026_04_28.md   ← THIS FILE
│   ├── SESSION_HANDOFF_2026_04_27.md   ← previous session (mostly superseded)
│   ├── SESSION_SUMMARY_2026_04_27_strategies.md  ← 9-strategy audit
│   ├── SESSION_CONTEXT.md
│   └── CONTEXT_SNAPSHOT_2026_04_22.md
├── archive_kronos/                     ← 10 files: failed model, ignore
└── archive_hyperliquid/                ← 37 files: older project (V8-V37 era), reference only
```

---

## Data available

### On VPS (Postgres @ `127.0.0.1:5432`, db=`storedata`, user=`tradingvenue_ro`)
- `binance_klines_v2` — 1MIN BTC/ETH/SOL spot, real-time
- `markets` — Polymarket markets with `slug`, `condition_id` (slow writer, see TV blocker note), `yes_token_id`, `no_token_id`, `resolved_at`, `outcome`
- `orderbook_snapshots_v2` — TimescaleDB hypertable, 25 bid + 25 ask levels per snapshot per (slug, outcome). Indexed by `(slug, timestamp_us DESC)`. ~13.58M snapshots. **Always slug-scope queries to avoid table-scan lock incidents.**
- `market_resolutions_v2` — resolved markets with outcomes
- `binance_funding_rate_v2` — Mar 2026 only; Apr backfill expected ~May 1

### Locally extracted (in `data/polymarket/` and `data/binance/`)
- `{btc,eth,sol}_features_v3.csv` — 5,742 markets × 25 features (incl. `entry_yes_ask`, `ret_5m`, `smart_minus_retail`)
- `{btc,eth,sol}_trajectories_v3.csv` — 10s buckets × bid/ask first/last/min/max
- `{btc,eth,sol}_book_depth_v3.csv` — 466k rows × 47 cols, top-10 levels per (slug, bucket, outcome). NEW this session.
- `{btc,eth,sol}_klines_window.csv` — Binance 1MIN bars for the data window
- `{btc,eth,sol}_metrics_window.csv` — OI / L/S / taker flow

### Key derived knowledge

- `sig_ret5m` p-value < 1e-6 (Pearson r ≈ +0.123 on 5m universe)
- `q10` quantile holds out-of-sample on 5m (+7pp ROI lift over q20)
- `q20` quantile is in-sample optimal on 15m (locked baseline)
- Cross-asset: BTC ret at lag=0 confirms ETH/SOL on 5m (+5pp lift); fails on 15m
- Maker entry: 25% fill rate at bid+1¢/30s on 15m; 5m fills are noise
- Hedge maker: 3-4% fill rate at rev_bp trigger (directional flow); negative-EV
- TP at any target: capping winners destroys asymmetric upside
- Vol/volume regime filters: q10 already encodes regime info; double-counting fails

---

## Active code (use these as the foundation)

In `strategy_lab/`:
- `polymarket_signal_grid_v2.py` — primary backtest engine (signal + hedge-hold simulator)
- `polymarket_forward_walk_v2.py` — chronological 80/20 forward-walk framework
- `polymarket_forward_walk_q10.py` — q10-specific forward-walk
- `polymarket_forward_walk_maker.py` — maker-entry forward-walk
- `polymarket_forward_walk_spread.py` — spread-filter forward-walk
- `polymarket_extract_*.sql` — SQL extractors (markets_v3, trajectories_v3, xasset, book_depth, features)
- `polymarket_revbp_floor_sweep.py` — fine rev_bp sweep
- `polymarket_signal_grid_realfills.py` — book-walking fill simulator (E1)
- `polymarket_realfills_validate.py` — apples-to-apples baseline_v2 vs realistic
- `polymarket_realfills_dashboard.py` — dashboard builder
- `polymarket_alt_signal_grid.py` — 9 alt-signal cross-asset grid
- `polymarket_strategy_stacks.py` — stack combinations (q × time)
- `polymarket_time_of_day.py` — UTC-hour stratification
- `polymarket_robustness_check.py` — 4 robustness tests for small samples
- `polymarket_alt_dashboard.py` — alt-strategies dashboard
- `polymarket_maker_entry.py` — maker-entry simulator (16 variants)
- `polymarket_maker_hedge.py` — maker-hedge simulator (8 variants)
- `polymarket_take_profit.py` — TP simulator (10 targets × 2 modes)
- `polymarket_side_asymmetry.py` — UP-vs-DOWN test
- `polymarket_cross_asset_leader.py` — cross-asset signal grid (E6)
- `polymarket_cross_asset_validate.py` — E6 forward-walk
- `polymarket_volregime_revbp.py` — adaptive rev_bp test (E7)
- `polymarket_volume_filter.py` — Binance volume filter (E3)
- `polymarket_microstructure_filter.py` — spread/depth filter (E4)
- `book_walk.py` — orderbook-walking fill function

## Files to ignore (explicitly: don't waste time)

- `polymarket_baselines_grid.py` — pre-signal era, all baselines failed
- `polymarket_signal_grid.py` — superseded by `_v2`
- `polymarket_forward_walk.py` — superseded by `_v2`
- `polymarket_revbp_sweep.py` — superseded by `_revbp_floor_sweep.py`
- `polymarket_extract_markets.sql`, `_v2.sql` — superseded by `_v3` and `_xasset.sql`
- `polymarket_extract_trajectories.sql` — superseded by `_xasset.sql` and `_v3.sql`
- `kronos_*` files — Kronos failed OOD; do not retrain
- The 7 indexed GitHub bot repos — already mined for ideas; nothing else there

## VPS access

```bash
ssh -i "$HOME/.ssh/vps2_ed25519" -6 root@2605:a140:2323:6975::1
# DB env: /etc/storedata/collector.env
# OR via peer auth: sudo -u postgres psql -d storedata
```

**Important:** large `EXISTS (SELECT 1 FROM orderbook_snapshots_v2 ...)` queries can lock the table for tens of minutes. Always use bounded queries (filter by `slug` or short timestamp range, e.g. `slug = '...' AND timestamp_us BETWEEN x AND y`). If a query hangs, kill it with `pg_cancel_backend(pid)`.

---

## Next task — AlphaPurify analysis

Full spec: **`polymarket/context_brief/NEXT_TASK_ALPHAPURIFY_ANALYSIS.md`**

TL;DR — clone https://github.com/eliasswu/AlphaPurify, read the engine, identify:
1. Anything we should steal for the **Polymarket UpDown** backtest engine (in this session's strategy_lab/)
2. Anything we should steal for the **Hyperliquid futures** backtest engine (separate project, lives on VPS)

Output: `reports/polymarket/02_analysis/ALPHAPURIFY_COMPARISON.md` — feature-by-feature comparison + ranked theft list.

---

**End of handoff. Start with `polymarket/context_brief/NEXT_TASK_ALPHAPURIFY_ANALYSIS.md` for the next session's task.**
