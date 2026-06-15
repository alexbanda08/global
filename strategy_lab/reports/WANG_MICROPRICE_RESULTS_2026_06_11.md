# Wang-Transform + Stoikov Microprice on our markets — 2026-06-11

Two lenses from the awesome-systematic-trading review, run same-day. Scripts:
`directional/wang_transform_2026_06_11.py` (+ `_results/wang_transform_2026_06_11.txt`),
`directional/microprice_scalp_2026_06_11.py` (+ `_results/microprice_scalp_2026_06_11.parquet`).

## 1. Wang Transform — calibration of Poly binary prices (FRESH production window, n=52M trades)
Data: ALL poly trades BTC/ETH/SOL Apr22→Jun11 × chainlink outcomes (not the burned BBO window).
Probit fit `won ~ Φ(a + b·Φ⁻¹(price))`; perfect calibration = a=0,b=1.

| segment | a (≈λ) | b | n |
|---|---|---|---|
| ALL | +0.013 | 1.047 | 51.9M |
| BTC / ETH / SOL | +0.014 / +0.021 / +0.025 | 1.07 / 1.00 / 0.96 | |
| early t<1/3 | **+0.007** | 1.029 | 18.2M |
| mid | +0.009 | 1.047 | 16.2M |
| **late t>2/3** | **+0.033** | 1.044 | 17.5M |

**Findings:**
1. **These markets are extraordinarily well calibrated** — max |bin mispricing| ≈ 1.5¢ across the whole price
   range at n=52M. **Definitively kills any static "buy the underpriced price-bin" strategy** (the
   favorite-longshot residual b≈1.05 is real but ≈1¢ — under fees/spread). This is the strongest efficiency
   measurement the project has produced.
2. ⭐ **The risk premium is 5× larger LATE in the window** (a: +0.007 early → +0.033 late): prices in the last
   third systematically sit ~1–3¢ BELOW fair value. **Independent, large-n corroboration of the late-slot
   oracle-snipe thread (E2)** — late cheap winners are structurally underpriced, and the V2 fee is ≈0 there.
   This upgrades E2's prior.
3. Gate-test honesty: the per-fire "Wang residual" is a monotone function of entry price, so its tercile result
   (low-ask tercile +2.91 t=5.7 vs high-ask +0.64 ns within the <0.55 band) is really **"cheaper entries are
   better within the band"** — a knob hint (entry<≈0.45?) on the burned window, NOT an independent signal. Park.

## 2. Stoikov Microprice — book-pressure tilt at fire time (corrected harness, Mar30–Apr21, n=677 CLEAN)
`micro = (ask_sz·bid + bid_sz·ask)/(bid_sz+ask_sz)` on the lead token at +5s; tilt = (micro−mid)/spread.
ALIGNED = book pressure already points the binance way.

| bucket | $/tr (t) |
|---|---|
| OPPOSED tercile | +1.03 (1.65, CI spans 0) |
| NEUTRAL | **+2.44 (4.87)** |
| ALIGNED | +2.08 (3.71) |

- Time-split: ALIGNED holds both halves (CI>0); OPPOSED weak both halves.
- Per-coin: **inconsistent** — ETH/SOL favor aligned/neutral, BTC inverts (OPPOSED +2.73 best).
- The naive hypothesis (opposed book = more reprice left) is WRONG — microprice acts as a *confirmation*
  signal (book agreeing with binance ⇒ move continues; disagreeing ⇒ blip more often reverts).
**Verdict: real shape, not deployable** — coin-inconsistent + burned window + dropping OPPOSED only lifts
pooled $/tr ~+0.3–0.5 for −33% volume. Same fate as every regime lens: nothing beats `delta_bps` robustly.
One valuable negative: the edge is NOT concentrated in opposed/toxic books — no adverse-selection smell.

## Net actions
- **E2 (late-slot oracle snipe) gets a priority upgrade** — the Wang late-window premium (+0.033) is exactly
  the structural mispricing that trade harvests. Backtest it next.
- Microprice: parked (monitor file kept). Wang λ: bank as the project's efficiency benchmark; re-fit
  occasionally as a market-health dashboard metric (λ drifting up = more harvestable premium).
- No change to the deployed scalp.
