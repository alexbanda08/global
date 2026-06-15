# Avellaneda-Stoikov for the b945 binary ladder — applicability analysis

_2026-06-12. Source: AS market-making primer (reservation price + optimal spread + GLT/Cartea-Jaimungal
extensions). Assessed against our decoded b945 strategy (`B945_ARTICLE_INFRA_GAP_ANALYSIS_2026_06_12.md` §8:
early-placed two-sided GTC ladders, paired sum<1 capture +$35.5k, residual drag −$29.3k, +$21,742 audited)._

---

## TL;DR

**AS is the formal theory of the exact problem b945 solves heuristically** (inventory skew + spread sizing
under inventory risk + adverse selection). It is **useful as the Phase-B ladder-shape engine** — and it
**directly attacks our biggest leak: the −$29.3k residual drag**. BUT it optimizes quote placement *given
you get fills*; it does **NOT** solve queue position (early placement), which is our actual deploy NO-GO.
So: **build queue-priority first (the moat), bolt AS on as the ladder-math second.** AS is more
sophisticated than b945's own bot (he runs clip∝price + a soft gate, and warns ">3 filters = fragile") —
but it is ONE coherent model with γ as the master dial, with k and σ *estimated from data not tuned*, so it
is not "3 more filters." Net: **adopt the adapted AS skew + inventory bound; treat the full spread formula
as an optimization to calibrate against his fill economics, not gospel.**

## 1. Why AS maps onto our problem almost 1:1

The binary 15m up/down market is in several ways a **cleaner** AS fit than the spot/perp crypto the article
targets:

| AS concept | Spot crypto (article) | **Our binary 15m market** |
|---|---|---|
| Session end `T` | none → needs ergodic/rolling hacks (Assumption 5) | **NATIVE: T = slot_end / resolution.** No hack. The single hardest AS adaptation is free for us. |
| Inventory `q` | gross position | **net residual `r = q_up − q_dn`** — the PAIRED part is RISKLESS ($1 redemption), only the residual carries variance. This is the key reinterpretation. |
| Fair value `s` | order-book mid | settlement-prob proxy: oracle (Chainlink RTDS / Pyth-Lazer settlement-value feed) → P(up); token mid as fallback |
| Volatility `σ²` | realized vol of price | vol of P(up): underlying BTC vol scaled by distance-to-strike & time-to-resolution. **Explodes near strike, →0 when pinned far from strike.** |
| Order arrival `k` | taker-flow sensitivity to spread | sensitivity of taker SELL flow to our bid distance — **we already measured the raw flow** (flow study: ~234 prints/win, $2,150 sell flow). `λ(δ)=A·e^{−kδ}` is fittable from our trade tape + L25. |

**Every heuristic in our §8 plan is the hand-rolled version of an AS component:**

| Our §8 heuristic | AS formal equivalent |
|---|---|
| Soft imbalance gate (skew/widen heavy side) | **Reservation price** `r = s − q·γ·σ²·(T−t)` — optimal skew magnitude, not a guessed threshold |
| Max-imbalance "stop quoting heavy side" | **GLT inventory bound `Q`** (Guéant-Lehalle-Tapia 2013) — stop quoting the exposed side at `|r|≥Q`; gives a closed-form solution |
| `>85¢` filter (his measured −EV zone) | **Cartea-Jaimungal adverse-selection term** — widen/withdraw when informed flow elevated (late-window, extreme prices) |
| Warmup gate / skip-window / >15¢ reject | **Circuit breaker** (Assumption 6, jumps) — oracle moves discontinuously; pause quoting |
| clip∝price ladder sizing | AS arrival intensity `λ(δ)` implies the size-vs-edge tradeoff per level |

That correspondence is the whole point: **AS unifies our 5 separate hand-tuned rules into one model with a
single risk-aversion dial γ**, where k and σ come from live estimation. Less overfit surface, not more.

## 2. The headline value-add: AS attacks the residual drag directly

Our economics: paired capture **+$35.5k** (the engine) is half-eaten by residual drag **−$29.3k** (the
unpaired side wins only 37% — because clip∝price mechanically piles excess onto the cheap/losing side).
b945 *tolerates* this drag. **AS's reservation-price skew is precisely the tool to minimize it:** when
residual `r` grows, skew bids to mean-revert inventory toward paired (riskless) → fewer unpaired shares →
less directional bleed. A successful AS skew that halves the residual drag (−$29.3k → −$15k) would, at his
volume, **roughly double net PnL** (+$21.7k → ~+$36k) with the SAME paired engine. **This is a concrete
improvement over b945 himself, not just replication.** It is the strongest reason to bother with AS.

⚠️ Counterforce: skewing to rebalance means quoting the light side more aggressively = worse fills on that
side = potentially lower pair fraction. The γ dial trades residual-drag reduction against pair-fraction.
This is an empirical calibration, and it can ONLY be tuned live (queue-position-dependent) — see §4.

## 3. The binary-market adaptations that matter (don't use the formula naked)

1. **`q` = net residual, NOT gross inventory.** Using gross would skew against a paired book that carries
   zero risk — wrong. The paired leg is locked profit; only `r = q_up − q_dn` enters the reservation price.
2. **`σ²` is the binary-token vol, which is non-stationary and path-dependent**, not Brownian. As t→T with
   price far from strike, σ→0 (token pinned at ~1 or ~0); near strike, σ is large and the residual is most
   dangerous. Feed a **time-and-distance-aware σ from the oracle** (BTC realized vol × |Δ to strike| sensitivity),
   not a constant. This is Assumption 3 in acute form.
3. **Two coupled books, one constraint.** p_up + p_dn ≈ 1 (no-arb). Quote both sides off ONE reservation
   price for P(up); the Down-side bid follows from (1 − r_price). Our sum<1 capture = posting both bids such
   that bid_up + bid_dn < 1.
4. **Adverse selection is the dominant risk near resolution** (his >85¢ losses). The Cartea-Jaimungal term
   isn't optional polish here — it's the mechanism that stops the residual from getting run over in the final
   minutes. Implement as: widen δ (or stop quoting the exposed side) as (T−t)→0 AND when |Δ to strike| is small
   (coin-flip zone = max adverse selection).
5. **No mid-window unwind via the spread** the way AS assumes — we mostly hold to resolution + merge. So the
   "inventory cost" is realized at T, not continuously. The (T−t) clock still governs how much MORE residual
   we're willing to carry, but the exit is the redemption, not a market sell. (If the merge-timing agent
   finds mid-window merges, AS's continuous-unwind assumption gets closer to literally true.)

## 4. Where AS does NOT help — and the correct sequencing

- **AS does not get you fills.** It answers "given my flow arrives at rate λ(δ), where do I quote?" Our
  NO-GO is pair fraction 29% vs his 44% = a **queue-position problem** (he places ~24h early, front of FIFO).
  AS optimizes the economics of fills you actually get; it is silent on being first in queue. **Early
  placement (the moat) must be built first; AS is the layer on top.**
- **AS assumes you can continuously cancel/replace cheaply.** On Polymarket, GTC cancel/replace is free
  (no gas, maker rebates) — so the continuous-quoting assumption holds well, unlike many venues. Good.
- **Over-engineering risk is real.** b945 prints +$21.7k with clip∝price + a soft gate. If AS's marginal
  gain (residual-drag reduction) is eaten by added latency in the hot path (computing r, σ, k every requote),
  it's net-negative. **The hot path must stay clone+send (pre-signed grid); AS recomputation belongs on the
  decision core, not the submit core** (maps cleanly to the A3 CPU-pinning split).

**Sequencing verdict:** Phase A (racer + early placement + pre-signed ladder + pinning) unchanged and FIRST.
Phase B `tv-strat-ladder` ships in **two tiers**: B0 = b945-faithful (clip∝price + soft gate) to validate
the queue mechanism cheaply; **B1 = AS ladder** (reservation-price-centered levels, GLT inventory bound,
Cartea-Jaimungal late-window widening) as the economics-optimizing upgrade, A/B'd against B0 on the same box.
Judge B1 vs B0 on **net $/slug and residual-drag $**, not pair fraction (both should match on fills).

## 5. Concrete TVRUST shape (if/when B1)

- New pure crate `tv-mm-as` (no I/O): `reservation_price(s,q,t,γ,σ,T)`, `optimal_spread(t,γ,σ,k,T)`,
  `inventory_bound(Q)`, `adverse_selection_widen(t,T,dist_to_strike)`. Pure functions → trivially
  parity-testable (the AS primer's worked example: s=100,q=5,γ=0.1,σ²=0.02,T−t=0.5 → r=99.995 = a golden vector).
- **Live estimators** (decision core, rolling 5–15 min): σ from oracle returns; k from taker-flow-vs-bid-distance
  fit on the racer's own tick tape (A4 latency tape feeds this). γ = the single operator dial.
- **Inputs we already have**: oracle feed (RTDS + Pyth-Lazer), L25 books, the measured taker sell-flow.
- Hot path stays pre-signed: AS outputs target (price,size) per level on the 1¢ grid → look up the matching
  pre-signed order → send. AS math never runs on the submit core.

## 6. Verdict

**USEFUL — adopt as the Phase-B1 ladder-math, after the queue-priority moat is built.** Specifically:
1. **Reservation-price skew on net residual** → the principled soft-imbalance gate; **directly targets the
   −$29.3k drag** = the one place we can plausibly BEAT b945, not just match him.
2. **GLT inventory bound** → the max-imbalance stop-quote, with a closed form instead of a guess.
3. **Cartea-Jaimungal adverse-selection widening** → the formal >85¢/late-window filter (his own −EV zone).
4. The binary market gives us **AS's hardest parameter (session T) for free** — cleaner than the article's
   24/7-crypto use case.
**Do NOT** treat the full spread formula as deploy-ready truth (k, σ are venue-specific estimates; calibrate
against his fill economics), and **do NOT** let it touch the hot path or precede the early-placement build.
The moat is queue position; AS is how you make the most of the fills the moat earns you.
