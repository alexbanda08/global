"""
clean_settled_audit.py — authoritative per-slug PnL for the maker-arb sleeves
using the FULLY-SETTLED measure (the only unbiased slice, see
MAKER_ARB_CONTEXT_HANDOFF_2026_05_28.md §3).

Three ways to slice per-slug PnL diverge badly:
  1. REDEEM-slugs only        -> biased HIGH (only counts slugs where leftover
                                  directional inventory won; ACC-M merges most
                                  pairs mid-slug so most slugs never REDEEM).
  2. All traded slugs, cash   -> biased LOW (right-censored: recent slugs still
                                  hold residual inventory whose redemption is not
                                  yet in the captured CSV).
  3. Fully-settled slugs      -> CLEAN, uncensored. A slug is fully settled when
     (final inv_up == inv_dn == 0)  its window has elapsed AND its final
                                  inventory is zero (engine already merged/
                                  redeemed everything). Its slug_pnl_so_far is
                                  the final realized cash. THIS is what we report.

Engine accounting is verified exact (per_slug_recon.py: 10 slugs reconcile to
$0.000000), so we trust slug_pnl_so_far as the per-slug realized PnL and
cross-check it against the cumulative-cash formula.

Outputs:
  _results/clean_settled_per_slug.csv   — every slug with its classification
  _results/clean_settled_summary.csv    — per-sleeve clean table
  prints a compact summary (the authoritative replacement for handoff §2).

Usage:
  py -X utf8 strategy_lab/maker_arb_audit/clean_settled_audit.py
"""
from __future__ import annotations
import glob
import os
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
CSV_DIR = ROOT / "migration_ireland_audit_2026_05_28" / "maker_csvs"
OUT_DIR = ROOT / "strategy_lab" / "maker_arb_audit" / "_results"
OUT_DIR.mkdir(parents=True, exist_ok=True)

INV_EPS = 1e-6  # |inventory| below this counts as settled (engine logs exact 0)

NUMCOLS = ["price", "size", "inv_up", "inv_dn", "cash_spent", "cash_received",
           "cash_recovered", "rebates", "taker_fees", "slug_pnl_so_far",
           "slug_offset_s"]

# V1 = control, V2 = fixed (PAT off + convergence-cancel + eth_15m).
PREFIXES = ["acc-m", "acc-m-v2", "acc-h", "acc-h-v2",
            "acc-pc", "acc-pc-v2", "mas", "mas-v2"]


def window_s(slug: str) -> int:
    return 300 if "-5m-" in slug else 900


def slot_start_s(slug: str) -> int:
    return int(slug.rsplit("-", 1)[1])


def slot_end_us(slug: str) -> int:
    return (slot_start_s(slug) + window_s(slug)) * 1_000_000


def load_prefix(prefix: str) -> pd.DataFrame | None:
    files = sorted(CSV_DIR.glob(f"{prefix}_2026*.csv"))
    if not files:
        return None
    parts = []
    for f in files:
        d = pd.read_csv(f, engine="python", on_bad_lines="skip")
        d["__srcfile"] = os.path.basename(f)
        parts.append(d)
    df = pd.concat(parts, ignore_index=True)
    for c in NUMCOLS:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    df["fill_simulated"] = (pd.to_numeric(df["fill_simulated"], errors="coerce")
                            .fillna(0).astype(int))
    df["ts_us"] = pd.to_numeric(df["ts_us"], errors="coerce")
    df["action"] = df["action"].astype(str).str.upper().str.strip()
    return df


def classify_slugs(df: pd.DataFrame, sleeve_id: str) -> pd.DataFrame:
    """One row per slug for a sleeve, with settlement classification."""
    sub = df[df["sleeve_id"] == sleeve_id]
    sim = sub[sub["fill_simulated"] == 1]
    if sim.empty:
        return pd.DataFrame()

    now_us = int(sim["ts_us"].max())  # snapshot horizon = latest captured event
    rows = []
    for slug, g in sim.groupby("slug"):
        g = g.sort_values("ts_us")
        last = g.iloc[-1]
        inv_up = float(last["inv_up"])
        inv_dn = float(last["inv_dn"])
        # engine running pnl (verified exact)
        pnl_eng = float(last["slug_pnl_so_far"])
        # independent cash-formula cross-check off the same last row
        pnl_cash = (float(last["cash_received"]) + float(last["cash_recovered"])
                    - float(last["cash_spent"]) + float(last["rebates"])
                    - float(last["taker_fees"]))
        settled = (abs(inv_up) < INV_EPS) and (abs(inv_dn) < INV_EPS)
        elapsed = now_us >= slot_end_us(slug)
        n_src = sub[sub["slug"] == slug]["__srcfile"].nunique()
        has_redeem = "REDEEM" in sub[sub["slug"] == slug]["action"].values
        n_fills = int((g["action"] == "FILL").sum())
        if settled:
            cls = "settled"
        elif elapsed:
            cls = "residual_open"   # window over, inv != 0 -> censored, recoverable
        else:
            cls = "inflight"        # window not yet elapsed
        rows.append({
            "sleeve_id": sleeve_id, "slug": slug,
            "asset": str(last.get("asset", "")), "tf": str(last.get("tf", "")),
            "pnl_eng": pnl_eng, "pnl_cash": pnl_cash,
            "pnl_recon_err": abs(pnl_eng - pnl_cash),
            "inv_up": inv_up, "inv_dn": inv_dn,
            "n_fills": n_fills, "has_redeem": has_redeem,
            "class": cls, "cross_file": n_src > 1,
        })
    return pd.DataFrame(rows)


def ci95(x: np.ndarray):
    n = len(x)
    if n == 0:
        return (np.nan, np.nan, np.nan)
    m = float(np.mean(x))
    if n == 1:
        return (m, np.nan, np.nan)
    se = float(np.std(x, ddof=1)) / np.sqrt(n)
    return (m, m - 1.96 * se, m + 1.96 * se)


def main():
    per_slug = []
    for prefix in PREFIXES:
        df = load_prefix(prefix)
        if df is None:
            continue
        if "sleeve_id" not in df.columns:
            continue
        for sleeve in sorted(df["sleeve_id"].dropna().unique()):
            cs = classify_slugs(df, sleeve)
            if not cs.empty:
                cs.insert(0, "prefix", prefix)
                per_slug.append(cs)

    if not per_slug:
        print("NO DATA")
        return

    allslug = pd.concat(per_slug, ignore_index=True)
    allslug.to_csv(OUT_DIR / "clean_settled_per_slug.csv", index=False)

    # recon error on the COUNTED population only (settled+active). Open/inflight
    # slugs carry unredeemed inventory the naive cash formula can't mark, so a
    # global max-err is misleading — those are excluded from the clean measure.
    counted_mask = (allslug["class"] == "settled") & (allslug["n_fills"] > 0)
    recon_max = float(allslug.loc[counted_mask, "pnl_recon_err"].max()) if counted_mask.any() else 0.0
    n_xfile = int(allslug["cross_file"].sum())

    summ = []
    for sleeve, g in allslug.groupby("sleeve_id"):
        settled = g[g["class"] == "settled"]
        # CLEAN measure = settled AND active (strategy actually took a position).
        # A slug where nothing ever filled is a no-op, not a settled trade —
        # counting it dilutes the edge toward zero (esp. MAS gated sleeves).
        active = settled[settled["n_fills"] > 0]
        resid = g[g["class"] == "residual_open"]
        inflight = g[g["class"] == "inflight"]
        pnl = active["pnl_eng"].to_numpy()
        m, lo, hi = ci95(pnl)
        # biased measures, for contrast (the wrong ways), on active slugs only
        g_active = g[g["n_fills"] > 0]
        redeem_only = g_active[g_active["has_redeem"]]["pnl_eng"]
        all_cash = g_active["pnl_eng"]   # all active traded slugs incl censored residual
        summ.append({
            "sleeve_id": sleeve,
            "n_settled": len(active),       # settled & active = clean n
            "n_noop": int((settled["n_fills"] == 0).sum()),
            "win_pct": (100.0 * (pnl > 0).mean()) if len(pnl) else np.nan,
            "mean_clean": m, "ci_lo": lo, "ci_hi": hi,
            "median_clean": float(np.median(pnl)) if len(pnl) else np.nan,
            "total_clean": float(pnl.sum()) if len(pnl) else 0.0,
            "n_resid_open": len(resid),     # censored, recoverable via canonical
            "n_inflight": len(inflight),
            "biased_redeem_only_mean": (float(redeem_only.mean())
                                        if len(redeem_only) else np.nan),
            "biased_allcash_mean": (float(all_cash.mean())
                                    if len(all_cash) else np.nan),
        })
    summ = pd.DataFrame(summ).sort_values("mean_clean", ascending=False)
    summ.to_csv(OUT_DIR / "clean_settled_summary.csv", index=False)

    pd.set_option("display.width", 240)
    pd.set_option("display.max_columns", 30)

    print("=" * 110)
    print("CLEAN FULLY-SETTLED AUDIT  (measure #3: final inv_up==inv_dn==0)")
    print("=" * 110)
    print(f"engine pnl recon max-err on COUNTED slugs : ${recon_max:.6f}"
          f"   (settled+active; cross-file flagged: {n_xfile})")
    print("clean measure = settled (final inv=0) AND active (>=1 fill). "
          "no-op slugs excluded.")
    print()
    show = summ.copy()
    for c in ["mean_clean", "ci_lo", "ci_hi", "median_clean", "total_clean",
              "biased_redeem_only_mean", "biased_allcash_mean"]:
        show[c] = show[c].map(lambda v: f"{v:+.3f}" if pd.notna(v) else "  -")
    show["win_pct"] = show["win_pct"].map(lambda v: f"{v:.1f}%" if pd.notna(v) else "-")
    print(show.to_string(index=False))

    print()
    print("CENSORING SUMMARY (does canonical refresh add much?):")
    tot_settled = int(summ["n_settled"].sum())
    tot_resid = int(summ["n_resid_open"].sum())
    tot_inflight = int(summ["n_inflight"].sum())
    print(f"  settled (clean, counted)        : {tot_settled}")
    print(f"  residual_open (recoverable)     : {tot_resid}  "
          f"<- canonical-refresh target")
    print(f"  inflight (window not elapsed)   : {tot_inflight}")
    print()
    print(f"wrote {OUT_DIR / 'clean_settled_per_slug.csv'}")
    print(f"wrote {OUT_DIR / 'clean_settled_summary.csv'}")


if __name__ == "__main__":
    main()
