# Hyperliquid Archive Ingestion

## Prerequisites — 1 thing you must do

The bucket is **requester-pays**: you need AWS credentials (any AWS account works, even a brand-new free one).

**Set them up, either of:**

**Option 1 — Env vars (simplest)**
```bash
export AWS_ACCESS_KEY_ID=AKIA...
export AWS_SECRET_ACCESS_KEY=...
export AWS_DEFAULT_REGION=us-east-1
```

**Option 2 — `~/.aws/credentials`**
```ini
[default]
aws_access_key_id = AKIA...
aws_secret_access_key = ...
region = us-east-1
```

To get keys:
1. Sign into AWS console
2. IAM → Users → your user → Security credentials → Create access key (type: CLI)
3. Copy both values (you won't see the secret again)

**Permissions needed:** `s3:GetObject` with `requester-pays` header on `arn:aws:s3:::hyperliquid-archive/*`. The default user policy with AmazonS3ReadOnlyAccess is sufficient.

## What's in the archive

| Path | Contents |
|---|---|
| `market_data/YYYYMMDD/[0..23]/l2Book/[coin].lz4` | Sub-second L2 book snapshots, hourly files, per-coin |
| `asset_ctxs/YYYYMMDD.csv.lz4` | Daily snapshot of funding rate, OI, mark price for every asset |

**Fills/liquidations** live in a separate bucket `s3://hl-mainnet-node-data/node_fills_by_block` — same setup but different folder layout (one Parquet file per block). We'll wire that in after the archive test is green.

## Usage

**1. Sanity test (~1 MB download, verifies credentials + format):**
```bash
python -m strategy_lab.hyperliquid.fetch_archive --test
```

**2. Bulk pull a date range:**
```bash
python -m strategy_lab.hyperliquid.fetch_archive \
    --start 2024-01-01 --end 2024-01-31 --coins BTC ETH SOL
```

Skips already-downloaded files, so you can resume anytime.

## Cost estimate
- Per coin per day of L2 snapshots: **100-500 MB** (varies with volatility / venue activity)
- 3 coins × 1 month ≈ 10-40 GB ≈ **$1-4** at $0.09/GB egress
- 3 coins × 3 years ≈ 300-500 GB ≈ **$25-45**

Run the `--test` first and look at the actual size of one hour to calibrate before committing.
