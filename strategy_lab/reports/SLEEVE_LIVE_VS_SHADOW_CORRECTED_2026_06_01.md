# CORRECTED forensics — live vs shadow for the 2 stopped sleeves (2026-06-01)

⚠️ **Supersedes `SLEEVE_STOP_FORENSICS_2026_06_01.md`**, which wrongly concluded "they don't lose."
That report analyzed the SHADOW engine (which IS +positive) and missed the LIVE wallet (which LOSES).
The user was right; the live wallet is ground truth.

## The data
| sleeve | mode | n | WR | ROI | PnL | stake |
|---|---|---|---|---|---|---|
| btc_15m_ema50_ema800_off600_down | **LIVE** | 17 | **59% (10/17)** | **−30.3%** | **−$5.29** | $1 |
| btc_15m_..._off600_down_H | shadow | 109 | 80% (87/109) | +27.4% | +$149.56 | $5 |
| eth_5m_l_ema50_hurst_grandparent_v8 | **LIVE** | 32 | **50% (16/32)** | **−31.3%** | **−$10.02** | $1 |
| eth_5m_l_ema50_hurst_grandparent_v8 | shadow | 173 | 72% (125/173) | +15.2% | +$131.79 | $5 |

**Same strategy/signal → live WR is ~21pp below shadow** (btc 59 vs 80; eth 50 vs 72). ROI flips from
+27%/+15% (shadow) to −30%/−31% (live).

## Live = priced-out / negative (from the actual trades)
Live entry prices span the WHOLE spectrum and WR ≈ or below entry price (efficient market):
- BTC DOWN wins @ {0.62,0.78,0.83,0.97,0.98}, losses @ {0.26,0.83,0.79} → WR 62% < avg entry 0.76 → losing.
  Pattern: small wins `(1−p)/p`, full **−$1.00** losses → net negative after fees.
- ETH UP: WR 53% << avg entry ~0.67 → losing badly (−$3.93 over the 15 sampled).
The −$1.00 losers at 0.26/0.45/0.50/0.53 (underdog entries) are the killers — the strategy fired the
UNFAVORED side and lost the full stake.

## Why the shadow/backtest overstated WR (the diagnosis)
- **Shadow records favorable entries** (btc median **0.81** = the trending/favored side) with perfect
  as-of timing. At 0.81 the win rate is ~81% (efficient) → shadow looks +EV.
- **LIVE fills across 0.26–0.98**, including the underdog side. The live order is placed hundreds of ms
  after the signal, into a **moved WS book** (latency + the documented canonical-L25-vs-live-book
  divergence). It transacts at the true, adverse, post-signal price → WR drops to (or below) the base rate.
- eth-5m collapses as hard as btc-15m → the driver is **execution/latency/fill-price**, not the signal.

## Honest retraction + reconciliation
The "second validated edge" (btc-15m ema50_ema800 DOWN, +$1.66/trade, WR 82% in backtest; +$845 in shadow)
was a **FILL-MODEL ARTIFACT**. The LIVE wallet proves the real result is **priced-out + execution drag
(negative)**. This is fully consistent with `EFFICIENT_MARKET_FINDING_2026_05_28.md`: there is no
reproducible directional edge on these markets — the backtest and shadow hid it behind optimistic fills
(favorable entry price + zero-latency timing the live engine cannot achieve).

**Implication for the whole directional program:** any sleeve whose backtest/shadow edge depends on the
entry PRICE being favorable (vs the live-executable price) is suspect. The live wallet is the only ground
truth. Stopping these was correct.

## Status
- Both LIVE sleeves STOPPED: `TV_POLY_SNIPER_V5_LIVE_ENABLED=false` (env backed up `.bak_20260601_233548`),
  tv-engine restarted + active. Live exposure was small ($1 notional; −$5.29 + −$10.02 ≈ −$15 total).
- Recommendation: do NOT re-enable. If any directional sleeve is reconsidered, validate on a **live
  paper-fill model that uses the real WS book + latency at the actual order moment**, not the canonical
  L25 snapshot — and require the LIVE WR (not shadow/backtest WR) to beat the entry-implied price.
