"""G1 alpha gate — does FLOW alone (or as a momo confirmation filter) have alpha?

Tests two hypotheses against the existing extended_backtest framework:

  H1 (FLOW as momo refiner):
       Among the trades momo would fire on, do those where flow_score CONFIRMS
       the signal direction outperform those where flow_score OPPOSES?
       Pass: confirms_mean − opposes_mean ≥ $+4/trade with p<0.05 perm test on confirms.

  H2 (FLOW standalone signal):
       If we ignore momo entirely and fire on |flow_score| > threshold in the
       direction of flow_score, do we generate alpha?
       Pass: mean $/trade ≥ $+2 on at least 2 of 3 assets, p<0.05.

Outputs:
  strategy_lab/results/meta_classifier/flow_g1_h1.csv   (H1 confirms vs opposes by cell)
  strategy_lab/results/meta_classifier/flow_g1_h2.csv   (H2 standalone alpha by cell)
  strategy_lab/reports/FLOW_G1_GATE_2026_05_07.md       (verdict report)

Usage:
  py -X utf8 -m strategy_lab.confluence.flow.backtest_flow_only

Prereqs:
  data/v4/refresh_2026_05_06/cache/{btc,eth,sol}_flow_features.parquet  (built by build_features.py)
  data/v4/refresh_2026_05_06/market_resolutions_full.csv
  data/v4/refresh_2026_05_06/klines_full.csv
  data/v4/refresh_2026_05_06/tier1_entries/*.parquet
  data/v4/refresh_2026_05_02/{asset}_book_depth_v3_full.csv
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "strategy_lab"))

# Reuse existing engine — no rebuild
from strategy_lab.meta_classifier.extended_backtest_with_robustness import (
    asof,
    load_universe,
    load_klines,
    load_tier1_entries,
    load_book_buckets,
    permutation_test,
    run_cell,
    SPREAD_FILTER,
)

CACHE_DIR = ROOT / "data" / "v4" / "refresh_2026_05_06" / "cache"
OUT_DIR = ROOT / "strategy_lab" / "results" / "meta_classifier"
REPORT = ROOT / "strategy_lab" / "reports" / "FLOW_G1_GATE_2026_05_07.md"

# Thresholds
FLOW_CONFIRM_MIN = 0.10   # |flow_score| floor for "flow has an opinion"
FLOW_STRONG_MIN  = 0.30   # |flow_score| floor for H2 standalone fire
PERM_DRAWS = 1000


def load_flow_features() -> pd.DataFrame:
    """Concat per-asset FLOW parquets. Returns DataFrame keyed by (slug, outcome)."""
    parts = []
    for a in ("btc", "eth", "sol"):
        p = CACHE_DIR / f"{a}_flow_features.parquet"
        if not p.exists():
            print(f"[flow] WARN: missing {p} — skipping {a}")
            continue
        parts.append(pd.read_parquet(p))
    if not parts:
        raise SystemExit("no FLOW feature parquets found — run build_features.py first")
    df = pd.concat(parts, ignore_index=True)
    print(f"[flow] loaded {len(df):,} (slug, outcome) rows from {len(parts)} assets")
    return df


def _split_by_flow(fired: pd.DataFrame, flow_df: pd.DataFrame) -> pd.DataFrame:
    """Attach FLOW score and direction agreement to fired-trades df.

    Adds columns: flow_score, flow_dir, flow_agrees, flow_strong.
      flow_dir       = +1 (flow bullish) / -1 (bearish) / 0 (ambiguous)
      flow_agrees    = bool, signal direction matches flow direction
      flow_strong    = bool, |flow_score| >= FLOW_CONFIRM_MIN
    """
    fired = fired.copy()
    fired["held_outcome"] = np.where(fired["signal"].astype(int) == 1, "Up", "Down")
    fl = flow_df[["slug", "outcome", "flow_score"]].rename(columns={"outcome": "held_outcome"})
    out = fired.merge(fl, on=["slug", "held_outcome"], how="left")
    out["flow_dir"] = np.sign(out["flow_score"]).fillna(0).astype(int)
    # signal: 1=Up→positive flow_score is agreement; 0=Down→negative flow_score is agreement
    sig_dir = np.where(out["signal"].astype(int) == 1, 1, -1)
    out["flow_agrees"] = (out["flow_dir"] == sig_dir) & (out["flow_score"].abs() >= FLOW_CONFIRM_MIN)
    out["flow_opposes"] = (out["flow_dir"] == -sig_dir) & (out["flow_score"].abs() >= FLOW_CONFIRM_MIN)
    out["flow_strong"] = out["flow_score"].abs() >= FLOW_STRONG_MIN
    return out


def _summary(label: str, r: dict) -> str:
    if r.get("n", 0) == 0:
        return f"  {label:30s}  n=0  (no trades)"
    return (f"  {label:30s}  n={r['n']:4d}  hit={r['hit']*100:5.1f}%  "
            f"pnl_total=${r['pnl_total']:+8.2f}  mean=${r['pnl_mean']:+.4f}  "
            f"std=${r['pnl_std']:5.2f}")


def fire_universe() -> tuple[pd.DataFrame, dict, dict, dict]:
    """Re-create the fired-momo universe using the same logic as extended_backtest.main."""
    print("[g1] loading universe + klines + books…")
    uni = load_universe()
    klines = load_klines()
    for a in ("btc", "eth", "sol"):
        m = uni.asset == a
        ws_arr = uni.loc[m, "window_start_unix"].astype("int64").values
        p0 = np.array([asof(klines[a], int(w)) for w in ws_arr])
        p2 = np.array([asof(klines[a], int(w) + 120) for w in ws_arr])
        with np.errstate(divide="ignore", invalid="ignore"):
            uni.loc[m, "asset_ret_2m"] = np.log(p2 / p0)
    active = uni[uni["asset_ret_2m"].notna() & np.isfinite(uni["asset_ret_2m"])].copy()

    entry_books  = {a: load_tier1_entries(a) for a in ("btc", "eth", "sol")}
    bucket_books = {a: load_book_buckets(a)  for a in ("btc", "eth", "sol")}

    fired = []
    for a in ("btc", "eth", "sol"):
        for tf in ("5m", "15m"):
            sub = active[(active.asset == a) & (active.timeframe == tf)].copy()
            if len(sub) < 50:
                continue
            thr = sub["asset_ret_2m"].abs().quantile(0.90)
            f = sub[sub["asset_ret_2m"].abs() >= thr].copy()
            f["signal"] = (f["asset_ret_2m"] > 0).astype(int)
            fired.append(f)
            print(f"[g1] {a.upper()}_{tf}: thr={thr:.5f}  fires={len(f)}/{len(sub)}")
    fired_all = pd.concat(fired, ignore_index=True)
    print(f"[g1] total fires: {len(fired_all)}")
    return fired_all, klines, entry_books, bucket_books


def gate_h1(fired_with_flow: pd.DataFrame, klines, entry_books, bucket_books) -> pd.DataFrame:
    """H1: FLOW as momo refiner — confirms vs opposes."""
    print("\n[H1] FLOW as momo refiner — confirms vs opposes")
    rows = []
    for a in ("btc", "eth", "sol"):
        for tf in ("5m", "15m"):
            sub = fired_with_flow[(fired_with_flow.asset == a) & (fired_with_flow.timeframe == tf)]
            if len(sub) == 0:
                continue
            cell = f"{a.upper()}_{tf}"

            full = run_cell(sub, klines[a], entry_books[a], bucket_books[a],
                             "HOLD", f"{cell}_FULL", a)
            confirms = sub[sub["flow_agrees"]]
            opposes  = sub[sub["flow_opposes"]]
            r_conf = run_cell(confirms, klines[a], entry_books[a], bucket_books[a],
                                "HOLD", f"{cell}_CONFIRM", a) if len(confirms) else {"n": 0}
            r_opp  = run_cell(opposes, klines[a], entry_books[a], bucket_books[a],
                                "HOLD", f"{cell}_OPPOSE", a) if len(opposes) else {"n": 0}

            print(_summary(f"{cell}/full",     full))
            print(_summary(f"{cell}/confirms", r_conf))
            print(_summary(f"{cell}/opposes",  r_opp))

            # Permutation test on confirms
            p_val = float("nan")
            if r_conf.get("n", 0) > 30:
                rng = np.random.default_rng(hash((a, tf, "confirm")) % (2**32))
                p = permutation_test(r_conf.get("per_trade", []), n_permutations=PERM_DRAWS, rng=rng)
                p_val = p["p_value"]

            rows.append(dict(
                cell=cell,
                n_full=full.get("n", 0), pnl_mean_full=full.get("pnl_mean", 0.0),
                n_conf=r_conf.get("n", 0), pnl_mean_conf=r_conf.get("pnl_mean", 0.0),
                n_opp=r_opp.get("n", 0), pnl_mean_opp=r_opp.get("pnl_mean", 0.0),
                edge=r_conf.get("pnl_mean", 0.0) - r_opp.get("pnl_mean", 0.0),
                p_conf=p_val,
            ))
    return pd.DataFrame(rows)


def gate_h2(fired_with_flow: pd.DataFrame, klines, entry_books, bucket_books) -> pd.DataFrame:
    """H2: FLOW alone — fire when |flow_score| >= FLOW_STRONG_MIN, direction = sign(flow).

    Note: this still uses the momo universe (markets that fired top-10% |ret_2m|),
    just overrides the SIGNAL direction with sign(flow_score). For pure-flow
    universe, we'd need a different fire gate — defer to follow-up if H1 passes.
    """
    print("\n[H2] FLOW direction-override (within momo-fired universe)")
    rows = []
    for a in ("btc", "eth", "sol"):
        for tf in ("5m", "15m"):
            sub = fired_with_flow[
                (fired_with_flow.asset == a)
                & (fired_with_flow.timeframe == tf)
                & (fired_with_flow["flow_strong"])
            ].copy()
            if len(sub) == 0:
                continue
            cell = f"{a.upper()}_{tf}"
            # Override signal with sign(flow_score)
            sub["signal"] = (sub["flow_score"] > 0).astype(int)
            r = run_cell(sub, klines[a], entry_books[a], bucket_books[a],
                           "HOLD", f"{cell}_FLOW_DIR", a)
            print(_summary(f"{cell}/flow_dir", r))

            p_val = float("nan")
            if r.get("n", 0) > 30:
                rng = np.random.default_rng(hash((a, tf, "h2")) % (2**32))
                p = permutation_test(r.get("per_trade", []), n_permutations=PERM_DRAWS, rng=rng)
                p_val = p["p_value"]
            rows.append(dict(
                cell=cell,
                n=r.get("n", 0),
                pnl_mean=r.get("pnl_mean", 0.0),
                pnl_total=r.get("pnl_total", 0.0),
                hit=r.get("hit", 0.0),
                p_value=p_val,
            ))
    return pd.DataFrame(rows)


def write_report(h1: pd.DataFrame, h2: pd.DataFrame) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    L = [
        "# FLOW G1 Alpha Gate Report",
        "",
        "**Date:** 2026-05-07",
        "**Test:** Phase 1 G1 gate — does FLOW have alpha?",
        "",
        "## Bar to clear",
        "",
        "- **H1 (FLOW refines momo):** confirms_mean − opposes_mean ≥ $+4/trade, p_conf < 0.05.",
        "- **H2 (FLOW standalone):** mean $/trade ≥ $+2 on at least 2 of 3 assets, p < 0.05.",
        "",
        "## H1 — FLOW as momo refiner",
        "",
        h1.to_markdown(index=False) if not h1.empty else "(no data)",
        "",
        "## H2 — FLOW direction override",
        "",
        h2.to_markdown(index=False) if not h2.empty else "(no data)",
        "",
        "## Verdict",
        "",
    ]

    h1_pass = (
        not h1.empty
        and (h1["edge"] >= 4.0).sum() >= 4              # ≥4 of 6 cells show edge
        and (h1["p_conf"].fillna(1.0) < 0.05).sum() >= 2 # ≥2 cells statistically significant
    )
    h2_pass = (
        not h2.empty
        and (h2.groupby(h2["cell"].str[:3])["pnl_mean"].mean() >= 2.0).sum() >= 2
        and (h2["p_value"].fillna(1.0) < 0.05).sum() >= 2
    )

    if h1_pass:
        L.append("- ✅ **H1 PASS** — proceed with FLOW as momo refiner in confluence stack.")
    else:
        L.append("- ❌ **H1 FAIL** — FLOW does not lift momo signal.")
    if h2_pass:
        L.append("- ✅ **H2 PASS** — FLOW has standalone direction alpha (bonus).")
    else:
        L.append("- ⚠️  **H2 FAIL** — FLOW is not a standalone signal (expected — H1 is the actual gate).")
    L.append("")
    L.append("Overall G1: **" + ("PASS — proceed to Phase 2" if h1_pass else "FAIL — re-examine FLOW features") + "**")

    REPORT.write_text("\n".join(L), encoding="utf-8")
    print(f"\n[report] wrote {REPORT}")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    flow_df = load_flow_features()
    fired_all, klines, entry_books, bucket_books = fire_universe()
    fired_with_flow = _split_by_flow(fired_all, flow_df)

    coverage = float(fired_with_flow["flow_score"].notna().mean())
    print(f"\n[g1] flow_score coverage: {coverage*100:.1f}% of fired trades")
    if coverage < 0.5:
        print("[g1] WARN: <50% coverage. Some markets in fired universe lack FLOW features.")

    h1 = gate_h1(fired_with_flow, klines, entry_books, bucket_books)
    h1.to_csv(OUT_DIR / "flow_g1_h1.csv", index=False)

    h2 = gate_h2(fired_with_flow, klines, entry_books, bucket_books)
    h2.to_csv(OUT_DIR / "flow_g1_h2.csv", index=False)

    write_report(h1, h2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
