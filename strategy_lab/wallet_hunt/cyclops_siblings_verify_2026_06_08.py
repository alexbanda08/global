"""Verify the candidate sibling wallets (funded by the same narrow EOA 0x2e1e827f as
Cyclops) are actually Polymarket up/down bots — via data-api /activity. Confirm trade
count, asset/tf mix, and recent activity. Only confirmed PM traders = real siblings.

Run: C:/Python314/python.exe strategy_lab/wallet_hunt/cyclops_siblings_verify_2026_06_08.py
"""
from __future__ import annotations
import sys, io, time
from collections import Counter
import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
print("CYCLOPS_SIBLINGS_VERIFY_2026_06_08 OUTPUT START", flush=True)

DATA = "https://data-api.polymarket.com"
UA = {"User-Agent": "global-strategy-lab/1.0", "Accept": "application/json"}

CYCLOPS = "0xf69af0b9af9c92a342b682e5dee262dbc39e7b5c"
FUNDER = "0x2e1e827fbec36e1dad4a2ee4ed3650d191a7278e"
CANDIDATES = [
    "0xb92fe925dc43a0ecde6c8b1a2709c170ec4fff4f",  # also direct-linked to cyclops
    "0x4cd00e387622c35bddb9b4c962c136462338bc31",
    "0xc0de9f5c6d80fa4a4f848a087b9f994c7cd319f5",
    "0x886a78bfd638ea1e73db9da0b6fb7f4dfa7af1f4",
    "0x990636ecb3ff04d33d92e970d3d588bf5cd8d086",
    "0xccc88a9d1b4ed6b0eaba998850414b24f1c315be",
    "0xe13f68e17f699b2db99a1841b65d5ff53d574348",
]


def _get(url, params=None):
    for _ in range(4):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=20)
            if r.status_code == 200:
                return r.json()
            time.sleep(0.4)
        except Exception:
            time.sleep(0.4)
    return None


def profile(addr):
    acts, offset = [], 0
    while offset < 2000:
        page = _get(f"{DATA}/activity", {"user": addr, "limit": 500, "offset": offset})
        if not isinstance(page, list) or not page:
            break
        acts.extend(page)
        if len(page) < 500:
            break
        offset += 500
        time.sleep(0.2)
    trades = [a for a in acts if str(a.get("type")) == "TRADE"]
    mix = Counter()
    last_ts = 0
    for a in trades:
        slug = str(a.get("slug") or "")
        asset = slug.split("-updown")[0] if "-updown" in slug else "?"
        tf = ""
        if "-updown-" in slug:
            tf = slug.split("-updown-")[1].split("-")[0]
        mix[f"{asset}-{tf}"] += 1
        last_ts = max(last_ts, int(a.get("timestamp") or 0))
    return len(acts), len(trades), mix.most_common(4), last_ts


import datetime as dt
print(f"\n{'wallet':44s} {'acts':>5s} {'trades':>6s} {'last_trade_utc':20s} top asset-tf mix")
for tag, addr in [("CYCLOPS", CYCLOPS), ("FUNDER", FUNDER)] + [("cand", c) for c in CANDIDATES]:
    na, nt, mix, lt = profile(addr)
    lts = dt.datetime.utcfromtimestamp(lt).strftime("%Y-%m-%d %H:%M") if lt else "-"
    verdict = "PM up/down BOT ✓" if nt > 20 and any("updown" not in m[0] and "-" in m[0] and m[0] != "?-" for m in mix) else ("PM trader" if nt > 0 else "NOT a PM trader")
    print(f"{tag:7s} {addr:36s} {na:5d} {nt:6d} {lts:20s} {mix}  -> {verdict}", flush=True)

print("CYCLOPS_SIBLINGS_VERIFY_2026_06_08 OUTPUT END")
