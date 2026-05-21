"""Momo + Coinbase LEAD-LAG — chase the inverse-F5 alpha pocket.

Prior finding (MOMO_COINBASE_ADDALPHA_2026_05_09.md):
  - Baseline (B0) HOLD: 949 trades, +$12,846, mean $13.54.
  - F5 (venues agree): 711 trades, +$5,972, mean $8.40.
  - **Disagreement subset (949−711=238 trades): +$6,874, mean $28.88 — 2.13× baseline per-trade.**

Hypothesis: when binance leads and coinbase hasn't caught up yet, there's
sharper directional edge. We slice the disagreement pocket multiple ways
to find the tightest profitable slice.

Variants (signal direction = sign(bin_ret_2m) in all cases):
  B0 baseline                         (reference)
  G1 disagree-raw                     sign(bin) ≠ sign(coin)
  G2 disagree + gap > 5bp             G1 AND |bin - coin| > 5 bp
  G3 disagree + gap > 10bp            G1 AND |bin - coin| > 10 bp
  G4 disagree + coin reversal         G1 AND |coin_ret| > 0.5·|bin_ret|
                                       (strong disagreement, not "coin near zero")
  G5 signed-lead top-quartile         sl = (bin - coin) × sign(bin); sl > rolling q75
                                       AND signal = sign(bin)
  G6 signed-lead top-decile           sl > rolling q90 (tighter slice)

Policies: HOLD / HEDGE_5bp / SELL_V1_5bp / SELL_V2_5bp (anchor=ws / fire).

Outputs:
  data/v4/refresh_2026_05_09/coinbase_lead/{summary,lift,per_trade}.csv
  strategy_lab/reports/MOMO_COINBASE_LEAD_2026_05_09.md
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "strategy_lab"))
sys.path.insert(0, str(ROOT / "strategy_lab" / "meta_classifier"))

from momo_full_universe_validation import (                                # noqa: E402
    load_klines, load_universe, compute_ret_2m, compute_thresholds,
    load_l25_for_asset,
    REFRESH_NEW,
)
from momo_coinbase_addalpha import (                                       # noqa: E402
    load_coinbase_klines, attach_coinbase_features, simulate_with_policy,
    POLICIES, gate_baseline,
)

OUT_DIR = REFRESH_NEW / "coinbase_lead"
OUT_DIR.mkdir(parents=True, exist_ok=True)
REPORT = ROOT / "strategy_lab" / "reports" / "MOMO_COINBASE_LEAD_2026_05_09.md"

VARIANTS = ["B0", "G1", "G2", "G3", "G4", "G5", "G6"]

GAP_5BP = 0.0005   # 5 bp
GAP_10BP = 0.0010  # 10 bp


def _signed_lead_quantile_thresholds(uni: pd.DataFrame, q: float,
                                       lookback_days: int = 14) -> dict:
    """Per (asset, tf, day): rolling 14d quantile q of signed_lead among prior days
    where lead was positive (i.e., binance pulls in trade direction).
    """
    out: dict = {}
    uni = uni.copy()
    uni["signed_lead"] = (uni.ret_2m - uni.coin_ret_2m) * np.sign(uni.ret_2m)
    for (a, tf), g in uni.groupby(["asset", "tf"]):
        g = g.sort_values("ws").reset_index(drop=True)
        for day, _ in g.groupby("day"):
            cutoff = day - pd.Timedelta(days=lookback_days)
            train = g[(g.day >= cutoff) & (g.day < day)]
            samples = train["signed_lead"].dropna().values
            samples = samples[samples > 0]  # restrict to positive lead
            if len(samples) >= 50:
                out[(a, tf, str(day.date()))] = float(np.quantile(samples, q))
            else:
                out[(a, tf, str(day.date()))] = float("nan")
    return out


def apply_lead_variant(uni: pd.DataFrame, variant: str) -> pd.DataFrame:
    """All variants pre-gate by canonical |ret_2m| q90, then add lead-lag filter.
    Direction = sign(bin_ret_2m) in all variants (binance is the lead venue).
    """
    thr_bin = compute_thresholds(uni)
    if variant == "B0":
        return gate_baseline(uni, "ret_2m", thr_bin)

    base = gate_baseline(uni, "ret_2m", thr_bin)
    # Add coin_ret_2m presence
    base = base[base.coin_ret_2m.notna()].copy()
    sig_int = base.signal.map({"UP": 1, "DOWN": -1})
    bin_ret = base.ret_2m
    coin_ret = base.coin_ret_2m

    if variant == "G1":
        keep = (np.sign(bin_ret) != np.sign(coin_ret)) & (coin_ret != 0)
    elif variant == "G2":
        keep = (np.sign(bin_ret) != np.sign(coin_ret)) & ((bin_ret - coin_ret).abs() > GAP_5BP)
    elif variant == "G3":
        keep = (np.sign(bin_ret) != np.sign(coin_ret)) & ((bin_ret - coin_ret).abs() > GAP_10BP)
    elif variant == "G4":
        keep = (np.sign(bin_ret) != np.sign(coin_ret)) & (coin_ret.abs() > 0.5 * bin_ret.abs())
    elif variant in ("G5", "G6"):
        # signed lead = how much binance is ahead in the trade direction
        signed_lead = (bin_ret - coin_ret) * sig_int
        q = 0.75 if variant == "G5" else 0.90
        thr_q = _signed_lead_quantile_thresholds(uni, q)
        thr_col = base.apply(lambda r: thr_q.get((r.asset, r.tf, str(r.day.date())),
                                                    float("nan")), axis=1)
        keep = (signed_lead > thr_col) & thr_col.notna()
    else:
        raise ValueError(f"unknown variant {variant!r}")

    return base[keep.fillna(False)].copy()


def main():
    print("=== Momo + Coinbase LEAD-LAG ===\n")
    print("[1] Loading klines (binance + coinbase)...")
    bin_klines = load_klines()
    coin_klines = load_coinbase_klines()

    print("[2] Loading universe + computing ret_2m...")
    uni = load_universe()
    uni["ret_2m"] = compute_ret_2m(uni, bin_klines)
    uni["abs_ret_2m"] = uni.ret_2m.abs()
    print(f"    universe: {len(uni)} markets ({uni.day.min().date()} → {uni.day.max().date()})")

    print("[3] Attaching coinbase features...")
    uni = attach_coinbase_features(uni, bin_klines, coin_klines)
    print(f"    coin_ret_2m finite: {uni.coin_ret_2m.notna().sum()}")

    print("\n[4] Computing variant gates...")
    gated_per_variant: dict[str, pd.DataFrame] = {}
    for v in VARIANTS:
        g = apply_lead_variant(uni, v)
        gated_per_variant[v] = g
        n_up = int((g.signal == "UP").sum())
        n_down = int((g.signal == "DOWN").sum())
        print(f"    {v}: gated={len(g)} (UP={n_up}, DOWN={n_down})")

    print("\n[5] Loading L25 books per asset and simulating...")
    rows_all = []
    for asset in ("BTC", "ETH", "SOL"):
        gated_mids = set()
        for v in VARIANTS:
            sub = gated_per_variant[v]
            gated_mids |= set(sub[sub.asset == asset].condition_id.unique())
        if not gated_mids:
            print(f"    {asset}: no gated mids, skip")
            continue
        print(f"    [{asset}] mids={len(gated_mids)}")
        books_a, _ = load_l25_for_asset(asset, gated_mids=gated_mids)
        if not books_a:
            print(f"    {asset}: no books, skip")
            continue
        books = {asset: books_a}
        for v in VARIANTS:
            sub = gated_per_variant[v]
            sub = sub[sub.asset == asset]
            if sub.empty:
                continue
            for p in POLICIES:
                for r in sub.to_dict("records"):
                    res = simulate_with_policy(r, bin_klines, books, p)
                    if res is None:
                        continue
                    rows_all.append({
                        "variant": v, "policy": p,
                        "slug": r["slug"], "asset": asset, "tf": r["tf"],
                        "ws": int(r["ws"]), "day": str(r["day"].date()),
                        "signal": r["signal"], "outcome": r["outcome"],
                        "ret_2m": r["ret_2m"], "coin_ret_2m": r.get("coin_ret_2m"),
                        "premium_ws": r.get("premium_ws"),
                        **res,
                    })
        del books_a, books
        print(f"    [{asset}] done — total rows: {len(rows_all)}")

    print(f"\n[6] {len(rows_all)} per-trade rows — aggregating...")
    df = pd.DataFrame(rows_all)
    df.to_csv(OUT_DIR / "per_trade.csv", index=False)

    summary = df.groupby(["variant", "policy"]).agg(
        n=("pnl", "size"),
        n_fired=("fired", "sum"),
        fire_pct=("fired", lambda s: round(100 * s.sum() / max(len(s), 1), 1)),
        hit=("pnl", lambda s: round(100 * (s > 0).mean(), 2)),
        pnl_total=("pnl", lambda s: round(s.sum(), 2)),
        pnl_mean=("pnl", lambda s: round(s.mean(), 4)),
        avg_vwap=("vwap_e", "mean"),
    ).reset_index()
    summary.to_csv(OUT_DIR / "summary.csv", index=False)

    base = summary[summary.variant == "B0"].set_index("policy")
    lift_rows = []
    for v in VARIANTS:
        if v == "B0":
            continue
        for p in POLICIES:
            sub = summary[(summary.variant == v) & (summary.policy == p)]
            if sub.empty or p not in base.index:
                continue
            r = sub.iloc[0]
            b = base.loc[p]
            lift_rows.append({
                "variant": v, "policy": p,
                "n": int(r.n), "n_base": int(b.n),
                "n_pct_of_base": round(100 * r.n / max(b.n, 1), 1),
                "hit_pct": float(r.hit), "hit_base_pct": float(b.hit),
                "hit_lift_pp": round(r.hit - b.hit, 2),
                "pnl_total": float(r.pnl_total),
                "pnl_total_base": float(b.pnl_total),
                "pnl_total_lift": round(r.pnl_total - b.pnl_total, 2),
                "pnl_mean": float(r.pnl_mean),
                "pnl_mean_base": float(b.pnl_mean),
                "pnl_mean_lift": round(r.pnl_mean - b.pnl_mean, 4),
            })
    lift = pd.DataFrame(lift_rows)
    lift.to_csv(OUT_DIR / "lift.csv", index=False)

    print("\n=== Summary ===")
    print(summary.to_string(index=False))
    print("\n=== Lift over B0 ===")
    if not lift.empty:
        print(lift.sort_values(["policy", "pnl_mean_lift"],
                                  ascending=[True, False]).to_string(index=False))

    write_report(summary, lift, gated_per_variant)
    print(f"\n[7] wrote {REPORT}")


def write_report(summary, lift, gated):
    L = [
        "# Momo + Coinbase LEAD-LAG — chasing the inverse-F5 alpha pocket",
        "_Generated: 2026-05-09_",
        "",
        "## Hypothesis",
        "Prior MOMO_COINBASE_ADDALPHA found that the F5 disagreement subset (binance and coinbase 2m returns disagree on sign) had **2.13× baseline per-trade PnL** (~$28.88 vs $13.54). This run slices that pocket multiple ways to find the tightest profitable slice.",
        "",
        "## Variants",
        "- **B0** baseline (reference)",
        "- **G1** disagree-raw — sign(bin) ≠ sign(coin)",
        "- **G2** disagree + |bin−coin| > 5bp",
        "- **G3** disagree + |bin−coin| > 10bp",
        "- **G4** disagree + |coin| > 0.5·|bin| (strong reversal, coin not near zero)",
        "- **G5** signed-lead top-quartile (rolling 14d)",
        "- **G6** signed-lead top-decile (rolling 14d, tighter slice)",
        "",
        "## Gate coverage",
        "| Variant | n_gated |",
        "|---|---:|",
    ]
    for v in VARIANTS:
        L.append(f"| {v} | {len(gated[v])} |")
    L += ["", "## Headline (variant × policy)", "",
          summary.to_markdown(index=False) if not summary.empty else "_no rows_",
          "", "## Lift vs B0 baseline (same policy)", ""]
    if not lift.empty:
        L.append(lift.sort_values(["policy", "pnl_mean_lift"],
                                      ascending=[True, False]).to_markdown(index=False))
    else:
        L.append("_no lift rows_")

    L += ["", "## Verdict (auto)", ""]
    if not lift.empty:
        # For HOLD: highest pnl_mean_lift wins (per-trade edge)
        # Also report best total PnL variant
        for policy in ("HOLD",):
            sub = lift[lift.policy == policy]
            if sub.empty:
                continue
            top_mean = sub.sort_values("pnl_mean_lift", ascending=False).iloc[0]
            top_total = sub.sort_values("pnl_total", ascending=False).iloc[0]
            L.append(f"- **{policy} best per-trade**: `{top_mean.variant}` "
                      f"mean Δ${top_mean.pnl_mean_lift:+.2f} (n={int(top_mean.n)}/"
                      f"{int(top_mean.n_base)}, hit Δ{top_mean.hit_lift_pp:+.2f}pp)")
            L.append(f"- **{policy} best total**: `{top_total.variant}` "
                      f"PnL ${top_total.pnl_total:+.2f} vs base ${top_total.pnl_total_base:+.2f} "
                      f"(Δ${top_total.pnl_total_lift:+.2f})")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
