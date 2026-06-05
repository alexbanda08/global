# Live-sleeve stop + forensics — eth_5m_hurst & btc_15m_ema50_ema800 (2026-06-01)

## Action taken (live, Ireland)
User requested STOP of the 2 LIVE sniper-v5 sleeves. Done, reversibly:
- These 2 were the entire LIVE allowlist (`TV_POLY_SNIPER_V5_LIVE_ALLOWLIST`), **$1 notional**
  (`TV_POLY_SNIPER_V5_LIVE_NOTIONAL_USD=1.0`).
- Backed up `/etc/tv/tradingvenue.env` → `.bak_20260601_233548`, flipped
  **`TV_POLY_SNIPER_V5_LIVE_ENABLED=true → false`** (master live gate; only these 2 are live; momo/vwap/
  maker/kalshi families unaffected), `systemctl restart tv-engine` → active. Verified env=false, engine up.
- **Revert** = set the flag back to `true` + restart.
- Real-money exposure was ~nil: `btc_15m_ema50_ema800_off600_down` placed **0** live; `eth_5m_l_ema50_hurst`
  placed **1** live (DOWN @ 0.64, **won**).

## "Why do they lose a lot?" — they DON'T. It's a measurement artifact.
The shadow JSONL (`/var/log/tradingvenue/sniper_v5/*.jsonl`, VPS3) logs `won` + `fill_vwap` but the
**`pnl` field is null/0** — it is NOT computed in-log. Any dashboard/aggregate reading PnL from that field
shows $0 / garbage → the source of the "lose a lot" impression.

**Reconstructed** realistic PnL ($25 notional, poly 0.07·p·(1−p) fee + $0.01 tx) from `won`+`fill_vwap`:

| sleeve | n (resolved) | WR | entry vwap (p25/med/p75) | total PnL | $/trade | wins (avg) | losses (avg) |
|---|---|---|---|---|---|---|---|
| btc_15m_ema50_ema800_off600_down | 127 | 81.1% | 0.56 / **0.81** / 0.95 | **+$845** | +$6.65 | 103 (+$14.24) | 24 (−$25.93) |
| btc_15m_..._down_H (HEDGE_LATE twin) | 109 | 79.8% | — / 0.74 / — | + (pos) | — | 87 | 22 |
| eth_5m_l_ema50_hurst_grandparent_v8 | 173 | 72.3% | 0.54 / **0.64** / 0.715 | **+$622** | +$3.60 | 125 (+$14.86) | 48 (−$25.75) |

Both are **net positive**, consistent with the btc-15m backtest (a genuine gate-clean edge).

## The REAL, honest catch — thin margin at live fill prices
The shadow fills cluster at **median entry 0.81** for btc-15m vs the backtest's **0.69**. At 0.81 the
**breakeven WR is 81.0%** and realized is **81.1%** → **razor-thin**. +EV on this 127-fire sample, but a
small WR dip flips it negative. The live engine fills the *expensive, later-confirmed* setups the backtest
didn't, because the off=600 read + 0.02 spread gate selects higher-priced slugs. So:
- NOT "losing a lot" (it's +$845 reconstructed).
- But the **harvestable edge is much thinner than the backtest (+$1.66 @ 0.69) implied** — it's marginal
  at the 0.81 prices it actually fills.

## Recommendations
1. **Fix the PnL logging/dashboard** — populate `pnl` in the §7 resolved record (won → notional·(1−vwap)/vwap
   − fee − tx; lose → −notional − fee − tx) so the dashboard stops showing false losses.
2. **Decide on re-enabling live** with eyes open: the edge is real but thin at the real fill distribution
   (0.81). If re-enabling, prefer a **lower entry-px cap** (e.g. only fire when the side vwap ≤ ~0.75) to
   avoid the razor-thin 0.81 zone — but re-validate that the lower-px subset keeps +EV (it likely thins n a lot).
3. Keep both in SHADOW with corrected PnL logging; accumulate ≥2–3 weeks before any live re-enable.
