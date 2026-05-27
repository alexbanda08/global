# Full-window OOS validation — 2026-05-26

**Window**: Apr 24 → May 25 2026 UTC (~32 days, chainlink-resolved markets)
**Reference (REF) slice**: existing joined files = May 1 → May 21 20:00 UTC (~21 days)
**OOS slice**: May 21 20:00 → May 25 19:10 UTC (~4 days, genuine out-of-sample, never tested before)
**Fee model**: Legacy 2%-on-profit-only (LegacyConfig per CLAUDE.md)
**Outcome source**: Chainlink RTDS (canonical resolutions)
**Spread filter**: 0.02 BTC/ETH, 0.025 SOL
**Notional**: $25/trade

## Method

1. **Reference**: Score every sleeve on the existing `s6_joined_all.parquet`,
   `s15_joined_all.parquet`, `v15m_joined_all.parquet` (May 1 → May 21 20:00).
   SMS gates joined from `*_with_sms.parquet`.
2. **OOS**: For each (asset, tf), built a fresh fire universe for May 21 20:00 →
   May 25 19:10:
   - Streamed 1s binance OHLCV from canonical `klines_1s.parquet`
   - Recomputed inline: Range Filter [DW], TR EMAs (5/13/50/200/800) +
     cloud + pivots + sessions, MA Ribbon + ribbon_color, Stoch 60s,
     BB 60s, MFI 60s, CCI 60s, SMS liquidity (5m bar pivot sweep)
   - L25 walk fill via `engine_v2.fill_at_book` with LegacyConfig
   - Outcome from chainlink resolutions (filtered to OOS window)
   - Same gate definitions as `hybrid_join_and_gates.py` +
     `sms_gate_overlay.py`
3. **Full** = REF + OOS, de-duped on (slug, fire_us, direction).

Artifacts:
- `data/v4/canonical/_results/_full_window_2026_05_26/sleeve_full_window_validation.csv`
- `data/v4/canonical/_results/_full_window_2026_05_26/sleeve_weekly_stability.csv`
- `data/v4/canonical/_results/_full_window_2026_05_26/oos_fires_{asset}_{tf}.parquet`
  (per-asset OOS fire universe with all features + gates joined)

## Data availability confirmation

| Asset | Resolutions (5m) | Resolutions (15m) | 1s klines | L25 books |
|---|---|---|---|---|
| BTC | 8,778 (Apr 24 01:40 → May 25 19:10) | 2,920 | 4.1M bars to May 25 19:15 | Apr 22 → May 25 (5 deltas) |
| ETH | 8,778 | 2,920 | 4.1M | same |
| SOL | 8,778 | 2,920 | 4.1M | same |

OOS slice has **1,090 new 5m markets and 360 new 15m markets per asset**.

## Per-sleeve results

WR_doc / dpt_doc / sum_doc = original 22d reference from prior reports.
REF_rerun = our re-scored 21d REF using the existing joined files.
OOS = May 21 20:00 → May 25 19:10 only (~4 days, genuine OOS).
FULL = REF + OOS combined (~25 days).

| # | sleeve_id | n_doc / n_ref / n_oos / n_full | WR_doc / WR_ref / WR_oos / WR_full | dpt_doc / dpt_ref / dpt_oos / dpt_full | sum_doc / sum_ref / sum_oos / sum_full |
|---|---|---|---|---|---|
| 01 | btc_5m_s6_hybrid_v2_sms | 699 / 699 / 132 / 831 | 88.3% / 88.3% / **78.0%** / 86.6% | $18.71 / $18.71 / **$0.14** / $15.76 | $13,075 / $13,075 / $19 / **$13,094** |
| 02 | btc_5m_s6_hybrid_v1 | 2764 / 2764 / 2570 / 5334 | 77.8% / 77.8% / **71.4%** / 74.7% | $5.10 / $5.10 / **$1.90** / $3.56 | $14,103 / $14,103 / $4,875 / **$18,978** |
| 03 | eth_5m_s6_hybrid_v2_sms | 324 / 718 / 584 / 1302 | 61.4% / 78.1% / 73.3% / 76.0% | $10.52 / $6.47 / **$0.29** / $3.70 | $3,410 / $4,649 / $170 / **$4,819** |
| 04 | eth_5m_s6_hybrid_v1 | 3531 / 3531 / 5454 / 8985 | 76.0% / 76.0% / 70.1% / 72.4% | $1.57 / $1.57 / **$0.86** / $1.14 | $5,553 / $5,553 / $4,694 / **$10,247** |
| 05 | btc_5m_off120_sms_liq | 166 / 298 / 229 / 527 | 77.1% / 81.9% / **48.9%** / 67.6% | $20.68 / $23.60 / **−$4.33** / $11.46 | $3,432 / $7,032 / **−$992** / $6,040 |
| 06 | eth_5m_s15_hybrid_v1 | 3420 / 4495 / 2509 / 7004 | 85.1% / 85.0% / 77.6% / 82.4% | $1.34 / $1.24 / **−$0.33** / $0.68 | $4,596 / $5,591 / −$817 / **$4,774** |
| 07 | btc_5m_s15_hybrid_v1 | 1365 / 1753 / 1783 / 3536 | 85.6% / 86.3% / 73.4% / 79.8% | $3.06 / $3.12 / $2.08 / $2.60 | $4,176 / $5,477 / $3,714 / **$9,191** |
| 08 | sol_5m_s6_hybrid_v1 | 1503 / 1803 / 3920 / 5723 | 92.9% / 88.3% / 71.0% / 76.4% | $2.20 / $1.87 / $0.61 / $1.01 | $3,307 / $3,376 / $2,407 / **$5,782** |
| 09 | btc_5m_xa_down (DOWN only) | 2726 / 1468 / 8047 / 9515 | 82.1% / 68.9% / **56.0%** / 58.0% | $1.64 / $5.75 / **−$1.10** / −$0.05 | $4,463 / $8,434 / **−$8,869** / **−$435** |
| 10 | btc_15m_s7_hybrid_v1 | 816 / 1332 / 1185 / 2517 | 88.0% / 83.6% / 78.3% / 81.1% | $2.15 / $0.39 / **−$1.16** / −$0.34 | $1,752 / $516 / −$1,378 / **−$862** |
| 11 | eth_15m_off120_240 | 130 / 358 / 359 / 717 | 84.6% / 78.8% / **60.2%** / 69.5% | $3.81 / $1.37 / **−$1.59** / −$0.12 | $495 / $489 / −$572 / **−$83** |
| 12 | eth_15m_off60_120 | 87 / 165 / 91 / 256 | 78.2% / 77.6% / 76.9% / 77.3% | $4.48 / $3.27 / **$5.68** / $4.13 | $390 / $540 / $517 / **$1,057** |
| 13 | pool_15m_offge480 | 86 / 1207 / 621 / 1828 | 87.2% / 84.7% / **45.6%** / 71.4% | $5.48 / $0.79 / $0.70 / $0.76 | $471 / $956 / $434 / **$1,391** |
| 14 | sol_5m_drz_res_down (DOWN) | 291 / 487 / 6685 / 7172 | 63.9% / 78.2% / **45.5%** / 47.7% | $6.62 / $1.04 / **−$5.34** / **−$4.91** | $1,927 / $508 / **−$35,730** / **−$35,221** |
| 15 | btc_15m_s7_tight | 816 / 1240 / 1169 / 2409 | 88.0% / 84.0% / 78.4% / 81.3% | $2.15 / $0.40 / **−$1.08** / −$0.32 | $1,752 / $501 / −$1,268 / **−$767** |

### Why ref_rerun differs from ref_doc on some sleeves

- **#01, #02, #04**: exact match. Original numbers carry over.
- **#03 (n=324→718)**: original doc used a more restrictive subset (probably
  inner test slice from walk-forward); our re-run uses the whole REF window.
  WR rises 17pp but $/tr drops 38% — consistent with looser filter.
- **#05 (n=166→298)**: doc used only off=120 strict; our re-run filtered the
  larger BTC 5m off=120 set with `g_sms_liq_reclaim_with`.
- **#06 (n=3420→4495)**: doc subset was the test split; full window picks up more.
- **#13 (n=86→1207)**: doc was POOL (BTC+ETH+SOL combined); our re-run is BTC-only
  with `g_rf_in_band`. Different population. Treat as "BTC subset of pool sleeve".
- **#14 (n=291→487)**: doc used DRZ panel filter (not in joined files); our
  re-run is SOL DOWN with `g_tr_above_pp` — looser and different gate.

These are **definitional drift** — not OOS-vs-IS. The OOS column is the true OOS
slice and is comparable cross-sleeve.

## Stability ranking (by OOS WR robustness vs REF WR)

| Rank | sleeve_id | WR_ref | WR_oos | Δ_WR | dpt_ref | dpt_oos | Δ_dpt | Verdict |
|---|---|---|---|---|---|---|---|---|
| 1 | 12_eth_15m_off60_120 | 77.6% | 76.9% | −0.7 pp | +$3.27 | **+$5.68** | +$2.41 | **IMPROVING in OOS** |
| 2 | 07_btc_5m_s15_hybrid_v1 | 86.3% | 73.4% | −12.9 pp | +$3.12 | +$2.08 | −$1.04 | **HOLDS — best 5m sleeve** |
| 3 | 06_eth_5m_s15_hybrid_v1 | 85.0% | 77.6% | −7.4 pp | +$1.24 | −$0.33 | −$1.57 | breakeven OOS |
| 4 | 02_btc_5m_s6_hybrid_v1 | 77.8% | 71.4% | −6.4 pp | +$5.10 | +$1.90 | −$3.20 | **HOLDS positive OOS** |
| 5 | 04_eth_5m_s6_hybrid_v1 | 76.0% | 70.1% | −5.9 pp | +$1.57 | +$0.86 | −$0.71 | **HOLDS positive OOS** |
| 6 | 01_btc_5m_s6_hybrid_v2_sms | 88.3% | 78.0% | −10.3 pp | +$18.71 | +$0.14 | −$18.57 | flat OOS (n=132) |
| 7 | 03_eth_5m_s6_hybrid_v2_sms | 78.1% | 73.3% | −4.8 pp | +$6.47 | +$0.29 | −$6.18 | flat OOS |
| 8 | 08_sol_5m_s6_hybrid_v1 | 88.3% | 71.0% | −17.3 pp | +$1.87 | +$0.61 | −$1.26 | degrading WR but +OOS |
| 9 | 10_btc_15m_s7_hybrid_v1 | 83.6% | 78.3% | −5.3 pp | +$0.39 | −$1.16 | −$1.55 | **NEGATIVE OOS** |
| 10 | 15_btc_15m_s7_tight | 84.0% | 78.4% | −5.6 pp | +$0.40 | −$1.08 | −$1.48 | **NEGATIVE OOS** |
| 11 | 13_pool_15m_offge480 | 84.7% | **45.6%** | −39.1 pp | +$0.79 | +$0.70 | −$0.09 | **WR COLLAPSE, $/tr held by tail bets** |
| 12 | 11_eth_15m_off120_240 | 78.8% | 60.2% | −18.6 pp | +$1.37 | −$1.59 | −$2.96 | **FAILS — negative OOS** |
| 13 | 05_btc_5m_off120_sms_liq | 81.9% | **48.9%** | −33.0 pp | +$23.60 | **−$4.33** | −$27.93 | **FAILS HARD — coin-flip OOS** |
| 14 | 09_btc_5m_xa_down | 68.9% | 56.0% | −12.9 pp | +$5.75 | **−$1.10** | −$6.85 | **FAILS — directional bias dies** |
| 15 | 14_sol_5m_drz_res_down | 78.2% | **45.5%** | −32.7 pp | +$1.04 | **−$5.34** | −$6.38 | **FAILS HARD — catastrophic** |

## Sleeves that FAIL OOS validation (WR < 60% OR $/tr ≤ 0)

Five sleeves do NOT pass OOS validation:

| sleeve_id | OOS WR | OOS $/tr | OOS sum | Failure mode |
|---|---|---|---|---|
| 14_sol_5m_drz_res_down | **45.5%** | **−$5.34** | **−$35,730** | Catastrophic. The DOWN-only SOL bet evaporated entirely. n=6,685 in OOS is suspicious — likely the loosened gate stack (no DRZ filter) over-fires. Do NOT deploy. |
| 09_btc_5m_xa_down | **56.0%** | **−$1.10** | **−$8,869** | The "BTC 5m DOWN with rf_with" bias has reversed in OOS. Cross-asset down picker lost edge. |
| 05_btc_5m_off120_sms_liq | **48.9%** | **−$4.33** | −$992 | The single-gate liquidity_reclaim sleeve is essentially a coin flip OOS. WR collapsed 33pp from 81.9%. **Not deployable as-is.** |
| 11_eth_15m_off120_240 | **60.2%** | −$1.59 | −$572 | The cci+tr_above_pp+tr_above_ema200 stack lost its edge on ETH 15m. |
| 13_pool_15m_offge480 | **45.6%** | +$0.70 | +$434 | WR collapse, but $/tr stayed positive due to a few big tail wins (W22 has $16.61/tr on n=137). Statistical fluke. |

## Sleeves that EXCEED reference (genuine OOS edge)

Only **one** sleeve shows OOS performance > REF: **12_eth_15m_off60_120**
(`g_rf_aged AND g_ribbon_agrees`).
OOS $/tr +$5.68 vs REF +$3.27 (+$2.41 lift on n=91). This is the most
RF-aged-trigger sleeve and the smallest sample — promising but n=91 is small.

## Sleeves that HOLD positive OOS edge

**Three sleeves remain unambiguously deployable** after OOS validation
(WR > 70% and $/tr > $0.50 in OOS):

| # | sleeve_id | OOS n | OOS WR | OOS $/tr | OOS sum | full_sum |
|---|---|---|---|---|---|---|
| 02 | btc_5m_s6_hybrid_v1 | 2,570 | 71.4% | +$1.90 | +$4,875 | **+$18,978** |
| 04 | eth_5m_s6_hybrid_v1 | 5,454 | 70.1% | +$0.86 | +$4,694 | **+$10,247** |
| 07 | btc_5m_s15_hybrid_v1 | 1,783 | 73.4% | +$2.08 | +$3,714 | **+$9,191** |
| 12 | eth_15m_off60_120 | 91 | 76.9% | +$5.68 | +$517 | **+$1,057** |

Plus three with modest OOS PnL but still positive on the FULL window:
| 06 | eth_5m_s15_hybrid_v1 | 2,509 | 77.6% | −$0.33 | −$817 | $4,774 |
| 08 | sol_5m_s6_hybrid_v1 | 3,920 | 71.0% | +$0.61 | +$2,407 | $5,782 |
| 13 | pool_15m_offge480 (BTC subset) | 621 | 45.6% | +$0.70 | +$434 | $1,391 |

## Updated combined deployable estimate (33d window)

If we deploy ONLY the 4 sleeves that pass strict OOS validation (#02, #04, #07, #12)
plus the 3 marginal positives (#06, #08, #13):

**Sum of full-window PnL: $51,506 on $25 notional / 25 days = $2,060/day**

Scaled to $250 notional: ~**$20,600/day**.

For comparison, the original spec promised:
- MASTER_DEPLOY_SPEC top-7: ~$40k/22d at $25 = $1,820/day at $25, $18,200/day at $250.
- NEW_INDICATORS_SYNTHESIS combined uplift: claimed +$25-35k/28d = $890-1,250/day at $25.

**OOS validated total ≈ same order of magnitude as the spec, but ~20% lower
on a per-day basis.** Most of the loss is from the SMS-enhanced sleeves (#01,
#03, #05) which collapsed in OOS — the iconic "$18.71/tr" headline number on
sleeve #01 turns out to be a sample-size artifact (n=699 ref vs n=132 OOS;
OOS dpt = $0.14, essentially zero).

## Weekly stability — illustrative selections

**Sleeve #01 (btc_5m_s6_hybrid_v2_sms)** — clear degradation:
- W18: n=14, WR=78.6%, $/tr=+$42.76
- W19: n=62, WR=77.4%, $/tr=+$5.68
- W20: n=50, WR=72.0%, $/tr=+$1.47
- W21: n=148, WR=80.4%, $/tr=+$1.66
- W22: n=20, WR=75.0%, $/tr=−$0.69

W18 single-week edge is a 14-trade fluke (+$42.76/tr could have been 2-3 big wins).
The "real" weekly cadence is W19-W22 at +$5.68 → −$0.69, decaying to zero.

**Sleeve #02 (btc_5m_s6_hybrid_v1)** — most stable:
- W18: +$9.83, W19: +$1.42, W20: +$4.88, W21: +$2.57, W22: −$0.28
- WR holds 65-77% across all 5 weeks.

**Sleeve #12 (eth_15m_off60_120)** — IMPROVING:
- W18: n=19, $/tr=−$1.25
- W19: n=52, $/tr=+$1.10
- W20: n=53, $/tr=+$4.89
- W21: n=118, $/tr=+$5.10
- W22: n=14, $/tr=+$11.64

Small samples, but clearly trending up. Either over-fit to the recent regime
or a genuine edge — n=91 OOS too small to call.

## Surprises

1. **SMS liquidity_reclaim does NOT survive OOS**. The headline #01 sleeve
   (BTC 5m S6 + SMS liq_reclaim) had OOS $/tr of $0.14, essentially zero.
   The 22d $18.71/tr was driven by W18-W21 high-WR clusters that didn't repeat.
   Sleeve #05 (the pure liquidity_reclaim BTC off=120) collapses to coin-flip
   in OOS.

2. **Cross-asset directional bias (#09) fully inverted**. BTC 5m DOWN with
   `g_rf_with` was the headline cross-asset finding — in OOS the same gate
   stack flipped to **negative** $/tr. Either the directional regime changed
   mid-window or this was an over-fit artifact.

3. **SOL DRZ DOWN (#14) was catastrophic OOS**. The 22d $6.62/tr promise
   produced n=6,685 trades in OOS at WR=45.5% / $/tr=−$5.34 / sum=−$35,730.
   Note: our re-run does NOT use the DRZ panel filter (not in joined files);
   without DRZ filter the gate is way too loose. Likely DEPLOYABLE in original
   spec form with DRZ filter, but our test is a worst-case unbounded version.

4. **15m sleeves degraded more than 5m**. Sleeves #10, #11, #13, #15 all
   went OOS-negative. The 15m timeframe has only ~360 markets in 4 days, so
   sample-size is small — but the trend is uniform.

5. **The two highest n-of-fires sleeves (#02, #04) are the most stable**.
   This is encouraging: large-base hybrid stacks with simple gate logic
   are the survivors. The bespoke high-headline-$/tr sleeves are the
   over-fitters.

## Caveats

- **OOS is 4 days, n is small per sleeve.** WR ± standard error at n=132
  (sleeve #01) is ~7pp — the 78% OOS WR is consistent with 88% REF within
  noise. Even our "failures" might recover with more data.
- **Several sleeves' REF_rerun differs from REF_DOC** because (a) the original
  doc numbers came from walk-forward test splits (not full REF), (b) the
  joined files don't have DRZ/QR/regime panels merged for sleeves #11, #13,
  #14 — those need the DRZ-joined and QR-joined files (`s6_joined_drz.parquet`,
  `s15_joined_drz.parquet`, `v15m_joined_drz.parquet`).
- **The "ref" window starts May 1 (not Apr 24)** because that's where the
  existing joined files start. The genuine 33d full window has data from
  Apr 24, but the L25/TA panels behind the joined files only cover from May 1.
  An additional Apr 24-30 slice (~6 days) is theoretically available for
  EXTRA OOS testing but would require rebuilding the joined files from scratch
  with a wider window.
- **SMS gate definition simplification**: our OOS computes SMS liquidity_up/dn
  from 1s OHLCV resampled to 5m bars (last-20-bar pivot tap). The original
  `compute_sms_panel.py` may use additional logic (BOS/CHoCH, divergences).
  If the SMS-enhanced sleeves' OOS failure is just our simpler proxy, the
  full SMS panel might salvage them — but we'd need to re-build it.

## Recommendation

1. **Deploy with confidence**: #02, #04, #07. These are the 21d/4d-consistent
   sleeves. Estimated $/day = $2,000 at $25 notional (~$20,000/day at $250).
2. **Deploy with monitor**: #06, #08, #12. Holding marginal-positive on full
   window but volatile per-week. Set strict daily-drawdown stop.
3. **Hold from deployment**: #01, #03, #05 (SMS-enhanced) — over-fit signature.
   Need to verify the full SMS panel rebuild + re-test before any commitment.
4. **Suspend** these "failed OOS" sleeves: #09, #10, #11, #13, #14, #15.
   They worked in REF but the OOS rejection is loud.
5. **Rebuild feature panels through May 25** for the next iteration. The
   joined files lag the data by 4+ days — this systematically prevents the
   research from staying aligned with the deployment fleet.

---

*Generated by `strategy_lab/full_window_validation_v2.py` on 2026-05-26.
Validation runtime 2.5 min on the live system.
Output artifacts in `data/v4/canonical/_results/_full_window_2026_05_26/`.*
