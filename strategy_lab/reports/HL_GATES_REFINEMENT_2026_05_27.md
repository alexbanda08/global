# HL Liquidation Gates Refinement — 2026-05-27

**Compute script:** `strategy_lab/hl_gates_refinement_compute.py`  
**Full sweep CSV:** `strategy_lab/reports/hl_gates_refinement_full_sweep.csv`  
**Passing configs CSV:** `strategy_lab/reports/hl_gates_refinement_passing.csv`

---

## 1. Original Finding + Caveat

From `strategy_lab/reports/NEW_GATES_RESEARCH_2026_05_27.md`:

| Gate | Window | Threshold | n | WR_true | Lift |
|------|--------|-----------|---|---------|------|
| A2 HL Short Cascade + UP | 300s | $200k | 25 | 92.0% | +11.88pp |
| A2 HL Short Cascade + UP | 60s | $200k | 10 | 100.0% | +19.88pp |

**Caveat:** These n values are too small for statistical confidence. The LONG cascade gate (A1, predicts DOWN) was completely dead at $200k+ thresholds because `Close Long` WS events have median $419/event — impossible to accumulate $200k in a 60-300s window. The SHORT cascade uses S3 fills with median $1,197/event but still needs lower thresholds to hit n≥50.

---

## 2. Threshold Sweep Results

**Fire universe:** 5,000 fires sampled from 18,270 (seed=42), WR_baseline=80.12%.  
**Asset split:** BTC 42%, SOL 37%, ETH 21%.

### SHORT Cascade (predicts UP) — All Assets

| Window | Threshold | n_gate | WR_true | WR_base | Lift |
|--------|-----------|--------|---------|---------|------|
| 600s | $10k | 131 | 84.7% | 80.1% | +4.6pp |
| 600s | $20k | 95 | 83.2% | 80.1% | +3.1pp |
| 300s | $10k | 60 | 83.3% | 80.1% | +3.2pp |
| 300s | $20k | 44 | 84.1% | 80.1% | +4.0pp |
| 300s | $50k | 28 | 85.7% | 80.1% | +5.6pp |
| 180s | $10k | 33 | 84.8% | 80.1% | +4.7pp |
| 60s | $10k | 16 | 87.5% | 80.1% | +7.4pp |

### LONG Cascade (predicts DOWN) — All Assets

All LONG configs fail n≥50. Maximum n_gate for any threshold/window combo is 8 (600s/$10k).  
**Root cause:** `Close Long` WS events are $419 median — 1-year full dataset only has 56,308 LONG proxy rows total (vs 1,063,502 SHORT proxy rows). LONG cascade is structurally undersized for this approach.

### SHORT Cascade — BTC Only (best performing asset-split)

| Window | Threshold | n_gate | WR_true | WR_base | Lift |
|--------|-----------|--------|---------|---------|------|
| 600s | $10k | **54** | **90.7%** | 85.1% | **+5.67pp** ✓ |
| 600s | $20k | **53** | **90.6%** | 85.1% | **+5.49pp** ✓ |
| 300s | $10k | 28 | 89.3% | 85.1% | +4.2pp |
| 300s | $20k | 24 | 91.7% | 85.1% | +6.6pp |
| 180s | $10k | 18 | 88.9% | 85.1% | +3.8pp |

### SOL Asset-Split (notable but tiny n)

All SOL configs have 100% WR (1.0000) but n≤11. SOL HL liq events in the fire window are extremely rare → any that fire happen to all win. Not reliable signal.

### ETH Asset-Split

ETH configs are similarly sparse (n≤7). No reliable signal.

---

## 3. Passing Configs (n ≥ 50, lift ≥ +5pp)

Only 2 configurations pass both bars:

| Rank | Gate | Asset | Window | Threshold | n | WR_true | WR_base | Lift |
|------|------|-------|--------|-----------|---|---------|---------|------|
| 1 | SHORT cascade + UP | BTC | 600s | $10k | 54 | 90.74% | 85.07% | **+5.67pp** |
| 2 | SHORT cascade + UP | BTC | 600s | $20k | 53 | 90.57% | 85.07% | **+5.49pp** |

---

## 4. Asset-Split Results Summary

| Asset | SHORT proxy rows | LONG proxy rows | Best passing config |
|-------|-----------------|-----------------|---------------------|
| BTC | ~442k | ~21k | SHORT 600s/$10k → +5.67pp (n=54) |
| ETH | ~490k | ~20k | None (n too small) |
| SOL | ~131k | ~15k | None (n too small for 5k sample) |

**Key insight:** BTC HL SHORT liq volume is concentrated enough that 600s windows accumulate $10-20k regularly (1.1% trigger rate). ETH S3 fills have similar total rows but fire in the ETH arm less frequently relative to SOL's smaller fire count.

---

## 5. Top 3 Refined Gate Configs to Productionize

### #1 — BTC SHORT Cascade 600s/$10k (RECOMMENDED)
- **Config:** Sum of `Close Short` market S3 fills in prior 600s > $10,000 USD, BTC asset only, direction UP
- **Stats:** n=54, WR=90.74%, base=85.07%, lift=**+5.67pp**
- **Coverage:** 54/2,100 BTC UP fires ≈ 2.6% trigger rate
- **Verdict:** Weakly significant. Passes n≥50 bar but only just. Use as additive confidence booster, not hard gate.

### #2 — BTC SHORT Cascade 600s/$20k (SIMILAR)
- **Config:** Same as #1 but $20k threshold
- **Stats:** n=53, WR=90.57%, base=85.07%, lift=**+5.49pp**
- **Coverage:** Virtually identical to #1 (only 1 fire drops out)
- **Verdict:** $10k and $20k thresholds are functionally equivalent — most events cluster above $20k when any fire at all.

### #3 — SHORT Cascade ALL assets 600s/$10k (fallback)
- **Config:** Sum of SHORT liq USD in prior 600s > $10,000, any asset, direction UP
- **Stats:** n=131, WR=84.7%, base=80.1%, lift=**+4.6pp**
- **Coverage:** 131/5,000 = 2.6% trigger rate
- **Note:** Does NOT pass the +5pp bar but is the only all-asset config above 4pp. Covers more fires.

---

## 6. Recommendation

**The LONG cascade gate is structurally dead.** With only 56k rows in the entire year (vs 1M+ SHORT proxy rows) and a median of $419/event, no feasible threshold or window produces n≥50 in the 5k fire sample. Do not include A1 (LONG/DOWN) in V9.

**The SHORT cascade signal is real but narrow:** Only BTC with a 600s window passes the statistical bar, and only marginally (n=54). Options:

1. **Productionize at BTC-600s/$10k as a soft booster:** Treat as +1 confidence point in a multi-signal scoring framework, not a hard binary gate. Expected impact: +5.67pp on 2.6% of BTC UP fires.

2. **Wait for more data:** With 5× the fires (full production volume), the same signal likely survives at shorter windows (300s/$20k shows +6.6pp at n=24 — promising). Re-test after 90-day fire window becomes available.

3. **Investigate SOL separately:** SOL shows 100% WR on the handful of qualifying fires, but the fire count in the 5k sample is too small to confirm. A dedicated SOL HL liq pull with the full 18k fire universe (no 5k subsample) may uncover a real effect.

**Bottom line:** Current data supports BTC SHORT cascade 600s/$10k as a marginal (+5.67pp, n=54) additive signal. Not strong enough to gate V9 alone. Combine with Polymarket flow gate B3 for a confluence approach.

---

## Appendix: Data Notes

- `hyperliquid_liquidations_full.parquet`: 5,275,626 rows (full year)
- LONG proxy (WS): 56,308 rows total, median $419/event — data-starved
- SHORT proxy (S3 market): 1,063,502 rows total, median $1,197/event — usable
- Fire universe: 5,000 sample, WR baseline 80.12% (curated sleeve universe, not all fires)
- Compute time: 5.8s total (vectorized searchsorted per fire)
- Sparsity ceiling: at $10k/600s, SHORT BTC gate fires on only 2.6% of BTC-UP fires
