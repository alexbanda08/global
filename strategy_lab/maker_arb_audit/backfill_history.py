"""
backfill_history.py — recompute REAL PnL over the FULL shadow history by
reprocessing the recorded fills through the corrected (post-fix) settlement.

We do NOT re-run the live engine. The E1 bug was purely in settlement/marking;
the recorded fills/merges/redeems (and thus realized cash) were always correct.
So real PnL = realized cash + settle any leftover residual at the chainlink
outcome (winner residual → $1, loser → $0).

Settlement source per slug (priority):
  1. chainlink outcome from canonical resolutions_from_rtds (covers May 25-28).
     real = realized_cash + (inv_up if Up else inv_dn).  Works whether or not the
     engine already redeemed the winner (redeemed side already has inv=0 → +0).
  2. else if engine already settled it (inv_up==inv_dn==0, i.e. post-fix EXPIRE/
     REDEEM on May 29): real = realized_cash (final).
  3. else: uncovered (genuinely in-flight at snapshot edge, or a canonical gap).

`realized_cash = cash_received + cash_recovered - cash_spent` — pure cash, NO
rebates/taker_fees (those used the wrong per-fill fee model; this matches the
dashboard "REAL PnL"). A winner-only 2%-on-profit overlay is reported separately.

Contrast columns:
  real_mean       — corrected, uncensored (the truth)
  old_settled_mean— what the OLD buggy reporting showed (mean slug_pnl_so_far over
                    inv==0 slugs only = the survivorship-biased number)

Usage: py -X utf8 strategy_lab/maker_arb_audit/backfill_history.py
"""
from __future__ import annotations
import sys, glob
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
from load import load_resolutions  # noqa: E402

CSV_DIR = ROOT / "migration_ireland_recheck_2026_05_29" / "maker_csvs"
OUT = ROOT / "strategy_lab" / "maker_arb_audit" / "_results"
OUT.mkdir(parents=True, exist_ok=True)

EPS = 1e-6
NUM = ["inv_up", "inv_dn", "cash_spent", "cash_received", "cash_recovered",
       "rebates", "taker_fees", "slug_pnl_so_far"]
PREFIXES = ["acc-m", "acc-m-v2", "acc-h", "acc-h-v2",
            "acc-pc", "acc-pc-v2", "mas", "mas-v2"]


def winsec(s): return 300 if "-5m-" in s else 900
def slotend_us(s): return (int(s.rsplit("-", 1)[1]) + winsec(s)) * 1_000_000


def load_prefix(pfx):
    fs = sorted(glob.glob(str(CSV_DIR / f"{pfx}_2026-05-*.csv")))
    if not fs:
        return None
    df = pd.concat([pd.read_csv(f, engine="python", on_bad_lines="skip") for f in fs],
                   ignore_index=True)
    for c in NUM:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    df["fill_simulated"] = pd.to_numeric(df["fill_simulated"], errors="coerce").fillna(0).astype(int)
    df["ts_us"] = pd.to_numeric(df["ts_us"], errors="coerce")
    df["action"] = df["action"].astype(str).str.upper().str.strip()
    return df


def ci95(x):
    n = len(x)
    if n == 0: return (np.nan, np.nan, np.nan)
    m = float(np.mean(x))
    if n == 1: return (m, np.nan, np.nan)
    se = float(np.std(x, ddof=1)) / np.sqrt(n)
    return (m, m - 1.96 * se, m + 1.96 * se)


def main():
    res = load_resolutions()[["slug", "outcome"]].drop_duplicates("slug")
    out_map = dict(zip(res.slug, res.outcome))

    per_slug = []
    for pfx in PREFIXES:
        df = load_prefix(pfx)
        if df is None or "sleeve_id" not in df.columns:
            continue
        for slv, sub in df.groupby("sleeve_id"):
            sim = sub[sub.fill_simulated == 1]
            if sim.empty:
                continue
            now = int(sim.ts_us.max())
            for slug, g in sim.groupby("slug"):
                g = g.sort_values("ts_us"); last = g.iloc[-1]
                iu, idn = float(last.inv_up), float(last.inv_dn)
                realized = float(last.cash_received) + float(last.cash_recovered) - float(last.cash_spent)
                inv0 = abs(iu) < EPS and abs(idn) < EPS
                nf = int((g.action == "FILL").sum()); nm = int((g.action == "MINT").sum())
                active = nf > 0 or nm > 0
                o = out_map.get(slug)
                if o in ("Up", "Down"):
                    redemption = iu if o == "Up" else idn
                    real = realized + redemption
                    src = "chainlink"
                elif inv0:
                    real = realized
                    src = "engine_settled"
                else:
                    real = np.nan
                    src = "uncovered"
                # winner-only 2%-on-profit overlay (true-live fee estimate)
                win_qty = (iu if (o == "Up") else idn) if o in ("Up", "Down") else 0.0
                per_slug.append(dict(
                    sleeve=slv.replace("poly_", "").replace("_shadow", ""),
                    slug=slug, version=("v2" if "-v2" in pfx else "v1"),
                    realized=realized, real=real, src=src, active=active,
                    inv0=inv0, eng_pnl=float(last.slug_pnl_so_far),
                    elapsed=now >= slotend_us(slug)))
    ps = pd.DataFrame(per_slug)
    ps.to_csv(OUT / "backfill_per_slug.csv", index=False)

    rows = []
    for slv, g in ps.groupby("sleeve"):
        a = g[g.active]
        counted = a[a.real.notna()]
        x = counted.real.to_numpy()
        m, lo, hi = ci95(x)
        old = a[a.inv0]   # OLD buggy view = settled-only (inv==0), biased high
        rows.append(dict(
            sleeve=slv,
            days=("v2:3" if "v2" in slv else "v1:5"),
            n_counted=len(counted),
            n_uncov=int((a.src == "uncovered").sum()),
            win=round(100 * (x > 0).mean(), 1) if len(x) else np.nan,
            real_mean=round(m, 3),
            ci_lo=round(lo, 3), ci_hi=round(hi, 3),
            real_total=round(float(np.nansum(x)), 1),
            old_settled_mean=round(float(old.eng_pnl.mean()), 3) if len(old) else np.nan,
            old_n=len(old)))
    summ = pd.DataFrame(rows).sort_values("real_mean", ascending=False)
    summ.to_csv(OUT / "backfill_summary.csv", index=False)

    pd.set_option("display.width", 220); pd.set_option("display.max_columns", 30)
    print("=" * 120)
    print("FULL-HISTORY REAL PnL BACKFILL (recorded fills reprocessed through corrected settlement)")
    print("=" * 120)
    print(summ.to_string(index=False))
    print()
    tot = ps[ps.active & ps.real.notna()]
    print(f"total counted slugs: {len(tot)}   uncovered (in-flight/gap): {int((ps.active & (ps.src=='uncovered')).sum())}")
    print(f"GRAND TOTAL real PnL across all sleeves: ${tot.real.sum():+.2f}")
    print()
    print("real_mean        = corrected uncensored PnL (= dashboard 'REAL PnL'), pure realized cash + chainlink residual settle")
    print("old_settled_mean = the OLD buggy reporting (mean slug_pnl_so_far over inv==0 slugs only = survivorship-biased)")
    print(f"wrote {OUT/'backfill_summary.csv'} + backfill_per_slug.csv")


if __name__ == "__main__":
    main()
