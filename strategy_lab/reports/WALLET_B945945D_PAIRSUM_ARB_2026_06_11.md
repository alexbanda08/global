# Wallet decode — `0xb945945d5bcaf7b56834d4da8cdf8f8f94b2db68`

_2026-06-11. Single-sleeve BTC-15m **temporal pair-sum arbitrageur**. Active since 2026-03-19._

## TL;DR
He buys **both** Up and Down on the **same BTC 15-min up/down market**, accumulating each leg
in small clips across the whole window. No single instant has `ask_up+ask_dn < 1` (book overround
is always ~1.01) — the edge is **temporal**: as BTC oscillates inside the 900s window, whichever leg
is momentarily out-of-the-money trades cheap, and he repeatedly scoops the cheap leg on **each** side.
He ends each market holding a **matched pair bought at a blended ~$0.94–0.96**, which pays $1.00 at
resolution = locked, ~direction-neutral **+4–6¢ per matched pair**.

## PnL (two independent ground truths agree)
- Polymarket leaderboard `/profit?window=all` = **$20,661**
- Alchemy net USDC cash = **+$19,734**
- → lifetime **≈ $20k over ~87 days ≈ $230/day net**; recent 2-day run hotter (~$590/day locked, below).
- `cash_pnl` activity-tape number ($1.3M) is an **artifact** — REDEEM income is fully captured but the
  matching BUY cost is truncated by the data-api 3500-trade cap. Ignore it.
- Turnover ~$1.1M. Thin edge × very high volume.

## How he does it (mechanism)
- **Pure taker.** `maker_rebate_share = 0.0027` (≈0). Counterparty 87% = NegRisk matcher
  `0xe111180000d2663c0091e4f400237545b87b996b` → CLOB fills, **0 mints** (does not split/mint pairs).
- **Both sides, same market.** 39 / 40 recent markets bought on **both** Up and Down.
- **Small clips, full-window working.** usdcSize median **$5.40** (max ~$30), ~**87 fills/market** on a
  15-min market; entry offset spans the whole window (median ~540s of 900s).
- **Blended pair cost < $1.** Size-weighted (avg buy_up + avg buy_dn): **median $0.94, p10 $0.857,
  89.7% of markets < $1.00.** Recent matched-book weighted cost **$0.9599**.
- **Matched-pair economics (40 recent BTC-15m markets, 2 days):** 29,478 matched pair-shares,
  locked net **+$1,181.90** (~$590/day), directional **residual only 20.8%** of matched (mostly neutral).
- Redeems winners: 2,010 REDEEM events, $1.33M gross redemption.
- **Why it works:** the instantaneous overround keeps naive `sum_asks<1` arb impossible, but over the
  window the two legs anti-correlate with BTC; buying each leg's transient cheap ask accumulates the
  pair below $1. Spreads on BTC-15m are tight (~1¢ median) so taker cost is small relative to the 4–6¢ edge.

## How he selects sleeves
**He doesn't rotate — it's a single sleeve: `btc-updown-15m`, always.**
- REDEEM ground truth (2,010 settled markets, 2026-03-19 → 2026-06-11): **100% BTC, 100% 15m, every week.**
  No ETH/SOL/alts, no 5m, no hourly/long-form.
- Within that sleeve he's in **essentially every consecutive 15m BTC window** (settles 100–200/week recently).
  "Selection" = *trade every BTC-15m market and work both books*, not cherry-picking.
- Scaled in mid-March (~1–65 markets/wk wks 11–15) → peak wks 16–17 (~310–375/wk) → steady ~110–200/wk.
- **Why BTC-15m specifically:** deepest/tightest up-down book (1¢ spreads → low taker drag), longest
  window (900s → most intra-window oscillation to accumulate cheap legs), enough vol that legs dislocate.
  5m too short / thin; alts too thin to size into both legs cheaply.

## Archetype
This is the **pair-accumulator** (HANDOFF_WALLET_DECODER §3), refined: taker, single-sleeve BTC-15m,
**temporal** (not instantaneous) pair accumulation. Distinct from mint-and-sell (he never mints/sells pairs).

## Reproduction artifacts
- `strategy_lab/wallet_hunt/cache/0xb945945d/alchemy_transfers.parquet` (357,113 transfers, full history)
- `strategy_lab/wallet_hunt/cache/_pm_portfolio/0xb945945d/` (activity TRADE/REDEEM tape, lb_profit, positions)
- `strategy_lab/wallet_hunt/_b945_analyze.py`, `_b945_analyze2.py` (the analysis above)
- Fix applied this session: `fetch_alchemy.py` now retries transient `IncompleteRead`/timeouts (6×
  backoff) instead of aborting — a blip previously truncated the *oldest* history (desc pagination).

## Open question for backtest (if we want to replicate)
Does the matched-pair blended-cost-<$1 reproduce on **our canonical L25** for BTC-15m, net of the
0.07 taker fee curve, with realistic same-window both-leg fill probability? The temporal-accumulation
fill model is the crux — needs the native-10Hz L25 walk over the full 900s window, both tokens.
