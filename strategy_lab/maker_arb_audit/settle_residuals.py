"""
settle_residuals.py — recover the right-censored maker-arb slugs.

After the 2026-05-28 canonical refresh, resolutions_from_rtds covers May 28, so
the residual_open slugs (window elapsed, engine hadn't booked REDEEM in our CSV
snapshot) can be settled against independent chainlink truth:

    settled_pnl = realized_cash + redemption
    realized_cash = cash_received + cash_recovered - cash_spent + rebates - taker_fees   (last sim row)
    redemption    = inv_up * $1  if outcome == 'Up'   else inv_dn * $1   (losing side pays $0)

This converts ~476 censored slugs into clean settled observations, ~doubling n
on the 15m sleeves and tightening the CIs.

Also performs an INDEPENDENT CROSS-CHECK: for slugs the engine already settled
(REDEEM booked), the REDEEM side is the engine's winning side. We compare it to
the chainlink outcome from resolutions_from_rtds. Agreement validates both the
outcome lookup and that the Ireland engine resolves identically to canonical.

Outputs:
  _results/settled_combined_per_slug.csv
  _results/settled_combined_summary.csv
  prints the larger-n authoritative table + cross-check agreement.

Usage:
  py -X utf8 strategy_lab/maker_arb_audit/settle_residuals.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
from load import load_resolutions  # noqa: E402

CSV_DIR = ROOT / "migration_ireland_audit_2026_05_28" / "maker_csvs"
OUT_DIR = ROOT / "strategy_lab" / "maker_arb_audit" / "_results"
OUT_DIR.mkdir(parents=True, exist_ok=True)

INV_EPS = 1e-6
NUMCOLS = ["price", "size", "inv_up", "inv_dn", "cash_spent", "cash_received",
           "cash_recovered", "rebates", "taker_fees", "slug_pnl_so_far"]
PREFIXES = ["acc-m", "acc-m-v2", "acc-h", "acc-h-v2",
            "acc-pc", "acc-pc-v2", "mas", "mas-v2"]


def window_s(slug): return 300 if "-5m-" in slug else 900
def slot_start_s(slug): return int(slug.rsplit("-", 1)[1])
def slot_end_us(slug): return (slot_start_s(slug) + window_s(slug)) * 1_000_000


def load_prefix(prefix):
    files = sorted(CSV_DIR.glob(f"{prefix}_2026*.csv"))
    if not files:
        return None
    df = pd.concat([pd.read_csv(f, engine="python", on_bad_lines="skip") for f in files],
                   ignore_index=True)
    for c in NUMCOLS:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    df["fill_simulated"] = pd.to_numeric(df["fill_simulated"], errors="coerce").fillna(0).astype(int)
    df["ts_us"] = pd.to_numeric(df["ts_us"], errors="coerce")
    df["action"] = df["action"].astype(str).str.upper().str.strip()
    df["side"] = df["side"].astype(str).str.lower().str.strip()
    return df


def per_slug(df, sleeve):
    sub = df[df["sleeve_id"] == sleeve]
    sim = sub[sub["fill_simulated"] == 1]
    if sim.empty:
        return pd.DataFrame()
    now_us = int(sim["ts_us"].max())
    rows = []
    for slug, g in sim.groupby("slug"):
        g = g.sort_values("ts_us")
        last = g.iloc[-1]
        inv_up, inv_dn = float(last["inv_up"]), float(last["inv_dn"])
        pnl_eng = float(last["slug_pnl_so_far"])
        pnl_cash = (float(last["cash_received"]) + float(last["cash_recovered"])
                    - float(last["cash_spent"]) + float(last["rebates"])
                    - float(last["taker_fees"]))
        settled = abs(inv_up) < INV_EPS and abs(inv_dn) < INV_EPS
        elapsed = now_us >= slot_end_us(slug)
        n_fills = int((g["action"] == "FILL").sum())
        redeem_rows = g[g["action"] == "REDEEM"]
        redeem_side = (redeem_rows.iloc[-1]["side"] if len(redeem_rows) else "")
        cls = "settled" if settled else ("residual_open" if elapsed else "inflight")
        rows.append(dict(sleeve_id=sleeve, slug=slug,
                         inv_up=inv_up, inv_dn=inv_dn,
                         pnl_eng=pnl_eng, pnl_cash=pnl_cash,
                         n_fills=n_fills, cls=cls, redeem_side=redeem_side))
    return pd.DataFrame(rows)


def ci95(x):
    n = len(x)
    if n == 0: return (np.nan, np.nan, np.nan)
    m = float(np.mean(x))
    if n == 1: return (m, np.nan, np.nan)
    se = float(np.std(x, ddof=1)) / np.sqrt(n)
    return (m, m - 1.96 * se, m + 1.96 * se)


def main():
    parts = []
    for prefix in PREFIXES:
        df = load_prefix(prefix)
        if df is None or "sleeve_id" not in df.columns:
            continue
        for sleeve in sorted(df["sleeve_id"].dropna().unique()):
            ps = per_slug(df, sleeve)
            if not ps.empty:
                parts.append(ps)
    allslug = pd.concat(parts, ignore_index=True)

    # chainlink outcomes
    res = load_resolutions()[["slug", "outcome"]].drop_duplicates("slug")
    out_map = dict(zip(res.slug, res.outcome))
    allslug["chainlink_outcome"] = allslug["slug"].map(out_map)

    # ---- independent cross-check: engine REDEEM side vs chainlink outcome ----
    side2out = {"up": "Up", "dn": "Down"}
    chk = allslug[(allslug.cls == "settled") & (allslug.n_fills > 0)
                  & (allslug.redeem_side.isin(side2out))
                  & (allslug.chainlink_outcome.notna())].copy()
    chk["engine_out"] = chk["redeem_side"].map(side2out)
    agree = (chk["engine_out"] == chk["chainlink_outcome"]).mean() if len(chk) else np.nan
    n_chk = len(chk)

    # ---- settlement of residual_open (active, covered) ----
    def settle_row(r):
        o = r["chainlink_outcome"]
        if r["cls"] == "settled":
            return r["pnl_eng"]            # already final
        if r["cls"] == "residual_open" and o in ("Up", "Down") and r["n_fills"] > 0:
            redemption = r["inv_up"] if o == "Up" else r["inv_dn"]
            return r["pnl_cash"] + redemption
        return np.nan

    allslug["final_pnl"] = allslug.apply(settle_row, axis=1)
    allslug["counted"] = allslug["final_pnl"].notna() & (allslug["n_fills"] > 0)
    allslug["recovered"] = (allslug["cls"] == "residual_open") & allslug["counted"]
    allslug.to_csv(OUT_DIR / "settled_combined_per_slug.csv", index=False)

    summ = []
    for sleeve, g in allslug.groupby("sleeve_id"):
        c = g[g["counted"]]
        pnl = c["final_pnl"].to_numpy()
        m, lo, hi = ci95(pnl)
        summ.append(dict(sleeve_id=sleeve, n=len(c),
                         n_orig_settled=int(((g.cls == "settled") & (g.n_fills > 0)).sum()),
                         n_recovered=int(g["recovered"].sum()),
                         win_pct=(100 * (pnl > 0).mean()) if len(pnl) else np.nan,
                         mean=m, ci_lo=lo, ci_hi=hi,
                         median=float(np.median(pnl)) if len(pnl) else np.nan,
                         total=float(pnl.sum()) if len(pnl) else 0.0,
                         still_censored=int(((g.cls == "residual_open") & (~g.counted) & (g.n_fills > 0)).sum())))
    summ = pd.DataFrame(summ).sort_values("mean", ascending=False)
    summ.to_csv(OUT_DIR / "settled_combined_summary.csv", index=False)

    pd.set_option("display.width", 240); pd.set_option("display.max_columns", 30)
    print("=" * 115)
    print("SETTLED-COMBINED AUDIT (original settled + chainlink-settled residuals)  POST_SIZE=20")
    print("=" * 115)
    print(f"independent cross-check: engine REDEEM side vs chainlink outcome "
          f"= {agree*100:.2f}% agree on n={n_chk} settled slugs")
    print()
    show = summ.copy()
    for col in ["mean", "ci_lo", "ci_hi", "median", "total"]:
        show[col] = show[col].map(lambda v: f"{v:+.3f}" if pd.notna(v) else "  -")
    show["win_pct"] = show["win_pct"].map(lambda v: f"{v:.1f}%" if pd.notna(v) else "-")
    print(show.to_string(index=False))
    print()
    print(f"total counted slugs: {int(summ['n'].sum())}  "
          f"(orig settled {int(summ['n_orig_settled'].sum())} + recovered {int(summ['n_recovered'].sum())})  "
          f"still censored: {int(summ['still_censored'].sum())}")
    print(f"wrote {OUT_DIR/'settled_combined_summary.csv'}")


if __name__ == "__main__":
    main()
