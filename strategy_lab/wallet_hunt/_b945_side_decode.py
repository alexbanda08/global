"""b945 side decode — which SIDE does he buy, at open and per-fill, + net residual direction.
Uses cached ml_features.parquet (from _b945_ml_decode.py)."""
import numpy as np
import pandas as pd
from pathlib import Path

W = Path(r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\wallet_hunt\cache\0xb945945d")
F = pd.read_parquet(W / "ml_features.parquet")
fills = F[F.is_fill == 1].copy()
fills["dn_mid"] = (fills.dn_ask + fills.dn_bid) / 2
print(f"fills: {len(fills)}  legs: {fills.leg.value_counts().to_dict()}")

SIGNED = ["delta", "rtds_ret5", "rtds_ret15", "rtds_ret30", "rtds_ret60",
          "bret5", "bret15", "bret30", "bret60"]

def sign_table(df, label):
    print(f"\n--- {label} (n={len(df)}, base P(Up)={df.side_up.mean():.3f}) ---")
    print(f"{'feature':>12} {'P(Up|f>0)':>10} {'P(Up|f<0)':>10} {'acc(sign)':>10} {'n+':>7} {'n-':>7}")
    for c in SIGNED:
        d = df.dropna(subset=[c])
        pos, neg = d[d[c] > 0], d[d[c] < 0]
        if len(pos) < 30 or len(neg) < 30:
            continue
        acc = (pos.side_up.mean() * len(pos) + (1 - neg.side_up.mean()) * len(neg)) / (len(pos) + len(neg))
        print(f"{c:>12} {pos.side_up.mean():>10.3f} {neg.side_up.mean():>10.3f} {acc:>10.3f} {len(pos):>7} {len(neg):>7}")
    # cheaper-side rule: buys the side whose mid is LOWER?
    d = df.dropna(subset=["up_mid", "dn_mid"])
    buys_cheaper = ((d.side_up == 1) & (d.up_mid < d.dn_mid)) | ((d.side_up == 0) & (d.dn_mid < d.up_mid))
    print(f"  buys-CHEAPER-side rate: {buys_cheaper.mean():.3f} (n={len(d)})")
    # own-mid distribution of what he buys
    own_mid = np.where(d.side_up == 1, d.up_mid, d.dn_mid)
    print(f"  own-side mid at buy: p10 {np.percentile(own_mid,10):.2f} med {np.median(own_mid):.2f} p90 {np.percentile(own_mid,90):.2f}")

sign_table(fills[fills.leg == "open"], "LEG1 OPEN side")
sign_table(fills[fills.leg == "add"], "ADD side")
sign_table(fills[fills.leg.isin(["hedge", "rebal"])], "HEDGE/REBAL side")
sign_table(fills, "ALL fills side")

# GBT side decode at open with relaxed split
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.model_selection import cross_val_score
op = fills[fills.leg == "open"].dropna(subset=["up_mid"])
feats = SIGNED + ["up_mid", "imb_up", "imb_dn", "overround", "off", "oracle_gap"]
X, y = op[feats], op.side_up
if y.nunique() == 2 and len(op) > 200:
    m = HistGradientBoostingClassifier(max_iter=200, max_depth=4, random_state=7)
    cv = cross_val_score(m, X, y, cv=5, scoring="roc_auc")
    print(f"\nGBT OPEN-side 5-fold AUC: {cv.mean():.3f} +/- {cv.std():.3f} (n={len(op)})")

# per-slug NET residual direction: final q_up - q_dn sign vs early delta
T = pd.read_parquet(W / "fill_tape.parquet")
T = T[(T.side == "BUY") & T.slug.str.match(r"btc-updown-15m-\d+$")].copy()
inv = T.groupby(["slug", "outcome"]).shares.sum().unstack(fill_value=0)
inv["net_up"] = inv.get("Up", 0) - inv.get("Down", 0)
inv["resid_frac"] = (inv.net_up.abs() / (inv.get("Up", 0) + inv.get("Down", 0))).round(3)
print(f"\nNET residual: P(net long Up)={(inv.net_up>0).mean():.3f}  "
      f"resid_frac med {inv.resid_frac.median():.3f} p90 {inv.resid_frac.quantile(.9):.3f}")
# join residual sign to delta at off=120 (from features of that slug's earliest fills)
early = fills[fills.off < 180].groupby("slug").delta.mean()
j = inv.join(early.rename("delta_early")).dropna(subset=["delta_early"])
j = j[j.net_up != 0]
agree = ((j.net_up > 0) == (j.delta_early > 0)).mean()
print(f"residual-side vs early-delta agreement: {agree:.3f} (n={len(j)})")
# and vs LATE delta (off>700)
late = fills[fills.off > 700].groupby("slug").delta.mean()
j2 = inv.join(late.rename("delta_late")).dropna(subset=["delta_late"])
j2 = j2[j2.net_up != 0]
print(f"residual-side vs LATE-delta agreement: {((j2.net_up>0)==(j2.delta_late>0)).mean():.3f} (n={len(j2)})")
