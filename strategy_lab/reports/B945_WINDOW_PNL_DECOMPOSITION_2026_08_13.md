# b945 — per-window P&L, capital, loss causes, profit sources — 2026-08-13

Cash-truth reconstruction ("a carteira é a única verdade"): per window,
`pnl = redeem_usd − buy_usd`. She NEVER sells and NEVER merges (0 events, 123k fills), so
cash closes exactly. Sample: **Jul 24 → Aug 13 (~20.4 days), 2,868 settled windows**
(22 too-recent excluded). Script: `wallet_hunt/_b945_window_pnl_2026_08_13.py`.

## 1. The headline table

| | **15m (btc+eth)** | 5m (btc+eth) | ALL |
|---|---:|---:|---:|
| windows | 1,058 | 1,810 | 2,868 |
| **capital/window** mean · median · p90 · max | **$982 · $869 · $1,712 · $3,665** | $84 · $58 · $188 · $594 | $415 · $124 |
| **profitable** | **830 (78.4%)** | 1,010 (55.8%) | 1,840 (64.2%) |
| profit total · avg win | **+$71,969 · +$86.71** | +$25,074 · +$24.83 | +$97,043 · +$52.74 |
| **losing** | **228 (21.6%)** | 800 (44.2%) | 1,028 (35.8%) |
| loss total · avg loss | −$11,156 · **−$48.93** | −$27,117 · −$33.90 | −$38,273 · −$37.23 |
| **NET** | **+$60,813 (+$57.48/w)** | **−$2,043 (−$1.13/w)** | +$58,770 (+$20.49/w) |
| ROI on deployed | **+5.85%** | −1.34% | +4.93% |
| $/day | **~$2,981** | ~−$100 | ~$2,881 |

Payoff profile 15m: WR 78.4% × avg win $86.71 vs avg loss $48.93 → payoff ratio 1.77.
Plus **$6,332 in MAKER_REBATE payments in the same period** (16 payments; $12,953
lifetime) — another ~$310/day ≈ **+10.8% on top of trading net**, not included above.

## 2. Where the profit comes from (attribution, 15m)

| source | net | gross + / − |
|---|---:|---|
| **residual settlement** | **+$37,094** | +$53,394 / −$16,300 |
| **paired spread (pvs<1)** | **+$23,719** | +$32,445 / −$8,726 |
| maker rebate (period, all tf) | +$6,332 | — |

Win-source count (830 winners): residual-dominant 535 windows (+$52,764), paired-spread-
dominant 293 (+$18,908), one-sided 2.

**The surprise: the residual is not noise she tolerates — it is her LARGEST profit line.**
This looks contradictory with "residual is adversely selected" until you connect yesterday's
taker finding: she buys the expensive leg as taker late in the window **when the heavy side
is losing**, converting exactly the would-be-losing residuals into pairs. What SURVIVES as
residual is therefore disproportionately the winning side. The taker-completion is not just
pair manufacturing — **it is the selection device that flips the residual book positive**
(+$53k won vs −$16k lost, on heavy-side entries averaging 0.458).

## 3. Why she loses, when she loses (1,028 losing windows)

| cause | windows | $ | share of losses |
|---|---:|---:|---:|
| **residual lost** (heavy side ≠ winner, completion didn't/couldn't fire) | 447 | **−$20,563** | 54% |
| **one-sided window lost** (never got the second leg at all — 5m-dominated: 340 of 341) | 341 | −$11,022 | 29% |
| **paired above $1** (pvs > 1 — she overpays for some pairs) | 240 | −$6,687 | 17% |

Same taxonomy as ours — she just runs it at 1/5th our residual exposure and with the
completion engine trimming the losing tail. Note she is NOT immune to pvs>1 (240 windows,
including 68 on her core 15m book): even the reference wallet pays >$1 for ~8% of its
paired windows and eats it.

## 4. The 5m line is a genuine LOSER for her

−$2,043 over 20 days, 44.2% losing windows, paired leg NET NEGATIVE (−$1,482: her 5m
pairs cost >$1 on average), one-sided coin flips ≈ wash (+$12.3k vs −$10.9k). Combined
with the earlier structure read (ratio 0.42, back-loaded, sums>1): **b945's 5m activity is
either a loss-leader (queue-priming/rebate farming) or simply bad** — it is NOT the
strategy. Every dollar of her edge is the 15m book. This hardens the earlier conclusion:
benchmark 5m against b27 (ratio 4.07, pair-sum 0.983, profitable), 15m against b945.

## 5. Capital usage picture

- 15m: median $869/window, p90 $1,712 — and she pre-places (books exist 80+ min early),
  so working capital spans the active window + pre-quoted future windows + the ~47s
  redemption float. Turnover ≈ $154k/day of buys against ~$1.0M deployed over the period.
- Implied working capital for the 15m operation alone: low-single-digit thousands
  (2 coins × ~$1–1.7k live + pre-placed clips + float) generating ~$3.0k/day + rebates —
  consistent with the +$690k/all-time figure for the group's larger wallet (b27).
- Our current live wallet ($55) is **~30–60× under** the minimum scale at which this
  strategy's economics (rebate tier included) actually express.

## 6. What this changes for us (delta vs current plan)

1. **v5_tc gets a stronger thesis**: TC is not only pair completion — it is residual
   *selection*. The spec's H3 (layer pays for itself) stays, but expect the bigger effect
   on `resid_pnl`, not `tc_locked`. Worth adding `resid_pnl_post_tc` to the verdict read.
2. **15m first for any live scale-up.** Her 5m is negative; b27's 5m is positive but
   thin-margin-high-velocity (needs merge + volume). The 15m book is where a $1k-capital
   maker with queue priority provably earns 5.85% ROI/window-cycle. Our
   `poly_ladder_btc_15m_v3` paper arm should be promoted in priority over any 5m arm once
   the sim reconciles — at 15m our capital constraint also binds 3× less often.
3. **Rebates are 10%+ of the economics** — the arm rankings ignore rebate tiering
   entirely (`rebate_rate_assumed=0.0015` flat). At real scale this needs the actual
   Polymarket rebate schedule.
4. Even the reference eats pvs>1 on 8% of paired windows — our `pair_max_sum` gate at
   0.99 with the epsilon-fixed guard is already tighter than her realized discipline.
