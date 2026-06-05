# Physics-of-BTC signal — implemented + WEAK_COMBO thresholds tuned (2026-06-01)

Implements the article's "physics" signal on our canonical data and recovers the 2
thresholds the author withheld. Speed/dist/cross/have computed on the **chainlink**
basis (outcome-consistent; binance-1s ablation matches). Bet = CONTINUATION (the side
BTC is on vs strike). Fire at slot_end−60s (have=1.0m, matching his log).

- Feature module (reusable, engine-ready): `strategy_lab/physics/physics_signal.py`
- Backtest + grid: `strategy_lab/physics/backtest_physics_2026_06_01.py`
- Data: `strategy_lab/physics/_results/physics_fires_btc.parquet` (14,101 fires), `physics_weakcombo_grid.csv`

## 1. Distribution — our data vs the article
| metric | article (binance, 24/7) | ours (chainlink, @60s-to-close) |
|---|---|---|
| mean speed | 13 $/min | **19.4** |
| median | 7 | **12.6** |
| max | 134 | **392** |
| storm (>15) | 26% | **44%** |
| avg \|dist\| | 49 $ | **54 $** |

Same skewed, storm-heavy shape; ours runs hotter (we sample the last minute of 5m/15m
windows, the most active moment; binance ablation = mean 19.1 → not a feed artifact).
His "quiet<5 = 0%" vs our 25% is the sampling difference (one snapshot/slug near close
includes flat oracle steps). **The physics is reproduced.**

## 2. Where the edge lives — DIST dominates, speed is the secondary axis
Baseline continuation-bet WR (no filter): **ALL 85.1%** (5m 82.9%, 15m 91.9%).

**WR by |dist| (the dominant axis) — monotonic and steep:**
| \|dist\| $ | n | WR |
|---|---|---|
| 0–15 | 3374 | **64.6%** ← coin-flip near strike |
| 15–30 | 2827 | 79.8% |
| 30–50 | 2667 | 90.6% |
| 50–100 | 3256 | 97.6% |
| 100+ | 1977 | **99.9%** |

WR by |speed| is much flatter (80%→90% across buckets) → **speed/inertia is the weaker,
secondary signal**, exactly as the article frames it ("two weak signals" = near strike
AND low inertia).

## 3. THE TWO THRESHOLDS (WEAK_COMBO block)
Rule: **`if dist_abs < THR_DIST and speed_away < THR_SPEED: SKIP`** (block only when BOTH
weak; one strong — far OR moving-away-fast — lets the trade through). The article-implied
pair (`dist_abs × speed_away`) **dominated the grid** (entire top-12, OOS train60/test40).

**Tuned thresholds (robust OOS region):**
- **THR_DIST ≈ 30–40 $**
- **THR_SPEED ≈ 10–15 $/min** (speed_away = speed component moving AWAY from strike)

| config (block if both <) | test WR | lift vs 85.1% | keeps | blocked-set WR |
|---|---|---|---|---|
| dist<40 & speed_away<15 | **93.6%** | +8.5pp | 56% | 74.1% (losers removed) |
| dist<30 & speed_away<10 | 92.2% | +7.1pp | 67% | 70.5% |
| dist<25 & speed_away<10 | 92.0% | +6.9pp | 71% | 68.0% |

The blocked set sits at 68–74% WR while the kept set is 92–94% — the filter is genuinely
removing the losers, as the author claimed ("removed most of the losses"). These thresholds
align with his own data boundaries (his storm line = 15 $/min; his avg dist ≈ 49 $).

**Recommended default:** `THR_DIST=30, THR_SPEED=10` (keeps 67% of fires at 92% WR — best
WR×retention balance). Tighten to `40/15` if you want max WR and can afford to fire less.

## 4. 🚨 Critical caveat — high WR ≠ edge (this is a FAVORITE bet)
85% baseline WR means we're buying near-decided favorites (token ≈ 0.85+); the kept set
(dist≥30/40) is even deeper (token ≈ 0.93–0.97). Breakeven WR for buying at price p with
the 0.07 fee curve is ≈ p/(p+(1−p)(1−0.07p)) — e.g. **p=0.93 → breakeven ≈ 93%.** So WR
alone does NOT establish edge; the filtered 93.6% WR may just equal the token-implied prob.
This is exactly why the article author fires on **gaps** (cheaper entries, ~72% WR that
*beats* the implied prob), not on raw favorites.

**→ The edge test (Phase 2, required before any deploy):** overlay the L25 token entry
price at fire and keep only fires where **physics-WR > token-implied prob + fee** (the
"gap"). Use `engine_v2.fill_at_book` for real entry + 0.07-curve PnL. The physics signal +
WEAK_COMBO is the SELECTION layer; the gap vs token price is the EV layer. Without Phase 2,
treat these thresholds as a WR-improving filter, not a proven money-maker.

## 5. How to use in our designs
`physics_signal.physics_at(ts_us, px, strike, fire_us, slot_end_us)` → dict with
`dist, dist_abs, side, bet, speed, speed_away, cross, have_m, margin`. Drop into a
sniper_v5 gate: `g_physics_weakcombo` = block iff `dist_abs<30 and speed_away<10`. Pair
with the gap gate (token vwap below physics-implied) for the EV layer.

## 6. Next steps
1. **Phase 2 edge test** — L25 entry-price overlay → physics-WR vs token-implied (the gap). Decides real EV.
2. **derivative-of-speed** (article's open hypothesis): is speed rising/falling in last 30s? Add `d_speed` to `physics_at` and test as a 3rd gate (fading inertia → skip).
3. Sweep `have` (30/60/90/120s) and 15m-vs-5m separately; 15m baseline is already 91.9%.
4. ETH/SOL: same module, swap the feed; verify the dist/speed edge generalizes.
