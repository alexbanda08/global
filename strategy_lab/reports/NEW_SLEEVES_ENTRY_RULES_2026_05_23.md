# New sleeves — entry rules explained

_2026-05-23. Plain-English description of what each S1.5 / S6 / S7 sleeve
fires on. Engineering-level detail, not marketing._

---

## Background: how Polymarket up-down markets work

A "BTC-updown-5m-<slot_start>" market opens at `slot_start`, sets a strike
price from chainlink RTDS at slot_start, and settles at `slot_end = slot_start + 300s`
(for 5m) based on whether chainlink-fast price at slot_end > strike (UP wins)
or < strike (DOWN wins). The market has two tokens: UP and DOWN. Each
settles at $1.00 if its side wins, $0.00 otherwise. Token prices float
between $0.00-$1.00 during the 5-minute slot.

**Bet logic**: buy the UP token if you think price will end ABOVE strike,
buy DOWN if you think it will end BELOW.

**Slot lifecycle** (5m market example):
- t=0s: slot opens, chainlink RTDS samples binance/CME basis → sets strike.
- t=0-300s: traders buy/sell UP and DOWN tokens. Each token's price reflects current consensus.
- t=300s: chainlink samples again → settles based on price vs strike.

---

## S1.5 — Slot-anchored VWAP continuation (10 sleeves)

### Core idea

At some moment inside the 5-minute slot, look at binance spot price. Compute
the volume-weighted average price (VWAP) since slot_start. If binance is
clearly above its slot-anchored VWAP, the market has rallied since the
strike was set → **bet UP** (continuation). If below, **bet DOWN**.

This is **NOT mean reversion**. It's **momentum continuation**: a clear move
from the strike's reference window tends to hold through to settlement.

### Why slot-anchored (vs the original 15m-anchored S1)

S1 used the start of the current 15m UTC bucket as the VWAP anchor. That
anchor moves at fixed times (:00, :15, :30, :45 each hour) which doesn't
align with our market slots.

S1.5 uses **slot_start** as the anchor — the SAME moment chainlink set the
strike. So `dev_bps = 10000·ln(binance_close_now / VWAP_since_slot_open)`
literally answers "how much has binance moved relative to the strike's
reference window?" That's the semantically correct anchor.

### Generic entry rule (same for all S1.5 sleeves; only parameters differ)

```python
At time t = slot_start + offset_s (seconds since slot opened):
  vwap = Σ(binance_close[s] × volume[s]) / Σ(volume[s])
         for all 1-second bars from slot_start to t
  close_now = binance_close@t
  dev_bps = 10_000 × ln(close_now / vwap)

  if thr_min_bps < |dev_bps| ≤ thr_max_bps:
      direction = "UP" if dev_bps > 0 else "DOWN"
      BUY the corresponding token at current PM book
      HOLD until slot_end
```

### Per-sleeve parameters (10 sleeves)

| Sleeve | Asset | offset (sec into slot) | thr range (bps) | Translation |
|---|---|--:|---|---|
| BTC_210_5-10bps | BTC | 210 (3m30s in) | 5-10 | At 210s into a 5m slot (90s left), if binance is 5-10 bps from slot-open VWAP, bet WITH the move. |
| ETH_210_10-15bps | ETH | 210 | 10-15 | Same as #1 but ETH, larger deviation tier. |
| BTC_240_3-5bps | BTC | 240 (4m in) | 3-5 | Late fire, only 60s left. Tiny deviation OK because chainlink will resolve very close to binance's current level. |
| ETH_150_5-10bps | ETH | 150 (2m30s in) | 5-10 | Mid-slot fire, halfway through. |
| ETH_240_5-10bps | ETH | 240 | 5-10 | Like BTC_240 but ETH. |
| SOL_270_5-10bps | SOL | 270 (4m30s in) | 5-10 | Very late fire on SOL, only 30s left. |
| BTC_150_3-5bps | BTC | 150 | 3-5 | Mid-slot, small deviation. |
| BTC_60_3-5bps | BTC | 60 (1m in) | 3-5 | Early fire, 4 min remaining. |
| SOL_30_5-10bps | SOL | 30 (30s in) | 5-10 | Earliest fire of the bunch. Catches the initial reaction within the slot. |
| ETH_210_5-10bps | ETH | 210 | 5-10 | Same offset as ETH_210_10-15bps but smaller deviation tier. |

**Note**: "thr range" being a band (e.g., 5-10 bps) means we ONLY fire when
deviation is in that band. Below 5 bps → too noisy, skip. Above 10 bps →
mean-revert risk (exhaustion), skip. Each sleeve picks its own band.

### Why different offsets work differently

- **Late offsets (210-270s)**: only 30-90s remain until settlement. Chainlink
  reads binance/CME basis at slot_end, and binance doesn't usually round-trip
  in 30s. So a clear deviation late in the slot → high WR (85-90%) but PM
  token has already priced this in → entry vwap is 0.83-0.88, $/trade is
  small ($0.84-$1.25).
- **Early offsets (30-60s)**: 4-5 minutes remain. More time for the move to
  fade or reverse, so WR is lower (75-80%). But PM token is cheaper
  (entry vwap 0.55-0.70), so each win pays more → $/trade is higher
  ($1.31-$4.84).

There's a clean inverse relationship: WR ↑ as offset ↑, but $/tr ↓ as
offset ↑. Both can be profitable.

---

## S6 — Spike-driven entry (10 sleeves)

### Core idea

Instead of waiting for binance to drift away from a VWAP reference, look at
the LAST 5-30 SECONDS of binance action. If there was a sudden spike (a
sharp move with corresponding order-flow imbalance), bet that the spike will
continue through the slot.

This is **momentum from raw price action**, NOT from VWAP. It's a different
signal — it fires on slugs where momo's `ret_2m` would NOT fire, capturing
brief intraslot bursts that VWAP-based strategies miss.

### Why this is independent of S1.5

VWAP captures "where have we been over the last N seconds" (a smoothed
reference). Spike captures "what just happened in the last 5 seconds" (an
instantaneous move). On the 28d data, 6,514 spike fires happen on slugs that
S1.5 does NOT fire on — genuinely independent edge.

### Generic entry rule

```python
At time t = slot_start + offset_s:
  ret_5s_bps  = 10_000 × ln(binance_close@t / binance_close@(t-5s))
  ret_15s_bps = 10_000 × ln(binance_close@t / binance_close@(t-15s))
  ret_30s_bps = 10_000 × ln(binance_close@t / binance_close@(t-30s))
  cvd_5s      = cumulative (2 × taker_buy_volume - total_volume) over last 5s
  cvd_15s     = same over last 15s

  if spike_definition(ret_5s_bps, ret_15s_bps, ret_30s_bps, cvd_5s, cvd_15s):
      direction = "UP" if ret_15s_bps > 0 else "DOWN"
      BUY the corresponding token, HOLD to slot_end
```

### Spike definitions (D1-D4)

Each definition is a different way to declare "a spike just happened":

| Def | Rule | Intent |
|---|---|---|
| **D1** | `|ret_5s_bps| > 2.5bps AND sign(cvd_5s) == sign(ret_5s_bps)` | Sharp 5s move CONFIRMED by order flow agreement |
| **D2** | `|ret_15s_bps| > thr AND sign(cvd_15s) == sign(ret_15s_bps)` | Sustained 15s move with flow confirmation |
| **D3** | `|ret_5s_bps| > 1.5bps AND |ret_15s_bps| > 2.5bps` | Consistent spike (both 5s and 15s agree) |
| **D4** | `ret_30s_bps > 5bps AND ret_5s_bps > 0` | Fresh continuation after a 30s run (no pullback yet) |

### Spike tiers (T1-T3)

Each spike definition has 3 magnitude tiers. T1 = loose threshold (more
fires, lower per-fire signal). T2 = medium. T3 = strict (fewer fires,
higher signal). Per-asset thresholds calibrated to actual 1s return
distribution: BTC p99=4.3bps, ETH p99=5.5bps, SOL p99=6.4bps.

T1 wins on $/tr × n product across most cells — strict thresholds reduce
fire count without proportionally improving quality.

### Per-sleeve parameters (10 sleeves)

| Sleeve | Asset | offset | Def | Tier | Translation |
|---|---|--:|---|---|---|
| BTC_off120_D1_T1 | BTC | 120 | D1 | T1 | At 120s into 5m slot, fire if last 5s move > 2.5bps AND CVD agrees. Direction = sign of move. |
| BTC_off45_D1_T1 | BTC | 45 | D1 | T1 | Earlier offset, same spike rule. |
| BTC_off30_D1_T1 | BTC | 30 | D1 | T1 | Earliest BTC spike fire. |
| BTC_off60_D2_T1 | BTC | 60 | D2 | T1 | At 60s, 15s sustained spike with CVD agreement. |
| BTC_off60_D4_T1 | BTC | 60 | D4 | T1 | At 60s, 30s of cumulative run continuing → "fresh continuation". |
| SOL_off30_D2_T1 | SOL | 30 | D2 | T1 | Early SOL fire on 15s sustained spike. |
| ETH_off60_D1_T1 | ETH | 60 | D1 | T1 | ETH 5s spike. |
| ETH_off120_D4_T1 | ETH | 120 | D4 | T1 | At 120s into slot, ETH had a 30s run that's still continuing. |
| BTC_off45_D2_T1 | BTC | 45 | D2 | T1 | Sustained spike, earlier offset. |
| ETH_off15_D2_T1 | ETH | 15 | D2 | T1 | Very early ETH fire (only 15s in) on 15s spike. |

### Why spike fires at CHEAP entry vwap

Spike entries happen in the first 15-120 seconds of a slot. PM book hasn't
fully priced in the move yet. Entry vwap ranges 0.55-0.74 (cheap relative to
S1.5's 0.78-0.88). So even though spike WR is lower (66-83%) than late-fire
S1.5 (87%+), each win pays substantially more → $/trade is HIGHER on spike
sleeves ($2.46-$6.57) than on S1.5 late-fire sleeves ($0.84-$2.99).

This is the spike-driven family's unique selling point: **catches the move
before the PM book reflects it**.

---

## S7 — VWAP continuation on 15m markets (8 sleeves)

### Core idea

Exactly the same logic as S1.5 (slot-anchored VWAP continuation), applied
to 15-minute markets instead of 5-minute. Slot is 900 seconds; fire offsets
range from 60 to 840 seconds.

### Generic entry rule

Identical to S1.5 in math; only the universe (15m markets) and offset
range (60-840s instead of 30-270s) differ:

```python
At time t = slot_start + offset_s (within 15m slot of 900s):
  vwap = VWAP from slot_start to t (using 1s binance bars)
  dev_bps = 10_000 × ln(binance_close@t / vwap)

  if thr_min < |dev_bps| ≤ thr_max:
      direction = "UP" if dev_bps > 0 else "DOWN"
      BUY corresponding token, HOLD until slot_end (900s)
```

### Per-sleeve parameters (8 sleeves)

| Sleeve | Asset | offset (sec) | thr (bps) | Translation |
|---|---|--:|---|---|
| **SOL_840_20-30bps** | SOL | 840 (14m in, 60s left) | 20-30 | Very late SOL fire; only 1 minute remains. Large deviation (20-30bps) needed because SOL is volatile. ⭐ best $/tr (+$17.34) |
| ETH_480_5-10bps | ETH | 480 (8m in) | 5-10 | Mid-slot ETH fire. |
| SOL_240_10-15bps | SOL | 240 (4m in) | 10-15 | Early-mid SOL fire. |
| ETH_720_15-20bps | ETH | 720 (12m in, 3m left) | 15-20 | Late ETH with large deviation. |
| ETH_240_10-15bps | ETH | 240 | 10-15 | Mid-slot ETH. |
| SOL_360_10-15bps | SOL | 360 (6m in) | 10-15 | Mid-slot SOL. |
| ETH_480_15-20bps | ETH | 480 | 15-20 | Mid-slot ETH, larger deviation tier. |
| BTC_480_10-15bps | BTC | 480 | 10-15 | Mid-slot BTC. |

### Why 15m is less compelling than 5m

- Fewer fires per day (15m slots open 4× less often than 5m).
- Larger time-to-settlement at any offset means more time for noise/reversion.
- Per-trade economics are usually worse: entry vwap is high (0.78-0.88),
  win pays ~$0.15-$0.22/share on $25 notional after fee → small absolute $/tr.

Only ONE 15m sleeve stands out: **SOL_840_20-30bps**. SOL volatility +
60-second-to-settlement + large extension → 77.5% WR at $17.34/tr. Worth
shipping as a single high-edge 15m sleeve.

---

## Quick reference card — when does each sleeve fire?

| Sleeve | Time into slot | Signal | Asset | Slot length |
|---|---|---|---|---|
| S1.5_BTC_210_5-10bps | 3m30s | binance 5-10bps from slot-VWAP | BTC | 5m |
| S1.5_ETH_210_10-15bps | 3m30s | binance 10-15bps from slot-VWAP | ETH | 5m |
| S1.5_BTC_240_3-5bps | 4m | binance 3-5bps from slot-VWAP | BTC | 5m |
| S1.5_ETH_150_5-10bps | 2m30s | binance 5-10bps from slot-VWAP | ETH | 5m |
| S1.5_ETH_240_5-10bps | 4m | binance 5-10bps from slot-VWAP | ETH | 5m |
| S1.5_SOL_270_5-10bps | 4m30s | binance 5-10bps from slot-VWAP | SOL | 5m |
| S1.5_BTC_150_3-5bps | 2m30s | binance 3-5bps from slot-VWAP | BTC | 5m |
| S1.5_BTC_60_3-5bps | 1m | binance 3-5bps from slot-VWAP | BTC | 5m |
| S1.5_SOL_30_5-10bps | 30s | binance 5-10bps from slot-VWAP | SOL | 5m |
| S1.5_ETH_210_5-10bps | 3m30s | binance 5-10bps from slot-VWAP | ETH | 5m |
| S6_BTC_off120_D1_T1 | 2m | binance 5s spike with CVD-agree | BTC | 5m |
| S6_BTC_off45_D1_T1 | 45s | binance 5s spike with CVD-agree | BTC | 5m |
| S6_BTC_off30_D1_T1 | 30s | binance 5s spike with CVD-agree | BTC | 5m |
| S6_BTC_off60_D2_T1 | 1m | binance 15s sustained spike + CVD | BTC | 5m |
| S6_BTC_off60_D4_T1 | 1m | binance 30s continuation move | BTC | 5m |
| S6_SOL_off30_D2_T1 | 30s | binance 15s sustained spike + CVD | SOL | 5m |
| S6_ETH_off60_D1_T1 | 1m | binance 5s spike with CVD-agree | ETH | 5m |
| S6_ETH_off120_D4_T1 | 2m | binance 30s continuation move | ETH | 5m |
| S6_BTC_off45_D2_T1 | 45s | binance 15s sustained spike + CVD | BTC | 5m |
| S6_ETH_off15_D2_T1 | 15s | binance 15s sustained spike + CVD | ETH | 5m |
| S7_SOL_840_20-30bps | 14m | binance 20-30bps from slot-VWAP | SOL | 15m |
| S7_ETH_480_5-10bps | 8m | binance 5-10bps from slot-VWAP | ETH | 15m |
| S7_SOL_240_10-15bps | 4m | binance 10-15bps from slot-VWAP | SOL | 15m |
| S7_ETH_720_15-20bps | 12m | binance 15-20bps from slot-VWAP | ETH | 15m |
| S7_ETH_240_10-15bps | 4m | binance 10-15bps from slot-VWAP | ETH | 15m |
| S7_SOL_360_10-15bps | 6m | binance 10-15bps from slot-VWAP | SOL | 15m |
| S7_ETH_480_15-20bps | 8m | binance 15-20bps from slot-VWAP | ETH | 15m |
| S7_BTC_480_10-15bps | 8m | binance 10-15bps from slot-VWAP | BTC | 15m |

---

## Common across ALL three families

After deciding to fire (whatever the signal says):

1. **Direction**: sign of the relevant binance move (positive → UP, negative → DOWN).
2. **Token to buy**: UP token if direction == UP, DOWN token if direction == DOWN.
3. **Entry method**: L25 book walk via `engine_v2.fill_at_book` at fire_us
   timestamp. Spread filter: 0.02 for BTC/ETH, 0.025 for SOL. Notional: $25
   (paper-only shadow phase).
4. **Hold to slot_end**: NO mid-slot exit. NO stop-loss. NO take-profit. Just
   buy and wait for chainlink settlement.
5. **Fee model**: 2%-on-profit-only (production-actual fee, verified vs
   25,900 prod resolutions; NOT the hypothetical 0.07·p·(1−p) curve).
6. **Settlement**: chainlink samples again at slot_end; UP wins if
   chainlink price > strike, DOWN wins if <. PM token of the winning side
   pays $1.00 per share; loser pays $0.00.
7. **PnL** = `(shares × $1.00 − notional) × 0.98` on win, `−notional` on loss.

The strategies differ ONLY in step 1 (the entry decision). Everything after
firing — book walk, hold logic, settlement — is identical across all 28
sleeves.

## End
