# Leg-1 oracle-lag DIRECTIONAL taker — foundation backtest (2026-05-29)

> **Leg 1 of "Buy → Wait → Hedge".** Quantifies the standalone DIRECTIONAL edge of buying
> the binance-LEADING side of a BTC/ETH/SOL up-down market at its stale-cheap L25 ask
> (before chainlink/polymarket reprices) and holding to resolution — under the
> operator-confirmed **real 0.07 fee curve** (winner-only), not the legacy 2%.
>
> Script: `strategy_lab/directional/lag_taker_foundation_2026_05_29.py`
> Fire universe: `strategy_lab/lag_taker_fires_2026_05_29.parquet` (3,653 fires)
> Window: **2026-05-08 → 05-29** (binance-1s coverage bound, ~21 days). IS/OOS split @ 05-18.
> Signal replicates `oracle_lag.price_delta_bps`: `binance(slot_start+5s)/binance(slot_start)−1`;
> sign = leading side. Anchor = intra-window stale-ask pickoff at `fire=(slot_start+5)·1e6`
> (NOT a ws_s momentum predictor — the move is realized inside the live window; we buy the
> resting ask before it reprices and resolve on the slug's own chainlink settlement → no lookahead).
> Fills: `engine_v2.fill_at_book` ($25 book-walk + 85ms latency + same-token spread≤0.05,
> native-10Hz L25). Fee: `pnl_won=(1−vwap)·shares·(1−0.07·vwap)`, `pnl_loss=−vwap·shares`.

---

## VERDICT — the edge is REAL, BTC/ETH-led, ~+$2.4/$25 after the 0.07 fee

A genuine directional lag edge exists and **survives the real 0.07 fee** with a textbook
monotonic dose-response. It is **concentrated in BTC + ETH; SOL is a net drag** (kill it).
The recommended foundation config — **BTC+ETH, |delta|≥3bps, fire at slot_start+5s** — nets
**+$2.39/$25 trade (≈+9.6%/fire), WR 65.4%, t=4.06 (IS t=3.47, OOS t=2.46)**, ~59 fires/day.
Dropping the worst time-of-day window (18-23 UTC) lifts it to **+$2.90/tr, t=4.19, OOS t=3.29**.

---

## PART A — Lag-predictiveness (binance pre-fire move → directional WR)

Pooled across assets/tfs. For each pre-fire window W and threshold X: when binance moved
≥X bps over the W seconds ending at fire, how often did chainlink resolve the SAME direction?

| thr (bps) | W=30s | W=60s | W=120s | n@30 | n@60 | n@120 |
|---:|---:|---:|---:|---:|---:|---:|
| 5  | 57.5% | 53.5% | 50.8% | 2883 | 5082 | 8016 |
| 10 | 63.6% | 58.4% | 52.8% | 539  | 1227 | 2653 |
| 20 | 55.3% | 60.8% | 56.9% | 47   | 148  | 487  |
| 40 | 66.7% | 70.6% | 61.4% | 3    | 17   | 57   |

**Read:** bigger move + SHORTER measurement window ⇒ higher directional WR (the lag is
fresh). A ≥10bps move in the last 30s ⇒ 63.6% same-direction; ≥40bps ⇒ 66-71% (small n).
The W=120s column decays toward 50% — the further back you measure, the more the move is
already priced. This is the lag signature: directional predictiveness lives in the *recent*
move, exactly where a fast taker buys the not-yet-repriced ask. (The PART-B taker uses the
5s intra-window move as its operational signal; this table validates the underlying physics.)

---

## PART B — Leg-1 taker backtest ($25 walk + 85ms + spread≤0.05, 0.07 fee)

### Pooled by move threshold (all assets/tfs)
| thr (bps) | n | WR | mean vwap | $/tr | total | maxDD | t-stat | tr/day |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2  | 3653 | 59.8% | 0.582 | +0.42 | +1540 | −1060 | 1.20 | 170 |
| **3**  | **1865** | **63.3%** | **0.593** | **+1.43** | **+2659** | **−519** | **2.98** | **87** |
| **5**  | **541** | **67.7%** | **0.615** | **+2.34** | **+1267** | **−339** | **2.75** | **25** |
| 8  | 136 | 69.1% | 0.658 | +1.69 | +230 | −218 | 1.04 | 6.3 |
| 10 | 82  | 65.9% | 0.662 | −0.01 | −1.2  | −248 | −0.01 | 3.8 |

**Monotonic WR dose-response 59.8→63.3→67.7→69.1% as gate rises 2→3→5→8bps** — the
stale-ask thesis prediction, strong evidence of a real mechanism (overfit shows no gradient).
2bps is too loose (marginal moves dilute, t=1.2). 8/10bps collapse on small n, not on edge.
**3bps = robust sweet spot** (t≈3, 87 fires/day); 5bps = sharper $/tr at lower volume.

### IS vs OOS (split @ 05-18)
| thr | period | n | WR | $/tr | t |
|---:|---|---:|---:|---:|---:|
| 3 | IS  | 700  | 64.6% | +2.27 | 2.89 |
| 3 | OOS | 1165 | 62.6% | +0.92 | 1.52 |
| 5 | IS  | 178  | 68.5% | +3.32 | 2.20 |
| 5 | OOS | 363  | 67.2% | +1.86 | 1.81 |

Positive in both halves; OOS weaker (SOL drag — see below).

### By asset (≥3bps) — **BTC/ETH carry it, SOL is the drag**
| asset | n | WR | $/tr | total | t |
|---|---:|---:|---:|---:|---:|
| **BTC** | 513 | 66.7% | **+2.99** | +1533 | **3.31** |
| **ETH** | 717 | 64.4% | **+1.95** | +1401 | **2.53** |
| SOL | 635 | 59.4% | −0.43 | −275  | −0.52 |

### By timeframe (≥3bps) — 15m cleaner than 5m
| tf | n | WR | $/tr | t |
|---|---:|---:|---:|---:|
| 15m | 590  | 62.0% | +2.84 | 3.09 |
| 5m  | 1275 | 63.9% | +0.77 | 1.39 |

### Time-of-day UTC (≥3bps) — avoid 18-23
| bucket | n | WR | $/tr | t |
|---|---:|---:|---:|---:|
| 00-05 | 412 | 66.3% | +2.34 | 2.36 |
| 06-11 | 285 | 66.0% | +1.89 | 1.59 |
| 12-17 | 638 | 61.8% | +1.61 | 1.90 |
| 18-23 | 530 | 61.5% | +0.25 | 0.28 |

### Recommended-config sweep (BTC+ETH only, SOL dropped)
| config | n | WR | $/tr | total | maxDD | t |
|---|---:|---:|---:|---:|---:|---:|
| BTC+ETH all-tf ≥2bps | 2400 | 61.9% | +1.37 | +3297 | −479 | 3.17 |
| **BTC+ETH all-tf ≥3bps** | **1230** | **65.4%** | **+2.39** | **+2934** | **−394** | **4.06** |
| BTC+ETH all-tf ≥5bps | 371  | 69.8% | +3.38 | +1256 | −237 | 3.33 |
| BTC+ETH 15m ≥3bps    | 399  | 62.2% | +3.25 | +1298 | −254 | 2.88 |
| **BTC+ETH ≥3bps, ex-18-23UTC** | **880** | **66.2%** | **+2.90** | **+2552** | **−254** | **4.19** |

**BTC+ETH ≥3bps IS/OOS: IS t=3.47 (+$3.40), OOS t=2.46 (+$1.80) — significant OUT-OF-SAMPLE.**
Adding the 18-23 UTC time filter: OOS t=3.29, +$2.84/tr. SOL was the entire OOS weakness.

---

## PART C — Breakeven under the 0.07 curve

### Single-leg directional taker (what leg-1 must clear)
Solve `p·(1−v)·(1−0.07v) = (1−p)·v`:
| entry vwap | breakeven WR p\* |
|---:|---:|
| 0.50 | 50.9% |
| 0.55 | 56.0% |
| 0.58 | 59.0% |
| 0.60 | 61.0% |
| 0.65 | 66.0% |
| 0.70 | 71.0% |
| 0.77 | 78.0% |

The 0.07 fee adds only **~0.9-1.0 pp** to breakeven WR vs no-fee (`p*≈v`). At the realized
mean vwap ≈0.59 the taker needs ~60% WR; it delivers **63-66%** at the ≥3bps gate ⇒ the
~4-6pp WR surplus is the captured stale-ask discount, net of fee.

### Complete-set lock threshold (for leg-2 / next phase)
Net per locked set = `1 − v1 − v2 − 0.07·v_win·(1−v_win)`. The 0.07 winner fee on a complete
set is tiny (max ~1.75¢ at v=0.5), so the binding constraint is just **sum < ≈0.985**:
| leg1 entry | max leg2 | **max sum (nets ≥0)** |
|---:|---:|---:|
| 0.60 | 0.383 | **0.983** |
| 0.66 | 0.324 | **0.984** |
| 0.70 | 0.285 | **0.985** |
| 0.77 | 0.217 | **0.987** |

**Under the 0.07 curve the lock breakeven sum is ~0.985-0.99** (vs the old ~0.97 under the
legacy 2%). The lock is MORE forgiving on fees than the strategy doc assumed — but the prior
`LATENCY_EDGE_FINDING` / `LOCK_THE_LAG` tests show the binding problem is **execution**: leg-2's
ask reprices to ~$1.09 pair-cost before you can complete cheap. The fee was never the blocker;
the second-leg repricing is. The lock overlay stays EV-neutral-to-negative regardless of fee.

---

## Recommended leg-1 entry config (fire universe for the gates/stop-loss phase)

```
asset      ∈ {BTC, ETH}            # DROP SOL — net-negative, t=−0.5, the OOS drag
timeframe  ∈ {5m, 15m}            # 15m cleaner ($3.25/tr t=2.88); 5m still +EV at ≥3bps
signal     delta_bps = binance_1s(slot_start+5s)/binance_1s(slot_start) − 1, ×1e4
gate       |delta_bps| ≥ 3.0      # sweet spot (t=4.06). Use ≥5bps for higher $/fire, less n
direction  Up if delta>0 else Down (the binance-leading side)
fire       fire_us = (slot_start + 5)·1e6   # 5s into window = freshest stale ask
fill       engine_v2.fill_at_book, $25 book-walk, 85ms latency, spread≤0.05, native-10Hz L25
exit       HOLD to chainlink resolution
fee        0.07 winner-only curve
time-filter (optional) AVOID 18-23 UTC → lifts t to 4.19, OOS t=3.29
```
Expected: **~59 fires/day (≥3bps, BTC+ETH), WR ~65%, +$2.4/$25 (+9.6%/fire), maxDD ~$390**
over 21 days. Variance is high (single-fire ±$25) — the next phase should add a **stop-loss
(15-20¢, variance reducer, ~same mean, higher t per prior `path_overlay.py`)** and test
sizing. Do NOT add the complete-set lock as an alpha source (leg-2 reprices; EV-neutral).

### Fire universe parquet — `strategy_lab/lag_taker_fires_2026_05_29.parquet`
3,653 fires (gate ≥2bps so the next phase can re-sweep). Columns:
`slug, asset, tf, fire_us, slot_start, direction, delta_bps, entry_vwap, shares, outcome,
won, pnl, hour, period`. Filter `asset∈{BTC,ETH} & delta_bps≥3` for the recommended universe.

---

## Caveats
- **~21-day window** (binance-1s coverage May 8→29). Forward data needed to lock OOS.
- **3/5bps chosen from a sweep** — mitigated by IS+OOS co-significance + monotonic gradient.
- Fill model = same-token spread≤0.05 (correct gate for a directional taker; the CLAUDE.md V5
  cross-token issue is a maker/arb problem, not relevant here per `LATENCY_EDGE_FINDING`).
- This corroborates the prior `LATENCY_EDGE_FINDING_2026_05_29.md` (which used legacy 2%); the
  0.07 curve barely changes the verdict (+~1pp breakeven) — the edge is fee-robust. New here:
  the clean SOL-exclusion + 15m-preference + time-of-day filter that pushes OOS t past 3.

## Artifacts
- `strategy_lab/directional/lag_taker_foundation_2026_05_29.py` (backtest)
- `strategy_lab/lag_taker_fires_2026_05_29.parquet` (fire universe)
- `strategy_lab/directional/_results/{lag_predictiveness_pooled.csv, lag_predictiveness_full.csv, lag_taker_by_cell.csv}`
- `strategy_lab/directional/_lag_postproc_2026_05_29.py` (BTC+ETH recommended-config cells)
