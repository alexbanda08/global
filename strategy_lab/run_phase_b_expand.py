"""
Phase B Expansion — SMC family + V23 BBBreak coverage gaps.

Builds equity curves for:
  - 25 SMC cells  (5 signals × 5 coins via run_v38_smc.py)
  -  3 BB gaps    (sig_bbbreak on AVAX/LINK/XRP via run_v38b_smc_mixes.py)

Outputs: docs/research/phase5_results/equity_curves/perps/<label>.parquet
         column: equity

Usage:
    python strategy_lab/run_phase_b_expand.py
"""
from __future__ import annotations

import contextlib
import importlib.util as _il
import io
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "strategy_lab"))

import engine                                                # noqa: E402
from eval.perps_simulator import simulate, compute_metrics  # noqa: E402

# ── Output dirs ──────────────────────────────────────────────────────────────
OUT_DIR = REPO / "docs" / "research" / "phase5_results"
EQ_DIR  = OUT_DIR / "equity_curves" / "perps"
EQ_DIR.mkdir(parents=True, exist_ok=True)

# ── Simulator constants (mirrors run_portfolio_hunt.py) ───────────────────────
BARS_PER_YEAR = {"15m": 365.25*96, "30m": 365.25*48, "1h": 365.25*24,
                 "2h":  365.25*12, "4h":  365.25*6,  "1d": 365.25}
EXIT_4H   = dict(tp_atr=10.0, sl_atr=2.0, trail_atr=6.0, max_hold=60)
DEFAULT_CFG = dict(risk_per_trade=0.03, leverage_cap=3.0,
                   fee=0.00045, slip=0.0003, init_cash=10_000.0)

# ── Cells to build ────────────────────────────────────────────────────────────
CELLS = [
    # SMC family (5 signals × 5 coins)
    ("SMC_BOS_BTC_4h",    "run_v38_smc.py", "sig_bos_continuation",  "BTCUSDT",  "4h"),
    ("SMC_BOS_ETH_4h",    "run_v38_smc.py", "sig_bos_continuation",  "ETHUSDT",  "4h"),
    ("SMC_BOS_SOL_4h",    "run_v38_smc.py", "sig_bos_continuation",  "SOLUSDT",  "4h"),
    ("SMC_BOS_AVAX_4h",   "run_v38_smc.py", "sig_bos_continuation",  "AVAXUSDT", "4h"),
    ("SMC_BOS_LINK_4h",   "run_v38_smc.py", "sig_bos_continuation",  "LINKUSDT", "4h"),

    ("SMC_CHOCH_BTC_4h",  "run_v38_smc.py", "sig_choch_reversal",    "BTCUSDT",  "4h"),
    ("SMC_CHOCH_ETH_4h",  "run_v38_smc.py", "sig_choch_reversal",    "ETHUSDT",  "4h"),
    ("SMC_CHOCH_SOL_4h",  "run_v38_smc.py", "sig_choch_reversal",    "SOLUSDT",  "4h"),
    ("SMC_CHOCH_AVAX_4h", "run_v38_smc.py", "sig_choch_reversal",    "AVAXUSDT", "4h"),
    ("SMC_CHOCH_LINK_4h", "run_v38_smc.py", "sig_choch_reversal",    "LINKUSDT", "4h"),

    ("SMC_FVG_BTC_4h",    "run_v38_smc.py", "sig_fvg_entry",         "BTCUSDT",  "4h"),
    ("SMC_FVG_ETH_4h",    "run_v38_smc.py", "sig_fvg_entry",         "ETHUSDT",  "4h"),
    ("SMC_FVG_SOL_4h",    "run_v38_smc.py", "sig_fvg_entry",         "SOLUSDT",  "4h"),
    ("SMC_FVG_AVAX_4h",   "run_v38_smc.py", "sig_fvg_entry",         "AVAXUSDT", "4h"),
    ("SMC_FVG_LINK_4h",   "run_v38_smc.py", "sig_fvg_entry",         "LINKUSDT", "4h"),

    ("SMC_OB_BTC_4h",     "run_v38_smc.py", "sig_ob_touch",          "BTCUSDT",  "4h"),
    ("SMC_OB_ETH_4h",     "run_v38_smc.py", "sig_ob_touch",          "ETHUSDT",  "4h"),
    ("SMC_OB_SOL_4h",     "run_v38_smc.py", "sig_ob_touch",          "SOLUSDT",  "4h"),
    ("SMC_OB_AVAX_4h",    "run_v38_smc.py", "sig_ob_touch",          "AVAXUSDT", "4h"),
    ("SMC_OB_LINK_4h",    "run_v38_smc.py", "sig_ob_touch",          "LINKUSDT", "4h"),

    ("SMC_CONF_BTC_4h",   "run_v38_smc.py", "sig_smc_confluence",    "BTCUSDT",  "4h"),
    ("SMC_CONF_ETH_4h",   "run_v38_smc.py", "sig_smc_confluence",    "ETHUSDT",  "4h"),
    ("SMC_CONF_SOL_4h",   "run_v38_smc.py", "sig_smc_confluence",    "SOLUSDT",  "4h"),
    ("SMC_CONF_AVAX_4h",  "run_v38_smc.py", "sig_smc_confluence",    "AVAXUSDT", "4h"),
    ("SMC_CONF_LINK_4h",  "run_v38_smc.py", "sig_smc_confluence",    "LINKUSDT", "4h"),

    # V23 BB gaps — coins not already in pool (BTC/ETH/SOL/DOGE covered)
    ("BB_AVAX_4h",  "run_v38b_smc_mixes.py", "sig_bbbreak", "AVAXUSDT", "4h"),
    ("BB_LINK_4h",  "run_v38b_smc_mixes.py", "sig_bbbreak", "LINKUSDT", "4h"),
    ("BB_XRP_4h",   "run_v38b_smc_mixes.py", "sig_bbbreak", "XRPUSDT",  "4h"),
]


# ── Module loader (same as run_portfolio_hunt.py) ─────────────────────────────
def _load_mod(fname: str):
    p = REPO / "strategy_lab" / fname
    spec = _il.spec_from_file_location(f"_phb_{p.stem}", p)
    mod  = _il.module_from_spec(spec)
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        spec.loader.exec_module(mod)
    return mod


def _unpack(out):
    if isinstance(out, tuple) and len(out) == 2:
        return out[0], out[1]
    if isinstance(out, dict):
        return out.get("entries") or out.get("long_entries"), out.get("short_entries")
    raise TypeError(f"unexpected signal output type: {type(out)}")


# ── NaN-bleed check: warn if first-500-bar signals are all NaN-driven ─────────
def _check_warmup(label: str, long_sig: pd.Series, short_sig: pd.Series) -> bool:
    """
    Returns True (ok to proceed) / False (suspicious — skip).
    Heuristic: if the first 500 bars have >95% True in EITHER direction
    the signal hasn't warmed up and is leaking noise.
    """
    n = min(500, len(long_sig))
    for s, name in [(long_sig.iloc[:n], "long"), (short_sig.iloc[:n], "short")]:
        rate = float(s.mean())
        if rate > 0.95:
            print(f"  {label}: WARMUP SKIP — {name} fires {rate*100:.0f}% in first {n} bars")
            return False
    return True


# ── Per-cell build ────────────────────────────────────────────────────────────
def build_one(label: str, fname: str, fn_name: str, sym: str, tf: str):
    """Returns (equity, metrics) or raises on error."""
    mod = _load_mod(fname)
    fn  = getattr(mod, fn_name, None)
    if fn is None:
        raise AttributeError(f"function '{fn_name}' not found in {fname}")

    df = engine.load(sym, tf, start="2021-01-01", end="2026-04-24")

    long_sig, short_sig = _unpack(fn(df))

    if not _check_warmup(label, long_sig, short_sig):
        raise ValueError("warmup/NaN bleed detected — skipped")

    trades, equity = simulate(df, long_sig, short_sig, **EXIT_4H, **DEFAULT_CFG)

    bpy = BARS_PER_YEAR.get(tf, 2190.0)
    m   = compute_metrics(label, equity, trades, bpy)
    return equity, m


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    t0 = time.perf_counter()

    persisted   = []
    errors      = {}   # label -> error string
    cell_mets   = []

    print(f"\n=== Phase B — building {len(CELLS)} cells ===\n")

    for label, fname, fn_name, sym, tf in CELLS:
        print(f"  {label:24s} {sym:10s} {tf} ... ", end="", flush=True)
        try:
            eq, m = build_one(label, fname, fn_name, sym, tf)
        except Exception as e:
            tag = type(e).__name__
            errors[label] = f"{tag}: {e}"
            print(f"ERROR [{tag}]: {e}")
            continue

        # Persist
        out_path = EQ_DIR / f"{label}.parquet"
        eq.to_frame("equity").to_parquet(out_path)
        persisted.append(label)

        n_t = m.get("n_trades", "?")
        sh  = m.get("sharpe", 0.0)
        cg  = m.get("cagr", 0.0)
        mdd = m.get("max_dd", 0.0)

        # Trade count flags
        flag = ""
        if isinstance(n_t, int):
            if n_t < 20:
                flag = " [LOW-TRADES]"
            elif n_t >= 500:
                flag = " [OVER-TRADING]"

        print(f"n_trades={n_t} Sh={sh:+.2f} CAGR={cg*100:+.0f}% MDD={mdd*100:.1f}%{flag}")
        cell_mets.append({**m, "label": label, "symbol": sym, "tf": tf,
                          "fn": fn_name, "module": fname})

    elapsed = time.perf_counter() - t0

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n=== Phase B Summary ===")
    print(f"  Persisted : {len(persisted)}/{len(CELLS)}")
    print(f"  Errors    : {len(errors)}")

    if errors:
        # Group by error category
        cats: dict[str, list[str]] = {}
        for lbl, msg in errors.items():
            cat = msg.split(":")[0]
            cats.setdefault(cat, []).append(lbl)
        for cat, lbls in cats.items():
            print(f"    [{cat}] ({len(lbls)}): {', '.join(lbls)}")

    if cell_mets:
        df_m = pd.DataFrame(cell_mets)
        # Save per-cell CSV
        df_m.to_csv(OUT_DIR / "phase_b_cells.csv", index=False)

        # Trade count analysis
        if "n_trades" in df_m.columns:
            low_t  = df_m[df_m["n_trades"] < 20]
            over_t = df_m[df_m["n_trades"] >= 500]
            print(f"\n  Trade-count check:")
            print(f"    <20 trades  : {len(low_t)} cells")
            print(f"    >=500 trades: {len(over_t)} cells")

        # Top 5 by Sharpe + stars
        if "sharpe" in df_m.columns:
            top5 = df_m.nlargest(5, "sharpe")[
                ["label", "sharpe", "cagr", "max_dd", "n_trades"]
            ]
            print(f"\n  Top 5 by Sharpe:")
            for _, r in top5.iterrows():
                star = ""
                if r.get("sharpe", 0) > 1.5:
                    star += " ** SHARPE>1.5"
                if abs(r.get("max_dd", 1)) < 0.15:
                    star += " ** MDD<15%"
                print(f"    {r['label']:24s}  Sh={r['sharpe']:+.2f}  "
                      f"CAGR={r['cagr']*100:+.1f}%  MDD={r['max_dd']*100:.1f}%"
                      f"  n={int(r['n_trades'])}{star}")

        stars = df_m[(df_m.get("sharpe", pd.Series(dtype=float)) > 1.5) |
                     (df_m.get("max_dd",  pd.Series(dtype=float)).abs() < 0.15)]
        if len(stars):
            print(f"\n  Potential stars (Sh>1.5 or MDD<15%): {', '.join(stars['label'].tolist())}")

    print(f"\n  Runtime: {elapsed:.1f}s")
    print(f"  Output : {EQ_DIR}")


if __name__ == "__main__":
    main()
