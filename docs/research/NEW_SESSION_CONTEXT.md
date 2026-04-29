# Research Context — Handoff for Next Session

**Status as of this handoff:** V52 champion is being implemented by the engineering agent and will start paper-trading at small size on Hyperliquid. The strategy is locked. **The next session is NOT about modifying V52 — it's about finding NEW strategies that complement or eventually replace it.**

---

## 1. Mission for the next session

**Find more aggressive strategies with better WR and CAGR than V52, especially regime-aware variants that adapt to bull / bear / sideline markets.**

Specific objectives:
1. Build a **3-regime market classifier** (Bull / Bear / Sideline) — different from the volatility-based 5-regime HMM in V52
2. Design strategies that **switch behavior** based on regime (e.g., trend-follow in bull, fade in bear, fade-extremes in sideline)
3. Target **higher WR** (>50% blended) and **higher CAGR** (>50% annualized) while keeping MDD < 15%
4. Test **leverage scaling** by regime (V52 deliberately doesn't do this; we have research showing why — but worth re-testing with directional regimes vs vol regimes)
5. Explore **new signal families** we haven't touched: pairs trading, on-chain flows, options-implied vol, cross-coin spread strategies

**Constraint:** V52 will already be running with small capital. New strategies must be **additive** (different sub-account, different signal stream, low correlation to V52), not replacements.

---

## 2. Where V52 is right now (do NOT modify)

**V52 CHAMPION = 60% V41 base + 4 diversifier sleeves at 10% each**

| Sleeve | Symbol | Signal | Exit | Weight (of V52) |
|---|---|---|---|---:|
| CCI_ETH | ETH | sig_cci_extreme (V30) | V41 regime-adaptive | 60% × invvol(P3) + 60% × eqw(P5) — appears twice |
| STF_AVAX | AVAX | sig_supertrend_flip + volume filter (V45) | V41 regime-adaptive | 60% × invvol(P3) |
| STF_SOL | SOL | sig_supertrend_flip (V30) | canonical EXIT_4H | 60% × invvol(P3) + 60% × eqw(P5) |
| LATBB_AVAX | AVAX | sig_lateral_bb_fade (V29) | canonical EXIT_4H | 60% × eqw(P5) |
| MFI_SOL | SOL | sig_mfi_extreme 25/75 (V50) | V41 regime-adaptive | 10% |
| VP_LINK | LINK | sig_volume_profile_rot 60-bar (V50) | canonical EXIT_4H | 10% |
| SVD_AVAX | AVAX | sig_signed_vol_div (V50) | canonical EXIT_4H | 10% |
| MFI_ETH | ETH | sig_mfi_extreme 25/75 (V50) | canonical EXIT_4H | 10% |

**Validated metrics on Hyperliquid (2024-01-12 → 2026-04-25, with funding):**
- Sharpe **2.52** · CAGR **+31.4%** · MDD **−5.8%** · Calmar **5.42**
- 9/10 gates pass (Gate 3 Calmar lower-CI 0.987 — near-miss, sample-size artifact)
- Permutation p=0.0000 (real Sharpe 15× null 99th percentile)
- Forward 1y MC: P(neg year)=1.1%, P(DD>20%)=0%

**Deployment artifacts:**
- `docs/deployment/V52_CHAMPION_IMPLEMENTATION_SPEC.md` — full strategy spec
- `docs/deployment/V52_HYPERLIQUID_DEPLOYMENT_NOTES.md` — HL deployment numbers
- `tests/v52_fixtures/` — parity test bundle (engineer regression-tests against this)

---

## 3. Mission trajectory so far (~24 studies, condensed)

**Studies 1-17:** built the simulator, tested 50+ individual strategies, found ~10 promotion-grade single-coin sleeves
**Study 18 (NEW_60_40 EQW):** baseline blended portfolio — Sharpe 2.24
**Study 19 (leverage):** added inverse-vol weighting + BTC defensive gate — Sharpe 2.25, but learned that explicit leverage scaling at sleeve level HURTS the blend
**Study 20 (V40 regime-adaptive entries):** tried CCI/ST/switcher with regime-conditional ENTRIES — failed; entries shouldn't be regime-filtered
**Study 21 (V41 regime-adaptive exits):** **breakthrough** — keep V30 entries, swap to regime-conditional EXITS (LowVol → loose, HighVol → tight). Sharpe 2.42
**Study 22 (V41 expansion scan):** tested V41 across 6 coins × 5 strategies × 3 exits (90 runs) — only 2 useful diversifiers, blend already near-optimal
**Study 23 (V52 multi-stack):** **biggest breakthrough** — 4 new signal families (MFI, Volume Profile, Signed Volume Divergence, etc.) layered at 10% each, all uncorrelated with V41 (ρ < 0.1), Sharpe jumped to **3.04**
**Study 24 (HL native validation):** re-ran on HL data with funding, Sharpe 2.52 (window-shortening haircut), 9/10 gates pass

---

## 4. Codebase landscape — where to find things

### Data
```
data/binance/parquet/<COIN>USDT/<TF>.parquet     # 5-6 years of Binance OHLCV
data/hyperliquid/parquet/<COIN>/{4h,1d}.parquet  # 2.3y 4h + 5+y daily
data/hyperliquid/funding/<COIN>_funding.parquet   # hourly funding history
```

Loaders:
- `strategy_lab/engine.py::load(symbol, tf, start, end)` — Binance loader
- `strategy_lab/util/hl_data.py::load_hl(symbol, tf, ...)` — Hyperliquid loader
- `strategy_lab/util/hl_data.py::funding_per_4h_bar(symbol, index)` — funding aggregator

### Simulators (canonical contract: `(trades_list, equity_series)`)
- `strategy_lab/eval/perps_simulator.py::simulate()` — canonical (next-bar fills, 2-bar cooldown, ATR-trail ratchet)
- `strategy_lab/eval/perps_simulator_adaptive_exit.py::simulate_adaptive_exit()` — V41 regime-adaptive exits
- `strategy_lab/eval/perps_simulator_tp12.py::simulate_tp12()` — TP1/TP2 partial exits (50% out at TP1, rest trails to TP2)
- `strategy_lab/eval/perps_simulator_funding.py::simulate_with_funding()` — funding-aware variant

### Signal library
- `strategy_lab/run_v30_creative.py` — sig_cci_extreme, sig_supertrend_flip, sig_vwap_zfade
- `strategy_lab/run_v29_regime.py` — sig_lateral_bb_fade
- `strategy_lab/run_v23_*` and `run_v22_*` — BB breakout variants
- `strategy_lab/run_v25_*` — TGMT, HTFD, KAMA, etc.
- `strategy_lab/strategies/v50_new_signals.py` — sig_mfi_extreme, sig_vwap_band_fade, sig_volume_profile_rot, sig_signed_vol_div
- `strategy_lab/strategies/adaptive/v40_regime_adaptive.py` — failed regime-entry experiments (kept for reference)

### Regime classifier
- `strategy_lab/regime/hmm_adaptive.py` — GaussianMixture-based, K∈{3,4,5} BIC-selected, **VOLATILITY-only** features (log_r, rvol, vol_ratio, hl_range_pct), forward-only no-look-ahead

**This classifier does NOT distinguish bull/bear/sideline — it only sorts regimes by volatility level.** That's a known limitation and is one of the things to fix in the next session.

### Validation framework (10-gate battery)
- `strategy_lab/eval/robustness.py` — bootstrap CIs, walk-forward, permutation, plateau
- `strategy_lab/run_leverage_audit.py::verdict_8gate()` — gates 1-6 (per-year, bootstrap, walk-forward)
- `strategy_lab/run_leverage_gates78.py` — gates 7-8 (asset-level permutation, plateau sweeps)
- `strategy_lab/run_leverage_gates910.py` — gates 9-10 (path-shuffle MC, forward 1y MC)

### Scan/research scripts (templates to copy/modify)
- `strategy_lab/run_v50_new_signals.py` — multi-coin × multi-strategy × multi-exit scan
- `strategy_lab/run_v51_refine.py` — parameter refinement + correlation-vs-champion analysis
- `strategy_lab/run_v52_multistack.py` — multi-layer diversifier blending
- `strategy_lab/run_v52_hl_gates.py` — full 10-gate battery on a candidate

### Documents
```
docs/research/
  18_PORTFOLIO_FINAL.md       # study 18
  19_LEVERAGE_STUDY.md        # study 19
  20_V40_ADAPTIVE_STUDY.md    # study 20 (failed entry-regime experiments)
  21_V41_CHAMPION.md          # study 21 (V41 breakthrough)
  22_V41_EXPANSION.md         # study 22
  23_V52_CHAMPION.md          # study 23
  NEW_SESSION_CONTEXT.md      # this document
docs/deployment/
  V52_CHAMPION_IMPLEMENTATION_SPEC.md
  V52_HYPERLIQUID_DEPLOYMENT_NOTES.md
```

---

## 5. Validated learnings (KEEP, do not re-test)

1. **Regime info belongs in EXITS, not entries.** Filtering entries by regime makes signals less common, doesn't make them better. Adapting EXIT stack (TP/SL/trail) per regime is where the alpha is.
2. **Inverse-volatility blending beats EQW** by ~1pp Sharpe with no return cost. Use 500-bar rolling window.
3. **Stacking uncorrelated positive-Sharpe streams is the highest-leverage gain.** 4 streams at 10% each with ρ<0.1 produced +0.6 Sharpe lift on top of the V41 base.
4. **TP1/TP2 boosts WR dramatically** (33-48% → 64-84%) at the cost of CAGR. Useful for psychological stability or when blended with high-CAGR sleeves.
5. **Volume-based signals don't transfer cleanly between Binance and HL** (return corr 0.999 but volume corr 0.5-0.7). MFI/VP/SVD will fire at different bars on each venue.
6. **Funding cost is small (~0.4pp/yr)** at current HL rate environment. Per-bar accrual is correct method.
7. **Bootstrap Calmar lower-CI > 1.0 is THE binding gate** for promotion. Most baselines fail it; V52 passed by stacking diversifiers (1.10 vs 0.94 for baselines).

## 6. Anti-knowledge (FAILED — don't repeat without new approach)

1. ❌ **Regime-conditional CCI thresholds** (V40): widening CCI bands in HighVol → fewer good signals.
2. ❌ **Regime-switcher (CCI in LowVol, ST in MedVol)** (V40): exits don't fit the trade shape; mean-reversion trades with trend-tuned EXIT_4H gave back too quickly.
3. ❌ **Per-sleeve leverage scaling by regime** (V19 Exp 3): improves per-sleeve Sharpe but HURTS blend due to correlated-DD amplification across sleeves in same regime.
4. ❌ **Raising leverage_cap alone**: dead parameter at 4h crypto with 3% risk per trade; sizing rarely hits cap. Must scale risk_per_trade.
5. ❌ **Multi-TF confirmation (4h signal + 1h trend agreement)** for CCI: zero trades fire because 1h trend rarely agrees with CCI extreme signal.
6. ❌ **Naive concat of all "winning" sleeves into a portfolio**: 7/9 single-sleeve "winners" HURT the blend because they're correlated with existing sleeves.
7. ❌ **Volatility-only regime classification (current HMM)** can't distinguish a bull-trending HighVol from a bear-trending HighVol. Both look the same to V41 exits.

## 7. Performance bar to beat

V52 on HL (the deployed strategy): **Sharpe 2.52, CAGR +31.4%, MDD −5.8%, Calmar 5.42**

For a NEW strategy to be worth deploying as an additive sleeve, it needs at least:
- Standalone Sharpe > 0.8 (otherwise it's noise)
- Correlation with V52 < 0.2 (otherwise no diversification benefit)
- Pos_yrs ≥ 4/4 on HL data (or equivalent fraction on Binance)
- 6+ tests pass on the 10-gate battery

For it to **REPLACE** V52, it needs:
- Sharpe > 3.0 with full 10/10 gates passing
- AND beat V52 on at least 3 of 4 (Sharpe, CAGR, MDD, Calmar)

---

## 8. Specific research vectors for the next session

Ranked by expected value of information:

### Vector 1 (HIGH PRIORITY): **Directional regime classifier (Bull/Bear/Sideline)**
The current HMM only detects volatility levels. A directional regime classifier would let strategies say "I'm long-only in bull regime, fade-only in bear, range-trade in sideline." Possible features:
- Long-term trend slope (EMA200 slope, normalized by ATR)
- Higher-highs / lower-lows count
- Drawdown-from-peak (bear if > 15% off ATH)
- Realized return over rolling 60-day window
- BTC dominance changes (proxy for alt-bull / risk-off)

Test: build it, see if V52's existing signals perform differently in each regime, design entry/exit/sizing variations.

### Vector 2 (HIGH): **Leverage scaling by directional regime**
Study 19 showed VOL-regime leverage scaling hurts the blend. But that was vol-regime. Try DIRECTIONAL-regime scaling:
- Bull regime: 1.5× size on long signals, 0.5× on shorts (asymmetric leverage)
- Bear regime: 0.5× longs, 1.5× shorts
- Sideline: standard

Hypothesis: directional asymmetry doesn't suffer from correlated-DD amplification because shorts and longs are anti-correlated by construction.

### Vector 3 (MEDIUM-HIGH): **Pairs / spread strategies (NEW signal family)**
Cross-coin cointegration: ETH/BTC ratio, SOL/AVAX ratio, etc. When the spread reverts to mean, take counter-trade. Inherently uncorrelated with directional crypto signals.
- ETH/BTC z-score reversion
- SOL vs sector basket (AVAX+SOL+LINK average) z-score
- Dollar-neutral: long X, short Y, market-direction-agnostic

### Vector 4 (MEDIUM): **Funding-rate signal**
Hyperliquid funding spikes are often regime markers. Possible signals:
- Funding > +0.005%/hr (extreme positive) → fade longs (longs paying to be long = euphoria)
- Funding < −0.003%/hr → fade shorts
- Cross-coin funding divergence (BTC high, ETH low → sector rotation)

Have the data; haven't built signals on it yet.

### Vector 5 (MEDIUM): **TWAP/anchored-VWAP exits, not just entries**
We have V41 (regime exits), V47 (breakeven SL), TP1/TP2. Haven't tried:
- TWAP exit: scale out over N bars instead of single fill
- Anchored VWAP target: exit when price reaches VWAP from a key anchor point
- Time-of-day exits (crypto has weekend liquidity differences — Mon/Fri exit windows)

### Vector 6 (LOW-MEDIUM): **More signal families** (research findings already in study 23)
- Keltner Channel breakout (like BB but ATR-based — different volatility model)
- Ichimoku Cloud
- Money Flow + ADX combined
- Stochastic RSI divergence
- Donchian channel breakout (Turtle revival)
- Heikin-Ashi smoothed entry

### Vector 7 (LONG-TERM): **Daily timeframe**
HL has 5+ years of daily data. We've only run 4h. Daily strategies would have:
- 6× fewer trades → much lower fees/slippage cost
- Different statistical structure (less noise, slower regime shifts)
- Potential to add as a third sub-account fully uncorrelated with 4h sleeves

### Vector 8 (LONG-TERM): **More coins**
Currently using ETH, AVAX, SOL, LINK (+ BTC for regime only). HL has 100+ perp markets. Top candidates by liquidity:
- BTC (only used for regime so far — could be a sleeve directly)
- ARB, OP (L2 ecosystem)
- HYPE (HL's own token, listed on HL itself)
- SEI, INJ, TIA (alt-L1s)
- DOGE, SHIB, PEPE (memecoins — different volatility profile)

### Vector 9 (LONG-TERM): **On-chain features**
Active addresses, exchange netflow, open interest delta, liquidation cascades. These are slow-moving (daily) but could be regime indicators. Requires additional data ingestion (Glassnode, Coinglass APIs).

---

## 9. Quickstart for next session

To pick up where this session left off:

```python
# Standard imports — put these at the top of any new research script
import sys
from pathlib import Path
REPO = Path("/c/Users/alexandre bandarra/Desktop/global")
sys.path.insert(0, str(REPO))

from strategy_lab.engine import load as load_binance
from strategy_lab.util.hl_data import load_hl, funding_per_4h_bar
from strategy_lab.eval.perps_simulator import simulate as sim_canonical, atr
from strategy_lab.eval.perps_simulator_adaptive_exit import simulate_adaptive_exit, REGIME_EXITS_4H
from strategy_lab.eval.perps_simulator_funding import simulate_with_funding
from strategy_lab.regime.hmm_adaptive import fit_regime_model
from strategy_lab.run_leverage_audit import eqw_blend, invvol_blend, verdict_8gate
from strategy_lab.run_leverage_gates910 import gate9_path_shuffle, gate10_forward_paths

# Standard exit profiles
EXIT_4H = dict(tp_atr=10.0, sl_atr=2.0, trail_atr=6.0, max_hold=60)
TP12_4H = dict(tp1_atr=3.0, tp2_atr=10.0, tp1_frac=0.5,
               sl_atr=2.0, trail_atr=6.0, tight_trail_atr=2.5, max_hold=60)
```

To benchmark a new strategy against V52:
```python
# Load the V52 reference equity for correlation analysis
import json
ref = json.loads((REPO / "docs/research/phase5_results/v52_hl_champion_audit.json").read_text())
# Or rebuild it from scratch using strategy_lab/run_v52_hl_gates.py::build_v52_hl()
```

---

## 10. Specific commands to start the new session

Suggested first actions:

1. **Build the directional regime classifier** (Vector 1 above) — single most valuable deliverable. Output: `strategy_lab/regime/directional_regime.py` + a study showing the regime distribution on BTC over 5 years.

2. **Re-run V52 BUT with the new directional regime classifier replacing the vol-only HMM** — see if labels (Bull/Bear/Sideline) improve V41 exit selection vs current (LowVol/MedVol/HighVol).

3. **Test asymmetric leverage** (Vector 2) on a single sleeve (CCI_ETH is good test bed) using directional regime — confirm or refute the hypothesis that directional asymmetry doesn't suffer from correlated-DD.

4. **Build pairs strategy** (Vector 3) on ETH/BTC ratio — measure correlation with V52, target Sharpe > 1.0 standalone.

5. **At each step, run the 10-gate battery before declaring a winner.** The Calmar lower-CI gate is the strictest; design strategies that produce *consistent* returns, not lottery tickets.

---

## 11. Constraints and reminders

- **V52 is sacred.** It's deployed (or about to be). Do NOT change its logic or weights. New strategies are ADDITIVE.
- **V52 will trade with small initial capital** — so the new research has time to find more aggressive complements before V52 scales up.
- **Hyperliquid is the deployment venue.** Backtest on HL data + funding. Binance can be used for longer history but final validation must be on HL.
- **Don't re-run failed experiments.** Anti-knowledge in §6 saves time. If you must revisit, design a NEW twist (e.g., directional regime for leverage, not vol regime).
- **"Higher WR" is achievable but be careful.** TP1/TP2 lifts WR to 70%+ but at CAGR cost. The WR-CAGR tradeoff is real. The user wants BOTH higher WR AND higher CAGR — that requires either better signal quality or anti-correlated streams (V52 path), not just exit tweaks.
- **Bootstrap Calmar CI is the killer gate.** A point Sharpe of 3 doesn't help if the lower-CI dips to 0.8. Diversification + longer history are the only ways past it.

---

## 12. Glossary (for the next session)

| Term | Meaning |
|---|---|
| V30 | Original V30 sigma family (CCI Extreme, SuperTrend Flip, VWAP Z-Fade) |
| V41 | Regime-adaptive EXIT stack (study 21 breakthrough) |
| V52 | Currently deployed — V41 base + 4 new diversifiers |
| EXIT_4H | Canonical static exit (tp=10, sl=2, trail=6, hold=60) |
| Sharpe lower-CI | 2.5th percentile of bootstrap distribution |
| 10-gate battery | Standard validation: per-year, bootstrap CIs, walk-forward, permutation, plateau, MC |
| invvol blend | Inverse-volatility weighting (500-bar rolling stdev) |
| eqw blend | Equal-weight blending |
| HMM | Volatility-regime classifier (GaussianMixture under the hood) |
| Promotion-grade | Passes ≥ 8/10 gates |

---

**End of context document.** Next session can read this top-to-bottom and pick up immediately. Suggested first message to next session: "Read `docs/research/NEW_SESSION_CONTEXT.md` and propose a research plan for Vector 1 (directional regime classifier)."
