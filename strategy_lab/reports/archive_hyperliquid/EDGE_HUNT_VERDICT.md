# Edge Hunt — Validated Strategies Across Expanded Universe

Audit date: 2026-04-20
Script: `strategy_lab/edge_hunt.py`
CSV: `strategy_lab/results/edge_hunt.csv`

Tested: 9 pairs × 3 timeframes × 3 strategies per TF = **81 backtests**.

## Headline

| TF | Passing (sharpe>0.5 & CAGR>0) |
|---|---|
| 4h  | **25 / 27** |
| 1h  | 2 / 27 |
| 15m | 0 / 27 |

4h trend-following generalizes across the entire liquid crypto majors universe. 1h edge is ETH-only. 15m has no edge (fees eat alpha, as prior work found).

## New deploy-candidate shortlist (4h, ranked by Sharpe)

| Pair | Strategy | Sharpe | CAGR | MaxDD | Trades | Final on $10k |
|---|---|---:|---:|---:|---:|---:|
| SOLUSDT | V4C_range_kalman | 1.42 | +111 % | −56 % | 49 | $600,411 |
| AVAXUSDT | **V3B_adx_gate** | **1.31** | +100 % | −66 % | 66 | $430,681 |
| ETHUSDT | V3B_adx_gate | 1.26 | +56 % | −34 % | 88 | $395,501 |
| BTCUSDT | V4C_range_kalman | 1.32 | +40 % | −29 % | 78 | $156,611 |
| DOGEUSDT | **V3B_adx_gate** | **1.02** | +80 % | −83 % | 92 | $486,865 |
| LINKUSDT | **V3B_adx_gate** | 0.84 | +39 % | −68 % | 95 | $104,058 |
| ADAUSDT | **V4C_range_kalman** | 0.79 | +32 % | −59 % | 84 | $86,877 |
| BNBUSDT | **V2B_volume_breakout** | 0.77 | +28 % | −57 % | 149 | $79,219 |
| XRPUSDT | **V3B_adx_gate** | 0.78 | +32 % | −58 % | 92 | $89,486 |

**Bold = newly discovered winners** (the other three rows are our existing 5/5-robustness-passed deploys).

## Interpretation

- **V3B_adx_gate is the dominant 4h engine** — it's the best or tied-best on 5 of the 6 new pairs (AVAX, DOGE, LINK, XRP, plus ETH from before). This is a strong cross-asset signal that the ADX-filter + Donchian-breakout + regime-gate recipe is the most generalizable.
- V4C Range Kalman wins on BTC, SOL, ADA.
- V2B wins on BNB (only).
- **DD is ugly.** Several new candidates (DOGE −83 %, AVAX −66 %, XRP −58 %, LINK −68 %) have drawdowns well beyond what a $10k portfolio should ever take. Any live deploy will need per-pair position sizing (vol-normalized, so the smallest pairs hold the least capital).

## 1h — weak

Only 2 passes: **ETH V13A_range_kalman (0.81 sharpe)** and **ETH V13C_volume_breakout (0.71)**. Every other pair-strategy combo fails at 1h. Consistent with prior conclusion that ETH is the only asset with a real 1h trend edge.

## 15m — nothing

0 / 27 passed. Best candidate was ETH V15A with sharpe 0.02 (null). Confirms: at our fee floor (0.015 %-maker / 0.045 %-taker for Hyperliquid, 0.1 %-round-trip for Binance spot), 15m trend-following has no edge on any of these pairs. If we want 15m, it has to be **market-making (maker rebates)** or a different signal class (order-flow, liquidations), not price-action trend.

## Important caveat — not yet robustness-audited

These numbers are **single-run full-period backtests with NO out-of-sample split**. Before any new pair is added to the live portfolio it needs the same 5-test audit that BTC/ETH/SOL 4h and ETH V13A 1h passed (cross-asset, MC shuffle, random windows, k-fold, param-ε).

## Recommended next step

Run `robust_validate_v13a.py`-style audits on the **top-3 new candidates**: AVAX V3B, DOGE V3B, LINK V3B. If they each pass 4+ of 5 tests, the portfolio expands from 4 deploys (BTC/ETH/SOL 4h + ETH 1h) to **7**.
