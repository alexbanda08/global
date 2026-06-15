# MAKER QUEUE-AWARE SHADOW — b945 replication, all quoting policies tested — 2026-06-12

_Operator was RIGHT that maker strategies CAN be shadow-tested: with the trade tape + L25 books we
built a queue-aware fill sim (FIFO strict lower bound + proportional-share upper bound, bracketing
truth). Runners: `wallet_hunt/_maker_queue_bt.py`, `_maker_ladder_bt.py`. Universe: ALL 4,729
btc-updown-15m windows Apr 22 → Jun 11 (50 days), $1 orders, hold-to-redeem, winner-only 0.07 fee,
+0.0015/sh rebate, FULL resolutions (no 05-28-style censoring). 12 pre-registered cells total._

## Headline: fills are REAL — economics are NOT (at our scale/policies)

| Arm (policy) | fill% | both-sides | $/fired window | CI95 | verdict |
|---|---|---|---|---|---|
| A: join best bid BOTH tokens, track (faithful b945) — FIFO | 72% | 68% | **−0.053** | [−.089,−.017] | SIG-NEG |
| A — proportional | 75% | 74% | −0.050 | [−.067,−.032] | SIG-NEG |
| B: favorite band [0.55,0.97] only, track — FIFO | 19% | — | −0.002 | [−.041,+.037] | flat |
| B — proportional | 36% | — | +0.003 | [−.018,+.023] | flat |
| C: static ladder bid−2¢/−4¢ BOTH tokens | 72-74% | 33-35% | **−0.411** | [−.435,−.386] | SIG-NEG (adverse selection) |
| D: static ladder, favorite only | 31% | — | −0.243 | [−.288,−.199] | SIG-NEG |

## What this establishes
1. **The 06-11 "maker = 0% fills" verdict is OVERTURNED for the resting-bid regime** — that sim's
   price-through criterion was the wrong model. Queue-aware: 72-76% of windows fill, 68-74% both
   sides. The shadow_engine approach (trade-tape + queue share) is validated and now extended
   (FIFO mode). **Reusable asset for any future maker idea.**
2. **But no observable quoting policy reproduces b945's +3.1%/slug.** Faithful replication (arm A)
   loses ~−3.7%/window on deployed capital; favorite-band is dust; ladders are toxic.
3. Residual hypotheses for HIS profit (untestable offline): (a) **selective quoting** — ML model D
   showed his fire intensity rises with |oracle move|; providing liquidity exactly during taker
   panics captures wider effective spread (our sims quote unconditionally); (b) queue PRIORITY from
   sub-second requote infrastructure (his article's CPU section); (c) larger pool-prorated rebate
   share at his 2.4M-share volume.

## DECISION (operator to confirm)
- **Do NOT spend the $100 live probe on arms A/C/D** — offline bracket is sig-negative; live can
  only be worse than the FIFO lower bound's economics (fills were never the problem).
- The probe spec (`TV_AGENT_SPEC_MAKER_PROBE_BTC15M_2026_06_12.md`) is SUPERSEDED unless we choose
  to test the ONE untested pre-registered variant: **oracle-gated quoting** (rest favorite-band
  bids only while |rtds_ret_5s| is elevated — the model-D signature). That can be shadow-tested
  first with the same queue sim (+ RTDS join) for free.
- Otherwise: **thread PARKED.** The sum-arb/b945 campaign produced: corrected harness insights,
  the maker shadow capability, the flow/markout map (favorite band +2.4¢, cheap band −2.5¢ —
  reusable for exit policy research), and a definitive "his edge = ops + selectivity, not mechanics."

Artifacts: `wallet_hunt/cache/_maker_queue_bt.parquet`, `_maker_ladder_bt.parquet`.
Prior chain: `WALLET_B945945D_ML_DECODE_2026_06_12.md` → `PAIRLOCK_BT_RESULTS_2026_06_12.md` →
`_maker_flow_study.py` results → this.
