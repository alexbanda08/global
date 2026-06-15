"""Classify Cyclops counterparties: SHARED Polymarket infra vs REAL related wallet.
Test: shared infra (deposit/relayer/exchange) = contract + huge counterparty breadth +
touches thousands of users. Real related wallet = EOA or narrow breadth.

Also trace the SEED funding: earliest incoming USDC.e transfers (before trading) = the
personal funder chain.

Run: C:/Python314/python.exe strategy_lab/wallet_hunt/cyclops_classify_counterparties_2026_06_08.py
"""
from __future__ import annotations
import sys, io, json, time
import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
print("CYCLOPS_CLASSIFY_2026_06_08 OUTPUT START", flush=True)

ALCHEMY = "https://polygon-mainnet.g.alchemy.com/v2/CkcB0ru1bUfColNdPoTLO"
W = "0xf69af0b9af9c92a342b682e5dee262dbc39e7b5c".lower()

CANDIDATES = {
    "0xf70da97812cb96acdf810712aa562db8dfa3dbef": "labeled F1-treasury?",
    "0xf3cfb6a6ebfeb51876289eb235719eb1c65252b0": "relay/inventory-exit?",
    "0xe3f18acc55091e2c48d883fc8c8413319d4ab7b0": "840-in USDC+pos",
    "0x2e1e827fbec36e1dad4a2ee4ed3650d191a7278e": "657-in MATIC+USDC",
    "0xe111180000d2663c0091e4f400237545b87b996b": "NegRisk exchange?",
    "0x115f48dc2a731aa16251c6d6e1befc42f92accc9": "46-out pUSD",
    "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb": "4-out USDC sink?",
}


def post(method, params):
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    for _ in range(4):
        try:
            r = requests.post(ALCHEMY, json=body, timeout=30)
            if r.status_code == 200:
                return r.json().get("result")
            time.sleep(0.6)
        except Exception:
            time.sleep(0.6)
    return None


def is_contract(addr):
    code = post("eth_getCode", [addr, "latest"])
    return bool(code and code != "0x")


def breadth(addr, cap_pages=3):
    """Distinct counterparties across up to cap_pages*1000 transfers, both dirs."""
    cps = set()
    total = 0
    for dirn in ("from", "to"):
        pk = None
        for _ in range(cap_pages):
            p = {"category": ["erc20", "erc1155", "external"], "maxCount": "0x3e8",
                 "excludeZeroValue": False, "order": "asc",
                 ("fromAddress" if dirn == "from" else "toAddress"): addr}
            if pk:
                p["pageKey"] = pk
            res = post("alchemy_getAssetTransfers", [p])
            if not res:
                break
            for t in res.get("transfers", []):
                total += 1
                cps.add((t.get("to") or "").lower() if dirn == "from" else (t.get("from") or "").lower())
            pk = res.get("pageKey")
            if not pk:
                break
            time.sleep(0.2)
    cps.discard(addr.lower())
    cps.discard("")
    return len(cps), total


print(f"\n{'address':44s} {'contract':8s} {'breadth(distinct cps)':22s} note")
print(f"{W:44s} {'Y' if is_contract(W) else 'N':8s} {'(the cyclops wallet)':22s}")
for addr, note in CANDIDATES.items():
    ctr = is_contract(addr)
    b, tot = breadth(addr)
    flag = "  <<< SHARED INFRA (exclude)" if b > 200 else "  <<< NARROW — possible REAL relation"
    print(f"{addr:44s} {'Y' if ctr else 'N':8s} {str(b)+' (>='+str(tot)+' sampled)':22s} {note}{flag}", flush=True)

# --- SEED funding trace: earliest incoming USDC.e to cyclops ---
print("\n=== EARLIEST INCOMING USDC.e TO CYCLOPS (seed funding) ===")
res = post("alchemy_getAssetTransfers", [{
    "toAddress": W, "category": ["erc20"], "maxCount": "0x3e8",
    "excludeZeroValue": True, "order": "asc",
}])
seen = 0
if res:
    for t in res.get("transfers", []):
        asset = t.get("asset")
        if asset not in ("USDC", "USDC.e", "USDCE"):
            continue
        print(f"  block {t.get('blockNum')}  from {t.get('from')}  {t.get('value')} {asset}")
        seen += 1
        if seen >= 8:
            break
if not seen:
    print("  (no USDC.e incoming in first page — funding may be via pUSD/relay)")

# --- earliest incoming pUSD (Polymarket deposit token) ---
print("\n=== EARLIEST INCOMING pUSD/any-erc20 TO CYCLOPS (first 6) ===")
if res:
    for t in res.get("transfers", [])[:6]:
        print(f"  block {t.get('blockNum')}  from {t.get('from')}  {t.get('value')} {t.get('asset')}")

print("CYCLOPS_CLASSIFY_2026_06_08 OUTPUT END")
