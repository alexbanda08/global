"""Score MLOFI panel — TASK 2 (standalone rules), TASK 3 (L1 vs MLOFI comparison),
TASK 4 (gate overlay on top sleeves), TASK 5 (lockbox 3-way validation).

Inputs:
  mlofi_panel_{btc,eth,sol}.parquet  (MLOFI features per fire)
  hybrid_fire_universe_{5m,15m}.parquet  (PnL + outcome + fill metadata)

Outputs:
  task2_standalone_rules.csv
  task3_mlofi_vs_l1.csv
  task4_gate_overlay.csv
  task5_lockbox.csv
"""
from __future__ import annotations
import sys, os
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
WORK = ROOT / "strategy_lab" / "mlofi_2026_05_26"
OUT_DIR = ROOT / "data" / "v4" / "canonical" / "_results"


# ---------------------------------------------------------------------------
# Panel load + PnL augmentation (LegacyConfig: 2% on profit, winning leg only)
# ---------------------------------------------------------------------------

def load_panel():
    parts = []
    for asset in ["BTC", "ETH", "SOL"]:
        p = WORK / f"mlofi_panel_{asset.lower()}.parquet"
        if p.exists():
            parts.append(pd.read_parquet(p))
        else:
            print(f"WARN: missing {p}", flush=True)
    panel = pd.concat(parts, ignore_index=True)
    print(f"  loaded {len(panel)} MLOFI rows", flush=True)
    return panel


def load_panel_with_pnl_and_returns():
    panel = load_panel()
    fr5 = pd.read_parquet(OUT_DIR / "hybrid_fire_universe_5m.parquet")
    fr15 = pd.read_parquet(OUT_DIR / "hybrid_fire_universe_15m.parquet")
    fires = pd.concat([fr5, fr15], ignore_index=True)
    keep = ["asset","slug","tf","fire_us","fire_offset_s","outcome",
            "up_fill_ok","dn_fill_ok","up_vwap","up_shares","up_usd",
            "dn_vwap","dn_shares","dn_usd",
            "ret_2m_at_ws","mag_ratio","vwap_since_open_bps","prod_q90"]
    m = panel.merge(
        fires[keep],
        on=["asset","slug","tf","fire_us","fire_offset_s","outcome"], how="left",
    )
    # Add PnL columns (LegacyConfig: 2% on winning-leg profit)
    shares_up = m.up_shares.values
    usd_up = m.up_usd.values
    won_up = (m.outcome.values == "Up")
    gross_up = shares_up - usd_up
    pnl_up_won = gross_up - np.where(gross_up > 0, gross_up * 0.02, 0.0)
    pnl_up_lost = -usd_up
    m["pnl_up"] = np.where(won_up, pnl_up_won, pnl_up_lost)
    m["pnl_up"] = np.where(m.up_fill_ok, m["pnl_up"], np.nan)

    shares_dn = m.dn_shares.values
    usd_dn = m.dn_usd.values
    won_dn = (m.outcome.values == "Down")
    gross_dn = shares_dn - usd_dn
    pnl_dn_won = gross_dn - np.where(gross_dn > 0, gross_dn * 0.02, 0.0)
    pnl_dn_lost = -usd_dn
    m["pnl_dn"] = np.where(won_dn, pnl_dn_won, pnl_dn_lost)
    m["pnl_dn"] = np.where(m.dn_fill_ok, m["pnl_dn"], np.nan)
    print(f"  merged: {len(m)}, with both-side-fill: {(m.up_fill_ok & m.dn_fill_ok).sum()}", flush=True)
    return m


# Add 7d rolling zscore of mlofi_l5_30s
def add_zscores(p):
    """Z-score each MLOFI variable using 7d rolling stdev computed per-asset."""
    p = p.copy()
    p = p.sort_values(["asset","fire_us"]).reset_index(drop=True)
    for asset in ["BTC","ETH","SOL"]:
        mask = p.asset == asset
        if not mask.any():
            continue
        sub = p[mask].set_index("fire_us")
        # use 7d (7*86400e6 us) rolling — use pandas rolling time-based
        sub2 = sub.copy()
        sub2.index = pd.to_datetime(sub2.index, unit="us")
        for col in ["up_mlofi_l5_30s", "dn_mlofi_l5_30s", "mlofi_skew_l5_30s",
                     "up_mlofi_l25_30s", "dn_mlofi_l25_30s", "mlofi_skew_l25_30s",
                     "up_ofi_l1_30s", "dn_ofi_l1_30s"]:
            if col not in sub2.columns:
                continue
            rstd = sub2[col].rolling("7D", min_periods=200).std()
            rmean = sub2[col].rolling("7D", min_periods=200).mean()
            z = (sub2[col] - rmean) / rstd.replace(0, np.nan)
            p.loc[mask, f"{col}_z7d"] = z.values
    return p


# ---------------------------------------------------------------------------
# TASK 2 — Standalone rules
# ---------------------------------------------------------------------------

def task2_standalone(panel):
    """Test 5 candidate rules per spec:
    O-A: bet WITH sign(mlofi_l5_30s)  (uses UP token mlofi to choose direction)
    O-B: bet WITH sign(mlofi_skew_l5_30s)
    O-C: bet UP when up_mlofi_l5_30s > threshold AND dn_mlofi_l5_30s < -threshold
    O-D: bet AGAINST sign(mlofi_skew) when |z| > 2 (mean revert on extremes)
    O-E: bet WITH sign(mlofi_l25_30s) (full-book MLOFI)
    """
    p = panel.copy()

    # Rule O-A
    p["O_A_dir"] = np.where(p.up_mlofi_l5_30s > 0, "Up",
                       np.where(p.up_mlofi_l5_30s < 0, "Down", "Skip"))

    # Rule O-B
    p["O_B_dir"] = np.where(p.mlofi_skew_l5_30s > 0, "Up",
                       np.where(p.mlofi_skew_l5_30s < 0, "Down", "Skip"))

    # Rule O-C: asymmetric: UP token has buy-side, DN token has sell-side
    # Threshold: per-asset stddev as scale (use median-abs as robust proxy)
    thr_per_asset = p.groupby("asset")["up_mlofi_l5_30s"].apply(
        lambda s: s.abs().median()).to_dict()
    p["_thr"] = p.asset.map(thr_per_asset).fillna(0.0)
    cond_up_C = (p.up_mlofi_l5_30s > p._thr) & (p.dn_mlofi_l5_30s < -p._thr)
    cond_dn_C = (p.up_mlofi_l5_30s < -p._thr) & (p.dn_mlofi_l5_30s > p._thr)
    p["O_C_dir"] = np.where(cond_up_C, "Up",
                       np.where(cond_dn_C, "Down", "Skip"))

    # Rule O-D: bet AGAINST sign(mlofi_skew) when |z| > 2
    if "mlofi_skew_l5_30s_z7d" in p.columns:
        p["O_D_dir"] = np.where((p.mlofi_skew_l5_30s_z7d > 2), "Down",
                           np.where((p.mlofi_skew_l5_30s_z7d < -2), "Up", "Skip"))
    else:
        # fallback: use 99th-pctl heuristic
        p["O_D_dir"] = "Skip"

    # Rule O-E: full-book L25 MLOFI
    p["O_E_dir"] = np.where(p.up_mlofi_l25_30s > 0, "Up",
                       np.where(p.up_mlofi_l25_30s < 0, "Down", "Skip"))

    # Score each
    rows = []
    for rule in ["O_A","O_B","O_C","O_D","O_E"]:
        dcol = f"{rule}_dir"
        for asset in ["BTC","ETH","SOL","ALL"]:
            for tf in ["5m","15m","ALL"]:
                sub = p
                if asset != "ALL":
                    sub = sub[sub.asset == asset]
                if tf != "ALL":
                    sub = sub[sub.tf == tf]
                up_mask = (sub[dcol] == "Up") & sub.up_fill_ok
                dn_mask = (sub[dcol] == "Down") & sub.dn_fill_ok
                up_pnl = sub.loc[up_mask, "pnl_up"].dropna()
                dn_pnl = sub.loc[dn_mask, "pnl_dn"].dropna()
                pnl = pd.concat([up_pnl, dn_pnl], ignore_index=True)
                if len(pnl) < 30:
                    continue
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
                    "median_pnl": float(pnl.median()),
                    "sharpe_dpt": float(pnl.mean() / pnl.std() * np.sqrt(252)) if pnl.std()>0 else 0.0,
                })
    return pd.DataFrame(rows).sort_values("dpt", ascending=False)


# ---------------------------------------------------------------------------
# TASK 3 — MLOFI vs L1 OFI: predictive power on future 60s return
# ---------------------------------------------------------------------------

def task3_mlofi_vs_l1(panel):
    """Compare correlation/R^2 of MLOFI vs L1-OFI with future 60s return.

    'Future 60s return' for this purpose: ret on BTC/ETH/SOL price from fire_us
    to fire_us + 60s. We can use load_klines_1s for asof lookup.
    """
    import sys as _sys
    _sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
    from load import load_klines_1s

    p = panel.copy()
    # Add future 60s return per fire
    p["fut_ret_60s"] = np.nan

    for asset in ["BTC", "ETH", "SOL"]:
        k = load_klines_1s(asset=asset, source="binance-spot-ws")
        if len(k) == 0:
            # try vision
            k = load_klines_1s(asset=asset, source="binance-vision")
        if len(k) == 0:
            print(f"  WARN: no 1s klines for {asset}; skipping", flush=True)
            continue
        ts = k.time_period_start_us.values.astype("int64")
        prc = k.price_close.values.astype("float64")
        # Asof at fire_us and fire_us + 60s
        mask = p.asset == asset
        fire = p.loc[mask, "fire_us"].values.astype("int64")
        fire_future = fire + 60_000_000
        idx0 = np.searchsorted(ts, fire, side="right") - 1
        idx1 = np.searchsorted(ts, fire_future, side="right") - 1
        ok = (idx0 >= 0) & (idx1 >= 0)
        p0 = np.full(len(fire), np.nan)
        p1 = np.full(len(fire), np.nan)
        p0[ok] = prc[idx0[ok]]
        p1[ok] = prc[idx1[ok]]
        ret = np.log(p1 / p0)
        p.loc[mask, "fut_ret_60s"] = ret
    n_finite = p.fut_ret_60s.notna().sum()
    print(f"  future_60s_return populated: {n_finite}/{len(p)} fires", flush=True)

    # Pair each MLOFI variant with fut_ret; compute corr + R^2 + sign-accuracy
    feats = {
        "ofi_l1_30s_up": p["up_ofi_l1_30s"],
        "ofi_l1_30s_dn": p["dn_ofi_l1_30s"],
        "ofi_skew_l1_30s": p["ofi_skew_l1_30s"],
        "mlofi_l5_30s_up": p["up_mlofi_l5_30s"],
        "mlofi_l5_30s_dn": p["dn_mlofi_l5_30s"],
        "mlofi_skew_l5_30s": p["mlofi_skew_l5_30s"],
        "mlofi_l25_30s_up": p["up_mlofi_l25_30s"],
        "mlofi_skew_l25_30s": p["mlofi_skew_l25_30s"],
        "mlofi_l5_60s_up": p["up_mlofi_l5_60s"],
        "mlofi_skew_l5_60s": p["mlofi_skew_l5_60s"],
    }
    rows = []
    for asset in ["BTC","ETH","SOL","ALL"]:
        sub = p if asset == "ALL" else p[p.asset == asset]
        sub = sub[sub.fut_ret_60s.notna()]
        if len(sub) < 100:
            continue
        y = sub.fut_ret_60s.values
        for fname, fvals in feats.items():
            x = fvals.reindex(sub.index).values
            ok = np.isfinite(x) & np.isfinite(y)
            if ok.sum() < 100:
                continue
            xv, yv = x[ok], y[ok]
            corr = np.corrcoef(xv, yv)[0, 1] if xv.std() > 0 else 0.0
            r2 = corr ** 2
            # Sign accuracy
            sign_match = (np.sign(xv) == np.sign(yv)) & (np.sign(xv) != 0) & (np.sign(yv) != 0)
            sign_acc = sign_match.sum() / max(((np.sign(xv) != 0) & (np.sign(yv) != 0)).sum(), 1)
            # RMSE of predicting yv from linear regression on xv
            # OLS slope = cov(x,y)/var(x)
            if xv.std() > 0:
                slope = np.cov(xv, yv, ddof=0)[0, 1] / np.var(xv)
                intercept = yv.mean() - slope * xv.mean()
                yhat = slope * xv + intercept
                rmse = np.sqrt(((yv - yhat) ** 2).mean())
            else:
                rmse = np.nan
            rmse_naive = yv.std()
            rmse_reduction = (rmse_naive - rmse) / rmse_naive if rmse_naive > 0 else 0.0
            rows.append({
                "asset": asset, "feature": fname,
                "n": int(ok.sum()),
                "corr": float(corr), "r2": float(r2),
                "sign_acc": float(sign_acc),
                "rmse_naive": float(rmse_naive), "rmse_pred": float(rmse),
                "rmse_reduction_pct": float(rmse_reduction * 100),
            })
    df = pd.DataFrame(rows)
    return df


# ---------------------------------------------------------------------------
# TASK 4 — MLOFI as gate overlay on top sleeves
# ---------------------------------------------------------------------------

def build_mlofi_gates(p):
    """MLOFI binary gates per spec. Direction-aware (UP-bet vs DN-bet)."""
    gates_up = {}
    gates_dn = {}

    # g_mlofi_l5_with: mlofi direction matches bet
    # For UP-bet: WITH means up_mlofi_l5_30s > 0
    gates_up["g_mlofi_l5_with"] = (p.up_mlofi_l5_30s > 0)
    gates_dn["g_mlofi_l5_with"] = (p.dn_mlofi_l5_30s > 0)

    # g_mlofi_l25_with: full-book MLOFI matches direction
    gates_up["g_mlofi_l25_with"] = (p.up_mlofi_l25_30s > 0)
    gates_dn["g_mlofi_l25_with"] = (p.dn_mlofi_l25_30s > 0)

    # g_mlofi_skew_with: skew matches bet
    # For UP-bet: WITH means mlofi_skew > 0 (UP-side dominates)
    gates_up["g_mlofi_skew_with"] = (p.mlofi_skew_l5_30s > 0)
    gates_dn["g_mlofi_skew_with"] = (p.mlofi_skew_l5_30s < 0)

    # g_mlofi_strong_with: |z| > 1.5 AND direction matches
    if "up_mlofi_l5_30s_z7d" in p.columns:
        gates_up["g_mlofi_strong_with"] = (p.up_mlofi_l5_30s_z7d > 1.5)
        gates_dn["g_mlofi_strong_with"] = (p.dn_mlofi_l5_30s_z7d > 1.5)
    else:
        gates_up["g_mlofi_strong_with"] = (p.up_mlofi_l5_30s > p.up_mlofi_l5_30s.abs().quantile(0.85))
        gates_dn["g_mlofi_strong_with"] = (p.dn_mlofi_l5_30s > p.dn_mlofi_l5_30s.abs().quantile(0.85))

    # g_mlofi_no_extreme: |z| < 2 (avoid liquidity shocks)
    if "up_mlofi_l5_30s_z7d" in p.columns:
        no_ext = (p.up_mlofi_l5_30s_z7d.abs() < 2) & (p.dn_mlofi_l5_30s_z7d.abs() < 2)
        gates_up["g_mlofi_no_extreme"] = no_ext
        gates_dn["g_mlofi_no_extreme"] = no_ext
    else:
        no_ext = (p.up_mlofi_l5_30s.abs() < p.up_mlofi_l5_30s.abs().quantile(0.95))
        gates_up["g_mlofi_no_extreme"] = no_ext
        gates_dn["g_mlofi_no_extreme"] = no_ext

    return gates_up, gates_dn


def define_sleeves(p):
    """Sleeves derived from fire_universe features (matches the microstructure overlay
    sleeve set used in microstructure_2026_05_26/sleeve_overlay.py).
    """
    sleeves = {}
    m1 = (p.ret_2m_at_ws.abs() >= 0.0005) & (p.mag_ratio >= 1.5)
    dir1 = np.where(p.ret_2m_at_ws > 0, "Up", "Down")
    sleeves["momo_v2_anywhere"] = (m1, pd.Series(dir1, index=p.index))

    m2 = (p.ret_2m_at_ws.abs() >= 0.001) & (p.mag_ratio >= 2.5)
    dir2 = np.where(p.ret_2m_at_ws > 0, "Up", "Down")
    sleeves["momo_v2_strong"] = (m2, pd.Series(dir2, index=p.index))

    m3 = (p.fire_offset_s.isin([120, 240, 360, 480])) & (p.ret_2m_at_ws.abs() >= 0.0003)
    dir3 = np.where(p.ret_2m_at_ws > 0, "Up", "Down")
    sleeves["sniper_midwindow"] = (m3, pd.Series(dir3, index=p.index))

    m4 = (p.ret_2m_at_ws.abs() < 0.0003)
    dir4 = np.where(p.ret_2m_at_ws > 0, "Down", "Up")  # FADE
    sleeves["fade_small"] = (m4, pd.Series(dir4, index=p.index))

    m5 = (p.ret_2m_at_ws.abs() >= 0.0015) & (p.mag_ratio >= 3.0)
    dir5 = np.where(p.ret_2m_at_ws > 0, "Up", "Down")
    sleeves["momo_extreme"] = (m5, pd.Series(dir5, index=p.index))
    return sleeves


def compute_sleeve_pnl(p, mask, direction):
    sub = p[mask].copy()
    if len(sub) == 0:
        return None
    pnl = np.where(direction[mask] == "Up", sub.pnl_up.values, sub.pnl_dn.values)
    fill_ok = np.where(direction[mask] == "Up", sub.up_fill_ok.values, sub.dn_fill_ok.values)
    won = (direction[mask] == sub.outcome).values
    return sub.assign(_pnl=pnl, _fill_ok=fill_ok, _won=won, _dir=direction[mask].values)


def task4_gate_overlay(p):
    sleeves = define_sleeves(p)
    gates_up, gates_dn = build_mlofi_gates(p)
    rows = []
    for sname, (smask, sdir) in sleeves.items():
        sleeve_df = compute_sleeve_pnl(p, smask, sdir)
        if sleeve_df is None or len(sleeve_df) < 60:
            continue
        sleeve_df = sleeve_df[sleeve_df._fill_ok]
        if len(sleeve_df) < 60:
            continue
        for asset in ["BTC","ETH","SOL","ALL"]:
            for tf in ["5m","15m","ALL"]:
                sub = sleeve_df
                if asset != "ALL":
                    sub = sub[sub.asset == asset]
                if tf != "ALL":
                    sub = sub[sub.tf == tf]
                if len(sub) < 50:
                    continue
                base_dpt = sub._pnl.mean()
                base_wr = sub._won.mean()
                base_sum = sub._pnl.sum()
                rows.append({
                    "sleeve": sname, "asset": asset, "tf": tf,
                    "gate": "NONE",
                    "n_base": len(sub), "wr_base": float(base_wr),
                    "dpt_base": float(base_dpt), "sum_pnl": float(base_sum),
                    "wr_lift_pp": 0.0, "dpt_lift": 0.0,
                })
                for gname in gates_up.keys():
                    gate_per_fire = np.where(
                        sub._dir == "Up",
                        gates_up[gname].reindex(sub.index, fill_value=False).values,
                        gates_dn[gname].reindex(sub.index, fill_value=False).values,
                    )
                    sub2 = sub[gate_per_fire]
                    if len(sub2) < 30:
                        continue
                    dpt = sub2._pnl.mean()
                    wr = sub2._won.mean()
                    rows.append({
                        "sleeve": sname, "asset": asset, "tf": tf,
                        "gate": gname,
                        "n_base": len(sub), "wr_base": float(base_wr),
                        "dpt_base": float(base_dpt), "sum_pnl": float(sub2._pnl.sum()),
                        "wr_lift_pp": float((wr - base_wr) * 100),
                        "dpt_lift": float(dpt - base_dpt),
                        "n_gate": len(sub2), "wr_gate": float(wr),
                        "dpt_gate": float(dpt),
                    })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# TASK 5 — Strict 3-way (train 20d / val 7d / lockbox 5d) + 200 bootstrap
# ---------------------------------------------------------------------------

def task5_lockbox(p, top_combos, n_boot=200):
    """For each top combo (sleeve, asset, tf, gate_expr):
       - Split fires chronologically: train (first 20d), val (next 7d), lockbox (last 5d).
       Actually since we only have 23d total per spec, we adjust:
         - train_frac = 20/32  ~ 62.5%
         - val_frac  = 7/32   ~ 21.9%
         - lockbox  = remainder
       Per spec: 200-shuffle bootstrap.
    """
    sleeves = define_sleeves(p)
    gates_up, gates_dn = build_mlofi_gates(p)
    rng = np.random.RandomState(42)
    rows = []
    t_min = p.fire_us.min()
    t_max = p.fire_us.max()
    span_us = t_max - t_min
    # Per spec proportions
    train_end = int(t_min + span_us * (20.0/32.0))
    val_end = int(t_min + span_us * (27.0/32.0))

    for combo in top_combos:
        sname, asset, tf, gname = combo["sleeve"], combo["asset"], combo["tf"], combo["gate"]
        if sname not in sleeves:
            continue
        smask, sdir = sleeves[sname]
        sub = compute_sleeve_pnl(p, smask, sdir)
        if sub is None:
            continue
        sub = sub[sub._fill_ok]
        if asset != "ALL":
            sub = sub[sub.asset == asset]
        if tf != "ALL":
            sub = sub[sub.tf == tf]
        if gname != "NONE":
            gate_per_fire = np.where(
                sub._dir == "Up",
                gates_up[gname].reindex(sub.index, fill_value=False).values,
                gates_dn[gname].reindex(sub.index, fill_value=False).values,
            )
            sub = sub[gate_per_fire]
        if len(sub) < 30:
            continue
        train = sub[sub.fire_us < train_end]
        val = sub[(sub.fire_us >= train_end) & (sub.fire_us < val_end)]
        lockbox = sub[sub.fire_us >= val_end]
        if len(train) < 15 or len(val) < 5 or len(lockbox) < 5:
            continue
        lps = lockbox._pnl.values
        boot = np.array([rng.choice(lps, size=len(lps), replace=True).mean()
                         for _ in range(n_boot)])
        p_neg = float((boot < 0).mean())
        boot_low = float(np.percentile(boot, 5))
        boot_high = float(np.percentile(boot, 95))
        rows.append({
            "sleeve": sname, "asset": asset, "tf": tf, "gate": gname,
            "n_train": len(train), "wr_train": train._won.mean(),
            "dpt_train": train._pnl.mean(), "sum_train": train._pnl.sum(),
            "n_val": len(val), "wr_val": val._won.mean(),
            "dpt_val": val._pnl.mean(), "sum_val": val._pnl.sum(),
            "n_lockbox": len(lockbox), "wr_lockbox": lockbox._won.mean(),
            "dpt_lockbox": lockbox._pnl.mean(), "sum_lockbox": lockbox._pnl.sum(),
            "boot_p_neg": p_neg, "boot_ci5": boot_low, "boot_ci95": boot_high,
            "pass_lockbox": (train._pnl.mean() > 0 and val._pnl.mean() > 0
                              and lockbox._pnl.mean() > 0 and p_neg < 0.10),
        })
    return pd.DataFrame(rows)


def main():
    import builtins
    bp = builtins.print
    def fp(*a, **k):
        k.setdefault('flush', True); bp(*a, **k)
    builtins.print = fp

    print("=== LOADING PANEL + PnL ===")
    p = load_panel_with_pnl_and_returns()

    print("=== ADDING Z-SCORES (7d rolling) ===")
    p = add_zscores(p)

    print("\n=== TASK 2: standalone rules ===")
    t2 = task2_standalone(p)
    t2.to_csv(WORK / "task2_standalone_rules.csv", index=False)
    print(t2.head(25).to_string())

    print("\n=== TASK 3: MLOFI vs L1 OFI predictive power ===")
    t3 = task3_mlofi_vs_l1(p)
    t3.to_csv(WORK / "task3_mlofi_vs_l1.csv", index=False)
    print(t3.head(40).to_string())

    print("\n=== TASK 4: gate overlay on sleeves ===")
    t4 = task4_gate_overlay(p)
    t4.to_csv(WORK / "task4_gate_overlay.csv", index=False)
    # Top gated by sum_pnl
    t4_gated = t4[t4.gate != "NONE"]
    pos = t4_gated[(t4_gated.get("n_gate", 0) >= 100) & (t4_gated.dpt_gate > 0)]
    if len(pos) > 0:
        print("Top by sum_pnl (positive, n_gate>=100):")
        print(pos.sort_values("sum_pnl", ascending=False).head(30).to_string())
    # Baselines
    base = t4[t4.gate == "NONE"]
    print("\nSleeve baselines:")
    print(base.sort_values("dpt_base", ascending=False).head(20).to_string())

    print("\n=== TASK 5: 3-way validation (train/val/lockbox) ===")
    # Select top candidates: positive in TASK 4 gated, n_gate>=100
    cands = t4_gated[(t4_gated.get("n_gate", 0) >= 100) & (t4_gated.dpt_gate > 0)]
    cands = cands.sort_values("sum_pnl", ascending=False).head(30)
    base_cands = base[base.dpt_base > 0].sort_values("sum_pnl", ascending=False).head(10)
    base_cands = base_cands.assign(gate="NONE")
    all_cands = pd.concat([cands, base_cands], ignore_index=True)
    top_combos = [
        {"sleeve": r["sleeve"], "asset": r["asset"], "tf": r["tf"], "gate": r["gate"]}
        for _, r in all_cands.iterrows()
    ]
    t5 = task5_lockbox(p, top_combos)
    t5.to_csv(WORK / "task5_lockbox.csv", index=False)
    print(t5.sort_values(["pass_lockbox","dpt_lockbox"], ascending=[False,False]).head(25).to_string())
    print(f"\nLOCKBOX PASS: {t5.pass_lockbox.sum()}/{len(t5)}")


if __name__ == "__main__":
    main()
