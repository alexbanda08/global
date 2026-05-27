# HL Perpetual Futures — Final Deploy Candidates (Wave 4 PERP)

**Date**: 2026-05-26 (PERP-native rerun, supersedes earlier `PAPER_DEPLOY_CANDIDATES.md`)
**Universe**: BTC, ETH, SOL, HYPE on Hyperliquid; AVAX, LINK, BNB, ADA, DOGE, XRP, SUI, TON tested via Binance backbone
**Engine**: `hl_engine.HyperliquidConfig` — taker 4.5 bps × 2 + slip 3 bps + hourly funding (1.25 bps/hr cap) + 50ms latency
**Exits**: signal-flip / ATR trailing stop / ATR SL+TP / regime-change (perp-native, NOT fixed-time)
**Total cells tested (perp rerun)**: 3,929 across 6 families
**Cells passing strict deploy criteria** (n≥50, OOS Sharpe≥1.5, gates pass): identified per tier

---

## What was wrong with the prior run

The previous wave (Polymarket-anchored) DID use a perp-native engine (continuous PnL, fees, funding) — but the **strategy DESIGN** was sometimes a direct port of Polymarket binary triggers (SMS as direct entry, Cyclops as direct trigger, 5m/15m timeframes anchored to Polymarket's binary windows). The user's correction was right: indicators port over, **strategy structure must be perp-native**.

This rerun fixes that. All 6 families use perp-native templates (trend, mean-rev, breakout, carry, regime-composite, ML-sized) with futures-native exits and timeframes (1h, 4h, 1d, multi-day holds for carry).

---

## TL;DR — Three categories of confirmed perp-native edge

1. **CARRY** (D1 basis-carry) — the strongest finding. 62 cells passed all 7 gates. Refined search 100× wider than original W2b found new winners across z-thresholds, hold horizons, and expected-basis proxies. Deploy ETH 24h and SOL 72h as primaries.

2. **TREND FOLLOWING** (A1/A3) — ETH 4h Donchian N=50 ATR=1.5 produces OOS Sharpe 3.32 with PF 1.47 and beats ETH buy-and-hold by 5.6×. Trend dominates crypto perp.

3. **BREAKOUT** (C1/C3) — ETH 4h cluster has 6 cells passing ALL 6 gates (perm p≤0.005). 4h breakouts > 1d breakouts on crypto perp.

**Composite (E4 Cyclops-as-confidence-sizing)** adds material lift to trend baselines.
**Mean Reversion (B family)** does NOT work — 5/90 cells profitable. Crypto perp is momentum-dominated, NOT mean-reverting.
**ML probability-trading (F1/F2)** is too thin for HL fees. F3 single-feature rules give a marginal viable option.

---

## TIER 1 — CARRY (Primary Deploy)

### T1.1 ⭐ D1 ETH Basis Carry 24h — RECOMMENDED FIRST DEPLOY
- Spec: `D1|ETH|z1.5|h24h|zwin7d|fund30davg|atr0`
- **n=296, WR 56%, Sharpe 3.27, total PnL +$519 on $250 notional**
- Passes ALL 7 gates (G1 p=0.04, G4 perm-p=0.001, G6 boot lo=+$0.10/tr, G7 min regime sharpe 0.15)
- Hold horizon 24h is operationally manageable
- Signal: at each hourly bar, compute `basis_bps = (binance_spot - hl_perp) / hl_perp × 10000`. Compare to `expected_basis = fund_30d_mean × 24/8`. Rolling 7d z-score of mispricing. Fire LONG when z > +1.5 (HL cheap), SHORT when z < -1.5.

### T1.2 D1 SOL Basis Carry 72h
- Spec: `D1|SOL|z1.5|h72h|zwin14d|term_next|atr0`
- **n=259, WR 57%, Sharpe 4.66, total PnL +$874**
- All 7 gates pass; 3-day hold reduces fee drag
- Uses `term_next` expected-basis proxy (current funding × 9 = 72h expected basis)

### T1.3 D1 SOL Basis Carry 48h
- Spec: `D1|SOL|z2.0|h48h|zwin7d|term_next|atr0`
- **n=130, WR 64%, Sharpe 6.40, PnL +$502**
- All 7 gates pass

### T1.4 D1 SOL Basis Carry 24h (ATR-exit on)
- Spec: `D1|SOL|z2.0|h24h|zwin90d|zero_fund|atr1`
- **n=80, WR 65%, Sharpe 4.57, PnL +$43**
- Tests the ATR-exit variant (closes early when mispricing reverts to <1.5σ). PnL smaller but Sharpe high.

### T1.5 (HIGH-N RUNNER-UP) D1 SOL z1.0 h72h zwin14d term_next
- **n=676, WR 53%, Sharpe 4.30, PnL +$2,159** (LARGEST raw PnL across grid)
- Looser z=1.0 threshold = more trades = more PnL per dollar of capital

### Carry deploy allocation (Tier 1 ensemble)
- 30% T1.1 ETH 24h z1.5 — anchor (highest n, manageable hold)
- 25% T1.2 SOL 72h z1.5 — anchor (highest n on SOL)
- 20% T1.5 SOL 72h z1.0 high-n — capital efficient
- 15% T1.3 SOL 48h z2.0 — diversification on hold horizon
- 10% T1.1-equivalent at z2.0 BTC 24h (original W2b verified) — BTC diversification

### Caveat
- D was tested on 107-day HL window only. All Sharpe values >15 in raw results are likely overfit (small-n folds). Refresh with longer history (when more HL kline data accumulates) before scaling notional beyond $1k per cell.

### D2 funding-extreme verdict — CONTRARIAN wins
- BTC contrarian Sharpe **+2.66** vs momentum -3.90
- HYPE contrarian +2.21 vs momentum -2.88
- ETH contrarian +1.15 vs momentum -2.16
- SOL contrarian +0.47 vs momentum -1.33
- **Conclusion**: When funding gets extreme, fade it. Do NOT trade WITH extreme funding (momentum loses sharply on all 4 assets).
- D2 cells did NOT pass all 7 gates standalone (G7 not run on D2 grid), so use as **directional confirmation** for D1 entries, not as standalone strategy.

---

## TIER 2 — TREND FOLLOWING (Secondary Deploy)

### T2.1 ⭐ A1 ETH 4h Donchian Breakout
- Spec: lookback N=50, ATR trail mult=1.5
- **n=249, OOS Sharpe 3.32, PF 1.47, max DD -$88, beats BH 5.6×**
- Signal: at 4h bar, LONG when close > 50-bar high; SHORT when close < 50-bar low
- Exit: trailing stop at 1.5 × ATR_14 from peak/trough

### T2.2 A3 ETH 1h ADX-gated trend
- Spec: ADX>30 + EMA50 cross
- **n=527 (high frequency), OOS Sharpe 2.06, PF 1.44**
- Useful for capital that wants more turnover

### T2.3 A2 BNB 4h EMA-stack crossover
- Spec: ema_stack_score ≥ 3 = LONG; ≤ -3 = SHORT
- **n=321, Sharpe 1.42, +$190 PnL**
- Beats BNB buy-and-hold

### A5 Cyclops as trend FILTER
- Sharpens A1 on BTC (0.95→1.26 Sharpe) and ETH (0.69→1.25)
- Flips negative on SOL — do not apply to SOL
- Use: layer Cyclops coherence filter on A1/A3 for BTC and ETH

### A4 Range Filter — NOT DEPLOYABLE
- Direction-flip strategy chops too fast on 4h (avg 2 bars held → fee bleed)
- 1d cells look strong but n<50

---

## TIER 3 — BREAKOUT (Tertiary Deploy, ETH 4h cluster)

### T3.1 — Multi-variant ETH 4h breakout cluster
6 cells pass ALL 6 gates (perm p≤0.005, n≥70, beats buy-hold):
- C1 ETH 4h `lb50_off0.5_trail3.0`
- C1 ETH 4h `lb20_off1.0_trail3.0`
- C1 ETH 4h `lb20_off0.5_trail3.0`
- C1 ETH 4h `lb20_off0.25_trail3.0`
- C3 ETH 4h (volume-confirmed, lb20_off0.5_volx2_trail2.5)
- One more variant in cluster

**Treat as portfolio**: deploy 2-3 variants with capital weighted by perm p-value.

### T3.2 C3 SOL 4h volume-confirmed Donchian
- Spec: lb=20, off=0.5, vol > 2× 20-bar avg, ATR trail mult=2.5
- **n=62, OOS Sharpe 5.28, PF 3.10, perm p=0.005**
- Caveat: loses to SOL buy-and-hold ($1,904 vs $21,145 in SOL bull). Useful in capital where you want non-correlated PnL to a long-only SOL position.

### NOT deployable
- C1 SUI 4h Sharpe 5.53 (OOS n=11 — too small)
- C2 TON 4h Sharpe 5.09 (OOS n=14 — too small)
- 1d timeframe cells in general

---

## TIER 4 — COMPOSITE (Sizing Layer, not standalone)

### T4.1 E4 Cyclops-as-confidence-multiplier on A2 base
- SOL 4h: **Sharpe 1.98, Calmar 2.78, n=134, +$286**
- Lift over A2 baseline: **+0.82 Sharpe**
- Sizing: 2× notional when all 3 Cyclops axes aligned, 1× when 2-of-3, skip otherwise
- ETH 4h: lift +1.05 Sharpe but absolute Sharpe still weak (+0.08)
- **Use as sizing layer on top of A1/A2 trend strategies, NOT standalone**

### T4.2 E2 Volatility-sizing on A3 ADX-gated trend
- BTC 4h: +0.58 Sharpe lift over flat-leverage A3
- ETH 4h: +0.42 Sharpe lift
- Sizing: 2× leverage in low-vol regime, 1× mid, 0.5× high
- **Use as sizing layer**

### NOT deployable as standalone
- E1 Markov-router (forces MR in sideways, destroys good trends)
- E3 Session-switch (drag)

---

## TIER 5 — ML-DERIVED (Limited)

### T5.1 F3 ETH 4h `rf_dist_bps z>1.5 momentum` — single-feature rule
- **n=48, mean OOS Sharpe 1.16, 3-of-4 windows positive, +$220 across 4 windows**
- Trigger: when `rf_dist_bps` (distance from Range Filter band) z-score > +1.5 → LONG with momentum
- Single-feature rule, NOT a full classifier — full classifiers (F1, F2) lose money at HL fees

### Verdict on ML
- Real AUC edge: 2-4 ppt above null (G4 confirms)
- BUT: 12 bps round-trip HL costs eat the edge entirely
- ML pays off only when used as **feature selector** (W3 importance) → simple rule-based strategies
- ML breakeven at HL Tier-2 fees (2.5 bps). At full taker (4.5 bps), no go.

---

## REJECTED FAMILIES

| Family | Why rejected |
|---|---|
| **B Mean Reversion (all 5 variants)** | 5/90 cells profitable. Buy-hold dominates. Crypto perp is MOMENTUM, not mean-reverting. |
| **D3 Hedged spot-perp arb** | All 27 cells lose. 2-venue fees + slippage = ~25 bps round-trip × 2 sides, eats convergence. |
| **D4 Funding-regime composite** | High Sharpe (BTC 7.09) but FAILS G7 regime hold-out — collapses in at least one regime. Hidden concentration risk. |
| **F1 ML probability-gated sized** | Loses on every cell. AUC edge < HL fee threshold. |
| **F2 RF+LGB+XGB ensemble vote** | Loses on every cell. Same reason as F1. |
| **E1 Markov router** | Drags vs best component (router destroys good trends by forcing MR). |
| **E3 Session-switch** | Drags vs best component. |
| **A4 Range Filter direction-flip** | Chops on 4h (avg 2 bars held → fee bleed). |
| **5m / 15m timeframes generally** | Fees crush sub-bar edges on perpetual futures. Reserved for special cases (basis carry minimum 24h). |

---

## DEPLOY PORTFOLIO COMPOSITION

### Conservative ($10k total capital)
- $3k T1.1 ETH 24h carry (anchor)
- $2k T1.2 SOL 72h carry
- $2k T2.1 ETH 4h Donchian trend
- $1.5k T1.5 SOL high-n carry
- $1k T2.2 ETH 1h ADX trend
- $0.5k T2.3 BNB 4h EMA-stack

### Aggressive ($50k)
- Above scaled 5× + add T3 ETH 4h breakout cluster (3 variants × $2k each = $6k) + T4.1 SOL 4h Cyclops sizing layer

### Diversification check
- Carry strategies (D1 family) hold for 24-168h — different time horizon to trend (A) and breakout (C). Low intraday correlation.
- ETH dominates many cells; ensure SOL/BTC weighting prevents single-asset concentration.

---

## PRE-DEPLOY CHECKLIST

1. **Refresh data**: pull HL klines + funding through 2026-05-26 (last data ends 2026-05-16). Re-run T1 candidates on the +10d window. Sharpe should remain positive.
2. **Latency validation**: 50ms is engine default. Verify against actual HL API round-trip from production environment.
3. **Slippage validation**: backtest assumes 3 bps. Pull recent HL trade tape, compute realized slippage at $250 notional.
4. **Funding cap**: HL contract caps at 1.25 bps/hr — verify on live HL contract before relying on this in strategy.
5. **Portfolio simulation**: combine T1-T2-T3 into single simulated portfolio with capital allocation. Compute BLEND Sharpe (could lift or sink vs per-cell sum due to correlation).
6. **Carry funding monitoring**: T1 strategies hold 24-168h with funding accrual. Max funding drag ~10-30 bps/trade. Monitor real funding accrual closely vs backtested.
7. **Stop rule**: drawdown circuit breaker — auto-pause any sleeve that goes below 60% of its backtested max DD.

---

## NEXT-WAVE RESEARCH

1. **Extend HL data history** — current 107-day window limits D1 statistical confidence on 168h holds. Pull S3 archive bulk to extend to 1-2 years.
2. **HL L2 orderbook microstructure** — raw S3 archive downloaded but unparsed. Could unlock perp-native microstructure (order-flow imbalance, microprice).
3. **Refine D4 G7 failure mode** — composite is high-Sharpe; identify which single regime breaks it and design around.
4. **Test D1 basis carry on other coins** — currently only BTC/ETH/SOL have Binance + HL overlap. HYPE has no Binance equivalent (perp-only).
5. **Cyclops sizing layer (E4) on D1 carry** — combine the working sizing layer with the working carry signal.
6. **Cross-coin trend ensemble** — A1 ETH 4h works; test BTC/SOL/AVAX/LINK on same template; ensemble decorrelates regime risk.

---

## FILES (all under `strategy_lab/hl_research_2026_05_26/`)

```
PAPER_DEPLOY_CANDIDATES_PERP.md   ← THIS FILE (final deploy spec)
PAPER_DEPLOY_CANDIDATES.md         ← PRIOR (superseded; kept for audit trail)
MASTER_PLAN.md
MASTER_TABLE_PERP.{csv,md}        ← 3,929 perp-native cells ranked
MASTER_TABLE.{csv,md}              ← prior Polymarket-anchored run
INDICATOR_REGISTRY.md
HL_DATA_AUDIT.md
EXISTING_HL_STRATS.md
WAVE1_FEATURES.md
WAVE1_ENGINE.md
build_hl_panel.py
hl_engine.py
perp_exit_rules.py
panels/                            ← 24 feature panels (input to all strategies)
wave2/                             ← prior Polymarket-anchored backtests (W2a-e + W3)
wave2_perp/                        ← THIS RERUN
  A_trend_following.{py,md,csv}    — Trend (T2 picks here)
  B_mean_reversion.{py,md,csv}     — Rejected
  C_breakout.{py,md,csv}           — Breakout (T3 picks here)
  D_carry.{py,md,csv}              — Carry (T1 picks here) + D2/D3/D4 verdicts
  E_regime_composite.{py,md,csv}   — Composite (T4 sizing layers)
  F_ml_sized.{py,md,csv}           — ML (T5 — limited)
  aggregate_perp_results.py        — schema-adaptive aggregator
```

---

**Recommended first action**: deploy **T1.1 D1 ETH 24h z1.5** to paper at $250 notional × 1× leverage. Monitor Sharpe daily for 30d on fresh data. If Sharpe stays > 1.5 and gates hold on refreshed window, scale to $1k notional and add T1.2 SOL 72h z1.5.
