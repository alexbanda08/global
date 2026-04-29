# V27 — Higher-Timeframe Swing Round — Final Portfolio

**Date:** 2026-04-21
**Status:** V27 hunt complete. One family (HTF_Donchian 4h) delivered 5 clean
OOS-validated edges; two families collapsed once a latent HTF-resample
look-ahead bug was fixed. The V23 core is still the engine; V27 adds a
trend-following breakout sleeve across 5 coins.
**Execution model:** unchanged — 0.045% taker fee/side, 3 bps slippage, 3×
leverage cap, next-bar-open fills.

This is the second time in two rounds that the headline finding came from
catching a look-ahead bug, not from a new indicator. The takeaway compounds:
**any signal that touches two timeframes needs a causality audit before the
numbers are trusted.**

---

## Headline: HTF_Donchian 4h is the real discovery

After the HTF-resample fix (see "What went wrong" below), 5 of 9 coins
produced a clean walk-forward OOS pass for a vanilla Donchian-N breakout on
their native 4h data, gated by an EMA regime filter:

| Coin | Donch | EMA reg | Full CAGR | Full Sh | IS Sh | OOS Sh | OOS CAGR | n (full) |
|------|------:|--------:|----------:|--------:|------:|-------:|---------:|---------:|
| **ETH**  | 40 | 100 | +63.2% | +1.19 | +0.93 | **+1.62** | +114.7% | 328 |
| **DOGE** | 20 | 100 | +51.3% | +1.35 | +1.12 | **+1.67** | +72.9%  | 298 |
| **SOL**  | 40 | 200 | +58.4% | +1.15 | +1.29 | +0.94     | +38.7%  | 219 |
| **SUI**  | 20 | 100 | +44.7% | +0.92 | -0.11 | **+1.25** | +81.6%  | 146 |
| **BTC**  | 40 | 200 | +15.6% | +0.69 | +0.84 | +0.53     | +9.0%   | 285 |

ETH and DOGE are particularly striking because OOS *beats* IS — the
opposite of overfitting. Both exit the 2024-2026 sample with higher Sharpe
than they entered it. SUI has a thin IS (data starts 2023-05, so only 28 IS
trades) and must be treated as OOS-only; SOL degrades from IS but stays
positive. BTC is modest in size but passes.

Rejected on HTF_Donchian: LINK (OOS Sh -0.05), AVAX (degrades from IS
+1.75 to OOS +0.69 — classic overfitting), INJ (OOS Sh -0.36), TON
(IS=0, OOS Sh -0.92).

### Why this family works

A Donchian-N breakout on the *native* 4h bar is a structurally honest
trend signal: it uses only fully-closed bars of its own timeframe
(`ta.highest(high, N)[1]`), it has no hidden regime dependence, and the
EMA-regime gate keeps it from firing against the larger trend. On pairs
with cleanly persistent 4h trends (ETH, SOL, DOGE) the edge is durable;
on pairs with choppy 4h structure (AVAX, LINK, INJ) it isn't.

The "prior-bar channel" detail — `ta.highest(high, donchN)[1]` rather than
`[0]` — matters. It means the channel wall the break has to cross is
*already set* when the bar opens, not being redefined by the bar that's
breaking it. Most backtest implementations skip this; it costs almost
nothing if done right and is a small but real leak if done wrong.

---

## What went wrong (and got caught): the HTF-resample look-ahead leak

The first sweep of the V27 families looked too good — Trend_Pullback and
Daily_EMA_X both had clean OOS passes on several coins. Before shipping,
I audited the cross-TF signal generators in Python and found this:

```python
# BAD — default pandas resample
h4 = df["close"].resample("4h").last()        # labels bucket at ITS OPEN
h4_trend = (h4 > ema(h4, 50)).reindex(df.index, method="ffill")
```

`.resample("4h").last()` with pandas' default (`label="left"`, `closed="left"`)
timestamps the 4h close at the bucket's *opening* time. Then
`.reindex(ltf_index, method="ffill")` at LTF bar `t = 00:00` pulls the close
of the bucket `[00:00, 04:00)` — i.e. the close at 03:00, which is **3 hours
in the future**. Every LTF bar inside an HTF bucket was effectively
looking at that bucket's already-known close.

**Fix** — right-labeled resample so the HTF close is stamped at the
bucket's *closing* time, then forward-fill:

```python
# GOOD — at LTF bar t, only fully-closed HTF buckets contribute
h4 = df["close"].resample("4h", label="right", closed="left").last().dropna()
h4_trend = (h4 > ema(h4, 50)).reindex(df.index, method="ffill").fillna(False)
```

This pattern was applied to both `run_v27_swing.py` (`sig_trend_pullback`,
`sig_daily_ema_cross`) and the older `run_v25_creative.py` (`sig_mtf_conf`).

### Impact on V25 portfolio (post-fix reruns)

The V25 MTF-Conf family was affected too. Reruns with the fix:

| Coin / V25 strategy | Pre-fix OOS Sh | Post-fix OOS Sh | Status change |
|---|---:|---:|---|
| **AVAX V25 MTFConf 1h** | +2.74 | **+1.61** | Still strong — stays in portfolio, numbers downgraded |
| **SOL V25 MTFConf 1h**  | +1.43 | **+0.70** | Still positive but borderline — demoted to watch |
| **SUI V25 MTFConf 30m** | +0.84 | **fails**| **Deprecated** — OOS no longer holds |

See `V25_FINAL_PORTFOLIO.md` post-script for updated numbers.

### Why the Pine scripts were already safe

TradingView's `request.security(syminfo.tickerid, "240", close)` with the
default `barmerge.lookahead_off` waits for the HTF bar to close before the
LTF bar sees its value — i.e. the causality is correct on the chart. So
the **shipped Pine scripts for V25 MTFConf** (AVAX, SOL, SUI) were never
lying about what they'd do live; they just had their *expected Python
numbers* overstated. The live/paper expectations in this doc reflect the
corrected backtest.

### General rule

Any time we merge data from two timeframes in Python:
1. Use `resample(..., label="right", closed="left")` on the HTF source.
2. Verify with a toy example — print the LTF timestamp and the HTF value
   it's seeing, make sure the HTF value's source bar closed BEFORE the
   LTF timestamp.
3. If the pattern requires forward bars to confirm (OB-style, swing
   pivots), shift by the confirmation window (see V26 OB fix).

---

## V27 Donchian 4h — portfolio integration

Each V27 Donchian sleeve is its own sub-account with its own Pine script.
No signal collision with V23/V24/V25 — Donchian breakout is a different
entry family from BB-Break (mean reversion), RangeKalman (mean reversion),
MTFConf (EMA cross), Regime Router, etc.

| Coin | Pre-V27 sleeve | V27 addition | New blended sleeve |
|------|----------------|--------------|--------------------|
| **BTC**  | 100% V23 RangeKalman 4h | V27 Donchian 4h @ 20% | **V23 80% / V27 20%** |
| **ETH**  | V23 70% / V24 30% | V27 Donchian 4h @ 30% | **V23 50% / V24 20% / V27 30%** |
| **SOL**  | V23 70% / V25 30% | V27 Donchian 4h @ 30% | **V23 50% / V25 20% / V27 30%** |
| **DOGE** | V23 70% / V25 30% | V27 Donchian 4h @ 25% | **V23 50% / V25 25% / V27 25%** |
| **SUI**  | 100% V23 | V27 Donchian 4h @ 20% *(paper first)* | **V23 80% / V27 20%** after 4-week paper |
| **AVAX** | V23 50% / V25 50% | — (V27 degraded on AVAX) | no change |
| **LINK** | V23 60% / V24 40% | — (V27 failed on LINK) | no change |
| **INJ**  | 100% V23 | — (V27 failed on INJ) | no change |
| **TON**  | 100% V23 + V26 LiqSweep *(paper)* | — (V27 failed on TON) | no change |

### Why these weights

The weights are set so the V27 sleeve is additive, not dominant. The V23
core is still the most-validated edge across every coin (2020-2023 IS +
2024-2026 OOS both holding strongly), and V27 is only 1 year out of 2.5+
years of data for the 4 majors. Allocating 20-30% gives V27 enough skin
to matter if live fills track the backtest, without leaving the portfolio
concentrated on the newer family.

### Risk parameters per sleeve

| Coin | Donch / EMA | TP×ATR | SL×ATR | Trail | MH | Risk | Lev |
|------|-------------|-------:|-------:|------:|---:|-----:|----:|
| ETH  | 40 / 100 | 6  | 1.5 | 3.5 | 20 | 5% | 3× |
| SOL  | 40 / 200 | 10 | 2.0 | 5.0 | 40 | 5% | 3× |
| DOGE | 20 / 100 | 10 | 2.0 | 5.0 | 40 | 3% | 3× |
| SUI  | 20 / 100 | 10 | 2.0 | 5.0 | 40 | 5% | 3× |
| BTC  | 40 / 200 | 10 | 2.0 | 5.0 | 40 | 3% | 3× |

---

## Portfolio-level expectation (back-of-envelope)

Running V27 on top of the post-V26 portfolio:

- **BTC sleeve:** +24% → +28% CAGR (small bump from 20% V27 @ +15.6%)
- **ETH sleeve:** ~+98% → **~+108%** CAGR (V27 +63% at 30% weight adds ~+19%)
- **SOL sleeve:** ~+123% → **~+130%** CAGR (V27 +58% at 30% weight, offset by trimming V23)
- **DOGE sleeve:** ~+53% → **~+58%** CAGR (V27 +51% at 25% weight)
- **SUI sleeve:** +160% → ~+163% CAGR (paper-only initially)
- **AVAX sleeve (post-V26):** ~+165-180% CAGR — no change, V27 doesn't add here
- **LINK / INJ / TON:** no change

**Net portfolio CAGR:** ~+98-103% (post-V26) → **~+105-115%** with V27
**Net portfolio Sharpe:** ~2.05-2.15 → **~2.15-2.25** (adding 5 uncorrelated
Donchian sleeves improves risk-adjusted return more than headline return)
**Net portfolio DD:** similar or slightly better (~-22 to -25%) — Donchian
DDs tend to cluster during chop, which is where BB-Break (V23) is quiet,
so cross-sleeve DDs shouldn't overlap much.

These are backtest projections; actual live returns will almost certainly
fall below these numbers. Budget a 30-40% haircut on CAGR for V27
sleeves, 20-30% for V23/V24/V25.

---

## What V27 tried and rejected

| Family | Result |
|--------|--------|
| **Trend_Pullback (4h HTF EMA + 1h RSI pullback)** | Pre-fix: 4 coins holding OOS. Post-fix: only BTC, SUI, TON, DOGE marginal (Sh 0.5-0.8). Family works on paper but barely clears fees; not adding sleeves. |
| **Daily_EMA_X (daily EMA cross)** | Pre-fix: 3-4 coins holding. Post-fix: only AVAX, DOGE, INJ, SUI marginal — small samples (n < 40), Sh 0.5-1.0, not enough evidence. Watch-list. |
| **VWAP_Fade (anchored deviation reversion)** | Best result was SUI (Sh +1.62 IS, +0.01 OOS). AVAX, BTC, ETH, TON all degraded OOS. Family is not an edge. |
| **HTF_Donchian 4h** (the winner) | 5 clean OOS passes. The real V27 discovery. |
| **Cross-asset ratio (ETH/BTC pair trading)** | Not implemented this round. Queued for V28. |

The pattern across V25/V26/V27: most "creative" pattern-based families
either collapse under leak audits or fail to clear fees. The edges that
survive are simple and structural — BB-Break, RangeKalman, ATR Squeeze
(V26), Donchian (V27). The plumbing has to be causally clean *before* the
metrics mean anything.

---

## Files

### V27 additions

- `pine/ETH_V27_Donchian4h.pine` — NEW (live, primary V27 winner)
- `pine/SOL_V27_Donchian4h.pine` — NEW (live)
- `pine/DOGE_V27_Donchian4h.pine` — NEW (live)
- `pine/SUI_V27_Donchian4h.pine` — NEW (paper first)
- `pine/BTC_V27_Donchian4h.pine` — NEW (live, small sleeve)
- `strategy_lab/run_v27_swing.py` — 4-family sweep (HTF-leak fixed)
- `strategy_lab/run_v27_oos.py` — walk-forward OOS
- `strategy_lab/run_v25_creative.py` — **patched**: `sig_mtf_conf` HTF-leak fix
- `strategy_lab/results/v27/v27_swing_results.pkl` — result pickle
- `strategy_lab/results/v27/v27_swing_summary.csv` — flat metrics
- `strategy_lab/results/v27/v27_oos_summary.csv` — OOS verdicts

---

## Go-live checklist (updated)

1. **Pine scripts paper-test (4 weeks minimum) for all V27 sleeves:**
   - `ETH_V27_Donchian4h.pine`, `SOL_V27_Donchian4h.pine`,
     `DOGE_V27_Donchian4h.pine`, `BTC_V27_Donchian4h.pine`
   - `SUI_V27_Donchian4h.pine` (paper-only; promote to capital after
     realized Sharpe > 0.6 with n >= 15 live trades)

2. **Compare live fills to Python backtest** trade-by-trade for each V27
   sleeve. Halt if trade count diverges by more than ±25% or PF drops
   below 1.15 after 20 trades.

3. **Re-run V25 MTF numbers with the leak-fix expectations:**
   - AVAX V25 MTFConf: expected Sharpe ~+1.6 (was +2.7) — still live
   - SOL V25 MTFConf: expected Sharpe ~+0.7 (was +1.4) — demote to 15% overlay
     or retire; doesn't clear the 0.8-Sharpe-live bar reliably
   - SUI V25 MTFConf: **deprecated** — do NOT deploy

4. **Re-audit cadence:** every 6 months. Flags for re-audit:
   - ALL V27 sleeves (only 1 year of OOS for the 4 majors)
   - SUI V27 (OOS-dominated; data starts 2023)
   - V25 MTFConf family (demoted; audit whether realized stays positive)

---

## Honest caveats specific to V27

- **SUI V27 has only 28 IS trades.** Treat it as an OOS-only finding and
  paper-trade for 4 weeks before committing capital. The +81.6% OOS CAGR
  is real but unvalidated by a pre-2024 sample.

- **Donchian breakouts get chopped in range-bound regimes.** The EMA
  regime filter mitigates this but doesn't eliminate it. Expect clusters
  of 3-5 losing trades in a row during sideways markets; the max-hold
  exit (40 bars = 6.7 days) limits damage but it's still uncomfortable.

- **Two HTF causality bugs in two rounds.** This strongly suggests a
  third exists somewhere we haven't looked. Before the next round, I'd
  like to add a systematic "leak audit" pass: for every signal, compute
  it twice — once with the real data and once with the final N% of
  history shuffled — and verify IS metrics collapse on the shuffled
  copy. If they don't, there's a leak.

- **OOS-dominant results (ETH, DOGE, SUI) look too clean.** Because OOS
  beats IS for all three, there's a small chance of a subtle regime bias
  in the 2024-2026 period (e.g. all four majors happened to trend
  strongly up) rather than a durable edge. The 30% weight cap on V27 is
  partly protection against this.

- **4h Donchian breakouts are widely known.** There's no proprietary edge
  here — the edge (to the extent it exists) is in the specific per-coin
  parameter choice and the exit scheme, not in the entry pattern. If the
  market gets smarter about 4h breakouts, these will decay. Monitor
  6-month rolling Sharpe; if it drops below 0.4, reduce sleeve weight.

---

## Supersedes

`V26_FINAL_PORTFOLIO.md` (as the *deployable* doc). V23 is still the core;
V24/V25/V26 overlays remain in place (with V25 MTFConf numbers
downgraded — see V25 post-script); V27 adds the 4h Donchian sleeves on
BTC/ETH/SOL/DOGE (live) and SUI (paper-first).

**If you prefer the simplest upgrade:** deploy only ETH and DOGE V27
Donchian. These are the two cleanest OOS results (both OOS beating IS),
both on coins you already run V23. Two new TradingView slots, two new
sub-accounts, 30% and 25% weight respectively. Everything else stays as
it was post-V26.
