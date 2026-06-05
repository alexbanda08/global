# Directional Up/Down Backtest — Full Gate Battery (2026-05-28)

Backtest of the decoded directional strategies over the **full 33-day canonical
window** (Apr 24 – May 27), all 6 markets (BTC/ETH/SOL × 5m/15m), with the
complete robustness gate battery. This is the go/no-go on the wallet decode.

## Method
- **Data**: canonical, full granularity. L25 order book at **native 10Hz**
  (`subsample_1hz=False`), Binance **1s** klines for price/returns, Chainlink RTDS
  for the oracle, 1m closes for EMA slope. Outcome truth = chainlink resolutions.
- **Engine**: `engine_v2.LegacyConfig` (2%-on-profit = production fee), `$25` taker
  fill via `book_walk_fill` (real book walk, strict-asof, no future leak). LiveMimic
  (poly curve) computed as sensitivity.
- **Stage 1** `directional_scan.py`: per (slug, offset) records causal signals + real
  fills for BOTH sides. **Stage 2** `eval_strategies.py`: strategies + gates + plateau.
- **Universal gates per fire**: side book fills; entry_px ∈ [0.55, 0.92]; same-token
  spread (ask0−bid0) ≤ 0.02 (BTC/ETH) / 0.025 (SOL). Cross-token spread variant
  (live def `|up_vwap5−(1−dn_vwap5)|`≤0.02) reported alongside.
- **Robustness gates**: G1 mean PnL>0 · G2 walk-forward (≥75% of 2-day test windows +)
  · G3 permutation (outcome-shuffle MCPT, p<0.05) · G4 bootstrap (95% CI lower>0) ·
  Plateau (sweep offset×px_lo×px_hi → fraction of grid cells +EV; PASS≥0.75).

## Strategies tested
- `mom_ema` — Up if ema9_slope>0 else Down (the decoded cross-asset signal)
- `mom_ema_sel` — same but only fires on strong (top-30% trailing) |ema9_slope|
- `mom_ret60` — Up if 60s binance return>0
- `mom_strike` — Up if binance already past the strike
- `clbasis_rel` — binance−chainlink divergence vs its trailing ambient (~13bps);
  fire only on EXTREME deviation (Up if dev>+3bps, Down if dev<−3bps)

## Headline result
**Only ONE cell passes the full battery (G1+G2+G3+G4+Plateau): `btc-5m clbasis_rel`.**

| market | strategy | n | WR | entry px | $/trade (legacy) | G1 | G3 p | G4 CI-lo | G2 WF | Plateau |
|---|---|---|---|---|---|---|---|---|---|---|
| **btc-5m** | **clbasis_rel** | **64** | **85.9%** | 0.688 | **+6.31** | ✅ | 0.0005 | **+2.93** | ✅ | ✅ 0.978 |
| sol-15m | clbasis_rel | 45 | 84.4% | 0.724 | +4.34 | ✅ | 0.0010 | +0.28 | ✅ | ❌ 0.231 |
| sol-15m | mom_ema | 1445 | 72.3% | 0.707 | +0.39 | ✅ | 0.0005 | −0.47 | ❌ | ❌ |
| btc-15m | mom_ema | 1770 | 71.0% | 0.699 | +0.24 | ✅ | 0.0005 | −0.55 | ❌ | weak |
| eth-5m | clbasis_rel | 71 | 69.0% | 0.691 | −0.70 | ❌ | 0.0060 | −4.69 | ❌ | ✅ 0.867 |
| *(all other momentum cells)* | | 1.4k–5.1k | 68–75% | ~0.69 | −0.07 to −0.84 | mostly ❌ | 0.0005 | negative | ❌ | ❌ |

Full 30-row table: `data/v4/canonical/_results/dir_eval_results.csv`. Plateau grids:
`dir_eval_plateau.json`.

## What the gates prove

### 1. The directional signal is REAL — but already priced
**G3 (permutation) PASSES in every single market×strategy** (p = 0.0005–0.0105).
The direction picks are genuinely correlated with the chainlink outcome — the
decoded wallets are NOT lucky. WR sits at a robust 68–75% blind, 84–86% on the
selective cl_basis cells.

**But mean entry price ≈ win rate** (e.g. eth-5m: WR 68%, entry $0.69). At those
prices a 70% hitter is at break-even, and the 2% winner fee tips it negative. So
the **blind momentum-taker family is net-negative / marginal** and fails G1, G4,
walk-forward, and plateau almost universally. The Polymarket book has already
moved with Binance by the time you fire → you pay for the momentum you see.

Selecting only *strong* momentum (`mom_ema_sel`) makes it **worse**, not better —
strong signal ⇒ even higher entry price, no net gain.

### 2. The edge lives in EXTREME oracle divergence, not in trend-following
`clbasis_rel` fires rarely (~45–70 times in 33 days ≈ 2/day) — only when Binance
has diverged from the Chainlink RTDS oracle by an unusually large amount vs the
ambient ~13bps. At those moments the chainlink-keyed resolution is highly likely
to catch up AND the Polymarket price has under-reacted → genuine mispricing.
- **btc-5m: +$6.31/trade, WR 85.9%, ALL FIVE GATES PASS** (plateau 0.978 = 98% of
  the offset×price grid is +EV → robust to parameters, not a single-point fit).
- **sol-15m: +$4.34/trade, WR 84.4%, 4/5 gates** (plateau fails — fragile to params).
- eth/sol-5m and btc/eth-15m cl_basis: do NOT hold up (negative or plateau-fragile).

This matches the wallet decode: the profitable wallets weren't just trend-followers;
the real alpha was in **selective, extreme binance-leads-chainlink** moments + cheaper
execution.

## Caveats
- **Small n on the survivors** (btc-5m n=64, sol-15m n=45). Statistically significant
  (G3/G4 pass) and plateau-robust on btc-5m, but 33 days only — needs forward
  validation + threshold tuning before any size.
- **Execution model is taker at +60s/+180s.** The losing momentum cells would flip
  if entry were ~10c cheaper (maker/limit or earlier). The wallets entered at
  0.59–0.67 vs our blind ~0.69 → a maker variant of the momentum signal is the
  untested upside path.
- Cross-token spread filter barely changes results here (tight surviving books);
  not the 99%-block seen in the V5 live incident, because the entry_px+same-token
  gates already remove wide books.
- Fee = legacy 2%-on-profit (production reality per CLAUDE.md). LiveMimic poly-curve
  would make every momentum cell more negative; cl_basis survivors shrink but stay +.

## Verdict per strategy
| strategy | verdict |
|---|---|
| mom_ema / mom_ret60 / mom_strike | **NOT deployable** — real signal, efficiently priced, net-negative as blind taker |
| mom_ema_sel | **NOT deployable** — selectivity raises WR but raises entry price more |
| **clbasis_rel (btc-5m)** | **DEPLOY-CANDIDATE** — passes full battery; forward-test + grow n first |
| clbasis_rel (sol-15m) | **WATCH** — 4/5 gates, plateau-fragile; corroborates the mechanism |
| clbasis_rel (eth, sol-5m, btc-15m) | not robust |

## Recommended next steps
1. **Forward-test `clbasis_rel` on btc-5m** paper-live; log every fire; re-run G3/G4
   weekly on accumulating n (kill-switch: G3 p≥0.05 or G4 CI-lo≤0).
2. **Threshold sweep** the cl_basis deviation (currently +3bps) + trailing-baseline
   window as an explicit plateau axis to confirm robustness beyond the price/offset grid.
3. **Maker variant of momentum** — test posting limit orders ~5–10c below the
   momentum-side ask to capture the trend signal at the wallets' cheaper entry; this
   is the one path that could rescue the (real but priced-out) momentum signal.

## Artifacts
- `strategy_lab/directional_signal/directional_scan.py` — stage-1 feature+fill scan
- `strategy_lab/directional_signal/eval_strategies.py` — stage-2 strategies+gates+plateau
- `data/v4/canonical/_results/dirscan_{asset}_{tf}.parquet` — per-fire scan tables (6)
- `data/v4/canonical/_results/dir_eval_results.csv` — 30-row gate summary
- `data/v4/canonical/_results/dir_eval_plateau.json` — plateau grids
- Upstream: `DECODE_SYNTHESIS_2026_05_28.md`, `DIRECTIONAL_WR_SCAN_2026_05_28.md`
