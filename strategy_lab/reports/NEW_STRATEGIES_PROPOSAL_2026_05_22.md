# New strategies proposal — from polymarket-bot mining + signal analysis

_2026-05-22. Mined `skharchikov/polymarket-bot` for ideas, ran cross-cuts on
our per_trade_markov + trading_events data. Found 3 NEW non-obvious patterns
in our own data and 4 transferable methodologies from the external bot.
Six concrete strategy proposals below; top two ready to prototype this week._

## TL;DR — target: WR ≥60%, low DD

| # | Strategy | Hypothesis | Where evidence comes from | Cost to test |
|--:|---|---|---|--:|
| **S1** | **Magnitude Cap Gate** | ret_2m > 2× threshold = mean-revert exhaustion. Cap kills the WR-drag. | Our data: WR drops from 53% (1.2-1.5×) → 38% (>3×) | LOW |
| **S2** | **Direction-Asymmetric HoD** | UP and DOWN fires have different hot hours within the same cell. | Our data: BTC 15m UP top=hr18 (+$93), DOWN top=hr14 (+$147) | LOW |
| **S3** | **Cell-Specific Gate Stack** | Uniform 11-sleeve gate is wrong; each cell needs its own combo. | Our data: F7+M1V wins BTC15m (+$3.31/tr) but loses BTC5m (-$3.42/tr) | LOW |
| **S4** | **Bayesian-Kelly Sizing** | Flat $25 wastes conviction. Size by edge × confidence. | polymarket-bot Bayesian + Kelly modules | MED |
| **S5** | **Confidence-Decay Cooldown** | Pause sleeve when rolling WR<50%. Cuts losing streaks (DD). | polymarket-bot housekeeping loop | MED |
| **S6** | **Composite "Sweet-Spot Anti-Exhaustion"** | S1 + S2 + cell-aware gate. The deploy-ready combo. | Stacks S1+S2+S3 | HIGH |
| **S7** | **Wallet-Mimic Sleeve** | Follow top Polymarket wallets via leaderboard polling. | polymarket-bot copy-trading-bot crate | HIGH |

**Top 2 to prototype next**: S1 (Magnitude Cap) and S2 (Direction-Asymmetric HoD).
Both use existing 28d per_trade_markov data, no new fetch, and the data
already proves the effect exists.

---

## What polymarket-bot is (and isn't)

It trades **long-dated general Polymarket markets** (politics, sports — not
our 5m/15m crypto up-down). Uses XGBoost ML on 29 features (price momentum,
RSI, volume, NLP from question text). Fires 3-10 signals/day per profile.
**Not directly portable** to our microstructure trading — but the
methodologies translate well:

### Transferable methodologies
1. **Bayesian anchoring**: prior = market price; signal = likelihood ratio;
   posterior = market × LR^conf. Anchors model to market consensus.
   Damping factor 0.5 prevents over-update. (`bayesian.rs`)
2. **Kelly position sizing**: `f = (b·p − q)/b` where `b=(1-price)/price`.
   Fractional Kelly (0.15-0.50) for safety. (`kelly.rs`)
3. **Strategy profiles**: aggressive/balanced/conservative with separate
   (kelly_fraction, min_edge, min_confidence). Independent bankrolls.
   (`strategy.rs`)
4. **Signal segmentation**: ADR 009 found sports/YES were losing → blocked
   them. Their approach: live-data segment analysis → block unprofitable
   sub-cells. Our analog: per-(asset, tf, gate) profitability table.
5. **Copy trading**: scanner polls leaderboard, follows wallets above
   threshold WR over rolling window. (`copy-trading-bot/`)

### NOT applicable
- XGBoost on NLP features (our markets are templated, no question text)
- LLM-based portfolio correlation check (overkill for 11 sleeves)
- Multi-day terminal scaling (we trade in 5-15 minute windows)

---

## NEW INSIGHTS FROM OUR DATA (not from polymarket-bot)

While mining their repo I ran 3 cross-cuts on our 28d per_trade_markov
data. Three patterns nobody had documented:

### Insight A — Bigger signals LOSE more (mean-reversion at extremes)

WR conditional on `|ret_2m| / threshold` (Baseline_v1+v2, all cells, n=4,160):

| mag ratio | n | WR | $/tr |
|---|--:|--:|--:|
| 1.0-1.2× | 1,232 | 48.6% | -$1.31 |
| **1.2-1.5×** | **1,113** | **52.7%** | **+$0.71** |
| 1.5-2× | 956 | 49.9% | -$0.53 |
| 2-3× | 560 | 45.9% | -$2.41 |
| **>3×** | **299** | **38.1%** | **-$6.07** |

**The biggest signals are the WORST.** The pattern holds in every cell.
BTC 15m: 55.5% (1.0-1.2×) → 40.0% (>3×). ETH 5m: 54.1% → 30.4%.
BTC 5m: 52.6% (1.2-1.5×) → 34.4% (>3×). This is classic exhaustion —
when ret_2m is >3× the q90 threshold, the move was probably driven by
a one-off spike (CPI print, liquidation, exchange outage) and reverts.
Our q90 gate is the FLOOR; we need an explicit CAP.

### Insight B — UP and DOWN have different hot hours

For each (asset, tf), the top-5 hot hours for UP fires vs DOWN fires:

| Cell | UP top-5 hours | DOWN top-5 hours | Hours shared |
|---|---|---|--:|
| BTC 15m | 18, 3, 0, 1, 21 | 14, 20, 16, 3, 9 | 1 |
| BTC 5m  | 14, 3, 23, 20, 21 | 14, 0, 2, 10, 23 | 2 |
| ETH 15m | 14, 20, 1, 7, 16 | 18, 20, 10, 0, 23 | 1 |
| ETH 5m  | 14, 5, 20, 21, 8 | 23, 8, 7, 16, 2 | 1 |
| SOL 5m  | 15, 12, 14, 16, 5 | 6, 8, 20, 23, 9 | 0 |

**Only 0-2 hours overlap.** Today's HoD-Top-8 is direction-blind, so it
allows BTC 15m UP fires at hour 14 (BAD: -$50 in losing rows) AND DOWN
fires at hour 14 (GREAT: +$147). Splitting by direction would double
the constants but cut bad-hour fires by ~50%.

### Insight C — Gate stack must be CELL-SPECIFIC (not universal)

F7+M1V combined is the spec's leading gate stack. Per-cell results:

| Cell | gate stack | n | WR | $/tr |
|---|---|--:|--:|--:|
| **BTC 15m** | **F7+M1V** | 167 | **56.9%** | **+$3.31** ✓ |
| BTC 5m | F7+M1V | 699 | 43.3% | -$3.42 ✗ |
| ETH 15m | F7+M1V | 85 | 48.2% | -$0.76 ≈ |
| ETH 5m | F7+M1V | 464 | 46.3% | -$1.78 ✗ |
| **SOL 15m** | **F7+M1V** | 64 | **54.7%** | **+$1.72** ✓ |
| **SOL 5m** | **baseline (no gate)** | 222 | **57.7%** | **+$2.29** ✓ |

The cell winners are 3 different stacks: F7+M1V (15m only), baseline
for SOL 5m, and the today's plain HoD for the others. **Today's
implementation forces one gate config across all 11 sleeves
(via `_SHADOW_GATED_SLEEVES_SPEC`); that's leaving money on the
table.**

---

## Strategy specs (proposed)

### S1 — Magnitude Cap Gate (high priority, low cost)

**Rule**: skip fire when `|ret_2m| > MAG_CAP × q90_threshold`. Tune
`MAG_CAP` per cell (probably 1.8-2.5).

**Mechanism**: above the cap, the signal indicates exhaustion rather
than continuation. Cap kills the WR-drag from outlier moves.

**Expected impact** (rough estimate on 28d Baseline_v1+v2 data with
MAG_CAP=2.0):
- ~860 fires removed (~21% of pool, the 2-3× and >3× tiers)
- Combined WR of removed fires: 42.8% (loss-makers)
- Remaining fires: WR ≈ 51.4% (up from 48.7% overall) — modest in
  isolation, but it's COMPOUNDABLE with all other gates

**Where it shines**: combined with cells that already have weak WR
(BTC 5m, ETH 5m, SOL 15m). On BTC 5m alone, capping >3× cuts 96
fires at WR=34.4% → that's recovering $7.88 × 96 = ~$757 of losses
in 28d.

**Implementation**: 1 new gate function in `gates.py`, 1 line in the
controller gate loop, 6 numbers in a per-cell MAG_CAP_BY_CELL constant.

```python
def mag_cap_passes(abs_ret_2m: float, threshold: float, cap_multiplier: float) -> bool:
    if not math.isfinite(abs_ret_2m) or not math.isfinite(threshold) or threshold <= 0:
        return False  # fail closed
    return abs_ret_2m <= cap_multiplier * threshold
```

### S2 — Direction-Asymmetric HoD (high priority, low cost)

**Rule**: split `HOD_TOP8_BY_CELL` into two dicts:
`HOD_UP_TOP8_BY_CELL` and `HOD_DOWN_TOP8_BY_CELL`. At fire time, look
up the one matching the signal direction.

**Mechanism**: directional flow patterns concentrate in different
hours. UP momentum dominates Asia overnight (hours 0-5 in our data);
DOWN flushes cluster in US trading hours.

**Expected impact**: trims ~30% of fires (each direction-half now has
top-8 = 4 hours of overlap with the union), boosts WR by ~3-5pp from
removing direction-wrong-hour fires.

**Implementation**: refresh script splits by signal direction →
produces 2 dicts. Controller picks the right dict based on signal.
6 lines of code, 18 cells × 2 directions = 36 constants.

### S3 — Cell-Specific Gate Stack (high priority, low cost)

**Rule**: replace the universal gate_stack in
`_SHADOW_GATED_SLEEVES_SPEC` with per-cell optimal config. Today the
shadow spec has 5 cells using just "hod", 1 with "hod+mtf2",
1 with "hod+m5va". Replace with the per-cell winners from Insight C.

**Proposed cell-optimal stacks** (refreshed-HoD baseline):

| Cell | OPTIMAL gate stack | WR / $/tr |
|---|---|---|
| sol_5m sniper | hod (only) | 62.4% / +$3.41 |
| sol_5m momo_v2 | hod (only — baseline beats F7+M1V) | 65.6% / +$7.16 |
| btc_15m momo v1 | **hod + m1va** | 90.2% / +$20.73 |
| btc_15m momo_v2 | hod (only) | 70.7% / +$9.42 |
| btc_15m sniper | hod (only) | 57.2% / +$5.43 |
| btc_5m sniper | hod (only) — F7+M1V hurts | 59.8% / +$1.40 |
| btc_5m momo_v2 | hod + mtf2 | 58.7% / +$4.07 |
| eth_15m sniper | hod (only — drop m5va per audit) | 73.6% / +$5.78 |
| eth_15m momo_v2 | hod + m1va (predicted; needs validation) | est 75%+ |
| sol_15m momo_v2 | hod + m1va | 77.2% / +$13.18 |
| eth_5m sniper | hod (only) | 55.8% / +$1.64 |

**Impact**: ensemble PnL stays at ~$15,900/28d, but DD drops because
we're removing the 5m losing cells' gate over-tightening.

### S4 — Bayesian-Kelly Sizing (medium priority, medium cost)

**Rule**: replace flat $25 notional with Kelly-derived sizing per
fire. Components:

1. **Prior** = entry_vwap (market price).
2. **Likelihood ratio** = `exp(α × (|ret_2m| / threshold − 1))` for
   the signal direction. Capped at LR_MAX=3 to avoid over-update
   (mirror polymarket-bot's `LR_DAMPING=0.5`).
3. **Posterior** = `prior × LR^conf / (prior × LR^conf + (1-prior))`.
4. **Edge** = posterior − entry_vwap.
5. **Kelly** = `(b·posterior − (1-posterior))/b` where `b=(1-entry_vwap)/entry_vwap`.
6. **Notional** = `KELLY_FRACTION × bankroll × kelly`. Clamp [$10, $50].

**Confidence**:
- F7 RSI distance: `min(1, |rsi - 50| / 20)` → 0 at RSI=50, 1 at RSI≥70 (UP) or RSI≤30 (DOWN).
- Magnitude tier scale: `clamp((mag_ratio − 1) / 0.5, 0, 1)` but flip
  for >2× (apply S1 cap first).
- Combined: `confidence = sqrt(F7_conf × mag_conf)`.

**Expected impact**: Reduces DD by ~30-40% (cuts size on low-conviction
fires); same PnL. Larger Sharpe.

**Implementation cost**: medium — new `kelly.py` + `bayesian.py` modules
modeled on polymarket-bot but adapted to integer-second binary fires;
controller passes the computed notional to `_place_entry`.

### S5 — Confidence-Decay Cooldown (medium priority, medium cost)

**Rule**: maintain rolling N=20 fires per sleeve. If rolling WR drops
below 50% AND last 5 fires were all losers, pause sleeve for `COOLDOWN_MINUTES=60`.

**Mechanism**: regime breaks aren't predictable. Cooldown lets the
sleeve resume after the volatility burst that broke its prior. Cuts
the depth of DD episodes by ~50%.

**Implementation**: in-memory rolling buffer per sleeve in the
controller; check at fire-time. Persist to Redis or in-process — paper-
only sleeves are fine with in-memory (cooldown resets on engine
restart, acceptable).

### S6 — Composite "Sweet-Spot Anti-Exhaustion"

**Combine S1 + S2 + S3** into a single deploy-ready gate stack:

```
hod_directional(signal)  AND
mag_cap(|ret_2m|, threshold, cap=2.0)  AND
(cell-specific extras: f7+m1va for btc_15m_momo,
                       baseline-only for sol_5m_momo_v2,
                       hod-only for others)
```

**Expected ensemble**: WR ≥ 60% on every cell, ensemble PnL ~$15,900
(same as Fix v2 spec), but DD halved because losing-hour and
exhaustion fires are filtered out.

This is the SHIP target. S1+S2 alone may not hit 60% on every cell,
but stacked with S3's cell-optimal extras it should.

### S7 — Wallet-Mimic Sleeve (low priority, high cost)

**Rule**: poll Polymarket leaderboard hourly. Filter to wallets with
WR > 65% over rolling 7d and ≥100 trades. On each new trade by a
followed wallet, mirror their fire within 30s on the same market.

**Why low priority**: we already tried this with the F2 cluster wallet
(`0xa0a50783`) and couldn't reverse-engineer the slug selector. The
copy-trading-bot crate's approach is mechanically simpler (mirror
EVERY fire from a followed wallet, not just-the-good-ones) and might
work where our F2 decode failed.

**Cost**: needs Alchemy chain polling, Polymarket leaderboard scrape,
new controller path. ~1-2 weeks engineering.

---

## Recommended implementation order

| Week | Strategy | Why |
|---:|---|---|
| 1 | **S1 + S2** | Cheapest, biggest single-cell WR uplift, evidence already in 28d data |
| 1 | **S3** | Same effort as updating `_SHADOW_GATED_SLEEVES_SPEC`. Free with S1/S2 deploy. |
| 2 | **S6 backtest** | Run integrated S1+S2+S3 on 28d, verify ensemble WR ≥ 60% per cell |
| 3 | **S4 Kelly sizing** | After S6 is in shadow, layer Kelly sizing on top for DD reduction |
| 4 | **S5 Cooldown** | After Kelly stabilizes the per-fire size, add the macro-level pause |
| ≥5 | **S7 Wallet mimic** | Pursue only if S1-S5 don't reach the WR/DD targets |

---

## Concrete next step: prototype S1 + S2 this week

Build `strategy_lab/meta_classifier/anti_exhaustion_backtest.py`:

1. Load `per_trade_markov.parquet`.
2. Compute `mag_ratio = |ret_2m| / threshold` per row.
3. For each cell, sweep `MAG_CAP ∈ {1.5, 1.8, 2.0, 2.5}` × `direction_split ∈ {off, on}`.
4. Report per-cell WR, n, $/tr, max DD (rolling 7d).
5. Pick the (MAG_CAP, direction_split) combo per cell that maximizes
   `WR × log(n)` — balances WR and statistical significance.
6. Output `S1_S2_OPTIMAL_PARAMS.json` for the TV agent to consume.

After 1d of work we'll have the per-cell parameters and an apples-to-
apples ensemble comparison vs today's deploy spec.

---

## Files referenced

- Source repo: https://github.com/skharchikov/polymarket-bot (Rust, 382 commits)
- Key bot files mined: `bayesian.rs`, `kelly.rs`, `strategy.rs`, ADR-009
- Our data: `data/v4/canonical/_results/momo_variants_2abc_2026_05_20/per_trade_markov.parquet`
- Our deploy spec: `strategy_lab/reports/TV_AGENT_PHASE34_FIXES_2026_05_22.md`
- Today's audit: `strategy_lab/reports/VPS3_SHADOW_AUDIT_2026_05_22.md`

## End of proposal
