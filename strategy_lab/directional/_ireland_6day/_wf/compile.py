import json, sys
import pandas as pd
import numpy as np

BASE = r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\directional\_ireland_6day"
SPLIT = pd.Timestamp("2026-07-08 12:15:00", tz="UTC")

def boot_ci(x, n=10000, seed=0):
    x = np.asarray(x, dtype=float)
    if len(x) == 0:
        return (np.nan, np.nan)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(x), size=(n, len(x)))
    means = x[idx].mean(axis=1)
    return (np.percentile(means, 2.5), np.percentile(means, 97.5))

# ---------- LADDER ----------
rows = []
with open(f"{BASE}/ladder_all_refresh.tsv", encoding="utf-8") as f:
    for line in f:
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 3:
            continue
        at, sleeve, data = parts[0], parts[1], parts[2]
        try:
            d = json.loads(data)
        except Exception:
            continue
        d["at"] = at
        d["sleeve_id"] = sleeve
        rows.append(d)

df = pd.DataFrame(rows)
df["at"] = pd.to_datetime(df["at"], utc=True)

numcols = ["total_net_usd","paired_pnl_locked_usd","rebate_usd","residual_pnl_usd",
           "coc_cut_cost_usd","coc_taker_fee_usd","pair_frac","pvs",
           "filled_up_sh","filled_dn_sh","fill_below_touch_ticks_up","fill_below_touch_ticks_dn"]
for c in numcols:
    if c in df.columns:
        df[c] = pd.to_numeric(df[c], errors="coerce")

df["traded"] = ((df.get("filled_up_sh",0) > 0) | (df.get("filled_dn_sh",0) > 0))
df["settled"] = df["outcome"].notna() & (df["outcome"] != "")
traded = df[df["traded"] & df["settled"]].copy()

now = pd.Timestamp.utcnow()
if now.tzinfo is None:
    now = now.tz_localize("UTC")

out = []
out.append("# Ladder compile\n")

trust_lines = []
per_day_rows = []

for sleeve, g in traded.groupby("sleeve_id"):
    g = g.sort_values("at")
    n_all = len(g)
    span_days = (g["at"].max() - g["at"].min()).total_seconds()/86400 if n_all>1 else 0
    out.append(f"\n## {sleeve}  (n={n_all}, span={span_days:.2f}d, w/day={n_all/span_days if span_days>0 else float('nan'):.1f})\n")

    # trust check: total_net vs decomposition
    recon = (g["paired_pnl_locked_usd"].fillna(0) + g["rebate_usd"].fillna(0) + g["residual_pnl_usd"].fillna(0)
             - g["coc_cut_cost_usd"].fillna(0) - g["coc_taker_fee_usd"].fillna(0))
    diff = (g["total_net_usd"] - recon).abs()
    trust_lines.append(f"- {sleeve}: max|total_net-recon|={diff.max():.4f} (n={n_all})")

    if "outcome_binance" in g.columns:
        mismatch = (g["outcome_binance"].notna() & (g["outcome_binance"] != g["outcome"])).sum()
        trust_lines.append(f"  outcome_binance mismatch: {mismatch}/{g['outcome_binance'].notna().sum()}")

    for period_name, mask in [
        ("Jul2-Jul8 12:15", (g["at"] < SPLIT)),
        ("Jul8 12:15-now", (g["at"] >= SPLIT)),
    ]:
        gp = g[mask]
        n = len(gp)
        if n == 0:
            out.append(f"**{period_name}**: n=0\n")
            continue
        vals = gp["total_net_usd"].dropna().values
        mean = vals.mean() if len(vals) else float('nan')
        lo, hi = boot_ci(vals)
        total = vals.sum()
        pspan = (gp["at"].max()-gp["at"].min()).total_seconds()/86400
        per_day = total/pspan if pspan>0 else float('nan')
        median = np.median(vals) if len(vals) else float('nan')
        pos = (vals>0).mean()*100 if len(vals) else float('nan')

        # ex-top2
        if len(vals) > 2:
            sorted_v = np.sort(vals)[::-1]
            ex2 = vals[~np.isin(vals, sorted_v[:2])] if len(set(sorted_v[:2]))==2 else np.delete(np.sort(vals)[::-1],[0,1])
            # simpler: drop two largest by index
            idx_sorted = np.argsort(vals)[::-1]
            ex2 = np.delete(vals, idx_sorted[:2])
            ex2_mean = ex2.mean()
            ex2_lo, ex2_hi = boot_ci(ex2)
        else:
            ex2_mean, ex2_lo, ex2_hi = float('nan'), float('nan'), float('nan')

        decomp = gp[["paired_pnl_locked_usd","rebate_usd","residual_pnl_usd","coc_cut_cost_usd","coc_taker_fee_usd"]].mean()
        pair_frac_mean = gp["pair_frac"].mean() if "pair_frac" in gp else float('nan')
        pvs_mean = gp["pvs"].mean() if "pvs" in gp else float('nan')
        pvs_max = gp["pvs"].max() if "pvs" in gp else float('nan')
        fu = gp["filled_up_sh"].mean() if "filled_up_sh" in gp else float('nan')
        fd = gp["filled_dn_sh"].mean() if "filled_dn_sh" in gp else float('nan')
        fbtu = pd.concat([gp.get("fill_below_touch_ticks_up"), gp.get("fill_below_touch_ticks_dn")]).dropna() if "fill_below_touch_ticks_up" in gp else pd.Series(dtype=float)
        fbtu_mean = fbtu.mean() if len(fbtu) else float('nan')
        fbtu_min = fbtu.min() if len(fbtu) else float('nan')

        out.append(f"**{period_name}**: n={n}, span={pspan:.2f}d\n")
        out.append(f"- total_net: mean={mean:.4f} CI95[{lo:.4f},{hi:.4f}] sum={total:.2f} $/day={per_day:.2f}\n")
        out.append(f"- ex-top2: mean={ex2_mean:.4f} CI95[{ex2_lo:.4f},{ex2_hi:.4f}]\n")
        out.append(f"- median={median:.4f} pos%={pos:.1f}\n")
        out.append(f"- decomp means: paired={decomp['paired_pnl_locked_usd']:.4f} rebate={decomp['rebate_usd']:.4f} residual={decomp['residual_pnl_usd']:.4f} coc_cut={decomp['coc_cut_cost_usd']:.4f} coc_taker={decomp['coc_taker_fee_usd']:.4f}\n")
        out.append(f"- pair_frac mean={pair_frac_mean:.3f} pvs mean={pvs_mean:.3f} max={pvs_max:.3f} fills up/dn mean={fu:.2f}/{fd:.2f} fill_below_touch pooled mean={fbtu_mean:.2f} min={fbtu_min:.2f}\n")

    # unsettled traded windows older than 1h (from full df, not just settled)
    all_g = df[df["sleeve_id"]==sleeve]
    unsettled = all_g[all_g["traded"] & (~all_g["settled"]) & (now - all_g["at"] > pd.Timedelta(hours=1))]
    trust_lines.append(f"  unsettled traded >1h old: {len(unsettled)}")

    # per-day net table
    g2 = g.copy()
    g2["day"] = g2["at"].dt.date
    daily = g2.groupby("day")["total_net_usd"].sum()
    per_day_rows.append((sleeve, daily))

out.append("\n## Trust checks\n")
out.extend([l+"\n" for l in trust_lines])

out.append("\n## Per-day net table\n")
for sleeve, daily in per_day_rows:
    out.append(f"\n**{sleeve}**\n")
    for day, val in daily.items():
        out.append(f"- {day}: {val:.2f}\n")

with open(f"{BASE}/ladder_compile_refresh.txt", "w", encoding="utf-8") as f:
    f.writelines(out)

print("LADDER DONE, wrote ladder_compile_refresh.txt")
print("".join(out[:5]))
