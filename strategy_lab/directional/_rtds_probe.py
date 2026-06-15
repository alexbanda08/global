import asyncio, json, time, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import websockets

async def probe():
    uri = "wss://ws-live-data.polymarket.com"
    subs = [
        {"action": "subscribe", "subscriptions": [
            {"topic": "crypto_prices", "type": "update", "filters": "{\"symbol\":\"btcusdt\"}"}]},
        {"action": "subscribe", "subscriptions": [{"topic": "crypto_prices_chainlink", "type": "*"}]},
        {"action": "subscribe", "subscriptions": [
            {"topic": "crypto_prices_chainlink", "type": "update", "filters": "{\"symbol\":\"btc/usd\"}"}]},
    ]
    async with websockets.connect(uri, open_timeout=15) as ws:
        for s in subs:
            await ws.send(json.dumps(s))
        t0 = time.time(); n = 0
        while time.time() - t0 < 20 and n < 12:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=6)
                print(msg[:300], flush=True); n += 1
            except asyncio.TimeoutError:
                print("(timeout, no msg)"); break

asyncio.run(probe())
