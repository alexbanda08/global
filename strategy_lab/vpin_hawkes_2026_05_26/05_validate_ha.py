"""Validate Rule H-A (bet sign of hawkes_lambda_imbalance when |imb|>0.3) through 3-way split.

Note: this is the STANDALONE rule, NOT a gate. We test if the rule itself survives time-OOS.
"""
import pandas as pd
import numpy as np

FIRES = "C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/_results/vpin_hawkes_at_fires.parquet"
OUT = "C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/_results/vpin_hawkes_validation_HA.csv"


def split(df, fire_col="fire_us"):
    ts = df[fire_col].astype(np.int64)
    tmin, tmax = ts.min(), ts.max()
    span = tmax - tmin
    train_end = tmin + int(span * 0.64)
    val_end = tmin + int(span * 0.85)
    return df[ts < train_end], df[(ts >= train_end) & (ts < val_end)], df[ts >= val_end]


def stats(d):
    if len(d) == 0:
        return 0, np.nan, np.nan, np.nan
    won = (d["outcome"] == "Up") == (d["bet_dir"] == 1)
    pnl = np.where(won, (1-0.5)/0.5 * 0.98, -1.0)
    return len(d), float(won.mean()), float(pnl.mean()), float(pnl.sum())


def main():
    f = pd.read_parquet(FIRES)
    print(f"loaded: {f.shape}")
    f = f[f["hawkes_lambda_imbalance"].notna() & f["outcome"].notna()].copy()
    f = f[(f["outcome"] == "Up") | (f["outcome"] == "Down")]
    f["bet_dir"] = np.sign(f["hawkes_lambda_imbalance"]).astype(int)
    # H-A filter: |imbalance| > 0.3
    h = f[f["hawkes_lambda_imbalance"].abs() > 0.3].copy()
    print(f"after |imb|>0.3 filter: {len(h):,}")

    rows = []
    for (a, tf, off), g in h.groupby(["asset", "tf", "fire_offset_s"]):
        if len(g) < 200: continue
        tr, va, lo = split(g)
        n_t, wr_t, dpt_t, sp_t = stats(tr)
        n_v, wr_v, dpt_v, sp_v = stats(va)
        n_l, wr_l, dpt_l, sp_l = stats(lo)
        # Bootstrap on lockbox
        if len(lo) >= 30:
            won = ((lo["outcome"] == "Up") == (lo["bet_dir"] == 1)).to_numpy()
            pnl = np.where(won, (1-0.5)/0.5*0.98, -1.0)
            rng = np.random.default_rng(42)
            boot = [rng.choice(pnl, size=len(pnl), replace=True).mean() for _ in range(1000)]
            cl, ch = np.quantile(boot, [0.025, 0.975])
        else:
            cl = ch = np.nan
        passed = (dpt_t > 0) and (dpt_v > 0) and (dpt_l > 0) and (cl > 0)
        rows.append({
            "asset": a, "tf": tf, "offset_s": off,
            "n_train": n_t, "WR_train": wr_t, "dpt_train": dpt_t, "sum_train": sp_t,
            "n_val": n_v, "WR_val": wr_v, "dpt_val": dpt_v, "sum_val": sp_v,
            "n_lock": n_l, "WR_lock": wr_l, "dpt_lock": dpt_l, "sum_lock": sp_l,
            "ci_lo_lock": cl, "ci_hi_lock": ch, "PASS": passed,
        })
    out = pd.DataFrame(rows).sort_values("dpt_lock", ascending=False)
    out.to_csv(OUT, index=False)
    print(f"\nwrote {OUT}: {out.shape}")
    print("\nH-A standalone 3-way validation (top 30 by dpt_lock):")
    print(out.head(30).to_string())
    print(f"\nLockbox PASS count: {out['PASS'].sum()} / {len(out)}")
    print(f"Sleeves with dpt_lock>0: {(out['dpt_lock']>0).sum()}")
    print(f"Sleeves with dpt_lock>0 AND ci_lo>0: {((out['dpt_lock']>0)&(out['ci_lo_lock']>0)).sum()}")


if __name__ == "__main__":
    main()
