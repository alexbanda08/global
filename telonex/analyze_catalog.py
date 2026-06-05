"""Analyze Telonex catalog for OUR use case: BTC/ETH/SOL up-or-down coverage + channels + date range."""
from pathlib import Path
import pandas as pd
pd.set_option("display.width", 200)

C = Path(r"C:\Users\alexandre bandarra\Desktop\global\telonex\samples\markets_catalog.parquet")
df = pd.read_parquet(C)
s = df["slug"].astype(str)

print(f"TOTAL markets: {len(df):,}")
print(f"exchanges: {df.exchange.value_counts().to_dict()}")

# up-or-down universe
ud = df[s.str.contains("up-or-down", case=False, na=False)].copy()
uds = ud["slug"].astype(str)
print(f"\n=== UP-OR-DOWN: {len(ud):,} markets ===")

# our crypto assets
for asset in ["bitcoin","ethereum","solana","btc","eth","sol","xrp","bnb"]:
    n = uds.str.contains(f"^{asset}-up-or-down|^{asset}-", case=False, na=False, regex=True).sum()
    print(f"  {asset}: {n:,}")

# epoch-style (matches OUR canonical btc-updown-5m-<epoch> / 15m)
print("\n=== EPOCH-STYLE (our canonical format) ===")
for pat in ["-up-or-down-5m-", "-up-or-down-15m-", "-up-or-down-1m-", "-up-or-down-1h-"]:
    sub = ud[uds.str.contains(pat, na=False)]
    print(f"  *{pat}* : {len(sub):,}")
    if len(sub):
        # coverage dates from book_snapshot_25
        b = sub[sub["book_snapshot_25_from"].notna()]
        if len(b):
            print(f"      book_snapshot_25 coverage: {b['book_snapshot_25_from'].min()} -> {b['book_snapshot_25_to'].max()}  ({len(b):,} mkts w/ L25)")

# BTC/ETH/SOL up-or-down (both human + epoch) channel coverage
print("\n=== BTC/ETH/SOL up-or-down — per-channel coverage ===")
crypto = ud[uds.str.contains("bitcoin|ethereum|solana|^btc-|^eth-|^sol-", case=False, na=False, regex=True)].copy()
print(f"  crypto up-or-down markets: {len(crypto):,}")
for ch in ["trades","quotes","book_snapshot_25","book_snapshot_full","onchain_fills"]:
    fr, to = f"{ch}_from", f"{ch}_to"
    has = crypto[crypto[fr].notna() & (crypto[fr] != "")]
    if len(has):
        print(f"  {ch:<20} {len(has):>7,} mkts   {has[fr].min()} -> {has[to].max()}")
    else:
        print(f"  {ch:<20} none")

# earliest crypto up-down ever (how far back can we backfill?)
print("\n=== BACKFILL POTENTIAL (earliest dates) ===")
cb = crypto[crypto["trades_from"].notna() & (crypto["trades_from"]!="")]
print(f"  earliest crypto up-down trades_from: {cb['trades_from'].min()}")
print(f"  latest crypto up-down trades_to:     {cb['trades_to'].max()}")
# our canonical starts 2026-04-22 — how many crypto up-down markets BEFORE that?
pre = cb[cb["trades_from"] < "2026-04-22"]
print(f"  crypto up-down markets w/ data BEFORE 2026-04-22 (our window start): {len(pre):,}")

# sample of our-style 5m/15m epoch slugs with their coverage
print("\n=== SAMPLE epoch 5m/15m slugs + L25 coverage ===")
ep = ud[uds.str.contains("-up-or-down-(5m|15m)-", na=False, regex=True)].copy()
ep = ep[ep["book_snapshot_25_from"].notna() & (ep["book_snapshot_25_from"]!="")]
print(ep[["slug","book_snapshot_25_from","book_snapshot_25_to","onchain_fills_from","status"]].head(12).to_string(index=False))
