"""Shadow tracker — polls each watched wallet every 30s, logs new trades.

Per-wallet output: data/wallet_shadow/<short>/<utc_date>.jsonl with one
NEW trade per line. Also computes live realized PnL for each wallet's
recent trades against CLOB winners.

For each new BUY trade on a market we cover (BTC/ETH/SOL up-down), records
a "paper mirror decision" so we can evaluate what our engine would have
done at the same fire_us.

Usage:
    py -3 strategy_lab/wallet_hunt/shadow_track.py
        (uses the wallets configured in WATCHED below)

Stop with Ctrl-C; resumes from the latest cached trade per wallet.
"""
from __future__ import annotations
import argparse
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))

OUT_BASE = ROOT / "data" / "wallet_shadow"
OUT_BASE.mkdir(parents=True, exist_ok=True)
DATA_API = "https://data-api.polymarket.com"
UA = {"User-Agent": "global-strategy-lab/1.0", "Accept": "application/json"}

# Edit this list to add/remove wallets, or pass --wallets
WATCHED = [
    # short=eebde7a0 — contrarian pyramid, currently losing
    ("0xeebde7a0e019a63e6b476eb425505b7b3e6eba30", "user"),
    # short=ce25e214 — PROFITABLE contrarian pyramid +$7.05/leg
    ("0xce25e214d5cfe4f459cf67f08df581885aae7fdc", "user"),
    # short=89b5cdaa — market maker (35.9% both-sides)
    ("0x89b5cdaaa4866c1e738406712012a630b4078beb", "user"),
    # short=7cde1da9 — flash burst maker (5-min window)
    ("0x7cde1da9d380bf8002ccbe8e0cb9474c4d71e48e", "proxyWallet"),
    # short=cfb103c3 — losing BTC 5m pyramid
    ("0xcfb103c37c0234f524c632d964ed31f117b5f694", "user"),
    # short=04b6d7e9 — PROFITABLE deep-value, BTC 15m +$2466
    ("0x04b6d7e930cf9e493c5e6ef24b496294f95594c8", "user"),
]


def get(url: str, timeout: float = 10.0):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def latest_ts_for(wallet_short: str) -> int:
    """Read the latest timestamp we've seen for this wallet so we don't re-log."""
    odir = OUT_BASE / wallet_short
    if not odir.exists():
        return 0
    latest = 0
    for jl in sorted(odir.glob("*.jsonl")):
        with open(jl) as f:
            for line in f:
                try:
                    t = int(json.loads(line)["timestamp"])
                    if t > latest:
                        latest = t
                except Exception:
                    continue
    return latest


def poll_wallet(wallet: str, user_param: str) -> int:
    short = wallet.lower()[:10]
    odir = OUT_BASE / short
    odir.mkdir(parents=True, exist_ok=True)
    last_seen = latest_ts_for(short)
    url = f"{DATA_API}/trades?{user_param}={wallet}&limit=200&offset=0"
    try:
        trades = get(url)
    except Exception as e:
        print(f"  [{short}] poll error: {e}")
        return 0
    if not trades:
        return 0
    # Keep only trades newer than last_seen
    new_trades = [t for t in trades if int(t.get("timestamp", 0)) > last_seen]
    if not new_trades:
        return 0
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    outfile = odir / f"{today}.jsonl"
    new_trades.sort(key=lambda t: int(t["timestamp"]))
    with open(outfile, "a") as f:
        for t in new_trades:
            f.write(json.dumps(t, default=str) + "\n")
    return len(new_trades)


def status_line():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval-s", type=int, default=30, help="poll interval in seconds")
    ap.add_argument("--once", action="store_true", help="poll once and exit")
    ap.add_argument("--wallets", nargs="*", help="override WATCHED list (addresses only)")
    args = ap.parse_args()

    watch = WATCHED
    if args.wallets:
        watch = [(w, "user") for w in args.wallets]

    print(f"=== shadow_track started — {len(watch)} wallets, interval {args.interval_s}s")
    print(f"=== output dir: {OUT_BASE}")
    print(f"=== Ctrl-C to stop. Resume-safe.")

    while True:
        loop_start = time.time()
        line = []
        for wallet, user_param in watch:
            try:
                n = poll_wallet(wallet, user_param)
            except Exception as e:
                n = -1
            short = wallet.lower()[:10]
            line.append(f"{short}={n:+d}" if n else f"{short}=.")
        print(f"  {status_line()}  {' '.join(line)}", flush=True)
        if args.once:
            return
        elapsed = time.time() - loop_start
        sleep_for = max(1, args.interval_s - elapsed)
        time.sleep(sleep_for)


if __name__ == "__main__":
    main()
