"""V4-C data fetcher — Fear & Greed + Reddit sentiment posts.

No-auth, free sources:
  - alternative.me Fear & Greed daily index (30+ days history)
  - reddit.com /r/<sub>/new.json paginated (limited ~1000 posts per sub)

Subreddits chosen for crypto coverage:
  r/Bitcoin (BTC), r/ethfinance (ETH), r/solana (SOL), r/CryptoCurrency (general)

Output:
  data/v4/sentiment/fear_greed.parquet
  data/v4/sentiment/reddit_posts.parquet  (subreddit, created_utc, title, score, num_comments)
"""
from __future__ import annotations
import io
import json
import time
import urllib.request
import urllib.error
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT  = ROOT / "data" / "v4" / "sentiment"
OUT.mkdir(parents=True, exist_ok=True)

UA = {"User-Agent": "v4c-research-bot/0.1 by /u/researcher"}


def http_get_json(url: str, headers=None, timeout=20) -> dict:
    req = urllib.request.Request(url, headers=headers or UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def fetch_fear_greed(limit: int = 60) -> pd.DataFrame:
    d = http_get_json(f"https://api.alternative.me/fng/?limit={limit}")
    rows = d["data"]
    df = pd.DataFrame(rows)
    df["timestamp"] = df["timestamp"].astype("int64")
    df["value"] = df["value"].astype(int)
    df["date"] = pd.to_datetime(df["timestamp"], unit="s", utc=True).dt.date
    df = df.sort_values("timestamp").reset_index(drop=True)
    df["fg_value"] = df["value"]
    df["fg_change_1d"] = df["fg_value"].diff()
    df["fg_change_3d"] = df["fg_value"].diff(3)
    return df[["date", "timestamp", "fg_value", "fg_change_1d", "fg_change_3d", "value_classification"]]


def fetch_reddit_paginated(subreddit: str, max_pages: int = 10, sleep: float = 1.5) -> pd.DataFrame:
    rows = []
    after = None
    for page in range(max_pages):
        url = f"https://www.reddit.com/r/{subreddit}/new.json?limit=100"
        if after:
            url += f"&after={after}"
        try:
            d = http_get_json(url)
        except urllib.error.HTTPError as e:
            print(f"    {subreddit} page {page}: HTTP {e.code} — stopping pagination")
            break
        children = d.get("data", {}).get("children", [])
        if not children:
            break
        for c in children:
            p = c["data"]
            rows.append({
                "subreddit": subreddit,
                "created_utc": int(p["created_utc"]),
                "title": p.get("title", ""),
                "selftext": (p.get("selftext", "") or "")[:500],
                "score": p.get("score", 0),
                "num_comments": p.get("num_comments", 0),
                "author": p.get("author", ""),
                "url": p.get("url", ""),
            })
        after = d["data"].get("after")
        if not after:
            break
        time.sleep(sleep)
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("created_utc").reset_index(drop=True)
    return df


def main():
    print("== FEAR & GREED (alternative.me) ==")
    fg = fetch_fear_greed(limit=60)
    print(f"  rows={len(fg)} range={fg['date'].min()} .. {fg['date'].max()}")
    fg.to_parquet(OUT / "fear_greed.parquet")

    print("\n== REDDIT (paginated /new.json) ==")
    SUBS = ["Bitcoin", "ethfinance", "solana", "CryptoCurrency"]
    all_posts = []
    for sub in SUBS:
        print(f"  pulling r/{sub}...")
        df = fetch_reddit_paginated(sub, max_pages=10, sleep=1.5)
        if df.empty:
            print(f"    no posts")
            continue
        oldest = pd.to_datetime(df["created_utc"].min(), unit="s", utc=True)
        newest = pd.to_datetime(df["created_utc"].max(), unit="s", utc=True)
        print(f"    n={len(df)} window={oldest.strftime('%Y-%m-%d %H:%M')} -> {newest.strftime('%Y-%m-%d %H:%M')}")
        all_posts.append(df)

    if all_posts:
        big = pd.concat(all_posts, ignore_index=True)
        big.to_parquet(OUT / "reddit_posts.parquet")
        print(f"\n  total reddit posts: {len(big)} -> {OUT / 'reddit_posts.parquet'}")


if __name__ == "__main__":
    main()
