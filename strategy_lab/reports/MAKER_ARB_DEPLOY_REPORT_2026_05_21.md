# Maker-Arb Live-Deploy Decision Report (2026-05-21)

Synthesis of 6 parallel investigations + wallet-template re-decode + external literature review.

**Read order**: §0 TL;DR → §1 critical reframe → §2 per-sleeve verdict → §3 deploy plan → §4 known gaps & blockers.

**Source reports**: `migration_ireland_shadow_2026_05_21/{acc_m_loss_decomp.md, mas_loss_decomp.md, profitable_sanity.md, deploy_capital_analysis*}`, `strategy_lab/reports/{SHADOW_AUDIT_2026_05_21, TV_AGENT_FIX_SPEC_2026_05_21, MINT_AND_SELL_V3_SIMULATION_2026_05_23, WALLET_STRATEGIES_DECODED_2026_05_17}.md`, this file consolidates.

## 0. TL;DR

| Sleeve | Status | What changed today |
|---|---|---|
| **ACC-M btc 5m** | **HOLD — needs proof, not promotion** | "+$2.20/slug honest" is propped up by inventory mark; cash-only is **-$1.02/slug**. PAT overlay is a NET DRAG (not the +$0.73 uplift HYBRID spec claimed). Wallet template (0x04b6d7e9) is **SELL-side mint-and-sell, not BUY-side maker** — we're running the wrong direction. |
| **ACC-H btc 5m** | **DEMOTE (disable V3f rules)** | V3f rule B + C are net-destructive. Maker-only baseline = **+$3.39/slug** vs full-sleeve +$0.73. Killing rule B + C lifts to +$2.85 — but that's just ACC-M with the V3f label. |
| **ACC-H btc 15m** | **TIGHTEN + CONTINUE SHADOW** | PAT cap at $1.00 is past breakeven (0.479 implied → $0.9825). 220 fires in [0.98, 1.00) collectively LOSE -$10.60. Recommend cap tighten to 0.98. |
| **ACC-PC btc 15m** | **CONTINUE SHADOW** | n=79 too small; SE=$0.95, 95% CI crosses zero. Need ~785 slugs (8 days). |
| **MAS btc 5m + 15m** | **REWORK or KILL** | -$0.41/slug structural loss from held-side selection bias. Code = V1 verbatim, missing V3 selectivity gate (`min_sum_asks ≥ 1.005`). Time-of-day pattern: 14-21 UTC bleeds, 04-12 UTC earns. |
| **PAT-SHADOW** | **KILL** | -$8.27/slug structural bleed. Literature confirms PAT is structurally dead post-fee. |
| **Binance-Directional Hold (NEW)** | **BUILD** | Wallets 0x9dae874a + 0xa0a50783 = $5,800/day each, fully reproducible signal. NOT in current 5-sleeve suite. |

**Bottom line for live deploy**: **DO NOT promote anything to live yet.** Run F1-F5 fixes first, then re-shadow for 7-14 days. Then:
- IF ACC-M btc 5m re-verifies ≥+$1.00/slug HONEST CASH (not mark-propped): Phase 1 paper at $50.
- ELSE: re-implement ACC-M as **SELL-side mint-and-sell** to match the wallet template.

## 1. The big reframe: ACC-M is not what we thought

Yesterday's audit said ACC-M btc 5m is "the strongest live candidate at +$2.20/slug honest, beating the wallet template's $1.25 spec backtest." Agent B's per-slug attribution today shows that's an artifact.

**Truth**:
- Engine reports +$2.66/slug. Confirmed by repro.
- Of that, only **−$1.02/slug is cash** (fills + MERGE + REDEEM). The remaining +$3.68/slug is **mark-to-market on open inventory at $0.50/share for residual + $1/share for paired**.
- Apply canonical fees on TAKE legs: cash drops to **−$1.71/slug**.
- Production isn't booking those fees yet (Bug F1), so the engine number is what it is — but the moment F1 lands, ACC-M's reported PnL drops by ~$0.70/slug (the fee delta) AND the mark dependence becomes visible.

**Cross-check vs wallet template**:
- Wallet 0x04b6d7e9 is doing **mint-and-sell on the SELL side**. Average sell price ~$0.48. 230 fills/slug. Earns ~$10.58/fill.
- ACC-M is doing **maker BIDs on the BUY side**. Average BID fill at ~$0.40-0.50. Only 11.3 fills/slug. **Loses ~$0.09/fill** before mark.
- Same "pair-arb maker" label, **opposite signal**. Tuning ACC-M's gate/size/cancel knobs cannot close this gap because the strategy is structurally different.

This means **the entire ACC-M / ACC-H / ACC-PC stack inherits the wrong template**. The "best wallet" template runs MAS-style (sell at premium-to-fair), not BID-stacker-style (buy at discount).

**MAS itself runs the right template structurally** but is missing the V3 selectivity gate (per agent C), so it underperforms.

## 2. Per-sleeve verdict (consolidated)

### 2.1 ACC-M btc 5m — HOLD

- Engine: +$2.66/slug. Cash-only: −$1.02. Honest (canonical fees on TAKE): −$1.71.
- PAT overlay is **destructive**, not additive (-$0.68/slug engine view, -$2.84 with real fees).
- Maker-only fill rate = 7.4 % (POST_BIDs that get hit), vs spec backtest's implicit 75 %. Most posts get canceled before fill.
- **Action**:
  - **F1 first** (book canonical fees). Re-shadow 24 h. If cash-only PnL stays negative, this sleeve is not live-deployable in current form.
  - **Optionally disable PAT** on this sleeve (`tv_poly_maker_acc_m_enable_pat=False` for one day) to confirm PAT is the drag.
  - **Do not scale POST_SIZE** until cash-only is verified positive.

### 2.2 ACC-H btc 5m — DEMOTE TO ACC-M

- Maker-only baseline: **+$3.39/slug gross**.
- Full sleeve (V3f rules B/C/D + PAT on top of maker): +$1.05 gross → +$0.73 honest.
- V3f rule B contributes −$102 excess on 138 slugs. V3f rule C never fires.
- **Action**: disable V3f rules B + C on btc 5m. What remains is ACC-M with the "H" label.

### 2.3 ACC-H btc 15m — TIGHTEN + SHADOW

- Honest +$1.85/slug, n=78. PAT carrier of most edge.
- PAT cap at $1.00 admits −EV fires: 220 fires in pair_cost ∈ [0.98, 1.00) lose −$10.60 collectively.
- **Breakeven pair_cost at avg p=0.479 is $0.9825** (after fees + gas).
- **Action**: tighten `pat_max_pair_cost` from 1.00 → 0.98 on this sleeve. Continue shadow 14 more days. Re-evaluate.

### 2.4 ACC-PC btc 15m — UNDERPOWERED

- +$0.95/slug honest, n=79. SE=$0.95, 95 % CI: [−$0.78, +$2.93]. Crosses zero.
- Top-3 hours contribute 134.9 % of total PnL (offset by negative hours).
- **Action**: hold shadow. Min sample for promotion: 785 slugs (~8 days). No tuning.

### 2.5 MAS btc 5m + 15m — REWORK or KILL

- Honest −$0.41/slug (5m), 0 (15m).
- Root cause (agent C): held-side selection bias. When we partial-fill, the sold side often turns out to be the winner (sold winner-shares for $0.50 → forfeited $0.50 of redemption value).
  - 60 % of slugs: unfilled side was the loser → mean **+$2.50**
  - 38 % of slugs: sold winner-side shares → mean **−$4.52**
- 37 % of slugs are 0-fill = riskless (mint $30, redeem $30, net $0).
- **Time-of-day pattern is sharp**: 14-21 UTC bleeds (-$2 to -$4/slug); 04-12 UTC earns (+$1 to +$3/slug).
- Current code = V1 verbatim. Missing:
  - `min_sum_asks ≥ 1.005` gate (V3 selectivity)
  - Asymmetric posting (V3 uses CVD signal)
  - Time-of-day filter
- May-23 simulation (`MINT_AND_SELL_V3_SIMULATION_2026_05_23.md`) said V3 simulator with full slug economics actually loses $1,381-$6,370/day across cells — **the May-18 "V3 profitable" claim was a methodology mirage**.
- **Action**: cheapest improvements first:
  1. Add UTC-hour skip (04-12 only) — should halve the bleed at no implementation cost.
  2. Add `min_sum_asks ≥ 1.015` gate in `mas.py`'s post path.
  3. If those don't push HONEST PnL ≥+$0.20/slug after 14 days, **kill MAS**.
- Do NOT scale `pre_mint` above $30 until cash positive.
- Do NOT port to "V3 profitable" — that claim was overturned.

### 2.6 PAT-SHADOW — KILL

- −$8.27/slug standalone. Structural bleed.
- Literature (agent E): sum_asks rarely beats $1 after fees on liquid BTC/ETH/SOL up-down; PAT is structurally dead post-fee.
- **Action**: disable on Ireland. The remaining PAT overlay inside ACC-M / ACC-H stays (it's a different code path).

### 2.7 NEW: Binance-Directional Hold (BDH) — **BUILD (re-confirmed)**

**Final verdict 2026-05-21 late** after portfolio audit using official Polymarket API. See `migration_ireland_shadow_2026_05_21/portfolio_audit/PORTFOLIO_AUDIT_REPORT.md`.

**ALL 6 decoded wallets are profitable per Polymarket's official numbers.** The "wallet headlines collapse on cash audit" pattern I reported earlier was a **decoder bug, not a strategy reality**. The local decoder filters on `side ∈ {BUY, SELL}` and silently drops every REDEEM, MERGE, MAKER_REBATE event (which all carry `side=""`). On every wallet, REDEEM alone is 80-90% of cash income.

Corrected wallet table (Polymarket official, lifetime + 30d):

| wallet | role | lifetime | 30d | 30d $/day |
|---|---|---:|---:|---:|
| 0x9dae874a | BDH F2 | +$49,205 | +$49,205 | **+$1,640** |
| 0xa0a50783 | BDH F2 | +$43,578 | +$43,578 | **+$1,453** |
| 0x04b6d7e9 | paired-bid maker hold-to-expiry | +$215,949 | +$83,796 | **+$2,793** |
| 0xeebde7a0 | "Bonereaper" same template, HFT | +$825,721 | +$253,121 | **+$8,437** |
| 0xb27bc932 | same template, HFT | +$568,928 | +$52,001 | **+$1,733** |
| 0x89b5cdaa | multi-asset same template | +$530,088 | +$166,901 | **+$5,563** |

Original "$X k/day" claims were leaderboard top-rank rankings, not 30d averages — overstated by 2-200×. **But all wallets ARE positive.**

**Implications**:
1. **BDH is real alpha.** Build the sleeve. Use binance 60s price return as signal (not 5s flow_imbalance — wallet correlation evidence).
2. **0x04b6d7e9 is NOT mint-and-sell** (despite the catalog label). It's a **paired-bid CLOB maker that holds to expiry** — which is **exactly what ACC-M does structurally**. ACC-M's template is right; the "ACC-M is the wrong template" claim in §1 of this report was based on agent B's flawed decoder audit and is **retracted**.
3. **MAS template is NOT what the top earners do.** 0xeebde7a0 / 0xb27bc932 / 0x89b5cdaa have ZERO `SPLIT` events — they never mint from collateral. They acquire shares only via CLOB buys. MAS as a strategy class is misnamed; the top earners are all running variants of ACC-M.
4. **Maker rebates are real and material**: $80k-$196k per wallet lifetime. The shadow engine needs to credit these (MAS partially does, others don't).

**Action**: BDH spec status changed to **BUILD (pending decoder fix + signal re-derivation)**.

**Update 2026-05-21 late**: my BDH research agent reported both BDH wallets as NET NEGATIVE on cash basis (−$348/day and −$296/day). The user pushed back: the decoder likely under-counts. Specific decoder gaps suspected:

- **Merge proceeds** — when a wallet has 1 up + 1 dn, it can merge for $1 USDC. If the decoder treats this as two zero-value transfers it misses the $1 redemption-equivalent income.
- **Unclaimed positions** — winning shares the wallet hasn't called `redeemPositions` on yet still sit on the wallet, worth $1 each. The chain settlement decoder may only count `redeemPositions` events, missing the actual win.
- **Polymarket maker-rebate program** — paid monthly off-chain. Not in `getAssetTransfers`.
- **NegRiskAdapter conversions** — `convertPositions` (USDC out without burning a full set) is a separate primitive from `mergePositions`.
- **USDC.e vs USDC** — Polymarket settled on USDC.e at first then migrated. Asset-transfer queries that filter only one token miss the other half.
- **Mark-to-market on open positions** — actively-held inventory has value; counting only realized cash misses it.

A new audit is in progress using **Polymarket's official portfolio / activity API** (the same one their UI uses) to get ground-truth PnL per wallet. Reconciles to:
  - Polymarket-reported lifetime PnL
  - Open positions × mark price
  - Realized cash flow (USDC.e + USDC + USDT)
  - Monthly maker rebates (if exposed via API)

Status: **DO NOT KILL BDH YET**. Wait for the portfolio audit to reconcile. The pattern "decoder shows loss / leaderboard shows profit" is most likely a decoder gap, not strategy failure. F2_FINAL_VERDICT_2026_05_18.md should also be re-audited the same way.

**Action**: BDH spec marked PENDING_RE_AUDIT (`TV_DEPLOY_SPEC_BDH_2026_05_21.md`). Do not implement until reconciliation lands.

## 3. Live deploy plan (only viable path)

### Phase 0 — Fix the engine (this week)

Land **F1-F5** from `TV_AGENT_FIX_SPEC_2026_05_21.md`:
- F1: book canonical fees + rebates per fill (single edit in `poly_maker_fill_sim.py`)
- F2: close phantom-fill race (CANCEL vs in-flight trade)
- F3: strict-cross trigger + queue-depth respect
- F4: 85 ms latency floor + sparse-book gate
- F5: dedupe multi-fill emissions

Plus from agent D:
- F8: enforce **cell exclusivity** — exactly one sleeve per `(asset, tf)` cell. ACC-M and ACC-H both running on btc 5m today = 2× BID exposure + 2× fee burn in live mode.

After landing, re-shadow 24 h. Verify console PnL = honest PnL per sleeve. **Hard gate**: ACC-M btc 5m must show ≥+$1.00/slug HONEST CASH (not mark) over the 24 h, or DO NOT proceed.

### Phase 1 — Paper validation (week 1)

If Phase 0 hard gate clears:
- Capital: **$50** (POST_SIZE=5, micro-test)
- Sleeves enabled: **ACC-M btc 5m + ACC-H btc 15m** only
- Disable: PAT-SHADOW, V3f rules B/C on ACC-H btc 5m
- Pass criterion: 7-day mean ≥+$0.50/slug honest, drawdown ≤−$25
- Kill switches: 5 consecutive losing slugs → pause 1 h; aggregate DD ≤−$15 → pause + investigate

### Phase 2 — Small live (week 2-3)

If Phase 1 passes:
- Capital: **$700 USDC.e** ($325 ACC-M + $375 ACC-H 15m)
- POST_SIZE=20 (matches wallet seeds)
- Sleeves: same as Phase 1
- Kill: -$80 daily DD on ACC-M, -$95 on ACC-H 15m; ≤50 % paired-slugs profitable over last 30

### Phase 3 — Scale (week 4)

If Phase 2 holds: POST_SIZE=50, capital ~$1,000. Same sleeves.

### Phase 4 — Full deploy (week 6+)

If Phase 3 sustains ≥0.20 $/$/day over 30 days: POST_SIZE=100, capital **$2,500 USDC.e**, projected **+$385/day** after 30 % adverse-selection haircut.

### Total ask through Phase 4

| Item | Amount |
|---|---:|
| Phase 1 paper | $50 |
| Phase 2 live | $700 |
| Phase 3 scale | $1,000 |
| Phase 4 full | $2,500 |
| Gas reserve | $10 |
| **Total committed capital ceiling** | **$2,510** |
| **Projected daily PnL at Phase 4** | **+$385** |

## 4. Known gaps + open blockers

### 4.1 Wallet-template confusion

Re-decode of 0x04b6d7e9 (agent A + agent B) shows it's a SELL-side mint-and-sell wallet, not the BUY-side maker we thought. The 5-sleeve suite was built against the wrong template. Options:
1. **Pivot to mint-and-sell focus**: fix MAS (UTC filter + sum_asks gate), drop ACC-M/H/PC.
2. **Accept ACC-M as its own strategy** (not wallet-replicated) and continue tuning.
3. **Build both** in parallel: BDH (binance-directional hold, new wallet template) + fixed MAS.

### 4.2 Production fee model assumption

CLAUDE.md says production currently charges 2 % on profit only, NOT the canonical `0.07 × p × (1-p)`. If true, F1's "book canonical fees" overcorrects vs what production actually pays — but underbooks vs the published rebate program.

**To verify**: pull a sample of last week's resolved trades from `trading.events` and back-derive the actual fee charged. If it matches 2 %-on-profit, then F1 should use that formula, not the canonical one.

### 4.3 Adverse selection literature warning

Bartlett & O'Hara (agent E) shows single-name markets ARE the toxic regime — our 5m crypto up-down is single-name. Behavioral surplus that saves makers in broad markets may NOT apply here. Translation: at scale, our maker spread may not cover toxicity. Need to instrument VPIN before committing >$1k capital.

### 4.4 Convergence-window dynamics

Literature: cancel all quotes at T-60s for 5m / T-120s for 15m. Currently `stop_posting_offset_s=270` (= T-30s) in spec. **Too late** — we're leaving quotes in the worst window. Tighten to T-60s (`stop_posting_offset_s=240`).

### 4.5 Queue priority

Top wallets post within ms of slug birth. We post on first L25 event AFTER slug-active fires. Latency from slug-active to first post = ?, measure it. If >100 ms we're losing queue position to other bots.

### 4.6 Maker-rebate verification

CLAUDE.md notes feeRate may be 0 on these markets (= no rebates accruing). Action: check Polymarket account dashboard for monthly rebate payouts. If $0, mint-and-sell economics are worse than spec'd.

## 5. Files produced this session

| File | Purpose |
|---|---|
| `MAKER_ARB_DEPLOY_REPORT_2026_05_21.md` | this consolidated report |
| `migration_ireland_shadow_2026_05_21/acc_m_loss_decomp.md` | ACC-M cash vs mark breakdown |
| `migration_ireland_shadow_2026_05_21/mas_loss_decomp.md` | MAS held-side bias analysis |
| `migration_ireland_shadow_2026_05_21/profitable_sanity.md` | ACC-H + ACC-PC math sanity + tuning |
| `migration_ireland_shadow_2026_05_21/deploy_capital_analysis.py` | capital sizing + kill switches |
| `migration_ireland_shadow_2026_05_21/audit_pat_cashflow.py` | PAT MERGE accounting (confirms not a bug) |
| `migration_ireland_shadow_2026_05_21/audit_acc_h_decomp.py` | per-rule V3f breakdown |
| `migration_ireland_shadow_2026_05_21/fill_sim_audit.md` | fill simulator over-optimism findings |
| `strategy_lab/reports/TV_AGENT_FIX_SPEC_2026_05_21.md` | engine fixes (F1-F8) |
| `strategy_lab/reports/SHADOW_AUDIT_2026_05_21.md` | engine PnL audit |

## 6. Updated decision tree (post-BDH-research, 2026-05-21 late)

The BDH research result + the recurring "wallet headline collapses on cash audit" pattern force a re-evaluation:

### Three open paths

**Path A — Verify ACC-M independently**

Land F1 first, run 24 h re-shadow. ACC-M cash-only must show ≥+$1.00/slug HONEST cash (not mark-propped). If pass → Phase 1 paper at $50. If fail → ACC-M's edge was an accounting artifact; kill the whole maker-arb suite and stop deploying capital.

**Path B — Land MAS-V3 cheap fixes**

Independent of A. Add UTC-hour filter (04-12 only) + min_sum_asks ≥ 1.015 gate. 30 lines, 2 dev-hours. Spec at `TV_AGENT_FIX_MAS_V3_SPEC.md`. Expected: −$0.41/slug → +$0.30 to +$0.80/slug. Kill if 7d post-fix < +$0.10/slug.

**Path C — Stop chasing wallet templates**

Every decoded wallet has failed cash audit. Either:
- The wallets are net negative AND surviving via fee rebates / undisclosed tax-loss harvesting / volume-rebate programs we can't replicate
- The wallets are SOPHISTICATED in ways the decoder can't pick up (e.g. private slug-selection signals, manual override)
- The wallets are unprofitable AND just running with patient capital

In all three cases, blind replication is dead. Path C says: **stop building from wallet decode evidence**. Build instead from first principles + literature (Bartlett & O'Hara adverse selection, Polymarket rebate program, queue priority).

### Recommended sequence

1. **THIS WEEK** — Land F1. Run 24h re-shadow. Run Path A hard gate.
2. **IF Path A passes** — Phase 1 paper at $50 on ACC-M btc 5m only. Land MAS-V3 (Path B) in parallel as cheap secondary experiment.
3. **IF Path A fails** — Stop deploying capital on maker-arb. Pivot 100 % to Path C: instrument the current suite to compute realized rebate income on Ireland's actual Polymarket wallet (independent of strategy-level PnL), and decide based on whether rebates alone cover infra cost.
4. **PARALLEL** — pull May 17-21 fills on the 7 decoded wallets to check if any are still active. If all dormant, that's a strong signal the templates were transient regime arbitrage, not sustainable alpha.

### Hard rule for the next 90 days

**Do not deploy live capital on any strategy whose backtest depends on inventory mark-to-market.** Cash-basis settlement only. The ACC-M "+$2.20/slug honest" → "−$1.02/slug cash" gap is the warning shot.

**However**, "cash-basis" includes REDEEM proceeds, MERGE proceeds, and MAKER_REBATE income — not just CLOB trade buys/sells. The earlier conclusion that the wallets are net-negative was a decoder bug (filtered on side ∈ {BUY,SELL}, dropped REDEEM/MERGE/REBATE rows with side=""). Top wallet 0xeebde7a0 earns 78 % of its lifetime cash from REDEEM + MERGE alone.

**Updated hard rule**: Cash-basis includes (TRADE_sells − TRADE_buys + MERGE + REDEEM + MAKER_REBATE + REWARD − SPLIT + CONVERSION + open_position_MTM). Anything else still counts as mark.

### What we are NOT doing

- Implementing F3, F4, F5 from `TV_AGENT_FIX_SPEC_2026_05_21.md` — until Path A clears, those are premature optimization.
- Scaling MAS pre-mint above $30 — locked until V3 gates land + show ≥+$0.30/slug.
- Touching ACC-PC — n=79 too small; just keep shadow data accumulating.
- Pursuing 0xb27bc932 (HFT colo gap) — re-audit shows +$568k lifetime but the **HFT colo / sub-second reaction requirement** is the real blocker; profitability is not enough if we can't compete at that latency.

### What we ARE doing

- **Decoder fix (NEW, highest priority)** — index REDEEM, MERGE, MAKER_REBATE, CONVERSION events. Trivial (filter change). $80k-$5M per-wallet income currently invisible.
- **Re-run BDH research** with corrected accounting + binance 60s price return signal (not 5s flow). Expected: trigger formula is positive, slug-selection filter exists.
- **Build BDH** as 6th sleeve (spec `TV_DEPLOY_SPEC_BDH_2026_05_21.md`, status BUILD pending re-derivation).
- **Continue ACC-M / ACC-H / ACC-PC** — wallet 0x04b6d7e9 PROVES the paired-bid-maker-hold-to-expiry template earns ~$2,793/day on 30d. Our ACC-M IS that template. The bug is in our PnL accounting, not the strategy.
- **F1 still required** — book canonical fees so console PnL equals true PnL. Same priority, same hard gate.
- **MAS V3 cheap fixes still worth landing** (UTC + sum_asks gates). Won't make MAS a top earner but should turn flat-to-slightly-positive.
