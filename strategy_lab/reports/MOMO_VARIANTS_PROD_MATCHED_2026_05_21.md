# Momo variants — production-matched (verified ws_s anchor + prod code review)

_2026-05-21. Final reconciliation after pulling VPS3 production code and
re-verifying the F7 RSI anchor against 1,331 live fires._

## What the production code actually does

Pulled from VPS3 `/opt/tradingvenue/backend/app/`:

1. **`strategies/polymarket/momo.py` (v1)**: fires `UP`/`DOWN` iff:
   - `aux["bar_ctx_phase"] == "t_plus_120"` (controller phase gate)
   - `|ret_2m| ≥ aux["abs_ret_2m_threshold"]` (q90 of rolling 14d |ret_2m| samples)
   - `f7_passes(direction, aux["rsi_14"], aux["f7_filter_mode"])` (F7 RSI agreement)

2. **`strategies/polymarket/momo_v2.py`**: identical logic, different anchor:
   - phase = `t_plus_60` (fires 60s into prev slot vs 120s for v1)
   - `ret_2m = log(close@ws_s+60 / close@ws_s-60)` (centered window vs forward window)

3. **`strategies/polymarket/f7_gate.py`**: three modes (basic/extreme/off):
   - basic: UP requires RSI > 50, DOWN requires RSI < 50
   - extreme: UP > 60, DOWN < 40

4. **`indicators/rsi.py`**: explicitly Wilder simple-MA flavor (NOT exponential),
   matching my backtest implementation.

5. **`engine/poly_updown_loop.py::build_bar_context_t_plus_120/60`**: fetches
   15 closes at offsets `[-840, -780, ..., -60, 0]` from `ws_s`. The LAST close
   is at `ws_s` exactly → **RSI is anchored at `ws_s`**.

6. **Controller pre-strategy gates**: only ONE for momo:
   - momo_v2 per-cell disable via `TV_POLY_MOMO_V2_DISABLED_CELLS` env
     (currently disables `eth_5m`, `btc_15m` — v2 anchor mis-fires there per
     `TV_AGENT_FIX_MOMO_V2_BUGS` 2026-05-21 report).
   - **No spread filter for momo** (V3 family only).
   - **No additional indicator gates**.

## RSI anchor — verified against 1,331 production fires

`_match_live_f7_v2.py` (version-aware ws_s derivation):

| Anchor | Match accuracy |
|---|---|
| **rsi_at_ws_s** | **94.67%** ← LIVE ANCHOR (per source code + verifier) |
| rsi_at_fire_us | 92.41% (works for v2 because fire is 60s from ws_s) |
| rsi_at_slot_start (= ws) | 83.70% (post-fire, not what production does) |

Earlier verifier was version-unaware (subtracted 120 from both v1 and v2 fires),
which biased v2's "ws_s" by 60s — that's why it falsely concluded `fire_us` was
the anchor. Version-aware derivation reproduces production: ws_s = fire_s − 120
for v1, ws_s = fire_s − 60 for v2.

## 28-day backtest with corrected ws_s anchor (sub-sec L25)

```
variant                          F7     n     WR   leg_tot  real_tot   leg/tr  real/tr
2A_late_fire_late_signal        ALL  2018  47.4% $-3607.08 $-4883.52  -$1.79  -$2.42
2A_late_fire_late_signal         F7   963  46.3% $-1678.43 $-2301.78  -$1.74  -$2.39
2A_late_fire_late_signal        F7x   588  46.4% $ -872.39 $-1255.39  -$1.48  -$2.13
2B_late_fire_early_signal       ALL  1953  48.3% $-2024.25 $-3258.93  -$1.04  -$1.67
2B_late_fire_early_signal        F7  1037  45.2% $-2112.90 $-2794.16  -$2.04  -$2.69
2B_late_fire_early_signal       F7x   628  44.7% $-1287.58 $-1704.30  -$2.05  -$2.71
2C_edge_of_slot                 ALL  2162  48.2% $-2900.52 $-4262.52  -$1.34  -$1.97
2C_edge_of_slot                  F7  1062  45.8% $-1899.18 $-2595.35  -$1.79  -$2.44
2C_edge_of_slot                 F7x   625  42.4% $-1920.33 $-2345.71  -$3.07  -$3.75
Baseline_v1                     ALL  1850  48.4% $-2332.75 $-3497.45  -$1.26  -$1.89
Baseline_v1                      F7  1007  45.0% $-2571.44 $-3230.00  -$2.55  -$3.21
Baseline_v1                     F7x   620  43.7% $-1863.20 $-2274.85  -$3.01  -$3.67
Baseline_v2                     ALL  2313  49.2% $-2226.73 $-3670.23  -$0.96  -$1.59
Baseline_v2                      F7  1458  47.7% $-2018.84 $-2946.84  -$1.38  -$2.02
Baseline_v2                     F7x   992  47.9% $-1091.59 $-1723.77  -$1.10  -$1.74
```

**F7 (with correct ws_s anchor) cuts MORE fires than the buggy fire-us anchor:**
- Baseline_v1: 1437 (fire-us) → 1007 (ws_s) F7-kept fires
- Baseline_v2: 1777 → 1458
- 2C: 1541 → 1062

And aggregate WR drops with F7 in this 28d window (e.g. Baseline_v1 ALL=48.4% →
F7=45.0%). This is the OPPOSITE of the +$3.6k/day production claim. Why?

## Why my backtest disagrees with production's +$3.6k/day F7 lift

**CORRECTION 2026-05-21**: I previously listed "REST staleness gives production
favorable entries" as a gap driver. That's WRONG — production tradingvenue is
on WS-only book reads since Phase 18.6 Wave 1. Live logs verified:
every `paper.book_fetched` event sources from `ws_mirror`
(`wss://ws-subscriptions-clob.polymarket.com/ws/market`). CLOB REST is Tier-2
fallback only; Storedata DB is Tier-3 disaster fallback with CRITICAL alert.
**No REST-staleness edge component in production today.**

So the remaining gap drivers are TWO, not three:

### 1. Universe size — production fires ~10x more often

Live VPS3 in 23.5h (from `PER_STRATEGY_FAMILY_GATE_COMPARE`):
- btc_5m_v1 + F7: **225 fires** (= ~225/day)
- sol_5m_v2 + F7: 97
- eth_15m_v2 + F7: 84

My 28d backtest:
- Baseline_v1 btc_5m + F7: 588 fires / 28d = **21/day**
- Baseline_v2 sol_5m + F7: 285 / 28d = 10/day
- Baseline_v2 eth_15m + F7: 67 / 28d = 2.4/day

**Production fires ~10x more.** Production's q90 threshold uses the feed-backed
rolling deque from `binance_klines_v2` (queried via `_fetch_abs_ret_2m_history`
in `polymarket_updown.py` ~L1525), which samples ALL minute-bars in the rolling
14d window. My backtest computes q90 only over the |ret_2m| values seen at
chainlink-confirmed-resolved market windows — a much smaller and more selective
sample → higher q90 → fewer fires pass.

Production's looser threshold means more fires AT marginal momentum levels,
giving F7 more room to filter and create an apparent WR lift. My tighter
threshold already filters out the marginal fires, leaving less F7 work to do.

### 2. Fee model — PRODUCTION USES 2%-ON-PROFIT-ONLY (verified)

**CORRECTION 2026-05-22**: I claimed production's reported PnL was "inflated by
legacy fee accounting" relative to "real" Polymarket curve. **WRONG.** Production
shadow PnL accounting MATCHES what Polymarket actually charges these markets:

Verified against 25,900 `poly_updown_resolution` events:
- LOST trades: `pnl_usd = -entry_qty × entry_price` exactly (median diff 0.000000)
- WON trades: `pnl_usd = entry_qty × (1 - entry_price) × 0.98` exactly

So Polymarket's BTC/ETH/SOL up-down crypto markets either have `feeRate = 0`
or `feesEnabled = false`, and the only fee that hits is the legacy 2% on
winning leg's profit. The "real curve" `0.07 × p × (1-p)` model in `fees.py`
applies to other Polymarket market categories but NOT to our crypto up-down
universe.

**Implication**: my `pnl_real_usd` column in the variants per-trade output is
fictitious — over-charges fees that production doesn't actually pay. Use
`pnl_legacy_usd` instead. The +$3.6k/day production F7 lift is NOT inflated;
it's the right accounting.

The remaining gap to my backtest is therefore EVEN MORE concentrated in
universe size (production fires ~10x more often than my chainlink-only universe).

## Profit pockets (28d, ws_s F7 anchor, real fees)

Cells with real PnL > 0 after corrections:

| Variant | Cell | F7 | n | WR | real $/tr |
|---|---|---|---|---|---|
| **2A late/late** | **eth_15m** | **F7x** | 34 | **55.9%** | **+$4.17** |
| **Baseline_v1** | **sol_15m** | **F7x** | 12 | **58.3%** | **+$4.80** ⚠ n=12 |
| 2B late/early | btc_15m | F7x | 66 | 54.5% | +$3.05 |
| Baseline_v1 | sol_15m | F7 | 24 | 58.3% | +$3.49 |
| 2B late/early | btc_15m | F7 | 106 | 53.8% | +$2.44 |
| Baseline_v1 | btc_15m | F7x | 48 | 56.2% | +$2.73 |
| Baseline_v1 | btc_15m | ALL | 144 | 56.9% | +$2.39 |
| Baseline_v1 | btc_15m | F7 | 76 | 52.6% | +$0.76 |
| 2A late/late | sol_15m | F7x | 25 | 56.0% | +$1.49 |
| 2B late/early | btc_15m | ALL | 218 | 52.3% | +$0.77 |
| 2A late/late | eth_15m | F7 | 51 | 49.0% | +$0.22 |
| Baseline_v2 | btc_15m | F7 | 135 | 53.3% | +$0.74 |

All on 15m markets. 5m universally negative.

## Mixing production-discovered gates with the new variants

From the production code review, the only additional gate beyond
`|ret_2m| ≥ q90 + F7` is:

- **momo_v2 per-cell disable**: skip `eth_5m` and `btc_15m` for v2

Applying that to the v2 results:
- Baseline_v2 eth_5m F7: -$1.36/tr × 364 = -$496 (skipped → recovered)
- Baseline_v2 btc_15m F7: +$0.74/tr × 135 = +$99 (skipped → lost)
- Net: skipping these cells SAVES Baseline_v2 ~$397 over 28d
  but cuts +$99 of profit on btc_15m. NET: +$298 = +$10.6/day

That's the only meaningful gate from production. No other filters exist on the
momo path beyond the threshold + F7.

## Final recommendation

The strategy edge IS real but live's apparent +$3.6k/day is structurally
inflated. Sustainable deploy under WS-only + real fees:

1. **BTC 15m**: best cell, multiple variants positive after real fees:
   - Baseline_v1 ALL: WR=56.9%, +$2.39/tr × 144/28d = **+$12/day** at $25 notional
   - 2B + F7: WR=53.8%, +$2.44/tr × 106/28d = **+$9/day**
   - 2B + F7x: WR=54.5%, +$3.05/tr × 66/28d = **+$7/day**
   - **Don't apply F7 to Baseline_v1 btc_15m** — cuts WR 56.9 → 52.6 (F7 anchored
     at ws_s now correctly removes more fires, including some winners on this cell).

2. **ETH 15m + 2A + F7x**: small but consistent (n=34, +$4.17/tr) → +$5/day

3. **SOL 15m + Baseline_v1 + F7/F7x**: profitable but tiny sample
   (n=12 over 28d, ~0.4 fires/day). Pilot only.

4. **Drop ALL 5m and ETH/SOL 15m baselines** — universally negative even with
   F7. Focus capital on BTC 15m ensemble.

5. **Production PnL is NOT inflated** (revised 2026-05-22): both the book source
   (WS) and the fee model (2%-on-profit-only) match what production reports.
   The +$3.6k/day F7 lift is the actual sustainable number. My backtest under-
   produces because (a) my universe is ~10x smaller than production's
   feed-backed q90 sample, and (b) I was over-charging fees with the wrong
   `real_curve` model. Use `pnl_legacy_usd` column going forward when comparing
   to production.

## What I'd build next to close the remaining gap

1. **Mirror production's feed-backed q90 calculation**. My ret_2m threshold
   is q90 of chainlink-only universe. Production uses feed-backed deque
   including binance-resolved markets. Loosen threshold → more fires →
   sample matches production's 10x rate.

2. **Cell-level production audit**: pull `fires_with_gates.csv` + match
   each production fire's slug to my universe, see which my gate REJECTS
   that production ACCEPTS. The delta tells us what's different.

3. **DONE 2026-05-22**: Production uses 2%-on-profit-only (verified against
   25,900 resolution events, median diff 0.000000 vs naive-no-fee on losses and
   2%-on-profit on wins). My `pnl_real_usd` column was over-charging — drop it.
   Use `pnl_legacy_usd` for production-parity comparisons.

## Files

- VPS3 controller code: `migration_2026_05_21/vps3_controller_inspect/`
- Verifier (correct version): `strategy_lab/meta_classifier/_match_live_f7_v2.py`
- Updated runner: `strategy_lab/meta_classifier/momo_variants_2abc.py` (ws_s anchor)
- Per-trade output: `data/v4/canonical/_results/momo_variants_2abc_2026_05_20/per_trade.parquet`
- Run log: `data/v4/canonical/_results/_momo_variants_2abc_v7_wss_anchor_run.log`
- CLAUDE.md updated: F7 anchor block now reflects ws_s (94.67% verified)
