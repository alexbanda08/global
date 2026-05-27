# Hybrid System research — Range Filter [DW] × Traders Reality Main

_2026-05-25. Research synthesis for adapting the TradingView "Hybrid System"
(Range Filter [DW] by DonovanWall + Traders Reality Main by TR community)
to **binary up-down 5m / 15m crypto prediction markets** on Polymarket. Maps the
indicators' standard rules onto our existing per-fire dataset and prioritises
testable AND-gate rules ranked by expected uplift vs effort._

---

## 1. What is the "Hybrid System"

The **Hybrid System** is a proprietary scalping methodology owned by Tino at
TradersReality.com that blends two schools: (a) **PVSRA** (Price, Volume,
Spread, Relative analysis — institutional volume reading) and (b) the
**Market Maker Method** (timing + repeatable patterns). The official course
["Breaking Down The Hybrid System"](https://tradersreality.com/courses/breaking-down-the-hybrid-system/)
lists its five teachable pillars as: who the Market Makers are, the recurring
patterns, the moving-average stack, the Pivot/M levels, and how to read
Vector Candles. The flagship TradingView indicator that bundles every
visual component for the system is
[**Traders Reality Main**](https://www.tradingview.com/script/Etj1ixAs-Traders-Reality-Main/)
(open-source, Pine v5, 134k uses, 9.5k boosts) — it ships PVSRA candles,
the 5/13/50/200/800 EMA stack with a 50-EMA "cloud", Pivot/M-levels, ADR/AWR
ranges, Psy High/Low and Vector-Candle zones in one script.

The "Hybrid + Range Filter" combo is **not a single published script**. It is
a community pattern: the TR Hybrid gives the **bias/context** (which way
price is trending and where the institutional levels are), and
DonovanWall's
[**Range Filter [DW]**](https://www.tradingview.com/script/lut7sBgG-Range-Filter-DW/)
(Pine v4, 223k uses) gives a **noise-gated trend trigger** (an
extension of QQE's volatility filter applied directly to price). Several
community references confirm this pairing:
[Mr Robot's "EMA Clouds and Options Scalping"](https://mr-robottradez.medium.com/ema-clouds-and-options-scalping-55fd34cf1624)
treats EMA-cloud + range filter as a scalping pair;
[A1TradingHub's "Range Filter Enhanced Accuracy"](https://www.tradingview.com/script/DkRhiizW-Range-Filter-Enhanced-Accuracy/)
explicitly recommends layering the Range Filter on top of a longer-period
EMA "neutral zone"; and [mabonyi's "EBB & Flow"](https://www.tradingview.com/script/XfamjyTi-EBB-Flow-a-multi-EMA-based-BB-cloud/)
"is a scalping strategy built on Traders Reality thinking and is best put
together with the PVSRA indicator." (Quoted directly.) The
[Cryptorum trading-guide thread](https://cryptorum.com/t/trading-guide-using-the-hybrid-system-from-traders-reality.666249/)
+ [Masterclass-68 "Retrace & Continuation" e-book](https://anyflip.com/qcnr/hfpt/basic)
flesh out the pattern naming ("the Tattoo"), and
[Traders Reality Scalping Masterclass Part 5](https://www.scribd.com/document/834134470/Traders-Reality-Masterclass-Part-5-Scalping)
documents the 1m and 5m execution rules.

---

## 2. Range Filter [DW] — exact signal logic (Pine source)

Verified against the
[B&S-Signals Pine source](https://gist.github.com/comdet/948444ec95d7b4c0546c4d16c47273af)
(MPL-2.0, credits DonovanWall) and the updated v4 of the original. The 2020
update **adds an external output `1=bull / -1=bear`** specifically so other
scripts can consume it.

### 2.1 Calculation
```pine
// average abs(change) over n bars, smoothed again over 2n-1
rng_size(x, qty, n) =>
    wper  = (n*2) - 1
    avrng = ema(abs(x - x[1]), n)
    AC    = ema(avrng, wper) * qty      // qty = multiplier (default 3.5)
    AC

// gate price to the range: filter only moves when price exceeds ±r
rng_filt(x, r, n) =>
    var rfilt = array.new_float(2, x)
    array.set(rfilt, 1, array.get(rfilt, 0))
    if x - r > array.get(rfilt, 1)
        array.set(rfilt, 0, x - r)
    if x + r < array.get(rfilt, 1)
        array.set(rfilt, 0, x + r)
    rng_filt1 = array.get(rfilt, 0)
    hi_band   = rng_filt1 + r
    lo_band   = rng_filt1 - r
    [hi_band, lo_band, rng_filt1]
```
Default inputs: `Source = close`, `Swing Period = 20`, `Swing Multiplier = 3.5`.

### 2.2 Direction state
```pine
var fdir = 0.0
fdir    := filt > filt[1] ? 1 : filt < filt[1] ? -1 : fdir
upward   = fdir==1 ? 1 : 0
downward = fdir==-1 ? 1 : 0
```
`fdir` is the **trend-output variable that the updated script exposes
externally**. It is sticky (carries the last non-zero direction across
unchanged bars).

### 2.3 Buy / Sell rule (community B&S version, also the AmiBroker port)
```pine
longCond  = (rng_src > filt and rng_src > rng_src[1] and upward   > 0) or
            (rng_src > filt and rng_src < rng_src[1] and upward   > 0)
shortCond = (rng_src < filt and rng_src < rng_src[1] and downward > 0) or
            (rng_src < filt and rng_src > rng_src[1] and downward > 0)
```
So in plain English, **BUY** requires:
- `close > filt` (price above the gated trend line), AND
- `fdir == +1` (filter ticking up)

**SELL** is the mirror image. The `rng_src vs rng_src[1]` clause is a no-op
inside the OR — either branch suffices once `fdir == +1`. **Net rule**:
`buy ⇔ close > filt AND fdir == +1`. Most published B&S-style versions also
add a "first-fire only" filter (`CondIni`) so the signal only prints on the
bar where `fdir` flipped, not on every subsequent bar.

### 2.4 Common stacked filters in B&S-Signals strategy
The shipped strategy adds two extra gates (configurable on/off):
- **EMA filter**: `close > ema(close, 50) AND close > ema(close, 200)` for longs.
- **Regression-trendline filter** (off by default).

### 2.5 What this maps to in our per-fire dataset
We do NOT have `filt` / `fdir` computed today, but they are derivable in
< 30s from `klines_1s/binance_1s_28d.parquet`. Reasonable proxy lookups
against features we already have:

| RF concept | Cheap proxy on our data |
|---|---|
| `fdir == +1` | `ribbon_lead_slope_bps > 0` (ema_5 5-second slope) OR `ribbon_color in {1,4}` (lime, green) |
| `fdir == −1` | `ribbon_lead_slope_bps < 0` OR `ribbon_color in {2,3}` (maroon, red) |
| `close > filt` (above gated trend) | `dev_bps_vwap > 0` (slot-anchored VWAP deviation) |
| `close > filt` magnitude | `bb_pos_60s > 0.5` (price above mid of 60s Bollinger) |
| RF flip (CondIni) | `ribbon_color_change` since slot_start (need to compute) |

Implementing the real `rng_filt` on top of 1s binance closes is recommended
for a fair test — it's a 20-line numpy port and lets us A/B against the
proxies. See §7.

---

## 3. Traders Reality Main — what it exposes

The script publishes plots, not signals. Below is the inventory and the
**implicit reading rules** the community uses for each.

### 3.1 PVSRA Vector Candles (six-state color)
Default thresholds, per the indicator help text:
- **Climax bull (lime/green)**: `volume ≥ 200% × avg(volume, 10 prior)` AND `(spread × volume) ≥ max(spread × volume, 10 prior)`.
- **Climax bear (red)**: same condition, candle closes down.
- **Rising bull (blue)**: `volume ≥ 150% × avg(volume, 10 prior)`, bull body.
- **Rising bear (violet/fuchsia)**: same, bear body.
- **Normal bull (white)** / **Normal bear (gray)**: everything else.

Plus a hidden 7th state: **Absorption** — climax volume but spread < ½ avg
spread (often reversal). Not in the canonical color palette but the TR
literature flags it heavily.

### 3.2 EMA stack 5 / 13 / 50 / 200 / 800
The 50-EMA is rendered as a **"cloud" = Bollinger band built on the
50-EMA** (per the cryptorum guide). Standard reading:
- **Stack agree bull**: `ema_5 > ema_13 > ema_50 > ema_200 > ema_800`.
- **Stack agree bear**: inverse.
- **Above cloud**: `close > upper(50EMA cloud)`.
- **Below cloud**: `close < lower(50EMA cloud)`.
- **Inside cloud (chop)**: `lower < close < upper` — usually a NO-trade zone.

### 3.3 Pivot points & M-Levels
Standard floor-trader pivot formula:
- `PP = (H + L + C) / 3` of prior day
- `R1 = 2·PP − L`, `S1 = 2·PP − H`
- `R2 = PP + (H − L)`, `S2 = PP − (H − L)`
- `R3 = H + 2·(PP − L)`, `S3 = L − 2·(H − PP)`

**M-Levels** are midpoints (Hybrid prefers these over raw S/R per the
cryptorum guide):
- `M0 = (S2+S3)/2`, `M1 = (S1+S2)/2`, `M2 = (PP+S1)/2`
- `M3 = (PP+R1)/2`, `M4 = (R1+R2)/2`, `M5 = (R2+R3)/2`

### 3.4 ADR / AWR / AMR
Average True Range over Daily / Weekly / Monthly windows. Used as
"distance-already-travelled" filter: don't fade-trade if price is < 50% of
ADR, don't trend-trade if > 100% of ADR (exhaustion).

### 3.5 Psy High / Low
Configurable per asset class. For **crypto**: weekly midpoint between
yesterday's high and last week's low (rendered as horizontal lines).

### 3.6 Market boxes (sessions)
Configurable rectangles for Tokyo / Hong Kong / Frankfurt / London / NY +
"Brinks Boxes" (15-min pre-session). The Hybrid System trades **Frankfurt
+ London opens** (06:00-10:00 UTC) per the Scalping Masterclass.

### 3.7 Standard "Hybrid checklist" entry (paraphrased from the masterclass)
Per the Scribd
[Scalping Masterclass Part 5](https://www.scribd.com/document/834134470/Traders-Reality-Masterclass-Part-5-Scalping)
+ Masterclass 68:

1. **Direction filter** — `close > 50-EMA` for longs (or `< 50-EMA` for shorts).
2. **Vector candle** — a green (or blue) PVSRA candle prints **through the
   50-EMA cloud**.
3. **Retrace** — price pulls back into / onto the 50-EMA cloud and **holds**
   (no candle closes below the cloud for longs).
4. **Confirmation candle** — next bar closes back in the direction of the
   vector (the "Tattoo" pattern).
5. **Confluence** — at least one of {pivot, M-level, Psy high/low,
   prior-day high/low, ADR mid} sits near the entry.
6. **Session filter** — Frankfurt or London open is active.
7. **Volume confirmation** — rising volume on the retrace (else "fake move").
8. **Exit** — when price extends sharply away from 50-EMA and snaps back
   inside the 50-EMA cloud's bands.

---

## 4. Combined "Hybrid + Range Filter" rule (community-implicit)

There is no canonical Pine script that fuses both, so the rule is
synthesised from the components. A **literal direct port** is:

> **LONG entry** ⇔
> (a) Range Filter direction `fdir == +1` AND `close > filt`
>      *(noise-gated trend confirmation)*
> AND (b) PVSRA candle color ∈ {lime, blue} on the trigger bar
>      *(institutional volume present)*
> AND (c) `close > 50-EMA cloud upper` *(TR bias filter)*
> AND (d) EMA stack `ema_5 > ema_13 > ema_50` *(short-stack agree)*
> AND (e) Active session in {Frankfurt, London, NY-AM}
> AND (f) `close` not within 25% of `adr_high` *(room to run)*
> AND (g) `close` near pivot/M-level/Psy level support (optional confluence)
>
> Exit: opposite RF flip (fdir → −1) OR close inside 50-EMA cloud OR
> ADR exhaustion.

The corresponding SHORT is the mirror. In practice most community examples
**collapse to {a, b, c}** for actual entries and use {d-g} as priors.

---

## 5. Adapting to our binary up-down crypto markets

In our setting we don't manage exits — we just bet UP or DOWN at a fixed
fire_offset_s into the slot and the market resolves at slot_end. So a
"trade" is the binary direction selection at a moment in time. We have
~28d of fire-level parquets joining each (slug, offset) to ribbon, slot
VWAP, Markov regime, F7 RSI, BB, MFI, CCI, slow stoch.

**What's already present in `s15_with_ta_and_markov.parquet` (33,323 S1.5
fires) and `v15m_with_ta_and_markov.parquet` (12,492 S7 15m fires)**:
- `ribbon_color` (0-4 per Pine logic) — direct PVSRA-color analogue
- `ribbon_lead_slope_bps` — direct RF-fdir analogue
- `ribbon_lead_vs_ref_bps` — analogue of "above EMA cloud"
- `ribbon_alignment_pct` — analogue of "EMA stack agree"
- `ribbon_compression_bps` — analogue of "compressed ribbon"
- `stoch_k/d_60s`, `stoch_k/d_300s` — for KD-cross
- `bb_pos_60s`, `bb_width_60s` — analogue of "50-EMA cloud position"
- `mfi_60s`, `mfi_300s` — Money Flow / volume
- `cci_60s`
- `dev_bps_vwap` — slot-anchored VWAP deviation
- `markov_m1v` regime label

**What's missing and needs computing once**:
- Actual `filt` and `fdir` from the Range Filter algorithm (run on 1s
  binance closes, ema(20)/ema(39)/qty=3.5). 30-line numpy port.
- Pivot / M-Level / Psy levels (daily aggregates → straightforward).
- ADR / AWR / AMR (rolling window). Trivial.
- True PVSRA color from binance volume per chart-tf (we currently have
  Madrid ribbon color which is volume-blind). Adds the volume-tier info.

### 5.1 Twelve testable AND-gate rules

Notation: `bet_dir` ∈ {UP, DOWN}. Direction-agreement means the gate matches
`bet_dir` (e.g. `ribbon_color ∈ {lime, green}` agrees with UP).

| ID | Rule (binary AND) | What it tests | Maps to |
|---|---|---|---|
| **V1** | `RF_fdir == bet_dir` AND `close > filt` (UP) / `close < filt` (DOWN) | **Pure RF trigger** — bet only on flip-day, requires noise gate | Pillar (a) |
| **V2** | V1 AND `ribbon_color ∈ {lime,blue}` (UP) / `{red,violet}` (DOWN) | RF + PVSRA color agree | (a)+(b) |
| **V3** | V1 AND `bb_pos_60s > 0.5` (UP) / `< 0.5` (DOWN) | RF + "above 50-EMA cloud" proxy | (a)+(c) |
| **V4** | V1 AND `ribbon_alignment_pct ≥ 80` AND color agrees | RF + stack-aligned EMAs | (a)+(d) |
| **V5** | V2 AND active session ∈ {Frankfurt 06-09, London 08-12, NY 13-17 UTC} | Add session filter | (a)+(b)+(e) |
| **V6** | V2 AND `close` within 0.25·ADR of `pivot/M-level` (need compute) | Add confluence | (a)+(b)+(g) |
| **V7** | V2 AND `mfi_60s` agrees with direction (UP: mfi>50, DOWN: mfi<50) | Add volume confirmation | (a)+(b)+vol |
| **V8** | V2 AND **NOT** at ADR exhaustion (`dev_from_daily_open < 0.8·ADR`) | Avoid exhaustion | (a)+(b)+(f) |
| **V9** | V2 AND `markov_m1v_va` agrees (existing M1V gate) | RF+PVSRA+regime | replaces (g) |
| **V10** | RF flip in the **last 3 bars before fire** AND `dev_bps_vwap` agrees | "Fresh RF trigger" — only act if it just flipped | RF freshness |
| **V11** | `ribbon_color == lime` AND `ribbon_compression_bps < 2` AND `bb_width_60s` expanding AND `bet=UP` (mirror for DOWN) | Tight-ribbon **breakout** in PVSRA direction (this is the documented "Tattoo retrace + breakout" without the retrace step) | (b)+(d)+breakout |
| **V12** | V2 AND `f7_rsi` not in {<25, >75} (avoid existing F7 reverse zones) | Combine with existing F7 gate | stack with proven gate |

All twelve are computable as one-line pandas boolean masks against the
existing per-fire parquets (V1, V10 need the new `filt`/`fdir` column; V6
needs pivot derivation; everything else is already there).

---

## 6. What NOT to test (already proven redundant / negative)

Per `MA_RIBBON_OVERLAY_2026_05_23.md`, `MA_RIBBON_STRATEGY_5M_2026_05_23.md`,
`SLOW_STOCH_OVERLAY_2026_05_23.md`, `TA_INDICATORS_MEGA_RUN_2026_05_23.md`:

1. **`ribbon_color` standalone as direction picker** — Rule R1 in the
   standalone ribbon backtest hit 73.4% WR but lost $13,414 (avg pnl
   −$0.27). Adverse entry vwap killed it. → **Don't test V1-style "color
   alone" without RF or VWAP cofilter.**

2. **`ribbon_color + RF_fdir` is likely 80%+ overlapping.** `RF_fdir` is
   computed from the gated price-trend; `ribbon_color` from the 5s slope of
   ema_5. Both will flag the same bars during a clean trend. Worth confirming
   the overlap before stacking — if > 80%, V2 ≈ V1 and the test adds nothing.

3. **`ribbon_lead_vs_ref + slope` (R2) ≈ S1.5 (slot-anchored VWAP).** R2's
   82% slug-overlap with S1.5 means a "RF + ribbon stack" sleeve probably
   just rediscovers S1.5. **Test against S1.5 as a baseline, not against
   pure momo.**

4. **Compressed ribbon (R4) standalone** — 54% WR, sum −$200,206. Don't
   bet that "tight ribbon → break in the direction of the ribbon color"
   alone. V11 must include the breakout confirmation (BB width expanding)
   to differentiate from R4.

5. **PVSRA exhaustion fade** (H1 in slow-stoch report) — our fires KEEP
   winning at overbought. **Do NOT add a fade-on-climax-vector rule.**

6. **Oversold bounce** — consistently loses. Don't add an
   "RSI<30 + RF buy" V13 candidate.

7. **`ribbon_agrees` is *already* deployed as a universal $/tr filter on
   S1.5 + S6** (per TA mega-run §10). Re-testing V2/V3 in isolation will
   just rediscover what we already shipped. **The new question is: does
   adding the *RF gate* on top of `ribbon_agrees` add edge, or is RF
   redundant with ribbon?**

8. **Standalone `bb_pos_60s_extreme_agrees`** — already a winning gate
   per Agent D's combinatorial; appears in 14.6% of S6 winners. V3 alone
   is a known win — the new question is whether RF+BB beats BB alone.

---

## 7. Recommended search budget — top 20 to backtest first

Ranked by **(expected uplift) / (engineering effort)**. Effort 1-3, expect
uplift in $ / 28d at $25 notional (calibrated against typical S1.5 sleeve
of $700-1,500).

| # | Rule | Effort | Expected uplift | Why |
|--:|---|--:|--:|---|
| 1 | **Compute `filt`, `fdir` from 1s binance** (one-time numpy port; per-asset; output: 3M rows, 50MB parquet) | 1 | infra | Unblocks rules V1, V10, and all RF stacks. Run on `binance_1s_28d.parquet`. |
| 2 | **V1 alone vs S1.5 baseline** | 1 | uplift uncertain — test for **independence** first. If WR > 81% on RF-fire-only subset, RF carries info. | Decide whether RF is a real signal or a relabel of ribbon. |
| 3 | **Overlap check: |RF_fdir agree ∩ ribbon_color agree| / |either|** | 1 | analytical | Drives every downstream stack. If overlap > 90%, RF is redundant with ribbon. |
| 4 | **V2: RF + PVSRA-color agree** on S1.5 5m-BTC top sleeves (210s, 240s) | 1 | +$200-500/28d if RF independent of ribbon | Cheapest 2-gate stack to test. |
| 5 | **V10: "fresh" RF flip in last 3 bars** | 1 | +$500-1,500/28d (highest hope) | RF "stalest" signals are the noisiest. Freshness = entry-only-on-flip should be the cleanest. Test on top 10 S1.5 cells. |
| 6 | **V9: V2 + Markov M1V** on cells where M1V not already stacked | 1 | +$300/28d, +WR | M1V is already known to push WR to 95%. Adding it to RF-filtered fires likely tightens WR similarly. |
| 7 | **V11: ribbon compression < 2bps AND BB-width expanding AND PVSRA color agree** on S6 fires | 2 | possibly large — S6 already has +$17k from tight-ribbon+ribbon-agree. Adding the BB expansion gate may filter to better-quality breakouts. | Refines existing S6 best gate. |
| 8 | **Compute pivot / M-levels / Psy high-low** per UTC day from binance daily OHLC | 2 | infra | Unblocks V6 + future TR-level work. |
| 9 | **V6: V2 + within 0.25·ADR of pivot or M-level** | 1 (after #8) | +$400-1,000/28d if confluence matters | Most distinctive Hybrid claim — test it. |
| 10 | **V5: V2 + Frankfurt/London/NY-AM session** | 1 | +$200-500/28d | TR claims sessions matter. We've never gated on session — quick test. |
| 11 | **V7: V2 + MFI agree (60s)** | 1 | +$100-300/28d | MFI overlaps with `taker_buy_base` we already pull. Cheap stack. |
| 12 | **V8: V2 NOT at ADR exhaustion** (compute ADR first) | 2 | +$200/28d if exhaustion bites | TR says skip > 100% ADR. Plausible filter on long slugs. |
| 13 | **V4: V1 + ribbon_alignment_pct ≥ 80** | 1 | +0-300/28d | Already known: 95-100% alignment + ribbon_agrees gives WR 84.7% on n=9,997. Adding RF: marginal. |
| 14 | **V3: V1 + bb_pos_60s favoured direction** | 1 | +0-200/28d | Likely redundant — bb_pos is already in our 14-gate combinatorial. |
| 15 | **V12: V2 AND F7 RSI in (25, 75)** | 1 | +$100/28d | Avoids overlap with already-shipped F7-contra fade. |
| 16 | **Sweep RF `Swing Multiplier` qty ∈ {1.5, 2.5, 3.5, 5.0}** on V1 | 1 | tune | Default 3.5 may not be optimal for 1s binance — sweep cheaply. |
| 17 | **Sweep RF `Swing Period` n ∈ {10, 20, 50, 100}** on V1 | 1 | tune | Same — 20-period EMA of abs(change) may be too short for 1s data. |
| 18 | **Test V1 on 15m slot fires (S7) at offsets 480-840s** | 1 | +$500-1,500/28d if RF lines up with late-fire S7 winners | S7 late-fire is the highest WR 15m bucket. |
| 19 | **PVSRA vector-only fires** (no RF gate) — bet UP if a climax-bull PVSRA candle prints in (slot_start, fire) | 2 | +$300-800/28d | Tests whether PVSRA volume signal carries independent of slope. Need true PVSRA color from 1s binance volume + spread × volume. |
| 20 | **V2 + ribbon_compression < 2bps** on S1.5 | 1 | +$200/28d | Already known S6 wins on this combo; check whether S1.5 also benefits. |

### 7.1 Suggested execution order
1. Tasks **#1, #3** in parallel. Block all other RF work until #3 result is known.
2. If overlap < 80%: do #2, #5 in parallel.
3. Tasks **#4, #6, #11** in parallel after #5 reads RF-independence.
4. Tasks **#8** → **#9, #12** (need pivots first).
5. Tasks **#10, #19** in parallel.
6. Tasks **#16, #17** as a 2-d sweep on V1 once V1 baseline is known.
7. Tasks **#7, #13, #14, #15, #18, #20** as cheap fillers / final polish.

### 7.2 Acceptance criteria
A rule "wins" if, on a held-out 5-day OOS split (May 21-25 of our 28d
window), it meets ALL:
- `n_fires ≥ 30`
- `WR ≥ 70%` (5m) or `WR ≥ 75%` (15m)
- `$/tr ≥ +$1.00` after `engine_v2.LegacyConfig` 2%-on-profit fee
- `sum_pnl_28d ≥ +$200`
- `max_DD ≤ −$200`
- non-overlapping with already-shipped sleeves: < 60% slug-overlap with
  best S1.5 / S6 / S7 sleeve

---

## 8. Open caveats

- **The Range Filter [DW] algorithm has had three versions** (2018 Pine v3
  original, 2020 v4 rewrite, 2020-10 v5 array rewrite). The B&S-Signals
  variant we lifted source from uses the v3 formula (`ema(ema(abs(diff),
  n), 2n-1) × qty`). The canonical updated v5 lets the user pick scale
  (Pips/Ticks/ATR/Standard Deviation/Absolute/Average Change). For our
  numpy port, replicate the v3/v4 "Average Change" formula (default,
  matches B&S-Signals and most community uses).

- **The 50-EMA cloud width is undocumented.** Indicator-settings guide
  doesn't specify. Inspect the open-source Pine to extract `cloud_mult`
  (likely 1.0 or 1.5 std-dev around the 50-EMA on the chart tf). Important
  for V3.

- **PVSRA colour from our 1s data may not match TR's chart-tf colour.**
  TR computes PVSRA on whatever timeframe the chart is set to (1m / 5m /
  15m typically). To map cleanly to our 5m markets, we should compute
  PVSRA on a **5-minute** resample of the 1s data, not on the 1s bars
  themselves. (Our existing `ribbon_color` is on 1s — fine for ribbon, but
  PVSRA classification is timeframe-dependent by design.)

- **Hybrid mid-trade exit doesn't apply to us.** TR's "close when price
  snaps back inside the 50-EMA cloud bands" doesn't translate — we hold
  to slot_end. Our binary nature means we trade the rule's *direction
  conviction*, not its *trade-management*. Worth keeping in mind for
  sleeve sizing.

- **All of the above is one-shot retrospective on 28d.** Re-run on the
  forthcoming 7-day forward slice once data refreshes.

---

## 9. Sources cited

- [Range Filter [DW] on TradingView (DonovanWall)](https://www.tradingview.com/script/lut7sBgG-Range-Filter-DW/)
- [Range Filter B&S-Signals Pine source (comdet gist, MPL-2.0)](https://gist.github.com/comdet/948444ec95d7b4c0546c4d16c47273af)
- [Range Filter AmiBroker port (Marketcalls / Rajandran R)](https://www.marketcalls.in/amibroker/range-filter-trading-strategy-amibroker-better-trend-following-indicator.html)
- [Traders Reality Main on TradingView (open-source)](https://www.tradingview.com/script/Etj1ixAs-Traders-Reality-Main/)
- [Traders Reality PVSRA Volume Suite on TradingView](https://www.tradingview.com/script/UcbR9FIH-Traders-Reality-PVSRA-Volume-Suite/)
- [Traders Reality "Breaking Down The Hybrid System" course (gated, Bronze)](https://tradersreality.com/courses/breaking-down-the-hybrid-system/)
- [Traders Reality "The Trigger Candle" (free blog post)](https://tradersreality.com/the-trigger-candle/)
- [Traders Reality Scalping Masterclass Part 5 (Scribd PDF)](https://www.scribd.com/document/834134470/Traders-Reality-Masterclass-Part-5-Scalping)
- [Traders Reality Indicator Settings Guide (Scribd PDF)](https://www.scribd.com/document/727272438/TradersReality-Indicator-Settings-Guide)
- [Traders Reality Guidebook V5 (Scribd PDF)](https://www.scribd.com/document/727272440/Traders-Reality-Guidebook-Skippers-undertanding-V5)
- [Cryptorum Hybrid System trading guide (community)](https://cryptorum.com/t/trading-guide-using-the-hybrid-system-from-traders-reality.666249/)
- [Masterclass 68 "Retrace & Continuation" e-book](https://anyflip.com/qcnr/hfpt/basic)
- [mabonyi "EBB & Flow" multi-EMA-BB cloud (built on TR thinking)](https://www.tradingview.com/script/XfamjyTi-EBB-Flow-a-multi-EMA-based-BB-cloud/)
- [A1TradingHub "Range Filter Enhanced Accuracy"](https://www.tradingview.com/script/DkRhiizW-Range-Filter-Enhanced-Accuracy/)
- [Mr Robot "EMA Clouds and Options Scalping" (Medium)](https://mr-robottradez.medium.com/ema-clouds-and-options-scalping-55fd34cf1624)
- [PHVNTOM_TRADER "Range Filter Buy and Sell 5min — guikroth version"](https://www.tradingview.com/script/J8GzFGfD-Range-Filter-Buy-and-Sell-5min-guikroth-version/)
- [CryptoZoso "SuperTrend AI + PVSRA Full Dashboard" (entry rules cited)](https://www.tradingview.com/script/pV0BDqlp/)
- Internal repo: `strategy_lab/reports/{HANDOFF_2026_05_23_COMPLETE,MA_RIBBON_OVERLAY_2026_05_23,MA_RIBBON_STRATEGY_5M_2026_05_23,NEW_INDICATOR_SLEEVES_15M_2026_05_23,TA_INDICATORS_MEGA_RUN_2026_05_23}.md`
- Internal data: `data/v4/canonical/_results/{s15_with_ta_and_markov,v15m_with_ta_and_markov,s6_with_ta,ta_indicators_1s}.parquet`

## End
