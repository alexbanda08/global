"""Live shadow trade analysis — VPS2 (V1 volume) + VPS3 (V2 sniper + V3 + volume).

Pulls real paper-mode resolutions from both VPS Postgres instances.
Outputs:
  - Per-sleeve hit rate, PnL, fire count, time window
  - Direction asymmetry (UP vs DOWN per sleeve)
  - Hour-of-day pattern on live data (validates Phase 1 backtest finding)
  - Daily PnL trend (trending better/worse?)
  - Cross-VPS comparison: V1 (VPS2 volume) vs V2 (VPS3 sniper) vs V3 (VPS3)
"""
from __future__ import annotations
import numpy as np
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
    # Postgres boolean dump: 't' / 'f' -> True/False
    df["won"] = df["won"].map({"t": True, "f": False, True: True, False: False})
    df["hedged"] = df["hedged"].map({"t": True, "f": False, True: True, False: False})
    df["notional"] = df["entry_qty"] * df["entry_price"]

    # Classify sleeve type
    def classify(s):
        if s.endswith("_v3"): return "V3"
        if "_sniper" in s: return "V2_sniper"
        if "_volume" in s: return "V1_volume"
        return "other"
    df["sleeve_type"] = df["sleeve_id"].apply(classify)
    df["hour_utc"] = df["at"].dt.tz_convert("UTC").dt.hour
    df["date_utc"] = df["at"].dt.tz_convert("UTC").dt.date
    return df


def per_sleeve_summary(df: pd.DataFrame):
    print(f"\n{'='*100}")
    print("PER-SLEEVE SUMMARY (live paper trades)")
    print(f"{'='*100}")
    print(f"{'sleeve_id':<32} {'host':<5} {'n':>4} {'wins':>4} {'hit':>6} {'pnl':>10} {'avg_pnl':>8} {'avg_fill':>8} {'first_fire':>17} {'last_fire':>17}")
    print("-" * 130)
    g = df.groupby("sleeve_id")
    rows = []
    for sleeve, sub in g:
        n = len(sub)
        wins = int(sub["won"].sum())
        hit = wins / n if n else 0
        pnl = sub["pnl_usd"].sum()
        avg = pnl / n if n else 0
        avg_fill = sub["entry_price"].mean()
        host = sub["host"].iloc[0]
        first = sub["at"].min().strftime("%m-%d %H:%M")
        last = sub["at"].max().strftime("%m-%d %H:%M")
        rows.append({"sleeve": sleeve, "n": n, "hit": hit, "pnl": pnl})
        print(f"{sleeve:<32} {host:<5} {n:>4d} {wins:>4d} {hit*100:>5.1f}% ${pnl:>9.2f} ${avg:>+7.2f} ${avg_fill:>7.4f} {first:>17} {last:>17}")
    return pd.DataFrame(rows)


def direction_asymmetry(df: pd.DataFrame):
    print(f"\n{'='*90}")
    print("DIRECTION ASYMMETRY — UP vs DOWN per sleeve")
    print(f"{'='*90}")
    g = df.groupby(["sleeve_id", "signal"])
    print(f"{'sleeve':<32} {'sig':<5} {'n':>4} {'hit':>6} {'pnl':>10}")
    print("-" * 80)
    for (sleeve, sig), sub in g:
        n = len(sub); hit = sub["won"].mean(); pnl = sub["pnl_usd"].sum()
        print(f"{sleeve:<32} {sig:<5} {n:>4d} {hit*100:>5.1f}% ${pnl:>+9.2f}")


def hour_pattern_live(df: pd.DataFrame):
    print(f"\n{'='*90}")
    print("HOUR-OF-DAY PATTERN (LIVE) — sniper + V3 only (skip volume)")
    print(f"{'='*90}")
    edge_df = df[df["sleeve_type"].isin(["V2_sniper", "V3"])].copy()
    print(f"  Total edge fires: {len(edge_df)}, baseline hit: {edge_df['won'].mean()*100:.2f}%")
    print(f"  Hour | n   | hit    | pnl     | dev_pp_vs_base")
    print("  -----|-----|--------|---------|----------------")
    base = edge_df["won"].mean()
    blocklist = {1, 16, 22}
    for h in range(24):
        sub = edge_df[edge_df["hour_utc"] == h]
        if len(sub) < 3: continue
        hit = sub["won"].mean()
        pnl = sub["pnl_usd"].sum()
        dev = (hit - base) * 100
        flag = "  BLOCKED" if h in blocklist else ""
        print(f"  {h:>4d} | {len(sub):>3d} | {hit*100:>5.1f}% | ${pnl:>+7.2f} | {dev:+5.1f}{flag}")


def daily_trend(df: pd.DataFrame):
    print(f"\n{'='*90}")
    print("DAILY P&L TREND — by sleeve_type")
    print(f"{'='*90}")
    edge_df = df[df["sleeve_type"].isin(["V2_sniper", "V3"])].copy()
    g = edge_df.groupby(["date_utc", "sleeve_type"]).agg(
        n=("won", "size"), hit=("won", "mean"), pnl=("pnl_usd", "sum"),
    ).reset_index()
    print(f"  date       | type      | n   | hit    | pnl")
    print("  -----------|-----------|-----|--------|--------")
    for _, r in g.iterrows():
        print(f"  {r['date_utc']!s:<10} | {r['sleeve_type']:<9} | {int(r['n']):>3d} | {r['hit']*100:>5.1f}% | ${r['pnl']:>+7.2f}")


def cross_vps_comparison(df: pd.DataFrame):
    print(f"\n{'='*90}")
    print("CROSS-VPS / CROSS-STRATEGY COMPARISON")
    print(f"{'='*90}")
    g = df.groupby("sleeve_type").agg(
        n=("won", "size"), wins=("won", "sum"), hit=("won", "mean"),
        pnl=("pnl_usd", "sum"), notional=("notional", "sum"),
    ).reset_index()
    g["roi_pct"] = g["pnl"] / g["notional"] * 100
    print(f"  {'type':<10} | {'n':>5} | {'wins':>5} | {'hit':>6} | {'pnl':>10} | {'notional':>10} | {'roi':>7}")
    print("  " + "-"*78)
    for _, r in g.iterrows():
        print(f"  {r['sleeve_type']:<10} | {int(r['n']):>5d} | {int(r['wins']):>5d} | {r['hit']*100:>5.1f}% | ${r['pnl']:>+9.2f} | ${r['notional']:>9.2f} | {r['roi_pct']:+6.2f}%")


def fill_cost_diagnostic(df: pd.DataFrame):
    print(f"\n{'='*90}")
    print("FILL COST DIAGNOSTIC — are we paying too much?")
    print(f"{'='*90}")
    edge_df = df[df["sleeve_type"].isin(["V2_sniper", "V3"])].copy()
    g = edge_df.groupby(["sleeve_id", "won"])["entry_price"].agg(["mean", "count"]).reset_index()
    print(f"  Hypothesis: losing fires pay HIGHER entry cost than winning fires.")
    for sleeve, sub in edge_df.groupby("sleeve_id"):
        wins = sub[sub["won"] == True]
        loss = sub[sub["won"] == False]
        if len(wins) >= 3 and len(loss) >= 3:
            wc = wins["entry_price"].mean()
            lc = loss["entry_price"].mean()
            diff = (lc - wc) * 100  # in pp
            print(f"    {sleeve:<32} win_cost={wc:.4f} loss_cost={lc:.4f} loss_costs_more={diff:+.2f}pp")


def time_since_last_fire(df: pd.DataFrame):
    print(f"\n{'='*90}")
    print("TIME SINCE LAST FIRE — does fire density correlate with hit rate?")
    print(f"{'='*90}")
    edge_df = df[df["sleeve_type"].isin(["V2_sniper", "V3"])].copy().sort_values("at")
    edge_df["mins_since_prev"] = edge_df.groupby("sleeve_id")["at"].diff().dt.total_seconds() / 60
    valid = edge_df.dropna(subset=["mins_since_prev"])
    print(f"  fired_within_30m_of_prev: n={(valid['mins_since_prev']<30).sum()}  hit={valid[valid['mins_since_prev']<30]['won'].mean()*100:.1f}%")
    print(f"  fired_30-120m_after_prev: n={((valid['mins_since_prev']>=30)&(valid['mins_since_prev']<120)).sum()}  hit={valid[(valid['mins_since_prev']>=30)&(valid['mins_since_prev']<120)]['won'].mean()*100:.1f}%")
    print(f"  fired_>120m_after_prev:   n={(valid['mins_since_prev']>=120).sum()}  hit={valid[valid['mins_since_prev']>=120]['won'].mean()*100:.1f}%")


def main():
    df = load()
    print(f"Total resolutions: {len(df)}")
    print(f"Window: {df['at'].min()} -> {df['at'].max()}")
    print(f"Days covered: {(df['at'].max() - df['at'].min()).total_seconds()/86400:.2f}")
    print(f"Hosts: {df['host'].value_counts().to_dict()}")
    print(f"Sleeve types: {df['sleeve_type'].value_counts().to_dict()}")

    cross_vps_comparison(df)
    per_sleeve_summary(df)
    direction_asymmetry(df)
    hour_pattern_live(df)
    daily_trend(df)
    fill_cost_diagnostic(df)
    time_since_last_fire(df)


if __name__ == "__main__":
    main()
