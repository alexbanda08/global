# Shadow Trade Diagnosis — VPS2 vs VPS3 (2026-04-29)

**TL;DR:** Both boxes are firing live, both are losing money. Backtest predicted ~60% hit (volume mode); reality is 22–50%. **VPS3 (V2 HYBRID) is materially worse than VPS2 (V1 HEDGE_HOLD)** — the bid-exit branch is locking in a guaranteed spread loss on every reversed bar.

---

## 1. What's actually firing

| | VPS2 (V1 HEDGE_HOLD, OKX-WS) | VPS3 (V2 HYBRID, Binance-WS) |
|---|---|---|
| Sleeves | 6 (volume only, no `_volume`/`_sniper` suffix) | 6 (volume only — sniper cold-start, returns NONE because Binance backfill not landed) |
| Signals fired | 660 | 1,537 |
| Resolutions | 634 | 586 |
| Hedge skips (`no_asks`) | 6,783 | 272 |
| Hedge+exit both failed | n/a | 15 |
| Hedged positions | **0** | **0** |
| `exited_at_bid` outcomes | n/a | **most of them** |

VPS2's hedge-policy code is firing the trigger but the buy-opposite leg never fills (`no_asks`), so positions ride to resolution naked. VPS3's HYBRID does the same first branch, fails the same way, then **falls through to sell-at-bid exit** — which is where the bleeding starts.

## 2. Hit rate vs backtest

Backtest expectation (V1/V2 guides):
- volume 5m: ~60% hit
- volume 15m: ~59% hit
- sniper 5m q10: 81.4% hit (not running yet — Binance backfill needed)
- sniper 15m q20: 91.3% hit (same)

**VPS2 actuals (V1, ride-to-resolution):**

| sleeve | n | hit % | total PnL | avg PnL |
|---|---|---|---|---|
| BTC 5m | 163 | 49.7 | -$113 | -$0.70 |
| BTC 15m | 53 | 47.2 | -$112 | -$2.11 |
| ETH 5m | 163 | **44.2** | **-$597** | **-$3.66** |
| ETH 15m | 53 | 47.2 | -$134 | -$2.53 |
| SOL 5m | 153 | 49.0 | -$319 | -$2.08 |
| SOL 15m | 49 | 42.9 | -$256 | -$5.23 |
| **TOTAL** | 634 | ~47 | **-$1,532** | -$2.42 |

**VPS3 actuals (V2 HYBRID, exit-at-bid on reversal):**

| sleeve | n | hit % | total PnL | avg PnL |
|---|---|---|---|---|
| BTC 5m | 148 | 30.4 | -$342 | -$2.31 |
| BTC 15m | 51 | 29.4 | -$8 | -$0.15 |
| ETH 5m | 149 | **22.1** | **-$777** | **-$5.21** |
| ETH 15m | 52 | 26.9 | -$108 | -$2.09 |
| SOL 5m | 142 | 29.6 | -$820 | -$5.77 |
| SOL 15m | 47 | 21.3 | -$524 | **-$11.14** |
| **TOTAL** | 589 | ~27 | **-$2,578** | -$4.38 |

VPS3 hit rate is **below random for a 50/50 binary** (random = 50%, observed = 27%). That's not a "small edge gone" — the V2 exit path is *systematically* losing.

## 3. Root causes (in order of severity)

### A. The HYBRID 5-bp reversal trigger is too tight (the killer)
- V2 says: "every ~10s, if 1m close has reversed ≥5 bp against signal → hedge or exit."
- 5 bp on BTC at $80k is ~$40. **Normal 1m noise**.
- The strategy fires entry at the binary's window-start, then within seconds the underlying ticks 5 bp the wrong way (almost guaranteed in any 1m), the hedge attempt fails (opposite ask thin/empty on Polymarket UpDown — the side that just got cheap has no offers), and the fallback sells at bid.
- Sample resolved row: entry @ $0.50, exit @ $0.48 → -$1.18 on $25 = -4.7% per round trip, before any directional outcome matters.
- Effect: ~75% of resolutions land in `exited_at_bid` — outcome is "we ate the bid-ask spread."

### B. Entry pricing — paying the ask
Fill price distribution on VPS3:
```
0.50 → 127 fills
0.51 → 126
0.52 → 119
0.53 → 221  ← peak
0.54 → 49
```
Average entry ≈ $0.52. By the time the order lands, the book has already moved to price the signal. We're hitting the ask, not midpoint. At a $1 binary payoff:
- Pay $0.52, win 50% → +$0.50 × 0.5 − $0.52 × 0.5 = **−$0.01 per share**, naked-EV negative even at 50% hit.
- Pay $0.52, win 60% (backtest claim) → +$0.50 × 0.6 − $0.52 × 0.4 = **+$0.09 per share**, viable.

The backtest may have priced fills closer to midpoint or used post-trade reference prices. Live taker fills are running 2–3 bps worse than backtest assumed.

### C. Feed lead-lag — Binance-WS is FASTER than Polymarket book
This is why VPS3 is worse than VPS2:
- Binance-WS feed gets the 1m close ~100 ms before OKX-WS in many cases.
- VPS3 fires the signal earlier → catches the 5-bp reversal earlier → triggers the disastrous bid-exit branch more often.
- VPS2 with OKX-WS reacts later, the 5-bp reversal "noise" already mean-reverted by the time it'd trigger, hedge-trigger fires less, position rides to resolution at random ~47% hit.
- VPS2's "worse" feed is accidentally the safer config because it under-triggers the broken exit logic.

### D. ETH 5m ate the most damage
Both boxes show ETH 5m as the worst sleeve (-$597 / -$777). Likely structural — ETH 5m UpDown markets resolve slightly differently or have thinner liquidity than BTC/SOL. Worth a per-symbol audit but it's the same direction on both boxes, just amplified by the V2 exit path.

### E. Sniper isn't running yet
- Binance backfill not loaded → cold-start → `NONE` → 0 sniper fills.
- All 1537 signals on VPS3 are volume-mode. We have no live sample of the supposedly 81%/91% sniper edge.
- Whether sniper survives live as well as backtest is **completely untested**.

## 4. What this means for the original backtest

The V2 backtest reportedly showed +0.9–2.0 pp ROI lift from the bid-exit branch over HEDGE_HOLD. Live shows the bid-exit branch is **−$1,000+ worse** than HEDGE_HOLD. Possible causes (all need ruling out):

1. Backtest exit threshold differs from live (5 bp vs something larger).
2. Backtest priced bid-exit at mid, not at actual top-of-book bid (live bids are systematically ~5–8 bps below mid on the losing side).
3. Backtest timing: bar-close granularity (every 1m) instead of the live ~10 s tick — so the trigger fires far less often in backtest.
4. Backtest used Chainlink-fast resolution prices for both legs; live's exit path uses live order book bid which is noisier.

## 5. Recommended actions (priority order)

1. **STOP THE BLEEDING — flip VPS3 to HEDGE_HOLD or disable bid-exit.**
   - `TV_POLY_HEDGE_POLICY=HEDGE_HOLD` on VPS3, restart `tv-engine`.
   - Removes the bid-exit branch. Positions ride to resolution. Hit rate should jump from 27% → ~47% (matching VPS2).
   - Still negative EV (taker entry at $0.52), but ~$1k less negative per equivalent sample.

2. **Audit the V2 simulator vs live execution.**
   - Pull last 100 VPS3 `exited_at_bid` events (entry px, exit px, time delta, 1m close at trigger).
   - Replay the same windows through the V2 backtest engine. Confirm:
     - Trigger fires at the same wall-clock seconds.
     - Exit price matches actual top-of-book bid (not mid).
     - Hedge-attempt fails on the same fraction.
   - If simulator passes more than live → simulator bug. If they match → 5-bp threshold is wrong.

3. **Recalibrate the reversal threshold.**
   - Measure realized 1m noise σ on BTC/ETH/SOL during 5m UpDown windows in the historical book data on VPS2.
   - Set the threshold to ≥3σ of that noise (probably 15–25 bp, not 5).
   - Re-run V2 backtest with the new threshold; if EV doesn't recover, kill the bid-exit branch entirely.

4. **Audit entry pricing vs backtest.**
   - For each VPS3 fill, check the L10 book snapshot at the entry timestamp on VPS2. Did backtest assume a tighter price than live got?
   - If yes, change to maker-entry (the V1 strategy_lab repo has `polymarket_maker_entry.py` — sit on the bid for N seconds, fall back to taker if not filled).

5. **Get sniper firing.**
   - Land the 15-day Binance backfill on VPS3 (per `SNIPER_DATA_SPEC_VPS3.md`).
   - Sniper threshold becomes computable. 6 sniper sleeves auto-activate.
   - Sniper hit rate is the real thesis. Without it the strategy has no edge to defend.

6. **Don't ramp to live.** Current shadow PnL is −$4,000 combined in ~24h of trading at $25/trade. Live at any size is suicide until #1–#5 land.

## 6. Honest assessment

The strategy as currently shipped is structurally short the bid-ask spread of Polymarket UpDown books. Backtest claimed +28% ROI on sniper q10 — that result lives or dies on entries closer to mid and a less trigger-happy exit. Both assumptions break in live. Until #2 explains the gap, treat all backtest numbers as suspect.

The data and infra are fine. The signal might still be real. The execution path between signal and PnL is broken.
