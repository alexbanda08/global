# TV Agent: $1 Live Transition Spec — Single Momo Sleeve

**Status:** **DRAFT — GATED ON +24h PASS** (recheck 2026-05-07 ~00:30 UTC)
**Author:** Strategy lab (laptop)
**Date drafted:** 2026-05-06 ~12:30 UTC (at +12h, INTERIM marginal)
**Prerequisite docs:** `TV_AGENT_MOMO_SLEEVES_IMPLEMENTATION.md` · `MOMO_SHADOW_VS_BACKTEST_2026_05_06.md` · `SESSION_HANDOFF_2026_05_06.md`
**Goal:** flip ONE momo sleeve from paper to **$1 live** for empirical book-walk + fee + settlement validation. Stage rollout. Hold for 24h, then decide on enabling additional sleeves.

---

## 0 · Gating decision tree

This spec executes only after the gating reading passes.

```
Pull /tmp/momo_resolutions.csv at 2026-05-07 00:30 UTC (+24h)
  ↓
Run momo_shadow_vs_backtest.py
  ↓
+24h verdict?
  PASS  → execute §3-§7 below
  MARGINAL → wait until +48h (2026-05-08 00:30 UTC) and recheck
  FAIL  → abort. Investigate root cause. Do NOT proceed to live.
```

**+24h pass conditions** (full spec §7 of MOMO_SLEEVES_IMPL, scaled to elapsed window):

| Metric | Pass | Fail |
|---|---:|---:|
| Total fires | ≥ 50 | < 30 |
| Combined PnL | ≥ +$400 | < +$100 |
| Profitable (asset,tf) cells | ≥ 4 of 6 | ≤ 2 of 6 |
| Worst (cell,exit) PnL | > -$150 | < -$250 |
| BTC_5m hit rate (need n_unique ≥ 20) | ≥ 0.75 | < 0.65 |
| ContextVar audit completeness on FILLED post-fix | 100% | < 95% |

**Current +12h reading:** PnL +$229.66, 72 fires, 3/6 cells profitable, worst -$21.68, audit 69/69 = 100%. **Trajectory positive but BTC_5m bleeding (3 unique trades, all losses).** Cannot pick BTC_5m_momo_SELL as the live candidate while it's underperforming shadow.

---

## 1 · Sleeve selection rule

The original spec named `btc_5m_momo_SELL` (highest backtest Sharpe = 21.2). **Override rule:** pick the live candidate from the +24h shadow read, not from backtest, because backtest haircut empirically runs 30-63%.

Selection algorithm at +24h:
1. Filter to (asset, tf, exit) cells with `n_shadow ≥ 10` AND `pnl_total_shadow > 0`.
2. Rank by `pnl_mean_shadow / pnl_std_shadow` (live-Sharpe proxy).
3. Tiebreak: prefer `_SELL` exit (highest backtest Sharpe across all cells).
4. Tiebreak 2: prefer 5m over 15m (more samples per day → faster live signal).

**+12h provisional ranking** (only for trajectory checking; do NOT act on this):

| Rank | Cell | n | pnl_total | pnl_mean | live-Sharpe |
|---|---|---:|---:|---:|---:|
| 1 | SOL_5m_SELL | 15 | +$56.22 | +$3.75 | (compute at +24h) |
| 2 | SOL_5m_HEDGE | 15 | +$54.21 | +$3.61 | — |
| 3 | SOL_5m_HOLD  | 15 | +$54.21 | +$3.61 | — |

If at +24h SOL_5m_SELL still leads with n ≥ 25 and combined SOL_5m PnL > +$80, **the live candidate is `poly_updown_sol_5m_momo_SELL`** — not BTC_5m_SELL.

If BTC_5m recovers and shows positive PnL by +24h with n_unique ≥ 20, revert to backtest preference (BTC_5m_SELL).

---

## 2 · Pre-flight blockers (must clear ALL before flipping live)

| # | Blocker | Status | Required |
|---|---|---|---|
| B1 | ContextVar bug fix verified on FILLED rows | **CLEARED** (69/69 post-fix) | — |
| B2 | Per-controller notional override (D-04: $25 hardcoded) | **OPEN** | code change §3 |
| B3 | WS book subscription (Phase 2) | **OPEN** but waivable for $1 test | argued §4 |
| B4 | Live-mode flag wired per sleeve | **OPEN** | code change §3 |
| B5 | Polymarket account funded (≥ $20 USDC.e on Polygon) | **OPEN — user action** | manual deposit |
| B6 | Settlement-pnl reconciler logs both paper & live for diff audit | **OPEN** | check VPS3 §3d |

B5 is the only blocker the user must clear personally. B2/B3/B4/B6 are TV-agent code changes.

---

## 3 · Required code changes (TV agent on VPS3)

### 3a · Per-controller notional override

The hardcoded `$25` is in `polymarket_updown.py` (controller). Replace with a per-controller `notional_usd` arg, defaulting to env `TV_POLY_MOMO_NOTIONAL_USD`.

```python
# backend/app/controllers/polymarket_updown.py (sketch)
class PolymarketUpDownController:
    def __init__(self, ..., notional_usd: Decimal | None = None, mode: str = "paper"):
        self._notional_usd = notional_usd or Decimal(os.getenv("TV_POLY_MOMO_NOTIONAL_USD", "25"))
        self._mode = mode  # "paper" | "live"
```

In the master scheduler / sleeve registration, pass `notional_usd=Decimal("1.0")` for the live sleeve only:

```python
# backend/app/engine/sleeve_registry.py (sketch)
LIVE_SLEEVE = "poly_updown_<sym>_<tf>_momo_<exit>"  # filled at +24h
for sleeve_id, hedge_policy, sym, tf in MOMO_SLEEVES:
    is_live = (sleeve_id == LIVE_SLEEVE)
    register(PolymarketUpDownController(
        sleeve_id=sleeve_id,
        hedge_policy=hedge_policy,
        notional_usd=Decimal("1.0") if is_live else None,
        mode="live" if is_live else "paper",
    ))
```

### 3b · `mode='live'` plumbing

Trace `mode` through:
- `controller.__init__(mode=...)` → store `self._mode`
- entry: branch on `self._mode`. `paper` → `PolyPaperExecutor.place_entry_order`. `live` → `PolyLiveExecutor.place_entry_order` (which signs via `EthSigner` and POSTs to `/order`).
- exit: same branch. The `_try_bid_exit` path needs the same branch.
- audit-event write: `data["mode"]` must reflect actual execution path, not paper-by-default.

### 3c · D-04 invariant relaxation

Find the `assert notional == 25` (or equivalent) — usually in `PolyPaperExecutor.place_entry_order` or in `book_walk()`. Relax to `notional > 0 and notional <= 25` as a safety floor/ceiling for the live test (anything > $25 should still hard-fail).

### 3d · Live + paper dual-write reconciliation

For the single live sleeve, ALSO emit a shadow-paper resolution row with the same fill, so we can diff `pnl_live` vs `pnl_paper` per trade. Either:
- (Preferred) The live executor returns the actual fill_qty/fill_price; reuse to build a paper-mode `poly_updown_resolution` event with `data.live_fill_event_id` cross-link.
- (Simpler) Run the SAME (asset,tf,exit) cell as TWO sleeves: one live ($1), one paper ($25). Diff at end of 24h.

**Pick (Simpler).** No code path divergence, easier audit. The 17 remaining sleeves stay paper $25; the chosen cell's live sleeve runs $1. We end up with 19 sleeves, not 18, for the live-test window.

### 3e · Test additions

```
tests/controllers/test_polymarket_updown_live_mode.py
  - test_notional_override_paper
  - test_notional_override_live_branch
  - test_audit_event_records_mode_field
  - test_live_branch_calls_live_executor (mock EthSigner)
  - test_paper_and_live_dual_emission (3d: simpler path)
```

All must pass on VPS3 CI before §5 deploy.

---

## 4 · WS migration waiver argument for $1 test

The Phase 2 WS migration is mandatory **at scale**. For a $1 single-sleeve test the case for waiving:

- Worst-case book staleness on REST = 200-500ms + 1s cache = ~1.5s old book.
- Worst-case adverse price move on Polymarket in 1.5s = ~$0.05 mid drift on a 5m UpDown YES token (rare; observed in PnL audit).
- $1 notional × $0.05/$0.50 mid = **$0.10 max adverse fill slippage**.
- Even a 10% slippage = $0.10. Across 24h × ~8 fires/day (per-cell median) = $0.80 expected slippage cost.
- That's an acceptable price for the live-vs-paper diff signal we get.

**Waiver: OK to skip Phase 2 WS for the $1 single-sleeve test.** Re-impose as blocker before any sleeve at $25+ live notional.

---

## 5 · Deployment checklist

- [ ] +24h verdict = PASS (run `momo_shadow_vs_backtest.py` on 2026-05-07 00:30 UTC)
- [ ] Live sleeve picked per §1 selection rule
- [ ] B5 cleared: USDC.e ≥ $20 in TV agent's Polymarket account; verify with `cast call` on Polygon
- [ ] Code changes §3a-§3e applied + unit tests green on VPS3 CI
- [ ] `git diff` reviewed by user before merge to main
- [ ] Deploy: `systemctl restart tv-engine` after env update
- [ ] Within first hour post-deploy: confirm at least 1 live FILLED row with `data.mode='live'` and `data.fill_event_id` resolves to a real Polymarket trade hash
- [ ] Within first 4 hours: paper-vs-live PnL diff per trade ≤ $0.20 (slippage tolerance)
- [ ] Within 24h: live PnL ≥ paper PnL × 0.5 (haircut tolerance)

If any post-deploy check fails → run kill switch §6 immediately.

---

## 6 · Kill switches (in order of severity, least-destructive first)

```bash
# 1. Disable just the live sleeve, keep its paper twin running
ssh -i ~/.ssh/vps3_ed25519 root@185.190.143.7 \
  "sed -i 's/^TV_POLY_MOMO_LIVE_SLEEVE=.*/TV_POLY_MOMO_LIVE_SLEEVE=/' /etc/tv/tradingvenue.env \
   && systemctl restart tv-engine"

# 2. Disable all momo sleeves (live + 17 paper)
ssh -i ~/.ssh/vps3_ed25519 root@185.190.143.7 \
  "sed -i 's/^TV_POLY_MOMO_ENABLED=.*/TV_POLY_MOMO_ENABLED=false/' /etc/tv/tradingvenue.env \
   && systemctl restart tv-engine"

# 3. Force-close any open live position (manual — Polymarket CLOB UI)
#    Do this BEFORE step 1 if a position is open and bleeding.
```

Trigger conditions:
- Any single live trade loses > $0.50 (50% of notional) on entry slippage alone
- Live FILLED row shows `mode='paper'` (regression — kill switch immediately)
- ContextVar audit regression: any post-fix FILLED row missing the 4 enrichment fields
- Cumulative live PnL hits −$3 (3× single-trade limit) within 24h

---

## 7 · Decision at +48h post-flip (= +72h from original deploy)

Re-aggregate. Outcomes:

| Live PnL | Live-vs-paper diff | Decision |
|---|---|---|
| > $0 and within 30% of paper | < $0.20/trade | **Proceed.** Enable second live sleeve at $1, then $5 ramp on the original. |
| 0 to slight negative | within 50% | Hold at $1. Run another 48h. |
| < $0 OR diff > $1 per trade | — | Roll back. Live execution model has unmodelled cost. Revisit. |

---

## 8 · Out of scope (explicit non-goals)

- Multi-sleeve live deploy (gated on §7 first-sleeve pass)
- WS migration (separate Phase 2 doc)
- Cross-asset live (BTC + ETH + SOL simultaneously) — single sleeve only
- Notional > $1 (D-04 ceiling stays at $25; we're using $1 floor)
- Settlement on Chainlink retries — re-uses existing logic

---

## 9 · Open questions for next session (after +24h pull)

1. Q1: Did the BTC_5m bleeder reverse? (3 losses on first 3 trades = bad luck or systemic?)
2. Q2: Does the +24h profitable-cells count cross 4 of 6?
3. Q3: Does any (cell, exit) cross n_unique ≥ 20 to give us BTC_5m hit rate signal?
4. Q4: Is the bar_ctx_age_ms p95 on FILLED still < 500ms? (currently 257ms)
5. Q5: Confirm B5 (Polymarket account funding status) before §3 code work begins.

---

*End of TV_AGENT_LIVE_TRANSITION_SPEC.md (DRAFT). Re-verify gating at 2026-05-07 00:30 UTC before treating any §3+ section as actionable.*
