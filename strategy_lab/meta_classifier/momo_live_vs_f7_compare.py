"""Compare LIVE VPS3 momo shadow trades + Ireland maker live trades vs F7-RSI counterfactual.

VPS3 momo (paper mode = real shadow direction bets):
  - Loads momo_events_14d.csv pulled from trading.events
  - Applies F7 RSI filter (UP+RSI>50 / DOWN+RSI<50) using binance 1m klines
  - Reports WR/PnL/trade-count per sleeve: current vs F7 vs F7_extreme

Ireland maker sleeves (acc-m / acc-h / acc-pc / mas / pat-shadow):
  - Loads each shadow CSV
  - F7 doesn't apply (non-directional pair-arb / mint-sell), so just reports
    current per-slug PnL aggregates
  - Tags which 3 sleeves are "live" vs pure shadow (heuristic: ts of recent fills)

Output:
  strategy_lab/results/meta_classifier/momo_live_vs_f7.csv     (VPS3 per-sleeve)
  strategy_lab/results/meta_classifier/ireland_live_sleeves.csv (Ireland per-sleeve)
  strategy_lab/reports/MOMO_LIVE_VS_F7_2026_05_20.md
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
IRELAND_DIR = ROOT / "strategy_lab" / "monitoring" / "_logs" / "ireland"
OUT_DIR = ROOT / "strategy_lab" / "results" / "meta_classifier"
OUT_DIR.mkdir(parents=True, exist_ok=True)
REPORT = ROOT / "strategy_lab" / "reports" / "MOMO_LIVE_VS_F7_2026_05_20.md"


# ---------------------------------------------------------------------------
# VPS3 momo: parse → F7 overlay
# ---------------------------------------------------------------------------

def load_vps3_momo() -> pd.DataFrame:
    df = pd.read_csv(VPS3_FILE)
    df["parsed"] = df.data_json.apply(lambda s: json.loads(s) if isinstance(s, str) else {})
    df["mode"] = df.parsed.apply(lambda d: d.get("mode"))
    df["symbol"] = df.parsed.apply(lambda d: d.get("symbol"))
    df["tf"] = df.parsed.apply(lambda d: d.get("tf"))
    df["signal"] = df.parsed.apply(lambda d: d.get("signal"))
    df["won"] = df.parsed.apply(lambda d: d.get("won"))
    df["pnl_usd"] = df.parsed.apply(lambda d: float(d.get("pnl_usd") or 0))
    df["outcome"] = df.parsed.apply(lambda d: d.get("outcome"))
    df["at_ts"] = pd.to_datetime(df["at"], utc=True)
    df["ws_s"] = (df.at_ts.astype("int64") // 1_000_000_000)
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
    if not (rsi == rsi):
        return False
    if signal == "UP" and rsi <= 50: return False
    if signal == "DOWN" and rsi >= 50: return False
    return True


def f7x_keep(signal, rsi):
    if not (rsi == rsi):
        return False
    if signal == "UP" and rsi <= 60: return False
    if signal == "DOWN" and rsi >= 40: return False
    return True


def vps3_per_sleeve(df: pd.DataFrame) -> pd.DataFrame:
    res = df[df.kind == "poly_updown_resolution"].copy()
    res["keep_f7"] = res.apply(lambda r: f7_keep(r["signal"], r["rsi_14"]), axis=1)
    res["keep_f7x"] = res.apply(lambda r: f7x_keep(r["signal"], r["rsi_14"]), axis=1)

    rows = []
    for sid, grp in res.groupby("sleeve_id"):
        cur_n = len(grp)
        cur_w = int((grp.won == True).sum())
        cur_pnl = float(grp.pnl_usd.sum())
        f7 = grp[grp.keep_f7]
        f7x = grp[grp.keep_f7x]

        rows.append(dict(
            sleeve_id=sid,
            symbol=grp.symbol.iloc[0] if cur_n else "",
            tf=grp.tf.iloc[0] if cur_n else "",
            mode=grp["mode"].iloc[0] if cur_n else "",
            cur_n=cur_n,
            cur_wins=cur_w,
            cur_wr_pct=round(cur_w / max(cur_n, 1) * 100, 2),
            cur_pnl=round(cur_pnl, 2),
            cur_pnl_per=round(cur_pnl / max(cur_n, 1), 4),
            f7_n=len(f7),
            f7_wins=int((f7.won == True).sum()),
            f7_wr_pct=round((f7.won == True).sum() / max(len(f7), 1) * 100, 2),
            f7_pnl=round(f7.pnl_usd.sum(), 2),
            f7_pnl_per=round(f7.pnl_usd.sum() / max(len(f7), 1), 4),
            f7_skipped=cur_n - len(f7),
            f7_pnl_delta=round(f7.pnl_usd.sum() - cur_pnl, 2),
            f7_wr_delta=round((f7.won == True).sum() / max(len(f7), 1) * 100 - cur_w / max(cur_n, 1) * 100, 2),
            f7x_n=len(f7x),
            f7x_wins=int((f7x.won == True).sum()),
            f7x_wr_pct=round((f7x.won == True).sum() / max(len(f7x), 1) * 100, 2),
            f7x_pnl=round(f7x.pnl_usd.sum(), 2),
            f7x_pnl_per=round(f7x.pnl_usd.sum() / max(len(f7x), 1), 4),
            f7x_skipped=cur_n - len(f7x),
            f7x_pnl_delta=round(f7x.pnl_usd.sum() - cur_pnl, 2),
        ))
    return pd.DataFrame(rows).sort_values("cur_pnl", ascending=False)


# ---------------------------------------------------------------------------
# Ireland maker sleeves: parse → per-slug aggregates (F7 N/A — non-directional)
# ---------------------------------------------------------------------------

def parse_ireland_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    return df


def ireland_per_sleeve() -> pd.DataFrame:
    """Aggregate per sleeve from Ireland CSVs (last 2 days available: May 19-20)."""
    rows = []
    sleeves = {}  # sleeve_name -> [csvs]
    for csv in sorted(IRELAND_DIR.glob("*.csv")):
        name = csv.stem.split("_2026-")[0]  # acc-m, acc-h, etc
        sleeves.setdefault(name, []).append(csv)

    for sleeve, files in sleeves.items():
        parts = [parse_ireland_csv(p) for p in files]
        df = pd.concat(parts, ignore_index=True)
        # Per-slug aggregation:
        # cost_spent, cash_received, rebates, taker_fees → slug PnL summed at last row per slug
        if "slug" not in df.columns:
            continue
        # Use last row per slug for cumulative values
        last_per_slug = df.sort_values("ts_us").drop_duplicates("slug", keep="last")
        # Identify slugs that finished (have a MERGE or LOG_SLUG_COMPLETE action — for completeness use all)
        # PnL approximation: cash_recovered + rebates - cash_spent - taker_fees (when fill_simulated=1)
        for col in ["cash_spent", "cash_received", "cash_recovered", "rebates", "taker_fees", "slug_pnl_so_far"]:
            if col not in last_per_slug.columns:
                last_per_slug[col] = 0
            last_per_slug[col] = pd.to_numeric(last_per_slug[col], errors="coerce").fillna(0)
        # Use slug_pnl_so_far if present, else compute
        last_per_slug["pnl_calc"] = (
            last_per_slug["cash_received"] + last_per_slug["cash_recovered"] +
            last_per_slug["rebates"] - last_per_slug["cash_spent"] - last_per_slug["taker_fees"]
        )
        pnl_field = "slug_pnl_so_far" if last_per_slug["slug_pnl_so_far"].abs().sum() > 0 else "pnl_calc"
        n_slugs = last_per_slug["slug"].nunique()
        # Count action events
        actions = df.action.value_counts().to_dict() if "action" in df.columns else {}
        # Fills (real trades)
        fills_df = df[df.get("fill_simulated", pd.Series([0]*len(df))) == 1] if "fill_simulated" in df.columns else df.iloc[:0]
        # Mode inference: if fill_simulated=0 everywhere → pure shadow; if some =1 → live with simulated fills? Check
        n_fill_sim = int((df.get("fill_simulated", pd.Series([0]*len(df))) == 1).sum())
        n_post = int(actions.get("POST_BID", 0) + actions.get("POST_ASK", 0))
        n_cancel = int(actions.get("CANCEL", 0))
        n_fill = int(actions.get("FILL", 0))
        n_merge = int(actions.get("MERGE", 0))
        n_take = int(actions.get("TAKE", 0))

        pnl_total = float(last_per_slug[pnl_field].sum())
        n_winners = int((last_per_slug[pnl_field] > 0).sum())
        wr = n_winners / max(n_slugs, 1) * 100

        rows.append(dict(
            sleeve=sleeve,
            n_slugs=n_slugs,
            n_winners=n_winners,
            wr_pct=round(wr, 2),
            pnl_total=round(pnl_total, 2),
            pnl_per_slug=round(pnl_total / max(n_slugs, 1), 4),
            n_post=n_post,
            n_cancel=n_cancel,
            n_fill=n_fill,
            n_merge=n_merge,
            n_take=n_take,
            n_log_rows=len(df),
            note="F7 N/A — pair-arb / mint-sell not directional",
        ))
    return pd.DataFrame(rows).sort_values("pnl_total", ascending=False)


# ---------------------------------------------------------------------------
# Render report
# ---------------------------------------------------------------------------

def render_report(vps3_tbl: pd.DataFrame, ireland_tbl: pd.DataFrame) -> str:
    L = ["# Momo VPS3 shadow + Ireland live sleeves — F7 RSI comparison — 2026-05-20\n",
         "**Data pulled fresh today**:",
         f"- VPS3 (`storedata-vps3`) momo events last 14d: {VPS3_FILE.name}",
         f"- Ireland VPS (`vps`) maker shadow CSVs (May 19-20): 5 sleeves\n",
         "## 1. VPS3 momo sleeves — current vs F7 vs F7_extreme\n",
         "Direct queries on `trading.events`. F7 = RSI(14) on binance 1m agrees with signal direction.\n"]

    # Aggregate VPS3
    cur_n = vps3_tbl.cur_n.sum()
    cur_w = vps3_tbl.cur_wins.sum()
    cur_pnl = vps3_tbl.cur_pnl.sum()
    f7_n = vps3_tbl.f7_n.sum()
    f7_w = vps3_tbl.f7_wins.sum()
    f7_pnl = vps3_tbl.f7_pnl.sum()
    f7x_n = vps3_tbl.f7x_n.sum()
    f7x_w = vps3_tbl.f7x_wins.sum()
    f7x_pnl = vps3_tbl.f7x_pnl.sum()

    L.append("### Aggregate (all momo sleeves)\n")
    L.append("| Config | n_trades | WR % | Sum PnL | $/trade |")
    L.append("|---|---:|---:|---:|---:|")
    L.append(f"| **Current production** | {cur_n:,} | {cur_w/max(cur_n,1)*100:.2f}% | ${cur_pnl:+,.2f} | ${cur_pnl/max(cur_n,1):.4f} |")
    L.append(f"| **+ F7 filter** | {f7_n:,} | {f7_w/max(f7_n,1)*100:.2f}% | ${f7_pnl:+,.2f} | ${f7_pnl/max(f7_n,1):.4f} |")
    L.append(f"| **+ F7_extreme** | {f7x_n:,} | {f7x_w/max(f7x_n,1)*100:.2f}% | ${f7x_pnl:+,.2f} | ${f7x_pnl/max(f7x_n,1):.4f} |")
    L.append(f"\n**Swing**: ${cur_pnl:+,.2f} → ${f7_pnl:+,.2f} = **${f7_pnl - cur_pnl:+,.2f}** improvement over 14d.")
    L.append(f"\n=> **~${(f7_pnl - cur_pnl)/14:+,.2f} / day** if F7 had been live.\n")

    L.append("### Per-sleeve detail (all momo, sorted by current PnL desc)\n")
    L.append("| sleeve_id | sym | tf | cur_n | cur_WR% | cur_PnL | f7_n | f7_WR% | f7_PnL | f7_Δ$ | f7x_WR% | f7x_PnL |")
    L.append("|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for _, r in vps3_tbl.iterrows():
        L.append(
            f"| {r.sleeve_id} | {r.symbol} | {r.tf} | "
            f"{r.cur_n:,} | {r.cur_wr_pct:.1f}% | ${r.cur_pnl:+,.0f} | "
            f"{r.f7_n:,} | {r.f7_wr_pct:.1f}% | ${r.f7_pnl:+,.0f} | "
            f"${r.f7_pnl_delta:+,.0f} | {r.f7x_wr_pct:.1f}% | ${r.f7x_pnl:+,.0f} |"
        )
    L.append("")

    L.append("### Top 15 sleeves by F7 PnL improvement\n")
    top = vps3_tbl.nlargest(15, "f7_pnl_delta")
    L.append("| sleeve_id | cur_n | cur_WR% | cur_PnL | f7_n | f7_WR% | f7_PnL | improvement |")
    L.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for _, r in top.iterrows():
        L.append(
            f"| {r.sleeve_id} | {r.cur_n:,} | {r.cur_wr_pct:.1f}% | ${r.cur_pnl:+,.0f} | "
            f"{r.f7_n:,} | {r.f7_wr_pct:.1f}% | ${r.f7_pnl:+,.0f} | "
            f"**${r.f7_pnl_delta:+,.0f}** |"
        )
    L.append("")

    L.append("### Sleeves where F7 HURTS (counter-examples)\n")
    hurt = vps3_tbl[vps3_tbl.f7_pnl_delta < -5].nsmallest(15, "f7_pnl_delta")
    if hurt.empty:
        L.append("None — F7 helps every momo sleeve or stays roughly neutral.\n")
    else:
        L.append("| sleeve_id | cur_n | cur_WR% | cur_PnL | f7_n | f7_WR% | f7_PnL | loss |")
        L.append("|---|---:|---:|---:|---:|---:|---:|---:|")
        for _, r in hurt.iterrows():
            L.append(
                f"| {r.sleeve_id} | {r.cur_n:,} | {r.cur_wr_pct:.1f}% | ${r.cur_pnl:+,.0f} | "
                f"{r.f7_n:,} | {r.f7_wr_pct:.1f}% | ${r.f7_pnl:+,.0f} | "
                f"**${r.f7_pnl_delta:+,.0f}** |"
            )
    L.append("")

    L.append("## 2. Ireland VPS maker sleeves (May 19-20 data)\n")
    L.append("These are PAT/ACC-M/MAS strategies — NOT directional. F7 RSI filter does not apply directly. Reporting current per-slug PnL aggregates.\n")
    L.append("| sleeve | n_slugs | n_winners | WR % | Sum PnL | $/slug | n_POST | n_FILL | n_MERGE | n_TAKE | n_log | F7 note |")
    L.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for _, r in ireland_tbl.iterrows():
        L.append(
            f"| {r.sleeve} | {r.n_slugs} | {r.n_winners} | "
            f"{r.wr_pct:.1f}% | ${r.pnl_total:+,.2f} | ${r.pnl_per_slug:+.4f} | "
            f"{r.n_post:,} | {r.n_fill:,} | {r.n_merge:,} | {r.n_take:,} | "
            f"{r.n_log_rows:,} | {r.note} |"
        )
    L.append("")

    L.append("### Why F7 doesn't apply to Ireland sleeves\n")
    L.append("F7 filter requires a directional signal (UP/DOWN) to filter by RSI agreement:")
    L.append("- `acc-m`: posts BIDs on BOTH sides when `sum_bids < $1` — NOT directional")
    L.append("- `acc-h`: composite taker with 4 sub-rules (discount-capture, sharp-drop, early-slot, buy-pressure) — only ACC-H's `buy_pressure` sub-rule has direction inherent")
    L.append("- `acc-pc`: pair-completion taker, reacts to OWN inventory imbalance — semi-directional but signal is from book, not market direction")
    L.append("- `mas`: mint-and-sell, posts ASKs both sides after minting — NOT directional")
    L.append("- `pat-shadow`: pure pair-arb taker, fires when sum_asks < $1 — NOT directional\n")
    L.append("To apply F7 to ANY of these, we'd need to:")
    L.append("1. Pick a synthetic 'signal direction' (e.g. side with higher RSI)")
    L.append("2. Skip fires where RSI disagrees with that synthetic signal\n")
    L.append("This is a research experiment, NOT the F7 the user asked about. The F7 alpha demonstrated on momo paper data (74% WR) is specific to **directional bets**. Ireland's maker bots don't make directional bets.\n")

    L.append("## 3. Summary recommendation\n")
    L.append("**Momo on VPS3 (directional)**: Apply F7 filter immediately. Expected lift: see Section 1 aggregate.")
    L.append("- Add `rsi_14_at_ws` to the momo signal payload (computed at fire time)")
    L.append("- Filter: skip fire if `(signal==UP and rsi<50) or (signal==DOWN and rsi>50)`")
    L.append("- Test variants:")
    L.append("  - F7: `rsi >= 50` agreement → biggest universe")
    L.append("  - F7_extreme: `rsi >= 60 / <= 40` → smaller universe, higher WR\n")
    L.append("**Ireland maker bots (non-directional)**: F7 not applicable. Use the existing shadow data to validate the recent maker bot deployment instead. Separate analysis stream.\n")

    L.append("## 4. Files\n")
    L.append(f"- `{OUT_DIR / 'momo_live_vs_f7.csv'}` — VPS3 per-sleeve table")
    L.append(f"- `{OUT_DIR / 'ireland_live_sleeves.csv'}` — Ireland per-sleeve table")
    L.append(f"- `{VPS3_FILE}` — raw 159k VPS3 momo events (signal + resolution + hedge_skip)")
    L.append(f"- `{IRELAND_DIR}/*.csv` — raw Ireland maker shadow CSVs\n")

    return "\n".join(L)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("[1] Loading VPS3 momo events ...")
    df = load_vps3_momo()
    n_sig = (df.kind == "poly_updown_signal").sum()
    n_res = (df.kind == "poly_updown_resolution").sum()
    print(f"    {len(df):,} rows total — {n_sig:,} signals, {n_res:,} resolutions")
    print(f"    sleeves: {df.sleeve_id.nunique()}, modes: {df['mode'].value_counts().to_dict()}")

    print("[2] Attaching RSI ...")
    df = attach_rsi(df)
    res_with_rsi = ((df.kind == "poly_updown_resolution") & df.rsi_14.notna()).sum()
    print(f"    Resolutions with RSI: {res_with_rsi:,}")

    print("[3] Building VPS3 per-sleeve table ...")
    vps3_tbl = vps3_per_sleeve(df)
    vps3_tbl.to_csv(OUT_DIR / "momo_live_vs_f7.csv", index=False)
    print(f"    Wrote {OUT_DIR / 'momo_live_vs_f7.csv'} ({len(vps3_tbl)} sleeves)")

    print("[4] Building Ireland maker sleeves table ...")
    ireland_tbl = ireland_per_sleeve()
    ireland_tbl.to_csv(OUT_DIR / "ireland_live_sleeves.csv", index=False)
    print(f"    Wrote {OUT_DIR / 'ireland_live_sleeves.csv'} ({len(ireland_tbl)} sleeves)")

    print("[5] Writing report ...")
    REPORT.write_text(render_report(vps3_tbl, ireland_tbl), encoding="utf-8")
    print(f"    Wrote {REPORT}")

    print()
    print("=" * 100)
    print("AGGREGATE — VPS3 momo (14d production)")
    print("=" * 100)
    cur_n = vps3_tbl.cur_n.sum()
    cur_w = vps3_tbl.cur_wins.sum()
    cur_pnl = vps3_tbl.cur_pnl.sum()
    f7_n = vps3_tbl.f7_n.sum()
    f7_w = vps3_tbl.f7_wins.sum()
    f7_pnl = vps3_tbl.f7_pnl.sum()
    print(f"  Current: n={cur_n:,}  WR={cur_w/max(cur_n,1)*100:.2f}%  Sum=${cur_pnl:+,.2f}")
    print(f"  + F7:    n={f7_n:,}  WR={f7_w/max(f7_n,1)*100:.2f}%  Sum=${f7_pnl:+,.2f}")
    print(f"  Swing:   ${f7_pnl - cur_pnl:+,.2f} = ${(f7_pnl - cur_pnl)/14:+,.2f}/day")
    print()
    print("Top 10 VPS3 momo sleeves by F7 improvement:")
    print(vps3_tbl.nlargest(10, "f7_pnl_delta")[
        ["sleeve_id", "cur_n", "cur_wr_pct", "cur_pnl",
         "f7_n", "f7_wr_pct", "f7_pnl", "f7_pnl_delta"]].to_string(index=False))
    print()
    print("Ireland maker sleeves (current state, F7 N/A):")
    print(ireland_tbl[["sleeve", "n_slugs", "n_winners", "wr_pct",
                       "pnl_total", "pnl_per_slug", "n_fill", "n_merge"]].to_string(index=False))


if __name__ == "__main__":
    main()
