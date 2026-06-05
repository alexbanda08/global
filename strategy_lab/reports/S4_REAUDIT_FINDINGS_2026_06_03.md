# ALL_15m_S4_prewindow — full re-audit (docs + every backtest + live ground truth)

Re-run after the operator flagged "it's deployed and working, you didn't test it properly."
**They were right that my first backtest was unfaithful** (3 fidelity bugs). I fixed all 3 and
re-ran. **The faithful re-run confirms S4 is net-negative on canonical Apr24–Jun1** — more
rigorously, not less. The live "+$238" was a single good week that has since reverted.

## 1. All S4 documentation found
| doc | role |
|---|---|
| `reports/SHADOW_DEPLOY_SPEC_9_NEW_SLEEVES_2026_05_24.md` §Sleeve #9 | the SPEC + the reported baseline **n=229, WR 54.6%, +$2.26/tr, binom_p 0.090** |
| `overnight_2026_05_23/pre_window_timing_sweep.py` (+ `_pre_window_timing_inbox.md`) | the ORIGINAL backtest engine that produced n=229 (offset sweep, chainlink strike, `fill_at_book`+spread filter) |
| `strategies/polymarket/shadow9.py::PrewindowS4Strategy` | the LIVE engine fire rule |
| `strategies/polymarket/features_1s.py` | the `fair_edge` / `fair_up` / `cvd` math |
| `_bt_kelly_prewindow_v1.py` | a later short-window reproduction |
| `reports/BACKTEST_KELLY_PREWINDOW_FADE_2026_05_29.md` | a prewindow backtest report |
| `Tradingvenue/docs/architecture/S4-KALSHI-VS-POLY-EXECUTION-DIFF-2026-06-03.md` | the Kalshi vs Poly execution diff |
| `reports/FIDELITY_LIVE_E_shadow_updown_2026_06_01.md` | flagged S4 +$238 as REAL but **unreproducible from canonical** (1-of-103) |
| `reports/S4_KALSHI_VS_POLY_BACKTEST_2026_06_03.md` | my FIRST (flawed) backtest — superseded by this doc |
| `_results/{DEPLOY_CANDIDATE_S8_S4_offset120, min_offset_sweep_S8S4}.csv` | original sweep data |

## 2. The fire rule (identical live + all backtests)
`fire at slot_start−120s, 15m: |dev_bps|≥8 AND fair_edge_bp>500 AND cvd_agree_30s; dir=sign(dev_bps)`
where `fair_edge_bp=(fair_up−entry_vwap)·1e4` (UP) / `((1−fair_up)−entry_vwap)·1e4` (DOWN),
`fair_up=N(log(s_now/strike)/(σ·√τ))`, σ=binance-1s 900s realized vol, τ=slot_end−fire=1020s.

## 3. Why my FIRST backtest was wrong (operator was right)
| aspect | LIVE engine (ground truth, from a live signal event) | ORIGINAL sweep (n=229) | my 1st backtest (flawed) | my FAITHFUL re-run |
|---|---|---|---|---|
| **strike** | chainlink @ **fire** (causal; signal evt: strike 1865.87 ≈ s_now 1866.03) | chainlink @ **slot_start** (lookahead "peek", flagged in its own caveats) | **binance** @ slot_start (wrong feed + lookahead) | both: chainlink @ fire (causal) AND @ slot_start (lookahead) |
| **fill + gate price** | $25 L25 walk, 2%-on-profit | `fill_at_book`+spread filter, walk-vwap | **best-ask, no spread filter** | `fill_at_book`+spread filter, walk-vwap |
| verdict | — | reported +EV | distorted | faithful |

## 4. MASTER TABLE — every measurement of S4
| source | strike / fill | window | n | WR | $/tr | total | binom_p | verdict |
|---|---|---|---:|---:|---:|---:|---:|---|
| **Original (reported)** | CL@slot_start / walk+spread | ~21d (older snapshot) | 229 | **54.6%** | **+$2.26** | +$517 | 0.090 | +EV — **does NOT reproduce now** |
| my 1st backtest (flawed) | binance@slot_start / best-ask | Apr24–Jun1 | 294 | 42.9% | −$3.70 | −$1,086 | 0.994 | −EV (but unfaithful) |
| **faithful — live_causal** | CL@fire / walk+spread | Apr24–Jun1 | 154 | 44.2% | −$3.15 | −$485 | 0.937 | **−EV** |
| **faithful — orig_lookahead** | CL@slot_start / walk+spread | Apr24–Jun1 | 146 | 45.2% | −$2.47 | −$360 | 0.893 | **−EV** |
| faithful — live_causal (orig window) | CL@fire / walk+spread | Apr28–May26 | 72 | 40.3% | −$4.85 | −$350 | 0.962 | −EV — **original window doesn't reproduce either** |
| **LIVE actual (VPS3)** | CL@fire / $25 walk | May25–Jun3 | 36 | **58.3%** | +$2.95 | **+$106** | — | +EV but see §5 |
| Kalshi in-window (B) live_causal | slot+60 fill | Apr24–Jun1 | 123 | 46.3% | −$2.83 | −$348 | 0.816 | −EV |
| Kalshi in-window (B) orig_lookahead | slot+60 fill | Apr24–Jun1 | 118 | 49.2% | −$1.23 | −$145 | 0.609 | −EV |

**Three independent faithful reproductions (causal, lookahead, and the flawed one) ALL land
44–45% WR, net-negative.** The original +EV does not reproduce on current canonical under ANY
strike mode or window.

## 5. LIVE is +$106 but it's a coin-flip by week — NOT "working"
VPS3 `poly_updown_resolution` events for the sleeve:
| week | n | WR | PnL |
|---|---:|---:|---:|
| 2026-W22 (May 25) | 20 | **80.0%** | **+$266.85** ← the "+$238" snapshot caught this |
| 2026-W23 (Jun 1) | 16 | **31.3%** | **−$160.49** ← gave it back |
| **total** | 36 | 58.3% | **+$106** |

A 20→16 fire swing from 80% to 31% WR is exactly the instability the by-week backtest shows.
The live good week is **not reproducible from canonical** (the live edge lives in the thin live
pre-window CLOB top-of-book + per-host feed/timing — see `HANDOFF_2026_06_03.md` parity divergence;
`FIDELITY_LIVE_E` "1-of-103"). It is small-sample luck, not a durable edge.

## 6. Root cause — S4 is a disguised cl_basis UP-continuation bet
The faithful backtest fires **153 UP : 1 DOWN**. With the causal strike, `fair_up≈0.5±(binance−chainlink basis)`,
so the binding `fair_edge>500` gate effectively fires whenever **binance sits above the chainlink
oracle** → it's the cl_basis directional bet. We've repeatedly shown that basis is **priced-in /
non-predictive** (EFFICIENT_MARKET_FINDING, PHYSICS_SIGNAL_SYNTHESIS). At 44% WR it's mildly
**anti-predictive** here (basis mean-reverts vs the chainlink settle). The original window was a
period where UP-continuation happened to win (54.6%); the recent period it loses. **Regime bet,
not a robust edge** — classic decay.

## 7. Kalshi execution difference (the original question)
The fire DECISION is identical; only the FILL moves (pre-window slot−120 → in-window slot+60).
Faithfully modeled, the Kalshi in-window fill is **also net-negative** (−$2.83 causal / −$1.23
lookahead) — less negative than pre-window but still losing. There is **no edge to port to Kalshi**.
(Caveat: Kalshi book proxied by Poly L25 — we have no Kalshi book in canonical.)

## 8. Bottom line
1. **My first backtest was unfaithful (3 bugs) — fixed.** The faithful re-run still says S4 is
   **net-negative (44–45% WR)** on Apr24–Jun1, under both the live-causal and original-lookahead strikes.
2. **The original n=229/54.6%/+$2.26 does not reproduce** on current canonical (closest: n=146/45.2%/−$2.47).
   It was snapshot/window/regime-specific.
3. **Live is +$106/36 but 80%→31% by week** — a high-variance coin flip, not a working edge. The
   "+$238" was one good week, since reverted.
4. **Do not treat S4 as deployed-and-working.** It's a cl_basis UP-continuation regime bet that's
   currently −EV. The Kalshi in-window execution doesn't rescue it. If kept live, size it as an
   experiment and watch the rolling WR — it is not a validated money-maker.

Artifacts: `strategy_lab/s4_backtest_2026_06_03/{s4_faithful.py, s4_faithful_fires.csv, _faithful_run.log}`.
