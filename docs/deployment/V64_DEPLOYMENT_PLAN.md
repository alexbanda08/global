# V64 Deployment Plan — Migration from V52

**Date:** 2026-04-27
**Status:** Planning. Not yet authorized for live capital changes.
**Target:** CAGR +57%, MDD −10%, Sharpe 2.50 (V64 backtest)

---

## 0. The fundamental question — replace or parallel?

V64 is **NOT a different strategy** from V52. V64 is V52 with two parameters changed:
- `risk_per_trade`: 0.03 → 0.0525 (1.75× sizing)
- `leverage_cap`: 3.0 → 4.0 (per-sleeve cap raised to allow the new sizing)

Same signals, same coins (ETH, SOL, AVAX, LINK + BTC regime only), same exits, same blend weights.

That means **V52 and V64 trade the SAME signals at the SAME bars on the SAME coins**. They are perfectly correlated by construction.

### What "running them in parallel" would actually mean

| Mode | Effective behaviour | Verdict |
|---|---|---|
| V52 on $100k + V64 on $100k, both trading | Equivalent to V52 at risk=0.0825 on $200k, but with **2× fees and slippage** paid on the V52 portion | ❌ wasteful |
| V52 on Sub-A + V64 on Sub-B as **isolated capital** | Two independent equity curves, same signals. Risk-segregated but operationally redundant | ✓ only useful for staged validation |
| V64 fully replaces V52 | Single book, single set of fills, lowest cost | ✓ end-state goal |

**Recommendation: STAGED MIGRATION, not permanent parallel.** Use a sub-account during validation only, then decommission V52 once V64 is proven.

---

## 1. Recommended deployment path: 12-week staged migration

### Stage 1 (Weeks 1–4): **V64 small-size validation**
- V52 continues at 100% of current capital (Sub-Account A). No change.
- V64 deploys at **10% of current V52 capital** in **Sub-Account B**.
- Goal: verify V64's live per-trade PnL matches simulator within ±15%.

### Stage 2 (Weeks 5–8): **Live parity confirmation + scale-up**
- If Stage 1 parity holds, raise V64 to **50% of capital** (Sub-B), reduce V52 to **50%** (Sub-A).
- Continue collecting parity data on both books.
- This is the only window where running both books in parallel makes sense: live A/B comparison.

### Stage 3 (Weeks 9–12): **Migrate fully to V64**
- If Stage 2 parity holds, migrate remaining V52 capital to V64.
- Decommission V52 (keep code in repo for audit; halt live execution).
- V64 now runs at 100% capital.

### Decision gate at each stage
Proceed only if **all three** hold for ≥ 4 weeks:
1. Trade-by-trade live fills match backtest fills (within reasonable slippage)
2. Per-week P&L within ±15% of expected (V64 ≈ V52 × 1.75 weekly)
3. No operational issues (margin warnings, partial fills, missed signals)

If any check fails → **HALT scale-up, debug, do not proceed.**

---

## 2. Code changes (the actual diff)

The migration is two parameters. Concrete changes:

### File: existing V52 implementation (live trading bot)

Whatever module currently calls the simulator/exchange-side sizing, the change is:

```python
# OLD (V52 production)
RISK_PER_TRADE = 0.03
LEVERAGE_CAP   = 3.0

# NEW (V64 production)
RISK_PER_TRADE = 0.0525
LEVERAGE_CAP   = 4.0
```

These flow through to position sizing as:
```
size_dollars = (cash × RISK_PER_TRADE) / (sl_atr × ATR_t)
size_cap     = (cash × LEVERAGE_CAP)   / entry_price
final_size   = min(size_dollars, size_cap)
```

So at V64 settings, each trade requests 1.75× the dollar risk, and the per-sleeve cap allows that request to succeed up to 4× equity in nominal exposure (was 3×).

### File: `strategy_lab/run_v52_hl_gates.py`

For backtest reproduction (already validated in `run_v64_simulator_rebuild.py`):

```python
# Apply to ALL 8 sleeve simulator calls in build_v41_sleeve and build_diversifier:
common_kwargs = dict(risk_per_trade=0.0525, leverage_cap=4.0)
_, eq = simulate_with_funding(df, le, se, fund, **EXIT_4H, **common_kwargs)
```

---

## 3. Hyperliquid sub-account setup (Stages 1–2 only)

| Item | Value |
|---|---|
| Sub-Account A | Continues to run V52 at risk=0.03, leverage_cap=3.0 |
| Sub-Account B | New sub-account for V64 at risk=0.0525, leverage_cap=4.0 |
| Initial Sub-B funding (Stage 1) | 10% of current V52 equity |
| Per-asset HL leverage limit | 50× BTC/ETH, 20× SOL/AVAX, 10× LINK — **none binding** at our sizing |
| Funding cost | Auto-amplifies linearly with position size; no config change |

After Stage 3 migration: Sub-Account A is wound down, all capital in Sub-Account B (V64).

---

## 4. Pre-deployment checklist

Before deploying V64 to **any** live capital:

- [ ] **Code parity check:** Run `python -m strategy_lab.run_v64_simulator_rebuild` and verify L=1.75 row matches CAGR +57.35% / MDD −9.86% within ±0.5pp. (Already passing as of 2026-04-26.)
- [ ] **Production code review:** Verify production trading bot reads `RISK_PER_TRADE` and `LEVERAGE_CAP` from a single config file (not hardcoded across multiple modules).
- [ ] **Margin / liquidation simulation:** With current Sub-B capital, simulate worst historical bar (V52 −2.7%) → at L=1.75 = −4.7% bar. Confirm no liquidation, no margin call.
- [ ] **Fee accrual test:** Run V64 on last 30 days of live data offline; confirm fee model matches what HL actually charged on V52 over the same window.
- [ ] **Position size sanity:** Hand-compute position size for one CCI_ETH trigger at current ETH price + ATR. Confirm production matches simulator.
- [ ] **Halt switch:** Confirm one-button kill exists for Sub-Account B.
- [ ] **Monitoring dashboard:** Live P&L vs backtest expectation, per-day. Trade count vs backtest expectation, per-week. (Expected: ~5 trades/week.)

---

## 5. Live monitoring metrics (Stages 1–3)

Track weekly:

| Metric | Backtest expectation | Halt threshold |
|---|---:|---:|
| Trades / week | 4.59 | <2 or >9 sustained 4 weeks |
| Win rate | 35.16% | <22% sustained 4 weeks |
| Avg trade ret | +1.69% | <0% sustained 4 weeks |
| Weekly P&L (V64) ÷ Weekly P&L (V52) | 1.75× | outside [1.40, 2.10] sustained 4 weeks |
| Live MDD vs backtest 5th-pctile | better than −17.5% | breach −20% any week |
| Per-trade slippage vs sim | within 5 bps | >15 bps sustained |

**Live MDD breach of −20% in any rolling year window = HARD HALT.** This was V64's user-target ceiling; breaching it means the forward-MC tail (1.9% probability) materialised, and we should re-evaluate before continuing.

---

## 6. Rollback plan

If Stage 1 or 2 fails parity check:

1. **Stop opening new V64 positions immediately** (kill switch on Sub-Account B).
2. Let existing V64 positions close naturally on their stops/TPs/time-stops (max 13 days). Do NOT manually close — that creates a different P&L distribution than the backtest.
3. Once Sub-B is flat, withdraw remaining capital back to Sub-A (V52).
4. V52 keeps running unchanged; V64 deployment goes back into research.
5. Document the failure mode in the next study (V65/V66).

If Stage 3 fails after V52 is decommissioned:

1. **Re-deploy V52 on Sub-A first** before disabling V64. Don't go flat.
2. Then halt V64.
3. Bigger debug effort needed (since V52 forward parity is now also stale).

---

## 7. Why staged not in-place

The temptation is to just flip the parameters in production tomorrow. Why we don't:

1. **V52 just started paper-trading live.** We need that 1× live track record to anchor V64's parity check. Lose that and we're flying blind.
2. **V64 is a 1.75× leverage step**. Direct jump from 1.0× live → 1.75× live skips the validation that fees, slippage, and execution timing scale linearly. Models can be wrong about all three.
3. **Risk segregation** during validation: a bug in V64's deployment can't blow up V52's capital while we're learning.
4. **Operational drift detection**: parallel running surfaces issues (signal lag, partial fills, funding miscalculation) by direct comparison rather than by deviation-from-expected alone.

The 12-week staged migration costs us at most 12 weeks of capital being under-leveraged (Sub-B at 10% then 50% before reaching 100% V64). On a $X book that's roughly **half a quarter at ~30% effective annual return instead of 57%** — about 3-4% of annual return given up to buy 12 weeks of live evidence. Cheap insurance.

---

## 8. End-state operating spec (post-Stage 3)

| Item | Value |
|---|---|
| Strategy | V64 (V52 with risk=0.0525, leverage_cap=4.0) |
| Active sleeves | 8 (CCI_ETH, STF_SOL, STF_AVAX, LATBB_AVAX, MFI_SOL, VP_LINK, SVD_AVAX, MFI_ETH) |
| Active coins (trading) | ETH, SOL, AVAX, LINK |
| Active coins (regime only) | BTC |
| Bar frequency | 4h Hyperliquid native |
| Trade frequency | ~4.6 / week, ~20 / month |
| Avg holding period | ~3 days, max 13 days |
| Long / short balance | ~48% / 52% |
| Re-validation cadence | Every 6 months: rerun gates 1–10 on rolling window |
| Capital scaling cadence | Monthly review of MDD vs forward-MC; if MDD < −15% rolling 90d, revisit L |

---

## 9. Files

- `docs/deployment/V64_DEPLOYMENT_PLAN.md` — this document
- `docs/research/33_V64_SIMULATOR_CONFIRMATION.md` — backtest confirmation
- `docs/research/34_V64_DASHBOARD.md` — full statistics
- `strategy_lab/run_v64_simulator_rebuild.py` — sim-level builder for V64
- `strategy_lab/run_v64_dashboard.py` — operational stats generator
- `docs/research/phase5_results/v64_simulator_rebuild.json` — raw numbers
- `docs/research/phase5_results/v64_dashboard.json` — dashboard data

---

## 10. Authorization

This plan requires **explicit user approval** at each stage before proceeding:

- [ ] Stage 1 start (deploy V64 to 10% in Sub-B): authorized by ____ on ____
- [ ] Stage 2 start (50/50 split): authorized by ____ on ____
- [ ] Stage 3 start (full V64 migration): authorized by ____ on ____
- [ ] V52 decommission (after Stage 3 ≥ 4 weeks parity): authorized by ____ on ____

---

**Headline answer to "replace or parallel?":**
**Stage migration. Parallel for 8 weeks (Stages 1–2) for live validation, then replace.** End-state is one book running V64 only. Don't run V52 and V64 forever — they trade the same signals and you'd just be paying double fees on duplicated positions.
