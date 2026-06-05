# Lag-Taker (FAST_TAKER_LAGV2) — Longer-Window OOS Re-Validation — 2026-06-01

Re-validates the leg-1 binance→chainlink directional lag-taker edge before any real-money
sizing (the open item from `HANDOFF_2026_06_01_AUDIT_LAGTAKER_FORENSICS.md` §B).

- Script: `strategy_lab/directional/lag_taker_oos_reval_2026_06_01.py`
- Fires: `strategy_lab/lag_taker_fires_oos_2026_06_01.parquet` (2,538 BTC/ETH/SOL filled fires)
- Segments CSV: `strategy_lab/directional/_results/lag_taker_oos_segments_2026_06_01.csv`
- Run log: `strategy_lab/directional/_results/oos_reval_run.log`

---

## TL;DR — DO NOT size up on real money yet. Forward OOS is encouraging but underpowered; backward probe is non-confirmatory (confounded by data source).

The directional edge is a **WR surplus over breakeven of ~3.6–4.2pp** in the fit window. It
**reproduces on the genuinely-forward, production-feed OOS** (May 29→Jun 1: +3.6pp surplus,
+$2.3/$25, WR 65.8%) but at small n (76 fires, 3 days, t≈1). It is **absent on the backward
probe** (Apr 24→May 8: +0.5pp surplus, ≈$0/tr) — but that segment is confounded: it relies on
**binance-vision 1s data, NOT the live `binance-spot-ws` feed production uses**, and it is an
earlier market regime. The aggregate "unseen" t-stat is **0.41 (base ≥3bps)** — not significant.

Net: the edge is real on production-representative data (fit + forward), but the longer-window
test does **not** deliver the statistical power needed to justify scaling. Collect 2–4 weeks of
**live-feed forward shadow** (with the corrected binance-return signal — see caveat 3) and re-test.

---

## 1. What changed vs the foundation, and why it matters

| | Foundation (2026-05-29) | This re-val (2026-06-01) |
|---|---|---|
| Window | May 8 → May 29 13:00 (~21d) | **Apr 24 → Jun 1 09:00 (~38d)** |
| 1s signal source | `binance-spot-ws` only | `binance-vision` (Apr 7→May 6) **+** `binance-spot-ws` (May 7→Jun 1) |
| Engine | pre-fix (min_book_events **not enforced**) | current (min_book_events=25 **enforced**, fix 2026-05-30) |

Two genuinely-unseen segments relative to the config frozen 2026-05-29:
- **`fwd_oos`** May 29 13:00 → Jun 1 (~3d, `spot-ws` = same feed as live) — the clean forward test.
- **`bwd_oos`** Apr 24 → May 8 (~14d, `binance-vision`) — extends backward but on a *different feed*.

The vision/spot-ws series do **not overlap** (vision ends May 6 23:59, spot-ws starts May 7 21:16;
~21h gap auto-dropped by a 10s asof-staleness guard). Returns are always computed intra-source
(fire vs fire−5s, same source), so there is no cross-source return contamination — but the
backward segment's *signal quality* is a vision-vs-live-feed question, not apples-to-apples with
production. **The forward segment is the production-representative OOS.**

---

## 2. Headline — UNSEEN vs FIT (BTC+ETH, hold-to-resolution, 0.07 fee)

| config | segment | n | WR | $/tr | total | t |
|---|--:|--:|--:|--:|--:|--:|
| **ge3** | FIT (IS+OOS) | 786 | 65.1% | +1.71 | +1342 | **2.38** |
| **ge3** | **UNSEEN (bwd+fwd)** | 556 | 60.8% | **+0.36** | +201 | **0.41** |
| ge3_ex18-23 | FIT | 575 | 67.1% | +2.67 | +1534 | **3.20** |
| ge3_ex18-23 | **UNSEEN** | 422 | 61.8% | **+1.13** | +476 | **1.10** |
| ge5 | FIT | 250 | 68.0% | +1.92 | +480 | 1.58 |
| ge5 | **UNSEEN** | 180 | 58.9% | **−0.63** | −113 | **−0.40** |

**The "sharper" ≥5bps gate INVERTS NEGATIVE out-of-sample** (−$0.63/tr, t=−0.40) — a classic
overfit signature. Do **not** use ≥5bps as the deploy gate. ≥3bps degrades but stays ≥0.

---

## 3. The split — it's a hit-rate (regime/feed) effect, isolated to the backward probe

WR surplus over the 0.07-curve breakeven WR, by segment (≥3bps, BTC+ETH):

| segment | n | WR | breakeven WR | **surplus** | $/tr | feed |
|---|--:|--:|--:|--:|--:|--|
| `bwd_oos` (Apr24–May8) | 480 | 60.0% | 59.5% | **+0.5pp** | +0.06 | vision |
| `fit_IS` (May8–18) | 286 | 63.6% | 59.4% | +4.2pp | +1.49 | spot-ws |
| `fit_OOS` (May18–29) | 500 | 66.0% | 62.1% | +3.9pp | +1.83 | spot-ws |
| **`fwd_oos` (May29–Jun1)** | 76 | 65.8% | 62.2% | **+3.6pp** | +2.28 | spot-ws |

The edge mechanism — directional hit-rate **above** breakeven — is **present and stable (~3.6–4.2pp)
in every `spot-ws` segment, including the forward OOS**, and **collapses to +0.5pp only in the
`vision`/late-April backward segment.** Because the backward weakness coincides exactly with the
feed switch, it is confounded: we cannot attribute it to regime vs vision-source noise. Either way,
the backward segment is **not** a valid refutation of a strategy that trades on the live feed.

ge3_ex18-23 forward-OOS is the strongest unseen cell: **+$4.36/tr, WR 68.5%, n=54** (t=1.54).

### Forward-OOS daily (≥3bps) — volatile, net-positive, underpowered
| day | n | WR | $/tr |
|---|--:|--:|--:|
| 05-29 | 36 | 61.1% | +0.60 |
| 05-30 | 10 | 80.0% | +8.95 |
| 05-31 | 14 | 57.1% | −2.24 |
| 06-01 | 16 | 75.0% | +5.83 |

3 of 4 days positive; net carried by 05-30 / 06-01. n too small for day-level confidence.

---

## 4. Stability cuts (UNSEEN, ≥3bps)

- **By asset:** BTC +$0.83/tr (WR 62.4%, t=0.73) carries; **ETH −$0.31/tr (t=−0.22) degraded.**
  Consistent with the foundation's "BTC most robust."
- **By tf:** 5m +$0.37 (t=0.38), 15m +$0.32 (t=0.14). 15m lost its fit-window "cleaner" edge on
  unseen data — the 15m preference does **not** survive OOS.
- **SOL:** only **13** fills cleared min_book_events=25 at ≥3bps (vs 635 in the foundation under the
  un-enforced engine) → ≈$0. Confirms SOL L25 is genuinely too thin to trade; correctly excluded.

---

## 5. Caveats / why the absolute numbers moved vs the foundation

1. **Engine min_book_events=25 now enforced** (fix 2026-05-30). This rejects thin-book fills the
   foundation silently accepted. Fit-window base ≥3bps fell from the foundation's **+$2.39/tr to
   +$1.71/tr (−28%)** purely from this. The current engine is *more* live-faithful, so re-baseline
   deploy expectations to the lower number.
2. **Backward segment is vision-sourced** → not production-representative. Treat it as a regime
   probe, not an OOS verdict.
3. **The live impl had a wrong-signal bug** (`LAGV2_ROOTCAUSE_ALWAYS_UP_2026_06_01.md`): production
   read feed-vs-oracle basis (100% UP) instead of the intra-window binance return used here. This
   backtest uses the CORRECT signal. Any forward live shadow must run the fixed signal
   (`TV_AGENT_FIX_LAGV2_SIGNAL_2026_06_01.md`) or its data is worthless for this re-test.
4. Forward OOS is only ~3 days / n=54–76 → t≈1–1.5. Encouraging, **not** conclusive.

---

## 6. Recommendation

**Hold real-money sizing.** The directional lag edge is confirmed on production-feed data (fit +
forward, ~3.6–4.2pp WR surplus, +$1.7–2.7/$25 at ≥3bps after the real fee + min-book gate), but the
longer-window test is underpowered and the only large unseen block is feed-confounded.

Path forward:
1. Land the LAGV2 signal fix (B1) so live fires use the binance-return signal (≈50/50 UP/DOWN).
2. Run `FAST_TAKER_LAGV2` **paper/shadow at minimal stake**, BTC-first, gate **≥3bps + ex-18-23 UTC**
   (NOT ≥5bps — it's overfit). Hold-to-resolution.
3. Accumulate **2–4 weeks** of live-feed forward fires; re-test for the +3.6pp surplus with n large
   enough for t≥2.5 before any real sizing. Drop the 15m sleeve unless it re-confirms.

## END
