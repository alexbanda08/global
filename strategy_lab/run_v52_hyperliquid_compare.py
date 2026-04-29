"""
Re-run V52 champion on Hyperliquid OHLCV + funding, compare vs Binance.

Overlap window: 2024-01-12 -> 2026-04-24 (~2.3 years)

Outputs:
  docs/research/phase5_results/v52_hyperliquid_vs_binance.json
  docs/research/phase5_results/binance_vs_hl_correlations.csv
"""
from __future__ import annotations
import importlib.util, json, sys, time, warnings
from pathlib import Path
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from strategy_lab.engine import load as load_binance
from strategy_lab.util.hl_data import load_hl, funding_per_4h_bar
from strategy_lab.eval.perps_simulator import simulate as sim_canonical
from strategy_lab.eval.perps_simulator_adaptive_exit import simulate_adaptive_exit, REGIME_EXITS_4H
from strategy_lab.eval.perps_simulator_funding import simulate_with_funding
from strategy_lab.regime.hmm_adaptive import fit_regime_model
from strategy_lab.run_leverage_audit import eqw_blend, invvol_blend
from strategy_lab.run_v41_expansion import metrics
from strategy_lab.strategies.v50_new_signals import (
    sig_mfi_extreme, sig_signed_vol_div, sig_volume_profile_rot,
)

OUT = REPO / "docs" / "research" / "phase5_results"
BPY = 365.25 * 6

# Overlap window — HL klines start 2024-01-12, take everything from there
START = "2024-01-12"
END = "2026-04-24"
EXIT_4H = dict(tp_atr=10.0, sl_atr=2.0, trail_atr=6.0, max_hold=60)

# V41 BEST_VARIANT_MAP (champion sleeves)
V41_VARIANT_MAP = {
    "CCI_ETH_4h":    "V41",
    "STF_SOL_4h":    "baseline",
    "STF_AVAX_4h":   "V45",
    "LATBB_AVAX_4h": "baseline",
}

SLEEVE_SPECS = {
    "CCI_ETH_4h":    ("run_v30_creative.py",  "sig_cci_extreme",     "ETHUSDT",  "ETH"),
    "STF_SOL_4h":    ("run_v30_creative.py",  "sig_supertrend_flip", "SOLUSDT",  "SOL"),
    "STF_AVAX_4h":   ("run_v30_creative.py",  "sig_supertrend_flip", "AVAXUSDT", "AVAX"),
    "LATBB_AVAX_4h": ("run_v29_regime.py",    "sig_lateral_bb_fade", "AVAXUSDT", "AVAX"),
}

# Diversifiers
DIV_SPECS = [
    ("MFI_SOL",    "SOLUSDT",  "SOL",  sig_mfi_extreme,        dict(lower=25, upper=75), "V41"),
    ("VP_LINK",    "LINKUSDT", "LINK", sig_volume_profile_rot, dict(win=60, n_bins=15), "baseline"),
    ("SVD_AVAX",   "AVAXUSDT", "AVAX", sig_signed_vol_div,     dict(lookback=20, cvd_win=50, min_cvd_threshold=0.5), "baseline"),
    ("MFI_ETH",    "ETHUSDT",  "ETH",  sig_mfi_extreme,        dict(lower=25, upper=75), "baseline"),
]


def import_sig(script, fn):
    path = REPO / "strategy_lab" / script
    spec = importlib.util.spec_from_file_location(script.replace(".","_"), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, fn)


def load(source: str, symbol_b: str, symbol_h: str) -> pd.DataFrame:
    """source = 'binance' or 'hyperliquid'"""
    if source == "binance":
        df = load_binance(symbol_b, "4h", start=START, end=END)
    else:
        df = load_hl(symbol_h, "4h", start=START, end=END)
    return df


def build_v41_sleeve(source: str, sleeve: str, with_funding: bool):
    script, fn, sym_b, sym_h = SLEEVE_SPECS[sleeve]
    sig = import_sig(script, fn)
    df = load(source, sym_b, sym_h)
    out = sig(df); le, se = out if isinstance(out, tuple) else (out, None)
    variant = V41_VARIANT_MAP[sleeve]

    # Funding series (only HL with_funding case)
    if source == "hyperliquid" and with_funding:
        fund = funding_per_4h_bar(sym_h, df.index)
    else:
        fund = pd.Series(0.0, index=df.index)

    if variant == "baseline":
        if with_funding and source == "hyperliquid":
            tr, eq = simulate_with_funding(df, le, se, fund, **EXIT_4H)
        else:
            tr, eq = sim_canonical(df, le, se, **EXIT_4H)
    elif variant == "V41":
        # use full df for regime fit (forward-only)
        _, rdf = fit_regime_model(df, train_frac=0.30, seed=42)
        if with_funding and source == "hyperliquid":
            tr, eq = simulate_with_funding(df, le, se, fund,
                                             regime_labels=rdf["label"],
                                             regime_exits=REGIME_EXITS_4H)
        else:
            tr, eq = simulate_adaptive_exit(df, le, se, rdf["label"])
    elif variant == "V45":
        # V41 + volume filter
        vol = df["volume"]
        vmean = vol.rolling(20, min_periods=10).mean()
        active = vol > 1.1 * vmean
        le2 = le & active
        se2 = se & active if se is not None else None
        _, rdf = fit_regime_model(df, train_frac=0.30, seed=42)
        if with_funding and source == "hyperliquid":
            tr, eq = simulate_with_funding(df, le2, se2, fund,
                                             regime_labels=rdf["label"],
                                             regime_exits=REGIME_EXITS_4H)
        else:
            tr, eq = simulate_adaptive_exit(df, le2, se2, rdf["label"])
    return eq, tr


def build_diversifier(source: str, name: str, with_funding: bool):
    spec = next(s for s in DIV_SPECS if s[0] == name)
    _, sym_b, sym_h, sig_fn, kw, exit_style = spec
    df = load(source, sym_b, sym_h)
    out = sig_fn(df, **kw); le, se = out if isinstance(out, tuple) else (out, None)
    fund = (funding_per_4h_bar(sym_h, df.index)
            if source == "hyperliquid" and with_funding
            else pd.Series(0.0, index=df.index))
    if exit_style == "V41":
        _, rdf = fit_regime_model(df, train_frac=0.30, seed=42)
        if with_funding and source == "hyperliquid":
            tr, eq = simulate_with_funding(df, le, se, fund,
                                             regime_labels=rdf["label"],
                                             regime_exits=REGIME_EXITS_4H)
        else:
            tr, eq = simulate_adaptive_exit(df, le, se, rdf["label"])
    else:
        if with_funding and source == "hyperliquid":
            tr, eq = simulate_with_funding(df, le, se, fund, **EXIT_4H)
        else:
            tr, eq = sim_canonical(df, le, se, **EXIT_4H)
    return eq, tr


def build_v52(source: str, with_funding: bool):
    """Build full V52 champion blend equity for given source."""
    print(f"  Building V41 sleeves for {source}...")
    v41_curves = {}
    v41_trades = {}
    for s in V41_VARIANT_MAP:
        eq, tr = build_v41_sleeve(source, s, with_funding)
        v41_curves[s] = eq
        v41_trades[s] = tr
    p3 = invvol_blend({k: v41_curves[k] for k in ["CCI_ETH_4h","STF_AVAX_4h","STF_SOL_4h"]}, window=500)
    p5 = eqw_blend({k: v41_curves[k] for k in ["CCI_ETH_4h","LATBB_AVAX_4h","STF_SOL_4h"]})
    idx = p3.index.intersection(p5.index)
    v41_r = 0.6 * p3.reindex(idx).pct_change().fillna(0) + 0.4 * p5.reindex(idx).pct_change().fillna(0)
    v41_eq = (1 + v41_r).cumprod() * 10_000.0

    print(f"  Building diversifiers for {source}...")
    div_curves = {}
    div_trades = {}
    for spec in DIV_SPECS:
        eq, tr = build_diversifier(source, spec[0], with_funding)
        div_curves[spec[0]] = eq
        div_trades[spec[0]] = tr

    # V52 60/10/10/10/10
    all_idx = v41_eq.index
    for eq in div_curves.values():
        all_idx = all_idx.intersection(eq.index)
    cr = v41_eq.reindex(all_idx).pct_change().fillna(0)
    drs = {k: eq.reindex(all_idx).pct_change().fillna(0) for k, eq in div_curves.items()}
    combined = (0.60 * cr + 0.10 * drs["MFI_SOL"] + 0.10 * drs["VP_LINK"]
                + 0.10 * drs["SVD_AVAX"] + 0.10 * drs["MFI_ETH"])
    v52_eq = (1 + combined).cumprod() * 10_000.0

    return v52_eq, v41_eq, v41_curves, div_curves, v41_trades, div_trades


def short_metrics(eq, label=""):
    rets = eq.pct_change().dropna()
    mu, sd = float(rets.mean()), float(rets.std())
    sh = (mu/sd)*np.sqrt(BPY) if sd > 0 else 0
    pk = eq.cummax(); mdd = float((eq/pk - 1).min())
    yrs = (eq.index[-1] - eq.index[0]).total_seconds()/(365.25*86400)
    total = float(eq.iloc[-1]/eq.iloc[0] - 1)
    cagr = (1+total)**(1/max(yrs,1e-6))-1
    cal = cagr/abs(mdd) if mdd != 0 else 0
    yearly = {}
    for yr in sorted(set(eq.index.year)):
        e = eq[eq.index.year == yr]
        if len(e) >= 30:
            yearly[int(yr)] = float(e.iloc[-1]/e.iloc[0] - 1)
    return {"label": label, "sharpe": round(sh, 3), "cagr": round(cagr, 4),
            "mdd": round(mdd, 4), "calmar": round(cal, 3),
            "yearly": {y: round(r, 4) for y, r in yearly.items()}}


def main():
    t0 = time.time()
    print("="*78)
    print("V52 Hyperliquid vs Binance comparison")
    print(f"Window: {START} -> {END}")
    print("="*78)

    # ---------- 1. Quick price-level correlation between sources ----------
    print("\n--- 1. Binance vs HL price correlation (close-to-close) ---")
    corr_rows = []
    for sleeve, (script, fn, sym_b, sym_h) in SLEEVE_SPECS.items():
        df_b = load("binance", sym_b, sym_h)
        df_h = load("hyperliquid", sym_b, sym_h)
        # Align on common index
        idx = df_b.index.intersection(df_h.index)
        if len(idx) < 30:
            print(f"  {sym_h}: too few common bars ({len(idx)})")
            continue
        cb = df_b["close"].reindex(idx)
        ch = df_h["close"].reindex(idx)
        rb = cb.pct_change().dropna()
        rh = ch.pct_change().dropna()
        idx_r = rb.index.intersection(rh.index)
        rb = rb.reindex(idx_r); rh = rh.reindex(idx_r)
        c_close = float(cb.corr(ch))
        c_ret = float(rb.corr(rh))
        # Volume correlation
        vb = df_b["volume"].reindex(idx)
        vh = df_h["volume"].reindex(idx)
        c_vol = float(vb.corr(vh))
        # Average volume ratio
        ratio = (vb.sum() / vh.sum()) if vh.sum() > 0 else float("nan")
        corr_rows.append({"sleeve": sleeve, "symbol": sym_h,
                          "common_bars": len(idx),
                          "corr_close": round(c_close, 4),
                          "corr_returns": round(c_ret, 4),
                          "corr_volume": round(c_vol, 4),
                          "binance_volume_x_hl": round(ratio, 1)})
    corr_df = pd.DataFrame(corr_rows)
    corr_df.to_csv(OUT / "binance_vs_hl_correlations.csv", index=False)
    print(corr_df.to_string(index=False))

    # ---------- 2. Build V52 on Binance and HL (with and without funding) ----------
    print("\n--- 2. Build V52 on Binance ---")
    binance_v52, binance_v41, _, _, _, _ = build_v52("binance", with_funding=False)
    print("\n--- 3. Build V52 on Hyperliquid (no funding) ---")
    hl_v52_nofund, hl_v41_nofund, _, _, _, _ = build_v52("hyperliquid", with_funding=False)
    print("\n--- 4. Build V52 on Hyperliquid (WITH funding) ---")
    hl_v52_fund, hl_v41_fund, _, _, _, _ = build_v52("hyperliquid", with_funding=True)

    # ---------- 5. Compare metrics ----------
    print("\n" + "="*78)
    print("V52 PERFORMANCE — overlap window 2024-01-12 -> 2026-04-24")
    print("="*78)
    results = {
        "Binance V52":            short_metrics(binance_v52, "Binance V52"),
        "Hyperliquid V52 (no funding)": short_metrics(hl_v52_nofund, "HL V52 no funding"),
        "Hyperliquid V52 (w/ funding)": short_metrics(hl_v52_fund, "HL V52 w/ funding"),
    }
    print(f"{'Variant':40s} {'Sharpe':>8s} {'CAGR':>8s} {'MDD':>8s} {'Calmar':>8s}")
    for name, r in results.items():
        print(f"{name:40s} {r['sharpe']:>8.3f} {r['cagr']*100:>7.1f}% "
              f"{r['mdd']*100:>7.1f}% {r['calmar']:>8.2f}")

    print("\nV41 (sub-component)")
    v41_results = {
        "Binance V41":            short_metrics(binance_v41, "Binance V41"),
        "Hyperliquid V41 (no funding)": short_metrics(hl_v41_nofund, "HL V41 no funding"),
        "Hyperliquid V41 (w/ funding)": short_metrics(hl_v41_fund, "HL V41 w/ funding"),
    }
    for name, r in v41_results.items():
        print(f"{name:40s} {r['sharpe']:>8.3f} {r['cagr']*100:>7.1f}% "
              f"{r['mdd']*100:>7.1f}% {r['calmar']:>8.2f}")

    # Funding cost summary
    print("\nFunding cost impact on HL V52: "
          f"CAGR drag = {(results['Hyperliquid V52 (no funding)']['cagr'] - results['Hyperliquid V52 (w/ funding)']['cagr'])*100:.2f}pp/yr")

    # ---------- 6. Save ----------
    summary = {
        "window_start": START, "window_end": END,
        "v52_results": results,
        "v41_results": v41_results,
        "correlations": corr_rows,
    }
    with open(OUT / "v52_hyperliquid_vs_binance.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\nSaved -> {OUT}/v52_hyperliquid_vs_binance.json")
    print(f"Total runtime: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
