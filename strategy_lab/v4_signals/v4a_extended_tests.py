"""V4-A extended: 15m markets, composite signals, V3 conditional overlay test."""
from __future__ import annotations
import numpy as np
import pandas as pd
from pathlib import Path
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[2]
FUNDING = ROOT / "data" / "v4" / "funding"
OI      = ROOT / "data" / "v4" / "oi"
PM_DIR  = ROOT / "strategy_lab" / "data" / "polymarket"
ASSETS = ["btc", "eth", "sol"]


def load_funding(asset):
    sym = f"{asset.upper()}USDT"
    df = pd.read_parquet(FUNDING / f"{sym}.parquet").copy().sort_values("fundingTime").reset_index(drop=True)
    df["fundingTime_unix"] = df["fundingTime"].astype("int64") // 10**9
    return df


def load_oi(asset):
    sym = f"{asset.upper()}USDT"
    df = pd.read_parquet(OI / f"{sym}.parquet").copy()
    df["create_time"] = pd.to_datetime(df["create_time"], utc=True)
    df["create_time_unix"] = df["create_time"].astype("int64") // 10**9
    return df.sort_values("create_time_unix").reset_index(drop=True)


def asof_lookup(values, times, query_times):
    idx = np.searchsorted(times, query_times, side="right") - 1
    return np.where(idx >= 0, values.to_numpy()[np.maximum(idx, 0)], np.nan)


def asof_at_offset(values, times, query_times, offset_sec):
    return asof_lookup(values, times, query_times - offset_sec)


def build(asset, timeframe):
    df = pd.read_csv(PM_DIR / f"{asset}_features_v3.csv")
    df = df.dropna(subset=["outcome_up", "ret_5m", "ret_15m", "ret_1h", "window_start_unix"])
    df = df[df["timeframe"] == timeframe].copy()
    f = load_funding(asset); o = load_oi(asset)
    q = df["window_start_unix"].to_numpy()
    f_t = f["fundingTime_unix"].to_numpy()
    o_t = o["create_time_unix"].to_numpy()
    df["funding_rate"]        = asof_lookup(f["fundingRate"], f_t, q)
    df["funding_rate_4h_ago"] = asof_at_offset(f["fundingRate"], f_t, q, 4*3600)
    df["funding_rate_chg_4h"] = df["funding_rate"] - df["funding_rate_4h_ago"]
    oi_now = asof_lookup(o["sum_open_interest"], o_t, q)
    oi_15  = asof_at_offset(o["sum_open_interest"], o_t, q, 15*60)
    oi_1h  = asof_at_offset(o["sum_open_interest"], o_t, q, 60*60)
    df["oi_chg_15m"] = (oi_now - oi_15) / oi_15
    df["oi_chg_1h"]  = (oi_now - oi_1h) / oi_1h
    df["top_ls_ratio"]    = asof_lookup(o["sum_toptrader_long_short_ratio"], o_t, q)
    df["retail_ls_ratio"] = asof_lookup(o["count_long_short_ratio"], o_t, q)
    df["smart_minus_retail_ext"] = df["top_ls_ratio"] - df["retail_ls_ratio"]
    df["taker_lvol_ratio"]    = asof_lookup(o["sum_taker_long_short_vol_ratio"], o_t, q)
    df["asset"] = asset
    return df


def ic_one(s, y):
    sub = pd.concat([s, y], axis=1).dropna()
    if len(sub) < 30: return np.nan, np.nan, len(sub)
    r, p = spearmanr(sub.iloc[:, 0], sub.iloc[:, 1])
    return r, p, len(sub)


def ic_table(df, features, target="outcome_up"):
    rows = []
    for f in features:
        r, p, n = ic_one(df[f], df[target])
        rows.append({"feat": f, "n": n, "ic": r, "p": p})
    return pd.DataFrame(rows).sort_values("ic", key=lambda s: s.abs(), ascending=False)


def report_table(label, df, features):
    print(f"\n=== {label} (n={len(df)}, baseline UP={df['outcome_up'].mean():.3f}) ===")
    ic = ic_table(df, features)
    for _, r in ic.iterrows():
        sig = "***" if r["p"] < 0.001 else ("**" if r["p"] < 0.01 else ("*" if r["p"] < 0.05 else " "))
        print(f"  {r['feat']:<28} n={r['n']:>4d} ic={r['ic']:+.4f} p={r['p']:.3f} {sig}")


def main():
    feats = ["funding_rate", "funding_rate_chg_4h", "oi_chg_15m", "oi_chg_1h",
             "top_ls_ratio", "retail_ls_ratio", "smart_minus_retail_ext", "taker_lvol_ratio"]

    # === Test 1: 15m polymarket markets (longer horizon, may give funding more time) ===
    print(">>> TEST 1: 15min Polymarket markets (was 5m before)")
    frames = [build(a, "15m") for a in ASSETS]
    big15 = pd.concat(frames, ignore_index=True)
    report_table("15m POOLED", big15, feats)

    # === Test 2: Composite "positioning aligned" signal ===
    print("\n\n>>> TEST 2: Composite signals (5m + 15m pooled)")
    frames = [build(a, "5m") for a in ASSETS] + [build(a, "15m") for a in ASSETS]
    big = pd.concat(frames, ignore_index=True)

    # Aligned-bullish: funding>0, oi rising, top_ls>1, retail_ls<1 (smart bullish, retail bearish)
    big["bull_aligned"] = (
        (big["funding_rate"] > 0).astype(int) +
        (big["oi_chg_1h"] > 0).astype(int) +
        (big["top_ls_ratio"] > 1).astype(int) +
        (big["retail_ls_ratio"] < 1).astype(int)
    )
    big["bear_aligned"] = (
        (big["funding_rate"] < 0).astype(int) +
        (big["oi_chg_1h"] < 0).astype(int) +
        (big["top_ls_ratio"] < 1).astype(int) +
        (big["retail_ls_ratio"] > 1).astype(int)
    )
    big["positioning_score"] = big["bull_aligned"] - big["bear_aligned"]
    big["fade_score"] = -big["positioning_score"]  # mean-reversion hypothesis

    print("  Composite signals (Spearman IC vs outcome_up):")
    for f in ["bull_aligned", "bear_aligned", "positioning_score", "fade_score"]:
        r, p, n = ic_one(big[f], big["outcome_up"])
        sig = "***" if p < 0.001 else ("**" if p < 0.01 else ("*" if p < 0.05 else " "))
        print(f"    {f:<25} n={n} ic={r:+.4f} p={p:.4g} {sig}")

    print("\n  positioning_score buckets (extreme alignment vs outcome):")
    for score in sorted(big["positioning_score"].dropna().unique()):
        sub = big[big["positioning_score"] == score]
        print(f"    score={score:+.0f}  n={len(sub):>4d}  hit={sub['outcome_up'].mean():.3f}")

    # === Test 3: V3 conditional overlay — does funding/OI improve V3's hit rate? ===
    print("\n\n>>> TEST 3: V3 conditional overlay (funding-z gates V3 magnitude sniper)")

    # V3 fires per asset cell (BTC q10, ETH q5, SOL q15). Test whether trades that ALSO have
    # funding aligned with the price-action direction hit better than baseline V3.
    print("\n  Compute V3 fires (5m only), then segment by funding alignment with ret_5m sign:")

    # 5m only for V3
    pm5_frames = [build(a, "5m") for a in ASSETS]
    cells = {"btc": 0.10, "eth": 0.05, "sol": 0.15}
    for a, pm in zip(ASSETS, pm5_frames):
        thr = pm["ret_5m"].abs().quantile(1 - cells[a])
        fired = pm[pm["ret_5m"].abs() >= thr].copy()
        # Direction predicted = sign(ret_5m). UP if ret_5m>0.
        # Funding "aligned with direction" = sign(funding_rate) == sign(ret_5m)
        aligned = np.sign(fired["funding_rate"]) == np.sign(fired["ret_5m"])
        oi_aligned = np.sign(fired["oi_chg_15m"]) == np.sign(fired["ret_5m"])
        smart_aligned = ((fired["top_ls_ratio"] > 1) & (fired["ret_5m"] > 0)) | \
                        ((fired["top_ls_ratio"] < 1) & (fired["ret_5m"] < 0))

        # Outcome hit = predicted direction matches actual
        pred_up = fired["ret_5m"] > 0
        actual_up = fired["outcome_up"] == 1
        hit = (pred_up & actual_up) | (~pred_up & ~actual_up)

        print(f"\n  -- {a.upper()} V3 fires n={len(fired)} baseline_hit={hit.mean():.3f} --")
        for label, mask in [
            ("funding_aligned",       aligned),
            ("funding_NOT_aligned",  ~aligned),
            ("oi15_aligned",          oi_aligned),
            ("oi15_NOT_aligned",     ~oi_aligned),
            ("top_ls_aligned",        smart_aligned),
            ("top_ls_NOT_aligned",   ~smart_aligned),
            ("funding_AND_oi_aligned", aligned & oi_aligned),
        ]:
            sub = fired[mask]
            if len(sub) < 5:
                print(f"    {label:<28} n={len(sub):>3d} (skip)")
                continue
            sub_hit = ((sub["ret_5m"] > 0) == (sub["outcome_up"] == 1)).mean()
            delta = sub_hit - hit.mean()
            print(f"    {label:<28} n={len(sub):>3d} hit={sub_hit:.3f}  delta_vs_baseline={delta:+.3f}")


if __name__ == "__main__":
    main()
