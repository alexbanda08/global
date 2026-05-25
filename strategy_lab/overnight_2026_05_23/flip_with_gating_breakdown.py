"""Refined FLIP_DIRECTION analysis.

The headline FLIP result (fade-all-production-momo-on-F7-off) is too strong
without HOD/Markov gate context. Production currently deploys ONLY the gated
subset (HOD top-8 + Markov pass) as the 11 sleeves earning ~$249/day.

This script splits F7-off fires by whether they would pass the HOD/Markov
filters and tests FLIP on the un-gated subset (i.e. the fires production
already drops).

Hypothesis: production keeps the WINNERS via HOD/Markov gates; the fires that
fail those gates are systematically LOSERS that should be FADED, not silently
discarded.
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
PANEL = ROOT / "data" / "v4" / "canonical" / "_results" / "prod_fills_with_indicators.parquet"

# HoD top-8 (per CLAUDE.md / prior reports)
HOD_TOP8 = {
    ("sniper",  "sol_5m"):  [0, 1, 2, 4, 8, 15, 19, 23],
    ("sniper",  "eth_15m"): [0, 6, 7, 9, 13, 14, 19, 22],
    ("momo_v1", "btc_15m"): [0, 1, 3, 5, 9, 14, 16, 20],
    ("sniper",  "btc_15m"): [0, 3, 10, 11, 12, 13, 14, 15],
    ("sniper",  "btc_5m"):  [0, 1, 3, 5, 12, 15, 19, 21],
    ("momo_v2", "btc_5m"):  [0, 2, 5, 6, 10, 12, 21, 23],
    ("momo_v2", "btc_15m"): [1, 11, 12, 16, 18, 20, 21, 22],
    ("momo_v2", "sol_5m"):  [4, 5, 6, 8, 10, 12, 14, 17],
    ("momo_v2", "eth_15m"): [0, 5, 8, 12, 16, 17, 20, 22],
    ("momo_v2", "sol_15m"): [1, 2, 5, 12, 13, 16, 17, 21],
    ("sniper",  "eth_5m"):  [0, 2, 11, 13, 14, 17, 20, 21],
}


def flip_pnl(sub):
    """Pnl if we'd fired the OPPOSITE direction at the same vwap-on-the-other-side."""
    vw = sub["entry_vwap"].astype(float)
    vw_flip = (1.0 - vw).clip(0.01, 0.99)
    sh_flip = 25.0 / vw_flip
    won_flip = ~sub["won"].astype(bool)
    pnl = np.where(won_flip,
                    (1 - vw_flip) * sh_flip * 0.98,
                    -vw_flip * sh_flip)
    return pnl


def score(sub, label, use_flip=False):
    if len(sub) < 30: return None
    pnl = flip_pnl(sub) if use_flip else sub["pnl_legacy_usd"].to_numpy()
    n = len(pnl); s = float(pnl.sum()); pt = s/n
    won = ~sub["won"].astype(bool) if use_flip else sub["won"].astype(bool)
    wr = float(won.mean())
    days = max(1.0, (sub["fire_us"].max() - sub["fire_us"].min())/1e6/86400)
    return {
        "label": label, "n": n, "days": round(days,1),
        "WR_pct": round(wr*100, 2),
        "per_tr": round(pt, 3),
        "sum_pnl": round(s, 2),
        "per_day": round(s/days, 2),
    }


def main():
    d = pd.read_parquet(PANEL)
    d["hour"] = pd.to_datetime(d["fire_us"], unit="us", utc=True).dt.hour
    d["cell_key"] = d["asset"].str.lower() + "_" + d["tf"]
    print(f"loaded prod panel: {len(d):,} rows")

    # Map markov column names
    markov_cols = [c for c in d.columns if "markov" in c.lower()]
    print(f"markov cols: {markov_cols}")
    # Use m5v_pass if present (built fresh by the agent)
    if "m5v_pass" in d.columns:
        m5v = d["m5v_pass"].astype(bool)
    else:
        m5v = pd.Series(False, index=d.index)
    if "m1v_pass" in d.columns:
        m1v = d["m1v_pass"].astype(bool)
    else:
        m1v = pd.Series(False, index=d.index)

    rows = []
    for (strat, cell), hod in HOD_TOP8.items():
        asset, tf = cell.upper().split("_")[0], cell.split("_")[1]
        sub = d[(d["strategy"] == strat) & (d["asset"] == asset) & (d["tf"] == tf)].copy()
        if len(sub) < 30: continue
        hod_pass = sub["hour"].isin(set(hod))
        # gated = passes HoD AND Markov m5v (proxy for current production sleeve filter)
        gated = hod_pass & m5v[sub.index]
        un_gated = ~gated

        gated_sub = sub[gated]
        un_gated_sub = sub[un_gated]

        # baseline: ALL fires
        rows.append(score(sub, f"{strat}_{asset}_{tf}_ALL_base"))
        # gated only (production-equivalent)
        rows.append(score(gated_sub, f"{strat}_{asset}_{tf}_GATED_base"))
        # un-gated only (production drops these)
        rows.append(score(un_gated_sub, f"{strat}_{asset}_{tf}_UNGATED_base"))
        # FLIP un-gated (fade the dropped fires)
        rows.append(score(un_gated_sub, f"{strat}_{asset}_{tf}_UNGATED_FLIP", use_flip=True))
        # FLIP all
        rows.append(score(sub, f"{strat}_{asset}_{tf}_ALL_FLIP", use_flip=True))
        # FLIP gated (sanity — should be NEGATIVE if gated wins)
        rows.append(score(gated_sub, f"{strat}_{asset}_{tf}_GATED_FLIP", use_flip=True))

    out = pd.DataFrame([r for r in rows if r])
    out.to_csv(ROOT / "data" / "v4" / "canonical" / "_results" / "flip_with_gating_breakdown.csv", index=False)
    pd.set_option("display.max_columns", None); pd.set_option("display.width", 240)
    pd.set_option("display.max_colwidth", 60)
    print()
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
