"""TASK 6 — Strict 3-way validation on top LM gate-overlay sleeves.

Train (20d) / Val (7d) / Lockbox (5d) split + 200-shuffle bootstrap on top combos.

Top combos (from gate_overlay output):
  S1: btc_s6_15_300 + g_lm_high_stat            (n=84, WR 82.1, $/tr +15.44)
  S2: btc_s6_15_300 + g_lm_extreme_with         (n=104, WR 82.7, $/tr +6.35)
  S3: btc_s6_15_300 + g_lm_extreme_with_or_high (n=160, WR 81.2, $/tr +7.87)
  S4: eth_s6_15_300 + g_lm_extreme_with_or_high (n=127, WR 81.9, $/tr +2.53)
  S5: sol_s6_15_300 + g_lm_extreme_with_or_high (n=57, WR 87.7, $/tr +3.97)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
S6 = ROOT / "data" / "v4" / "canonical" / "_results" / "s6_joined_all.parquet"
LM_5M = ROOT / "data" / "v4" / "canonical" / "_results" / "lm_at_fires_5m.parquet"
OUT = ROOT / "data" / "v4" / "canonical" / "_results" / "lm_validation_3way.csv"

RNG = np.random.default_rng(0)


def legacy_pnl(direction: str, outcome: str, vwap: float, shares: float, usd_in: float) -> float:
    won = (direction == "UP" and outcome == "Up") or (direction == "DOWN" and outcome == "Down")
    if won:
        gross = shares - usd_in
        if gross > 0:
            return gross - 0.02 * gross
        return gross
    return -usd_in


def build_base() -> pd.DataFrame:
    s6 = pd.read_parquet(S6)
    s6_keep = s6[["asset", "slug", "fire_offset_s", "fire_us", "direction", "outcome"]].copy()
    s6_keep = s6_keep.drop_duplicates(["asset", "slug", "fire_offset_s"], keep="first")
    lm = pd.read_parquet(LM_5M)
    lm_keep = lm[["asset", "slug", "fire_offset_s",
                  "up_fill_ok", "dn_fill_ok",
                  "up_vwap", "up_shares", "up_usd",
                  "dn_vwap", "dn_shares", "dn_usd",
                  "lm_L_stat_at_fire", "lm_has_jump_60s", "lm_has_jump_120s",
                  "lm_last_jump_dir_60s", "lm_last_jump_dir_extreme_120s",
                  "lm_n_jumps_in_last_300s"]].copy()
    base = s6_keep.merge(lm_keep, on=["asset", "slug", "fire_offset_s"], how="inner")
    fills_ok = np.where(base["direction"] == "UP", base["up_fill_ok"], base["dn_fill_ok"])
    base = base[fills_ok].copy()
    vwap = np.where(base["direction"] == "UP", base["up_vwap"], base["dn_vwap"])
    shares = np.where(base["direction"] == "UP", base["up_shares"], base["dn_shares"])
    usd = np.where(base["direction"] == "UP", base["up_usd"], base["dn_usd"])
    pnl = np.zeros(len(base))
    for i in range(len(base)):
        pnl[i] = legacy_pnl(base["direction"].iloc[i], base["outcome"].iloc[i],
                            vwap[i], shares[i], usd[i])
    base["pnl_legacy_usd"] = pnl
    base["won"] = (((base["direction"] == "UP") & (base["outcome"] == "Up")) |
                   ((base["direction"] == "DOWN") & (base["outcome"] == "Down"))).astype(int)
    # add gates
    dir_sign = np.where(base["direction"] == "UP", 1, -1)
    base["g_lm_high_stat"] = (base["lm_L_stat_at_fire"] > 5.97)
    base["g_lm_extreme_with"] = (
        (base["lm_last_jump_dir_extreme_120s"] == dir_sign)
    )
    base["g_lm_extreme_with_or_high"] = (base["g_lm_extreme_with"] | base["g_lm_high_stat"])
    return base


def split_by_time(df: pd.DataFrame, train_d: int = 12, val_d: int = 5, lockbox_d: int = 3):
    """Time-ordered split. Returns (train, val, lockbox)."""
    df = df.sort_values("fire_us").reset_index(drop=True)
    ts_min = int(df["fire_us"].min())
    train_end = ts_min + int(train_d * 86400 * 1_000_000)
    val_end = train_end + int(val_d * 86400 * 1_000_000)
    train = df[df["fire_us"] < train_end].copy()
    val = df[(df["fire_us"] >= train_end) & (df["fire_us"] < val_end)].copy()
    lockbox = df[df["fire_us"] >= val_end].copy()
    return train, val, lockbox


def stats(g: pd.DataFrame) -> dict:
    if len(g) == 0:
        return {"n": 0, "wr_pct": np.nan, "per_tr_usd": np.nan, "sum_pnl_usd": 0.0}
    return {
        "n": int(len(g)),
        "wr_pct": float(100.0 * g["won"].mean()),
        "per_tr_usd": float(g["pnl_legacy_usd"].mean()),
        "sum_pnl_usd": float(g["pnl_legacy_usd"].sum()),
    }


def bootstrap_pval(g: pd.DataFrame, n_boot: int = 200) -> float:
    """Bootstrap p-value that mean PnL > 0 (one-sided)."""
    if len(g) < 5:
        return np.nan
    vals = g["pnl_legacy_usd"].values
    means = np.empty(n_boot)
    for b in range(n_boot):
        sample = RNG.choice(vals, size=len(vals), replace=True)
        means[b] = sample.mean()
    return float((means <= 0).mean())


def evaluate_sleeve(name: str, base: pd.DataFrame, asset: str,
                    off_range: tuple[int, int], gate_col: str) -> list[dict]:
    """Apply asset + offset_range + gate filter; report train/val/lockbox stats."""
    sub = base[(base["asset"] == asset) &
               (base["fire_offset_s"] >= off_range[0]) &
               (base["fire_offset_s"] <= off_range[1]) &
               (base[gate_col])].copy()
    train, val, lockbox = split_by_time(sub, 12, 5, 3)
    rows = []
    for split_name, g in (("train_12d", train), ("val_5d", val), ("lockbox_3d", lockbox)):
        s = stats(g)
        s["sleeve"] = name
        s["asset"] = asset
        s["off_lo"] = off_range[0]
        s["off_hi"] = off_range[1]
        s["gate"] = gate_col
        s["split"] = split_name
        s["bootstrap_p_pnl_gt0"] = bootstrap_pval(g) if len(g) >= 5 else np.nan
        rows.append(s)
    return rows


def main() -> int:
    print("[1] building base ...")
    base = build_base()
    print(f"    base: {len(base):,} S6 fires with LM features")
    # check time coverage
    ts_min = pd.Timestamp(base["fire_us"].min(), unit="us")
    ts_max = pd.Timestamp(base["fire_us"].max(), unit="us")
    print(f"    span: {ts_min} -> {ts_max}")

    sleeves = [
        ("S1_btc_high_stat",          "BTC", (15, 300), "g_lm_high_stat"),
        ("S2_btc_extreme_with",       "BTC", (15, 300), "g_lm_extreme_with"),
        ("S3_btc_extreme_with_or_high", "BTC", (15, 300), "g_lm_extreme_with_or_high"),
        ("S4_eth_extreme_with_or_high", "ETH", (15, 300), "g_lm_extreme_with_or_high"),
        ("S5_sol_extreme_with_or_high", "SOL", (15, 300), "g_lm_extreme_with_or_high"),
        ("S6_btc_60_150_high_stat",   "BTC", (60, 150), "g_lm_high_stat"),
        ("S7_btc_60_150_extreme_with", "BTC", (60, 150), "g_lm_extreme_with"),
    ]
    all_rows = []
    print("\n=== 3-WAY VALIDATION + BOOTSTRAP ===")
    for sleeve in sleeves:
        rows = evaluate_sleeve(sleeve[0], base, sleeve[1], sleeve[2], sleeve[3])
        for r in rows:
            print(f"  {r['sleeve']:32s} {r['split']:12s} n={r['n']:4d}  "
                  f"WR={r['wr_pct']:5.1f}%  $/tr={r['per_tr_usd']:+7.3f}  "
                  f"sum=${r['sum_pnl_usd']:+9.2f}  p(boot)={r['bootstrap_p_pnl_gt0']:.3f}")
        all_rows.extend(rows)
    out = pd.DataFrame(all_rows)
    out.to_csv(OUT, index=False)

    # Lockbox pass count (lockbox per_tr_usd > 0 AND n >= 5)
    lockbox = out[out["split"] == "lockbox_3d"]
    passes = lockbox[(lockbox["per_tr_usd"] > 0) & (lockbox["n"] >= 5)]
    print(f"\n[LOCKBOX] {len(passes)}/{len(lockbox)} sleeves pass (per_tr>0, n>=5)")
    for _, r in passes.iterrows():
        print(f"  PASS: {r['sleeve']:32s}  n={r['n']:4d}  WR={r['wr_pct']:5.1f}%  $/tr={r['per_tr_usd']:+.3f}")
    print(f"\n[saved] {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
