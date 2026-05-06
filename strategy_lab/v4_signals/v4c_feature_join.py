"""V4-C feature joiner + IC scan.

Joins Fear & Greed + Reddit sentiment to Polymarket UP/DOWN markets.
Features per market:
  fg_value, fg_change_1d, fg_change_3d (daily granularity)
  reddit_posts_1h, reddit_posts_4h     (post count in lookback window matching asset)
  reddit_avg_score_4h                  (mean post score)
  reddit_pos_kwd_4h, reddit_neg_kwd_4h (positive/negative lexicon hits in titles+selftext)
  reddit_sentiment_4h                  (pos - neg)
"""
from __future__ import annotations
import re
import numpy as np
import pandas as pd
from pathlib import Path
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[2]
SENT = ROOT / "data" / "v4" / "sentiment"
PM_DIR = ROOT / "strategy_lab" / "data" / "polymarket"
ASSETS = ["btc", "eth", "sol"]

# Asset-specific subreddit + keyword filter for cross-sub posts
ASSET_FILTERS = {
    "btc": {"subreddits": ["Bitcoin"], "keywords": ["btc", "bitcoin"]},
    "eth": {"subreddits": ["ethfinance"], "keywords": ["eth ", "ethereum", "ether ", "vitalik"]},
    "sol": {"subreddits": ["solana"], "keywords": ["sol ", "solana"]},
}

POSITIVE_KEYWORDS = ["pump", "moon", "bull", "bullish", "rally", "breakout", "ath",
                     "all-time high", "new high", "rocket", "buying", "long", "accumul",
                     "green", "surge", "soar", "spike", "support held", "bottom in"]
NEGATIVE_KEYWORDS = ["dump", "crash", "bear", "bearish", "sell-off", "selloff", "drop",
                     "drops", "liquidat", "rip", "dead", "rugpull", "rug", "bottom",
                     "selling", "short", "red", "tank", "plummet", "rejected", "broke down",
                     "support broke", "capitulation", "blood"]


def load_fg() -> pd.DataFrame:
    df = pd.read_parquet(SENT / "fear_greed.parquet")
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("timestamp").reset_index(drop=True)


def load_reddit() -> pd.DataFrame:
    df = pd.read_parquet(SENT / "reddit_posts.parquet")
    df["text"] = (df["title"].fillna("") + " " + df["selftext"].fillna("")).str.lower()
    df = df.sort_values("created_utc").reset_index(drop=True)
    return df


def kwd_count(text_series: pd.Series, keywords: list[str]) -> pd.Series:
    pat = "|".join(re.escape(k) for k in keywords)
    return text_series.str.count(pat, flags=re.IGNORECASE)


def filter_posts_for_asset(reddit: pd.DataFrame, asset: str) -> pd.DataFrame:
    f = ASSET_FILTERS[asset]
    kwd_pat = "|".join(re.escape(k) for k in f["keywords"])
    sub_match = reddit["subreddit"].isin(f["subreddits"])
    kwd_match = reddit["text"].str.contains(kwd_pat, regex=True, na=False)
    # Match if (sub matches) OR (post mentions asset keyword in title/text — for r/CryptoCurrency)
    keep = sub_match | (reddit["subreddit"].eq("CryptoCurrency") & kwd_match)
    return reddit[keep].copy()


def build(asset: str, timeframe: str, fg: pd.DataFrame, reddit_all: pd.DataFrame) -> pd.DataFrame:
    pm = pd.read_csv(PM_DIR / f"{asset}_features_v3.csv")
    pm = pm.dropna(subset=["outcome_up", "ret_5m", "window_start_unix"])
    pm = pm[pm["timeframe"] == timeframe].copy()
    pm["asset"] = asset

    # Filter reddit to asset
    reddit = filter_posts_for_asset(reddit_all, asset)
    reddit["pos_kwd"] = kwd_count(reddit["text"], POSITIVE_KEYWORDS)
    reddit["neg_kwd"] = kwd_count(reddit["text"], NEGATIVE_KEYWORDS)

    # F&G: daily lookup
    pm["window_start_dt"] = pd.to_datetime(pm["window_start_unix"], unit="s", utc=True)
    pm["window_date"] = pm["window_start_dt"].dt.normalize()
    fg2 = fg.copy()
    fg2["fg_date"] = pd.to_datetime(fg2["date"]).dt.tz_localize("UTC")
    pm = pm.merge(
        fg2[["fg_date", "fg_value", "fg_change_1d", "fg_change_3d"]].rename(columns={"fg_date": "window_date"}),
        on="window_date", how="left"
    )

    # Reddit: count posts and aggregate features in 1h, 4h lookback windows for each market
    # Use sorted reddit timestamps + searchsorted to find indices
    r_t = reddit["created_utc"].to_numpy()
    r_score = reddit["score"].to_numpy()
    r_pos = reddit["pos_kwd"].to_numpy()
    r_neg = reddit["neg_kwd"].to_numpy()

    q = pm["window_start_unix"].to_numpy()

    def slice_in(window_sec: int):
        lo = np.searchsorted(r_t, q - window_sec, side="left")
        hi = np.searchsorted(r_t, q, side="right")
        return lo, hi

    # 1h
    lo1, hi1 = slice_in(60 * 60)
    pm["reddit_posts_1h"] = hi1 - lo1
    # 4h
    lo4, hi4 = slice_in(4 * 60 * 60)
    pm["reddit_posts_4h"] = hi4 - lo4
    # avg score 4h, sum pos/neg keywords 4h, sentiment
    avg_score = np.zeros(len(q)); pos_sum = np.zeros(len(q)); neg_sum = np.zeros(len(q))
    for i, (lo, hi) in enumerate(zip(lo4, hi4)):
        if hi > lo:
            avg_score[i] = r_score[lo:hi].mean()
            pos_sum[i]   = r_pos[lo:hi].sum()
            neg_sum[i]   = r_neg[lo:hi].sum()
    pm["reddit_avg_score_4h"] = avg_score
    pm["reddit_pos_kwd_4h"]   = pos_sum
    pm["reddit_neg_kwd_4h"]   = neg_sum
    pm["reddit_sentiment_4h"] = pos_sum - neg_sum
    pm["reddit_sent_ratio_4h"] = (pos_sum - neg_sum) / np.where(pm["reddit_posts_4h"] > 0, pm["reddit_posts_4h"], 1)

    return pm


def ic_one(s, y):
    sub = pd.concat([s, y], axis=1).dropna()
    if len(sub) < 30: return np.nan, np.nan, len(sub)
    r, p = spearmanr(sub.iloc[:, 0], sub.iloc[:, 1])
    return r, p, len(sub)


def report(label, df, features):
    print(f"\n=== {label} (n={len(df)}, baseline UP={df['outcome_up'].mean():.3f}) ===")
    rows = []
    for f in features:
        r, p, n = ic_one(df[f], df["outcome_up"])
        rows.append({"feat": f, "n": n, "ic": r, "p": p})
    out = pd.DataFrame(rows).sort_values("ic", key=lambda s: s.abs(), ascending=False)
    for _, r in out.iterrows():
        sig = "***" if r["p"] < 0.001 else ("**" if r["p"] < 0.01 else ("*" if r["p"] < 0.05 else " "))
        print(f"  {r['feat']:<25} n={r['n']:>4d} ic={r['ic']:+.4f} p={r['p']:.3f} {sig}")
    return out


def decile(df, feat):
    sub = df[[feat, "outcome_up"]].dropna()
    if len(sub) < 30: return None
    q10 = sub[feat].quantile(0.10)
    q90 = sub[feat].quantile(0.90)
    bot = sub[sub[feat] <= q10]
    top = sub[sub[feat] >= q90]
    return {"top_n": len(top), "top_hit": top["outcome_up"].mean(),
            "bot_n": len(bot), "bot_hit": bot["outcome_up"].mean()}


def main():
    fg = load_fg()
    reddit_all = load_reddit()
    print(f"F&G rows={len(fg)}, Reddit posts={len(reddit_all)}")

    feats = ["fg_value", "fg_change_1d", "fg_change_3d",
             "reddit_posts_1h", "reddit_posts_4h",
             "reddit_avg_score_4h", "reddit_pos_kwd_4h", "reddit_neg_kwd_4h",
             "reddit_sentiment_4h", "reddit_sent_ratio_4h"]

    # 5m markets
    frames5 = [build(a, "5m", fg, reddit_all) for a in ASSETS]
    big5 = pd.concat(frames5, ignore_index=True)
    out5 = report("5m POOLED (BTC+ETH+SOL)", big5, feats)

    # 15m markets
    frames15 = [build(a, "15m", fg, reddit_all) for a in ASSETS]
    big15 = pd.concat(frames15, ignore_index=True)
    report("15m POOLED", big15, feats)

    # Per-asset 5m
    for a in ASSETS:
        sub = big5[big5["asset"] == a]
        report(f"5m {a.upper()}", sub, feats)

    # Decile lift on top features (5m pooled)
    print("\n=== Top/bottom decile hit rates (5m pooled) ===")
    for f in feats:
        d = decile(big5, f)
        if d:
            t = d["top_hit"] - 0.5; b = d["bot_hit"] - 0.5
            print(f"  {f:<25} top10%(n={d['top_n']:>3d}) hit={d['top_hit']:.3f} ({t:+.3f})  "
                  f"bot10%(n={d['bot_n']:>3d}) hit={d['bot_hit']:.3f} ({b:+.3f})")

    # Sanity: how many markets have 0 reddit coverage?
    print(f"\nReddit coverage (5m): markets with 0 posts in 4h = {(big5['reddit_posts_4h']==0).sum()}/{len(big5)}")
    print(f"Reddit coverage by asset (5m, posts_4h):")
    print(big5.groupby("asset")["reddit_posts_4h"].describe()[["count","mean","50%","75%","max"]].to_string())


if __name__ == "__main__":
    main()
