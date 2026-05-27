"""Score microstructure panel (TASK 2, 3, 4, 5).

Loads micro_panel + computes pnl per fire under LegacyConfig fees.

Then:
  TASK 2 — Standalone rules (A-E)
  TASK 3 — Microstructure gates as overlays on top sleeves
  TASK 4 — VPIN proxy from 1s klines
  TASK 5 — Walk-forward + bootstrap on top combos
"""
from __future__ import annotations
import sys, time, os
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra/Desktop/global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))
from load import load_klines_1s  # noqa

OUT_DIR = ROOT / "data" / "v4" / "canonical" / "_results"
WORK = ROOT / "strategy_lab" / "microstructure_2026_05_26"


# -----------------------------------------------------------------
# Load panel + merge with fire universe to get up_usd/dn_usd/vwap
# -----------------------------------------------------------------
def load_panel_with_pnl():
    parts = []
    for asset in ["BTC", "ETH", "SOL"]:
        p = WORK / f"micro_panel_{asset.lower()}.parquet"
        if p.exists():
            parts.append(pd.read_parquet(p))
        else:
            print(f"WARN: missing {p}")
    panel = pd.concat(parts, ignore_index=True)
    print(f"panel rows: {len(panel)}")

    fr5 = pd.read_parquet(OUT_DIR / "hybrid_fire_universe_5m.parquet")
    fr15 = pd.read_parquet(OUT_DIR / "hybrid_fire_universe_15m.parquet")
    fires = pd.concat([fr5, fr15], ignore_index=True)

    # merge on (asset, slug, tf, fire_us, fire_offset_s, outcome)
    keep = ["asset","slug","tf","fire_us","fire_offset_s","outcome",
            "up_fill_ok","dn_fill_ok","up_vwap","up_shares","up_usd",
            "dn_vwap","dn_shares","dn_usd"]
    m = panel.merge(fires[keep], on=["asset","slug","tf","fire_us","fire_offset_s","outcome"], how="left")
    print(f"after merge: {len(m)}, fill_ok both: {((m.up_fill_ok)&(m.dn_fill_ok)).sum()}")
    return m


def legacy_pnl_up(row):
    """If we BET UP, pnl using LegacyConfig (2% on profit-only winning leg)."""
    if not row.up_fill_ok:
        return np.nan
    shares = row.up_shares
    usd = row.up_usd
    won = (row.outcome == "Up")
    if won:
        gross = shares - usd
        return gross - (gross * 0.02 if gross > 0 else 0.0)
    else:
        return -usd


def legacy_pnl_dn(row):
    if not row.dn_fill_ok:
        return np.nan
    shares = row.dn_shares
    usd = row.dn_usd
    won = (row.outcome == "Down")
    if won:
        gross = shares - usd
        return gross - (gross * 0.02 if gross > 0 else 0.0)
    else:
        return -usd


# Vectorized
def add_pnl_cols(df):
    df = df.copy()
    # PnL if we bet UP
    shares_up = df.up_shares.values
    usd_up = df.up_usd.values
    won_up = (df.outcome.values == "Up")
    gross_up = shares_up - usd_up
    pnl_up_won = gross_up - np.where(gross_up > 0, gross_up * 0.02, 0.0)
    pnl_up_lost = -usd_up
    df["pnl_up"] = np.where(won_up, pnl_up_won, pnl_up_lost)
    df["pnl_up"] = np.where(df.up_fill_ok, df["pnl_up"], np.nan)

    shares_dn = df.dn_shares.values
    usd_dn = df.dn_usd.values
    won_dn = (df.outcome.values == "Down")
    gross_dn = shares_dn - usd_dn
    pnl_dn_won = gross_dn - np.where(gross_dn > 0, gross_dn * 0.02, 0.0)
    pnl_dn_lost = -usd_dn
    df["pnl_dn"] = np.where(won_dn, pnl_dn_won, pnl_dn_lost)
    df["pnl_dn"] = np.where(df.dn_fill_ok, df["pnl_dn"], np.nan)
    return df


# -----------------------------------------------------------------
# TASK 2 — Standalone rules
# -----------------------------------------------------------------
def task2_standalone(panel):
    """Test 5 candidate rules from the spec."""
    p = panel.copy()
    # Make sure pnl_up/pnl_dn exist
    p = add_pnl_cols(p)

    # Rule A: bet WITH book_imbalance direction (UP if up_imbalance > 0.5 else DN)
    p["ruleA_dir"] = np.where(p.up_imb5 > 0.5, "Up",
                       np.where(p.up_imb5 < -0.5, "Down", "Skip"))

    # Rule B: bet WITH microprice skew
    # UP if up_micro > up_mid AND dn_micro < dn_mid (top-of-book asymmetry favors UP)
    cond_up_B = (p.up_micro_dev_bps > 0) & (p.dn_micro_dev_bps < 0)
    cond_dn_B = (p.up_micro_dev_bps < 0) & (p.dn_micro_dev_bps > 0)
    p["ruleB_dir"] = np.where(cond_up_B, "Up",
                       np.where(cond_dn_B, "Down", "Skip"))

    # Rule C: bet UP when up-token effective spread narrows AND down-token effective spread widens
    # Asymmetry: up_spread_bps < dn_spread_bps (UP side is tighter)
    cond_up_C = (p.up_spread_bps < p.dn_spread_bps - 50)
    cond_dn_C = (p.dn_spread_bps < p.up_spread_bps - 50)
    p["ruleC_dir"] = np.where(cond_up_C, "Up",
                       np.where(cond_dn_C, "Down", "Skip"))

    # Rule D: bet UP at high quote intensity (>20/5s = ~4/sec) AND book_imbalance_top5 > 0.3
    cond_up_D = (p.up_quote_intensity_5s > 20) & (p.up_imb5 > 0.3)
    cond_dn_D = (p.dn_quote_intensity_5s > 20) & (p.up_imb5 < -0.3)  # symmetric: DN-side
    p["ruleD_dir"] = np.where(cond_up_D, "Up",
                       np.where(cond_dn_D, "Down", "Skip"))

    # Rule E: bet AGAINST extreme book_imbalance (>0.9 or <-0.9) — mean reversion
    cond_up_E = (p.up_imb5 < -0.9)   # UP side has extreme sell pressure -> bet UP (mean-reversion of liquidity shock)
    cond_dn_E = (p.up_imb5 > 0.9)
    p["ruleE_dir"] = np.where(cond_up_E, "Up",
                       np.where(cond_dn_E, "Down", "Skip"))

    rows = []
    for rule in ["ruleA","ruleB","ruleC","ruleD","ruleE"]:
        dcol = f"{rule}_dir"
        for asset in ["BTC","ETH","SOL","ALL"]:
            for tf in ["5m","15m","ALL"]:
                sub = p
                if asset != "ALL":
                    sub = sub[sub.asset == asset]
                if tf != "ALL":
                    sub = sub[sub.tf == tf]
                # Fires where rule fired
                up_mask = (sub[dcol] == "Up") & sub.up_fill_ok
                dn_mask = (sub[dcol] == "Down") & sub.dn_fill_ok
                up_pnl = sub.loc[up_mask, "pnl_up"].dropna()
                dn_pnl = sub.loc[dn_mask, "pnl_dn"].dropna()
                pnl = pd.concat([up_pnl, dn_pnl], ignore_index=True)
                if len(pnl) < 30:
                    continue
                # WR: count UP wins + DN wins
                wins_up = ((sub[dcol] == "Up") & (sub.outcome == "Up") & sub.up_fill_ok).sum()
                wins_dn = ((sub[dcol] == "Down") & (sub.outcome == "Down") & sub.dn_fill_ok).sum()
                n_total = (up_mask.sum() + dn_mask.sum())
                wr = (wins_up + wins_dn) / n_total if n_total else 0.0
                rows.append({
                    "rule": rule, "asset": asset, "tf": tf,
                    "n": int(n_total),
                    "wr": float(wr),
                    "dpt": float(pnl.mean()),
                    "sum_pnl": float(pnl.sum()),
                })
    return pd.DataFrame(rows).sort_values(["dpt"], ascending=False)


# -----------------------------------------------------------------
# TASK 3 — Microstructure as gates on top sleeves
# -----------------------------------------------------------------
def build_gates(panel):
    """Compute boolean gates per fire. Requires we know intended direction.

    We test gates on TWO universes:
      U1: bet UP (use pnl_up)
      U2: bet DOWN (use pnl_dn)
    """
    p = panel.copy()
    # Define gates as bet-direction-aware
    # Each gate(dir): pass iff gate aligns with `dir`
    # For overlay, we apply on top of "baseline universe" — apply only when gate=True

    # gate dict keyed by direction: gates_up[g] = bool series
    # Treat UP-bet first
    gates_up = {}
    gates_dn = {}

    # g_book_imbalance_with: imb5 direction matches bet
    gates_up["g_imb5_with"] = (p.up_imb5 > 0)
    gates_dn["g_imb5_with"] = (p.up_imb5 < 0)  # for DN bet, imbalance OPPOSITE on UP token

    # g_imb5_strong_with: |imb5| > 0.3 and direction matches
    gates_up["g_imb5_strong_with"] = (p.up_imb5 > 0.3)
    gates_dn["g_imb5_strong_with"] = (p.up_imb5 < -0.3)

    # g_microprice_with: microprice dev direction matches bet
    gates_up["g_microprice_with"] = (p.up_micro_dev_bps > 0)
    gates_dn["g_microprice_with"] = (p.dn_micro_dev_bps > 0)

    # g_spread_tight: both < 200 bps
    g_spread_tight = (p.up_spread_bps < 200) & (p.dn_spread_bps < 200)
    gates_up["g_spread_tight"] = g_spread_tight
    gates_dn["g_spread_tight"] = g_spread_tight

    # g_spread_wide_skew: opposite-side spread WIDER (exit liquidity asymmetry)
    gates_up["g_spread_wide_skew"] = (p.up_spread_bps < p.dn_spread_bps)
    gates_dn["g_spread_wide_skew"] = (p.dn_spread_bps < p.up_spread_bps)

    # g_quote_intensity_high: >20/5s (active market)
    g_qi_high = (p.up_quote_intensity_5s > 20) | (p.dn_quote_intensity_5s > 20)
    gates_up["g_quote_intensity_high"] = g_qi_high
    gates_dn["g_quote_intensity_high"] = g_qi_high

    # g_book_slope_steep_against: your side's book is THICK (low slippage if hit)
    # For UP: bid side liquid means low downside cost; ask side steep means easy fill
    gates_up["g_book_slope_steep_against"] = (p.up_ask_slope.abs() < 0.0001)  # ask slope shallow = thick
    gates_dn["g_book_slope_steep_against"] = (p.dn_ask_slope.abs() < 0.0001)

    # g_microprice_skew_with: both microprices favor bet direction
    gates_up["g_microprice_skew_with"] = (p.up_micro_dev_bps > 0) & (p.dn_micro_dev_bps < 0)
    gates_dn["g_microprice_skew_with"] = (p.up_micro_dev_bps < 0) & (p.dn_micro_dev_bps > 0)

    # g_depth_high: depth_2pct > median
    g_depth_high = (p.up_depth_2pct + p.dn_depth_2pct) > (p.up_depth_2pct + p.dn_depth_2pct).median()
    gates_up["g_depth_high"] = g_depth_high
    gates_dn["g_depth_high"] = g_depth_high

    # g_queue_top_high: > 0.1 (you would get queue priority)
    gates_up["g_queue_top_high"] = (p.up_queue_top_bid > 0.1)
    gates_dn["g_queue_top_high"] = (p.dn_queue_top_bid > 0.1)

    # g_imb_change_with: imb5 grew over last 500ms in your direction
    gates_up["g_imb_change_with"] = (p.up_imb5_change_500ms > 0)
    gates_dn["g_imb_change_with"] = (p.dn_imb5_change_500ms > 0)

    return gates_up, gates_dn


def task3_gate_overlay(panel):
    """Apply each gate to the FULL universe of UP/DOWN bets and report:
    n, WR, dpt with/without gate, lift.
    """
    p = add_pnl_cols(panel.copy())
    gates_up, gates_dn = build_gates(p)

    # Baseline: bet UP universe (all up_fill_ok)
    base_up = p[p.up_fill_ok].copy()
    base_dn = p[p.dn_fill_ok].copy()

    rows = []
    # Also do per-asset/tf cuts
    for asset in ["BTC","ETH","SOL","ALL"]:
        for tf in ["5m","15m","ALL"]:
            for bet_side, base, gates in [("UP", base_up, gates_up), ("DOWN", base_dn, gates_dn)]:
                sub = base
                if asset != "ALL":
                    sub = sub[sub.asset == asset]
                if tf != "ALL":
                    sub = sub[sub.tf == tf]
                if len(sub) < 30:
                    continue
                pnl_col = "pnl_up" if bet_side == "UP" else "pnl_dn"
                # Baseline (no gate)
                base_pnl = sub[pnl_col].dropna()
                base_wr = (sub.outcome == bet_side.capitalize()).mean()
                # Just store baseline
                for gname, gmask in gates.items():
                    gm = gmask.reindex(sub.index, fill_value=False)
                    sub2 = sub[gm]
                    if len(sub2) < 30:
                        continue
                    pnl = sub2[pnl_col].dropna()
                    if len(pnl) < 30:
                        continue
                    wr = (sub2.outcome == bet_side.capitalize()).mean()
                    rows.append({
                        "asset": asset, "tf": tf, "bet_side": bet_side,
                        "gate": gname,
                        "n_base": len(sub), "wr_base": float(base_wr),
                        "dpt_base": float(base_pnl.mean()) if len(base_pnl) else 0.0,
                        "n_gate": len(sub2), "wr_gate": float(wr),
                        "dpt_gate": float(pnl.mean()),
                        "sum_pnl_gate": float(pnl.sum()),
                        "wr_lift_pp": float((wr - base_wr) * 100),
                        "dpt_lift": float(pnl.mean() - (base_pnl.mean() if len(base_pnl) else 0.0)),
                    })
    return pd.DataFrame(rows).sort_values(["dpt_lift"], ascending=False)


# -----------------------------------------------------------------
# TASK 4 — VPIN proxy
# -----------------------------------------------------------------
def compute_vpin(asset, bucket_size=None, window=50):
    """VPIN from 1s binance klines.

    bucket_size: total volume per bucket (in base asset units).
                 If None, auto = total_vol / 5000 (~5000 buckets per asset).
    window: rolling window N buckets for VPIN
    """
    df = load_klines_1s(asset=asset, source="binance-spot-ws")
    df = df.dropna(subset=["taker_buy_base"])
    print(f"{asset} 1s valid rows: {len(df)}, span {df.time_period_start_us.min()/1e6:.0f} -> {df.time_period_start_us.max()/1e6:.0f}", flush=True)
    # Each row has: volume_traded, taker_buy_base
    df = df.sort_values("time_period_start_us").reset_index(drop=True).copy()
    df["sell_vol"] = df["volume_traded"] - df["taker_buy_base"]
    df["buy_vol"] = df["taker_buy_base"]
    # Bucket by cumulative volume crossing
    df["cum_vol"] = df["volume_traded"].cumsum()
    total_vol = df["cum_vol"].iloc[-1]
    if bucket_size is None:
        bucket_size = total_vol / 5000.0
    print(f"  total_vol={total_vol:.1f}, bucket_size={bucket_size:.4f}", flush=True)
    df["bucket_id"] = (df["cum_vol"] // bucket_size).astype("int64")
    g = df.groupby("bucket_id").agg(
        buy=("buy_vol","sum"),
        sell=("sell_vol","sum"),
        vol=("volume_traded","sum"),
        t_start_us=("time_period_start_us","min"),
        t_end_us=("time_period_start_us","max"),
    ).reset_index()
    g["asym"] = (g["buy"] - g["sell"]).abs() / g["vol"].where(g["vol"]>0, np.nan)
    g["vpin"] = g["asym"].rolling(window, min_periods=10).mean()
    return g[["bucket_id","t_start_us","t_end_us","vpin"]]


def add_vpin_to_panel(panel, vpin_by_asset):
    """For each fire, asof-lookup VPIN value as of fire_us."""
    p = panel.copy()
    p["vpin"] = np.nan
    for asset, vp in vpin_by_asset.items():
        vp = vp.dropna(subset=["vpin"]).sort_values("t_end_us")
        ts = vp.t_end_us.values
        vals = vp.vpin.values
        mask = (p.asset == asset)
        targets = p.loc[mask, "fire_us"].values
        idx = np.searchsorted(ts, targets, side="right") - 1
        ok = idx >= 0
        out = np.full(len(targets), np.nan)
        out[ok] = vals[idx[ok]]
        p.loc[mask, "vpin"] = out
    return p


def task4_vpin(panel):
    """Compute VPIN per asset, merge into panel, test as gate."""
    vpin_assets = {}
    for asset in ["BTC","ETH","SOL"]:
        vpin_assets[asset] = compute_vpin(asset)
        v = vpin_assets[asset]
        print(f"  {asset} VPIN: {len(v)} buckets, mean={v.vpin.mean():.4f}, median={v.vpin.median():.4f}")
    p = add_vpin_to_panel(panel, vpin_assets)
    p = add_pnl_cols(p)

    rows = []
    for asset in ["BTC","ETH","SOL","ALL"]:
        for tf in ["5m","15m","ALL"]:
            sub = p
            if asset != "ALL":
                sub = sub[sub.asset == asset]
            if tf != "ALL":
                sub = sub[sub.tf == tf]
            # Get median vpin within sub-universe
            med = sub.vpin.median()
            if pd.isna(med):
                continue
            # Test: low VPIN should be cleaner trading
            for bet_side in ["UP","DOWN"]:
                pnl_col = "pnl_up" if bet_side == "UP" else "pnl_dn"
                fill_col = "up_fill_ok" if bet_side == "UP" else "dn_fill_ok"
                base = sub[sub[fill_col]]
                low = base[base.vpin < med]
                high = base[base.vpin >= med]
                if len(low) < 100 or len(high) < 100:
                    continue
                rows.append({
                    "asset": asset, "tf": tf, "bet_side": bet_side,
                    "vpin_median": float(med),
                    "n_low": len(low), "wr_low": (low.outcome==bet_side.capitalize()).mean(),
                    "dpt_low": low[pnl_col].dropna().mean(),
                    "n_high": len(high), "wr_high": (high.outcome==bet_side.capitalize()).mean(),
                    "dpt_high": high[pnl_col].dropna().mean(),
                    "dpt_lift_low_minus_high": low[pnl_col].dropna().mean() - high[pnl_col].dropna().mean(),
                })
    df_t4 = pd.DataFrame(rows)
    if len(df_t4) > 0 and "dpt_lift_low_minus_high" in df_t4.columns:
        df_t4 = df_t4.sort_values("dpt_lift_low_minus_high", ascending=False)
    return df_t4, p


# -----------------------------------------------------------------
# Walk-forward + bootstrap on top combos
# -----------------------------------------------------------------
def walk_forward_and_bootstrap(p_with_vpin, top_combos, train_end_us):
    """For each combo (gate config, asset, tf, bet_side), compute train/test stats + bootstrap p."""
    rows = []
    for combo in top_combos:
        asset, tf, bet_side, gate_expr = combo["asset"], combo["tf"], combo["bet_side"], combo["gate_expr"]
        sub = p_with_vpin.copy()
        if asset != "ALL":
            sub = sub[sub.asset == asset]
        if tf != "ALL":
            sub = sub[sub.tf == tf]
        # Apply gate
        # gate_expr like "g_imb5_with & g_spread_tight"
        # We need pre-computed gates_up/gates_dn
        gates_up, gates_dn = build_gates(sub)
        gates = gates_up if bet_side == "UP" else gates_dn
        gnames = [g.strip() for g in gate_expr.split("&")]
        mask = np.ones(len(sub), dtype=bool)
        for gn in gnames:
            mask &= gates[gn].values
        sub = sub[mask].copy()
        if len(sub) < 60:
            continue
        # Filter by fill
        fill_col = "up_fill_ok" if bet_side == "UP" else "dn_fill_ok"
        pnl_col = "pnl_up" if bet_side == "UP" else "pnl_dn"
        sub = sub[sub[fill_col]]
        if len(sub) < 40:
            continue
        train = sub[sub.fire_us < train_end_us]
        test = sub[sub.fire_us >= train_end_us]
        if len(train) < 20 or len(test) < 10:
            continue
        train_pnl = train[pnl_col].dropna()
        test_pnl = test[pnl_col].dropna()
        train_wr = (train.outcome == bet_side.capitalize()).mean()
        test_wr = (test.outcome == bet_side.capitalize()).mean()
        # bootstrap p on test
        rng = np.random.RandomState(42)
        boot_means = []
        for _ in range(200):
            samp = rng.choice(test_pnl.values, size=len(test_pnl), replace=True)
            boot_means.append(samp.mean())
        boot_means = np.array(boot_means)
        p_neg = float((boot_means < 0).mean())
        rows.append({
            "asset": asset, "tf": tf, "bet_side": bet_side, "gate_expr": gate_expr,
            "n_train": len(train_pnl), "wr_train": train_wr, "dpt_train": train_pnl.mean(),
            "sum_train": train_pnl.sum(),
            "n_test": len(test_pnl), "wr_test": test_wr, "dpt_test": test_pnl.mean(),
            "sum_test": test_pnl.sum(),
            "bootstrap_p_test_neg": p_neg,
            "pass_walkfwd": (test_pnl.mean() > 0 and p_neg < 0.10),
        })
    return pd.DataFrame(rows)


def main():
    import builtins
    bp = builtins.print
    def fp(*a, **k):
        k.setdefault('flush', True)
        bp(*a, **k)
    builtins.print = fp

    print("=== TASK 2-5 SCORING ===")
    panel = load_panel_with_pnl()

    print("\n--- TASK 2: standalone rules ---")
    t2 = task2_standalone(panel)
    t2.to_csv(WORK / "task2_standalone_rules.csv", index=False)
    print(t2.head(20).to_string())

    print("\n--- TASK 3: gate overlays ---")
    t3 = task3_gate_overlay(panel)
    t3.to_csv(WORK / "task3_gate_overlay.csv", index=False)
    print(t3.head(30).to_string())

    print("\n--- TASK 4: VPIN ---")
    t4, p_vpin = task4_vpin(panel)
    t4.to_csv(WORK / "task4_vpin.csv", index=False)
    print(t4.head(20).to_string())

    print("\n--- TASK 5: walk-forward + bootstrap ---")
    # Pick top-10 from TASK3 by sum_pnl_gate (volume-weighted edge)
    top = t3.sort_values("sum_pnl_gate", ascending=False).head(20)
    top_combos = []
    for _, r in top.iterrows():
        top_combos.append({
            "asset": r["asset"], "tf": r["tf"],
            "bet_side": r["bet_side"], "gate_expr": r["gate"],
        })
    # Pick top from TASK2 results too
    # train end: 75% of window
    p_with_pnl = add_pnl_cols(panel)
    t_min = p_with_pnl.fire_us.min()
    t_max = p_with_pnl.fire_us.max()
    train_end_us = int(t_min + (t_max - t_min) * 0.75)
    print(f"  train_end_us = {train_end_us} ({train_end_us/1e6:.0f}s)")
    t5 = walk_forward_and_bootstrap(p_with_pnl, top_combos, train_end_us)
    t5.to_csv(WORK / "task5_walkforward.csv", index=False)
    print(t5.head(20).to_string())

    # Save final panel with vpin for reuse
    p_vpin.to_parquet(OUT_DIR / "microstructure_panel.parquet")
    print(f"\nFINAL: saved {OUT_DIR / 'microstructure_panel.parquet'}")


if __name__ == "__main__":
    main()
