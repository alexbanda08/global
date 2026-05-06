"""Per-sleeve, per-asset, per-direction, per-host detail. NOT composed.
Every individual sleeve broken out — no V1/V2/V3 aggregation."""
from __future__ import annotations
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "v4" / "shadow_trades_2026_05_01"


def load() -> pd.DataFrame:
    v3 = pd.read_csv(DATA / "vps3.csv", parse_dates=["at"]); v3["host"] = "vps3"
    v2 = pd.read_csv(DATA / "vps2.csv", parse_dates=["at"]); v2["host"] = "vps2"
    df = pd.concat([v3, v2], ignore_index=True).sort_values("at").reset_index(drop=True)
    df["won"] = df["won"].map({"t": True, "f": False, True: True, False: False})
    df["hedged"] = df["hedged"].map({"t": True, "f": False, True: True, False: False})
    df["notional"] = df["entry_qty"] * df["entry_price"]
    df["asset"] = df["sleeve_id"].str.extract(r"poly_updown_(btc|eth|sol)")[0]
    df["tf"] = df["sleeve_id"].str.extract(r"_(5m|15m)_")[0]
    return df


def detail_per_sleeve(df: pd.DataFrame):
    """Each sleeve x host fully broken out by direction."""
    print(f"\n{'='*95}")
    print("PER-SLEEVE DETAIL (host × asset × tf × strategy × direction) — no aggregation")
    print(f"{'='*95}")
    print(f"  {'host':<5} {'sleeve':<32} {'sig':<5} {'n':>5} {'wins':>4} {'hit':>7} {'pnl':>9} {'fill':>7} {'roi':>7}")
    print(f"  {'-'*88}")
    g = df.groupby(["host", "sleeve_id", "signal"]).agg(
        n=("won", "size"), wins=("won", "sum"), hit=("won", "mean"),
        pnl=("pnl_usd", "sum"), fill=("entry_price", "mean"),
        notional=("notional", "sum"),
    ).reset_index()
    g["roi"] = g["pnl"] / g["notional"] * 100
    g = g.sort_values(["host", "sleeve_id", "signal"])
    last_sleeve = None
    for _, r in g.iterrows():
        if last_sleeve and last_sleeve != r["sleeve_id"]:
            print()  # blank line between sleeves
        print(f"  {r['host']:<5} {r['sleeve_id']:<32} {r['signal']:<5} "
              f"{int(r['n']):>5d} {int(r['wins']):>4d} {r['hit']*100:>6.1f}% "
              f"${r['pnl']:>+8.2f} {r['fill']:>7.4f} {r['roi']:>+6.2f}%")
        last_sleeve = r["sleeve_id"]


def per_sleeve_total(df: pd.DataFrame):
    print(f"\n{'='*95}")
    print("PER-SLEEVE TOTALS (no direction split)")
    print(f"{'='*95}")
    g = df.groupby(["host", "sleeve_id"]).agg(
        n=("won", "size"), wins=("won", "sum"), hit=("won", "mean"),
        pnl=("pnl_usd", "sum"), notional=("notional", "sum"),
        first=("at", "min"), last=("at", "max"),
    ).reset_index()
    g["roi"] = g["pnl"] / g["notional"] * 100
    g = g.sort_values(["host", "sleeve_id"])
    print(f"  {'host':<5} {'sleeve':<32} {'n':>5} {'wins':>4} {'hit':>7} {'pnl':>10} {'roi':>7} {'last_fire':>17}")
    print(f"  {'-'*92}")
    last_host = None
    for _, r in g.iterrows():
        if last_host and last_host != r["host"]:
            print()
        last = r["last"].strftime("%m-%d %H:%M")
        print(f"  {r['host']:<5} {r['sleeve_id']:<32} {int(r['n']):>5d} {int(r['wins']):>4d} "
              f"{r['hit']*100:>6.1f}% ${r['pnl']:>+9.2f} {r['roi']:>+6.2f}% {last:>17}")
        last_host = r["host"]


def per_asset_per_tf_per_direction(df: pd.DataFrame):
    """Cross-host: per (asset, tf, direction) so user can see same-market behavior."""
    print(f"\n{'='*95}")
    print("PER (ASSET × TF × DIRECTION) — cross all sleeves and hosts")
    print(f"{'='*95}")
    g = df.groupby(["asset", "tf", "signal"]).agg(
        n=("won", "size"), wins=("won", "sum"), hit=("won", "mean"),
        pnl=("pnl_usd", "sum"), notional=("notional", "sum"),
    ).reset_index()
    g["roi"] = g["pnl"] / g["notional"] * 100
    print(f"  {'asset':<5} {'tf':<5} {'sig':<5} {'n':>5} {'wins':>4} {'hit':>7} {'pnl':>10} {'roi':>7}")
    print(f"  {'-'*60}")
    last_asset = None
    for _, r in g.iterrows():
        if last_asset and last_asset != r["asset"]:
            print()
        print(f"  {r['asset']:<5} {r['tf']:<5} {r['signal']:<5} {int(r['n']):>5d} "
              f"{int(r['wins']):>4d} {r['hit']*100:>6.1f}% ${r['pnl']:>+9.2f} {r['roi']:>+6.2f}%")
        last_asset = r["asset"]


def detail_btc(df: pd.DataFrame):
    """User said 'per asset and market not composed' — give per market view too."""
    print(f"\n{'='*95}")
    print("PER-MARKET BTC DETAIL (one row per resolved market)")
    print(f"{'='*95}")
    btc = df[df["asset"] == "btc"].copy().sort_values("at")
    print(f"Total BTC markets resolved: {len(btc)}")
    print(f"Window: {btc['at'].min()} -> {btc['at'].max()}")
    print(f"\nFirst 10 BTC markets in window (sample):")
    print(f"  {'at':<22} {'host':<5} {'sleeve':<32} {'sig':<5} {'out':<5} won  fill   pnl")
    for _, r in btc.head(10).iterrows():
        won = "✓" if r["won"] else "✗"
        print(f"  {r['at'].strftime('%m-%d %H:%M:%S'):<22} {r['host']:<5} {r['sleeve_id']:<32} "
              f"{r['signal']:<5} {r['outcome']:<5} {won}    {r['entry_price']:.4f} ${r['pnl_usd']:>+6.2f}")


def main():
    df = load()
    print(f"Total resolutions: {len(df)} | Window: {df['at'].min()} -> {df['at'].max()}")
    print(f"Days covered: {(df['at'].max() - df['at'].min()).total_seconds()/86400:.2f}")
    print(f"\nMode distribution:")
    for m, c in df["mode"].value_counts().items():
        print(f"  {m}: {c}")
    print(f"Hedged distribution:")
    for h, c in df["hedged"].value_counts().items():
        print(f"  {h}: {c}")
    print(f"Host x sleeve count:")
    for (h, s), c in df.groupby(["host", "sleeve_id"]).size().items():
        last_fire = df[(df["host"] == h) & (df["sleeve_id"] == s)]["at"].max()
        mins_ago = (pd.Timestamp.now(tz="UTC") - last_fire.tz_convert("UTC")).total_seconds() / 60
        print(f"  {h} {s:<32} n={c:>4d} last_fire={last_fire.strftime('%m-%d %H:%M')} ({mins_ago:.0f}m ago)")

    per_sleeve_total(df)
    detail_per_sleeve(df)
    per_asset_per_tf_per_direction(df)


if __name__ == "__main__":
    main()
