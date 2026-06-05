# Wallet decode — @hightemptation / "HighTempTation" (2026-06-03)

`0x6011655c4afb76f36dd1b08a137a1ba73466b31e` (resolved from polymarket.com/@hightemptation via the
profile page's embedded `proxyWallet`). Pseudonym **HighTempTation** → weather/temperature specialist.

## Headline (lb-api truth + complete tape)
| metric | value |
|---|---|
| lifetime profit | **+$7,793** |
| **30d / 7d profit** | **+$2,768 / +$2,768** (all recent — currently hot) |
| lifetime volume | $140,888 |
| activity | 1,292 TRADE + **17 REDEEM** (feed complete, <3500 cap) |
| span | 2026-03-05 → 2026-06-03 |

## Strategy = weather nowcast SCALP (buy near-certain bucket, sell out early)
- **~100% weather/temperature markets** (276/282 markets; $129k of $129.3k notional). 6 tiny crypto test trades (−$10).
- **SELL-OUT, not hold-to-resolution:** 951 SELLs vs only 17 REDEEMs. **Median hold = 0.2 h (~12 min).**
- **Buys near-certain favorites:** entry price **median 0.95** (p10 0.75, p90 0.98). He buys the temperature
  bucket his forecast says will hit, **before the market fully converges**, then **sells as it firms toward
  ~0.98–1.0** — capturing the last few cents and exiting before resolution to recycle capital / dodge tail.
- **Sizing:** median $119/buy, up to $982. Meaningful size for weather books.
- **Market-WR 97.2%** (98.6% weather). Realized net +$7,473 (≈ lb $7,793 ✓, complete feed).
- **Ramping hard & currently winning:**
  | month | markets | net | WR |
  |---|--:|--:|--:|
  | Mar | 3 | $1 | 67% |
  | Apr | 8 | −$27 | 38% |
  | **May** | 199 | **+$4,850** | **99%** |
  | **Jun** | 72 | **+$2,649** | **100%** |

## Why it works (and the contrast with 0x331bf91c)
The earlier weather wallet `0x331bf91c` **held to resolution** and is lifetime-positive but fading / recently
flat. **This wallet SELLS OUT minutes after buying** — it monetizes the **convergence move** (e.g. bucket
goes 0.90→0.98 as the day's actual reading confirms) and avoids holding through resolution variance and the
hold-to-expiry fee drag. Same domain (weather forecasting edge), better execution: short holds, fast capital
recycle, 97–100% WR.

## Copy-trade verdict: ⚠️ Better than most, but marginal to COPY
- ✅ Currently very profitable (+$2.7k/7d), high WR, short holds, real edge, scaling.
- ❌ **Forecast/nowcast-driven** — the edge is a fast/accurate weather read; you can't replicate the signal,
  and by the time you copy his 0.95 entry the price is often already 0.97+ (the 3–5¢ edge is mostly gone).
- ❌ **Thin per-trade margin** (buys at 0.95 → ~3–5% upside) → late-copy slippage + weather-book illiquidity
  erases it. He's already sizing $400–980/trade, near the book's capacity.
- ❌ Weather markets are illiquid; a copier piling into the same buckets pushes price and self-competes.
- **Bottom line:** excellent wallet to **WATCH/study** (the sell-out-early weather scalp is a genuinely good
  pattern), but as a pure copy feed the edge doesn't survive the latency+slippage of following. To run it
  yourself you'd need your own fast temperature nowcast feed.

## Resolution method (for future)
Polymarket handles don't resolve via a clean API; fetch `https://polymarket.com/@<handle>` HTML and regex the
embedded `proxyWallet":"0x...`. (Got 0x6011655c, appears 31× + pseudonym "HighTempTation".)

## Artifacts
- `strategy_lab/wallet_hunt/cache/_6011_per_market.csv` — 282-market table (cat, n_buy/sell, cost, net, hold_hr).
- Script: `strategy_lab/wallet_hunt/decode_6011655c.py`.
