"""
Hyperliquid public archive downloader.

Bucket:     s3://hyperliquid-archive  (requester-pays)
Layout:
  market_data/[YYYYMMDD]/[hour]/[datatype]/[coin].lz4     L2 book snapshots
  asset_ctxs/[YYYYMMDD].csv.lz4                            funding + OI + marks

Fills / liquidations live in a separate bucket:
  s3://hl-mainnet-node-data/node_fills_by_block            trade fills (incl. liq)

This downloader supports:
  * test-mode: pull 1 day / 1 hour / 1 coin to verify end-to-end
  * bulk-mode: date range × coin list (with idempotent skip)
  * LZ4 decompression and Parquet conversion for market_data/*/l2Book

Requires AWS credentials configured (env vars OR ~/.aws/credentials)
with S3:GetObject + requester-pays authorisation.

Usage:
    python -m strategy_lab.hyperliquid.fetch_archive --test
    python -m strategy_lab.hyperliquid.fetch_archive --start 2024-01-01 --end 2024-01-07 --coins BTC ETH SOL
"""
from __future__ import annotations
import argparse
import io
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import lz4.frame
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, NoCredentialsError

ROOT = Path(__file__).resolve().parent.parent.parent    # .../global
OUT  = ROOT / "data" / "hyperliquid"
BUCKET = "hyperliquid-archive"

# One session; reused across all downloads
_session = None
def s3():
    global _session
    if _session is None:
        _session = boto3.client("s3", config=Config(
            retries={"max_attempts": 5, "mode": "adaptive"},
            connect_timeout=15, read_timeout=60,
        ))
    return _session


def _dl(key: str, local: Path, quiet: bool = False) -> int:
    """Download an S3 key with requester-pays. Returns bytes written (0 on skip)."""
    if local.exists() and local.stat().st_size > 0:
        return 0
    local.parent.mkdir(parents=True, exist_ok=True)
    try:
        obj = s3().get_object(Bucket=BUCKET, Key=key, RequestPayer="requester")
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code")
        if code in ("NoSuchKey", "404"):
            if not quiet:
                print(f"  miss  {key}")
            return -1
        raise
    body = obj["Body"].read()
    local.write_bytes(body)
    return len(body)


def fetch_l2(d: date, coin: str, hours=range(24)) -> dict:
    """Fetch all hourly L2 snapshot files for a coin/date. Stores .lz4 raw files."""
    out_dir = OUT / "raw" / "market_data" / d.strftime("%Y%m%d") / coin
    stats = {"downloaded": 0, "bytes": 0, "missing": 0, "skipped": 0}
    for h in hours:
        key = f"market_data/{d.strftime('%Y%m%d')}/{h}/l2Book/{coin}.lz4"
        local = out_dir / f"{h:02d}.lz4"
        n = _dl(key, local, quiet=True)
        if n == 0:
            stats["skipped"] += 1
        elif n == -1:
            stats["missing"] += 1
        else:
            stats["downloaded"] += 1
            stats["bytes"] += n
    return stats


def fetch_asset_ctx(d: date) -> int:
    key = f"asset_ctxs/{d.strftime('%Y%m%d')}.csv.lz4"
    local = OUT / "raw" / "asset_ctxs" / f"{d.strftime('%Y%m%d')}.csv.lz4"
    return _dl(key, local)


def decompress_inspect(lz4_path: Path, max_chars: int = 800) -> str:
    """Decompress an LZ4 file and return a preview."""
    raw = lz4.frame.decompress(lz4_path.read_bytes())
    return raw[:max_chars].decode("utf-8", errors="replace")


def test_mode():
    """Sanity check: pull 1 hour of BTC L2 on a known-good date + 1 day asset_ctx."""
    print("=== Hyperliquid archive test ===")
    print(f"  Output dir: {OUT}")
    # credentials sanity
    try:
        ident = boto3.client("sts").get_caller_identity()
        print(f"  AWS account: {ident.get('Account')}  arn: {ident.get('Arn')}")
    except NoCredentialsError:
        print("  ERROR: No AWS credentials. Configure ~/.aws/credentials or AWS_ACCESS_KEY_ID env vars.")
        sys.exit(2)

    d = date(2024, 6, 1)              # arbitrary known-available date
    print(f"\n[1] Pulling BTC L2 hour 12 for {d} ...")
    t0 = time.time()
    out = fetch_l2(d, "BTC", hours=[12])
    print(f"    {out}  ({time.time()-t0:.1f}s)")

    print(f"\n[2] Pulling asset_ctxs for {d} ...")
    n = fetch_asset_ctx(d)
    print(f"    bytes={n}")

    lz4s = list((OUT / "raw" / "market_data" / d.strftime('%Y%m%d') / "BTC").glob("*.lz4"))
    if lz4s:
        print(f"\n[3] Decompressing {lz4s[0]} ...")
        print("    first 600 chars:")
        print("    " + decompress_inspect(lz4s[0], 600).replace("\n", "\n    "))

    ctx = OUT / "raw" / "asset_ctxs" / f"{d.strftime('%Y%m%d')}.csv.lz4"
    if ctx.exists():
        print(f"\n[4] Decompressing asset_ctxs ...")
        print("    " + decompress_inspect(ctx, 400).replace("\n", "\n    "))

    print(f"\nTotal size on disk: "
          f"{sum(p.stat().st_size for p in OUT.rglob('*') if p.is_file()) / 1024 / 1024:.2f} MB")


def bulk_fetch(start_d: date, end_d: date, coins: list[str]):
    total_bytes = 0
    t0 = time.time()
    for d in daterange(start_d, end_d):
        # asset_ctxs once per day
        n = fetch_asset_ctx(d)
        if n > 0: total_bytes += n

        for coin in coins:
            stats = fetch_l2(d, coin)
            total_bytes += stats["bytes"]
            print(f"  {d} {coin:6s}  dl={stats['downloaded']}  skip={stats['skipped']}  "
                  f"miss={stats['missing']}  +{stats['bytes']/1024/1024:.1f} MB",
                  flush=True)
    print(f"\nTotal new bytes: {total_bytes/1024/1024:.1f} MB  "
          f"in {time.time()-t0:.1f}s")


def daterange(start_d: date, end_d: date):
    d = start_d
    while d <= end_d:
        yield d
        d = d + timedelta(days=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true",
                    help="1-day sanity check before committing to bulk download")
    ap.add_argument("--start",  type=lambda s: date.fromisoformat(s))
    ap.add_argument("--end",    type=lambda s: date.fromisoformat(s))
    ap.add_argument("--coins",  nargs="+", default=["BTC", "ETH", "SOL"])
    a = ap.parse_args()

    if a.test:
        test_mode()
        return
    if not (a.start and a.end):
        ap.error("--start and --end required for bulk")
    bulk_fetch(a.start, a.end, a.coins)


if __name__ == "__main__":
    main()
