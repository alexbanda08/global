"""Probe Polymarket APIs for wallet 0xeebde7a0e019a63e6b476eb425505b7b3e6eba30."""
import json, urllib.request

WALLET = "0xeebde7a0e019a63e6b476eb425505b7b3e6eba30"
UA = {"User-Agent": "global-strategy-lab/1.0", "Accept": "application/json"}

def get(url):
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8")), r.status
    except urllib.error.HTTPError as e:
        return None, e.code
    except Exception as e:
        return None, str(e)[:60]

candidates = [
    f"https://data-api.polymarket.com/trades?user={WALLET}&limit=5",
    f"https://data-api.polymarket.com/trades?proxyWallet={WALLET}&limit=5",
    f"https://data-api.polymarket.com/positions?user={WALLET}",
    f"https://data-api.polymarket.com/value?user={WALLET}",
    f"https://data-api.polymarket.com/holdings?user={WALLET}",
    f"https://data-api.polymarket.com/profile?address={WALLET}",
    f"https://data-api.polymarket.com/profile?proxyWallet={WALLET}",
    f"https://data-api.polymarket.com/activity?user={WALLET}&limit=5",
    f"https://data-api.polymarket.com/leaderboard/profile?address={WALLET}",
    f"https://lb-api.polymarket.com/profile/{WALLET}",
    f"https://polymarket.com/api/profile/{WALLET}",
]
for u in candidates:
    data, code = get(u)
    if isinstance(data, list):
        print(f"  {code}  list len={len(data)}  {u[80:]}")
        if data:
            print(f"     sample keys: {list(data[0].keys())[:10]}")
    elif isinstance(data, dict):
        print(f"  {code}  dict keys={list(data.keys())[:6]}  {u[80:]}")
    else:
        print(f"  {code}  -                                {u[80:]}")
