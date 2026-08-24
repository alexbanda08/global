"""Classify b945 fills as maker/taker from OrderFilled logs. Runs on Ireland.
Usage: python3 _b945_receipt_classify.py <rpc_url> <txlist_file>
"""
import json, sys, time, urllib.request

RPC, TXFILE = sys.argv[1], sys.argv[2]
WPAD = "0x" + "0"*24 + "b945945d5bcaf7b56834d4da8cdf8f8f94b2db68"
EXCH = {"0x4bfb41d5b3570defd03c39a9a4d8de6bd8b8982e",
        "0xc5d563a36ae78145c45a50134d48a1215220f80a"}

def receipt(tx):
    body = json.dumps({"jsonrpc": "2.0", "id": 1,
                       "method": "eth_getTransactionReceipt", "params": [tx]}).encode()
    req = urllib.request.Request(RPC, data=body, headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=20).read()).get("result")

txs = [l.strip() for l in open(TXFILE) if l.strip()]
tx_maker = tx_taker = tx_both = miss = 0
ev_maker = ev_taker = 0
of_topic = None
for tx in txs:
    try:
        r = receipt(tx)
    except Exception:
        r = None
    if not r:
        miss += 1
        continue
    m = t = 0
    for lg in r.get("logs", []):
        if lg.get("address", "").lower() not in EXCH:
            continue
        tp = [x.lower() for x in lg.get("topics", [])]
        if len(tp) == 4:
            if of_topic is None:
                of_topic = tp[0]
            if tp[2] == WPAD: m += 1
            if tp[3] == WPAD: t += 1
    ev_maker += m; ev_taker += t
    if m and t: tx_both += 1
    elif m: tx_maker += 1
    elif t: tx_taker += 1
    time.sleep(0.12)

print(f"txs: maker-only {tx_maker} | taker-only {tx_taker} | both {tx_both} | miss {miss}")
print(f"OrderFilled events: wallet-as-MAKER {ev_maker} | wallet-as-TAKER {ev_taker}")
print(f"event topic0 seen: {of_topic}")
