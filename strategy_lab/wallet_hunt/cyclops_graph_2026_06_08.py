"""CYCLOPS WALLET — FULL ON-CHAIN COUNTERPARTY GRAPH — 2026-06-08
Pull ALL Alchemy getAssetTransfers (both directions, all categories, full history,
paginated) for the cyclops wallet. Build the counterparty graph: every address that
sent tokens TO it and every address it sent tokens TO. Label known Polymarket system
contracts so the real related wallets (funder, controller EOA, relays) surface.

Wallet = 0xf69af0b9af9c92a342b682e5dee262dbc39e7b5c
Run: C:/Python314/python.exe strategy_lab/wallet_hunt/cyclops_graph_2026_06_08.py
"""
from __future__ import annotations
import sys, io, json, time
from pathlib import Path
from collections import defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import requests

TAG = "CYCLOPS_GRAPH_2026_06_08"
print(TAG, "OUTPUT START", flush=True)

W = "0xf69af0b9af9c92a342b682e5dee262dbc39e7b5c".lower()
ALCHEMY = "https://polygon-mainnet.g.alchemy.com/v2/CkcB0ru1bUfColNdPoTLO"
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
CACHE = ROOT / "strategy_lab" / "wallet_hunt" / "cache" / "_cyclops_graph"
CACHE.mkdir(parents=True, exist_ok=True)

# Known Polymarket / Polygon system contracts (lowercase) → label
SYS = {
    "0x2791bca1f2de4661ed88a30c99a7a9449aa84174": "USDC.e",
    "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359": "USDC (native)",
    "0x4d97dcd97ec945f40cf65f87097ace5ea0476045": "CTF ConditionalTokens",
    "0x4bfb41d5b3570defd03c39a9a4d8de6bd8b8982e": "CTF Exchange",
    "0xc5d563a36ae78145c45a50134d48a1215220f80a": "NegRisk CTF Exchange",
    "0x78769d50be1763ed1ca0d5e878d93f05aabff29e": "NegRisk Adapter",
    "0xd91e80cf2e7be2e162c6513ced06f1dd0da35296": "NegRisk Adapter (alt)",
    "0xab45c5a4b0c941a2f231c04c3f49182e1a254052": "Proxy Wallet Factory",
    "0xaacfeea03eb1561c4e67d661e40682bd20e3541b": "Relay Hub",
    "0x0000000000000000000000000000000000000000": "ZERO/mint-burn",
}


def rpc(params):
    body = {"jsonrpc": "2.0", "id": 1, "method": "alchemy_getAssetTransfers", "params": [params]}
    for _ in range(4):
        try:
            r = requests.post(ALCHEMY, json=body, timeout=30)
            if r.status_code == 200:
                j = r.json()
                if "result" in j:
                    return j["result"]
                print("RPC err:", str(j.get("error"))[:160], flush=True)
            time.sleep(0.6)
        except Exception as e:
            print("EXC", str(e)[:100], flush=True); time.sleep(0.6)
    return None


def pull(direction):
    """direction 'from' = wallet is sender; 'to' = wallet is receiver."""
    out, pageKey = [], None
    base = {
        "category": ["external", "internal", "erc20", "erc721", "erc1155"],
        "withMetadata": False, "excludeZeroValue": False, "maxCount": "0x3e8",
        "order": "asc",
    }
    base["fromAddress" if direction == "from" else "toAddress"] = W
    while True:
        p = dict(base)
        if pageKey:
            p["pageKey"] = pageKey
        res = rpc(p)
        if not res:
            break
        out.extend(res.get("transfers", []))
        pageKey = res.get("pageKey")
        if not pageKey:
            break
        time.sleep(0.25)
    return out


sent = pull("from")     # wallet -> X
recv = pull("to")       # X -> wallet
(CACHE / "transfers_from.json").write_text(json.dumps(sent, default=str), encoding="utf-8")
(CACHE / "transfers_to.json").write_text(json.dumps(recv, default=str), encoding="utf-8")
print(f"\nTOTAL transfers: sent(out)={len(sent)}  recv(in)={len(recv)}", flush=True)


def lbl(a):
    a = (a or "").lower()
    if a == W:
        return "SELF"
    return SYS.get(a, a)


def agg(transfers, key):
    """key='to' for outgoing counterparties, 'from' for incoming. Returns
    {counterparty: {n, assets:set, usdc:float, first, last}}."""
    g = defaultdict(lambda: {"n": 0, "assets": set(), "usdc": 0.0, "first": None, "last": None})
    for t in transfers:
        cp = lbl(t.get(key))
        rec = g[cp]
        rec["n"] += 1
        asset = t.get("asset") or t.get("category")
        rec["assets"].add(str(asset))
        val = t.get("value")
        if asset in ("USDC", "USDC.e") and val:
            try:
                rec["usdc"] += float(val)
            except Exception:
                pass
        bn = t.get("blockNum")
        if rec["first"] is None:
            rec["first"] = bn
        rec["last"] = bn
    return g


out_g = agg(sent, "to")     # who wallet sent to
in_g = agg(recv, "from")    # who sent to wallet


def show(title, g):
    print(f"\n========== {title} ({len(g)} counterparties) ==========")
    rows = sorted(g.items(), key=lambda kv: -kv[1]["n"])
    print(f"{'counterparty':46s} {'n':>5s} {'usdc':>12s}  assets")
    for cp, r in rows:
        tag = ""
        if cp.startswith("0x") and cp not in SYS.values():
            tag = "  <-- NON-SYSTEM WALLET"
        print(f"{cp:46s} {r['n']:5d} {r['usdc']:12.2f}  {','.join(sorted(r['assets']))[:40]}{tag}")


show("OUTGOING — wallet SENT tokens TO", out_g)
show("INCOMING — addresses that SENT tokens TO wallet", in_g)

# Surface the real (non-system, non-self) related wallets explicitly
def real_wallets(g):
    return {cp: r for cp, r in g.items()
            if cp.startswith("0x") and cp != W and cp not in SYS.values()}

ro = real_wallets(out_g)
ri = real_wallets(in_g)
print("\n\n########## RELATED (non-system) WALLETS ##########")
print(f"\n-- wallet SENT to these {len(ro)} real wallets --")
for cp, r in sorted(ro.items(), key=lambda kv: -kv[1]["usdc"]):
    print(f"  {cp}  n={r['n']}  usdc={r['usdc']:.2f}  assets={','.join(sorted(r['assets']))}")
print(f"\n-- these {len(ri)} real wallets SENT to the wallet (funders/sources) --")
for cp, r in sorted(ri.items(), key=lambda kv: -kv[1]["usdc"]):
    print(f"  {cp}  n={r['n']}  usdc={r['usdc']:.2f}  assets={','.join(sorted(r['assets']))}")

print(TAG, "OUTPUT END")
