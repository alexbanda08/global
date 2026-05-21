"""
Within-slug fill-timing decoder.

For each reference wallet:
  1. Load fills.parquet (has `offset_from_slot_start_s`, book state at fill)
  2. Distribution of offsets — when in slug do they fire?
  3. Per-fill binance leading features (ret_5s, ret_30s, abs_ret_5s, vol_5m)
     — compute by joining ts_s to binance 1s/1m klines via asof
  4. Side-direction analysis: buy vs sell timing, paired-vs-single
  5. Compare wallet patterns side-by-side

Outputs:
  _wallet_fill_timing_offsets.csv  — fills × offset buckets per wallet
  _wallet_fill_timing_features.csv — per-fill enriched (offset + binance lead)
  _wallet_fill_timing_summary.csv  — one row per wallet × tf with key stats

Usage:
    py -3 -X utf8 strategy_lab/backtests/within_slug_timing.py
"""
from __future__ import annotations
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "strategy_lab" / "backtests"
CACHE_DIR = ROOT / "strategy_lab" / "wallet_hunt" / "cache"
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
from load import load_klines_asof  # noqa: E402

WALLETS = [
    ("0x04b6d7e9", "MAS"),
    ("0xeebde7a0", "HYBRID (Bonereaper)"),
    ("0x89b5cdaa", "directional MAS (ohanism)"),
    ("0xcfb103c3", "PAT (xuanxuan008)"),
    ("0xce25e214", "mixed taker"),
]


def asof_close(target_us_arr: np.ndarray, end_us: np.ndarray,
               close: np.ndarray) -> np.ndarray:
    """Vector asof: return close of bar that ended at-or-before each target."""
    out = np.full(len(target_us_arr), np.nan, dtype="float64")
    if len(end_us) == 0:
        return out
    idx = np.searchsorted(end_us, target_us_arr, side="right") - 1
    mask = idx >= 0
    out[mask] = close[idx[mask]]
    return out


def add_binance_leading(df: pd.DataFrame) -> pd.DataFrame:
    """Add ret_60s, ret_120s, abs versions, vol_5m using 1m binance klines.
    Anchors on ts_s of the fill (when the wallet actually fired)."""
    end_us, close = load_klines_asof("BTC", "binance-spot-ws", "1MIN")
    ts_us = (df["ts_s"].values.astype("int64") * 1_000_000)

    p_now = asof_close(ts_us, end_us, close)
    p_60 = asof_close(ts_us - 60 * 1_000_000, end_us, close)
    p_120 = asof_close(ts_us - 120 * 1_000_000, end_us, close)

    with np.errstate(invalid="ignore", divide="ignore"):
        df["binance_at_fire"] = p_now
        df["ret_60s_at_fire"] = np.log(p_now / p_60)
        df["ret_120s_at_fire"] = np.log(p_now / p_120)
        df["abs_ret_60s_at_fire"] = np.abs(df["ret_60s_at_fire"])
        df["abs_ret_120s_at_fire"] = np.abs(df["ret_120s_at_fire"])

    # vol_5m = std of 1m log-returns over 5 bars ending at ts
    n_total = len(end_us)
    log_rets = np.full(n_total, np.nan, dtype="float64")
    log_rets[1:] = np.log(close[1:] / close[:-1])
    idx = np.searchsorted(end_us, ts_us, side="right") - 1
    vol5 = np.full(len(ts_us), np.nan, dtype="float64")
    vol10 = np.full(len(ts_us), np.nan, dtype="float64")
    for i, j in enumerate(idx):
        if j >= 5 and not np.isnan(log_rets[j-4:j+1]).any():
            vol5[i] = log_rets[j-4:j+1].std()
        if j >= 10 and not np.isnan(log_rets[j-9:j+1]).any():
            vol10[i] = log_rets[j-9:j+1].std()
    df["vol_5m_at_fire"] = vol5
    df["vol_10m_at_fire"] = vol10
    return df


def per_wallet_timing_stats(df: pd.DataFrame, wallet: str, tag: str,
                            tf: str) -> dict:
    """Per-wallet × tf summary."""
    if df.empty:
        return {}
    o = df["offset_from_slot_start_s"]
    w = (df["window_s"] if "window_s" in df.columns else
         pd.Series([300] * len(df), index=df.index))
    pct_into_slot = (o / w).clip(0, 1)

    out = {
        "wallet": wallet,
        "label": tag,
        "tf": tf,
        "n_fills": int(len(df)),
        "n_slugs": int(df["slug"].nunique()),
        "n_buys": int((df["side"].str.upper() == "BUY").sum()),
        "n_sells": int((df["side"].str.upper() == "SELL").sum()),
        "pct_maker": float((df["is_maker"] == True).mean() * 100),
        # Offset stats
        "offset_mean": float(o.mean()),
        "offset_median": float(o.median()),
        "offset_p10": float(o.quantile(0.10)),
        "offset_p25": float(o.quantile(0.25)),
        "offset_p75": float(o.quantile(0.75)),
        "offset_p90": float(o.quantile(0.90)),
        "pct_into_slot_mean": float(pct_into_slot.mean()),
        "pct_into_slot_median": float(pct_into_slot.median()),
        # Bucket fractions
        "frac_first_30s": float((o < 30).mean()),
        "frac_first_60s": float((o < 60).mean()),
        "frac_first_120s": float((o < 120).mean()),
        "frac_last_30s": float((o > (w - 30)).mean()),
        # Binance vol at fire
        "abs_ret_60s_mean": float(df["abs_ret_60s_at_fire"].mean()),
        "abs_ret_120s_mean": float(df["abs_ret_120s_at_fire"].mean()),
        "vol_5m_mean": float(df["vol_5m_at_fire"].mean()),
        # Book state at fire
        "spread_mean": float(df["book_spread"].mean()),
        "ask_size_top_median": float(df["ask_size_top"].median()),
        "bid_size_top_median": float(df["bid_size_top"].median()),
    }
    return out


def offset_buckets(df: pd.DataFrame, wallet: str, tf: str,
                   bucket_s: int = 30) -> pd.DataFrame:
    """Fills per offset bucket per wallet × tf."""
    if df.empty:
        return pd.DataFrame()
    window_s = 300 if tf == "5m" else 900
    bins = list(range(0, window_s + bucket_s, bucket_s))
    df = df.copy()
    df["bucket"] = pd.cut(df["offset_from_slot_start_s"], bins=bins,
                          right=False, labels=[f"{b}-{b+bucket_s}" for b in bins[:-1]])
    buy_counts = df[df["side"].str.upper() == "BUY"].groupby("bucket").size()
    sell_counts = df[df["side"].str.upper() == "SELL"].groupby("bucket").size()
    maker_counts = df[df["is_maker"] == True].groupby("bucket").size()
    taker_counts = df[df["is_maker"] == False].groupby("bucket").size()
    out = pd.DataFrame({
        "wallet": wallet, "tf": tf,
        "bucket_start_s": bins[:-1],
        "bucket_end_s": bins[1:],
        "n_buys": buy_counts.reindex([f"{b}-{b+bucket_s}" for b in bins[:-1]],
                                      fill_value=0).values,
        "n_sells": sell_counts.reindex([f"{b}-{b+bucket_s}" for b in bins[:-1]],
                                       fill_value=0).values,
        "n_maker": maker_counts.reindex([f"{b}-{b+bucket_s}" for b in bins[:-1]],
                                        fill_value=0).values,
        "n_taker": taker_counts.reindex([f"{b}-{b+bucket_s}" for b in bins[:-1]],
                                        fill_value=0).values,
    })
    out["n_total"] = out["n_buys"] + out["n_sells"]
    out["frac_of_total"] = out["n_total"] / max(out["n_total"].sum(), 1)
    return out


def main():
    t0 = time.time()
    print("Loading binance klines (cached after first call) ...")

    summary_rows = []
    bucket_rows = []
    all_fills = []

    for wallet, tag in WALLETS:
        p = CACHE_DIR / wallet / "fills.parquet"
        if not p.exists():
            print(f"  SKIP {wallet}: no fills.parquet")
            continue
        df = pd.read_parquet(p)
        # Filter to BTC
        df = df[df["asset_sym"].str.upper() == "BTC"].copy()
        if df.empty:
            continue

        # Add window_s from slug suffix prefix
        df["tf"] = df["slug"].str.extract(r"-(\d+m)-")[0]
        df["window_s"] = df["tf"].map({"5m": 300, "15m": 900}).fillna(300).astype("int64")

        df = add_binance_leading(df)
        df["wallet"] = wallet
        df["label"] = tag
        all_fills.append(df[[
            "wallet", "label", "slug", "tf", "window_s", "ts_s", "slot_start_s",
            "offset_from_slot_start_s", "side", "outcome", "price", "size",
            "is_maker", "book_ask", "book_bid", "book_spread",
            "ask_size_top", "bid_size_top",
            "binance_at_fire", "ret_60s_at_fire", "ret_120s_at_fire",
            "abs_ret_60s_at_fire", "abs_ret_120s_at_fire",
            "vol_5m_at_fire", "vol_10m_at_fire",
        ]])

        for tf in ["5m", "15m"]:
            sub = df[df["tf"] == tf]
            if sub.empty:
                continue
            row = per_wallet_timing_stats(sub, wallet, tag, tf)
            if row:
                summary_rows.append(row)
            buckets = offset_buckets(sub, wallet, tf, bucket_s=30)
            if not buckets.empty:
                bucket_rows.append(buckets)

    summary_df = pd.DataFrame(summary_rows)
    bucket_df = pd.concat(bucket_rows, ignore_index=True) if bucket_rows else pd.DataFrame()
    fills_df = pd.concat(all_fills, ignore_index=True) if all_fills else pd.DataFrame()

    summary_df.to_csv(OUT_DIR / "_wallet_fill_timing_summary.csv", index=False)
    bucket_df.to_csv(OUT_DIR / "_wallet_fill_timing_offsets.csv", index=False)
    fills_df.to_csv(OUT_DIR / "_wallet_fill_timing_features.csv", index=False)

    # Print summary
    print(f"\n[Done in {time.time()-t0:.1f}s]")
    print(f"  Wrote {OUT_DIR / '_wallet_fill_timing_summary.csv'}  ({len(summary_df)} rows)")
    print(f"  Wrote {OUT_DIR / '_wallet_fill_timing_offsets.csv'}  ({len(bucket_df)} rows)")
    print(f"  Wrote {OUT_DIR / '_wallet_fill_timing_features.csv'}  ({len(fills_df)} rows)")
    print()

    print("=" * 110)
    print("PER-WALLET × TF FILL TIMING SUMMARY")
    print("=" * 110)
    cols = ["wallet", "label", "tf", "n_fills", "n_slugs",
            "offset_median", "pct_into_slot_median",
            "frac_first_30s", "frac_first_60s", "frac_last_30s",
            "abs_ret_60s_mean", "spread_mean"]
    print(summary_df[cols].round(3).to_string(index=False))

    print()
    print("=" * 110)
    print("OFFSET DISTRIBUTION (5m fills, frac per 30s bucket)")
    print("=" * 110)
    for wallet, tag in WALLETS:
        sub = bucket_df[(bucket_df.wallet == wallet) & (bucket_df.tf == "5m")]
        if sub.empty:
            continue
        print(f"\n{wallet} ({tag}):")
        cols = ["bucket_start_s", "bucket_end_s", "n_total", "frac_of_total"]
        # Show only buckets with at least 1% of fills
        s = sub[sub.frac_of_total >= 0.01]
        print(s[cols].round(3).to_string(index=False))


if __name__ == "__main__":
    main()
