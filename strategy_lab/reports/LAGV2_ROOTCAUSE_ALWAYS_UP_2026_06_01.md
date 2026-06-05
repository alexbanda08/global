# poly_fast_taker_lagv2 — root cause of the bad WR (NOT contrarian — it's degenerate "always UP") — 2026-06-01

Operator asked: btc_15m lagv2 is 13% WR — did we implement it contrarian (wrong side)? Answer below.

## Verdict
**NOT contrarian / not inverted.** The gate direction logic is correct (buy the binance-leading side). The real bug: **the sleeve fires `UP` on 100% of slots and never `DOWN`** because the LIVE signal is a different, one-sided quantity than the BACKTESTED signal. With no working direction signal it's just an always-UP coin-flip → btc_15m got 13% on an unlucky n=15 (BTC mostly fell), the others 38-57%.

## Evidence
| | Backtest (validated) | Live (deployed) |
|---|---|---|
| Direction split | **Up 1819 / Down 1834 (~50/50)** — BTC15m 163/156 | **95 fires, ALL UP, 0 DOWN** |
| WR | ~68% (BTC+ETH, hold-to-resolution) | btc_5m 37.8% · btc_15m **13.3%** (n=15) · eth_5m 39.3% · eth_15m 57.1% |
| Signal logged | delta_bps populated | `oracle_lag_bps = None` on all 95 (logging bug masks it) |

## The two signals are NOT the same quantity

**Backtest signal** (`lag_taker_foundation_2026_05_29.py` + `LAG_TAKER_EDGE_RESEARCH`):
```
delta_bps = binance_1s(slot_start + offset) / binance_1s(slot_start) − 1, × 1e4
direction = Up if delta>0 else Down          # the binance INTRA-WINDOW move
```
= how much binance moved **since the slot opened**. Swings **symmetrically ±** → fires UP and DOWN ~50/50 → 68% WR. This IS the edge: binance leads chainlink by ~5-20s, so the side binance has moved toward in the first 5s tends to win.

**Live signal** (deployed gate `g_oracle_lag_with`, `sniper_v5_gates.py:805`):
```
bps = oracle_lag.price_delta_bps = (binance_feed − chainlink_oracle) / oracle × 1e4
leading = "UP" if bps>0 else "DOWN"
```
= binance feed **minus the chainlink oracle price** — a feed-vs-oracle BASIS, a different quantity. On the live box this sits **persistently positive** (the chainlink oracle/strike reference reads below the live binance feed — oracle lags an upward-drifting feed / small persistent offset), so `bps` lands in the **[+3,+12] UP band every time** and never in the [−12,−3] DOWN band. → **always UP.**

## This was a KNOWN, flagged substitution
Spec `TV_AGENT_SPEC_FAST_TAKER_LAGV2_2026_05_29.md §2.1` explicitly swapped the signal:
> "the backtest used `ret = binance(now)/binance(slot_start)−1`; the engine's `price_delta_bps` (feed-vs-oracle) is the **better** signal … the shadow run will confirm it reproduces the backtest WR."

The shadow run **DISPROVED** it: feed-vs-oracle ≠ binance intra-window return, and live it's degenerate (one-sided). We deployed the substitute signal without first verifying it reproduces the backtest's ±-symmetric direction split.

## Root idea (what the sleeve is SUPPOSED to do)
Binance leads the Polymarket/chainlink up-down resolution by ~5-20s. **In the first ~5s of a slot, whichever side binance has moved toward (vs the slot-open price) is the side that tends to close that way.** Buy that leading side's stale-cheap L25 ask, hold to resolution, cap |move| ≤12bps (bigger = already priced), exit on a ≥10bps binance reversal. Backtest 68% WR, +$2.4-3.4/$25.

## Why "just flip it to contrarian" is WRONG
Flipping always-UP→always-DOWN would make btc_15m look ~87% **in that 15-fire sample** — but that's only because BTC fell those 15 slots, not a real edge. An always-one-side bet has ~0 edge over many slots. The fix is **not** to invert; it's to **restore the working direction signal** so each slot fires the correct side (UP or DOWN).

## Fix
Change the gate to compute the **intra-window binance return** (the backtested signal), not the feed-vs-oracle basis:
```
delta_bps = binance_1s(fire_us) / binance_1s(slot_start) − 1, × 1e4
leading   = UP if delta_bps>0 else DOWN
gate      pass iff 3 ≤ |delta_bps| ≤ 12 AND direction == leading
```
i.e. read binance close at slot_start and at fire-time from the live klines feed; sign of the move = the side. This restores the ±-symmetric direction split (≈50/50 UP/DOWN) and the 68% WR. The reversal-stop should also measure binance move vs entry (it already does, via `price_delta_bps` — switch it to the same intra-window-return basis for consistency).

Also fix the logging bug: `oracle_lag_bps` is None on every resolved event (the value isn't captured into the log field) — populate it so this is visible next time.

## Applies to all 4 lagv2 sleeves
btc_5m / btc_15m / eth_5m / eth_15m — identical gate, identical bug. All fire 100% UP. btc_15m just drew the unluckiest small sample (13%).

## END
