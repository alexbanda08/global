"""Test several per-asset strategy combos at risk-adjusted alloc."""
from __future__ import annotations

import json
import pandas as pd
from strategy_lab import portfolio, engine

# Candidate combos to evaluate
COMBOS = {
    "C01_all_V2B_4h":           {"BTCUSDT": ("V2B_volume_breakout", "4h"),
                                 "ETHUSDT": ("V2B_volume_breakout", "4h"),
                                 "SOLUSDT": ("V2B_volume_breakout", "4h")},
    "C02_mix_bestperasset":     {"BTCUSDT": ("V2B_volume_breakout", "4h"),
                                 "ETHUSDT": ("V2F_gaussian_channel", "1h"),
                                 "SOLUSDT": ("V2B_volume_breakout", "4h")},
    "C03_all_V2F_gauss":        {"BTCUSDT": ("V2F_gaussian_channel", "4h"),
                                 "ETHUSDT": ("V2F_gaussian_channel", "4h"),
                                 "SOLUSDT": ("V2F_gaussian_channel", "4h")},
    "C04_all_V2D_supertrend":   {"BTCUSDT": ("V2D_supertrend_regime", "4h"),
                                 "ETHUSDT": ("V2D_supertrend_regime", "4h"),
                                 "SOLUSDT": ("V2D_supertrend_regime", "4h")},
    "C05_mix_1d_only":          {"BTCUSDT": ("V2C_donchian_v2", "1d"),
                                 "ETHUSDT": ("V2C_donchian_v2", "1d"),
                                 "SOLUSDT": ("V2C_donchian_v2", "1d")},
    "C06_conservative_btc_lead":{"BTCUSDT": ("V2C_donchian_v2", "1d"),
                                 "ETHUSDT": ("V2F_gaussian_channel", "1h"),
                                 "SOLUSDT": ("V2C_donchian_v2", "1d")},
    "C07_all_V2A_ema":          {"BTCUSDT": ("V2A_ema_trend_adx", "4h"),
                                 "ETHUSDT": ("V2A_ema_trend_adx", "4h"),
                                 "SOLUSDT": ("V2A_ema_trend_adx", "4h")},
}

# Risk-adjusted allocations to try
ALLOCS = {
    "alloc_50_30_20": {"BTCUSDT": 0.50, "ETHUSDT": 0.30, "SOLUSDT": 0.20},
    "alloc_60_25_15": {"BTCUSDT": 0.60, "ETHUSDT": 0.25, "SOLUSDT": 0.15},
    "alloc_40_35_25": {"BTCUSDT": 0.40, "ETHUSDT": 0.35, "SOLUSDT": 0.25},
}

def main():
    rows = []
    for combo_name, combo in COMBOS.items():
        for alloc_name, alloc in ALLOCS.items():
            tag = f"{combo_name}__{alloc_name}"
            try:
                r = portfolio.run_combined(combo, allocation=alloc, tag=tag)
            except Exception as e:
                print(f"  FAIL {tag}: {e}")
                continue
            pm = r["portfolio"]
            bh = r["buy_and_hold_portfolio"]
            rows.append({
                "combo": combo_name,
                "alloc": alloc_name,
                "cagr":   pm["cagr"],
                "sharpe": pm["sharpe"],
                "sortino":pm["sortino"],
                "max_dd": pm["max_dd"],
                "calmar": pm["calmar"],
                "final":  pm["final"],
                "bh_cagr":   bh["cagr"],
                "bh_max_dd": bh["max_dd"],
                "bh_final":  bh["final"],
            })
            print(f"  ok  {tag:60s} CAGR={pm['cagr']:.2%}  DD={pm['max_dd']:.2%}  Calmar={pm['calmar']:.2f}")

    df = pd.DataFrame(rows).sort_values("calmar", ascending=False)
    for c in ["cagr","sharpe","sortino","max_dd","calmar","bh_cagr","bh_max_dd"]:
        df[c] = df[c].round(3)
    df.to_csv("strategy_lab/results/combo_matrix.csv", index=False)
    print("\n=== RANKED BY CALMAR ===")
    print(df.to_string(index=False))

if __name__ == "__main__":
    main()
