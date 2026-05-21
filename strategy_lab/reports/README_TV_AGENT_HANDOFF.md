# 📦 TV Agent Handoff — Index

**Date**: 2026-05-18
**Project**: Polymarket maker-bot suite deployment
**Target VPS**: Ireland (`ssh vps_ireland`)
**Deliverable**: 3 production strategies (ACC-M, MAS, ACC-H) running on Polymarket

---

## ⏱️ Read this first (1 minute)

You're deploying a 3-strategy maker-bot suite for Polymarket binary up-down markets. Strategies decoded from real on-chain wallets making $10k-$254k/day. Estimated dev time: ~11 days. Initial capital: $200 USDC.e total. Expected day-1 PnL: $25-150/day at test scale.

All decisions, rules, parameters are chain-validated. You build the infrastructure; we provide the strategy logic.

---

## 📚 Read in this order

### 1. Master deployment plan — **READ FIRST**

📄 **[TV_AGENT_DEPLOYMENT_PLAN_2026_05_18.md](TV_AGENT_DEPLOYMENT_PLAN_2026_05_18.md)**

What it covers:
- What's already on the Ireland VPS (don't rebuild — BookMirror, PolymarketClient, redeemer, allowance, live_gate all exist)
- What you need to build (event-driven loop + merger + minter services)
- 8-day implementation phases
- Capital model + cell allocation
- Risk + safety + kill switches
- Open questions to clarify before starting

### 2. Performance + Rust transition

📄 **[TV_AGENT_HANDOFF_2026_05_18.md](TV_AGENT_HANDOFF_2026_05_18.md)**

What it covers:
- 10 mandatory performance requirements (P1-P10): Ireland VPS ✅, WS-only posting, pre-signed orders, async pipeline, integer-cent quantization, latency instrumentation
- Phase 3 Rust transition plan (PyO3 hot-path extension when ready)
- When to migrate to Rust (only after Python validated profitable + queue starvation observed)

### 3. Per-strategy specs (one per strategy)

| Doc | Strategy | What it does | Edge per pair | Wallet seed |
|---|---|---|---|---|
| 📄 [TV_DEPLOY_SPEC_ACC_M_2026_05_18.md](TV_DEPLOY_SPEC_ACC_M_2026_05_18.md) | **ACC-M** | Pure pair-arb maker (post BIDs only, merge for $1) | $0.05-$0.20 | $50 |
| 📄 [TV_DEPLOY_SPEC_MAS_2026_05_18.md](TV_DEPLOY_SPEC_MAS_2026_05_18.md) | **MAS** | Mint-and-sell (mint pairs, post ASKs) | $0.02-$0.04 | $100 |
| 📄 [TV_DEPLOY_SPEC_ACC_H_2026_05_18.md](TV_DEPLOY_SPEC_ACC_H_2026_05_18.md) | **ACC-H** | ACC-M + 4-rule composite taker (V3f, 78.9% coverage) | $0.10-$0.30 | $50 |

Each spec has: state machine, decision rules (with pseudocode), config parameters, per-slug expectations, shadow logging requirements, live promotion criteria, implementation checklist.

---

## 💻 Code references (port to TV codebase)

Working Python implementation that validates the strategies end-to-end:

```
shadow_engine/
├── __init__.py
├── base.py                # Event types, Side, Action, SlugState, OpenOrder
├── strategies/
│   ├── base.py            # StrategyBase ABC + helpers
│   ├── acc_m.py           # Pure pair-arb maker
│   ├── acc_h.py           # Hybrid with 4-rule composite taker
│   └── mas.py             # Mint-and-sell mirror
├── feeds/
│   ├── replay.py          # Historical replay (validation only)
│   └── replay_l25.py      # L25-direct replay (with real bid sizes)
└── runner.py              # Orchestrator + shadow logging + fill simulation

examples/
├── shadow_acc_m_btc_5m.py        # ACC-M solo run
├── shadow_compare_acc_m_vs_h.py  # ACC-M vs ACC-H side-by-side
├── shadow_all_3_strategies.py    # All 3 strategies in parallel shadow
└── shadow_calibrated_l25.py      # L25-calibrated full validation
```

**Use the Python as a REFERENCE.** Port to TV's coding patterns (Pydantic, structlog, dependency injection). The decision logic is the truth — architectural integration is your call.

---

## 📖 Supporting research (background context, optional)

Read these if you want to understand WHY the rules are what they are. Not required for implementation.

### Strategy decode (how we arrived at the 4-rule composite for ACC-H)

- 📄 [EEBDE7A0_TAKER_TRIGGER_V3_2026_05_18.md](EEBDE7A0_TAKER_TRIGGER_V3_2026_05_18.md) — Final V3f decode (4 rules, 78.9% coverage)
- 📄 [EEBDE7A0_TAKER_TRIGGER_V2_2026_05_18.md](EEBDE7A0_TAKER_TRIGGER_V2_2026_05_18.md) — V2 decode (3 rules, 68.9%)
- 📄 [EEBDE7A0_TAKER_TRIGGER_DECODED_2026_05_18.md](EEBDE7A0_TAKER_TRIGGER_DECODED_2026_05_18.md) — V1 decode (discount-capture only)

### Operational rules (cancel discipline, merge timing)

- 📄 [CANCEL_RULES_DECODED_2026_05_18.md](CANCEL_RULES_DECODED_2026_05_18.md) — Decoded cancel-on-displacement (3¢) + max-age (20s) rules

### Wallet anatomy

- 📄 [WALLET_TX_TAXONOMY_2026_05_18.md](WALLET_TX_TAXONOMY_2026_05_18.md) — Full TX type breakdown for 4 reference wallets
- 📄 [MULTI_WALLET_ALPHA_DECODE_2026_05_18.md](MULTI_WALLET_ALPHA_DECODE_2026_05_18.md) — 5-wallet alpha decode (per-wallet classifications)
- 📄 [NEW_WALLETS_ALPHA_DECODE_2026_05_18.md](NEW_WALLETS_ALPHA_DECODE_2026_05_18.md) — Additional 2 wallets decoded
- 📄 [RELAY_WALLET_DECODE_0xf3cfb6a6_2026_05_18.md](RELAY_WALLET_DECODE_0xf3cfb6a6_2026_05_18.md) — NegRiskAdapter relay analysis

---

## 🎯 Quick reference cheat sheet

### Polygon contract addresses (already in TV settings)
```
USDC.e         = 0x2791bca1f2de4661ed88a30c99a7a9449aa84174
CTF            = 0x4d97dcd97ec945f40cf65f87097ace5ea0476045
CLOB Matcher   = 0xe111180000d2663c0091e4f400237545b87b996b
NegRiskAdapter = 0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296
```

### CLOB minimum order size
**5 shares per side** (Polymarket CLOB rule).

### Universal cancel rule (all 3 strategies)
Cancel an open order when EITHER:
- Best price moves > 3¢ from our posted price, OR
- Order age > 20 seconds

DO NOT cancel on partial fill (leave residuals on book).
DO NOT cancel near slug close (let orders fill or expire naturally).

### Merge timing
ACC strategies call `mergePositions` via NegRiskAdapter when paired inventory ≥ 5. Also check periodically every 5 seconds.

### Per-slug capital (test scale)
- ACC-M: $50 wallet (no pre-mint)
- MAS: $30 pre-mint per slug × all 6 cells = $180 active capital
- ACC-H: $50 wallet (no pre-mint)

---

## ✅ Sprint checklist

```
Sprint 1 (Days 1-2): PORT strategies
  [ ] Create backend/app/strategies/polymarket/maker/
  [ ] Port shadow_engine/base.py → maker/types.py
  [ ] Port shadow_engine/strategies/{base,acc_m,acc_h,mas}.py → maker/
  [ ] Unit tests using replayed slugs

Sprint 2 (Days 3-4): BUILD infrastructure
  [ ] backend/app/engine/poly_maker_loop.py (event-driven dispatcher)
  [ ] backend/app/services/poly_merger.py (NegRiskAdapter merge call)
  [ ] backend/app/services/poly_minter.py (splitPosition for MAS)
  [ ] Add env vars to /etc/tv/tradingvenue.env
  [ ] Wire into engine/main.py TaskGroup
  [ ] Implement P3 (pre-signed orders), P7 (int cents), P10 (latency)

Sprint 3 (Day 5): SHADOW deploy ACC-M
  [ ] systemctl restart tv-engine
  [ ] Monitor: journalctl -u tv-engine -f | grep maker

Sprint 4 (Day 6): SHADOW deploy MAS (parallel with ACC-M shadow)
  [ ] Different cells to avoid conflict

Sprint 5 (Days 7-8): VALIDATE shadow + promote ACC-M + MAS to LIVE
  [ ] Set TV_POLY_MAKER_SHADOW_MODE=false
  [ ] Verify wallet funded ($50 ACC-M + $100 MAS)
  [ ] Verify allowance preflight passes

Sprint 6 (Days 9-10): SHADOW deploy ACC-H
  [ ] Test the 4-rule composite trigger
  [ ] Verify fill discipline matches expected

Sprint 7 (Day 11): PROMOTE ACC-H to LIVE
  [ ] Total $200 USDC.e capital deployed across 3 strategies
```

---

## ❓ 5 questions to clarify before you start

(from §11 of the deployment plan)

1. Does BookMirror already subscribe to trades, or do we need a separate trade_mirror?
2. Should merge use NegRiskAdapter or vanilla CTF? (poly_redeemer recently switched to vanilla CTF for redeems)
3. How do ACC-M and MAS share USDC.e balance for allowance preflight?
4. Can the new event-driven `poly_maker_loop` coexist with existing bar-driven `poly_updown_loop`?
5. If we use a new wallet for maker strategies, how is allowance preflight configured?

---

## 🆘 If stuck

- Strategy logic question → check the Python reference in `shadow_engine/`
- Infrastructure question → check what's on VPS Ireland (`/opt/tradingvenue/backend/app/`)
- Performance question → check `TV_AGENT_HANDOFF_2026_05_18.md` §"Performance requirements"
- Why-it-works question → check the per-strategy spec or supporting research

---

## 🏁 Definition of "DONE"

All 3 strategies running in LIVE mode on Ireland VPS, generating real PnL data, with:
- ACC-M producing $25-50/day (positive)
- MAS producing $30-100/day (positive)
- ACC-H producing $50-150/day (positive)
- Total: $100-300/day on $200 capital
- 30-day Sharpe > 1.5
- Max 24h drawdown < $30 per strategy
- No critical alerts triggered
