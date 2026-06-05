# Strategy concept — "Buy → Wait → Hedge" (lock-the-lag complete-set) — 2026-05-29

> **Status: idea / research backlog.** A standalone note so this can be picked up in a future
> session. The naive form was tested and is NOT free money (see §4 + `LOCK_THE_LAG_HYPOTHESIS_TEST_2026_05_29.md`),
> but a disciplined variant + finding wallets that actually run it are open threads worth pursuing.

## 1. The idea (as described)
On a BTC/ETH/SOL up-down market, exploit the binance→chainlink oracle lag on BOTH legs:
1. **BUY** the binance-leading side while its ask is stale-cheap (e.g. **Up @ 0.66** as binance ticks up).
2. **WAIT** for the lag to fill — the move propagates, the leading side appreciates
   (**Up → 0.77**), so the lagging side gets cheap (**Down → 0.23**).
3. **HEDGE / complete the set** by buying the other side now-cheap (**Down @ 0.23**), same size.
4. You now hold a **complete set bought for 0.66 + 0.23 = 0.89**, which **redeems $1** →
   **locked ~11¢, market-neutral** (minus fees). Merge to realize early, or hold to resolution.

The profit is the **stale-ask discount captured on leg 1** (bought Up at 0.66 vs its post-move
fair ~0.77), converted from a directional bet into a fixed locked spread by completing the set
once leg 1 was right.

## 2. Profit condition (precise)
Locks a gain **iff** `entry_px(leg1) + entry_px(leg2) < $1 − fees`. Equivalently: leg 1 must
appreciate enough that the complement's ask is cheap enough that the two entries sum < $1.
Fee model = 2%-on-winning-profit only → the complete set redeems `$1` and the winning leg pays
the 2%; net lock ≈ `(1 − sum) − 0.02 × (1 − winning_leg_entry)`. Rule of thumb: need
**sum ≲ 0.97** to clear fees + spread comfortably.

## 3. Why it's appealing
- Converts the (risky) directional lag bet into a **market-neutral locked spread** when right.
- Uses infra we have: `oracle_lag.price_delta_bps` signal + L25 book + gasless MERGE.
- It's what we *thought* `0xeebde7a0` ($826k) was doing.

## 4. Why the NAIVE version is NOT free money (tested 2026-05-29)
FIFO time-ordered pair-matching on `0xeebde7a0` (the real wallet):
- Matched-pair sum **median 1.020**, only **38.8%** of completions sum < $1.
- "Good locks" (sum<1, +12.3¢ avg) are **outweighed** by "loss locks" (sum≥1) → **net −$961** on
  the completed-pair book. The wallet's profit is the **directional residual**, not the locks.
- **EV trap:** "lock only when right" = directional bet with **capped winners + full losers** →
  *lower* EV than just holding the lag bet. You can't lock away the downside, only relocate it.
- **Execution trap:** the opposite-side ask **reprices before you can complete cheap** — realistic
  pair cost ~**$1.09**, not <$1 (`LATENCY_EDGE_FINDING_2026_05_29.md` hedge test). By the time
  Up is 0.77, Down's *ask* is already ~0.25+, so sum ≈ 1 + two spreads.

## 5. Open threads for next session (where it might still work)
1. **Disciplined sum<$1-only completion as an EXIT overlay** on the directional taker: hold the
   lag bet; *if and only if* the book offers a complement at `leg1+leg2 < 0.97`, complete to lock;
   else ride to resolution. Measure its standalone EV vs pure-hold on the SAME fires (does locking
   the winners early beat holding them, after fees + the repricing slippage?). Likely small but
   could reduce variance / drawdown.
2. **Find wallets that ACTUALLY run it.** Screen harvested wallets for a **high sum<$1 completion
   rate** (FIFO matched-pair median < 0.97) — distinct from eebde7a0's 1.02. If one exists and is
   profitable, decode its leg-2 timing/threshold. (Use `_decode_lock_pattern_2026_05_29.py` as the
   screen; run it on harvest candidates.)
3. **Speed/latency study of leg 2.** The killer is leg-2 repricing. Quantify: after a ≥Xbps move,
   how long (ms) is the complement's ask still below `1 − leg1_px`? If there's a real sub-second
   window, the lock is only reachable with faster execution (Ireland <2ms helps, but the book
   event rate matters). If the window is ~0, the idea is dead at our infra.
4. **Neg-risk basket analogue.** The only place consistent sum<$1 buying is real in our data is the
   multi-outcome neg-risk basket (wallet `0x143732d8`) — different markets (sports/price-buckets),
   currently unprofitable, but the *mechanism* (buy a complete/NO basket < $1) is the same family.

## 6. Tooling already built (reuse next session)
- `strategy_lab/wallet_hunt/_decode_lock_pattern_2026_05_29.py` — FIFO matched-pair analyzer
  (sum distribution, %<$1, locked spread, leg gap, example sequences). Point it at any wallet.
- `oracle_lag.py` (VPS3 engine) — the leg-1 signal (`price_delta_bps`).
- `engine_v2.fill_at_book` / `LATENCY_EDGE_FINDING` scripts — for the leg-2 repricing study.
- Fee model: `engine_v2.LegacyConfig` (2%-on-winning-profit).

## 7. One-line verdict
Naive "always complete to lock" = EV-negative (caps winners, keeps losers, leg-2 reprices).
**Worth one more look** only as (a) a disciplined sum<0.97 exit overlay on the directional taker,
or (b) by finding a wallet that demonstrably runs it profitably. Otherwise the directional taker
(hold to resolution) remains the better expression of the same lag edge.
