"""Probe Binance combined-stream @kline_1s vs @kline_1m delivery from THIS host.
Replicates BinanceMarketDataFeed's URL (1m+1s for btc/eth/sol). Counts CLOSED
bars per interval over ~9s. Decides if @kline_1s reaches this box.

Run on the box: <venv>/bin/python ~/_ws_1s_probe.py
"""
import asyncio, json, collections
import websockets

URL = ("wss://stream.binance.com:9443/stream?streams="
       "btcusdt@kline_1m/btcusdt@kline_1s/"
       "ethusdt@kline_1m/ethusdt@kline_1s/"
       "solusdt@kline_1m/solusdt@kline_1s")

async def main():
    closed = collections.Counter()
    any_msg = collections.Counter()
    sample = {}
    try:
        async with websockets.connect(URL, ping_interval=20, ping_timeout=20) as ws:
            try:
                while True:
                    raw = await asyncio.wait_for(ws.recv(), timeout=10)
                    m = json.loads(raw)
                    d = m.get("data", m)
                    if d.get("e") != "kline":
                        continue
                    k = d.get("k", {})
                    i = k.get("i"); s = k.get("s")
                    any_msg[i] += 1
                    if k.get("x"):
                        closed[i] += 1
                        sample.setdefault((s, i), k.get("c"))
                    # stop once we have several 1s closes or timeout
                    if closed["1s"] >= 6:
                        break
            except asyncio.TimeoutError:
                pass
    except Exception as e:
        print("CONNECT_ERROR", type(e).__name__, str(e)[:200])
        return
    print("any_msg_by_interval:", dict(any_msg))
    print("CLOSED_by_interval:", dict(closed))
    print("samples:", {f"{a}@{b}": v for (a, b), v in sample.items()})
    print("VERDICT_1s_delivered:", closed["1s"] > 0)

asyncio.run(main())
