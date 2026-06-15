"""b945 step 1: full fill-tape reconstruction from chain.

1. Resolve unknown ERC1155 token_ids via gamma API (?clob_token_ids=, batched).
2. Reconstruct per-fill tape: tx_hash groups -> (ts, slug, outcome, side, shares, usd, price).
   Single-token txs only for price integrity (report skip %).
Output:
  cache/0xb945945d/token_lookup_ext.parquet
  cache/0xb945945d/fill_tape.parquet
"""
import json, time, urllib.request, urllib.parse
from pathlib import Path
import pandas as pd
import numpy as np

CACHE = Path(__file__).resolve().parent / "cache"
W = CACHE / "0xb945945d"
UA = {"User-Agent": "global-strategy-lab/1.0"}

a = pd.read_parquet(W / "alchemy_transfers.parquet")
lk = pd.read_parquet(CACHE / "_token_lookup.parquet")

e = a[a.category == "erc1155"].copy()
e["tok"] = e.asset.map(lambda x: str(int(x, 16)) if isinstance(x, str) and x.startswith("0x") else str(x))
known = {str(r.asset_id): (r.slug, r.outcome) for r in lk.itertuples()}

ext_p = W / "token_lookup_ext.parquet"
if ext_p.exists():
    ext = pd.read_parquet(ext_p)
    for r in ext.itertuples():
        known[str(r.asset_id)] = (r.slug, r.outcome)
    print(f"loaded existing ext: {len(ext)}")

unk = sorted(set(e.tok) - set(known))
print(f"tokens: {e.tok.nunique()} total, {len(unk)} unknown -> gamma batch lookup")

# Gamma does NOT index short-form serial markets (tested: known 15m token -> 0 results).
# Correct source: CLOB GET /markets/{condition_id}; condition_id = canonical resolutions.market_id.
new_rows = []
ROOT = Path(__file__).resolve().parents[2]
res = pd.read_parquet(ROOT / "data" / "v4" / "canonical" / "resolutions.parquet",
                      columns=["market_id", "slug"])
res = res[res.slug.str.contains("btc-updown-15m", na=False, regex=False)].drop_duplicates("slug")
clob_cache = pd.read_parquet(ROOT / "data" / "v4" / "canonical" / "clob_resolutions_cache.parquet")
have_slugs = set(clob_cache.slug.dropna())
# seed known from clob cache too
for r in clob_cache.itertuples():
    if pd.notna(r.up_token_id):
        known.setdefault(str(r.up_token_id), (r.slug, "Up"))
    if pd.notna(r.down_token_id):
        known.setdefault(str(r.down_token_id), (r.slug, "Down"))
unk = sorted(set(e.tok) - set(known))
print(f"after clob-cache seed: {len(unk)} still unknown; "
      f"fetching {len(res[~res.slug.isin(have_slugs)])} missing btc-15m markets from CLOB")

todo = res[~res.slug.isin(have_slugs)]
for k, r in enumerate(todo.itertuples()):
    url = f"https://clob.polymarket.com/markets/{r.market_id}"
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=20) as rr:
                m = json.loads(rr.read().decode())
            for t in m.get("tokens", []):
                new_rows.append(dict(asset_id=str(t.get("token_id")), slug=r.slug,
                                     outcome=t.get("outcome")))
            break
        except Exception as ex:
            if attempt == 2:
                pass
            time.sleep(1.0 * (attempt + 1))
    if k % 250 == 0:
        print(f"  clob {k}/{len(todo)}: +{len(new_rows)} token rows", flush=True)
    time.sleep(0.08)

if new_rows:
    ext_new = pd.DataFrame(new_rows).drop_duplicates("asset_id")
    if ext_p.exists():
        ext_new = pd.concat([pd.read_parquet(ext_p), ext_new]).drop_duplicates("asset_id")
    ext_new.to_parquet(ext_p, index=False)
    for r in ext_new.itertuples():
        known[str(r.asset_id)] = (r.slug, r.outcome)
    print(f"ext lookup saved: {len(ext_new)} tokens")

cov = e.tok.isin(known).mean()
print(f"coverage now: {cov:.1%}")

# ---- fill tape ----
u = a[a.asset.isin(["pUSD", "USDCE"])].copy()
usd_out = u[u.direction == "from"].groupby("tx_hash").value.sum()
usd_in = u[u.direction == "to"].groupby("tx_hash").value.sum()

rows = []
skipped_multi = 0
for tx, g in e.groupby("tx_hash"):
    gin = g[g.direction == "to"]     # tokens received = BUY legs
    gout = g[g.direction == "from"]  # tokens sent = SELL/redeem legs
    if len(gin) and not len(gout):
        toks = gin.tok.unique()
        if len(toks) != 1:
            skipped_multi += 1
            continue
        sl_o = known.get(toks[0])
        if sl_o is None:
            continue
        shares = gin.value.sum()
        usd = usd_out.get(tx, np.nan)
        if not np.isfinite(usd) or shares <= 0:
            continue
        px = usd / shares
        if not (0.001 <= px <= 1.0):
            continue
        rows.append(dict(tx=tx, ts=gin.ts.iloc[0], side="BUY", slug=sl_o[0],
                         outcome=sl_o[1], shares=shares, usd=usd, price=px))
    elif len(gout) and not len(gin):
        toks = gout.tok.unique()
        if len(toks) != 1:
            continue
        sl_o = known.get(toks[0])
        if sl_o is None:
            continue
        shares = gout.value.sum()
        usd = usd_in.get(tx, np.nan)
        is_redeem = (gout.to == "0x0000000000000000000000000000000000000000").any()
        rows.append(dict(tx=tx, ts=gout.ts.iloc[0], side=("REDEEM" if is_redeem else "SELL"),
                         slug=sl_o[0], outcome=sl_o[1], shares=shares,
                         usd=usd if np.isfinite(usd) else 0.0,
                         price=(usd / shares) if (np.isfinite(usd) and shares > 0) else np.nan))

T = pd.DataFrame(rows)
T["ts_dt"] = pd.to_datetime(T.ts, utc=True)
T = T.sort_values("ts_dt").reset_index(drop=True)
T.to_parquet(W / "fill_tape.parquet", index=False)
print(f"\nfill tape: {len(T)} rows ({(T.side=='BUY').sum()} BUY / {(T.side=='SELL').sum()} SELL / "
      f"{(T.side=='REDEEM').sum()} REDEEM), multi-token tx skipped: {skipped_multi}")
print(f"span: {T.ts_dt.min()} -> {T.ts_dt.max()}")
b = T[T.side == "BUY"]
print(f"BUY price: med {b.price.median():.3f}  usd med {b.usd.median():.2f}")
print(f"slugs: {b.slug.nunique()}  | Apr22+ buys: {(b.ts_dt >= '2026-04-22').sum()}")
