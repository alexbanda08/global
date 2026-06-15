"""Enumerate the Cyclops operator fleet via the narrow funding EOA 0x2e1e827f
(EOA, breadth 26, 657 transfers to Cyclops = personal gas/USDC funder).
Its distinct counterparties = the sibling wallets. Classify each (contract=PM proxy
candidate). Also trace Cyclops's own seed funding.

Run: C:/Python314/python.exe strategy_lab/wallet_hunt/cyclops_fleet_2026_06_08.py
"""
from __future__ import annotations
import sys, io, time
from collections import defaultdict
import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
print("CYCLOPS_FLEET_2026_06_08 OUTPUT START", flush=True)

ALCHEMY = "https://polygon-mainnet.g.alchemy.com/v2/CkcB0ru1bUfColNdPoTLO"
CYCLOPS = "0xf69af0b9af9c92a342b682e5dee262dbc39e7b5c".lower()
FUNDER = "0x2e1e827fbec36e1dad4a2ee4ed3650d191a7278e".lower()  # narrow gas/USDC EOA


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


def all_transfers(addr, dirn, cap_pages=8):
    out, pk = [], None
    field = "fromAddress" if dirn == "from" else "toAddress"
    for _ in range(cap_pages):
        p = {"category": ["erc20", "external"], "maxCount": "0x3e8",
             "excludeZeroValue": False, "order": "asc", field: addr}
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


# Funder's full counterparty list (who it sends to)
sent = all_transfers(FUNDER, "from")
cps = defaultdict(lambda: {"n": 0, "assets": set()})
for t in sent:
    to = (t.get("to") or "").lower()
    if not to or to == FUNDER:
        continue
    cps[to]["n"] += 1
    cps[to]["assets"].add(str(t.get("asset")))

print(f"\nfunder 0x2e1e827f sent {len(sent)} transfers to {len(cps)} distinct addresses")
print(f"{'address':44s} {'n':>5s} {'contract':8s} assets")
fleet = []
for addr, r in sorted(cps.items(), key=lambda kv: -kv[1]["n"]):
    code = post("eth_getCode", [addr, "latest"])
    is_ctr = bool(code and code != "0x")
    star = "  <-- CYCLOPS" if addr == CYCLOPS else ("  <-- PM-proxy (sibling bot?)" if is_ctr else "  (EOA)")
    print(f"{addr:44s} {r['n']:5d} {'Y' if is_ctr else 'N':8s} {','.join(sorted(r['assets']))[:24]}{star}", flush=True)
    fleet.append((addr, r["n"], is_ctr))

# Who funds the funder (one hop up = the operator's source)
print("\n=== who funds the funder 0x2e1e827f (sources) ===")
recv = all_transfers(FUNDER, "to", cap_pages=3)
src = defaultdict(lambda: {"n": 0, "assets": set()})
for t in recv:
    fr = (t.get("from") or "").lower()
    if not fr or fr == FUNDER:
        continue
    src[fr]["n"] += 1
    src[fr]["assets"].add(str(t.get("asset")))
for addr, r in sorted(src.items(), key=lambda kv: -kv[1]["n"])[:12]:
    code = post("eth_getCode", [addr, "latest"])
    print(f"  {addr}  n={r['n']}  {'contract' if code and code!='0x' else 'EOA'}  {','.join(sorted(r['assets']))[:30]}")

print("CYCLOPS_FLEET_2026_06_08 OUTPUT END")
