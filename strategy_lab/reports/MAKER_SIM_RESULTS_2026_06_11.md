# Conservative Maker-Fill Simulation — Results (2026-06-11)

**Script:** `strategy_lab/directional/maker_sim_2026_06_11.py`
**Checkpoints:** `strategy_lab/directional/_results/maker_sim_2026_06_11_{A,B}_{all,BTC,ETH,SOL,XRP}.parquet`
**Log:** `strategy_lab/directional/_results/maker_sim_2026_06_11.log`
**Window:** BBO Mar30–Apr21 (XRP Apr7–21). Coins BTC/ETH/SOL/XRP (only these have aliplayer trades).

## TL;DR

- **A (maker entry for the open scalp): maker LOSES decisively to taker.** Conservative fill rate = **0.0%** (0/1380 gated candidates) — you cannot get filled as a maker. The taker baseline on the same candidates is **+$0.759/tr (t=2.54, CI[+0.15,+1.34])**, i.e. the real edge requires *taking*. Even at the optimistic upper bound (queue=0), only 3.0% fill and those fills are heavily adversely-selected (WR 0.29 vs 0.55, maker $/tr ≈ **−$5.4**).
- **B (late-window favored-side maker bid = oracle pocket as maker): pocket is NOT capturable as a maker.** Conservative fill rate = **0.0%** (1/16,376). Upper-bound fill 4.7% gives WR 0.82 but $/tr = **−$2.8** with adverse-selection delta **−0.158** — you fill precisely when the near-certain favorite is about to flip and lose.

## Verified data facts (this session)

- **Trades `side` IS the taker aggressor side** (empirical check vs BBO, SOL, 30 slugs): BUY prints 63% sit ≥ best_ask (lift ask), SELL prints 68% sit ≤ best_bid (hit bid). So a resting maker BUY fills from `side=='SELL'` prints at price ≤ P; a resting maker SELL fills from `side=='BUY'` prints at price ≥ P. `shares = size_usdc / price`.
- Trades coverage SOL ≈ Mar13→Apr21; aligns to the slot. BBO size==0 (~47%) is a collector artifact → resolved via `resolve_size` carry-forward.

## Fill rule (exactly as pre-registered, conservative / under-filling)

Resting BUY at P, size Q (shares), posted at t0: fills only from taker SELL prints (price ≤ P, ts > t0). `QUEUE_AHEAD = resting best_bid_size at t0` (resolve_size). Our fill = min(Q, max(0, Σ qualifying SELL-print shares − QUEUE_AHEAD)). Symmetric for sells. **An UPPER-BOUND variant (queue=0, front-of-queue / improve) is reported alongside** to bracket the result — because the conservative fill is ~0, the upper bound is what makes the experiment interpretable. Both agree: fills are near-zero and adversely selected.

Rebate income: `rebate_per_share = k × 0.07 × P × (1−P)`, k ∈ {0, 0.05, 0.20}. Maker pays $0 fee. (k=0.20 = sole-maker ceiling of the 20% crypto pool; k=0.05 ≈ competitive. Per `_retro_2026_06_10/POLYMARKET_REBATE_FACTS_2026_06_11.md`.) **Rebate is economically negligible here** — at P≈0.5, k=0.05 adds ~$0.04/share*... no: ~$0.05×0.07×0.25 = $0.0009/share, i.e. < $0.05 per $25 order. It never changes a verdict.

---

## EXPERIMENT A — Maker ENTRY (open scalp), gate ev<0.55, delta_bps≥3

Pooled (BTC+ETH+SOL+XRP), n=1380 gated candidates.

| metric | conservative (queue=full) | upper-bound (queue=0) |
|---|---|---|
| fill rate (≥50%) | **0.000** (0/1380) | 0.030 (41/1380) |
| WR(all candidates) | 0.553 | 0.553 |
| WR(filled) | — (no fills) | 0.293 |
| **adverse-selection delta** | n/a | **−0.260** |
| maker $/tr, k=0 | — | −5.445 (CI[−7.63,−3.38]) |
| maker $/tr, k=0.05 | — | −5.409 (CI[−7.56,−3.34]) |
| maker $/tr, k=0.20 | — | −5.300 (CI[−7.47,−3.22]) |

**Taker baseline (same candidate set, n=1380): $/tr = +0.759, t=+2.54, CI[+0.149,+1.342].**

### A verdict
**MAKER LOSES — taker stays.** Pre-registered rule: maker wins only if maker(k=0.05) $/tr > taker baseline with paired CI>0. Conservatively the maker never fills (0%), so there is nothing to compare; the taker edge is positive and significant. The upper-bound fills (3%) are catastrophically adversely-selected (WR 0.29, $/tr −$5.4) — the only taker SELL flow that hits your resting bid is informed flow dumping the loser onto you. The script's "maker_ub−taker = +1.9 SIG+" line is an artifact of pairing on the same adverse subset (taker is also bad there) and is NOT a recommendation; in absolute terms maker_ub $/tr ≈ −$5.4.

**Adverse-selection delta (the number that killed maker-entry in 06-05): −0.260** (upper-bound). Re-confirmed: maker entry on the open scalp is dead, rebate does not save it.

---

## EXPERIMENT B — Late-window favored-side maker bid (oracle pocket, maker version)

T−60s & T−30s, |z|≥2, favored token. variant `join` = bid at min(best_bid, 0.95); `improve_m1c` = that − 0.01.

### variant `join` (n=16,376 candidates)

| metric | conservative | upper-bound (queue=0) |
|---|---|---|
| fill rate | **0.000** (1/16,376) | 0.047 (768) |
| WR(candidates) | 0.981 | 0.981 |
| WR(filled) | — | 0.823 |
| **adverse-selection delta** | +0.019 (n=1, meaningless) | **−0.158** |
| pooled $/tr, k=0 | — | −2.835 (CI[−3.53,−2.13]) |
| pooled $/tr, k=0.05 | — | −2.830 (CI[−3.57,−2.15]) |
| pooled $/tr, k=0.20 | — | −2.813 (CI[−3.57,−2.12]) |

### variant `improve_m1c` (n=16,344)

| metric | upper-bound (queue=0) |
|---|---|
| fill rate | 0.038 (629) |
| WR(filled) | 0.787 |
| adverse-selection delta | −0.194 |
| pooled $/tr, k=0.05 | −3.582 (CI[−4.40,−2.76]) |

### B verdict
**Pocket NOT real as a maker.** Pre-registered rule: real iff filled $/tr>0 CI>0 AND adverse-sel delta not strongly negative. Conservatively the maker bid never fills (1 fill in 16k) — nobody sells you the near-certain winner at the bid. The candidate direction is excellent (WR 0.981), but you can only realize it by *taking* the ask (the existing oracle-snipe taker strategy), not by resting a bid. The upper-bound fills are negative (−$2.8 to −$3.6/tr) with adverse-selection −0.16/−0.19: the only time your resting favored-side bid fills is when the favorite is collapsing (WR drops 0.98→0.82, and conditional on the fill the realized PnL is negative). Mechanism: a maker bid on the favorite only trades against taker sellers who are dumping the favorite — i.e. against the flip. **The pocket belongs to takers, not makers.**

Per coin-tf the conservative fill rate is 0% everywhere (BTC 1/4874, ETH/SOL/XRP 0). Time-split irrelevant (no conservative fills).

---

## Why fills are ~zero (diagnostic)

For both experiments the at-or-below-our-price taker-SELL flow in the rest window is essentially absent:
- A (30s rest): mean ≈ 1.4 qualifying SELL prints/window, cumulative ≈ 0–10 shares, vs resting `best_bid_size` (queue ahead) of 2,000–8,000 shares → `max(0, cum−queue) = 0`.
- B (≤60s rest, favored side priced ~0.95): cumulative qualifying SELL shares ≈ 0 (nobody sells the near-certain winner cheap), queue ahead 600–2,700 shares.

The upper-bound (queue=0) only lifts fills to 3–5% and selects the informed/adverse prints. This is a **structural** result, not a queue-priority tuning issue.

## Caveats

- **Conservative fill = strict lower bound on fills.** Reported with an explicit queue=0 upper bound; both ends agree (near-zero, adversely selected).
- **Trades coverage** Mar30–Apr21 (XRP from Apr7). aliplayer ticks; `side` verified = taker side. BTC/ETH/SOL/XRP only.
- **BBO top-of-book** (no L25 depth walk) — queue-ahead uses best_bid_size; deeper book not modeled (would make conservative fills *even harder*, not easier).
- **Mar30–Apr21 is the BURNED OOS window** for the open-scalp (used in the 06-05 OOS). Experiment A is therefore a fill/economics test of the *maker* execution, NOT a fresh OOS of the scalp signal; the taker baseline here is in-sample-ish and only used as the apples-to-apples comparator.
- Rebate income is negligible at these prices/sizes and never flips a verdict.
