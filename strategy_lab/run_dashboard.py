"""
run_dashboard — the standard entrypoint for every test we display.

Usage from Python:
    from strategy_lab.run_dashboard import show
    show([
        ("V15 Balanced",  eq_v15,  trades_v15),
        ("V24 MF",        eq_v24,  trades_v24),
        ("USER 5-Sleeve", eq_user, None),       # trades are optional
    ])
    # -> opens a self-contained HTML dashboard with our native numbers.

Usage from CLI (default):
    python -m strategy_lab.run_dashboard
    # rebuilds dashboard from the canonical 4 portfolios currently saved
    # in strategy_lab/results/v35_cross/sleeve_equities_2023plus_normed.csv.

The dashboard features you get "for free" from IAF:
  * Equity overlay (log + linear)
  * Drawdown underwater chart per strategy
  * Monthly / yearly return heatmap
  * Leaderboard sorted by any of: CAGR, Sharpe, Sortino, Calmar, MaxDD
  * Per-strategy tabs with trade list / stats
  * 14-metric side-by-side table
  * Rolling 252-bar Sharpe

The math (equity + trades + metrics) is ALWAYS computed by our native
simulators (vbt-free, in `portfolio_audit.py`, `v23_low_dd_xsm.py`,
`v29_long_short_deep.py`, `run_v34_portfolio.py`).  IAF is used ONLY as a
presentation layer.
"""
from __future__ import annotations
from pathlib import Path
import shutil

import pandas as pd

from strategy_lab.native_to_iaf import render_native_dashboard


DEFAULT_OUT = Path("strategy_lab/reports/NATIVE_DASHBOARD.html")
PUBLIC_COPY = Path("C:/Users/alexandre bandarra/Desktop/newstrategies/NATIVE_DASHBOARD.html")


def show(entries,
         output_html: str | Path = DEFAULT_OUT,
         public_copy: str | Path | None = PUBLIC_COPY,
         initial_balance: float = 10_000.0,
         trading_symbol: str = "USDT",
         open_browser: bool = False):
    """
    entries: iterable of (label, equity_series, trades_df_or_None)
             - equity_series: pandas Series indexed by UTC datetimes
             - trades_df:     DataFrame with columns (entry_time, exit_time,
                              entry_price, exit_price, shares, return)
                              or None (dashboard still renders)
    """
    output_html = Path(output_html)
    out, _ = render_native_dashboard(
        entries=list(entries),
        output_html=str(output_html),
        initial_balance=initial_balance,
        trading_symbol=trading_symbol,
    )
    if public_copy:
        public_copy = Path(public_copy)
        public_copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(out, public_copy)
        print(f"Copied to {public_copy}")

    if open_browser:
        import webbrowser
        webbrowser.open(str(out))

    return out


# ---------------------------------------------------------------------
def _default_entries(include_user_sleeves: bool = True):
    """Canonical entries:
      * 4 portfolio aggregates (USER 5-Sleeve combined + V15 / V24 / V27 XSM) — equity only.
      * 5 USER per-sleeve entries WITH per-trade logs for drill-down (when available).
    """
    v35 = Path("strategy_lab/results/v35_cross/sleeve_equities_2023plus_normed.csv")
    df = pd.read_csv(v35, index_col=0, parse_dates=[0])
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    entries = []
    for col, label in [("USER_5SLEEVE_EQW", "USER 5-Sleeve"),
                       ("MY_V15_BALANCED",  "V15 Balanced XSM"),
                       ("MY_V24_MF_1x",     "V24 Multi-filter XSM"),
                       ("MY_V27_LS_0.5x",   "V27 L/S 0.5x")]:
        if col in df.columns:
            entries.append((label, df[col].dropna(), None))

    if include_user_sleeves:
        try:
            from strategy_lab.dashboard_user_sleeves import (
                load_user_5sleeve_with_trades, USER_5_TARGETS,
            )
            print("Loading USER per-sleeve trade logs ...")
            sl = load_user_5sleeve_with_trades()
            for label in USER_5_TARGETS:
                eq, trs = sl.get(label, (None, None))
                if eq is None or len(eq) == 0:
                    continue
                entries.append((f"USER · {label}", eq, trs))
        except Exception as e:
            print(f"  (skipping per-sleeve trades: {type(e).__name__}: {e})")

    return entries


def main():
    print("Rendering default dashboard from saved V35 cross-reference equities ...")
    entries = _default_entries()
    out = show(entries, open_browser=False)
    print(f"\nDone: {out}")


if __name__ == "__main__":
    main()
