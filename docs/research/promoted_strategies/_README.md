# Promoted Strategies — strategies that worked

Strategies that **passed promotion gates** and either became champions, are
running in production, or are deployment-ready candidates. Read in numeric
order to follow the champion lineage.

## Champion lineage at a glance

```
V41 (21,22) ──► V52 (23) ──► V63 leveraged (32) ──► V64 simulator-confirmed (33,34)
                                                          │
                                                          ▼
                                  V67 (34_V67) ──► V52* α=0.75 (37) ──► V69 (38, 39)
                                                                          ▲
                                                                          └── current candidate
```

## Files (in lineage order)

### V41 line — first regime-adaptive champion
- **18_PORTFOLIO_FINAL.md** — final 7/8 portfolio comparison; one Calmar-CI gate failure surfaced, fixed by leverage in next doc.
- **19_LEVERAGE_STUDY.md** — leverage study; **NEW 60/40 V41** is the only candidate that passes all 6 testable gates after blending two leverage techniques.
- **21_V41_CHAMPION.md** — V41 regime-adaptive exit champion.
- **22_V41_EXPANSION.md** — V41 expansion scan; champion holds (`NEW_60_40_V41`).

### V52 — multi-signal champion
- **23_V52_CHAMPION.md** — V52 multi-signal champion (Sharpe 3.04, CAGR +42.7%, MDD −7.4%, 8 sleeves: CCI, STF, LATBB, MFI, VP, SVD, etc.).
- **24_DIRECTIONAL_REGIME.md** — directional regime classifier (Bull/Bear/Sideline). PROMOTE for use as exit/sizing modifier; do NOT use as entry filter.

### V63/V64 — first leveraged champion (target: CAGR ≥ 50%, MDD ≤ 20%)
- **32_V63_LEVERAGED_CHAMPION.md** — V63 = V52 at portfolio leverage L=1.75. **TARGET HIT.** Passes 9 gates including the previously-failing Gate 3 (Calmar lower-CI).
- **33_V64_SIMULATOR_CONFIRMATION.md** — V64 = V63 confirmed at simulator level (`risk=0.0525, leverage_cap=4.0`). Returns within prediction.
- **34_V64_DASHBOARD.md** — V64 strategy dashboard.

### V67/V68b/V69 — current candidate (target: CAGR ≥ 60%, WR ≥ 50%, MDD ≥ −40%)
- **34_V67_LEVERAGE_HIT.md** — V67 = V52 × L=1.75 blend-level. CAGR +60.1%, MDD −10.0%, WR_d 50.4%. First hit of the new 60%/50% target.
- **37_V68B_V41_RESHARE_WIN.md** — V52* with α=0.75 V41-share (vs V52's 0.60). Sharpe 2.64 (+0.12 vs V52), CAGR +33.3% standalone. Surgical single-parameter win sourced from QuantMuse FactorOptimizer pattern.
- **38_V68B_GATES_PROMOTED.md** — full 10-gate battery on V52* × L=1.75. **9/9 gates PASS**, Calmar lower-CI +0.142 over V52. **V69 promoted** as champion candidate.
- **39_V69_PER_POSITION_LEVERAGE.md** — V69 per-position validation (size_mult=1.75 inside simulator). Divergence ≤ 4.5% vs blend-level estimate. **Production headline: Sh 2.61 / CAGR +61.1% / MDD −12.4% / WR_d 50.4%.**

## Current production candidate

**V69 = V52* (α = 0.75, 8 sleeves: V41 core + 4 diversifiers) × per-position L=1.75.**
- Backtest: Sh 2.61, CAGR +61.1%, MDD −12.4%, WR_d 50.4%, Calmar 4.92.
- Live MDD planning (1.5× backtest): −18.6%; still inside −40% mission cap.
- All 9 gates pass; per-position validated; production headline locked.

## What still owes before live capital

1. V64 → V69 deployment plan amendment (use the 12-week staged migration template).
2. Hyperliquid testnet dry-run to verify position-sizing math.
3. ≥ 4 weeks paper-trade with kill-switch (Sh ≥ 1.32 = 0.5 × backtest 2.64 sustained 30 days).

## Stage-2 candidates (paper-trade A/B at next iteration)

- `drop_MFI_ETH` variant (α = 0.8125): tested in [rejected_strategies/40_V68C_DROP_DIVERSIFIERS.md](../rejected_strategies/40_V68C_DROP_DIVERSIFIERS.md). +0.04 Sharpe / +3.8 pp CAGR vs V69 baseline; within statistical noise on 27mo sample. Worth A/B testing live before promoting to V70.
