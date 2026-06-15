#!/usr/bin/env python3
"""
Pyth Lazer (Pyth Pro) real-time WS reachability + latency probe.

Goal: prove whether we can actually REACH and SUBSCRIBE to the fast channels
(`real_time` / `fixed_rate@1ms`) for BTC/ETH/SOL, and measure the true cadence +
observed latency. If this passes, port the connect/subscribe/parse logic into the
storedata collector.

Ground truth (SDK @pythnetwork/pyth-lazer-sdk v6.2.2, verified 2026-06-12):
  - Auth (server/Node path): HTTP header  Authorization: Bearer <token>  on the WS upgrade.
    (Browser path uses ?ACCESS_TOKEN=; we use the header path.)
  - 3 HA endpoints: wss://pyth-lazer-{0,1,2}.dourolabs.app/v1/stream
  - Feed IDs are u32 ints: BTC=1, ETH=2, SOL=6. price is a STRING i64; real = price * 10**exponent (exponent=-8).
  - Subscribe msg fields: type, subscriptionId, priceFeedIds, properties, formats, channel,
    deliveryFormat, parsed, ignoreInvalidFeedIds.
  - Channels: real_time (1-50ms, push-on-change), fixed_rate@1ms|50ms|200ms|1000ms.
  - Permission: real_time / 1ms need a paid tier. Upgrade rejects with HTTP 401 (bad token)
    / 403 (no permission); or an accepted socket may return a JSON {"type":"error"} on subscribe.
  - SETTLEMENT CAVEAT: Pyth != Chainlink. This is a SIGNAL source; Polymarket settles on Chainlink RTDS.

Usage:
  export PYTH_LAZER_TOKEN=...           # free key from https://pythdata.app (real_time needs paid tier)
  python pyth_lazer/probe_lazer.py                       # default: real_time, 20s, BTC/ETH/SOL
  python pyth_lazer/probe_lazer.py --channel fixed_rate@1ms --seconds 30
  python pyth_lazer/probe_lazer.py --channel fixed_rate@200ms   # works on free tier (sanity check)
  python pyth_lazer/probe_lazer.py --fallback              # if fast channel is denied, auto-retry @200ms to prove token works

Deps: pip install websockets
"""
import argparse
import asyncio
import json
import os
import sys
import time

try:
    import websockets
except ImportError:
    sys.exit("missing dep: pip install websockets")

ENDPOINTS = [
    "wss://pyth-lazer-0.dourolabs.app/v1/stream",
    "wss://pyth-lazer-1.dourolabs.app/v1/stream",
    "wss://pyth-lazer-2.dourolabs.app/v1/stream",
]
FEEDS = {1: "BTC", 2: "ETH", 6: "SOL"}
EXP = -8  # Pyth crypto exponent; real price = int(price) * 10**EXP


def _pct(vals, p):
    if not vals:
        return float("nan")
    s = sorted(vals)
    k = max(0, min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1)))))
    return s[k]


async def _connect(url, token):
    """Connect with Bearer header across websockets lib versions (additional_headers vs extra_headers)."""
    hdr = [("Authorization", f"Bearer {token}")]
    try:
        return await websockets.connect(url, additional_headers=hdr, open_timeout=10, ping_interval=20)
    except TypeError:
        return await websockets.connect(url, extra_headers=dict(hdr), open_timeout=10, ping_interval=20)


def _status_of(exc):
    """Pull HTTP status from whichever websockets exception type fired at upgrade."""
    for attr in ("status_code",):
        if hasattr(exc, attr):
            return getattr(exc, attr)
    resp = getattr(exc, "response", None)
    if resp is not None and hasattr(resp, "status_code"):
        return resp.status_code
    return None


async def reach_test(token):
    """Per-endpoint reachability: can we open the socket with this token?"""
    print("== endpoint reachability ==")
    ok = []
    for url in ENDPOINTS:
        try:
            ws = await _connect(url, token)
            await ws.close()
            print(f"  OK   {url}")
            ok.append(url)
        except Exception as e:  # noqa: BLE001
            st = _status_of(e)
            tag = f"HTTP {st}" if st else type(e).__name__
            print(f"  FAIL {url}  ({tag}: {e})")
    return ok


def _subscribe_msg(channel):
    return {
        "type": "subscribe",
        "subscriptionId": 1,
        "priceFeedIds": list(FEEDS.keys()),
        "properties": ["price", "bestBidPrice", "bestAskPrice", "exponent", "feedUpdateTimestamp"],
        "formats": [],  # empty => no signed binary blob, just parsed JSON (lowest overhead for a probe)
        "channel": channel,
        "deliveryFormat": "json",
        "parsed": True,
        "ignoreInvalidFeedIds": True,
    }


async def run_stream(url, token, channel, seconds):
    """Subscribe and collect cadence/latency stats for `seconds`. Returns a dict summary or raises."""
    ws = await _connect(url, token)
    await ws.send(json.dumps(_subscribe_msg(channel)))

    counts = {fid: 0 for fid in FEEDS}
    gaps = {fid: [] for fid in FEEDS}        # inter-arrival ms per feed (true cadence)
    last_recv = {fid: None for fid in FEEDS}
    skew = {fid: [] for fid in FEEDS}        # recv_us - timestampUs (ms); includes clock offset
    stale = {fid: 0 for fid in FEEDS}        # feedUpdateTimestamp < timestampUs => carried-forward
    last_price = {fid: None for fid in FEEDS}
    first_err = None
    t_end = time.time() + seconds
    t0 = time.time()

    while time.time() < t_end:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=max(0.1, t_end - time.time()))
        except asyncio.TimeoutError:
            break
        recv_us = time.time() * 1e6
        try:
            m = json.loads(raw)
        except Exception:  # noqa: BLE001
            continue
        mt = m.get("type")
        if mt == "error" or (mt and "error" in str(mt).lower()):
            first_err = first_err or m
            break
        if mt != "streamUpdated":
            continue  # subscribed/heartbeat/etc.
        parsed = m.get("parsed") or {}
        ts_us = float(parsed.get("timestampUs", 0) or 0)
        for pf in parsed.get("priceFeeds", []):
            fid = pf.get("priceFeedId")
            if fid not in FEEDS:
                continue
            counts[fid] += 1
            if last_recv[fid] is not None:
                gaps[fid].append((recv_us - last_recv[fid]) / 1000.0)
            last_recv[fid] = recv_us
            if ts_us:
                skew[fid].append((recv_us - ts_us) / 1000.0)
            fut = pf.get("feedUpdateTimestamp")
            if fut is not None and ts_us and float(fut) < ts_us:
                stale[fid] += 1
            if pf.get("price") is not None:
                last_price[fid] = int(pf["price"]) * (10 ** EXP)

    await ws.close()
    if first_err is not None:
        raise RuntimeError(f"subscribe rejected: {first_err}")
    dur = max(1e-6, time.time() - t0)
    return {
        "channel": channel, "url": url, "dur_s": dur,
        "counts": counts, "gaps": gaps, "skew": skew, "stale": stale, "last_price": last_price,
    }


def print_summary(s):
    print(f"\n== stream summary  (channel={s['channel']}, {s['dur_s']:.1f}s, {s['url']}) ==")
    print(f"{'feed':<5} {'msgs':>6} {'msg/s':>7} {'gap_p50':>9} {'gap_p99':>9} {'gap_min':>9} "
          f"{'lat_p50':>9} {'stale':>6}  last_price")
    total = 0
    for fid, name in FEEDS.items():
        c = s["counts"][fid]; total += c
        g = s["gaps"][fid]; lat = s["skew"][fid]
        rate = c / s["dur_s"]
        lp = s["last_price"][fid]
        lp_str = f"{lp:,.2f}" if lp is not None else "-"
        print(f"{name:<5} {c:>6} {rate:>7.1f} "
              f"{_pct(g,50):>8.1f}m {_pct(g,99):>8.1f}m {(min(g) if g else float('nan')):>8.1f}m "
              f"{_pct(lat,50):>8.1f}m {s['stale'][fid]:>6}  {lp_str}")
    print(f"\ntotal msgs: {total} | gap_* = inter-arrival ms (TRUE cadence) | "
          f"lat_p50 = recv-server ms (incl clock skew, indicative)")
    fastest = min((min(s["gaps"][f]) for f in FEEDS if s["gaps"][f]), default=None)
    if fastest is not None:
        print(f"fastest observed inter-arrival: {fastest:.1f} ms")


async def main():
    ap = argparse.ArgumentParser(description="Pyth Lazer real-time reachability + latency probe")
    ap.add_argument("--channel", default="real_time",
                    help="real_time | fixed_rate@1ms | fixed_rate@50ms | fixed_rate@200ms | fixed_rate@1000ms")
    ap.add_argument("--seconds", type=int, default=20)
    ap.add_argument("--token", default=os.environ.get("PYTH_LAZER_TOKEN", ""))
    ap.add_argument("--url", default=ENDPOINTS[0], help="primary stream endpoint")
    ap.add_argument("--fallback", action="store_true",
                    help="if fast channel is denied, retry @200ms to confirm the token works at all")
    args = ap.parse_args()

    if not args.token:
        sys.exit("no token. set PYTH_LAZER_TOKEN (free key: https://pythdata.app) or pass --token")

    ok = await reach_test(args.token)
    if not ok:
        sys.exit("\nUNREACHABLE: token rejected at upgrade on all endpoints (401=bad token, 403=no perm).")

    url = args.url if args.url in ok else ok[0]
    try:
        s = await run_stream(url, args.token, args.channel, args.seconds)
        print_summary(s)
        print(f"\nRESULT: channel '{args.channel}' is REACHABLE and streaming. Port to storedata.")
    except RuntimeError as e:
        print(f"\nRESULT: channel '{args.channel}' DENIED/failed -> {e}")
        if args.fallback and args.channel != "fixed_rate@200ms":
            print("retrying @200ms to confirm the token itself works...")
            s = await run_stream(url, args.token, "fixed_rate@200ms", min(10, args.seconds))
            print_summary(s)
            print("\nRESULT: token valid; the FAST channel needs a paid-tier upgrade (contact Pyth).")
        else:
            print("token may be valid but lacks fast-channel permission (free tier = >=200ms). "
                  "Re-run with --fallback to confirm, or upgrade the key.")


if __name__ == "__main__":
    asyncio.run(main())
