# Shadow PnL Re-Audit Runbook (post-F1 + post-decoder-fix)

**Run this after** both:
1. F1 lands on Ireland (`TV_AGENT_FIX_F1_SPEC.md` applied + `tv-engine.service` restarted + 24h of fresh data collected)
2. Decoder fix lands locally (`WALLET_DECODER_FIX_SPEC_2026_05_21.md` applied + lb-api cache populated)

**Outputs**: a fresh `SHADOW_AUDIT_2026_05_22.md` (or whatever date) that supersedes the current audit's mark-propped numbers with cash-truth numbers.

**Why both fixes are prerequisites**:
- F1 fixes the engine's `taker_fees` and `rebates` CSV columns. Until F1, console PnL is over-stated by exactly the unbooked fees/rebates.
- Decoder fix lets us compare our shadow $/slug to the wallet templates' true $/day cleanly. Until decoder fix, we can't tell whether ACC-M shadow is at 10% or 100% of wallet-template alpha.

The two fixes are independent — apply in either order. But the re-audit needs both done first.

## 0. Pre-flight checklist

- [ ] F1 deployed to Ireland (`engine/poly_maker_fill_sim.py:_apply_bps_deltas` rewritten; mas.py duplicate booking removed)
- [ ] `tv-engine.service` restarted: `systemctl status tv-engine | head`
- [ ] At least **24h of post-F1 shadow data** in `/var/log/tv/maker/<sleeve>_<date>.csv`
- [ ] Decoder fix applied locally per `WALLET_DECODER_FIX_SPEC_2026_05_21.md`
- [ ] `strategy_lab/wallet_hunt/cache/_pm_portfolio/` populated for ≥10 wallets
- [ ] `strategy_lab/wallet_hunt/cache/_master_catalog.csv` re-built with `pm_*` columns

If any pre-flight item is missing, STOP and finish that first.

## 1. Pull fresh shadow data from Ireland

```bash
# On the dev box, working dir = global/
mkdir -p migration_ireland_shadow_post_f1_2026_05_22

# Pull all post-F1 shadow CSVs (limit to dates after F1 deployment)
ssh vps_ireland 'sudo tar -czf - -C /var/log/tv maker' \
  > migration_ireland_shadow_post_f1_2026_05_22/maker_csvs.tgz
cd migration_ireland_shadow_post_f1_2026_05_22
mkdir -p maker_csvs && tar -xzf maker_csvs.tgz -C maker_csvs --strip-components=1

# Confirm dates
ls maker_csvs/
# Should see acc-h, acc-m, acc-pc, mas, pat-shadow for all dates since F1 deploy
```

## 2. Re-run console PnL reproduction

```bash
cd migration_ireland_shadow_post_f1_2026_05_22
cp ../migration_ireland_shadow_2026_05_21/audit_08_console_repro.py .
# Edit the script's `base` path to point at the new maker_csvs/ dir
py -X utf8 audit_08_console_repro.py > _console_repro_out.txt 2>&1
```

**Expected outcome after F1**: `repro_diff` column should be near zero for every sleeve (within ±$2). If any sleeve shows >$5 diff between repro and operator console, F1 didn't land cleanly — investigate before continuing.

## 3. Compute honest cash-truth PnL per sleeve

This is the key step. After F1 the engine CSV's `taker_fees` and `rebates` columns are populated, so:

```
honest_cash_pnl  =  cash_received  +  cash_recovered  −  cash_spent  +  rebates  −  taker_fees
mark             =  paired × $1.00  +  residual × $0.50 (pre-REDEEM) or × $0 (post-REDEEM)
console_pnl      =  honest_cash_pnl + mark   (what the operator sees)
```

Use the existing per-slug audit script:

```bash
cp ../migration_ireland_shadow_2026_05_21/audit_05_clean_pnl.py .
# Edit base path to new maker_csvs/
py -X utf8 audit_05_clean_pnl.py > _clean_pnl_out.txt 2>&1
```

Output: `per_slug_audit.csv` with `pnl_truth`, `engine_pnl`, `delta` columns per slug per sleeve.

## 4. Per-sleeve hard gates

Compute aggregate over the full post-F1 window:

| sleeve | gate | action if fail | action if pass |
|---|---|---|---|
| **ACC-M btc 5m** | honest cash $/slug ≥ **+$1.00** | DO NOT promote. Strategy edge was mark-propped. Pivot to F2/BDH or rebuild from wallet template. | Phase 1 paper-trade at $50 stake — see `deploy_capital_analysis.py` for sizing. |
| ACC-H btc 5m | honest cash $/slug ≥ +$0.30 | Disable V3f rules B + C. Becomes ACC-M-equivalent. | Continue shadow. |
| ACC-H btc 15m | honest cash $/slug ≥ +$0.80 | Tighten PAT cap to 0.98 per agent D finding. Re-shadow 14d. | Continue shadow. |
| ACC-PC btc 15m | n_slugs ≥ 200 AND $/slug 95% CI lower > 0 | Continue shadow. | Phase 1 paper at $50. |
| MAS btc 5m | honest cash $/slug ≥ +$0.10 (post UTC + sum_asks gates) | Kill MAS. | Continue shadow. |
| MAS btc 15m | honest cash $/slug ≥ $0 (≥ flat) | Kill MAS 15m. | Continue shadow. |
| PAT-SHADOW | n/a — standalone is structurally negative | Kill PAT-SHADOW. Inherited PAT inside ACC-M/H stays. | n/a |

## 5. Cross-check with wallet templates

After decoder fix, the wallet catalog has `pm_30d_profit` and `pm_maker_rebate_share` per wallet. Build a comparison:

```python
import pandas as pd
cat = pd.read_csv("strategy_lab/wallet_hunt/cache/_master_catalog.csv")

# Filter to wallets running ACC-M-like paired-bid hold-to-expiry strategy:
acc_m_template = cat[
    (cat["pm_lifetime_profit"] > 50_000)
    & (cat["pm_maker_rebate_share"] > 0.01)
    & (cat["n_splits"] == 0)         # no minting
]
# Median $/day across these wallets:
template_per_day = acc_m_template["pm_30d_profit"].sum() / 30 / len(acc_m_template)

# Compare to our shadow ACC-M $/day at same notional:
shadow_per_day_at_size_20 = ... # from per_slug_audit.csv aggregated
ratio = shadow_per_day_at_size_20 / template_per_day
print(f"We're at {ratio:.0%} of wallet-template alpha at POST_SIZE=20.")
```

**Healthy ratio**: 30-80% of wallet template at same notional. The wallets often run at much larger sizes (5-10× POST_SIZE), so per-fire we'd expect to be similar. If we're <10% of template, fill rate or queue position is broken — investigate.

## 6. Produce the new audit doc

```bash
cp ../strategy_lab/reports/SHADOW_AUDIT_2026_05_21.md \
   ../strategy_lab/reports/SHADOW_AUDIT_<NEW_DATE>.md
```

Then edit the new file to:
1. Replace §1 TL;DR with the post-F1 honest cash $/slug numbers
2. Replace §2 fee correction note with "F1 landed — see X commit/PR"
3. Replace §4 bug inventory with what (if anything) is left after F1 + decoder fix
4. Add a new §5b — wallet-template comparison (from step 5 above)
5. Update §6 promote/hold per sleeve based on the hard-gate results from §4

## 7. Decision tree

After steps 1-6, you have one of three outcomes:

### Outcome A — ACC-M passes hard gate (≥+$1.00/slug honest cash)

→ Go to Phase 1 paper deploy per `MAKER_ARB_DEPLOY_REPORT_2026_05_21.md` §3. Capital $50 on ACC-M btc 5m. 7-day verification window. Then Phase 2 live at $700.

### Outcome B — ACC-M fails hard gate (<+$1.00/slug honest cash)

→ ACC-M is NOT live-deployable in current form. Branches:

- If wallet-template comparison shows we're at <10% of template alpha: the BUG is in fill simulation. Land F2-F5 from `TV_AGENT_FIX_SPEC_2026_05_21.md`, re-shadow another 24h, re-audit.
- If we're at 30-80% of template alpha but absolute $/slug is small: the wallets succeed by scaling (POST_SIZE 100+, capital $5k+). Decide whether to skip paper-stage and go straight to Phase 2 at higher size, OR continue shadow tuning.
- If we're at <10% of template alpha AND fill simulation looks correct: the bug is in QUEUE POSITION. We're losing rebate share to faster bots. Need queue-priority instrumentation per agent E literature review.

### Outcome C — Decoder finds new high-PnL wallets we hadn't audited

→ Add to `_master_catalog.csv`. If any earn >$5k/day on patterns we don't yet implement, write a new sleeve spec. Top candidates per the audit so far: 0xeebde7a0 (+$8,437/day), 0x89b5cdaa (+$5,563/day) — both are ACC-M-template with HFT pacing, so we may not need a new sleeve, just to size up.

## 8. Failure modes to watch

- **F1 didn't fully land**: check `console_repro.csv` diff. If diff >$5/sleeve, F1 wasn't applied or there's a missing edit (mas.py duplicate not removed?). Re-verify against `TV_AGENT_FIX_F1_SPEC.md`.
- **Shadow data window too short**: <24h post-F1 gives too few resolved slugs for a clean per-sleeve estimate. Wait longer.
- **Engine restart caused dropped events**: confirm no gap in CSV `ts_us` series around restart. If gap exists, exclude that hour from the audit window.
- **REDEEM events not yet logged on Ireland**: if Ireland engine's `_observe_redeem` isn't writing REDEEM rows to the shadow CSV (separate from F1 — that's a different code path), the `cash_recovered` column won't populate post-resolution and honest cash PnL will be incomplete. Verify by counting `action=="REDEEM"` rows per sleeve.

## 9. Files this runbook produces

| Path | Description |
|---|---|
| `migration_ireland_shadow_post_f1_<date>/maker_csvs/` | Fresh CSVs from Ireland |
| `migration_ireland_shadow_post_f1_<date>/audit_08_console_repro.py` | Console reproduction |
| `migration_ireland_shadow_post_f1_<date>/audit_05_clean_pnl.py` | Per-slug truth |
| `migration_ireland_shadow_post_f1_<date>/per_slug_audit.csv` | Per-slug table |
| `migration_ireland_shadow_post_f1_<date>/console_repro.csv` | Sleeve totals reconciliation |
| `migration_ireland_shadow_post_f1_<date>/wallet_template_compare.csv` | Step 5 comparison |
| `strategy_lab/reports/SHADOW_AUDIT_<date>.md` | New audit doc, supersedes 2026_05_21 |
| `strategy_lab/reports/MAKER_ARB_DEPLOY_REPORT_<date>.md` | Updated promote/hold decisions |

## 10. Estimated effort

| Step | Time |
|---|---:|
| Pull shadow data + extract | 5 min |
| Re-run console_repro + clean_pnl | 5 min |
| Per-sleeve hard gates | 15 min (Python aggregation) |
| Wallet-template comparison | 30 min (assumes decoder fix landed and catalog is fresh) |
| Write new audit doc + update deploy report | 1 h |
| **Total** | **~2 h** |
