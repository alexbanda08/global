"""Validate the F2 fade-flow trigger discovered via trade-tape.

Two candidate variants from the grand search:

  A. FADE-flow (broad):
       n_trades_5s >= 10
       |flow_imbalance_5s| >= 0.1
       sum_asks >= 1.005
       max_asz >= 100
       offset >= 60s
       Direction: FADE (buy opposite of recent flow)
       Sample: n=8246, WR=46.01%, +$0.35/trade, +$2909 total

  B. FOLLOW-flow (cherry-pick, high-WR):
       n_trades_5s >= 100
       |flow_imbalance_5s| >= 0.3
       sum_asks >= 1.01
       max_asz >= 500
       offset >= 120s
       Direction: FOLLOW (buy same side as recent flow)
       Sample: n=473, WR=86.26%, +$0.31/trade, +$146 total

For both, compute: G1 (positive mean), G3 (perm test), G4 (bootstrap CI),
G2 (walkforward 5d train / 2d test).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
from load import load_chainlink_asof, asof_strict, load_orderbook_l25_streaming  # noqa: E402
from cyclops.validate.permutation import permutation_test  # noqa: E402
from cyclops.validate.bootstrap import bootstrap_mean_ci  # noqa: E402
from cyclops.validate.walkforward import walkforward_test  # noqa: E402

CACHE = Path(__file__).resolve().parents[1] / "wallet_hunt" / "cache"
WINDOW_S = {"5m": 300, "15m": 900}
FEE = 0.07


def parse_slug(slug):
    p = slug.split("-")
    if len(p) != 4 or p[1] != "updown": return None
    return p[0].upper(), p[2], int(p[3])


def derive_outcome(slug, rtds):
    info = parse_slug(slug)
    if info is None: return None
    a, tf, st = info
    se = st + WINDOW_S[tf]
    ts, px = rtds.get(a, (None, None))
    if ts is None: return None
    strike = asof_strict(ts, px, st * 1_000_000)
    settle = asof_strict(ts, px, se * 1_000_000)
    if not (strike > 0 and settle > 0): return None
    return "Up" if settle > strike else "Down"


def hold_pnl(entry_px, won):
    if not (0 < entry_px < 1): return 0.0
    fee = FEE * entry_px * (1 - entry_px)
    return (1 - entry_px - fee) if won else (-entry_px - fee)


def build_dataset():
    """Reload feature parquet + add winner + book + filter to BTC up-down."""
    df = pd.read_parquet(CACHE / "_f2_trade_flow_features.parquet")
    rtds = {a: load_chainlink_asof(a) for a in ("BTC", "ETH", "SOL")}
    df["winner"] = df.slug.map(lambda s: derive_outcome(s, rtds))
    df = df.dropna(subset=["winner"]).copy()

    slugs = sorted(df.slug.unique())
    ob = load_orderbook_l25_streaming("btc", slugs=set(slugs))

    df["up_ask"] = np.nan; df["dn_ask"] = np.nan
    df["up_asz"] = np.nan; df["dn_asz"] = np.nan
    for slug in slugs:
        idx = df.index[df.slug == slug]
        if len(idx) == 0: continue
        bu = ob.get((slug, "Up")); bd = ob.get((slug, "Down"))
        if bu is None or bd is None: continue
        ts_us = df.loc[idx, "fire_ts_us"].values
        for tag, rec in (("up", bu), ("dn", bd)):
            ts_arr, ap, asz, _, _ = rec
            pos = np.clip(np.searchsorted(ts_arr, ts_us, side="right") - 1, 0, None)
            df.loc[idx, f"{tag}_ask"] = ap[pos, 0]
            df.loc[idx, f"{tag}_asz"] = asz[pos, 0]

    df["sum_asks"] = df.up_ask + df.dn_ask
    df["max_asz"] = df[["up_asz", "dn_asz"]].max(axis=1)
    df = df.dropna(subset=["up_ask", "dn_ask"]).copy()
    df["slot_start_s"] = df.slug.apply(
        lambda s: int(s.rsplit("-", 1)[1]) if s.startswith("btc-updown-") else np.nan
    )
    df = df.dropna(subset=["slot_start_s"]).copy()
    df["offset_s"] = (df.fire_ts_us // 1_000_000).astype(int) - df.slot_start_s.astype(int)
    df["ws_s"] = df.slot_start_s.astype(int)
    return df


def filter_apply(df, n_thr, flow_thr, sa_thr, asz_thr, off_thr):
    return df[
        (df.n_trades_5s >= n_thr)
        & (df.flow_imbalance_5s.abs() >= flow_thr)
        & (df.sum_asks >= sa_thr)
        & (df.max_asz >= asz_thr)
        & (df.offset_s >= off_thr)
    ].copy()


def attach_trades(df, direction_mode):
    """direction_mode = 'fade' or 'follow'."""
    df = df.copy()
    if direction_mode == "fade":
        df["direction"] = np.where(df.flow_imbalance_5s > 0, "Down", "Up")
    else:
        df["direction"] = np.where(df.flow_imbalance_5s > 0, "Up", "Down")
    df["entry_px"] = np.where(df.direction == "Up", df.up_ask, df.dn_ask)
    df["entry_size"] = np.where(df.direction == "Up", df.up_asz, df.dn_asz)
    df = df[df.entry_px.notna() & (df.entry_px > 0) & (df.entry_px < 1)].copy()
    df["won"] = (df.direction == df.winner)
    df["outcome_truth"] = df.winner
    df["shares"] = (1.0 / df.entry_px).clip(upper=df.entry_size)
    df["stake_usd"] = df.shares * df.entry_px
    df["pnl_usd"] = df.apply(
        lambda r: r.shares * hold_pnl(r.entry_px, bool(r.won)), axis=1
    )
    return df


def run_validation(label, df, params, mode):
    """Apply trigger + direction, then run gates."""
    flt = filter_apply(df, **params)
    trades = attach_trades(flt, mode)
    if len(trades) < 50:
        print(f"\n  {label}: insufficient n ({len(trades)})")
        return

    print(f"\n{'=' * 70}")
    print(f"[{label}]  mode={mode}  thresholds={params}")
    print(f"{'=' * 70}")
    print(f"  n_trades   : {len(trades)}")
    print(f"  WR         : {trades.won.mean()*100:.2f}%")
    print(f"  mean entry : ${trades.entry_px.mean():.4f}")
    print(f"  mean PnL   : ${trades.pnl_usd.mean():+.4f}")
    print(f"  total PnL  : ${trades.pnl_usd.sum():+.2f}  (=$25×{trades.pnl_usd.sum()*25:+.2f})")

    # Save the trade tape
    out = CACHE / f"_f2_v2_validated_{label}.csv"
    trades_save = trades.copy()
    trades_save["fired"] = True
    trades_save.to_csv(out, index=False)
    print(f"  saved -> {out.name}")

    # G3 permutation
    perm = permutation_test(trades_save, n_permutations=5000, seed=42)
    p = perm["p_value"]
    print(f"  G3 perm: p={p:.4f}  -> {'PASS' if p < 0.05 else 'FAIL'}")

    # G4 bootstrap
    boot = bootstrap_mean_ci(trades_save, n_boot=20000, seed=42)
    lo, hi = boot["ci_lower"], boot["ci_upper"]
    print(f"  G4 boot: CI [{lo:+.4f} .. {hi:+.4f}]  P(mean<=0)={boot['frac_negative_draws']*100:.2f}%  "
          f"-> {'PASS' if lo > 0 else 'FAIL'}")

    # G2 walkforward
    wf = walkforward_test(trades_save, train_days=5, test_days=2)
    print(f"  G2 walk: {wf['n_positive']}/{wf['n_windows']} windows positive ({wf['frac_positive']*100:.1f}%)  -> {wf['verdict']}")
    for w in wf["windows"]:
        marker = "+" if w["mean_pnl"] > 0 else "-"
        print(f"    [{marker}] day {w['test_start_day']}-{w['test_end_day']}  "
              f"n={w['n_trades']:4d}  mean=${w['mean_pnl']:+.4f}")


def main():
    print("Building dataset (winner + book + offset)...")
    df = build_dataset()
    print(f"  dataset rows: {len(df):,}")

    # Variant A: broad fade (high-volume strategy)
    run_validation(
        label="A_fade_broad",
        df=df,
        params={"n_thr": 10, "flow_thr": 0.1, "sa_thr": 1.005, "asz_thr": 100, "off_thr": 60},
        mode="fade",
    )

    # Variant B: cherry-pick follow (high-WR)
    run_validation(
        label="B_follow_cherry",
        df=df,
        params={"n_thr": 100, "flow_thr": 0.3, "sa_thr": 1.01, "asz_thr": 500, "off_thr": 120},
        mode="follow",
    )

    # Variant C: middle ground (best balance)
    run_validation(
        label="C_fade_mid",
        df=df,
        params={"n_thr": 50, "flow_thr": 0.2, "sa_thr": 1.005, "asz_thr": 200, "off_thr": 60},
        mode="fade",
    )

    # Variant D: tighter fade (higher WR fade)
    run_validation(
        label="D_fade_tight",
        df=df,
        params={"n_thr": 100, "flow_thr": 0.3, "sa_thr": 1.005, "asz_thr": 500, "off_thr": 60},
        mode="fade",
    )


if __name__ == "__main__":
    main()
