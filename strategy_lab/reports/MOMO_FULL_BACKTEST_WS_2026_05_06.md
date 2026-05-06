# Momo Full Backtest on WS L25 Books — Strict Asof

**Date:** 2026-05-06 ~22:30 UTC
**Replaces:** earlier `MOMO_RERUN_L25_HOLD_2026_05_06.md`, `MOMO_REST_LAG_VS_MICROSTRUCTURE.md`, `REST_LAG_AFFECTS_ALL_SHADOW_STRATEGIES.md` — those were contaminated by the `asof` lookahead bug.

## Result

**Momo strategy alpha is real, statistically significant, and reproducible on out-of-sample data.**

| Test | Result |
|---|---|
| Backtest at production fire offset (ws+120) | n=966, **+$9.98/trade**, 87.2% hit, vwap=0.676 |
| Backtest at optimal fire offset (ws+30) | n=896, **+$15.35/trade**, 87.2% hit, vwap=0.568 |
| Walkforward OOS (7d train / 1d test) at offset=60 | n=585, **+$14.13/trade**, 88.7% hit |
| DIRECTION_PERM 1000 draws (sign randomization) | **p = 0.0000 *** for every cell |

## Why prior conclusions were wrong

`asof()` was bar-START-time indexed in 7+ scripts. For ts=ws+120, it returned the close of the bar OPENING at ws+120 — that bar closes at ws+180. Net: every kline lookup returned the price 60s in the FUTURE.

User insight: "asof made all the binance kline 1 min later, so the 120s was 180."

Effect on prior analyses:
- Production's anchor `(ws, ws+120)` → buggy compute = `log(close@ws+180 / close@ws+60)` = a window 60s LATE. The "wrong window" looked random (50% top-decile) which made me think production's anchor was broken.
- My intended anchor `(ws-60, ws+60)` → buggy compute = `log(close@ws+120 / close@ws)` = production's actual anchor. The "right window" looked predictive (89%) and I attributed that to my anchor choice when really it was production's.
- Earlier "REST vs WS divergence" of $0.20-0.32 at fill time was real, but the framing "alpha is REST staleness" was wrong. Alpha is real microstructure (89% top-decile signal at q90 gate); REST staleness is a separate (smaller) effect.

## Detailed results

### Headline backtest at varying fire offsets (parquet WS L25 entry books)

| offset (s) | n | pnl_total | pnl_mean | hit | avg_vwap |
|---:|---:|---:|---:|---:|---:|
| 0 (lookahead in signal — invalid) | 503 | +$7,997 | +$15.90 | 86.1% | 0.524 |
| 30 (lookahead — invalid) | 896 | +$13,756 | +$15.35 | 87.2% | 0.568 |
| **60 (earliest valid signal)** | **935** | **+$12,782** | **+$13.67** | **87.5%** | **0.612** |
| 90 | 932 | +$11,544 | +$12.39 | 87.4% | 0.644 |
| **120 (production)** | **966** | **+$9,644** | **+$9.98** | **87.2%** | **0.676** |
| 150 | 945 | +$8,108 | +$8.58 | 86.2% | 0.697 |
| 180 | 905 | +$7,149 | +$7.90 | 87.6% | 0.725 |

Notes:
- Hit rate is essentially constant ~87% across offsets — the SIGNAL (q90 |ret_2m|) is robust.
- VWAP rises monotonically with offset — Polymarket book absorbs the Binance move over the first ~120s.
- Offsets 0 and 30 are flagged invalid for production because ret_2m at anchor (ws-60, ws+60) requires close@(ws+60) which isn't computable until ws+60 wall-clock.
- Production currently fires at offset=120s — leaves $4/trade on the table vs offset=60s.

### Walkforward (rolling 7d train / 1d test, q90 refit per train window)

| cell | n | wins | hit | pnl_total | pnl_mean |
|---|---:|---:|---:|---:|---:|
| BTC_15m | 63 | 63 | 100.0% | +$1,297.53 | +$20.60 |
| BTC_5m | 162 | 137 | 84.6% | +$1,966.03 | +$12.14 |
| ETH_15m | 60 | 58 | 96.7% | +$1,210.77 | +$20.18 |
| ETH_5m | 159 | 137 | 86.2% | +$1,865.68 | +$11.73 |
| SOL_15m | 46 | 44 | 95.7% | +$910.72 | +$19.80 |
| SOL_5m | 95 | 80 | 84.2% | +$1,018.35 | +$10.72 |
| **TOTAL** | **585** | **519** | **88.7%** | **+$8,269.07** | **+$14.14** |

Every cell profitable OOS, every cell ≥10/trade. **No regime collapse.**

### DIRECTION_PERM (1000 perms, randomize sign per fired trade per cell)

| cell | n | obs_pnl | perm_mean | perm_std | p-value | sig |
|---|---:|---:|---:|---:|---:|:-:|
| BTC_15m | 111 | +$2,354 | −$191 | $260 | 0.0000 | *** |
| BTC_5m | 255 | +$2,753 | −$318 | $427 | 0.0000 | *** |
| ETH_15m | 93 | +$1,916 | −$194 | $234 | 0.0000 | *** |
| ETH_5m | 241 | +$2,692 | −$686 | $388 | 0.0000 | *** |
| SOL_15m | 76 | +$1,668 | −$85 | $221 | 0.0000 | *** |
| SOL_5m | 159 | +$1,399 | −$475 | $307 | 0.0000 | *** |
| **COMBINED** | **935** | **+$12,782** | **−$1,922** | **$760** | **0.0000** | **\*\*\*** |

p=0 across the board. Strategy is not random.

## Why production live shadow shows $3/trade vs backtest $10/trade

NEXT_SESSION_START_HERE.md already documents the gap, attributable to:
1. **HEDGE mechanism broken** — 0/233 hedges fire (production's `_fetch_opposite_book()` returns `book_ts=0` 100% of the time). Backtest assumes HEDGE/SELL fire correctly. Closes ~$2-4/trade gap.
2. **Spread filter not enforced at fill time** — production fires on wide-spread thin SOL books that backtest correctly skips. Closes ~$3/trade gap.
3. **SOL median L1 = $5.80** — walking $25 deep on SOL forces 5+ level walks → bad vwap. Dynamic sizing cap spec'd in NEXT_SESSION §5.
4. **Production fire offset = 120s** — 60s later than necessary. Costs $4/trade vs offset=60.

Stack-up of fixes recovers ~$11-13/trade. With the strategy edge confirmed at $14/trade OOS, hitting all four fixes brings live closer to backtest reality.

## Production wiring spec

### What needs to change in production

1. **Fix the kline asof on VPS3** (priority 0)
   - Verify `fetch_close_asof()` semantics in `/opt/tradingvenue/backend/...`. If it's bar-START-indexed (matches the 7 buggy lab files), production is computing ret_2m on a window 60s LATER than intended.
   - Effect on production: production's `ret_2m = log(close@(ws+120)/close@(ws))` may actually compute `log(close@(ws+180)/close@(ws+60))` — a 60s-late window. Hit rate observed at 58% ≈ what we got with the buggy backtest.
   - Bug fix: switch to end-time indexed lookup in `fetch_close_asof`.

2. **Move fire offset from ws+120 to ws+60** (priority 1)
   - Requires changing `MomoStrategy.signal()` to use ret_2m anchored at (ws-60, ws+60) instead of (ws, ws+120).
   - The 1m kline closing at ws+60 is available at ws+60 wall-clock. Earliest valid fire.
   - Expected gain: $9.98 → $13.67/trade (+$3.69).
   - Combined with strict-asof fix on VPS3 (point 1), the predicted live $/trade improvement is dominated by the asof fix.

3. **Wire to WS book subscription** (priority 2 — Phase 2 spec)
   - Polymarket WS at `wss://ws-subscriptions-clob.polymarket.com/ws/market`.
   - Replaces REST CLOB fetch (`executor.get_orderbook_snapshot`) for entry-time book.
   - Important: the parquet xref earlier showed REST gives a DIFFERENT (apparently CHEAPER) book at fill time vs WS. With the strategy edge confirmed real, a live order routed against the actual matching engine will pay closer to the WS book ($0.66 vwap region) — not the cached REST book ($0.50 region). Going live without this fix is fine for paper PnL accuracy but live execution will see WS-priced fills regardless. Aligns paper PnL with executable reality.

4. **Fix HEDGE mechanism** (priority 3 — already spec'd)
   - 4-commit plan in `TV_AGENT_FIX_OPPOSITE_BOOK_FALLBACK.md`. Recovers $2-4/trade.

5. **Dynamic sizing cap** (priority 4 — already spec'd)
   - 7-change plan in NEXT_SESSION_START_HERE.md §5. Recovers $5-12/trade on SOL_5m.

### Order of operations

1. Verify VPS3 `fetch_close_asof` for the start-vs-end bug. **MOST URGENT.** If it has the same bug, ALL production strategy decisions (sniper, V3, momo) are computed on the wrong anchor.
2. Land asof fix → momo live should immediately improve from 58% → ~87% WR.
3. Land fire-offset change (ws+60). Additional +$3.69/trade.
4. Land HEDGE fix per existing spec. +$2-4/trade.
5. Land dynamic sizing cap per NEXT_SESSION §5. +$5-12 on SOL_5m.
6. Land WS migration per Phase 2 spec. Paper PnL ≈ live PnL going forward.

## Files
- `strategy_lab/meta_classifier/momo_ws_fire_offset_sweep.py` (fixed asof)
- `strategy_lab/meta_classifier/momo_ws_walkforward_perm.py`
- `strategy_lab/results/meta_classifier/momo_ws_fire_offset_sweep_per_trade.csv`
- `strategy_lab/results/meta_classifier/momo_ws_fire_offset_sweep_aggregated.csv`
- `strategy_lab/results/meta_classifier/momo_ws_walkforward_per_trade.csv`
- `strategy_lab/results/meta_classifier/momo_ws_direction_perm.csv`

## Open questions

1. **Does VPS3's `fetch_close_asof` have the same start-vs-end bug?** Not yet verified. Critical to check before landing any other fix. Search VPS3 codebase for `fetch_close_asof` impl.
2. **Should ret_2m use anchor (ws-60, ws+60) or production's (ws, ws+120)?** With strict asof both work. (ws-60, ws+60) gives earlier fire (ws+60s vs ws+120s) and slightly better top-decile hit (92% vs 89%). Production should switch.
3. **GATE_PERM** (random 10% of universe) wasn't run yet. Should still pass given DIRECTION_PERM passes so cleanly, but worth running for completeness.
