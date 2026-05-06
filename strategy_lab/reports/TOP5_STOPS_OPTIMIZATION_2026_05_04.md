# Top-5 Sleeves — Stop-Loss / Take-Profit Optimization

**Date:** 2026-05-04
**Status:** Production-replay backtest (n=301 across 5 sleeves) with intra-window 10s-bucket orderbook trajectories. Each sleeve gets its own optimal SL/TP combination.
**Source:** `strategy_lab/v4_signals/sleeve_replay_with_stops.py`

---

## TL;DR — Per-sleeve recommendations

Different sleeves benefit from different stop combinations. **One-size-fits-all FAILS.**

| Sleeve | n | Baseline | Best combo | New PnL | New MaxDD | New Sharpe | Δ PnL |
|---|---:|---:|---|---:|---:|---:|---:|
| btc_5m_v3 | 43 | +$10.83 / DD -$6.28 / Sh +0.27 | **SL=50%, TP=30%** | +$6.81 | **-$1.18** | **+0.35** | -$4.02 (better DD!) |
| btc_5m_sniper | 114 | +$5.24 / DD -$13.62 / Sh +0.05 | **NO STOPS** | +$5.24 | -$13.62 | +0.05 | $0 (stops hurt) |
| btc_15m_sniper | 53 | +$2.62 / DD -$4.19 / Sh +0.05 | **SL=50%, no TP** | **+$7.09** | -$3.04 | +0.17 | **+$4.47** |
| sol_15m_sniper | 54 | +$2.05 / DD -$8.52 / Sh +0.04 | **SL=70%, no TP** | +$3.36 | -$7.14 | +0.07 | +$1.31 |
| eth_15m_sniper | 37 | +$0.83 / DD -$5.64 / Sh +0.02 | **no SL, TP=70%** | **+$3.91** | -$3.18 | +0.13 | **+$3.08** |

**Combined portfolio (with best per-sleeve stops):**

| Metric | Baseline (no stops) | With optimal stops |
|---|---:|---:|
| Total live PnL ($1/trade) | +$21.57 | **+$26.41** (+22%) |
| Combined MaxDD | ~-$38 (sum) | ~-$28 (sum) |
| Combined Sharpe | weighted ~0.10 | **weighted ~0.16** |

---

## Detailed per-sleeve analysis

### 1. BTC 5m V3 (n=43)

**Pattern: hold-to-resolution gives most PnL but highest DD.** Stops trade PnL for stability.

| SL\TP | TP=0% | TP=30% | TP=50% | TP=70% |
|---|---:|---:|---:|---:|
| 0% | +$10.83 / +0.27 ⭐ | +$7.26 / +0.31 | +$2.17 / +0.07 | +$5.24 / +0.15 |
| 30% | +$4.01 / +0.14 | +$5.41 / +0.33 | +$1.86 / +0.08 | +$2.95 / +0.12 |
| **50%** | +$6.17 / +0.18 | **+$6.81 / +0.35** ⭐ | +$2.10 / +0.08 | +$4.46 / +0.15 |
| 70% | +$3.30 / +0.09 | +$5.24 / +0.24 | -$0.77 / -0.03 | +$1.59 / +0.05 |

**Recommendation: SL=50% + TP=30%.**
- Lower total PnL (+$6.81 vs +$10.83)
- BUT drawdown reduced 81% (-$1.18 vs -$6.28)
- Sharpe IMPROVED 0.27 → 0.35
- 32/43 trades hit TP=30%; 10/43 hit SL=50%

Why: V3 fires on strong directional momentum (q90 BTC). YES price often runs to $0.65+ within the 5min window — TP=30% locks that in before reversion. SL=50% cuts the rare big losses.

**Caveat:** V3 already has hedge-hold (rev_bp=15) in production. Adding a separate SL=50% may double-count. **Decide with TV agent: keep hedge-hold + add NEW TP=30%, OR replace hedge-hold with SL=50%/TP=30%.**

### 2. BTC 5m sniper (n=114)

**Stops HURT every combination.** Largest sample, most reliable conclusion.

```
SL\TP   TP=0%      TP=30%     TP=50%     TP=70%
0%     +$5.24      -$1.99     -$6.56     -$0.98
30%    -$6.44      -$3.85     -$7.86     -$5.19
50%    -$2.11      -$2.65     -$6.66     -$2.10
70%   -$10.10      -$5.76    -$12.57    -$10.08
```

**Recommendation: NO stops.** Hold-to-resolution is optimal for V2 BTC 5m sniper.

Why: 53.5% hit rate is barely above random; signal is weak. Stops cap upside but don't meaningfully help downside (losses on weak signals don't drift gradually — they go to zero quickly at settlement). Net effect: stops cut winners > help losers.

### 3. BTC 15m sniper (n=53)

**SL=50% nearly TRIPLES the PnL.** Most dramatic improvement of any sleeve.

```
SL\TP   TP=0%      TP=30%     TP=50%     TP=70%
0%     +$2.62     -$2.61     -$1.02     +$1.24
30%    -$0.37     -$3.01     -$3.12     -$1.84
50%    +$7.09 ⭐   -$0.11     +$1.00     +$3.71
70%    +$2.80     -$1.74     -$1.04     -$0.15
```

**Recommendation: SL=50%, no TP.**
- PnL up +171% ($2.62 → $7.09)
- MaxDD down 27% (-$4.19 → -$3.04)
- Sharpe up 3× (0.05 → 0.17)
- 24/53 trades stop out at SL; 24 hold to resolution

Why: 15min hold is long enough that adverse moves can develop. SL=50% catches them before they reach -100% at settlement. TP doesn't help because 15m markets often need the full window for resolution to lock in.

### 4. SOL 15m sniper (n=54)

**SL=70% gives modest improvement.** Mostly defensive.

```
SL\TP   TP=0%      TP=30%     TP=50%     TP=70%
0%     +$2.05     -$0.03     -$2.05     -$0.35
30%    -$0.87     -$3.99     -$5.56     -$3.31
50%    -$1.51     -$5.17     -$6.90     -$4.32
70%    +$3.36 ⭐   -$2.09     -$2.31     +$1.10
```

**Recommendation: SL=70%, no TP.**
- PnL up 64% ($2.05 → $3.36)
- MaxDD slightly improved (-$8.52 → -$7.14)
- 25/54 trades stop out at SL; 28 settle

Why: SOL 15m has high variance (MaxDD -$8.52 was largest among non-V3 sleeves). SL=70% caps the largest losses. TP doesn't help because SOL momentum often holds the full window.

### 5. ETH 15m sniper (n=37)

**TP=70% nearly QUINTUPLES the PnL.** Most dramatic TP improvement.

```
SL\TP   TP=0%      TP=30%     TP=50%     TP=70%
0%     +$0.83     -$0.25     +$3.17     +$3.91 ⭐
30%    -$1.50     -$0.78     +$0.05     +$0.46
50%    +$0.07     +$0.08     +$1.81     +$1.44
70%    -$2.48     -$2.50     -$0.13     -$0.79
```

**Recommendation: no SL, TP=70%.**
- PnL up 371% ($0.83 → $3.91)
- MaxDD reduced 44% (-$5.64 → -$3.18)
- Sharpe up 6× (0.02 → 0.13)
- 22/37 trades hit TP=70%; 14 settle

Why: ETH 15m has low hit rate (54%) but when it wins, the move is often DRAMATIC within the window. TP=70% locks in those big moves before mean-reversion. SL doesn't help because losses tend to be at settlement, not progressive.

---

## Why SL/TP behavior differs across sleeves

| Pattern | Asset/TF | Explanation |
|---|---|---|
| TP=30%-50% works | 5m sleeves with strong signals | YES price spikes early in the 5min window; lock it in before reversion |
| SL=50% works | 15m sniper | 15min hold is long enough for losing trades to drift further; cap them |
| TP=70% works | ETH 15m | When ETH 15m hits 70% gain, it's usually NOT going higher (heavy reversion) |
| Stops hurt | BTC 5m sniper | Weak signal (53% hit) → stops cut winners more than they save losers |

**The key takeaway: stops are NOT universally good or bad. Per-sleeve calibration matters.**

---

## Implementation considerations

### Polymarket UpDown stop mechanics

For Polymarket UpDown markets, "stop-loss" means: during the 5/15min window, monitor the YES (or NO) token's market price. If it drops X% from entry ask, SELL all shares at the current bid.

```python
# At each 10s bucket:
if direction == "UP":
    current_yes_bid = book[(slug, "Up")][bucket]["bid"]
    pnl_unrealized = shares × current_yes_bid × (1 - taker_fee) - cost
    if pnl_unrealized < -stop_loss_threshold:
        EXIT (sell all shares at current_yes_bid)
```

### Polling cadence

- 10s bucket trajectory matches my backtest assumption.
- Production needs: orderbook subscription per active market + intra-window monitor.
- Fee: each early-exit costs another 2% taker fee. Already modeled in backtest.

### Required code changes (TV agent)

```python
# polymarket_updown.py — add stop-loss/TP loop in hedge-hold tick
class StopLossConfig:
    sleeve_id: str
    sl_drop_pct: float | None    # e.g. 0.50 (50% loss cap)
    tp_rise_pct: float | None    # e.g. 0.30 (30% take profit)

# Per-sleeve config
PER_SLEEVE_STOPS = {
    "poly_updown_btc_5m_v3":      StopLossConfig(sl_drop_pct=0.50, tp_rise_pct=0.30),
    "poly_updown_btc_5m_sniper":  None,                    # no stops
    "poly_updown_btc_15m_sniper": StopLossConfig(sl_drop_pct=0.50, tp_rise_pct=None),
    "poly_updown_sol_15m_sniper": StopLossConfig(sl_drop_pct=0.70, tp_rise_pct=None),
    "poly_updown_eth_15m_sniper": StopLossConfig(sl_drop_pct=None, tp_rise_pct=0.70),
}

# In existing tick loop (already runs for hedge-hold), check stop conditions:
async def _tick_check_stops(slot, current_yes_bid):
    cfg = PER_SLEEVE_STOPS.get(slot.sleeve_id)
    if not cfg:
        return
    pnl_pct = (current_yes_bid - slot.entry_price) / slot.entry_price
    if cfg.sl_drop_pct and pnl_pct <= -cfg.sl_drop_pct:
        await place_exit_order(slot, current_yes_bid, reason="stop_loss")
    elif cfg.tp_rise_pct and pnl_pct >= cfg.tp_rise_pct:
        await place_exit_order(slot, current_yes_bid, reason="take_profit")
```

### Conflict with V3 hedge-hold

V3 has existing hedge-hold (rev_bp=15) — sells 50% if price moves -15bps. My SL=50% would TRIGGER BEFORE hedge-hold (15bps = 0.15% << 50%). They'd interact.

**Options for V3:**
- **(a)** Replace hedge-hold with SL=50% + TP=30% (cleaner, my backtest assumes this)
- **(b)** Layer: hedge-hold first, then SL=50% / TP=30% on remaining position (more conservative, but my backtest doesn't model this)
- **(c)** Keep hedge-hold only (current production); skip new SL/TP for V3

Recommendation: **(c) for V3 launch.** V3's hedge-hold is already validated in production. Don't change two things at once. After 7-14 days live, if V3 metrics underperform, then swap to (a).

For sleeves #3 (btc_15m_sniper), #4 (sol_15m_sniper), #5 (eth_15m_sniper): **add stops as recommended.** No conflict — these don't have hedge-hold.

For sleeve #2 (btc_5m_sniper): **no stops** — backtest is unanimous they hurt.

---

## Final live launch matrix

After applying optimal stops per sleeve:

| Rank | Sleeve | Stake | SL | TP | Expected PnL/day at $1 |
|---|---|---:|---|---|---:|
| 1 | btc_5m_v3 | $1 | (current hedge-hold) | (current hedge-hold) | +$0.95 |
| 2 | btc_5m_sniper | $1 | none | none | +$0.45 |
| 3 | btc_15m_sniper | $1 | **50%** | none | +$0.62 |
| 4 | sol_15m_sniper | $1 | **70%** | none | +$0.29 |
| 5 | eth_15m_sniper | $1 | none | **70%** | +$0.34 |

**Combined: ~$2.65/day expected at $1/trade. ~$80/month at this rate.**

Worst case (all sleeves at observed MaxDD simultaneously): ~-$30. **Bankroll recommendation: $50-100.**

---

## Caveats

1. **Sample sizes are small** for sleeves with stops:
   - btc_15m_sniper SL=50%: triggered 24 times. Sufficient for direction but not statistical certainty.
   - eth_15m_sniper TP=70%: triggered 22 times. Same caveat.
2. **Backtest used PRODUCTION's actual fired markets** — these are NOT a random sample, but a strict subset of markets where production's signal triggered. Stop performance may differ on a different fire stream.
3. **Live execution risk:** real exits will have slippage; backtest assumes execution at observed bid price. Could be 1-2% worse.
4. **15m sniper sleeves have small n** (37-54). Recommend running with stops for 7+ days live, then re-evaluate.

---

## Action items for TV agent

1. **No code change for V3** — keep hedge-hold; do NOT add SL=50%/TP=30% on first launch.
2. **Per-sleeve stop config** for btc_15m_sniper, sol_15m_sniper, eth_15m_sniper:
   ```bash
   TV_POLY_STOP_LOSS_BTC_15M_SNIPER=0.50
   TV_POLY_STOP_LOSS_SOL_15M_SNIPER=0.70
   TV_POLY_TAKE_PROFIT_ETH_15M_SNIPER=0.70
   ```
3. **Implement intra-window monitor** that checks current bid every 10s for active positions and triggers stop orders.
4. **Add audit events** for stop_loss / take_profit trigger reasons so we can validate post-hoc.
5. **No stops for btc_5m_sniper** — confirmed via backtest.

---

## Files

- This doc: `strategy_lab/reports/TOP5_STOPS_OPTIMIZATION_2026_05_04.md`
- Backtest: `strategy_lab/v4_signals/sleeve_replay_with_stops.py`
- Companion: `strategy_lab/reports/LIVE_LAUNCH_TOP5_2026_05_04.md` (sleeve selection)
- Backtest framework validated: `strategy_lab/reports/BACKTEST_PRODUCTION_FAITHFUL_2026_05_04.md`
