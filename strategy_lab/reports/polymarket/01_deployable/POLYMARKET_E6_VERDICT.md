# E6 Cross-Asset Leader — Verdict

**Status:** validated as ETH/SOL × 5m augmentation. Clean timeframe split.

## Recommended deployment

Apply BTC-confirmation filter (S2) on **5m ETH/SOL markets only**:

```
if asset in ["eth", "sol"] and timeframe == "5m":
    sig_own = q10(own_ret_5m)        # ETH/SOL ret_5m, q10 quantile
    sig_btc = q10(btc_ret_5m_at_ws)  # BTC ret_5m at the same window_start
    if sig_own == sig_btc and sig_own != -1:
        trade(direction=sig_own)
    else:
        skip()
else:
    # use baseline q10/q20 logic per existing TV guide
```

For 15m markets and BTC markets: **use existing q10/q20 baseline** (S2 doesn't help, sometimes hurts).

## Key numbers

In-sample (cross-asset Apr 22-26, ETH+SOL × 5m):
- S2 (own + btc agree): n=181, hit **85.1%**, ROI **+28.73%**
- Baseline (own_q10): n=290, hit 79.4%, ROI +23.38%
- **Lift: +5.36pp** with 38% reduction in trade volume

Holdout (chronological 80/20):
- 5m × ETH: +7.85pp lift (n=8, hit 87.5%)
- 5m × SOL: +1.79pp lift (n=9, hit 88.9%)
- Both holdout cells have ROI CI strictly above zero

Day-by-day (in-sample 5m + 15m): 4/5 days S2 beats own_q10.

## Why it works on 5m

Cross-asset correlation is highest on short timeframes. When BTC and ETH both signal UP simultaneously, the move is **market-wide and synchronous** — high-conviction continuation.

When they diverge, it's idiosyncratic noise — likely to mean-revert before resolution.

## Why it fails on 15m

By 15 minutes, individual asset price discovery dominates. BTC's instant signal at ws=0 has decayed by ws+15min. The filter removes valid ETH/SOL trades whose own ret_5m signal has already diverged from BTC's.

## Files

- [polymarket_cross_asset_leader.py](../polymarket_cross_asset_leader.py) — full lag sweep grid (S0-S3 × 5 lags)
- [polymarket_cross_asset_validate.py](../polymarket_cross_asset_validate.py) — per-asset / per-day / forward-walk
- [POLYMARKET_CROSS_ASSET_LEADER.md](POLYMARKET_CROSS_ASSET_LEADER.md) — full grid results
- [POLYMARKET_CROSS_ASSET_VALIDATE.md](POLYMARKET_CROSS_ASSET_VALIDATE.md) — validation report

## Caveats

- **Holdout n is tiny** (8-9 per cell). CIs wide. Lift is real but precise magnitude uncertain.
- **Trade-volume cost: -38%** on ETH/SOL 5m (S2 fires only when both signals agree).
- Combined with q10 baseline (already 50% volume reduction vs q20), total ETH/SOL 5m volume drops to ~30% of original q20-volume. Compensated by higher precision.
- **Lag=0 (synchronous) is best.** Lagged BTC signals (30-120s ago) all UNDERPERFORM. The information transmits in <30 seconds.
- The "divergence" signal (S3, bet on ETH/SOL to catch up to BTC) had n=0-5 — far too sparse to test. Future work could use a lower threshold to trigger more often.
