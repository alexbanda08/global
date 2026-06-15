# 5-LENS STRATEGY AUDIT — 2026-06-12

Five parallel opus auditors: harness code, statistical rigor, live-deploy parity, data integrity, missed-edge synthesis.
All findings cross-referenced; convergent findings flagged. GROUND-TRUTH RULE applies to every magnitude below.

---

## A. FLAWS — ranked

### A1. [CRITICAL — convergent, 2 agents] The scalp's exit-fee proxy is unverified and likely ~5× too low
`bpnl` charges `0.015·sh·(ev(1−ev)+sell(1−sell))` in EVERY scalp driver + `scalp_fill_lib_2026_06_10.py:64`.
A taker buy + taker sell at the live 0.07 curve would charge **0.07** on the round trip:
- ev=0.45, sell=0.55, 55 sh: gross +5.50 → proxy net +5.09; live-both-legs net **+3.59** (−1.50/tr); live-sell-only net **+4.55** (−0.55/tr).
- BUT host-side audit (96c4b786 F-fixes) measured the `sell_leg_fee=0.0→fixed` drag at only **~$0.15/tr** — so the TRUE live
  fee model for a mid-window taker sell on crypto-updown is **UNVERIFIED** (operator-confirmed model covers HOLDS only:
  winner-only 0.07 at settlement, $0 on losers; the intra-window sell leg was never ground-truthed).
- **Inflation bound: $0.15–1.50/tr against a claimed +1.85/tr edge.** At the upper bound most of the edge is fee fiction.
- **FIX #1 (ground truth):** pull actual LIVE scalp sell fills from `poly_updown_resolution`/trade events (Ireland $1 sleeve
  has real sells) and back out the exact fee charged on the sell leg. Then set `bpnl` to that and re-run the OOS table.

### A2. [HIGH — convergent, 2 agents] ~1s signal lookahead: bar-START asof in every scalp driver
`asof(be,bc, ss+5e6)` searchsorts on `time_period_start_us` (bar OPEN) → numerator close realized at **ss+6s**, fire at
ss+5s+85ms. Probe-verified bar `[start, start+999999]`. Canonical `asof_strict` has correct END-time semantics; the
drivers bypass it with a local `asof` (pattern in `scalp_oos_bbo_2026_06_05.py:53`, `_fixed_2026_06_10.py:81`,
`scalp_synth_book:174`, `gate_soften:92`, `microprice:49`, `maker_sim:143`, trailing drivers...).
- Quantified (BTC Mar30–Apr21, 6,336 slots): direction agreement leaky-vs-causal **99.5%**; but **29.5% of fires are a
  different slot set** (the leak cherry-picks borderline δ≥3 gate decisions with 1s hindsight). Causal signal fires MORE
  (728 vs 628). Net: modest inflation via selection, direction essentially intact.
- **FIX #2:** end-indexed asof (searchsorted on `time_period_end_us` or `load.asof_strict`) in ALL drivers; re-run.

### A3. [HIGH — stats] Magnitudes are in-sample; only DIRECTION is validated
- The +$1.85/tr "bug-fix rerun" is on the SAME burned Mar30–Apr21 window (re-read ≥6×) — it validates the bug fix, not
  the edge. Retro's own trust table: direction HIGH, magnitude LOW (~⅓ ⇒ expect ~+$0.6/tr).
- Family-wise trial count ≈ 56 scalp variants: headline pooled edge SURVIVES Bonferroni (p×56=6.3e-4 ✓).
- **momalign +$4.24/tr:** "pre-registered" claim has no timestamped artifact; its "OOS" is a tail-split of the search
  window (Apr24–Jun8 overlaps Apr22–Jun4) — NOT disjoint. Survives Bonferroni only barely (p×56=0.021). FRAGILE.
- **cloud_vwap_hurstmp_v7 DSR 0.94:** n_trials=25 indefensible vs 155-sleeve fleet. DSR(155)≈0.90 only because implied
  trial variance is unrealistically tiny; underlying t=2.32 ⇒ **fails Bonferroni at both N=25 (p×25=0.51) and N=155**.
  Selected-on-shadow. Treat as hypothesis; forward-only validation.
- Live evidence: **~18–21 live fires**, partly on the WRONG config (TP/stop era). No positive live $/tr exists anywhere.

### A4. [HIGH — data] The scalp OOS window is a LAYER change with zero Chainlink overlap
`resolutions_hf` (Jan2–Apr21) ∩ `resolutions_from_rtds` (Apr24+) = **0 common slugs**. OOS outcomes = 49% aliplayer +
28% bmoney + 23% settle-DERIVED — never externally Chainlink-validated. Plus different collector (BBO vs L25 vs prod WS).
"OOS-validated" conflates data-source effects with time effects. Label scalp OOS as backfill-layer-internal.

### A5. [HIGH — live] Dead maker-exit STILL configured on the live $1 sleeve
`TV_AGENT_SPEC_SCALP_DISABLE_MAKER_EXIT_2026_06_11.md` PENDING; `scalp_exit_mode="maker_fixed"` verified set on
generator + explicit blocks + the live allowlisted `shadow_scalp_exit_btc_15m_d3_v1`. The supporting +$0.42 reversed to
−$0.07 ns. Live impact muted (maker lift never fills → taker fallback) but breaks live↔shadow parity.

### A6. [MED — live] Deployment-state gaps
- cloud_vwap_v7 deploy + coinflip-filter specs (the only DSR-passing new sleeve) idle since 06-09 — apply as a PAIR.
- **76 KILL sleeves: disable UNVERIFIABLE from this repo** (no spec/commit). Blind spot — need host-side allowlist diff.
- Ireland duplicate-resolution bug (1 slug→106 rows): no fix spec found; if dashboard dedup doesn't collapse it, Ireland
  live PnL is corrupted.
- HL V52/XSM production cards dead (`bundle: none`) — port `hl_perp_loop` or hide cards.
- `maker_probe_btc15m` spec is SUPERSEDED (b945 handoff explicit) — risk of accidental application by a spec-reading agent.

### A7. [MED — harness] iid bootstrap overstates ALL CIs
Fires cluster by slug/hour/coin; per-fire iid resampling ⇒ CI too narrow, t too large, in every driver. Use slug-block
(or UTC-hour-block) bootstrap before any go-live CI claim.

### A8. [LOW] Misc
- `resolve_size` forward-carry (next positive size ≤300s AFTER) is technically lookahead; rarely binds (order 55 sh vs
  p10 depth 5,210). Test: disable forward branch, confirm $/tr unchanged.
- OOS BBO drivers omit `min_book_events` screen (BBO ~200Hz, usually moot).
- `scalp_oos_bbo_2026_06_05.py` still contains the outcome-leak fallback (line 82) — superseded by `_fixed_2026_06_10`;
  header-mark it SUPERSEDED to prevent reuse.
- BBO entry size==0 artifact (47.2% confirmed) halves OOS fill counts — a fill-RATE haircut, not a price bug.
- Local infra: `python` alias is a broken MS-Store stub (exit 9009); use `py`.

### CLEAN (verified, do not re-audit)
`engine_v2` hold_pnl both branches (winner formula exact match 23.1528), latency shift semantics, find_book_strict
causality, exit_fill staleness/entry-idx guards, held_value(won) usage (remainder-only, faithful), book_walk orderings,
fees curve, spread float-fix, underfill rule, BBO +60s exit price freshness (max stale 7.8s — exit price executable),
loader determinism, resolutions_hf.slot_end_us 0% null, canonical freshness matches Jun-11 claims.

---

## B. MISSED EDGES — ranked (edge-hunter, premise-corrected)

Status corrections: oracle-gated maker DONE & DEAD (06-12, all 6 cells ~0 — b945 thread parked for good);
lazer-δ entry A/B already LIVE (18 sleeves, VPS3); queue maker-exit dead. Remaining genuinely-open:

1. **Poly×Kalshi deep-dip arb — EXECUTE.** Only item signal-validated AND depth-validated AND capacity-real
   (+2.7¢/set <0.95, 88% fillable ≥$5, ~200–240 opps/day). Blocker purely operational: dual-venue order path +
   settlement-agreement filter (4% disagreement ≈ 37 winning sets each — use <0.90 tier). Honest $2–6/day at $5/set,
   $20–60/day at $50/set. The only credible path past ~$20/day on the board.
2. **Binance 1s taker-OFI entry gate — FREE test, data ready.** `taker_buy_base/quote` never extracted; reads the CAUSE
   of the Binance move (escapes the priced-in trap that killed Poly-CVD). Independent substrate (klines_1s Jan–Mar,
   NOT the burned BBO window). Dose-response by OFI quintile. Maybe +$0.3–0.8/tr by trimming anti-aligned losers.
3. **Lazer-as-EXIT-timing** (hold past +60s iff lazer δ not reverted) — different input class than the dead trailing
   exits (settlement-value preview, not noise). Needs 1–2 wk Lazer collector accrual. High chance +60s already optimal.
4. **HL ETH-4h Donchian promotion** — Sharpe 3.32 sitting in shadow; 4wk gate clears ~early July; regime-muted near-term.
5. Kalshi pre-subscribe scalp port (4¢ entry penalty likely eats the edge) / perp-basis regime gate (weak prior) — low.

---

## C. ACTION ORDER

1. **Ground-truth the live sell-leg fee** from actual Ireland scalp sell fills (A1) — decides whether the edge is
   +$1.7/tr or +$0.4/tr. Everything else is downstream of this number.
2. **Fix #2 (causal end-time asof) + slug-block bootstrap + corrected fee → ONE pre-registered re-run on the untouched
   Feb21–Mar24 L25 window.** Single shot, never re-read. This is the only honest OOS left.
3. **One restart, both hosts:** apply maker-exit-disable + cloud_vwap_v7 deploy + coinflip filter (3 pending specs).
4. **Reset the live fire counter** post-final-config; graduate at n≥200 live fires, judged by live wallet CI.
5. **Host-side verification:** 76-KILL disable diff + Ireland 106-row dedup fix.
6. **Build the Kalshi dip-arb executor** (B1) in parallel — independent of the scalp question entirely.
7. Run the OFI gate test (B2) — free, one session.

---

## D. EMPIRICAL RESOLUTION of A1+A2 (2026-06-12, `scalp_causal_asof_oneshot_2026_06_12.py`)

Tested directly instead of asserting. Results supersede the A1/A2 framing above:

- **A2 (1s lookahead) CONFIRMED real + previously unfixed.** Schema probe: `time_period_start_us`=bar OPEN, end=start+999999.
  Every driver incl. the 06-10 "fixed" one computes the delta signal via start-time asof → numerator close at ~ss+6s, fire
  at ss+5s+85ms (~0.9s future). Paired leaky(L)-vs-causal(C) one-shot, identical else:
  - POOLED gated ev<0.55: **ARM L +1.714/tr (t=5.23) → ARM C +1.015/tr (t=2.92, CI[+0.32,+1.69]).**
  - **Edge SURVIVES causally (CI>0).** Lookahead inflated backtest **−41%** via hindsight slug/direction SELECTION
    (lead-flips 36/2806=1.3%; paired same-fire C−L≈0, only 22/2070 nonzero). Bigger than the audit's "modest" estimate.
- **A1 (fee) DOWNGRADED.** Operator correct: hold fee = winner-only 0.07, $0 on losers (already in held_value/hold_pnl).
  The $0.55–1.50/tr figure conflated that with the intra-window sell leg; irrelevant here (both arms share `bpnl`).
- **Feb21–Mar24 OOS is IMPOSSIBLE for the +5s scalp.** Probe: L25-backfill AND trades_hf both start ~80s into each slot
  (recorder subscribed late — min first-trade +32.5s, median +83s, 0 pre-slot prints in 880k trades). No book to fill a
  +5s entry. The "clean OOS window" recommendation is retracted.
- **LIVE was never affected** (production anchors causally on ws_s closes) → live shadow is the unbiased estimator
  (~+$1/tr expected, not +$1.7). Reinforces judge-by-live n≥200. The only true OOS left = live forward fires.

**Net:** the scalp edge is real but ~60% of the headline magnitude. The actionable fix is to patch every driver's signal
asof to end-time (so future backtests aren't inflated) and trust live over backtest.
