# Scalp Live Audit — Ireland + VPS3 (2026-06-06)

Two-host audit of the exit-scalp implementation vs the developed optimal spec. Sonnet subagents per host.

## Verdict: core logic SPEC-TRUE on both; 3 actionable divergences.

## Hosts
- **Ireland** (`ssh vps_ireland`, live exec, git `af59d38 deploy/ireland`) — runs ONE scalp sleeve live.
- **VPS3** (`ssh vps3`, shadow + storedata, git `96d456d4 deploy/vps3`) — full research fleet, paper.

## Spec-true (both hosts)
| item | spec | status |
|---|---|---|
| entry gate `g_oracle_lag_with` | δ=`(feed−oracle)/oracle·1e4` ∈ [5,12]/[3,12]; dir==leading | ✓ |
| lag anchor | snapshot at fire_us = slot_start+5s (offsets=(5,)) | ✓ |
| entry_band | (0.0,0.55) on `_v1`, None on `_control_v1` | ✓ |
| exit deadline | fire_us + scalp_exit_offset_s(=60)·1e6 → +60s, walk bids | ✓ |
| notional | $25 (δ5) / $5 (δ3); Ireland live $1 | ✓ |
| one_shot/BOTH | yes | ✓ |
| authority | python `SNIPER_V5_SLEEVES` (yaml stale/unused) | ✓ |

## VPS3 fleet (full, paper)
BTC/ETH × 5m/15m × {v1,control} × {δ5 $25, δ3 $5} = 16, **plus** TOD2 (`g_hour_not_in(12,17)`) variants **plus**
SOL/DOGE/BNB/XRP extended group (XRP added 2026-06-05) — i.e. this session's TOD + multi-coin specs are already
in the code. Extended-asset sleeves fire signals but ~0 scalp-exits (lag gate rarely passes on thin alts — matches
the SOL/fill finding). All `shadow_` prefix → paper.

## Ireland (live)
Only `shadow_scalp_exit_btc_5m_d3_v1` (BTC 5m δ3, entry_band (0,0.55), +60). **LIVE-PROMOTED**: on
`TV_POLY_SNIPER_V5_LIVE_ALLOWLIST`, fires real orders as `..._LIVE` at $1/fire (max $2). ~16 live signals, 8 real
scalp-exits, 15 held-to-resolution so far.

## 🔴 Divergences from the validated OPTIMAL (act on these)
1. **TP@0.65 + stop@(fill−0.10) active on BOTH hosts** (`scalp_tp_bid=0.65, scalp_stop_delta=0.10, scalp_poll_s=5`).
   `SCALP_DYNAMIC_EXIT_2026_06_04` proved take-profit CAPS RUNNERS and underperforms the pure +60 exit; the hedge
   sweep showed always-sell-at-+60 dominates stops. **This is the biggest live edge-leak. → disable TP (set ≥0.99)
   + disable stop; revert to pure +60.** (Maker-exit test #1 should also be vs the pure-+60 baseline, not TP.)
2. **Ireland live $1 capital BEFORE the ≥200-fire graduation gate** (~16 fires). Tiny/low-risk but ahead of the
   stated gate — confirm intentional micro-live accrual.
3. **Shadow `sell_leg_fee=0.0`** — shadow scalp PnL (e.g. the +$4.49/tr btc_5m_v1 cited in VPS3 verification)
   OVERSTATES by the real taker sell fee. Re-baseline before comparing to live wallet.

## Non-issues
- `spread_filter=0.05` (both) vs 0.02 sniper default = BY DESIGN (lag edge lives in dislocated/wide books).
- TP/stop are a *post-spec addition*, not a corruption — but our research says remove them.

## Action
- TV spec to disable TP/stop (pure +60) — see next.
- Then test maker-exit-with-taker-fallback as the exit upgrade (favorable selection).
