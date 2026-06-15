# Pre-registered RS-MOMENTUM + BTC-regime gate — DSR(N=1)

**Hypothesis (single, pre-committed):** weekly dollar-neutral, LONG 8 strongest-RS alts / SHORT 8 weakest (signal=daily RS score2), traded ONLY when BTC>SMA50 (uptrend). Direction corrected after catching the rs_backtest.py label-swap.

## Result — gated config
- Sharpe (full): **0.91** ann · ann return 29.2% · maxDD -43% · hit 48% · time-in-market 54%
- Train Sharpe 0.74 · Test (OOS) Sharpe 1.45
- Return skew 1.34, kurtosis 19.02
- **DSR at N=1 (= PSR vs 0): 0.940**  — bar 0.95 → FAIL
- Block-bootstrap Sharpe 90% CI: **[0.07, 1.82]** (median 0.88) → CI excludes 0

## Does the gate help? (gated vs ungated vs opposite gate — NOT re-selected)
| variant | Sharpe ann | maxDD | time-in-mkt |
|---|---|---|---|
| gated (BTC up) — REGISTERED | 0.91 | -43% | 54% |
| ungated (always) | 1.52 | -35% | 100% |
| opposite (BTC down) | 1.28 | -18% | 46% |

## Honest caveats
- **N=1 is optimistic.** The base config came from a 180-config grid (its DSR there was 0.24). True pre-registration means committing BEFORE any scan; this is the upper bound, not proof.
- Survivorship (listed coins only), flat 8bps cost (no HL funding/slippage), 2.7y span only.
- The proper next gate is a fresh **forward** period or longer survivorship-free history — not another scan.

## Verdict: Does not clear the bar even as N=1 — shelve.