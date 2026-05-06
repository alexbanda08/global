"""Deep investigation of live shadow trades — open mysteries.

1. VPS2 V1 vs VPS3 V2 same-sleeve volume — same strategy, different price feeds.
   Are they getting different fills / hit rates? (V1=OKX-WS, V2=binance-spot-ws)

2. 05-01 sniper crash — hit rate fell 55.7% -> 28% in 14 hours. Why?
   - Hour pattern of failed trades
   - Direction pattern
   - Per-asset breakdown
   - Compare to 04-30 baseline

3. SOL 15m volume UP — winning 64% on n=106. Investigate:
   - What time of day?
   - Are wins concentrated on specific dates?
   - Fill cost pattern (paying less = better edge)?

4. 15m vs 5m live edge — backtest said 15m dilutes; live says 15m sniper works.
   - Per-asset 5m vs 15m sniper PnL
   - Hour patterns differ?
"""
from __future__ import annotations
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "v4" / "shadow_trades_2026_05_01"


def load() -> pd.DataFrame:
    v3_df = pd.read_csv(DATA / "vps3.csv", parse_dates=["at"])
    v3_df["host"] = "vps3"
    v2_df = pd.read_csv(DATA / "vps2.csv", parse_dates=["at"])
    v2_df["host"] = "vps2"
    df = pd.concat([v3_df, v2_df], ignore_index=True)
    df = df.sort_values("at").reset_index(drop=True)
    df["won"] = df["won"].map({"t": True, "f": False, True: True, False: False})
    df["hedged"] = df["hedged"].map({"t": True, "f": False, True: True, False: False})
    df["notional"] = df["entry_qty"] * df["entry_price"]

    def classify(s):
        if s.endswith("_v3"): return "V3"
        if "_sniper" in s: return "V2_sniper"
        if "_volume" in s: return "volume"
        return "other"
    df["sleeve_type"] = df["sleeve_id"].apply(classify)
    df["hour_utc"] = df["at"].dt.tz_convert("UTC").dt.hour
    df["date_utc"] = df["at"].dt.tz_convert("UTC").dt.date
    df["asset"] = df["sleeve_id"].str.extract(r"poly_updown_(btc|eth|sol)")[0]
    df["tf"] = df["sleeve_id"].str.extract(r"_(5m|15m)_")[0]
    return df


def fmt_row(label, n, hit, pnl, extra=""):
    n_str = f"n={n:>4d}"
    hit_str = f"hit={hit*100:>5.1f}%" if n else "hit=  —  "
    pnl_str = f"pnl=${pnl:>+8.2f}"
    avg = (pnl/n) if n else 0
    return f"  {label:<40} {n_str} {hit_str} {pnl_str}  avg=${avg:>+6.2f} {extra}"


def investigation_1_v1_vs_v2_volume(df: pd.DataFrame):
    print(f"\n{'='*100}")
    print("INVESTIGATION 1: VPS2 V1 vs VPS3 V2 — same volume sleeves, different price feeds")
    print(f"{'='*100}")
    print("VPS2 = OKX-WS feed (V1 control arm)")
    print("VPS3 = binance-spot-ws feed (V2 test arm)")
    print()

    vol = df[df["sleeve_type"] == "volume"].copy()
    print(f"  Volume mode total: n={len(vol)}, baseline hit={vol['won'].mean()*100:.1f}%")
    print(f"  By host:")
    for host in ["vps2", "vps3"]:
        s = vol[vol["host"] == host]
        if len(s):
            print(fmt_row(f"  {host} (all volume)", len(s), s["won"].mean(), s["pnl_usd"].sum()))

    print(f"\n  Per-asset / per-tf breakdown (host comparison):")
    for asset in ["btc", "eth", "sol"]:
        for tf in ["5m", "15m"]:
            print(f"\n  --- {asset.upper()} {tf} volume ---")
            for host in ["vps2", "vps3"]:
                s = vol[(vol["asset"] == asset) & (vol["tf"] == tf) & (vol["host"] == host)]
                if len(s):
                    print(fmt_row(f"  {host}", len(s), s["won"].mean(), s["pnl_usd"].sum(),
                                  f"avg_fill=${s['entry_price'].mean():.4f}"))


def investigation_2_sniper_crash_05_01(df: pd.DataFrame):
    print(f"\n{'='*100}")
    print("INVESTIGATION 2: Sniper hit-rate crash 04-30 (55.7%) -> 05-01 (28%)")
    print(f"{'='*100}")
    sniper = df[df["sleeve_type"] == "V2_sniper"].copy()
    print(f"\n  By date / hour (V2 sniper only):")
    for date in sorted(sniper["date_utc"].unique()):
        day_sub = sniper[sniper["date_utc"] == date]
        print(f"\n  Date {date}: n={len(day_sub)}, hit={day_sub['won'].mean()*100:.1f}%, pnl=${day_sub['pnl_usd'].sum():+.2f}")
        print(f"    Hour | n | hit  | pnl     | dirs")
        for h in range(24):
            hsub = day_sub[day_sub["hour_utc"] == h]
            if len(hsub) == 0: continue
            ups = (hsub["signal"] == "UP").sum()
            downs = (hsub["signal"] == "DOWN").sum()
            print(f"    {h:>3d}  | {len(hsub):>2d} | {hsub['won'].mean()*100:>4.0f}% | ${hsub['pnl_usd'].sum():>+7.2f} | UP={ups} DOWN={downs}")

    print(f"\n  Direction asymmetry by date:")
    for date in sorted(sniper["date_utc"].unique()):
        day_sub = sniper[sniper["date_utc"] == date]
        for sig in ["UP", "DOWN"]:
            s = day_sub[day_sub["signal"] == sig]
            if len(s):
                print(fmt_row(f"  {date} {sig}", len(s), s["won"].mean(), s["pnl_usd"].sum()))

    print(f"\n  Per-asset by date:")
    for date in sorted(sniper["date_utc"].unique()):
        day_sub = sniper[sniper["date_utc"] == date]
        for a in ["btc", "eth", "sol"]:
            s = day_sub[day_sub["asset"] == a]
            if len(s):
                print(fmt_row(f"  {date} {a.upper()}", len(s), s["won"].mean(), s["pnl_usd"].sum()))


def investigation_3_sol_15m_volume(df: pd.DataFrame):
    print(f"\n{'='*100}")
    print("INVESTIGATION 3: SOL 15m volume UP outperformance — why?")
    print(f"{'='*100}")
    s15v = df[(df["sleeve_id"] == "poly_updown_sol_15m_volume")].copy()
    print(f"  Total: n={len(s15v)}, hit={s15v['won'].mean()*100:.1f}%, pnl=${s15v['pnl_usd'].sum():+.2f}")

    print(f"\n  By signal direction:")
    for sig in ["UP", "DOWN"]:
        s = s15v[s15v["signal"] == sig]
        if len(s):
            print(fmt_row(f"  {sig}", len(s), s["won"].mean(), s["pnl_usd"].sum(),
                          f"avg_fill=${s['entry_price'].mean():.4f}"))

    print(f"\n  By date (UP only — that's where edge lives):")
    up = s15v[s15v["signal"] == "UP"]
    for d in sorted(up["date_utc"].unique()):
        s = up[up["date_utc"] == d]
        if len(s):
            print(fmt_row(f"  {d} UP", len(s), s["won"].mean(), s["pnl_usd"].sum()))

    print(f"\n  By hour (UP only):")
    for h in range(24):
        s = up[up["hour_utc"] == h]
        if len(s) >= 3:
            print(fmt_row(f"  hour {h}", len(s), s["won"].mean(), s["pnl_usd"].sum()))

    print(f"\n  Compare: BTC and ETH 15m volume UP same window:")
    for a in ["btc", "eth", "sol"]:
        s = df[(df["asset"] == a) & (df["tf"] == "15m") &
               (df["sleeve_type"] == "volume") & (df["signal"] == "UP")]
        if len(s):
            print(fmt_row(f"  {a.upper()} 15m volume UP", len(s), s["won"].mean(), s["pnl_usd"].sum()))


def investigation_4_15m_vs_5m(df: pd.DataFrame):
    print(f"\n{'='*100}")
    print("INVESTIGATION 4: 15m vs 5m live edge — backtest said 15m dilutes")
    print(f"{'='*100}")
    edge = df[df["sleeve_type"].isin(["V2_sniper", "V3"])].copy()

    print(f"  Sniper + V3 by tf:")
    for tf in ["5m", "15m"]:
        s = edge[edge["tf"] == tf]
        if len(s):
            print(fmt_row(f"  {tf} (combined assets)", len(s), s["won"].mean(), s["pnl_usd"].sum()))

    print(f"\n  Per-asset 5m vs 15m (sniper only):")
    sniper = edge[edge["sleeve_type"] == "V2_sniper"]
    for a in ["btc", "eth", "sol"]:
        for tf in ["5m", "15m"]:
            s = sniper[(sniper["asset"] == a) & (sniper["tf"] == tf)]
            if len(s):
                print(fmt_row(f"  {a.upper()} {tf} sniper", len(s), s["won"].mean(), s["pnl_usd"].sum()))

    print(f"\n  Direction split: 15m sniper UP vs DOWN per asset:")
    sniper15 = sniper[sniper["tf"] == "15m"]
    for a in ["btc", "eth", "sol"]:
        for sig in ["UP", "DOWN"]:
            s = sniper15[(sniper15["asset"] == a) & (sniper15["signal"] == sig)]
            if len(s):
                print(fmt_row(f"  {a.upper()} 15m sniper {sig}", len(s), s["won"].mean(), s["pnl_usd"].sum()))


def investigation_5_consistency_check(df: pd.DataFrame):
    """If V1 (VPS2) volume and V2 (VPS3) volume are running same strategy on same markets,
    they should fire on the SAME markets at the SAME times (within feed-latency).
    Check: how aligned are the fire counts? Are the hit rates similar?"""
    print(f"\n{'='*100}")
    print("INVESTIGATION 5: V1/V2 volume consistency — should be same strategy, do they agree?")
    print(f"{'='*100}")

    # Pivot to compare same (asset, tf) across hosts
    print(f"  Volume sleeve fire-count by (asset, tf, host):")
    print(f"  {'asset':<5} {'tf':<5} {'vps2 (V1, OKX)':<25} {'vps3 (V2, binance-WS)':<28} {'feed_diff'}")
    print("  " + "-"*78)
    for asset in ["btc", "eth", "sol"]:
        for tf in ["5m", "15m"]:
            v1 = df[(df["asset"] == asset) & (df["tf"] == tf) &
                    (df["sleeve_type"] == "volume") & (df["host"] == "vps2")]
            v2 = df[(df["asset"] == asset) & (df["tf"] == tf) &
                    (df["sleeve_type"] == "volume") & (df["host"] == "vps3")]
            if len(v1) > 0 or len(v2) > 0:
                v1_hit = f"{v1['won'].mean()*100:.1f}%" if len(v1) else "-"
                v2_hit = f"{v2['won'].mean()*100:.1f}%" if len(v2) else "-"
                v1_pnl = f"${v1['pnl_usd'].sum():+.0f}" if len(v1) else "-"
                v2_pnl = f"${v2['pnl_usd'].sum():+.0f}" if len(v2) else "-"
                v1_str = f"n={len(v1)} hit={v1_hit} {v1_pnl}"
                v2_str = f"n={len(v2)} hit={v2_hit} {v2_pnl}"
                if len(v1) and len(v2):
                    diff_pct = (v2['won'].mean() - v1['won'].mean()) * 100
                    diff_str = f"{diff_pct:+.1f}pp (V2-V1)"
                else:
                    diff_str = "—"
                print(f"  {asset:<5} {tf:<5} {v1_str:<25} {v2_str:<28} {diff_str}")


def main():
    df = load()
    print(f"Total resolutions: {len(df)} | Window: {df['at'].min()} -> {df['at'].max()}")
    print(f"Days covered: {(df['at'].max() - df['at'].min()).total_seconds()/86400:.2f}")

    investigation_1_v1_vs_v2_volume(df)
    investigation_5_consistency_check(df)
    investigation_2_sniper_crash_05_01(df)
    investigation_3_sol_15m_volume(df)
    investigation_4_15m_vs_5m(df)


if __name__ == "__main__":
    main()
