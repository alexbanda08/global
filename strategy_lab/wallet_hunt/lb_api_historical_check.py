"""
For the BIG_LOSER 0xe9076a87 and one of our reference winners (0xb27bc932),
page back through /activity to find when they were trading updown vs sports.

Goal: confirm the hypothesis that big makers migrated from updown -> sports.
"""
from __future__ import annotations
import json
import re
from pathlib import Path

import pandas as pd
import requests

CACHE = Path(r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\wallet_hunt\cache")
DATA = "https://data-api.polymarket.com"

TARGETS = [
    ("0xe9076a87c5ed90ef16e6fe6529c943baeca0cff6", "BIG_LOSER_e9076"),
    ("0xb27bc932bf8110d8f78e55da7d5f0497a18b5b82", "KNOWN_WINNER_b27"),
    ("0xfb0f17657c9c24293b918adb86362a4d8fc90b02", "aoe2gamer_allcross"),
]


def paginate(addr: str, max_pages: int = 30) -> list[dict]:
    """Page through /activity in 500-event chunks."""
    out = []
    for page_idx in range(max_pages):
        offset = page_idx * 500
        try:
            r = requests.get(f"{DATA}/activity",
                             params={"user": addr, "limit": 500, "offset": offset},
                             timeout=15)
            if r.status_code != 200:
                break
            j = r.json()
            if not isinstance(j, list) or not j:
                break
            out.extend(j)
            if len(j) < 500:
                break
        except Exception:
            break
    return out


def bucket_by_day(activity: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(activity)
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    df["date"] = df["ts"].dt.date
    df["slug"] = df["slug"].astype(str)
    df["is_updown"] = df["slug"].str.contains("-up-or-down-", case=False, na=False)
    df["is_sport"] = df["slug"].str.match(r"^(mlb|nba|nhl|nfl|epl|nba)-", case=False, na=False)

    daily = df.groupby("date").agg(
        n_total=("slug", "count"),
        n_updown=("is_updown", "sum"),
        n_sport=("is_sport", "sum"),
    ).reset_index()
    daily["pct_updown"] = daily["n_updown"] / daily["n_total"] * 100
    daily["pct_sport"] = daily["n_sport"] / daily["n_total"] * 100
    return daily


def main():
    out_all = {}
    for addr, label in TARGETS:
        print(f"\n=== {addr[:10]}... [{label}]")
        activity = paginate(addr, max_pages=30)
        if not activity:
            print("  NO ACTIVITY")
            continue
        df_total = pd.DataFrame(activity)
        ts_min = int(df_total["timestamp"].min())
        ts_max = int(df_total["timestamp"].max())
        span_days = (ts_max - ts_min) / 86400
        print(f"  records: {len(activity)} | window: {span_days:.1f} days "
              f"({pd.Timestamp(ts_min, unit='s', tz='UTC')} -> {pd.Timestamp(ts_max, unit='s', tz='UTC')})")

        daily = bucket_by_day(activity)
        print(f"  daily breakdown:")
        cols = ["date", "n_total", "n_updown", "pct_updown", "n_sport", "pct_sport"]
        print(daily[cols].to_string(index=False))
        out_all[addr] = {"label": label, "daily": daily.to_dict("records")}

    (CACHE / "_lb_historical_pivot_check.json").write_text(
        json.dumps(out_all, default=str, indent=2)
    )


if __name__ == "__main__":
    main()
