import json
import pandas as pd
import numpy as np

BASE = r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\directional\_ireland_6day"
NEWSPLIT = pd.Timestamp("2026-07-09 12:00:00", tz="UTC")

def boot_ci(x, n=10000, seed=0):
    x = np.asarray(x, dtype=float)
    if len(x) == 0:
        return (np.nan, np.nan)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(x), size=(n, len(x)))
    means = x[idx].mean(axis=1)
    return (np.percentile(means, 2.5), np.percentile(means, 97.5))

def load_tsv(path):
    rows = []
    with open(path, encoding="utf-8") as f:
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
    if len(df):
        df["at"] = pd.to_datetime(df["at"], utc=True)
    return df

out = []

# ---------- LADDER ----------
df = load_tsv(f"{BASE}/ladder_all_refresh2.tsv")
out.append(f"# Ladder compile (refresh2)\nrows_loaded={len(df)}\n")

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

trust_lines = []
per_day_rows = []
mode_live_rows = 0

for sleeve, g in traded.groupby("sleeve_id"):
    g = g.sort_values("at")
    n_all = len(g)
    span_days = (g["at"].max() - g["at"].min()).total_seconds()/86400 if n_all>1 else 0
    out.append(f"\n## {sleeve}  (n={n_all}, span={span_days:.2f}d)\n")

    recon = (g["paired_pnl_locked_usd"].fillna(0) + g["rebate_usd"].fillna(0) + g["residual_pnl_usd"].fillna(0)
             - g["coc_cut_cost_usd"].fillna(0) - g["coc_taker_fee_usd"].fillna(0))
    diff = (g["total_net_usd"] - recon).abs()
    trust_lines.append(f"- {sleeve}: max|total_net-recon|={diff.max():.4f} (n={n_all})")

    if "outcome_binance" in g.columns:
        mismatch = (g["outcome_binance"].notna() & (g["outcome_binance"] != g["outcome"])).sum()
        trust_lines.append(f"  outcome_binance mismatch: {mismatch}/{g['outcome_binance'].notna().sum()}")

    if "mode" in g.columns:
        lm = (g["mode"] == "live").sum()
        mode_live_rows += lm
        if lm:
            trust_lines.append(f"  {sleeve}: mode=live rows: {lm}")

    for period_name, mask in [
        ("FULL Jul2-now", pd.Series(True, index=g.index)),
        ("NEW Jul9 12:00-now", (g["at"] >= NEWSPLIT)),
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

        if len(vals) > 2:
            idx_sorted = np.argsort(vals)[::-1]
            ex2 = np.delete(vals, idx_sorted[:2])
            ex2_mean = ex2.mean()
            ex2_lo, ex2_hi = boot_ci(ex2)
        else:
            ex2_mean, ex2_lo, ex2_hi = float('nan'), float('nan'), float('nan')

        decomp = gp[["paired_pnl_locked_usd","rebate_usd","residual_pnl_usd","coc_cut_cost_usd","coc_taker_fee_usd"]].mean()
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
        out.append(f"- fills up/dn mean={fu:.2f}/{fd:.2f} fill_below_touch pooled mean={fbtu_mean:.2f} min={fbtu_min:.2f}\n")

    all_g = df[df["sleeve_id"]==sleeve]
    unsettled = all_g[all_g["traded"] & (~all_g["settled"]) & (now - all_g["at"] > pd.Timedelta(hours=1))]
    trust_lines.append(f"  unsettled traded >1h old: {len(unsettled)}")

    g2 = g.copy()
    g2["day"] = g2["at"].dt.date
    daily = g2.groupby("day")["total_net_usd"].sum()
    per_day_rows.append((sleeve, daily))

out.append("\n## Trust checks (ladder)\n")
out.extend([l+"\n" for l in trust_lines])
out.append(f"total mode=live rows across sleeves: {mode_live_rows}\n")

out.append("\n## Per-day net table (ladder, FULL period)\n")
for sleeve, daily in per_day_rows:
    out.append(f"\n**{sleeve}**\n")
    for day, val in daily.items():
        out.append(f"- {day}: {val:.2f}\n")

# ---------- SUMPAIR ----------
sp = load_tsv(f"{BASE}/sumpair_refresh2.tsv")
out.append(f"\n\n# Sumpair compile (refresh2)\nrows_loaded={len(sp)}\n")
if len(sp):
    settle = sp[sp.get("phase") == "settle"].copy()
    for c in ["net_pnl_level0", "net_pnl_walk"]:
        if c in settle.columns:
            settle[c] = pd.to_numeric(settle[c], errors="coerce")
    key_cols = [c for c in ["condition_id"] if c in settle.columns]
    if key_cols:
        settle = settle.sort_values("at").groupby(["sleeve_id"]+key_cols, as_index=False).tail(1)
    for sleeve, g in settle.groupby("sleeve_id"):
        g = g.sort_values("at")
        out.append(f"\n## {sleeve} (n={len(g)})\n")
        for period_name, mask in [
            ("FULL Jul2-now", pd.Series(True, index=g.index)),
            ("NEW Jul9 12:00-now", (g["at"] >= NEWSPLIT)),
        ]:
            gp = g[mask]
            n = len(gp)
            if n == 0:
                out.append(f"**{period_name}**: n=0\n")
                continue
            for col in ["net_pnl_level0", "net_pnl_walk"]:
                if col not in gp.columns:
                    continue
                vals = gp[col].dropna().values
                mean = vals.mean() if len(vals) else float('nan')
                lo, hi = boot_ci(vals)
                out.append(f"**{period_name}** {col}: mean={mean:.4f} CI95[{lo:.4f},{hi:.4f}] n={len(vals)}\n")
else:
    out.append("NO ROWS\n")

# ---------- SCALP_EXIT ----------
sc = load_tsv(f"{BASE}/scalp_refresh2.tsv")
out.append(f"\n\n# Scalp_exit compile (refresh2)\nrows_loaded={len(sc)}\n")
if len(sc):
    pnl_col = None
    for cand in ["pnl_usd","total_net_usd","pnl"]:
        if cand in sc.columns:
            pnl_col = cand
            break
    if pnl_col:
        sc[pnl_col] = pd.to_numeric(sc[pnl_col], errors="coerce")
        vals = sc[pnl_col].dropna().values
        out.append(f"n={len(sc)}, mean {pnl_col}={vals.mean() if len(vals) else float('nan'):.4f}\n")
    entry_col = None
    for cand in ["entry_vwap","entry_price"]:
        if cand in sc.columns:
            entry_col = cand
            break
    if entry_col:
        sc[entry_col] = pd.to_numeric(sc[entry_col], errors="coerce")
        pct_low = (sc[entry_col] < 0.55).mean()*100
        out.append(f"entries<0.55: {pct_low:.1f}%\n")
    new_n = (sc["at"] >= NEWSPLIT).sum()
    out.append(f"fires in NEW period (Jul9 12:00-now): {new_n}\n")
    out.append("\nRaw rows dump:\n")
    for _, r in sc.iterrows():
        out.append(f"- {r['at']} {r['sleeve_id']} {dict(r.drop(['at','sleeve_id']))}\n")
else:
    out.append("NO ROWS\n")

with open(f"{BASE}/compile2_refresh.txt", "w", encoding="utf-8") as f:
    f.writelines(out)

print("DONE, wrote compile2_refresh.txt")
print("".join(out))
