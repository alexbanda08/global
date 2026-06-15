"""
_ce25_ml_decode.py — ML decode of wallet 0xce25e214's entry structure.

Uses existing fills.parquet (May 15-16, 35k fills, legacy decode) +
canonical klines_1s + chainlink_rtds for the same window.

Stage 1: featurize BUY fills vs matched controls at canonical data.
Stage 2: HistGradientBoosting:
  A: fire vs control (when does he trade?)
  B: side Up vs Down (directional signal?)
  C: price < 0.50 vs price >= 0.50 (does he target cheap/expensive tokens?)

Usage: python strategy_lab/wallet_hunt/_ce25_ml_decode.py [--rebuild]
"""
from __future__ import annotations
import sys, time
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
from load import load_chainlink_rtds, load_klines  # noqa

W = ROOT / "strategy_lab" / "wallet_hunt" / "cache" / "0xce25e214"
FEAT_P = W / "ml_features.parquet"
RNG = np.random.default_rng(42)
RET_WINDOWS = [5, 15, 30, 60]

# ── helpers ──────────────────────────────────────────────────────────────
def asof(ts_arr, val_arr, t):
    i = np.searchsorted(ts_arr, t, "right") - 1
    return val_arr[i] if i >= 0 else np.nan


def build_features():
    t0 = time.time()

    # Load BUY fills (taker side only; May 15-16)
    fills = pd.read_parquet(W / "fills.parquet")
    T = fills[fills.side == "BUY"].copy()
    T["t_us"] = T.ts_s.astype(np.int64) * 1_000_000
    T["ss"] = T.slot_start_s.astype(np.int64)
    T["off"] = T.ts_s - T.slot_start_s
    T = T[(T.off >= 0) & (T.off <= 1800)]  # include 15m window = 900s, some slack
    print(f"BUY fills: {len(T)}, slugs: {T.slug.nunique()}", flush=True)

    # Load RTDS for BTC/ETH (the main coins)
    print("Loading RTDS...", flush=True)
    rtds = {}
    for coin in ["btc", "eth", "sol", "xrp"]:
        try:
            r = load_chainlink_rtds(asset=coin)
            # Filter to May 15-16 window
            r = r[(r.timestamp_us >= int(1.747e15)) & (r.timestamp_us <= int(1.748e15))]
            if len(r):
                rtds[coin] = (r.timestamp_us.to_numpy(np.int64),
                              r.price.to_numpy(np.float64))
                print(f"  RTDS {coin}: {len(r)} rows", flush=True)
        except Exception as e:
            print(f"  RTDS {coin} error: {e}")

    # Load 1s klines for BTC/ETH/SOL/XRP
    print("Loading klines...", flush=True)
    klines = {}
    for coin in ["btc", "eth", "sol", "xrp"]:
        try:
            k = load_klines(asset=coin, period_id="1SEC")
            k = k[(k.time_open_us >= int(1.747e15)) & (k.time_open_us <= int(1.748e15))]
            if len(k):
                k = k.sort_values("time_open_us")
                klines[coin] = (k.time_open_us.to_numpy(np.int64),
                                k.close.to_numpy(np.float64))
                print(f"  klines {coin}: {len(k)} rows", flush=True)
        except Exception as e:
            print(f"  klines {coin} error: {e}")

    # Extract coin from slug
    def slug_to_coin(slug):
        for c in ["btc", "eth", "sol", "xrp"]:
            if slug.startswith(c):
                return c
        return "btc"

    T["coin"] = T.slug.map(slug_to_coin)

    # Strike prices (RTDS asof slot_start)
    strikes = {}
    for row in T.drop_duplicates("slug")[["slug", "ss", "coin"]].itertuples(index=False):
        rt = rtds.get(row.coin)
        if rt is not None:
            strikes[row.slug] = asof(rt[0], rt[1], row.ss * 1_000_000)
        else:
            strikes[row.slug] = np.nan

    # Controls: per slug, same count as fills, uniform in window, >=2s from fills
    ctrl_rows = []
    for slug, g in T.groupby("slug"):
        ss = int(g.ss.iloc[0])
        tf_s = 900 if "15m" in slug else 300
        fill_ts = g.t_us.to_numpy()
        n = min(len(g), 20)
        cand = (ss + RNG.uniform(10, tf_s - 10, size=n * 5)) * 1e6
        ok = []
        for c in cand:
            if len(ok) >= n:
                break
            if np.min(np.abs(fill_ts - c)) > 2_000_000:
                ok.append(int(c))
        for c in ok:
            ctrl_rows.append((slug, ss, c, slug_to_coin(slug)))
    C = pd.DataFrame(ctrl_rows, columns=["slug", "ss", "t_us", "coin"])
    C["off"] = C.t_us / 1e6 - C.ss
    print(f"Controls: {len(C)}", flush=True)

    def featurize(df, is_fill):
        out = []
        for r in df.itertuples():
            t = int(r.t_us)
            coin = r.coin
            rt = rtds.get(coin)
            kl = klines.get(coin)
            strike = strikes.get(r.slug, np.nan)

            f = dict(slug=r.slug, ss=r.ss, t_us=t, off=r.off, is_fill=int(is_fill),
                     coin=coin)

            # RTDS features
            if rt is not None:
                px = asof(rt[0], rt[1], t)
                f["delta"] = (px - strike) if np.isfinite(strike) else np.nan
                f["rtds_px"] = px
                for w in RET_WINDOWS:
                    px_w = asof(rt[0], rt[1], t - w * 1_000_000)
                    f[f"rtds_ret{w}"] = (px / px_w - 1) if (np.isfinite(px) and np.isfinite(px_w) and px_w > 0) else np.nan
            else:
                f["delta"] = np.nan
                f["rtds_px"] = np.nan
                for w in RET_WINDOWS:
                    f[f"rtds_ret{w}"] = np.nan

            # Binance kline returns
            if kl is not None:
                kpx = asof(kl[0], kl[1], t)
                for w in RET_WINDOWS:
                    kpx_w = asof(kl[0], kl[1], t - w * 1_000_000)
                    f[f"bret{w}"] = (kpx / kpx_w - 1) if (np.isfinite(kpx) and np.isfinite(kpx_w) and kpx_w > 0) else np.nan
            else:
                for w in RET_WINDOWS:
                    f[f"bret{w}"] = np.nan

            # Fill-specific features
            if is_fill:
                f["side_up"] = int(getattr(r, "outcome", "Up") == "Up")
                f["price"] = getattr(r, "price", np.nan)
                f["book_ask"] = getattr(r, "book_ask", np.nan)
                f["book_bid"] = getattr(r, "book_bid", np.nan)
                f["book_spread"] = getattr(r, "book_spread", np.nan)
                f["is_cheap"] = int(f["price"] < 0.50)  # below fair
            else:
                f["side_up"] = np.nan
                f["price"] = np.nan
                f["book_ask"] = np.nan
                f["book_bid"] = np.nan
                f["book_spread"] = np.nan
                f["is_cheap"] = np.nan

            out.append(f)
        return pd.DataFrame(out)

    print("Featurizing fills...", flush=True)
    Ff = featurize(T, True)
    print(f"Fill features: {len(Ff)}  t={time.time()-t0:.0f}s", flush=True)
    print("Featurizing controls...", flush=True)
    Fc = featurize(C, False)
    print(f"Control features: {len(Fc)}  t={time.time()-t0:.0f}s", flush=True)

    F = pd.concat([Ff, Fc], ignore_index=True)
    F.to_parquet(FEAT_P, index=False)
    print(f"Saved {len(F)} rows -> {FEAT_P}  t={time.time()-t0:.0f}s")
    return F


def train(F):
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import roc_auc_score
    from sklearn.inspection import permutation_importance

    feats = (["off", "delta"]
             + [f"rtds_ret{w}" for w in RET_WINDOWS]
             + [f"bret{w}" for w in RET_WINDOWS])

    # Time split: train on first 60%, test on last 40% by ss (slot_start)
    cut = np.percentile(F.ss.dropna(), 60)

    def fit_report(df, ycol, label):
        df = df.dropna(subset=["off"])
        df = df[[c for c in feats + [ycol, "ss"] if c in df.columns]].dropna(subset=[ycol])
        tr = df[df.ss < cut]
        te = df[df.ss >= cut]
        if len(te) < 100 or tr[ycol].nunique() < 2:
            print(f"[{label}] insufficient data (te={len(te)})"); return
        m = HistGradientBoostingClassifier(max_iter=300, max_depth=5,
                                           learning_rate=0.08, random_state=42)
        m.fit(tr[[c for c in feats if c in tr.columns]], tr[ycol])
        f_use = [c for c in feats if c in te.columns]
        auc_tr = roc_auc_score(tr[ycol], m.predict_proba(tr[f_use])[:, 1])
        auc_te = roc_auc_score(te[ycol], m.predict_proba(te[f_use])[:, 1])
        print(f"\n[{label}]  n_tr={len(tr)}  n_te={len(te)}  AUC train={auc_tr:.3f} / TEST={auc_te:.3f}")
        pi = permutation_importance(m, te[f_use], te[ycol], n_repeats=5,
                                     random_state=42, scoring="roc_auc")
        order = np.argsort(-pi.importances_mean)
        for i in order[:6]:
            fname = f_use[i]
            print(f"    {fname:>14}: {pi.importances_mean[i]:+.4f}")
        # Decile readout on top feature
        top_f = f_use[order[0]]
        q = pd.qcut(te[top_f], 8, duplicates="drop")
        tab = te.groupby(q, observed=True)[ycol].mean()
        print(f"    -- {top_f} decile->P({ycol}):")
        print("       " + "  ".join(f"{iv.right:+.3g}:{v:.2f}" for iv, v in tab.items()))

    print("=" * 70)
    # A: fire vs control
    fit_report(F, "is_fill", "A: any-fire vs control")

    # B: side decode (Up vs Down)
    op = F[F.is_fill == 1].copy()
    op["side_up"] = op.side_up.fillna(0).astype(int)
    fit_report(op, "side_up", "B: side decode (Up vs Down)")

    # C: cheap (<0.50) vs expensive
    op2 = F[F.is_fill == 1].copy()
    op2["is_cheap"] = op2.is_cheap.fillna(0).astype(int)
    fit_report(op2, "is_cheap", "C: cheap token (<0.50) selection")


if __name__ == "__main__":
    if "--rebuild" in sys.argv or not FEAT_P.exists():
        F = build_features()
    else:
        F = pd.read_parquet(FEAT_P)
        print(f"Loaded cached features: {len(F)}")
    train(F)
