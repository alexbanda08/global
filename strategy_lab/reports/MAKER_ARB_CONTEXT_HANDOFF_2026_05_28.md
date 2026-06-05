> ⏭️ **SUPERSEDED by `MAKER_ARB_CONTEXT_HANDOFF_2026_05_29.md`** — start there. The
> 2026-05-29 session refreshed canonical to May 29, verified the maker-arb sleeves are
> net-negative (no reproducible edge), and found a new directional latency-taker candidate.
> Several §2 numbers below (e.g. "+$4.44/slug") were later shown to be survivorship bias.

# Maker-Arb Project — Context Handoff (2026-05-28)

> **Read this first to continue the maker-arb work in a fresh session.** Self-contained: what we're doing, current state, every key finding, what's deployed, what's pending, the gotchas, and exact next steps.

---

## 0. What this project is

Polymarket maker-arb strategy suite running in **shadow mode** on the **Ireland VPS** (`ssh vps_ireland`, code at `/opt/tradingvenue/`). The strategies were reverse-engineered from on-chain-decoded profitable wallets. Goal: validate them in shadow, fix bugs, then promote the best to **live** with real capital.

**Market**: Polymarket BTC/ETH/SOL up-down binary markets (5m + 15m windows). Each market = a paired CLOB (up_token + dn_token) that resolves $1/$0 at slug end via chainlink.

**Core mechanic**: post maker BIDs on both sides when `sum_bids < $1.00`, accumulate paired inventory, MERGE pairs for $1 (minus 0.25% protocol fee), redeem leftover winners at resolution.

---

## 1. The sleeves (8 running: 4 V1 + 4 V2, PAT killed)

| sleeve_id | what | status |
|---|---|---|
| `poly_acc_m_btc_5m_shadow` | ACC-M V1 — paired-bid maker + PAT taker overlay | running (V1 control) |
| `poly_acc_m_v2_btc_5m_shadow` | ACC-M-V2 — **PAT disabled** + convergence-cancel | running ✓ best-fixed |
| `poly_acc_h_btc_15m_shadow` | ACC-H V1 — ACC-M + V3f composite taker | running (control) |
| `poly_acc_h_v2_btc_15m_shadow` | ACC-H-V2 — + convergence-cancel T-120s | running ✓ **strongest** |
| `poly_acc_h_v2_eth_15m_shadow` | ACC-H-V2 on eth_15m (NEW cell) | running ✓ |
| `poly_acc_pc_btc_15m_shadow` | ACC-PC V1 — ACC-M + pair-completion taker | running (control) |
| `poly_acc_pc_v2_btc_15m_shadow` | ACC-PC-V2 — + convergence-cancel | running ✓ |
| `poly_acc_pc_v2_eth_15m_shadow` | ACC-PC-V2 on eth_15m (NEW cell) | running ✓ |
| `poly_mas_v2_btc_5m_shadow` | MAS-V2 — mint+sell, min_ask=0.52, sum_asks gate | running (≈flat) |
| `poly_mas_btc_15m_shadow` | MAS V1 btc 15m | running (≈flat) |
| ~~`poly_pat_shadow_btc_5m_shadow`~~ | PAT standalone | **KILLED** (`TV_POLY_MAKER_KILL=pat_shadow:btc_5m`) |

Strategy code: `/opt/tradingvenue/backend/app/strategies/polymarket/maker/{acc_m,acc_h,acc_pc,mas,pat_shadow}.py`
Engine: `engine/poly_maker_fill_sim.py` (fill sim) + `poly_maker_loop.py` + `main.py` (registration)
Shadow CSVs: `/var/log/tv/maker/{sleeve}_{date}.csv`
Config: `/etc/tv/tradingvenue.env`

---

## 2. CURRENT PERFORMANCE (corrected, 2026-05-28)

**Use the FULLY-SETTLED measure** (slugs ending with inventory=0, fully resolved, uncensored). This is the only unbiased number from short windows:

| Sleeve | n_settled | Win% | $/slug (POST_SIZE=20) |
|---|---:|---:|---:|
| **ACC-H-V2 btc 15m** | 41 | 73.2% | **+$4.44** ← best |
| ACC-PC-V2 eth 15m | 33 | 84.8% | +$4.78 |
| ACC-H-V2 eth 15m | 19 | 89.5% | +$5.24 (small n) |
| ACC-PC-V2 btc 15m | 42 | 69.0% | +$3.21 |
| ACC-M-V2 btc 5m | 157 | 53.5% | +$0.85 (most data, weakest edge) |
| MAS-V2 btc 5m | settled | — | ≈$0 (mint+redeem, asks rarely fill) |

**All sleeves are positive on the clean measure.** ACC-H-V2 btc 15m is the strongest.

---

## 3. 🚨 CRITICAL MEASUREMENT GOTCHA (do not repeat my mistakes)

Three ways to slice per-slug PnL give wildly different answers. **Only #3 is correct:**

1. **REDEEM-slugs only** → biased HIGH (only counts slugs where leftover directional inventory won). I wrongly reported "+$3.07/slug, 64.6% WR" this way.
2. **All traded slugs, cash basis** → biased LOW (right-censored: recent slugs have unsettled residual inventory; their redemption isn't in the data yet). I wrongly reported "−$1.77/slug" this way.
3. **Fully-settled slugs (final inv_up=inv_dn=0)** → CLEAN, uncensored. Use this. +$0.85 to +$4.44/slug.

Why: ACC-M MERGES pairs for $1 mid-slug, so most slugs have NO REDEEM event. "Resolved = REDEEM fired" is wrong — must use "slot window elapsed AND inventory settled."

Also: **canonical resolutions only extend to 2026-05-27 13:25 UTC**; shadow data is May 28. Can't settle May-28 residual against chainlink until canonical is refreshed from VPS3. To get the true number on residual slugs, refresh canonical first.

---

## 4. ENGINE CORRECTNESS — VERIFIED ✅ (no bugs)

Full audit 2026-05-28 (`strategy_lab/reports/ENGINE_CORRECTNESS_AUDIT_2026_05_28.md` + 4 sub-reports in `migration_ireland_audit_2026_05_28/engine_audit/`):

- **Per-slug accounting EXACT** — 10 hand-traced slugs reconcile to $0.000000.
- MINT/MERGE/REDEEM/CLOB-fill all economically correct vs on-chain CTF.
- MERGE carries a **0.25% protocol fee** (`pairs × 0.9975`) — engine applies it; naive backtests miss it.
- Fill sim: queue model, book-cross, 25bps adv-sel haircut, phantom-fill guard — all realistic.
- F1 (canonical fee booking) ALREADY DEPLOYED — `taker_fees` now populated, was $0 pre-May-25.

**Minor gaps (not bugs)**:
- MINT + REDEEM gas not subtracted (~$22/day overstatement)
- Fill sim fills 100% on queue-drain (no partial fills) → 10-25% over-fill, mildly optimistic
- Fee model = `0.07·p(1-p)` but live may be 2%-on-profit (conservative direction — see §5)

**The strategies and engine are SOUND.** Earlier negative numbers were my analysis slicing the data wrong, not Ireland bugs.

---

## 5. OPEN QUESTION — fee model (highest-value unknown)

Shadow charges taker fee `0.07 × p × (1-p)` per share. CLAUDE.md (verified vs 25,900 production resolution events) says live BTC/ETH/SOL up-down markets actually charge **2%-on-profit-only** (no fee on losses, 2% on winning-leg profit). If true → shadow over-charges → shadow PnL is **understated** (real live would be BETTER).

**To resolve**: pull recent resolved fills from VPS3 `trading.events`, back-derive the actual fee. Spec written: `strategy_lab/reports/TV_AGENT_FIX_FEE_MODEL_SPEC.md` (has the SQL + the selectable-fee-model code).

---

## 6. SPECS READY FOR TV AGENT (Ireland deploy)

All in `strategy_lab/reports/`:

| Spec | Purpose | Status |
|---|---|---|
| `TV_AGENT_FIX_F1_SPEC.md` | Canonical fee booking | ✅ ALREADY DEPLOYED |
| `TV_AGENT_SPEC_NEW_SLEEVES_V2_2026_05_27.md` | 4 V2 sleeves + PAT kill + eth_15m | ✅ DEPLOYED (verified firing) |
| `TV_AGENT_FIX_CONVERGENCE_CANCEL_SPEC.md` | stop_posting_offset_s gates | ✅ DEPLOYED (verified firing at right offsets) |
| `TV_AGENT_FIX_DASHBOARD_CUMULATIVE_PNL_SPEC.md` | lifetime PnL (not daily-reset) | ⏳ PENDING |
| `TV_AGENT_FIX_FEE_MODEL_SPEC.md` | selectable fee model + verify 2%-on-profit | ⏳ PENDING (verify first) |
| `TV_AGENT_FIX_MAS_V3_SPEC.md` | MAS gates (superseded by V2 spec) | partial |

**Still pending for TV agent**: dashboard cumulative PnL, fee-model resolution, optional MINT/REDEEM gas booking, optional partial-fill knob.

---

## 7. DASHBOARD PnL — known quirk (not a bug)

Operator dashboard shows **TODAY UTC only** (resets at midnight). Confirmed: matches `today-only with mark-to-market` computation. Spec to add lifetime columns: `TV_AGENT_FIX_DASHBOARD_CUMULATIVE_PNL_SPEC.md`. The mark-to-market in the dashboard inflates vs cash (open paired inventory marked $1/pair, residual $0.50) — so today's screen number > realized cash.

---

## 8. LIVE-vs-SHADOW RISKS (read before deploying real capital)

Full register: `strategy_lab/reports/LIVE_VS_SHADOW_RISK_REGISTER_2026_05_28.md`. Shadow simulates book + settlement correctly but is blind to: partial fills (R1), cancel-vs-fill race (R2), state-dependent adverse selection beyond 25bps (R3), self-competition when 2 sleeves share a cell (R4), capital/gas limits (R5/R6), redemption lag (R7), rate limits (R8), oracle disputes (R12), market impact at scale (R13).

**Expect 40-70% of shadow PnL to survive to live at small size.**

---

## 9. BEST SLEEVE TO TEST LIVE + MINIMUM CAPITAL

- **Best**: `ACC-H-V2 btc 15m` — +$4.44/slug clean, 73.2% WR, n=41.
- **Minimum capital**: ~$25-30 (≈$20 USDC.e wallet at POST_SIZE=5 + ~$5-10 MATIC gas).
- **Feedback rate**: 15m = ~4 resolutions/hour to watch.
- ⚠️ Before live: pick ONE sleeve per cell (ACC-H and ACC-PC both run btc_15m + eth_15m — in LIVE they'd be the same wallet competing with itself, R4). Use `TV_POLY_MAKER_KILL`.

---

## 10. DEFERRED / KILLED

- **BDH (Binance-Directional Hold)** — DEFERRED. Wallets profitable per official Polymarket API (+$1,640/$1,453/day) but the trigger loses on broad universe; edge is a slug-selection signal we can't decode without CLOB WS event tape (~100GB/mo) + cross-exchange basis. Spec: `TV_DEPLOY_SPEC_BDH_2026_05_21.md` (status DEFER). NOT maker-arb — it's directional.
- **PAT-SHADOW standalone** — KILLED (−$10/slug structural bleed).
- **Decoded wallets** — all 6 audited are profitable per official Polymarket API ($49k-$825k lifetime). Our local decoder had a bug (filtered side∈{BUY,SELL}, dropped REDEEM/MERGE/REBATE) — FIXED locally in `strategy_lab/wallet_hunt/cash_pnl.py`. The "ACC-M template" wallet (0x04b6d7e9) is a paired-bid maker hold-to-expiry = exactly what ACC-M does.

---

## 11. KEY FILE LOCATIONS

**Reports** (`strategy_lab/reports/`):
- `ENGINE_CORRECTNESS_AUDIT_2026_05_28.md` — engine is exact
- `LIVE_VS_SHADOW_RISK_REGISTER_2026_05_28.md` — 13 live risks
- `MAKER_ARB_DEPLOY_DECISIONS_2026_05_27.md` — per-sleeve deploy plan
- `SHADOW_PNL_REAUDIT_RUNBOOK_2026_05_21.md` — how to re-audit after fixes
- `TV_AGENT_*_SPEC.md` — all the fix specs (see §6)

**Audit data/scripts** (`migration_ireland_audit_2026_05_28/`):
- `maker_csvs/` — May 27-28 shadow CSVs (V1 + V2)
- `source/` — current Ireland strategy + engine source
- `engine_audit/` — 4 audit sub-reports + per_slug_recon.py
- `best_sleeve_for_live.py`, `audit_v2_logic.py` — analysis scripts
- ⚠️ these analysis scripts use the BIASED REDEEM-only or all-slug measures — **redo with fully-settled filter** (§3)

**Canonical data** (`data/v4/canonical/`): 32.66 days resolutions (through May 27 13:25), L25 books through May 26, klines through May 26. Refresh via `migration_2026_05_27/` scripts (`load.py` is the API).

---

## 12. NEXT STEPS (priority order for fresh session)

1. **Verify fee model** — pull VPS3 `trading.events`, confirm 2%-on-profit vs 0.07-curve (`TV_AGENT_FIX_FEE_MODEL_SPEC.md` §2 SQL). This is the biggest unknown.
2. **Refresh canonical resolutions** to cover May 28 so the residual-inventory slugs can be settled against chainlink → get the TRUE (not censored, not biased) per-slug PnL for all V2 sleeves.
3. **Re-run the clean audit** using the fully-settled measure (§3) on a longer window (7+ days of V2 data) for statistical confidence.
4. **Decide live test**: ACC-H-V2 btc 15m at ~$30, ONE sleeve per cell. Write the TV agent spec to flip it to live micro-mode with instrumentation (live-vs-shadow fill-rate delta, realized adv-sel bps, MATIC balance, rejection rate, redemption latency) + kill switches.
5. **Land pending specs**: dashboard cumulative PnL, fee-model selector.
6. **Optional tuning**: tighten ACC-M sum_bids gate to reduce pair-completion overpay.

---

## 13. ONE-PARAGRAPH STATE

The maker-arb suite (V2 sleeves) is **deployed, verified-correct, and net-positive** on the clean fully-settled measure (ACC-H-V2 btc 15m +$4.44/slug @ 73% WR is best; all sleeves green). The Ireland engine computes everything exactly ($0 reconciliation error). PAT was the loss source on V1 ACC-M and is now disabled; convergence-cancel is live and working. No code bugs in engine or strategies — earlier negative readings were my analysis biases (REDEEM-only / censored-cash), now corrected to the fully-settled measure. Two things gate live deployment: (a) verify the real fee model (likely 2%-on-profit = shadow is conservative), (b) pick one sleeve per cell to avoid self-competition. Minimum to start a live watch-test: ~$30 on ACC-H-V2 btc 15m. Expect 40-70% of shadow PnL to survive live.
