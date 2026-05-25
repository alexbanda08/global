"""Contra-gate test for momo_v1 BTC 5m (production loser, sum=-$1681).

Agent indicator-overlay flagged this sleeve as contrarian — agree-style gates
made it worse. Test: fire only when indicators DISAGREE with the production
direction (i.e., momo_v1 fires UP but binance 1s says DOWN ⇒ fade momo's UP).
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import stats as sstats

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
P = ROOT / "data" / "v4" / "canonical" / "_results" / "prod_fills_with_indicators.parquet"


def score(sub, label):
    if len(sub) < 30: return None
    pnl = sub["pnl_legacy_usd"].to_numpy()
    n = len(pnl); wr = float(sub["won"].mean()); s = float(pnl.sum()); pt = s/n
    sd = pnl.std(ddof=1) if n>1 else 0
    sharpe_pt = pt/sd if sd>0 else 0
    days = max(1.0, (sub.fire_us.max() - sub.fire_us.min()) / 1e6 / 86400)
    # walk-forward
    st = sub.sort_values("fire_us").reset_index(drop=True)
    cut = int(0.7*len(st)); tr,te = st.iloc[:cut], st.iloc[cut:]
    ts = float(tr["pnl_legacy_usd"].sum()); es = float(te["pnl_legacy_usd"].sum())
    wf = es/ts if ts!=0 else float("nan")
    return {
        "label": label, "n": n,
        "WR_pct": round(wr*100, 2),
        "per_tr": round(pt, 3),
        "sum_pnl": round(s, 2),
        "per_day": round(s/days, 2),
        "sharpe_pt": round(sharpe_pt, 3),
        "train_WR": round(float(tr["won"].mean())*100, 2),
        "test_WR": round(float(te["won"].mean())*100, 2),
        "train_sum": round(ts, 2),
        "test_sum": round(es, 2),
        "wf_ret": round(wf, 2) if np.isfinite(wf) else None,
    }


def main():
    d = pd.read_parquet(P)
    print(f"loaded prod panel: {len(d):,} rows; cols sample: {d.columns.tolist()[:20]}")
    # focus on losing sleeves
    LOSERS = [
        ("momo_v1", "BTC", "5m"),
        ("momo_v1", "ETH", "5m"),
        ("momo_v1", "ETH", "15m"),
        ("momo_v1", "SOL", "15m"),
        ("momo_v2", "BTC", "5m"),
        ("momo_v2", "ETH", "5m"),
        ("momo_v2", "SOL", "5m"),
        ("momo_v2", "SOL", "15m"),
        ("sniper", "BTC", "5m"),
        ("sniper", "ETH", "5m"),
        ("sniper", "ETH", "15m"),
        ("sniper", "SOL", "15m"),
    ]
    rows = []
    for strat, asset, tf in LOSERS:
        sub = d[(d.strategy == strat) & (d.asset == asset) & (d.tf == tf)].copy()
        if len(sub) < 30: continue
        base = score(sub, f"{strat}_{asset}_{tf}_BASE")
        if base: rows.append(base)
        # disagree gates — fire only when 1s indicator DISAGREES with prod signal
        cvd_d = ~sub["cvd_agree_30s"].astype(bool)
        macd_d = ~sub["macd_agree"].astype(bool)
        fair_d = (sub["fair_edge_bp"].fillna(0) < 0)
        fair_d500 = (sub["fair_edge_bp"].fillna(0) < -500)
        for label, mask in [
            ("cvd_DISagree_30s",       cvd_d),
            ("macd_DISagree",          macd_d),
            ("fair_edge_NEG",          fair_d),
            ("fair_edge_NEG500",       fair_d500),
            ("cvd_dis_AND_macd_dis",   cvd_d & macd_d),
            ("cvd_dis_AND_fair_neg",   cvd_d & fair_d),
            ("ALL_three_disagree",     cvd_d & macd_d & fair_d),
            # flip — fire UP when prod fires DOWN, etc
            ("FLIP_DIRECTION",         pd.Series(True, index=sub.index)),
        ]:
            ssub = sub[mask].copy()
            if label == "FLIP_DIRECTION":
                # flip the won label: production lost = we'd have won; production won = we'd have lost
                ssub["won"] = ~ssub["won"].astype(bool)
                # flip pnl sign-ish: this isn't exactly right since fees apply asymmetrically;
                # better: simulate the opposite outcome. For losing fires, the opposite would have won 1.0
                # but the fee model is 2%-on-profit on winners only. So pnl_flipped = approximate.
                # For now treat as: pnl_flipped = -pnl + 2 * fee_adjustment (rough — better to recompute)
                # Cleaner approximation: if production lost -$25, flipped won (1-vwap)*shares*0.98
                # If production won $X (= (1-vwap)*shares*0.98), flipped lost -shares*vwap = -$(25+x/0.98 - x)
                # We need vwap + shares — assume vwap col exists
                # Reconstruct PnL for flipped direction using entry_vwap + shares
                vw_col = "entry_vwap" if "entry_vwap" in ssub.columns else "vwap"
                sh_col = "shares" if "shares" in ssub.columns else None
                if vw_col in ssub.columns and sh_col is not None:
                    won_flip = ~sub.loc[ssub.index, "won"].astype(bool)
                    # Note: in the flipped scenario we buy the OPPOSITE outcome.
                    # The opposite outcome's vwap = 1 - vwap (approx, ignoring spread)
                    # at the same notional $25.
                    vwap_flip = 1.0 - ssub[vw_col].astype(float)
                    shares_flip = 25.0 / vwap_flip
                    pnl_flip = np.where(won_flip,
                                         (1 - vwap_flip) * shares_flip * 0.98,
                                         -vwap_flip * shares_flip)
                    ssub["pnl_legacy_usd"] = pnl_flip
            row = score(ssub, f"{strat}_{asset}_{tf}_{label}")
            if row: rows.append(row)
    out = pd.DataFrame(rows)
    out.to_csv(ROOT / "data" / "v4" / "canonical" / "_results" / "contra_gates_losers.csv", index=False)
    pd.set_option("display.max_columns", None); pd.set_option("display.width", 240)
    # show only configs where the modified PnL >= base + some buffer
    print()
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
