# 🚨 Maker-Arb Censoring Reversal — SUPERSEDES handoff §2/§3 and CLEAN_SETTLED_AUDIT (2026-05-28)

> **Headline: the maker-arb "edge" was a survivorship-bias artifact. On the
> truly-uncensored measure, every sleeve is net-negative or flat. DO NOT deploy
> any maker-arb sleeve live.**

This corrects both `MAKER_ARB_CONTEXT_HANDOFF_2026_05_28.md` §2/§3 and the
intermediate `CLEAN_SETTLED_AUDIT_2026_05_28.md`. Both reported ACC-H-V2 btc 15m
at **+$4.44/slug**. The true number is **−$0.41/slug**.

## What changed

After refreshing canonical from VPS3 storedata (chainlink RTDS + resolutions
through May 28 20:00 UTC), the 493 right-censored `residual_open` slugs could be
settled against independent chainlink outcomes:

```
settled_pnl = realized_cash + redemption
realized_cash = cash_received + cash_recovered - cash_spent + rebates - taker_fees   (last sim row, pre-redemption)
redemption    = inv_up·$1 if outcome=='Up' else inv_dn·$1     (losing side pays $0)
```

476/493 residual slugs (100% of the V2 15m cells) gained a chainlink resolution.

## The bias mechanism (verified, not theorized)

The shadow engine books a **REDEEM only for the directional WINNER** (inventory
returns to 0). A directional **LOSER** holds worthless tokens that simply expire
— **no event is logged, inventory never returns to 0** — so a losing slug is
stuck in `residual_open` in *every* snapshot, no matter how fresh.

Verified on `acc_h_v2_btc_15m`:

| bucket | n | composition | mean $/slug |
|---|---:|---|---:|
| orig-settled (inv=0) — counted by §2/§3 | 41 | 32 redeemed directional **winners** (+6.80) + 9 fully-paired (−3.93) | **+4.44** |
| recovered (residual_open) — **excluded** by §2/§3 | 26 | **26/26 directional losers, 0 winners, 0 REDEEM events** | **−8.05** |
| **combined (uncensored truth)** | **67** | all active resolved slugs | **−0.41** |

"Settled-only" counted all 32 directional winners and **excluded all 26 directional
losers** → biased high by ~$4.85/slug. This is structural, not a snapshot-freshness
problem: re-pulling fresher Ireland CSVs would reproduce the same inflated number,
because losers never settle in the log. Only outcome-based settlement fixes it.

Independent cross-check: on the 559 slugs the engine actually redeemed, the engine
REDEEM side agrees with the chainlink outcome **99.64%** — validating both the
outcome lookup and that Ireland resolves identically to canonical chainlink.

## Corrected authoritative table (uncensored, POST_SIZE=20)

| sleeve | n | win% | mean $/slug | 95% CI | median | total | §2 said |
|---|---:|---:|---:|---|---:|---:|---:|
| acc_h_v2_eth_15m  | 32  | 53.1% | **+0.15** | [−2.78, +3.08] | +0.60 | +4.8   | +5.24 |
| acc_h_v2_btc_15m  | 67  | 46.3% | **−0.41** | [−2.58, +1.77] | −0.97 | −27.2  | +4.44 |
| mas_btc_5m        | 109 | 43.1% | −0.79 | [−1.85, +0.27] | −3.67 | −86.3  | ≈0 |
| mas_btc_15m       | 35  | 42.9% | −1.20 | [−3.30, +0.90] | −4.37 | −42.0  | ≈0 |
| acc_pc_v2_btc_15m | 79  | 43.0% | −1.33 | [−3.27, +0.61] | −2.52 | −105.0 | +3.21 |
| acc_m_v2_btc_5m   | 232 | 40.9% | **−1.60** | [−2.63, −0.57] | −1.25 | −370.4 | +0.85 |
| acc_pc_v2_eth_15m | 70  | 42.9% | −2.12 | [−4.15, −0.10] | −3.27 | −148.7 | +4.78 |
| acc_pc_btc_15m V1 | 111 | 36.9% | −2.24 | [−3.92, −0.57] | −2.60 | −248.9 | +2.80 |
| acc_h_btc_15m V1  | 89  | 32.6% | −2.86 | [−4.58, −1.15] | −1.58 | −254.7 | +2.33 |
| acc_m_btc_5m V1   | 460 | 35.2% | **−3.63** | [−4.41, −2.84] | −3.10 | −1667.3| +0.33 |
| mas_v2_btc_5m     | 0   | —     | inert | — | — | 0 | ≈0 |

(orig settled 813 + recovered 471 = **1284 counted**; 15 still censored = missing chainlink.)

### Reading the table
- **No sleeve has a positive edge.** The only ~zero one (acc_h_v2_eth_15m +$0.15)
  has a CI straddling zero on n=32 (~1.5 days).
- Sleeves with enough data are **definitively negative**: acc_m_btc_5m −$3.63
  (CI [−4.41, −2.84], n=460); acc_m_v2_btc_5m −$1.60 (CI below 0, n=232).
- **V2 fixes still help** (less negative than V1): acc_h btc_15m −0.41(V2) vs
  −2.86(V1); acc_m btc_5m −1.60(V2) vs −3.63(V1). Convergence-cancel + PAT-off
  reduce adverse-selected residual — directionally right, but **not enough to
  reach positive**.

## Implications

1. **DO NOT deploy any maker-arb sleeve to live capital.** The shadow edge does
   not exist once directional losers are counted. This overrides handoff §9
   ("Best sleeve to test live: ACC-H-V2 btc 15m") and the deploy-ready framing.

2. **Shadow logging gap (report to TV agent).** The engine never realizes the
   expiry-loss of directional losers — it marks them (optimistically, ~$0.50/
   share) and they never resolve in the log. So `slug_pnl_so_far` and any
   cumulative/operator-dashboard PnL built on it **drift permanently positive**.
   Engine mark on recovered slugs averaged +$1.95 vs actual −$8.05. Fix: book a
   settlement event (−cost) when a held side expires worthless, OR settle all
   open inventory against chainlink at slot_end. This sharpens handoff §7 (the
   dashboard inflation is worse than "mark-to-market vs cash" — losers are never
   booked at all).

3. **The maker-arb thesis needs a real directional/selection edge.** Pure paired
   merging is breakeven-to-negative after pair-completion overpay (the 9 paired
   slugs averaged −$3.93 — see handoff §13 "tighten sum_bids gate"). The PnL
   swing is dominated by the adversely-selected directional residual, which is a
   coin-flip the maker loses on net.

## Caveats / next steps
- V2 sleeves have only ~1.5 days of data (May 27-28). Confirm on a longer window
  — but the mechanism (losers never redeem) guarantees the direction of the
  correction regardless of n.
- To get an even cleaner read, re-pull Ireland shadow CSVs through several more
  days and re-run `settle_residuals.py` (now that canonical covers May 28).
- Consider whether convergence-cancel can be tightened enough to avoid the
  adverse residual entirely (i.e., only ever hold fully-paired inventory). If a
  sleeve can be forced to NEVER carry directional residual, it reduces to pure
  merge-arb — re-evaluate that variant.

## Artifacts
- Settlement script: `strategy_lab/maker_arb_audit/settle_residuals.py`
- Per-slug: `strategy_lab/maker_arb_audit/_results/settled_combined_per_slug.csv`
- Summary: `strategy_lab/maker_arb_audit/_results/settled_combined_summary.csv`
- Superseded: `CLEAN_SETTLED_AUDIT_2026_05_28.md` (settled-only, biased high)
