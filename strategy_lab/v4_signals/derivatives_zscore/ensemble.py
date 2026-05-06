"""Ensemble champion: 1h-v4 (low-vol regime, fixed hold) + 4h-A6_3of3 (event-driven exits).

Logic: split capital 50/50 between the two sub-strategies.
Each runs independently with $5,000 starting cash; final equity = sum of both legs.
Because they fire at different times and use different exit logic, they're naturally
diversified — combined MDD should be shallower than either alone.

Per-asset champion configs from prior research:
  BTC : v4 V9_lowvol      (1h)   +  4h A3_brigalS+TP6+3loss_pause    (4h, BTC's best 4h)
  ETH : v4 V10_ma200_lowvol (1h) +  4h A1_zlsr_only+TP6+R_none       (4h)
  SOL : v4 V10_ma200_lowvol (1h) +  4h A6_3of3+TP6+3loss_pause       (4h, the breakthrough)

Output:
  strategy_lab/reports/derivatives_zscore/ensemble/
    {SYMBOL}/equity_1h.parquet
    {SYMBOL}/equity_4h.parquet
    {SYMBOL}/equity_combined.parquet
    {SYMBOL}/trades_1h.parquet
    {SYMBOL}/trades_4h.parquet
    summary.csv          — final metrics per asset for the dashboard
"""
from __future__ import annotations
from pathlib import Path
import sys
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "strategy_lab"))

from eval.perps_simulator import simulate, compute_metrics
from v4_signals.derivatives_zscore import strategy_4h as s4h
from v4_signals.derivatives_zscore import gauntlet as g

PANELS = ROOT / "data" / "v4" / "derivatives_zscore" / "panels"
SPOT = ROOT / "data" / "v4" / "derivatives_zscore" / "spot"
REPORTS = ROOT / "strategy_lab" / "reports" / "derivatives_zscore" / "ensemble"
REPORTS.mkdir(parents=True, exist_ok=True)

INIT_CAPITAL = 10_000.0
LEG_CAPITAL = INIT_CAPITAL / 2  # 50/50 split

# Per-asset champion definitions
CHAMPIONS = {
    "BTCUSDT": {
        "v4_1h": {"variant": "V9_lowvol", "z_thr": -1.5, "hold_h": 24,
                  "stop_loss_pct": None, "use_vol_sizing": False, "vol_scaled_hold": True},
        "4h": {"entry": "A3_brigalS", "exit": "TP6_SL2p5_TR4_H48", "rfilter": "R_3loss_pause"},
    },
    "ETHUSDT": {
        "v4_1h": {"variant": "V10_ma200_lowvol", "z_thr": -1.5, "hold_h": 24,
                  "stop_loss_pct": None, "use_vol_sizing": False, "vol_scaled_hold": True},
        "4h": {"entry": "A1_zlsr_only", "exit": "TP6_SL2p5_TR4_H48", "rfilter": "R_none"},
    },
    "SOLUSDT": {
        "v4_1h": {"variant": "V10_ma200_lowvol", "z_thr": -1.5, "hold_h": 48,
                  "stop_loss_pct": None, "use_vol_sizing": False, "vol_scaled_hold": False},
        "4h": {"entry": "A6_3of3_composite", "exit": "TP6_SL2p5_TR4_H48", "rfilter": "R_3loss_pause"},
    },
}


# ─────────────────────────────────────────
#  Run 1h v4 leg (re-uses gauntlet.run_strategy)
# ─────────────────────────────────────────

def run_1h_leg(symbol: str, cfg: dict, init_cash: float) -> tuple[pd.Series, list]:
    df = g.load_h(symbol)
    eq, trades, _ = g.run_strategy(
        df,
        z_thr=cfg["z_thr"], hold_h=cfg["hold_h"], variant=cfg["variant"],
        stop_loss_pct=cfg["stop_loss_pct"],
        use_vol_sizing=cfg["use_vol_sizing"],
        vol_scaled_hold=cfg["vol_scaled_hold"],
    )
    # gauntlet.run_strategy uses cash=1.0 (multiplicative), scale to dollar
    eq_dollar = eq * init_cash
    return eq_dollar, trades


# ─────────────────────────────────────────
#  Run 4h leg (re-uses strategy_4h.run_one's internals)
# ─────────────────────────────────────────

def run_4h_leg(symbol: str, cfg: dict, init_cash: float) -> tuple[pd.Series, list]:
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
        risk_per_trade=0.03, leverage_cap=3.0,
        fee=s4h.FEE, slip=s4h.SLIP,
        init_cash=init_cash,
    )
    return eq, trades


# ─────────────────────────────────────────
#  Combine equity curves
# ─────────────────────────────────────────

def combine(eq_1h: pd.Series, eq_4h: pd.Series) -> pd.Series:
    """Sum the two legs on a common 1h grid (4h forward-filled)."""
    eq_4h_1h = eq_4h.reindex(eq_1h.index, method="ffill").fillna(LEG_CAPITAL)
    eq_1h_aligned = eq_1h.fillna(LEG_CAPITAL)
    combined = eq_1h_aligned + eq_4h_1h
    return combined


# ─────────────────────────────────────────
#  Metrics
# ─────────────────────────────────────────

def metrics(label: str, eq: pd.Series, trades_count: int, bh: float) -> dict:
    if len(eq) < 2:
        return {"label": label, "n_trades": trades_count}
    rets = eq.pct_change().dropna()
    if len(rets) < 2:
        return {"label": label, "n_trades": trades_count}
    bars_per_year = 24 * 365  # 1h grid for combined
    sd = float(rets.std())
    sharpe = (float(rets.mean()) / sd) * np.sqrt(bars_per_year) if sd > 0 else 0.0
    peak = eq.cummax()
    mdd = float((eq / peak - 1).min())
    years = (eq.index[-1] - eq.index[0]).total_seconds() / (365.25 * 86400)
    total = float(eq.iloc[-1] / eq.iloc[0]) - 1
    cagr = (1 + total) ** (1 / max(years, 1e-6)) - 1
    cal = cagr / abs(mdd) if mdd != 0 else 0.0
    return {
        "label": label,
        "n_trades": trades_count,
        "sharpe": round(sharpe, 3),
        "calmar": round(cal, 3),
        "max_dd": round(mdd, 4),
        "cagr": round(cagr, 4),
        "final_eq_x": round(eq.iloc[-1] / eq.iloc[0], 3),
        "buy_hold_x": round(bh, 3),
        "outperform": round((eq.iloc[-1] / eq.iloc[0]) / bh, 3),
    }


# ─────────────────────────────────────────
#  Main
# ─────────────────────────────────────────

def main():
    rows = []
    for sym, cfg in CHAMPIONS.items():
        print(f"\n══════ {sym} ══════")
        out_dir = REPORTS / sym
        out_dir.mkdir(parents=True, exist_ok=True)

        # Buy-and-hold baseline
        spot = pd.read_parquet(SPOT / f"BINANCE-{sym.replace('USDT','')}-1h.parquet").set_index("time")["close"].astype(float)
        bh = float(spot.iloc[-1] / spot.iloc[0])

        # 1h leg
        print(f"  [1h] {cfg['v4_1h']['variant']} (hold={cfg['v4_1h']['hold_h']}h)")
        eq_1h, trades_1h = run_1h_leg(sym, cfg["v4_1h"], LEG_CAPITAL)
        m_1h = metrics(f"1h_{cfg['v4_1h']['variant']}", eq_1h, len(trades_1h), bh)
        eq_1h.to_frame("equity").to_parquet(out_dir / "equity_1h.parquet")
        if trades_1h:
            pd.DataFrame(trades_1h).to_parquet(out_dir / "trades_1h.parquet")
        print(f"    n={m_1h['n_trades']}  Sharpe={m_1h['sharpe']:+.2f}  "
              f"Calmar={m_1h['calmar']:+.2f}  MDD={m_1h['max_dd']*100:+.1f}%  "
              f"eq={m_1h['final_eq_x']:.2f}× ({m_1h['outperform']:.2f}× B&H)")

        # 4h leg
        print(f"  [4h] {cfg['4h']['entry']} + {cfg['4h']['exit']} + {cfg['4h']['rfilter']}")
        eq_4h, trades_4h = run_4h_leg(sym, cfg["4h"], LEG_CAPITAL)
        m_4h = metrics(f"4h_{cfg['4h']['entry']}", eq_4h, len(trades_4h), bh)
        eq_4h.to_frame("equity").to_parquet(out_dir / "equity_4h.parquet")
        if trades_4h:
            pd.DataFrame(trades_4h).to_parquet(out_dir / "trades_4h.parquet")
        print(f"    n={m_4h['n_trades']}  Sharpe={m_4h['sharpe']:+.2f}  "
              f"Calmar={m_4h['calmar']:+.2f}  MDD={m_4h['max_dd']*100:+.1f}%  "
              f"eq={m_4h['final_eq_x']:.2f}× ({m_4h['outperform']:.2f}× B&H)")

        # Combine
        eq_combined = combine(eq_1h, eq_4h)
        # Note: combined "n_trades" is sum of both legs
        n_combined = len(trades_1h) + len(trades_4h)
        # Buy-hold for combined: $10k → $10k * bh
        bh_combined = bh
        m_combined = metrics("combined_50_50", eq_combined, n_combined, bh_combined)
        # Override final_eq_x: combined equity / INIT_CAPITAL
        m_combined["final_eq_x"] = round(eq_combined.iloc[-1] / INIT_CAPITAL, 3)
        m_combined["outperform"] = round(m_combined["final_eq_x"] / bh, 3)
        eq_combined.to_frame("equity").to_parquet(out_dir / "equity_combined.parquet")
        print(f"  [Combined 50/50]  n={n_combined}  Sharpe={m_combined['sharpe']:+.2f}  "
              f"Calmar={m_combined['calmar']:+.2f}  MDD={m_combined['max_dd']*100:+.1f}%  "
              f"eq={m_combined['final_eq_x']:.2f}× ({m_combined['outperform']:.2f}× B&H)")

        # Aggregate row
        rows.append({
            "symbol": sym,
            "buy_hold_x": bh,
            "leg_1h_variant": cfg["v4_1h"]["variant"],
            "leg_1h_n": m_1h["n_trades"],
            "leg_1h_sharpe": m_1h["sharpe"],
            "leg_1h_mdd": m_1h["max_dd"],
            "leg_1h_eq_x": m_1h["final_eq_x"],
            "leg_4h_variant": f"{cfg['4h']['entry']}+{cfg['4h']['exit']}+{cfg['4h']['rfilter']}",
            "leg_4h_n": m_4h["n_trades"],
            "leg_4h_sharpe": m_4h["sharpe"],
            "leg_4h_mdd": m_4h["max_dd"],
            "leg_4h_eq_x": m_4h["final_eq_x"],
            "combined_n": n_combined,
            "combined_sharpe": m_combined["sharpe"],
            "combined_calmar": m_combined["calmar"],
            "combined_mdd": m_combined["max_dd"],
            "combined_cagr": m_combined["cagr"],
            "combined_eq_x": m_combined["final_eq_x"],
            "combined_outperform": m_combined["outperform"],
        })

    out = pd.DataFrame(rows)
    out.to_csv(REPORTS / "summary.csv", index=False)
    print(f"\nWrote {REPORTS / 'summary.csv'}")
    print(out[["symbol", "leg_1h_eq_x", "leg_4h_eq_x", "combined_eq_x",
               "combined_sharpe", "combined_mdd", "combined_outperform"]].to_string(index=False))


if __name__ == "__main__":
    main()
