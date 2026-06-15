# V52-Optimized Shadow Mode — Deployment

**Status:** LIVE (paper). Scheduled Windows task `V52Shadow` runs hourly.
**Wired:** 2026-06-08 (V52) + 2026-06-09 (XSM basket + sleeve cards). Data auto-refreshed each tick.
**Mode:** PAPER ONLY — records what the live bots WOULD do. Submits no orders, moves no money.
**Fleet:** 9 V52 per-coin sleeves (active trader) + 1 V24-XSM 9-coin basket (defensive, currently cash). 10 sleeve cards under `cards/`.

---

## What this is

The optimized V52 fleet (9 sleeves) running in shadow/paper mode on Hyperliquid 4h perps.
Each hour the scheduled task refreshes HL data and recomputes the full fleet state from
history, logging fires, open paper positions, and pending entries.

### Fleet (9 sleeves)

| Sleeve | Coin | Signal | Variant | Gate (NEW) |
|---|---|---|---|---|
| **STF_BTC** ⭐NEW | BTC | SuperTrend(10,3.0)+EMA200 | V45 (vol>1.1×20MA) | FUND_Z<2 |
| CCI_ETH | ETH | CCI(20) extreme + ADX<22 | V41 regime exits | FUND_Z<2 |
| STF_SOL | SOL | SuperTrend(10,3.0)+EMA200 | baseline | FUND_Z<2 |
| STF_AVAX | AVAX | SuperTrend(10,3.0)+EMA200 | V45 (vol>1.1×20MA) | FUND_Z<2 |
| LATBB_AVAX | AVAX | Lateral BB fade, ADX<18 | baseline | FUND_Z<2 |
| MFI_SOL | SOL | MFI(14) extreme 25/75 | V41 regime exits | ATR_NOTOPVOL |
| VP_LINK | LINK | Volume-profile rotation | baseline | ATR_NOTOPVOL |
| SVD_AVAX | AVAX | Signed-volume divergence | baseline | ATR_NOTOPVOL |
| MFI_ETH | ETH | MFI(14) extreme 25/75 | baseline | ATR_NOTOPVOL |

**New gates (from the 2026-05-26 optimization audit):**
- `FUND_Z<2` — skip entries when 4h-funding z-score (rolling 500) |z|≥2. Lifts all 5 V41-family sleeves.
- `ATR_NOTOPVOL` — skip entries when ATR(14) percentile-rank (rolling 500) ≥0.80. Lifts all 4 volume diversifiers.

**Exits:** EXIT_4H (tp 10 ATR / sl 2 ATR / trail 6 ATR / max_hold 60 bars) for baseline; V41/V45 use regime-adaptive REGIME_EXITS_4H.

### XSM basket (V24, separate book)

V24-XSM cross-sectional momentum on a 9-coin universe (BTC/ETH/SOL/LINK/ADA/XRP/BNB/DOGE/AVAX),
4h bars, weekly rebalance. **Long top-4 by 14d momentum** only when the `multi_filter` passes:
BTC > 100d-MA **AND** BTC 50d-MA rising **AND** breadth ≥ 5/9 coins above own 50d-MA. Else → CASH.

- **Currently FLAT** (breadth 1/9, BTC below 100d-MA) — correct defensive behavior. The filter
  passed only ~4.5% of 2026 bars; it is doing its job, not broken.
- **Live allocation 0%** — only 5 of 9 coins are HL-tradeable. Kept shadow-only until the HL
  universe widens (per the optimization audit; every filter relaxation tested made it worse).
- Data: BTC/ETH/SOL/AVAX/LINK close from fresh HL; ADA/XRP/BNB/DOGE from Binance Vision 4h
  (close corr 0.9997 — interchangeable for MA/momentum).

---

## Files

| File | Purpose |
|---|---|
| `shadow_tick.py` | The scheduled unit: refresh HL data → V52 runner → XSM eval → rebuild cards. Idempotent. |
| `shadow_tick.bat` | Windows Task Scheduler wrapper (logs to `tick.log`). |
| `_register_task.py` | Registers/removes the hourly `V52Shadow` scheduled task. |
| `register_task.bat` | Same, as a double-clickable .bat. |
| `xsm_shadow.py` | V24-XSM basket evaluator (9-coin cross-sectional momentum + multi_filter). |
| `build_sleeve_cards.py` | Generates the 10 sleeve cards (JSON) + `SLEEVE_CARDS.md` index. |
| `cards/*.json` | One card per sleeve: spec + gate + exit + weight + validated metrics + live status. |
| `SLEEVE_CARDS.md` | Human-readable card index for the whole fleet. |
| `XSM_STATUS.md` / `xsm_status.csv` | XSM filter state + target basket each run. |
| `../strategy_lab/hl_research_2026_05_26/v52_v24_audit/v52_shadow_runner.py` | The V52 shadow engine (signals+gates+sim+fire detection). |

### Outputs (written every run)

| File | Content |
|---|---|
| `positions_latest.csv` | Per-sleeve snapshot: FLAT / OPEN (dir, entry, unrealized). |
| `pending_fires_latest.csv` | Fresh fires on the just-closed bar → enter at next open. |
| `fires_ledger.csv` | Append-only, de-duplicated history of all paper fires (entry→exit→PnL). |
| `run_log.csv` | One row per run: ts, n_open, n_pending, n_recent_closed, ledger_total. |
| `STATUS.md` | Human-readable current state. |
| `tick.log` | Scheduler stdout log. |

---

## Schedule

Registered as Windows scheduled task **`V52Shadow`**, hourly at HH:05.

The tick is idempotent and cheap (no-op when no new 4h bar exists), so hourly polling
catches each 4h bar close (UTC 00/04/08/12/16/20) within ~1h without timezone-alignment
fiddling.

```
Verify:   schtasks /Query /TN V52Shadow
Run now:  schtasks /Run   /TN V52Shadow
Remove:   py shadow_v52\_register_task.py --delete
Re-add:   py shadow_v52\_register_task.py
```

---

## First-run verification (2026-06-08)

End-to-end confirmed via Task Scheduler → .bat → refresh → fire → logs:

- **46 paper fires** in the last 60 days across all 9 sleeves (STF_BTC fired 3×, all TP wins).
- Paper PnL **+$267 / 60d** at $250/sleeve notional; win-rate 34.8% (asymmetric: SL caps −3%, TP runs +15–24%).
- Fleet currently **FLAT** (0 open, 0 pending) — last fire Jun 1, last exit Jun 5. This is the true current state, NOT a data-staleness bug (the prior "flat" was 44-day-stale data, now refreshed).

---

## Reality check (read before risking capital)

This is the **optimized V52** validated on 2024-01 → 2026-06 HL data. Honest caveats:

1. **2026 is a degraded regime** for V52 — alt realized-vol collapsed ~30% and funding fell to ~1/3 of 2024. The audit confirmed this is a regime story, not a bug. Expect lower returns than the 2024-25 backtest until vol returns.
2. **Win rate is low by design** (~35%) — the edge is the asymmetric exit (small stops, large trailing TP). PnL comes from a few big winners. Drawdown discipline matters.
3. **Paper first.** Per the V52 deployment notes, run ≥4 weeks of shadow and check: per-sleeve fire count within ±25% of expected, aggregate realized Sharpe > 1.2, funding accrual reconciles ±5%, no single sleeve −12% DD. Only then size real capital.
4. **STF_BTC is new** — never live before. It carried 2026 in backtest (+3.61 Sharpe) but has the shortest track record. Watch it closely.

---

## How to read the daily state

```
py shadow_v52\shadow_tick.py        # manual tick (or let the scheduler do it)
type shadow_v52\STATUS.md           # current open positions + pending fires + recent trades
```

A **pending fire** in `pending_fires_latest.csv` = the live bot would open that position at
the next 4h bar open. That's your signal that shadow mode "fired".
