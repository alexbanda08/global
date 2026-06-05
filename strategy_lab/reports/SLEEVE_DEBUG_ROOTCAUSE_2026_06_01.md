# Sleeve live-loss debug — ROOT CAUSE (2026-06-01)

Supersedes the sub-agent's `SLEEVE_DEBUG_LIVE_VS_SHADOW_2026_06_01.md`, which **wrongly concluded "no live
fills / no bug."** That agent queried the base sleeve_id and missed the **`_LIVE` suffix** — the live fires
are logged under `poly_sniper_v5_..._LIVE` in `trading.events` kind `poly_updown_resolution`. The losses are REAL.

## CONFIRMED: the live sleeves lose (real Polymarket fills)
Ireland `poly_updown_resolution`, all history, `pnl_usd` populated:
| sleeve | n | WR | total PnL | avg |
|---|---|---|---|---|
| btc_15m_ema50_ema800_off600_down**_LIVE** | 9 | 55.6% | **−$3.39** | −$0.38 |
| eth_5m_l_ema50_hurst_grandparent_v8**_LIVE** | 16 | 50.0% | **−$5.01** | −$0.31 |
Per-fire detail matches the operator's wallet exactly (e.g. btc DOWN @0.62 won +$0.585; @0.26 lost −$1.00).

## PRIMARY ROOT CAUSE (strong): live fires at the SLOT BOUNDARY, not the configured offset
Per the resolved-event fields, `actual_offset = (fire_us − slot_start_us)/1e6`:
| sleeve | configured `fire_offset_s` | **ACTUAL offset** |
|---|---|---|
| btc_15m …_off600_down_LIVE | 600 | **900 (= slot END, window_s)** |
| eth_5m …_hurst_v8_LIVE | 60 | **300 (= slot END, window_s)** |

Three independent confirmations:
1. `fire_us − slot_start_us` = the full window (900/300), not the offset (600/60).
2. The operator's wallet trade timestamps land on the 15m **boundaries** (`:00/:15/:30/:45`), NOT off=600
   (`:10/:25/:40/:55`).
3. Live fill prices span **0.26–0.98** (slot-end / near-resolution dispersion), vs the VPS3 shadow's ~0.81
   (mid-window favored side).

**Why this kills the edge:** the strategy's edge is at **off=600** — buy the trending side at ~0.81 with
5min left for the trend to hold. Firing **~5min late at resolution** means buying the marginal/near-decided
cases at extreme prices → WR collapses to ~the base rate, with full −$1 losses on the flips → net negative.
Same gates pass, same signal — **wrong fire time.**

**Note:** the local VPS3 loop (`engine/poly_sniper_v5_loop.py`) computes `fire_us = slot_start_us +
offset_s*1e6` CORRECTLY, and the VPS3 shadow fires at the right off=600 (WR 80%). So the bug is in the
**Ireland live deployment** — its offset scheduler / slot-indexing / `slot_start_us` anchor fires at the slot
boundary. (Possible: an older deployed loop, OR a `ws_s = slot_start − window` anchor that shifts the
effective fire to slot-end, OR the live-mirror path uses bar-boundary dispatch instead of the offset scheduler.)

## HONEST CAVEAT — sample is tiny
n=9 (btc) / 16 (eth). The live-vs-shadow WR gap (55% vs 80%; 50% vs 72%) is only **p≈0.06–0.09** (binomial)
— NOT a slam-dunk; small-window variance can't be fully excluded on the WR alone. BUT the offset anomaly is a
concrete, mechanical defect that fully explains the dispersed fill prices and is worth fixing regardless of n.

## What is NOT the problem (ruled out)
- Gates: live `gates_evaluated` matches spec (g_dir_down + g_tr_above_ema50/ema800 all true) — correct.
- Binance feed: same Binance kline feed for the EMA panel on both hosts (`TV_POLY_UPDOWN_KLINE_FEED=binance`;
  TR panel fed by BinanceMarketDataFeed). `TV_BAR_SOURCE=hl_live` is the momo path, not the sniper EMA.
- Fee/notional: live $1, `fill_latency_ms=0`, taker fill at dn_ask0 — consistent.

## RESTART GO/NO-GO
**NO-GO until the offset-fire timing is fixed + verified.** Checklist for the TV agent:
1. On Ireland, confirm the deployed `poly_sniper_v5_loop.py` `_fire_at_offset` computes
   `fire_us = slot.slot_start_us + offset_s*1e6` AND that `slot.slot_start_us` is the TRUE market slot_start
   (not a ws_s/previous-slot anchor). Fix whichever shifts the fire to the slot boundary.
2. After fix, verify in `poly_updown_resolution`: `(fire_us − slot_start_us)/1e6 == 600` (btc) / `== 60` (eth),
   and that live `fill_vwap` distribution clusters ~0.81 (btc) like the VPS3 shadow — NOT 0.26–0.98.
3. Re-enable LIVE (`TV_POLY_SNIPER_V5_LIVE_ENABLED=true`) at $1, shadow-watch ≥2 weeks, and require LIVE WR
   to beat the entry-implied price (not just the shadow number) before sizing.
4. Independent of the timing fix: the edge is thin at real fill prices — keep $1 notional until live n≥100.

## Current state
Both LIVE sleeves remain **stopped** (`TV_POLY_SNIPER_V5_LIVE_ENABLED=false`, env backed up `.bak_20260601_233548`,
engine active). Total realized live loss ≈ −$8.4 (btc −$3.39 + eth −$5.01).
