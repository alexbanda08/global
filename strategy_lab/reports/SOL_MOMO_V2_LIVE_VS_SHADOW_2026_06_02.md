# sol_5m_momo_v2_HOLD_f7 — why live (Ireland) & shadow (VPS3) fire different trades (2026-06-02)

## Setup (corrected)
- SHADOW = VPS3 `poly_updown_signal`, `strategy_mode='momo_v2'`, `mode='paper'`, symbol SOL, tf 5m.
  (NOTE: the momo signal logs with an EMPTY `sleeve_id` + a `strategy_mode` field — an earlier query for
  `sleeve_id LIKE '%momo_v2%'` wrongly returned "none on VPS3". VPS3 DOES run it: 1,420 signals / 138 placed / 24h.)
- LIVE = Ireland same, `mode='live'`; real placements land as `poly_redeemed` under sleeve_id
  `poly_updown_sol_5m_momo_v2_HOLD_f7` (tx_hash, gas, usdc_received).
- Strategy: fire `signal=UP/DOWN` when **`|ret_2m_at_signal| > abs_ret_2m_threshold`** (HOLD-to-resolution).

## Evidence (3h matched window)
| | threshold | example ret_2m values | placed |
|---|---|---|---|
| VPS3 shadow | **0.00151** | −0.00120, 0.00093, −0.00187, 0.00013, 0.00107 | DOWN @ cond `0x69039231…` |
| Ireland live | **0.00151** | −0.00187, 0.00202, 0.00174, −0.00148, −0.00067 | UP @ cond `0x638c050feb…` |

- **Threshold identical (0.00151)** on both → same gate logic.
- **`ret_2m_at_signal` differs per host** for the same time window.
- **They placed on DIFFERENT slots, different directions** (VPS3 DOWN @0x6903, Ireland UP @0x638c).

## Root cause
`momo_v2` is a **boundary-trigger** strategy: fire iff `|ret_2m| > 0.00151`. Many slots sit with `|ret_2m|`
right at the boundary. The two hosts compute `ret_2m` (the 2-min Binance return at the signal anchor) from
**their own Binance feeds at their own bar timing/freshness** (`bar_ctx_age_ms` in the row). A small feed
difference flips a boundary slot between **fire / no_signal — and can flip direction**. Threshold is the same;
the **price read differs** → different fires.

This is the SAME mechanism as the sniper sleeve divergence (`ETH_SHADOW_FIRES_LIVE_DOESNT_BOOKSOURCE_2026_06_02.md`):
a **per-host snapshot/feed divergence at the decision boundary**. For the sniper it was the WS book spread;
for momo_v2 it's the Binance 2-min return.

## Is it a bug?
**Parity issue, not a logic bug.** Both engines run identical momo_v2 code; they just read slightly different
Binance feeds at signal time. On a boundary-trigger strategy that makes them place on different slots, so the
VPS3 shadow does NOT predict the Ireland live fills slot-for-slot.

## Fix (TV agent)
For shadow to predict live, compute `ret_2m_at_signal` (and the threshold's rolling history) from the SAME
Binance feed/snapshot the LIVE host uses — i.e. align the bar source + anchor timing across hosts. Otherwise
boundary slots will always diverge. If exact parity isn't feasible, treat the shadow as an APPROXIMATION and
judge the strategy only by the LIVE wallet (which is what trades).

## Caveat (honesty)
The threshold being identical (0.00151) and the ret_2m streams differing are directly observed. The
attribution to Binance feed/bar-timing is the well-supported explanation (consistent with `bar_ctx_age_ms`
and the boundary behaviour), not a captured side-by-side feed timestamp diff. To prove it cold, match a
handful of identical condition_ids across hosts and compare their `ret_2m_at_signal` + the bar timestamps.
