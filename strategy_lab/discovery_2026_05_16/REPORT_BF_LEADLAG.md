# Strategy B & F — Lead-Lag Discovery Report

**Date:** 2026-05-16
**Data window:** Apr 22 → May 16 2026, chainlink-resolved
**Universe sampled:** 2,500 per (asset, timeframe) — 13,608 markets for B, 9,072 for F
**Conventions:** UTC microseconds; chainlink outcome; `asof_strict` causal asof; `ws_s = slug_suffix - window_s`; fee = 2% on profit only.

---

## Strategy B — Cross-venue lead-lag

### Hypothesis & setup
- `bn_ret = bn_close(fire) / bn_close(fire-120s) - 1`
- `cb_ret` same for coinbase (fallback kraken→okx)
- `lag = bn_ret - cb_ret`

Variants:
- **A (confirmation→continuation):** `|lag|<eps AND bn,cb agree AND |bn|>thr` → in-direction.
- **B (binance alone→mean revert):** `bn>thr AND cb<=0` → DOWN (mirror for shorts).
- **C (slower-venue truth):** sign(cb_ret) past thr.

Primary fire = `(ws_s+120)*1e6` (5m). LATE = `slot_end-60s` (15m).

### 5m primary results (top by hit, n≥200)

| variant | eps_bp | thr_bp | asset | n | hit |
|---|---:|---:|:---:|---:|---:|
| A | 0.5 | 1.0 | ETH | 777 | 0.5341 |
| B | 0.5 | 0.0 | ALL | 564 | 0.5337 |
| A | 0.5 | 0.5 | ETH | 866 | 0.5300 |
| B | 0.5 | 0–1 | SOL | 204 | 0.5294 |
| A | 0.5 | 0.0 | ETH | 932 | 0.5279 |
| A | 0.5 | 0.0 | BTC | 973 | 0.5242 |
| A | 0.5 | 1.0 | ALL | 2,238 | 0.5210 |
| C | 0.5 | 1.0 | BTC | 1,970 | 0.5112 |

### 15m LATE results

| variant | eps_bp | thr_bp | asset | n | hit |
|---|---:|---:|:---:|---:|---:|
| A | 0.5 | 5.0 | ETH | 212 | 0.6509 |
| C | 0.5 | 5.0 | BTC | 452 | 0.6438 |
| A | 1.0 | 5.0 | ETH | 381 | 0.6430 |
| A | 0.5 | 5.0 | ALL | 580 | 0.6379 |
| A | 5.0 | 5.0 | SOL | 664 | 0.6310 |
| A | 5.0 | 5.0 | ALL | 1,601 | 0.6284 |
| C | 0.5 | 5.0 | ALL | 1,781 | 0.6261 |

### Verdict B
- **5m @ ws_s+120: NULL.** Best ALL config 52% hit, ETH-only 53.4%. Edge too thin for entry costs + 2% fee.
- **15m LATE @ slot_end-60s: INCONCLUSIVE.** 63-65% hit is suspect: at slot_end-60 the 15m market has run 14/15 minutes; bn/cb return over [fire-120, fire] is dominated by trivial spot persistence vs settlement 60s away. Needs naive-momentum baseline ablation before claiming alpha.

---

## Strategy F — Cross-asset (BTC leads ETH/SOL)

### Hypothesis & setup
- `btc_ret = binance.BTC over [fire-120s, fire]`
- **basic:** sign(btc_ret) past thr.
- **consensus:** also require self_ret aligned with btc_ret.

### 5m primary results

| variant | thr_bp | asset | n | hit |
|---|---:|:---:|---:|---:|
| basic | 0.0 | SOL | 2,281 | 0.4967 |
| basic | 0.0 | ALL | 4,562 | 0.4928 |
| consensus | 0.0 | ALL | 3,537 | 0.4894 |
| basic | 0.0 | ETH | 2,281 | 0.4888 |
| basic | 5.0 | SOL | 602 | 0.4934 |
| consensus | 5.0 | ALL | 1,159 | 0.4814 |

**All configs hit at or BELOW 50%.**

### 15m LATE results

| variant | thr_bp | asset | n | hit |
|---|---:|:---:|---:|---:|
| consensus | 5.0 | ETH | 391 | 0.6343 |
| consensus | 5.0 | ALL | 768 | 0.6250 |
| basic | 5.0 | ETH | 402 | 0.6244 |
| consensus | 5.0 | SOL | 377 | 0.6154 |
| basic | 5.0 | ALL | 804 | 0.6119 |
| consensus | 2.0 | ALL | 1,868 | 0.6071 |

### Verdict F
- **5m @ ws_s+120: NULL.** Below random across all configs/thresholds. BTC's 2-min pre-window return carries no directional info on the upcoming 5-min ETH/SOL outcome. Hypothesis falsified.
- **15m LATE @ slot_end-60s: INCONCLUSIVE.** Same caveat as Strategy B LATE — 60-63% likely dominated by spot persistence in the last minute.

---

## Combined summary

| strategy | anchor | best ALL hit | n | verdict |
|---|---|---:|---:|:---:|
| B cross-venue | ws_s+120 (5m) | 52.1% | 2,238 | **NULL** |
| B cross-venue | slot_end-60 (15m) | 63.8% | 580 | **INCONCLUSIVE** (autocorr suspect) |
| F BTC→ETH/SOL | ws_s+120 (5m) | 49.3% | 4,562 | **NULL** |
| F BTC→ETH/SOL | slot_end-60 (15m) | 62.5% | 768 | **INCONCLUSIVE** (autocorr suspect) |

### Key finding
Both LATE-15m hits at 60-65% are almost certainly **spot-path persistence**, not cross-venue or cross-asset alpha. The 2-min return ending 60s before settlement of a 14-minute-old market is reading motion in the last 12% of the prediction window. To convert INCONCLUSIVE → ALPHA/NULL: ablate against a naive-momentum baseline (just `bn_ret > 0 → UP` at the same fire) and check whether venue/asset structure adds material edge above it.

### No-lookahead sample (5m)
| slug | fire_us | slot_end_us | fire ≤ slot_end-180s | bn_ret | cb_ret | outcome |
|---|---:|---:|:-:|---:|---:|:-:|
| btc-updown-5m-1777344300 | 1,777,344,120,000,000 | 1,777,344,600,000,000 | True | 0.000000 | +0.000208 | Down |
| btc-updown-5m-1777771200 | 1,777,771,020,000,000 | 1,777,771,500,000,000 | True | -0.000143 | -0.000186 | Down |
| btc-updown-5m-1778879100 | 1,778,878,920,000,000 | 1,778,879,400,000,000 | True | +0.000180 | +0.000308 | Up |

Fire 8 min before settlement. All asof reads end at-or-before fire_us. Clean.
