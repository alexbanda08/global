"""Continue fetching trades beyond the 3500-offset cap using timestamp pagination.

API returns trades sorted DESCENDING by timestamp. To page past 3500 we use
`?limit=500&offset=0&end_time=<earliest_ts_so_far>`.
"""
from __future__ import annotations
import json
import time
import urllib.request
from pathlib import Path

import pandas as pd

WALLET = "0xeebde7a0e019a63e6b476eb425505b7b3e6eba30"
DATA_API = "https://data-api.polymarket.com"
UA = {"User-Agent": "global-strategy-lab/1.0", "Accept": "application/json"}
CACHE = Path(__file__).resolve().parent / "cache"

def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    existing_p = CACHE / f"{WALLET[:10]}_trades.parquet"
    existing = pd.read_parquet(existing_p)
    print(f"have {len(existing)} trades, earliest ts={int(existing.timestamp.min())} "
          f"({pd.to_datetime(int(existing.timestamp.min()), unit='s', utc=True)})")

    all_rows = existing.to_dict("records")
    seen = set(zip(existing.transactionHash.astype(str), existing.asset.astype(str)) if "transactionHash" in existing.columns
                else zip(existing.timestamp.astype(int), existing.asset.astype(str)))
    end_ts = int(existing.timestamp.min())
    page = 0
    while page < 50:
        url = f"{DATA_API}/trades?user={WALLET}&limit=500&offset=0&end_time={end_ts}"
        try:
            batch = get(url)
        except Exception as e:
            print(f"ERR: {e}")
            break
        if not batch:
            print("empty batch — done")
            break
        # filter duplicates
        new_rows = []
        for r in batch:
            k = ((str(r.get("transactionHash", "")), str(r.get("asset", "")))
                 if r.get("transactionHash") else (int(r["timestamp"]), str(r.get("asset", ""))))
            if k in seen:
                continue
            seen.add(k)
            new_rows.append(r)
        if not new_rows:
            print(f"page {page+1}: all dupes, advance ts manually")
            end_ts -= 1
            page += 1
            continue
        all_rows.extend(new_rows)
        page += 1
        new_min = min(int(r["timestamp"]) for r in new_rows)
        print(f"page {page}: +{len(new_rows)} new (cum {len(all_rows)}), "
              f"earliest now {pd.to_datetime(new_min, unit='s', utc=True)}")
        end_ts = new_min
        time.sleep(0.15)
        if len(batch) < 500:
            print("short batch — done")
            break

    out = pd.DataFrame(all_rows).drop_duplicates(
        subset=["transactionHash", "asset"] if "transactionHash" in pd.DataFrame(all_rows).columns
        else ["timestamp", "asset", "size", "price"], keep="first"
    )
    out = out.sort_values("timestamp", ascending=False).reset_index(drop=True)
    out.to_parquet(existing_p, index=False)
    span_h = (out.timestamp.max() - out.timestamp.min()) / 3600.0
    print(f"\nDone. Final: {len(out)} trades over {span_h:.1f} h")
    print(f"  {pd.to_datetime(out.timestamp.min(), unit='s', utc=True)} → "
          f"{pd.to_datetime(out.timestamp.max(), unit='s', utc=True)}")


if __name__ == "__main__":
    main()
