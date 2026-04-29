"""
V12 — 1h strategy. Two variants:

  V12A  "FadePrevHour"  rule-based
        LONG when prev-bar return < -X% AND regime_bull AND wick pattern
        Takes advantage of strongest IC we have (ret_1 at 1h: -0.07)

  V12B  "LightGBM triple-barrier"
        Same ML pipeline as V11 but 1h bars, longer horizon, more history

Both tested on BTC/ETH/SOL, walk-forward IS/OOS cut at 2024-07-01.
Fees Hyperliquid tier (0.015%/side, 3bps slip).
"""
from __future__ import annotations
import sys, time
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
FEAT = ROOT/"strategy_lab"/"features"
OUT  = ROOT/"strategy_lab"/"results"

FEE = 0.00015; SLIP = 0.0003; INIT = 10_000.0
HORIZON = 8     # 8h max hold


# ============================================================
#  V12A — rule-based fade
# ============================================================
def simulate(df, direction=1, tp_atr=1.0, sl_atr=1.0, max_hold=HORIZON,
             size_frac=0.25, entry_mask=None):
    op, hi, lo, cl = df["open"].values, df["high"].values, df["low"].values, df["close"].values
    at = df["atr_14"].values
    sig = entry_mask.values.astype(bool)
    N = len(df)
    cash = INIT
    eq = np.empty(N); eq[0] = cash
    pos=0; entry_p=sl=tp=0.0; size=0.0; entry_idx=0; last_exit=-9999
    trades=[]
    for i in range(1, N-1):
        if pos != 0:
            held = i - entry_idx
            hit_sl = (lo[i] <= sl) if pos==1 else (hi[i] >= sl)
            hit_tp = (hi[i] >= tp) if pos==1 else (lo[i] <= tp)
            exited = False
            if hit_sl:
                ep = sl*(1 - SLIP*pos); ret=(ep-entry_p)*pos/entry_p - 2*FEE
                cash += size*((ep-entry_p)*pos) - size*(entry_p+ep)*FEE
                trades.append({"ret":ret,"reason":"SL","side":pos,"bars":held}); exited=True
            elif hit_tp:
                ep = tp*(1 - SLIP*pos); ret=(ep-entry_p)*pos/entry_p - 2*FEE
                cash += size*((ep-entry_p)*pos) - size*(entry_p+ep)*FEE
                trades.append({"ret":ret,"reason":"TP","side":pos,"bars":held}); exited=True
            elif held >= max_hold:
                ep = cl[i]; ret=(ep-entry_p)*pos/entry_p - 2*FEE
                cash += size*((ep-entry_p)*pos) - size*(entry_p+ep)*FEE
                trades.append({"ret":ret,"reason":"TIME","side":pos,"bars":held}); exited=True
            if exited:
                pos=0; last_exit=i; eq[i]=cash; continue
        if pos==0 and (i-last_exit)>2 and sig[i]:
            ep = op[i+1]*(1 + SLIP*direction)
            s = ep - sl_atr*at[i]*direction
            t = ep + tp_atr*at[i]*direction
            if np.isfinite(s) and np.isfinite(t):
                size = (cash*size_frac)/ep
                pos=direction; entry_p=ep; sl=s; tp=t; entry_idx=i+1
        if pos==0: eq[i]=cash
        else:
            unreal = size*(cl[i]-entry_p)*pos - size*entry_p*FEE
            eq[i] = cash + unreal
    eq[-1] = eq[-2]
    return trades, pd.Series(eq, index=df.index)


def report(label, eq, trades):
    if len(trades) < 5: return {"label":label,"n":len(trades),"final":float(eq.iloc[-1]),
                                 "cagr":0,"sharpe":0,"dd":0,"win":0,"pf":0}
    rets = eq.pct_change().dropna()
    dt = rets.index.to_series().diff().median()
    bpy = pd.Timedelta(days=365.25)/dt if dt else 1
    sh = rets.mean()/rets.std()*np.sqrt(bpy) if rets.std()>0 else 0
    yrs = (eq.index[-1]-eq.index[0]).total_seconds()/(365.25*86400)
    cagr = (eq.iloc[-1]/eq.iloc[0])**(1/max(yrs,1e-6))-1
    dd = float((eq/eq.cummax()-1).min())
    pnl = np.array([t["ret"] for t in trades])
    pf = pnl[pnl>0].sum()/abs(pnl[pnl<0].sum()) if (pnl<0).any() else 0
    return dict(label=label, n=len(trades), final=float(eq.iloc[-1]),
                cagr=round(cagr,4), sharpe=round(sh,3), dd=round(dd,4),
                win=round((pnl>0).mean(),3), pf=round(pf,3))


def v12a_signal(df, ret1_thr=-0.008, ret4_thr=-0.01):
    """FadePrevHour — LONG after a drop, bull regime."""
    bull = df["regime_bull"] == 1
    drop = df["ret_1"] < ret1_thr
    confirm = df["ret_4"] < ret4_thr
    return bull & drop & confirm & (~(bull & drop & confirm).shift(1).fillna(False))


def run_v12a():
    print("=== V12A FadePrevHour ===")
    rows=[]
    for sym in ["BTCUSDT","ETHUSDT","SOLUSDT"]:
        df = pd.read_parquet(FEAT/f"{sym}_1h_features.parquet").dropna(subset=["ret_1","ret_4","atr_14","regime_bull"])
        # Sweep threshold pairs
        for r1,r4 in [(-0.005,-0.008),(-0.008,-0.01),(-0.01,-0.015),(-0.015,-0.02)]:
            sig = v12a_signal(df, r1, r4)
            tr, eq = simulate(df, 1, tp_atr=1.0, sl_atr=1.0, entry_mask=sig)
            r = report(f"{sym}_r1{r1}_r4{r4}", eq, tr)
            rows.append(r)
            # Walk-forward OOS from 2024-07
            cut = pd.Timestamp("2024-07-01", tz="UTC")
            tr_oos, eq_oos = simulate(df[df.index>=cut], 1, entry_mask=sig[df.index>=cut])
            r_o = report(f"{sym}_r1{r1}_r4{r4}_OOS", eq_oos, tr_oos)
            rows.append(r_o)
            print(f"  {sym} r1<{r1} r4<{r4}  FULL n={r['n']:4d} Sh={r['sharpe']:5.2f} CAGR={r['cagr']*100:+6.1f}% Win={r['win']*100:4.1f} PF={r['pf']:.2f} | OOS n={r_o['n']:4d} Sh={r_o['sharpe']:5.2f} CAGR={r_o['cagr']*100:+6.1f}%")
    pd.DataFrame(rows).to_csv(OUT/"V12A_results.csv", index=False)


# ============================================================
#  V12B — LightGBM on 1h
# ============================================================
def v12b_ml():
    print("\n=== V12B ML (LightGBM triple-barrier, 1h) ===")
    import lightgbm as lgb
    from sklearn.metrics import roc_auc_score

    FCOLS = ["ret_1","ret_4","ret_12","atr_14","realized_vol_24",
             "wick_up_frac","wick_dn_frac","sum_open_interest_value",
             "count_toptrader_long_short_ratio","sum_toptrader_long_short_ratio",
             "count_long_short_ratio","sum_taker_long_short_vol_ratio",
             "oi_pct_chg_4","oi_pct_chg_24","taker_ratio_z_7d","top_trader_ls_z_7d",
             "funding_rate","funding_rate_z_30d","premium_1h","premium_z_30d",
             "liq_count","liq_notional_usd","liq_notional_z_7d","regime_bull"]

    def tb_labels(d, tp=1.0, sl=1.0, h=HORIZON):
        entry = d["open"].shift(-1).values
        at = d["atr_14"].values
        hi, lo = d["high"].values, d["low"].values
        n=len(d); lab=np.zeros(n, dtype=np.int8)
        for i in range(n-h-1):
            e,a = entry[i], at[i]
            if not np.isfinite(e) or not np.isfinite(a) or a<=0: continue
            T=e+tp*a; S=e-sl*a
            for k in range(i+1, i+1+h):
                if k>=n: break
                if lo[k]<=S: lab[i]=-1; break
                if hi[k]>=T: lab[i]=+1; break
        return lab

    rows=[]
    for sym in ["BTCUSDT","ETHUSDT","SOLUSDT"]:
        print(f"  {sym}:")
        df = pd.read_parquet(FEAT/f"{sym}_1h_features.parquet")
        df = df[df.index >= pd.Timestamp("2021-01-01", tz="UTC")]
        df = df.dropna(subset=["open","high","low","close","atr_14","ret_4"]).copy()
        df["lab"] = tb_labels(df)
        df = df.iloc[:-HORIZON-1]
        feat = [c for c in FCOLS if c in df.columns]
        X = df[feat].astype(np.float32).fillna(0).values
        y = (df["lab"]==1).astype(np.int8).values
        cut = pd.Timestamp("2024-07-01", tz="UTC")
        is_m = df.index < cut
        oos_m = df.index >= cut
        if is_m.sum() < 500 or oos_m.sum() < 200:
            print(f"    not enough data"); continue

        # Train with last 10% for early stop
        idx = np.where(is_m)[0]
        v_start = int(len(idx)*0.9)
        tr_i, vl_i = idx[:v_start], idx[v_start:]
        train = lgb.Dataset(X[tr_i], y[tr_i], feature_name=feat)
        valid = lgb.Dataset(X[vl_i], y[vl_i], reference=train)
        params = dict(objective="binary", metric="binary_logloss", learning_rate=0.03,
                      num_leaves=31, feature_fraction=0.85, bagging_fraction=0.85,
                      bagging_freq=5, min_child_samples=200, reg_alpha=0.1, reg_lambda=0.1, verbose=-1)
        m = lgb.train(params, train, num_boost_round=600, valid_sets=[valid],
                      callbacks=[lgb.early_stopping(30, verbose=False)])
        p_oos = m.predict(X[oos_m])
        p_is  = m.predict(X[is_m])
        auc_is = roc_auc_score(y[is_m], p_is)
        auc_oos = roc_auc_score(y[oos_m], p_oos) if y[oos_m].any() else 0.0

        # Simulate trading: enter LONG when P>threshold
        oos = df[oos_m].copy(); oos["p"] = p_oos
        for th in [0.52, 0.55, 0.58, 0.60]:
            sig = (oos["p"] > th) & (~(oos["p"] > th).shift(1).fillna(False))
            sig_full = pd.Series(False, index=df.index)
            sig_full.loc[oos.index] = sig.values
            tr, eq = simulate(df[oos_m], 1, tp_atr=1.0, sl_atr=1.0,
                              entry_mask=sig_full[oos_m])
            r = report(f"{sym}_ML_th{th}", eq, tr)
            rows.append({**r, "auc_is":round(auc_is,4),"auc_oos":round(auc_oos,4)})
            print(f"    th={th}  n={r['n']:4d} Sh={r['sharpe']:5.2f} CAGR={r['cagr']*100:+6.1f}% Win={r['win']*100:4.1f} PF={r['pf']:.2f}  AUC IS={auc_is:.3f} OOS={auc_oos:.3f}")

    pd.DataFrame(rows).to_csv(OUT/"V12B_results.csv", index=False)


if __name__ == "__main__":
    run_v12a()
    v12b_ml()
