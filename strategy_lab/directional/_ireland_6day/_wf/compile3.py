import json, sys
import pandas as pd
import numpy as np

DIR = r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\directional\_ireland_6day"
NEW_CUT = pd.Timestamp("2026-07-10 20:00:00+00:00")

def load_tsv(fn):
    rows = []
    with open(fn, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            parts = line.split("\t", 2)
            if len(parts) != 3:
                continue
            at, sleeve, data = parts
            try:
                d = json.loads(data)
            except Exception:
                continue
            d["_at"] = pd.Timestamp(at)
            d["_sleeve"] = sleeve
            rows.append(d)
    return pd.DataFrame(rows)

def boot_ci(x, n=10000, seed=0):
    x = np.asarray(x, dtype=float)
    if len(x) == 0:
        return (np.nan, np.nan)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(x), size=(n, len(x)))
    means = x[idx].mean(axis=1)
    return (np.percentile(means, 2.5), np.percentile(means, 97.5))

def ex_top2(x):
    x = np.asarray(x, dtype=float)
    if len(x) <= 2:
        return np.nan
    srt = np.sort(x)[::-1]
    return srt[2:].mean()

# ---------- LADDER ----------
lad = load_tsv(f"{DIR}/ladder_all_refresh3.tsv")
print(f"LADDER rows: {len(lad)}  max_at={lad['_at'].max() if len(lad) else 'NA'}")

lad_settled = lad[lad["total_net_usd"].notna()].copy() if "total_net_usd" in lad.columns else pd.DataFrame()

def summarize_ladder(df, label):
    out = []
    for sleeve, g in df.groupby("_sleeve"):
        x = g["total_net_usd"].dropna().values
        if len(x) == 0:
            continue
        n = len(x)
        mean = x.mean()
        lo, hi = boot_ci(x)
        ex2 = ex_top2(x)
        med = np.median(x)
        pct_pos = (x > 0).mean() * 100
        days = max((g["_at"].max() - g["_at"].min()).total_seconds() / 86400, 1e-9)
        per_day = x.sum() / days if days > 0 else np.nan
        # decomp
        decomp = {}
        for col in ["paired_pnl_locked_usd", "rebate_usd", "residual_pnl_usd", "net_paired_estimate_usd"]:
            if col in g.columns:
                decomp[col] = g[col].dropna().mean()
        out.append(dict(period=label, sleeve=sleeve, n=n, mean=mean, ci_lo=lo, ci_hi=hi,
                         ex_top2=ex2, median=med, pct_pos=pct_pos, per_day=per_day, **decomp))
    return pd.DataFrame(out)

if len(lad_settled):
    full = summarize_ladder(lad_settled, "FULL")
    new = summarize_ladder(lad_settled[lad_settled["_at"] > NEW_CUT], "NEW")
    ladder_summary = pd.concat([full, new], ignore_index=True)
    print("\n=== LADDER SUMMARY ===")
    print(ladder_summary.round(3).to_string(index=False))

# trust checks: reconciliation
def trust_ladder(df):
    if "total_net_usd" not in df.columns:
        return
    recon_cols = ["paired_pnl_locked_usd", "rebate_usd", "residual_pnl_usd"]
    have = [c for c in recon_cols if c in df.columns]
    tmp = df.copy()
    for c in recon_cols:
        if c not in tmp.columns:
            tmp[c] = 0.0
    tmp = tmp.fillna(0.0)
    # coc terms may not exist; check columns
    coc_cut = tmp["coc_cut_usd"] if "coc_cut_usd" in tmp.columns else 0.0
    coc_taker = tmp["coc_taker_usd"] if "coc_taker_usd" in tmp.columns else 0.0
    recon = tmp["paired_pnl_locked_usd"] + tmp["rebate_usd"] + tmp["residual_pnl_usd"]
    if not isinstance(coc_cut, float):
        recon = recon - coc_cut
    if not isinstance(coc_taker, float):
        recon = recon - coc_taker
    diff = (tmp["total_net_usd"] - recon).abs()
    print(f"\nLADDER trust: max|recon diff| = {diff.max():.4f}  (n={len(diff)})")

trust_ladder(lad_settled)

# outcome_binance mismatch (if column exists)
if "outcome_binance" in lad.columns and "outcome" in lad.columns:
    mism = (lad["outcome_binance"].notna() & (lad["outcome_binance"] != lad["outcome"])).mean()
    print(f"LADDER outcome_binance mismatch rate: {mism:.4f}")
else:
    print("LADDER: no outcome_binance column present (skip mismatch check)")

# unsettled > 1h : rows with total_net_usd null and _at older than 1h ago
if "total_net_usd" in lad.columns:
    now = lad["_at"].max()
    unresolved = lad[lad["total_net_usd"].isna()]
    stale = unresolved[(now - unresolved["_at"]).dt.total_seconds() > 3600]
    print(f"LADDER unsettled>1h: {len(stale)} rows")

# live mode check
for col_check_df, name in [(lad, "LADDER")]:
    if "mode" in col_check_df.columns:
        nlive = (col_check_df["mode"] == "live").sum()
        print(f"{name} mode=live rows: {nlive}")
    else:
        print(f"{name}: no 'mode' field in ladder_summary payload")

# emission gap check
print("\n=== LADDER emission gap check (>2h) per sleeve ===")
for sleeve, g in lad.groupby("_sleeve"):
    ts = g["_at"].sort_values()
    gaps = ts.diff().dt.total_seconds() / 3600
    maxgap = gaps.max()
    if pd.notna(maxgap) and maxgap > 2:
        print(f"  {sleeve}: max gap {maxgap:.2f}h (at {ts[gaps.idxmax()] if gaps.idxmax() in ts.index else '?'})")

# per-day net table (settled only, key sleeves)
if len(lad_settled):
    print("\n=== LADDER per-day net (top sleeves by |sum|) ===")
    lad_settled["_day"] = lad_settled["_at"].dt.date
    piv = lad_settled.groupby(["_sleeve", "_day"])["total_net_usd"].sum().unstack(fill_value=0)
    top_sleeves = lad_settled.groupby("_sleeve")["total_net_usd"].sum().abs().sort_values(ascending=False).index[:8]
    print(piv.loc[piv.index.intersection(top_sleeves)].round(2).to_string())

ladder_summary.to_csv(f"{DIR}/_wf/ladder_compiled3.csv", index=False) if len(lad_settled) else None

# ---------- SUMPAIR ----------
print("\n\n=========== SUMPAIR ===========")
sp = load_tsv(f"{DIR}/sumpair_refresh3.tsv")
print(f"SUMPAIR rows: {len(sp)} max_at={sp['_at'].max() if len(sp) else 'NA'}")
sp_settle = sp[sp.get("phase") == "settle"].copy() if "phase" in sp.columns else pd.DataFrame()
if len(sp_settle):
    # dedup last row per condition_id
    sp_settle = sp_settle.sort_values("_at").drop_duplicates(subset=["_sleeve", "condition_id"], keep="last")
    if "mode" in sp_settle.columns:
        nlive = (sp_settle["mode"] == "live").sum()
        print(f"SUMPAIR mode=live rows: {nlive}")

    def summarize_sp(df, label):
        out = []
        for sleeve, g in df.groupby("_sleeve"):
            x = g["net_pnl_level0"].dropna().values
            if len(x) == 0:
                continue
            lo, hi = boot_ci(x)
            out.append(dict(period=label, sleeve=sleeve, n=len(x), mean=x.mean(), ci_lo=lo, ci_hi=hi,
                             ex_top2=ex_top2(x)))
        return pd.DataFrame(out)

    full_sp = summarize_sp(sp_settle, "FULL")
    new_sp = summarize_sp(sp_settle[sp_settle["_at"] > NEW_CUT], "NEW")
    sp_summary = pd.concat([full_sp, new_sp], ignore_index=True)
    print(sp_summary.round(3).to_string(index=False))
    sp_summary.to_csv(f"{DIR}/_wf/sumpair_compiled3.csv", index=False)

# ---------- SCALP ----------
print("\n\n=========== SCALP ===========")
sc = load_tsv(f"{DIR}/scalp_refresh3.tsv")
print(f"SCALP rows: {len(sc)} max_at={sc['_at'].max() if len(sc) else 'NA'}")
if len(sc):
    n_new = (sc["_at"] > NEW_CUT).sum()
    print(f"SCALP fires total={len(sc)}, in NEW period (>Jul10 20:00) = {n_new}")
    if "mode" in sc.columns:
        nlive = (sc["mode"] == "live").sum()
        print(f"SCALP mode=live rows: {nlive}")
    if "pnl_exit_usd" in sc.columns:
        x = sc["pnl_exit_usd"].dropna().values
        print(f"SCALP pnl mean={x.mean():.3f} n={len(x)}")

print("\nDONE")
