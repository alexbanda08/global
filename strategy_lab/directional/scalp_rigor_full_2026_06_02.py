"""
scalp_rigor_full_2026_06_02.py — graduation gates 3-6 on the FULL local window (Apr24->Jun1).
Exit-scalp on lag-taker fires (BTC+ETH). Builds held + OPPOSITE-token exit paths + CUSUM, then:
  Gate 3  forward-OOS: bootstrap 95% CI of TIME+60s $/tr per segment (fee 0 / 0.015 / 0.07)
  Gate 4  walk-forward: rolling train (pick exit_dt + vwap-gate) -> test next window, accumulate OOS
  Gate 5  direction-permutation: actual (lag-side) scalp vs taking the OPPOSITE side; perm p
  Gate 6  CUSUM gate: (cusum_strength>=1.0 OR entry_vwap<0.55) lift on TIME+60s, bootstrap CI
PASS 1 (heavy, chunked L25 + klines CUSUM) writes scalp_rigor_full_2026_06_02.parquet; PASS 2 analyses.
Usage: C:/Python314/python.exe -X utf8 strategy_lab/directional/scalp_rigor_full_2026_06_02.py
"""
from __future__ import annotations
import sys, gc, math, time, traceback
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))
from load import load_orderbook_l25_streaming  # noqa: E402
from engine_v2 import LiveMimicConfig, find_book_strict, sell_at_bid_partial, fill_at_book  # noqa: E402

FIRES = ROOT / "strategy_lab" / "lag_taker_fires_oos_2026_06_01.parquet"
CANON = ROOT / "data" / "v4" / "canonical"
OUT = ROOT / "strategy_lab" / "directional" / "_results"
ENR = OUT / "scalp_rigor_full_2026_06_02.parquet"
WIN = {"5m": 300, "15m": 900}
SYM = {"BTC": "BINANCE_SPOT_BTC_USDT", "ETH": "BINANCE_SPOT_ETH_USDT"}
FEE = 0.07; LAT = 85_000; NOTIONAL = 25.0; SPREAD = 0.05
EXIT_DTS = [45, 60, 90]
rng = np.random.default_rng(20260602)


def fee_share(v): return FEE * v * (1 - v)


def unified_1s(asset):
    df = pd.read_parquet(CANON / "klines_1s.parquet",
                         columns=["time_period_start_us", "price_close", "symbol_id", "source", "period_id"])
    df = df[(df.symbol_id == SYM[asset]) & (df.period_id == "1SEC")
            & df.source.isin(["binance-vision", "binance-spot-ws"])].sort_values("time_period_start_us")
    ts = df.time_period_start_us.values.astype(np.int64) + 1_000_000
    px = df.price_close.values.astype(float)
    keep = np.concatenate([np.diff(ts) != 0, [True]])
    return ts[keep], px[keep]


def running_cusum(px, k=0.5, roll=300):
    n = len(px); r = np.zeros(n); r[1:] = np.diff(px) / px[:-1]
    s = pd.Series(r); mu = s.rolling(roll, min_periods=30).mean().to_numpy()
    sd = s.rolling(roll, min_periods=30).std(ddof=0).to_numpy()
    z = np.nan_to_num(np.where(sd > 0, (r - mu) / sd, 0.0))
    Sp = np.zeros(n); Sn = np.zeros(n); sp = sn = 0.0
    for t in range(1, n):
        sp = max(0.0, sp + z[t] - k); sn = max(0.0, sn - z[t] - k); Sp[t] = sp; Sn[t] = sn
    return Sp, Sn


def bid_vwap(books, slug, tok, ts, shares, cfg):
    bk = find_book_strict(books, slug, tok, int(ts) + LAT, max_staleness_us=cfg.max_book_staleness_us)
    if bk is None or not len(bk.get("bp", [])):
        return np.nan
    vw, fsh, _ = sell_at_bid_partial(np.asarray(bk["bp"], float), np.asarray(bk["bsz"], float), shares)
    return vw if fsh > 0 else np.nan


def build():
    t0 = time.time()
    F = pd.read_parquet(FIRES)
    F = F[F.asset.isin(["BTC", "ETH"])].copy()
    print(f"fires BTC+ETH: {len(F)}", flush=True)
    # CUSUM per asset
    cus = {}
    for a in ["BTC", "ETH"]:
        ts, px = unified_1s(a)
        Sp, Sn = running_cusum(px)
        cus[a] = (ts, Sp, Sn)
        print(f"[{a}] cusum built t={time.time()-t0:.0f}s", flush=True)
    recs = []
    LO = int(F.slot_start.min()); HI = int(F.slot_start.max()) + 1
    bounds = list(range(LO, HI, 3 * 86400)) + [HI]
    cfg = LiveMimicConfig()
    for ci in range(len(bounds) - 1):
        clo, chi = bounds[ci], bounds[ci + 1]
        for asset in ["BTC", "ETH"]:
            for tf in ["5m", "15m"]:
                books = None
                try:
                    sub = F[(F.asset == asset) & (F.tf == tf) & (F.slot_start >= clo) & (F.slot_start < chi)]
                    if sub.empty:
                        continue
                    books = load_orderbook_l25_streaming(asset.lower(), slugs=set(sub.slug.values), subsample_1hz=False)
                    ts_c, Sp, Sn = cus[asset]
                    for _, r in sub.iterrows():
                        held = r.direction; opp = "Down" if held == "Up" else "Up"
                        fu = int(r.fire_us); sh = float(r.shares); ev = float(r.entry_vwap)
                        rec = dict(slug=r.slug, asset=asset, tf=tf, slot_start=int(r.slot_start), fire_us=fu,
                                   direction=held, delta_bps=float(r.delta_bps), entry_vwap=ev, shares=sh,
                                   won=bool(r.won), hold_pnl=float(r.pnl), segment=r.segment)
                        for dt in EXIT_DTS:
                            rec[f"exit_h{dt}"] = bid_vwap(books, r.slug, held, fu + dt * 1_000_000, sh, cfg)
                        # opposite side round-trip (gate 5): opp entry ask + opp exit bid @60
                        of = fill_at_book(books, r.slug, opp, fu, cfg=cfg, side="buy", spread_filter=SPREAD, notional_usd=NOTIONAL)
                        rec["opp_entry"] = float(of["vwap"]) if of else np.nan
                        rec["opp_shares"] = float(of["shares"]) if of else np.nan
                        rec["opp_exit60"] = bid_vwap(books, r.slug, opp, fu + 60 * 1_000_000,
                                                     float(of["shares"]) if of else sh, cfg)
                        # cusum at fire
                        j = int(np.searchsorted(ts_c, fu, side="right")) - 1
                        if j >= 0:
                            rec["cusum_strength"] = float(max(Sp[j], Sn[j]))
                            rec["cusum_up"] = bool(Sp[j] > Sn[j])
                        else:
                            rec["cusum_strength"] = np.nan; rec["cusum_up"] = None
                        recs.append(rec)
                except Exception:
                    print(f"  !! {asset} {tf} {pd.to_datetime(clo,unit='s',utc=True):%m-%d}", flush=True); traceback.print_exc()
                finally:
                    del books; gc.collect()
        print(f"[chunk {pd.to_datetime(clo,unit='s',utc=True):%m-%d}] recs={len(recs)} t={time.time()-t0:.0f}s", flush=True)
    E = pd.DataFrame(recs); E.to_parquet(ENR, index=False)
    print(f"wrote {ENR} ({len(E)}) t={time.time()-t0:.0f}s", flush=True)
    return E


# ---------- PASS 2 analysis ----------
def hold_pnl(ev, sh, won): return (1 - ev) * sh * (1 - FEE * ev) if won else -ev * sh


def scalp(ev, ex, sh, won, fl):
    if not np.isfinite(ex):
        return hold_pnl(ev, sh, won)
    rt = (ex - ev) * sh
    if fl > 0:
        rt -= (fl * ev * (1 - ev) + fl * ex * (1 - ex)) * sh
    return rt


def stat(x):
    x = np.asarray(x, float); n = len(x)
    if n < 2: return (np.nan, np.nan)
    m = x.mean(); se = x.std(ddof=1) / np.sqrt(n); return m, (m / se if se else np.nan)


def boot_ci(x, B=8000):
    x = np.asarray(x, float); n = len(x)
    if n < 5: return (np.nan, np.nan)
    return tuple(np.percentile(x[rng.integers(0, n, (B, n))].mean(axis=1), [2.5, 97.5]))


def analyze(E):
    E = E[E.delta_bps >= 3].copy()
    print("\n" + "=" * 92)
    print(f"SCALP RIGOR — gates 3-6 (BTC+ETH delta>=3, n={len(E)}, exit=TIME, fee curve per leg)")
    print("=" * 92)
    def col_pnl(dt, fl): return np.array([scalp(r.entry_vwap, r[f"exit_h{dt}"], r.shares, r.won, fl) for _, r in E.iterrows()])

    # GATE 3: per-segment bootstrap CI for TIME+60s
    print("\n--- GATE 3: forward-OOS by segment (TIME+60s) ---")
    print(f"{'segment':<10}{'n':>5}{'hold$':>8}{'t+60 fee0':>11}{'CI0':>18}{'fee.015':>9}{'fee.07':>9}{'t.07':>7}")
    for seg in ["bwd_oos", "fit_IS", "fit_OOS", "fwd_oos", "ALL"]:
        g = E if seg == "ALL" else E[E.segment == seg]
        if len(g) < 5: continue
        h = np.array([hold_pnl(r.entry_vwap, r.shares, r.won) for _, r in g.iterrows()])
        p0 = np.array([scalp(r.entry_vwap, r.exit_h60, r.shares, r.won, 0.0) for _, r in g.iterrows()])
        p15 = np.array([scalp(r.entry_vwap, r.exit_h60, r.shares, r.won, 0.015) for _, r in g.iterrows()])
        p7 = np.array([scalp(r.entry_vwap, r.exit_h60, r.shares, r.won, FEE) for _, r in g.iterrows()])
        lo, hi = boot_ci(p0); m7, t7 = stat(p7)
        print(f"{seg:<10}{len(g):>5}{h.mean():>8.2f}{p0.mean():>11.3f}{f'[{lo:+.2f},{hi:+.2f}]':>18}{p15.mean():>9.3f}{m7:>9.3f}{t7:>7.2f}")

    # GATE 4: walk-forward (rolling 7d train -> 3d test; pick exit_dt + vwap gate by train mean)
    print("\n--- GATE 4: walk-forward (train 7d pick {exit_dt, vwap_gate} -> test next 3d), fee=0.015 ---")
    Es = E.sort_values("slot_start").reset_index(drop=True)
    t_lo = int(Es.slot_start.min()); t_hi = int(Es.slot_start.max())
    oos = []; chosen = []
    cur = t_lo + 7 * 86400
    while cur < t_hi:
        tr = Es[(Es.slot_start >= cur - 7 * 86400) & (Es.slot_start < cur)]
        te = Es[(Es.slot_start >= cur) & (Es.slot_start < cur + 3 * 86400)]
        if len(tr) >= 30 and len(te) >= 5:
            best = None
            for dt in EXIT_DTS:
                for gate in [False, True]:
                    sub = tr[tr.entry_vwap < 0.55] if gate else tr
                    if len(sub) < 15: continue
                    pnl = np.array([scalp(r.entry_vwap, r[f"exit_h{dt}"], r.shares, r.won, 0.015) for _, r in sub.iterrows()])
                    m, t = stat(pnl)
                    if best is None or (t or -9) > best[0]:
                        best = (t, dt, gate)
            if best:
                _, dt, gate = best
                sub = te[te.entry_vwap < 0.55] if gate else te
                if len(sub) >= 3:
                    pnl = np.array([scalp(r.entry_vwap, r[f"exit_h{dt}"], r.shares, r.won, 0.015) for _, r in sub.iterrows()])
                    oos.extend(pnl); chosen.append((dt, gate))
        cur += 3 * 86400
    if oos:
        m, t = stat(oos); lo, hi = boot_ci(oos)
        from collections import Counter
        print(f"  walk-forward OOS: n={len(oos)} $/tr={m:+.3f} t={t:.2f} 95%CI=[{lo:+.2f},{hi:+.2f}]  picks={dict(Counter(chosen))}")
    else:
        print("  walk-forward: insufficient windows")

    # GATE 5: direction permutation (held vs opposite-side round-trip)
    print("\n--- GATE 5: direction permutation (lag-side vs OPPOSITE side, fee=0.015) ---")
    G = E[np.isfinite(E.opp_entry) & np.isfinite(E.opp_exit60) & np.isfinite(E.exit_h60)].copy()
    held = np.array([scalp(r.entry_vwap, r.exit_h60, r.shares, r.won, 0.015) for _, r in G.iterrows()])
    oppp = np.array([(r.opp_exit60 - r.opp_entry) * r.opp_shares - (0.015 * r.opp_entry * (1 - r.opp_entry) + 0.015 * r.opp_exit60 * (1 - r.opp_exit60)) * r.opp_shares for _, r in G.iterrows()])
    mh, th = stat(held); mo, to = stat(oppp)
    # permutation: randomly pick held vs opp per fire, build null of mean
    both = np.vstack([held, oppp])  # 2 x n
    B = 8000; n = both.shape[1]
    pick = rng.integers(0, 2, (B, n))
    null = both[pick, np.arange(n)].mean(axis=1)
    p = float((null >= mh).mean())
    print(f"  n={len(G)}  lag-side $/tr={mh:+.3f} (t={th:.2f})  opposite-side $/tr={mo:+.3f} (t={to:.2f})  perm_p(lag>=null)={p:.4f}")

    # GATE 6: CUSUM gate
    print("\n--- GATE 6: CUSUM/vwap gate on TIME+60s ---")
    E2 = E[np.isfinite(E.cusum_strength)].copy()
    for lab, mask in [("gate(cusum>=1 OR vwap<.55)", (E2.cusum_strength >= 1.0) | (E2.entry_vwap < 0.55)),
                      ("vwap<0.55 only", E2.entry_vwap < 0.55),
                      ("cusum>=1.0 only", E2.cusum_strength >= 1.0),
                      ("NO gate (all)", pd.Series(True, index=E2.index))]:
        g = E2[mask]
        if len(g) < 10: continue
        p0 = np.array([scalp(r.entry_vwap, r.exit_h60, r.shares, r.won, 0.0) for _, r in g.iterrows()])
        p7 = np.array([scalp(r.entry_vwap, r.exit_h60, r.shares, r.won, FEE) for _, r in g.iterrows()])
        m0, t0_ = stat(p0); m7, t7 = stat(p7); lo, hi = boot_ci(p7)
        print(f"  {lab:<28} n={len(g):>4} fee0 ${m0:+.3f}(t={t0_:.2f}) | fee.07 ${m7:+.3f}(t={t7:.2f}) CI07=[{lo:+.2f},{hi:+.2f}]")


if __name__ == "__main__":
    if ENR.exists() and "--reuse" in sys.argv:
        E = pd.read_parquet(ENR); print(f"reusing {ENR} ({len(E)})")
    else:
        E = build()
    analyze(E)
