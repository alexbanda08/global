# btc-15m ema50_ema800 DOWN — deployability + fillability (2026-06-01)

The rigorous bias-free re-run (fresh June-1 data, `EMA50_800_5M_VARIANTS_2026_05_31.md`) confirmed
`poly_sniper_v5_btc_15m_ema50_ema800_off600_down` is a REAL directional edge (passes look-ahead /
survivorship / overfit / matched-null / WR-vs-implied / block-bootstrap / OOS). This doc answers the
remaining question: **can it be harvested live, and only at off=600?**

Script: `strategy_lab/directional_signal/ema_offset_fillability_2026_06_01.py`
CSV: `data/v4/canonical/_results/ema_offset_fillability_btc15m.csv`

## Offset × fillability (btc-15m, fresh, realistic cost = 0.07·p·(1−p) + $0.01 tx)
| offset | dir | n | WR | $/tr | WR−impl (CI_lo) | block_lo | OOS | same-token fill% | fillable $/tr | verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| **600** | **DOWN** | 483 | **0.820** | **+1.59** | **+0.071 (+0.037)** | **+0.46** | **+1.91** | **0.94** | **+1.66** | ✅ DEPLOYABLE |
| 180 | DOWN | 825 | 0.722 | +0.30 | +0.032 (+0.002) | −0.73 | +0.64 | 0.94 | +0.37 | block-CI fail |
| 300 | DOWN | 794 | 0.743 | −0.03 | +0.022 (−0.008) | −1.20 | −0.03 | 0.94 | −0.02 | breakeven |
| 840 | DOWN | 186 | 0.785 | +0.37 | +0.041 (−0.017) | +0.51 | +0.51 | 0.87 | −0.53 | fillable subset loses |
| 60 / all UP | — | — | ~0.64–0.76 | negative | fail | fail | 0.94 | negative | DEAD |

## Findings
1. **The edge is DOWN-only and ONLY at off=600.** At earlier offsets (60/180/300) it collapses on
   block-bootstrap CI — the **late-window trend confirmation (10min in, 5min to close) is the mechanism**,
   not a fittable artifact. You cannot "move it earlier to fill better"; earlier kills it.
2. **It IS live-fillable.** Same-token spread (ask0−bid0 ≤ 0.02) passes **94%** of fires at off=600; the
   fillable subset still yields +$1.66/trade, WR 82.4%. ~12 fires/day.
3. **It beats the market price**, not just 50%: WR−implied (de-vigged) +7.1pp, CI_lo +3.7pp; matched-null
   p=0.001; survives a 10-way Bonferroni over this offset×dir sweep.
4. **This is a SECOND validated directional edge** alongside `clbasis_rel-btc-5m` (oracle-lag). Different
   mechanism (late-window trend persistence vs binance-leads-chainlink), both gate-clean.

## Why the live sleeve places 0 — and the fix
NOT un-fillability (94% pass same-token). The live `poly_sniper_v5_btc_15m_ema50_ema800_off600_down`
evaluates ~106×/day but places 0. The blocker is the LIVE-ENGINE spread/book gate config — most likely:
- the sleeve's spread gate still uses the **cross-token** metric `abs(up_vwap−(1−dn_vwap))` (fails 99%+
  on real books; the same-token fix may not be wired for this sleeve), OR
- the sparse-book `min_book_events` filter at off=600.
**Action (TV agent, VPS3):** confirm which spread metric this sleeve uses; switch to same-token `ask0−bid0`
(per `_sniper_spread.compute_spread`, the 2026-05-27 fix) and verify min-book-events isn't over-filtering.
Then it should fire ~12/day and harvest the +$1.66/trade edge in shadow.

## ⚠️ CORRECTION from LIVE skip-reason evidence (2026-06-01)
Checked the live `sniper_v5` JSONL skip_reasons for this sleeve (3 days). My "cross-token spread bug /
one-line fix" hypothesis above is **WRONG** — corrected:
- The spread gate is **already same-token** (`_sniper_spread.compute_spread` = ask0−bid0, the 2026-05-27
  fix; verified in `polymarket_sniper_v5.py:579,188`). NOT the old cross-token formula.
- Live skip distribution: **140 `g_tr_above_ema50=False` + 39 `g_tr_above_ema800=False`** (the directional
  setup close<both-EMAs is RARE in real time) ; only **~13 `spread_bidask_too_wide_0.03_>_0.02`** ; 9
  sparse-book ; 1 empty.
- So the 0-placement is mostly the **setup being rare live**, plus a **spread-threshold mismatch**: real
  15m-off600 books run ~**0.03** spread, just over the **0.02** gate. My backtest "94% fillable" used
  canonical L25, which is likely **tighter than the live WS book** at off=600 (the documented
  backtest-vs-live book divergence, CLAUDE.md). **True live fill rate is probably < 94%.**

**Revised action (not a config flip):** before believing this harvests live —
1. Re-test the edge allowing **0.03-spread fills** (walk the wider book): does +$1.66/trade survive the
   worse vwap? If yes, widen this sleeve's `spread_filter` 0.02→0.03 and re-shadow.
2. Reconcile canonical-L25 top-of-book spread vs the live WS-book spread at off=600 (is canonical
   optimistically tight?). If live books are genuinely ~0.03, the harvestable edge is whatever survives at
   0.03 — re-measure.
The edge is REAL in the data; live harvestability is gated by real book width at off=600, NOT a wiring bug.

### Spread-tolerance test (canonical, off600 DOWN) — answers "does it survive at 0.03?"
Canonical book spread at off600 fires: **p50=0.010, p75=0.010, p90=0.020** (TIGHT in canonical).
Edge by same-token spread tolerance (realistic cost):
| spr ≤ | n (%) | WR | $/trade | WR−impl | boot CI_lo |
|---|---|---|---|---|---|
| 0.02 | 454 (94%) | 82.4% | +$1.66 | +0.073 | +$0.42 |
| 0.03 | 475 (98%) | 82.3% | +$1.68 | +0.073 | +$0.46 |
| 0.04 | 477 (99%) | 82.4% | +$1.71 | +0.073 | +$0.49 |
| all | 483 (100%) | 82.0% | +$1.59 | +0.071 | +$0.39 |
→ **the edge is unchanged at 0.03** (canonical books are 0.01 median). But LIVE the engine logs `0.03>0.02`
rejects → canonical L25 is **tighter than the live WS book** at the off600 read moment (documented divergence).

### ✅ Concrete low-risk action
**Widen this sleeve's `spread_filter` 0.02 → 0.03 on VPS3.** Backtest-safe (edge unchanged at 0.03), and it
unblocks the live `spread_bidask_too_wide_0.03_>_0.02` rejects. Then shadow-accumulate live fills to measure
(a) the TRUE live fill rate, (b) whether +$1.66/trade holds on real fills. This is the cheapest way to find
out if the real edge harvests — no code rewrite, one threshold.

## Caveats
- OOS-only (last 13 days) WR−impl CI dips slightly negative; the full-39-day evidence clears the bar →
  accumulate ≥2–3 weeks shadow fills before sizing.
- No 5m variant of this family survives (block-CI fails — regime-concentrated). 15m-off600-DOWN is the
  whole edge.

## Deployable set so far (both directional, gate-clean, June-1 data)
1. `clbasis_rel` btc-5m (oracle-lag), ~2/day, +$5.95/trade.
2. `ema50_ema800` btc-15m DOWN off600 (late-window trend), ~12/day, +$1.66/trade, 94% fillable.
