# Wallet analysis — 0x331bf91c (weather-market trader) — copy-trade assessment 2026-06-03

`0x331bf91c132af9d921e1908ca0979363fc47193f`

## Data caveat (read first)
Polymarket's `/activity` TRADE feed is **capped at 3500 rows** for this wallet → it only reaches back to
**2026-02-20**, while REDEEMs reach back to 2025-09-18. So pre-Feb-20 buy costs are MISSING; any tape-based
$ before then is inflated (markets show cost=$0 + big redeem). **All-time $ is taken from lb-api (official,
server-side, trustworthy). Detailed per-market $ is restricted to the complete-feed window (≥ 2026-02-20).**

## Headline (official lb-api — truth)
| metric | value |
|---|---|
| **lifetime profit** | **+$65,203** |
| **30d profit** | **+$467** |
| 7d profit | +$467 |
| lifetime volume | **$1,542,883** |
| **30d volume** | **$3,006** ← activity has collapsed |
| open positions | 6 (~$3,004) |
| first activity | 2025-09-18 (≈8.5 months) |

## What he trades
**~100% weather/temperature markets** — "Will the highest temperature in {Miami/Seattle/NYC/Atlanta/Dallas/
SF/Chicago/Seoul} be between X-Y°F/°C on {date}?" In the clean window: **721/726 markets are weather**, 5 other.

## Complete window (≥ 2026-02-20, both legs captured) — 726 markets
| metric | value |
|---|---|
| realized net | **+$46,698** |
| capital deployed (cost) | $169,058 |
| **ROI on deployed** | **27.6%** |
| market win-rate (net>0) | **57.2%** |
| weather net / non-weather net | +$46,609 / +$89 |

### Monthly (clean window) — the trend that matters
| month | markets | deployed | net | WR |
|---|---|---|---|---|
| 2026-02 | 114 | $19,436 | **+$14,443** | 45.6% |
| 2026-03 | 302 | $108,635 | **+$20,040** | 58.9% |
| 2026-04 | 250 | $34,833 | **+$14,941** | 59.6% |
| 2026-05 | 59 | $3,599 | **−$171** | 61.0% |
| 2026-06 | 1 | $2,555 | **−$2,555** | 0% |

**Edge concentrated Feb–Apr; in May he scaled deployment 30× down ($108k→$3.6k) and went flat; June opened
with a −$2,555 loss (Seoul 27°C).** Consistent with the official 30d=+$467 on only $3k volume — he has
largely stopped / the run cooled.

## How the strategy works
- **Buys cheap longshot temperature buckets** the market misprices: entry-price median **0.153**, p10 **0.004**
  (deep longshots), p90 0.981 (also some near-certain). Bimodal — load mispriced tails.
- **Variable sizing**: median buy $5.7, mean $65, up to **$10,108** — scales hard on high-conviction forecasts.
- **Hold to resolution** (weather settles on the date). This is **weather-forecast alpha** — superior
  temperature models vs the crowd, not microstructure/flow.
- Lumpy outcomes: biggest wins +$7.7k/+$4.1k/+$2.2k; biggest losses −$2,554 (Seoul), −$915 (Seattle), −$674 (NYC).

## Copy-trade verdict: ❌ NOT a good copy-trade target
Real skill, real money, but **uncopyable for our purposes**:
1. **Edge is forecast-based, not replicable.** He prices buckets from better weather models. Copying = buying
   AFTER his order already moved the (thin) price → you inherit a worse, post-signal entry.
2. **Markets are illiquid, multi-day-resolving.** Weather buckets have tiny books; copying with size = heavy
   slippage. No latency/edge advantage to exploit.
3. **He buys deep longshots (median 0.153, p10 0.004).** A follower entering behind him on a thin book gets a
   materially worse fill; the longshot edge evaporates after he's filled.
4. **Activity/PnL has dried up.** 30d = +$467 on $3k volume (vs $1.5M lifetime); May flat, June −$2.5k. You'd
   be copying a **fading** signal, not a live edge.
5. High per-market variance (single losses up to −$2.5k).

**Bottom line:** a genuinely skilled weather-forecast specialist (+$65k lifetime, 27.6% ROI Feb–Apr), but the
alpha is non-replicable domain forecasting in illiquid markets, and his book has gone quiet. Good wallet to
*admire / study*, **poor wallet to copy-trade.** If you want a weather edge, you'd need your own forecast
model — not a copy feed.

## Artifacts
- `strategy_lab/wallet_hunt/cache/_331_clean_per_market.csv` — 726 clean-window markets (title, cat, n_buys,
  cost, proceeds, net, avg_entry, last, won).
- `strategy_lab/wallet_hunt/cache/_331_per_market.csv` — full 1421-market table (early $ unreliable per caveat).
- Scripts: `analyze_331bf91c.py`, `analyze_331bf91c_clean.py`.
