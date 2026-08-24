"""Refresh b945 + b27 activity from Polymarket data-api (2026-08-13).

The /activity endpoint hard-caps offset pagination at ~3,500 records, so we
paginate by TIME CURSOR: exhaust the offset window, then set `end=<oldest_ts>`
and continue. Dedups on (transactionHash, asset, side, sizex100, timestamp).

Output: cache/_pm_portfolio/<wallet>/activity_<TYPE>_2026_08_13.json
"""
import requests, json, time, os, sys

WALLETS = {
    "0xb945945d": "0xb945945d5bcaf7b56834d4da8cdf8f8f94b2db68",
    "0xb27bc932": "0xb27bc932bf8110d8f78e55da7d5f0497a18b5b82",
}
if len(sys.argv) > 1:                      # override: fetch a single wallet from argv
    _full = sys.argv[1].lower()
    WALLETS = {_full[:10]: _full}
TYPES = ["TRADE", "REDEEM", "MERGE", "SPLIT", "CONVERSION"]
BASE = "https://data-api.polymarket.com/activity"
SINCE_TS = 1780272000          # 2026-05-31 — ~2.5 months back
MAX_RECORDS = {"TRADE": 120_000, "REDEEM": 40_000, "MERGE": 20_000,
               "SPLIT": 20_000, "CONVERSION": 20_000}

def key(r):
    return (r.get("transactionHash"), r.get("asset"), r.get("side"),
            int(float(r.get("size") or 0) * 100), r.get("timestamp"))

def fetch(wallet, typ, since_ts, cap):
    seen, out = set(), []
    end_cursor = None
    stall = 0
    while len(out) < cap:
        got_this_window = 0
        for offset in range(0, 3500, 500):
            url = f"{BASE}?user={wallet}&type={typ}&limit=500&offset={offset}"
            if end_cursor:
                url += f"&end={end_cursor}"
            for attempt in range(3):
                try:
                    r = requests.get(url, timeout=30)
                    r.raise_for_status()
                    batch = r.json()
                    break
                except Exception as e:
                    print(f"    retry {attempt}: {e}", flush=True)
                    time.sleep(2 * (attempt + 1))
            else:
                batch = []
            if not batch:
                break
            for rec in batch:
                k = key(rec)
                if k not in seen:
                    seen.add(k)
                    out.append(rec)
                    got_this_window += 1
            if len(batch) < 500:
                break
            time.sleep(0.15)
        if not out:
            break
        oldest = min(r["timestamp"] for r in out)
        print(f"  {typ}: {len(out)} recs, oldest {time.strftime('%Y-%m-%d %H:%M', time.gmtime(oldest))}", flush=True)
        if oldest <= since_ts or got_this_window == 0:
            if got_this_window == 0:
                stall += 1
                if stall >= 2:
                    break
            else:
                break
        else:
            stall = 0
        end_cursor = oldest  # next window strictly older
    return [r for r in out if r["timestamp"] >= since_ts] or out

def main():
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "_pm_portfolio")
    for short, full in WALLETS.items():
        outdir = os.path.join(root, short)
        os.makedirs(outdir, exist_ok=True)
        print(f"\n=== {short} ===", flush=True)
        for typ in TYPES:
            recs = fetch(full, typ, SINCE_TS, MAX_RECORDS[typ])
            path = os.path.join(outdir, f"activity_{typ}_2026_08_13.json")
            with open(path, "w") as f:
                json.dump(recs, f)
            ts = [r["timestamp"] for r in recs] or [0]
            print(f"  SAVED {typ}: {len(recs)} recs "
                  f"[{time.strftime('%m-%d', time.gmtime(min(ts)))} .. "
                  f"{time.strftime('%m-%d', time.gmtime(max(ts)))}]", flush=True)

if __name__ == "__main__":
    main()
