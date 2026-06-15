"""
FAIR-VALUE-GAP scalp — CORRECTED EXIT MODEL (2026-06-10). Fixed clone of scalp_fvg_2026_06_09.py.
Exit via scalp_fill_lib_2026_06_10.exit_fill (size-capped bid, staleness guard, no outcome-leak; remainder held).
Every cell reports ALL + CLEAN (frac_held==0). Env: FVG_COINS/FVG_TFS/FVG_TAG/FVG_VOLLB/FVG_W0/FVG_W1/FVG_LIMIT.
"""
import sys, os, warnings, math
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings("ignore"); np.random.seed(0)
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data/v4/canonical")); sys.path.insert(0, str(ROOT / "strategy_lab/directional"))
from load import load_orderbook_bbo
from scalp_fill_lib_2026_06_10 import entry_fill, exit_fill, boot, cell
CANON = ROOT / "data/v4/canonical"; RES = ROOT / "strategy_lab/directional/_results"

SPREAD = 0.05; STAKE = 25.0; LAT_US = 85_000; VOL_LB = int(os.environ.get("FVG_VOLLB", "300"))
EXIT_S = 60
COINS = os.environ.get("FVG_COINS", "BTC,ETH,SOL").split(",")
TFS = os.environ.get("FVG_TFS", "15m,5m").split(",")
WIN = (os.environ.get("FVG_W0", "2026-03-30"), os.environ.get("FVG_W1", "2026-04-21"))
TAG = os.environ.get("FVG_TAG", ""); LIMIT = int(os.environ.get("FVG_LIMIT", "0"))
TF_SEC = {"5m": 300, "15m": 900}
GRID = {"15m": list(range(5, 781, 30)), "5m": list(range(5, 241, 20))}
_erf = np.vectorize(math.erf)


def Phi(x): return 0.5 * (1.0 + _erf(np.asarray(x, float) / math.sqrt(2.0)))


def klines(coin):
    sym = f"BINANCE_SPOT_{coin.upper()}_USDT"
    df = pd.read_parquet(CANON / "klines_1s.parquet", columns=["symbol_id", "time_period_start_us", "price_close"],
                         filters=[("symbol_id", "==", sym)]).sort_values("time_period_start_us").drop_duplicates("time_period_start_us")
    return df.time_period_start_us.values.astype("int64"), df.price_close.values.astype(float)


def asof_idx(ts, t): return np.searchsorted(ts, t, "right") - 1


res = pd.read_parquet(CANON / "resolutions_hf.parquet")
res = res[res.outcome.isin(["Up", "Down"])].drop_duplicates("slug")
BCOLS = ["timestamp_us", "slug", "outcome", "best_bid", "best_ask", "best_bid_size", "best_ask_size"]
lo_ts = pd.Timestamp(WIN[0], tz="UTC").value // 1000; hi_ts = pd.Timestamp(WIN[1], tz="UTC").value // 1000
ROWS = []
outp = RES / f"scalp_fvg_grid_fixed_2026_06_10{TAG}.parquet"

for coin in COINS:
    ts_k, px_k = klines(coin); lpx = np.log(px_k)
    for tf in TFS:
        d = res[(res.ticker == coin) & (res.timeframe == tf) &
                (res.slot_start_us >= lo_ts) & (res.slot_start_us <= hi_ts)].copy()
        if not len(d):
            print(f"{coin} {tf}: no slugs", flush=True); continue
        if LIMIT > 0: d = d.iloc[:LIMIT]
        wsec = TF_SEC[tf]; offs = GRID[tf]
        print(f"\n=== {coin} {tf}: {len(d)} windows, {len(offs)} offsets/window ===", flush=True)
        slugs = d.slug.tolist(); B = 120
        for i in range(0, len(slugs), B):
            chunk = d.iloc[i:i + B]
            cmin = int(chunk.slot_start_us.min()) - 2_000_000; cmax = int(chunk.slot_end_us.max()) + 2_000_000
            bbo = load_orderbook_bbo(coin, slugs=set(chunk.slug), min_ts_us=cmin, max_ts_us=cmax, columns=BCOLS)
            bk = {}
            for (sl, oc), g in bbo.groupby(["slug", "outcome"]):
                g = g.sort_values("timestamp_us")
                bk[(sl, oc)] = (g.timestamp_us.values.astype("int64"), g.best_ask.values.astype(float),
                                g.best_bid.values.astype(float), g.best_ask_size.values.astype(float),
                                g.best_bid_size.values.astype(float))
            for _, r in chunk.iterrows():
                ss = int(r.slot_start_us); send = int(r.slot_end_us)
                si = asof_idx(ts_k, ss)
                if si < VOL_LB + 5: continue
                strike = px_k[si]
                if not (strike > 0): continue
                up = bk.get((r.slug, "Up")); dn = bk.get((r.slug, "Down"))
                if up is None or dn is None: continue
                d5 = (px_k[asof_idx(ts_k, ss + 5_000_000)] / strike - 1.0) * 1e4
                for off in offs:
                    t = ss + off * 1_000_000
                    ti = asof_idx(ts_k, t)
                    if ti < VOL_LB or ti >= len(px_k): continue
                    tau = wsec - off
                    if tau < EXIT_S + 5: continue
                    sigma = np.std(np.diff(lpx[ti - VOL_LB:ti + 1]))
                    if not (sigma > 0): continue
                    price_t = px_k[ti]
                    z = math.log(price_t / strike) / (sigma * math.sqrt(tau))
                    imp_up = float(Phi(z))

                    def book_at(arr, when):
                        tt, ask, bid, asz, bsz = arr
                        j = np.searchsorted(tt, when, "right") - 1
                        if j < 0 or j >= len(tt): return None
                        return ask[j], bid[j], asz[j], bsz[j]
                    bu = book_at(up, t + LAT_US); bd = book_at(dn, t + LAT_US)
                    if bu is None or bd is None: continue
                    ua, ub, uasz, _ubsz = bu; da, db_, dasz, _dbsz = bd
                    polyup = []
                    if np.isfinite(ua) and np.isfinite(ub): polyup.append((ua + ub) / 2)
                    if np.isfinite(da) and np.isfinite(db_): polyup.append(1 - (da + db_) / 2)
                    if not polyup: continue
                    poly_p_up = float(np.mean(polyup))
                    gap = imp_up - poly_p_up
                    dirn = "Up" if gap > 0 else "Down"
                    arr = up if dirn == "Up" else dn
                    ts_a, ask_a, bid_a, asz_a, bsz_a = arr
                    ent = entry_fill(ts_a, ask_a, asz_a, t + LAT_US, STAKE, SPREAD, bid_a)
                    if ent is None: continue
                    ev = ent["ev"]; shares = ent["shares"]; eidx = ent["entry_idx"]
                    ext = min(t + EXIT_S * 1_000_000, send)
                    won = (r.outcome == dirn)
                    ef = exit_fill(ts_a, bid_a, bsz_a, eidx, ext, shares, ev, won)
                    hour = (t // 1_000_000 % 86_400) // 3600
                    ROWS.append(dict(coin=coin, tf=tf, slug=r.slug, off=off, t_us=t, hour=hour,
                                     strike=strike, price_t=price_t, sigma_bps=sigma * 1e4, tau=tau,
                                     imp_up=imp_up, poly_p_up=poly_p_up, gap=gap, abs_gap=abs(gap),
                                     dirn=dirn, ev=ev, sell=ef["sell_px"], shares=shares, won=won,
                                     pnl60=ef["pnl"], frac_held=ef["frac_held"], held_full=ef["held_full"],
                                     d5_bps=d5))
            del bbo, bk
        F = pd.DataFrame(ROWS); F.to_parquet(outp)
        ct = F[(F.coin == coin) & (F.tf == tf)]
        q8 = ct[ct.abs_gap >= 0.08].sort_values(["slug", "off"]).drop_duplicates("slug", keep="first") if len(ct) else ct
        print(f"  [ckpt] {coin} {tf}: grid_rows={len(ct)}  |gap|>=.08 firstcross "
              f"ALL {cell(q8.pnl60.values) if len(q8) else 'n=0'} | "
              f"CLEAN {cell(q8[q8.frac_held == 0].pnl60.values) if len(q8) else 'n=0'}", flush=True)

F = pd.DataFrame(ROWS); F.to_parquet(outp)
print(f"\nsaved {len(F)} grid rows -> {outp.name}")


def dual(sub):
    return f"ALL {cell(sub.pnl60.values)} | CLEAN {cell(sub[sub.frac_held == 0].pnl60.values)}"


print(f"\n===== FVG first-cross (1 entry/window) — pooled {'+'.join(COINS)} {'+'.join(TFS)}, vol_lb={VOL_LB} =====")
for thr in [0.04, 0.06, 0.08, 0.10, 0.12]:
    q = F[F.abs_gap >= thr].sort_values(["slug", "off"]).drop_duplicates("slug", keep="first")
    offmean = q.off.mean() if len(q) else np.nan
    print(f"  |gap|>={thr:.2f}  {dual(q)}  mean_off={offmean:.0f}s")
print("\n  -- |gap|>=0.08 split open(+5..60) vs mid(>=120) --")
q = F[F.abs_gap >= 0.08].sort_values(["slug", "off"]).drop_duplicates("slug", keep="first")
print(f"     OPEN  off<120  {dual(q[q.off < 120])}")
print(f"     MID   off>=120 {dual(q[q.off >= 120])}")
print("\nREAD: if MID (off>=120) $/tr>0 CI>0 at some threshold -> real mid-window FVG scalp. CAVEAT: BBO top-of-book.")
