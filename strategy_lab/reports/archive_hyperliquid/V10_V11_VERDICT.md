# V10 + V11 Exploration — Orderflow & Regime Ensemble Verdict

Date: 2026-04-21.
Scripts: `strategies_v10.py`, `strategies_v11.py`, `v10_hunt.py`, `v11_hunt.py`.
Raw data: `results/v10_hunt.csv`, `results/v11_hunt.csv`.

## What was tried

### V10 — Orderflow alpha
Built four strategies that blend our proven V3B/V4C entries with futures
orderflow signals (only available for BTC/ETH/SOL):

| # | Hypothesis | How | Result (best of 3 coins) |
|---|---|---|---|
| V10A | Funding rate fade (skip long when 3-d funding > +0.015 %) | V3B + funding filter | BTC 18 tr · WR 55.6 % · **PF 0.97 (loses)** |
| V10B | OI slope confirmation (require rising OI on entry) | V4C + OI gate | ETH 5 tr · WR 20 % · PF 0.32 |
| V10C | Top-trader L/S > 1.3 = smart-money long | standalone LS strat | SOL 17 tr · WR 52.9 % · PF 0.69 |
| V10D | Liquidation cascade rebound (buy dips after > 5× spike) | standalone | SOL 2 tr · WR 50 % · PF 0.60 |

**Zero passers.** Every combo either fires too rarely (< 5 trades in 4 years) or
has PF < 1.

### V11 — Regime-switching ensemble
One strategy: classify each 4 h bar into BULL / CHOP / BEAR / OTHER using
price + ADX, then run V4C on bull bars and HWR1 on chop bars; stay flat
otherwise.  Works on all 6 coins (no futures data dependency).

Regime shares across the 6 coins (typical):
- **BULL**  ~35 % of bars
- **CHOP**  ~5 %
- **BEAR**  ~45 %
- **OTHER** ~15 % (transitional)

Per-coin outcome vs baseline:

| Coin | Baseline | V11 Sharpe | V11 CAGR | V11 WR | V11 Final |
|---|---|---:|---:|---:|---:|
| BTC  | V4C 0.95 / CAGR 22 % | 0.27 | +1.0 % | 0 trades | $10,485 |
| ETH  | V3B 1.16 / CAGR 45 % | 0.07 | +0.2 % | 50 % (n=2) | $10,078 |
| SOL  | V4C 0.81 / CAGR 35 % | 0.20 | +0.8 % | 50 % (n=2) | $10,401 |
| LINK | V3B 0.58 / CAGR 18 % | −0.04 | −0.7 % | 62 % (n=13) | $9,681 |
| ADA  | V4C 0.39 / CAGR 8 % | 0.55 | +1.1 % | 0 trades | $10,554 |
| XRP  | HWR1 0.43 / CAGR 6 % | 0.27 | +1.8 % | 100 % (n=1) | $10,893 |

**V11 did NOT beat baseline on any coin.** The regime gate eliminates
too many valid entries.  Baseline V3B/V4C already has an implicit regime
filter (Donchian break + volume + regime EMA for V3B; Kalman-range +
regime for V4C) so stacking a second regime layer is over-filtering.

## The cumulative R&D verdict across all explorations

After V7 (high-WR rule strategies), V8 (SuperTrend/HMA/Vol-Donchian), V9
(multi-TP ladder wraps), V10 (orderflow), and V11 (regime ensemble), the
conclusion is consistent:

> **For rule-based 4 h crypto trend-following on the 6-coin universe,
> the V3B / V4C baseline with simple trailing stops is Pareto-optimal
> for CAGR, and the only genuine win-rate bump is the XRP → HWR1 swap
> (which costs ~40 % of CAGR).  Every other "improvement" we have
> tested either trades CAGR for WR with no frontier movement, or fails
> outright due to over-filtering.**

Things that DIDN'T work (and why):
- Multi-TP ladders — caps the big winners that compensate many small losses
- Novel entries (SuperTrend stack, HMA+ADX, Vol-Donchian) — over-filter; < 13 trades in 4 years
- Funding / OI / L/S / liquidation filters — lagging aggregations; no intrabar info
- Regime-switching ensemble — adds a redundant filter layer

## Where a real edge might still live

None of these are small projects.  Each is a 1-4 week research track.

1. **Supervised ML on orderflow microstructure (1-min bars)**
   — gradient boosting on OI delta, taker-buy %, funding change + price features.
   - Data is ready: `data/binance/futures/metrics/*/5m` + `data/coinapi/liquidations/*/1m`.
   - Target: 4h-ahead price direction probability, calibrate with Platt.

2. **Market-making on Hyperliquid (15 min rebates)**
   — post both sides of the book, earn 0.015 % maker on every fill, manage inventory.
   - Already flagged in our backlog as task 6.
   - Different problem class — not directional, flat expected return/hr.

3. **Cross-sectional momentum across 15-20 coins**
   — rank all coins weekly by 4-week return, long top quintile, short bottom.
   - Binance has clean spot data for 20+ majors; we only use 6.
   - Classical CTA-style factor, may add 3-5 uncorrelated Sharpe to existing.

4. **Event-driven scalping on liquidation cascades (1-min bars)**
   — fade 5 σ liquidation spikes, hold 15-60 min.
   - Requires faster execution than 4 h bars allow.

## Recommendation

1. **Lock in the current portfolio** (6 coins, V3B/V4C/HWR1-on-XRP, 5 % × 5x,
   Hyperliquid maker fees): 1.19 Sharpe · 46 % CAGR · 40 % DD · 1.15 Calmar.
2. **Run live forward-test for 4-6 weeks** on Binance-sourced Hyperliquid-paper
   to validate fill rate and signal alignment.  `live_forward.py` is ready.
3. **Pick ONE of the 4 frontiers above** as the next real R&D bet.  Orderflow
   ML is probably the highest-EV given the data is already in hand.
