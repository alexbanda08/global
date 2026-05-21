"""
Generate parity test fixtures for V52 implementation handoff.

Produces a self-contained test bundle the engineering agent uses to validate
their re-implementation matches our reference outputs within tolerance.

Outputs:
  tests/v52_fixtures/input_klines.parquet          — input OHLCV (HL data)
  tests/v52_fixtures/input_funding.parquet         — funding history
  tests/v52_fixtures/expected_indicators.json      — ATR + intermediate values
  tests/v52_fixtures/expected_signals.json         — boolean entry arrays per signal
  tests/v52_fixtures/expected_regime.json          — regime classifier outputs
  tests/v52_fixtures/expected_trades.json          — trade lists per strategy
  tests/v52_fixtures/expected_equity.json          — equity curves per strategy
  tests/v52_fixtures/expected_v52_blend.json       — final V52 blend equity + headline metrics

Test contract (engineering agent runs):
  1. Load input_klines + input_funding from the parquets
  2. Run their implementation through the V52 pipeline
  3. Compare each output against expected_* JSONs within documented tolerance
  4. PASS if all match
"""
from __future__ import annotations
import importlib.util, json, sys, time
from pathlib import Path
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from strategy_lab.util.hl_data import load_hl, funding_per_4h_bar
from strategy_lab.eval.perps_simulator import simulate as sim_canonical, atr
from strategy_lab.eval.perps_simulator_adaptive_exit import simulate_adaptive_exit, REGIME_EXITS_4H
from strategy_lab.eval.perps_simulator_funding import simulate_with_funding
from strategy_lab.regime.hmm_adaptive import fit_regime_model
from strategy_lab.run_leverage_audit import eqw_blend, invvol_blend
from strategy_lab.strategies.v50_new_signals import (
    sig_mfi_extreme, sig_signed_vol_div, sig_volume_profile_rot,
)

OUT = REPO / "tests" / "v52_fixtures"
OUT.mkdir(parents=True, exist_ok=True)

EXIT_4H = dict(tp_atr=10.0, sl_atr=2.0, trail_atr=6.0, max_hold=60)
N_BARS = 2000   # last N bars per symbol — enough for HMM fit + sim
SYMBOLS = ["ETH", "AVAX", "SOL", "LINK"]

# ------------- helpers -------------
def trades_to_jsonable(trades: list[dict]) -> list[dict]:
    out = []
    for t in trades:
        rec = {}
        for k, v in t.items():
            if isinstance(v, (np.integer,)):
                rec[k] = int(v)
            elif isinstance(v, (np.floating,)):
                rec[k] = round(float(v), 8)
            elif isinstance(v, pd.Timestamp):
                rec[k] = v.isoformat()
            else:
                rec[k] = v
        out.append(rec)
    return out

def import_sig(script, fn):
    path = REPO / "strategy_lab" / script
    spec = importlib.util.spec_from_file_location(script.replace(".","_"), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, fn)

# ------------- main -------------
def main():
    t0 = time.time()
    print("Building V52 parity test fixtures...")

    # === 1. Load input data ===
    print(f"Loading last {N_BARS} bars per symbol...")
    klines = {}
    fundings = {}
    for sym in SYMBOLS:
        df_full = load_hl(sym, "4h")
        df = df_full.tail(N_BARS).copy()
        klines[sym] = df
        fundings[sym] = funding_per_4h_bar(sym, df.index)

    # Save input data
    klines_combined = pd.concat({sym: klines[sym] for sym in SYMBOLS},
                                  names=["symbol"], axis=0)
    klines_combined.to_parquet(OUT / "input_klines.parquet")
    funding_combined = pd.DataFrame({sym: fundings[sym] for sym in SYMBOLS})
    funding_combined.to_parquet(OUT / "input_funding.parquet")
    print(f"  Saved {len(SYMBOLS)} symbols x {N_BARS} bars")

    # === 2. ATR reference (test indicator math) ===
    print("Computing ATR reference (n=14)...")
    atr_ref = {}
    for sym in SYMBOLS:
        a = atr(klines[sym], n=14)
        # Sample 50 evenly-spaced points for compact JSON
        idx = np.linspace(20, N_BARS - 1, 50, dtype=int)
        atr_ref[sym] = {
            "n": 14,
            "sample_indices": idx.tolist(),
            "sample_values": [round(float(a[i]), 8) for i in idx],
            "first_valid_idx": 13,  # ATR(14) needs 14 bars
            "tolerance_rtol": 1e-9,
            "comment": "Wilder-smoothed ATR with alpha=1/n. Compare element-wise within rtol.",
        }
    with open(OUT / "expected_indicators.json", "w") as f:
        json.dump({"atr": atr_ref}, f, indent=2)

    # === 3. Signal parity (each function on ETH) ===
    print("Computing signal references on ETH...")
    eth = klines["ETH"]
    sig_specs = [
        ("cci_extreme", "run_v30_creative.py", "sig_cci_extreme",
         dict(cci_n=20, cci_lo=-150, cci_hi=150, adx_max=22, adx_n=14)),
        ("supertrend_flip", "run_v30_creative.py", "sig_supertrend_flip",
         dict(st_n=10, st_mult=3.0, ema_reg=200)),
        ("lateral_bb_fade", "run_v29_regime.py", "sig_lateral_bb_fade",
         dict(bb_n=20, bb_k=2.0, adx_max=18, adx_n=14)),
    ]
    signals_out = {}
    for name, script, fn, kw in sig_specs:
        sig = import_sig(script, fn)
        out = sig(eth, **kw)
        le, se = out if isinstance(out, tuple) else (out, None)
        # Encode entries as list of bar indices where entry fires (compact)
        long_idx = [int(i) for i, v in enumerate(le.values) if bool(v)]
        short_idx = ([int(i) for i, v in enumerate(se.values) if bool(v)]
                     if se is not None else [])
        signals_out[name] = {
            "params": kw,
            "n_bars": len(eth),
            "long_entry_indices": long_idx,
            "short_entry_indices": short_idx,
            "n_longs": len(long_idx),
            "n_shorts": len(short_idx),
            "tolerance": "exact-match required (booleans)",
        }

    # New signals (v50)
    new_sigs = [
        ("mfi_75_25", sig_mfi_extreme,
         dict(n=14, lower=25, upper=75, require_cross=True)),
        ("vp_rot_60", sig_volume_profile_rot,
         dict(win=60, n_bins=15, touch_buffer=0.001)),
        ("svd_tight", sig_signed_vol_div,
         dict(lookback=20, cvd_win=50, min_cvd_threshold=0.5)),
    ]
    for name, fn, kw in new_sigs:
        out = fn(eth, **kw)
        le, se = out if isinstance(out, tuple) else (out, None)
        long_idx = [int(i) for i, v in enumerate(le.values) if bool(v)]
        short_idx = ([int(i) for i, v in enumerate(se.values) if bool(v)]
                     if se is not None else [])
        signals_out[name] = {
            "params": kw,
            "n_bars": len(eth),
            "long_entry_indices": long_idx,
            "short_entry_indices": short_idx,
            "n_longs": len(long_idx),
            "n_shorts": len(short_idx),
            "tolerance": "exact-match required (booleans)",
        }
    with open(OUT / "expected_signals.json", "w") as f:
        json.dump(signals_out, f, indent=2)
    print(f"  6 signal references saved")

    # === 4. Regime classifier reference ===
    print("Fitting regime classifier on ETH...")
    model, regime_df = fit_regime_model(eth, train_frac=0.30, seed=42)
    regime_ref = {
        "params": {
            "train_frac": 0.30,
            "seed": 42,
            "k_range": [3, 4, 5],
            "covariance_type": "full",
            "n_init": 3,
            "max_iter": 300,
            "persistence_bars": 3,
            "flicker_window": 20,
            "flicker_max_changes": 4,
        },
        "best_k": int(model.best_k),
        "bic_table": {str(k): round(float(v), 4)
                       for k, v in model.bic_table.items()},
        "regime_labels_by_id": model.regime_labels,
        "vol_score_by_id": {str(k): round(float(v), 6)
                              for k, v in model.regime_vol_score.items()},
        "verification": model.verification,
        "regime_distribution": (regime_df["label"].value_counts().to_dict()),
        "first_50_regime_labels": regime_df["label"].iloc[:50].tolist(),
        "tolerance": "exact-match on best_k, regime_distribution, label sequence (given seed=42)",
    }
    with open(OUT / "expected_regime.json", "w") as f:
        json.dump(regime_ref, f, indent=2, default=str)

    # === 5. Simulator parity (canonical + V41 + funding) ===
    print("Computing simulator reference trades + equity...")
    sig_cci = import_sig("run_v30_creative.py", "sig_cci_extreme")
    le_cci, se_cci = sig_cci(eth)

    # 5a. Canonical simulator
    tr_can, eq_can = sim_canonical(eth, le_cci, se_cci, **EXIT_4H)
    # 5b. V41 regime-adaptive simulator
    tr_v41, eq_v41 = simulate_adaptive_exit(eth, le_cci, se_cci, regime_df["label"])
    # 5c. Funding-aware simulator (canonical)
    fund_eth = fundings["ETH"]
    tr_fund, eq_fund = simulate_with_funding(eth, le_cci, se_cci, fund_eth, **EXIT_4H)

    trades_ref = {
        "canonical_cci_eth": {
            "n_trades": len(tr_can),
            "trades": trades_to_jsonable(tr_can),
            "exit_params": EXIT_4H,
            "tolerance": "exact entry_idx/exit_idx/side; rtol=1e-6 on prices/return",
        },
        "v41_regime_adaptive_cci_eth": {
            "n_trades": len(tr_v41),
            "trades": trades_to_jsonable(tr_v41),
            "exit_profiles": REGIME_EXITS_4H,
            "tolerance": "exact entry_idx/exit_idx/side/regime; rtol=1e-6 on prices",
        },
        "with_funding_cci_eth": {
            "n_trades": len(tr_fund),
            "trades": trades_to_jsonable(tr_fund),
            "tolerance": "exact entry_idx/exit_idx/side; rtol=1e-5 on funding_cost (compounding)",
        },
    }
    with open(OUT / "expected_trades.json", "w") as f:
        json.dump(trades_ref, f, indent=2, default=str)

    # === 6. Equity curve sample points ===
    print("Sampling equity curves...")
    sample_idx = np.linspace(0, N_BARS - 1, 100, dtype=int)
    equity_ref = {
        "canonical_cci_eth": {
            "init_cash": 10_000.0,
            "final": round(float(eq_can.iloc[-1]), 4),
            "sample_indices": sample_idx.tolist(),
            "sample_values": [round(float(eq_can.iloc[i]), 4) for i in sample_idx],
            "tolerance_rtol": 1e-5,
        },
        "v41_regime_adaptive_cci_eth": {
            "init_cash": 10_000.0,
            "final": round(float(eq_v41.iloc[-1]), 4),
            "sample_indices": sample_idx.tolist(),
            "sample_values": [round(float(eq_v41.iloc[i]), 4) for i in sample_idx],
            "tolerance_rtol": 1e-5,
        },
        "with_funding_cci_eth": {
            "init_cash": 10_000.0,
            "final": round(float(eq_fund.iloc[-1]), 4),
            "sample_indices": sample_idx.tolist(),
            "sample_values": [round(float(eq_fund.iloc[i]), 4) for i in sample_idx],
            "tolerance_rtol": 1e-5,
        },
    }
    with open(OUT / "expected_equity.json", "w") as f:
        json.dump(equity_ref, f, indent=2)

    # === 7. End-to-end V52 blend (the big one) ===
    print("Building end-to-end V52 blend reference...")
    # Build all 4 V41 sleeves with funding
    v41_curves = {}
    sleeve_specs = {
        "CCI_ETH_4h":    ("ETH",  "run_v30_creative.py",  "sig_cci_extreme",     "V41"),
        "STF_AVAX_4h":   ("AVAX", "run_v30_creative.py",  "sig_supertrend_flip", "V45"),
        "STF_SOL_4h":    ("SOL",  "run_v30_creative.py",  "sig_supertrend_flip", "baseline"),
        "LATBB_AVAX_4h": ("AVAX", "run_v29_regime.py",    "sig_lateral_bb_fade", "baseline"),
    }
    for sleeve, (sym, script, fn, variant) in sleeve_specs.items():
        df = klines[sym]
        sig = import_sig(script, fn)
        out = sig(df); le, se = out if isinstance(out, tuple) else (out, None)
        fund = fundings[sym]
        if variant == "baseline":
            _, eq = simulate_with_funding(df, le, se, fund, **EXIT_4H)
        elif variant == "V41":
            _, rdf = fit_regime_model(df, train_frac=0.30, seed=42)
            _, eq = simulate_with_funding(df, le, se, fund,
                                            regime_labels=rdf["label"],
                                            regime_exits=REGIME_EXITS_4H)
        elif variant == "V45":
            vol = df["volume"]; vmean = vol.rolling(20, min_periods=10).mean()
            active = vol > 1.1 * vmean
            le2 = le & active
            se2 = se & active if se is not None else None
            _, rdf = fit_regime_model(df, train_frac=0.30, seed=42)
            _, eq = simulate_with_funding(df, le2, se2, fund,
                                            regime_labels=rdf["label"],
                                            regime_exits=REGIME_EXITS_4H)
        v41_curves[sleeve] = eq

    p3 = invvol_blend({k: v41_curves[k] for k in
                       ["CCI_ETH_4h","STF_AVAX_4h","STF_SOL_4h"]}, window=500)
    p5 = eqw_blend({k: v41_curves[k] for k in
                    ["CCI_ETH_4h","LATBB_AVAX_4h","STF_SOL_4h"]})
    idx = p3.index.intersection(p5.index)
    v41_r = (0.6 * p3.reindex(idx).pct_change().fillna(0)
            + 0.4 * p5.reindex(idx).pct_change().fillna(0))
    v41_eq = (1 + v41_r).cumprod() * 10_000.0

    # Diversifiers
    div_specs = [
        ("MFI_SOL",  "SOL",  sig_mfi_extreme,        dict(lower=25, upper=75), "V41"),
        ("VP_LINK",  "LINK", sig_volume_profile_rot, dict(win=60, n_bins=15), "baseline"),
        ("SVD_AVAX", "AVAX", sig_signed_vol_div,
         dict(lookback=20, cvd_win=50, min_cvd_threshold=0.5), "baseline"),
        ("MFI_ETH",  "ETH",  sig_mfi_extreme,        dict(lower=25, upper=75), "baseline"),
    ]
    div_curves = {}
    for name, sym, fn, kw, exit_style in div_specs:
        df = klines[sym]
        out = fn(df, **kw); le, se = out if isinstance(out, tuple) else (out, None)
        fund = fundings[sym]
        if exit_style == "V41":
            _, rdf = fit_regime_model(df, train_frac=0.30, seed=42)
            _, eq = simulate_with_funding(df, le, se, fund,
                                            regime_labels=rdf["label"],
                                            regime_exits=REGIME_EXITS_4H)
        else:
            _, eq = simulate_with_funding(df, le, se, fund, **EXIT_4H)
        div_curves[name] = eq

    all_idx = v41_eq.index
    for eq in div_curves.values():
        all_idx = all_idx.intersection(eq.index)
    cr = v41_eq.reindex(all_idx).pct_change().fillna(0)
    drs = {k: eq.reindex(all_idx).pct_change().fillna(0) for k, eq in div_curves.items()}
    combined = (0.60 * cr + 0.10 * drs["MFI_SOL"] + 0.10 * drs["VP_LINK"]
                + 0.10 * drs["SVD_AVAX"] + 0.10 * drs["MFI_ETH"])
    v52_eq = (1 + combined).cumprod() * 10_000.0

    # Headline
    rets = v52_eq.pct_change().dropna()
    sd = float(rets.std())
    sh = (float(rets.mean())/sd) * np.sqrt(365.25*6) if sd > 0 else 0
    pk = v52_eq.cummax(); mdd = float((v52_eq/pk - 1).min())
    yrs = (v52_eq.index[-1] - v52_eq.index[0]).total_seconds()/(365.25*86400)
    total = float(v52_eq.iloc[-1]/v52_eq.iloc[0] - 1)
    cagr = (1+total)**(1/max(yrs,1e-6))-1
    cal = cagr/abs(mdd) if mdd != 0 else 0

    sample_idx2 = np.linspace(0, len(v52_eq) - 1, 100, dtype=int)
    v52_ref = {
        "headline": {
            "sharpe": round(sh, 4), "cagr": round(cagr, 5),
            "mdd": round(mdd, 5), "calmar": round(cal, 4),
            "final_equity": round(float(v52_eq.iloc[-1]), 4),
            "n_bars_blended": len(v52_eq),
        },
        "weights": {
            "v41_total": 0.60, "MFI_SOL": 0.10, "VP_LINK": 0.10,
            "SVD_AVAX": 0.10, "MFI_ETH": 0.10,
        },
        "v41_inner_weights": {"P3": 0.60, "P5": 0.40},
        "v41_p3_weighting": "inverse-vol rolling 500-bar",
        "v41_p5_weighting": "equal-weight",
        "sample_indices": sample_idx2.tolist(),
        "sample_equity": [round(float(v52_eq.iloc[i]), 4) for i in sample_idx2],
        "tolerance_rtol_equity": 1e-4,
        "tolerance_rtol_headline": 5e-3,
        "comment": ("End-to-end test: implementation must reproduce these "
                    "values within tolerance using ONLY input_klines.parquet "
                    "and input_funding.parquet as inputs."),
    }
    with open(OUT / "expected_v52_blend.json", "w") as f:
        json.dump(v52_ref, f, indent=2)

    # === Manifest ===
    manifest = {
        "fixture_version": "1.0",
        "generated_utc": pd.Timestamp.utcnow().isoformat(),
        "data_source": "Hyperliquid candleSnapshot + fundingHistory",
        "n_bars_per_symbol": N_BARS,
        "symbols": SYMBOLS,
        "files": {
            "input_klines.parquet": "Multi-symbol OHLCV input (the only data engine should consume)",
            "input_funding.parquet": "Per-symbol per-4h-bar summed hourly funding rates",
            "expected_indicators.json": "ATR(14) reference values at 50 sample bars",
            "expected_signals.json": "6 signal functions: long/short entry indices",
            "expected_regime.json": "GMM fit results: K*, BIC table, label distribution",
            "expected_trades.json": "Trade lists from canonical, V41, and funding-aware simulators on CCI_ETH",
            "expected_equity.json": "Equity curve sample points from each simulator",
            "expected_v52_blend.json": "End-to-end V52 blend headline metrics + 100 equity samples",
        },
        "tolerances": {
            "indicators (ATR)": "rtol=1e-9",
            "signals (booleans)": "exact match",
            "regime (best_k, distribution)": "exact (given seed=42)",
            "trade indices/sides": "exact match",
            "trade prices": "rtol=1e-6",
            "equity samples": "rtol=1e-5",
            "v52 final equity / headline metrics": "rtol=1e-4 / rtol=5e-3",
        },
        "test_order": [
            "1. ATR — proves indicator math correct",
            "2. CCI/ST/BB signals — proves signal logic correct",
            "3. New signals (MFI/VP/SVD) — proves new signal logic correct",
            "4. Regime — proves classifier deterministic with seed=42",
            "5. Canonical simulator trades — proves engine semantics correct",
            "6. V41 simulator trades — proves regime-adaptive exits correct",
            "7. Funding simulator trades — proves funding accrual correct",
            "8. V52 final equity — proves end-to-end integration correct",
        ],
    }
    with open(OUT / "MANIFEST.json", "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"\nFixtures saved to: {OUT}")
    print(f"Files: {sorted(p.name for p in OUT.glob('*'))}")
    print(f"V52 reference Sharpe={v52_ref['headline']['sharpe']} "
          f"CAGR={v52_ref['headline']['cagr']*100:+.2f}% "
          f"final_eq={v52_ref['headline']['final_equity']}")
    print(f"Time: {time.time()-t0:.1f}s")

if __name__ == "__main__":
    main()
