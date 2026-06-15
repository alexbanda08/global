# Scalp exit config — per-timeframe (5m vs 15m) — maker vs taker, and the STOP question (2026-06-06)

**Script:** `strategy_lab/directional/maker_exit_by_tf_2026_06_06.py`
**Question (operator):** best config for 5m vs 15m scalp — which switches TP→maker, which keeps; Kalshi maintain?; keep the stop-loss?
**One line:** **5m keeps pure-taker +60; 15m switches to maker@0.60+fallback. KEEP the stop@−0.10 on both (it HELPS — this corrects the handoff's "disable the stop"), but the stop win is slippage-sensitive.** Kalshi stays taker.

Gated scalp BTC/ETH `entry_vwap<0.55`, in-sample Apr–Jun, n=780 (5m=531, 15m=249). Maker fill = first BUY trade ≥target in [fire,+60] (optimistic, no queue). Stop = bid path crosses `ev−0.10` → taker-cross at that level. Paired bootstrap CI vs pure-taker-+60.

## Results

### 5m (n=531)
| policy | $/tr | paired vs taker+60 |
|---|---|---|
| pure taker +60 (fixed-time argmax) | +2.91 | baseline |
| maker@0.65 + fallback | +3.32 | +0.41 **ns** |
| **taker +60 + STOP@−0.10 (slip 0c)** | **+3.79** | **+0.88 SIG+** |
| ↳ STOP slip 3c | +3.38 | +0.48 SIG+ |
| ↳ STOP slip 6c | +2.98 | +0.07 ns (dies) |
| maker@0.60 + STOP combo | +3.60 | +0.69 ns |

- Fixed-time optimum = **+60s** (peak; +45 = +2.68). Keep +60.
- **Maker-exit = ns on 5m** (fast/small move, little spread to capture over bid_60). → **keep TAKER.**
- **Stop is the real 5m upgrade (+0.88 SIG)** — caps losers that decay toward 0 instead of dumping at bid_60. Triggers 27.3%. Survives ≤3c slippage; gone by 6c.

### 15m (n=249)
| policy | $/tr | paired vs taker+60 |
|---|---|---|
| pure taker +60 (fixed-time argmax) | +1.78 | baseline |
| **maker@0.60 + fallback** | **+2.62** | **+0.84 SIG+** |
| maker@0.62 / 0.65 | +2.32 / +2.22 | +0.54 / +0.44 SIG+ |
| taker +60 + STOP (slip 0c) | +2.00 | +0.22 SIG+ |
| ↳ STOP slip 3c / 6c | +1.78 / +1.56 | ns / **SIG−** |
| **maker@0.60 + STOP combo** ⭐ | **+2.86** | **+1.08 SIG+** (CI [+0.54,+1.61]) |

- Fixed-time optimum = **+60s**. Keep +60.
- **Maker-exit SIG+ on 15m, best at the LOW target 0.60** (longer window → more spread to capture selling into a buyer lift). → **switch to maker.**
- Stop-alone is marginal on 15m and slippage-fragile, **but the maker@0.60+STOP combo is the single best 15m config (+1.08 SIG, t=7.89).**

## ANSWERS

| | **Poly 5m** | **Poly 15m** | **Kalshi 15m** |
|---|---|---|---|
| Take-profit | **drop taker-TP@0.65 → pure taker +60** | **drop taker-TP → MAKER@0.60 + taker-+60 fallback** | drop taker-TP → **pure taker +60** |
| Exit time | +60s | +60s | +60s |
| Stop-loss @ fill−0.10 | **KEEP** (big win, +0.88) | **KEEP** (combo w/ maker = best) | **KEEP** (protective; unverified on Kalshi book) |
| Maker rebate? | no | yes (0.60 offer) | **no — Kalshi has no maker rebate → stays taker** |

- **Which switches TP→maker:** only **Poly 15m** (maker@0.60). **5m maintains taker.** Kalshi maintains taker (no rebate; maker tested worse — `kalshi_scalp_maker_exit_2026_06_06.py`).
- **Kalshi:** maintain — taker +60, no maker. Same +60 + stop.
- **Stop-loss:** **maintain it on all three.** ⚠️ This REVERSES the handoff §D / `TV_AGENT_SPEC_SCALP_DISABLE_TP` recommendation to disable the stop. The handoff lumped "TP + stop" together; only the **taker-TP@0.65 leaks edge** (lookahead-confirmed in `SCALP_DYNAMIC_EXIT`). The **stop is protective and significantly positive**, especially 5m. → disable the TP, **NOT** the stop.

## Kalshi 15m stop — tested (`kalshi_scalp_stop_2026_06_06.py`)
Ran the same fill−0.10 stop on the Kalshi book. **Underpowered: n=15 (Kalshi data Jun2–5 only).**
| policy | $/contract | paired vs taker |
|---|---|---|
| pure taker +60 | +0.0467 | — |
| +STOP slip0 / 3c / 6c | +0.054 / +0.046 / +0.038 | +0.007 / −0.001 / −0.009 — all **ns** |

Stop triggers 27% (4/15), same as Poly. Point estimate flat, CI spans 0 everywhere → **no statistical case either way.**
**Decision: keep the stop as protective insurance** (rationale transfers from Poly; didn't hurt at n=15) but mark
UNPROVEN — re-test once Kalshi accrues weeks of data. Dropping it is also defensible; the data can't distinguish.

## Caveats / GROUND-TRUTH before deploy
- **Stop fill is optimistic** (sells at exact `ev−0.10`). Live = taker-cross a FALLING book in dislocated/thin scalp books (spread_filter 0.05). At 6c slippage the 5m stop edge vanishes and the 15m stop turns NEGATIVE. **Must re-test the stop with L25 queue/slippage-aware fill before trusting magnitudes.** Direction (keep it) is robust; size is an upper bound.
- **Maker fill is optimistic** (first buy-trade≥target, ignores queue). 15m maker win is SIG even so, but confirm with the queue-aware sim (handoff §E-1) + OOS on Mar30–Apr21 BBO.
- In-sample Apr–Jun. OOS pending.
- BNB/SOL excluded (underpowered). ETH/BTC only.

## Net recommendation
1. **Disable the taker-TP@0.65 on all live sleeves** (confirmed leak) — keep the existing disable-TP spec but **edit it to PRESERVE the stop**, not remove it.
2. **Poly 15m → maker@0.60 + taker-+60 fallback + stop** (best, +1.08). Shadow-first A/B (`TV_AGENT_SPEC_SCALP_MAKER_EXIT`).
3. **Poly 5m → pure taker +60 + stop.** No maker.
4. **Kalshi 15m → pure taker +60 + stop.** No maker.
5. Before scaling: queue/slippage-aware re-test of BOTH the stop and the maker leg + Mar30–Apr21 OOS.
