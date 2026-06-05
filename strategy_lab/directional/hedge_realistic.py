"""
hedge_realistic.py — realistic hedged fast-taker: book-walk hedge leg + real fees.

Fixes the two optimism flags in path_overlay.py's hedge:
  1. Hedge leg now filled via engine_v2.fill_at_book (book-WALK for ~lead_shares of the
     other side) at trigger+85ms latency + spread filter — not top-of-book.
  2. Resolution fee: production 2%-on-WINNING-profit-only applied to the winning leg of
     the completed pair (and to any directional residual). Losing legs pay $0.
  3. Unequal-share handling: paired = min(lead_shares, hedge_shares); the leftover on the
     heavier side resolves directionally.

Also instruments (answers the accounting questions):
  - no-reversal trades carry NO hedge cost (= directional base).
  - among HEDGED trades: how many the original leg would have WON (gave up upside) vs
    LOST (hedge saved the loss), and the mean pair cost (ep_lead+ep_hedge; <1 => cheap).

Usage: py -X utf8 strategy_lab/directional/hedge_realistic.py
"""
from __future__ import annotations
import sys, time
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))
from load import load_resolutions, load_orderbook_l25_streaming  # noqa: E402
from engine_v2 import LiveMimicConfig, fill_at_book  # noqa: E402

CANON = ROOT / "data" / "v4" / "canonical"
OUT = ROOT / "strategy_lab" / "directional" / "_results"
WIN = {"5m": 300, "15m": 900}
OFFSET = 5; SPREAD = 0.05; NOTIONAL = 25.0; MIN_RET = 3.0
IS_CUTOFF = int(pd.Timestamp("2026-05-15", tz="UTC").timestamp())
HEDGES = [3.0, 5.0]
FEE = 0.02  # 2% on winning-leg profit
SYM = {"BTC": "BINANCE_SPOT_BTC_USDT", "ETH": "BINANCE_SPOT_ETH_USDT", "SOL": "BINANCE_SPOT_SOL_USDT"}
CHUNK = 5 * 86400


def binance_1s(asset):
    df = pd.read_parquet(CANON / "klines_1s.parquet",
                         columns=["time_period_start_us", "price_close", "symbol_id", "source", "period_id"])
    df = df[(df.symbol_id == SYM[asset]) & (df.source == "binance-spot-ws") & (df.period_id == "1SEC")].sort_values("time_period_start_us")
    return (df.time_period_start_us.values.astype(np.int64) + 1_000_000), df.price_close.values.astype(float)


def asof1(ts, v, t):
    i = int(np.searchsorted(ts, int(t), side="right")) - 1
    return float(v[i]) if i >= 0 else np.nan


def asof_vec(ts, v, T):
    i = np.searchsorted(ts, T.astype(np.int64), side="right") - 1
    out = np.full(len(T), np.nan); ok = i >= 0; out[ok] = v[i[ok]]; return out


def dir_pnl(shares, vwap, won):
    """Directional hold to resolution, 2%-on-winning-profit."""
    return shares * (1 - vwap) * (1 - FEE) if won else -shares * vwap


def run():
    res = load_resolutions(); res["slug"] = res["slug"].astype(str)
    cfg = LiveMimicConfig()
    bz = {a: binance_1s(a) for a in ["BTC", "ETH", "SOL"]}
    lo = int(pd.Timestamp("2026-04-22", tz="UTC").timestamp())
    hi = int(pd.Timestamp("2026-05-30", tz="UTC").timestamp())
    bounds = list(range(lo, hi, CHUNK)) + [hi]
    rows = []
    for i in range(len(bounds) - 1):
        clo, chi = bounds[i], bounds[i + 1]
        for asset in ["BTC", "ETH", "SOL"]:
            be, bc = bz[asset]
            for tf in ["5m", "15m"]:
                pref = f"{asset.lower()}-updown-{tf}-"
                sub = res[(res.ticker == asset) & (res.timeframe == tf)]
                sub = sub[sub.slug.str.startswith(pref)].copy()
                sub["ss"] = sub.slug.str.rsplit("-", n=1).str[-1].astype(np.int64)
                sub = sub[(sub.ss >= clo) & (sub.ss < chi)]
                if sub.empty: continue
                slugs = set(sub.slug); won_up = dict(zip(sub.slug, sub.outcome.str.lower() == "up"))
                books = load_orderbook_l25_streaming(asset.lower(), slugs=slugs, subsample_1hz=False)
                for ss, slug in zip(sub.ss.values.astype(np.int64), sub.slug.values):
                    fire = (ss + OFFSET) * 1_000_000; slot_end = (ss + WIN[tf]) * 1_000_000
                    px0 = asof1(be, bc, ss * 1_000_000); pxf = asof1(be, bc, fire)
                    if not (np.isfinite(px0) and np.isfinite(pxf)): continue
                    ret = pxf / px0 - 1.0
                    if abs(ret) * 1e4 < MIN_RET: continue
                    lead = "Up" if ret > 0 else "Down"; other = "Down" if lead == "Up" else "Up"
                    f0 = fill_at_book(books, slug, lead, int(fire), cfg=cfg, side="buy",
                                      spread_filter=SPREAD, notional_usd=NOTIONAL)
                    if f0 is None: continue
                    Ls = float(f0["shares"]); Lusd = float(f0["usd"]); Lv = Lusd / Ls
                    won_lead = (ret > 0) == won_up[slug]
                    won_other = not won_lead
                    base = dir_pnl(Ls, Lv, won_lead)
                    rec = {"slot_start": int(ss), "base": base}

                    ob = books.get((slug, other))
                    for r in HEDGES:
                        hed = base; hedged = 0; gaveup = 0; saved = 0; paircost = np.nan
                        if ob is not None:
                            ots = ob[0].astype(np.int64); oask = ob[1][:, 0].astype(float)
                            m = (ots > fire) & (ots <= slot_end)
                            ots2 = ots[m]
                            if len(ots2):
                                bret = asof_vec(be, bc, ots2) / px0 - 1.0
                                against = (ret - bret) * 1e4 if ret > 0 else (bret - ret) * 1e4
                                hit = np.where(against >= r)[0]
                                if len(hit):
                                    t_trig = int(ots2[hit[0]])
                                    pk = oask[m][hit[0]]
                                    tgt = max(5.0, Ls * (pk if (np.isfinite(pk) and pk > 0) else 0.5) * 1.10)
                                    fh = fill_at_book(books, slug, other, t_trig, cfg=cfg, side="buy",
                                                      spread_filter=SPREAD, notional_usd=tgt)
                                    if fh is not None:
                                        hedged = 1
                                        Hs = float(fh["shares"]); Hv = float(fh["usd"]) / Hs
                                        paired = min(Ls, Hs)
                                        # pair: winning leg pays $1 on `paired`, 2% on its profit
                                        if won_lead:
                                            winfee = FEE * paired * (1 - Lv); gaveup = 1
                                        else:
                                            winfee = FEE * paired * (1 - Hv); saved = 1
                                        pair_pnl = paired * 1.0 - paired * (Lv + Hv) - winfee
                                        # residual on the heavier side -> directional
                                        if Ls > Hs:
                                            res_pnl = dir_pnl(Ls - paired, Lv, won_lead)
                                        elif Hs > Ls:
                                            res_pnl = dir_pnl(Hs - paired, Hv, won_other)
                                        else:
                                            res_pnl = 0.0
                                        hed = pair_pnl + res_pnl
                                        paircost = Lv + Hv
                        rec[f"hedge{int(r)}"] = hed
                        rec[f"hedged{int(r)}"] = hedged
                        rec[f"gaveup{int(r)}"] = gaveup
                        rec[f"saved{int(r)}"] = saved
                        rec[f"paircost{int(r)}"] = paircost
                    rows.append(rec)
        print(f"[chunk {pd.to_datetime(clo,unit='s',utc=True):%m-%d}] cum={len(rows)}", flush=True)
    df = pd.DataFrame(rows)
    df["period"] = np.where(df.slot_start < IS_CUTOFF, "IS", "OOS")
    df.to_csv(OUT / "hedge_realistic.csv", index=False)

    def stat(x):
        x = np.asarray(x); m = x.mean(); t = m / (x.std(ddof=1)/np.sqrt(len(x))) if (len(x) > 1 and x.std()) else np.nan
        return m, t, 100*(x > 0).mean(), x.min()
    print("\n" + "=" * 95)
    print("REALISTIC HEDGE (book-walk hedge leg + 2%-on-profit fee + residual) — IS vs OOS")
    print("=" * 95)
    for per in ["IS", "OOS"]:
        g = df[df.period == per]
        print(f"\n--- {per}  n={len(g)} ---")
        for c in ["base", "hedge3", "hedge5"]:
            m, t, wr, w = stat(g[c].to_numpy())
            print(f"  {c:<8} mean={m:+.4f}  t={t:5.2f}  win%={wr:4.1f}  worst={w:+.1f}  total={g[c].sum():+.0f}")
        for r in HEDGES:
            hg = g[g[f"hedged{int(r)}"] == 1]
            if len(hg):
                print(f"  [hedge{int(r)}] hedged={len(hg)} ({100*len(hg)/len(g):.0f}%)  "
                      f"saved_loss={int(hg[f'saved{int(r)}'].sum())}  gave_up_win={int(hg[f'gaveup{int(r)}'].sum())}  "
                      f"mean_paircost={hg[f'paircost{int(r)}'].mean():.4f}  mean_hedged_pnl={hg[f'hedge{int(r)}'].mean():+.3f}")
    print(f"\nwrote {OUT/'hedge_realistic.csv'}")


if __name__ == "__main__":
    run()
