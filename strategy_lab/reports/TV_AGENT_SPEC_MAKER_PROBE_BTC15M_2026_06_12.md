# TV AGENT SPEC — live micro-maker probe `maker_probe_btc15m` (REAL $, capped $100)

_2026-06-12. Final stage of the b945 sum-arb thread. The ML decode proved the wallet is a passive
two-sided maker (`WALLET_B945945D_ML_DECODE_2026_06_12.md`); queue position is unmodelable offline,
so this is a LIVE probe — NOT a shadow sleeve (paper mode assumes fills, which is the very question).
Offline feasibility PASSED 2026-06-12 (`wallet_hunt/_maker_flow_study.py`, 340 windows sampled):_

| Measured fact (per btc-15m window) | Value | Consequence for this spec |
|---|---|---|
| Taker-sell $ hitting bids | med **$2,150**, 0% empty windows, ~234 prints | fills are flow-abundant; queue is the only question |
| Markout 60s after bid-side prints | overall **+0.5¢** (sellers uninformed) | maker side is structurally fine |
| Markout by price band | **0.55–0.97: +2.4¢** · 0.3–0.55: −0.5¢ · **0.1–0.3: −2.5¢** | quote the FAVORITE band; cheap band is toxic |
| Bid-side flow by time | rises all window: $210 (0-3min) → $929 (11-14.5min) | quote the whole window, weight late |
| Queue at best bid | med 143 sh (p10 13) | $1 (~2-10sh) join is tiny; level turns over 234×/window |

## Probe design — TWO policies, $1 orders, btc-updown-15m, every window, 7 days

**ARM A — `maker_probe_b945` (faithful replication):** join (never improve) the best bid on BOTH
tokens with $1 GTC each, from t+60s. Requote (cancel/replace) when our level is no longer best bid
by >1¢. Cancel all at t+870s. Fills are HELD TO REDEMPTION (no sells). Max 2 requotes per token per
minute (rate hygiene).

**ARM B — `maker_probe_fav` (markout-informed):** identical, but quote ONLY the token whose best bid
is in **[0.55, 0.97]** (the favorite). If both/neither qualify → the higher-priced token / no quote.
Single-sided inventory settles directionally at redeem.

**Caps:** $1/order · ≤$4 working per window across arms · total bankroll **$100** · auto-halt if
cumulative realized PnL < **−$30** or fills show systematic instant-adverse pattern (median 60s
markout of OUR fills < −3¢ after ≥30 fills).

## Instrumentation (the probe IS the data)
Per order: place_ts, level, queue_ahead_estimate (best-bid size at join), requotes, fill_ts/px/sh
or cancel. Per fill: 30s/60s markout, window outcome, redeem value, MAKER_REBATE accrual.
Per window: both-side-filled?, blended pair cost if matched. Emit as `maker_probe.*` events.

## Pre-registered evaluation (after 7 days ≈ 670 windows)
1. **Fill rate:** fills/window per arm (b945 benchmark at scale: ~82; expectation at $1: ≥2-5).
   FAIL if < 0.5/window → queue position is the moat, thread CLOSED permanently.
2. **Fill quality:** median 60s markout of our fills ≥ 0 (arm B expected ≈ +2¢).
3. **Economics:** net $/window incl rebates > 0 with CI (dedup metric, actual wallet flows —
   GROUND-TRUTH RULE: reconcile vs on-chain, not events).
4. **Pair completion (arm A):** % windows both sides filled; blended pair cost vs his 0.94 median.
5. Decision: PASS arm(s) → capacity study at $5 clips (new spec). FAIL → bank the kill, never reopen
   without new evidence.

## Why not just shadow it (answer recorded)
The 06-11 maker sim already "shadow-tested" this at 0% fills under conservative price-through rules,
while the flow study shows $2,150/window actually trades AT the bid — the gap between those two
numbers IS queue reality, observable only with live orders. $100 cap buys the answer permanently.

## Implementation notes
- Maker plumbing: EIP712 GTC post/cancel + user-channel fill tracking — reuse the mint-and-sell
  engine primitives if shipped; otherwise this spec is blocked on that build (flag it).
- This is REAL money: needs the live wallet, not paper config. Deploy on Ireland (CLOB RTT <2ms).
- Keep the deployed scalp sleeves untouched; the probe is additive and independent.
