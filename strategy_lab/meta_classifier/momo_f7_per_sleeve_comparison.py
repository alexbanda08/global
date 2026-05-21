"""Per-sleeve comparison: current production WR/PnL vs F7-filtered counterfactual.

Loads ALL `poly_updown_resolution` events from trading_events_30d.parquet (production
shadow + paper modes — no live yet) and:
  1. Groups by sleeve_id → reports current WR, n, PnL
  2. Attaches RSI(14) on binance 1m at signal time (ws)
  3. Applies F7 filter (RSI agrees with signal direction)
  4. Reports counterfactual WR/PnL — what the sleeve would have shown if F7 gate had been added
  5. Side-by-side delta

Output:
  strategy_lab/results/meta_classifier/momo_f7_per_sleeve.csv
  strategy_lab/reports/MOMO_F7_PER_SLEEVE_TABLE_2026_05_20.md
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
from load import load_klines_asof  # noqa: E402

OUT_CSV = ROOT / "strategy_lab" / "results" / "meta_classifier" / "momo_f7_per_sleeve.csv"
REPORT  = ROOT / "strategy_lab" / "reports" / "MOMO_F7_PER_SLEEVE_TABLE_2026_05_20.md"
OUT_CSV.parent.mkdir(parents=True, exist_ok=True)


def load_resolutions() -> pd.DataFrame:
    p = ROOT / "data" / "v4" / "canonical" / "trading_events_30d.parquet"
    d = ds.dataset(str(p), format="parquet")
    res = d.to_table(filter=ds.field("kind") == "poly_updown_resolution").to_pandas()
    res["parsed"] = res.data.apply(lambda s: json.loads(s) if isinstance(s, str) else {})
    res["mode"] = res.parsed.apply(lambda d: d.get("mode"))
    res["tf"] = res.parsed.apply(lambda d: d.get("tf"))
    res["symbol"] = res.parsed.apply(lambda d: d.get("symbol"))
    res["signal"] = res.parsed.apply(lambda d: d.get("signal"))
    res["won"] = res.parsed.apply(lambda d: d.get("won"))
    res["pnl_usd"] = res.parsed.apply(lambda d: float(d.get("pnl_usd") or 0))
    res["entry_price"] = res.parsed.apply(lambda d: float(d.get("entry_price") or 0))
    res["entry_qty"] = res.parsed.apply(lambda d: float(d.get("entry_qty") or 0))
    res["hedged"] = res.parsed.apply(lambda d: d.get("hedged"))
    res["at_ts"] = pd.to_datetime(res["at"], utc=True)
    res["ws_s"] = (res.at_ts.astype("int64") // 1_000_000_000)
    # Keep only resolutions with a sleeve_id we can group by
    res = res[res.sleeve_id.notna() & (res.sleeve_id != "system")].copy()
    return res[["sleeve_id", "mode", "symbol", "tf", "signal", "won",
                "pnl_usd", "entry_price", "entry_qty", "hedged", "at_ts", "ws_s"]]


def attach_rsi(df: pd.DataFrame) -> pd.DataFrame:
    """Add rsi_14 column using binance 1m closes ending at ws_s."""
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

        # 14-bar RSI on log returns of 1m closes
        log_rets = np.full(len(close), np.nan, dtype="float64")
        log_rets[1:] = np.log(close[1:] / close[:-1])
        up = np.where(log_rets > 0, log_rets, 0.0)
        dn = np.where(log_rets < 0, -log_rets, 0.0)
        n14 = 14
        csu = np.cumsum(up)
        csd = np.cumsum(dn)
        roll_up = np.full_like(up, np.nan)
        roll_dn = np.full_like(dn, np.nan)
        roll_up[n14:] = (csu[n14:] - csu[:-n14]) / n14
        roll_dn[n14:] = (csd[n14:] - csd[:-n14]) / n14
        rsi = np.where(roll_dn > 0,
                       100 - 100 / (1 + roll_up / np.maximum(roll_dn, 1e-12)),
                       50.0)
        rsi[:n14] = np.nan

        idx = np.searchsorted(end_us, ws_us, side="right") - 1
        idx = np.clip(idx, 0, len(rsi) - 1)
        rsi_vals = np.where(idx >= 0, rsi[idx], np.nan)
        df.loc[m, "rsi_14"] = rsi_vals
    return df


def f7_keep(signal, rsi) -> bool:
    if not (rsi == rsi):  # NaN check
        return False
    if signal == "UP" and rsi <= 50: return False
    if signal == "DOWN" and rsi >= 50: return False
    return True


def f7_extreme_keep(signal, rsi) -> bool:
    if not (rsi == rsi):
        return False
    if signal == "UP" and rsi <= 60: return False
    if signal == "DOWN" and rsi >= 40: return False
    return True


def per_sleeve_table(df: pd.DataFrame) -> pd.DataFrame:
    """Group by sleeve_id, compute current + F7 + F7_extreme stats."""
    df = df.copy()
    df["keep_f7"] = df.apply(lambda r: f7_keep(r["signal"], r["rsi_14"]), axis=1)
    df["keep_f7x"] = df.apply(lambda r: f7_extreme_keep(r["signal"], r["rsi_14"]), axis=1)

    rows = []
    for sleeve_id, grp in df.groupby("sleeve_id"):
        cur_n = len(grp)
        cur_w = int((grp.won == True).sum())
        cur_wr = cur_w / cur_n * 100 if cur_n else 0
        cur_pnl = float(grp.pnl_usd.sum())
        cur_mean = float(grp.pnl_usd.mean()) if cur_n else 0

        f7 = grp[grp.keep_f7]
        f7_n = len(f7); f7_w = int((f7.won == True).sum())
        f7_wr = f7_w / f7_n * 100 if f7_n else 0
        f7_pnl = float(f7.pnl_usd.sum())
        f7_mean = float(f7.pnl_usd.mean()) if f7_n else 0

        f7x = grp[grp.keep_f7x]
        f7x_n = len(f7x); f7x_w = int((f7x.won == True).sum())
        f7x_wr = f7x_w / f7x_n * 100 if f7x_n else 0
        f7x_pnl = float(f7x.pnl_usd.sum())
        f7x_mean = float(f7x.pnl_usd.mean()) if f7x_n else 0

        rows.append(dict(
            sleeve_id=sleeve_id,
            symbol=grp.symbol.iloc[0],
            tf=grp.tf.iloc[0],
            mode=grp["mode"].iloc[0],
            cur_n=cur_n, cur_wr_pct=round(cur_wr, 2),
            cur_pnl_total=round(cur_pnl, 2),
            cur_pnl_per_trade=round(cur_mean, 4),
            f7_n=f7_n, f7_wr_pct=round(f7_wr, 2),
            f7_pnl_total=round(f7_pnl, 2),
            f7_pnl_per_trade=round(f7_mean, 4),
            f7_skipped=cur_n - f7_n,
            f7x_n=f7x_n, f7x_wr_pct=round(f7x_wr, 2),
            f7x_pnl_total=round(f7x_pnl, 2),
            f7x_pnl_per_trade=round(f7x_mean, 4),
            f7x_skipped=cur_n - f7x_n,
            f7_pnl_delta=round(f7_pnl - cur_pnl, 2),
            f7x_pnl_delta=round(f7x_pnl - cur_pnl, 2),
            f7_wr_delta=round(f7_wr - cur_wr, 2),
            f7x_wr_delta=round(f7x_wr - cur_wr, 2),
        ))
    return pd.DataFrame(rows).sort_values("cur_pnl_total", ascending=False)


def render_md(tbl: pd.DataFrame) -> str:
    L = ["# Per-sleeve comparison — current vs F7 RSI filter — 2026-05-20\n",
         "**Data sources**:",
         f"- `trading_events_30d.parquet` — {len(tbl):,} sleeves with paper/shadow resolutions",
         "- Modes present: only `paper` (momo direction bets) and `shadow` (MAS mint-sell). NO `live` events yet.",
         "- Source canonical binance 1m klines for RSI(14) on log-returns.\n",
         "## How to read this",
         "- **cur_***: what the production sleeve actually produced (paper/shadow mode)",
         "- **f7_***: counterfactual if F7 gate was applied (UP+RSI>50 / DOWN+RSI<50)",
         "- **f7x_***: stricter F7_extreme (UP+RSI>60 / DOWN+RSI<40)",
         "- `f7_skipped`: how many fires F7 would have filtered out",
         "- `pnl_delta`: F7 sum PnL minus current sum PnL\n",
         "## Aggregate (sum across all 74 sleeves)\n"]
    agg_cur_n = tbl.cur_n.sum()
    agg_cur_w = (tbl.cur_n * tbl.cur_wr_pct / 100).sum()
    agg_cur_wr = agg_cur_w / agg_cur_n * 100 if agg_cur_n else 0
    agg_cur_pnl = tbl.cur_pnl_total.sum()
    agg_f7_n = tbl.f7_n.sum()
    agg_f7_w = (tbl.f7_n * tbl.f7_wr_pct / 100).sum()
    agg_f7_wr = agg_f7_w / agg_f7_n * 100 if agg_f7_n else 0
    agg_f7_pnl = tbl.f7_pnl_total.sum()
    agg_f7x_n = tbl.f7x_n.sum()
    agg_f7x_w = (tbl.f7x_n * tbl.f7x_wr_pct / 100).sum()
    agg_f7x_wr = agg_f7x_w / agg_f7x_n * 100 if agg_f7x_n else 0
    agg_f7x_pnl = tbl.f7x_pnl_total.sum()

    L.append("| Config | n_trades | WR % | Sum PnL | $/trade |")
    L.append("|---|---:|---:|---:|---:|")
    L.append(f"| **Current production** | {agg_cur_n:,} | {agg_cur_wr:.2f}% | ${agg_cur_pnl:+,.2f} | ${agg_cur_pnl/max(agg_cur_n,1):.4f} |")
    L.append(f"| **+ F7 filter** | {agg_f7_n:,} | {agg_f7_wr:.2f}% | ${agg_f7_pnl:+,.2f} | ${agg_f7_pnl/max(agg_f7_n,1):.4f} |")
    L.append(f"| **+ F7_extreme** | {agg_f7x_n:,} | {agg_f7x_wr:.2f}% | ${agg_f7x_pnl:+,.2f} | ${agg_f7x_pnl/max(agg_f7x_n,1):.4f} |")
    L.append("")
    L.append(f"**Swing**: current ${agg_cur_pnl:+,.2f} → F7 ${agg_f7_pnl:+,.2f} = "
             f"**${agg_f7_pnl - agg_cur_pnl:+,.2f}** improvement over the data window.")
    L.append("")

    # Split into momo vs mint_sell vs sniper
    is_momo = tbl.sleeve_id.str.contains("momo")
    is_sniper = tbl.sleeve_id.str.contains("sniper")
    is_mint = tbl.sleeve_id.str.contains("mint_sell")
    is_vol = tbl.sleeve_id.str.contains("volume_INV_NIGHT")

    def family_summary(name: str, mask: pd.Series) -> str:
        sub = tbl[mask]
        n = sub.cur_n.sum()
        cn = (sub.cur_n * sub.cur_wr_pct / 100).sum()
        cp = sub.cur_pnl_total.sum()
        fn = sub.f7_n.sum()
        fw = (sub.f7_n * sub.f7_wr_pct / 100).sum()
        fp = sub.f7_pnl_total.sum()
        xn = sub.f7x_n.sum()
        xw = (sub.f7x_n * sub.f7x_wr_pct / 100).sum()
        xp = sub.f7x_pnl_total.sum()
        return (
            f"| {name} | {len(sub)} | {n:,} | {(cn/max(n,1)*100):.1f}% | ${cp:+,.0f} | "
            f"{fn:,} | {(fw/max(fn,1)*100):.1f}% | ${fp:+,.0f} | "
            f"{xn:,} | {(xw/max(xn,1)*100):.1f}% | ${xp:+,.0f} |"
        )

    L.append("## Aggregate by strategy family\n")
    L.append("| Family | n_sleeves | cur_n | cur_WR% | cur_PnL | f7_n | f7_WR% | f7_PnL | f7x_n | f7x_WR% | f7x_PnL |")
    L.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    L.append(family_summary("momo (all)", is_momo))
    L.append(family_summary("sniper (all)", is_sniper))
    L.append(family_summary("mint_sell (shadow)", is_mint))
    L.append(family_summary("volume_INV_NIGHT", is_vol))
    L.append("")

    L.append("## Per-sleeve full table (sorted by current PnL desc)\n")
    L.append("| sleeve_id | symbol | tf | mode | cur_n | cur_WR% | cur_PnL | f7_n | f7_WR% | f7_PnL | f7_Δ$ | f7_Δwr |")
    L.append("|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for _, r in tbl.iterrows():
        L.append(
            f"| {r.sleeve_id} | {r.symbol} | {r.tf} | {r['mode']} | "
            f"{r.cur_n:,} | {r.cur_wr_pct:.1f}% | ${r.cur_pnl_total:+,.0f} | "
            f"{r.f7_n:,} | {r.f7_wr_pct:.1f}% | ${r.f7_pnl_total:+,.0f} | "
            f"${r.f7_pnl_delta:+,.0f} | {r.f7_wr_delta:+.1f}pp |"
        )
    L.append("")

    L.append("## Top 10 by F7 PnL improvement\n")
    top = tbl.nlargest(10, "f7_pnl_delta")
    L.append("| sleeve_id | cur_PnL | f7_PnL | improvement | cur_WR | f7_WR | n_skipped |")
    L.append("|---|---:|---:|---:|---:|---:|---:|")
    for _, r in top.iterrows():
        L.append(
            f"| {r.sleeve_id} | ${r.cur_pnl_total:+,.0f} | ${r.f7_pnl_total:+,.0f} | "
            f"**${r.f7_pnl_delta:+,.0f}** | {r.cur_wr_pct:.1f}% | {r.f7_wr_pct:.1f}% | "
            f"{r.f7_skipped} |"
        )
    L.append("")

    L.append("## Sleeves where F7 HURTS (counter-examples / risks)\n")
    hurt = tbl[tbl.f7_pnl_delta < -10].nsmallest(15, "f7_pnl_delta")
    if hurt.empty:
        L.append("None — F7 helps every sleeve or stays neutral.\n")
    else:
        L.append("| sleeve_id | cur_PnL | f7_PnL | loss | cur_WR | f7_WR | n_skipped |")
        L.append("|---|---:|---:|---:|---:|---:|---:|")
        for _, r in hurt.iterrows():
            L.append(
                f"| {r.sleeve_id} | ${r.cur_pnl_total:+,.0f} | ${r.f7_pnl_total:+,.0f} | "
                f"**${r.f7_pnl_delta:+,.0f}** | {r.cur_wr_pct:.1f}% | {r.f7_wr_pct:.1f}% | "
                f"{r.f7_skipped} |"
            )
    L.append("")

    L.append("## Caveats\n")
    L.append("- Mode breakdown: only `paper` (momo) and `shadow` (mint_sell) — **no `live` events in this 30d window**.")
    L.append("- mint_sell sleeves: F7 applied based on signal direction inferred from outcome; not meaningful for pair-buy strategies.")
    L.append("- RSI on binance 1m closes — at the resolution timestamp (close to fire+resolve time).")
    L.append("- This is COUNTERFACTUAL — assumes filter had been live; reality would also depend on fill price drift.")
    return "\n".join(L)


def main():
    print("[1] Loading production resolutions ...")
    df = load_resolutions()
    print(f"    {len(df):,} rows, {df.sleeve_id.nunique()} sleeves")

    print("[2] Attaching RSI ...")
    df = attach_rsi(df)
    print(f"    RSI finite: {df.rsi_14.notna().sum():,}")

    print("[3] Building per-sleeve comparison table ...")
    tbl = per_sleeve_table(df)
    tbl.to_csv(OUT_CSV, index=False)
    print(f"    Wrote {OUT_CSV}")

    print("[4] Writing report ...")
    REPORT.write_text(render_md(tbl), encoding="utf-8")
    print(f"    Wrote {REPORT}")
    print()

    # Print aggregate to stdout
    agg_cur_n = tbl.cur_n.sum()
    agg_cur_w = (tbl.cur_n * tbl.cur_wr_pct / 100).sum()
    agg_cur_pnl = tbl.cur_pnl_total.sum()
    agg_f7_n = tbl.f7_n.sum()
    agg_f7_w = (tbl.f7_n * tbl.f7_wr_pct / 100).sum()
    agg_f7_pnl = tbl.f7_pnl_total.sum()
    print("=" * 80)
    print(f"AGGREGATE — current production vs F7-filtered counterfactual")
    print("=" * 80)
    print(f"  Current: n={agg_cur_n:,}  WR={agg_cur_w/max(agg_cur_n,1)*100:.2f}%  Sum=${agg_cur_pnl:+,.2f}")
    print(f"  + F7:    n={agg_f7_n:,}  WR={agg_f7_w/max(agg_f7_n,1)*100:.2f}%  Sum=${agg_f7_pnl:+,.2f}")
    print(f"  Swing:   ${agg_f7_pnl - agg_cur_pnl:+,.2f}")
    print()
    print("Top 10 sleeves by F7 PnL improvement:")
    print(tbl.nlargest(10, "f7_pnl_delta")[
        ["sleeve_id", "cur_n", "cur_wr_pct", "cur_pnl_total",
         "f7_n", "f7_wr_pct", "f7_pnl_total", "f7_pnl_delta"]].to_string(index=False))


if __name__ == "__main__":
    main()
