"""
Phase A Expansion — ~20 new cells for portfolio-hunt.

Runs canonical perps simulator on each cell and persists equity curves to
docs/research/phase5_results/equity_curves/perps/<label>.parquet

INJ quirk: INJUSDT absent from parquet — LATBB_INJ_4h uses LINKUSDT as proxy
and is relabelled LATBB_INJ_4h_via_LINK in output.
"""
from __future__ import annotations

import time
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "strategy_lab"))

# Import build_one and constants directly from run_portfolio_hunt
from run_portfolio_hunt import build_one, EQ_DIR, BARS_PER_YEAR  # noqa: E402

# ---------------------------------------------------------------------------
# Cell definitions for Phase A expansion
# ---------------------------------------------------------------------------
CELLS = [
    # V29 Lateral_BB_Fade — ADD coins
    ("LATBB_AVAX_4h",      "run_v29_regime.py", "sig_lateral_bb_fade", "AVAXUSDT", "4h"),
    ("LATBB_LINK_4h",      "run_v29_regime.py", "sig_lateral_bb_fade", "LINKUSDT", "4h"),
    # INJ not in parquet — use LINK as proxy; label marked accordingly
    ("LATBB_INJ_4h_via_LINK", "run_v29_regime.py", "sig_lateral_bb_fade", "LINKUSDT", "4h"),

    # V29 Trend_Grade_MTF — new family
    ("TGMT_AVAX_4h", "run_v29_regime.py", "sig_trend_grade", "AVAXUSDT", "4h"),
    ("TGMT_LINK_4h", "run_v29_regime.py", "sig_trend_grade", "LINKUSDT", "4h"),
    ("TGMT_BTC_4h",  "run_v29_regime.py", "sig_trend_grade", "BTCUSDT",  "4h"),
    ("TGMT_ETH_4h",  "run_v29_regime.py", "sig_trend_grade", "ETHUSDT",  "4h"),

    # V30 VWZ — fill gaps
    ("VWZ_BTC_4h",  "run_v30_creative.py", "sig_vwap_zfade", "BTCUSDT",  "4h"),
    ("VWZ_SOL_4h",  "run_v30_creative.py", "sig_vwap_zfade", "SOLUSDT",  "4h"),
    ("VWZ_AVAX_4h", "run_v30_creative.py", "sig_vwap_zfade", "AVAXUSDT", "4h"),
    ("VWZ_LINK_4h", "run_v30_creative.py", "sig_vwap_zfade", "LINKUSDT", "4h"),

    # V30 TTM — fill gaps
    ("TTM_ETH_4h",  "run_v30_creative.py", "sig_ttm_squeeze", "ETHUSDT",  "4h"),
    ("TTM_LINK_4h", "run_v30_creative.py", "sig_ttm_squeeze", "LINKUSDT", "4h"),

    # V30 STF / CCI DOGE
    ("STF_DOGE_4h", "run_v30_creative.py", "sig_supertrend_flip", "DOGEUSDT", "4h"),
    ("CCI_DOGE_4h", "run_v30_creative.py", "sig_cci_extreme",     "DOGEUSDT", "4h"),

    # V27 HTF Donchian — remaining coins
    ("HTFD_BTC_4h",  "run_v34_expand.py", "sig_htf_donchian_ls", "BTCUSDT",  "4h"),
    ("HTFD_ETH_4h",  "run_v34_expand.py", "sig_htf_donchian_ls", "ETHUSDT",  "4h"),
    ("HTFD_AVAX_4h", "run_v34_expand.py", "sig_htf_donchian_ls", "AVAXUSDT", "4h"),
    ("HTFD_LINK_4h", "run_v34_expand.py", "sig_htf_donchian_ls", "LINKUSDT", "4h"),
]


def main():
    t0 = time.time()
    EQ_DIR.mkdir(parents=True, exist_ok=True)

    successes = []
    errors = []

    print(f"\n=== Phase A Expansion: {len(CELLS)} cells ===\n")

    for label, fname, fn_name, sym, tf in CELLS:
        print(f"  {label:30s} {sym:10s} {tf} ... ", end="", flush=True)
        try:
            out = build_one(label, fname, fn_name, sym, tf)
        except Exception as e:
            msg = f"{type(e).__name__}: {e}"
            print(f"ERROR: {msg}")
            errors.append((label, msg))
            continue

        if out is None:
            msg = "build_one returned None (signal fn missing or signal error)"
            print(f"SKIP: {msg}")
            errors.append((label, msg))
            continue

        eq, m = out
        out_path = EQ_DIR / f"{label}.parquet"
        eq.to_frame("equity").to_parquet(out_path)
        print(f"n_trades={m['n_trades']} Sh={m['sharpe']:+.2f} CAGR={m['cagr']*100:+.0f}%")
        successes.append({**m, "label": label, "symbol": sym, "tf": tf, "fn": fn_name})

    elapsed = time.time() - t0

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    print("\n" + "=" * 60)
    print(f"Phase A complete in {elapsed:.1f}s")
    print(f"  Persisted : {len(successes)}")
    print(f"  Errored   : {len(errors)}")

    if errors:
        print("\nErrors:")
        for lbl, msg in errors:
            print(f"  {lbl:30s}  {msg}")

    if successes:
        df = pd.DataFrame(successes).sort_values("sharpe", ascending=False)
        print("\nTop 5 by Sharpe:")
        for _, row in df.head(5).iterrows():
            print(f"  {row['label']:30s}  Sharpe={row['sharpe']:+.3f}")

        # Also persist a summary CSV alongside the equity curves
        summary_path = EQ_DIR.parent.parent / "phase_a_expand_summary.csv"
        df.to_csv(summary_path, index=False)
        print(f"\nSummary CSV: {summary_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
