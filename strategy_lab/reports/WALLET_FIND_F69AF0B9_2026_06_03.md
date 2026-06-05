# Wallet identified from activity screenshot — 0xf69af0b9 (2026-06-03)

## Ask
Find the exact Polymarket wallet behind a screenshotted activity feed (BTC Up/Down 5-min markets,
June 2 ET, ~$3 buys, hold-to-resolution) so we can reverse-engineer its strategy with our decoder.

## Method (cold match, not a guess)
1. The 12 markets in the image are `btc-updown-5m-<slot_start_s>` (real Polymarket slug = our canonical
   slug; EDT = UTC-4, verified against a known market: ts 1780304100 = "June 1 4:55AM ET").
2. Resolved each conditionId via `gamma-api/events?slug=` → `markets[0].conditionId`.
3. Pulled EVERY trade per market from `data-api.polymarket.com/trades?market=<conditionId>` (~2.5–3.5k
   trades/market).
4. Fingerprint-matched each slot on (outcome + size ±0.25sh + price ±0.03) against the image.
   Script: `strategy_lab/wallet_hunt/find_btc5m_image_wallet.py`.

## Result — unambiguous
**`0xf69af0b9af9c92a342b682e5dee262dbc39e7b5c`** matched **12/12** slots; next-best wallet 2/12.
Every slot lines up:
```
ET     image (o,sh,px)        wallet buy
2:20   Up   4.1sh @0.756   →  Up   4.108sh @0.740
3:40   Up   3.1sh @0.868   →  Up   3.069sh @0.870
3:55   Down 4.2sh @0.767   →  Down 4.213sh @0.750
5:05   Up   4.0sh @0.745   →  Up   4.000sh @0.730
5:15   Up   3.0sh @0.897   →  Up   3.000sh @0.890
6:15   Up   3.5sh @0.831   →  Up   3.543sh @0.810
6:40   Down 4.0sh @0.840   →  Down 4.000sh @0.830
6:45   Up   5.1sh @0.596   →  Up   5.086sh @0.580
6:55   Up   4.0sh @0.745   →  Up   4.000sh @0.730
7:00   Down 4.0sh @0.840   →  Down 4.049sh @0.820
7:25   Down 4.6sh @0.661   →  Down 4.641sh @0.640
7:40   Down 4.1sh @0.737   →  Down 4.111sh @0.720
```

## Wallet profile (our decoder — `polymarket_api.py`)
- lb_profit **all = −$197.88**, 30d = +$17.04, 7d = +$17.04 (all recent gain is the last week).
- volume_all = $11,734; open_value $0; activity 1697 TRADE + 1179 REDEEM (pure hold-to-resolution, 13 sells).

## Strategy decode (`decode_f69af0b9.py`, from the activity tape)
- **Markets:** BTC only — **15m (850 buys) + 5m (831 buys)**. The screenshot was just the 5m slice.
- **Sizing:** ~fixed small notional — usdcSize median **$3.13**, mean $3.68 (occasionally scales to ~$10);
  shares = notional/price → variable share count (low price = more shares), exactly as the image shows.
- **Side selection:** **balanced & near-coinflip** — Down 864 / Up 817; only **60.6%** on the favorite
  (price>0.5), 35.7% on the underdog. Entry price median **0.54** (5–95%: 0.35–0.75). NOT a pure
  favorite-buyer.
- **Entry timing:** mid-to-late in the window — entry-offset median **~197 s**, IQR 60–320 s (enters after
  the window opens, often into the back half; some pre-window at −178 s).
- **Win rate ≈ 52.5%** (markets that redeemed >0). Slightly above coinflip; with ~0.54 entry + ~$3 stake +
  fees this is **break-even-to-slightly-negative**, matching the lifetime −$198.
- **Cadence:** 79 active days, ramping hard (≈5 buys/day late-May → 20–40/day Jun 1–2). On btc-5m, 40% of
  buys are on consecutive 300-s slots (fires many adjacent slots, not all); some same-slot scale-ins.

## Verdict
This is a **small-stake near-coinflip BTC 5m/15m directional bot, hold-to-resolution, ~52.5% WR, lifetime
net-negative.** It is NOT a profitable edge to clone — entirely consistent with the exhaustive
efficient-market finding (`EFFICIENT_MARKET_FINDING_2026_05_28.md`): no reproducible directional edge in
price/flow; this wallet wins ~its entry-implied probability and bleeds the fee. The screenshot's "all
greens" is survivorship of one favorable window, not a durable edge (true WR 52.5%, all-time −$198).

## Optional deep trigger-decode (if still wanted)
The btc-5m/15m fires from late-May → Jun 1 are inside canonical (max Jun 1 09:07), so the **side-picker**
(what makes it choose Up vs Down at entry) could be decoded by joining each fire to binance klines / L25 /
chainlink RTDS at `slot_start + entry_offset_s` (`book_anchored_decode.py` / `replicate/decode_triggers.py`).
But given WR 52.5% and net-negative, expect to find no exploitable trigger. June-2/3 fires need a live data
pull (not in canonical).

## Artifacts
- `strategy_lab/wallet_hunt/find_btc5m_image_wallet.py` — the matcher (+ `cache/_btc5m_image_wallet.json`,
  `cache/_btc5m_image_rawtrades.json`).
- `strategy_lab/wallet_hunt/decode_f69af0b9.py` — tape decode (+ `cache/_f69_recent_buys.csv`).
