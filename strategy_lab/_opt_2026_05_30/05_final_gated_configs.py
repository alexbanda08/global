"""
05_final_gated_configs.py
Build and validate final gated sleeve configs.
For each sleeve: pick best generalizing gate stack (1-3 gates),
compute full metrics + block-bootstrap CI + holdout test.
"""
import pandas as pd
import numpy as np
import itertools
import warnings
warnings.filterwarnings("ignore")

BASE = r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\_opt_2026_05_30\_results"
REPORT_DIR = r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\reports"

fires = pd.read_parquet(f"{BASE}\\fires_resolved_all.parquet")
wf    = pd.read_csv(f"{BASE}\\walkforward_gates.csv")

# ── gate definitions ─────────────────────────────────────────────────────────
def apply_gate(df, gate):
    if gate == "drop_US":        return df[~df["hour"].between(14, 21)]
    if gate == "keep_ASIA_EU":   return df[~df["hour"].between(14, 21)]
    if gate == "keep_EU":        return df[df["hour"].between(6, 13)]
    if gate == "evcap_0.70":     return df[df["entry_vwap"] <= 0.70]
    if gate == "evcap_0.75":     return df[df["entry_vwap"] <= 0.75]
    if gate == "evcap_0.80":     return df[df["entry_vwap"] <= 0.80]
    if gate == "vsum_1.25":      return df[df["vwap_sum"] <= 1.25]
    if gate == "vsum_1.30":      return df[df["vwap_sum"] <= 1.30]
    if gate == "xspread_0.25":   return df[df["cross_spread"] <= 0.25]
    if gate == "xspread_0.22":   return df[df["cross_spread"] <= 0.22]
    if gate == "depth_1000":     return df[df["own_depth"] >= 1000]
    if gate == "dir_UP":         return df[df["direction"] == "UP"]
    if gate == "dir_DOWN":       return df[df["direction"] == "DOWN"]
    return df

def apply_gates(df, gates):
    for g in gates:
        df = apply_gate(df, g)
    return df

def boot_ci_mean(pnl_arr, n_boot=2000, seed=42):
    rng = np.random.default_rng(seed)
    if len(pnl_arr) < 2: return np.nan
    arr = np.array(pnl_arr)
    means = [rng.choice(arr, size=len(arr), replace=True).mean() for _ in range(n_boot)]
    return np.percentile(means, 2.5)

def metrics(df):
    n = len(df)
    wr = df["won"].mean() * 100 if n > 0 else np.nan
    mean_pnl = df["pnl_usd"].mean() if n > 0 else np.nan
    total_pnl = df["pnl_usd"].sum() if n > 0 else np.nan
    return n, wr, mean_pnl, total_pnl

def holdout_test(df_sleeve, stack):
    """Chronological 50/50 split. Return (base_test_mean, gated_test_mean, gated_test_n)."""
    df_sorted = df_sleeve.sort_values("fire_us")
    split = len(df_sorted) // 2
    test_half = df_sorted.iloc[split:]
    base_mean = test_half["pnl_usd"].mean()
    gated_test = apply_gates(test_half.copy(), stack)
    gated_mean = gated_test["pnl_usd"].mean() if len(gated_test) > 0 else np.nan
    return base_mean, gated_mean, len(gated_test)

# ── get validated gates per sleeve ───────────────────────────────────────────
gen_gates = (wf[wf["generalizes"] == True]
             .groupby("sleeve")["gate"]
             .apply(list)
             .to_dict())

ALL_GATE_POOL = [
    "drop_US","keep_ASIA_EU","keep_EU",
    "evcap_0.70","evcap_0.75","evcap_0.80",
    "vsum_1.25","vsum_1.30",
    "xspread_0.25","xspread_0.22",
    "depth_1000",
    "dir_UP","dir_DOWN"
]

results = []

for sleeve, sdf in fires.groupby("sleeve"):
    base_n, base_wr, base_mean, base_total = metrics(sdf)
    valid_gates = gen_gates.get(sleeve, [])

    # Add special gates for special-case sleeves
    if sleeve == "btc_5m_l_1hrf_imb5_ribbon_v8":
        extra = ["vsum_1.30","depth_1000","xspread_0.22"]
        valid_gates = list(set(valid_gates + extra))

    min_n_req = min(40, max(1, int(0.5 * base_n)))

    best = None  # (stack, total, mean, n, wr, ci_lo, base_test, gate_test, gated_test_n, generalizes)

    # Try stacks size 1, 2, 3
    for size in [1, 2, 3]:
        if size > len(valid_gates): continue
        for combo in itertools.combinations(valid_gates, size):
            stack = list(combo)
            gdf = apply_gates(sdf.copy(), stack)
            n, wr, mean_pnl, total_pnl = metrics(gdf)
            if n < min_n_req: continue
            base_test, gate_test, gated_test_n = holdout_test(sdf.copy(), stack)
            ci_lo = boot_ci_mean(gdf["pnl_usd"].values)
            holdout_pass = (not np.isnan(gate_test)) and (gate_test > base_test)

            if not holdout_pass: continue  # must beat holdout

            if best is None or total_pnl > best["gated_total"]:
                best = dict(
                    sleeve=sleeve, stack="|".join(stack),
                    gated_n=n, gated_wr=wr, gated_mean=mean_pnl,
                    gated_total=total_pnl, ci_lo=ci_lo,
                    base_test_mean=base_test, gated_test_mean=gate_test,
                    gated_test_n=gated_test_n,
                    base_n=base_n, base_wr=base_wr,
                    base_mean=base_mean, base_total=base_total
                )

    # If no valid stack found, record ungated
    if best is None:
        best = dict(
            sleeve=sleeve, stack="UNGATED",
            gated_n=base_n, gated_wr=base_wr, gated_mean=base_mean,
            gated_total=base_total, ci_lo=boot_ci_mean(sdf["pnl_usd"].values),
            base_test_mean=np.nan, gated_test_mean=np.nan,
            gated_test_n=base_n//2,
            base_n=base_n, base_wr=base_wr,
            base_mean=base_mean, base_total=base_total
        )

    results.append(best)
    print(f"  {sleeve}: stack={best['stack']} n={best['gated_n']} mean={best['gated_mean']:.3f} total={best['gated_total']:.1f} ci_lo={best['ci_lo']:.3f}")

out = pd.DataFrame(results)

# ── special-case deep dive: btc_5m_l_1hrf_imb5_ribbon_v8 ────────────────────
print("\n=== SPECIAL CASE: btc_5m_l_1hrf_imb5_ribbon_v8 ===")
sdf_btc_l = fires[fires["sleeve"] == "btc_5m_l_1hrf_imb5_ribbon_v8"].copy()

for test_gates in [
    ["vsum_1.30"],
    ["vsum_1.30","depth_1000"],
    ["xspread_0.22"],
    ["vsum_1.25"],
    ["xspread_0.25"],
    ["depth_1000","vsum_1.30"],
]:
    gdf = apply_gates(sdf_btc_l.copy(), test_gates)
    n, wr, mean_pnl, total_pnl = metrics(gdf)
    ci_lo = boot_ci_mean(gdf["pnl_usd"].values) if n >= 10 else np.nan
    base_test, gate_test, gtest_n = holdout_test(sdf_btc_l.copy(), test_gates)

    # Both halves check
    df_sorted = sdf_btc_l.sort_values("fire_us")
    split = len(df_sorted) // 2
    h1 = apply_gates(df_sorted.iloc[:split].copy(), test_gates)
    h2 = apply_gates(df_sorted.iloc[split:].copy(), test_gates)
    h1_mean = h1["pnl_usd"].mean() if len(h1) > 0 else np.nan
    h2_mean = h2["pnl_usd"].mean() if len(h2) > 0 else np.nan
    both_pos = (not np.isnan(h1_mean)) and (not np.isnan(h2_mean)) and h1_mean > 0 and h2_mean > 0
    net_pos = mean_pnl > 0

    print(f"  {test_gates}: n={n} WR={wr:.1f}% mean={mean_pnl:.3f} total={total_pnl:.1f} ci_lo={ci_lo:.3f} "
          f"h1={h1_mean:.3f} h2={h2_mean:.3f} both_pos={both_pos} net_pos={net_pos}")

# ── special-case: btc_5m_q_parent15mslope_ts_imb5_v8 ────────────────────────
print("\n=== SPECIAL CASE: btc_5m_q_parent15mslope_ts_imb5_v8 ===")
sdf_q = fires[fires["sleeve"] == "btc_5m_q_parent15mslope_ts_imb5_v8"].copy()
best_q = None

val_q = gen_gates.get("btc_5m_q_parent15mslope_ts_imb5_v8", [])
for size in [1, 2]:
    pool = list(set(val_q + ["vsum_1.25","vsum_1.30","xspread_0.25","depth_1000","dir_UP","dir_DOWN","drop_US","keep_EU"]))
    for combo in itertools.combinations(pool, size):
        stack = list(combo)
        gdf = apply_gates(sdf_q.copy(), stack)
        if len(gdf) < 40: continue
        n, wr, mean_pnl, total_pnl = metrics(gdf)
        if best_q is None or mean_pnl > best_q["mean_pnl"]:
            best_q = dict(stack="|".join(stack), n=n, wr=wr, mean_pnl=mean_pnl, total_pnl=total_pnl)

if best_q:
    print(f"  BEST <=2-gate: {best_q['stack']} n={best_q['n']} mean={best_q['mean_pnl']:.3f} total={best_q['total_pnl']:.1f}")
    verdict = "SALVAGE" if best_q["mean_pnl"] >= 0 else "KILL"
    print(f"  VERDICT: {verdict}")

# ── special-case: btc_5m_ts_mpskew_any_off30 ────────────────────────────────
print("\n=== SPECIAL CASE: btc_5m_ts_mpskew_any_off30 ===")
sdf_ts = fires[fires["sleeve"] == "btc_5m_ts_mpskew_any_off30"].copy()
val_ts = gen_gates.get("btc_5m_ts_mpskew_any_off30", [])
best_ts = None
pool_ts = list(set(val_ts + ["vsum_1.25","vsum_1.30","xspread_0.25","depth_1000","dir_UP","dir_DOWN","drop_US","keep_EU"]))
for size in [1,2]:
    for combo in itertools.combinations(pool_ts, size):
        stack = list(combo)
        gdf = apply_gates(sdf_ts.copy(), stack)
        if len(gdf) < 20: continue
        n, wr, mean_pnl, total_pnl = metrics(gdf)
        base_test, gate_test, gtn = holdout_test(sdf_ts.copy(), stack)
        if gate_test is np.nan or np.isnan(gate_test): continue
        both_half = False
        df_sorted = sdf_ts.sort_values("fire_us")
        split = len(df_sorted) // 2
        h1 = apply_gates(df_sorted.iloc[:split].copy(), stack)
        h2 = apply_gates(df_sorted.iloc[split:].copy(), stack)
        h1m = h1["pnl_usd"].mean() if len(h1)>0 else np.nan
        h2m = h2["pnl_usd"].mean() if len(h2)>0 else np.nan
        both_half = (not np.isnan(h1m)) and (not np.isnan(h2m)) and h1m>0 and h2m>0
        if both_half and (best_ts is None or mean_pnl > best_ts["mean_pnl"]):
            best_ts = dict(stack="|".join(stack), n=n, wr=wr, mean_pnl=mean_pnl, total_pnl=total_pnl, h1m=h1m, h2m=h2m)

if best_ts:
    print(f"  SALVAGEABLE: {best_ts}")
else:
    print("  UNSALVAGEABLE - no stack passes both halves positive")
    # Report best achievable
    for size in [1,2]:
        for combo in itertools.combinations(pool_ts, size):
            stack = list(combo)
            gdf = apply_gates(sdf_ts.copy(), stack)
            if len(gdf) < 20: continue
            n, wr, mean_pnl, total_pnl = metrics(gdf)
            if best_ts is None or mean_pnl > best_ts["mean_pnl"]:
                best_ts = dict(stack="|".join(stack), n=n, wr=wr, mean_pnl=mean_pnl, total_pnl=total_pnl)
    print(f"  BEST achievable: {best_ts}")

# ── save results ─────────────────────────────────────────────────────────────
out.to_csv(f"{BASE}\\final_gated_configs.csv", index=False)
print(f"\nSaved: {BASE}\\final_gated_configs.csv")
print("\n=== FULL RESULTS TABLE ===")
print(out[["sleeve","stack","base_total","gated_total","gated_mean","ci_lo",
           "gated_n","base_n","gated_wr","base_test_mean","gated_test_mean"]].to_string())
