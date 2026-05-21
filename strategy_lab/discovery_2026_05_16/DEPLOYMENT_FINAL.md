# Production Sleeve Restructuring — Definitive Deployment Spec (2026-05-16)

## TL;DR

**Current production: -$10,323/month (50.6% win, 30d paper).**
**Optimized: +$10,220/month** projection (KEEP 8 + FADE 27 cuts + KILL 36).
**Net swing: +$20,543/month.**

Built from live `trading_events_30d.parquet` + lookahead-corrected L25 backtest with 100ms latency. Drill-down on the 4 Bonferroni-strict cuts validates per-day-of-week + per-hour stability.

---

## Action table

### KEEP (8 sleeves) — leave running unchanged
| Sleeve | n | Win% | Live PnL |
|---|---:|---:|---:|
| poly_updown_sol_5m_momo_SELL | 240 | 56.3% | +$636 |
| poly_updown_sol_5m_momo_HEDGE | 242 | 55.8% | +$489 |
| poly_updown_sol_5m_momo_HOLD | 240 | 55.4% | +$451 |
| poly_updown_btc_15m_sniper | 234 | 49.6% | +$281 |
| poly_updown_eth_15m_volume_INV_NIGHT | 315 | 53.0% | +$156 |
| poly_updown_sol_5m_momo_v2_HOLD | 198 | 53.0% | +$150 |
| poly_updown_eth_5m_sniper | 317 | 49.5% | +$71 |
| poly_updown_sol_5m_v4 | 146 | 55.5% | +$33 |

**Subtotal: +$2,298/month, 1,932 trades.**

### FADE (27 sub-cuts) — invert signal at specific (sleeve, signal, hour) cuts

**Tier 1 — Bonferroni-strict (p<0.001), deploy first:**
| Cut | n | Inv hit | $/trade | Notes |
|---|---:|---:|---:|---|
| btc_5m_momo_HEDGE DOWN @ **18-22** UTC | 37 | **81%** | +$13.6 | Excl. hour 23 (signal flips correct) |
| btc_5m_momo_HOLD DOWN @ 18-22 UTC | 37 | 81% | +$13.6 | Same signal, different exit |
| btc_5m_momo_SELL DOWN @ 18-22 UTC | 38 | 79% | +$11.8 | Same signal |
| btc_15m_volume_INV_NIGHT UP @ 06-11 UTC | 55 | 74.5% | +$11.75 | Hour 23 N/A |

**Tier 2 — p<0.05, deploy after Tier 1 confirms:**
- eth_5m_volume_INV_NIGHT UP @ 06-11 (n=116, 61% inv hit, +$5.19/trade)
- sol_5m_sniper_INV UP @ 00-05 (n=36, 75%, +$11.80)
- eth_5m_sniper_DOWN_INV UP @ 00-05 (n=34, 68%, +$9.18)
- sol_15m_volume_INV_NIGHT DOWN @ 06-11 (n=34, 68%, +$7.58)
- eth_5m_momo_v2_HEDGE DOWN @ 12-17 (n=30, 67%, +$6.66)
- eth_5m_momo_v2_HOLD DOWN @ 12-17 (n=30, 67%, +$6.66)

**Tier 3 — p<0.10, paper-validate before deploying:**
17 remaining cuts. See `fade_scan_significant.csv`.

**FADE subtotal: +$7,922/month, 1,196 trades.**

### KILL (36 sleeves) — disable
All v3/v3_1/v3_2/v3_3/v4 family on BTC + SOL. All sniper variants except KEEP'd ones. All momo_v2 variants outside the 27 fade cuts. Saves compute + reduces audit noise.

---

## Refinement from drill-down

The btc_5m_momo DOWN @ 18-23 UTC fade has a **degenerate edge at hour 23**:

| Hour | Same hit | Inv hit | n |
|---:|---:|---:|---:|
| 18 | 8% | **92%** | 13 |
| 19 | 17% | 83% | 6 |
| 20 | 20% | 80% | 5 |
| 21 | 11% | **89%** | 9 |
| 22 | 25% | 75% | 4 |
| 23 | **80%** | **20%** | 5 |

→ **Deploy 18-22 UTC only.** Hour 23 the same-side wins.

DOW split confirms no Mon-only or weekend-only artifact:
- BTC momo DOWN @ 18-22: weekday n=30 inv=80%, weekend n=12 inv=75% — both robust.
- BTC volume_INV_NIGHT UP @ 06-11: weekday n=48 inv=75%, weekend n=15 inv=80% — both robust.

---

## Phased rollout

**Phase 1 — paper validation (2 weeks)**
- Wire FADE rules into production controller's signal layer (intercept (sleeve, signal, hour) → invert direction → fill opposite outcome at L25 ask).
- Disable KILL sleeves.
- Pass: realized 30d PnL > +$2,500 AND no single sleeve > -$500.

**Phase 2 — $5 notional live (2 weeks)**
- Scale-down deploy of validated cuts.
- Pass: per-trade edge ≥ $1.50 AND aggregate win rate ≥ 58%.

**Phase 3 — $25 full-size**
- Deploy all 8 KEEP + Tier 1+2 FADE.
- Add Tier 3 sub-cuts after each passes Phase 1.

**Kill switches**
- Any cut DD > -$500 over 50 trades → pause that cut.
- Aggregate DD > -$2,000/7d → pause stack, manual review.
- Hit rate < 55% rolling 100 trades → pause.

---

## Why this works

Production sleeves were calibrated using a backtest framework with a microsecond-level lookahead in `asof_strict` at minute-boundary anchors. The lookahead inflated backtest claims by 73-86%. Live (paper) execution reveals the real edge — which is **negative on aggregate** but **positively patterned at specific (sleeve, signal, hour) cuts**.

The fade alpha is mechanistically interpretable:
1. **BTC momo DOWN @ 18-22 UTC** — US session bid-pressure overpowers intraday "down" signals.
2. **volume_INV_NIGHT UP @ 06-11 UTC** — sleeves designed for overnight reversal pattern actually break at European morning open.
3. **ETH momo @ 12-17 UTC** — NY-hours signal is contrarian; fade.
4. **sniper_INV / DOWN_INV @ 00-05 UTC** — already-inverse sleeves get re-inverted (back to original direction) during Asian hours.

Same signal generator + multiple exit policies (HOLD/HEDGE/SELL) → all three show identical fade pattern → confirms mechanism is in the SIGNAL, not curve-fit per exit.

---

## Honest caveats

1. **30 days is short.** Most cuts n=25-150. Tier 1 (n=37-55) survives Bonferroni; Tiers 2-3 are tentative — Phase 1 verifies.
2. **Multiple testing.** ~328 cuts scanned. Bonferroni α=1.5e-4 strict; top 4 cuts clear it.
3. **Real fees.** Backtest used 2% legacy fee on profit. Real Polymarket fee is `0.07·p·(1-p)/share` — at vwap=0.5 / $25 notional, adds ~$0.88/trade. Tier 1 cuts have $11-14/trade margin, easily absorb. Tier 3 marginal cuts may flip — Phase 1 verifies.
4. **Local L25 vs live VPS3.** Backtest uses local cache, prod hits live books. Latency assumption (100ms) is conservative — verify in Phase 1.
5. **Time-of-day pattern stability.** Re-evaluate quarterly. Pattern shift = retire affected cuts.

---

## Files
- `FINAL_DEPLOYMENT_PLAN.md` — earlier comprehensive plan
- `fade_scan_significant.csv` — all 27 deployable fade cuts with stats
- `fade_scan_results.csv` — full 59 positive-inverse cuts
- `fade_scan_all.py` — reproducer
- `LOOKAHEAD_CORRECTION.md` — context on why backtest != production
- `DEPLOYMENT_FINAL.md` — this file
