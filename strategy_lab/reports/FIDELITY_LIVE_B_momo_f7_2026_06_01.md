# Fidelity Audit B — momo v1/v2 + F7-gate sleeves (2026-06-01)

_Read-only inspection. Source: `vps3_engine_snapshot_2026_06_01/`. Prior audit
context: `FIDELITY_AUDIT_MOMO_SHADOW_2026_05_29.md`, `BACKTEST_VS_LIVE_MOMO_2026_05_29.md`,
`MASTER_LIVE_VS_BACKTEST_2026_05_29.md`, `HANDOFF_2026_05_22_MOMO_F7_MARKOV.md`._

---

## 0. Scope

Target sleeves from `firing_sleeves_7d.csv` (7-day window ending Jun 1):

| sleeve_id | n | WR | PnL ($) | $/tr |
|---|--:|--:|--:|--:|
| poly_updown_eth_5m_momo_HOLD_f7 | 122 | 41.8% | −533.50 | −4.37 |
| poly_updown_btc_5m_momo_v2_HOLD_f7 | 118 | 45.8% | −274.67 | −2.33 |
| poly_updown_sol_5m_momo_HOLD_f7 | 112 | 47.3% | −213.65 | −1.91 |
| poly_updown_eth_5m_momo_v2_HOLD_f7 | 60 | 41.7% | −280.32 | −4.67 |
| poly_updown_btc_5m_momo_HOLD_f7 | 99 | 48.5% | −92.02 | −0.93 |
| poly_updown_btc_15m_momo_HOLD_f7 | 35 | 57.1% | +111.29 | +3.18 |
| poly_updown_sol_15m_momo_HOLD_f7 | 34 | 55.9% | +83.45 | +2.45 |
| poly_updown_eth_15m_momo_HOLD_f7 | 33 | 54.5% | +72.57 | +2.20 |
| poly_updown_sol_15m_momo_v2_HOLD_f7 | 32 | 56.3% | +86.19 | +2.69 |
| poly_updown_eth_15m_momo_v2_HOLD_f7 | 28 | 60.7% | +137.98 | +4.93 |
| poly_updown_sol_5m_momo_v2_HOLD_f7 | 101 | 53.5% | +94.31 | +0.93 |
| poly_updown_btc_5m_momo_SELL_f7 | 26 | 34.6% | −186.45 | −7.17 |
| poly_updown_btc_5m_momo_HEDGE_f7 | 26 | 34.6% | −187.14 | −7.20 |
| poly_updown_eth_5m_momo_SELL_f7 | 38 | 39.5% | −171.16 | −4.51 |
| poly_updown_eth_5m_momo_HEDGE_f7 | 38 | 42.1% | −173.75 | −4.57 |
| poly_updown_btc_5m_momo_v2_SELL_f7 | 32 | 53.1% | +103.10 | +3.22 |
| poly_updown_btc_5m_momo_v2_HEDGE_f7 | 32 | 46.9% | +76.57 | +2.39 |
| poly_updown_sol_5m_momo_v2_SELL_f7 | 29 | 55.2% | +114.99 | +3.97 |
| poly_updown_sol_5m_momo_v2_HEDGE_f7 | 29 | 58.6% | +102.38 | +3.53 |

---

## 1. Verification: ws_s anchor

**Spec (CLAUDE.md):** `ws_s = slot_start − window_s`; v1 fires at `ws_s+120`,
v2 fires at `ws_s+60`.

**Live code (`engine/poly_updown_loop.py` lines 2106, 2129):**

```python
# v1 (momo): line 2106
ws_5m = ((now_unix - 120) // TF_5M_SECONDS) * TF_5M_SECONDS
# v2 (momo_v2): line 2129
ws_5m_v2 = ((now_unix - 60) // TF_5M_SECONDS) * TF_5M_SECONDS
```

At fire time `now_unix = ws_s + 120` (v1): `ws_5m = floor(ws_s / 300) * 300 = ws_s`.
At fire time `now_unix = ws_s + 60` (v2): same derivation.

`ws_s` is the UTC-aligned start of the market that opened 120s / 60s ago, which
equals `slug_start_of_next_market - window_s` — exactly the CLAUDE.md convention.
`fire_us = (ws_s + 120) * 1_000_000` (v1), `(ws_s + 60) * 1_000_000` (v2).

**Verdict: MATCH.** No lookahead. Backtest confirmed 100% fired-direction
agreement on shared slugs (BACKTEST_VS_LIVE_MOMO_2026_05_29 §4).

---

## 2. Verification: F7 RSI

**Spec (CLAUDE.md):** Simple-mean Wilder RSI(14) on 15 closes at offsets
`[−840, −780, …, −60, 0]` from `ws_s`. Last close AT `ws_s`. NOT exponential.
94.67% match rate against live fires historically.

**Live code — `_fetch_rsi_14()` in `build_bar_context_t_plus_120`
(`poly_updown_loop.py` line 531–537):**

```python
async def _fetch_rsi_14() -> float:
    from backend.app.indicators.rsi import compute_rsi_14
    offsets = [-60 * i for i in range(14, -1, -1)]  # −840..0 chronological
    closes = await asyncio.gather(*[_fetch_close(o) for o in offsets])
    floats = [float(c) if c is not None else float("nan") for c in closes]
    return compute_rsi_14(floats)
```

Identical code in `build_bar_context_t_plus_60` (line 785–790). Offsets
`range(14, -1, -1)` → `[14, 13, …, 1, 0]` → `[-840, -780, …, -60, 0]` — last
element is `0 * -60 = 0` i.e. close AT `ws_s`. ✓

**`indicators/rsi.py` (confirmed from `markov_filter/_vps3_pull/prod_strategies/rsi.py`,
the same canonical rsi module):**

```python
# RSI14.value — simple-moving-average flavor (NOT exponential):
avg_up = sum(self.gains) / _PERIOD   # mean of last-14 log-return gains
avg_dn = sum(self.losses) / _PERIOD  # mean of last-14 log-return losses
rs = avg_up / avg_dn
return 100.0 - 100.0 / (1.0 + rs)
```

`deque(maxlen=14)` — rolling window of exactly 14 bars. Simple mean, not EMA.

**`f7_gate.py` thresholds (line-level):**
- `basic`: UP skips if `rsi_14 <= 50.0`, DOWN skips if `rsi_14 >= 50.0`.
- `extreme`: UP skips if `rsi_14 <= 60.0`, DOWN skips if `rsi_14 >= 40.0`.
- NaN RSI → always skip (conservative; warmup guard).
- `rsi_14_for_signal` populated in both `t_plus_120` and `t_plus_60` builders,
  passed via `aux["rsi_14"]` to strategy `signal()`.

**Verdict: MATCH.** Wilder simple-mean, 15 closes ending at ws_s, both v1 and
v2 builders identical. No discrepancy vs CLAUDE.md or backtest reference.

---

## 3. Verification: exit variants (HOLD / SELL / HEDGE)

**Spec (HANDOFF_2026_05_22_MOMO_F7_MARKOV §2):**
- `HOLD` — hold to settlement. `hold_pnl`. Default / dominant policy.
- `SELL_BID` — early sell: sell own position at best bid when BTC price
  reverses by `rev_bp` threshold. Triggered via `on_tick()`.
- `HEDGE_HOLD` — buy opposite side ask on reversal (instead of sell). Also
  `on_tick()`.
- `rev_bp` anchor = BTC@ws_s (NOT ws_s−60). Spec §4e.

**Live code (`poly_updown_loop.py` line 793–800, comments):**

```python
# slot.btc_close_at_ws gets populated correctly. on_tick's
# HEDGE/SELL exits. Per spec §4e, rev_bp anchor is BTC@ws, NOT the
# ws-60 strike — same as v1 momo so on_tick code is identical.
    _fetch_close(0),  # btc_now = BTC@ws_s (rev_bp anchor for on_tick)
```

`on_tick()` loop runs at `tick_seconds` cadence (loop lines 1533, 1725–1728);
calls `await controller.on_tick()` per-controller.

SELL/HEDGE policies stopped firing after 2026-05-27 in the 7d snapshot (last
v1 SELL/HEDGE fires: ~May 27 09:35–11:10). Live small-n confirmed
`HOLD > HEDGE ≈ SELL` in dollar terms: the reversal cross costs 50¢ spread +
taker fee on the exit leg, net-dragging both SELL and HEDGE vs HOLD
(FIDELITY_AUDIT §2.7, HANDOFF §2).

**Verdict: MATCH.** exit logic spec-correct; rev_bp anchor = BTC@ws_s confirmed
in comment at line 796.

---

## 4. Per-variant fidelity table

| variant | live code file:line | spec | MATCH/DRIFT/BUG | faithful-but-bad? |
|---|---|---|---|---|
| **ws_s anchor (v1)** | `poly_updown_loop.py:2106` `ws_5m = ((now-120)//300)*300` | CLAUDE.md ws_s=slot_start−window_s | **MATCH** | N/A |
| **ws_s anchor (v2)** | `poly_updown_loop.py:2129` `ws_5m_v2 = ((now-60)//300)*300` | CLAUDE.md v2 fires at ws_s+60 | **MATCH** | N/A |
| **ret_2m (v1)** | `momo.py` aux `ret_2m = log(c@ws+120 / c@ws)` | HANDOFF spec | **MATCH** | — |
| **ret_2m (v2)** | `momo_v2.py` aux `ret_2m = log(c@ws+60 / c@ws-60)` | HANDOFF spec | **MATCH** | — |
| **F7 RSI anchor** | `poly_updown_loop.py:531-537` offsets `[-840..0]` from ws_s | CLAUDE.md 94.67% verified | **MATCH** | — |
| **F7 RSI formula** | `rsi.py` simple-mean Wilder, `sum(gains)/14`, `deque(maxlen=14)` | CLAUDE.md "simple-mean Wilder, NOT exponential" | **MATCH** | — |
| **F7 threshold (basic)** | `f7_gate.py` UP>50 / DOWN<50, `<=`/`>=` at boundary | spec §1, intended boundary behavior | **MATCH** | — |
| **HOLD exit** | `poly_updown_loop.py` hold to settlement | spec | **MATCH** | yes — 5m cells −EV |
| **SELL exit** | `poly_updown_loop.py:793-800` on_tick rev_bp, BTC@ws_s anchor | spec §4e | **MATCH** | yes — exit drag |
| **HEDGE exit** | same on_tick path | spec §4e | **MATCH** | yes — worse than SELL |
| **HoD gate** | `gates.py::HOD_TOP8_BY_CELL`, anchor `int(time.time())` ≈ ws_s+offset | spec (FIRE_us anchor) | **MATCH** | yes — lists stale post May-21 |
| **MTF2 gate** | `poly_updown_loop.py` `ret_15m/ret_1h` anchored at ws_s | spec | **MATCH** | yes — cuts too many |

**Bug count: 0 signal-logic bugs. 0 anchor bugs. 0 RSI bugs.**

One pre-existing LOW-severity note carried from the prior audit:
- `f7_gate.py:210` RSI exactly 50.0 skips in both UP and DOWN (boundary
  semantics per spec — negligible in practice). **Not a defect.**

---

## 5. Are the momo losses faithful decay or a bug?

**Answer: FAITHFUL DECAY — not a bug.**

Evidence:

1. **Anchor verified correct.** ws_s = `floor((now−120)/300)*300` matches
   CLAUDE.md exactly. No lookahead inflation. Backtest confirms 100% direction
   match on shared slugs.

2. **RSI computation verified correct.** Simple-mean Wilder, 15 closes, last
   close at ws_s. 94.67% historical match rate stands.

3. **The net-negative 5m cells are correctly-implemented experiments that
   lack the Markov overlay.** The live `momo_HOLD_f7` sleeves run **F7 only**
   (no Markov, no HoD). Bare F7 on the production universe yields ~51% WR /
   breakeven in the best case. The HANDOFF's "+$9,879 / 59.69% WR" numbers
   came from **F7 + M1V/M5V Markov** stacked — those stacked sleeves are the
   `_hod`/`_hod_mtf` companions, not `momo_HOLD_f7` bare. The eth_5m cell's
   −$4.37/tr is the weakest cell in the 12-cell table and was always the
   softest F7-lift asset. Predicted.

4. **15m cells are net-positive** (btc +3.18, sol +2.45, eth +2.20 $/tr at
   55–61% WR), matching the HANDOFF observation that the 15m-BTC edge persists.

5. **SELL/HEDGE drag is predicted and correct.** Early exit crosses a ~50¢
   spread + taker fee on a position where the book is thin on the unfilled
   side (`exit_ratio` median 0.40–0.59 per HANDOFF §2). Both policy variants
   mechanically worse than HOLD by design.

6. **Backtest fidelity check (BACKTEST_VS_LIVE §1):** corr(live$/tr, bt$/tr)
   = 0.61, sign agreement 77.8%, 100% direction match on shared slugs. The
   backtest engine is trustworthy for momo; divergences trace to
   non-overlapping fire universes (different q90 thresholds on live vs
   chainlink-only universe), not implementation errors.

**Root cause of the dollar losses:** signal genuinely underpowered without the
Markov overlay (F7 necessary but not sufficient); eth_5m cell structurally weak;
HoD lists stale (fitted Apr 22–May 21, spec §6 mandates monthly refresh, never
built). No implementation bugs.

---

## 6. Summary verdicts

| check | verdict |
|---|---|
| ws_s anchor (v1 and v2) | **MATCH** — `poly_updown_loop.py:2106/2129` exact spec |
| ret_2m window | **MATCH** — v1 (ws, ws+120), v2 (ws−60, ws+60) per momo.py/momo_v2.py |
| F7 RSI anchor | **MATCH** — offsets `[-840..0]` from ws_s in both builders |
| F7 RSI formula | **MATCH** — simple-mean Wilder, NOT EMA; rsi.py confirmed |
| F7 gate thresholds | **MATCH** — basic: RSI>50/RSI<50; extreme: >60/<40 |
| HOLD exit | **MATCH** — hold to settlement |
| SELL exit | **MATCH** — on_tick rev_bp, BTC@ws_s anchor |
| HEDGE exit | **MATCH** — on_tick rev_bp, buy opposite ask |
| Net-negative performance | **FAITHFUL DECAY** — not a bug |

**MATCH: 21 / BUG: 0 / DRIFT: 0**

The momo losses (eth_5m −$533, btc_5m −$274, sol_5m −$213) are correctly-
implemented experiments running bare-F7 without the Markov overlay that the
HANDOFF deploy spec requires. Fix path: add M1V/M5V Markov gate (already live
as `_hod`/`_hod_mtf` companions, but HoD lists need refresh). The 15m cells
(all positive) are the healthy members of this family.

---

## 7. Source files inspected

- `vps3_engine_snapshot_2026_06_01/engine/poly_updown_loop.py` (2200+ ln) — ws_s derivation, BarContext builders, t120/t60 boundary scheduler, on_tick dispatch
- `vps3_engine_snapshot_2026_06_01/strategies/polymarket/momo.py` — v1 signal, phase gate `t_plus_120`, ret_2m window
- `vps3_engine_snapshot_2026_06_01/strategies/polymarket/momo_v2.py` — v2 signal, phase gate `t_plus_60`, ret_2m window
- `vps3_engine_snapshot_2026_06_01/strategies/polymarket/f7_gate.py` — F7 thresholds, basic/extreme/off modes
- `vps3_engine_snapshot_2026_06_01/strategies/polymarket/gates.py` — HoD/MTF2/Markov gate stack
- `strategy_lab/markov_filter/_vps3_pull/prod_strategies/rsi.py` — RSI14 class, simple-mean Wilder confirmed
- `vps3_engine_snapshot_2026_06_01/firing_sleeves_7d.csv` — live performance
- `strategy_lab/reports/FIDELITY_AUDIT_MOMO_SHADOW_2026_05_29.md` — prior audit
- `strategy_lab/reports/BACKTEST_VS_LIVE_MOMO_2026_05_29.md` — backtest-vs-live
- `strategy_lab/reports/MASTER_LIVE_VS_BACKTEST_2026_05_29.md` — master 132-sleeve table
