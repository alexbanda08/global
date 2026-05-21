# TRIGGER Tighten — Run Report 2026-05-07

## TL;DR

**G3 gate: FAIL** (avg_spread = 0.0pp, bar = ≥8pp).
GOLD collapsed to 10 trades across all 6 cells (was 57 before tightening).
Root cause: liq_magnet data ends Feb 2026; universe spans Apr–May 2026 → liq_magnet fires ≈37% overall but almost never for the actual test slugs. AND-of-2 requiring liq_magnet starves GOLD of samples.

---

## Trigger rebuild stats (v4, rebuild4)

| Metric | v2 (OR logic) | v4 (AND-of-2) |
|---|---:|---:|
| trigger_active rate | 79.7% | **14.9%** |
| trig_liq_magnet_active | 36.9% | 36.9% (unchanged) |
| trig_fvg_active | 96.4% | 96.4% (unchanged, dropped) |
| OFI threshold | >0.30 | >=0.50 |
| Composite logic | OR-of-3 | AND(liq_magnet, ofi_aligned) |

trigger_active at 14.9% is within the 5–25% target range.

---

## Tier breakdown comparison

| Tier | v2 (old OR) | v4 (new AND) |
|---|---:|---:|
| GOLD | 57 | **10** |
| SILVER | 123 | 170 |
| BRONZE | 189 | 30 |
| SKIP | 1236 | 1395 |

GOLD shrank 83%, BRONZE shrank 84%. Trades demoted to SKIP (where liq_magnet=0 kills TRIGGER).

---

## Per-cell GOLD vs BRONZE — was vs now

| Cell | GOLD n (was→now) | GOLD hit% (was→now) | GOLD mean$ (was→now) | BRONZE n (was→now) | BRONZE hit% (was→now) | BRONZE mean$ (was→now) |
|---|---:|---:|---:|---:|---:|---:|
| BTC_5m  | 24→6  | 87.5%→83.3% | +$0.26→-$0.25 | 66→5  | 87.9%→80.0% | +$0.41→-$2.93 |
| BTC_15m | 8→1   | 50.0%→0.0%  | -$8.63→-$25.00 | 19→2  | 73.7%→50.0% | -$1.38→-$8.28 |
| ETH_5m  | 6→0   | 100.0%→—    | +$3.36→—      | 20→5  | 85.0%→80.0% | -$2.07→-$3.00 |
| ETH_15m | 6→0   | 66.7%→—     | -$3.68→—      | 9→1   | 77.8%→100.0%| -$0.58→+$4.42 |
| SOL_5m  | 0→0   | —→—         | —→—           | 6→1   | 83.3%→100.0%| -$0.88→+$5.02 |
| SOL_15m | 1→0   | 100%→—      | +$8.12→—      | 7→0   | 57.1%→—     | -$6.73→—      |

Most GOLD cells now have 0 or 1 trade — no statistical content. G3 is undefined/0 spread.

---

## G3 gate verdict

```
[grand] G3 gate (GOLD vs BRONZE WR spread >= 8pp): FAIL (avg_spread=0.0pp)
```

Previous v2 result: FAIL (avg_spread = -0.4pp)
New v4 result: FAIL (avg_spread = 0.0pp) — trivially, because most GOLD cells are empty.

---

## Root cause analysis

The AND-of-2 logic is architecturally correct but **empirically untestable** until HL liquidations data is refreshed past Feb 2026:

1. `trig_liq_magnet_active` uses HL liquidations CSV ending 2026-02-06.
2. The momo universe was fetched 2026-04-27 to 2026-05-06.
3. For universe slugs, liq_magnet fires 0% of the time (no data overlap) → GOLD = 0 in 4/6 cells.
4. The 37% liq_magnet rate in the parquet comes from earlier slugs not in the momo backtest universe.

The OR-of-3 (v2) accidentally produced more GOLD samples by relying on FVG+OFI which ARE present — but those signals are saturated and noisy, so G3 also failed.

**Neither approach can pass G3 with stale liquidations data.**

---

## Recommendation

| Option | Expected outcome |
|---|---|
| **Revert to v2 OR logic** | GOLD=57, G3 spread=-0.4pp — still FAIL but more samples |
| **Keep v4 AND logic, wait for liq data** | Correct architecture; GOLD will populate once liq_csv updated |
| **Drop liq_magnet requirement, use OFI-only** | trigger_active ≈ OFI-aligned rate; avoids data gap; test if OFI>=0.50 alone separates tiers |
| **Try OFI-only (|ofi|>=0.50 AND aligned)** | Estimated trigger_active ~30-40%; GOLD could reach 50-100 trades |

**Recommended next step: P0 — top up HL liquidations data** (as flagged in CONFLUENCE_VERDICT_2026_05_07.md). The AND-of-2 logic in v4 is sound; it just needs the right data. Alternatively, implement OFI-only trigger (no liq_magnet) as a fast interim test.

---

## Artifacts

- Modified: `strategy_lab/confluence/trigger/build_trigger.py` — OFI_TRIGGER_ABS 0.30→0.50, composite changed to AND(liq_magnet, ofi_aligned), FVG dropped
- Log: `strategy_lab/results/trigger_rebuild4_2026_05_07.log`
- Log: `strategy_lab/results/grand_backtest_v3_2026_05_07.log`
- Report: `strategy_lab/reports/TRIGGER_TIGHTEN_2026_05_07.md` (this file)
- Updated: `strategy_lab/reports/CONFLUENCE_GRAND_BACKTEST_2026_05_07.md` (auto-written by grand backtest runner)
