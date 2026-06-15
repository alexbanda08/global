"""(A) Decode sibling 0x886a78bfd (strategy + PnL).
(B) Trace UP from funder 0x2e1e827f: who funds it, classify each source (EOA/contract +
breadth + label known CEX hot wallets), find the operator root / CEX withdrawal.

Run: C:/Python314/python.exe strategy_lab/wallet_hunt/cyclops_root_trace_2026_06_08.py
"""
from __future__ import annotations
import sys, io, time
import datetime as dt
from collections import Counter, defaultdict
import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
print("CYCLOPS_ROOT_TRACE_2026_06_08 OUTPUT START", flush=True)

ALCHEMY = "https://polygon-mainnet.g.alchemy.com/v2/CkcB0ru1bUfColNdPoTLO"
DATA = "https://data-api.polymarket.com"
UA = {"User-Agent": "global-strategy-lab/1.0", "Accept": "application/json"}

SIBLING = "0x886a78bfd638ea1e73db9da0b6fb7f4dfa7af1f4"
FUNDER = "0x2e1e827fbec36e1dad4a2ee4ed3650d191a7278e".lower()

# known Polygon CEX / bridge hot wallets (lowercase) for labeling roots
KNOWN = {
    "0xe7804c37c13166ff0b37f5ae0bb07a3aebb6e245": "Binance",
    "0xf89d7b9c864f589bbf53a82105107622b35eaa40": "Bybit hot",
    "0x505e71695e9bc45943c58adec1650577bca68fd9": "Binance hot",
    "0x290275e3db66394c52272398959845170e4dcb88": "Binance",
    "0x9696f59e4d72e237be84ffd425dcad154bf96976": "Binance",
    "0x1ab4973a48dc892cd9971ece8e01dcc7688f8f23": "Binance",
    "0x0d0707963952f2fba59dd06f2b425ace40b492fe": "Gate.io",
    "0xf70da97812cb96acdf810712aa562db8dfa3dbef": "shared onramp (827 cps)",
}


def post(method, params):
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    for _ in range(4):
        try:
            r = requests.post(ALCHEMY, json=body, timeout=30)
            if r.status_code == 200:
                return r.json().get("result")
            time.sleep(0.5)
        except Exception:
            time.sleep(0.5)
    return None


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


def transfers(addr, dirn, cats, cap=4):
    out, pk = [], None
    field = "fromAddress" if dirn == "from" else "toAddress"
    for _ in range(cap):
        p = {"category": cats, "maxCount": "0x3e8", "excludeZeroValue": False,
             "order": "asc", field: addr}
        if pk:
            p["pageKey"] = pk
        res = post("alchemy_getAssetTransfers", [p])
        if not res:
            break
        out.extend(res.get("transfers", []))
        pk = res.get("pageKey")
        if not pk:
            break
        time.sleep(0.2)
    return out


# ================= (A) decode sibling =================
print("\n========== (A) SIBLING 0x886a78bfd DECODE ==========")
acts, off = [], 0
while off < 3000:
    pg = _get(f"{DATA}/activity", {"user": SIBLING, "limit": 500, "offset": off})
    if not isinstance(pg, list) or not pg:
        break
    acts.extend(pg)
    if len(pg) < 500:
        break
    off += 500
    time.sleep(0.2)
import pandas as pd
A = pd.DataFrame(acts)
if not A.empty:
    for c in ("price", "size", "usdcSize", "timestamp"):
        if c in A:
            A[c] = pd.to_numeric(A[c], errors="coerce")
    A["type"] = A["type"].astype(str)
    A["side"] = A.get("side", "").astype(str).str.upper()
    tr = A[A["type"] == "TRADE"].copy()
    tr["asset"] = tr["slug"].astype(str).str.extract(r"^([a-z0-9]+)-updown")[0]
    tr["tf"] = tr["slug"].astype(str).str.extract(r"-updown-(\d+[mh])-")[0]
    buys = tr[tr["side"] == "BUY"]
    red = A[A["type"] == "REDEEM"]
    first = dt.datetime.utcfromtimestamp(int(A["timestamp"].min())).strftime("%Y-%m-%d")
    last = dt.datetime.utcfromtimestamp(int(A["timestamp"].max())).strftime("%Y-%m-%d %H:%M")
    bc, rp = float(buys["usdcSize"].sum()), float(red["usdcSize"].sum())
    print(f"activity={len(A)} trades={len(tr)} buys={len(buys)} redeems={len(red)}")
    print(f"first={first} last={last}")
    print(f"asset×tf:\n{tr.groupby(['asset','tf']).size().sort_values(ascending=False).head(8).to_string()}")
    if len(buys):
        print(f"buy notional med=${buys['usdcSize'].median():.2f}  entry price med={buys['price'].median():.3f}  fav%={(buys['price']>0.5).mean()*100:.0f}")
    print(f"buy_cost=${bc:.2f}  redeem=${rp:.2f}  lifetime_net=${rp-bc:+.2f}")
else:
    print("no activity")

# ================= (B) trace up the funder =================
print("\n========== (B) WHO FUNDS 0x2e1e827f (one hop up) ==========")
recv = transfers(FUNDER, "to", ["erc20", "external"], cap=4)
src = defaultdict(lambda: {"n": 0, "assets": set()})
for t in recv:
    fr = (t.get("from") or "").lower()
    if not fr or fr == FUNDER:
        continue
    src[fr]["n"] += 1
    src[fr]["assets"].add(str(t.get("asset")))
print(f"{'source':44s} {'n':>4s} {'type':9s} {'breadth':>7s} {'label':24s} assets")
for addr, r in sorted(src.items(), key=lambda kv: -kv[1]["n"])[:12]:
    code = post("eth_getCode", [addr, "latest"])
    is_ctr = bool(code and code != "0x")
    # quick breadth (1 page each dir)
    b = set()
    for dirn in ("from", "to"):
        res = post("alchemy_getAssetTransfers", [{"category": ["erc20", "external"], "maxCount": "0x3e8",
                   "order": "asc", ("fromAddress" if dirn == "from" else "toAddress"): addr}])
        if res:
            for x in res.get("transfers", []):
                b.add((x.get("to") or "").lower() if dirn == "from" else (x.get("from") or "").lower())
        time.sleep(0.15)
    b.discard(addr); b.discard("")
    lab = KNOWN.get(addr, "")
    print(f"{addr:44s} {r['n']:4d} {'contract' if is_ctr else 'EOA':9s} {len(b):7d} {lab:24s} {','.join(sorted(r['assets']))[:20]}", flush=True)

print("CYCLOPS_ROOT_TRACE_2026_06_08 OUTPUT END")
