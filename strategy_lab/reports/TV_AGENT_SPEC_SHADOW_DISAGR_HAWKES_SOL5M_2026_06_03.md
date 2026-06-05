# TV Agent Spec — shadow sleeve `shadow_disagr_hawkes_sol_5m_dn` — 2026-06-03

## Why
Phase-A production-fill re-validation (`REVALIDATION_ENGINE_V2_2026_06_03.md`) found that of the 6
cross-feature lockbox survivors, **exactly one survives engine_v2 fills (native 10Hz, 0.07 winner-only fee,
85ms latency, min_book_events=25, 2¢ spread): DISAGR-HAWKES SOL 5m DN** — win07 **+$3.70/tr, t=2.84,
bootstrap CI [+1.42,+6.49]**, and a clean fill-selection test (the 2¢ spread filter rejects *losers*: filled
WR 95.3% vs unfilled 75.7%, p<0.001). It is the only genuine directional signal we have beyond the deployed
exit-scalp. Deploy it as a **shadow (paper) sleeve** to accumulate forward OOS fires toward the graduation bar.

⚠️ **Caveats (this is shadow-only, NOT live capital):** edge measured on the rule-discovery window
(Apr24→May25, in-sample-ish), n=128 filled, deep-favorite entry (vwap≈0.87 → fragile to a losing streak).
Graduation bar = **≥200 forward fires + bootstrap CI>0** before any real capital, same as the exit-scalp.

## Sleeve identity
| field | value |
|---|---|
| `sleeve_id` | `shadow_disagr_hawkes_sol_5m_dn` |
| asset / tf | SOL / 5m |
| direction | **DN only** (buy the "Down"/NO token) |
| fire offset | **ws_s + 210s** (i.e. `slot_start − 300 + 210` = 90s before slot open... NO: `ws_s = slot_start − 300`; fire at `fire_us = (ws_s + 210)*1e6` = 90s into the *prior* anchor = 90s before the new slot's start). Use the SAME offset semantics as the cross-feature study: `fire_us = (ws_s + fire_offset_s)*1_000_000`, `fire_offset_s=210`. |
| notional | $25 |
| mode | `paper_only: true`, `mode: shadow` |
| event_type | distinct `sleeve_disagr_hawkes` so it's filterable in `trading.events` |
| entry | $25 L25 book-walk on the Down token |
| spread gate | same-token bid-ask on the Down (buy) token: `ask0 − bid0 ≤ 0.02` (see §Spread note) |
| fill guard | `min_book_events ≥ 25` in the 120s pre-fire window; reject if under-filled (<50% of $25) |
| exit | **HOLD to resolution** (directional bet; DN wins if chainlink outcome = Down) |
| one-shot | yes — one fire per (slug) |

## The fire condition (all three must hold at `fire_us`)
```
fire DN  iff   mp_skew < 0   AND   imb5_diff > 0   AND   hawkes_lambda_imbalance < -0.2
```
This is the "disagreement-with-Hawkes-confirmation" pattern: microprice leans DOWN (`mp_skew<0`), L1 depth
disagrees and leans UP (`imb5_diff>0`), and the Binance flow Hawkes intensity confirms net SELL (`<−0.2`).

## Feature computation — these are NOT in the current `BarContext`; define them live

All evaluated at `fire_us` (= `(ws_s+210)·1e6`), strictly causal. Books from the WS BookMirror; flow from the
in-memory Binance 1s buffer (the same buffer that already feeds `cvd_30s`/`macd_hist`).

### 1. `mp_skew` (cross-token L1 microprice deviation skew, in bps)
Per token, from the L25 snapshot at `fire_us` (latest snap with ts ≤ fire_us+85ms latency, ≤60s stale):
```
mid       = (ask0 + bid0) / 2
mp_simple = (bsz0 * ask0 + asz0 * bid0) / (bsz0 + asz0)      # Stoikov L1 microprice
mp_dev_bps = (mp_simple - mid) / mid * 1e4
```
Compute for BOTH the Up token and the Down token, then:
```
mp_skew = mp_up_dev_bps - mp_dn_dev_bps
```
(`bsz0,asz0` = L1 bid/ask DOLLAR sizes; `ask0,bid0` = best prices.) Skip the fire if either token's L1 is
missing/non-finite.

### 2. `imb5_diff` (cross-token 5-level book imbalance differential)
Per token, from the same L25 snapshot, using dollar sizes at levels 0..4 (finite prices only):
```
s_top5 = sum(ask_size[0:5]) + sum(bid_size[0:5])
imb5   = (sum(bid_size[0:5]) - sum(ask_size[0:5])) / s_top5      # 0 if s_top5==0; range [-1,1]
imb5_diff = up_imb5 - dn_imb5
```

### 3. `hawkes_lambda_imbalance` (EWMA Hawkes flow intensity imbalance, range [-1,1])
From Binance SOLUSDT **1-second** bars (the live engine already keeps a 1s buffer with buy/quote volume +
trade count — same source as `cvd_30s`). Sampled at `fire_us − 1s` (strict causal). EWMA recurrence,
**half-life 60s**:
```
DECAY = exp(ln(0.5)/60)        # ≈ 0.98858
# per 1s bar:
pct_buy = buy_vol / total_vol        (0.5 if total_vol == 0)
is_buy  = 1.0 if pct_buy > 0.6 else 0.0
is_sell = 1.0 if pct_buy < 0.4 else 0.0
w       = clip(trades_count, 0, q99) / median_nonzero_trades_count    # trade-count weight
buy_event  = is_buy  * w
sell_event = is_sell * w
lambda_buy[i]  = DECAY*lambda_buy[i-1]  + (1-DECAY)*buy_event[i]
lambda_sell[i] = DECAY*lambda_sell[i-1] + (1-DECAY)*sell_event[i]
lam_total      = lambda_buy + lambda_sell
hawkes_lambda_imbalance = (lambda_buy - lambda_sell)/lam_total   if lam_total>0 else 0.0
```
Warm the EWMA over ≥300s (5 half-lives) of 1s bars before `fire_us`. `q99`/`median_nonzero_trades_count` are
rolling stats over the warm-up buffer. If <300s of 1s bars are available → `f7_decision`-style skip the fire
(log reason `hawkes_warmup`).

## Spread note (read before wiring the gate)
The Phase-A validation that produced the +$3.70/tr edge used the **same-token bid-ask** spread on the buy
(Down) token (`ask0 − bid0 ≤ 0.02`) — NOT the live cross-token arb spread. Per CLAUDE.md, the live sniper_v5
controller uses a *cross-token* spread definition that rejects ~99% of fires on real books. **For
apples-to-apples with the backtested edge, this shadow sleeve MUST use the same-token bid-ask gate.** Wire
it explicitly; do not inherit the cross-token spread filter. (If you want a second arm, also log the
cross-token spread value on each fire for later comparison, but gate on same-token.)

## Audit / observability
Emit on every evaluation a `poly_updown_signal`-style row with: `mp_skew`, `imb5_diff`,
`hawkes_lambda_imbalance`, the same-token spread, cross-token spread (logged, not gated), `entry_vwap`,
`fill_ok`, `n_book_events`, reason ∈ {order_placed, no_signal, wide_spread, few_book_events, underfill,
hawkes_warmup}. On resolution emit the standard `poly_updown_resolution` (won, pnl_usd, entry_price,
entry_qty, outcome) with `event_type=sleeve_disagr_hawkes`.

## Acceptance / verification
1. Unit: feed a synthetic snapshot where `mp_skew<0, imb5_diff>0, hawkes<−0.2` → fires DN; flip any one → no fire.
2. Unit: hawkes warm-up <300s → `hawkes_warmup` skip, no fire.
3. Unit: same-token spread 3¢ → `wide_spread` skip (this is the gate that rejects the losers).
4. Live canary (shadow): after deploy, confirm `trading.events` shows `sleeve_disagr_hawkes` fires on SOL 5m
   DN with `entry_vwap≈0.85–0.90` and the logged features matching the fire condition. Target fire rate ≈
   the backtest (~half of raw signals pass the spread gate).
5. Weekly: track filled-fire WR + bootstrap $/tr (win07 fee) toward the ≥200-fire / CI>0 graduation bar.

## Plumbing (per the engine audit)
- Add to `backend/app/configs/poly_sniper_v5_sleeves.yaml` + matching tuple in
  `strategies/polymarket/sniper_v5_sleeves.py` (kept in sync by `tests/.../sniper_v5/test_sleeves.py`).
- Register the three feature computations + the fire predicate as a new gate `g_disagr_hawkes` in
  `strategies/polymarket/sniper_v5_gates.py` (or a new `strategy_mode="disagr_hawkes"`). `paper_only: true`.
- Promote to live only after the forward gate passes (flip `paper_only:false`, `mode:live`).

## Source
`strategy_lab/reports/REVALIDATION_ENGINE_V2_2026_06_03.md` (validation + fill-selection),
`strategy_lab/cross_feature_2026_05_26/{revalidate_engine_v2_2026_06_03.py, fill_selection_check_2026_06_03.py}`,
`strategy_lab/reports/CROSS_FEATURE_RULES_2026_05_26.md` (original rule + feature formulas).
