"""
Kelly full-period backtest on master_5m_panel.parquet (May 1-21).
Reconstructs ALL_5m_phase1_kelly fires using S4|S8 signal + kelly_mult tiers.
Tests BASE / keep_EU / half-Kelly / new gates.
Computes WR, $/tr, total$, MaxDrawdown$, Calmar.
Walk-forward 50/50 split.

Fee: 0.07 curve (won -> (1-vwap)*shares*(1-0.07*vwap); lost -> -vwap*shares)
Stake: $25 * kelly_mult (full-Kelly); $12.5 * kelly_mult (half-Kelly)
kelly_mult: fe>3000->4x, fe>2000->3x, fe>1000->2x, else 1x
Base: (S4 or S8) and fire_offset_s>=120, dedup(asset+slug+dir, keep first)
S4: fair_edge_bp>500 AND cvd_agree_30s AND abs(dev_bps)>=8
S8: macd_agree AND rvol_30_300>1.2
"""
from __future__ import annotations
import sys, math
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
PANEL = ROOT / "data" / "v4" / "canonical" / "_results" / "master_5m_panel.parquet"
OUT_DIR = ROOT / "strategy_lab" / "_opt_2026_05_30" / "_results"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ── helpers ──────────────────────────────────────────────────────────

def kelly_mult(fe: float) -> float:
    if fe > 3000: return 4.0
    if fe > 2000: return 3.0
    if fe > 1000: return 2.0
    return 1.0

def pnl_07(vwap: float, stake: float, won: bool) -> float:
    """0.07-curve PnL given dollar stake."""
    shares = stake / vwap
    if won:
        return (1.0 - vwap) * shares * (1.0 - 0.07 * vwap)
    return -stake

def pnl_flat5(vwap: float, won: bool) -> float:
    """Flat-$5 stake, legacy 2%-on-profit (matches pnl_legacy_usd scale for comparison)."""
    shares = 5.0 / vwap
    if won:
        return (1.0 - vwap) * shares * 0.98
    return -5.0

def stats(pnl_series: pd.Series, name: str, period_days: float,
          flat5_series: pd.Series | None = None) -> dict:
    """Compute summary stats for a PnL series (chronological order assumed)."""
    n = len(pnl_series)
    if n == 0:
        return {"config": name, "n": 0, "WR_pct": None, "per_tr": None,
                "total": None, "MDD": None, "Calmar": None, "period_days": period_days}
    won_mask = pnl_series > 0
    wr = won_mask.mean() * 100
    total = float(pnl_series.sum())
    per_tr = total / n
    # Max drawdown (chronological cumsum)
    cumsum = np.cumsum(pnl_series.values)
    running_max = np.maximum.accumulate(cumsum)
    mdd = float((cumsum - running_max).min())
    calmar = (total / period_days * 365) / abs(mdd) if mdd != 0 else float("inf")
    row = {"config": name, "n": n, "WR_pct": round(wr, 2),
           "per_tr": round(per_tr, 4), "total": round(total, 2),
           "MDD": round(mdd, 2), "Calmar": round(calmar, 3),
           "period_days": round(period_days, 1)}
    if flat5_series is not None and len(flat5_series) == n:
        flat5_total = float(flat5_series.sum())
        row["flat5_total"] = round(flat5_total, 2)
        row["flat5_per_tr"] = round(flat5_total / n, 4)
    return row

def wf_stats(df: pd.DataFrame, label: str, period_days: float) -> dict:
    """50/50 walk-forward: train first half, evaluate second half (same config)."""
    n = len(df)
    if n < 10:
        return {"config": label + "_WF", "n_test": n, "train_total": None,
                "test_total": None, "test_per_tr": None, "test_WR": None}
    cut = n // 2
    train = df.iloc[:cut]
    test = df.iloc[cut:]
    train_total = float(train["kelly_pnl"].sum())
    test_total = float(test["kelly_pnl"].sum())
    test_per = test_total / len(test) if len(test) > 0 else None
    test_wr = (test["kelly_pnl"] > 0).mean() * 100 if len(test) > 0 else None
    return {"config": label + "_WF50", "n_train": len(train), "n_test": len(test),
            "train_total": round(train_total, 2), "test_total": round(test_total, 2),
            "test_per_tr": round(test_per, 4) if test_per else None,
            "test_WR": round(test_wr, 2) if test_wr else None}

# ── load panel ───────────────────────────────────────────────────────

print("Loading panel...")
df = pd.read_parquet(PANEL)
df["dt"] = pd.to_datetime(df["fire_us"], unit="us", utc=True)
df["hour_utc"] = df["dt"].dt.hour
df["week"] = df["dt"].dt.isocalendar().week.astype(int)
df["date"] = df["dt"].dt.date

print(f"Panel: {len(df):,} rows, {df['dt'].min().date()} to {df['dt'].max().date()}")

# ── apply base S4|S8 filter ──────────────────────────────────────────

s4 = (
    (df["fair_edge_bp"] > 500).fillna(False)
    & df["cvd_agree_30s"].fillna(False).astype(bool)
    & (df["dev_bps"].abs() >= 8).fillna(False)
)
s8 = (
    df["macd_agree"].fillna(False).astype(bool)
    & (df["rvol_30_300"] > 1.2).fillna(False)
)
base_sig = (s4 | s8) & (df["fire_offset_s"] >= 120)

# Dedup: earliest fire per (asset, slug, direction)
base_df = (
    df[base_sig]
    .sort_values(["asset", "slug", "direction", "fire_offset_s"])
    .drop_duplicates(["asset", "slug", "direction"], keep="first")
    .reset_index(drop=True)
)
print(f"After S4|S8 filter + dedup: {len(base_df):,} rows")

# Add kelly_mult and stake PnL columns
base_df["kelly_mult_v"] = base_df["fair_edge_bp"].apply(
    lambda fe: kelly_mult(fe) if pd.notna(fe) else 1.0
)
base_df["stake_full"] = 25.0 * base_df["kelly_mult_v"]
base_df["stake_half"] = 12.5 * base_df["kelly_mult_v"]

# PnL 0.07 curve for both full and half Kelly
base_df["kelly_pnl"] = base_df.apply(
    lambda r: pnl_07(r["entry_vwap"], r["stake_full"], bool(r["won"])), axis=1
)
base_df["half_kelly_pnl"] = base_df.apply(
    lambda r: pnl_07(r["entry_vwap"], r["stake_half"], bool(r["won"])), axis=1
)
# Flat-$5 (legacy 2%) counterfactual
base_df["flat5_pnl"] = base_df.apply(
    lambda r: pnl_flat5(r["entry_vwap"], bool(r["won"])), axis=1
)

period_days = (base_df["dt"].max() - base_df["dt"].min()).total_seconds() / 86400
print(f"Period: {period_days:.1f} days")

# ── BASE stats ────────────────────────────────────────────────────────

results = []
wf_results = []

base_df_sorted = base_df.sort_values("fire_us").reset_index(drop=True)

r_base = stats(base_df_sorted["kelly_pnl"], "BASE_full_kelly", period_days,
               flat5_series=base_df_sorted["flat5_pnl"])
r_base["kelly_mult_mean"] = round(base_df_sorted["kelly_mult_v"].mean(), 3)
results.append(r_base)

r_half = stats(base_df_sorted["half_kelly_pnl"], "BASE_half_kelly", period_days)
r_half["kelly_mult_mean"] = round(base_df_sorted["kelly_mult_v"].mean(), 3)
results.append(r_half)

wf_results.append(wf_stats(base_df_sorted.assign(kelly_pnl=base_df_sorted["kelly_pnl"]),
                            "BASE_full_kelly", period_days))
wf_results.append(wf_stats(base_df_sorted.assign(kelly_pnl=base_df_sorted["half_kelly_pnl"]),
                            "BASE_half_kelly", period_days))

# ── keep_EU gate (fire hour 6-13 UTC) ────────────────────────────────

eu_mask = base_df_sorted["hour_utc"].between(6, 13)
eu_df = base_df_sorted[eu_mask].copy()
r_eu = stats(eu_df["kelly_pnl"], "EU_gate_full_kelly", period_days, flat5_series=eu_df["flat5_pnl"])
r_eu["kelly_mult_mean"] = round(eu_df["kelly_mult_v"].mean(), 3)
results.append(r_eu)

r_eu_half = stats(eu_df["half_kelly_pnl"], "EU_gate_half_kelly", period_days)
r_eu_half["kelly_mult_mean"] = round(eu_df["kelly_mult_v"].mean(), 3)
results.append(r_eu_half)

wf_results.append(wf_stats(eu_df.assign(kelly_pnl=eu_df["kelly_pnl"]),
                            "EU_gate_full_kelly", period_days))
wf_results.append(wf_stats(eu_df.assign(kelly_pnl=eu_df["half_kelly_pnl"]),
                            "EU_gate_half_kelly", period_days))

# ── NEW GATES (single gate, test on both halves) ──────────────────────

# Helper: test one gate, report h1/h2 WR and total, full-kelly only
def gate_halfhold(mask: pd.Series, label: str) -> dict:
    gdf = base_df_sorted[mask].copy()
    n = len(gdf)
    if n < 20:
        return {"gate": label, "n": n, "WR": None, "per_tr": None,
                "total": None, "MDD": None, "Calmar": None,
                "h1_per_tr": None, "h2_per_tr": None, "verdict": "TOO_FEW"}
    cut = n // 2
    h1 = gdf.iloc[:cut]
    h2 = gdf.iloc[cut:]
    pnl_all = gdf["kelly_pnl"]
    total = float(pnl_all.sum())
    per_tr = total / n
    wr = (pnl_all > 0).mean() * 100
    cumsum = np.cumsum(pnl_all.values)
    running_max = np.maximum.accumulate(cumsum)
    mdd = float((cumsum - running_max).min())
    calmar = (total / period_days * 365) / abs(mdd) if mdd != 0 else float("inf")
    h1_per = float(h1["kelly_pnl"].sum()) / len(h1) if len(h1) > 0 else None
    h2_per = float(h2["kelly_pnl"].sum()) / len(h2) if len(h2) > 0 else None
    # base per_tr for comparison
    base_per = r_base["per_tr"]
    verdict = "PASS" if (h1_per is not None and h2_per is not None
                         and h1_per > base_per and h2_per > base_per) else "FAIL"
    return {"gate": label, "n": n, "WR": round(wr, 2), "per_tr": round(per_tr, 4),
            "total": round(total, 2), "MDD": round(mdd, 2), "Calmar": round(calmar, 3),
            "h1_per_tr": round(h1_per, 4) if h1_per is not None else None,
            "h2_per_tr": round(h2_per, 4) if h2_per is not None else None,
            "verdict": verdict, "retain_pct": round(n / len(base_df_sorted) * 100, 1)}

gate_rows = []
base_per = r_base["per_tr"]

# 1. cvd_agree_60s
gate_rows.append(gate_halfhold(
    base_df_sorted["cvd_agree_60s"].fillna(False).astype(bool),
    "cvd_agree_60s"))

# 2. macd_agree
gate_rows.append(gate_halfhold(
    base_df_sorted["macd_agree"].fillna(False).astype(bool),
    "macd_agree"))

# 3. f7_pass
gate_rows.append(gate_halfhold(
    base_df_sorted["f7_pass"].fillna(False).astype(bool),
    "f7_pass"))

# 4. cross_full_agree
gate_rows.append(gate_halfhold(
    base_df_sorted["cross_full_agree"].fillna(False).astype(bool),
    "cross_full_agree"))

# 5. cross_partial_agree
gate_rows.append(gate_halfhold(
    base_df_sorted["cross_partial_agree"].fillna(False).astype(bool),
    "cross_partial_agree"))

# 6. m1v_pass (Markov 1m vol)
gate_rows.append(gate_halfhold(
    base_df_sorted["m1v_pass"].fillna(False).astype(bool),
    "m1v_pass"))

# 7. m5v_pass (Markov 5m vol)
gate_rows.append(gate_halfhold(
    base_df_sorted["m5v_pass"].fillna(False).astype(bool),
    "m5v_pass"))

# 8. m1v_regime>=1 (trending up or down)
gate_rows.append(gate_halfhold(
    base_df_sorted["m1v_regime"].fillna(0) >= 1,
    "m1v_regime_ge1"))

# 9. rvol_30_300 > 1.5 (elevated vol)
gate_rows.append(gate_halfhold(
    (base_df_sorted["rvol_30_300"] > 1.5).fillna(False),
    "rvol_30_300_gt1p5"))

# 10. rvol_30_300 > 2.0
gate_rows.append(gate_halfhold(
    (base_df_sorted["rvol_30_300"] > 2.0).fillna(False),
    "rvol_30_300_gt2"))

# 11. spread_bp < 50 (tight book)
gate_rows.append(gate_halfhold(
    (base_df_sorted["spread_bp"] < 50).fillna(False),
    "spread_bp_lt50"))

# 12. spread_bp < 100
gate_rows.append(gate_halfhold(
    (base_df_sorted["spread_bp"] < 100).fillna(False),
    "spread_bp_lt100"))

# 13. fair_edge_bp > 1000 (higher conviction tier only)
gate_rows.append(gate_halfhold(
    (base_df_sorted["fair_edge_bp"] > 1000).fillna(False),
    "fair_edge_bp_gt1000"))

# 14. fair_edge_bp > 1500
gate_rows.append(gate_halfhold(
    (base_df_sorted["fair_edge_bp"] > 1500).fillna(False),
    "fair_edge_bp_gt1500"))

# 15. fair_edge_bp > 2000
gate_rows.append(gate_halfhold(
    (base_df_sorted["fair_edge_bp"] > 2000).fillna(False),
    "fair_edge_bp_gt2000"))

# 16. rsi_14 > 50 (momentum agree UP direction) + direction aligned
# More nuanced: rsi overbought filter
gate_rows.append(gate_halfhold(
    (base_df_sorted["rsi_14"].between(30, 70)).fillna(False),
    "rsi_14_mid_band"))

# 17. RSI direction agree (rsi>50 & UP, or rsi<50 & DOWN)
rsi_dir_agree = (
    ((base_df_sorted["rsi_14"] > 50) & (base_df_sorted["direction"] == "UP"))
    | ((base_df_sorted["rsi_14"] < 50) & (base_df_sorted["direction"] == "DOWN"))
).fillna(False)
gate_rows.append(gate_halfhold(rsi_dir_agree, "rsi_dir_agree"))

# 18. micro < mid (ask-side pressure / fade momentum)
gate_rows.append(gate_halfhold(
    (base_df_sorted["micro"] < base_df_sorted["mid"]).fillna(False),
    "micro_lt_mid"))

# 19. EU + fair_edge_bp > 1000 combo
gate_rows.append(gate_halfhold(
    eu_mask & (base_df_sorted["fair_edge_bp"] > 1000).fillna(False),
    "EU_fe_gt1000"))

# 20. EU + cvd_agree_60s
gate_rows.append(gate_halfhold(
    eu_mask & base_df_sorted["cvd_agree_60s"].fillna(False).astype(bool),
    "EU_cvd60"))

# 21. EU + macd_agree
gate_rows.append(gate_halfhold(
    eu_mask & base_df_sorted["macd_agree"].fillna(False).astype(bool),
    "EU_macd"))

# 22. EU + f7_pass
gate_rows.append(gate_halfhold(
    eu_mask & base_df_sorted["f7_pass"].fillna(False).astype(bool),
    "EU_f7"))

# 23. EU + cross_full_agree
gate_rows.append(gate_halfhold(
    eu_mask & base_df_sorted["cross_full_agree"].fillna(False).astype(bool),
    "EU_cross_full"))

# 24. m1v_pass + m5v_pass (both regime agree)
gate_rows.append(gate_halfhold(
    base_df_sorted["m1v_pass"].fillna(False).astype(bool)
    & base_df_sorted["m5v_pass"].fillna(False).astype(bool),
    "m1v_AND_m5v_pass"))

# 25. imb5 direction agree
imb5_dir = (
    ((base_df_sorted["imb5"] > 0) & (base_df_sorted["direction"] == "UP"))
    | ((base_df_sorted["imb5"] < 0) & (base_df_sorted["direction"] == "DOWN"))
).fillna(False)
gate_rows.append(gate_halfhold(imb5_dir, "imb5_dir_agree"))

# ── weekly breakdown ──────────────────────────────────────────────────

print("\nComputing weekly breakdown...")
weekly_rows = []
for wk, wdf in base_df_sorted.groupby("week"):
    if len(wdf) < 5:
        continue
    pnl = wdf["kelly_pnl"]
    wr = (pnl > 0).mean() * 100
    total = float(pnl.sum())
    per_tr = total / len(wdf)
    dt_lo = wdf["dt"].min().date()
    dt_hi = wdf["dt"].max().date()
    weekly_rows.append({
        "week": int(wk), "period": f"{dt_lo}/{dt_hi}", "n": len(wdf),
        "WR_pct": round(wr, 2), "per_tr": round(per_tr, 4),
        "total_kelly": round(total, 2),
        "total_flat5": round(float(wdf["flat5_pnl"].sum()), 2)
    })
    # EU gate
    eu_wdf = wdf[wdf["hour_utc"].between(6, 13)]
    if len(eu_wdf) >= 3:
        eu_pnl = eu_wdf["kelly_pnl"]
        weekly_rows[-1]["EU_n"] = len(eu_wdf)
        weekly_rows[-1]["EU_WR"] = round((eu_pnl > 0).mean() * 100, 2)
        weekly_rows[-1]["EU_per_tr"] = round(float(eu_pnl.sum()) / len(eu_wdf), 4)
        weekly_rows[-1]["EU_total"] = round(float(eu_pnl.sum()), 2)

# ── kelly tier breakdown ──────────────────────────────────────────────

print("\nKelly tier breakdown...")
tier_rows = []
for mult_v in [1.0, 2.0, 3.0, 4.0]:
    tdf = base_df_sorted[base_df_sorted["kelly_mult_v"] == mult_v]
    if len(tdf) == 0:
        continue
    pnl = tdf["kelly_pnl"]
    cumsum = np.cumsum(pnl.values)
    running_max = np.maximum.accumulate(cumsum)
    mdd = float((cumsum - running_max).min())
    total = float(pnl.sum())
    tier_rows.append({
        "kelly_mult": mult_v, "n": len(tdf), "WR_pct": round((pnl > 0).mean() * 100, 2),
        "per_tr": round(total / len(tdf), 4), "total": round(total, 2),
        "MDD": round(mdd, 2),
        "stake_per_fire": 25.0 * mult_v,
        "fe_mean": round(float(tdf["fair_edge_bp"].mean()), 1),
        "vwap_median": round(float(tdf["entry_vwap"].median()), 4),
    })

# ── save results ──────────────────────────────────────────────────────

results_df = pd.DataFrame(results)
gates_df = pd.DataFrame(gate_rows)
weekly_df = pd.DataFrame(weekly_rows)
tier_df = pd.DataFrame(tier_rows)
wf_df = pd.DataFrame(wf_results)

results_df.to_csv(OUT_DIR / "kelly_fullperiod_summary.csv", index=False)
gates_df.to_csv(OUT_DIR / "kelly_fullperiod_gates.csv", index=False)
weekly_df.to_csv(OUT_DIR / "kelly_fullperiod_weekly.csv", index=False)
tier_df.to_csv(OUT_DIR / "kelly_fullperiod_tiers.csv", index=False)
wf_df.to_csv(OUT_DIR / "kelly_fullperiod_wf.csv", index=False)

# ── print summary ─────────────────────────────────────────────────────

pd.set_option("display.max_columns", None)
pd.set_option("display.width", 200)
pd.set_option("display.float_format", lambda x: f"{x:.4f}")

print("\n=== SUMMARY TABLE ===")
print(results_df.to_string(index=False))

print("\n=== WEEKLY BREAKDOWN ===")
print(weekly_df.to_string(index=False))

print("\n=== KELLY TIER BREAKDOWN ===")
print(tier_df.to_string(index=False))

print("\n=== GATE SCAN (both-half holdout) ===")
gcols = ["gate", "n", "retain_pct", "WR", "per_tr", "total", "MDD", "Calmar",
         "h1_per_tr", "h2_per_tr", "verdict"]
print(gates_df[gcols].sort_values("per_tr", ascending=False).to_string(index=False))

print("\n=== WALK-FORWARD 50/50 ===")
print(wf_df.to_string(index=False))

print("\nDone. CSVs in:", OUT_DIR)
