"""
Run Gates 7 (permutation) and 8 (plateau) on the three leveraged winners:
  * NEW 60/40 blend  (P3_invvol 60% + P5_btc_defensive 40%)
  * P3_invvol
  * P5_btc_defensive

Gate 7 — permutation (30 shuffles per candidate):
  For each shuffle, independently shuffle log-returns of every underlying
  symbol, rebuild OHLC, re-run every sleeve, rebuild the blend, compute
  blend Sharpe. Compare observed Sharpe to null distribution.

Gate 8 — plateau (per-sleeve parameter sweep):
  For each sleeve, sweep its 2-3 key params +/-25% and +/-50% from canonical.
  For each sweep, re-run that sleeve only, rebuild blend, measure Sharpe.
  Report max Sharpe drop across all sweeps.

Outputs:
  docs/research/phase5_results/leverage_gates78_results.json
"""
from __future__ import annotations
import json, sys, time
from pathlib import Path
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from strategy_lab.run_leverage_study import SLEEVE_SPECS, PORTFOLIOS, OUT, BPY, _import_sig
from strategy_lab.run_leverage_study_v2 import simulate_lev
from strategy_lab.run_leverage_audit import eqw_blend, invvol_blend
from strategy_lab.engine import load as load_data
from strategy_lab.eval.perps_simulator import atr

# =============================================================================
# Config for the NEW 60/40 and its components
# =============================================================================
CANDIDATES = {
    "NEW_60_40":         {"p3_invvol": 0.60, "p5_btc_def": 0.40},
    "P3_invvol":         {"p3_invvol": 1.00},
    "P5_btc_defensive":  {"p5_btc_def": 1.00},
}

# Sleeves used (unique union)
UNIQUE_SLEEVES_P3 = PORTFOLIOS["P3"]   # CCI_ETH, STF_AVAX, STF_SOL
UNIQUE_SLEEVES_P5 = PORTFOLIOS["P5"]   # CCI_ETH, LATBB_AVAX, STF_SOL
ALL_SLEEVES = sorted(set(UNIQUE_SLEEVES_P3) | set(UNIQUE_SLEEVES_P5))

# unique underlying symbols to shuffle
SYMBOLS = sorted({spec[2] for _, spec in SLEEVE_SPECS.items() if _ in ALL_SLEEVES})

# =============================================================================
# Data caching
# =============================================================================
_DATA: dict[str, pd.DataFrame] = {}
def get_symbol_df(symbol: str) -> pd.DataFrame:
    if symbol in _DATA:
        return _DATA[symbol]
    df = load_data(symbol, "4h", start="2021-01-01", end="2026-03-31")
    _DATA[symbol] = df
    return df

_BTC_GATE: pd.Series | None = None
def get_btc_gate() -> pd.Series:
    global _BTC_GATE
    if _BTC_GATE is not None:
        return _BTC_GATE
    btc = get_symbol_df("BTCUSDT")
    close = btc["close"]
    ema200 = close.ewm(span=200, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    trend_any = ((close > ema200) & (ema50 > ema200)) | ((close < ema200) & (ema50 < ema200))
    a = pd.Series(atr(btc), index=btc.index)
    vol_rank = (a / close).rolling(500, min_periods=100).rank(pct=True)
    vol_low = vol_rank < 0.5
    gmult = pd.Series(1.0, index=btc.index)
    gmult[trend_any & vol_low] = 1.25
    gmult[trend_any & ~vol_low] = 0.75
    gmult[~trend_any & vol_low] = 1.0
    gmult[~trend_any & ~vol_low] = 0.4
    _BTC_GATE = gmult
    return gmult

def sleeve_signal_fn(sleeve: str):
    script, fn, _, _ = SLEEVE_SPECS[sleeve]
    return _import_sig(script, fn)

# =============================================================================
# Build leveraged equity curves given per-symbol dfs
# =============================================================================
def build_sleeve_curve(sleeve: str, df: pd.DataFrame, btc_gate: pd.Series | None,
                       use_btc_gate: bool, sig_kwargs: dict | None = None):
    """Run this sleeve on the provided df; return equity."""
    sig = sleeve_signal_fn(sleeve)
    sig_kwargs = sig_kwargs or {}
    out = sig(df, **sig_kwargs)
    le, se = out if isinstance(out, tuple) else (out, None)
    cap = 3.0
    if use_btc_gate and btc_gate is not None:
        mult = btc_gate.reindex(df.index).ffill().fillna(1.0)
        cap = 5.0
        _, eq = simulate_lev(df, le, se, size_mult=mult,
                             risk_per_trade=0.03, leverage_cap=cap)
    else:
        _, eq = simulate_lev(df, le, se, risk_per_trade=0.03, leverage_cap=cap)
    return eq

def build_blend(dfs_by_symbol: dict[str, pd.DataFrame],
                sig_overrides: dict[str, dict] | None = None) -> dict[str, pd.Series]:
    """
    Build both P3_invvol and P5_btc_defensive equity curves from the provided
    per-symbol dfs (may be shuffled). Returns dict with "p3_invvol" and
    "p5_btc_def" equity Series.
    """
    sig_overrides = sig_overrides or {}
    btc_gate = get_btc_gate()  # BTC gate is ALWAYS from real data — it's a market state

    # P3 sleeves (no BTC gate, EQW invvol blend)
    p3_curves = {}
    for s in UNIQUE_SLEEVES_P3:
        symbol = SLEEVE_SPECS[s][2]
        df = dfs_by_symbol[symbol]
        kw = sig_overrides.get(s, {})
        p3_curves[s] = build_sleeve_curve(s, df, btc_gate=None,
                                           use_btc_gate=False, sig_kwargs=kw)
    p3_eq = invvol_blend(p3_curves, window=500)

    # P5 sleeves (BTC gate applied)
    p5_curves = {}
    for s in UNIQUE_SLEEVES_P5:
        symbol = SLEEVE_SPECS[s][2]
        df = dfs_by_symbol[symbol]
        kw = sig_overrides.get(s, {})
        p5_curves[s] = build_sleeve_curve(s, df, btc_gate=btc_gate,
                                           use_btc_gate=True, sig_kwargs=kw)
    p5_eq = eqw_blend(p5_curves)
    return {"p3_invvol": p3_eq, "p5_btc_def": p5_eq}

def combine_weighted(parts: dict[str, pd.Series], weights: dict[str, float]) -> pd.Series:
    idx = None
    for k, eq in parts.items():
        if k in weights:
            idx = eq.index if idx is None else idx.intersection(eq.index)
    combined_r = None
    for k, w in weights.items():
        r = parts[k].reindex(idx).pct_change().fillna(0)
        combined_r = r * w if combined_r is None else combined_r + r * w
    return (1 + combined_r).cumprod() * 10_000.0

def blend_sharpe(eq: pd.Series) -> float:
    if len(eq) < 30:
        return 0.0
    rets = eq.pct_change().dropna()
    sd = float(rets.std())
    if sd == 0:
        return 0.0
    return (float(rets.mean()) / sd) * np.sqrt(BPY)

# =============================================================================
# Gate 7: Permutation test (portfolio-level)
# =============================================================================
def shuffle_df_lr(df: pd.DataFrame, rng) -> pd.DataFrame:
    """Shuffle log-returns; rebuild OHLC preserving bar structure."""
    close = df["close"].to_numpy()
    log_r = np.diff(np.log(close))
    perm = rng.permutation(log_r)
    new_close = np.exp(np.concatenate([[np.log(close[0])],
                                        np.cumsum(perm) + np.log(close[0])]))
    scale = new_close / close
    df2 = df.copy()
    df2["close"] = new_close
    df2["open"] = df["open"].to_numpy() * scale
    df2["high"] = df["high"].to_numpy() * scale
    df2["low"] = df["low"].to_numpy() * scale
    return df2

def run_gate7_permutation(n_perm: int = 30) -> dict:
    print(f"\n=== Gate 7: Permutation (n={n_perm}) ===")
    # real equity
    real_dfs = {sym: get_symbol_df(sym) for sym in SYMBOLS}
    real_parts = build_blend(real_dfs)
    real_shs = {name: blend_sharpe(combine_weighted(real_parts, w))
                for name, w in CANDIDATES.items()}
    print(f"  Real Sharpes: {real_shs}")

    rng = np.random.default_rng(42)
    null_map: dict[str, list[float]] = {name: [] for name in CANDIDATES}

    for k in range(n_perm):
        # shuffle each symbol independently
        shuffled_dfs = {sym: shuffle_df_lr(get_symbol_df(sym), rng) for sym in SYMBOLS}
        try:
            parts = build_blend(shuffled_dfs)
            for name, w in CANDIDATES.items():
                eq = combine_weighted(parts, w)
                null_map[name].append(blend_sharpe(eq))
        except Exception as e:
            print(f"  perm {k}: error {type(e).__name__}")
            continue
        if (k + 1) % 5 == 0:
            print(f"  permutation {k+1}/{n_perm} done")

    results = {}
    for name in CANDIDATES:
        arr = np.asarray(null_map[name], dtype=float)
        if len(arr) < 5:
            results[name] = {"error": "too_few_permutations", "n": len(arr)}
            continue
        real = real_shs[name]
        p = float((arr >= real).mean())
        results[name] = {
            "n_permutations":  int(len(arr)),
            "real_sharpe":     round(real, 3),
            "null_mean":       round(float(arr.mean()), 3),
            "null_99th":       round(float(np.quantile(arr, 0.99)), 3),
            "p_value":         round(p, 4),
            "pass_p_lt_0_01":  p < 0.01,
        }
    return results

# =============================================================================
# Gate 8: Plateau test (per-sleeve param sweeps)
# =============================================================================
# Canonical params + sweep axes per sleeve family
SWEEPS = {
    "CCI_ETH_4h": [
        {"cci_n": 15}, {"cci_n": 25}, {"cci_n": 10}, {"cci_n": 30},
        {"adx_max": 17}, {"adx_max": 27}, {"adx_max": 11}, {"adx_max": 33},
        {"cci_lo": -113, "cci_hi": 113},
        {"cci_lo": -188, "cci_hi": 188},
    ],
    "STF_SOL_4h": [
        {"st_n": 8}, {"st_n": 12}, {"st_n": 5}, {"st_n": 15},
        {"st_mult": 2.25}, {"st_mult": 3.75}, {"st_mult": 1.5}, {"st_mult": 4.5},
        {"ema_reg": 150}, {"ema_reg": 250},
    ],
    "STF_AVAX_4h": [
        {"st_n": 8}, {"st_n": 12}, {"st_n": 5}, {"st_n": 15},
        {"st_mult": 2.25}, {"st_mult": 3.75}, {"st_mult": 1.5}, {"st_mult": 4.5},
        {"ema_reg": 150}, {"ema_reg": 250},
    ],
    "LATBB_AVAX_4h": [
        {"bb_n": 15}, {"bb_n": 25}, {"bb_n": 10}, {"bb_n": 30},
        {"bb_k": 1.5}, {"bb_k": 2.5},
        {"adx_max": 13}, {"adx_max": 23},
    ],
}

def run_gate8_plateau() -> dict:
    print(f"\n=== Gate 8: Plateau (per-sleeve parameter sweeps) ===")
    real_dfs = {sym: get_symbol_df(sym) for sym in SYMBOLS}
    real_parts = build_blend(real_dfs)
    real_shs = {name: blend_sharpe(combine_weighted(real_parts, w))
                for name, w in CANDIDATES.items()}
    print(f"  Real Sharpes: {real_shs}")

    results = {}
    for name, w in CANDIDATES.items():
        results[name] = {"real_sharpe": round(real_shs[name], 3),
                         "sweeps": [], "max_drop_pct": 0.0}

    # Which sleeves are relevant per candidate
    sleeves_for = {
        "NEW_60_40":        set(UNIQUE_SLEEVES_P3) | set(UNIQUE_SLEEVES_P5),
        "P3_invvol":        set(UNIQUE_SLEEVES_P3),
        "P5_btc_defensive": set(UNIQUE_SLEEVES_P5),
    }

    for sleeve, sweeps in SWEEPS.items():
        print(f"\n  Sweeping {sleeve} ({len(sweeps)} configs)...")
        for k, kw in enumerate(sweeps):
            sig_overrides = {sleeve: kw}
            parts = build_blend(real_dfs, sig_overrides=sig_overrides)
            for name, w in CANDIDATES.items():
                if sleeve not in sleeves_for[name]:
                    continue
                eq = combine_weighted(parts, w)
                sh = blend_sharpe(eq)
                real = real_shs[name]
                drop = (real - sh) / abs(real) * 100 if real > 0 else 0
                results[name]["sweeps"].append({
                    "sleeve": sleeve, "override": kw,
                    "sharpe": round(sh, 3),
                    "drop_pct": round(drop, 1),
                })
                if drop > results[name]["max_drop_pct"]:
                    results[name]["max_drop_pct"] = drop

    # pass/fail
    for name in CANDIDATES:
        results[name]["pass_drop_le_30pct"] = results[name]["max_drop_pct"] <= 30.0
        results[name]["max_drop_pct"] = round(results[name]["max_drop_pct"], 1)
        print(f"  {name} max drop: {results[name]['max_drop_pct']}%")

    return results

# =============================================================================
# MAIN
# =============================================================================
def main():
    t0 = time.time()
    print(f"Warming caches for symbols: {SYMBOLS}")
    for sym in SYMBOLS:
        get_symbol_df(sym)
    get_symbol_df("BTCUSDT")  # needed for BTC gate

    print("\nRunning Gate 7 (permutation, n=30)...")
    g7 = run_gate7_permutation(n_perm=30)

    print("\nRunning Gate 8 (plateau)...")
    g8 = run_gate8_plateau()

    # Save
    out = {"gate7_permutation": g7, "gate8_plateau": g8,
           "runtime_seconds": round(time.time() - t0, 1)}
    out_path = OUT / "leverage_gates78_results.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, default=str)

    print("\n" + "=" * 70)
    print("GATE 7 & 8 SUMMARY — leveraged candidates")
    print("=" * 70)
    for name in CANDIDATES:
        g7r = g7.get(name, {})
        g8r = g8.get(name, {})
        print(f"\n{name}:")
        print(f"  Gate 7 permutation:")
        print(f"    real Sharpe     = {g7r.get('real_sharpe')}")
        print(f"    null mean       = {g7r.get('null_mean')}")
        print(f"    null 99th%ile   = {g7r.get('null_99th')}")
        print(f"    p-value         = {g7r.get('p_value')}")
        print(f"    GATE 7 p<0.01:  {'PASS' if g7r.get('pass_p_lt_0_01') else 'FAIL'}")
        print(f"  Gate 8 plateau:")
        print(f"    real Sharpe     = {g8r.get('real_sharpe')}")
        print(f"    max drop        = {g8r.get('max_drop_pct')}%")
        print(f"    GATE 8 drop<=30%: {'PASS' if g8r.get('pass_drop_le_30pct') else 'FAIL'}")

    print(f"\nSaved -> {out_path}")
    print(f"Total runtime: {out['runtime_seconds']}s")

if __name__ == "__main__":
    main()
