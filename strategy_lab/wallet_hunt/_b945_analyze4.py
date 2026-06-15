"""b945: per-slug stats table + capital growth from full chain history.

Sources:
 - cache/0xb945945d/alchemy_transfers.parquet  (FULL Mar 16 -> Jun 11 chain record)
 - cache/_pm_portfolio/0xb945945d/activity_TRADE.json   (3,500 most-recent fills, capped)
 - cache/_pm_portfolio/0xb945945d/activity_REDEEM.json  (redemptions w/ slug)
"""
import json, collections, datetime as dt
import pandas as pd

P = "strategy_lab/wallet_hunt/cache/_pm_portfolio/0xb945945d/"
tr = json.load(open(P + "activity_TRADE.json"))
rd = json.load(open(P + "activity_REDEEM.json"))

def ts2d(ts): return dt.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")

print("=== data-api spans ===")
print("TRADE:  n=%d  %s -> %s" % (len(tr), ts2d(min(t['timestamp'] for t in tr)), ts2d(max(t['timestamp'] for t in tr))))
print("REDEEM: n=%d  %s -> %s" % (len(rd), ts2d(min(r['timestamp'] for r in rd)), ts2d(max(r['timestamp'] for r in rd))))

# ---------- per-slug table (TRADE window only, where trades are complete) ----------
tr_min = min(t['timestamp'] for t in tr)
buys  = [t for t in tr if t['side'] == 'BUY']
sells = [t for t in tr if t['side'] == 'SELL']

cost = collections.defaultdict(float); ntr = collections.Counter()
sellpro = collections.defaultdict(float)
slug_of = {}
for t in buys:
    c = t['conditionId']; cost[c] += t['usdcSize']; ntr[c] += 1; slug_of[c] = t.get('slug')
for t in sells:
    c = t['conditionId']; sellpro[c] += t['usdcSize']; ntr[c] += 1; slug_of.setdefault(c, t.get('slug'))

redeem = collections.defaultdict(float)
for r in rd:
    if r['timestamp'] >= tr_min:
        redeem[r['conditionId']] += r['usdcSize']

# only slugs whose FIRST trade is inside the window (avoid partial-cost slugs at the boundary)
first_ts = {}
for t in sorted(tr, key=lambda x: x['timestamp']):
    first_ts.setdefault(t['conditionId'], t['timestamp'])

rows = []
now = max(t['timestamp'] for t in tr)
for c, cst in cost.items():
    # skip last 30 min (may be unsettled)
    pnl = redeem.get(c, 0.0) + sellpro.get(c, 0.0) - cst
    settled = (c in redeem) or (now - first_ts[c] > 3600)
    rows.append(dict(cond=c, slug=slug_of.get(c), n=ntr[c], cost=cst,
                     redeem=redeem.get(c, 0.0), pnl=pnl, settled=settled))
df = pd.DataFrame(rows)
dfs = df[df.settled]
won = (dfs.pnl > 0)
print("\n=== PER-SLUG TABLE (complete-trade window %s -> %s) ===" % (ts2d(tr_min), ts2d(now)))
print("slugs traded (settled): %d   total fills: %d (%d BUY / %d SELL)" % (len(dfs), len(tr), len(buys), len(sells)))
print("trades per slug: mean %.1f  median %.0f" % (dfs.n.mean(), dfs.n.median()))
print("WR (slug pnl>0): %.1f%%   (win %d / loss %d / flat %d)" % (
    100*won.mean(), won.sum(), (dfs.pnl < 0).sum(), (dfs.pnl == 0).sum()))
print("profit per slug: mean $%.2f  median $%.2f  p10 $%.2f  p90 $%.2f" % (
    dfs.pnl.mean(), dfs.pnl.median(), dfs.pnl.quantile(.1), dfs.pnl.quantile(.9)))
print("capital per slug (cost): mean $%.2f  median $%.2f  p90 $%.2f  max $%.2f" % (
    dfs.cost.mean(), dfs.cost.median(), dfs.cost.quantile(.9), dfs.cost.max()))
print("avg win $%.2f / avg loss $%.2f" % (dfs.pnl[dfs.pnl>0].mean(), dfs.pnl[dfs.pnl<0].mean()))

# ---------- full-history capital growth (alchemy chain) ----------
a = pd.read_parquet("strategy_lab/wallet_hunt/cache/0xb945945d/alchemy_transfers.parquet")
u = a[a.asset == "pUSD"].copy()
u["dt"] = pd.to_datetime(u.ts, utc=True)
ZERO = "0x0000000000000000000000000000000000000000"
# counterparty sets seen on polymarket flow
EXCH = {"0xe1111800f7b1f7e1f0db9d4a89e9e2f2e32e6c64",  # matcher (varies, prefix match below)
        }
def cls(row):
    cp = (row["from"] if row.direction == "to" else row["to"]) or ""
    if cp == ZERO: return "ctf"
    if cp.startswith("0xe1111800") or cp.startswith("0x4bfb41d5") or cp.startswith("0xc5d563a3"): return "exchange"
    return "external"
u["cp_class"] = u.apply(cls, axis=1)
u["signed"] = u.value.where(u.direction == "to", -u.value)

ext = u[u.cp_class == "external"].sort_values("dt")
print("\n=== external capital flows (deposits/withdrawals) ===")
for _, r in ext.iterrows():
    print("  %s  %+10.2f  cp=%s" % (r["dt"].strftime("%Y-%m-%d %H:%M"), r["signed"],
          (r["from"] if r["direction"] == "to" else r["to"])[:10]))
dep_in  = ext[ext.signed > 0].signed.sum()
dep_out = -ext[ext.signed < 0].signed.sum()
first_dep = ext[ext.signed > 0].iloc[0] if (ext.signed > 0).any() else None

trading = u[u.cp_class != "external"]
cum = trading.set_index("dt").sort_index().signed.cumsum()
weekly = trading.set_index("dt").sort_index().signed.resample("W").sum().cumsum()
print("\n=== capital growth ===")
print("external deposits in: $%.2f   withdrawals out: $%.2f" % (dep_in, dep_out))
if first_dep is not None:
    print("FIRST deposit: $%.2f on %s" % (first_dep.signed, first_dep.dt.strftime("%Y-%m-%d")))
print("trading net cash (cum PnL proxy): $%.2f" % cum.iloc[-1])
print("\nweekly cumulative trading PnL:")
for d, v in weekly.items():
    print("  %s  $%+10.2f" % (d.strftime("%Y-%m-%d"), v))

# sizing growth: median USDC-out per buy-tx per week
buytx = u[(u.cp_class != "external") & (u.direction == "from")].copy()
g = buytx.set_index("dt").sort_index().value.resample("W").median()
gq = buytx.set_index("dt").sort_index().value.resample("W").quantile(.9)
n = buytx.set_index("dt").sort_index().value.resample("W").count()
print("\nweekly clip size (USDC out per tx): median / p90 / n_tx")
for d in g.index:
    print("  %s  $%6.2f / $%7.2f / %5d" % (d.strftime("%Y-%m-%d"), g[d], gq[d], n[d]))
