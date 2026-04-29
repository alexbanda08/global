# V52 Parity Test Specification

**Purpose:** prove the engineer's V52 implementation reproduces the reference values exactly, given the same input data. This is a **regression test**, not a performance test — these numbers are NOT the deployment targets.

**Pass criterion:** all 8 tests pass within documented tolerances.

---

## How to use this bundle

1. Load `input_klines.parquet` → 4 symbols (ETH, AVAX, SOL, LINK), 2000 bars each, columns `[open, high, low, close, volume]`, multi-index `[symbol, timestamp]`.
2. Load `input_funding.parquet` → DataFrame with 2000 rows, columns `[ETH, AVAX, SOL, LINK]` containing per-4h-bar summed hourly funding rates (use directly with funding-aware simulator).
3. Run engineer's implementation through each stage of the V52 pipeline.
4. Compare each stage's output against the corresponding `expected_*.json`.
5. Each test produces PASS/FAIL. **All 8 must PASS.**

---

## Test sequence

### Test 1 — ATR(14) Wilder smoothing  → `expected_indicators.json`

**Input:** ETH OHLC slice from `input_klines.parquet`
**Implementation:** `atr(df, n=14)` returning numpy array of length N
**Expected:** 50 sample-point values
**Tolerance:** `rtol=1e-9` (pure math, no rounding)

**Pass:** for each `(idx, value)` pair in `expected_indicators.atr.ETH.sample_indices/sample_values`:
```python
assert math.isclose(impl_atr[idx], expected_value, rel_tol=1e-9)
```

If this fails, the indicator math is wrong — **no other test will pass**. Stop and fix this first.

### Test 2 — Price-based signal functions  → `expected_signals.json`

For each of `cci_extreme`, `supertrend_flip`, `lateral_bb_fade`:

**Input:** ETH OHLCV + the params in `expected_signals.<sig>.params`
**Expected output:** `(long_entries, short_entries)` boolean Series of length 2000

**Pass criterion:** convert engineer's output to the index-list format used in fixtures and compare:
```python
impl_long_idx  = [i for i, v in enumerate(impl_long.values)  if bool(v)]
impl_short_idx = [i for i, v in enumerate(impl_short.values) if bool(v)]
assert impl_long_idx == expected.long_entry_indices
assert impl_short_idx == expected.short_entry_indices
```

Exact match required (booleans, no tolerance).

### Test 3 — New signal functions (V50)  → `expected_signals.json`

Same contract as Test 2, for `mfi_75_25`, `vp_rot_60`, `svd_tight`. Exact-match required on entry indices.

### Test 4 — Regime classifier  → `expected_regime.json`

**Input:** ETH OHLCV (full 2000 bars)
**Implementation:** fit GaussianMixture per the spec §3 with seed=42

**Expected:** dict containing
- `best_k` (integer) — must match exactly
- `bic_table` — values within `rtol=1e-3` per K (sklearn output is reproducible to that precision with fixed seed)
- `regime_labels_by_id` — dict mapping sorted regime id (0..K*-1) to label string ("LowVol", etc.)
- `regime_distribution` — Counter of labels across all bars; counts must match exactly
- `first_50_regime_labels` — array of label strings for bars 0..49; exact match required

**Pass:** all five sub-assertions hold.

If `best_k` matches but distribution doesn't → check the regime relabel-by-vol logic (§3.3). If first labels match but later ones don't → check the persistence/flicker filter (§3.5).

### Test 5 — Canonical simulator  → `expected_trades.json` + `expected_equity.json`

**Input:** ETH OHLCV + signals from `sig_cci_extreme(df)` (use the engineer's now-validated implementation, OR the entry-index lists from `expected_signals.json` if Test 2 passed)
**Implementation:** canonical simulator with `EXIT_4H = (tp=10, sl=2, trail=6, max_hold=60)`

**Expected output:** `(trades_list, equity_series)`

**Trade-list pass criterion:** `expected_trades.canonical_cci_eth.trades` is a list of trade dicts. For each pair (impl[i], expected[i]):
- `entry_idx`, `exit_idx`, `side`, `bars`, `reason` → exact match
- `entry`, `exit`, `realized` → `rtol=1e-6`
- `ret` → `rtol=1e-6`
- Number of trades → exact match

**Equity pass criterion:** at each `expected_equity.canonical_cci_eth.sample_indices[i]`:
```python
assert math.isclose(impl_equity[idx], expected.sample_values[i], rel_tol=1e-5)
```

### Test 6 — V41 regime-adaptive simulator  → `expected_trades.json`

**Input:** same ETH + sig_cci_extreme entries, but exits adapt per regime label
**Implementation:** `simulate_adaptive_exit()` per spec §5.2 with `REGIME_EXITS_4H` table

**Expected:** `expected_trades.v41_regime_adaptive_cci_eth.trades` — each trade includes a `regime` field (the label at entry bar) plus the same fields as Test 5.

**Pass:** trade list matches with `rtol=1e-6` on prices, exact match on indices/side/regime.

### Test 7 — Funding-aware simulator  → `expected_trades.json`

**Input:** same ETH + sig_cci_extreme + funding column from `input_funding.parquet[ETH]`
**Implementation:** `simulate_with_funding()` per spec §9.2 — accrues `funding_pnl = -direction * notional * funding_per_bar` each bar a position is open

**Expected:** `expected_trades.with_funding_cci_eth.trades` — includes `funding_cost` field per trade

**Pass:** trade indices/sides exact, prices `rtol=1e-6`, `funding_cost` and `realized` `rtol=1e-5`.

If this fails but Test 5 passes → funding accrual logic is wrong. The bug is almost always in either (a) sign convention (long pays when rate>0) or (b) summing hourly rates into the per-bar value.

### Test 8 — End-to-end V52 blend  → `expected_v52_blend.json`

**The big one.** Takes raw `input_klines.parquet` + `input_funding.parquet`, runs the FULL V52 pipeline (all 4 V41 sleeves + 4 diversifiers, inv-vol blending, 60/10/10/10/10 weights), produces final equity series.

**Expected outputs:**
- `headline.sharpe`, `cagr`, `mdd`, `calmar`, `final_equity` — `rtol=5e-3`
- `sample_equity` at `sample_indices` — `rtol=1e-4` per point

**Pass:** all six headline metrics within tolerance AND all 100 equity samples within tolerance.

This test inherently tests:
- All 6 signal functions
- Both simulators (canonical + V41 regime-adaptive)
- Inverse-volatility weighting (500-bar rolling)
- Equal-weight blending
- Multi-symbol regime classifier fits
- Funding accrual on every sleeve
- Daily rebalance arithmetic
- Top-level 60/10/10/10/10 weighting

If Tests 1-7 pass and Test 8 fails, the bug is in blending arithmetic (most likely culprit: inverse-vol weight formula or daily-rebalance reindexing).

---

## Tolerance philosophy

| Layer | Tolerance | Reason |
|---|---|---|
| Indicators (ATR, EMA, etc.) | `rtol=1e-9` | Pure float math; differences mean wrong formula |
| Signal booleans | exact | No reason to disagree |
| GMM fit | exact (with seed=42) | sklearn is deterministic |
| Trade indices, side, reason | exact | Engine semantics |
| Trade prices (entry/exit) | `rtol=1e-6` | Slippage formula tolerance |
| Per-trade returns | `rtol=1e-6` | Compounds from prices |
| Equity at sample points | `rtol=1e-5` | Compounding rounding |
| V52 final equity / Sharpe | `rtol=5e-3` (~0.5%) | End-to-end accumulation |

The tolerances are deliberately tight — looser tolerances hide bugs.

## Reference numbers from this fixture

The fixtures are derived from the LAST 2000 4h bars of HL data (≈333 days). These are NOT the deployment targets in the spec — they're parity values for a small fixed window. From this fixture:

- V52 final equity (init=10,000): **11,386.09**
- V52 windowed Sharpe: 1.347
- V52 windowed CAGR: +15.29%

The deployment targets in the spec (Sharpe 2.52, CAGR +31%) come from the full 2.3-year HL window. Different window → different numbers. **Match THESE fixture numbers, not the spec targets, for the parity test.**

---

## Failure debugging guide

| Test fails first time at | Likely cause |
|---|---|
| Test 1 (ATR) | Wilder smoothing wrong (you used SMA?). Fix `atr()` |
| Test 2 (CCI) | `cci` calc uses std() instead of MAD. Fix CCI formula |
| Test 2 (SuperTrend) | Recursive `trend[i]` logic — most common bug is the equality case (close == st[i-1]) |
| Test 2 (BB Fade) | ADX formula — Wilder vs simple moving average for the smooth |
| Test 3 (MFI) | `tp_change` direction — must use prior typical-price comparison, not signed-volume |
| Test 3 (VP_ROT) | Value-area expansion — the "expand from POC outward, prefer higher-volume side" logic |
| Test 3 (SVD) | Rolling baseline window — must be `cvd_win * 2` for median/std baseline |
| Test 4 (regime) | Regime relabel-by-vol step (§3.3); or persistence filter (§3.5); or seed not set |
| Test 5 (canonical) | Most common: same-bar entry instead of next-bar-open. Check §2.2 |
| Test 5 (canonical) | Or: trail stop loosens (it must ratchet only — §2.4) |
| Test 6 (V41) | `regime_labels[entry_bar]` lookup — must use the bar where signal fires, not the next bar |
| Test 7 (funding) | Sign error — long pays funding when rate > 0; `pnl = -direction * notional * rate` |
| Test 8 (end-to-end) | Inv-vol weight normalization — must sum to 1.0 daily; fall back to equal-weight if any vol == 0 |

---

## Run command (engineer's environment)

```bash
# In the engineer's stack, after implementing all V52 components:
python tests/run_v52_parity.py --fixture-dir tests/v52_fixtures/

# Expected output:
# Test 1 ATR ............... PASS
# Test 2 CCI ............... PASS
# Test 2 SuperTrend ........ PASS
# Test 2 BB Fade ........... PASS
# Test 3 MFI ............... PASS
# Test 3 VP_ROT ............ PASS
# Test 3 SVD ............... PASS
# Test 4 Regime ............ PASS
# Test 5 Canonical sim ..... PASS
# Test 6 V41 sim ........... PASS
# Test 7 Funding sim ....... PASS
# Test 8 V52 blend ......... PASS
# 12/12 PASS — implementation matches reference within tolerance
```

If any test fails, the runner prints the first mismatch with index, expected, actual, delta, tolerance — enough to localize the bug to one function.

A reference test runner template is at `tests/v52_fixtures/run_v52_parity.py.template` — adapt to the engineer's import paths.
