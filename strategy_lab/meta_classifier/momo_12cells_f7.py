"""Clean 12-cell momo F7 comparison.

VPS3 has momo v1 + v2 across {BTC,ETH,SOL} × {5m,15m} = 12 cells.
Each cell has 3 exit-policy sleeves (HOLD/HEDGE/SELL) sharing the SAME fires.
For WR comparison we use the HOLD variant (pure direction bet, no exit logic).

Output: 12-row table — current WR/PnL vs F7-filtered WR/PnL.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
from load import load_klines_asof  # noqa: E402

VPS3_FILE = ROOT / "strategy_lab" / "monitoring" / "_logs" / "vps3" / "momo_events_14d.csv"
OUT = ROOT / "strategy_lab" / "results" / "meta_classifier" / "momo_12cells_f7.csv"
REPORT = ROOT / "strategy_lab" / "reports" / "MOMO_12CELLS_F7_2026_05_20.md"


def load_resolutions() -> pd.DataFrame:
    df = pd.read_csv(VPS3_FILE)
    df = df[df.kind == "poly_updown_resolution"].copy()
    df["parsed"] = df.data_json.apply(lambda s: json.loads(s) if isinstance(s, str) else {})
    df["mode"] = df.parsed.apply(lambda d: d.get("mode"))
    df["symbol"] = df.parsed.apply(lambda d: d.get("symbol"))
    df["tf"] = df.parsed.apply(lambda d: d.get("tf"))
    df["signal"] = df.parsed.apply(lambda d: d.get("signal"))
    df["won"] = df.parsed.apply(lambda d: d.get("won"))
    df["pnl_usd"] = df.parsed.apply(lambda d: float(d.get("pnl_usd") or 0))
    df["at_ts"] = pd.to_datetime(df["at"], utc=True)
    df["ws_s"] = (df.at_ts.astype("int64") // 1_000_000_000)
    # Extract version (v1 default, v2 if "_v2_" in sleeve_id)
    df["version"] = df.sleeve_id.apply(lambda s: "v2" if "_momo_v2_" in s else ("v1" if "_momo_" in s else None))
    df = df[df.version.notna()].copy()
    df["cell"] = df.symbol.str.lower() + "_" + df.tf
    df["policy"] = df.sleeve_id.str.extract(r"_momo(?:_v2)?_(HOLD|HEDGE|SELL)$")[0]
    return df


def attach_rsi(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["rsi_14"] = np.nan
    for asset in ["BTC", "ETH", "SOL"]:
        m = df.symbol == asset
        if not m.any():
            continue
        end_us, close = load_klines_asof(asset, "binance-spot-ws", "1MIN")
        if len(end_us) == 0:
            continue
        ws_us = df.loc[m, "ws_s"].values.astype("int64") * 1_000_000
        log_rets = np.full(len(close), np.nan, dtype="float64")
        log_rets[1:] = np.log(close[1:] / close[:-1])
        up = np.where(log_rets > 0, log_rets, 0.0)
        dn = np.where(log_rets < 0, -log_rets, 0.0)
        n14 = 14
        csu = np.cumsum(up); csd = np.cumsum(dn)
        roll_up = np.full_like(up, np.nan); roll_dn = np.full_like(dn, np.nan)
        roll_up[n14:] = (csu[n14:] - csu[:-n14]) / n14
        roll_dn[n14:] = (csd[n14:] - csd[:-n14]) / n14
        rsi = np.where(roll_dn > 0,
                       100 - 100 / (1 + roll_up / np.maximum(roll_dn, 1e-12)),
                       50.0)
        rsi[:n14] = np.nan
        idx = np.searchsorted(end_us, ws_us, side="right") - 1
        idx = np.clip(idx, 0, len(rsi) - 1)
        df.loc[m, "rsi_14"] = np.where(idx >= 0, rsi[idx], np.nan)
    return df


def f7_keep(signal, rsi):
    if not (rsi == rsi): return False
    if signal == "UP" and rsi <= 50: return False
    if signal == "DOWN" and rsi >= 50: return False
    return True


def f7x_keep(signal, rsi):
    if not (rsi == rsi): return False
    if signal == "UP" and rsi <= 60: return False
    if signal == "DOWN" and rsi >= 40: return False
    return True


def build_table(df: pd.DataFrame) -> pd.DataFrame:
    """One row per (cell, version, policy)."""
    rows = []
    for (cell, version, policy), grp in df.groupby(["cell", "version", "policy"]):
        if not policy:
            continue
        cur_n = len(grp); cur_w = int((grp.won == True).sum())
        cur_pnl = float(grp.pnl_usd.sum())
        f7 = grp[grp.apply(lambda r: f7_keep(r.signal, r.rsi_14), axis=1)]
        f7x = grp[grp.apply(lambda r: f7x_keep(r.signal, r.rsi_14), axis=1)]
        rows.append(dict(
            cell=cell, version=version, policy=policy,
            cur_n=cur_n, cur_wr=round(cur_w / max(cur_n, 1) * 100, 2),
            cur_pnl=round(cur_pnl, 2), cur_per=round(cur_pnl / max(cur_n, 1), 4),
            f7_n=len(f7), f7_w=int((f7.won == True).sum()),
            f7_wr=round((f7.won == True).sum() / max(len(f7), 1) * 100, 2),
            f7_pnl=round(f7.pnl_usd.sum(), 2),
            f7_per=round(f7.pnl_usd.sum() / max(len(f7), 1), 4),
            f7_delta=round(f7.pnl_usd.sum() - cur_pnl, 2),
            f7x_n=len(f7x), f7x_w=int((f7x.won == True).sum()),
            f7x_wr=round((f7x.won == True).sum() / max(len(f7x), 1) * 100, 2),
            f7x_pnl=round(f7x.pnl_usd.sum(), 2),
            f7x_per=round(f7x.pnl_usd.sum() / max(len(f7x), 1), 4),
        ))
    return pd.DataFrame(rows)


def render_md(tbl: pd.DataFrame, agg_v1: dict, agg_v2: dict) -> str:
    L = ["# Momo 6 v1 + 6 v2 cells — current vs F7 RSI filter — 2026-05-20\n",
         "Real VPS3 shadow trades, last 14 days. F7 = RSI(14) on binance 1m agrees with signal direction.\n",
         "## momo v1 — 6 cells × 3 policies (HEDGE/HOLD/SELL share same fires; WR identical across policies, PnL differs)\n"]

    # v1 table
    L.append("| cell | policy | cur_n | **cur_WR** | cur_PnL | $/trade | f7_n | **f7_WR** | f7_PnL | $/trade | f7_extr_WR | f7_extr_PnL |")
    L.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for _, r in tbl[tbl.version == "v1"].sort_values(["cell", "policy"]).iterrows():
        L.append(f"| {r.cell} | {r.policy} | {r.cur_n} | **{r.cur_wr:.2f}%** | ${r.cur_pnl:+,.0f} | ${r.cur_per:+.2f} | "
                 f"{r.f7_n} | **{r.f7_wr:.2f}%** | ${r.f7_pnl:+,.0f} | ${r.f7_per:+.2f} | "
                 f"{r.f7x_wr:.2f}% | ${r.f7x_pnl:+,.0f} |")

    L.append(f"\n**v1 aggregate**: {agg_v1['cur_n']:,} trades current WR {agg_v1['cur_wr']:.2f}% / "
             f"${agg_v1['cur_pnl']:+,.0f} → F7 WR **{agg_v1['f7_wr']:.2f}%** / ${agg_v1['f7_pnl']:+,.0f} "
             f"(+${agg_v1['f7_delta']:+,.0f}, ${agg_v1['f7_delta']/14:+,.0f}/day)\n")

    L.append("## momo v2 — 6 cells × 3 policies\n")
    L.append("| cell | policy | cur_n | **cur_WR** | cur_PnL | $/trade | f7_n | **f7_WR** | f7_PnL | $/trade | f7_extr_WR | f7_extr_PnL |")
    L.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for _, r in tbl[tbl.version == "v2"].sort_values(["cell", "policy"]).iterrows():
        L.append(f"| {r.cell} | {r.policy} | {r.cur_n} | **{r.cur_wr:.2f}%** | ${r.cur_pnl:+,.0f} | ${r.cur_per:+.2f} | "
                 f"{r.f7_n} | **{r.f7_wr:.2f}%** | ${r.f7_pnl:+,.0f} | ${r.f7_per:+.2f} | "
                 f"{r.f7x_wr:.2f}% | ${r.f7x_pnl:+,.0f} |")

    L.append(f"\n**v2 aggregate**: {agg_v2['cur_n']:,} trades current WR {agg_v2['cur_wr']:.2f}% / "
             f"${agg_v2['cur_pnl']:+,.0f} → F7 WR **{agg_v2['f7_wr']:.2f}%** / ${agg_v2['f7_pnl']:+,.0f} "
             f"(+${agg_v2['f7_delta']:+,.0f}, ${agg_v2['f7_delta']/14:+,.0f}/day)\n")

    L.append("## Per-cell summary (HOLD policy only — cleanest direction bet, no exit logic noise)\n")
    L.append("| cell | version | cur_n | **cur_WR** | cur_PnL | f7_n | **f7_WR** | f7_PnL | WR Δpp | PnL Δ$ |")
    L.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for _, r in tbl[tbl.policy == "HOLD"].sort_values(["version", "cell"]).iterrows():
        L.append(f"| {r.cell} | {r.version} | {r.cur_n} | **{r.cur_wr:.2f}%** | ${r.cur_pnl:+,.0f} | "
                 f"{r.f7_n} | **{r.f7_wr:.2f}%** | ${r.f7_pnl:+,.0f} | "
                 f"+{r.f7_wr - r.cur_wr:.2f} | ${r.f7_delta:+,.0f} |")

    return "\n".join(L)


def main():
    print("[1] Loading momo resolutions ...")
    df = load_resolutions()
    print(f"    {len(df):,} resolutions  v1: {(df.version=='v1').sum():,}  v2: {(df.version=='v2').sum():,}")
    print(f"    cells: {sorted(df.cell.unique())}")
    print(f"    policies: {sorted(df.policy.dropna().unique())}")

    print("[2] Attaching RSI ...")
    df = attach_rsi(df)
    print(f"    RSI finite: {df.rsi_14.notna().sum():,}")

    print("[3] Building table ...")
    tbl = build_table(df)
    tbl.to_csv(OUT, index=False)

    # Aggregates per version using HOLD only (each policy has same fires, just different exits)
    def agg(sub):
        return dict(
            cur_n=int(sub.cur_n.sum()),
            cur_w=int((sub.cur_n * sub.cur_wr / 100).sum()),
            cur_wr=float((sub.cur_n * sub.cur_wr / 100).sum() / max(sub.cur_n.sum(), 1) * 100),
            cur_pnl=float(sub.cur_pnl.sum()),
            f7_n=int(sub.f7_n.sum()),
            f7_w=int(sub.f7_w.sum()),
            f7_wr=float(sub.f7_w.sum() / max(sub.f7_n.sum(), 1) * 100),
            f7_pnl=float(sub.f7_pnl.sum()),
            f7_delta=float(sub.f7_pnl.sum() - sub.cur_pnl.sum()),
        )
    agg_v1 = agg(tbl[(tbl.version == "v1") & (tbl.policy == "HOLD")])
    agg_v2 = agg(tbl[(tbl.version == "v2") & (tbl.policy == "HOLD")])

    REPORT.write_text(render_md(tbl, agg_v1, agg_v2), encoding="utf-8")
    print(f"\n    Wrote {OUT}")
    print(f"    Wrote {REPORT}")

    print()
    print("=" * 110)
    print("THE ANSWER — HOLD-policy fires (same as actual momo signals; exit policies share fires)")
    print("=" * 110)
    print()
    hold = tbl[tbl.policy == "HOLD"].sort_values(["version", "cell"])
    print(f"{'cell':<10} {'ver':<4} {'cur_n':>6} {'cur_WR':>8} {'cur_PnL':>10} "
          f"{'f7_n':>6} {'f7_WR':>8} {'f7_PnL':>10} {'WRΔ':>7} {'PnLΔ':>10}")
    print("-" * 100)
    for _, r in hold.iterrows():
        print(f"{r.cell:<10} {r.version:<4} {r.cur_n:>6d} {r.cur_wr:>7.2f}% "
              f"${r.cur_pnl:>+9.0f} {r.f7_n:>6d} {r.f7_wr:>7.2f}% "
              f"${r.f7_pnl:>+9.0f} {r.f7_wr - r.cur_wr:>+6.2f} ${r.f7_delta:>+9.0f}")

    print()
    print("=" * 110)
    print(f"v1 AGGREGATE: cur={agg_v1['cur_n']} trades  WR {agg_v1['cur_wr']:.2f}%  PnL ${agg_v1['cur_pnl']:+,.0f}")
    print(f"              + F7 = {agg_v1['f7_n']} trades  WR **{agg_v1['f7_wr']:.2f}%**  PnL **${agg_v1['f7_pnl']:+,.0f}**")
    print(f"              Δ = ${agg_v1['f7_delta']:+,.0f} over 14d = ${agg_v1['f7_delta']/14:+,.0f}/day")
    print()
    print(f"v2 AGGREGATE: cur={agg_v2['cur_n']} trades  WR {agg_v2['cur_wr']:.2f}%  PnL ${agg_v2['cur_pnl']:+,.0f}")
    print(f"              + F7 = {agg_v2['f7_n']} trades  WR **{agg_v2['f7_wr']:.2f}%**  PnL **${agg_v2['f7_pnl']:+,.0f}**")
    print(f"              Δ = ${agg_v2['f7_delta']:+,.0f} over 14d = ${agg_v2['f7_delta']/14:+,.0f}/day")
    print()
    print(f"TOTAL v1+v2 SWING: ${agg_v1['f7_delta'] + agg_v2['f7_delta']:+,.0f} over 14d "
          f"= ${(agg_v1['f7_delta'] + agg_v2['f7_delta'])/14:+,.0f}/day")


if __name__ == "__main__":
    main()
