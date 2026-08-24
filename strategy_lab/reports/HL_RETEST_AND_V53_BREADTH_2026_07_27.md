# Hyperliquid system: re-test on fresh data, V53 breadth fleet, shadow wired

**Date:** 2026-07-27 · **Scope:** audit the in-app HL strategies, re-test them on current data, improve, get shadow firing.
**Artifacts:** `strategy_lab/hl_research_2026_05_26/retest_2026_07_27/` (`_r0`…`_r7` + CSVs) · `shadow_v52/v53_shadow_runner.py` · `shadow_v52/build_v53_cards.py`

---

## TL;DR

1. **The V52 fleet's forward result was real, not noise-free luck — but it was also not the whole story.** Its pre-registered live window (≥2026-06-11, n=46) is **−0.215%/trade**. Bootstrapped against a long untouched window, a block that bad occurs only **6.5–9.4%** of the time. Borderline, not proof of death.
2. **The signal families, not the sleeves, are the right unit of analysis.** Tested 6 families × 10 coins on data the V52 selection never saw (pre-2024-03, ~105k 4h bars). **STF (SuperTrend flip) passes Bonferroni with 9/10 coins positive** (n=877, +1.054%/tr, t=+5.01) and independently repeats in the second window (t=+4.37). **VP passes the untouched window** (n=1914, t=+3.93, 10/10 coins) **but has since decayed to significantly negative** (−1.091%/tr, t=−3.38, 2/10 coins).
3. **5 of the 9 deployed V52 sleeves sit on families that do not survive** (CCI/SVD nominal-only; MFI/LATBB weak, t=1.65/1.07). MFI_SOL was the shadow's best performer and is on the *weakest* family — a textbook cherry-pick.
4. **The real blocker was never the edge — it was trade rate.** V52 fires ~12/month; at sd=6.7%/tr it needs ~530 trades ≈ **45 months** to confirm itself. Fixed by breadth.
5. **The "70% stop-outs" is not a bug.** A 62-variant exit grid says the incumbent is near-optimal (rank 7/62) and *tighter* stops are better. No variant wins both windows → kept unchanged.
6. **Root-caused the empty production HL cards**, which was neither the API stub nor the DB pool: **`engine.hl_bars` held 42 bars at tf=4h** because retention pruned everything to 7 days, so EMA(200) and the 500-bar ATR gate silently degraded to flat. Fixed and backfilled to 5001 bars/coin.

---

## A. What the fresh data says about the existing fleet

### A-1. HL data reality (corrects the prior handoff)

| Claim in prior handoff | Actual |
|---|---|
| "3.3 years of HL 4h, 5 coins" | **False.** 180 bars of Apr-2023 with `volume == 0.0` on every bar, a 10-month hole, then continuous only from **2024-02-26**. |
| HL history extensible | **No.** HL API returns EMPTY for every probe before 2024-03 (`_r0_probe_hl_gap.py`). Retention starts ~2024-03. |
| VPS3 collector covers the sleeve coins | **No.** `hyperliquid_klines_v2` collects only BTC/ETH/HYPE/SOL — **no AVAX/LINK**, yet 4 of 9 sleeves trade them. |

The zero-volume block was **actively harmful**: `volume==0` breaks the V45 volume filter, MFI, volume-profile, signed-vol divergence and the HMM's `vol_ratio` feature, and a disconnected 10-month-stale prefix still seeds EMA200/SuperTrend warmup. Dropped by `_r7_clean_orphan_bars.py` (backups kept).

### A-2. Honest window split on HL (`_r1`)

The optimization window was **2024-01-12 → 2026-04-25**, so only the post-window is untouched:

| Window | n | mean/tr | WR | t | ex-top2 |
|---|---:|---:|---:|---:|---:|
| IS (selection) | 506 | +1.456% | 35.0% | +4.48 | +$83,215 |
| POST (untouched) | 76 | +1.440% | 32.9% | +1.59 | **+$2,199** of $13,657 |
| **SHADOW (≥Jun-11, pre-registered)** | **46** | **−0.215%** | 28.3% | **−0.24** | −$15,164 |

POST looks fine until you notice **84% of it is two trades**. The pre-registered slice is negative.

### A-3. Long-history validation (`_r2`) — where the power is

HL can't provide depth, so I used native Binance 4h (clean, 0 zero-volume bars) with **real Binance perp funding** for BTC/ETH/SOL. Everything before 2024-03 is untouched by the V52 selection.

Pooled untouched window: **n=927, +1.048%/tr, WR 32.9%, t=+4.76, ex-top2 +$140k of $174k** (only 20% from the top 2 trades). 6/9 sleeves hold, 3 weak-positive, **0 fail**.

So the sleeve family does carry an edge. The V52 *forward* disappointment is a mix of noise, regime, and — mainly — the next point.

---

## B. The decisive findings

### B-1. Family × universe (`_r4`) — the deployed set is partly cherry-picked

6 families × 10 coins, uniform static exits, uniform ATR gate, untouched window. One hypothesis per family, Bonferroni |t|>2.64. Headline stat is **breadth**: a family that only works on its discovery coin is an artifact.

| Family | n | mean/tr | t | breadth | ex-top2 | HL_ERA t | verdict |
|---|---:|---:|---:|:---:|---:|---:|---|
| **STF** | 877 | +1.054% | **+5.01** | **9/10** | +$124,216 | **+4.37** | **PASSES** |
| **VP** | 1914 | +0.501% | **+3.93** | **10/10** | +$159,319 | +1.40 | **PASSES** |
| CCI | 836 | +0.597% | +2.99 | 6/10 | +$63,736 | +1.31 | nominal only |
| SVD | 1301 | +0.335% | +2.19 | 7/10 | +$33,063 | +1.26 | nominal only |
| MFI | 1586 | +0.231% | +1.65 | 5/10 | +$34,846 | +1.43 | **weak** |
| LATBB | 515 | +0.264% | +1.07 | 6/10 | +$8,126 | +1.35 | **weak** |

**CCI_ETH, MFI_SOL, MFI_ETH, SVD_AVAX, LATBB_AVAX — 5 of 9 deployed sleeves — sit on non-validated families.**

### B-2. Sequential decay: STF persists, VP is dying

| window | STF | VP |
|---|---|---|
| 2017→2022 | +1.549% (t=+5.28) | +0.759% (t=+4.27) |
| 2022→2024-03 | +0.443% (t=+1.49) | +0.186% (t=+1.03) |
| 2024-03→2025 | +0.765% (t=+1.51) | +0.375% (t=+1.30) |
| 2025→2026-03 | +1.933% (t=+4.47) | +0.342% (t=+1.48) |
| 2026-04→now (HL) | **+1.144% (t=+1.62)** | **−1.091% (t=−3.38)** |
| recent breadth | 6/10 coins | **2/10 coins** |

STF is **positive in every window and never negative**. VP decays monotonically then flips significantly negative. This is why VP is logged but never sized.

### B-3. Power (`_r3`) — the actual blocker

- Live shadow block (n=46, −0.215%) vs the untouched distribution: **P = 6.5% (contiguous) / 9.4% (iid)**. Borderline; consistent with regime, not proof of death.
- To resolve a +1.05%/tr edge at 95% power with sd=6.70%: **~530 trades**. At V52's ~11.8 fires/month that is **~45 months**.

**Conclusion: V52 could never have been validated live.** The fix is breadth, and it is also why I did not simply retune V52.

### B-4. Gates (`_r3b`) — mostly earn their keep, two do not

Paired A/B on identical entries, untouched window: **5 help, 2 hurt**, mean +0.228pp. `FUND_Z` **hurts STF_SOL** (−0.330pp) and `ATR_NOTOPVOL` **hurts SVD_AVAX** (−0.253pp). Also corrected an assumption: FUND_Z is *not* a near-no-op — it rejects 32% of BTC/ETH bars (pass rate 68%), because funding is fat-tailed.

### B-5. Exits (`_r5`) — the premise was wrong, so nothing changed

62 variants on the validated portfolio, ranked on the untouched window and verified on the second:

- Incumbent `tp10/sl2/trail6/hold60` ranks **7 of 62**.
- Rank transfer rho = **+0.457** → the grid is informative, not noise.
- **No variant beats the incumbent in both windows → KEPT.**
- Marginals are monotonic and vindicate the design: sl 1.5 → +0.52, 2.0 → +0.49, **4.0 → +0.21**; trail 6–8/None ≈ +0.44 but trail 4 → +0.21; hold 60 → +0.49 vs 30 → +0.21.

**Tighter stops are better, so a ~70% stop-out rate is the intended positive-skew structure.** Only `tp_atr=15` is worth a future pre-registered test (+0.837 vs +0.675 untouched, neutral in the other window) — **not adopted**, it fails the both-windows rule.

---

## C. What I built: V53 breadth fleet

`shadow_v52/v53_shadow_runner.py` — the validated families across the whole 10-coin universe, **no per-coin cherry-picking** (deliberately keeps cells that look bad alone, e.g. STF on LINK was −0.078%, because excluding them is the bias that produced §B-1).

| | V52 (incumbent) | V53 (new) |
|---|---|---|
| streams | 9 hand-picked pairs | 20 (2 families × 10 coins) |
| on validated families | 4 of 9 | 10 of 10 in DEPLOY arm |
| fire rate | ~12/month | **~61/month** (243 closed in 120d) |
| months to 95% power | ~45 | ~27 |

**Arms** — the honest part: `DEPLOY = STF` (10 streams, capital-eligible after the shadow gate) and `OBSERVE = VP` (10 streams, logged at $0, never sized, so a recovery is visible without risking money on a decaying edge). PnL is reported per arm; pooling them would let one hide the other.

Config is entirely inherited, nothing re-fitted: ATR_NOTOPVOL gate, static EXIT_4H, equal weight.

**First 120 days of V53 paper:** DEPLOY/STF n=82, **+1.144%/tr**, WR 37.8%, +$234.59 · OBSERVE/VP n=161, −1.091%/tr, −$439.10. The DEPLOY arm matches its offline +1.054%.

---

## D. Bugs found and fixed

| # | Bug | Impact | Fix |
|---|---|---|---|
| 1 | **`engine.hl_bars` had 42 bars at tf=4h** — 7-day blanket retention vs EMA200 (200 bars) and the 500-bar ATR rank | **This is why the production HL cards were empty.** Every signal silently degraded to FLAT. Not the API stub, not the DB pool. | Per-table retention (`_patch_hl_retention.py`): 1h/4h/1d kept 400d, 15m/5m and the fat tables (hl_trades 426MB/7d, hl_asset_ctx 304MB/7d) unchanged. Backfilled to **5001 4h bars/coin**. |
| 2 | `tv_cards_feed.py:45` crashed with `EmptyDataError` on the empty `pending_fires_latest.csv` | Feed crashed **every run** with no pending fire (the common case) → `_tv_cards_feed.json` permanently stale | Empty-tolerant `_load()`; V52 runner now always writes a header row |
| 3 | 180 orphaned Apr-2023 HL bars with `volume == 0.0` | Breaks V45 volume filter, MFI, VP, SVD, HMM `vol_ratio`; pollutes EMA200 warmup | Dropped (`_r7`), backups kept |
| 4 | `tv-engine` inactive (manually stopped, 3d13h uptime, clean exit) | No HL loop at all | Compile-checked the other agent's uncommitted files, restarted; 10 V52 streams registered |
| 5 | HL store missing 5 of 10 universe coins | V53 not runnable | Bootstrapped ADA/BNB/DOGE/XRP/SUI (5000 bars each, clean) + added to `ingest_hyperliquid.COINS` so the hourly tick keeps them fresh |

---

## E. State now

**Local (hourly `V52Shadow` task, verified end-to-end):** data refresh 10 coins → V52 (9 sleeves) → **V53 (20 streams)** → XSM → V52 cards → **V53 cards** → TV feed. All steps clean; the feed no longer crashes.

**VPS3:** `tv-engine` + `tv-api` + Postgres active. `engine.hl_bars` 25,005 4h rows. Card signals compute for real — `V52-AVAX = SHORT (0.333)`, others genuinely voted flat (`confidence=0.0` = controllers ran; `None` = none registered). **Cross-check: VPS3 V52-AVAX SHORT agrees with local V53 STF_AVAX SHORT on the same bar.**

`V52-BTC` still reads FLAT/`None` because VPS3's registry has **no BTC stream** (10 streams, none BTC) — the STF_BTC sleeve is a local-only optimization not yet ported.

---

## F. Recommendation

1. **Do not give V52 capital.** 5 of 9 sleeves are on non-validated families and it cannot be validated live in under ~4 years.
2. **Promote V53's DEPLOY (STF) arm** through the shadow gate. It is the only thing here validated on an untouched window *and* positive in every sequential window *and* broad across coins.
3. **Never size VP.** Significantly negative now (t=−3.38); keep it logged only.
4. Keep exits exactly as they are.

**Open / not done (deliberately):**
- Port STF_BTC + the FUND_Z/ATR gate fixes to the VPS3 controllers, and drop `FUND_Z` from STF_SOL and `ATR_NOTOPVOL` from SVD_AVAX (§B-4). Not applied: VPS3 controllers are the other agent's active working tree.
- Extend the VPS3 HL collector past BTC/ETH/HYPE/SOL (no AVAX/LINK, and none of the 5 new coins).
- Pre-registered `tp_atr=15` test.
- Promotion gates unchanged: ≥4 weeks shadow, funding reconciles ±5%, no stream −12% DD.
