"""V28 — validate the winning portfolios with proper equity curves
(yearly-rebalanced convention applied on real daily equity)."""
from __future__ import annotations
import pickle, json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
RES  = ROOT / "results"
OUT  = RES / "v28"
OUT.mkdir(parents=True, exist_ok=True)

def load_eq(path, key):
    d = pickle.load(open(path, "rb"))[key]
    idx = pd.to_datetime(d["eq_index"], utc=True)
    vals = np.asarray(d["eq_values"], dtype=float)
    return pd.Series(vals, index=idx).dropna()

# The three candidate portfolios
PORTS = {
    "P1_2coin_SOL_SUI": [
        ("v23/v23_results_with_oos.pkl", "SUIUSDT", "V23 SUI BBBreak 4h"),
        ("v23/v23_results_with_oos.pkl", "SOLUSDT", "V23 SOL BBBreak 4h"),
    ],
    "P2_3coin_SOL_SUI_ETHdonch": [
        ("v23/v23_results_with_oos.pkl", "SUIUSDT", "V23 SUI BBBreak 4h"),
        ("v23/v23_results_with_oos.pkl", "SOLUSDT", "V23 SOL BBBreak 4h"),
        ("v27/v27_swing_results.pkl", "ETHUSDT_HTF_DONCHIAN", "V27 ETH Donchian 4h"),
    ],
    "P3_3coin_SOL_SUI_TONliq": [
        ("v23/v23_results_with_oos.pkl", "SUIUSDT", "V23 SUI BBBreak 4h"),
        ("v23/v23_results_with_oos.pkl", "SOLUSDT", "V23 SOL BBBreak 4h"),
        ("v26/v26_priceaction_results.pkl", "TONUSDT_LIQ_SWEEP", "V26 TON LiqSweep 1h"),
    ],
    "P4_4coin_SOL_SUI_TON_AVAX": [
        ("v23/v23_results_with_oos.pkl", "SUIUSDT", "V23 SUI BBBreak 4h"),
        ("v23/v23_results_with_oos.pkl", "SOLUSDT", "V23 SOL BBBreak 4h"),
        ("v26/v26_priceaction_results.pkl", "TONUSDT_LIQ_SWEEP", "V26 TON LiqSweep 1h"),
        ("v23/v23_results_with_oos.pkl", "AVAXUSDT", "V23 AVAX RangeKalman 4h"),
    ],
}

def blend(members):
    """Build a YEARLY-REBALANCED-EQUAL-WEIGHT portfolio equity curve.
    At Jan 1 each year, reallocate capital equally across member strategies
    that are live. Within the year each sleeve compounds independently."""
    eqs = {}
    for path, key, name in members:
        eqs[name] = load_eq(RES / path, key).resample("1D").last().ffill().dropna()
    all_idx = sorted(set().union(*[s.index for s in eqs.values()]))
    cap0 = 1.0
    port_series = pd.Series(dtype=float)
    year_metrics = {}

    # Iterate year by year
    start = pd.Timestamp("2020-01-01", tz="UTC")
    end   = pd.Timestamp("2026-01-01", tz="UTC")
    year_ranges = [(pd.Timestamp(f"{y}-01-01", tz="UTC"),
                    pd.Timestamp(f"{y+1}-01-01", tz="UTC")) for y in range(2020, 2026)]

    cap = cap0
    for (ys, ye) in year_ranges:
        # For each strat, find its equity at ys and ye (clamp to data range)
        live_members = []
        for name, s in eqs.items():
            yslc = s[(s.index >= ys) & (s.index < ye)]
            if len(yslc) < 5: continue
            start_v = yslc.iloc[0]; end_v = yslc.iloc[-1]
            yret = end_v / start_v - 1
            live_members.append((name, start_v, end_v, yret, yslc))

        if not live_members:
            # capital idle
            year_metrics[ys.year] = {"port_cagr": 0.0, "members": {}}
            continue

        # Build a daily portfolio equity series within the year
        weight = 1.0 / len(live_members)
        eq_port_year = None
        mems_this_year = {}
        for name, sv, ev, yr, yslc in live_members:
            norm_s = yslc / sv  # starts at 1.0
            sleeve_eq = cap * weight * norm_s
            eq_port_year = sleeve_eq if eq_port_year is None else eq_port_year.add(sleeve_eq, fill_value=0.0)
            mems_this_year[name] = round(yr * 100, 1)
        port_series = pd.concat([port_series, eq_port_year])
        cap_end = eq_port_year.iloc[-1]
        year_ret = cap_end / cap - 1
        year_metrics[ys.year] = {"port_cagr": round(year_ret*100,1),
                                  "members": mems_this_year,
                                  "n_live": len(live_members)}
        cap = cap_end

    # Overall Sharpe & DD from daily port_series
    port_series = port_series.sort_index()
    rets = port_series.pct_change().dropna()
    if len(rets) > 10 and rets.std() > 0:
        sharpe = rets.mean() / rets.std() * np.sqrt(365.25)
    else:
        sharpe = 0
    dd = float((port_series / port_series.cummax() - 1).min())
    yrs_total = (port_series.index[-1] - port_series.index[0]).total_seconds() / (365.25*86400)
    total_cagr = (port_series.iloc[-1] / port_series.iloc[0]) ** (1/max(yrs_total,1e-6)) - 1
    return {
        "year_metrics": year_metrics,
        "overall": {
            "cagr": round(total_cagr*100,1),
            "sharpe": round(sharpe,2),
            "dd":     round(dd*100,1),
            "years":  round(yrs_total,2),
        },
        "eq": port_series,
    }

summaries = {}
for pname, members in PORTS.items():
    r = blend(members)
    summaries[pname] = r
    r["eq"].to_csv(OUT / f"{pname}_equity.csv")
    print("="*88)
    print(f"Portfolio: {pname}")
    for path, key, name in members:
        print(f"  - {name}")
    print(f"  Overall: CAGR {r['overall']['cagr']:+.1f}%  "
          f"Sharpe {r['overall']['sharpe']:+.2f}  "
          f"DD {r['overall']['dd']:+.1f}%  "
          f"({r['overall']['years']} yr)")
    print(f"  Per-year portfolio CAGR:")
    for y, m in r["year_metrics"].items():
        print(f"    {y}: {m['port_cagr']:+7.1f}%   (members: {m['members']})")

# Save summary JSON
sane_summaries = {k: {kk: vv for kk, vv in v.items() if kk != "eq"} for k, v in summaries.items()}
json.dump(sane_summaries, open(OUT / "winner_summary.json", "w"), indent=2, default=str)
print("\nSaved:", OUT / "winner_summary.json")
