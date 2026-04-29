# strategy_lab/reports/polymarket — Index

Polymarket UpDown 5m/15m project. Subfolder layout:

## `01_deployable/` — ship-ready

Hand these to TV agent or a fresh-session Claude for production work.

| File | What |
|---|---|
| `TV_STRATEGY_IMPLEMENTATION_GUIDE.md` | **Primary spec** — full TV implementation (signal + entry + exit + redemption) |
| `TV_SHADOW_MODE_READINESS.md` | Shadow-mode readiness checklist for go-live |
| `POLYMARKET_E6_VERDICT.md` | Cross-asset BTC-confirmation filter (5m ETH/SOL only) — secondary candidate |
| `POLYMARKET_MAKER_ENTRY_VERDICT.md` | Maker-entry hybrid (15m only, behind feature flag) — secondary candidate |

## `02_analysis/` — grids, sweeps, raw experiment results

The full audit trail of validated strategies. Use these to verify the numbers in `01_deployable/`.

| Theme | Files |
|---|---|
| Forward-walk validation | `POLYMARKET_FORWARD_WALK_*.md` (Q10, V2, MAKER, SPREAD) |
| Signal grids | `POLYMARKET_SIGNAL_GRID*.md`, `POLYMARKET_ALT_SIGNAL_GRID.md` |
| rev_bp sweeps | `POLYMARKET_REVBP_FLOOR_SWEEP.md`, `POLYMARKET_REVBP_SWEEP.md` |
| Realistic fills | `POLYMARKET_REALFILLS_HAIRCUT.md` |
| Microstructure | `POLYMARKET_MICROSTRUCTURE_FILTER.md` (borderline, 4/8 holdout) |
| Time-of-day | `POLYMARKET_TIME_OF_DAY.md`, `POLYMARKET_STRATEGY_STACKS.md`, `POLYMARKET_ROBUSTNESS_CHECK.md` |
| Cross-asset | `POLYMARKET_CROSS_ASSET_LEADER.md`, `POLYMARKET_CROSS_ASSET_VALIDATE.md` |
| Maker entry | `POLYMARKET_MAKER_ENTRY.md` (full grid before verdict was extracted) |
| Univariate | `POLYMARKET_FEATURES_UNIVARIATE.md` |
| Backtest history | `POLYMARKET_BACKTEST_*.md`, `POLYMARKET_BASELINES_GRID.md`, `POLYMARKET_FULL_STATS.md` |
| Strategy hunt logs | `STRATEGY_HUNT_*_2026_04_27.md` |

## `03_no_edge/` — tested NEGATIVE — DON'T REVISIT

These strategies were tested and **showed no edge** or **made things worse**. Documented here for reference so we don't redo them.

| File | What was tested | Why it failed |
|---|---|---|
| `POLYMARKET_TAKE_PROFIT.md` + `_VERDICT.md` | TP at 5-150% targets | Polymarket binary pays $1; capping winners removes asymmetric upside |
| `POLYMARKET_MAKER_HEDGE.md` + `_VERDICT.md` | Hedge-side as limit order | rev_bp triggers in directional flow; hedge maker fill rate 3-4%, costs +1¢/hedge |
| `POLYMARKET_SIDE_ASYMMETRY.md` | UP-vs-DOWN bias (per JBecker paper) | No bias on mid-priced (30-70¢) UpDown markets |
| `POLYMARKET_VOLREGIME_REVBP.md` | Adapt rev_bp by current vol | q10 already selects for vol regime; double-counting |
| `POLYMARKET_VOLUME_FILTER.md` | Skip low-volume markets | q10's \|ret_5m\| selection already encodes volume |

## `dashboards/` — HTML reports

Open in browser. Self-contained (data embedded).

| File | What |
|---|---|
| `POLYMARKET_REALFILLS_DASHBOARD.html` | E1 capacity ladder + per-trade explorer (3,751 trades) |
| `POLYMARKET_ALT_STRATEGIES_DASHBOARD.html` | Alt-signal grid + time-of-day heatmap + stacks comparison |

## `context_brief/` — project state + next-experiments queue

| File | What |
|---|---|
| `POLYMARKET_CONTEXT_BRIEF.md` | Project bootstrap doc (history + how markets work) |
| `POLYMARKET_NEXT_EXPERIMENTS.md` | Queue of unstarted experiments (now also includes AlphaPurify analysis task) |
| `VPS_DATA_INVENTORY.md` | What's in the VPS Postgres database |
| `building_cyclops_style_bot.md` | Reference doc — CYCLOPS-style bot architecture |
