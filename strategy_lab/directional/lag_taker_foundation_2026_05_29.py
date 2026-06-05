"""
lag_taker_foundation_2026_05_29.py — FOUNDATION backtest for leg-1 of Buy->Wait->Hedge.

The DIRECTIONAL binance->chainlink oracle-lag taker. Leg 1 IS the edge; quantify it
under the REAL 0.07 fee curve (winner-only) before any lock/hedge overlay.

Signal (replicates oracle_lag.price_delta_bps direction): binance LEADS, chainlink LAGS.
  ret = binance_1s(slot_start+offset) / binance_1s(slot_start) - 1   (intra-window move)
  delta_bps = ret * 1e4   (sign = which side binance is leading toward)
  leading = "Up" if ret>0 else "Down"
Buy the leading side at its L25 best-ask asof fire (the stale resting ask), hold to
chainlink resolution.

Anchor: fire = (slot_start + offset)*1e6. slot_start = int(slug.rsplit('-',1)[1]).
This is the INTRA-WINDOW stale-ask pickoff (NOT a ws_s momentum predictor) — the move
is realized inside the live window; we buy before the book reprices, resolve on the
slot's own chainlink settlement. No lookahead: ask exists at fire, outcome is the slug's.

FEE MODEL (operator-confirmed real Polymarket, winner-only):
  pnl_won  = (1 - vwap) * shares * (1 - 0.07 * vwap)
  pnl_loss = -vwap * shares
Breakeven WR p*: p*(1-vwap)(1-0.07 vwap) = (1-p*) vwap  ->  solve below.

Outputs:
  PART A  lag-predictiveness table (klines-only; threshold X x window W -> directional WR)
  PART B  leg-1 taker backtest (L25 book-walk $25 + 85ms latency + spread filter, 0.07 fee)
          per asset/tf/threshold: n, WR, $/tr, total, maxDD, t-stat; + time-of-day; + IS/OOS
  PART C  breakeven under 0.07 curve (complete-set lock sum threshold)
  fire universe -> strategy_lab/lag_taker_fires_2026_05_29.parquet

Usage: C:/Python314/python.exe strategy_lab/directional/lag_taker_foundation_2026_05_29.py
"""
from __future__ import annotations
import sys
import time
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
OUT.mkdir(parents=True, exist_ok=True)
FIRE_PARQUET = ROOT / "strategy_lab" / "lag_taker_fires_2026_05_29.parquet"

WIN = {"5m": 300, "15m": 900}
SYM = {"BTC": "BINANCE_SPOT_BTC_USDT", "ETH": "BINANCE_SPOT_ETH_USDT", "SOL": "BINANCE_SPOT_SOL_USDT"}
ASSETS = ["BTC", "ETH", "SOL"]
TFS = ["5m", "15m"]

# binance-1s coverage = May 7 21:16 -> May 29 13:16. Bound the backtest there.
LO = int(pd.Timestamp("2026-05-08", tz="UTC").timestamp())
HI = int(pd.Timestamp("2026-05-29 13:00", tz="UTC").timestamp())
IS_CUTOFF = int(pd.Timestamp("2026-05-18", tz="UTC").timestamp())  # ~mid-window split

OFFSET = 5            # seconds into window — sweet spot from prior tests (stale-ask freshest)
PRE_WINDOWS = [30, 60, 120]                  # PART A: pre-fire move windows (s)
THRESHOLDS = [5.0, 10.0, 20.0, 40.0]         # PART A bps grid (lag predictiveness)
B_THRESHOLDS = [2.0, 3.0, 5.0, 8.0, 10.0]    # PART B fire-gate sweep (floor = min)
NOTIONAL = 25.0
SPREAD = 0.05
FEE_RATE = 0.07
CHUNK_DAYS = 5


def binance_1s(asset):
    df = pd.read_parquet(CANON / "klines_1s.parquet",
                         columns=["time_period_start_us", "price_close", "symbol_id", "source", "period_id"])
    df = df[(df.symbol_id == SYM[asset]) & (df.source == "binance-spot-ws")
            & (df.period_id == "1SEC")].sort_values("time_period_start_us")
    return (df.time_period_start_us.values.astype(np.int64) + 1_000_000), df.price_close.values.astype(float)


def asof(ts, v, t):
    i = np.searchsorted(ts, t.astype(np.int64), side="right") - 1
    out = np.full(len(t), np.nan)
    ok = i >= 0
    out[ok] = v[i[ok]]
    return out


def pnl_007(vwap: float, shares: float, won: bool) -> float:
    """Real Polymarket fee: winner-only fee on the winning leg's profit base."""
    if won:
        return (1.0 - vwap) * shares * (1.0 - FEE_RATE * vwap)
    return -vwap * shares


def breakeven_wr(vwap: float) -> float:
    """p* s.t. p*(1-vwap)(1-0.07 vwap) = (1-p*) vwap."""
    g = (1.0 - vwap) * (1.0 - FEE_RATE * vwap)  # win payoff per share
    loss = vwap                                  # loss per share
    return loss / (g + loss)


def stat(x):
    x = np.asarray(x, dtype=float)
    n = len(x)
    if n < 2:
        return (np.nan, np.nan)
    m = float(x.mean())
    se = float(x.std(ddof=1)) / np.sqrt(n)
    return m, (m / se if se else np.nan)


def max_dd(pnl_series: np.ndarray) -> float:
    """Max drawdown of cumulative PnL (most negative peak-to-trough)."""
    if len(pnl_series) == 0:
        return 0.0
    cum = np.cumsum(pnl_series)
    peak = np.maximum.accumulate(cum)
    return float((cum - peak).min())


def run():
    t_all = time.time()
    res = load_resolutions()
    res["slug"] = res["slug"].astype(str)
    bz = {a: binance_1s(a) for a in ASSETS}

    # ---- PART A: lag-predictiveness (klines only, all resolved slugs in window) ----
    # ---- + collect fire records for PART B in the same L25 pass ----
    lag_rows = []   # (asset, tf, window, thr) -> directional WR
    fire_recs = []  # full per-fire universe with fills + pnl

    bounds = list(range(LO, HI, CHUNK_DAYS * 86400)) + [HI]
    for ci in range(len(bounds) - 1):
        clo, chi = bounds[ci], bounds[ci + 1]
        for asset in ASSETS:
            be, bc = bz[asset]
            for tf in TFS:
                pref = f"{asset.lower()}-updown-{tf}-"
                sub = res[(res.ticker == asset) & (res.timeframe == tf)]
                sub = sub[sub.slug.str.startswith(pref)].copy()
                sub["ss"] = sub.slug.str.rsplit("-", n=1).str[-1].astype(np.int64)
                sub = sub[(sub.ss >= clo) & (sub.ss < chi)]
                if sub.empty:
                    continue
                ss = sub.ss.values.astype(np.int64)
                sl = sub.slug.values
                won_up = (sub.outcome.str.lower() == "up").values
                fire = (ss + OFFSET) * 1_000_000
                px_fire = asof(be, bc, fire)

                # PART A: pre-fire move windows -> directional WR (no books)
                for W in PRE_WINDOWS:
                    px_pre = asof(be, bc, (ss + OFFSET - W) * 1_000_000)
                    ret = px_fire / px_pre - 1.0
                    bps = np.abs(ret) * 1e4
                    lead_up = ret > 0
                    correct = (lead_up == won_up)
                    for thr in THRESHOLDS:
                        m = np.isfinite(ret) & (bps >= thr)
                        lag_rows.append((asset, tf, W, thr, int(m.sum()),
                                         float(correct[m].mean()) if m.sum() else np.nan))

                # PART B: L25 fills (use the OFFSET-relative move = production signal)
                px_open = asof(be, bc, ss * 1_000_000)
                ret_off = px_fire / px_open - 1.0
                slugs = set(sl)
                books = load_orderbook_l25_streaming(asset.lower(), slugs=slugs, subsample_1hz=False)
                cfg = LiveMimicConfig()  # 85ms latency, min_book_events=25, book-walk
                for k in range(len(sl)):
                    r = ret_off[k]
                    if not np.isfinite(r) or abs(r) < 1e-12:
                        continue
                    db = abs(r) * 1e4
                    if db < B_THRESHOLDS[0]:      # collection floor = smallest PART B gate (2bps)
                        continue
                    lead = "Up" if r > 0 else "Down"
                    fill = fill_at_book(books, sl[k], lead, int(fire[k]), cfg=cfg,
                                        side="buy", spread_filter=SPREAD, notional_usd=NOTIONAL)
                    if fill is None:
                        continue
                    vwap = float(fill["vwap"])
                    shares = float(fill["shares"])
                    won = (r > 0) == bool(won_up[k])
                    pnl = pnl_007(vwap, shares, won)
                    hour = pd.Timestamp(int(ss[k]), unit="s", tz="UTC").hour
                    fire_recs.append(dict(slug=sl[k], asset=asset, tf=tf,
                                          fire_us=int(fire[k]), slot_start=int(ss[k]),
                                          direction=lead, delta_bps=round(db, 3),
                                          entry_vwap=round(vwap, 5), shares=round(shares, 3),
                                          outcome="Up" if won_up[k] else "Down",
                                          won=bool(won), pnl=round(pnl, 5), hour=int(hour),
                                          period="IS" if ss[k] < IS_CUTOFF else "OOS"))
        print(f"[chunk {pd.to_datetime(clo, unit='s', utc=True):%m-%d}] "
              f"fires={len(fire_recs)} t={time.time()-t_all:.0f}s", flush=True)

    # ===================== PART A output =====================
    A = pd.DataFrame(lag_rows, columns=["asset", "tf", "window_s", "thr_bps", "n", "wr"])
    A_pool = (A.groupby(["window_s", "thr_bps"])
              .apply(lambda g: pd.Series({
                  "n": int(g.n.sum()),
                  "dir_wr_pct": round(100 * float((g.wr * g.n).sum() / g.n.sum()), 2)
                  if g.n.sum() else np.nan}), include_groups=False)
              .reset_index())
    A.to_csv(OUT / "lag_predictiveness_full.csv", index=False)
    A_pool.to_csv(OUT / "lag_predictiveness_pooled.csv", index=False)

    # ===================== PART B output =====================
    F = pd.DataFrame(fire_recs)
    F.to_parquet(FIRE_PARQUET, index=False)

    def cell_stats(g):
        pnl = g.pnl.to_numpy()
        m, t = stat(pnl)
        return pd.Series({
            "n": len(g), "wr_pct": round(100 * g.won.mean(), 1),
            "mean_vwap": round(g.entry_vwap.mean(), 3),
            "pnl_per_tr": round(m, 4), "total": round(pnl.sum(), 1),
            "max_dd": round(max_dd(pnl), 1), "t_stat": round(t, 2),
        })

    # per asset/tf/threshold (cumulative thresholds)
    btab = []
    for thr in B_THRESHOLDS:
        gthr = F[F.delta_bps >= thr]
        for asset in ASSETS:
            for tf in TFS:
                g = gthr[(gthr.asset == asset) & (gthr.tf == tf)]
                if len(g) < 20:
                    continue
                row = {"thr_bps": thr, "asset": asset, "tf": tf}
                row.update(cell_stats(g).to_dict())
                btab.append(row)
    B = pd.DataFrame(btab)
    B.to_csv(OUT / "lag_taker_by_cell.csv", index=False)

    # pooled by threshold (all assets/tfs)
    bp = []
    for thr in B_THRESHOLDS:
        g = F[F.delta_bps >= thr]
        if len(g) < 10:
            continue
        row = {"thr_bps": thr}
        row.update(cell_stats(g).to_dict())
        days = (HI - LO) / 86400
        row["tr_per_day"] = round(len(g) / days, 1)
        bp.append(row)
    BP = pd.DataFrame(bp)

    # IS/OOS by threshold
    bio = []
    for thr in B_THRESHOLDS:
        for per in ["IS", "OOS"]:
            g = F[(F.delta_bps >= thr) & (F.period == per)]
            if len(g) < 10:
                continue
            row = {"thr_bps": thr, "period": per}
            row.update(cell_stats(g).to_dict())
            bio.append(row)
    BIO = pd.DataFrame(bio)

    # time-of-day (UTC hour buckets) at >=3bps gate (candidate sweet spot, adequate n)
    GATE = 3.0
    g10 = F[F.delta_bps >= GATE].copy()
    g10["hbucket"] = pd.cut(g10.hour, bins=[-1, 5, 11, 17, 23],
                            labels=["00-05", "06-11", "12-17", "18-23"])
    tod = (g10.groupby("hbucket", observed=True)
           .apply(lambda g: cell_stats(g), include_groups=False).reset_index())

    # asset breakdown at >=3bps (is it BTC-led?)
    abk = (F[F.delta_bps >= GATE].groupby("asset")
           .apply(lambda g: cell_stats(g), include_groups=False).reset_index())
    tfbk = (F[F.delta_bps >= GATE].groupby("tf")
            .apply(lambda g: cell_stats(g), include_groups=False).reset_index())

    # ===================== PART C: breakeven under 0.07 =====================
    bevs = [(v, round(breakeven_wr(v), 4)) for v in [0.50, 0.55, 0.58, 0.60, 0.65, 0.70, 0.77]]
    # complete-set lock: buy leg1 @ v1, leg2 @ v2, redeem $1, fee 0.07*v_win on winner profit.
    # Worst case the winner is whichever side. Net lock = 1 - (v1+v2) - fee_on_winner.
    # Under 0.07 the fee on the winning leg's profit is tiny; the binding constraint is
    # sum < 1. Compute the sum that nets >=0 assuming winner is the higher-priced leg.
    def lock_net(v1, v2):
        # complete set: hold 1 Up + 1 Down share, redeem $1. One leg wins.
        # winner pays fee = 0.07 * v_win * (1 - v_win) per share (poly curve on settle? no:
        # winner-only-on-profit per task -> fee = 0.07*v_win*(profit)/share. For a complete
        # set the "profit" on the winning leg = (1 - v_win). So fee = 0.07*v_win*(1-v_win).)
        # Net per set = 1 - v1 - v2 - 0.07*max(v1,v2)*(1-max(v1,v2)).
        vw = max(v1, v2)
        return 1.0 - v1 - v2 - FEE_RATE * vw * (1.0 - vw)

    # solve max sum that still nets >=0 for a symmetric-ish split (leg1=0.66, leg2=x)
    lock_examples = []
    for v1 in [0.60, 0.66, 0.70, 0.77]:
        # find max v2 s.t. lock_net(v1,v2)>=0
        v2 = 0.40
        while v2 < 0.45 and lock_net(v1, v2) >= 0:
            v2 += 0.001
        # binary-ish: just scan
        best = None
        for vv in np.arange(0.10, 0.45, 0.001):
            if lock_net(v1, vv) >= 0:
                best = vv
        lock_examples.append((v1, round(best, 3) if best else np.nan,
                              round(v1 + best, 3) if best else np.nan))

    # ---------- console summary ----------
    pd.set_option("display.width", 240)
    print("\n" + "=" * 100)
    print("PART A — LAG PREDICTIVENESS (binance pre-fire move -> directional WR), pooled assets/tfs")
    print("=" * 100)
    piv = A_pool.pivot(index="thr_bps", columns="window_s", values="dir_wr_pct")
    npiv = A_pool.pivot(index="thr_bps", columns="window_s", values="n")
    print("Directional WR % (col=window_s):")
    print(piv.to_string())
    print("\nn fires per cell:")
    print(npiv.to_string())

    print("\n" + "=" * 100)
    print(f"PART B — LEG-1 TAKER (offset {OFFSET}s, $25 walk + 85ms + spread<={SPREAD}, 0.07 fee), POOLED")
    print("=" * 100)
    print(BP.to_string(index=False))
    print("\nIS vs OOS (split @ 05-18):")
    print(BIO.to_string(index=False))
    print("\nBy ASSET (>=3bps):")
    print(abk.to_string(index=False))
    print("\nBy TF (>=3bps):")
    print(tfbk.to_string(index=False))
    print("\nTime-of-day UTC (>=3bps):")
    print(tod.to_string(index=False))
    print("\nPer-cell (asset x tf x threshold), n>=20:")
    print(B.to_string(index=False))

    print("\n" + "=" * 100)
    print("PART C — BREAKEVEN UNDER 0.07 CURVE")
    print("=" * 100)
    print("Single-leg directional taker breakeven WR (p*) by entry vwap:")
    for v, p in bevs:
        print(f"  vwap={v:.2f}  ->  breakeven WR = {100*p:.1f}%")
    print("\nComplete-set LOCK: max leg2 (and sum) that still nets >=0, by leg1 entry:")
    print("  leg1   max_leg2   max_sum (nets>=0 after 0.07 winner fee)")
    for v1, v2, s in lock_examples:
        print(f"  {v1:.2f}    {v2:.3f}      {s:.3f}")
    print("\n(Under 0.07 the lock breakeven sum is ~0.985-0.99 vs ~0.97 under old 2%.)")

    print(f"\nwrote {FIRE_PARQUET}  ({len(F)} fires)")
    print(f"wrote {OUT/'lag_predictiveness_pooled.csv'}, lag_taker_by_cell.csv")
    print(f"total {time.time()-t_all:.0f}s")


if __name__ == "__main__":
    run()
