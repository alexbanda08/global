"""Inspect a few backtest fires vs entry books to see why vwap is so high."""
import pandas as pd
ROOT = r"C:\Users\alexandre bandarra\Desktop\global"
df = pd.read_csv(rf"{ROOT}\strategy_lab\results\meta_classifier\momo_rerun_l25_hold_per_trade.csv")
print("rows:", len(df), " cols:", list(df.columns)[:15])
print()
print("vwap distribution by cell:")
print(df.groupby(["asset","tf"]).vwap_e.describe(percentiles=[0.05,0.5,0.95])[["count","min","5%","50%","95%","max"]])
print()
print("vwap distribution by signal direction (within BTC_5m):")
print(df[(df.asset=="BTC")&(df.tf=="5m")].groupby("signal").vwap_e.describe()[["count","mean","min","max"]])
print()
print("Sample 5 BTC_5m trades:")
sub = df[(df.asset=="BTC")&(df.tf=="5m")].head(5)
print(sub[["slug","signal","outcome","ret_2m","threshold","ask0","bid0","vwap_e","shares","usd_spent","won","pnl"]].to_string(index=False))
print()
print("Are ret_2m values plausible? (should be |ret_2m| > threshold which is ~0.001)")
print(df[["abs_ret_2m","threshold"]].describe(percentiles=[0.5,0.95]))
