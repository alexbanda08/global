import urllib.request, json, time, csv, sys

ADDR = "0xb945945d5bcaf7b56834d4da8cdf8f8f94b2db68"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

# 1. profit windows
for w in ["all", "1d"]:
    url = f"https://lb-api.polymarket.com/profit?window={w}&address={ADDR}"
    try:
        d = get(url)
        print(f"profit[{w}]:", d)
    except Exception as e:
        print(f"profit[{w}] ERROR:", e)

# value
try:
    url = f"https://data-api.polymarket.com/value?user={ADDR}"
    d = get(url)
    print("value:", d)
except Exception as e:
    print("value ERROR:", e)

# 2. paginate trades
rows = []
offset = 0
limit = 500
while offset <= 3000:
    url = f"https://data-api.polymarket.com/trades?user={ADDR}&limit={limit}&offset={offset}"
    try:
        d = get(url)
    except Exception as e:
        print(f"trades offset={offset} ERROR:", e)
        break
    if not d:
        print(f"trades offset={offset}: empty, stop")
        break
    rows.extend(d)
    print(f"offset={offset}: got {len(d)} rows")
    if len(d) < limit:
        break
    offset += limit
    time.sleep(0.2)

print(f"TOTAL rows: {len(rows)}")

if rows:
    keys = sorted({k for r in rows for k in r.keys()})
    out = "b945_trades_2026_07_13.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print("saved", out)

    ts = [r.get("timestamp") for r in rows if r.get("timestamp")]
    if ts:
        ts = sorted(int(t) for t in ts)
        import datetime
        print("date range:", datetime.datetime.utcfromtimestamp(ts[0]), "to", datetime.datetime.utcfromtimestamp(ts[-1]))
