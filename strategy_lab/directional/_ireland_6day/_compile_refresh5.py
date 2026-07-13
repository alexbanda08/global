import json, math
import pandas as pd
import numpy as np

BASE = r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\directional\_ireland_6day"

def load_ladder(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            parts = line.split("\t", 2)
            if len(parts) < 3:
                continue
            at, sleeve, data = parts
            try:
                d = json.loads(data)
            except Exception:
                continue
            d["at"] = pd.Timestamp(at)
            d["sleeve_id"] = sleeve
            rows.append(d)
    return pd.DataFrame(rows)

df = load_ladder(BASE + r"\ladder_all_refresh5.tsv")
print("total rows:", len(df), "max at:", df["at"].max(), "min at:", df["at"].min())

def traded_mask(d):
    up = pd.to_numeric(d.get("filled_up_sh"), errors="coerce").fillna(0)
    dn = pd.to_numeric(d.get("filled_dn_sh"), errors="coerce").fillna(0)
    outc = d.get("outcome")
    return ((up > 0) | (dn > 0)) & outc.notna()

df["traded"] = traded_mask(df)
df["net"] = pd.to_numeric(df["total_net_usd"], errors="coerce")

def ci95(x):
    x = x.dropna()
    n = len(x)
    if n < 2:
        return (np.nan, np.nan)
    m = x.mean()
    se = x.std(ddof=1) / math.sqrt(n)
    return (m - 1.96 * se, m + 1.96 * se)

def headline(sub, label, span_days):
    t = sub[sub["traded"]]
    n = len(t)
    tot_rows = len(sub)
    pct = n / tot_rows * 100 if tot_rows else float("nan")
    if n == 0:
        print(f"{label}: n_traded=0")
        return
    mean = t["net"].mean()
    lo, hi = ci95(t["net"])
    ex2 = t.sort_values("net", ascending=False).iloc[2:]
    ex2_mean = ex2["net"].mean() if len(ex2) else float("nan")
    pos = (t["net"] > 0).mean() * 100
    perday = t["net"].sum() / span_days
    print(f"{label}: n_traded={n} traded%={pct:.1f}% mean/win={mean:.3f} CI95=[{lo:.3f},{hi:.3f}] ex-top2={ex2_mean:.3f} %pos={pos:.1f}% $/day={perday:.2f} n_days={span_days:.2f}")

span_full = (df["at"].max() - df["at"].min()).total_seconds() / 86400
NEW_CUTOFF = pd.Timestamp("2026-07-12 11:15:00+00:00")
span_new = (df["at"].max() - NEW_CUTOFF).total_seconds() / 86400

print("\n=== STEP 2: headline per sleeve ===")
for sleeve in sorted(df["sleeve_id"].unique()):
    sub = df[df["sleeve_id"] == sleeve]
    headline(sub, f"{sleeve} FULL", span_full)
    subnew = sub[sub["at"] > NEW_CUTOFF]
    headline(subnew, f"{sleeve} NEW", span_new)

print("\n=== STEP 3: btc_5m_v3 improvement slices (FULL) ===")
b = df[(df["sleeve_id"] == "poly_ladder_btc_5m_v3") & (df["traded"])].copy()
print("n traded:", len(b))

# (a) hour of day
b["hour"] = b["at"].dt.hour
hod = b.groupby("hour")["net"].agg(["count", "mean", "sum"]).round(3)
print("\n(a) HOUR-OF-DAY:\n", hod.to_string())

# (b) residual anatomy
b["rev"] = pd.to_numeric(b["residual_entry_vwap"], errors="coerce")
bins = [-np.inf, 0.3, 0.45, 0.6, np.inf]
labels = ["<0.3", "0.3-0.45", "0.45-0.6", ">0.6"]
b["rev_bucket"] = pd.cut(b["rev"], bins=bins, labels=labels)
resid = b.groupby("rev_bucket")["residual_pnl_usd"].agg(["count", "mean"]).round(3)
print("\n(b) RESIDUAL ANATOMY (residual_pnl_usd by residual_entry_vwap bucket):\n", resid.to_string())

# (c) backstop
bc = pd.to_numeric(b["residual_backstop_cost_usd"], errors="coerce")
paired_gain = pd.to_numeric(b["net_paired_estimate_usd"], errors="coerce")
share_drag = (bc > paired_gain).mean() * 100
print(f"\n(c) BACKSTOP: mean residual_backstop_cost_usd={bc.mean():.3f} share(backstop>paired_gain)={share_drag:.1f}%")

# (d) pvs headroom
pvs = pd.to_numeric(b["pvs"], errors="coerce")
print(f"\n(d) PVS: non-null n={pvs.notna().sum()}/{len(b)} p50={pvs.quantile(.5)} p90={pvs.quantile(.9)} max={pvs.max()}")
bound = pd.to_numeric(b["pair_gate_bound_sh"], errors="coerce").fillna(0)
n_bound = (bound > 0).sum()
tot_bound = bound.sum()
days = span_full
print(f"    pair_gate_bound_sh>0 windows={n_bound} total_bound_sh={tot_bound:.1f} bound_sh/day={tot_bound/days:.1f}")

# (e) coverage losses -- need full df (not just traded) for skipped_reason
allb = df[df["sleeve_id"] == "poly_ladder_btc_5m_v3"]
skip_counts = allb["skipped_reason"].fillna("NONE/traded_or_ok").value_counts()
print("\n(e) COVERAGE LOSSES (skipped_reason counts, full window):\n", skip_counts.to_string())
print(f"    recapturable/day (skipped_reason not null) = {(allb['skipped_reason'].notna()).sum()/span_full:.2f}")

# (f) flow capture
fc = pd.to_numeric(b["flow_capture"], errors="coerce")
mst = pd.to_numeric(b["market_sell_total_sh"], errors="coerce")
print(f"\n(f) FLOW CAPTURE: mean flow_capture={fc.mean():.5f} mean market_sell_total_sh={mst.mean():.1f}")

# (g) size curve
fill_usd = pd.to_numeric(b["filled_up_sh"], errors="coerce").fillna(0) * pd.to_numeric(b["filled_up_vwap"], errors="coerce").fillna(0) \
    + pd.to_numeric(b["filled_dn_sh"], errors="coerce").fillna(0) * pd.to_numeric(b["filled_dn_vwap"], errors="coerce").fillna(0)
netpertrade = b["net"]
corr = fill_usd.corr(netpertrade)
netperdollar = (netpertrade / fill_usd.replace(0, np.nan))
print(f"\n(g) SIZE CURVE: corr(fill_$, net)={corr:.3f} mean fill_$={fill_usd.mean():.2f} mean net/$={netperdollar.mean():.4f}")

print("\n=== eth_5m_v3 slices (a)(b) FULL ===")
e = df[(df["sleeve_id"] == "poly_ladder_eth_5m_v3") & (df["traded"])].copy()
print("n traded:", len(e))
e["hour"] = e["at"].dt.hour
hod_e = e.groupby("hour")["net"].agg(["count", "mean", "sum"]).round(3)
print("\n(a) HOUR-OF-DAY (ETH):\n", hod_e.to_string())
e["rev"] = pd.to_numeric(e["residual_entry_vwap"], errors="coerce")
e["rev_bucket"] = pd.cut(e["rev"], bins=bins, labels=labels)
resid_e = e.groupby("rev_bucket")["residual_pnl_usd"].agg(["count", "mean"]).round(3)
print("\n(b) RESIDUAL ANATOMY (ETH):\n", resid_e.to_string())

print("\n=== STEP 4: sumpair ===")
def load_kv(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            parts = line.split("\t", 2)
            if len(parts) < 3:
                continue
            at, sleeve, data = parts
            try:
                d = json.loads(data)
            except Exception:
                continue
            d["at"] = pd.Timestamp(at)
            d["sleeve_id"] = sleeve
            rows.append(d)
    return pd.DataFrame(rows)

sp = load_kv(BASE + r"\sumpair_all_refresh5.tsv")
sp_btc = sp[(sp["sleeve_id"] == "sumpair_osc_btc_5m") & (sp["phase"] == "settle")]
sp_btc_net = pd.to_numeric(sp_btc["net_pnl_level0"], errors="coerce")
sp_span_full = (sp["at"].max() - sp["at"].min()).total_seconds() / 86400
sp_new = sp_btc[sp_btc["at"] > NEW_CUTOFF]
sp_new_net = pd.to_numeric(sp_new["net_pnl_level0"], errors="coerce")
print(f"sumpair btc net_pnl_level0 FULL: n={len(sp_btc_net.dropna())} sum={sp_btc_net.sum():.2f} mean={sp_btc_net.mean():.4f}")
print(f"sumpair btc net_pnl_level0 NEW:  n={len(sp_new_net.dropna())} sum={sp_new_net.sum():.2f} mean={sp_new_net.mean():.4f}")

print("\nDone.")
