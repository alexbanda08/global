# Residual anatomy of the pros · are we in the same windows? · path to profit · 15m readiness — 2026-08-23

Data: full Aug-4→23 wallet pulls (deduped across tags; b27 464k fills these 2
days alone), Chainlink winners for every 5m+15m window, our complete 131-window
campaign, and the Ireland paper fleet's own `ladder_summary` telemetry (14 days,
per-window net with component decomposition).

---

## 1. What the professionals ACTUALLY do with residuals

Sells: **zero, re-verified** — no pro wallet sold a single share in the whole
sample. Everything unpaired rides to settlement. But WHAT rides differs by
model:

| wallet · tf | windows | pair% | resid% of book | resid WR | resid vwap | **resid EV ¢/sh** | pairs PnL | resid PnL |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| b27 · 5m | 1,556 | **93.7%** | 6.3% | 29.1% | 0.403 | −11.2 | +$51,693 | −$43,469 |
| b27 · 15m | 342 | **94.3%** | 5.7% | 42.0% | 0.446 | −2.6 | +$7,054 | −$1,868 |
| b945 · 15m | 1,085 | **92.5%** | 7.5% | 21.5% | 0.357 | −14.2 | +$47,741 | −$38,789 |
| b945 · 5m | 2,312 | 62.2% | 37.8% | 51.4% | 0.523 | **−1.0** | +$4,311 | −$2,027 |
| PBot-6 · 5m | 3,313 | 35.6% | 64.4% | 46.3% | 0.458 | +0.5 | +$2,326 | +$3,437 |
| PBot-5 · 5m | 1,973 | 23.0% | 77.0% | 48.3% | 0.451 | +3.3 | −$3,127 | +$11,022 |
| PBot-3 · 5m | 2,954 | 28.6% | 71.4% | **68.5%** | 0.641 | +4.5 | −$9,414 | +$8,300 |
| PBot-2 · 5m | 2,964 | 68.2% | 31.8% | **81.7%** | 0.652 | **+16.4** | −$25,816 | +$23,862 |
| **ours (all 131w)** | 131 | 69.9% | 30.1% | 19.9% | 0.354 | −15.4 | +$173 | −$248 |
| **ours (guard era, 18w)** | 18 | **85.3%** | 14.7% | 18.2% | 0.449 | **−26.8** | +$8.54 | −$14.73 |

Two professional models, and only two:
- **Pairing engines (b27, b945-15m):** residual squeezed to 6–8% of the book
  and ACCEPTED as a negative-EV cost line (−$1.9k to −$43k!) that the pairs
  out-earn 1.2–1.3×. They never fight the residual — they starve it.
- **Collectors (PBots):** residual is 64–90% of the book but lands on the
  winning side at prices BELOW its win rate (+0.5 to +16.4¢/sh) — the residual
  IS the product; "pairs" are incidental.
- b945's 5m sideline is the purest pricing lesson: only 62% paired, but his
  residual EV is −1.0¢/sh — **he never overpays the leg that might die.**

**Us:** the guard already moved pairing to 85% (pro territory) and residual to
14.7% — the STRUCTURE is now right. What remains wrong is residual QUALITY:
−26.8¢/sh, 2.4× worse than b27's, because our leftover clip is the collapsing
side bought above fair (vwap 0.449, WR 18%). We are a pairing engine whose
residual is priced like a bad collector.

## 2. Are we trading the same windows as the pros? — Yes (vs the ones that matter)

- **b27 is in essentially every 5m window, including all of ours** (9k–70k sh
  on our r8 sessions). Our windows are not special — the difference is behavior
  inside the window, not selection.
- **b945-15m "selectivity" is a SCHEDULE, not selection:** measured over 192
  recent windows he trades EVERY 15m window while on (all four :00/:15/:30/:45
  slots equally) and switches off daily **07:00–14:00 UTC**. No window-quality
  signal to copy — but his active hours are where two-sided 15m liquidity
  lives.
- PBots are posture-selective (pre-open/first-minute only), not window-selective;
  PBot-2 remains silent since Aug 18.
- Our drills (28–131 windows) sample the same population the pros grind 24/7;
  at our n, single-session variance dominates — judge across sessions.

## 3. Everything on the table — what flips us to profit (evidence-ranked)

1. **Ship `v3_faircap` (naked-only scope, round-8 spec).** It attacks the exact
   number this study isolates: residual EV −26.8¢/sh. Blocking naked loser-side
   quotes priced above `P_flip(elapsed,|d|)+2¢` turns the leftover clip from
   "collapsing side at 0.45" into "cheap-or-nothing": full-history replay
   −$39.33 → +$2.27. This is b945's measured posture (his loser legs price at
   fair everywhere).
2. **Port v5_tc's TAKER-COMPLETION to the 5m live sleeve (the b27 move).** Our
   one-sided windows (7 of 18 in r8) wait for a maker fill that never comes;
   b27 taker-completes the pair when `heavy_vwap + light_ask + fee ≤ tc_max_sum`
   (his decode: 15.5% taker share). On the 15m paper fleet this SINGLE change
   moves pairing from 0.13 (v3) to **0.79** (v5_tc) — b27/b945 territory. It
   directly converts our naked-clip windows into paired windows. Deploy behind
   the existing spec's gate (`tc_max_sum ≤ 0.98`, fee inside), pre-registered.
3. **Keep everything already verified:** 1-clip guard (enforcing, 18/18),
   Change A cuts, Change B entry window. Do NOT: early-exit residuals (nobody
   profitable does; retracted), tighten completion sum gate, blunt displacement
   ban, vol filter (absorbed by guard; rv5/rng15 already logged per window in
   `ladder_summary` if ever needed).
4. **Optional, cheap:** drill inside b945's active hours (avoid 07:00–14:00
   UTC) — both-side liquidity is measurably present when the big pairing books
   quote.
5. **Size honesty:** with 1–2 above working, 5m at current size projects
   ≈+$0.3–0.5/window. The multiplier is capital + 15m — gated by §4.

## 4. 15m: NOT ready for live — and exactly what makes it ready

14-day paper fleet, per-window nets from `ladder_summary`, with the campaign's
mandatory ex-top-2 outlier rule:

| sleeve | traded w | total | **ex-top2** | t(ex2) | pair_frac |
|---|---:|---:|---:|---:|---:|
| v4_wideglt | 164 | +56.86 | **−7.93** | −0.13 | 0.11 |
| v5_tc | 210 | +35.18 | **−5.32** | −0.27 | **0.79** |
| v4_mr | 171 | +19.72 | +6.62 | +0.33 | 0.12 |
| v3 (base) | 431 | +19.70 | **−3.66** | −0.05 | 0.13 |
| tc_live (allowlisted) | 97 | +12.13 | **−38.98** | −1.64 | 0.74 |
| v5_tcband / v4_paircomp | 98/173 | −24.65/−67.66 | −42/−83 | | |

**Every positive headline is carried by 1–2 outlier windows** (v5_tc: +$28.35 +
+$12.15 = more than its entire total). No arm passes the robustness bar; v5_tc
also misses its own pre-registered H2 (CI lower −0.175 < −0.15). Additionally,
`poly_ladder_btc_15m_tc_live` sits in the live allowlist while our wallet shows
ZERO 15m fills — TV agent should confirm its armed/filling state (its paper
twin is the worst ex-top2 on the table).

**Readiness plan (in order):**
1. **None of the 10 arms runs the validated 2026-08 stack.** Spawn ONE new
   paper arm `poly_ladder_btc_15m_v6_stack`: fills-only 1-clip guard + entry
   window 180s + cut gate 270s + faircap-naked (15m table is already banked in
   `ladder_sim_2026_08_21/flip_surface.json`, 900s rows) + v5_tc taker-completion.
   The current fleet tests 2026-07 ideas; the validated combination has never
   run on 15m.
2. **Pre-register the promotion gate:** n ≥ 250 traded windows (~2–3 weeks
   given b945-hours operation), pass = mean > 0 AND ex-top2 t > +1 AND
   pair_frac ≥ 0.6 AND residual EV per share > −5¢.
3. Only then: capital top-up ≥ $300, live at $10–20/side, b945 schedule
   (skip 07:00–14:00 UTC), judged against the paper twin.
4. Retire the clearly dead arms (v4_paircomp, v5_tcband) to free slots.

## 5. Verification

Residual table from deduped union of all cache tags (window books = BUY fills
per slug, hold-to-settle vs Chainlink winners; pros' zero-sell re-confirmed in
this pull); ours reconciles with round-8 cash to the cent (§2 of ROUND8 report:
pairs +8.54 / resid −14.73). b945 schedule measured on all 192 recent 15m
windows (4/8 per hour-bucket = every window while on, half the span; 0 fills
07:00–13:59 UTC; even :00/:15/:30/:45 split). 15m fleet stats from
`ladder_summary.total_net_usd` (traded = maker+taker sh > 0.1), ex-top2 per the
banked methodology; v5_tc taker fees confirmed inside its net (−$21.18).
Scripts: `ladder_sim_2026_08_21/{residual_anatomy.py, v5tc.txt, all15m.txt}`.
