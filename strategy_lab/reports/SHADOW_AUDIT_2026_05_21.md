# Maker-Arb Shadow Audit — 2026-05-21 (REV)

**Window**: 2026-05-20 17:56 UTC → 2026-05-21 19:27 UTC (≈25.5 h)
**Source**: `/var/log/tv/maker/{acc-h,acc-m,acc-pc,mas,pat-shadow}_2026-05-{20,21}.csv`
**Raw pulled to**: `migration_ireland_shadow_2026_05_21/maker_csvs/`
**Engine source pulled**: `migration_ireland_shadow_2026_05_21/source_code/`
**Reproducers**: `migration_ireland_shadow_2026_05_21/audit_*.py`

> **Supersedes the earlier draft of this file from earlier today.** That draft
> applied real Polymarket taker fees to the entire `TAKE` row stream and to
> "FILL" rows it mis-classified as taker. Correction in §2 below.

---

## 1. Bottom line

I reproduced the operator console's PnL numbers within ±$20 per sleeve from
the raw CSVs. The console formula is **correct**. The only systematic
over-statement is **taker fees that the engine computes for gating but never
books into the `taker_fees` CSV column**. Once that's applied, every active
sleeve except `acc-h_legacy` and `pat-shadow` shows positive structural alpha,
and most are running **at or above their backtest predictions**.

| sleeve_id | n_slugs | n_fills+takes | console PnL | unbooked taker fees | honest PnL | spec backtest $/slug | actual $/slug |
|---|---:|---:|---:|---:|---:|---:|---:|
| poly_acc_m_btc_5m_shadow | 235 | 2,647 | **+$624.36** | $162.45 | **+$518.64** | +$1.25 (REV) → +$1.98 (HYBRID) | **+$2.20** ✓ |
| poly_acc_h_btc_5m_shadow | 235 | 4,116 | **+$246.40** | $181.63 | **+$171.55** | **−$6.84** (V3f backtest) | **+$0.73** ✓ |
| poly_acc_h_btc_15m_shadow | 78 | 858 | **+$174.27** | $48.03 | **+$144.22** | — | **+$1.85** |
| poly_acc_pc_btc_15m_shadow | 79 | 1,030 | **+$84.83** | $44.06 | **+$74.74** | +$0.27 → +$0.49 | **+$0.95** ✓ |
| poly_mas_btc_5m_shadow | 235 | 210 | **−$61.95** | 0 | **−$54.94** (+rebate adj) | +$0.09 (flat) | **−$0.23** ≈ flat |
| poly_mas_btc_15m_shadow | 79 | 0 | $0.00 | 0 | $0.00 | flat | flat ✓ |
| poly_pat_shadow_btc_5m_shadow | 234 | 19,121 | **−$1,285.48** | $812.77 | **−$1,936.04** | overlay only | **−$8.27** ⚠ |

(`legacy` sleeve_id rows are pre-2026-05-20 17:56 patch — sleeve_id wasn't
written then; treat as discardable.)

**Verdict at the structural-alpha level**:

- **ACC-M btc 5m REV+HYBRID** is the strongest live candidate. Honest $2.20/slug
  on 235 slugs beats the 213-slug backtest's $1.25-$1.98 prediction. Same maker
  template that 3 chain-decoded wallets run at $10k-$254k/day.
- **ACC-H btc** (both 5m and 15m) is **outperforming its own spec**. Spec said
  V3f composite taker would LOSE $6.84/slug; live shadow shows +$0.73-$1.85/slug
  positive. The H-spec was conservative — needs another 7d of data to confirm
  it isn't sample-luck.
- **ACC-PC btc 15m** is +$0.95/slug vs $0.27-$0.49 backtest. 79 slugs is too
  small to tell signal from noise, but the sign is right.
- **MAS** is near-flat as the spec predicted. No alpha, no bleed. Decision
  point: kill it, or keep collecting data to test edge in higher-vol regimes.
- **PAT-SHADOW** is **structurally broken** — see Bug 4 below. PnL is
  meaningless until the REDEEM event hook is wired.

## 2. Fee model used in this audit (canonical)

    fee    = C × feeRate × p × (1 − p)
    rebate = C × feeRate × p × (1 − p) × rebate_share

where `C` = shares, `p` = fill price, `feeRate` = 0.07 for crypto up-down
(BTC/ETH/SOL 5m/15m), `rebate_share` = 0.20 for crypto. This is NOT a flat
7% — at p=0.5 the effective fee is 1.75% of share value, at p=0.85 it's
1.05%, going to zero at the price extremes. Source of truth:
`strategy_lab/fees.py`. The engine's `base.taker_fee()` implements the same
formula.

Correction to the earlier draft of this file:

1. **`TAKE` rows for ACC-M btc 5m are the PAT-overlay taker fills generated
   by ACC-M itself**, not book trade-prints by other participants — they
   correctly attract the per-share fee.
2. **The engine USES the canonical fee formula** in `base.taker_fee()` for
   trade gating (`pair_cost = ba_up + ba_dn + fee_up + fee_dn` in
   `acc_m.py:694`). What it does NOT do is **write that fee into the
   `taker_fees` CSV column / `slug_state.taker_fees_paid` field**. The
   bps-additive adder in `poly_maker_fill_sim.py:_observe_post_fill_fees`
   defaults to 0 and isn't set in `/etc/tv/tradingvenue.env`, so no fees
   flow through that path.

Net: the engine's `pnl_so_far` is over-stated by exactly the unbooked fees,
as listed in §1's table.

## 3. Console PnL formula (confirmed by reproduction)

`backend/app/api/maker_sleeves.py:510-535`, per sleeve_id:

```
for each slug:
    paired      = min(inv_up, inv_dn)
    residual    = abs(inv_up - inv_dn)
    if REDEEM fired:
        mark = paired * 1.00              # paired pays $1/pair at resolution
    else:
        mark = paired * 1.00 + residual * 0.50    # pre-resolution 50/50
    slug_pnl =  cash_received
              + cash_recovered
              - cash_spent
              + rebates
              - taker_fees                # ← always 0 today; this is the bug
              + mark
    pnl += slug_pnl
```

`mark_to_market` correctly distinguishes pre- and post-REDEEM (loser residual
is worth $0 once we know the outcome — the "residual-mark inflation bug" from
`MAS_15M_STALE_AND_PNL_BUG_2026_05_21.md` is already fixed in this version of
the API). Verified by reading the code, not just the comments.

## 4. Confirmed bugs (4 total)

### Bug 1 — Engine never writes `taker_fees` into the CSV / slug_state (HIGH)

Strategy code computes the per-share fee correctly via
`base.taker_fee(p) = 0.07 × p × (1 − p)` and uses it for trade gating, but the
fill simulator's `_observe_post_fill_fees` only adds to `taker_fees_paid` when
`tv_poly_taker_fee_bps != 0`, which it is in current Ireland config.

**Effect on each sleeve's reported PnL (over-statement)**:

| sleeve | unbooked fees | unbooked rebates | net over-statement |
|---|---:|---:|---:|
| poly_acc_m_btc_5m_shadow | $162.45 | $56.73 | **$105.72** |
| poly_acc_h_btc_5m_shadow | $181.63 | $106.77 | $74.86 |
| poly_acc_h_btc_15m_shadow | $48.03 | $17.98 | $30.05 |
| poly_acc_pc_btc_15m_shadow | $44.06 | $33.97 | $10.09 |
| poly_mas_btc_5m_shadow | $0 | $7.01 already booked | −$7.01 (under-stated) |
| poly_pat_shadow_btc_5m_shadow | $812.77 | $162.21 | $650.56 |

(MAS books rebates correctly because mas.py emits the rebate in its decisions;
other strategies don't. ACC-M btc_5m books a partial $0 to `rebates` column —
verified by re-grepping the CSV.)

**Fix**: in `poly_maker_fill_sim.py` `_observe_take` and `_observe_post_fill`,
add `slug_state.taker_fees_paid += taker_fee(price) * size` (TAKE branch) and
`slug_state.rebates_received += maker_rebate(taker_fee(price)) * size` (FILL
branch) at the same point as the cash bookkeeping. The bps-adder can stay as
an additional override.

### Bug 2 — PAT-SHADOW never emits REDEEM events (HIGH)

PAT-SHADOW touched 234 slugs (sharing 134 with ACC-M's resolved set) but the
PAT CSV contains **zero `REDEEM` rows**. Resolution accounting is completely
absent. Every PAT slug stays "open" forever in the log, so `cash_recovered`
is never credited, and the engine reports `−$1,285.48` console PnL that has
already paid for inventory but never recognizes the $1-per-winning-share
return.

After redeem-side accounting is fixed, the realistic floor for PAT is closer
to `cash_received − cash_spent + rebates − taker_fees + winner_inv × $1`,
not the current `cash − spent + mark`. Need controller to subscribe to
`slug.resolved` and emit REDEEM Decisions.

Reproducer: `audit_06_structure.py`, S4 section.

### Bug 3 — FILL events use synthetic order_ids that don't link to the POST (MEDIUM)

Across the maker strategies:

| strategy | FILL rows | FILLs with order_id matching a prior POST | %match |
|---|---:|---:|---:|
| acc-m | 1,547 | 464 | 30% |
| acc-h | 3,211 | 1,478 | 46% |
| acc-pc | 748 | 475 | 63% |
| mas | 210 | 210 | 100% (clean) |

Mechanism: when the simulator detects a TAKE Decision crossing a resting BID,
it logs the FILL with `order_id = f"TAKE-{strategy}-{ts_us}"` instead of
carrying the POST's order_id forward. Breaks per-order queue-position audits,
fill-attribution reports, and any rebate-share calc done by linking back to
the post. Doesn't affect aggregate PnL, but blocks quality-of-fill diagnostics.

### Bug 4 — Inventory peak mismatch on ACC-* strategies (MEDIUM)

For 26-28 / 30 sampled resolved+traded slugs on ACC-M / ACC-H / ACC-PC, peak
`inv_up` and `inv_dn` disagree with the cumulative sum of FILL + TAKE per side
by 1-3 shares. MAS is clean. Doesn't materially affect aggregate PnL (mark
errors of ±$0.50-$1.50 per slug), but it does inflate the operator's
"PAIRED" state-detection threshold. Recommend re-deriving inv from event
stream and asserting on REDEEM.

## 5. Structural alpha vs spec

Pulling each strategy's spec backtest number out of
`TV_DEPLOY_SPEC_*_2026_05_19.md`:

| strategy | backtest sample | backtest $/slug | live shadow $/slug (honest) | verdict |
|---|---:|---:|---:|---|
| ACC-M REV (BIDs only) | 213 slugs | +$1.25 | +$2.20 (235 slugs) | **above spec** |
| ACC-M HYBRID (PAT overlay) | 87 slugs | +$1.98 | +$2.20 (235 slugs) | **at/above spec** |
| ACC-H V3f composite | 213 slugs | **−$6.84** | +$0.73 (5m) / +$1.85 (15m) | **massively above spec** |
| ACC-PC pair-completion taker | 87 slugs | +$0.27 → +$0.49 | +$0.95 (79 slugs) | **above spec** (n too small) |
| MAS-pre30 | 213 slugs | +$0.09 (flat) | −$0.23 (235 slugs) | ≈ flat |
| PAT-SHADOW | overlay only | n/a | −$8.27 (broken by Bug 2) | not measurable yet |

**Strongest conclusion**: ACC-M REV+HYBRID on btc 5m is sitting at +$2.20/slug
over 25.5 h with 235 slugs. That's the wallet template (`0x04b6d7e9`,
`0xb27bc932`) running at honest +$0.10/share margin × ~22 shares net per slug.
At current shadow volume, scaled to $25 per leg instead of the wallet seeds'
$50-$2k: roughly the projected $/day depends on how many slugs per day the
strategy will see — at 235 slugs/day that's $516/day pre-tax pre-slippage.

**Most surprising finding**: ACC-H is profitable in shadow despite the spec
saying it would LOSE $6.84/slug. The H-spec was written with one regime's
backtest; the current 25h window's regime is more favorable to the 4-rule
composite taker. Don't trust this until another 7 days corroborates.

## 6. Action items

| # | Fix | Owner | Severity | Where |
|---|---|---|---|---|
| 1 | Book real taker fees + maker rebates into `slug_state` on every FILL / TAKE-driven fill (call `base.taker_fee(price) * size` + `base.maker_rebate(...)` from the fill sim) | TV agent | HIGH | `engine/poly_maker_fill_sim.py` `_observe_take` / `_observe_post_fill` |
| 2 | Wire PAT-SHADOW's `on_slug_resolved` hook so REDEEM Decisions emit + cash_recovered lands | TV agent | HIGH | `strategies/polymarket/maker/pat_shadow.py` |
| 3 | Link FILL order_id to the originating POST (carry through simulator) | TV agent | MEDIUM | `engine/poly_maker_fill_sim.py` |
| 4 | Re-derive inv_up/inv_dn from event stream + assert on REDEEM | TV agent | MEDIUM | base.py shared helper |
| 5 | Keep collecting; revisit after 7+ days of post-fix data before any live-promotion decision | Operator | — | — |

After Fix #1 lands, ACC-M btc 5m should still report **+$2.20/slug honest**,
just with `taker_fees` and `rebates` populated correctly so the console
agrees with the audit. After Fix #2 PAT goes from -$1,936 to whatever it
actually is — could be flat, could be net positive once the $1/winner share
lands.

## 7. Files produced

- `migration_ireland_shadow_2026_05_21/maker_csvs/` — 10 raw CSVs
- `migration_ireland_shadow_2026_05_21/source_code/` — current Ireland engine + strategies + API
- `migration_ireland_shadow_2026_05_21/logs/tv-engine.jsonl` — 109,143-line systemd journal
- `migration_ireland_shadow_2026_05_21/per_slug_audit.csv` — per-slug truth-vs-engine table
- `migration_ireland_shadow_2026_05_21/console_repro.csv` — sleeve-level PnL repro vs user's console
- `migration_ireland_shadow_2026_05_21/audit_*.py` — 8 reproducers
