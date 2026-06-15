"""
_b945_ml_decode.py — ML decode of wallet 0xb945945d's entry structure.

Stage 1: build supervised dataset — his 144k btc-15m fills (Apr 22+) + matched no-fire
controls, each joined to market state at that instant:
  RTDS (delta vs strike, short returns), Binance 1s returns, L25 top-of-book both tokens
  (asks/bids/sizes/overround), time-in-window, his inventory state (leg label).
Stage 2: HistGradientBoosting models, TIME-split (train early / test late):
  A: fire vs control (all fills)        — when does he trade at all
  B: leg1 (opening) fire vs control     — the unobservable entry trigger
  C: leg1 side Up vs Down               — the directional signal decode (the prize)
Outputs: cache/0xb945945d/ml_features.parquet + printed AUC/importance/cutpoints.

Usage: py -3 strategy_lab/wallet_hunt/_b945_ml_decode.py [--rebuild]
"""
from __future__ import annotations
import sys, time
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
from load import load_chainlink_rtds, load_klines_1s   # noqa: E402

W = ROOT / "strategy_lab" / "wallet_hunt" / "cache" / "0xb945945d"
L25 = ROOT / "data" / "v4" / "canonical" / "orderbook_l25" / "btc.parquet"
FEAT_P = W / "ml_features.parquet"
RNG = np.random.default_rng(7)
RET_WINDOWS = [5, 15, 30, 60]


def asof(ts_arr, val_arr, t):
    i = np.searchsorted(ts_arr, t, "right") - 1
    return val_arr[i] if i >= 0 else np.nan


def asof_idx(ts_arr, t):
    return np.searchsorted(ts_arr, t, "right") - 1


def load_tob(slug_set):
    cols = ["timestamp_us", "slug", "outcome", "ask_price_0", "ask_size_0",
            "bid_price_0", "bid_size_0"]
    f = pq.ParquetFile(L25)
    parts = []
    for i in range(f.num_row_groups):
        df = f.read_row_group(i, columns=cols).to_pandas()
        df = df[df.slug.isin(slug_set)]
        if len(df):
            parts.append(df)
    big = pd.concat(parts, ignore_index=True).sort_values("timestamp_us")
    out = {}
    for k, g in big.groupby(["slug", "outcome"], sort=False, observed=True):
        out[k] = (g.timestamp_us.to_numpy(np.int64),
                  g.ask_price_0.to_numpy(np.float64), g.ask_size_0.to_numpy(np.float64),
                  g.bid_price_0.to_numpy(np.float64), g.bid_size_0.to_numpy(np.float64))
    return out


def build_features():
    t0 = time.time()
    T = pd.read_parquet(W / "fill_tape.parquet")
    T = T[(T.side == "BUY") & T.slug.str.match(r"btc-updown-15m-\d+$")].copy()
    T["ss"] = T.slug.str.rsplit("-", n=1).str[1].astype(np.int64)
    T["t_us"] = pd.to_datetime(T.ts, utc=True).astype("int64") // 1000
    T["off"] = T.t_us / 1e6 - T.ss
    T = T[(T.off >= 0) & (T.off <= 900)]
    T = T[T.t_us >= int(pd.Timestamp("2026-04-22", tz="UTC").timestamp() * 1e6)]
    T = T.sort_values("t_us").reset_index(drop=True)
    print(f"fills in scope: {len(T)} across {T.slug.nunique()} slugs", flush=True)

    # inventory state before each fill -> leg label
    legs, q_own_l, q_opp_l = [], [], []
    inv = {}
    for r in T.itertuples():
        key = r.slug
        st = inv.setdefault(key, {"Up": 0.0, "Down": 0.0})
        q_own, q_opp = st[r.outcome], st["Down" if r.outcome == "Up" else "Up"]
        if q_own == 0 and q_opp == 0:
            legs.append("open")
        elif q_opp == 0:
            legs.append("add")
        elif q_own < q_opp:
            legs.append("hedge")
        else:
            legs.append("rebal")
        q_own_l.append(q_own); q_opp_l.append(q_opp)
        st[r.outcome] += r.shares
    T["leg"] = legs; T["q_own"] = q_own_l; T["q_opp"] = q_opp_l
    print(T.leg.value_counts().to_string(), flush=True)

    # market data
    rt = load_chainlink_rtds("BTC")
    rt_ts = rt.timestamp_us.to_numpy(np.int64)
    rt_px = rt.price_value.to_numpy(np.float64)
    k1 = load_klines_1s("BTC")
    tcol = "time_period_end_us" if "time_period_end_us" in k1.columns else (
        "end_us" if "end_us" in k1.columns else k1.columns[0])
    k1 = k1.sort_values(tcol)
    k_ts = k1[tcol].to_numpy(np.int64)
    k_px = k1.price_close.to_numpy(np.float64)
    print(f"rtds {len(rt_ts)} rows, klines_1s {len(k_ts)} rows  t={time.time()-t0:.0f}s",
          flush=True)
    slug_set = set(T.slug.unique())
    tob = load_tob(slug_set)
    print(f"L25 tob: {len(tob)} series  t={time.time()-t0:.0f}s", flush=True)

    # strike per slug = RTDS asof slot_start
    strikes = {}
    for slug, ss in T.drop_duplicates("slug")[["slug", "ss"]].itertuples(index=False):
        strikes[slug] = asof(rt_ts, rt_px, ss * 1_000_000)

    # controls: per slug, same count as fills (cap 30), uniform in [60,870], >=2s from fills
    ctrl_rows = []
    for slug, g in T.groupby("slug"):
        ss = int(g.ss.iloc[0])
        fill_ts = g.t_us.to_numpy()
        n = min(len(g), 30)
        cand = (ss + RNG.uniform(60, 870, size=n * 3)) * 1e6
        ok = []
        for c in cand:
            if np.min(np.abs(fill_ts - c)) > 2_000_000:
                ok.append(int(c))
            if len(ok) >= n:
                break
        for c in ok:
            ctrl_rows.append((slug, ss, c))
    C = pd.DataFrame(ctrl_rows, columns=["slug", "ss", "t_us"])
    C["off"] = C.t_us / 1e6 - C.ss
    print(f"controls: {len(C)}", flush=True)

    def featurize(df, is_fill):
        out = []
        for r in df.itertuples():
            t = int(r.t_us)
            strike = strikes.get(r.slug, np.nan)
            px = asof(rt_ts, rt_px, t)
            f = dict(slug=r.slug, ss=r.ss, t_us=t, off=r.off, is_fill=int(is_fill))
            f["delta"] = px - strike if np.isfinite(px) and np.isfinite(strike) else np.nan
            i0 = asof_idx(rt_ts, t)
            for wsec in RET_WINDOWS:
                p_old = asof(rt_ts, rt_px, t - wsec * 1_000_000)
                f[f"rtds_ret{wsec}"] = (px - p_old) if np.isfinite(p_old) else np.nan
            for wsec in RET_WINDOWS:
                pk = asof(k_ts, k_px, t)
                pk_old = asof(k_ts, k_px, t - wsec * 1_000_000)
                f[f"bret{wsec}"] = (pk - pk_old) if (np.isfinite(pk) and np.isfinite(pk_old)) else np.nan
            for side, tag in (("Up", "up"), ("Down", "dn")):
                rec = tob.get((r.slug, side))
                if rec is None:
                    f[f"{tag}_ask"] = f[f"{tag}_bid"] = f[f"{tag}_asz"] = f[f"{tag}_bsz"] = np.nan
                    continue
                ts_, a_, asz_, b_, bsz_ = rec
                j = asof_idx(ts_, t)
                if j < 0 or (t - ts_[j]) > 120_000_000:
                    f[f"{tag}_ask"] = f[f"{tag}_bid"] = f[f"{tag}_asz"] = f[f"{tag}_bsz"] = np.nan
                else:
                    f[f"{tag}_ask"] = a_[j]; f[f"{tag}_bid"] = b_[j]
                    f[f"{tag}_asz"] = asz_[j]; f[f"{tag}_bsz"] = bsz_[j]
            if is_fill:
                f["leg"] = r.leg; f["side_up"] = int(r.outcome == "Up")
                f["price"] = r.price; f["usd"] = r.usd
                f["q_own"] = r.q_own; f["q_opp"] = r.q_opp
            out.append(f)
        return pd.DataFrame(out)

    Ff = featurize(T, True)
    print(f"fill features done t={time.time()-t0:.0f}s", flush=True)
    Fc = featurize(C, False)
    print(f"ctrl features done t={time.time()-t0:.0f}s", flush=True)
    F = pd.concat([Ff, Fc], ignore_index=True)
    # derived
    F["overround"] = F.up_ask + F.dn_ask
    F["up_mid"] = (F.up_ask + F.up_bid) / 2
    F["spread_up"] = F.up_ask - F.up_bid
    F["spread_dn"] = F.dn_ask - F.dn_bid
    F["imb_up"] = (F.up_bsz - F.up_asz) / (F.up_bsz + F.up_asz)
    F["imb_dn"] = (F.dn_bsz - F.dn_asz) / (F.dn_bsz + F.dn_asz)
    # oracle-vs-market gap: oracle says Up iff delta>0; market prob = up_mid
    F["oracle_gap"] = np.where(F.delta > 0, 1.0, 0.0) - F.up_mid
    F.to_parquet(FEAT_P, index=False)
    print(f"saved {len(F)} rows -> {FEAT_P}  t={time.time()-t0:.0f}s", flush=True)
    return F


def train(F):
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import roc_auc_score
    from sklearn.inspection import permutation_importance

    feats_common = (["off", "delta", "overround", "up_mid", "spread_up", "spread_dn",
                     "imb_up", "imb_dn", "oracle_gap"]
                    + [f"rtds_ret{w}" for w in RET_WINDOWS]
                    + [f"bret{w}" for w in RET_WINDOWS])
    cut = F.ss.quantile(0.8)

    def fit_report(df, ycol, label, feats):
        df = df.dropna(subset=["up_mid"])
        tr, te = df[df.ss < cut], df[df.ss >= cut]
        if len(te) < 200 or tr[ycol].nunique() < 2:
            print(f"[{label}] insufficient data"); return None
        m = HistGradientBoostingClassifier(max_iter=300, max_depth=6,
                                           learning_rate=0.08, random_state=7)
        m.fit(tr[feats], tr[ycol])
        auc_tr = roc_auc_score(tr[ycol], m.predict_proba(tr[feats])[:, 1])
        auc_te = roc_auc_score(te[ycol], m.predict_proba(te[feats])[:, 1])
        print(f"\n[{label}] n_tr={len(tr)} n_te={len(te)}  AUC train {auc_tr:.3f} / TEST {auc_te:.3f}")
        pi = permutation_importance(m, te[feats], te[ycol], n_repeats=5, random_state=7,
                                    scoring="roc_auc")
        order = np.argsort(-pi.importances_mean)
        for i in order[:8]:
            print(f"    {feats[i]:>12}: {pi.importances_mean[i]:+.4f}")
        # cutpoint readout on top-3: decile means of y
        for i in order[:3]:
            fcol = feats[i]
            q = pd.qcut(te[fcol], 10, duplicates="drop")
            tab = te.groupby(q, observed=True)[ycol].mean()
            print(f"    -- {fcol} decile->P({ycol}):")
            print("       " + "  ".join(f"{iv.right:+.3g}:{v:.2f}" for iv, v in tab.items()))
        return m

    print("=" * 80)
    fit_report(F, "is_fill", "A: any-fire vs control", feats_common)

    leg1 = F[(F.is_fill == 0) | (F.leg == "open")]
    fit_report(leg1, "is_fill", "B: LEG1 (opening) fire vs control", feats_common)

    op = F[(F.is_fill == 1) & (F.leg == "open")].copy()
    fit_report(op, "side_up", "C: LEG1 SIDE decode (Up vs Down)", feats_common)

    hedge = F[(F.is_fill == 0) | (F.leg == "hedge")]
    fit_report(hedge, "is_fill", "D: HEDGE fire vs control", feats_common)


if __name__ == "__main__":
    if "--rebuild" in sys.argv or not FEAT_P.exists():
        F = build_features()
    else:
        F = pd.read_parquet(FEAT_P)
        print(f"loaded cached features: {len(F)}")
    train(F)
