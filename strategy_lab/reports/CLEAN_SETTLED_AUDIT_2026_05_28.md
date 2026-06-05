> 🚨 **SUPERSEDED (2026-05-28, same day).** The "fully-settled (inv=0)" measure
> below is **biased HIGH** — it structurally excludes directional-loser slugs
> (which never get a REDEEM event and stay `residual_open` forever). The true
> uncensored numbers are net-negative. See
> **`MAKER_ARB_CENSORING_REVERSAL_2026_05_28.md`** (ACC-H-V2 btc 15m: +$4.44 here
> → −$0.41 corrected). Do not use the table below for deploy decisions.

# Clean Fully-Settled Audit — Maker-Arb Sleeves (2026-05-28)

> Authoritative replacement for handoff §2. Computed by
> `strategy_lab/maker_arb_audit/clean_settled_audit.py` on the May 27-28 Ireland
> shadow CSVs. Uses the **fully-settled + active** measure (the only unbiased
> slice — see §3 of `MAKER_ARB_CONTEXT_HANDOFF_2026_05_28.md`).

## Measure definition

Per `(sleeve_id, slug)`, take the last `fill_simulated==1` row. A slug counts iff:
- **settled**: final `inv_up == inv_dn == 0` (engine merged/redeemed everything), AND
- **active**: `n_fills >= 1` (the strategy actually took a position).

`pnl = slug_pnl_so_far` (engine running PnL — verified exact: recon error vs the
cumulative-cash formula = **$0.000000** on every counted slug). No-op slugs
(posted but never filled) are excluded — counting them dilutes the edge to zero.

## Authoritative table (POST_SIZE=20)

| sleeve | n | no-op | win% | mean $/slug | 95% CI | median | total |
|---|---:|---:|---:|---:|---|---:|---:|
| acc_h_v2_eth_15m  | 19  | 0   | 89.5% | **+5.24** | [+2.20, +8.27] | +5.62 | +99.5 |
| acc_pc_v2_eth_15m | 33  | 0   | 84.8% | **+4.78** | [+2.84, +6.72] | +4.00 | +157.7 |
| **acc_h_v2_btc_15m**  | 41  | 0   | 73.2% | **+4.44** | [+2.13, +6.75] | +5.02 | +182.1 |
| acc_pc_v2_btc_15m | 42  | 0   | 69.0% | **+3.21** | [+1.02, +5.39] | +3.86 | +134.7 |
| acc_pc_btc_15m (V1)| 58 | 0   | 62.1% | +2.80 | [+0.87, +4.74] | +3.60 | +162.5 |
| acc_h_btc_15m (V1) | 45 | 0   | 64.4% | +2.33 | [+0.58, +4.07] | +1.17 | +104.6 |
| acc_m_v2_btc_5m   | 157 | 0   | 53.5% | +0.85 | [−0.33, +2.02] | +0.50 | +132.9 |
| acc_m_btc_5m (V1) | 275 | 0   | 56.7% | +0.33 | [−0.54, +1.20] | +1.37 | +90.6 |
| mas_btc_5m (V1)   | 109 | 376 | 43.1% | **−0.79** | [−1.85, +0.27] | −3.67 | −86.3 |
| mas_btc_15m (V1)  | 34  | 127 | 44.1% | **−1.04** | [−3.18, +1.10] | −4.32 | −35.3 |
| mas_v2_btc_5m     | 0   | 235 | —     | inert | — | — | 0 |

## Findings

1. **ACC-H-V2 btc 15m is the deploy candidate.** +$4.44/slug, 73.2% WR, n=41,
   95% CI lower bound **+$2.13** (comfortably positive). eth_15m cells score
   higher but on smaller n.

2. **V2 fixes are validated improvements** in every comparable cell:
   - convergence-cancel: acc_h btc_15m **+4.44 (V2) vs +2.33 (V1)** → ~+$2.1/slug
   - convergence-cancel: acc_pc btc_15m +3.21 (V2) vs +2.80 (V1)
   - PAT-off: acc_m btc_5m +0.85 (V2) vs +0.33 (V1) → ~+$0.5/slug

3. **MAS is NOT "≈flat" — correction to handoff §2.** The "≈$0" was no-op
   dilution masking a real loss:
   - **MAS-V2 took ZERO positions** (235/235 no-op). The min_ask=0.52 + sum_asks
     gate is so tight nothing ever fills → the sleeve is inert, not breakeven.
   - **MAS V1 loses when it actually trades**: −$0.79 (5m) to −$1.04 (15m) per
     active slug, <45% win. Median is sharply negative (−$3.67 / −$4.32).
   - **Recommendation: deprioritize/kill MAS.** Either retune the V2 gate so it
     trades, or accept the maker-arb edge lives entirely in the ACC family.

4. **The biased measures bracket the clean one** exactly as §3 predicts (proof
   the framing is right): for acc_h_v2_btc_15m, REDEEM-only = +$6.80 (biased
   high), all-active-cash = +$3.48 (biased low, censored), clean = **+$4.44**.

5. **Engine accounting is exact** — $0.000000 recon error on all 813 counted
   slugs. The $10/$20/$30 divergences seen globally are confined to the 493
   excluded residual-open slugs (unredeemed inventory the naive cash formula
   can't mark) and do not touch the clean numbers.

## Censoring — why the canonical refresh matters

| | count |
|---|---:|
| settled + active (counted) | 813 |
| **residual_open (recoverable)** | **493** |
| inflight (window not elapsed) | 8 |

The strong 15m sleeves are ~40-50% right-censored:

| sleeve | counted n | residual_open |
|---|---:|---:|
| acc_h_v2_btc_15m | 41 | 26 |
| acc_pc_v2_btc_15m | 42 | 37 |
| acc_h_v2_eth_15m | 19 | 13 |
| acc_pc_v2_eth_15m | 33 | 37 |

Recovering the residual tail would roughly lift acc_h_v2_btc_15m from n=41 to
~67 (+63%) and materially tighten the CI. **This justifies the canonical
refresh (next step).**

## Artifacts

- Script: `strategy_lab/maker_arb_audit/clean_settled_audit.py`
- Per-slug detail: `strategy_lab/maker_arb_audit/_results/clean_settled_per_slug.csv`
- Summary: `strategy_lab/maker_arb_audit/_results/clean_settled_summary.csv`
