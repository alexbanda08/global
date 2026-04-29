"""Quick test: is weekday-only a simpler/better filter than 12-hour cherry-pick?"""
import pandas as pd
import numpy as np

df = pd.read_csv("results/polymarket/time_of_day_per_trade.csv")
df["dt"] = pd.to_datetime(df.ws, unit="s", utc=True)
df["dow"] = df.dt.dt.weekday  # 0=Mon..6=Sun
df["is_weekday"] = df.dow < 5

rng = np.random.default_rng(42)
def boot_ci(pnls, n=10000):
    p = np.array(pnls)
    if len(p) == 0: return (0,0,0)
    s = rng.choice(p, size=(n, len(p)), replace=True).mean(axis=1)
    return float(p.mean()*100), float(np.quantile(s,0.025)*100), float(np.quantile(s,0.975)*100)

print(f"Total trades: {len(df)}")
print("Per day-of-week:")
for d in range(7):
    sub = df[df.dow == d]
    if len(sub) > 0:
        roi, lo, hi = boot_ci(sub.pnl.values)
        name = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"][d]
        print(f"  {name}: n={len(sub):>4d} hit={(sub.pnl>0).mean()*100:5.1f}% "
              f"ROI={roi:+6.2f}% CI[{lo:+.2f}, {hi:+.2f}]")

print("\n=== Filter comparisons (cross-asset, q20, hedge-hold rev=5) ===")
roi_all, lo_all, hi_all = boot_ci(df.pnl.values)
print(f"  Baseline (all):           n={len(df):4d}  ROI {roi_all:+.2f}%  CI[{lo_all:+.2f}, {hi_all:+.2f}]")

wd = df[df.is_weekday]
roi_wd, lo_wd, hi_wd = boot_ci(wd.pnl.values)
sig_wd = "STAT.SIG." if lo_wd > roi_all else "overlaps"
print(f"  Weekday only:             n={len(wd):4d}  ROI {roi_wd:+.2f}%  CI[{lo_wd:+.2f}, {hi_wd:+.2f}]   {sig_wd}")

we = df[~df.is_weekday]
roi_we, lo_we, hi_we = boot_ci(we.pnl.values)
print(f"  Weekend only:             n={len(we):4d}  ROI {roi_we:+.2f}%  CI[{lo_we:+.2f}, {hi_we:+.2f}]")

GOOD_HOURS = {3, 5, 8, 9, 10, 11, 12, 13, 14, 17, 19, 21}
gh = df[df.hour_utc.isin(GOOD_HOURS)]
roi_gh, lo_gh, hi_gh = boot_ci(gh.pnl.values)
print(f"  Good hours (12-pick):     n={len(gh):4d}  ROI {roi_gh:+.2f}%  CI[{lo_gh:+.2f}, {hi_gh:+.2f}]")

ghwd = df[df.is_weekday & df.hour_utc.isin(GOOD_HOURS)]
roi, lo, hi = boot_ci(ghwd.pnl.values)
print(f"  Weekday + good hours:     n={len(ghwd):4d}  ROI {roi:+.2f}%  CI[{lo:+.2f}, {hi:+.2f}]")

# Leave-one-day-out: stability of weekday-only filter
print("\n=== Leave-one-day-out CV for weekday-only ===")
for excl_d in sorted(df.dt.dt.date.unique()):
    train = df[(df.dt.dt.date != excl_d) & df.is_weekday]
    test = df[(df.dt.dt.date == excl_d) & df.is_weekday]
    if len(test) == 0:
        continue
    roi_train, _, _ = boot_ci(train.pnl.values)
    roi_test, lo_test, hi_test = boot_ci(test.pnl.values)
    print(f"  excl {excl_d}: train n={len(train):>3d} ROI {roi_train:+.2f}%  |  "
          f"holdout n={len(test):>3d} ROI {roi_test:+.2f}% CI[{lo_test:+.2f}, {hi_test:+.2f}]")

print("\n=== Cross-asset ROI stability for weekday-only filter ===")
for asset in ["btc", "eth", "sol"]:
    sub = df[(df.asset == asset) & df.is_weekday]
    roi, lo, hi = boot_ci(sub.pnl.values)
    print(f"  {asset}: n={len(sub):>4d} hit={(sub.pnl>0).mean()*100:5.1f}% ROI={roi:+.2f}% CI[{lo:+.2f}, {hi:+.2f}]")
