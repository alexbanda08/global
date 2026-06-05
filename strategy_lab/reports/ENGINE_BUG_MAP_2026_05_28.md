# Maker-Arb Shadow Engine — Bug Map for Fixes (2026-05-28)

> Source audited: `migration_ireland_audit_2026_05_28/source/` (read-only copy of
> Ireland `/opt/tradingvenue/backend/app/`). 3 parallel auditors + manual
> verification of every load-bearing claim against the actual code. Line numbers
> are from the audited copy; **✓verified** = I opened the code and confirmed,
> **⚠reported** = agent-reported, plausible, not line-confirmed by me.

## TL;DR — the one that matters

The shadow's **realized cash accounting is essentially correct** (that's why the
censoring-reversal analysis, which used pure cash, is trustworthy). The damage is
in the **displayed / tracked PnL**: `slug_pnl_so_far` and the operator dashboard
are **systematically optimistic** because the mark on worthless directional-loser
inventory **never clears at resolution**. Fix the settlement lifecycle (E1) and
the shadow's tracked PnL will finally match the true (negative) cash PnL.

## Severity-ordered summary

| ID | Severity | File:line | Theme | One-liner |
|---|---|---|---|---|
| **E1** | CRITICAL | poly_maker_fill_sim.py:848-874 + shadow_log.py:316-329 ✓ | settlement | Loser slugs never set `redeem_fired` / never zero `inv_loser` → `mark=residual×$0.50` never clears → `slug_pnl_so_far` + dashboard permanently optimistic |
| **E2** | CRITICAL | mas.py:404-449 ✓ | gating | MAS-V2 stacks V3 floor (sum_asks≥1.015) + V2 ceiling (≤1.015) → only ==1.015 passes → inert (0/235 posts) |
| **E3** | HIGH | fill_sim.py:358/507/626/1219 + main.py:3033 ✓ | routing | Single shared fill-sim, `_strategy_cache[slug]` last-write-wins → fills to shared cells (acc_h_v2 & acc_pc_v2 on btc_15m/eth_15m) misrouted/dropped → per-sleeve PnL cross-contaminated; live self-competition |
| **E4** | HIGH | base.py:57-89; fill_sim.py:806/815; acc_m:797, acc_h:320, acc_pc:217 ✓ | fee/parity | Fee = `0.07·p·(1-p)` everywhere; production crypto up-down = 2%-on-winning-profit-only → shadow over-charges taker on losers + accrues phantom maker rebates + gates over-conservative |
| **E5** | HIGH | poly_maker_loop.py:1046-1051; maker_sleeves.py:524-536,762-764 ⚠ | dashboard | Dashboard PnL omits `cash_recovered`; lifetime PnL bakes stale midnight mid-marks + double-counts midnight-spanning slugs |
| **E6** | HIGH | acc_m.py:430-449; acc_pc.py:165-168 ⚠ | convergence | Convergence-cancel only stops new posts; never flattens existing directional residual (the main loss driver) |
| **E7** | MED | acc_pc.py:216 ⚠ | pair-completion | `avg_lead_cost = cash_spent / lead_inv` uses BOTH-sides spend → distorts pair-cost gate (overpay / wrong fires) |
| **E8** | MED | fill_sim.py:1115-1123 ✓ | fill-realism | No partial fills — fills full `order.size` on queue-drain → ~10-25% over-fill (optimistic) |
| **E9** | MED | fill_sim.py:1053-1058 ✓ | adverse-sel | Adverse-sel haircut bids-only and **default-off** (`adv_sel_bps=0`); cannot model state-dependent selection |
| **E10** | MED | fill_sim.py (queue init ~411/934) ⚠ | fill-realism | Zero-depth-at-price → `initial_queue=0` → instant fill on first matching print (optimistic) |
| **E11** | MED | fill_sim.py:476-494 (`_observe_take`) ⚠ | fill-realism | TAKE VWAP walk has no min-book-levels / staleness guard → sparse-book fills (optimistic) |
| **E12** | MED | acc_h.py:308-315 ⚠ | parity | ACC-H pair-cost reads L25 cache with no staleness guard on `on_trade_print` bursts |
| **E13** | MED | maker_sleeves.py:709-719,848-852 ⚠ | dashboard/ops | Inventory card shows last-global row (masks live multi-slug exposure); no guard against two sleeves sharing a cell |
| **E14** | LOW | poly_maker_loop.py:1238 ⚠ | lifecycle | 60s resolution-poll gap → interim mark stale up to 60s post-resolution |
| **E15** | LOW | fill_sim.py `_observe_mint`/`_observe_redeem` ⚠ | accounting | MINT/REDEEM gas not booked (~$22/day optimistic) |
| **E16** | LOW | acc_m.py:424 etc. (getattr default 0) ✓ | ops | Missing `*_stop_posting_offset_s` env silently disables convergence-cancel — no warning |
| **E17** | LOW | fill_sim.py:828 (docstring) ✓ | docs | `_observe_redeem` docstring says `cash_received`; code correctly uses `cash_recovered` |

---

## Detailed findings

### E1 — CRITICAL — Loser-slug mark never clears (the optimism root cause) ✓verified

**Where:** `poly_maker_fill_sim.py:_observe_redeem` (848-874) + `shadow_log.py:_row_from_decision` (316-329).

**Mechanism (verified by reading both):**
- per-slug PnL written to CSV/dashboard is `slug_pnl_so_far = realized_cash + mark`, where
  `mark = paired×$1.0 + residual×$0.50` **if `not redeem_fired`**, else `paired×$1.0` (shadow_log.py:318-321).
- `_observe_redeem` sets `redeem_fired=True` only for the **winning** side, and only when `decision.size > 0`. The early-return at **848-851** (`if decision.size is None or decision.size <= 0: return`) means a **pure directional-loser slug (winner has 0 shares)** never sets `redeem_fired`.
- `inv_loser` is **never zeroed** (explicit by-design comment at 844-846: *"inv_loser stays untouched (worthless residual)"*).
- Result: for a loser slug holding e.g. 20 worthless tokens, `residual=20`, `redeem_fired=False` forever → `mark = 20×$0.50 = +$10` phantom on top of the (correct, negative) realized cash. Empirically: engine mark averaged **+$1.95** vs true **−$8.05** on recovered losers.

**Important nuance:** the **realized cash is correct** (the loser's cost is already in `cash_spent`; `cash_recovered=0` for the unredeemed loser is also correct). The bug is ONLY the mark + the fact the slug never "closes" (inv never returns to 0), which (a) inflates `slug_pnl_so_far`/dashboard and (b) made the censored-residual analysis necessary.

**Fix:**
1. At slot resolution, **always** mark the slug settled: set `redeem_fired=True` and zero **both** `inv_up` and `inv_dn` regardless of whether the winner had shares. Split the 848-851 guard: `slug_state is None` → bail; `size<=0` but valid resolution → still set `redeem_fired=True` and zero loser inventory.
2. Guarantee a resolution hook fires for **every** traded slug (even ones the strategy already popped) — see E14. Without this, slugs whose strategy state was popped never settle.
3. Post-fix, `mark = paired×$1.0 = 0` for losers → `slug_pnl_so_far` collapses to realized cash = correct.
4. (Optional, E17/A6) emit an explicit `EXPIRE` log row crediting $0 + zeroing `inv_loser`, so the CSV is self-contained and the PnL step-change is attributable.

---

### E2 — CRITICAL — MAS-V2 inert (stacked sum_asks gates) ✓verified

**Where:** `mas.py` V3 block (404-421) + V2 block (427-449).

**Mechanism:** `MAS_V3_ENABLED` defaults True (line 194) and runs **unconditionally** before the variant check. V3 Gate-2 (line 420): `if sum_asks < MAS_V3_MIN_SUM_ASKS (default 1.015): return []`. Then for `variant=="v2"` (427), V2 band (448): `if not (min_sum <= sum_asks <= max_sum): return []` with defaults `[1.005, 1.015]`. The two together require `sum_asks ≥ 1.015` **and** `sum_asks ≤ 1.015` → only exactly `1.015` posts → a zero-measure event → **0/235 posts observed**. (Mint-and-sell can't sell → sleeve does nothing.)

**Fix:** make V3 and V2 gates mutually exclusive — when `variant=="v2"`, skip the V3 `sum_asks` floor entirely and run only the V2 band; or set the V2 band to a non-degenerate window above the V3 floor. Re-tune the band against real book data so it actually fires while staying profitable.

---

### E3 — HIGH — Shared fill-sim + slug-keyed strategy routing ✓verified

**Where:** one global `_maker_fill_sim` (`main.py:3033`); `_strategy_cache[decision.slug] = strategy` (fill_sim.py:358, 507, 626); `_lookup_strategy(slug)` returns `_strategy_cache.get(slug)` (1212-1219).

**Mechanism:** the market slug (`btc-updown-15m-…`) is strategy-independent. `acc_h_v2` and `acc_pc_v2` both run `btc_15m` + `eth_15m`, so both post on the same slug. The cache is **last-write-wins**, so `_emit_post_fill` (1129) looks up the WRONG strategy for one of them. Its `on_order_fill` won't find the foreign `order_id` in its `open_orders` → fill dropped (`unknown_order_id`) or its `slug_state`/CSV row gets mutated by the other sleeve. **Per-sleeve PnL on shared cells (acc_h_v2 vs acc_pc_v2) is therefore cross-contaminated** — the aggregate sign of the reversal still holds, but the split between those two sleeves is unreliable. In live (single wallet) this is also self-competition (handoff R4).

**Fix:** key the cache/lookup by `(slug, strategy_code)` or maintain an `order_id → strategy` map and route fills by `order_id`. Independently, enforce one-sleeve-per-cell at registration (E13).

---

### E4 — HIGH — Fee model wrong for live parity ✓verified (locations)

**Where:** `base.py:57-89` (`_TAKER_FEE_RATE=0.07`, `taker_fee`, `maker_rebate`); applied in fill sim `_apply_bps_deltas` (806 taker rebate income, 815 taker fee) and in strategy gates (acc_m:797, acc_h:320, acc_pc:217, pat_shadow:~132).

**Mechanism:** shadow charges `0.07·p·(1-p)` per share on every fill and credits a maker rebate `0.20·0.07·p·(1-p)`. Production BTC/ETH/SOL up-down markets charge **2% on winning profit only** (verified vs 25,900 resolution events). So shadow (a) over-charges taker fees on the losing leg that live charges $0 (pessimistic on PnL), (b) accrues maker rebate **income that doesn't exist** if `feeRate≈0` (optimistic), and (c) the taker gates (pair-cost thresholds) are over-conservative, suppressing fires. Net direction is ambiguous until the live fee is confirmed.

**Fix:** add a selectable fee model (mirror `engine_v2.LegacyConfig`: 2%-on-winning-profit-only, zero maker rebate) and activate it for crypto up-down cells; keep the `0.07` curve as a "future fee" mode. **Verify first** against VPS3 `trading.events` (`TV_AGENT_FIX_FEE_MODEL_SPEC.md`).

---

### E5 — HIGH — Dashboard / lifetime PnL distortions ⚠reported

**Where:** `poly_maker_loop.py:_emit_state_tick` (1046-1051); `maker_sleeves.py` lifetime sum (524-536) + mark (762-764).
- **E5a:** `_emit_state_tick` computes `pnl_so_far = cash_received - cash_spent + rebates - taker_fees` — **omits `cash_recovered`** (MERGE+REDEEM proceeds) → live dashboard diverges from CSV `slug_pnl_so_far` (which includes it, shadow_log.py:324).
- **E5b:** lifetime PnL sums each day's `pnl_with_mark` (cash + mark). Mid-marks from slugs open at UTC midnight get **permanently baked in** even after those positions expired worthless → permanent optimism (compounds E1).
- **E5c:** slugs spanning midnight appear in two daily files; per-day "latest row per slug" cumulative cash is summed across days → **double-counts** `cash_spent`.

**Fix:** include `cash_recovered` in `_emit_state_tick`; compute lifetime from **cash-only** across all days (mark only the current day's still-open inventory); build a single global `latest-row-per-slug` across all day files so each slug counts once.

---

### E6 — HIGH — Convergence-cancel freezes directional residual ⚠reported

**Where:** `acc_m.py:_cancel_decisions` (430-449); ACC-PC taker blocked in window (`acc_pc.py:165-168`).

**Mechanism:** in the convergence window the sleeve cancels open orders and stops posting, but never emits a TAKE to **flatten** existing imbalance. If the slug already carries a large one-sided (adversely-selected) residual, that losing directional bet is locked in — which is exactly the loss driver behind the reversal. Convergence-cancel reduces *new* adverse fills but not the *accumulated* residual.

**Fix:** add a convergence-flatten pass that TAKEs the heavy side (or pair-completes at a tight cost gate) when `|inv_up - inv_dn|` exceeds a threshold, before/at stop-posting.

---

### E7 — MED — ACC-PC pair-cost uses both-sides average cost ⚠reported

**Where:** `acc_pc.py:216` — `avg_lead_cost = state.cash_spent / lead_inv`. `state.cash_spent` is total spend on **both** sides; `lead_inv` is one side only → inflated/garbled lead cost → `pair_cost` gate fires wrongly (rejects good completions or allows overpay; consistent with the −$3.93 paired-slug overpay).

**Fix:** track `cash_spent_up` / `cash_spent_dn` separately in `SlugState`; `avg_lead_cost = cash_spent_lead / lead_inv`.

---

### E8-E12 — MED — Fill-simulator realism (all make shadow OPTIMISTIC vs live)

- **E8** ✓ `fill_sim.py:1121` fills full `order.size` on queue-drain — no partial fills → ~10-25% over-fill.
- **E9** ✓ `fill_sim.py:1053-1058` adverse-sel haircut is **bids-only** and **default-off** (`tv_poly_maker_adv_sel_bps=0`); even when on, it's a flat price penalty that can't capture state-dependent selection (getting filled on the side about to lose).
- **E10** ⚠ zero published depth at the posted price → `initial_queue=0` → first matching trade print triggers a full fill (front-of-queue assumption).
- **E11** ⚠ `_observe_take` VWAP walk lacks a min-book-levels / staleness guard (`engine_v2.LiveMimicConfig` uses `min_book_events=25`); sparse/stale books fill at optimistic prices.
- **E12** ⚠ `acc_h.py:308-315` pair-cost reads the cached L25 with no staleness check; trade-print bursts evaluate against a possibly-stale book.

**Fix direction:** cap fill size to the draining aggressor's size (or a partial-fill ratio knob); apply adverse-sel symmetrically and enable it; require a confirmed book snapshot before counting a fill; add min-levels + staleness guards to TAKE and pair-cost paths.

---

### E13-E17 — lower priority

- **E13** ⚠ `maker_sleeves.py:709-719` inventory card uses the last global row (masks live multi-slug exposure); `848-852` has no guard against two sleeves sharing a cell. Fix: sum inventory across open slugs; error/warn on cell overlap.
- **E14** ⚠ `poly_maker_loop.py:1238` 60s resolution poll → up to 60s of stale post-resolution mark. Fix: poll on slot boundary or ≤10s.
- **E15** ⚠ MINT/REDEEM gas not booked (~$22/day optimistic). Fix: mirror the MERGE gas debit.
- **E16** ✓ `acc_m.py:424` (& acc_h/acc_pc) `getattr(..., 0)` default silently disables convergence-cancel if the env key is missing. Fix: warn when offset==0 for a V2 sleeve.
- **E17** ✓ `fill_sim.py:828` docstring stale (`cash_received` vs `cash_recovered`); code is correct.

---

## ❌ Rejected / false positives (do NOT spend time on these)

- **MERGE missing 0.25% fee (agent "B8"): REJECTED.** `_observe_merge` (746,752) does `cash_recovered += pairs − gas_usd` with `tv_poly_merge_gas_usd ≈ $0.05` (doc line 679). At POST_SIZE=20 that is `20 − 0.05 = 19.95 = 20×0.9975`, i.e. the merge **is** netted to 0.9975 — the "0.9975" `per_slug_recon` saw was this flat gas, not a missing rate. *Minor real subtlety:* it's modeled as flat gas, so it only equals 0.25% at size 20 — if merge sizes vary, revisit.
- **Adverse-sel "wrong sign" (agent "B3"): DOWNGRADED.** Raising the bid fill price is a defensible PnL-cost proxy, not a sign error; the real issues are that it's one-sided and default-off (folded into E9).
- **`self.variant` AttributeError on base `MasStrategy` (agent "C2"): likely FALSE** — MAS V1 produced data without crashing, so the base must define a `variant` default. Verify with a one-line grep before acting.

---

## Recommended fix order

1. **E1** (settlement lifecycle) — unblocks honest shadow PnL; everything downstream depends on it.
2. **E4** (fee model) — verify live fee first; gates the deploy-vs-not decision.
3. **E5** (dashboard/lifetime) — so operators stop seeing phantom profit.
4. **E3** (shared-sim routing) + **E13** (one-sleeve-per-cell) — fixes per-sleeve attribution + live self-competition.
5. **E2** (MAS gate) — only if MAS is worth reviving; otherwise kill MAS-V2.
6. **E6 / E7** (convergence-flatten + pair-cost) — the actual edge levers; needed before any sleeve can plausibly turn positive.
7. **E8-E12** (fill realism) — tighten before trusting live-parity of any retuned sleeve.

## Artifacts
- This map: `strategy_lab/reports/ENGINE_BUG_MAP_2026_05_28.md`
- Evidence/context: `MAKER_ARB_CENSORING_REVERSAL_2026_05_28.md`, `ENGINE_CORRECTNESS_AUDIT_2026_05_28.md`
- Settlement proof: `strategy_lab/maker_arb_audit/settle_residuals.py`
