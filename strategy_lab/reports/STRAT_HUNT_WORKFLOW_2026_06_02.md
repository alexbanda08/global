# Strategy Hunt Results — 2026-06-02

Generated: 2026-06-02 | 7 hypotheses tested across 6 cells (btc/eth/sol × 5m/15m)

---

## Ranked Results Table

| Hypothesis | Best Cell | n | WR | WR−Implied | Block CI lo | Mean PnL | Verdict |
|---|---|---|---|---|---|---|---|
| moneyness_t | btc_5m | 60 | 0.867 | +0.084 | +1.228 | +$2.32 | **PASS** |
| clbasis_tod | btc_5m | 47 | 0.809 | +0.118 | +0.259 | +$3.49 | WEAK |
| clbasis_lowvol | btc_5m | 89 | 0.562 | +0.065 | −4.015 | +$3.24 | WEAK |
| hl_liq_cascade | btc_5m | 57 | 0.772 | +0.068 | −3.431 | +$1.06 | WEAK |
| perp_funding_oi | sol_5m | 33 | 0.697 | +0.057 | −3.393 | +$0.46 | WEAK |
| polyflow | eth_15m | 615 | 0.712 | +0.046 | −0.393 | +$0.62 | FAIL |
| xasset_btc_lead | eth_5m | 2306 | 0.690 | +0.021 | −1.057 | −$0.33 | FAIL |

---

## G1/G2/G3 Gate Assessment

**Gate definitions:**
- G1: mean_pnl > 0 (directional profitability)
- G2: WR > implied (positive edge above entry cost)
- G3: block-bootstrap 95% CI lower bound > 0 (variance-adjusted significance)

### PASS: moneyness_t (btc_5m)

- n=60, WR=86.7%, WR−implied=+8.4pp, block CI lo=+1.228, mean_pnl=+$2.32
- G1 PASS (mean_pnl > 0), G2 PASS (WR > implied), G3 PASS (CI lo > 0)
- Only hypothesis to clear all three gates.
- **Caveats:** all 60 fires are UP-only (BTC above strike 91% of time in this regime); DOWN side has n=5 (untested). Thin n=60 on 11 UTC days. Regime overlap with other BTC-5m signals (clbasis_tod also targets btc_5m at higher WR but with wider CI). Signal reduces to "BTC is trending above strike at offset=60s → bet Up at vwap~0.79" — mechanically similar to a time-in-window moneyness filter. Not an independent alpha source until the DOWN direction is tested.

### WEAK (fail G3 or n < threshold)

- **clbasis_tod** (btc_5m): WR=80.9%, CI lo=+0.259 barely positive but n=47 at all-day scope; TOD restriction hypothesis is falsified (08-16 UTC is strongest band, not 00-08). Mean_pnl=+$3.49 is the highest of any cell in the hunt.
- **clbasis_lowvol**: CI lo=−4.02, fails G3 despite positive mean_pnl; regime filter kills sample.
- **hl_liq_cascade**: btc_5m CI lo=−3.43; only 22 unique days in bootstrap with HL liq data ending May 27.
- **perp_funding_oi**: futures window is only ~35h (2 calendar days) — block bootstrap degenerate; re-test at >=2 weeks.

### FAIL

- **polyflow**: signal is not independent of price level (mechanically follows vwap gate).
- **xasset_btc_lead**: BTC/ETH/SOL cl_basis are 0.989 correlated; no cross-asset lead; all cells negative PnL.

---

## Efficient-Market Prior Note

One hypothesis (moneyness_t) passed all three gates. This is within the range expected by chance given 7 hypotheses tested (familywise false-discovery rate is non-negligible with a small PASS set). The signal is UP-only in this sample period — half the signal space is untested. Before any position sizing or deployment:

1. Adversarial re-verify: confirm the backtest is not lookahead-contaminated (asof_strict at ws_s, not slot_start).
2. Test the DOWN direction independently once a regime with more below-strike fires is available.
3. Check regime overlap: moneyness_t btc_5m fires heavily overlap with clbasis_tod btc_5m fires — they may be the same underlying condition (BTC trending up in first 60s of 5m window).
4. Extend to a 30+ day OOS window before treating CI lo as reliable.

**Do not deploy on the basis of this hunt alone.**
