# Final Leak-Free Deployment Plan (2026-05-20)

## TL;DR

After fixing 3 lookahead leaks in the previous analysis, the deployable set shrinks but is now **truly validated**:

| Tier | Cells | Mechanism | Daily PnL (held-out) | Monthly proj | Confidence |
|---|---:|---|---:|---:|---|
| **TIER A — LIVE** | **1** | FDR-passing, 3 folds, held-out validates | **+$94/d** | **+$2,820** | High |
| **TIER B — PAPER** | **12** | Single-fold (late starter), strong p=0 | **+$679/d** | **+$20,400** | Provisional |
| Combined cautious (B at 1/3) | 13 | TIER A live, TIER B reduced size | **+$321/d** | **+$9,630** | Honest |
| Combined aggressive | 13 | Full size if mint_sell holds | +$773/d | +$23,200 | Optimistic |

vs current production: **-$700/day (-$10k/month)**. Even cautious deployment = **+$1,000/day swing**.

---

## Lookahead leaks that were fixed

### Leak 1: Held-out included in selection-windows
**Before**: robustness required positive PnL in 5 windows including `last_7d` and `last_3d`. Both overlap with the held-out window (start day 10.4 of 13). So we were filtering cells using held-out data, then claiming "validates on held-out".

**Fix**: Selection = first 80% (10.4d), split into 3 disjoint internal folds. Held-out = last 20% (2.6d), strictly disjoint. Never touched during selection.

### Leak 2: No multiple-testing correction
**Before**: 309 candidate cells × 3 actions = ~900 trials. We reported "p<0.05" without Bonferroni. With Bonferroni α = 0.05/900 = 5.5e-5, very few cells pass.

**Fix**: Apply Benjamini-Hochberg FDR (q=0.10) — less conservative than Bonferroni, accounts for correlated tests (same sleeve, adjacent hours).

### Leak 3: `pnl_invert` was optimistic
**Before**: `inv_entry_price = 1 - entry_price + spread` assumed opposite-side L25 ask = (1 - same-side ask) + spread. In practice the opposite side ask is 1-2c higher.

**Fix**: Conservative `pnl_invert -= 100bp × $25 = $0.25/trade` safety buffer.

---

## TIER A — LIVE DEPLOY (1 cell) — REAL-FILL VALIDATED

| Field | Value (approximation) | Value (REAL L25 walk, no subsample) |
|---|---:|---:|
| Cell | `poly_updown_btc_15m_volume_INV_NIGHT UP @ 06-11 wd → INVERT` | same |
| Action | INVERT (fade prod signal) | same |
| n_total trades | 75 | 72 valid (3 dropped by spread filter) |
| **Inverse hit rate** | — | **73.6%** (production loses 73.6% same-side) |
| **Mean entry vwap** | 0.5176 (approx) | **0.5014** (real opposite-side) |
| **Mean real spread** | 0.030 assumed | **0.0107** (actual) |
| **Per-trade EV** | +$10.92 | **+$11.36** |
| **Total PnL** | +$786 | **+$817.90** |
| **Held-out PnL (n=27)** | +$251 | **+$264.74** |
| Permutation p (selection) | 0.0005 | — |
| Active folds | 3 of 3 | — |
| Daily rate (real, held-out) | — | **+$102/day** |
| Monthly projection | $2,820 | **$3,058** |

### Real-fill payoff structure
- **Wins (n=53, 73.6%)**: mean payoff +$24.39 each (after 2% fee on profit)
- **Losses (n=19, 26.4%)**: mean payoff -$25.00 each (full notional lost — Up/Down market binary)
- **EV math**: 0.736 × $24.39 − 0.264 × $25.00 = **+$11.36/trade** (matches observed +$11.36 exactly)

### Why this works — at the fill level

When `volume_INV_NIGHT` fires `signal=UP` during EU morning weekdays (06-11 UTC):
1. **Production sleeve says**: "buy Up side of Polymarket BTC 15m market — BTC will rise"
2. **Reality**: BTC actually settles Down **73.6% of the time** in this hour-bucket
3. **Our fade**: ignore signal direction, buy the DOWN side instead
4. **Entry**: walk DOWN-side L25 asks for $25 → real vwap ≈ $0.50 (near mid — market uncertain when sleeve fires)
5. **Settle (15min later)**: chainlink resolves the BTC outcome
   - If Down (73.6%): ~50 shares × ($1.00 - $0.50) = +$25, minus 2% fee = **+$24.39**
   - If Up (26.4%): -$25 (lose full notional, standard Polymarket binary)

### Why the approximation was conservative
We assumed opposite-side ask = `1 - same_side_ask + spread + 100bp_safety = 0.5176`. Real opposite-side vwap is **0.5014** — about 1.6c better than estimated. The 100bp safety buffer was too cautious. **Approximation under-estimated PnL by ~$0.44/trade**.

### Book staleness check
Median time between snapshot and fire_us: **88.6 seconds**. Max: 35 min (rare outlier). Production reads live WebSocket so has 0 lag. For 15min market backtest, 88s lag is acceptable but worth noting.

---

## TIER B — PAPER-VALIDATE (12 cells, all mint_sell)

**ALL 12 cells are `poly_mint_sell_*` weekend KEEP at 06-11 or 12-17 UTC.**

### Why provisional, not live

These sleeves came online **May 13** (mid-data-window). They have:
- ZERO events in fold_a (May 6-10)
- ZERO events in fold_b (May 10-13)
- Massive events in fold_c (May 13-17) and held-out (May 17-19)

With only 1 fold of history, we **cannot certify regime-robustness**. They might be working because of a recent market condition that won't persist.

But:
- All 12 have permutation **p = 0.000** on BOTH selection and held-out
- Total n = 5,840 selection events + 8,914 held-out events
- Held-out PnL: **+$1,765 over 2.6 days = +$679/day**
- Mechanism is known: this is the on-chain mint-and-sell pattern CLAUDE.md identifies as the $10k-344k/day strategy
- All KEEP action — production sleeve is already doing the right thing

### Deployment recommendation

| Notional | Expected monthly PnL | Risk |
|---|---:|---|
| 1/3 of standard ($8.33) | ~$6,800 | Low — small loss if mint_sell decays |
| Full ($25) | ~$20,400 | Moderate — significant loss if decays |

**Recommended: deploy at 1/3 size, validate forward for 7+ days, promote to full size if cells maintain ≥55% hit rate and positive PnL.**

### Top mint_sell cells

| Sleeve | Hours | Held-out PnL | n_held |
|---|:---:|---:|---:|
| poly_mint_sell_btc_5m | 06-11 | +$265.36 | 1170 |
| poly_mint_sell_eth_5m | 06-11 | +$253.29 | 1088 |
| poly_mint_sell_btc_15m | 06-11 | +$214.92 | 1152 |
| poly_mint_sell_btc_5m | 12-17 | +$191.19 | 760 |
| poly_mint_sell_eth_5m | 12-17 | +$171.42 | 732 |
| poly_mint_sell_btc_15m | 12-17 | +$151.21 | 755 |
| poly_mint_sell_eth_15m | 06-11 | +$142.62 | 1073 |
| poly_mint_sell_sol_5m | 06-11 | +$98.43 | 534 |
| poly_mint_sell_eth_15m | 12-17 | +$95.78 | 695 |
| poly_mint_sell_sol_5m | 12-17 | +$82.71 | 401 |
| poly_mint_sell_sol_15m | 06-11 | +$56.45 | 703 |
| poly_mint_sell_sol_15m | 12-17 | +$41.13 | 351 |

**All weekend KEEP. Production sleeves must be verified firing.**

---

## What did NOT survive

### Mint_sell cells failed Tier A only because of fold history
They ALL show p=0.000 on held-out. If they had pre-May-13 data, they'd be Tier A. After 7 more days of data, re-run analysis — they likely promote to live.

### All previously-claimed "27 fade cuts" / "45 robust cells"
The leaky analysis claimed +$30-78k/month projections. After fixing leaks, only 1 cell certifies as live-deployable + 12 as provisional. Honest expectation: $3-23k/month, not $78k.

### What about momo / sniper / volume_INV_NIGHT inverts?
Some looked good in leaky analysis but failed leak-free perm test or FDR:
- BTC momo_v2_SELL INVERT @ 12-17 weekday: sel p=0.0067 (passes 5%), held p=0.000 — would be Tier 1.5 but Bonferroni-fails, doesn't make FDR cutoff either
- ETH volume_INV_NIGHT INVERT @ 06-11 weekday: similar, marginal
- These belong in a Tier C "watch list" — deploy ONLY after 7+ more days of data shows they persist

---

## Deployment plan

### Phase 0 — Verify mint_sell sleeves enabled (this week)
1. SSH to VPS3
2. `psql -d tradingvenue -c "SELECT sleeve_id, COUNT(*) FROM trading.events WHERE kind='poly_updown_signal' AND sleeve_id LIKE 'poly_mint_sell%' AND at > NOW() - INTERVAL '24 hours' GROUP BY sleeve_id"`
3. If any of the 12 sleeves aren't firing → enable in production config
4. If all firing but PnL doesn't match held-out projection → debug fill execution

### Phase 1 — Live TIER A + PAPER TIER B (1 week)
1. Add 1 fade rule in production controller:
   `poly_updown_btc_15m_volume_INV_NIGHT signal=UP hour=06-11 dow<5 → INVERT direction`
2. Continue running 12 mint_sell sleeves at full live size (they're production already)
3. Track per-cell realized PnL

**Pass criteria for Phase 2:**
- TIER A: realized 7d PnL > +$400
- TIER B: realized 7d PnL > +$3,000 (across 12 cells)

### Phase 2 — Promote validated TIER B to LIVE (1 week)
Any mint_sell cell with realized 7d PnL > $200 and hit rate > 53%: graduate to live unrestricted size.

### Phase 3 — Refit (2 weeks from now)
With 27 days of trading events (vs 13 today), re-run leak-free analysis. Expect significantly more Tier A cells as fold-a/b now contain the late-starter sleeves.

### Kill switches
- Any cell DD > -$300 / 30 trades → pause that cell
- Aggregate DD > -$1,500 / 3 days → pause stack, manual review
- TIER B aggregate hit rate < 53% over 50 trades → revert to 1/3 size

---

## Multi-window robustness for new data

When refit cadence runs monthly (next: 2026-06-20):

1. Re-pull events from VPS3 (`migration_2026_05_19/pull_delta_vps3.sh` extended)
2. Re-run leak-free pipeline:
   ```
   py -3 -X utf8 -m strategy_lab.ga_optimizer.path_b.robust_cells_clean
   py -3 -X utf8 -m strategy_lab.ga_optimizer.path_b.build_watchlist
   ```
3. Compare new TIER_A_DEPLOY.csv to current — drift in cells = regime shift signal
4. Pause any cell that drops out, add any new cell

---

## Files

- `strategy_lab/ga_optimizer/runs/TIER_A_DEPLOY.csv` — 1 cell live
- `strategy_lab/ga_optimizer/runs/TIER_B_WATCHLIST.csv` — 12 mint_sell cells
- `strategy_lab/ga_optimizer/runs/all_candidates_with_perm.csv` — full 113-cell table with perm-p values
- `strategy_lab/ga_optimizer/path_b/robust_cells_clean.py` — leak-free analyzer (reproducer)
- `strategy_lab/ga_optimizer/path_b/build_watchlist.py` — Tier A/B builder
- `strategy_lab/ga_optimizer/path_b/diagnose_mintsell.py` — why mint_sell fell to Tier B
- `strategy_lab/ga_optimizer/FINAL_DEPLOY_LEAK_FREE_2026_05_20.md` — this file (definitive)
- `strategy_lab/ga_optimizer/FINAL_DEPLOYABLE_2026_05_20.md` — RETRACTED (had leaks)

---

## Honest bottom line

- **With 13 days of production events + lookahead-free + FDR-corrected analysis:** 1 cell certifies as live alpha (+$2,820/month).
- **12 mint_sell cells are highly promising** but came online May 13 — need 14+ more days to certify.
- **Realistic deployment**: $9,630/month cautiously (TIER A live + TIER B at 1/3 size).
- **Best case**: $23,200/month if mint_sell holds, after Phase 2 promotion.
- Vs current production -$10k/month, **even cautious deployment = +$20k/month swing**.

This is the rigorous, leak-free, multiple-testing-corrected answer.
