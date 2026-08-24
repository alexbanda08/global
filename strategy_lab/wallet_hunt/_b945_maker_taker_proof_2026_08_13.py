"""Prove maker-vs-taker for b945, three independent ways (2026-08-13).

A) data-api /trades takerOnly=true vs activity TRADE volume (cheap, indirect)
B) on-chain: eth_getTransactionReceipt for a sample of fill txs; in CTFExchange
   OrderFilled(orderHash idx, maker idx, taker idx, ...) check which topic holds
   the wallet address. Definitive per-fill.
C) MAKER_REBATE activity records (rebates only accrue to makers).
"""
import json, os, random, time, urllib.request

W = "0xb945945d5bcaf7b56834d4da8cdf8f8f94b2db68"
WPAD = "0x" + "0"*24 + W[2:].lower()
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "_pm_portfolio", "0xb945945d")
RPCS = ["https://polygon-rpc.com", "https://polygon.llamarpc.com",
        "https://polygon-bor-rpc.publicnode.com", "https://1rpc.io/matic"]
EXCHANGES = {"0x4bfb41d5b3570defd03c39a9a4d8de6bd8b8982e": "CTFExchange",
             "0xc5d563a36ae78145c45a50134d48a1215220f80a": "NegRiskExchange"}

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
    return json.loads(urllib.request.urlopen(req, timeout=25).read())

def rpc(method, params, i=0):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    for k in range(len(RPCS)):
        try:
            req = urllib.request.Request(RPCS[(i+k) % len(RPCS)], data=body,
                                         headers={"Content-Type": "application/json"})
            r = json.loads(urllib.request.urlopen(req, timeout=25).read())
            if "result" in r:
                return r["result"]
        except Exception:
            time.sleep(0.4)
    return None

# ── A) taker-only trades probe ──────────────────────────────────────────────
print("A) data-api /trades takerOnly probe")
for flag in ("true", "false"):
    try:
        d = get(f"https://data-api.polymarket.com/trades?user={W}&takerOnly={flag}&limit=500")
        ts = [r.get("timestamp") for r in d if r.get("timestamp")]
        span = (max(ts) - min(ts)) / 3600 if len(ts) > 1 else 0
        print(f"  takerOnly={flag}: {len(d)} trades in one page; 500-trade span = {span:.1f}h")
    except Exception as e:
        print(f"  takerOnly={flag}: ERROR {e}")

# ── C) maker rebates ────────────────────────────────────────────────────────
print("\nC) MAKER_REBATE activity")
try:
    d = get(f"https://data-api.polymarket.com/activity?user={W}&type=MAKER_REBATE&limit=500")
    tot = sum(float(r.get("usdcSize") or 0) for r in d)
    ts = [r["timestamp"] for r in d] or [0]
    print(f"  {len(d)} rebate events (last page), ${tot:,.2f}, "
          f"{time.strftime('%m-%d', time.gmtime(min(ts)))}..{time.strftime('%m-%d', time.gmtime(max(ts)))}")
except Exception as e:
    print(f"  ERROR {e}")

# ── B) on-chain receipts sample ─────────────────────────────────────────────
print("\nB) on-chain OrderFilled sample")
trades = json.load(open(os.path.join(ROOT, "activity_TRADE_2026_08_13.json")))
txs = sorted({t["transactionHash"] for t in trades if t.get("transactionHash")})
random.seed(13)
sample = random.sample(txs, min(40, len(txs)))
as_maker = as_taker = both = none = 0
fills_maker = fills_taker = 0
multi_fill_txs = 0
for i, tx in enumerate(sample):
    rec = rpc("eth_getTransactionReceipt", [tx], i)
    if not rec:
        none += 1
        continue
    m = t = 0
    n_of = 0
    for lg in rec.get("logs", []):
        if lg.get("address", "").lower() not in EXCHANGES:
            continue
        topics = lg.get("topics", [])
        if len(topics) == 4:              # OrderFilled(orderHash, maker, taker)
            n_of += 1
            if topics[2].lower() == WPAD: m += 1
            if topics[3].lower() == WPAD: t += 1
    fills_maker += m; fills_taker += t
    if n_of > 2:
        multi_fill_txs += 1
    if m and t: both += 1
    elif m: as_maker += 1
    elif t: as_taker += 1
    else: none += 1
    time.sleep(0.25)

n = as_maker + as_taker + both
print(f"  sampled {len(sample)} txs, classified {n} (rpc-miss {none})")
print(f"  wallet appears as MAKER only: {as_maker}  ({100*as_maker/max(n,1):.1f}%)")
print(f"  wallet appears as TAKER only: {as_taker}  ({100*as_taker/max(n,1):.1f}%)")
print(f"  both in same tx:              {both}")
print(f"  OrderFilled events: wallet=maker {fills_maker}, wallet=taker {fills_taker}")
print(f"  txs with >2 OrderFilled (sweep filling several orders): {multi_fill_txs}")
