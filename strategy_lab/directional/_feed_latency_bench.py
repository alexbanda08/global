"""
_feed_latency_bench.py — live latency shoot-out vs Polymarket RTDS (settlement truth).

Feeds (all timestamped with the SAME local clock -> relative lead/lag is fair):
  RTDS : wss://ws-live-data.polymarket.com  topic crypto_prices_chainlink (btc/eth/sol)
  PYTH : hermes.pyth.network SSE stream (parsed, publish_time)
  ARB  : Chainlink Arbitrum AggregatorProxy latestRoundData() polled ~250ms,
         round-robin llamarpc / drpc / ankr. Address sanity-checked via description().

Output: _results/feed_bench_<ts>.parquet (feed, sym, t_local_ns, t_feed_ms, price)
then analysis: transport delay + pairwise best-shift alignment + move-event first-detection.

Usage: py -3 strategy_lab/directional/_feed_latency_bench.py [minutes]
"""
import asyncio, json, sys, time, threading
from pathlib import Path
import numpy as np
import pandas as pd
import requests
import websockets

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
OUT = Path(r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\directional\_results")
MINUTES = float(sys.argv[1]) if len(sys.argv) > 1 else 12.0
STOP_AT = time.time() + MINUTES * 60
ROWS = []          # (feed, sym, t_local_ns, t_feed_ms, price)
LOCK = threading.Lock()

PYTH_IDS = {
    "btc": "e62df6c8b4a85fe1a67db44dc12de5db330f7ac66b72dc658afedf0f4a415b43",
    "eth": "ff61491a931112ddf1bd8147cd1b641375f79f5825126d665480874634fd0ace",
    "sol": "ef0d8b6fda2ceba41da15d4095d1da392a0d2f8ed0c6c7bc0f4cfac8c280b56d",
}
ARB_FEEDS = {
    "btc": "0x6ce185860a4963106506C203335A2910413708e9",
    "eth": "0x639Fe6ab55C921f74e7fac1ee960C0B6293ba612",
    "sol": "0x24ceA4b8ce57cdA5058b924B9B9987992450590c",
}
ARB_RPCS = ["https://arb1.arbitrum.io/rpc", "https://arbitrum-one.publicnode.com",
            "https://1rpc.io/arb", "https://arbitrum.drpc.org"]
SESS = requests.Session()    # keep-alive: avoids per-call TLS handshake (~400ms)
SEL_LATEST = "0xfeaf968c"   # latestRoundData()
SEL_DESC = "0x7284e416"     # description()


def add(feed, sym, t_feed_ms, price):
    with LOCK:
        ROWS.append((feed, sym, time.time_ns(), int(t_feed_ms), float(price)))


# ---------- RTDS ----------
async def rtds_loop():
    uri = "wss://ws-live-data.polymarket.com"
    want = {"btc/usd": "btc", "eth/usd": "eth", "sol/usd": "sol"}
    while time.time() < STOP_AT:
        try:
            async with websockets.connect(uri, open_timeout=15, ping_interval=20) as ws:
                await ws.send(json.dumps({"action": "subscribe", "subscriptions": [
                    {"topic": "crypto_prices_chainlink", "type": "*"}]}))
                while time.time() < STOP_AT:
                    msg = await asyncio.wait_for(ws.recv(), timeout=15)
                    try:
                        d = json.loads(msg)
                    except Exception:
                        continue          # keepalive/empty frames
                    if not isinstance(d, dict) or d.get("topic") != "crypto_prices_chainlink":
                        continue
                    p = d.get("payload") or {}
                    sym = want.get(p.get("symbol"))
                    if sym:
                        add("rtds", sym, p.get("timestamp", 0), p.get("value", np.nan))
        except Exception as e:
            print(f"[rtds] reconnect: {str(e)[:60]}", flush=True)
            await asyncio.sleep(2)


def rtds_thread():
    asyncio.run(rtds_loop())


# ---------- PYTH SSE ----------
def pyth_thread():
    ids = "&".join(f"ids[]={v}" for v in PYTH_IDS.values())
    url = f"https://hermes.pyth.network/v2/updates/price/stream?{ids}&parsed=true"
    rev = {v: k for k, v in PYTH_IDS.items()}
    while time.time() < STOP_AT:
        try:
            with requests.get(url, stream=True, timeout=30) as r:
                for line in r.iter_lines():
                    if time.time() > STOP_AT:
                        break
                    if not line or not line.startswith(b"data:"):
                        continue
                    d = json.loads(line[5:])
                    for pr in d.get("parsed", []):
                        sym = rev.get(pr.get("id"))
                        if not sym:
                            continue
                        p = pr["price"]
                        px = float(p["price"]) * (10 ** p["expo"])
                        add("pyth", sym, p["publish_time"] * 1000, px)
        except Exception as e:
            print(f"[pyth] reconnect: {str(e)[:60]}", flush=True)
            time.sleep(2)


# ---------- ARBITRUM ----------
def eth_call(rpc, to, data, timeout=4):
    r = SESS.post(rpc, json={"jsonrpc": "2.0", "id": 1, "method": "eth_call",
                             "params": [{"to": to, "data": data}, "latest"]},
                  timeout=timeout)
    return r.json().get("result")


def arb_verify():
    for sym, addr in ARB_FEEDS.items():
        for rpc in ARB_RPCS:
            try:
                res = eth_call(rpc, addr, SEL_DESC)
                if res and len(res) >= 2:
                    raw = bytes.fromhex(res[2:])
                    s = raw[64:64 + int.from_bytes(raw[32:64], "big")].decode(errors="replace")
                    print(f"[arb] {sym} {addr[:10]} description: '{s}' via {rpc.split('//')[1].split('/')[0]}", flush=True)
                    break
            except Exception:
                continue


def arb_thread(sym):
    addr = ARB_FEEDS[sym]
    k = 0
    last_round = None
    while time.time() < STOP_AT:
        rpc = ARB_RPCS[k % len(ARB_RPCS)]; k += 1
        try:
            res = eth_call(rpc, addr, SEL_LATEST)
            if res and len(res) >= 2 + 64 * 5:
                raw = bytes.fromhex(res[2:])
                rid = int.from_bytes(raw[0:32], "big")
                ans = int.from_bytes(raw[32:64], "big", signed=False)
                upd = int.from_bytes(raw[96:128], "big")
                if rid != last_round:
                    last_round = rid
                    add("arb", sym, upd * 1000, ans / 1e8)
        except Exception:
            pass
        time.sleep(0.25)


# ---------- PYTH LAZER (real_time, 50ms) ----------
import os
LAZER_TOKEN = os.environ.get("PYTH_LAZER_TOKEN", "")  # set PYTH_LAZER_TOKEN env var (key scrubbed from repo)
LAZER_URL = "wss://pyth-lazer-0.dourolabs.app/v1/stream"
LAZER_FEEDS = {1: "btc", 2: "eth", 6: "sol"}


async def lazer_loop():
    sub = {"type": "subscribe", "subscriptionId": 1,
           "priceFeedIds": list(LAZER_FEEDS.keys()),
           "properties": ["price", "exponent"], "formats": [],
           "channel": "real_time", "deliveryFormat": "json", "parsed": True,
           "ignoreInvalidFeedIds": True}
    hdr = [("Authorization", f"Bearer {LAZER_TOKEN}")]
    while time.time() < STOP_AT:
        try:
            try:
                ws = await websockets.connect(LAZER_URL, additional_headers=hdr,
                                              open_timeout=10, ping_interval=20)
            except TypeError:
                ws = await websockets.connect(LAZER_URL, extra_headers=dict(hdr),
                                              open_timeout=10, ping_interval=20)
            async with ws:
                await ws.send(json.dumps(sub))
                while time.time() < STOP_AT:
                    raw = await asyncio.wait_for(ws.recv(), timeout=15)
                    try:
                        m = json.loads(raw)
                    except Exception:
                        continue
                    if m.get("type") != "streamUpdated":
                        continue
                    parsed = m.get("parsed") or {}
                    ts_us = float(parsed.get("timestampUs", 0) or 0)
                    for pf in parsed.get("priceFeeds", []):
                        sym = LAZER_FEEDS.get(pf.get("priceFeedId"))
                        if sym and pf.get("price") is not None:
                            add("lazer", sym, ts_us / 1000.0, int(pf["price"]) * 1e-8)
        except Exception as e:
            print(f"[lazer] reconnect: {str(e)[:60]}", flush=True)
            await asyncio.sleep(2)


def lazer_thread():
    asyncio.run(lazer_loop())


# ---------- BINANCE WS (bookTicker mid — our production signal venue) ----------
async def binance_loop():
    uri = ("wss://stream.binance.com:9443/stream?streams="
           "btcusdt@bookTicker/ethusdt@bookTicker/solusdt@bookTicker")
    want = {"BTCUSDT": "btc", "ETHUSDT": "eth", "SOLUSDT": "sol"}
    last = {}
    while time.time() < STOP_AT:
        try:
            async with websockets.connect(uri, open_timeout=15, ping_interval=20) as ws:
                while time.time() < STOP_AT:
                    raw = await asyncio.wait_for(ws.recv(), timeout=15)
                    try:
                        m = json.loads(raw).get("data") or {}
                    except Exception:
                        continue
                    sym = want.get(m.get("s"))
                    if not sym:
                        continue
                    mid = (float(m["b"]) + float(m["a"])) / 2
                    # bookTicker has no event-time; throttle to 100ms per sym to bound rows
                    now = time.time()
                    if now - last.get(sym, 0) >= 0.1:
                        last[sym] = now
                        add("binance", sym, now * 1000, mid)
        except Exception as e:
            print(f"[binance] reconnect: {str(e)[:60]}", flush=True)
            await asyncio.sleep(2)


def binance_thread():
    asyncio.run(binance_loop())


def main():
    print(f"benchmark {MINUTES:.0f} min — feeds: rtds, pyth, lazer, arb(btc/eth/sol)", flush=True)
    arb_verify()
    threads = [threading.Thread(target=rtds_thread, daemon=True),
               threading.Thread(target=pyth_thread, daemon=True),
               threading.Thread(target=lazer_thread, daemon=True),
               threading.Thread(target=binance_thread, daemon=True)]
    threads += [threading.Thread(target=arb_thread, args=(s,), daemon=True)
                for s in ARB_FEEDS]
    for t in threads:
        t.start()
    while time.time() < STOP_AT:
        time.sleep(10)
        with LOCK:
            n = len(ROWS)
        print(f"  t-{(STOP_AT-time.time())/60:.1f}min rows={n}", flush=True)
    time.sleep(2)
    with LOCK:
        df = pd.DataFrame(ROWS, columns=["feed", "sym", "t_local_ns", "t_feed_ms", "price"])
    OUT.mkdir(exist_ok=True)
    p = OUT / f"feed_bench_{int(time.time())}.parquet"
    df.to_parquet(p, index=False)
    print(f"saved {len(df)} rows -> {p}", flush=True)

    # ---------- analysis ----------
    print("\n=== rows per feed/sym ===")
    print(df.groupby(["feed", "sym"]).size().unstack(fill_value=0).to_string())
    print("\n=== transport delay (local_arrival - feed_ts) p50/p90 ms ===")
    df["lag_ms"] = df.t_local_ns / 1e6 - df.t_feed_ms
    print(df.groupby(["feed", "sym"]).lag_ms.quantile([0.5, 0.9]).round(0).unstack().to_string())

    # pairwise best-shift alignment vs rtds (100ms grid on local clock)
    print("\n=== price lead/lag vs RTDS (negative = feed LEADS rtds) ===")
    for sym in ["btc", "eth", "sol"]:
        base = df[(df.feed == "rtds") & (df.sym == sym)].sort_values("t_local_ns")
        if len(base) < 50:
            continue
        t0, t1 = base.t_local_ns.min(), base.t_local_ns.max()
        grid = np.arange(t0, t1, 100_000_000)  # 100ms
        def series(feed):
            s = df[(df.feed == feed) & (df.sym == sym)].sort_values("t_local_ns")
            if len(s) < 30:
                return None
            idx = np.searchsorted(s.t_local_ns.values, grid, "right") - 1
            v = np.where(idx >= 0, s.price.values[np.clip(idx, 0, None)], np.nan)
            return v
        b = series("rtds")
        for feed in ["lazer", "binance", "pyth", "arb"]:
            v = series(feed)
            if v is None:
                continue
            best, best_err = None, np.inf
            for shift in range(-100, 101, 2):   # +/-10s in 200ms steps
                vv = np.roll(v, shift)
                m = np.isfinite(b) & np.isfinite(vv)
                if m.sum() < 100:
                    continue
                err = np.nanmean(np.abs(b[m] - vv[m]) / b[m])
                if err < best_err:
                    best_err, best = err, shift
            if best is not None:
                print(f"  {sym} {feed}: best shift {best*0.1:+.1f}s (err {best_err*1e4:.1f}bp)"
                      f"  -> {'LEADS rtds' if best > 0 else 'LAGS rtds' if best < 0 else 'sync'}")

    # move-event first detection: RTDS move >= 5bp within 2s -> when did each feed cross half the move
    print("\n=== move-event first-detection (RTDS moves >=5bp/2s) ===")
    for sym in ["btc", "eth", "sol"]:
        base = df[(df.feed == "rtds") & (df.sym == sym)].sort_values("t_local_ns").reset_index(drop=True)
        if len(base) < 100:
            continue
        evs = []
        pv = base.price.values; tv = base.t_local_ns.values
        for i in range(len(base) - 2):
            j = np.searchsorted(tv, tv[i] + 2_000_000_000, "right") - 1
            if j <= i:
                continue
            mv = (pv[j] - pv[i]) / pv[i]
            if abs(mv) >= 5e-4:
                evs.append((tv[i], pv[i], pv[j]))
        evs = evs[:300]
        if not evs:
            print(f"  {sym}: no 5bp moves in sample"); continue
        for feed in ["lazer", "binance", "pyth", "arb"]:
            s = df[(df.feed == feed) & (df.sym == sym)].sort_values("t_local_ns")
            if len(s) < 30:
                continue
            st, sp = s.t_local_ns.values, s.price.values
            deltas = []
            for (te, p0, p1) in evs:
                half = (p0 + p1) / 2
                rising = p1 > p0
                k0 = np.searchsorted(st, te - 10_000_000_000)
                k1 = np.searchsorted(st, te + 10_000_000_000)
                seg_t, seg_p = st[k0:k1], sp[k0:k1]
                hit = np.where(seg_p >= half if rising else seg_p <= half)[0]
                if len(hit):
                    deltas.append((seg_t[hit[0]] - te) / 1e9)
            if deltas:
                d = np.array(deltas)
                print(f"  {sym} {feed}: n={len(d)}  median {np.median(d):+.2f}s  "
                      f"p25 {np.percentile(d,25):+.2f}s p75 {np.percentile(d,75):+.2f}s "
                      f"(negative = {feed} saw the move BEFORE rtds)")


if __name__ == "__main__":
    main()
