"""
edge_val_stage2_klines_2026_06_01.py — STAGE 2 of Tier-1 new-edge validation.
Klines-only gates (NO L25). All signals computed CAUSALLY at ws_s = slot_start - window_s.

Gates validated:
  base   momo ret_2m@ws_s: predict sign(close[ws_s]/close[ws_s-120]-1)  (production momo anchor)
  B2  KAMA Efficiency Ratio: ER_N = |c[ws_s]-c[ws_s-N]| / sum|dc|, N in {30,60,120}
        - kill: ER<0.3 (drop choppy)  - pass-dir: sign of net displacement
  B3  Realized semivariance asym A=RS+/(RS+ + RS-), N in {60,120,300}
        - kill UP when A>thr (up-vol exhausted), kill DOWN when A<1-thr
  B4  Rogers-Satchell vol breakout (1m): RS_fast(6) vs P75/P25 of RS_slow(24) -> regime gate on momo
  B5  Page-CUSUM (running, dual): direction at ws_s when |S|>h  (standalone directional)
  B6  Kalman velocity (running 2-state on 1s): sign(velocity) when |vel|>q75  (standalone directional)
  C5  Session-open burst (1m): within 90min of London/NY/Asia open AND |ret_from_open|>=Xbps AND aligned

EVAL: two views per gate:
  (a) STANDALONE: gate's own predicted direction vs chainlink outcome (WR vs base rate, z-test).
  (b) OVERLAY: keep only momo fires passing the gate -> WR-lift over the momo base, n retained.

Window: Apr24 -> Jun1 (1s coverage vision+spotws). BTC+ETH primary; SOL shown separately.
Usage: C:/Python314/python.exe strategy_lab/directional/edge_val_stage2_klines_2026_06_01.py
"""
from __future__ import annotations
import sys, math, time
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
from load import load_resolutions  # noqa: E402

CANON = ROOT / "data" / "v4" / "canonical"
OUT = ROOT / "strategy_lab" / "directional" / "_results"
OUT.mkdir(parents=True, exist_ok=True)
WIN = {"5m": 300, "15m": 900}
SYM = {"BTC": "BINANCE_SPOT_BTC_USDT", "ETH": "BINANCE_SPOT_ETH_USDT", "SOL": "BINANCE_SPOT_SOL_USDT"}
ASSETS = ["BTC", "ETH", "SOL"]
LO = int(pd.Timestamp("2026-04-24", tz="UTC").timestamp())
HI = int(pd.Timestamp("2026-06-01 09:00", tz="UTC").timestamp())


def norm_cdf(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def z_p(k, n, p0):
    if n == 0:
        return (np.nan, np.nan, np.nan)
    ph = k / n
    se = math.sqrt(p0 * (1 - p0) / n)
    if se == 0:
        return (ph, np.nan, np.nan)
    z = (ph - p0) / se
    return (ph, z, 1.0 - norm_cdf(z))


def two_sided_p(k, n, p0):
    """abs z two-sided (for direction-agnostic significance)."""
    if n == 0:
        return np.nan
    ph = k / n
    se = math.sqrt(p0 * (1 - p0) / n)
    if se == 0:
        return np.nan
    z = abs(ph - p0) / se
    return 2 * (1 - norm_cdf(z))


def unified_1s(asset):
    df = pd.read_parquet(CANON / "klines_1s.parquet",
                         columns=["time_period_start_us", "price_close", "symbol_id", "source", "period_id"])
    df = df[(df.symbol_id == SYM[asset]) & (df.period_id == "1SEC")
            & df.source.isin(["binance-vision", "binance-spot-ws"])].sort_values("time_period_start_us")
    ts = df.time_period_start_us.values.astype(np.int64) // 1_000_000 + 1   # bar-END seconds
    px = df.price_close.values.astype(float)
    keep = np.concatenate([np.diff(ts) != 0, [True]])
    return ts[keep], px[keep]


def klines_1m(asset):
    df = pd.read_parquet(CANON / "klines_1m.parquet",
                         columns=["time_period_start_us", "price_open", "price_high", "price_low",
                                  "price_close", "symbol_id", "source"])
    df = df[(df.symbol_id == SYM[asset])
            & df.source.isin(["binance-spot-ws", "binance-vision"])].sort_values("time_period_start_us")
    df = df.drop_duplicates("time_period_start_us", keep="last")
    ts = df.time_period_start_us.values.astype(np.int64) // 1_000_000 + 60  # bar-END seconds
    return (ts, df.price_open.values.astype(float), df.price_high.values.astype(float),
            df.price_low.values.astype(float), df.price_close.values.astype(float))


def running_kalman(px, Q=0.001, R=0.1):
    """2-state [pos,vel] constant-velocity Kalman over the whole 1s series. returns vel array.
    Scalar implementation (P = p00,p01,p10,p11) — no per-step array alloc."""
    n = len(px)
    vel = np.zeros(n)
    x0 = float(px[0]); x1 = 0.0
    p00, p01, p10, p11 = 1.0, 0.0, 0.0, 1.0
    for t in range(1, n):
        # predict (dt=1): x = F x ; P = F P F^T + Qm   with F=[[1,1],[0,1]]
        xp0 = x0 + x1
        xp1 = x1
        a00 = p00 + p01 + p10 + p11 + Q
        a01 = p01 + p11
        a10 = p10 + p11
        a11 = p11 + Q
        # update (observe position): S=a00+R ; K=[a00/S, a10/S]
        S = a00 + R
        K0 = a00 / S
        K1 = a10 / S
        err = px[t] - xp0
        x0 = xp0 + K0 * err
        x1 = xp1 + K1 * err
        p00 = (1.0 - K0) * a00
        p01 = (1.0 - K0) * a01
        p10 = a10 - K1 * a00
        p11 = a11 - K1 * a01
        vel[t] = x1
    return vel


def running_cusum(px, k=0.5, roll=300):
    """dual page-CUSUM on standardized 1s returns. returns (S_pos, S_neg)."""
    n = len(px)
    r = np.zeros(n)
    r[1:] = np.diff(px) / px[:-1]
    # rolling mean/std (causal, window=roll) via pandas
    s = pd.Series(r)
    mu = s.rolling(roll, min_periods=30).mean().to_numpy()
    sd = s.rolling(roll, min_periods=30).std(ddof=0).to_numpy()
    z = np.where(sd > 0, (r - mu) / sd, 0.0)
    z = np.nan_to_num(z)
    Sp = np.zeros(n); Sn = np.zeros(n)
    sp = sn = 0.0
    for t in range(1, n):
        sp = max(0.0, sp + z[t] - k)
        sn = max(0.0, sn - z[t] - k)
        Sp[t] = sp; Sn[t] = sn
    return Sp, Sn


def run():
    t0 = time.time()
    res = load_resolutions()
    res = res[res.ticker.isin(ASSETS) & res.timeframe.isin(["5m", "15m"])].copy()
    res["slot_start"] = (res.slot_start_us // 1_000_000).astype(np.int64)
    res["ws_s"] = res.slot_start - res.timeframe.map(WIN).astype(np.int64)
    res["won_up"] = (res.outcome.astype(str).str.lower() == "up")
    res = res[(res.ws_s >= LO) & (res.ws_s < HI)]

    recs = []  # per-fire feature dict
    for asset in ASSETS:
        ts, px = unified_1s(asset)
        absdc = np.concatenate([[0.0], np.abs(np.diff(px))])
        dc = np.concatenate([[0.0], np.diff(px)])
        logr = np.concatenate([[0.0], np.diff(np.log(px))])
        c_absdc = np.cumsum(absdc)
        c_rp = np.cumsum(np.where(logr > 0, logr * logr, 0.0))   # RS+ cumsum
        c_rn = np.cumsum(np.where(logr < 0, logr * logr, 0.0))   # RS- cumsum
        c_pow = np.cumsum(np.abs(logr))
        print(f"[{asset}] 1s n={len(ts):,} running kalman+cusum...", flush=True)
        vel = running_kalman(px)
        Sp, Sn = running_cusum(px)
        # 1m
        m_ts, m_o, m_h, m_l, m_c = klines_1m(asset)

        sub = res[res.ticker == asset]
        wss = sub.ws_s.values.astype(np.int64)
        won = sub.won_up.values
        tf = sub.timeframe.values
        # indices into 1s by ws_s (causal: last bar ended <= ws_s)
        i = np.searchsorted(ts, wss, side="right") - 1
        ok = i >= 5
        def at(arr, idx):
            out = np.full(len(idx), np.nan); m = idx >= 0; out[m] = arr[idx[m]]; return out
        def idx_back(sec):
            j = np.searchsorted(ts, wss - sec, side="right") - 1
            return j
        # base momo ret_2m
        i120 = idx_back(120)
        c_now = at(px, i); c_120 = at(px, i120)
        ret2m = c_now / c_120 - 1.0
        # ER_N and net displacement
        feats = dict(asset=asset, tf=tf, ws_s=wss, won_up=won, ret2m=ret2m)
        for N in [30, 60, 120]:
            iN = idx_back(N)
            num = np.abs(at(px, i) - at(px, iN))
            den = at(c_absdc, i) - at(c_absdc, iN)
            er = np.where(den > 0, num / den, np.nan)
            feats[f"ER{N}"] = er
            feats[f"disp{N}"] = at(px, i) - at(px, iN)
        # semivariance A_N
        for N in [60, 120, 300]:
            iN = idx_back(N)
            rp = at(c_rp, i) - at(c_rp, iN)
            rn = at(c_rn, i) - at(c_rn, iN)
            feats[f"A{N}"] = np.where((rp + rn) > 0, rp / (rp + rn), np.nan)
        # power (low-vol regime)
        i300 = idx_back(300)
        feats["pow300"] = at(c_pow, i) - at(c_pow, i300)
        # kalman vel & cusum at ws_s
        feats["vel"] = at(vel, i)
        feats["Sp"] = at(Sp, i); feats["Sn"] = at(Sn, i)
        # Rogers-Satchell 1m fast/slow
        mi = np.searchsorted(m_ts, wss, side="right") - 1
        def rsbar(idx):
            o = m_o[idx]; h = m_h[idx]; l = m_l[idx]; c = m_c[idx]
            with np.errstate(divide="ignore", invalid="ignore"):
                return np.log(h / c) * np.log(h / o) + np.log(l / c) * np.log(l / o)
        rs_fast = np.full(len(wss), np.nan); rs_slow = np.full(len(wss), np.nan)
        good = mi >= 24
        for kk in np.where(good)[0]:
            idxs = np.arange(mi[kk] - 23, mi[kk] + 1)
            bars = rsbar(idxs)
            rs_slow[kk] = np.nanmean(bars)
            rs_fast[kk] = np.nanmean(bars[-6:])
        feats["rs_fast"] = rs_fast; feats["rs_slow"] = rs_slow
        # session-open ret (1m)
        hour = ((wss % 86400) // 3600).astype(int)
        minute = ((wss % 3600) // 60).astype(int)
        feats["hour"] = hour
        # session opens: London 7:00, NY 13:30, Asia 23:00
        sess_open_s = np.full(len(wss), -1, dtype=np.int64)
        day0 = (wss // 86400) * 86400
        for oh, om in [(7, 0), (13, 30), (23, 0)]:
            op = day0 + oh * 3600 + om * 60
            since = wss - op
            m = (since >= 0) & (since <= 90 * 60)
            sess_open_s[m] = op[m]
        feats["sess_open"] = sess_open_s
        # ret from session open to ws_s using 1m
        ret_open = np.full(len(wss), np.nan)
        has = sess_open_s > 0
        if has.any():
            oi = np.searchsorted(m_ts, sess_open_s, side="right") - 1
            co = np.where(oi >= 0, m_c[np.clip(oi, 0, len(m_c) - 1)], np.nan)
            cn = np.where(mi >= 0, m_c[np.clip(mi, 0, len(m_c) - 1)], np.nan)
            ret_open = np.where(has, np.log(cn / co), np.nan)
        feats["ret_open"] = ret_open

        df = pd.DataFrame({k: v for k, v in feats.items()})
        recs.append(df)
        print(f"[{asset}] features built n={len(df)} t={time.time()-t0:.0f}s", flush=True)

    F = pd.concat(recs, ignore_index=True)
    F = F[np.isfinite(F.ret2m)]
    F.to_parquet(OUT / "edge_val_stage2_features_2026_06_01.parquet", index=False)

    # ---- evaluation: BTC+ETH primary ----
    def evalset(D, label):
        rows = []
        base_up = float(D.won_up.mean())
        n = len(D)
        # BASE momo
        mdir_up = D.ret2m > 0
        k = int((mdir_up == D.won_up).sum())
        wr, z, p = z_p(k, n, 0.5)
        rows.append(dict(set=label, gate="BASE_momo_ret2m", param="-", view="standalone",
                         n=n, wr=round(wr, 4), ref=0.5, lift_pp=round((wr - 0.5) * 100, 2),
                         z=round(z, 2), p=round(two_sided_p(k, n, 0.5), 4)))
        base_wr = wr
        # B6 Kalman standalone (dir = sign vel), threshold q75 |vel|
        thr = np.nanquantile(np.abs(D.vel), 0.75)
        q = np.abs(D.vel) >= thr
        kd_up = D.vel > 0
        nn = int(q.sum()); kk = int((kd_up[q] == D.won_up[q]).sum())
        wr, z, p = z_p(kk, nn, 0.5)
        rows.append(dict(set=label, gate="B6_kalman_vel", param="q75", view="standalone",
                         n=nn, wr=round(wr, 4), ref=0.5, lift_pp=round((wr - 0.5) * 100, 2),
                         z=round(z, 2), p=round(two_sided_p(kk, nn, 0.5), 4)))
        # B5 CUSUM standalone (dir = which accumulator higher) when max(Sp,Sn)>h
        for h in [1.0, 2.0, 3.0]:
            cdir_up = D.Sp > D.Sn
            q = np.maximum(D.Sp, D.Sn) > h
            nn = int(q.sum()); kk = int((cdir_up[q] == D.won_up[q]).sum())
            wr, z, p = z_p(kk, nn, 0.5)
            rows.append(dict(set=label, gate="B5_cusum_dir", param=f"h{h}", view="standalone",
                             n=nn, wr=round(wr, 4), ref=0.5, lift_pp=round((wr - 0.5) * 100, 2),
                             z=round(z, 2), p=round(two_sided_p(kk, nn, 0.5), 4)))
        # ----- OVERLAYS on momo base (keep fires passing gate, measure momo WR) -----
        def overlay(mask, gate, param):
            q = mask & np.isfinite(D.ret2m)
            nn = int(q.sum())
            if nn < 20:
                rows.append(dict(set=label, gate=gate, param=param, view="overlay_momo",
                                 n=nn, wr=np.nan, ref=round(base_wr, 4), lift_pp=np.nan, z=np.nan, p=np.nan)); return
            kk = int((mdir_up[q] == D.won_up[q]).sum())
            wr, z, p = z_p(kk, nn, base_wr)
            rows.append(dict(set=label, gate=gate, param=param, view="overlay_momo",
                             n=nn, wr=round(wr, 4), ref=round(base_wr, 4),
                             lift_pp=round((wr - base_wr) * 100, 2), z=round(z, 2),
                             p=round(z_p(kk, nn, base_wr)[2], 4)))
        # B2 KAMA ER kill: keep ER>=0.3 (drop chop)
        for N in [30, 60, 120]:
            overlay(D[f"ER{N}"] >= 0.3, "B2_kama_er_keep>=0.3", f"N{N}")
            for q_ in [0.5, 0.6]:
                thrER = np.nanquantile(D[f"ER{N}"], q_)
                overlay(D[f"ER{N}"] >= thrER, f"B2_kama_er_keep>=q{int(q_*100)}", f"N{N}")
        # B3 semivariance kill: drop fires where momo-UP but A>thr (up exhausted) or momo-DN but A<1-thr
        for N in [60, 120, 300]:
            for thr in [0.60, 0.65, 0.70]:
                bad = ((mdir_up) & (D[f"A{N}"] > thr)) | ((~mdir_up) & (D[f"A{N}"] < 1 - thr))
                overlay(~bad, "B3_semivar_kill", f"N{N}_t{thr}")
        # B4 Rogers-Satchell regime: keep high-vol (rs_fast>P75 rolling proxied by quantile) / low
        p75 = np.nanquantile(D.rs_slow, 0.75); p25 = np.nanquantile(D.rs_slow, 0.25)
        overlay(D.rs_fast > p75, "B4_rs_vol_high_keep", "fast>P75slow")
        overlay(D.rs_fast < p25, "B4_rs_vol_low_keep", "fast<P25slow")
        # pow300 low-regime
        plo = np.nanquantile(D.pow300, 0.25)
        overlay(D.pow300 < plo, "B_pow_low_keep", "<P25")
        overlay(D.pow300 > np.nanquantile(D.pow300, 0.75), "B_pow_high_keep", ">P75")
        # C5 session-open burst overlay (within 90min open & |ret_open|>=X & aligned to momo)
        for X in [10, 20, 30]:
            xb = X / 1e4
            aligned = (D.sess_open > 0) & (np.abs(D.ret_open) >= xb) & (np.sign(D.ret_open) == np.sign(D.ret2m))
            overlay(aligned, "C5_session_burst", f">={X}bps")
        return rows

    BE = F[F.asset.isin(["BTC", "ETH"])]
    SOLF = F[F.asset == "SOL"]
    allrows = evalset(BE, "BTC+ETH") + evalset(SOLF, "SOL")
    R = pd.DataFrame(allrows)
    R.to_csv(OUT / "edge_val_stage2_klines_2026_06_01.csv", index=False)

    pd.set_option("display.width", 220); pd.set_option("display.max_rows", 200)
    print("\n" + "=" * 100)
    print("STAGE 2 — KLINES-INDICATOR GATES (causal @ ws_s). standalone vs base 0.5; overlay vs momo base WR")
    print("=" * 100)
    for lab in ["BTC+ETH", "SOL"]:
        print(f"\n#### {lab} ####")
        print(R[R.set == lab].to_string(index=False))
    print(f"\ntotal {time.time()-t0:.0f}s ; wrote stage2 csv + features parquet")


if __name__ == "__main__":
    run()
