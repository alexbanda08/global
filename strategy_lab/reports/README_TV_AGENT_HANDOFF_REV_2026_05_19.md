# 📦 TV Agent Handoff REV — Index (supersedes 2026-05-18 version)

**Date**: 2026-05-19
**Project**: Polymarket maker-bot suite deployment — REVISED
**Target VPS**: Ireland (`ssh vps_ireland`)
**Deliverable**: 3 live + 1 shadow strategies, validated via 213-slug backtest
**Budget**: **$100 per strategy max** (total $300 across 3 live strategies)

---

## 🚨 What changed since the 2026-05-18 handoff

The original handoff (`README_TV_AGENT_HANDOFF.md`) promised:
- Initial capital: $200
- Expected: $100-300/day across 3 strategies
- Strategies: ACC-M ($50) + MAS ($100) + ACC-H ($50)
- Edge per pair: $0.05-$0.30 per strategy

After 213-slug backtest validation + LB-API audit of 5 reference wallets, **those numbers were 50-170x overstated**. The wallets we copied don't actually make those numbers — pickup extrapolations from short-window peaks were wrong.

**This revision is honest**:
- Initial capital: **$300** (was $200, but spread differently)
- Expected: **$30-85/day** across 3 live strategies (revised down 70%+)
- Strategies: **ACC-M REV ($100) + MAS REV ($100) + ACC-PC NEW ($100)**, **ACC-H shadow-only**
- Edge per slug: validated $0.09 to $1.25/slug per strategy in backtest

---

## ⏱️ Read this first (1 minute)

You're deploying a 3-strategy maker-bot suite for Polymarket binary up-down markets. The strategies are derived from real on-chain wallets, but the v1 spec made 3 errors:

1. **POST_SIZE=5 was too small** — reference wallets fill 100-254 shares per order
2. **ACC-H V3f composite taker LOSES money** in fee-accurate simulation
3. **PnL projections were 50-170x inflated** from short-window extrapolations

This handoff fixes those errors. Read `STRATEGY_REVISION_2026_05_19.md` for the full reasoning.

---

## 📚 Read in this order

### 1. Strategy revision (READ FIRST)

📄 **[STRATEGY_REVISION_2026_05_19.md](STRATEGY_REVISION_2026_05_19.md)**

What it covers:
- Why the original handoff is wrong (with data)
- What changes per strategy
- New strategies introduced (ACC-PC, PAT research-stage)
- Budget constraints ($100 per strategy)
- Realistic deployment timeline (4 weeks)
- Halt + scale-up criteria

### 2. Per-strategy specs (REVISED 2026-05-19 PM after PAT backtest)

| Doc | Strategy | Status | Capital | Backtest PnL/slug |
|---|---|---|---|---|
| 📄 [TV_DEPLOY_SPEC_PAT_ACCM_HYBRID_2026_05_19.md](TV_DEPLOY_SPEC_PAT_ACCM_HYBRID_2026_05_19.md) | **PAT+ACC-M HYBRID** ⭐ | **PRIMARY LIVE** | $200 | **+$1.98** ⭐ winner |
| 📄 [TV_DEPLOY_SPEC_ACC_M_REV_2026_05_19.md](TV_DEPLOY_SPEC_ACC_M_REV_2026_05_19.md) | ACC-M REV (base) | merged INTO hybrid above | — | +$1.25 alone |
| 📄 [TV_DEPLOY_SPEC_MAS_REV_2026_05_19.md](TV_DEPLOY_SPEC_MAS_REV_2026_05_19.md) | **MAS REV** | DEPLOY LIVE (week 2) | $80 | +$0.09 (data collection) |
| 📄 [TV_DEPLOY_SPEC_ACC_PC_2026_05_19.md](TV_DEPLOY_SPEC_ACC_PC_2026_05_19.md) | **ACC-PC** | optional 3rd (week 3) | $100 | +$0.30-0.50 |
| 📄 [TV_DEPLOY_SPEC_ACC_H_SHADOW_2026_05_19.md](TV_DEPLOY_SPEC_ACC_H_SHADOW_2026_05_19.md) | **ACC-H SHADOW** | SHADOW ONLY | $0 | -$6.84 (research only) |

📄 **[TV_AGENT_IMPLEMENTATION_DELTAS_2026_05_19.md](TV_AGENT_IMPLEMENTATION_DELTAS_2026_05_19.md)** — **READ THIS** — consolidated change list with code diffs
📄 **[PAT_FINDINGS_2026_05_19.md](PAT_FINDINGS_2026_05_19.md)** — why PAT+ACC-M HYBRID is the new primary

### 3. Infrastructure plan (UNCHANGED from v1)

📄 **[TV_AGENT_DEPLOYMENT_PLAN_2026_05_18.md](TV_AGENT_DEPLOYMENT_PLAN_2026_05_18.md)**

All infrastructure work stands:
- BookMirror, PolymarketClient, allowance, live_gate ALL exist on Ireland VPS ✓
- Build event-driven loop (`poly_maker_loop.py`)
- Build merger service (`poly_merger.py`)
- Build minter service (`poly_minter.py`) for MAS
- Implement P1-P10 performance requirements

### 4. Performance reqs (UNCHANGED from v1)

📄 **[TV_AGENT_HANDOFF_2026_05_18.md](TV_AGENT_HANDOFF_2026_05_18.md)**

10 mandatory performance requirements, Rust transition plan.

### 5. Background research (optional)

📄 **[OVERNIGHT_WALLET_VS_BACKTEST_2026_05_19.md](OVERNIGHT_WALLET_VS_BACKTEST_2026_05_19.md)** — full overnight analysis: 5 wallets profiled, 9 backtests, 213-slug validation, size sweep, slug-selection signal mining
📄 **[STRATEGY_AUDIT_REFS_ONLY_2026_05_19.md](STRATEGY_AUDIT_REFS_ONLY_2026_05_19.md)** — audit of original specs using only reference wallets

---

## 💻 Code references (port to TV codebase)

```
shadow_engine/                    # Python reference for v1 strategies
├── strategies/
│   ├── acc_m.py                  # use REV config (POST_SIZE=20)
│   ├── acc_h.py                  # shadow-only mode
│   └── mas.py                    # use REV config (2 cells)

strategy_lab/backtests/           # New validation scripts
├── multi_strat_backtest.py       # 5-strategy comparison engine
├── wallet_profiler.py            # per-slug wallet behavior
├── wallet_true_pnl.py            # actual PnL with rebates/fees
├── slug_selection_signal.py      # what predicts slug engagement
└── time_of_day_analysis.py       # hourly + offset patterns
```

**Use the Python as a REFERENCE.** Port to TV's coding patterns. The decision logic is the truth — architectural integration is your call.

---

## 🎯 Quick reference cheat sheet

### Polygon contract addresses (unchanged)
```
USDC.e         = 0x2791bca1f2de4661ed88a30c99a7a9449aa84174
CTF            = 0x4d97dcd97ec945f40cf65f87097ace5ea0476045
CLOB Matcher   = 0xe111180000d2663c0091e4f400237545b87b996b
NegRiskAdapter = 0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296
```

### CLOB minimum order size
**5 shares per side** (still applies — but POST_SIZE should be 20 for ACC-M REV)

### Universal cancel rule (all strategies)
Cancel an open order when EITHER:
- Best price moves > 3¢ from our posted price, OR
- Order age > 20 seconds (30s for MAS asks)

DO NOT cancel on partial fill. DO NOT cancel near slug close.

### Merge timing
ACC strategies call `mergePositions` via NegRiskAdapter when paired inventory ≥ 5.

### Per-strategy capital (REVISED 2026-05-19 PM)
- **PAT+ACC-M HYBRID: $200 wallet, POST_SIZE=20 + PAT overlay, 1 cell (BTC 5m)** ← primary, deploy week 1
- MAS REV: **$80 wallet, $30 pre-mint × 2 cells (BTC 5m + 15m)** ← deploy week 2
- ACC-PC: **$100 wallet, POST_SIZE=20, reactive taker** ← optional week 3
- ACC-H SHADOW: **$0 (logs only)**
- PAT SHADOW: **$0 (research logs)**

**Total live (week 3): $380** across 3 strategies. Concentrated on the +$1.98/slug winner.

If starting smaller: **$200 on PAT+ACC-M HYBRID only** is sufficient. Adds $80 MAS week 2. Adds $100 ACC-PC week 3.

---

## ✅ Sprint checklist (REVISED 4-week timeline)

### Week 1: ACC-M REV only

```
Day 1-2: PORT strategies REV
  [ ] Create backend/app/strategies/polymarket/maker/
  [ ] Port shadow_engine/base.py → maker/types.py
  [ ] Port shadow_engine/strategies/acc_m.py → maker/acc_m.py (use REV config)
  [ ] Unit tests using replayed slugs

Day 3-4: BUILD infrastructure
  [ ] backend/app/engine/poly_maker_loop.py
  [ ] backend/app/services/poly_merger.py
  [ ] Add env vars to /etc/tv/tradingvenue.env
  [ ] Wire into engine/main.py TaskGroup
  [ ] Implement P3 (pre-signed orders), P7 (int cents), P10 (latency)

Day 5: SHADOW deploy ACC-M REV
  [ ] systemctl restart tv-engine
  [ ] Monitor: journalctl -u tv-engine -f | grep ACC-M-REV

Day 6: VALIDATE shadow
  [ ] Mean $/slug > $0 confirmed
  [ ] Realized fill rate > 25% of simulated
  [ ] No critical errors

Day 7: PROMOTE ACC-M REV to LIVE
  [ ] Wallet funded with $100 USDC.e
  [ ] Allowance preflight passes
  [ ] Set TV_POLY_MAKER_SHADOW_MODE=false
```

### Week 2: Add MAS REV

```
Day 8-9: PORT + INTEGRATE MAS REV
  [ ] backend/app/services/poly_minter.py
  [ ] MAS strategy module with $30 pre-mint × 2 cells
  [ ] Shadow deploy MAS REV (parallel to ACC-M LIVE)

Day 10: VALIDATE shadow MAS
  [ ] Mean $/slug > -$0.50 (relaxed bar)
  [ ] 70%+ mints recovered

Day 11: PROMOTE MAS REV to LIVE
  [ ] Wallet funded with $100 USDC.e (separate from ACC-M)

Day 12-14: Monitor both, halt if drawdown > $20/day
```

### Week 3: Add ACC-PC + ACC-H shadow

```
Day 15-16: PORT ACC-PC NEW
  [ ] ACC-PC strategy module (extends ACC-M with reactive taker)
  [ ] Shadow deploy

Day 17: PROMOTE ACC-PC to LIVE
  [ ] Wallet funded with $100 USDC.e
  [ ] Run on BTC 15m (separate cell from ACC-M REV's BTC 5m)

Day 18: PORT ACC-H SHADOW
  [ ] V3f composite taker logic, NEVER promote to live
  [ ] Per-rule decision logging

Day 19-21: All 3 LIVE + ACC-H shadow logging
```

### Week 4: Validation + selective scale-up

```
Day 22-28: Daily review
  [ ] Per-strategy 7-day rolling PnL
  [ ] If ANY strategy > +$30/day for 5 days: scale that strategy to $300
  [ ] If ACC-H shadow confirms -$5/slug or worse: drop permanently
  [ ] If consistent profit across all 3: consider Phase 2 (multi-asset, multi-cell)
```

---

## ❓ Questions to clarify before you start (UNCHANGED)

(from §11 of the deployment plan)

1. Does BookMirror already subscribe to trades, or do we need a separate trade_mirror?
2. Should merge use NegRiskAdapter or vanilla CTF?
3. How do ACC-M, MAS, ACC-PC share USDC.e balance for allowance preflight? (probably separate wallets)
4. Can the new event-driven `poly_maker_loop` coexist with existing bar-driven `poly_updown_loop`?
5. If we use a new wallet for maker strategies, how is allowance preflight configured?

---

## 🆘 If stuck

- Strategy logic question → check the REV spec or shadow_engine reference
- Infrastructure question → check `/opt/tradingvenue/backend/app/` and the unchanged deployment plan
- Why a change happened → check `STRATEGY_REVISION_2026_05_19.md`
- Performance question → check `TV_AGENT_HANDOFF_2026_05_18.md` §"Performance requirements"

---

## 🏁 Definition of "DONE" (REVISED)

After 28 days:
- **ACC-M REV** live, producing $10-50/day consistently (positive ≥ 5/7 days)
- **MAS REV** live, producing $0-10/day (break-even acceptable as data collection)
- **ACC-PC NEW** live, producing $10-25/day
- **ACC-H SHADOW** has 14d+ of per-rule decision data, decision made (drop or refine)
- **Total realistic income: $20-85/day on $300 capital**
- Max 24h drawdown < $20 per strategy
- 7-day rolling PnL positive for at least 2 of 3 strategies
- No critical alerts triggered

**This replaces the old "DONE" definition of $100-300/day on $200 capital.**

---

## 🎯 The biggest TL;DR

| Aspect | OLD plan | NEW plan |
|---|---|---|
| Strategies live | ACC-M + ACC-H + MAS | ACC-M REV + MAS REV + ACC-PC NEW |
| ACC-H | $50 LIVE | $0 SHADOW ONLY |
| ACC-M POST_SIZE | 5 | 20 |
| MAS cells | 6 | 2 |
| Total capital | $200 | $300 |
| Expected daily | $100-300 | **$20-85** |
| Honest sizing? | No (inflated) | **Yes (213-slug validated)** |

The strategies are 90% the right design. The corrections are: size up ACC-M, scope down MAS, drop ACC-H from live, add ACC-PC as the lower-variance variant. Plus accept that $20-85/day is the realistic target, not $100-300.

**Start with $100 on ACC-M REV. Validate. Then add the others. Don't burn the bankroll on the original plan's inflated expectations.**

---

*See companion docs for full detail. This README is the entry point.*
