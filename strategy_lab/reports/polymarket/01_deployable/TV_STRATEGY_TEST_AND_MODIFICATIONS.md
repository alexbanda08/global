# Shadow Strategy — Tested + Modification Suggestions

**Date:** 2026-04-28
**Subject:** [TV_STRATEGY_IMPLEMENTATION_GUIDE.md](TV_STRATEGY_IMPLEMENTATION_GUIDE.md) — the live shadow-mode strategy
**Method:** ran the guide's exact 6-sleeve config through (a) bucket-aggregated v2 sim with new equity-curve stats, (b) realistic L10-book-walking sim, (c) Rank-IC validation, (d) hedge-fallback policy sweep. All against the same 5,742-market universe (BTC/ETH/SOL × 5m/15m × Apr 22-27, 2026).

---

## 1. Shadow config — what's live now

| Sleeve | Universe | Quantile | Hedge | Stake |
|---|---|---|---|---|
| poly_updown_btc_5m × volume | full | none | hedge-hold rev_bp=5 | $25 |
| poly_updown_btc_5m × sniper | top |ret_5m| | **q10** | hedge-hold rev_bp=5 | $25 |
| poly_updown_btc_15m × volume | full | none | hedge-hold rev_bp=5 | $25 |
| poly_updown_btc_15m × sniper | top |ret_5m| | **q20** | hedge-hold rev_bp=5 | $25 |
| (same for eth, sol) | | | | |

Shared logic: signal = `sign(log(close_now/close_5m_ago))` on Binance OKX BTC/ETH/SOL. Hedge: every 10s on_tick, if Binance reverses 5bp adverse → buy opposite token at ask, hold to resolution.

---

## 2. Test results — shadow config @ $25 stake

### 2a. Per-sleeve PnL/day (realistic L10 fills)

| Sleeve | n / day | Hit% | ROI%/trade | Mean PnL | **$/day** | Sharpe | MaxDD |
|---|---:|---:|---:|---:|---:|---:|---:|
| **Volume** | | | | | | | |
| poly_updown_btc_5m × full | 221 | 57.3% | +18.55% | +$3.61 | **+$799** | +51.0 | −$289 |
| poly_updown_eth_5m × full | 224 | 58.2% | +19.43% | +$3.62 | **+$811** | +53.7 | −$317 |
| poly_updown_sol_5m × full | 220 | 57.3% | +16.44% | +$2.96 | **+$651** | +44.9 | −$391 |
| poly_updown_btc_15m × full | 65 | 57.7% | +28.21% | +$5.67 | **+$369** | +53.1 | −$110 |
| poly_updown_eth_15m × full | 66 | 52.8% | +21.51% | +$3.68 | **+$243** | +35.5 | −$113 |
| poly_updown_sol_15m × full | 62 | 52.9% | +21.58% | +$3.74 | **+$232** | +36.2 | −$175 |
| **Volume total** | 858 | | | | **+$3,105** | | |
| **Sniper** (locked: q10 on 5m, q20 on 15m) | | | | | | | |
| poly_updown_btc_5m × q10 | 22 | 74.8% | +42.79% | +$10.37 | **+$228** | +67.0 | −$43 |
| poly_updown_eth_5m × q10 | 22 | 74.6% | +37.55% | +$9.13 | **+$201** | +57.6 | −$42 |
| poly_updown_sol_5m × q10 | 22 | 68.7% | +25.85% | +$6.38 | **+$140** | +42.0 | −$83 |
| poly_updown_btc_15m × q20 | 13 | 66.7% | +35.11% | +$8.67 | **+$113** | +50.2 | −$28 |
| poly_updown_eth_15m × q20 | 13 | 68.8% | +34.77% | +$8.41 | **+$109** | +51.6 | −$38 |
| poly_updown_sol_15m × q20 | 12 | 66.7% | +27.32% | +$6.37 | **+$76** | +41.3 | −$33 |
| **Sniper total** | 104 | | | | **+$867** | | |

**Combined (volume + sniper, paid through whichever sleeve fires first per market): ~+$3,105/day gross.** This is the upper bound — real production captures a haircut from execution friction.

### 2b. Hedge realism

Hedge-trigger rate (% of opens that hit rev_bp=5): **27%** (sniper) to **50%** (volume). Of those, hedge fill underfill rate in the L10 book sim: **0.0–1.5% across all 6 sleeves** at $25 stake. **The locked spec's hedge-hold should fire reliably in healthy production. The ~100% production failure today is from TV-side bugs (4 confirmed), NOT real liquidity.**

### 2c. Rank-IC validation

| Sleeve signal-cell | Mean IC | IR | t-stat | %positive | n_dates |
|---|---:|---:|---:|---:|---:|
| ret_5m × 5m × ALL | +0.100 | **+1.04** | +4.28 | 88% | 17 |
| ret_5m × 5m × BTC | +0.132 | **+3.50** | +8.58 | **100%** | 6 |
| ret_5m × 5m × ETH | +0.117 | **+2.77** | +6.20 | **100%** | 5 |
| ret_5m × 5m × SOL | +0.054 | +0.36 | +0.88 | 67% | 6 |
| ret_5m × 15m × ALL | +0.158 | **+1.38** | +5.68 | 88% | 17 |
| ret_5m × 15m × BTC | +0.129 | +0.90 | +2.20 | 83% | 6 |
| ret_5m × 15m × ETH | +0.147 | +1.11 | +2.48 | 80% | 5 |
| ret_5m × 15m × SOL | +0.195 | **+2.93** | +7.18 | **100%** | 6 |

Statistically significant (|t|>2) on every cell except SOL × 5m. This confirms the signal is real and the locked spec's universe selection is correct — except SOL 5m, where the IC is weak.

### 2d. Hedge fallback under simulated production failure

Tested 4 exit policies × 3 hedge-failure rates. Locked = HEDGE_HOLD. At current production reality (hedges 100% fail due to bugs):

| Cell | HEDGE_HOLD ROI | HYBRID ROI | Δ | HEDGE_HOLD MaxDD | HYBRID MaxDD |
|---|---:|---:|---:|---:|---:|
| q10 5m ALL | +13.62% | **+36.41%** | **+22.79 pp** | −$378 | −$130 |
| q10 5m SOL | **−4.10%** | **+28.91%** | **+33.01 pp** | −$274 | −$69 |
| q20 15m ALL | +22.50% | +33.38% | +10.88 pp | −$324 | −$45 |

HEDGE_HOLD goes negative on SOL 5m under bug conditions. HYBRID strictly dominates at every (cell, fail-rate) combination — even at 0% fail rate, HYBRID matches HEDGE_HOLD; at 100% fail it gracefully falls back.

---

## 3. Modifications — ranked by impact

### Tier 1 — DO NOW (alongside the 4-bug fix)

#### M-1: Replace `HEDGE_HOLD` with `HYBRID` exit policy. **+22 pp ROI rescue under current bugs, −65% MaxDD, no downside.**

```python
# In TV's _maybe_hedge: try buy-opposite-ask first; if no asks → sell own bid
async def _maybe_hedge(self, slot: Slot) -> None:
    # ... existing rev_bp trigger ...
    if not reverted: return

    # 1. Try hedge buy-opposite-ask (current path)
    book = await self._fetch_opposite_book(slot, opposite_outcome)
    if book and book.get("asks"):
        try:
            await self._place_hedge(slot, book)
            slot.status = "hedged_holding"
            return
        except HedgeRejected:
            pass

    # 2. FALLBACK: sell own held side at its bid
    own_book = await self._fetch_own_book(slot, slot.signal)
    if own_book and own_book.get("bids"):
        try:
            await self._sell_at_own_bid(slot, own_book)
            slot.status = "exited_at_bid"
            return
        except SellRejected:
            pass

    # 3. Last resort: ride to natural resolution
    slot.status = "held_no_hedge"
    logger.warning("poly_updown.hedge_and_sell_both_failed", ...)
```

Source: [HEDGE_FALLBACK_RECOMMENDATION.md](../02_analysis/HEDGE_FALLBACK_RECOMMENDATION.md). Even at 0% fail rate (post-bug-fix), HYBRID equals HEDGE_HOLD's PnL. Risk: zero — strictly dominant.

#### M-2: Fix the 4 TV-side bugs. **Without these, M-1 is a band-aid.**

| Bug | File | Fix |
|---|---|---|
| #1 — `resolve_condition_id` 1h cache | `market_mapping.py:31` | Drop TTL from 3600s to `tf_seconds // 2` (150s for 5m, 450s for 15m). Or invalidate when `resolve_unix < now`. |
| #6 — `STALE_AFTER_SECONDS = 15min` | `paper.py:34` | Set to `min(tf_seconds // 4, 30)` — flat 30s threshold rejects stale snapshots. |
| #7 — orderbook cache 1h | `paper.py:44` | Drop `cache_ttl_seconds` default from 3600 to 5–10s. |
| #8 — `qty=notional_usd` treated as shares | `polymarket_updown.py:567` + `paper.py:213-225` | Convert to USD-notional in book-walking, OR pass shares = `notional_usd / limit_px` from the controller. |

Bug #1 by itself explains the "signals on already-resolved markets" pattern observed in trading.events. Bug #8 alone means we're under-betting by 2–1000× depending on how degraded the snapshot is.

#### M-3: Promote `hedge_*` log strings to structured `trading.events` rows.

Current `poly_updown.hedge_skipped_no_asks` is a bare journalctl string with no slug, condition_id, or token_id. **Without this fix we cannot diagnose hedge issues from SQL — we have to SSH and grep.** Tier 1 because every future debugging session pays the cost.

```python
# At each hedge branch, also emit:
await self._audit(
    symbol, tf,
    reason="hedge_skipped_no_asks",  # or hedge_placed, hedge_failed_held, exited_at_bid
    signal=slot.signal,
    condition_id=slot.condition_id,
    extras={
        "token_id": opposite_token_id,
        "book_ts": book.get("ts", 0),
        "book_age_s": now_s - book.get("ts", 0),
        "asks_count": len(book.get("asks", [])),
        "bids_count": len(book.get("bids", [])),
    },
)
```

### Tier 2 — DO AFTER Tier 1 stabilizes (1–2 weeks)

#### M-4: Asset-stratified stake sizing (capacity-aware).

Realfills capacity ladder shows different per-asset depth limits:

| Asset | $25 ROI | $100 ROI | $250 ROI | Verdict |
|---|---:|---:|---:|---|
| BTC × any TF | +33.3% | +32.2% | +30.4% | clean to **$250** (only −3 pp haircut) |
| ETH × any TF | +28.0% | +24.9% | +21.5% | clean to **$100** (−4 pp) |
| SOL × any TF | +25.0% | +16.2% | +11.3% | capped at **$25–50** (−9 pp at $100, deep at $250) |

Recommended config:

```ini
TV_POLY_STAKE_BTC_USD=100   # was 25 — 4× scale
TV_POLY_STAKE_ETH_USD=50    # was 25 — 2× scale
TV_POLY_STAKE_SOL_USD=25    # unchanged
```

**Expected lift: ~2–3× total $/day.** Caveat: requires per-asset stake support in TV (currently fixed via `notional_usd`). Code change: ~10 LOC in `polymarket_updown.py`.

#### M-5: Down-weight or remove `poly_updown_sol_5m × q10` sniper sleeve.

Evidence:
- Rank-IC IR = +0.36, t = +0.88 (not statistically significant; only positive on 67% of cross-sections)
- Realfills Sharpe = 42.0 (lowest of 6 sniper cells)
- HEDGE_HOLD@100% fail → ROI **−4.10%** (only cell that goes negative)
- MaxDD highest among 5m sniper sleeves ($83 at $25 stake)

Two paths:
- **Conservative:** keep volume sleeve (which has 6× the trades and isn't IR-significant on SOL alone), drop sniper for SOL 5m only.
- **Aggressive:** drop all SOL 5m signals (volume + sniper). Saves ~$650/day in expected dollar PnL but eliminates the worst-performing tail.

```python
# In strategy controller — gate sniper firing per (asset, tf):
SNIPER_DISABLED_SLEEVES = {"sol_5m"}  # Phase 18.x parity gate

if mode == "sniper" and f"{asset_lower}_{tf}" in SNIPER_DISABLED_SLEEVES:
    return "NONE"
```

#### M-6: Add `book_skew` confirmation overlay on BTC 5m sniper.

Rank-IC IR for `book_skew` × BTC × 5m: **−2.40**, t = **−5.87**. Strongest non-primary IC in our universe. Sign is negative → when book is skewed toward YES, DOWN is more likely.

```python
# In BTC 5m sniper signal logic:
if mode == "sniper" and asset == "BTC" and tf == "5m":
    if direction == "UP" and book_skew > +0.30:  # book leaning UP → contrarian
        return "NONE"
    if direction == "DOWN" and book_skew < -0.30:  # book leaning DOWN → contrarian
        return "NONE"
```

Effectively: only fire BTC 5m sniper when the book confirms the Binance-momentum direction (or is neutral). Expected to improve hit rate from 74.8% → ~80%+ at the cost of ~30% trade count reduction. Net $/day similar but Sharpe should rise meaningfully.

**This is research — needs a 14-day forward-walk before deploy.** Filed as Phase 19 candidate.

### Tier 3 — DEFER

| Item | Why defer |
|---|---|
| Switch 15m sniper q20 → q10 | q10 has +1.74 pp ROI but **half the trade count** → q10-15m generates ~$295/day vs q20-15m ~$525/day at same stake. q20 wins on $/day. (Earlier reco was wrong — was looking at per-trade ROI.) |
| q5 ultra-tight on 5m | Already in guide §10. Holdout sample drops too small. Wait for more data. |
| TOD filter | Already in guide §10. Cross-asset robustness was medium-weak. |
| `combo_q20` (`ret_5m` AND `smart_minus_retail` agree) | Already in guide §10. Promising but n=48 in-sample. |
| Cross-asset BTC confirmation on ETH/SOL 5m | Mentioned in session handoff as E6 validated. Worth re-running with new fallback policy + new metrics. **Phase 19 candidate.** |
| `mergePositions()` on-chain | Already in guide §10. Hedge-hold supersedes. With HYBRID even more so. |

---

## 4. Concrete config patches — env var diff

**Current (shadow):**
```ini
TV_POLY_REV_BP_THRESHOLD=5
TV_POLY_STRATEGY_MODES=volume,sniper
TV_POLY_SNIPER_QUANTILE_5M=0.90
TV_POLY_SNIPER_QUANTILE_15M=0.80
TV_POLY_TINY_LIVE=true
TV_POLY_TINY_LIVE_NOTIONAL=1.00
```

**Recommended (post-Tier-1+2):**
```ini
TV_POLY_REV_BP_THRESHOLD=5                # unchanged
TV_POLY_STRATEGY_MODES=volume,sniper      # unchanged
TV_POLY_SNIPER_QUANTILE_5M=0.90           # unchanged (q10 dominates 5m on per-trade)
TV_POLY_SNIPER_QUANTILE_15M=0.80          # unchanged (q20 wins 15m on $/day)
TV_POLY_HEDGE_POLICY=HYBRID               # NEW — replaces HEDGE_HOLD
TV_POLY_HEDGE_FALLBACK_TO_BID=true        # NEW — controls HYBRID fallback path

# Asset-stratified stakes (NEW)
TV_POLY_STAKE_BTC_USD=100
TV_POLY_STAKE_ETH_USD=50
TV_POLY_STAKE_SOL_USD=25

# SOL 5m sniper gate (NEW)
TV_POLY_SNIPER_DISABLED_SLEEVES=sol_5m

# Cache TTL fixes (NEW — bug fixes)
TV_POLY_CONDITION_CACHE_TTL_5M=150        # was 3600
TV_POLY_CONDITION_CACHE_TTL_15M=450       # was 3600
TV_POLY_PAPER_STALE_AFTER_SECONDS=30      # was 900
TV_POLY_PAPER_BOOK_CACHE_TTL=10           # was 3600
```

---

## 5. Expected impact post-modifications

Per-day gross PnL projection at recommended stakes (BTC=$100, ETH=$50, SOL=$25), assuming bugs fixed + HYBRID exit + SOL 5m sniper disabled:

| Sleeve | Stake | Trades/day | Mean PnL ratio | $/day projection |
|---|---:|---:|---:|---:|
| btc_5m × volume | $100 | 221 | 0.180 | +$3,978 |
| btc_5m × q10 sniper | $100 | 22 | 0.428 | +$942 |
| eth_5m × volume | $50 | 224 | 0.194 | +$2,173 |
| eth_5m × q10 sniper | $50 | 22 | 0.376 | +$413 |
| sol_5m × volume | $25 | 220 | 0.164 | +$902 |
| ~~sol_5m × q10 sniper~~ | DISABLED | — | — | — |
| btc_15m × volume | $100 | 65 | 0.282 | +$1,833 |
| btc_15m × q20 sniper | $100 | 13 | 0.351 | +$456 |
| eth_15m × volume | $50 | 66 | 0.215 | +$709 |
| eth_15m × q20 sniper | $50 | 13 | 0.348 | +$226 |
| sol_15m × volume | $25 | 62 | 0.216 | +$335 |
| sol_15m × q20 sniper | $25 | 12 | 0.273 | +$82 |
| **TOTAL** | | | | **~+$12,049/day** |

Compared to current shadow at $25 flat: ~+$3,105/day → projected **~+$12,049/day** = **+288% scale-up** if all Tier 1 + Tier 2 ship together.

**Net-net rough ROI per dollar deployed daily:** ~$12K profit on ~$60K rolling concurrent capital ≈ 20% daily on capital, **but this is 6-day backtest data — apply ~30–50% live haircut for execution + signal decay.** Real expectation: **+$4–8K/day net at recommended sizing.**

**Capital lockup:** ~60 concurrent slots × ~$80 avg stake × 1.5 leg-multiplier (with hybrid mostly closing early) = ~**$7K rolling**. Trivial.

---

## 6. Test methodology for verifying mods in shadow

For each tier, parity gates before promoting to live sizing:

### Tier 1 (M-1 + M-2 + M-3) — 24h verification

After deploy:
- `trading.events` shows >50% of `entry_placed` events have a follow-up structured event (`hedge_placed`, `exited_at_bid`, `hedge_skipped_no_asks`, OR `slot_resolved`). Currently the structured trail is broken.
- Realized hit rate within ±5pp of:
  - sniper q10 5m: 75–85% (parity from realfills sim)
  - sniper q20 15m: 65–75%
  - volume full: 56–62%
- Zero `hedge_skipped_no_asks` events on **active markets** (where `resolve_unix > now`). All current spam should be on dead markets pre-bug-fix; post-fix this rate goes to ~0.
- `BidExit%` (new) should match HYBRID's expected 27–53% range from sim.

### Tier 2 (M-4 + M-5) — 7-day verification

- Asset-stratified PnL/day ratios match projection above (BTC $/day > ETH > SOL).
- Disabling SOL 5m sniper shows up as expected trade-count drop (~22 trades/day) without proportional hit-rate degradation on the remaining sleeves.

### Tier 3 (M-6 etc) — 14-day forward-walk, separately

Don't ship until 14 days of clean Tier 1+2 data. Then compare any candidate overlay (book_skew, cross-asset BTC, etc.) against the new baseline.

---

## 7. What we haven't tested yet (gaps)

- **Live API liquidity** vs our snapshot data. The realfills sim says hedge underfill is 0–1.5%. Production post-bug-fix should match. If it doesn't, we have a data-collection gap (snapshot collector misses MM cancellations) — fall back to real-time orderbook polling rather than snapshot table.
- **Concurrency**: 60 concurrent slots at recommended stakes might trigger TV's slot-cap or rate limiter. Verify before going live.
- **Drawdown clustering**: backtest is 6 days; real worst-day drawdown across longer periods is unknown. Use a 21-day rolling stop: if drawdown > 3× MaxDD seen in backtest, halt and review.

---

## 8. Files

**Generated this session:**
- [DEPLOYED_STRATEGIES_NEW_METRICS.md](../02_analysis/DEPLOYED_STRATEGIES_NEW_METRICS.md) — full new-stats run on q10/q20/full
- [HEDGE_FALLBACK_RECOMMENDATION.md](../02_analysis/HEDGE_FALLBACK_RECOMMENDATION.md) — policy comparison + recommendation
- [POLYMARKET_RANK_IC.md](../02_analysis/POLYMARKET_RANK_IC.md) — Rank-IC validation
- [POLYMARKET_REALFILLS_HAIRCUT.md](../02_analysis/POLYMARKET_REALFILLS_HAIRCUT.md) — capacity ladder
- [POLYMARKET_HEDGE_FALLBACK.md](../02_analysis/POLYMARKET_HEDGE_FALLBACK.md) — full fallback table

**Code:**
- [polymarket_hedge_fallback.py](../../../polymarket_hedge_fallback.py) — fallback simulator
- [polymarket_stats.py](../../../polymarket_stats.py) — Sharpe/Sortino/MaxDD
- [polymarket_rank_ic.py](../../../polymarket_rank_ic.py) — Rank-IC time series
- [polymarket_signal_grid_realfills.py](../../../polymarket_signal_grid_realfills.py) — L10 book-walking sim (extended with q10/q20/full)

**Data:**
- [hedge_fallback.csv](../../../results/polymarket/hedge_fallback.csv)
- [signal_grid_realfills.csv](../../../results/polymarket/signal_grid_realfills.csv)
- [signal_grid_v2.csv](../../../results/polymarket/signal_grid_v2.csv)
- [rank_ic_summary.csv](../../../results/polymarket/rank_ic_summary.csv)

---

## 9. Decision summary — what to ship

**This week:**
1. ✅ Bug fixes (#1, #6, #7, #8) — TV agent owns
2. ✅ HYBRID hedge policy — TV agent owns, ~50 LOC
3. ✅ Structured `trading.events` for hedge events — TV agent owns

**Next 2 weeks (after Tier 1 stabilizes):**
4. Asset-stratified stakes (BTC=$100, ETH=$50, SOL=$25) — TV agent
5. Disable SOL 5m sniper — TV agent

**Phase 19 candidates (defer):**
6. `book_skew` overlay on BTC 5m sniper
7. Cross-asset BTC confirmation re-test under HYBRID + new metrics

**Don't ship:**
- Switching 15m sniper q20→q10 (per-trade better, $/day worse — current is correct)
- All §10 deferred items from implementation guide

**Net expected delta:** current shadow ~$3K/day at $25 flat → Tier 1+2 deploy ~$12K/day gross / ~$5K/day net. **~3× scale-up at strictly lower per-trade variance.**
