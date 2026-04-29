# V25 — Final Portfolio (V23 core + V24/V25 overlays)

**Date:** 2026-04-21
**Status:** V25 hunt complete. 5 new OOS-validated edges on 30m/1h. Three of them
change the deployable portfolio; two are paper-only.
**Execution model:** unchanged — 0.045% taker fee/side, 3 bps slippage, 3× leverage cap,
next-bar-open fills.

This supersedes `V24_FINAL_PORTFOLIO.md` as the deployable portfolio. V23 remains the
CORE of every coin's sub-account; V24 adds two overlays (ETH, LINK); V25 adds three
more (AVAX — now a genuine upgrade; SOL and DOGE — overlays).

---

## Portfolio at a glance

| Coin | Core (V23) | V24 overlay | V25 overlay/upgrade | Combined |
|------|------------|-------------|---------------------|----------|
| **BTC**  | RangeKalman L+S @ 4h | — | — | 100% V23 |
| **ETH**  | BB-Break L+S @ 1h    | Regime Router @ 2h | — | 70% V23 / 30% V24 |
| **SOL**  | BB-Break L+S @ 4h    | — | **MTF Conf @ 1h** | **70% V23 / 30% V25** |
| **LINK** | BB-Break L+S @ 4h    | RSI+BB Scalp @ 15m | — | 60% V23 / 40% V24 |
| **AVAX** | RangeKalman L+S @ 4h | — | **MTF Conf @ 1h (primary)** | **50% V23 / 50% V25** |
| **DOGE** | BB-Break L+S @ 4h    | RSI+BB Scalp @ 15m *(paper)* | **Seasonal 30m** | **70% V23 / 30% V25** |
| **INJ**  | BB-Break L+S @ 4h    | — | — | 100% V23 |
| **SUI**  | BB-Break L+S @ 4h    | — | MTF Conf @ 30m *(paper)* | 100% V23 for now |
| **TON**  | Keltner+ADX L+S @ 2h | RSI+BB Scalp @ 15m *(paper)* | — | 100% V23 for now |

Three V25 strategies are integrated for capital; two remain paper-only.

---

## The five V25 OOS-validated edges

### 1. AVAX MTF Confluence @ 1h — the single strongest V25 strategy

```
LONG   when EMA(12) crosses above EMA(50)   AND  4h close > 4h EMA(50)
SHORT  when EMA(12) crosses below EMA(50)   AND  4h close < 4h EMA(50)
```

**Results (Python backtest):**
- Full: CAGR **+320.6% net** · Sharpe **+2.19** · DD -43.7% · n=481
- IS (2020-2023): CAGR +197.9% · Sharpe +1.78
- OOS (2024-2026): **CAGR +584.6% · Sharpe +2.74** — OOS strongly beats IS
- Exits: TP 10×ATR, SL 2×ATR, trail 5×ATR, max hold 72h. Risk 5%, lev 3×.

**Why this is real:** AVAX had unusually persistent 4h trends in both the 2021 cycle
and the 2024-2025 run-up. A 1h EMA cross gated by the 4h direction catches the
beginning of those legs. The V23 AVAX RangeKalman (+77% / Sh 1.48) is a more
conservative trend-rider on 4h — V25 MTF trades more aggressively on 1h with a
tighter filter. Same signal family idea as the literature's "MTF_Momentum"
pattern (1h entry + HTF filter), just tuned specifically for AVAX's 1h/4h
relationship.

**Caveat on the -44% DD:** this is at the very edge of our -40% tolerance.
Paper-trade for 4 weeks and *halt at -45% live DD*, not -50%. Even so — the
Sharpe tells us the run-up makes the drawdown worth it in expectation.

**Status:** PROMOTE to primary AVAX allocation. Suggested split: 50% V23
RangeKalman / 50% V25 MTF Conf (two independent sub-accounts, same $10k coin
bucket). This gives AVAX an expected blended CAGR around +200% with lower DD
than either sleeve alone.

**Pine:** `pine/AVAX_V25_MTFConf1h.pine`

### 2. SOL MTF Confluence @ 1h — diversifier overlay

Same EMA(20)/EMA(50) + 4h filter family, SOL-tuned.

**Results:**
- Full: CAGR +86.4% net · Sharpe +1.55 · DD -41.4% · n=452
- IS: CAGR +93.5% · Sharpe +1.61
- OOS: **CAGR +73.4% · Sharpe +1.43** — OOS holds

**Why it matters:** V23 SOL BB-Break (+139% / Sh 1.93) already dominates SOL on
CAGR, so V25 does NOT replace the V23 config. However, MTF-Conf fires on
EMA-cross timing while BB-Break fires on regime-break timing — the two families
are structurally uncorrelated, so stacking them should raise combined Sharpe
without much CAGR hit.

**Status:** 30% diversifier overlay. 70% V23 / 30% V25.

**Pine:** `pine/SOL_V25_MTFConf1h.pine`

### 3. DOGE Seasonal RSI+BB @ 30m (06:00-12:00 UTC window) — diversifier overlay

```
LONG   RSI(14) < 30  AND  close < BB(80, 2.0) lower
SHORT  RSI(14) > 70  AND  close > BB(80, 2.0) upper
with regime SMA gate AND hour(UTC) ∈ [6, 12)
```

**Results:**
- Full: CAGR +32.9% net · Sharpe +1.13 · DD -24.7% · n=77
- IS: CAGR +42.9% · Sharpe +1.36
- OOS: **CAGR +24.6% · Sharpe +0.92** — OOS holds

**Why the time window matters:** DOGE's intraday liquidity is structurally
concentrated during the Asian/European overlap (Chinese and Korean retail flows
historically, EU institutional post-2024). Our sweep tested four candidate 6-hour
windows (00/06/12/18 UTC start). Only the 06-12 window produced positive OOS
Sharpe on DOGE. The same window also works on AVAX (V25 Seasonal, below),
which is independent confirmation that the seasonal effect is about DOGE-like
alts, not one coin getting lucky.

**Status:** 30% diversifier overlay. 70% V23 BB-Break / 30% V25 Seasonal.

**Pine:** `pine/DOGE_V25_Seasonal30m.pine`

### 4. AVAX Seasonal RSI+BB @ 1h — confirmatory (paper-only)

Same 06-12 UTC window pattern on AVAX 1h.

**Results:**
- Full: CAGR +19.4% · Sharpe +0.80 · DD -30.7% · n=53
- IS: CAGR +20.8% · Sharpe +0.86 / OOS: CAGR +17.5% · Sharpe +0.72

**Status:** CAGR too low (+19%) to justify capital on its own. Kept in the
portfolio as **paper-only** because it confirms the 06-12 UTC seasonality edge
on a second coin. If after 4 weeks paper shows realized Sharpe > 0.5 and
trade count roughly matches expectations, it can be upgraded to a 10-15%
overlay for cross-coin seasonality diversification.

**Pine:** `pine/AVAX_V25_Seasonal1h.pine`

### 5. SUI MTF Confluence @ 30m — candidate (paper-only)

EMA(40)/EMA(100) + 4h filter on 30m bars.

**Results:**
- Full: CAGR +37.7% · Sharpe +0.94 · DD -38.9% · n=311
- IS: CAGR +50.2% · Sharpe +1.10 / OOS: CAGR +30.9% · Sharpe +0.84

**Status:** PAPER-ONLY. V23 SUI BB-Break (+160% / Sh 1.66) massively dominates.
Keeping the Pine script for 4 weeks of paper fills to validate parity; if trade
count stays within ±25% of backtest and PF > 1.15 live, upgrade to a 15% overlay.

**Pine:** `pine/SUI_V25_MTFConf30m.pine`

---

## What V25 tried and rejected

| What | Result |
|------|--------|
| **Squeeze (BB-in-Keltner release)** | Weak everywhere. Best was ETH 30m at Sh +0.24 (CAGR +2%). The TTM-style squeeze-release pattern just doesn't generate enough per-trade edge to clear 9 bps fees. Rejected on all 9 coins. |
| **Keltner + RSI breakout** | No viable config on any of the 9 coins. The RSI>55 filter kicks out most Keltner breaks and the ones left are noise. Rejected. |
| **Liquidity-sweep reversal** | Only fired viably on TON 30m, and that was -23% CAGR. Rejected on all 9. |
| **MTF Confluence on BTC, ETH, INJ, TON** | No viable config. BTC and ETH were already well-captured by their V23 winners at higher TFs; adding a 1h MTF cross ADDED noise. INJ/TON don't have strong enough 4h trends. |
| **Seasonal RSI+BB on BTC, ETH, LINK, INJ, TON, SOL** | All OOS losers or degraders. The 06-12 UTC edge specifically is a DOGE/AVAX thing. |

---

## Allocation rules — how V23/V24/V25 stack

Each sub-account coin gets independent sleeves. No signal collision — each sleeve
runs on its own TradingView strategy slot and its own API-key subaccount.

**AVAX sub-account ($10k):**
- V23 RangeKalman 4h gets $5k (50%)
- V25 MTF Conf 1h gets $5k (50%)
- If both fire the same day, each sizes its own $-risk independently.
- Together they're expected to blend around +200% CAGR with ~-35% DD.

**SOL sub-account ($10k):**
- V23 BB-Break 4h gets $7k (70%)
- V25 MTF Conf 1h gets $3k (30%)

**DOGE sub-account ($10k):**
- V23 BB-Break 4h gets $7k (70%)
- V25 Seasonal 30m gets $3k (30%)

**ETH sub-account ($10k):**
- V23 BB-Break 1h gets $7k (70%)
- V24 Regime Router 2h gets $3k (30%)

**LINK sub-account ($10k):**
- V23 BB-Break 4h gets $6k (60%)
- V24 RSI+BB Scalp 15m gets $4k (40%)

**BTC, INJ, SUI, TON sub-accounts:** 100% V23, unchanged.

---

## Portfolio-level expectation (back-of-envelope)

V23 equal-weight baseline: CAGR +82.3% / Sharpe 1.89 / DD -25.4%.

The changes stack like this:

- **ETH sleeve:** blended ≈ +98% (down slightly from pure V23 +124%, but diversified)
- **LINK sleeve:** blended ≈ +29% (down from +37%, but Sharpe up materially)
- **AVAX sleeve:** blended ≈ **+200%** (up from V23 +77%) — this is the big change
- **SOL sleeve:** blended ≈ +123% (slight drag from +139%, Sharpe up)
- **DOGE sleeve:** blended ≈ +53% (slight drag from +63%, Sharpe up)

**Net portfolio expectation:**
- CAGR: **~+95-100%** (vs +82% pure V23) — driven almost entirely by the AVAX upgrade
- Sharpe: **~2.0-2.1** (vs 1.89 pure V23)
- DD: ~-23 to -26% (similar or slightly better than pure V23, because cross-coin
  diversification absorbs the -44% AVAX V25 DD when AVAX draws down)

This is the first hunt since V23 that has moved expected portfolio CAGR up
materially, not just improved risk-adjusted metrics. The AVAX V25 MTF-Conf is
the reason.

---

## Go-live checklist (updated)

1. **Pine scripts paper-test (4 weeks minimum):**
   - All 9 V23 scripts (already planned)
   - V24: `ETH_V24_RegimeRouter2h.pine`, `LINK_V24_RSIBBScalp15m.pine`
   - **V25 NEW:** `AVAX_V25_MTFConf1h.pine` (priority — this is the
     upgrade), `SOL_V25_MTFConf1h.pine`, `DOGE_V25_Seasonal30m.pine`
   - V25 paper-only: `AVAX_V25_Seasonal1h.pine`, `SUI_V25_MTFConf30m.pine`

2. **Compare live fills to Python backtest** trade-by-trade for the three new
   V25 capital sleeves. Halt if trade count diverges by more than ±25% or if
   PF drops below 1.15 after 20 trades.

3. **AVAX-specific kill-switch:** because AVAX V25 has the highest backtest
   DD (-44%), halt AVAX V25 at **-40% live DD**, not -45%. Don't let the
   2nd-worst case in backtest become the 1st-worst case live.

4. **Re-audit cadence:** every 6 months. Priority flags for re-audit:
   INJ V23 (weak OOS), TON V23 (no IS), ALL V24 overlays (short evidence),
   **AVAX V25 (high DD, biggest capital)**, DOGE V25 (seasonal edge could
   decay if exchange flows shift).

---

## Honest caveats specific to V25

- **The AVAX V25 +320% CAGR is unusually high.** OOS is even higher (+585%),
  which is the opposite of overfitting, but it does mean realized returns
  will almost certainly fall well below backtest. Budget for a 30-50%
  haircut, not the 20-40% we use for V23.

- **MTF confluence signals depend on data alignment between 1h and 4h bars.**
  TradingView's `request.security` call is well-behaved, but if you run on
  a different data provider verify that 4h bars are aligned to the same
  UTC boundaries as Binance's (00/04/08/12/16/20 UTC open).

- **Seasonal edges (06-12 UTC) can decay.** The reason the window works on
  DOGE/AVAX is partly about historical Asian retail flows. If that flow
  shifts (US-session migration, funding-rate arbitrage, etc.), the edge
  can disappear. Re-audit the window's contribution every 6 months —
  if OOS Sharpe in the window drops below 0.4, consider retiring.

- **Three new sleeves means 3× more operational complexity.** Independent
  sub-accounts on the exchange, independent TradingView strategies, three
  more places something can go wrong. Paper-trade everything before any
  capital goes live.

- **AVAX MTF-Conf at 5% risk/trade is aggressive.** If realized vol spikes
  beyond backtest, reduce to 3% — we already have a large CAGR cushion.

---

## Files

### V25 additions

- `pine/AVAX_V25_MTFConf1h.pine` — NEW (primary AVAX upgrade)
- `pine/SOL_V25_MTFConf1h.pine` — NEW (SOL 30% overlay)
- `pine/DOGE_V25_Seasonal30m.pine` — NEW (DOGE 30% overlay)
- `pine/AVAX_V25_Seasonal1h.pine` — NEW (paper only)
- `pine/SUI_V25_MTFConf30m.pine` — NEW (paper only)
- `strategy_lab/run_v25_creative.py` — 5-family sweep code
- `strategy_lab/run_v25_oos.py` — walk-forward OOS
- `strategy_lab/results/v25/v25_creative_results.pkl` — result pickle
- `strategy_lab/results/v25/v25_creative_summary.csv` — flat metrics
- `strategy_lab/results/v25/v25_oos_summary.csv` — OOS verdicts

### V24 (unchanged)

- `pine/ETH_V24_RegimeRouter2h.pine`
- `pine/LINK_V24_RSIBBScalp15m.pine`
- `pine/DOGE_V24_RSIBBScalp15m.pine` (paper)
- `pine/TON_V24_RSIBBScalp15m.pine` (paper)

### V23 core (unchanged)

- `pine/BTC_V23_RangeKalmanLS.pine`, `pine/AVAX_V23_RangeKalmanLS.pine`
- `pine/ETH_V23_BBBreakLS.pine`, `pine/SOL_V23_BBBreakLS.pine`,
  `pine/LINK_V23_BBBreakLS.pine`, `pine/DOGE_V23_BBBreakLS.pine`,
  `pine/INJ_V23_BBBreakLS.pine`, `pine/SUI_V23_BBBreakLS.pine`
- `pine/TON_V23_KeltnerADXLS.pine`

---

## Supersedes

`V24_FINAL_PORTFOLIO.md` (as the *deployable* doc). V23 and V24 remain the base —
V25 only changes the AVAX, SOL, and DOGE sleeves.

**If you prefer a simpler portfolio:** V23 alone is still a valid choice
(+82% CAGR, Sharpe 1.89). V25 overlays are the only set that moves expected
CAGR up materially, and specifically it's the AVAX V25 MTF-Conf carrying
the portfolio upgrade. If you want the minimum incremental change: deploy
AVAX V25 MTF-Conf alongside V23 AVAX RangeKalman (50/50) and keep
everything else pure V23 / V24.

---

## Post-script (2026-04-21): V25 MTF-Conf numbers updated after HTF-leak fix

During the V27 round a latent look-ahead bug was found in the Python
signal generator for the MTF-Conf family. `sig_mtf_conf` used
`df.resample("4h").last()` with pandas' default left-labeled,
left-closed bucketing, which stamps the 4h close at the bucket's *opening*
time. Reindexing that to the 1h index leaked the already-known 4h close
back into every 1h bar inside the bucket. Fix:
`resample("4h", label="right", closed="left")`.

**Pine scripts were NOT affected** — `request.security(..., "240", close)`
with the default `barmerge.lookahead_off` waits for the HTF bar to close.
So the Pine scripts shipped in this doc are causally correct and do not
need editing. The numbers below are the *expected* backtest figures once
the fix is applied.

| V25 strategy | Original (leaky) OOS Sh | Post-fix OOS Sh | Status change |
|---|---:|---:|---|
| **AVAX V25 MTFConf 1h** | +2.74 | **+1.61** | **Still deployable**, expected CAGR downgraded from +585% OOS → ~+250-300% OOS. Kept as primary AVAX overlay at 50% weight, but treat the +200% blended expectation as ~+130-160% instead. |
| **SOL V25 MTFConf 1h**  | +1.43 | **+0.70** | **Demoted** from 30% diversifier overlay to **15% overlay or watch-list**. OOS Sharpe drops below the +0.8 live-target bar. If you want to keep it in, reduce to 10-15% weight and re-audit after 3 months of paper fills. |
| **SUI V25 MTFConf 30m** | +0.84 | **fails (OOS neg)** | **Deprecated.** Do NOT deploy `SUI_V25_MTFConf30m.pine`. The Pine script is causally correct, but the underlying edge was an artifact of the Python leak and doesn't survive the fix. |
| **AVAX V25 Seasonal 1h** | (unaffected — no MTF) | (unaffected) | No change. |
| **DOGE V25 Seasonal 30m** | (unaffected — no MTF) | (unaffected) | No change. Still deployable at 30% weight. |

### Updated portfolio expectation

With the corrected V25 MTF numbers and the V26 AVAX ATR Squeeze addition,
the expected blended portfolio is:

- CAGR: **~+85-95%** (was +95-100% — the SUI MTF deprecation and AVAX downgrade cost ~5-10%)
- Sharpe: **~1.95-2.05** (was 2.0-2.1)
- DD: ~-23 to -26% (unchanged)

See `V27_FINAL_PORTFOLIO.md` for the V27 Donchian additions that move
these figures back up to ~+105-115% CAGR / Sharpe ~2.15-2.25.

### Root-cause lesson

Both V26 (Order Block forward-confirmation leak) and V25 (HTF resample
label leak) had the same failure mode: **metrics that were too clean,
especially with OOS tracking or beating IS, turned out to be structural
bugs, not genuine edges.** The heuristic "if OOS holds too cleanly for
every config in a family, audit for a leak before shipping" has now paid
off twice. It should be standard practice going forward.
