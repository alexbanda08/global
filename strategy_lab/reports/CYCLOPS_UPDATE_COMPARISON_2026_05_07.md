# Cyclops v125 Update — Comparison + Gap Analysis

**Date:** 2026-05-07
**Source:** article from Cyclops author (4-layer confluence bot we modeled after)
**Headline:** WR 55% → 68% on the SAME signal stack — gain came from infrastructure fixes, not strategy changes.

---

## What changed in Cyclops

1. **Risk control now actually pauses trading.** Their `_check_risk()` was logging "drawdown limit" 213 times in one day but always returning True (debugging code never restored). Fixed: env-controlled mode (`hard`/`soft`/`off`), timed pause (no resume mid-drawdown), default = `hard`.

2. **Tier flows through the full pipeline.** Position object never copied `tier` from signal — every trade was managed as `UNKNOWN`. MICRO trades that should close early were held to expiry. Two-line fix to copy `tier` + `min_edge_required` into the position dict.

3. **Vote exception → SKIP candle (not fallback trade).** Their voting layer's exception handler was opening trades with a stale heuristic table from a previous model version (`fair = 0.52` for 2 sigs, etc.). 8–12 such fallback trades/day were a steady drain. Fixed: skip on exception.

4. **Session stats don't bleed across restarts.** They were loading `session_stats.json` with aggregated metrics from the previous session — including data from buggy runs. For 2–3 hours after each restart the bot anchored on stale history. Fix: file removed, every startup is clean, recompute from `trades.csv` on demand.

**Author's bottom line:** "The gap between backtest and live was never the strategy — it was the system failing to execute what the strategy intended."

---

## New tier: MICRO

Cyclops now classifies as **GOLD / SILVER / BRONZE / MICRO** (4 firing tiers, plus an implicit SKIP).

MICRO appears to be:
- A LOW-confidence tier that still fires (so we don't lose all the marginal signal)
- Specifically managed at exit (close early — don't ride to expiry)
- Different `min_edge_required` than GOLD/SILVER/BRONZE
- The article doesn't disclose exact thresholds or sizing

**Why this matters:** their bot had a bug where the tier was UNKNOWN, and "the MICRO filter worked at entry but not at exit — MICRO trades that should close early were being held to expiry." So MICRO is meant to capture trades with minimal edge that need TIGHT exits to avoid bleeding when the edge fails.

---

## Mapping to our implementation

### Architecture comparison

| Layer | Cyclops | Our implementation | Status |
|---|---|---|---|
| Signal/voting | Multi-module probability vote → fair value | momo (top-10% \|ret_2m\|) + 4-layer confluence enrichment | DIFFERENT signal source — momo is single-feature; their voting is multi-module |
| Tier classifier | GOLD/SILVER/BRONZE/MICRO | GOLD/SILVER/BRONZE/SKIP | **MISSING MICRO** |
| Risk control | timed pause, hard default | TV agent has 11-rail framework (rails 03/04/05 portfolio DD, rail_11 abs day loss) | **More comprehensive than Cyclops — but verify it's wired in confluence_silver_v1 spec** |
| Tier-driven exit rules | yes (MICRO closes early, GOLD rides) | NO — we only use HOLD | **MISSING — we don't differentiate exit by tier** |
| Vote exception → SKIP | yes (post-fix) | TV agent has `try/except` patterns but our SPEC doesn't mandate SKIP-on-feature-error | **MISSING IN SPEC** |
| Session stats reset | clean startup, recompute from journal | Not yet relevant (no live deploy) | OK for now |
| Decision loop | 10 Hz event-driven | Per-market-resolution (5m or 15m windows) | DIFFERENT cadence |
| Telegram /pause /resume /claim /status | yes | TV agent has its own command UI | DIFFERENT but functionally equivalent |

### What we have that they don't

- **11-rail risk framework** with independent watchdog (rail_07_exchange_outage, rail_09_correlation, etc.)
- **Multi-venue** (Polymarket + Hyperliquid + Kalshi)
- **Backtest infrastructure** (95-100% directional match shadow vs backtest, permutation+walkforward gates)
- **Claude Agent SDK supervisor** (24/7 oversight)
- **Storedata co-resident DB** for data layer

### What they have that we don't

- **MICRO tier** — soft-confidence fire with tight exit
- **Tier-driven exit rules** — different exits per tier
- **Demonstrated forward-test alpha** — 3 weeks at 68% WR on the SAME signal pre/post infra fixes
- **High-frequency decision loop** (10 Hz event-driven)
- **Trade journal as single source of truth** — recompute stats on demand, never persist aggregates

---

## What this means for our next decision

### Lessons that DIRECTLY apply to confluence_silver_v1

1. **The same-signal lesson is the headline.** Cyclops didn't change the strategy; they fixed the infra, and went from 55% → 68% WR. Our SILVER@SOL hit 100% on n=8 in backtest. If the live infra mirrors the backtest faithfully, the result should hold. If it doesn't, we'll see Cyclops's old gap.

2. **Hard-pause discipline.** When DD hits, freeze for a fixed duration. The TV agent's existing `rail_03_portfolio_dd_15` and similar already do this — but our `confluence_silver_v1` SPEC must explicitly inherit them. Verify in the spec.

3. **Skip on feature exception.** If FLOW or STRUCTURE compute throws (DB timeout, OB lag spike, kline gap), the sleeve must SKIP this market's evaluation, not fall back to baseline momo or stale features. This is missing from our SPEC.

4. **Session-state bleed.** Once live, we MUST NOT cache aggregated metrics. Every restart is clean. Recompute from `trading.events` (storedata) on demand. The TV agent spec needs this as a hard rule.

5. **Tier-driven exits.** Our backtest used HOLD only. Cyclops differentiates: GOLD rides to expiry, MICRO closes early. For our context (binary 5m/15m markets that resolve at fixed time), "close early" maps to HEDGE or SELL policy. We tested HEDGE/SELL in extended_backtest and they generally underperformed HOLD on these binary markets — because hedge/sell policies fire wrongly when the lookahead-fixed asof is used (the L25 realfill of momo SHADOW data showed +$7.30/trade missed by current production exit policies). Worth re-investigating per-tier.

### MICRO tier — do we want it?

Three options:

**Option A: Skip MICRO.** Stick with our 3-tier (GOLD/SILVER/BRONZE/SKIP). Argue our universe is too small (binary 5m markets, not perp), and adding MICRO just adds complexity.

**Option B: Add MICRO as "SOFT-SILVER".** Define MICRO = struct OR flow agreement (not both). Smaller stake (0.5% × bankroll). HOLD policy. Catches the trades currently classified as SKIP that have ONE layer aligned. Could reveal additional alpha or noise — needs backtest.

**Option C: Add MICRO as a tighter-exit tier.** Define MICRO = SILVER-ish thresholds but lower (struct ≥ 0.20, flow ≥ 0.30). Close at first sign of adverse move (HEDGE on rev_2bp instead of rev_5bp). This is the closest match to Cyclops's MICRO = small edge + tight exit.

**Recommendation: B first, then iterate.** Backtest MICRO = "either layer aligned + sign-aligned with held side, NOT both" on SOL universe. If it shows modestly positive expectancy, add as a new tier with reduced size_pct.

---

## Concrete actions before paper deploy

### MUST-DO (block ship without these)

1. **TV agent spec must explicitly mandate SKIP-on-feature-exception.** Add a section to `TV_AGENT_SPEC_CONFLUENCE_SILVER_V1.md`: "If FLOW or STRUCTURE compute throws, SKIP the market evaluation. Do NOT fall back to baseline momo. Log `feature_exception_skip` with the exception type."

2. **TV agent spec must mandate clean startup.** Add: "On controller restart, do NOT load any cached aggregated metrics. Compute live KPIs from `trading.events` table on demand. Never persist tier-level statistics to disk; always re-derive."

3. **TV agent spec must wire the existing rails.** Verify rail_03/04/05/11 are explicitly enabled for `confluence_silver_v1` sleeves. Hard-pause mode = default. Resume only after timer expires.

4. **Restrict spec to SOL only.** ETH_15m and BTC are confirmed losers under sign-aligned SILVER. Drop them from the production scope.

### SHOULD-DO (do before paper if time permits)

5. **Backtest MICRO option B** on SOL. If it adds samples without breaking the 86% breakeven, ship it as a 2nd sub-sleeve.

6. **Tier-driven exit policy backtest.** Re-run extended_backtest's HEDGE/SELL policies on SILVER trades only (not full momo universe). Cycle's MICRO = early close pattern might unlock alpha on the HEDGE/SELL cells that currently underperform HOLD.

7. **Telemetry contract update.** Add `feature_exception_skip` and `risk_pause_active` events to the spec.

### MAYBE-DO (post-paper, depending on data)

8. **Add MICRO as defined in option C** if we observe that SILVER trades that DO eventually lose tend to have early adverse signals.

9. **Increase decision-loop frequency for SILVER trades.** Re-evaluate at 30-second intervals during the hold window, not just at fixed buckets. Closer to Cyclops's 10 Hz.

---

## Updated recommendation for confluence_silver_v1 paper deploy

| Aspect | Original spec | Updated per Cyclops lessons |
|---|---|---|
| Cells | SOL_5m, SOL_15m, ETH_15m | **SOL_5m, SOL_15m only** |
| Exit policy | HOLD | HOLD (start), revisit per tier |
| Risk pause | implicit (rails) | **explicit `RISK_PAUSE_MODE=hard` + timed** |
| Feature errors | (unspecified) | **SKIP candle, log exception type** |
| Session stats | (unspecified) | **clean startup, recompute from events** |
| Tier classifier | 3-tier (GOLD/SILVER/BRONZE/SKIP) | **same** (defer MICRO to post-paper backtest) |
| Telemetry | log tier + scores | **+ skip_reason, risk_pause_active, feature_exception** |
| Promotion to live | n≥80, hit≥85%, mean≥+$2 | **same + at least one observed loss + walk-forward 6/8 positive** |

---

## Files

- This comparison: `strategy_lab/reports/CYCLOPS_UPDATE_COMPARISON_2026_05_07.md`
- Source spec to update: `strategy_lab/reports/TV_AGENT_SPEC_CONFLUENCE_SILVER_V1.md`
- Validation final: `strategy_lab/reports/SILVER_VALIDATION_FINAL_2026_05_07.md`

## Open questions for operator

1. Do we want a MICRO tier at all? Or stick with 3-tier (GOLD/SILVER/BRONZE/SKIP) for v1?
2. Should we backtest tier-driven exit policies (HEDGE/SELL per tier) before paper-deploying?
3. The TV agent spec assumed ETH_15m. Update it now or after paper feedback on SOL?
