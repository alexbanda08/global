"""Leverage sweep on the ensemble champions to find the ROI/MDD frontier.

Sweeps:
  1h leg: applies a leverage multiplier to per-trade returns (post-hoc, approximation)
            since gauntlet engine is unleveraged-style.
  4h leg: passes leverage_cap and risk_per_trade to perps_simulator natively.
            Vol-targeted ATR-risk sizing means leverage is "soft" — the simulator
            won't over-leverage if ATR-risk says size should be smaller.

Combinations tested per asset (4h leg):
  leverage_cap ∈ {1, 2, 3, 5, 10}
  risk_per_trade ∈ {0.02, 0.03, 0.05, 0.07}
  = 20 configs

Then for the 1h leg we test multiplier ∈ {1, 2, 3, 5} (on returns).
Combine pairs of (1h_lev, 4h_lev_cfg) and pick the Pareto frontier (highest ROI per MDD).

Output:
  strategy_lab/reports/derivatives_zscore/ensemble/leverage_sweep.csv
  Most-attractive points printed to stdout per asset.
"""
from __future__ import annotations
from pathlib import Path
import sys
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "strategy_lab"))

from eval.perps_simulator import simulate
from v4_signals.derivatives_zscore import strategy_4h as s4h
from v4_signals.derivatives_zscore import gauntlet as g
from v4_signals.derivatives_zscore.ensemble import CHAMPIONS, run_1h_leg, INIT_CAPITAL, LEG_CAPITAL

REPORTS = ROOT / "strategy_lab" / "reports" / "derivatives_zscore" / "ensemble"
REPORTS.mkdir(parents=True, exist_ok=True)


def lever_1h(eq_dollar: pd.Series, init_cash: float, lev: float) -> pd.Series:
    """Apply leverage multiplier to a 1h equity series.

    Treats the per-bar return stream as `lev * raw_return`. This is mathematically
    a leveraged version of the same trades — same entries, same holding periods, just
    bigger positions. Compounding is applied bar-by-bar so a -X% bar with 3× leverage
    becomes a -3X% bar.

    Note: the underlying gauntlet engine doesn't deduct extra fees for leverage, but
    Hyperliquid charges fees on notional, so leveraged positions cost N× more in fees.
    To approximate, we add an extra (lev-1)*0.0012 fee drag per trade (round-trip).
    """
    if lev == 1.0:
        return eq_dollar.copy()
    rets = eq_dollar.pct_change().fillna(0)
    leveraged = rets * lev
    # Approximate extra fee drag per trade: pretend one full RT fee per ~24 bars
    # (the average hold). This is rough — better to use trade list, but kept simple.
    extra_fee_per_bar = (lev - 1.0) * 0.0012 / 24
    leveraged_adj = leveraged - extra_fee_per_bar
    return init_cash * (1 + leveraged_adj).cumprod()


def run_4h_lev(symbol: str, cfg: dict, leverage_cap: float, risk_per_trade: float,
                init_cash: float) -> tuple[pd.Series, list]:
    df = s4h.load_4h(symbol)
    entry_fn = s4h.ENTRIES[cfg["entry"]]
    exit_cfg = s4h.EXIT_CONFIGS[cfg["exit"]]
    entries = entry_fn(df)
    if cfg["rfilter"] == "R_3loss_pause":
        entries = s4h.apply_3loss_pause(entries, df, exit_cfg)
    trades, eq = simulate(
        df=df, long_entries=entries,
        tp_atr=exit_cfg["tp_atr"], sl_atr=exit_cfg["sl_atr"],
        trail_atr=exit_cfg["trail_atr"], max_hold=exit_cfg["max_hold"],
        risk_per_trade=risk_per_trade, leverage_cap=leverage_cap,
        fee=s4h.FEE, slip=s4h.SLIP,
        init_cash=init_cash,
    )
    return eq, trades


def metrics(eq: pd.Series, n_trades: int, init_cash: float) -> dict:
    if len(eq) < 2:
        return {"sharpe": 0, "mdd": 0, "eq_x": 1, "roi_pct": 0,
                "blew_up": False, "n_trades": n_trades}
    rets = eq.pct_change().dropna()
    sd = float(rets.std())
    sharpe = (float(rets.mean()) / sd) * np.sqrt(24 * 365) if sd > 0 else 0.0
    peak = eq.cummax()
    mdd = float((eq / peak - 1).min())
    eq_x = float(eq.iloc[-1] / init_cash)
    blew_up = eq.min() <= init_cash * 0.05  # lost 95%+ at any point
    return {"sharpe": round(sharpe, 3),
            "mdd": round(mdd, 4),
            "eq_x": round(eq_x, 3),
            "roi_pct": round((eq_x - 1) * 100, 2),
            "blew_up": blew_up,
            "n_trades": n_trades}


def main():
    rows = []
    LEV_4H_CAPS = [1, 2, 3, 5, 10]
    RISKS = [0.02, 0.03, 0.05, 0.07]
    LEV_1H = [1, 2, 3, 5]

    for sym, cfg in CHAMPIONS.items():
        print(f"\n══════ {sym} ══════")

        # 1h leg base equity (lev=1)
        eq_1h_base, trades_1h = run_1h_leg(sym, cfg["v4_1h"], LEG_CAPITAL)
        n_1h = len(trades_1h)
        bh = float(pd.read_parquet(ROOT / "data/v4/derivatives_zscore/spot" /
                                    f"BINANCE-{sym.replace('USDT','')}-1h.parquet")
                   .set_index("time")["close"].astype(float).pct_change().fillna(0)
                   .add(1).prod())

        # Test each (1h_lev, 4h_lev_cap, 4h_risk) combo
        for lev_1h in LEV_1H:
            eq_1h_lev = lever_1h(eq_1h_base, LEG_CAPITAL, lev_1h)

            for lev_cap in LEV_4H_CAPS:
                for risk in RISKS:
                    eq_4h_lev, trades_4h = run_4h_lev(sym, cfg["4h"], lev_cap, risk,
                                                      LEG_CAPITAL)
                    # Combined on 1h grid (4h ffill)
                    eq_4h_aligned = eq_4h_lev.reindex(eq_1h_lev.index, method="ffill").fillna(LEG_CAPITAL)
                    eq_combined = eq_1h_lev + eq_4h_aligned

                    m_combined = metrics(eq_combined, n_1h + len(trades_4h), INIT_CAPITAL)
                    m_1h = metrics(eq_1h_lev, n_1h, LEG_CAPITAL)
                    m_4h = metrics(eq_4h_lev, len(trades_4h), LEG_CAPITAL)

                    rows.append({
                        "symbol": sym,
                        "lev_1h": lev_1h,
                        "lev_4h_cap": lev_cap,
                        "risk_4h": risk,
                        "buy_hold_x": round(bh, 3),
                        "leg_1h_eq_x": m_1h["eq_x"],
                        "leg_1h_mdd": m_1h["mdd"],
                        "leg_4h_eq_x": m_4h["eq_x"],
                        "leg_4h_mdd": m_4h["mdd"],
                        "leg_4h_blew_up": m_4h["blew_up"],
                        "combined_eq_x": m_combined["eq_x"],
                        "combined_mdd": m_combined["mdd"],
                        "combined_sharpe": m_combined["sharpe"],
                        "combined_roi_pct": m_combined["roi_pct"],
                        "combined_blew_up": m_combined["blew_up"],
                        "combined_outperform": round(m_combined["eq_x"] / bh, 3),
                        "final_dollar": round(INIT_CAPITAL * m_combined["eq_x"], 0),
                    })

    out = pd.DataFrame(rows)
    out.to_csv(REPORTS / "leverage_sweep.csv", index=False)

    # Print Pareto-frontier per asset: highest ROI without blowing up + MDD ≥ -50%
    print("\n══════════════ TOP 5 PER ASSET (no blow-up, MDD ≥ -50%) ══════════════")
    for sym in CHAMPIONS:
        sub = out[(out["symbol"] == sym)
                  & (~out["combined_blew_up"])
                  & (out["combined_mdd"] >= -0.50)]
        sub = sub.sort_values("combined_eq_x", ascending=False).head(5)
        print(f"\n{sym}:")
        if len(sub) == 0:
            print("  (no eligible config)")
            continue
        print(f"  {'lev1h':>5} {'lev4h':>5} {'risk':>5} {'eq×':>6} {'ROI%':>7} {'MDD%':>7} {'Sharpe':>6} {'final$':>10}")
        for _, r in sub.iterrows():
            print(f"  {r['lev_1h']:>5} {r['lev_4h_cap']:>5} {r['risk_4h']:>5.2f} "
                  f"{r['combined_eq_x']:>6.2f} {r['combined_roi_pct']:>+7.1f} "
                  f"{r['combined_mdd']*100:>+7.1f} {r['combined_sharpe']:>+6.2f} "
                  f"${r['final_dollar']:>9,.0f}")

    print(f"\nFull sweep: {REPORTS/'leverage_sweep.csv'} ({len(out)} rows)")


if __name__ == "__main__":
    main()
