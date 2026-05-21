# Multi-Layer Confluence System — Build & Test Plan

**Date:** 2026-05-07
**Replaces:** §6 of `NEXT_SESSION_START_HERE.md` (high-level sketch)
**Source spec:** `strategy_lab/reports/TRADINGVENUE_VS_CYCLOPS_2026_05_06.md`
**Prereqs cleared:** momo 5m fix landed, hedge bug fixed, dynamic stake cap deployed, lookahead asof bug fixed

---

## Goal

Ship `confluence_v1` sleeve to TV agent that beats current momo 15m by ≥30% mean $/trade with equal-or-tighter drawdown, validated through 3 audit gates (signal alpha, realfill alpha, production replay parity).

## Non-goals

- Pattern memory (240-segment bank) — DEFER, low value on 5m binary
- Multi-exchange OB aggregation — DEFER, geoblock + thin marginal info
- HL perps integration — keep Polymarket UpDown only for v1

---

## Success criteria (falsifiable, must hit before TV agent ship)

| Gate | Metric | Bar | If fail |
|---|---|---|---|
| **G1 FLOW alpha** | FLOW-only backtest mean $/trade vs random | p < 0.05 permutation, mean ≥ $+2/trade | Abandon or rework features |
| **G2 GUARD lift** | Each guard filter: $/trade lift on filtered subset | ≥ $+1/trade incremental | Drop that guard |
| **G3 Tier separation** | GOLD vs BRONZE win-rate spread | ≥ 8pp on shadow universe | Re-tune thresholds |
| **G4 Realfill alpha** | confluence_v1 realfill vs momo realfill same trades | ≥ +30% mean $/trade | Block ship |
| **G5 Production replay parity** | Backtest vs shadow same-trade comparison | dir_match ≥ 95%, $-diff < $1/trade | Block ship |

---

## Engines to reuse (DO NOT rebuild)

| Engine | Path | Use for |
|---|---|---|
| Backtest core (strict asof) | `strategy_lab/meta_classifier/extended_backtest_with_robustness.py` | Add confluence as new sleeve mode `confluence_v1` |
| Permutation test | `strategy_lab/meta_classifier/permutation_strict.py` | Statistical validity gate G1 |
| Production replay | `strategy_lab/meta_classifier/v3_production_replay.py` | Pattern for confluence replay harness |
| Shadow vs backtest audit | `strategy_lab/meta_classifier/momo_shadow_vs_backtest.py` | Pattern for G5 parity gate |
| L25 realfill | `strategy_lab/momo_realfill/validate_with_real_book.py` | G4 execution-realistic backtest |
| Same-trade matcher | `strategy_lab/momo_realfill/match_shadow_strict.py` | G4/G5 slug-by-slug comparison |
| 3-way comparator | `strategy_lab/momo_realfill/compare_3way.py` | Sanity check confluence vs momo vs shadow |
| Anti-edge / inversion | `strategy_lab/meta_classifier/anti_edge_analyzer.py` | Validates smart counter-trend hypothesis |

## Data inventory (already pulled, no new collection)

| Dataset | Path | Size | Window |
|---|---|---|---|
| L25 orderbook parquet | `data/v4/refresh_2026_05_06/cache/{btc,eth,sol}_orderbook_L25.parquet` | 4.3 GB | Apr-May 2026 |
| Trades v2 parquet | `data/v4/refresh_2026_05_06/cache/{btc,eth,sol}_trades.parquet` | small | same |
| HL liquidations | `data/v4/refresh_2026_05_06/hl_liquidations_btc_eth_sol.csv` | 245 MB | 1.98M rows |
| Binance klines | `data/v4/refresh_2026_05_06/binance_klines_full.csv` | refreshed | for STRUCTURE BTC trend |
| Markets + resolutions | `data/v4/refresh_2026_05_06/markets_full.csv`, `market_resolutions_full.csv` | refreshed | universe |
| Shadow trades | `data/v4/shadow_trades_2026_05_06/momo_resolutions_fresh.csv` | 299 fires | live audit |
| Shadow signal fills | `data/v4/shadow_trades_2026_05_06/momo_signal_fills.csv` | 235 events | telemetry |

Top-up pulls only if window extends past 2026-05-06. Live shadow data refreshes daily via existing scripts in `NEXT_SESSION_START_HERE.md` Quick start.

---

## Build phases

### Phase 0 — Skeleton + integration points (0.5 day)

**Deliverables:**
- `strategy_lab/confluence/__init__.py`
- `strategy_lab/confluence/schema.py` — feature schema (per slug × 10s bucket dataframe contract)
- `strategy_lab/confluence/aux_inject.py` — adapter that adds `aux["flow_*"]`, `aux["struct_*"]`, `aux["trig_*"]`, `aux["guard_*"]` to existing backtest aux dict
- `strategy_lab/confluence/tier_classifier.py` — stub, no logic yet
- 1 integration test: existing momo backtest still produces identical numbers when confluence aux injection is no-op

**Validation:** `extended_backtest_with_robustness.py` runs unchanged with confluence skeleton imported.

---

### Phase 1 — FLOW engine (3-5 days) [critical path]

Highest priority. Has the most data. If FLOW shows no alpha alone, the whole thesis is suspect.

**Module structure:**
```
strategy_lab/confluence/flow/
├── features.py          # per-(slug, 10s bucket) compute
├── build_features.py    # CLI: parquet cache → features parquet
├── join_with_signals.py # merge flow features into signal events
└── backtest_flow_only.py # G1 gate: FLOW alone backtest
```

**Features computed (10s buckets):**
- `cvd_1m`, `cvd_5m` — cumulative volume delta over rolling windows
- `aggressor_ratio_30s` — taker buys / total taker volume
- `imb_l1`, `imb_l5`, `imb_l10`, `imb_l25` — bid/ask size imbalance at each depth
- `bid_max_size_l10` — wall detection
- `depth_l5_usd`, `depth_l10_usd`, `depth_l25_usd` — total USD on each side
- `momentum_30s` — last 30s buy-vs-sell pressure
- `flow_score` — composite [-1, +1] for downstream tier classifier

**Inputs:** parquet cache `data/v4/refresh_2026_05_06/cache/`
**Output:** `data/v4/refresh_2026_05_06/cache/{btc,eth,sol}_flow_features.parquet` (~150 MB est.)

**G1 gate (must pass before Phase 2):**
- Run `backtest_flow_only.py` over Apr-May window using `extended_backtest_with_robustness.py` with strict asof
- Use `permutation_strict.py` (1000 perms) → require p < 0.05
- Mean $/trade ≥ $+2 on at least 2 of 3 assets (BTC/ETH/SOL)

**Test command:**
```bash
py -X utf8 -m strategy_lab.confluence.flow.build_features
py -X utf8 -m strategy_lab.confluence.flow.backtest_flow_only --tf 5m --asset btc
py -X utf8 -m strategy_lab.meta_classifier.permutation_strict --signal flow --perms 1000
```

---

### Phase 2 — GUARD filters (2 days) [fastest wins]

Cheap to implement, easy to A/B test, high expected impact.

**Filters:**
- `extreme_price` — block entries where `entry_price < 0.35 OR > 0.65`
- `dead_market` — block if `t < 90s post-window-open AND |btc_move| < $5`
- `smart_counter_trend` — if `|btc_move| ≥ $10` and `velocity_30s` SAME direction → block (continuation); REVERSED → allow (mean reversion). Validates against existing `anti_edge_analyzer.py` SOL inversion finding.
- `min_time_to_close` — block if remaining bucket time < 1 min
- `choppiness` — `chop_index_5m > 0.70` → block

**Files:**
```
strategy_lab/confluence/guard/
├── extreme_price.py
├── dead_market.py
├── counter_trend.py
├── time_filters.py
├── choppiness.py
└── backtest_guard_ablation.py  # G2 gate: each filter standalone
```

**G2 gate:**
- For each guard, run shadow universe with/without filter
- Each filter must add ≥ $+1/trade on the FILTERED-OUT subset (i.e., trades it removes were losers)
- Net: stacking all guards on momo baseline must add ≥ $+3/trade

**Expected wins (from Cyclops doc §5):**
- `smart_counter_trend` on SOL → matches 89% inverse hit finding
- `extreme_price` → kills low-edge late entries (V5 LATE rejection already partial signal)

---

### Phase 3 — STRUCTURE features (2-3 days)

**Files:**
```
strategy_lab/confluence/structure/
├── btc_trend.py        # rolling regression slope on 1h + 4h klines
├── sr_levels.py        # swing-high / swing-low extraction (last 5d)
├── regime_classifier.py # TREND / SIDEWAYS / VOLATILE with hysteresis
└── structure_score.py  # composite [-1, +1]
```

**Inputs:** `binance_klines_full.csv` (already cached locally)
**Outputs:** per-bucket `structure_score`, `regime` label

**Defer:** pattern memory (240 segments) — Phase 8+ if v1 needs more alpha.

**Validation:** structure-conditioned cells in backtest. Expect: trend regime amplifies momo edge, sideways suppresses it.

---

### Phase 4 — TRIGGER features (2-3 days)

**Files:**
```
strategy_lab/confluence/trigger/
├── liq_magnet.py       # large liquidations clustering near current px
├── fvg.py              # 3-candle fair value gap detection
├── ofi.py              # last 30s order flow imbalance (subset of flow_score)
└── trigger_score.py    # composite, binary fire flag
```

**Inputs:**
- `hl_liquidations_btc_eth_sol.csv` (245 MB, 1.98M rows) — already local
- Trade prints from parquet cache

**Validation:** trigger-active vs trigger-inactive cells split. Expect trigger-active subset has ≥ +5pp win rate.

---

### Phase 5 — Tier classifier (1-2 days)

**File:** `strategy_lab/confluence/tier_classifier.py`

**Logic (from Cyclops doc):**
```python
def classify(structure_score, flow_score, trigger_active, guard_blocks) -> dict:
    if any(guard_blocks):
        return {"tier": "SKIP", "fair_prob": None, "size_pct": 0.0}
    s_align = structure_score >= 0.50
    f_align = flow_score >= 0.40
    t_active = bool(trigger_active)
    if s_align and f_align and t_active and structure_score >= 0.50 and flow_score >= 0.50:
        return {"tier": "GOLD", "fair_prob": 0.72, "size_pct": 0.020}
    if s_align and f_align and structure_score >= 0.30 and flow_score >= 0.40:
        return {"tier": "SILVER", "fair_prob": 0.64, "size_pct": 0.015}
    if f_align and t_active and flow_score >= 0.40:
        return {"tier": "BRONZE", "fair_prob": 0.54, "size_pct": 0.010}
    return {"tier": "SKIP", "fair_prob": None, "size_pct": 0.0}
```

**Sizing:** convert `size_pct` × bankroll to USD stake, then apply dynamic L1 cap from §5 of NEXT_SESSION_START_HERE.md. Tier sets target, dynamic-cap enforces book reality.

**G3 gate:** GOLD win-rate − BRONZE win-rate ≥ 8pp on shadow universe.

---

### Phase 6 — Grand combo backtest + realfill (2-3 days)

**Step 6a — Backtest:**
- Wire confluence as new sleeve mode in `extended_backtest_with_robustness.py`
- Run 18-cell sweep: 3 assets × 2 tfs × 3 actions (HOLD/HEDGE/SELL) over Apr-May
- Permutation test on combined signal (1000 perms, p < 0.01 target — higher bar than FLOW alone)

**Step 6b — Realfill (G4 gate):**
- Adapt `strategy_lab/momo_realfill/validate_with_real_book.py` for confluence signal
- For each shadow momo fire, simulate confluence_v1 decision (skip/GOLD/SILVER/BRONZE)
- Walk L25 raw book at entry/exit using canonical `book_walk_fill`
- Compare to momo realfill on same slugs
- Bar: confluence_v1 mean $/trade ≥ momo × 1.30

**Step 6c — Production replay (G5 gate):**
- Use `v3_production_replay.py` pattern: run confluence over real production market timestamps
- Compare to shadow data: dir_match ≥ 95%, $-diff < $1/trade

**Tools:**
```bash
py -X utf8 -m strategy_lab.confluence.run_grand_backtest --window 2026-04-22..2026-05-06
py -X utf8 -m strategy_lab.confluence.realfill_compare --baseline momo
py -X utf8 -m strategy_lab.confluence.production_replay
```

---

### Phase 7 — TV agent ship spec (1 day)

**Deliverables:**
- `strategy_lab/reports/TV_AGENT_SHIP_CONFLUENCE_V1.md` — TV agent prompt
- New sleeve mode in production controller: `confluence_v1`
- Env flags for kill-switching back to momo
- Pre-deploy: 24h paper run on 6 sleeves (3 assets × 2 tfs)

**Promotion criteria post-deploy (7-day shadow):**
- mean $/trade ≥ $+15 (vs current momo 15m $+11)
- max DD ≤ momo_15m_max_dd × 1.0 (no worse drawdown)
- GOLD tier hit rate ≥ 65%, SILVER ≥ 55%, BRONZE ≥ 50%
- skip_rate ≥ 40% (filters working)

---

## Dependency graph

```
Phase 0 ─┬─→ Phase 1 (FLOW)  ─┐
         │                     ├─→ Phase 5 (Classifier) ─→ Phase 6 ─→ Phase 7
         ├─→ Phase 2 (GUARD)  ─┤
         ├─→ Phase 3 (STRUCT) ─┤
         └─→ Phase 4 (TRIG)   ─┘
```

Phases 1-4 can run in parallel after Phase 0 lands. Critical path is FLOW (Phase 1) — kill the project early if G1 fails.

## Timeline (single dev, sequential critical path)

| Phase | Days | Cumulative |
|---|---:|---:|
| 0 — Skeleton | 0.5 | 0.5 |
| 1 — FLOW + G1 | 4 | 4.5 |
| 2 — GUARD + G2 | 2 | 6.5 |
| 3 — STRUCTURE | 2.5 | 9 |
| 4 — TRIGGER | 2.5 | 11.5 |
| 5 — Classifier + G3 | 1.5 | 13 |
| 6 — Grand combo + G4/G5 | 3 | 16 |
| 7 — TV agent ship | 1 | 17 |

**Total: ~17 working days.** Parallelization (phases 2/3/4 simultaneous) compresses to ~12 days.

## Kill criteria (when to abandon and re-spec)

- **G1 fails (FLOW no alpha):** halt — re-examine feature definitions or thesis. Do not proceed to higher layers.
- **G3 fails (no tier separation):** classifier thresholds wrong; re-tune on validation fold before continuing.
- **G4 fails (realfill no lift):** signal works but execution kills it. Stop, diagnose entry vwap / spread / sizing.
- **G5 fails (production replay parity):** bug in feature pipeline that diverges from production. Block ship until reproduced.

## Open questions to resolve in Phase 0

1. Does production controller's `fetch_close_asof` use end-time-indexing? (Open Q3 from NEXT_SESSION_START_HERE.md.) If not, production has the same lookahead bug — affects G5 parity calibration.
2. Bucket grain: 10s or 5s? Cyclops doc unclear. Start with 10s, downgrade if signal fades.
3. Liquidation magnet radius: $X price-distance threshold. Default $50 BTC, $10 ETH, $0.50 SOL — tune in Phase 4.
4. Bankroll for `size_pct` calc: per-sleeve or total portfolio? Recommend per-sleeve to match existing rail_02 24h DD per sleeve.

## Risks

| Risk | Mitigation |
|---|---|
| FLOW features have lookahead | Reuse strict asof pattern from `extended_backtest_with_robustness.py:asof()`, add unit test that all features at ts=t use only data ≤ t |
| Tier thresholds overfit to Apr-May window | Hold out final 7 days as validation fold, tune on Apr-only |
| Confluence too restrictive (low fire rate) | Track skip_rate. If > 80%, lower threshold floor on BRONZE tier |
| TV agent integration breaks momo | New sleeve mode is additive; momo_15m sleeves continue running unchanged |
| L25 parquet stale by ship time | Run top-up pull from VPS3 before Phase 6 grand backtest |

---

## Immediate next actions (today)

1. **Confirm bug fixes deployed** — operator verifies all 3 (lookahead asof, hedge fallback, dynamic stake) shipped to VPS3 and producing healthy paper telemetry for ≥ 24h before Phase 1 validation runs (so G5 production-replay parity isn't muddied by stale code).
2. **Verify production `fetch_close_asof` semantics** (Open Q1) — `grep -n "fetch_close_asof" /opt/tradingvenue/backend/app/controllers/polymarket_updown.py` on VPS3.
3. **Kick off Phase 0** — write skeleton + aux_inject contract.
4. **In parallel, start Phase 1 feature compute** — `build_features.py` is the long pole.

---

## Files referenced

- Spec source: `strategy_lab/reports/TRADINGVENUE_VS_CYCLOPS_2026_05_06.md`
- Pointer doc: `NEXT_SESSION_START_HERE.md`
- Existing engine: `strategy_lab/meta_classifier/extended_backtest_with_robustness.py`
- Anti-edge proof: `strategy_lab/reports/ANTI_EDGE_FINDINGS.md`
- Strict asof bug-fix: `strategy_lab/momo_realfill/verify_lookahead_bug.py`

End of plan.
