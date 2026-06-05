# Oracle-Determinism Settlement Selector — REAL but UNDERPOWERED (deploy to shadow)

**Date:** 2026-06-05 · Experiment 1 from `SLUG_SELECTION_RESEARCH_2026_06_05.md` (top-ranked lead).
**Scripts:** `oracle_settlement_selector_2026_06_05.py` · `oracle_cheap_decided_fill_2026_06_05.py` · `oracle_determinism_eda_2026_06_05.py`
**One line:** Chainlink decides the outcome 30–60s before settle (18% of slugs, 99.6% acc, fidelity 1.0). The
poly price of the oracle-winner LAGS the oracle by ~1.5% (print EV +1.35%/share, CI excludes 0). The edge
concentrates in **cheap-but-decided** slugs (poly winner <0.90–0.95 while oracle says 99%) — and unlike the
favorite-longshot, **it survives fills *directionally*** (filled win 92–100% at vwap ~0.85, +$1.8–4.2/tr). BUT
those slugs are cheap because asks are thin → **fill rate 3–12%, only 9–42 fills/43d, CIs include 0.** Real,
structural, but **underpowered — deploy as a shadow sleeve to accrue power; do not size on current data.**

## Three-gate result
- **STEP 1 — Fidelity: 1.0000.** `sign(settlement_price − strike) == resolution outcome` on 46,055 slugs. Our
  Chainlink/RTDS data faithfully reproduces the settle print. (Resolves the research's load-bearing caveat.)
- **STEP 2 — Poly-lag: REAL.** Decided set (|oracle dist|≥15bp at T-60s) = 8,366 slugs (18.2%), RTDS-winner acc
  99.6%. Oracle-winner underpriced: win 99.6% vs mean price 0.981 → **print EV +1.35%/share, CI [+1.16,+1.53]**
  (BTC/ETH/SOL all +). Concentrated: p>0.98 (n=6635) EV +0.5% (priced in); **p<0.8 (n=124) EV +36%; 0.8–0.9
  (n=103) EV +11%** — the juice is in the rare cheap-but-decided slugs.
- **STEP 3 — Fill: directionally survives, but rare + underpowered.**
  | config | cheap-decided | fill% | n | $/tr | won | CI |
  |---|---|---|---|---|---|---|
  | T-60 $25 p<0.95 | 356 | 12% | 42 | +1.78 | .952 | [−0.69,+3.85] |
  | T-60 $5 p<0.95 | 356 | 12% | 42 | +0.37 | .952 | [−0.09,+0.78] |
  | T-30 $25 p<0.95 | 286 | 3% | 9 | +3.60 | 1.00 | [+1.24,+6.26] |
  | T-60 $25 p<0.90 | 215 | 6% | 13 | +4.15 | .923 | [−1.92,+9.09] |
  Fill-vwap ~0.85 ≪ realized win 0.92–1.0 = genuine mispricing (not the favorite trap). Asset mix skews ETH/SOL
  (thin books → more mispricing, less fill). Broad version (all decided, mostly p>0.98) dies on fills (15% fill,
  −$0.12, CI incl 0) — same favorite/print≠fill wall as FLB.

## Why this is the best lead so far
- It is **structural/settlement-mechanics** (front-run a near-deterministic oracle), not prediction — the class
  where our edge has always lived.
- It is the **first slug-selector that does not flip negative on realistic ask-walk fills** (favorite-longshot,
  maker entry, F2-basis all died; this stays +EV on the fillable subset).
- The signal is simple + deployable: at T-60s, if `|chainlink_price − strike|/strike ≥ 15bp` AND the
  oracle-winner ask `< 0.95`, buy $5–25, hold to settle.

## What blocks it (honest)
- **Underpowered**: only 9–42 fillable trades in 43 days (~1/day). Best-powered cell (n=42) CI **includes 0**.
  Cannot be confirmed on current data — it needs forward fills.
- **Low fill rate (3–12%)**: cheap-decided slugs are thin; live fill behavior may differ from backtest.
- Per-trade ROI is real but small in $ at $25 (favorite ~0.85 stake for ~$1.8 → ~7%/trade on fills).

## Recommendation
1. **Deploy a SHADOW sleeve** (`shadow_oracle_settle_<asset>`): fire at T-60s on decided+cheap slugs
   (|dist|≥15bp ∧ winner ask<0.95), $5 stake, hold to resolution, paper-only, distinct event_type. Accrue
   toward ≥100–200 forward fills + bootstrap CI>0 (same graduation bar as the scalp). This is the only way to
   settle the power question.
2. Hand to TV agent alongside the pending specs. Needs the live Chainlink RTDS feed (sponsored key per Polymarket
   docs) — already in our canonical, confirm live engine subscribes to `crypto_prices_chainlink`.
3. Re-verify the 0.07 winner-only fee vs live wallet before any real sizing (GROUND-TRUTH RULE).

## Files
- `oracle_settlement_selector_2026_06_05.py` (3-gate) · `oracle_cheap_decided_fill_2026_06_05.py` (subset fill) ·
  `oracle_determinism_eda_2026_06_05.py` (determinism profile). Research: `SLUG_SELECTION_RESEARCH_2026_06_05.md`.
