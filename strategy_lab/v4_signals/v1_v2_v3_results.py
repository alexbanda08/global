"""V1 / V2 / V3 — full per-version results breakdown.

V1 = VPS2 volume-mode sleeves (HEDGE_HOLD, OKX-WS feed) — control arm
V2 = VPS3 sleeves except _v3 (HYBRID volume+sniper, binance-spot-ws feed) — test arm
     V2_volume + V2_sniper sub-modes
V3 = VPS3 _v3 sleeves only (per-asset tuned portfolio sniper)
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

    # Version classifier
    def version(row):
        if row["sleeve_id"].endswith("_v3"):
            return "V3"
        if row["host"] == "vps2":
            return "V1"
        if "_sniper" in row["sleeve_id"]:
            return "V2_sniper"
        if "_volume" in row["sleeve_id"]:
            return "V2_volume"
        return "other"
    df["version"] = df.apply(version, axis=1)
    df["asset"] = df["sleeve_id"].str.extract(r"poly_updown_(btc|eth|sol)")[0]
    df["tf"] = df["sleeve_id"].str.extract(r"_(5m|15m)_")[0]
    df["date_utc"] = df["at"].dt.tz_convert("UTC").dt.date
    df["hour_utc"] = df["at"].dt.tz_convert("UTC").dt.hour
    return df


def fmt_block(df, label):
    n = len(df)
    if n == 0:
        print(f"{label}: NO DATA")
        return
    wins = int(df["won"].sum())
    hit = wins / n
    pnl = df["pnl_usd"].sum()
    notional = df["notional"].sum()
    roi = pnl / notional * 100 if notional else 0
    avg_pnl = pnl / n
    avg_fill = df["entry_price"].mean()
    win_pnl = df[df["won"]]["pnl_usd"].sum()
    loss_pnl = df[~df["won"]]["pnl_usd"].sum()
    win_avg = df[df["won"]]["pnl_usd"].mean() if wins else 0
    loss_avg = df[~df["won"]]["pnl_usd"].mean() if (n - wins) else 0

    print(f"\n=== {label} ===")
    print(f"  Fires:       {n:>5d}  ({wins} wins / {n - wins} losses)")
    print(f"  Hit rate:    {hit*100:>5.2f}%")
    print(f"  Total PnL:   ${pnl:>+9.2f}")
    print(f"  Notional:    ${notional:>9.2f}")
    print(f"  ROI:         {roi:>+5.2f}%")
    print(f"  Avg PnL/trade: ${avg_pnl:>+6.2f}")
    print(f"  Avg fill cost: ${avg_fill:.4f}")
    print(f"  Avg win:     ${win_avg:>+6.2f}    (total: ${win_pnl:+.2f})")
    print(f"  Avg loss:    ${loss_avg:>+6.2f}    (total: ${loss_pnl:+.2f})")
    print(f"  Time window: {df['at'].min()} -> {df['at'].max()}")


def per_sleeve_table(df, version_filter):
    sub = df[df["version"] == version_filter]
    if len(sub) == 0:
        return
    g = sub.groupby("sleeve_id").agg(
        n=("won", "size"),
        wins=("won", "sum"),
        hit=("won", "mean"),
        pnl=("pnl_usd", "sum"),
        notional=("notional", "sum"),
        avg_fill=("entry_price", "mean"),
    ).reset_index()
    g["roi"] = g["pnl"] / g["notional"] * 100
    g = g.sort_values("pnl", ascending=False)
    print(f"\nPer-sleeve {version_filter}:")
    print(f"  {'sleeve':<32} {'n':>5} {'wins':>5} {'hit':>7} {'pnl':>10} {'roi':>7}")
    print(f"  {'-'*68}")
    for _, r in g.iterrows():
        print(f"  {r['sleeve_id']:<32} {int(r['n']):>5d} {int(r['wins']):>5d} "
              f"{r['hit']*100:>6.1f}% ${r['pnl']:>+9.2f} {r['roi']:>+6.2f}%")


def per_asset_direction(df, version_filter):
    sub = df[df["version"] == version_filter]
    if len(sub) == 0:
        return
    g = sub.groupby(["asset", "tf", "signal"]).agg(
        n=("won", "size"),
        hit=("won", "mean"),
        pnl=("pnl_usd", "sum"),
    ).reset_index()
    print(f"\n{version_filter} by asset / tf / direction:")
    print(f"  {'asset':<5} {'tf':<5} {'sig':<5} {'n':>5} {'hit':>7} {'pnl':>10}")
    print(f"  {'-'*52}")
    for _, r in g.iterrows():
        print(f"  {r['asset']:<5} {r['tf']:<5} {r['signal']:<5} {int(r['n']):>5d} "
              f"{r['hit']*100:>6.1f}% ${r['pnl']:>+9.2f}")


def per_day(df, version_filter):
    sub = df[df["version"] == version_filter]
    if len(sub) == 0:
        return
    g = sub.groupby("date_utc").agg(
        n=("won", "size"),
        hit=("won", "mean"),
        pnl=("pnl_usd", "sum"),
    ).reset_index()
    print(f"\n{version_filter} by date:")
    for _, r in g.iterrows():
        print(f"  {r['date_utc']!s:<12} n={int(r['n']):>4d}  hit={r['hit']*100:>5.1f}%  pnl=${r['pnl']:>+8.2f}")


def main():
    df = load()
    print(f"\n{'='*78}")
    print(f"V1 / V2 / V3 RESULTS (live shadow paper)")
    print(f"{'='*78}")
    print(f"Window: {df['at'].min()} -> {df['at'].max()}")
    print(f"Days covered: {(df['at'].max() - df['at'].min()).total_seconds()/86400:.2f}")
    print(f"Versions: {df['version'].value_counts().to_dict()}")

    # Headline summary table first
    print(f"\n{'='*78}")
    print(f"HEADLINE — top-line per version")
    print(f"{'='*78}")
    print(f"  {'version':<12} {'n':>6} {'wins':>5} {'hit':>7} {'pnl':>11} {'notional':>11} {'roi':>7}")
    print(f"  {'-'*68}")
    for v in ["V1", "V2_volume", "V2_sniper", "V3"]:
        sub = df[df["version"] == v]
        if len(sub) == 0: continue
        n = len(sub); wins = int(sub["won"].sum())
        hit = sub["won"].mean()
        pnl = sub["pnl_usd"].sum(); notional = sub["notional"].sum()
        roi = pnl / notional * 100 if notional else 0
        print(f"  {v:<12} {n:>6d} {wins:>5d} {hit*100:>6.2f}% ${pnl:>+10.2f} ${notional:>+10.2f} {roi:>+6.2f}%")

    # Detailed per-version breakdown
    for v in ["V1", "V2_volume", "V2_sniper", "V3"]:
        sub = df[df["version"] == v]
        if len(sub) == 0: continue
        fmt_block(sub, v)
        per_sleeve_table(df, v)
        per_asset_direction(df, v)
        per_day(df, v)


if __name__ == "__main__":
    main()
