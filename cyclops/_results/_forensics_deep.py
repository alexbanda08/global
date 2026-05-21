"""Deep adverse-selection forensics on p2_full_21d.csv.

Goal: explain WHY 3-of-3 coherent votes resolve at 42% (worse than 2-of-3's
47%, both below the 50% baseline). Spec said STOP if G1 fails. User wants
forensics first, no feature iteration.

Sections:
  A) Hit rate per coherent vote tuple (8 cases)
  B) Hourly UTC: fire-rate × WR × outcome-base-rate (regime + calibration)
  C) Daily WR — regime shift over 21d?
  D) Vwap-stratified PnL — does anti-edge concentrate at specific prices?
  E) Pairwise axis predictiveness (drop one axis)
  F) Sanity: full universe outcome-truth base rates by time
"""
import pandas as pd, numpy as np
from datetime import datetime, timezone

df = pd.read_csv("cyclops/_results/p2_full_21d.csv")
df["dt_utc"] = pd.to_datetime(df.ws_s, unit="s", utc=True)
df["hour_utc"] = df.dt_utc.dt.hour
df["date_utc"] = df.dt_utc.dt.date
df["dow"] = df.dt_utc.dt.dayofweek  # 0=Mon, 6=Sun

fired = df[df.fired == True].copy()

# ---------------------------------------------------------------------------
# A) Hit rate per coherent vote tuple
# ---------------------------------------------------------------------------
print("=" * 72)
print("A) Hit rate per coherent (trend, levels, momentum) tuple")
print("=" * 72)
print(f"{'tuple':>16s}  {'n':>5s}  {'WR':>6s}  {'breakeven':>10s}  {'mean_pnl':>10s}  {'dir':>5s}")
for v in sorted(fired.groupby(["v_trend", "v_levels", "v_momentum"]).groups.keys()):
    sub = fired[(fired.v_trend == v[0]) & (fired.v_levels == v[1]) & (fired.v_momentum == v[2])]
    if sub.empty:
        continue
    wr = sub.won.mean()
    bk = sub.vwap_entry.mean()
    pnl = sub.pnl_usd.mean()
    direction = sub.direction.iloc[0]
    edge = "★" if wr > bk else ""
    print(f"  ({v[0]:+d},{v[1]:+d},{v[2]:+d})  {len(sub):5d}  {wr:6.3f}  "
          f"{bk:10.3f}  ${pnl:+9.4f}  {direction:>5s} {edge}")
print()

# ---------------------------------------------------------------------------
# B) Hourly UTC analysis
# ---------------------------------------------------------------------------
print("=" * 72)
print("B) Hourly UTC: fires + WR + universe base-rate-Up")
print("=" * 72)
print(f"{'hour':>4s}  {'eval':>5s}  {'fires':>5s}  {'fire%':>6s}  {'WR':>6s}  "
      f"{'mean_pnl':>10s}  {'univ_up%':>8s}")
for h in range(24):
    e = df[df.hour_utc == h]
    f = fired[fired.hour_utc == h]
    if e.empty:
        continue
    fire_pct = len(f) / len(e) * 100
    wr = f.won.mean() if len(f) else float("nan")
    pnl = f.pnl_usd.mean() if len(f) else float("nan")
    up_pct = (e.outcome_truth == "Up").mean() * 100
    print(f"  {h:4d}  {len(e):5d}  {len(f):5d}  {fire_pct:5.1f}%  {wr:6.3f}  "
          f"${pnl:+9.4f}  {up_pct:7.1f}%")
print()

# ---------------------------------------------------------------------------
# C) Daily WR
# ---------------------------------------------------------------------------
print("=" * 72)
print("C) Daily: fires + WR + cum_pnl")
print("=" * 72)
print(f"{'date':>12s}  {'fires':>5s}  {'WR':>6s}  {'mean_pnl':>10s}  {'day_pnl':>10s}")
for d, sub in fired.groupby("date_utc"):
    print(f"  {str(d):>12s}  {len(sub):5d}  {sub.won.mean():6.3f}  "
          f"${sub.pnl_usd.mean():+9.4f}  ${sub.pnl_usd.sum():+9.2f}")
print()

# ---------------------------------------------------------------------------
# D) Vwap-stratified PnL
# ---------------------------------------------------------------------------
print("=" * 72)
print("D) Vwap bucket: PnL stratified by entry price")
print("=" * 72)
bins = [0.0, 0.30, 0.40, 0.45, 0.50, 0.55, 0.60, 0.70, 1.01]
fired["vwap_bin"] = pd.cut(fired.vwap_entry, bins=bins)
print(f"{'vwap_bin':>15s}  {'n':>5s}  {'WR':>6s}  {'breakeven':>10s}  "
      f"{'edge_pp':>8s}  {'mean_pnl':>10s}")
for b, sub in fired.groupby("vwap_bin", observed=True):
    if sub.empty:
        continue
    wr = sub.won.mean()
    bk = sub.vwap_entry.mean()
    edge_pp = (wr - bk) * 100
    print(f"  {str(b):>15s}  {len(sub):5d}  {wr:6.3f}  {bk:10.3f}  "
          f"{edge_pp:+7.1f}pp  ${sub.pnl_usd.mean():+9.4f}")
print()

# ---------------------------------------------------------------------------
# E) Pairwise axis predictiveness (drop one axis, look at the other two)
# ---------------------------------------------------------------------------
print("=" * 72)
print("E) Pairwise axis predictiveness — would dropping one axis help?")
print("=" * 72)
print("Run conflict filter on each PAIR, no-axis case votes 0. Hit-rate of")
print("the pair's coherent direction vs outcome.")
print()
for drop in ("v_trend", "v_levels", "v_momentum"):
    others = [c for c in ("v_trend", "v_levels", "v_momentum") if c != drop]
    pos = df[others].gt(0).sum(axis=1)
    neg = df[others].lt(0).sum(axis=1)
    fire2 = (pos > 0) & (neg == 0)  # coherent up
    fire2 |= (neg > 0) & (pos == 0)  # coherent down
    sub = df[fire2].copy()
    sub["pred"] = np.where(sub[others].sum(axis=1) > 0, "Up", "Down")
    sub["hit"] = (sub.pred == sub.outcome_truth).astype(int)
    print(f"  drop {drop:12s} → uses {others}: n={len(sub):5d}  "
          f"hit_rate={sub.hit.mean():.3f}  (baseline 0.500)")
print()

# ---------------------------------------------------------------------------
# F) Universe outcome base rates (sanity)
# ---------------------------------------------------------------------------
print("=" * 72)
print("F) Universe outcome base rates")
print("=" * 72)
up_rate = (df.outcome_truth == "Up").mean()
print(f"  Whole universe: Up = {up_rate:.3f}  (Down = {1-up_rate:.3f})  n={len(df)}")
print(f"  Fired rows:     Up = {(fired.outcome_truth == 'Up').mean():.3f}  "
      f"n={len(fired)}")
print()
print("  By day-of-week (0=Mon..6=Sun):")
for d in range(7):
    sub = df[df.dow == d]
    if sub.empty: continue
    print(f"    dow={d}  n={len(sub):5d}  Up={ (sub.outcome_truth=='Up').mean():.3f}")
