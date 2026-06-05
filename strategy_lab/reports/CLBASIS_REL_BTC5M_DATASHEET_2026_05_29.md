# Strategy Data Sheet — `clbasis_rel` BTC-5m (the one validated edge)

The single strategy that survived the full bug-audit + harsh-cost gate battery (look-ahead clean,
no survivorship, no overfit, HIGH Polymarket fee + $0.01 tx, block-bootstrap + Bonferroni).

## How it works (mechanism)
Polymarket BTC up-down 5-minute markets **resolve on the Chainlink Data Streams (RTDS) oracle**, which
**lags Binance spot**. When Binance diverges from the Chainlink oracle by an UNUSUALLY large amount
(relative to the ambient ~+13 bps offset), the chainlink-keyed resolution will catch up to Binance →
the diverged side is the likely winner, and the Polymarket price has not yet fully repriced it.

**Signal (causal, computed at fire time `t = slot_start + 60s`):**
1. `cl_basis_bps = (binance_1s_px − chainlink_RTDS_px) / chainlink_RTDS_px × 1e4`
2. `dev = cl_basis_bps − trailing_median(cl_basis_bps, last ~200 slugs)`  (de-means the structural offset)
3. Fire when `|dev| > ~3 bps`:  `dev > +3` → **buy Up**;  `dev < −3` → **buy Down**
4. Gate entry price ∈ [0.55, 0.92]; same-token spread (ask−bid) ≤ 0.02. Hold to chainlink resolution.

## Validated stats (33.5-day canonical window, btc-5m, $25 stake, REALISTIC cost = 0.07·p·(1−p) fee + $0.01 tx)
| metric | value |
|---|---|
| n (fires) | **64** over 33.5 days |
| frequency | **~2 fires/day** (rare by construction — only extreme divergence) |
| **win rate** | **86.6%** |
| mean entry price | 0.686 |
| **mean PnL / trade** | **+$5.95** (on $25 stake; ≈ +$0.24 per $1 staked) |
| total PnL (window) | ~+$381–424 |
| **daily PnL** | **~+$12–13 per $25 working capital** |
| G1 edge sign | PASS (+) |
| G2 walk-forward | PASS (7/7 windows positive) |
| G3 permutation | PASS (p = 0.0005; survives Bonferroni over 66 cells) |
| G4 bootstrap 95% CI | **[+$2.55, +$9.03]** (IID); block-bootstrap CI-lo **+$4.26** (stronger) |
| plateau (param robustness) | 0.933 (93% of offset×price grid +EV) |
| threshold robustness | positive for all `thr ∈ [1.5, 5.0] bps` (not cherry-picked) |

## Capital needed
- Fires ~2/day, each held ≤5 min → essentially **never concurrent** → working capital ≈ **1× stake** (~$25–50 buffer).
- **Edge is per-trade fixed (+$5.95 at $25)**, so capital is NOT the constraint — *frequency* is.
- **Scaling levers (in order of safety):**
  1. **Stake up per fire** — but the fill walks the L25 ask; larger size walks deeper → worse vwap →
     edge erodes. Realistic ceiling ≈ $50–150/fire on btc-5m book depth before slippage bites. → maybe ~$25–40/day.
  2. **More cells** (eth-15m, sol-15m) — ONLY if independently gate-validated (do NOT assume transfer; being tested).
  3. **Maker entry** instead of taker — get filled below 0.686 → bigger edge IF queue/latency allows (being probed).
- Bottom line: as a standalone btc-5m taker it's a **small, real, low-capacity** edge (~$12–40/day). Value is as
  a proven building block + a base to add cells / maker execution.

## Requirements & risks
- **Live feeds (already collected by VPS3 storedata):** Binance spot 1s WS, Chainlink RTDS oracle WS,
  Polymarket CLOB L25 book (WS mirror). Execute from **Ireland VPS** (<2ms RTT to Polymarket CLOB on AWS eu-west-2).
- **Latency-sensitive** — it's a lag-arb; fire fast (engine models 85ms). The twins (0x3c58ef42/0xd9dea316) run
  this and concentrate **UTC 00–08**.
- **Risks:** thin n=64 → forward-test in SHADOW before sizing; kill-switch if rolling live G3 p≥0.05 or G4 CI-lo≤0;
  low capacity; possible alpha decay as more bots arb the oracle lag.

## Deploy posture
Shadow-first on btc-5m, $25 stake, log every fire vs chainlink, re-run G3/G4 weekly on accumulating live n.
Promote to live only after a live CI clears zero. Use `engine_v2.RealisticConfig` for all further backtests.
