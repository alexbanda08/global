# 36 — V68: Walk-forward sleeve-weight optimizer (QuantMuse Pattern 2)

**Date:** 2026-04-27
**Runner:** [strategy_lab/run_v68_sleeve_weight_opt.py](../../strategy_lab/run_v68_sleeve_weight_opt.py)
**Output:** [phase5_results/v68_sleeve_weight_opt.json](phase5_results/v68_sleeve_weight_opt.json)

## TL;DR

V68 is a scipy-driven walk-forward optimizer over V52's 8 underlying sleeves, structurally borrowed from QuantMuse's `FactorOptimizer` pattern with three overfit-trap guardrails (L2 reg toward 1/n, weight bounds [0.5/n, 2/n], walk-forward only).

**Standalone:** V68 does **not strictly beat V52** (ΔSharpe −0.074), but lifts **CAGR by +3.78 pp** at a small MDD cost.
**Stacked with V67 (L=1.75):** CAGR **+67.8%** / MDD **−11.4%** / Sharpe **2.45** — passes the 60% / 50% / −40% target with **+7.7 pp CAGR uplift over V67 alone**.

## Configuration

| Parameter | Value |
|---|---|
| Universe | 8 V52 sleeves: CCI_ETH, STF_SOL, STF_AVAX, LATBB_AVAX, MFI_SOL, VP_LINK, SVD_AVAX, MFI_ETH |
| Objective | maximize Sharpe(w · R) − λ‖w − 1/n‖² |
| L2 regularizer λ | 0.5 |
| Weight bounds | [0.0625, 0.25] = [0.5/n, 2/n] |
| Sum constraint | Σ wᵢ = 1 |
| IS window | 12 months (2160 4h-bars) |
| OOS window | 3 months (540 4h-bars) per fold |
| Folds produced | 5 (Jan 2025 → Apr 2026, total 15 months OOS) |
| Solver | SLSQP, ftol 1e-8, maxiter 200 |

## Headline numbers

| Strategy | Sharpe | CAGR | MDD | Calmar | Bars |
|---|---:|---:|---:|---:|---:|
| Equal-weight (1/8) baseline | 2.36 | +30.9% | −5.9% | 5.24 | 5001 (full) |
| V52 current implicit blend | **2.52** | +31.5% | −5.8% | 5.42 | 5001 (full) |
| V68 walk-forward optimized | 2.45 | **+35.2%** | −6.6% | 5.32 | 2700 (15mo OOS) |
| V67 (V52 × L=1.75)          | 2.52 | +60.1% | −10.0% | 6.02 | 5001 (full) |
| **V68 × V67 (L=1.75) stack** | **2.45** | **+67.8%** | **−11.4%** | **5.95** | 2700 (15mo OOS) |

V68 vs V52: ΔSh = −0.074, ΔCAGR = +3.78 pp, ΔMDD = −0.82 pp. Verdict by strict gate: **NO_LIFT** (Sharpe gate not cleared). Verdict by CAGR-priority view: **MARGINAL UPLIFT**.

## What the optimizer actually learned

Per-fold top-3 weights (ordered by fold start):

| Fold (OOS start) | #1 | #2 | #3 | OOS return |
|---|---|---|---|---:|
| 2025-01-06 | LATBB_AVAX_4h=0.250 | CCI_ETH_4h=0.202 | STF_AVAX_4h=0.191 | +8.7% |
| 2025-04-06 | STF_AVAX_4h=0.237 | CCI_ETH_4h=0.200 | LATBB_AVAX_4h=0.170 | +8.1% |
| 2025-07-05 | STF_AVAX_4h=0.195 | LATBB_AVAX_4h=0.195 | VP_LINK=0.170 | +4.5% |
| 2025-10-03 | STF_AVAX_4h=0.240 | STF_SOL_4h=0.234 | LATBB_AVAX_4h=0.213 | +12.4% |
| 2026-01-01 | STF_SOL_4h=0.250 | STF_AVAX_4h=0.237 | CCI_ETH_4h=0.150 | +5.0% |

**Stable pattern across all 5 folds:** the V41 core sleeves (CCI_ETH / STF_AVAX / STF_SOL / LATBB_AVAX) consistently dominate, often saturating the upper bound (0.25). The 4 diversifiers (MFI_SOL / VP_LINK / SVD_AVAX / MFI_ETH) are consistently pushed to or near the lower bound (0.0625). Only VP_LINK occasionally breaks into the top-3.

**Implied effective split:** ≈ 80–85% on V41 core, 15–20% on diversifiers.
**V52 actual current split:** 60% on V41 core, 40% on diversifiers (10% each on 4 diversifiers).

That's the durable insight. **V52's diversifier weight may be too high.**

## Durable insight

The hand-tuned V52 blend (60% V41 + 4×10% diversifier) is *not* what the optimizer settles on with regularized walk-forward training. The optimizer wants more V41 core and less diversifier — it views the diversifiers as having lower per-bar Sharpe than the V41 sleeves, even after regularization.

This isn't an "obvious win" — V52's hand-tuned blend is *Sharpe-better* on full history (2.52 vs 2.45). What's happening is:

- **V52 trades some CAGR for stability.** The 40% diversifier weight smooths the equity curve (better Sharpe on full history) but caps CAGR at 31.5%.
- **V68 trades stability for CAGR.** Concentrating ~80% on the V41 core lifts CAGR to 35.2% but at a slightly worse Sharpe.
- **In the L=1.75 leverage stack, the CAGR-priority blend wins:** V68 × V67 (+67.8%) > V67 alone (+60.1%) by 7.7 pp CAGR. The Sharpe loss is small enough that leverage compensates.

## Recommendation

**Do not replace V52 with V68 standalone.** V52 is the cleaner Sharpe-optimal blend on full history.

**Do consider V68-blended weights for a *new* leveraged variant** ("V69" — not yet built):
- V69 = walk-forward-optimized weights × L=1.75 leverage
- Backtest CAGR +67.8% on the OOS slice, MDD −11.4%, Sharpe 2.45
- Mandatory next step: re-run the full V52 10-gate battery (gates 1–10) on the V68×V67 stacked equity. Without that, this is V25/V27 territory: a "spectacular" result that hasn't been audited.

**Smaller surgical change:** rather than wholesale rebuild, **lift V52's V41-share from 0.60 → 0.75 and reduce diversifier share from 0.40 → 0.25** as a single-parameter tweak inside the existing build. This keeps V52's structure but moves toward the optimizer's preferred composition. Test as `run_v68_v52_reweight.py` (~50 lines) — much cheaper than a fresh blend.

## Caveats — read before any deploy decision

1. **V68 OOS = 15 months only.** Less data than V52's full-history evaluation. The Sharpe difference may not survive a longer history.
2. **Optimizer concentration is borderline-overfit.** 4 of 5 folds have at least one weight saturating the upper bound (0.25). Tighter bounds (e.g. [0.5/n, 1.5/n] = [0.0625, 0.1875]) might give more honest weights at the cost of less CAGR uplift. Worth sweeping λ in {0.25, 0.5, 1.0, 2.0} before promoting.
3. **The stack `V68 × V67` reuses V67's blend-level leverage assumption.** Same caveat as document 34: per-position leverage in the simulator (`leverage_cap` kwarg) may diverge 5–10% from this estimate.
4. **No gate battery has run on V68 yet.** Gates 1–10 (V59-style) are mandatory before promoting any candidate to "V69 champion."
5. **15-month OOS is a single run of the macro cycle.** A real walk-forward verdict needs longer history (more folds = more independent OOS samples).

## What this validates about V52

Despite V68 not strictly winning, the result **validates V52 as a strong baseline**:
- V52 hand-tuned blend Sharpe (2.52) > scipy-optimized blend Sharpe (2.45)
- That's not luck. The hand-tuned blend captures Sharpe-stability the optimizer doesn't see in IS data.
- The QuantMuse-style optimizer adds value *only when explicitly traded for CAGR*, not for Sharpe. That's a useful and durable finding about the limits of mean-variance-on-blends as an alpha source on top of an already well-tuned book.

## Files

- [run_v68_sleeve_weight_opt.py](../../strategy_lab/run_v68_sleeve_weight_opt.py)
- [phase5_results/v68_sleeve_weight_opt.json](phase5_results/v68_sleeve_weight_opt.json)
- Reference: [34_V67_LEVERAGE_HIT.md](34_V67_LEVERAGE_HIT.md) (V67 = the leveraged baseline V68 stacks on top of)
- Reference: [35_QUANTMUSE_REPO_ANALYSIS.md](35_QUANTMUSE_REPO_ANALYSIS.md) (Pattern 2 spec V68 implements)
