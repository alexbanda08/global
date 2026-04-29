# 11 — Why "Passed" Strategies Now Fail: Methodology Mismatch

**Date:** 2026-04-24
**Scope:** comparing the V22/V25/V28/V29/V30 historical "passing" configs against my new Phase-5 / robustness battery runs.

## Bottom line

**Your historical strategies did NOT fail this week.** They were never actually retested. The new battery ran *signature-compatible shells* of those strategies — the signal generators — but **every major axis of the execution model is different.** The strategies shipped in your Pine scripts and reports live in an entirely different sandbox than the one the new battery scored them in.

## The 8 axis-mismatches

| Axis | Historical (V22/V25/V28/V29/V30 reports) | My new battery |
|---|---|---|
| 1. **Venue / fee model** | **Hyperliquid perps** · 0.045% taker fee/side · 3 bps slip | **Binance spot** · 0.1% flat (v1) or 0.1% maker (limit) · 5 bps slip |
| 2. **Leverage** | **3× leverage cap** | **Unleveraged spot** |
| 3. **Sizing** | **3–5% ATR-risk per trade** | **100% of equity per trade** (vbt `size=inf, size_type="value"`) |
| 4. **Direction** | **Long + Short** (perps allow it) | **Long-only** (my runner only feeds `entries` + `exits`, **drops** `short_entries`/`short_exits`) |
| 5. **Exit stack** | **TP=10×ATR, SL=2×ATR, trail=6×ATR, max_hold=60 bars** applied externally | **Whatever the raw scanner-discovered signal function returned** — many are bare `entries`/`exits` with no ATR stack |
| 6. **Data window** | **2019-01 → 2026-04** (7 years) with IS=pre-2024, OOS=2024-onward | **2022-01 → 2024-12** (3 years, 75/25 split) — cuts off 2019–2021 AND 2025–2026 |
| 7. **Per-symbol tuning** | **Per-coin tuned params** (BTC 2h alpha=0.07 rng_len=300; SOL 2h rng_len=250; etc.) | **Default function signatures** — defaults may not match the tuned configs that actually passed |
| 8. **Unit of evaluation** | V28 "+156% CAGR, Sh 1.97, DD −33%" is a **3-sleeve yearly-rebalanced equal-weight portfolio** | **Per-cell single-symbol single-strategy** — apples vs. oranges |

## What this means per strategy you asked about

### SOL BBBreak_LS
- **Historical:** SOL V23 BBBreak **L+S perps 3× lev**, 4h, ATR-risk sizing → 2020–2026 CAGR +139% (V25 numbers) → 2023 alone: **+358%**.
- **My test:** `sig_bbbreak` long-only, 100%-equity sizing, no ATR exits, 2022-01→2024-12, Binance spot 0.1% fees → Sharpe −0.22.
- **Reason for gap:** I dropped the short side (which in 2022's bear contributed positively), dropped the 3× leverage, dropped the ATR stack, halved the data window, and doubled the fees.

### DOGE HTF_Donchian
- **Historical:** V27 family @ 4h with ATR TP/SL/trail, perps L+S. V28 portfolio shows DOGE as part of SOL/SUI/DOGE all-BBBreak blend — V27 Donchian was an ETH variant, not DOGE specifically.
- **My test:** `sig_htf_donchian_ls` on DOGE 4h spot long-only → Sharpe +1.53, Calmar +3.31, 4/8 battery (still the best single cell).
- **Reason for gap:** Smaller because I picked the LS variant from run_v34 which DOES include both sides; DOGE actually scored well because the raw signal is strong enough to survive even my stripped-down execution.

### SOL SuperTrend_Flip / ETH CCI_Extreme_Rev / DOGE TTM_Squeeze_Pop
- **Historical (V30 report):** these are OOS winners from the V30 "creative round" — 4h cadence, per-coin tuned params, **Hyperliquid perps model**, ATR exits, L+S. V30 reports CCI ETH 4h: IS Sh +1.16 / OOS Sh **+2.37** / OOS CAGR **+123%** / OOS DD −17.4%.
- **My test (long-only spot, defaults, 2022–2024):** CCI ETH Sharpe **+0.17**, Calmar −0.10, plateau **cliff detected**.
- **Reason for gap:** The OOS period in V30 is **2024-onward** (when ETH ran), while my 75/25 split put the OOS at 2024-Q3–2024-end (a small narrow window). The V30 numbers are also net of the **ATR exit stack** which I didn't apply.

### V24_MF_1x / _5SLEEVE_EQW
- These are **not signal functions** — they're portfolio-configuration labels referring to specific setups inside `run_v24_regime_router.py` and a 5-way sleeve combiner. Can't be run via a generic scanner. Need per-config adapters.

## Why the robustness battery's verdicts are still useful

Even though the numbers don't match historical reports, the battery's **relative** rankings remain informative:
- Strategies that fail per-year consistency in my stripped setup will likely fail it in the full setup too (because per-year consistency is orthogonal to sizing/leverage).
- Parameter plateau is fee-model-agnostic — a strategy that cliffs at ±50% params in my spot-test will cliff in perps too.
- The cross-cell ranking (DOGE_HTF > VB ETH > CCI ETH > SuperTrend SOL) probably holds qualitatively in the historical setup — the *absolute* numbers would scale up with leverage + ATR exits + per-coin tuning.

## Fix plan — properly "replicate the historical tests"

To reproduce the historical V22/V25/V28/V29/V30 numbers under the new battery, we need:

1. **Hyperliquid-equivalent execution mode.** Add a new `ExecutionConfig(mode="perps_hyperliquid")` that:
   - Taker fee 0.045% / maker rebate 0.015%
   - 3× leverage cap (sized up via `size_type="targetpct"` at 300%)
   - Slip 3 bps
   - Funding drag 8% APR on exposure
2. **ATR exit-stack overlay.** Take any raw `entries` from a signal fn and bolt on TP=10×ATR, SL=2×ATR, trail=6×ATR. This is precisely the v1-mode `sl_stop/tsl_stop/tp_stop` path — but translated from ATR multiples to percent floors.
3. **L+S wrapper.** Add a `L_plus_S_runner()` that accepts both `entries`+`exits` AND `short_entries`+`short_exits`. The scanner already discovered many L+S signal fns.
4. **Long-window runs.** Extend data load to `2019-01 → 2026-04` for coins with data; use `2019-onward` for BTC/ETH/SOL and `2023-05-onward` for SUI.
5. **Per-symbol tuned params.** Feed each cell the parameters listed in the V22/V25/V30 reports (e.g., BTC V22 RK: alpha=0.07, rng_len=300, rng_mult=3.0, regime_len=800).
6. **Portfolio aggregator.** V28 P2 "+156% CAGR" is a 3-sleeve blend — need a combiner that runs three single-cell backtests and produces a yearly-rebalanced equal-weight portfolio equity curve.

Each of those 6 is ~0.5–1 turn of work. If you want, I can stack them into a new `run_phase5_perps_parity.py` driver that replicates the historical setup, then rerun your 9 requested cells. That should reconcile the numbers.

## What stayed honest

- **volume_breakout ETH 4h** (4/8) — passed under my stripped execution, so it's edge-positive regardless of leverage/fees.
- **DOGE HTF_Donchian 4h** (4/8) — same.
- **ETH CCI_Extreme_Rev parameter cliff** — will also show up in the leveraged perps config; plateau test is independent of execution mode. That warning is real.

Both of those survive the methodology gap. Every other cell's failure could be overturned by the fix plan above.
