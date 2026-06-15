"""b945 part 2: seed capital + equity growth + sizing growth from full chain history.
On Polymarket CLOB, USDC settles wallet<->wallet (p2p), so 'deposit' detection =
chronology + size, not counterparty class."""
import pandas as pd

a = pd.read_parquet("strategy_lab/wallet_hunt/cache/0xb945945d/alchemy_transfers.parquet")
u = a[a.asset.isin(["pUSD", "USDCE"])].copy()
u["t"] = pd.to_datetime(u.ts, utc=True)
u["signed"] = u.value.where(u.direction == "to", -u.value)
u = u.sort_values("t")

print("=== first 8 USDC inflows (seed capital) ===")
fi = u[u.signed > 0].head(8)
for _, r in fi.iterrows():
    print("  %s  +%9.2f  from=%s" % (r["t"].strftime("%Y-%m-%d %H:%M"), r["value"], r["from"][:12]))

print("\n=== top 5 largest single inflows ever ===")
for _, r in u[u.signed > 0].nlargest(5, "value").iterrows():
    print("  %s  +%9.2f  from=%s" % (r["t"].strftime("%Y-%m-%d %H:%M"), r["value"], r["from"][:12]))

print("\n=== top 5 largest single OUTflows ever (withdrawals?) ===")
for _, r in u[u.signed < 0].nsmallest(5, "signed").iterrows():
    print("  %s  %9.2f  to=%s" % (r["t"].strftime("%Y-%m-%d %H:%M"), r["signed"], r["to"][:12]))

cum = u.set_index("t").signed.cumsum()
print("\n=== cumulative net cash (equity proxy) ===")
print("end: $%.2f   max: $%.2f   min: $%.2f" % (cum.iloc[-1], cum.max(), cum.min()))
wk = u.set_index("t").signed.resample("W").sum().cumsum()
print("\nweekly cumulative net cash:")
for d, v in wk.items():
    print("  %s  $%+10.2f" % (d.strftime("%Y-%m-%d"), v))

# clip sizing growth: USDC out per tx (grouped), weekly median/p90
out_tx = u[u.signed < 0].groupby("tx_hash").agg(usd=("value", "sum"), t=("t", "first"))
g = out_tx.set_index("t").sort_index().usd
print("\nweekly buy-tx size (USDC out per tx): median / p90 / n_tx / total_out")
for d, sub in g.resample("W"):
    if len(sub) == 0: continue
    print("  %s  $%7.2f / $%8.2f / %6d / $%10.0f" % (
        d.strftime("%Y-%m-%d"), sub.median(), sub.quantile(.9), len(sub), sub.sum()))
