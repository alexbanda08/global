# Deep-research findings — new edge possibilities (2026-06-03)

Internet deep-research (22 sources → 39 claims) targeting the white-space from `INDEX.md`.
⚠️ The harness's adversarial-verify stage **crashed** (all verifier agents failed to return → every claim
auto-labeled "refuted 0-0"). That is a tooling bug, NOT real refutation. Below I apply my own credibility
judgment (HIGH/MED/LOW) given domain knowledge + source quality. Treat HIGH/MED as leads to validate with our
own backtest (which we'd do regardless).

## 🥇 Angle 1 — Cross-venue arbitrage (Polymarket ↔ Kalshi). STRONGEST new lane (we run BOTH live)
**Mechanism:** buy YES on the cheaper venue + NO on the dearer when `P(YES_A) + P(NO_B) < $1` → lock ~$1
payout regardless of outcome. Multiple open-source bots exist (ImMike 10k-market text-matcher; realfishsam;
CarlosIbCu).
- **⭐ The concrete crypto one — BTC 1-hour up/down STRIKE-MISALIGNMENT "middle"** (CarlosIbCu bot, MED-HIGH):
  Poly and Kalshi use *different strike prices* for "BTC up/down this hour." When Poly_strike > Kalshi_strike,
  buy **Poly DOWN + Kalshi YES** → guaranteed **min $1**, and **$2 if BTC settles inside the strike gap**. The
  edge is the strike middle, NOT same-strike mispricing. **We have Poly BTC up/down + a live Kalshi BTC sniper
  + the Ireland VPS — this is directly testable with our infra.**
- Realized spreads: **1.5–4.5%** on high-volume Fed/election markets (realfishsam, MED); 2–5% headline on
  equivalent political contracts (blogs, LOW-MED — competed fast on liquid markets).
- 🚨 **RISKS (HIGH confidence, well-documented — these are why it's not free):**
  1. **Settlement DIVERGENCE.** Kalshi vs Poly resolved the Super Bowl "Cardi B halftime" market **opposite**
     (different resolution rules; Kalshi Rule 6.3(c) paid NO, Poly paid YES) → a cross-venue hedge became a
     **total loss**. "Same event" ≠ same resolution. The BTC strike-middle is *safer* (price-level, not
     wording) but still has **different oracle / settle-time / settle-price** risk — must model exactly.
  2. **Settlement timing asymmetry:** Kalshi settles in hours; Poly waits on UMA (≥2h, days if disputed;
     $750 bond, 2h challenge, dispute escalation). Capital lockup + you can't unwind symmetrically.
  3. **Fee asymmetry:** Poly maker $0 / taker 0.07-curve; **Kalshi charges a fee on *expected earnings* +
     maker fees** on some markets. Eats thin spreads.
  4. **Leg/latency risk:** prices drift between the two sequential placements; one leg fills, the other
     doesn't. Kalshi fiat withdrawal friction (regulated/KYC).
- **Verdict:** the most actionable NEW lane for us — but it's an **execution + settlement-modeling** game, not
  a prediction game. Our edge angle = we already have both venues + low-latency. Profit survives only if we
  model the cross-oracle settlement risk and win the leg race.

## 🥈 Angle 2 — Intra-market / term-structure arbitrage (UNTESTED, math-solid)
**Intra-market sum≠1** (HIGH, it's arithmetic): if the mutually-exclusive contracts in one market sum ≠ $1,
buy-all-at-<1 (or sell-all-at->1) locks risk-free profit. For binary up-down, UP+DOWN summed ~1.30 on real
books (we measured) → NO lock there. **But the multi-outcome ladders we already found in LP farming — temperature
buckets, the "BULK launch by {7 dates}" ladder, price-range markets — are exactly where complementary sets can
misprice.** Concrete untested scan: for each multi-outcome event, check `Σ best_ask(all outcomes)` < 1 (buy-all
lock) or `Σ best_bid` > 1 (sell-all lock), net of fees. Cheap to run on our gamma/CLOB data.

## Angle 3 — LP rewards (CONFIRMS our docs, no new edge)
One-sided ÷3, quadratic `S=((v−s)/v)²·b`, per-minute sampling (10,080/epoch), dYdX copy, `max_incentive_spread`
/`min_incentive_size` via CLOB+Markets API. All matches `polymarket_lp_rewards/`. HIGH confidence, nothing new.

## Angle 4 — Domain forecasting (leads, fetches failed)
Search surfaced but **failed to fetch**: a **Kalshi weather postmortem + pivot** (northlakelabs), a
**Poly↔Kalshi weather bot** (suislanchez), and 2 arxiv papers (2508.03474, 2602.19520). Weather is *proven
profitable for us* (HighTempTation +$7.8k) → these are worth a manual read. The "postmortem and pivot" framing
hints weather got competitive on Kalshi — verify before committing.

## Angle 5 — Academic persistent inefficiencies
- **Favorite-longshot bias (HIGH, classic + quantified):** 12,084 matches — favorites returned **−3.64%** vs
  outsiders **−26.08%**. Favorites are systematically *less overpriced* → a "buy favorites / avoid deep
  longshots" tilt is +EV-ish in *skewed* markets. NOT applicable to our near-50/50 up-down, but **relevant to
  sports / temperature-bucket / election markets** (and consistent with our finding that LP'ing deep-longshot
  thin books is toxic).
- UMA mechanics ($750 bond, 2h window, dispute escalation) — needed input for cross-venue settlement modeling.

## Net — what's genuinely NEW & actionable for us
1. **Poly↔Kalshi BTC hourly strike-misalignment middle** — testable NOW with our infra + data. Build an
   offline check first: how often is `Poly_strike ≠ Kalshi_strike` enough to create a profitable middle after
   fees, and how often do the two oracles/settle-times agree? This decides if it's real or a settlement trap.
2. **Multi-outcome sum≠1 scanner** — cheap, untested, runs on data we already pull (gamma/CLOB ladders).
3. (lower) **Cross-venue same-event spread bot** on liquid political/Fed markets — but settlement-divergence
   risk (Cardi B) makes this dangerous; only with strict same-resolution matching.
4. Re-read the failed-to-fetch **weather/Kalshi** sources before any domain-forecasting build.

## Sources (the ones that produced claims)
quantpedia.com/systematic-edges-in-prediction-markets · defirate.com/prediction-markets/how-contracts-settle ·
trevorlasn.com (poly-kalshi arb) · github.com/CarlosIbCu/polymarket-kalshi-btc-arbitrage-bot ·
github.com/ImMike/polymarket-arbitrage · dev.to/realfishsam (risk-free arb bot) ·
docs.polymarket.com/market-makers/liquidity-rewards · startpolymarket.com/strategies/reward-farming.
Failed-to-fetch leads: northlakelabs kalshi-weather-postmortem, suislanchez/polymarket-kalshi-weather-bot,
arxiv 2508.03474 + 2602.19520, docs.limitless.exchange/developers, cepr.org/voxeu kalshi.
