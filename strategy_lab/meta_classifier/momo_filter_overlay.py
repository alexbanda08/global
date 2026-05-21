"""Momo filter overlay — compute WR + PnL of production momo paper fires under
new filters: hourly, coinbase-premium, kraken-cross, RSI, CVD.

Uses REAL production outcomes from trading_events_30d.parquet (not simulated).
For each fired momo paper trade, attaches features at signal time (ws) and
recomputes WR/PnL for each filter variant.

NEW filters added on top of existing F1-F5 (coinbase variants already validated):
  F6  hour_utc filter        — only fire in high-WR hours (hours where past WR > 55%)
  F7  RSI overbought/oversold — RSI14_at_ws agrees with signal direction
  F8  CVD direction-agree    — Polymarket trade-flow CVD at ws aligns with signal
  F9  cross-venue 3-of-3     — sign(binance ret_2m) == sign(coinbase ret_2m) == sign(kraken ret_2m)
  F10 absolute volatility    — abs_ret_60s_at_ws above vol regime threshold

Output: strategy_lab/results/meta_classifier/momo_filter_overlay.csv
       strategy_lab/reports/MOMO_FILTER_OVERLAY_2026_05_20.md
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.dataset as ds
import pyarrow.parquet as pq

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
from load import load_klines, load_klines_asof  # noqa: E402

OUT_CSV = ROOT / "strategy_lab" / "results" / "meta_classifier" / "momo_filter_overlay.csv"
REPORT = ROOT / "strategy_lab" / "reports" / "MOMO_FILTER_OVERLAY_2026_05_20.md"
OUT_CSV.parent.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Load production momo paper resolutions
# ---------------------------------------------------------------------------

def load_momo_paper() -> pd.DataFrame:
    """All `poly_updown_resolution` events in `paper` mode (real direction bets)."""
    p = ROOT / "data" / "v4" / "canonical" / "trading_events_30d.parquet"
    dataset = ds.dataset(str(p), format="parquet")
    res = dataset.to_table(filter=ds.field("kind") == "poly_updown_resolution").to_pandas()
    res["parsed"] = res.data.apply(lambda s: json.loads(s) if isinstance(s, str) else {})
    res["mode"] = res.parsed.apply(lambda d: d.get("mode"))
    res = res[res["mode"] == "paper"].copy()
    res["won"] = res.parsed.apply(lambda d: d.get("won"))
    res["tf"] = res.parsed.apply(lambda d: d.get("tf"))
    res["symbol"] = res.parsed.apply(lambda d: d.get("symbol"))
    res["signal"] = res.parsed.apply(lambda d: d.get("signal"))
    res["outcome"] = res.parsed.apply(lambda d: d.get("outcome"))
    res["pnl_usd"] = res.parsed.apply(lambda d: float(d.get("pnl_usd") or 0))
    res["condition_id"] = res.parsed.apply(lambda d: d.get("condition_id"))
    res["entry_price"] = res.parsed.apply(lambda d: float(d.get("entry_price") or 0))
    res["entry_qty"] = res.parsed.apply(lambda d: float(d.get("entry_qty") or 0))
    res["at_ts"] = pd.to_datetime(res["at"], utc=True)
    res["ws_s"] = (res.at_ts.astype("int64") // 1_000_000_000)  # second precision
    return res[["symbol", "tf", "signal", "outcome", "won", "pnl_usd",
                "entry_price", "entry_qty", "condition_id",
                "at_ts", "ws_s"]].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Feature attachment
# ---------------------------------------------------------------------------

def attach_basic_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["hour_utc"] = df.at_ts.dt.hour
    df["weekday"] = df.at_ts.dt.weekday
    df["minute_in_hour"] = df.at_ts.dt.minute
    df["sig_int"] = df.signal.map({"UP": 1, "DOWN": -1}).astype("Int64")
    return df


def attach_kline_features(df: pd.DataFrame) -> pd.DataFrame:
    """Attach binance ret_60s, ret_120s, abs_ret, coinbase ret_60s/premium, kraken ret_60s/premium,
    RSI14 (binance 1m). Per-asset vectorized via load_klines_asof."""
    df = df.copy()
    for col in ["bin_close_ws", "bin_ret_60s", "bin_ret_120s", "abs_ret_60s",
                "rsi_14", "coin_close_ws", "coin_ret_60s", "premium_ws",
                "kraken_close_ws", "kraken_ret_60s", "kraken_premium_ws"]:
        df[col] = np.nan

    for asset in ["BTC", "ETH", "SOL"]:
        m = df.symbol == asset
        if not m.any():
            continue
        ws_us = df.loc[m, "ws_s"].values.astype("int64") * 1_000_000

        # Binance
        end_us, close = load_klines_asof(asset, "binance-spot-ws", "1MIN")
        if len(end_us) > 0:
            idx = np.searchsorted(end_us, ws_us, side="right") - 1
            idx_60 = np.searchsorted(end_us, ws_us - 60 * 1_000_000, side="right") - 1
            idx_120 = np.searchsorted(end_us, ws_us - 120 * 1_000_000, side="right") - 1
            p_now = np.where(idx >= 0, close[np.clip(idx, 0, len(close)-1)], np.nan)
            p_60 = np.where(idx_60 >= 0, close[np.clip(idx_60, 0, len(close)-1)], np.nan)
            p_120 = np.where(idx_120 >= 0, close[np.clip(idx_120, 0, len(close)-1)], np.nan)
            df.loc[m, "bin_close_ws"] = p_now
            with np.errstate(invalid="ignore", divide="ignore"):
                df.loc[m, "bin_ret_60s"] = np.log(p_now / p_60)
                df.loc[m, "bin_ret_120s"] = np.log(p_now / p_120)
                df.loc[m, "abs_ret_60s"] = np.abs(df.loc[m, "bin_ret_60s"])

            # RSI14 using 1m closes ending at ws_s
            log_rets = np.full(len(close), np.nan, dtype="float64")
            log_rets[1:] = np.log(close[1:] / close[:-1])
            up = np.where(log_rets > 0, log_rets, 0)
            dn = np.where(log_rets < 0, -log_rets, 0)
            # Simple 14-bar RSI
            n14 = 14
            roll_up = np.full_like(up, np.nan)
            roll_dn = np.full_like(dn, np.nan)
            csu = np.cumsum(up)
            csd = np.cumsum(dn)
            roll_up[n14:] = (csu[n14:] - csu[:-n14]) / n14
            roll_dn[n14:] = (csd[n14:] - csd[:-n14]) / n14
            rsi = np.where(roll_dn > 0, 100 - 100 / (1 + roll_up / np.maximum(roll_dn, 1e-12)), 50.0)
            rsi[:n14] = np.nan
            rsi_vals = np.where(idx >= 0, rsi[np.clip(idx, 0, len(rsi)-1)], np.nan)
            df.loc[m, "rsi_14"] = rsi_vals

        # Coinbase
        end_us_c, close_c = load_klines_asof(asset, "coinbase-spot-ws", "1MIN")
        if len(end_us_c) > 0:
            idx = np.searchsorted(end_us_c, ws_us, side="right") - 1
            idx_60 = np.searchsorted(end_us_c, ws_us - 60 * 1_000_000, side="right") - 1
            pc_now = np.where(idx >= 0, close_c[np.clip(idx, 0, len(close_c)-1)], np.nan)
            pc_60 = np.where(idx_60 >= 0, close_c[np.clip(idx_60, 0, len(close_c)-1)], np.nan)
            df.loc[m, "coin_close_ws"] = pc_now
            with np.errstate(invalid="ignore", divide="ignore"):
                df.loc[m, "coin_ret_60s"] = np.log(pc_now / pc_60)
                df.loc[m, "premium_ws"] = np.log(pc_now / df.loc[m, "bin_close_ws"])

        # Kraken
        try:
            end_us_k, close_k = load_klines_asof(asset, "kraken-spot-ws", "1MIN")
        except Exception:
            end_us_k = np.array([], dtype="int64")
        if len(end_us_k) > 0:
            idx = np.searchsorted(end_us_k, ws_us, side="right") - 1
            idx_60 = np.searchsorted(end_us_k, ws_us - 60 * 1_000_000, side="right") - 1
            pk_now = np.where(idx >= 0, close_k[np.clip(idx, 0, len(close_k)-1)], np.nan)
            pk_60 = np.where(idx_60 >= 0, close_k[np.clip(idx_60, 0, len(close_k)-1)], np.nan)
            df.loc[m, "kraken_close_ws"] = pk_now
            with np.errstate(invalid="ignore", divide="ignore"):
                df.loc[m, "kraken_ret_60s"] = np.log(pk_now / pk_60)
                df.loc[m, "kraken_premium_ws"] = np.log(pk_now / df.loc[m, "bin_close_ws"])
    return df


def attach_cvd_features(df: pd.DataFrame, lookback_s: int = 60) -> pd.DataFrame:
    """Compute Polymarket-side CVD in `lookback_s` before ws_s per (symbol, slug, ws_s).
    Joins trades_polymarket on condition_id (slug → cid map) and counts BUY−SELL volume.
    Sign convention: +CVD = net buying pressure on Up side OR net selling on Down side.

    For simplicity, we sum signed_volume = +size if BUY else -size, on the UP outcome only.
    """
    df = df.copy()
    df["cvd_60s_up"] = np.nan
    df["cvd_60s_dn"] = np.nan

    # Load all trades grouped by asset
    for asset in ["BTC", "ETH", "SOL"]:
        m = df.symbol == asset
        if not m.any():
            continue
        p = ROOT / "data" / "v4" / "canonical" / "trades_polymarket" / f"{asset.lower()}.parquet"
        if not p.exists():
            continue
        # Stream-friendly: filter columns
        pf = pq.ParquetFile(str(p))
        cols = pf.schema.names
        keep_cols = [c for c in ["timestamp_us", "condition_id", "side",
                                  "outcome", "asset", "size", "price"] if c in cols]
        # Build a Pandas DataFrame from streaming
        parts = []
        for rg in range(pf.metadata.num_row_groups):
            try:
                t = pf.read_row_group(rg, columns=keep_cols)
            except Exception:
                continue
            parts.append(t.to_pandas())
        trades = pd.concat(parts, ignore_index=True)
        if "timestamp_us" not in trades or "condition_id" not in trades:
            continue
        trades["ts_s"] = (trades["timestamp_us"] // 1_000_000).astype("int64")
        if "side" in trades.columns:
            trades["side_u"] = trades["side"].astype(str).str.upper()
        else:
            trades["side_u"] = ""
        # signed size: +size for BUY, -size for SELL (taker direction)
        trades["signed"] = np.where(trades["side_u"] == "BUY", trades["size"],
                                     np.where(trades["side_u"] == "SELL", -trades["size"], 0))
        # outcome filter into UP / DOWN
        if "outcome" in trades.columns:
            trades["oc"] = trades["outcome"].astype(str)
        else:
            trades["oc"] = ""

        # For each fire, find trades in window
        sub = df[m].copy().reset_index(drop=False)
        cvd_up = np.full(len(sub), np.nan)
        cvd_dn = np.full(len(sub), np.nan)
        # Group trades by condition_id for fast lookup
        for i, row in sub.iterrows():
            cid = row.condition_id
            ws_s = int(row.ws_s)
            t_cid = trades[trades.condition_id == cid]
            if t_cid.empty:
                continue
            mask = (t_cid.ts_s >= ws_s - lookback_s) & (t_cid.ts_s <= ws_s)
            window = t_cid[mask]
            if window.empty:
                continue
            up_v = window[window.oc.isin(["Up", "UP", "up"])]["signed"].sum()
            dn_v = window[window.oc.isin(["Down", "DOWN", "down"])]["signed"].sum()
            cvd_up[i] = up_v
            cvd_dn[i] = dn_v
        df.loc[sub["index"].values, "cvd_60s_up"] = cvd_up
        df.loc[sub["index"].values, "cvd_60s_dn"] = cvd_dn
    df["cvd_net"] = df["cvd_60s_up"].fillna(0) - df["cvd_60s_dn"].fillna(0)
    return df


# ---------------------------------------------------------------------------
# Filter variants
# ---------------------------------------------------------------------------

# High-WR hours discovered from earlier paper-momo BTC analysis (≥55% WR)
GOOD_HOURS_DEFAULT = {0, 1, 2, 3, 4, 14, 16, 19, 20, 21, 22, 23}
BAD_HOURS_DEFAULT = {5, 6, 7, 8, 10, 11, 13, 17, 18}


def apply_filter(df: pd.DataFrame, variant: str) -> pd.DataFrame:
    """Return df subset matching the variant filter."""
    if variant == "B0":
        return df

    # F1-F5 — coinbase variants (already proven in addalpha engine, replicated here)
    if variant == "F1":  # coinbase premium aligned with signal
        keep = (np.sign(df.premium_ws.fillna(0)) == df.sig_int.fillna(0).astype(int)) & df.premium_ws.notna()
        return df[keep]
    if variant == "F2":  # premium magnitude > 5bp
        return df[df.premium_ws.abs() > 0.0005]
    if variant == "F5":  # binance ret sign == coinbase ret sign
        keep = (np.sign(df.bin_ret_60s.fillna(0)) == np.sign(df.coin_ret_60s.fillna(0))) & \
               df.bin_ret_60s.notna() & df.coin_ret_60s.notna()
        return df[keep]

    # F6 — hour filter (only fire in high-WR hours)
    if variant == "F6":
        return df[df.hour_utc.isin(GOOD_HOURS_DEFAULT)]
    if variant == "F6b":  # SKIP bad hours only (more permissive than F6)
        return df[~df.hour_utc.isin(BAD_HOURS_DEFAULT)]

    # F7 — RSI agrees with signal direction
    if variant == "F7":
        # UP signal + RSI>50 (bullish momentum), DOWN signal + RSI<50 (bearish momentum)
        keep = ((df.signal == "UP") & (df.rsi_14 > 50)) | \
               ((df.signal == "DOWN") & (df.rsi_14 < 50))
        return df[keep & df.rsi_14.notna()]
    if variant == "F7_extreme":  # only extreme RSI
        keep = ((df.signal == "UP") & (df.rsi_14 > 60)) | \
               ((df.signal == "DOWN") & (df.rsi_14 < 40))
        return df[keep & df.rsi_14.notna()]
    if variant == "F7_contrarian":  # fire opposite of RSI (mean reversion)
        keep = ((df.signal == "UP") & (df.rsi_14 < 50)) | \
               ((df.signal == "DOWN") & (df.rsi_14 > 50))
        return df[keep & df.rsi_14.notna()]

    # F8 — CVD direction agrees with signal
    if variant == "F8":
        keep = ((df.signal == "UP") & (df.cvd_60s_up.fillna(0) > 0)) | \
               ((df.signal == "DOWN") & (df.cvd_60s_dn.fillna(0) > 0))
        return df[keep]

    # F9 — kraken cross-venue agreement
    if variant == "F9":
        # binance + coinbase + kraken all agree on direction
        keep = (np.sign(df.bin_ret_60s.fillna(0)) == np.sign(df.coin_ret_60s.fillna(0))) & \
               (np.sign(df.bin_ret_60s.fillna(0)) == np.sign(df.kraken_ret_60s.fillna(0))) & \
               df.bin_ret_60s.notna() & df.coin_ret_60s.notna() & df.kraken_ret_60s.notna()
        return df[keep]

    # F10 — volatility regime filter (high vol periods do better in momo)
    if variant == "F10_lo":  # only LOW vol (calm market = better trend follow)
        thr = df.abs_ret_60s.quantile(0.50)
        return df[df.abs_ret_60s < thr]
    if variant == "F10_hi":  # only HIGH vol
        thr = df.abs_ret_60s.quantile(0.50)
        return df[df.abs_ret_60s >= thr]

    # F11 — combined best filter (F6 + F1 + F7)
    if variant == "F11_combo":
        s1 = df.hour_utc.isin(GOOD_HOURS_DEFAULT)
        s2 = (np.sign(df.premium_ws.fillna(0)) == df.sig_int.fillna(0).astype(int)) & df.premium_ws.notna()
        s3 = ((df.signal == "UP") & (df.rsi_14 > 50)) | ((df.signal == "DOWN") & (df.rsi_14 < 50))
        return df[s1 & s2 & s3]

    raise ValueError(f"unknown variant {variant!r}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

VARIANTS = ["B0",
            "F1", "F2", "F5",
            "F6", "F6b",
            "F7", "F7_extreme", "F7_contrarian",
            "F9",
            "F10_lo", "F10_hi",
            "F11_combo"]


def summarize(df: pd.DataFrame, variant: str) -> dict:
    n = len(df)
    if n == 0:
        return dict(variant=variant, n=0, wr=float("nan"), mean_pnl=float("nan"),
                    sum_pnl=0.0)
    return dict(
        variant=variant,
        n=int(n),
        wr_pct=round((df.won == True).sum() / n * 100, 2),
        mean_pnl=round(float(df.pnl_usd.mean()), 4),
        sum_pnl=round(float(df.pnl_usd.sum()), 2),
    )


def main():
    print("[1] Loading momo paper resolutions ...")
    df = load_momo_paper()
    print(f"    {len(df):,} resolutions, {df.symbol.nunique()} symbols, "
          f"{df.tf.nunique()} tfs")
    print()

    print("[2] Attaching time + kline features ...")
    df = attach_basic_features(df)
    df = attach_kline_features(df)
    print(f"    bin_ret_60s finite: {df.bin_ret_60s.notna().sum()}")
    print(f"    coin_ret_60s finite: {df.coin_ret_60s.notna().sum()}")
    print(f"    kraken_ret_60s finite: {df.kraken_ret_60s.notna().sum()}")
    print(f"    rsi_14 finite: {df.rsi_14.notna().sum()}")
    print()

    print("[3] Attaching CVD features (Polymarket trade flow) ...")
    try:
        df = attach_cvd_features(df, lookback_s=60)
        print(f"    cvd_60s_up finite: {df.cvd_60s_up.notna().sum()}")
    except Exception as e:
        print(f"    CVD attachment failed: {e}; F8 will be skipped")
        df["cvd_60s_up"] = np.nan
        df["cvd_60s_dn"] = np.nan
        df["cvd_net"] = np.nan
    print()

    print("[4] Running filter variants ...")
    rows = []
    for v in VARIANTS:
        try:
            sub = apply_filter(df, v)
        except Exception as e:
            print(f"    {v}: FAILED — {e}")
            continue
        # Per (symbol, tf)
        for sym in ["BTC", "ETH", "SOL"]:
            for tf in ["5m", "15m"]:
                s = sub[(sub.symbol == sym) & (sub.tf == tf)]
                row = summarize(s, v)
                row["symbol"] = sym
                row["tf"] = tf
                row["scope"] = "per_cell"
                rows.append(row)
        # Aggregate
        row = summarize(sub, v)
        row["symbol"] = "ALL"
        row["tf"] = "ALL"
        row["scope"] = "aggregate"
        rows.append(row)

    out = pd.DataFrame(rows)
    out.to_csv(OUT_CSV, index=False)
    print(f"\n    Wrote {OUT_CSV}")
    print()

    print("=" * 90)
    print("AGGREGATE RESULTS BY VARIANT (all symbols/tfs):")
    print("=" * 90)
    agg = out[out.scope == "aggregate"].copy().sort_values("sum_pnl", ascending=False)
    print(agg[["variant", "n", "wr_pct", "mean_pnl", "sum_pnl"]].to_string(index=False))

    print()
    print("=" * 90)
    print("PER-CELL: BTC 15m (winners' cell from production)")
    print("=" * 90)
    btc15 = out[(out.symbol == "BTC") & (out.tf == "15m")].copy().sort_values("sum_pnl", ascending=False)
    print(btc15[["variant", "n", "wr_pct", "mean_pnl", "sum_pnl"]].to_string(index=False))

    print()
    print("=" * 90)
    print("PER-CELL: BTC 5m (largest universe, currently losing)")
    print("=" * 90)
    btc5 = out[(out.symbol == "BTC") & (out.tf == "5m")].copy().sort_values("sum_pnl", ascending=False)
    print(btc5[["variant", "n", "wr_pct", "mean_pnl", "sum_pnl"]].to_string(index=False))

    # Top picks
    print()
    print("=" * 90)
    print("TOP 5 (variant × cell) BY MEAN PnL/fire (min n=50):")
    print("=" * 90)
    cells = out[(out.scope == "per_cell") & (out.n >= 50)].copy()
    top = cells.nlargest(5, "mean_pnl")
    print(top[["variant", "symbol", "tf", "n", "wr_pct", "mean_pnl", "sum_pnl"]].to_string(index=False))


if __name__ == "__main__":
    main()
