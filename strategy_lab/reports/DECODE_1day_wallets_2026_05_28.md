# Decode Report: 1-Day-Span Wallets — 2026-05-28

## ⚠️ RELIABILITY CAVEAT (READ FIRST)

**Both wallets have ~1 day of trade history cached.** Every finding below rests on a single hot-streak window:
- `0x8ef6a1cc`: 40 fires, May 19–20 (~1 day)
- `0xf6d2f340`: 68 fires, May 26–27 (~1 day)

The statistical tests show p < 0.001 because the WIN RATE is extreme (80–93% in core tiers) — but a single good day on binary markets can produce exactly this. **Do NOT treat either wallet as validated. Re-pull multi-week chain history before trusting any signal here.** All findings are working hypotheses.

---

## Wallet 1: `0x8ef6a1cc` — BTC 5m

### Summary
- **40 fires, WR 80.0%, mean entry 0.625, span May 19–20**
- **Fires fast**: 85% within 60 seconds of slot start (mean offset 43s, median 20s)
- **Reference pattern: `0x0de4458d` (cl_basis_bps contrarian)**

### (a) Direction Picker

**Primary signal: `cl_basis_bps` (Cohen's d = −2.038 — very large)**

`cl_basis_bps` = `(binance_px − chainlink_px) / chainlink_px × 10000` bps, measuring the live divergence between Binance spot and Chainlink RTDS price feeds.

**Rule: `cl_basis_bps < 9 → Buy Up; else → Buy Down`**
- Agreement: **90.0%** (36/40 fires)
- Up fires: cl_basis mean = 7.1, median = 7.8
- Down fires: cl_basis mean = 12.0, median = 11.5
- Perfect Down-side: all 22 Down fires have cl_basis ≥ 9 (100%)
- Up-side: 14/18 Up fires have cl_basis < 9 (78%)

**Interpretation**: When Binance price is running *ahead* of the Chainlink oracle (high cl_basis), the wallet bets Down (fade the Binance premium). When Binance and Chainlink are tightly aligned, it bets Up. This is identical to the `0x0de4458d` pattern — trade the oracle-divergence cross signal.

Secondary signals (weak individually): `ema9_slope < 0 → Up` (60% agree), `rsi14 < 50 → Up` (55% agree). These are noise given the cl_basis dominance.

**No single secondary signal survives once cl_basis is controlled for.**

### (b) Entry Price Tiers

| Tier | n | WR | Interpretation |
|------|---|----|----------------|
| < 0.55 | 11 | 45.5% | Below-market entries — losing bucket |
| 0.55–0.75 | 20 | 90.0% | Core momentum tier |
| 0.75–0.90 | 9 | 100.0% | High-conviction / near-resolved |
| > 0.90 | 0 | — | No near-expiry extreme entries |

Core tier (0.55–0.90): n=29, WR=**93.1%**, 95%CI=[0.78, 0.98]. Fire offset mean=38s.

The 11 low-tier fires (<0.55) pull headline WR down. The `cl_basis` signal operates in the core tier; the losers cluster at entry_px < 0.55 where the wallet may be wrong about the direction.

### (c) Slug Selection

Weak signal overall (all Cohen's d < 0.40):
- `rv_15m_bps`: engaged=2.78 vs ctrl=3.48 (d=−0.39, p=0.045) — picks **lower-volatility** slugs
- `ema9_slope_bps`: engaged=0.16 vs ctrl=0.08 (p=0.88) — no significant selection
- `cl_basis_bps`: engaged=9.78 vs ctrl=10.04 (p=0.46) — no slug-level bias

**Verdict**: Slug selection signal is weak or absent with only 1 day of data. The wallet may simply be scanning all available 5m BTC slugs and applying the cl_basis direction filter universally.

### (d) Win vs Loss Separability

BTC losses (n=8) have significantly different features vs wins (n=32):
- `macd_hist`: wins=−1.48, losses=4.01 (d=−0.83, p=0.046)
- `ema9_slope_bps`: wins=−0.15, losses=1.43 (d=−0.76, p=0.082)
- `rsi14`: wins=48.2, losses=59.3 (d=−0.70, p=0.107)
- `px_vs_ema21_bps`: wins=−0.09, losses=3.92 (d=−0.69, p=0.088)

Pattern: **Losses occur when momentum was actually positive** (rising macd_hist, slope, RSI > 50) — i.e., when the wallet bought cl_basis-contrarian but momentum disagreed. The wallet wins when the market was already flat/bearish at entry.

---

## Wallet 2: `0xf6d2f340` — SOL 5m

### Summary
- **68 fires, WR 75.0%, mean entry 0.655, span May 26–27**
- **Fires mid-slot**: mean offset 125s, median ~125s (spread across slot)
- **Reference pattern: partial `0xe3867b68` (px_vs_strike momentum) — WEAK DECODE**

### (a) Direction Picker

**Primary signal: `px_vs_strike_bps` (Cohen's d = +1.095)**

`px_vs_strike_bps` = `(binance_px − strike_price) / strike_price × 10000` bps, measuring how far price has moved from the strike at entry time. Note: ALL 68 fires have `px_vs_strike > 0` (price was above strike for every fire).

**Best rule: `px_vs_strike_bps > 16 → Buy Up; else → Buy Down`**
- Agreement: **75.0%** (51/68 fires)
- Up fires: px_vs_strike mean = 18.0, median = 17.3
- Down fires: px_vs_strike mean = 11.9, median = 12.9

**Interpretation**: When SOL price is *well above* strike (>16 bps), wallet bets Up — momentum continuation. When price is only slightly above strike (~12 bps), wallet bets Down — expecting mean reversion back toward strike. This is a distance-from-strike momentum/reversion hybrid.

**Important caveat**: px_vs_strike correlates weakly with entry_px (r=0.03) and fire_offset (r=0.09), so this is a genuine directional signal, not an artefact of near-resolution timing.

No secondary rule materially improves agreement. All other features top out at 64% (ret_1m), 65% (ret_3m), 63% (rsi14). `cl_basis_bps` is flat between Up/Down (14.12 vs 14.89) — no oracle-divergence signal.

### (b) Entry Price Tiers

| Tier | n | WR | Mean fire offset (s) |
|------|---|----|----------------------|
| < 0.55 | 23 | 43.5% | 89 |
| 0.55–0.75 | 15 | 86.7% | 113 |
| 0.75–0.90 | 21 | 95.2% | 141 |
| > 0.90 | 9 | 88.9% | 196 |

Two-tier structure:
- **Below 0.55**: losing bucket (43.5% WR) — ~1/3 of all fires
- **Above 0.55**: high WR (87–95%) — the "real" signal fires
- High-px tier (>0.75, n=30): WR=**93.3%**, 95%CI=[0.79, 0.98]

The losing bucket fires earlier (89s offset) and at lower conviction. The wallet appears to have two modes: exploratory low-conviction entries that lose, and high-conviction late entries that nearly always win.

### (c) Slug Selection

**Statistically significant (p<0.05) — wallet prefers BEARISH slugs:**
- `ema9_slope_bps`: engaged=−0.99 vs ctrl=+0.47 (d=−0.31, p=0.032)
- `px_vs_ema21_bps`: engaged=−2.67 vs ctrl=+0.62 (d=−0.31, p=0.025)
- `ret_15m`: engaged=−4.84 vs ctrl=+1.30 (d=−0.30, p=0.030)
- `ret_5m`: engaged=−1.66 vs ctrl=+1.40 (d=−0.39, p=0.068)

**Verdict**: Wallet selects slugs where SOL has been falling over the prior 5–15 minutes. Then, within those bearish slugs, it either bets Down (momentum) or Up (when px_vs_strike is very high, suggesting oversold bounce). However the 1-day window is a severe confound — May 26–27 may have been a sustained SOL downtrend, making "bearish slug selection" trivially an artefact of the timeframe.

### (d) Win vs Loss Separability

Weak separation (all p > 0.08):
- `ret_3m`: wins=−0.81, losses=3.31 (d=−0.53, p=0.082) — losses had rising momentum
- `ret_1m`: wins=−1.12, losses=0.78 (d=−0.37, p=0.239)
- `px_vs_strike_bps`: wins=14.0, losses=15.6 (d=−0.29, p=0.379) — no useful split

**Pattern**: Similar to BTC wallet — losses occur when short-term momentum contradicted the px_vs_strike direction signal. Not strongly separable.

---

## Comparison to Reference Wallets

| Wallet | Asset/TF | Direction Signal | d | Pattern |
|--------|----------|-----------------|---|---------|
| `0x0de4458d` | BTC-5m | `cl_basis_bps` low → Up | 1.8+ | Oracle divergence contrarian |
| **`0x8ef6a1cc`** | **BTC-5m** | **`cl_basis_bps < 9 → Up`** | **2.04** | **Same as `0x0de4458d`** |
| `0xe3867b68` | Multi-15m | `ema9_slope > 0 → Up` | 0.5–1.0 | EMA momentum |
| **`0xf6d2f340`** | **SOL-5m** | **`px_vs_strike > 16 → Up`** | **1.10** | **Partial match — momentum-distance, not a clean EMA signal** |

---

## Edge Reliability Verdict

### `0x8ef6a1cc` BTC-5m

**Binomial test**: p=0.0001 vs null WR=50%. 95%CI for core tier: [0.78, 0.98].
**Assessment: PROMISING signal (cl_basis_bps, d=2.04) BUT 1-day data only.**

The cl_basis direction rule (90% agree) matches a previously-decoded wallet (`0x0de4458d`), which adds circumstantial credibility. However:
- 1 day = 40 fires. A single lucky streak can produce 80% WR.
- The WR in the low-tier bucket (45.5%) shows the strategy isn't infallible.
- **Action**: Re-pull chain history for this wallet. If it has been active for weeks with similar WR, the cl_basis signal is likely real. If it's a new wallet, treat as hot-streak only.

### `0xf6d2f340` SOL-5m

**Binomial test**: p<0.0001 vs null WR=50%. 95%CI for core tier: [0.76, 0.97].
**Assessment: INSUFFICIENT DATA, WEAK DECODE.**

- Best direction rule only 75% agree — not cleanly decoded.
- Slug selection reflects 1 day of bearish SOL market, not robust wallet behavior.
- No matching reference pattern found (px_vs_strike signal is novel and context-specific).
- **Action**: Re-pull chain history. If wallet has weeks of history with consistent SOL-5m activity, decode again with longer window. Otherwise treat as 1-day fluke.

---

## Recommended Next Steps

1. **Re-pull both wallets** via `strategy_lab/wallet_hunt/` chain pull scripts — get max available history.
2. **If `0x8ef6a1cc` has >2 weeks history**: re-run harness, validate cl_basis rule holds, check if it matches `0x0de4458d` deployment parameters.
3. **If `0xf6d2f340` has >2 weeks history**: re-run harness on expanded data; try multi-feature direction model; check if different TF (15m) shows cleaner signal.
4. **Do NOT deploy either strategy** based on 1-day decode. The high WR figures are visually compelling but statistically anemic given the sample size and hot-streak confound.

---

*Generated: 2026-05-28 | Data window: May 19–20 (BTC) and May 26–27 (SOL) | Harness: `trigger_decode_harness.py`*
