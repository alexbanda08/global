# Kline-trained model → Polymarket (relative-value + regime) — 2026-06-03

Kline DIRECTION model (GPU LSTM, calibrated) trained on 8.8y, ONLY before 2026-03-15; applied to poly weeks (genuine OOS). Device=cuda.

## Kline model OOS next-bar accuracy (per asset×tf)
| cell | acc | n |
|---|--:|--:|
| BTC 5m | 0.511 | 22463 |
| BTC 15m | 0.52 | 7487 |
| ETH 5m | 0.524 | 22463 |
| ETH 15m | 0.523 | 7487 |
| SOL 5m | 0.526 | 22463 |
| SOL 15m | 0.511 | 7487 |

## (1) Relative-value on Polymarket (bet when model P(up) ≠ poly price by >margin)

margin(dev)=0.02, win07 fee, $25.

| set | n | $/tr | CI |
|---|--:|--:|--:|
| lockbox ALL (model side) | 4711 | -0.350 | [-0.68,-0.02] |
| lockbox RV-gated | 3712 | -0.279 | [-0.65,+0.10] |

## (2) Regime gate — poly UP-rate by kline regime (does regime predict poly direction?)

| regime | n | poly UP-rate | mean up_vwap |
|---|--:|--:|--:|
| uptrend | 9995 | 48.8% | 0.515 |
| downtrend | 8847 | 50.8% | 0.518 |
| low-vol | 15734 | 49.4% | 0.517 |
| mid-vol | 2869 | 51.2% | 0.517 |
| high-vol | 239 | 51.9% | 0.502 |

## Read
- Relative-value works ONLY if RV-gated $/tr beats ALL with lockbox CI>0 (model finds poly mispricing).
- Regime gate works if poly UP-rate diverges from mean up_vwap within a regime (kline regime predicts poly).
- Kline next-bar acc≈0.50 expected (efficient); the test is whether the poly PRICE is beatable, not the underlying.
- Confirm any positive on the different-window OOS before sizing.