# Late-slot oracle-determinism snipe — full backtest, 6 coins × 5m/15m — 2026-06-11

**Setup:** at T−{30,15}s before slot end, z-score the window move (binance 1s, σ=300s causal); buy the favored
token at ask; hold to resolution; winner-only 0.07 fee; top-of-book size-carry fills; BBO Mar30–Apr21.
**Pre-registered primary cell:** T−30s, |z|≥2, ask≤0.95, Wang-margin≥0.02. Lenses integrated: Wang fair-value
margin (entry condition), microprice tilt (buckets). Script `directional/oracle_snipe_2026_06_11.py`,
data `_results/oracle_snipe_2026_06_11{,_alts}.parquet` (34.7k evals + 2.1k BTC15m).

## Verdict: ❌ FAILS the pre-registered gate. Niche thin-book pocket only — not deployable as a taker.

**Primary cell pooled (alts run): +$0.53/tr, t=1.50, CI[−0.20,+1.18], WR 93.0% (n=471)** — CI spans 0.
Time-split consistent but ns both halves. BTC 15m (separate run): **−$0.85** (n=55, WR 76%); ETH 15m −$0.93.

**The mechanism that kills it (diagnostic, important):** at z≥2 the books already price the winner at
**median ask = $1.000** (90% of evals ≥0.97) on BTC/ETH. The rare visibly-cheap favorite is **adversely
selected** — its realized WR (76–85%) sits far below both the z-implied ~97% and the ask-implied breakeven
(~93%). The Wang late-window premium (+1–3¢ on 17.5M trade PRINTS) is real but **not takeable**: prints ≠
the resting ask you can hit. Print≠fill claims another one — same death as favorite-longshot.

**Where a pulse exists (exploratory, multiplicity-laden):**
- **BNB 5m primary: +$1.37/tr, t=2.95, CI[+0.35,+2.20], WR 96.1% (n=152)** — the one CI>0 coin-cell.
- T−15s & z≥3 cells: +$3.57 CI[+0.17,+7.01] (ask≤0.93, n=57); +$1.31 CI[+0.15,+2.42] (ask≤0.97, n=199).
- Pattern: **extreme z + later timestamp + THIN books** = genuine staleness survives; in liquid books any
  cheapness is informed. Explains the decoded whale: their 87% likely comes from MAKER placement /
  many-thin-markets operation, not taker fills on majors.
- Capacity reality: BNB 5m ≈ 10 fires/day ≈ ~$14/day at $25 — niche even if real.

**Lens add-ons (the user's question):** the **Wang margin requirement had ZERO discriminating effect** here
(at extreme asks fair is always above; ablation flat) — Wang's value stays diagnostic (calibration/efficiency
benchmark + the late-premium discovery), not a per-trade gate. **Microprice tilt:** same ALIGNED ≥ NEUTRAL >
OPPOSED confirmation shape as on the scalp, all ns — consistent but not additive. Conclusion stands from the
scalp test: confirmation-shaped, coin-inconsistent, park both as monitors.

## Disposition
- Do NOT deploy a taker oracle snipe on majors — evidenced dead (adverse selection).
- The thin-book pocket (BNB/alt 5m, z≥3, T−15) is a candidate for the **maker-side** variant — post resting
  bids/asks late-window in thin books and collect the stale-quote flow + rebate. That folds into **E3
  (maker with rebate, queue-aware via hftbacktest)** — now the single highest-priority research thread, with
  THREE independent arrows pointing at it (rebate program economics, whale behavior, this thin-book pocket).
- Wang λ refit monthly as the standing market-efficiency dashboard (λ_late drifting up = premium growing).
