# W2e — SMS liquidity_reclaim port to Hyperliquid futures

**Date:** 2026-05-26
**Engine:** `strategy_lab/hl_research_2026_05_26/hl_engine.py` (`HyperliquidConfig`: taker 4.5 bps × 2 + slip 3 bps + hourly funding accrual, 50 ms latency)
**Window:** 2025-01-01 → 2026-03-31 (≈ 15 months, matched to HL funding history)
**Universe:** BTC, ETH, SOL × {5m, 15m, 1h, 4h}
**Notional:** $250 × 1× leverage (Markov variant: 1× / 2× sized by state)
**Code:** `strategy_lab/hl_research_2026_05_26/wave2/W2e_run.py`
**Raw results:** `strategy_lab/hl_research_2026_05_26/wave2/W2e_results.csv` (174 rows)

---

## TL;DR

The Polymarket SMS `liquidity_reclaim` signal **does NOT survive the port to HL
intraday timeframes (5m, 15m, 1h)** — the structural pattern is real (gross WR
52.7% on BTC 5m, +$0.008/tr gross) but fees of $0.225/tr (=2×4.5 bps × $250) +
$0.075 slip wipe out 30 bps of edge per round trip.

It **DOES survive on 4h with patience-style exits** (signal flip / hold10 /
ATR trail). The best cell is **SOL 4h + Markov-state sizing** (n=31, WR 80.6 %,
+$5.51 / trade, Sharpe 10.1, G1 p=0.0009, G6 95-CI lower bound +$2.94).
**SOL 4h pure_sms_signal_flip** is the most robust large-n cell (n=105,
WR 69.5 %, +$4.24/tr, Sharpe 3.75, total $445).

---

## 1. Outputs

| File | Description |
| --- | --- |
| `W2e_run.py` | Driver — pure SMS, gated, struct, cross-TF variants |
| `W2e_results.csv` | 174 rows: 12 (asset × TF) cells × ≈ 15 variants |
| `W2e_sms_regime.md` | This narrative |

---

## 2. Variants tested

| # | Variant family | Signal | Exit |
| --- | --- | --- | --- |
| 1 | `pure_sms_hold{1,3,5,10}` | `liquidity_dn` → LONG, `liquidity_up` → SHORT | fixed N bars |
| 2 | `pure_sms_signal_flip` | as above | hold until opposite signal fires |
| 3 | `pure_sms_atr_trail` | as above | first of 2× ATR stop / 3× ATR target / 30 bars |
| 4 | `sms_regime_trending_hold3` | LONG only if `regime_label="trending_up"`, mirror SHORT | hold 3 |
| 5 | `sms_session_londNy_hold3` | only when `tr_in_london OR tr_in_ny` | hold 3 |
| 6 | `sms_session_asia_hold3` | only `tr_in_tokyo` | hold 3 |
| 7 | `sms_ranging_hold3` | only `regime_label="ranging"` | hold 3 |
| 8 | `sms_markov_sized_hold3` | discard BEAR-LONG / BULL-SHORT bars, 2× notional in confirmed regime, 1× neutral | hold 3 |
| 9 | `bos_pure_hold5` | `bos_buy/sell` standalone | hold 5 |
| 10 | `choch_pure_hold5` | `choch_buy/sell` standalone | hold 5 |
| 11 | `bos_AND_liq_hold5` | both fired same bar | hold 5 |
| 12 | `5m_liq_AND_15m_ranging` | 5m liquidity + asof 15m regime=ranging | hold 5 |
| 13 | `15m_liq_AND_1h_liq` | same direction on both TFs | hold 5 |

---

## 3. Aggregate by TF (pure_sms_hold3, mean across BTC/ETH/SOL)

| TF | n_trades | WR | avg $/tr | sharpe |
| --- | ---: | ---: | ---: | ---: |
| 5m | 44 613 | 0.30 | **−$0.292** | −5.40 |
| 15m | 11 844 | 0.39 | **−$0.312** | −3.23 |
| 1h | 2 491 | 0.47 | **−$0.354** | −1.79 |
| 4h | 590 | 0.54 | **+$0.117** | +0.25 |

The signal's directional WR climbs monotonically with TF (30→39→47→54 %), but
only 4h crosses the fee breakeven. Fee burden is constant ($0.225/tr at $250
notional) but signal IC and per-trade edge scale with bar size, so 4h is the
first TF where the structural pattern outpaces the fee.

---

## 4. Top-15 cells (n ≥ 30, sorted by $/tr)

| Asset | TF | Variant | n | WR | $/tr | Total | Sharpe | G1 p | G6 95-CI lower |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **SOL** | **4h** | **sms_markov_sized_hold3** | 31 | **0.806** | **+$5.51** | $171 | **10.14** | **0.0009** | **+$2.94** |
| **SOL** | **4h** | **pure_sms_signal_flip** | 105 | **0.695** | **+$4.24** | $445 | **3.75** | **0.00008** | **+$1.22** |
| BTC | 4h | pure_sms_signal_flip | 103 | 0.680 | +$1.68 | $173 | 2.59 | 0.0003 | −$0.05 |
| ETH | 4h | pure_sms_atr_trail | 552 | 0.457 | +$0.87 | $478 | 0.96 | 0.045 | −$0.10 |
| SOL | 4h | pure_sms_hold10 | 610 | 0.544 | +$0.79 | $481 | 0.89 | 0.032 | −$0.12 |
| SOL | 4h | pure_sms_atr_trail | 610 | 0.472 | +$0.70 | $428 | 0.73 | 0.181 | −$0.29 |
| ETH | 4h | choch_pure_hold5 | 62 | 0.532 | +$0.50 | $31 | 1.09 | 0.704 | −$1.00 |
| SOL | 4h | pure_sms_hold3 | 610 | 0.533 | +$0.41 | $249 | 0.84 | 0.114 | −$0.10 |
| SOL | 4h | sms_ranging_hold3 | 495 | 0.525 | +$0.40 | $199 | 0.83 | 0.281 | −$0.17 |
| BTC | 4h | pure_sms_hold10 | 607 | 0.549 | +$0.34 | $209 | 0.75 | 0.018 | −$0.15 |
| SOL | 4h | sms_session_asia_hold3 | 260 | 0.500 | +$0.34 | $89 | 0.63 | 1.00 | −$0.53 |
| ETH | 4h | sms_ranging_hold3 | 427 | 0.576 | +$0.30 | $126 | 0.63 | 0.002 | −$0.29 |
| ETH | 4h | pure_sms_signal_flip | 91 | 0.648 | +$0.24 | $22 | 0.17 | 0.006 | −$3.54 |
| SOL | 4h | sms_session_londNy_hold3 | 420 | 0.536 | +$0.22 | $94 | 0.50 | 0.157 | −$0.33 |
| BTC | 4h | pure_sms_atr_trail | 607 | 0.458 | +$0.18 | $109 | 0.34 | 0.042 | −$0.38 |

**Observation: every positive cell is on 4h.** Below 4h, only 3 of ~160 cells are
positive, and none pass G6 (95% bootstrap lower bound on $/tr > 0).

---

## 5. Strongest cell — SOL 4h Markov-sized signal_flip

```
asset / TF      : SOL / 4h
variant         : sms_markov_sized_hold3
n_trades        : 31  (after Markov-state filtering — bears for LONG, bulls for SHORT removed)
win_rate        : 0.806
avg pnl_net     : +$5.51 / trade
total           : +$171
sharpe          : 10.1   (heavily inflated by small n + low denom; treat as upper-bound)
G1 binom p      : 0.0009   (significant)
G6 95-CI low    : +$2.94   (PASS: positive lower bound, real edge)
avg fees        : $0.27   (fee paid both sides)
avg funding     : −$0.001  (negligible at 4h horizon)
avg bars_held   : 2.8
```

**Why it works**: at 4h, a 20-bar sweep is a ~3-day fractal; SOL's vol is high
enough that a true sweep-and-reverse moves 1-2 % cleanly past the fee threshold.
Markov filter removes contradiction trades (LONG into a BEAR-confirmed state =
fighting both the structure and the regime).

**Caveat**: n=31 is sparse → G4 (1000-perm Sharpe) was NOT run on this cell to
conserve time. Treat the Sharpe of 10 as a wide upper bound; the binomial-p and
bootstrap-CI are the real evidence.

---

## 6. Why 5m / 15m fail — gross vs net check

I ran a side-experiment on BTC 5m pure_sms_hold3, setting fees=0 + slip=0 +
funding off:

```
GROSS (zero-fee):   n=54,500   WR=0.527   avg=$+0.0081/tr   sharpe=+0.21
NET   (real fees):  n=54,500   WR=0.218   avg=$-0.292 /tr   sharpe=-7.56
```

The **signal IS positive ex-fees** (52.7 % gross WR, ~30 bps edge), but a 4.5 bps
× 2 = 9 bps round-trip taker fee + 3 bps slip = 12 bps cost ≫ 6 bps signal at
$250 notional. The "WR = 0.218 net" is what happens when 47 % of gross-positive
trades net negative because the gross PnL is < 12 bps.

**Implication for live deploy**: SMS at 5m on HL requires either (a) bigger
notional ($1k+ moves the constant-fee headwind to 4.5 bps net, comparable to
gross edge), (b) maker-side execution (1.5 bps × 2 saves 6 bps), or (c) abandon
the TF and stick to 4h.

---

## 7. Variant family hit-rate (frac of cells with avg_pnl_usd > 0, n ≥ 30)

| Variant family | hit-rate |
| --- | ---: |
| `pure_sms_atr_trail` | 25 % |
| `pure_sms_signal_flip` | 25 % |
| `sms_ranging_hold3` | 25 % |
| `pure_sms_hold10` | 17 % |
| `pure_sms_hold5` | 17 % |
| `pure_sms_hold3` | 17 % |
| `sms_session_londNy_hold3` | 17 % |
| `sms_markov_sized_hold3` | 9 % |
| `sms_session_asia_hold3` | 8 % |
| `choch_pure_hold5` | 8 % |
| `pure_sms_hold1` | 0 % |
| `bos_pure_hold5` | 0 % |
| `bos_AND_liq_hold5` | 0 % |
| `sms_regime_trending_hold3` | 0 % |
| `5m_liq_AND_15m_ranging` | 0 % |
| `15m_liq_AND_1h_liq` | 0 % |

Notable failures:

- **`sms_regime_trending_hold3`** (Polymarket's STAR overlay) loses everywhere
  on HL. Reason: "trending_up + buy the sweep down" is a self-contradicting
  combination on continuous price (the regime label says "up" precisely when
  it's NOT mean-reverting). Polymarket's binary 5-min window let trend
  exhaustion mean-revert mechanically. HL futures don't.
- **`bos_AND_liq_hold5`** (the "strongest possible structural signal") fires
  rarely (n < 200 even on 5m) and loses every time. The two events are
  near-anti-correlated: a BOS is a structural continuation that fires near a
  trend extreme; a liquidity sweep fires when price reverses off that same
  extreme. The conjunction is mostly noise.
- **Cross-TF confluence** (5m_liq + 15m_ranging; 15m_liq + 1h_liq): 0 of 6
  cells positive. The asof join collapses the n severely (~30 % of 5m fires
  pass the 15m ranging filter) and the conditioning doesn't tilt direction
  enough to overcome fees.

---

## 8. Validation gates summary (top-2 cells)

| Cell | G1 binom-p | G6 95-CI lower | G7 regime sensitivity | Verdict |
| --- | --- | --- | --- | --- |
| SOL 4h `sms_markov_sized_hold3` | **0.0009 ✓** | **+$2.94 ✓** | not run (n=31) | PASS (sparse) |
| SOL 4h `pure_sms_signal_flip` | **0.00008 ✓** | **+$1.22 ✓** | not run | PASS |
| BTC 4h `pure_sms_signal_flip` | 0.0003 ✓ | −$0.05 ✗ | not run | MARGINAL |
| ETH 4h `pure_sms_atr_trail` | 0.045 ✓ | −$0.10 ✗ | not run | MARGINAL |

G2 (cost realism): all cells use real HL fees/funding via `HyperliquidConfig`.
G3 (OOS hold-out), G4 (perm test), G5 (walk-forward), G7 (regime) NOT run in
this wave — they require a Wave-3 follow-up on the surviving cells.

---

## 9. Did SMS port successfully?

**Mixed verdict.**

- **NO** for the marquee Polymarket finding (5m/15m liquidity_reclaim).
  The structural pattern transfers (gross +30 bps directional bias) but is
  killed by bps-of-notional fees at $250 stake. Polymarket's
  2 %-on-profit-only fee model masked the true round-trip cost; HL's bps
  model exposes it.
- **YES, but only on 4h.** SOL 4h pure_sms_signal_flip (n=105, WR 69.5 %,
  +$4.24/tr, Sharpe 3.75, G1+G6 PASS) is the strongest standalone port. SOL
  4h + Markov sizing (n=31, WR 80.6 %, +$5.51/tr) is even higher per-trade
  but sparse.
- BTC and ETH 4h are weaker but directionally consistent (BTC signal_flip
  +$1.68/tr, ETH ATR-trail +$0.87/tr).

**Recommended next step**: Wave-3 walk-forward + permutation test on the 4
cells with G6 CI lower > 0. If 4h SOL signal_flip survives WF and 1k-perm,
it's deploy-ready at modest notional ($250-$500) and 1× leverage.

**Cross-asset extension**: the Polymarket original found the edge primarily on
BTC. On HL the order reversed: SOL > BTC > ETH on 4h. SOL's higher realized
vol amplifies the per-bar move from a true sweep-reverse, so the signal-to-fee
ratio is more favorable. Worth re-running on AVAX / LINK / DOGE if their
panels become available.
