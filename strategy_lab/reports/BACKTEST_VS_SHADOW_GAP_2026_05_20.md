# Why backtest >> shadow PnL — 2026-05-20

**User question**: "Our shadow sleeves running on Ireland don't have those PnL numbers. Why?"

**Short answer**: **Two compounding biases inflate the backtest, both legitimate concerns:**

1. **Data-coverage bias** — the delta L25 refreshes (May 7+) capture only ~20-25% of the slug universe vs the base refresh (Apr 22-May 6) which captures ~75%. Backtest fires drop from 200/day to 15/day after May 6 because the strategy can't fire on slugs it doesn't have data for. The +175% lift is ~95% driven by pre-May 6 data.

2. **Engine modeling gaps** — even within covered slugs, the simulator is too optimistic about fill rates. The +50% live haircut I baked into projections is **not enough**. Real haircut is more like 60-80%.

**Bottom line**: shadow on Ireland is the only ground truth. Trust shadow > backtest. **Revise live PnL expectation downward from $4.3k/day → $1.0-2.0k/day** until shadow confirms otherwise.

---

## 1. The fire-count cliff — data coverage proof

Backtest fires per day, PAT+ACC-M baseline on BTC 5m (FIXED sources, 26d):

```
Apr 24-May 6 (13 days):  189-277 fires/day  (65-97% of resolved slugs)
                          ^^^ healthy
May 7-19 (13 days):       3-41 fires/day    (1-15% of resolved slugs)
                          ^^^ cliff
```

Same trend on `PAT+ACC-M-t210-COMBO`. Same trend on every strategy variant. **It's a data property, not a strategy property.**

Diagnostic — sampled opening-book observations per day from each L25 source:

| Date range | L25 source | Unique slugs/day (sampled) |
|---|---|---:|
| Apr 22 - May 6 | refresh_2026_05_06 (base, 28M rows) | 110-148 |
| May 7-14 | refresh_2026_05_16 (delta, 19.5M rows) | 50-65 |
| May 16-19 | refresh_2026_05_19 (delta, 7.5M rows) | 78-95 |

Per-day L25 EVENT counts are dense across all 26 days (1.5-2.3M events/day). But the events are concentrated on FEWER SLUGS in the delta refreshes. The deltas capture ~20-35% of the universe's slugs vs the base file's ~75%.

→ **The "best" config wins the backtest mostly because it captures 95% of its PnL in the 13 days where the data is dense.**

| Period | n_fires (baseline) | sum PnL | fire rate |
|---|---:|---:|---:|
| Apr 24 - May 6 (13d) | 2,894 | $26,885 | **80%** |
| May 7 - May 19 (13d) | 162 | $2,159 | **4.5%** |

If the post-May 6 data had pre-May 6 coverage (80% fire rate), projected post-May 6 PnL would be roughly $27k (matching pre-May 6) → **doubling the 26-day total to ~$57k for baseline / $160k for COMBO** for BTC 5m alone.

In other words: the data is the bottleneck, not the strategy. **A live bot sees ALL slugs** (real WS feed, no missing data). So live PnL **could be 2× the backtest** — IF the engine model is right.

**But the engine model is NOT right.** See §2.

---

## 2. Engine modeling gaps — the optimism baked into the simulator

Reading the engine (`strategy_lab/backtests/fast_full_backtest.py`):

### 2.1 Maker queue position assumption (`open_bid_queue_ahead = bid_size_at_best`)

When we post a BID, the engine assumes:
- We're behind ALL displayed depth at our price (line 235)
- Only that displayed-at-posting-time queue must be consumed before we fill
- **New orders that join the queue AFTER us are not modeled**

In reality, during a 5-minute slug, dozens of other makers post BIDs at the same price. Our queue position fills with new arrivals. Real fill rate is probably **30-50% of simulated**.

### 2.2 Trade price-priority not respected

In `handle_trade` (line 363): `if price <= side_ss.open_bid + 1e-9` → fill us.

In real CLOB matching:
- A SELL trade hits the HIGHEST BID first
- If our BID is $0.42 and someone else has $0.43, our bid wouldn't be touched until $0.43 is exhausted
- The engine doesn't track competing bids at higher prices

**This overstates our maker fill rate, possibly 1.5-2×.**

### 2.3 PAT zero latency, zero slippage

In `check_and_fire_pat` (line 247):
- Fires INSTANTLY when `pair_cost < pat_max_pair_cost`
- Takes the full `pat_take_size` at displayed `best_ask`

Real bot:
- 85ms WS-to-decision latency (per the deployment spec)
- In 85ms the book often moves — pair_cost edge can collapse
- Taking 50 shares with displayed depth 8 walks the book to deeper levels at worse prices

**This overstates PAT PnL per fire, maybe 1.3-1.5×.**

### 2.4 Immediate merge (no gas, no time)

After PAT pair fire: `state.cash_recovered += pairs * 1.0` instantly.

Real merge:
- Polygon tx (~2 seconds)
- ~$0.01-0.05 gas per merge
- During 2s, positions are EXPOSED to outcome resolution

**Small bias (~5-10% overstated PAT) but real.**

### 2.5 Two-phase processing artifact

The engine processes ALL L25 events first (Phase 1), THEN all trades (Phase 2):
- Maker bids posted/updated during Phase 1
- At end of Phase 1, `state.open_bid` reflects the LAST bid post
- Phase 2 fills all trades against this final-state bid
- A trade at slug+30s that would have hit our then-current $0.42 bid instead fills against our final $0.50 bid

This MAY over- or under-state PnL depending on bid drift direction; the net effect averages out but adds noise per slug.

### Aggregate inflation factor

Conservative compound estimate:
- Queue position: 2-3×
- Price-priority: 1.5-2×
- PAT latency/slippage: 1.3-1.5×
- Immediate merge: 1.1×

If these stacked multiplicatively: ~4-9× overstatement. If they're partially correlated/non-stacking: ~2-3× overstatement.

**Reasonable haircut: divide backtest by 3-5 to estimate shadow PnL.**

---

## 3. Reconciling with shadow

Backtest projections (FIXED 26d, prior reports):

| Metric | Reported | After data-coverage correction | After engine haircut (÷4) |
|---|---:|---:|---:|
| 26d backtest best | $245,463 | ~$490k (if dense everywhere) | ~$122k |
| Per day | $9,441 | ~$18,800 | **~$4,700** |
| Live (50% haircut) | $4,720 | $9,400 | **~$2,350** |

So the realistic live PnL estimate, accounting for BOTH biases:
- Data coverage would double if extrapolated to dense (×2 up)
- Engine model overstates fills (÷4 down)
- Net: **÷2 from the +175% number → ~$2.4k/day live, not $4.7k**

If shadow on Ireland is showing closer to current spec ($1.5k/day), it's because:
- Live also has competing makers we don't model
- Live latency is real
- Live slippage on PAT is real
- The 50% haircut in my report was too generous

---

## 4. What we can actually do about this

### Confirm with shadow first

The Ireland VPS shadow logs (`/var/log/tv/maker/acc-m_*.csv`) are the ONLY ground truth. **What's the actual realized $/slug there?** If it's:

- **Close to backtest pre-May 6 numbers** ($9/slug baseline) → data coverage was the only issue, COMBO config still merits deployment
- **Half of backtest** ($4-5/slug) → engine modeling gaps confirmed, but COMBO might still help
- **A fraction (e.g. $1-2/slug)** → both biases compound, COMBO probably not worth the variance

I don't have local access to those logs. Pull from Ireland with `bash strategy_lab/monitoring/pull_shadow_logs.sh`, then run the monitor.

### Build a proper backtest-shadow comparator

Apples-to-apples: take the SAME slugs Ireland shadowed yesterday, run the backtest engine on them with the same config, compare per-slug PnL. The ratio gives the empirical haircut to use going forward.

Until we have this comparator, no projection is reliable.

### Fix the engine gaps (in priority order)

1. **Track competing bids at price** — when posting our BID, query L25 for all bids at that price level. Our queue position = sum(displayed size). Account for new bids arriving.
2. **Add 85ms latency** to PAT trigger — delay the book read by 85ms when evaluating fire condition.
3. **Book-walk on PAT takes** — when taking 50 shares with displayed depth 8, fill 8 at best_ask and walk to next levels.
4. **Charge gas on merge** — deduct $0.02 per merge from state.cash_recovered.

These are ~2 days of engineering. Would tighten the backtest-to-live gap from ~3-5× down to ~1.3-1.5×.

### Recommend pulling delta refreshes from Ireland directly

The delta refreshes from VPS3 capture only a subset of slugs. Why? Possibly:
- The collector restarts didn't backfill old slug subscriptions
- The migration log shows VPS3 collector started fresh after May 6
- Need to investigate `migration_2026_05_12/local_pull.sh` to see what it pulls

If we can pull a denser May 7+ L25 dataset, the backtest universe coverage would match the base file's 75-80% rate, and the projections would be on a uniform data baseline.

---

## 5. Honest revised recommendation

**Drop the $4.3k/day live projection.** Use:

- **Pessimistic (default for planning)**: ~$1-1.5k/day live with COMBO config. Roughly 60% better than current spec.
- **Realistic (if engine gaps don't all compound)**: ~$2-3k/day live with COMBO.
- **Optimistic (engine model is closer to right than I fear)**: ~$4k/day live, matching prior projection.

The shadow A/B test is the ONLY honest way to pick which range to plan around. **Do not promote to live until shadow shows ≥ 50% lift over current spec in 7+ days of data.**

### What's still valid in the prior recommendation

- **The +175% in-sample lift is robust across walk-forward** — the relative ordering of configs is stable
- **The COMBO config is unambiguously a winner over baseline in backtest** — even with engine gaps applied uniformly, COMBO beats baseline
- **The per-cell timing structure** (BTC delay, ETH/SOL no delay) is real

### What's revised

- **Absolute PnL projections** ($9.4k/day → $1-3k/day expected range)
- **The "50% haircut" is too generous** — use 60-75% haircut as default
- **The "deployment-ready" framing in prior reports was overconfident**
- **The COMBO config's variance (3× of baseline) is more concerning at the real PnL level** — drawdowns are absolute, not relative; if real PnL is $1k/day, a $100 daily drawdown is 10% — bigger relative hit

---

## 6. Files

```
strategy_lab/reports/BACKTEST_VS_SHADOW_GAP_2026_05_20.md   (this report)
```

Related artifacts in this session:
- `EXTENDED_WINDOW_REVALIDATION_2026_05_20.md` — should be read alongside this
- `PAT_HYPERPARAMS_FULL_SWEEP_2026_05_20.md` — projections in here are biased high
- `WALKFORWARD_AUDIT_2026_05_20.md` — relative lifts still valid

---

## 7. Bottom line

The user's instinct was right — there IS a gap between backtest and shadow, and it's not small. Two compounding biases:

1. **Data coverage** (post-May 6 deltas capture ~25% of slugs vs 75% in base) — this hides the strategy on most slugs and only shows the dense-data subset
2. **Engine model gaps** (queue position, price priority, PAT latency, slippage, gas) — these inflate per-fire PnL by maybe 2-3× even on covered slugs

**Net: backtest projections are ~3-5× too high.** The relative lift between configs (+175%) is still real and stable across walk-forward, but the absolute PnL numbers need a much heavier haircut than the 50% I was using.

**Trust shadow data**. When 7 days of Ireland shadow comes in, the realized lift over baseline is the only number worth planning around.
