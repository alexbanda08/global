"""Phase 9 lookahead validation — ENGINE-FAITHFUL.

Replicates combined_gate_v2.py's gate firing + PnL semantics, then runs the
SAME engine on five competing gates to determine whether Phase 9 (poly_tfi_2m)
adds anything beyond the same-window BTC return that creates the lookahead
concern.

Gates compared:
  G1  P9_orig        — top-10% |poly_tfi_2m|, sign of TFI = direction (ORIGINAL Phase 9)
  G2  BTC_only       — top-10% |btc_ret_2m|,  sign of BTC = direction (apples-to-apples baseline)
  G3  P9_resid       — top-10% |residual| where residual = TFI − OLS(TFI~btc_ret_2m)
                      i.e. the part of TFI NOT explained by BTC return
  G4  P9 ∩ AGREE     — P9 fires AND sign(TFI) == sign(BTC). Filtered version.
  G5  P9 ∩ DISAGREE  — P9 fires AND sign(TFI) != sign(BTC). Diagnostic — if near
                      coin-flip, BTC is doing all the work.

PnL engines:
  A  Mid-fill   — entry @ $0.50, $0.01 fee  (combined_gate_v2 default)
                  win=+$0.49, loss=-$0.51
  B  Book-walk  — entry @ ask_price_0[bucket_10s=0], 2% taker per side
                  resolves at $1 / $0  (matches sleeve_replay_with_stops.py)

Outputs:
  strategy_lab/results/meta_classifier/phase9_lookahead_engine_results.csv
  strategy_lab/reports/PHASE9_LOOKAHEAD_ENGINE.md
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
UNIV = ROOT / "data" / "v4" / "refresh_2026_05_02" / "btc_markets_minimal.csv"
P9   = ROOT / "strategy_lab" / "data" / "meta_classifier" / "btc_trade_flow_v1.parquet"
BTC  = ROOT / "data" / "v4" / "refresh_2026_05_02" / "binance_spot_1min_full.csv"
BOOK = ROOT / "data" / "v4" / "refresh_2026_05_02" / "btc_book_depth_v3_full.csv"

OUT_CSV = ROOT / "strategy_lab" / "results" / "meta_classifier" / "phase9_lookahead_engine_results.csv"
REPORT  = ROOT / "strategy_lab" / "reports" / "PHASE9_LOOKAHEAD_ENGINE.md"

# combined_gate_v2 PnL constants
ENTRY_MID = 0.50
FEE_FIXED = 0.01

# Realistic book-walk constants (matches sleeve_replay_with_stops.py)
TAKER_FEE_PCT = 0.02   # 2% taker per side


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_btc_prices() -> dict[int, float]:
    df = pd.read_csv(BTC)
    df = df[df["symbol_id"] == "BINANCE_SPOT_BTC_USDT"].copy()
    df["ts"] = (df["time_period_start_us"] // 1_000_000).astype("int64")
    return dict(zip(df["ts"].values, df["price_close"].values))


def attach_btc_return(df: pd.DataFrame, prices: dict[int, float]) -> pd.DataFrame:
    """Forward 2m BTC return: log(close@ws+120s / close@ws). 1m bars."""
    p0 = []
    p2 = []
    for ws in df["window_start_unix"].astype("int64").values:
        p0.append(prices.get(int(ws) - 60))   # close at t=0
        p2.append(prices.get(int(ws) + 60))   # close at t=120s
    df = df.copy()
    df["btc_p0"] = p0
    df["btc_p2"] = p2
    df["btc_ret_2m"] = np.log(df["btc_p2"] / df["btc_p0"])
    return df


def load_book_entries() -> pd.DataFrame:
    """Per-slug, per-token entry book at bucket_10s=0.
    Returns DataFrame indexed by (slug, outcome) with ask_price_0, bid_price_0.
    """
    cols = ["slug", "outcome", "bucket_10s", "bid_price_0", "ask_price_0"]
    df = pd.read_csv(BOOK, usecols=cols)
    df = df[df["bucket_10s"] == 0]
    return df.set_index(["slug", "outcome"])[["ask_price_0", "bid_price_0"]]


# ---------------------------------------------------------------------------
# PnL engines
# ---------------------------------------------------------------------------

def pnl_mid(direction: int, outcome: int) -> float:
    """combined_gate_v2 logic: enter @ $0.50, fee $0.01."""
    win = direction == outcome
    return (1.00 - ENTRY_MID - FEE_FIXED) if win else (0.00 - ENTRY_MID - FEE_FIXED)


def pnl_book(direction: int, outcome: int, ask_at_entry: float) -> float:
    """Book-walk: pay ask, fee 2% taker per side; settle at $1 / $0."""
    if not np.isfinite(ask_at_entry) or ask_at_entry <= 0:
        return float("nan")
    entry_cost = ask_at_entry * (1 + TAKER_FEE_PCT)
    settle = 1.0 if direction == outcome else 0.0
    # Settlement is automatic at $1/$0 — no exit fee on resolution
    return settle - entry_cost


def gate_summary(df: pd.DataFrame, fire_mask: pd.Series, dir_col: str,
                 ask_col: str, label: str) -> dict:
    sub = df.loc[fire_mask & df[dir_col].notna() & df["outcome_up"].notna()].copy()
    if len(sub) == 0:
        return dict(label=label, n=0)
    direction = sub[dir_col].astype(int).values
    outcome   = sub["outcome_up"].astype(int).values
    correct   = (direction == outcome)
    pnl_a = np.array([pnl_mid(d, o)          for d, o in zip(direction, outcome)])
    pnl_b = np.array([pnl_book(d, o, a)
                      for d, o, a in zip(direction, outcome, sub[ask_col].values)])
    valid_b = ~np.isnan(pnl_b)
    return dict(
        label=label,
        n=len(sub),
        hit=correct.mean(),
        # Engine A — mid-fill (combined_gate_v2)
        pnl_a_total=float(pnl_a.sum()),
        pnl_a_mean=float(pnl_a.mean()),
        roi_a=float(pnl_a.mean() / ENTRY_MID),
        # Engine B — book-walked
        n_b=int(valid_b.sum()),
        pnl_b_total=float(np.nansum(pnl_b)),
        pnl_b_mean=float(np.nanmean(pnl_b[valid_b])) if valid_b.any() else float("nan"),
        roi_b=float(np.nanmean(pnl_b[valid_b])) if valid_b.any() else float("nan"),
        avg_ask=float(np.nanmean(sub[ask_col].values)),
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("[1] universe…")
    uni = pd.read_csv(UNIV).dropna(subset=["window_start_unix", "outcome_up"])
    uni["outcome_up"] = uni["outcome_up"].astype(int)

    print("[2] Phase 9 features…")
    p9 = pd.read_parquet(P9)[["slug", "poly_tfi_2m", "poly_trade_count_2m"]]

    print("[3] BTC 1m + 2m return…")
    prices = load_btc_prices()
    df = uni.merge(p9, on="slug", how="left")
    df = attach_btc_return(df, prices)

    print("[4] book depth at bucket_0…")
    book = load_book_entries()

    # Token we'd buy = "Up" if direction==1 else "Down"
    # Compute ask for both tokens, pick later by gate direction
    df = df.merge(
        book.xs("Up", level="outcome").add_suffix("_up"),
        left_on="slug", right_index=True, how="left",
    )
    df = df.merge(
        book.xs("Down", level="outcome").add_suffix("_dn"),
        left_on="slug", right_index=True, how="left",
    )

    # Compute residual TFI: poly_tfi_2m − OLS projection on btc_ret_2m
    fit = df.dropna(subset=["poly_tfi_2m", "btc_ret_2m"]).copy()
    cov = np.cov(fit["btc_ret_2m"].values, fit["poly_tfi_2m"].values, ddof=0)
    beta = cov[0, 1] / cov[0, 0]
    intercept = fit["poly_tfi_2m"].mean() - beta * fit["btc_ret_2m"].mean()
    df["poly_tfi_2m_resid"] = df["poly_tfi_2m"] - (intercept + beta * df["btc_ret_2m"])
    print(f"    OLS: poly_tfi_2m = {intercept:+.4f} + {beta:+.2f}·btc_ret_2m  (residual computed)")

    # Filter to active markets with btc data + book data
    valid = (df["poly_trade_count_2m"] >= 1) & df["btc_ret_2m"].notna() & df["poly_tfi_2m"].notna()
    active = df.loc[valid].copy()
    print(f"    active+btc+p9: {len(active)}")

    # ───────────────────────────────────────────────────────────────────────
    # Define gates (all top-10% percentile thresholds, matching production)
    # ───────────────────────────────────────────────────────────────────────
    P9_PCTILE = 0.90

    p9_thr  = active["poly_tfi_2m"].abs().quantile(P9_PCTILE)
    btc_thr = active["btc_ret_2m"].abs().quantile(P9_PCTILE)
    res_thr = active["poly_tfi_2m_resid"].abs().quantile(P9_PCTILE)

    active["g_p9_orig"]      = active["poly_tfi_2m"].abs() >= p9_thr
    active["g_btc_only"]     = active["btc_ret_2m"].abs()  >= btc_thr
    active["g_p9_resid"]     = active["poly_tfi_2m_resid"].abs() >= res_thr
    active["sign_tfi"]       = (active["poly_tfi_2m"] > 0).astype(int)
    active["sign_btc"]       = (active["btc_ret_2m"]  > 0).astype(int)
    active["sign_resid"]     = (active["poly_tfi_2m_resid"] > 0).astype(int)
    active["agree"]          = active["sign_tfi"] == active["sign_btc"]
    active["g_p9_agree"]     = active["g_p9_orig"] & active["agree"]
    active["g_p9_disagree"]  = active["g_p9_orig"] & ~active["agree"]

    # Direction & ask col selectors
    # We bet on "Up" → ask_price_0_up; on "Down" → ask_price_0_dn
    active["ask_p9"]  = np.where(active["sign_tfi"]   == 1, active["ask_price_0_up"], active["ask_price_0_dn"])
    active["ask_btc"] = np.where(active["sign_btc"]   == 1, active["ask_price_0_up"], active["ask_price_0_dn"])
    active["ask_res"] = np.where(active["sign_resid"] == 1, active["ask_price_0_up"], active["ask_price_0_dn"])

    # ───────────────────────────────────────────────────────────────────────
    # Run gates
    # ───────────────────────────────────────────────────────────────────────
    results = []
    results.append(gate_summary(active, active["g_p9_orig"],     "sign_tfi",   "ask_p9",  "G1 P9_orig (top-10% |TFI|)"))
    results.append(gate_summary(active, active["g_btc_only"],    "sign_btc",   "ask_btc", "G2 BTC_only (top-10% |btc_ret_2m|)"))
    results.append(gate_summary(active, active["g_p9_resid"],    "sign_resid", "ask_res", "G3 P9_resid (TFI − OLS(BTC))"))
    results.append(gate_summary(active, active["g_p9_agree"],    "sign_tfi",   "ask_p9",  "G4 P9 ∩ AGREE"))
    results.append(gate_summary(active, active["g_p9_disagree"], "sign_tfi",   "ask_p9",  "G5 P9 ∩ DISAGREE"))

    # By-timeframe slices for G1, G2, G3
    for tf in ["5m", "15m"]:
        a = active[active["timeframe"] == tf].copy()
        # recompute thresholds within tf for fairness (top-10% of THIS tf)
        for gname, score, dirname, askname, label in [
            ("g_p9_orig",   "poly_tfi_2m",       "sign_tfi",   "ask_p9",  f"G1 P9_orig — {tf}"),
            ("g_btc_only",  "btc_ret_2m",        "sign_btc",   "ask_btc", f"G2 BTC_only — {tf}"),
            ("g_p9_resid",  "poly_tfi_2m_resid", "sign_resid", "ask_res", f"G3 P9_resid — {tf}"),
        ]:
            thr = a[score].abs().quantile(P9_PCTILE)
            mask = a[score].abs() >= thr
            results.append(gate_summary(a, mask, dirname, askname, label))

    # Persist per-bet detail for top-level inspection
    bet_cols = ["slug", "timeframe", "window_start_unix", "outcome_up",
                "poly_tfi_2m", "poly_tfi_2m_resid", "btc_ret_2m",
                "g_p9_orig", "g_btc_only", "g_p9_resid",
                "g_p9_agree", "g_p9_disagree",
                "ask_price_0_up", "ask_price_0_dn"]
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    active[bet_cols].to_csv(OUT_CSV, index=False)
    print(f"[csv] wrote {OUT_CSV}")

    # ───────────────────────────────────────────────────────────────────────
    # Build report
    # ───────────────────────────────────────────────────────────────────────
    L = []
    L += [
        "# Phase 9 Lookahead — Engine-Faithful Test\n",
        "_Generated: 2026-05-05_\n",
        "## What this is\n",
        "Re-runs Phase 9 entries through the **same engine semantics that "
        "`combined_gate_v2.py` uses for the published +143.60 / 77.7% number**, "
        "but with five competing gates so we can isolate how much of P9's "
        "edge is just same-window BTC momentum.\n",
        "## Engine semantics\n",
        f"- **Gate firing**: top-10% percentile threshold on each gate's score (matches `combined_gate_v2`)",
        f"- **Direction**: sign of the gate's score (procyclic for TFI/resid/BTC)",
        f"- **Engine A (mid-fill)**: entry @ $0.50, $0.01 fixed fee → win=+$0.49 / loss=−$0.51 (combined_gate_v2 default)",
        f"- **Engine B (book-walk)**: entry @ `ask_price_0` at `bucket_10s=0`, 2% taker per side; resolves at $1/$0",
        "",
        "## Data\n",
        f"- Active universe: {len(active)} markets ({(active['timeframe']=='5m').sum()} 5m, "
        f"{(active['timeframe']=='15m').sum()} 15m), all with ≥1 trade in 2m + BTC return + P9 features",
        f"- BTC 1m bars: {len(prices)}",
        f"- Median ask_price_0 (Up token):   ${active['ask_price_0_up'].median():.3f}",
        f"- Median ask_price_0 (Down token): ${active['ask_price_0_dn'].median():.3f}",
        f"- Markets missing book@bucket_0:   {active['ask_price_0_up'].isna().sum()} ({active['ask_price_0_up'].isna().mean():.1%})",
        "",
        "## OLS used to build residual\n",
        f"- `poly_tfi_2m = {intercept:+.4f} + ({beta:+.2f}) · btc_ret_2m + ε`",
        f"- Residual (`poly_tfi_2m_resid`) is the part of TFI not explained by same-window BTC return.",
        "",
        "## Head-to-head — ENGINE A (mid-fill)\n",
        "| Gate | n | hit | ROI | total PnL | avg ask |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for r in results:
        if r["n"] == 0:
            continue
        L.append(
            f"| {r['label']} | {r['n']} | {r['hit']:.1%} | "
            f"{r['roi_a']:+.1%} | ${r['pnl_a_total']:+.2f} | "
            f"${r['avg_ask']:.3f} |"
        )

    L += [
        "",
        "## Head-to-head — ENGINE B (book-walked, realistic fills)\n",
        "| Gate | n | hit | mean PnL | total PnL |",
        "|---|---:|---:|---:|---:|",
    ]
    for r in results:
        if r["n"] == 0 or r.get("n_b", 0) == 0:
            continue
        L.append(
            f"| {r['label']} | {r['n_b']} | {r['hit']:.1%} | "
            f"${r['pnl_b_mean']:+.4f} | ${r['pnl_b_total']:+.2f} |"
        )

    # Verdict
    g_p9   = next(r for r in results if r["label"].startswith("G1 P9_orig (top"))
    g_btc  = next(r for r in results if r["label"].startswith("G2 BTC_only"))
    g_res  = next(r for r in results if r["label"].startswith("G3 P9_resid (TFI"))
    g_agr  = next(r for r in results if r["label"].startswith("G4"))
    g_dis  = next(r for r in results if r["label"].startswith("G5"))

    L += [
        "",
        "---",
        "",
        "## VERDICT\n",
        f"- **G1 P9_orig**  → hit {g_p9['hit']:.1%}, ROI_A {g_p9['roi_a']:+.1%}, total_A ${g_p9['pnl_a_total']:+.2f}",
        f"- **G2 BTC_only** → hit {g_btc['hit']:.1%}, ROI_A {g_btc['roi_a']:+.1%}, total_A ${g_btc['pnl_a_total']:+.2f}",
        f"- **G3 P9_resid** → hit {g_res['hit']:.1%}, ROI_A {g_res['roi_a']:+.1%}, total_A ${g_res['pnl_a_total']:+.2f}",
        f"- **G4 AGREE**    → hit {g_agr['hit']:.1%}, ROI_A {g_agr['roi_a']:+.1%}, total_A ${g_agr['pnl_a_total']:+.2f}",
        f"- **G5 DISAGREE** → hit {g_dis['hit']:.1%}, ROI_A {g_dis['roi_a']:+.1%}, total_A ${g_dis['pnl_a_total']:+.2f}",
        "",
    ]
    if g_btc["roi_a"] >= g_p9["roi_a"]:
        L.append("→ **G2 (BTC alone) ≥ G1 (P9)**: the published Phase 9 edge can be reproduced "
                 "by simply firing on the same-window BTC return — Polymarket trade flow is "
                 "redundant.")
    else:
        L.append("→ **G1 > G2**: Phase 9 has some incremental info beyond BTC return alone.")

    if g_res["hit"] < 0.55 or g_res["roi_a"] < 0.05:
        L.append("→ **G3 (residual TFI) is near coin-flip**: the BTC-purged component of "
                 "Phase 9 has no meaningful predictive power. Phase 9's edge is almost "
                 "entirely BTC momentum.")
    else:
        L.append("→ **G3 (residual TFI) holds up**: Phase 9 has independent predictive "
                 "power even after stripping the BTC component.")

    if g_dis["hit"] < 0.50:
        L.append("→ **G5 DISAGREE worse than coin-flip**: when TFI contradicts BTC, P9 is "
                 "actively bad — confirming P9 alone is unreliable.")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(L), encoding="utf-8")
    print(f"\n[report] wrote {REPORT}")
    # Print key lines for terminal
    print("\n=== ENGINE A (mid-fill) ===")
    for r in results:
        if r["n"] > 0 and not r["label"].startswith(("G", " ")):  # all rows
            pass
    for r in results:
        if r["n"] > 0:
            print(f"  {r['label']:40s}  n={r['n']:5d}  hit={r['hit']:.1%}  roi_A={r['roi_a']:+.1%}  pnl_A=${r['pnl_a_total']:+.2f}")


if __name__ == "__main__":
    main()
