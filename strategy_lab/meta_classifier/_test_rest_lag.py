"""Test if Polymarket REST /book endpoint returns stale data.

Strategy:
1. Pick a currently-active BTC-updown 5m market.
2. Query CLOB REST /book endpoint multiple times across 1 second.
3. Compare timestamp returned in book vs request time.
4. If book timestamp is N seconds old → REST lag = N seconds.

Also: capture Binance live BTC price during the test, see if REST book reacts.
"""
import json
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone

# Find active BTC updown markets via gamma-api
def fetch_active_btc_updown():
    # Query the most recent active btc-updown-5m via slug pattern lookup
    url = "https://gamma-api.polymarket.com/markets?slug=btc-updown-5m-1778185500"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.load(r)
    out = []
    for m in data:
        if m.get("active") and not m.get("closed"):
            tids = json.loads(m.get("clobTokenIds", "[]")) if isinstance(m.get("clobTokenIds"), str) else m.get("clobTokenIds", [])
            outc = json.loads(m.get("outcomes")) if isinstance(m.get("outcomes"), str) else m.get("outcomes", ["Up","Down"])
            out.append({"slug": m.get("slug",""), "tokens": tids, "outcomes": outc})
    return out

def fetch_clob_book(token_id):
    url = f"https://clob.polymarket.com/book?token_id={token_id}"
    t0 = time.time()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.load(r)
        return time.time() - t0, data
    except Exception as e:
        return time.time() - t0, {"error": str(e)}

def fetch_binance_btc():
    url = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=5) as r:
        data = json.load(r)
    return float(data.get("price", 0))

print("=== Polymarket REST /book lag test ===\n")
print(f"now: {datetime.now(timezone.utc).isoformat()}\n")

markets = fetch_active_btc_updown()
print(f"active btc-updown-5m markets: {len(markets)}")
if not markets:
    print("none active right now"); exit()

# Pick the first one (most recent)
m = markets[0]
print(f"\nselected: {m['slug']}")
print(f"  outcomes: {m['outcomes']}")
print(f"  token_ids: {[t[:30]+'...' for t in m['tokens']]}")

# Query REST /book 6 times spaced 200ms
yes_token = m['tokens'][0]
print(f"\n--- 6 REST /book queries (Up token), spaced 200ms ---")
for i in range(6):
    t_start = time.time()
    btc = fetch_binance_btc()
    elapsed_rest, book = fetch_clob_book(yes_token)
    book_ts = book.get("timestamp") if isinstance(book, dict) else None
    asks = book.get("asks", []) if isinstance(book, dict) else []
    bids = book.get("bids", []) if isinstance(book, dict) else []
    ask0 = asks[-1] if asks else None  # asks usually descending; check first
    bid0 = bids[-1] if bids else None
    # Actually CLOB returns asks ascending and bids descending (or vice versa)
    print(f"  [{i}] req_at={time.time():.3f} BTC=${btc:,.2f} rest_lat={elapsed_rest*1000:.0f}ms book_ts={book_ts} #asks={len(asks)} #bids={len(bids)} top_bid={bids[-1] if bids else '-'} top_ask={asks[0] if asks else '-'}")
    time.sleep(0.2)

# Also query for full book once and inspect
print(f"\n--- Full book inspect (Up token) ---")
elapsed, book = fetch_clob_book(yes_token)
print(f"REST latency: {elapsed*1000:.0f}ms")
print(f"book keys: {list(book.keys()) if isinstance(book, dict) else 'error'}")
if "timestamp" in book:
    book_ts_ms = int(book["timestamp"])
    book_age_s = time.time() - book_ts_ms/1000
    print(f"book.timestamp: {book_ts_ms}  ({datetime.fromtimestamp(book_ts_ms/1000, timezone.utc).isoformat()})")
    print(f"book age (now - timestamp): {book_age_s*1000:.0f}ms")
print(f"asks (top 5): {book.get('asks', [])[:5]}")
print(f"bids (top 5): {book.get('bids', [])[:5]}")

# Now query the OPPOSITE outcome token for sanity
no_token = m['tokens'][1] if len(m['tokens']) > 1 else None
if no_token:
    print(f"\n--- Down token book ---")
    elapsed, book2 = fetch_clob_book(no_token)
    print(f"top asks: {book2.get('asks', [])[:5]}")
    print(f"top bids: {book2.get('bids', [])[:5]}")
    if "timestamp" in book2:
        bt2 = int(book2["timestamp"])
        print(f"Down book age: {(time.time() - bt2/1000)*1000:.0f}ms")
