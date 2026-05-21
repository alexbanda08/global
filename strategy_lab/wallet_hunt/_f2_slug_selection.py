"""What's special about F2's 102 BTC slugs vs the rest of the universe?

Hypotheses:
  H1. Time-of-day filter — F2 only fires during specific UTC hours
  H2. Day-of-week filter (e.g., weekday only)
  H3. Slug-level volume floor — fire only on high-volume slugs
  H4. Binance volatility regime — fire only when binance is in a vol band
  H5. Time-since-last-fire / drawdown control

Build the feature dataset:
  - For every BTC 5m slug in canonical, compute:
      slot_start_dt, hour_of_day_utc, weekday, slug_total_trades_in_first_30s
      slug_total_volume_usd, binance_ret_60s_at_slot_start,
      binance_realized_vol_15min_pre_slot, etc.
  - Label is_f2 = slug in F2's 102 fired slugs
  - Compare distributions
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
from load import (  # noqa: E402
    load_resolutions, add_ws_s, load_klines_asof, asof_strict,
    load_trades,
)

CACHE = Path(__file__).resolve().parent / "cache"
WINDOW_S = {"5m": 300, "15m": 900}


def main():
    # 1. F2's slug set
    f2_features = pd.read_parquet(CACHE / "_f2_trade_flow_features.parquet")
    f2_slugs = set(f2_features[f2_features.is_fire == 1].slug.unique())
    print(f"F2 fired slugs: {len(f2_slugs)}")

    # 2. Universe (BTC 5m only, May 10-16 to match F2's active window)
    res = load_resolutions(assets=["BTC"], timeframes=["5m"])
    res = add_ws_s(res)
    # Compute slug timestamp
    res["slot_start_us"] = res.slug.apply(lambda s: int(s.rsplit("-", 1)[1]) * 1_000_000)
    res["slot_start_dt"] = pd.to_datetime(res.slot_start_us, unit="us")
    res["date"] = res.slot_start_dt.dt.date
    res["hour_utc"] = res.slot_start_dt.dt.hour
    res["minute_utc"] = res.slot_start_dt.dt.minute
    res["weekday"] = res.slot_start_dt.dt.weekday
    res["is_f2"] = res.slug.isin(f2_slugs)

    print(f"Universe BTC 5m: {len(res)} slugs")
    print(f"F2 in universe:  {int(res.is_f2.sum())}")
    print(f"F2 date range:   {res[res.is_f2].date.min()} -> {res[res.is_f2].date.max()}")
    print()

    # 3. Time-of-day comparison
    print("=" * 80)
    print("Hour-of-day distribution — F2 vs all (BTC 5m universe)")
    print("=" * 80)
    f2_hours = res[res.is_f2].hour_utc.value_counts(normalize=True).sort_index()
    all_hours = res[~res.is_f2].hour_utc.value_counts(normalize=True).sort_index()
    print(f"{'hour':>4s}  {'F2%':>6s}  {'all%':>6s}  {'lift':>6s}")
    for h in range(24):
        f = f2_hours.get(h, 0)
        a = all_hours.get(h, 0)
        lift = (f / a) if a > 0 else 0.0
        marker = " ★" if lift > 2.0 else ""
        print(f"  {h:3d}  {f*100:5.2f}%  {a*100:5.2f}%  {lift:5.2f}x{marker}")
    print()

    # 4. Weekday distribution
    print("=" * 80)
    print("Weekday distribution (0=Mon, 6=Sun)")
    print("=" * 80)
    f2_wd = res[res.is_f2].weekday.value_counts(normalize=True).sort_index()
    all_wd = res[~res.is_f2].weekday.value_counts(normalize=True).sort_index()
    print(f"{'wd':>4s}  {'F2%':>6s}  {'all%':>6s}  {'lift':>6s}")
    for d in range(7):
        f = f2_wd.get(d, 0); a = all_wd.get(d, 0)
        lift = (f / a) if a > 0 else 0.0
        marker = " ★" if lift > 1.3 else ""
        print(f"  {d:3d}  {f*100:5.2f}%  {a*100:5.2f}%  {lift:5.2f}x{marker}")
    print()

    # 5. Per-day distribution within F2's active window (May 10-16)
    print("=" * 80)
    print("Date distribution within F2's active window (May 10-16)")
    print("=" * 80)
    active = res[(res.date >= pd.Timestamp("2026-05-10").date()) &
                  (res.date <= pd.Timestamp("2026-05-16").date())].copy()
    print(f"  active-window total slugs: {len(active)}")
    print(f"  active-window F2 slugs:    {int(active.is_f2.sum())}  ({active.is_f2.mean()*100:.2f}%)")
    daily = active.groupby("date").agg(
        n_total=("slug", "size"),
        n_f2=("is_f2", "sum"),
    )
    daily["f2_pct"] = daily.n_f2 / daily.n_total * 100
    print(daily.to_string())
    print()

    # 6. Slug volume comparison — total trades per slug
    print("=" * 80)
    print("Slug volume — sum of trades in slug lifetime")
    print("=" * 80)
    print("(Loading trade tape — only need slug counts...)")
    tr = load_trades("btc")
    tr["date"] = pd.to_datetime(tr.timestamp_us, unit="us").dt.date
    # Restrict to active window for fair comparison
    tr_active = tr[(tr.date >= pd.Timestamp("2026-05-10").date()) &
                    (tr.date <= pd.Timestamp("2026-05-16").date())]
    slug_volume = tr_active.groupby("slug").size()

    f2_vol = slug_volume[slug_volume.index.isin(f2_slugs)]
    non_f2_active = active[~active.is_f2].slug.values
    other_vol = slug_volume[slug_volume.index.isin(non_f2_active)]
    print(f"  F2 slugs (n={len(f2_vol)}):  median={f2_vol.median():.0f}  "
          f"p10={f2_vol.quantile(0.1):.0f}  p90={f2_vol.quantile(0.9):.0f}  "
          f"mean={f2_vol.mean():.0f}")
    print(f"  Other slugs (n={len(other_vol)}):  median={other_vol.median():.0f}  "
          f"p10={other_vol.quantile(0.1):.0f}  p90={other_vol.quantile(0.9):.0f}  "
          f"mean={other_vol.mean():.0f}")
    print()

    # 7. Binance volatility at slot_start
    print("=" * 80)
    print("Binance realized-vol pre-slot (15 minutes before slot_start)")
    print("=" * 80)
    end_us, prices = load_klines_asof("BTC", "binance-spot-ws", "1MIN")
    def realized_vol_15m(t_us):
        # Compute std of 1MIN log returns in [t_us-15min, t_us]
        lo = t_us - 15 * 60 * 1_000_000
        mask = (end_us >= lo) & (end_us <= t_us)
        px = prices[mask]
        if len(px) < 3: return float("nan")
        rets = np.diff(np.log(px))
        return float(np.std(rets) * np.sqrt(60) * 10000)  # vol annualised? no, just bp/min

    print("Computing vol for active window slugs (slow, sampling 1000)...")
    sample = active.sample(min(1000, len(active)), random_state=42).copy()
    sample["vol_15m_bp"] = sample.slot_start_us.apply(realized_vol_15m)
    vol_f2 = sample[sample.is_f2].vol_15m_bp.dropna()
    vol_other = sample[~sample.is_f2].vol_15m_bp.dropna()
    print(f"  F2 slugs (n={len(vol_f2)}):    median={vol_f2.median():.2f}  "
          f"p10={vol_f2.quantile(0.1):.2f}  p90={vol_f2.quantile(0.9):.2f}")
    print(f"  Other slugs (n={len(vol_other)}): median={vol_other.median():.2f}  "
          f"p10={vol_other.quantile(0.1):.2f}  p90={vol_other.quantile(0.9):.2f}")
    print()

    # 8. Hour of day x F2 fire density chart
    print("=" * 80)
    print("F2's specific firing hours (top 5)")
    print("=" * 80)
    f2_fires_dt = pd.to_datetime(
        f2_features[f2_features.is_fire == 1].fire_ts_us, unit="us"
    )
    fire_hours = f2_fires_dt.dt.hour.value_counts(normalize=True).sort_index()
    print(f"  F2 fire hour distribution:")
    for h, p in fire_hours.sort_values(ascending=False).head(8).items():
        print(f"    {h:2d}:00 UTC  → {p*100:5.2f}% of fires")


if __name__ == "__main__":
    main()
