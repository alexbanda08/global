"""Probe both Goldsky subgraph and Polygon RPC for Polymarket OrderFilled events.

Goal: confirm we can pull > 3500 trades per wallet — ideally full history.
"""
import json, urllib.request, urllib.error

UA = {"User-Agent": "global-strategy-lab/1.0",
      "Accept": "application/json",
      "Content-Type": "application/json"}

def post_json(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                   headers=UA, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8")), r.status

def get_json(url):
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8")), r.status
    except urllib.error.HTTPError as e:
        return None, e.code


# --- A. Try Goldsky public subgraph patterns ---
print("=== Goldsky subgraph probes ===")
GOLDSKY_PROJECTS = [
    "project_cl6mb8i9h0003e201j6li0diw",  # commonly cited Polymarket project_id
    "project_cl6m6e9j10006e0u2dlnzj48p",  # other guesses
]
SUBGRAPHS = [
    ("polymarket-orderbook", "/latest"),
    ("polymarket-orderbook", "/prod/gn"),
    ("polymarket-fills", "/latest"),
    ("polymarket-trades", "/latest"),
    ("orderbook-subgraph", "/latest"),
]

QUERY = """
{ orderFilledEvents(first: 1) { id timestamp transactionHash maker taker } }
""".strip()

for proj in GOLDSKY_PROJECTS:
    for name, ver in SUBGRAPHS:
        url = f"https://api.goldsky.com/api/public/{proj}/subgraphs/{name}{ver}"
        try:
            data, code = post_json(url, {"query": QUERY})
            print(f"  {code}  {url}")
            if isinstance(data, dict):
                if data.get("data"):
                    print(f"    data keys: {list(data['data'].keys())}")
                    sample = data["data"]
                    for k, v in sample.items():
                        if v:
                            print(f"      first {k}: {v[0] if isinstance(v, list) else v}")
                if data.get("errors"):
                    print(f"    errors: {[e.get('message','?')[:80] for e in data['errors']]}")
        except Exception as e:
            print(f"  ERR  {url[:90]}  {str(e)[:50]}")

# --- B. Try The Graph hosted-service patterns ---
print("\n=== The Graph hosted-service probes ===")
GRAPH_NAMES = [
    "polymarket/matic-markets",
    "polymarket/polygon-fills",
    "polymarket/orderbook-subgraph",
    "polymarket/polymarket",
]
for name in GRAPH_NAMES:
    url = f"https://api.thegraph.com/subgraphs/name/{name}"
    try:
        data, code = post_json(url, {"query": QUERY})
        print(f"  {code}  {url}")
        if isinstance(data, dict):
            if data.get("data"):
                print(f"    DATA: {list(data['data'].keys())}")
            if data.get("errors"):
                msg = (data['errors'][0].get('message','?'))[:80]
                print(f"    errors: {msg}")
    except urllib.error.HTTPError as e:
        print(f"  {e.code}  {url}")

# --- C. Test Polygon RPC + know-block discovery ---
print("\n=== Polygon RPC (eth_getLogs) probes ===")
RPCS = [
    "https://polygon-rpc.com",
    "https://polygon-bor-rpc.publicnode.com",
    "https://rpc.ankr.com/polygon",
    "https://polygon.gateway.tenderly.co",
]
for rpc in RPCS:
    try:
        data, code = post_json(rpc, {
            "jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []
        })
        bn = int(data.get("result","0x0"), 16) if data else 0
        print(f"  {code}  {rpc:<50}  blockNumber={bn:,}")
    except Exception as e:
        print(f"  ERR  {rpc:<50}  {str(e)[:50]}")
