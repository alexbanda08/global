import json, sys
import pandas as pd
import numpy as np
from scipy import stats

BASE = r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\directional\_ireland_6day"
NEW_CUTOFF = pd.Timestamp("2026-07-12 07:00:00", tz="UTC")

def load_tsv(fname):
    cols = ["event_id","at","sleeve_id","mode","data"]
    rows = []
    with open(f"{BASE}\\{fname}", "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) < 5:
                # data field may be missing entirely (mode null and data null?) skip malformed
                continue
            event_id, at, sleeve_id, mode = parts[0], parts[1], parts[2], parts[3]
            data_str = "\t".join(parts[4:])
            try:
                data = json.loads(data_str)
            except Exception:
                data = {}
            rec = {"event_id": event_id, "at": at, "sleeve_id": sleeve_id, "mode": mode}
            rec.update(data)
            rows.append(rec)
    df = pd.DataFrame(rows)
    df["at"] = pd.to_datetime(df["at"], utc=True)
    return df

def ci95(x):
    x = np.asarray(x, dtype=float)
    n = len(x)
    if n < 2:
        return (np.nan, np.nan)
    m = x.mean()
    se = x.std(ddof=1) / np.sqrt(n)
    t = stats.t.ppf(0.975, n-1)
    return (m - t*se, m + t*se)

def ex_top2(x):
    x = sorted(x, reverse=True)
    if len(x) <= 2:
        return np.nan
    rest = x[2:]
    return np.mean(rest) if rest else np.nan

def compile_sleeve_stats(df, pnl_col, label):
    out = []
    for period, sub in [("FULL", df), ("NEW", df[df["at"] > NEW_CUTOFF])]:
        for sleeve, g in sub.groupby("sleeve_id"):
            n_all = len(g)
            traded = g[pnl_col].notna()
            n_traded = traded.sum()
            traded_pct = 100.0*n_traded/n_all if n_all else np.nan
            vals = g.loc[traded, pnl_col].astype(float).values
            n = len(vals)
            if n == 0:
                continue
            mean = vals.mean()
            lo, hi = ci95(vals)
            ex2 = ex_top2(vals)
            median = np.median(vals)
            pct_pos = 100.0*np.mean(vals > 0)
            days = g.loc[traded, "at"].dt.floor("D")
            ndays = days.nunique()
            per_day_dollar = vals.sum()/ndays if ndays else np.nan
            out.append(dict(period=period, sleeve=sleeve, n_traded=n, n_all=n_all,
                             traded_pct=traded_pct, mean=mean, ci_lo=lo, ci_hi=hi,
                             ex_top2=ex2, median=median, pct_pos=pct_pos,
                             dollar_per_day=per_day_dollar, ndays=ndays))
    return pd.DataFrame(out)

print("="*80)
print("LADDER (poly_ladder*) — traded windows only: filled_up_sh>0 OR filled_dn_sh>0 AND outcome not null")
print("="*80)
lad = load_tsv("ladder_all_refresh4.tsv")
print("max(at) ladder:", lad["at"].max())
for c in ["filled_up_sh","filled_dn_sh","outcome","total_net_usd"]:
    if c not in lad.columns:
        lad[c] = np.nan
traded_mask = ((lad["filled_up_sh"].astype(float) > 0) | (lad["filled_dn_sh"].astype(float) > 0)) & lad["outcome"].notna()
lad_traded = lad[traded_mask].copy()
lad_pnl_field = "total_net_usd"
lad_traded[lad_pnl_field] = lad_traded[lad_pnl_field].astype(float)
# for compile_sleeve_stats we need a df where non-traded rows have NaN in pnl_col, but we already filtered n_all should be from full df
# Rebuild: use full df, but pnl_col = total_net_usd only if traded_mask else NaN
lad["_pnl"] = np.where(traded_mask, lad["total_net_usd"].astype(float), np.nan)
stats_lad = compile_sleeve_stats(lad, "_pnl", "ladder")
pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 20)
print(stats_lad.to_string(index=False))
stats_lad.to_csv(f"{BASE}\\_compiled_ladder_stats.csv", index=False)

print()
print("="*80)
print("TRUST RECONCILIATION (ladder)")
print("="*80)
for col in ["paired_pnl_locked_usd","rebate_usd","residual_pnl_usd","coc_cut_cost_usd","coc_taker_fee_usd","total_net_usd"]:
    if col not in lad.columns:
        lad[col] = 0.0
    lad[col] = pd.to_numeric(lad[col], errors="coerce").fillna(0.0)
lad["_recon_calc"] = lad["paired_pnl_locked_usd"] + lad["rebate_usd"] + lad["residual_pnl_usd"] - lad["coc_cut_cost_usd"] - lad["coc_taker_fee_usd"]
lad["_recon_err"] = (lad["total_net_usd"] - lad["_recon_calc"]).abs()
for period, sub in [("FULL", lad), ("NEW", lad[lad["at"] > NEW_CUTOFF])]:
    for sleeve, g in sub.groupby("sleeve_id"):
        gt = g[traded_mask.reindex(g.index, fill_value=False)] if False else g[((g["filled_up_sh"].astype(float)>0)|(g["filled_dn_sh"].astype(float)>0)) & g["outcome"].notna()]
        if len(gt)==0: continue
        max_err = gt["_recon_err"].max()
        # outcome_binance mismatch
        if "outcome_binance" in gt.columns:
            mismatch = (gt["outcome"] != gt["outcome_binance"]).mean()*100
        else:
            mismatch = np.nan
        print(f"{period} {sleeve}: max_recon_err={max_err:.6f} outcome_binance_mismatch%={mismatch:.2f} n={len(gt)}")

print()
print("unsettled>1h check (outcome null, at older than 1h):")
now = pd.Timestamp.utcnow()
unsettled = lad[lad["outcome"].isna() & (lad["at"] < now - pd.Timedelta(hours=1))]
print(unsettled.groupby("sleeve_id").size())

print()
print("emission gaps >2h per sleeve:")
for sleeve, g in lad.sort_values("at").groupby("sleeve_id"):
    gaps = g["at"].diff().dt.total_seconds()/3600.0
    biggaps = gaps[gaps > 2]
    if len(biggaps):
        print(sleeve, "n_gaps>2h:", len(biggaps), "max_gap_h:", biggaps.max())

print()
print("="*80)
print("PER-DAY NET (ladder, traded)")
print("="*80)
lad_traded["_day"] = lad_traded["at"].dt.floor("D")
per_day = lad_traded.groupby(["sleeve_id","_day"])[lad_pnl_field].sum().reset_index()
print(per_day.to_string(index=False))
per_day.to_csv(f"{BASE}\\_compiled_ladder_per_day.csv", index=False)

print()
print("="*80)
print("SUMPAIR net_pnl_level0 — dedup last per condition_id")
print("="*80)
sp = load_tsv("sumpair_refresh4.tsv")
print("max(at) sumpair:", sp["at"].max())
sp = sp.sort_values("at")
sp_dedup = sp.dropna(subset=["condition_id"]).groupby(["sleeve_id","condition_id"], as_index=False).last()
if "net_pnl_level0" not in sp_dedup.columns:
    sp_dedup["net_pnl_level0"] = np.nan
sp_dedup["net_pnl_level0"] = pd.to_numeric(sp_dedup["net_pnl_level0"], errors="coerce")
for period, sub in [("FULL", sp_dedup), ("NEW", sp_dedup[sp_dedup["at"] > NEW_CUTOFF])]:
    for sleeve, g in sub.groupby("sleeve_id"):
        vals = g["net_pnl_level0"].dropna().values
        n = len(vals)
        if n==0: continue
        m = vals.mean()
        lo, hi = ci95(vals)
        print(f"{period} {sleeve}: n={n} mean={m:.4f} CI95=[{lo:.4f},{hi:.4f}]")

print()
print("="*80)
print("STEP 4: live-mode rows across all kinds since Jul2")
print("="*80)
for name, df_ in [("ladder", lad), ("sumpair", sp), ("scalp", None)]:
    if df_ is None: continue
    if "mode" in df_.columns:
        livecount = (df_["mode"]=="live").sum()
        print(name, "live rows:", livecount)

print()
print("="*80)
print("SCALP_EXIT — all rows since Jul2 (n=14 total per earlier scan)")
print("="*80)
sc = load_tsv("scalp_refresh4.tsv")
print(sc[["at","sleeve_id","mode"] + [c for c in ["pnl_exit_usd","entry_vwap","sell_vwap","direction"] if c in sc.columns]].to_string(index=False))
print("max(at) scalp:", sc["at"].max())
print("any since Jul12 07:00:", (sc["at"] > NEW_CUTOFF).sum())
