# P2 Exit-Timing Model — learned online exit policy — 2026-06-03

Model=XGBoost. Online HOLD-vs-SELL at checkpoints [30, 45, 60, 75, 90, 120]s. Features (causal at ckpt): ['cur', 'profit', 'mom', 'elapsed', 'entry_vwap', 'delta_bps', 'a_BTC', 'tf_15m', 'ps', 'pd_', 'pds', 'pmar']. Label=bid improves after ckpt (+0.005). Sell when P(hold)<thr. Trained on all filled BTC+ETH fires; lockbox=last 25% of fires by time. fee=0.015.

### LOCKBOX (all) (n_fire=629)

| policy | n | $/tr | t | CI |
|---|--:|--:|--:|--:|
| fixed TIME+45 | 629 | +0.273 | 1.00 | [-0.27,+0.81] |
| fixed TIME+60 | 629 | +0.251 | 0.83 | [-0.35,+0.83] |
| MODEL policy (thr=0.6) | 629 | +1.177 | 2.29 | [+0.14,+2.21] |

model − fixed45 = +0.904/tr.  exit-time dist: 30s:36, 45s:23, 60s:52, 75s:86, 90s:84, 120s:95, hold:253

### LOCKBOX deployed cell (δ≥5,vwap<0.55) (n_fire=17)

| policy | n | $/tr | t | CI |
|---|--:|--:|--:|--:|
| fixed TIME+45 | 17 | +5.650 | 3.49 | [+2.61,+8.74] |
| fixed TIME+60 | 17 | +3.469 | 2.27 | [+0.49,+6.38] |
| MODEL policy (thr=0.6) | 17 | +5.455 | 2.11 | [+0.85,+10.49] |

model − fixed45 = -0.195/tr.  exit-time dist: 30s:7, 45s:1, 60s:3, 75s:0, 90s:1, 120s:2, hold:3

### FULL deployed cell (in+out) (n_fire=118)

| policy | n | $/tr | t | CI |
|---|--:|--:|--:|--:|
| fixed TIME+45 | 118 | +5.564 | 6.90 | [+3.98,+7.12] |
| fixed TIME+60 | 118 | +5.560 | 6.51 | [+3.93,+7.22] |
| MODEL policy (thr=0.6) | 118 | +6.371 | 4.97 | [+3.78,+8.86] |

model − fixed45 = +0.808/tr.  exit-time dist: 30s:35, 45s:11, 60s:11, 75s:9, 90s:9, 120s:9, hold:34

## Top features
elapsed=0.166, cur=0.128, tf_15m=0.106, profit=0.091, entry_vwap=0.075, pmar=0.071, delta_bps=0.069, pd_=0.065

## Read
- Oracle best-exit ceiling was +$18.5/tr (vs fixed +45 ≈ +$5.6). This model tries to close that gap.
- If MODEL ≈ fixed45 → the early path carries no exploitable timing signal beyond 'exit fast'; keep fixed +45.
- If MODEL > fixed45 with lockbox CI>0 → deploy as a dynamic exit policy (shadow first).
## VERDICT — the exit-timing model adds REAL edge (lockbox-confirmed on the broad universe)

| set | fixed+45 $/tr | MODEL $/tr | Δ | model lockbox CI | call |
|---|--:|--:|--:|--:|---|
| **LOCKBOX all BTC+ETH (n=629)** | +0.27 (t=1.0, CI incl 0) | **+1.18 (t=2.29)** | **+0.90** | **[+0.14,+2.21] excl 0** | ✅ real lift |
| LOCKBOX deployed cell (n=17) | +5.65 | +5.46 | −0.19 | [+0.85,+10.5] | underpowered (n=17) |
| FULL deployed cell (n=118) | +5.56 | +6.37 (t=4.97) | +0.81 | [+3.78,+8.86] | encouraging (incl in-sample) |

**The model genuinely beats a fixed exit on the broad lockbox: +$0.90/tr, t=2.29, CI excludes 0.** It is NOT
just "exit fast" — it HOLDS ~40% of fires to resolution and spreads exits across 30–120s, learning a real
hold-vs-sell distinction. Top features = `elapsed, cur(bid), tf, profit, entry_vwap, phys_margin, delta` —
i.e. the current reprice level + time + how-far-in-the-money, exactly the path-shape signal hypothesized.

**Caveats / honesty:**
- The lift is clearest on the broad (lower-edge) universe. On the already-strong **deployed cell the lockbox
  is too thin (n=17)** to confirm the lift (tied there); the full-cell +$0.81 includes in-sample.
- It does NOT close the +$18.5 oracle ceiling (that needs perfect foresight) — it captures a fraction.

**Recommendation:** deploy the model as a **dynamic-exit SHADOW arm** alongside the fixed-+45 scalp
(`exit_policy = ML_EXIT`, sell when P(hold)<0.60 at 15-30s polling), and compare forward. It is a clear
incremental improvement on the broad universe; needs more deployed-cell fires to confirm the lift there.
Next refinement: retrain with the cross-feature MICROSTRUCTURE features (mp_skew/imb5/hawkes — not in this
cache) which had AUC 0.78 on price movement and should sharpen the path prediction.
