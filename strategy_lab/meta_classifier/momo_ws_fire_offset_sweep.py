"""Momo backtest — sweep fire-time offset using REAL WS L25 parquet books.

Hypothesis: production fires at slug_ws+120s, but the alpha thesis ("t+120 of
market") with strike at slug_ws-60 actually means fire at slug_ws+60s. The
extra 60 seconds let the Polymarket book absorb the move, killing the alpha.

Approach: for each fire-offset in {0, 30, 60, 90, 120, 150, 180s}, simulate
the full momo strategy using the parquet WS book at that exact moment.
Output PnL per cell per offset to find where alpha lives.

ret_2m anchor: (ws-60, ws+60) — verified predictive (89% top-decile hit).
Gate: rolling 14d q90 |ret_2m| per (asset, tf).
Notional: $25, fee 2% on profit.
HOLD-only (no exit-policy intervention).
"""
from __future__ import annotations
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "strategy_lab"))
from book_walk import book_walk_fill  # noqa

REFRESH = ROOT / "data" / "v4" / "refresh_2026_05_06"
CACHE = REFRESH / "cache"
OUT = ROOT / "strategy_lab" / "results" / "meta_classifier"
OUT.mkdir(parents=True, exist_ok=True)

LEVELS = 25
NOTIONAL = 25.0
FEE = 0.02
SPREAD_FILTER = {"BTC": 0.02, "ETH": 0.02, "SOL": 0.025}
GATE_Q = 0.90
LOOKBACK = 14
OFFSETS_S = [0, 30, 60, 90, 120, 150, 180]

ASSET_BIN = {"BTC": "BINANCE_SPOT_BTC_USDT", "ETH": "BINANCE_SPOT_ETH_USDT", "SOL": "BINANCE_SPOT_SOL_USDT"}
ASSET_OKX = {"BTC": "OKX_SPOT_BTC_USDT", "ETH": "OKX_SPOT_ETH_USDT", "SOL": "OKX_SPOT_SOL_USDT"}


def load_klines() -> dict[str, pd.DataFrame]:
    df = pd.read_csv(REFRESH / "klines_full.csv")
    df["ts_s"] = (df.time_period_start_us // 1_000_000).astype("int64")
    out = {}
    for a in ("BTC","ETH","SOL"):
        b = df[df.symbol_id == ASSET_BIN[a]][["ts_s","price_close"]].copy(); b["src"]="b"
        o = df[df.symbol_id == ASSET_OKX[a]][["ts_s","price_close"]].copy(); o["src"]="o"
        c = pd.concat([b,o]).sort_values(["ts_s","src"]).drop_duplicates("ts_s",keep="first").sort_values("ts_s").reset_index(drop=True)
        out[a] = c[["ts_s","price_close"]]
    return out


def asof(k, ts):
    """End-time-indexed (1MIN bars). Avoids 60s lookahead bug."""
    end_us = (k.ts_s.astype("int64") + 60).values * 1_000_000
    target_us = int(ts) * 1_000_000
    idx = int(np.searchsorted(end_us, target_us, side="right")) - 1
    return float("nan") if idx < 0 else float(k.price_close.iloc[idx])


def load_universe() -> pd.DataFrame:
    m = pd.read_csv(REFRESH / "markets_full.csv")
    r = pd.read_csv(REFRESH / "market_resolutions_full.csv")[["slug","outcome"]]
    df = m.merge(r, on="slug", how="inner", suffixes=("_m","")).copy()
    df = df.dropna(subset=["outcome"])
    df = df[df.ticker.isin(["BTC","ETH","SOL"]) & df.timeframe.isin(["5m","15m"])].copy()
    df["ws"] = df.slug.str.extract(r"-(\d+)$")[0].astype("int64")
    df["asset"] = df.ticker
    df["tf"] = df.timeframe
    df["window_s"] = df.tf.map({"5m": 300, "15m": 900})
    return df[["slug","asset","tf","ws","window_s","outcome"]].reset_index(drop=True)


def compute_ret_2m(uni, klines):
    """Anchor (ws-60, ws+60) — the predictive anchor verified in _sanity_gate.py."""
    out = []
    for asset, ws in zip(uni.asset.values, uni.ws.values):
        c0 = asof(klines[asset], int(ws) - 60)
        c2 = asof(klines[asset], int(ws) + 60)
        if math.isfinite(c0) and math.isfinite(c2) and c0 > 0 and c2 > 0:
            out.append(math.log(c2 / c0))
        else:
            out.append(float("nan"))
    return out


def compute_thresholds(uni: pd.DataFrame) -> dict:
    out: dict = {}
    uni = uni.copy(); uni["day"] = pd.to_datetime(uni.ws, unit="s").dt.floor("D")
    for (a, t), g in uni.groupby(["asset","tf"]):
        g = g.sort_values("ws").reset_index(drop=True)
        for day, _ in g.groupby("day"):
            cutoff_lo = day - pd.Timedelta(days=LOOKBACK)
            train = g[(g.day >= cutoff_lo) & (g.day < day)]
            samples = train["abs_ret_2m"].dropna().values
            out[(a,t,str(day.date()))] = float(np.quantile(samples, GATE_Q)) if len(samples) >= 50 else float("nan")
    return out


def load_books_for_slugs(asset: str, slugs: set) -> dict:
    """Return {(slug, outcome, ts_us): (ask_p[25], ask_s[25], bid_p[25], bid_s[25])}.

    Streamed once; we'll later index by slug+outcome to find closest snapshot to fire_us.
    Index by (slug, outcome) → list of (ts_us, ask_p, ask_s, bid_p, bid_s) sorted by ts.
    """
    pf = pq.ParquetFile(CACHE / f"{asset.lower()}_orderbook_L25.parquet")
    cols_keep = ["timestamp_us","slug","outcome"] + \
                [f"ask_price_{i}" for i in range(LEVELS)] + [f"ask_size_{i}" for i in range(LEVELS)] + \
                [f"bid_price_{i}" for i in range(LEVELS)] + [f"bid_size_{i}" for i in range(LEVELS)]
    chunks = []
    for batch in pf.iter_batches(batch_size=500_000, columns=cols_keep):
        df = batch.to_pandas()
        flt = df[df.slug.isin(slugs)]
        if len(flt):
            chunks.append(flt)
    raw = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()
    if raw.empty:
        return {}
    out: dict[tuple, list] = {}
    cols_ap = [f"ask_price_{i}" for i in range(LEVELS)]
    cols_as = [f"ask_size_{i}" for i in range(LEVELS)]
    cols_bp = [f"bid_price_{i}" for i in range(LEVELS)]
    cols_bs = [f"bid_size_{i}" for i in range(LEVELS)]
    raw = raw.sort_values(["slug","outcome","timestamp_us"])
    for slug, oc, sub in [(s, o, raw[(raw.slug==s)&(raw.outcome==o)]) for s in raw.slug.unique() for o in ("Up","Down")]:
        if len(sub) == 0:
            continue
        ts = sub.timestamp_us.values
        ap = sub[cols_ap].to_numpy(dtype=float); as_ = sub[cols_as].to_numpy(dtype=float)
        bp = sub[cols_bp].to_numpy(dtype=float); bs = sub[cols_bs].to_numpy(dtype=float)
        out[(slug, oc)] = (ts, ap, as_, bp, bs)
    return out


def find_book(idx, slug, outcome, fire_us, max_dt_us=10_000_000):
    rec = idx.get((slug, outcome))
    if rec is None:
        return None
    ts, ap, as_, bp, bs = rec
    pos = np.searchsorted(ts, fire_us)
    candidates = []
    if pos > 0: candidates.append(pos-1)
    if pos < len(ts): candidates.append(pos)
    best_i = None; best_dt = float("inf")
    for i in candidates:
        dt = abs(int(ts[i]) - fire_us)
        if dt < best_dt:
            best_dt = dt; best_i = i
    if best_i is None or best_dt > max_dt_us:
        return None
    return (ap[best_i], as_[best_i], bp[best_i], bs[best_i], best_dt)


def simulate_at_offset(uni_gated: pd.DataFrame, books_by_asset: dict, offset_s: int):
    """Simulate HOLD pnl for each gated trade using book at slug_ws + offset_s."""
    rows = []
    for r in uni_gated.itertuples(index=False):
        signal = "UP" if r.ret_2m > 0 else "DOWN"
        held = "Up" if signal == "UP" else "Down"
        idx = books_by_asset[r.asset]
        fire_us = int(r.ws + offset_s) * 1_000_000
        b = find_book(idx, r.slug, held, fire_us)
        if b is None:
            continue
        ap, as_, bp, bs, dt_us = b
        ask0 = ap[0] if math.isfinite(ap[0]) else float("nan")
        bid0 = bp[0] if math.isfinite(bp[0]) else float("nan")
        if math.isfinite(ask0) and math.isfinite(bid0):
            spread = ask0 - bid0
            if spread > SPREAD_FILTER[r.asset]:
                continue
        vwap, shares, usd, hits, under = book_walk_fill(ap, as_, NOTIONAL)
        if shares <= 0 or (under and usd < NOTIONAL * 0.5):
            continue
        won = (signal == "UP" and r.outcome == "Up") or (signal == "DOWN" and r.outcome == "Down")
        if won:
            profit = shares * 1.0 - usd
            fee = profit * FEE if profit > 0 else 0.0
            pnl = profit - fee
        else:
            pnl = -usd
        rows.append(dict(slug=r.slug, asset=r.asset, tf=r.tf, ws=int(r.ws), offset_s=offset_s,
                         signal=signal, outcome=r.outcome, won=int(won),
                         ask0=ask0, bid0=bid0, vwap_e=vwap, shares=shares, usd_spent=usd,
                         dt_us=int(dt_us), pnl=pnl))
    return rows


def main():
    print("[1] klines + universe + ret_2m…")
    klines = load_klines()
    uni = load_universe()
    uni["ret_2m"] = compute_ret_2m(uni, klines)
    uni["abs_ret_2m"] = uni.ret_2m.abs()
    print(f"    universe: {len(uni)} resolved markets")

    print("[2] thresholds (rolling 14d q90 per asset/tf/day)…")
    thr = compute_thresholds(uni)
    uni["day"] = pd.to_datetime(uni.ws, unit="s").dt.floor("D")
    uni["threshold"] = uni.apply(lambda r: thr.get((r.asset, r.tf, str(r.day.date())), float("nan")), axis=1)
    gated = uni[(uni.abs_ret_2m >= uni.threshold)].copy()
    print(f"    gated (above threshold): {len(gated)}")

    print("[3] loading parquet books (per asset)…")
    books_by_asset = {}
    for a in ("BTC","ETH","SOL"):
        slugs = set(gated[gated.asset == a].slug.unique())
        print(f"    {a}: streaming for {len(slugs)} slugs…")
        books_by_asset[a] = load_books_for_slugs(a, slugs)
        print(f"      indexed {len(books_by_asset[a])} (slug, outcome) keys")

    print("[4] simulating each fire-time offset…")
    all_rows = []
    for off in OFFSETS_S:
        rows = simulate_at_offset(gated, books_by_asset, off)
        all_rows.extend(rows)
        print(f"    offset={off:>3}s: fires={len(rows)}")

    df = pd.DataFrame(all_rows)
    df.to_csv(OUT / "momo_ws_fire_offset_sweep_per_trade.csv", index=False)

    # Per-cell per-offset aggregation
    agg = df.groupby(["asset","tf","offset_s"]).agg(
        n=("pnl","size"), wins=("won","sum"), hit=("won","mean"),
        pnl_total=("pnl","sum"), pnl_mean=("pnl","mean"), pnl_std=("pnl","std"),
        avg_vwap=("vwap_e","mean"), avg_dt_us=("dt_us","mean"),
    ).reset_index()
    agg.to_csv(OUT / "momo_ws_fire_offset_sweep_aggregated.csv", index=False)

    print(f"\n=== Per-cell PnL by fire-time offset (parquet WS books, $25 notional, HOLD) ===")
    pivot_pnl = agg.pivot_table(index=["asset","tf"], columns="offset_s", values="pnl_total", aggfunc="first")
    pivot_n = agg.pivot_table(index=["asset","tf"], columns="offset_s", values="n", aggfunc="first")
    pivot_hit = agg.pivot_table(index=["asset","tf"], columns="offset_s", values="hit", aggfunc="first")
    pivot_vwap = agg.pivot_table(index=["asset","tf"], columns="offset_s", values="avg_vwap", aggfunc="first")
    print(f"\n--- pnl_total ---\n{pivot_pnl.round(0).fillna(0)}\n")
    print(f"--- n_trades ---\n{pivot_n.fillna(0).astype(int)}\n")
    print(f"--- hit_rate ---\n{pivot_hit.round(3).fillna(0)}\n")
    print(f"--- avg_vwap ---\n{pivot_vwap.round(3).fillna(0)}\n")

    # Total across all cells per offset
    tot = df.groupby("offset_s").agg(
        n=("pnl","size"), pnl_total=("pnl","sum"), pnl_mean=("pnl","mean"),
        hit=("won","mean"), avg_vwap=("vwap_e","mean"),
    ).reset_index()
    print(f"=== TOTAL across all 6 cells ===")
    print(tot.to_string(index=False))


if __name__ == "__main__":
    main()
