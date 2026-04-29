"""
polymarket_time_of_day.py — E5: stratify locked baseline by UTC hour and weekday.

Strategy: sig_ret5m_q20 + hedge-hold rev_bp=5 (locked baseline).
Strata: window_start_unix → UTC hour-of-day, day-of-week.
Goal: identify session filters (e.g. skip Asia overnight, focus US hours).

Outputs:
  results/polymarket/time_of_day.csv
  reports/POLYMARKET_TIME_OF_DAY.md
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd
from datetime import datetime, timezone

HERE = Path(__file__).resolve().parent
RNG = np.random.default_rng(42)
FEE_RATE = 0.02
ASSETS = ["btc", "eth", "sol"]
REV_BP = 5


def load_features(asset):
    df = pd.read_csv(HERE/"data"/"polymarket"/f"{asset}_features_v3.csv")
    df["asset"] = asset
    return df


def load_trajectories(asset):
    t = pd.read_csv(HERE/"data"/"polymarket"/f"{asset}_trajectories_v3.csv")
    up = t[t.outcome == "Up"].rename(columns={
        "bid_first":"up_bid_first","bid_last":"up_bid_last","bid_min":"up_bid_min","bid_max":"up_bid_max",
        "ask_first":"up_ask_first","ask_last":"up_ask_last","ask_min":"up_ask_min","ask_max":"up_ask_max",
    })[["slug","bucket_10s","window_start_unix",
        "up_bid_first","up_bid_last","up_bid_min","up_bid_max",
        "up_ask_first","up_ask_last","up_ask_min","up_ask_max"]]
    dn = t[t.outcome == "Down"].rename(columns={
        "bid_first":"dn_bid_first","bid_last":"dn_bid_last","bid_min":"dn_bid_min","bid_max":"dn_bid_max",
        "ask_first":"dn_ask_first","ask_last":"dn_ask_last","ask_min":"dn_ask_min","ask_max":"dn_ask_max",
    })[["slug","bucket_10s",
        "dn_bid_first","dn_bid_last","dn_bid_min","dn_bid_max",
        "dn_ask_first","dn_ask_last","dn_ask_min","dn_ask_max"]]
    merged = up.merge(dn, on=["slug","bucket_10s"], how="outer").sort_values(["slug","bucket_10s"])
    return {slug:g.reset_index(drop=True) for slug,g in merged.groupby("slug")}


def load_klines_1m(asset):
    k = pd.read_csv(HERE/"data"/"binance"/f"{asset}_klines_window.csv")
    k1m = k[k.period_id == "1MIN"].copy()
    k1m["ts_s"] = (k1m.time_period_start_us // 1_000_000).astype(int)
    return k1m.sort_values("ts_s").reset_index(drop=True)[["ts_s","price_close"]]


def asof_close(k1m, ts):
    idx = k1m.ts_s.searchsorted(ts, side="right") - 1
    return float("nan") if idx < 0 else float(k1m.price_close.iloc[idx])


def add_q20(df):
    df = df.copy()
    df["signal"] = -1
    for asset in df.asset.unique():
        for tf in df.timeframe.unique():
            m = (df.asset == asset) & (df.timeframe == tf)
            r = df.loc[m, "ret_5m"].abs()
            q20 = r.quantile(0.80)
            sel = m & (df.ret_5m.abs() >= q20) & df.ret_5m.notna()
            df.loc[sel, "signal"] = (df.loc[sel, "ret_5m"] > 0).astype(int)
    return df[df.signal != -1].copy()


def simulate_market(row, traj_g, k1m, rev_bp):
    sig = int(row.signal)
    entry = float(row.entry_yes_ask) if sig == 1 else float(row.entry_no_ask)
    if not (np.isfinite(entry) and 0 < entry < 1):
        return None
    ws = int(row.window_start_unix)
    btc_at_ws = asof_close(k1m, ws)
    hedge_p = None
    for _, b in traj_g.iterrows():
        bucket = int(b.bucket_10s)
        if bucket < 0:
            continue
        if rev_bp is not None and np.isfinite(btc_at_ws):
            ts_in = ws + bucket * 10
            btc_now = asof_close(k1m, ts_in)
            if not np.isfinite(btc_now):
                continue
            bp = (btc_now - btc_at_ws) / btc_at_ws * 10000
            reverted = (sig == 1 and bp <= -rev_bp) or (sig == 0 and bp >= rev_bp)
            if reverted:
                col = "dn_ask_min" if sig == 1 else "up_ask_min"
                oa = b[col]
                if pd.notna(oa) and 0 < oa < 1:
                    hedge_p = float(oa)
                    break
    sig_won = (sig == int(row.outcome_up))
    if hedge_p is None:
        if sig_won:
            return 1.0 - (1.0 - entry) * FEE_RATE - entry
        return -entry
    if sig_won:
        payout = 1.0 - (1.0 - entry) * FEE_RATE
    else:
        payout = 1.0 - (1.0 - hedge_p) * FEE_RATE
    return payout - entry - hedge_p


def cell_stats(pnls):
    pnls = np.array(pnls)
    n = len(pnls)
    if n == 0:
        return dict(n=0, pnl_total=0, pnl_mean=0, roi=0, hit=float('nan'), ci_lo=0, ci_hi=0)
    boot = RNG.choice(pnls, size=(2000, n), replace=True).sum(axis=1)
    return dict(
        n=n, pnl_total=float(pnls.sum()), pnl_mean=float(pnls.mean()),
        roi=float(pnls.mean() * 100), hit=float((pnls > 0).mean()),
        ci_lo=float(np.quantile(boot, 0.025)), ci_hi=float(np.quantile(boot, 0.975)),
    )


def main():
    print("Loading data...")
    feats = pd.concat([load_features(a) for a in ASSETS], ignore_index=True)
    traj = {a: load_trajectories(a) for a in ASSETS}
    k1m = {a: load_klines_1m(a) for a in ASSETS}
    feats_q = add_q20(feats)
    print(f"q20 markets: {len(feats_q)}")

    # Compute pnl per row
    pnls = []
    rows = []
    for _, row in feats_q.iterrows():
        traj_g = traj[row.asset].get(row.slug)
        if traj_g is None or traj_g.empty:
            continue
        p = simulate_market(row, traj_g, k1m[row.asset], REV_BP)
        if p is None:
            continue
        ws = int(row.window_start_unix)
        dt = datetime.fromtimestamp(ws, tz=timezone.utc)
        rows.append({
            "asset": row.asset, "tf": row.timeframe, "slug": row.slug,
            "ws": ws, "hour_utc": dt.hour, "dow": dt.weekday(),  # 0=Mon, 6=Sun
            "session": _session(dt.hour),
            "pnl": p,
        })
    df = pd.DataFrame(rows)
    print(f"trades: {len(df)}")

    # Headline: by hour
    by_hour = []
    for h in range(24):
        sub = df[df.hour_utc == h]
        s = cell_stats(sub.pnl.tolist())
        s["hour_utc"] = h
        by_hour.append(s)
    bh = pd.DataFrame(by_hour)

    by_session = []
    for sess in ["asia", "europe", "us_morning", "us_afternoon", "off"]:
        sub = df[df.session == sess]
        s = cell_stats(sub.pnl.tolist())
        s["session"] = sess
        by_session.append(s)
    bs = pd.DataFrame(by_session)

    by_dow = []
    for d in range(7):
        sub = df[df.dow == d]
        s = cell_stats(sub.pnl.tolist())
        s["dow"] = d
        s["dow_name"] = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"][d]
        by_dow.append(s)
    bd = pd.DataFrame(by_dow)

    # Per asset × hour-bucket (4-hour bins)
    df["hour_bin"] = (df.hour_utc // 4) * 4
    by_asset_hb = []
    for asset in ASSETS:
        for hb in range(0, 24, 4):
            sub = df[(df.asset == asset) & (df.hour_bin == hb)]
            s = cell_stats(sub.pnl.tolist())
            s["asset"] = asset
            s["hour_bin"] = f"{hb:02d}-{hb+4:02d}"
            by_asset_hb.append(s)
    ba = pd.DataFrame(by_asset_hb)

    # Filter recommendation: keep hours with ROI > total_mean
    overall_roi = df.pnl.mean() * 100
    overall_hit = (df.pnl > 0).mean() * 100
    good_hours = bh[bh.roi > overall_roi].hour_utc.tolist()
    bad_hours = bh[bh.roi < overall_roi - 5].hour_utc.tolist()  # 5pp below overall

    # Filtered run: only good hours
    df_filtered = df[df.hour_utc.isin(good_hours)]
    filt_stats = cell_stats(df_filtered.pnl.tolist())

    # Outputs
    out = HERE/"results"/"polymarket"
    out.mkdir(parents=True, exist_ok=True)
    bh.to_csv(out/"time_of_day_hourly.csv", index=False)
    bs.to_csv(out/"time_of_day_session.csv", index=False)
    bd.to_csv(out/"time_of_day_dow.csv", index=False)
    ba.to_csv(out/"time_of_day_asset_hourbin.csv", index=False)
    df.to_csv(out/"time_of_day_per_trade.csv", index=False)

    # MD report
    md = ["# Polymarket Time-of-Day Analysis — sig_ret5m_q20 hedge-hold rev_bp=5\n",
          f"Universe: {len(df)} trades cross-asset Apr 22-27. Each market's window_start UTC hour bucketed.\n",
          f"\n**Overall:** {len(df)} trades, hit {overall_hit:.1f}%, ROI {overall_roi:+.2f}%/trade.\n",
          "\n## By UTC hour\n",
          "| Hour UTC | n | Hit% | ROI | 95% CI total |",
          "|---|---|---|---|---|"]
    for _, r in bh.iterrows():
        marker = " ★" if r.roi > overall_roi else ("" if r.roi >= overall_roi - 3 else " ✗")
        md.append(f"| {int(r.hour_utc):02d}:00-{int(r.hour_utc)+1:02d}:00 | {int(r.n)} | "
                  f"{r.hit*100:.1f}% | {r.roi:+.2f}%{marker} | [${r.ci_lo:+.0f}, ${r.ci_hi:+.0f}] |")

    md.append("\n## By session (UTC blocks)\n")
    md.append("Asia: 00-08, Europe: 08-13, US morning: 13-18, US afternoon: 18-22, Off: 22-24\n")
    md.append("| Session | n | Hit% | ROI | 95% CI |")
    md.append("|---|---|---|---|---|")
    for _, r in bs.iterrows():
        md.append(f"| {r.session} | {int(r.n)} | {r.hit*100:.1f}% | {r.roi:+.2f}% | [${r.ci_lo:+.0f}, ${r.ci_hi:+.0f}] |")

    md.append("\n## By day of week\n")
    md.append("| Day | n | Hit% | ROI | 95% CI |")
    md.append("|---|---|---|---|---|")
    for _, r in bd.iterrows():
        md.append(f"| {r.dow_name} | {int(r.n)} | {r.hit*100:.1f}% | {r.roi:+.2f}% | [${r.ci_lo:+.0f}, ${r.ci_hi:+.0f}] |")

    md.append("\n## Per asset × 4-hour bin (heatmap data)\n")
    md.append("| Asset | Hour bin (UTC) | n | Hit% | ROI |")
    md.append("|---|---|---|---|---|")
    for _, r in ba.iterrows():
        md.append(f"| {r.asset} | {r.hour_bin} | {int(r.n)} | {r.hit*100:.1f}% | {r.roi:+.2f}% |")

    md.append("\n## Filter recommendation\n")
    md.append(f"- Hours where ROI **above** overall ({overall_roi:+.2f}%): {good_hours}")
    md.append(f"- Hours where ROI **5pp below** overall: {bad_hours}")
    md.append(f"\n**Filtered (only good hours):** n={filt_stats['n']}, "
              f"hit={filt_stats['hit']*100:.1f}%, ROI={filt_stats['roi']:+.2f}%, "
              f"vs unfiltered {overall_roi:+.2f}%")
    md.append(f"\nLift from filter: {filt_stats['roi'] - overall_roi:+.2f}pp ROI, "
              f"trade-volume reduction: {len(df_filtered)/len(df)*100:.0f}% of original.")

    out_md = HERE/"reports"/"POLYMARKET_TIME_OF_DAY.md"
    out_md.write_text("\n".join(md), encoding="utf-8")
    print(f"Wrote {out_md}")
    print(f"Filter: keep hours {good_hours} → n={filt_stats['n']}, "
          f"hit={filt_stats['hit']*100:.1f}%, ROI={filt_stats['roi']:+.2f}% "
          f"(vs unfiltered {overall_roi:+.2f}%)")


def _session(hour):
    if hour < 8: return "asia"
    if hour < 13: return "europe"
    if hour < 18: return "us_morning"
    if hour < 22: return "us_afternoon"
    return "off"


if __name__ == "__main__":
    main()
