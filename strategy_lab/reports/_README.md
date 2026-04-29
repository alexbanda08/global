# strategy_lab/reports — Master Index

**Last reorganized: 2026-04-28.** Read this file first to navigate.

## Where do I start?

| If you want to... | Go to |
|---|---|
| Resume the session / understand current state | [`session/SESSION_HANDOFF_2026_04_28.md`](session/SESSION_HANDOFF_2026_04_28.md) |
| Understand WHAT each strategy filter does (in plain English) | [`_STRATEGY_FILTERS_EXPLAINED.md`](_STRATEGY_FILTERS_EXPLAINED.md) |
| Hand a doc to TV agent for live deployment | [`polymarket/01_deployable/TV_STRATEGY_IMPLEMENTATION_GUIDE.md`](polymarket/01_deployable/TV_STRATEGY_IMPLEMENTATION_GUIDE.md) |
| See the strategy hunt session results (9 strategies tested, 4 validated) | [`session/SESSION_SUMMARY_2026_04_27_strategies.md`](session/SESSION_SUMMARY_2026_04_27_strategies.md) |
| Run the next experiment | [`polymarket/context_brief/POLYMARKET_NEXT_EXPERIMENTS.md`](polymarket/context_brief/POLYMARKET_NEXT_EXPERIMENTS.md) |

## Folder map

```
reports/
├── _README.md                          ← you are here
├── _STRATEGY_FILTERS_EXPLAINED.md      ← plain-English filter reference
│
├── polymarket/                         ← active project (Polymarket UpDown 5m/15m)
│   ├── 01_deployable/                  ← ship-ready docs (TV guide + verdicts)
│   ├── 02_analysis/                    ← grids, sweeps, intermediate experiments
│   ├── 03_no_edge/                     ← TESTED NEGATIVE — don't revisit
│   ├── dashboards/                     ← interactive HTML reports
│   └── context_brief/                  ← project state + next experiments queue
│
├── session/                            ← handoff + context snapshots
│
├── archive_kronos/                     ← failed Kronos model attempts (2026-04-22/23)
│
└── archive_hyperliquid/                ← older Hyperliquid perps project (V8-V37 era)
```

## File counts

| Folder | Files | Purpose |
|---|---|---|
| `polymarket/01_deployable/` | 4 | TV-ready specs |
| `polymarket/02_analysis/` | 28 | grids, sweeps, validated experiment results |
| `polymarket/03_no_edge/` | 7 | tested negative, kept for reference |
| `polymarket/dashboards/` | 2 | HTML interactive reports |
| `polymarket/context_brief/` | 4 | current-state docs + next-experiments queue |
| `session/` | 4 | handoffs + snapshots |
| `archive_kronos/` | 10 | failed Kronos model |
| `archive_hyperliquid/` | 37 | older Hyperliquid project (V8-V37) |
| **Total** | **96** | + this README + filters explained = 98 |

## Project status (2026-04-28)

**Active:** Polymarket UpDown 5m + 15m strategy.

**Validated for live deploy** (handed to TV agent):
- `sig_ret5m_q10` on 5m markets (top 10% of |ret_5m|, taker entry)
- `sig_ret5m_q20` on 15m markets (top 20% of |ret_5m|, maker-entry hybrid)
- Cross-asset BTC-confirmation filter on 5m ETH/SOL (require BTC q10 agree direction)
- Hedge-hold exit at rev_bp=5 (universal)

**Currently running:** TV implementing shadow mode (Phase 18-01 → 18-06).

**Out of scope:**
- Hyperliquid perps work (separate project, see `archive_hyperliquid/`)
- Kronos retrain (failed OOD, abandoned)

See [`session/SESSION_HANDOFF_2026_04_28.md`](session/SESSION_HANDOFF_2026_04_28.md) for full state.
