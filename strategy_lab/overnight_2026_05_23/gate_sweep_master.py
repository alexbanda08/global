"""Rule-based gate sweep on master_5m_panel.

Tests every combination of:
  - fire_offset_s in {60, 90, 120, 180, 240, 270}
  - dev_bps tier (none, ≥3, ≥5, ≥8, ≥12 bps)
  - 0-3 gates from the following pool, applied as AND
    {fair_edge_pos, cvd_agree_30s, cvd_agree_60s, macd_agree,
     m1v_pass, m5v_pass, m1f_pass, m5f_pass, f7_pass,
     cross_partial, cross_full, micro_imb_up, micro_imb_down,
     rvol_elevated, spread_tight}

Outputs the top-50 configs by `wr × sum_pnl × √n` score, per asset.
"""
from __future__ import annotations
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
PANEL = ROOT / "data" / "v4" / "canonical" / "_results" / "master_5m_panel.parquet"
OUT   = ROOT / "data" / "v4" / "canonical" / "_results" / "gate_sweep_master.csv"

MIN_N        = 80          # samples per config
WR_MIN       = 0.58        # require WR > 58 %
MAX_GATE_K   = 3           # max gates in AND


def build_gate_columns(d: pd.DataFrame) -> pd.DataFrame:
    """Derive boolean gate columns from the panel."""
    g = pd.DataFrame(index=d.index)
    # Direction
    g["dir_UP"]   = d["direction"] == "UP"
    g["dir_DOWN"] = d["direction"] == "DOWN"
    # FV
    g["fair_edge_pos"]    = d["fair_edge_bp"] >  0
    g["fair_edge_strong"] = d["fair_edge_bp"] >  500       # ≥5 % EV edge
    # CVD
    g["cvd_agree_30s"]    = d["cvd_agree_30s"].astype(bool)
    g["cvd_agree_60s"]    = d["cvd_agree_60s"].astype(bool)
    g["cvd_agree_120s"]   = d["cvd_agree_120s"].astype(bool)
    # MACD
    g["macd_agree"]       = d["macd_agree"].astype(bool)
    # Markov
    g["m1v_pass"] = d["m1v_pass"].astype(bool)
    g["m5v_pass"] = d["m5v_pass"].astype(bool)
    g["m1f_pass"] = d["m1f_pass"].astype(bool)
    g["m5f_pass"] = d["m5f_pass"].astype(bool)
    # F7
    g["f7_pass"]  = d["f7_pass"].astype(bool)
    # Cross-asset
    g["cross_partial"] = d["cross_partial_agree"].astype(bool)
    g["cross_full"]    = d["cross_full_agree"].astype(bool)
    # Microstructure
    g["micro_imb_up"]   = (d["imb5"] >  0.10).fillna(False) & g["dir_UP"]
    g["micro_imb_down"] = (d["imb5"] < -0.10).fillna(False) & g["dir_DOWN"]
    g["micro_dev_up"]   = (d["micro_minus_mid_bp"] >  20).fillna(False) & g["dir_UP"]
    g["micro_dev_down"] = (d["micro_minus_mid_bp"] < -20).fillna(False) & g["dir_DOWN"]
    g["spread_tight"]   = (d["spread_bp"] < 100).fillna(False)
    g["rvol_elevated"]  = (d["rvol_30_300"] > 1.2).fillna(False)
    g["rvol_high"]      = (d["rvol_60_900"] > 1.5).fillna(False)
    return g


GATE_POOL = [
    "fair_edge_pos", "fair_edge_strong",
    "cvd_agree_30s", "cvd_agree_60s", "cvd_agree_120s",
    "macd_agree",
    "m1v_pass", "m5v_pass", "m1f_pass", "m5f_pass",
    "f7_pass",
    "cross_partial", "cross_full",
    "micro_imb_up", "micro_imb_down",
    "micro_dev_up", "micro_dev_down",
    "spread_tight",
    "rvol_elevated", "rvol_high",
]

DEV_TIERS = [
    ("any",  lambda d: pd.Series(True, index=d.index)),
    ("≥3bp", lambda d: d["dev_bps"].abs() >= 3),
    ("≥5bp", lambda d: d["dev_bps"].abs() >= 5),
    ("≥8bp", lambda d: d["dev_bps"].abs() >= 8),
    ("≥12bp", lambda d: d["dev_bps"].abs() >= 12),
]

OFFSETS = [60, 90, 120, 180, 240, 270]


def score_config(d: pd.DataFrame, mask: pd.Series, key: str) -> dict:
    sub = d[mask]
    n = len(sub)
    if n < MIN_N: return None
    wr = float(sub["won"].mean())
    if wr < WR_MIN: return None
    sum_pnl = float(sub["pnl_legacy_usd"].sum())
    per_tr  = float(sub["pnl_legacy_usd"].mean())
    pnl = sub["pnl_legacy_usd"].to_numpy()
    sd = float(pnl.std(ddof=1)) if n > 1 else 0.0
    sharpe_pt = (per_tr / sd) if sd > 0 else 0.0
    loss = pnl[pnl < 0]
    sd_dn = float(loss.std(ddof=1)) if len(loss) > 1 else 0.0
    sortino_pt = (per_tr / sd_dn) if sd_dn > 0 else 0.0
    score = wr * sum_pnl * (n ** 0.5)
    return {
        "key": key, "n": n, "wr": round(wr, 4),
        "per_tr": round(per_tr, 3), "sum_pnl": round(sum_pnl, 2),
        "sharpe_pt": round(sharpe_pt, 3), "sortino_pt": round(sortino_pt, 3),
        "score": round(score, 1),
    }


def main():
    d = pd.read_parquet(PANEL)
    print(f"[load] {len(d):,} rows")
    g = build_gate_columns(d)
    # also ensure boolean column dtypes
    print(f"[gates] {len(GATE_POOL)} gates × {len(DEV_TIERS)} dev tiers × "
          f"{len(OFFSETS)} offsets × {sum(1 for k in range(MAX_GATE_K+1))} combo sizes")

    rows = []
    for asset in ["ALL"] + ["BTC", "ETH", "SOL"]:
        for off in [None] + OFFSETS:
            for dev_lbl, dev_fn in DEV_TIERS:
                base_mask = pd.Series(True, index=d.index)
                if asset != "ALL":
                    base_mask &= (d["asset"] == asset)
                if off is not None:
                    base_mask &= (d["fire_offset_s"] == off)
                base_mask &= dev_fn(d)
                # bootstrap: every combo size k in 0..MAX_GATE_K
                for k in range(MAX_GATE_K + 1):
                    if k == 0:
                        # no gate, just base
                        key = f"{asset}|{off or 'any'}|{dev_lbl}|0g"
                        row = score_config(d, base_mask, key)
                        if row is not None: rows.append(row)
                        continue
                    for combo in combinations(GATE_POOL, k):
                        gate_mask = base_mask.copy()
                        for gname in combo:
                            gate_mask &= g[gname]
                        if gate_mask.sum() < MIN_N: continue
                        key = (f"{asset}|{off or 'any'}|{dev_lbl}|"
                               f"{'+'.join(combo)}")
                        row = score_config(d, gate_mask, key)
                        if row is not None: rows.append(row)
        print(f"   {asset}: {len(rows):,} cumulative configs")

    out = pd.DataFrame(rows)
    out = out.sort_values("score", ascending=False).reset_index(drop=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index=False)
    print(f"\n[write] {len(out):,} configs → {OUT}")
    print(f"\nTop 30 by score:")
    pd.set_option("display.max_colwidth", 120)
    pd.set_option("display.width", 250)
    print(out.head(30).to_string(index=False))

    # Top per asset
    print(f"\nTop 5 per asset:")
    for a in ("ALL", "BTC", "ETH", "SOL"):
        sub = out[out["key"].str.startswith(f"{a}|")]
        if sub.empty: continue
        print(f"\n--- {a} ---")
        print(sub.head(5).to_string(index=False))


if __name__ == "__main__":
    main()
