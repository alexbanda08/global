"""
Harvestability test for the ONE real directional edge: btc-15m ema50_ema800 trend-continuation.

It passes all bias-free gates at off=600 (+$1.66/trade, WR 82%, beats price +7.3pp, matched-null
p=0.001, block-CI>0, OOS+) BUT places 0 live because the cross-token/same-token SPREAD gate blocks
at off=600 (book not tight 5min before close). DECISIVE QUESTION: does the edge survive at EARLIER
offsets where the book IS tight (fillable), and on the spread-PASSING (live-fillable) subset?

Per offset {60,180,300,600,840} for btc-15m, DOWN (close<ema50 & close<ema800) and UP (close>both):
  - n, WR, mean realistic PnL/trade (poly 0.07 p(1-p) fee + $0.01 tx)
  - WR_minus_implied (de-vigged) + bootstrap CI
  - block-bootstrap-by-UTC-day CI_lo + OOS (train60/test40) test PnL
  - spread_pass% = frac(traded-side ask0-bid0 <= 0.02)  -> LIVE-FILLABLE fraction
  - on the FILLABLE subset only: n, WR, mean PnL  (the live-harvestable edge)

Output: data/v4/canonical/_results/ema_offset_fillability_btc15m.csv + console table.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
from load import load_klines_1s  # noqa: E402

RES = ROOT / "data" / "v4" / "canonical" / "_results"
FEE_RATE, TX = 0.07, 0.01
SPREAD_BTC = 0.02
OFFSETS = [60, 180, 300, 600, 840]


def settle_real(won, shares, stake, vwap):
    fee = shares * FEE_RATE * vwap * (1 - vwap)
    return np.where(won, shares - stake - fee, -stake - fee) - TX


def boot_ci(x, n=8000, seed=1):
    if len(x) < 8:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    bm = x[rng.integers(0, len(x), size=(n, len(x)))].mean(1)
    return float(np.quantile(bm, .025)), float(np.quantile(bm, .975))


def block_ci_lo(df, col="pnl", n=8000, seed=3):
    # bootstrap over UTC days (resample whole days) -> respects serial corr
    df = df.copy()
    df["day"] = (df["slot_start_s"] // 86400).astype(int)
    days = df["day"].unique()
    if len(days) < 5:
        return float("nan")
    g = {d: df.loc[df["day"] == d, col].values for d in days}
    rng = np.random.default_rng(seed)
    means = np.empty(n)
    for i in range(n):
        pick = rng.choice(days, size=len(days), replace=True)
        vals = np.concatenate([g[d] for d in pick])
        means[i] = vals.mean()
    return float(np.quantile(means, .025))


def main():
    print("loading binance 1s btc + computing ema50/ema800 (causal)...")
    k = load_klines_1s("btc")
    ecol = [c for c in k.columns if "end" in c.lower()][0]
    ccol = "price_close" if "price_close" in k.columns else [c for c in k.columns if "close" in c.lower()][0]
    k = k[[ecol, ccol]].dropna().sort_values(ecol)
    end = k[ecol].to_numpy(np.int64)
    close = k[ccol].to_numpy(float)
    ema50 = pd.Series(close).ewm(span=50, adjust=False).mean().to_numpy()
    ema800 = pd.Series(close).ewm(span=800, adjust=False).mean().to_numpy()

    d = pd.read_parquet(RES / "dirscan_btc_15m.parquet")

    def asof(arr, t):  # last bar end_us <= t
        i = np.searchsorted(end, t, side="right") - 1
        return arr[i] if i >= 0 else np.nan

    rows = []
    for off in OFFSETS:
        do = d[d["offset_s"] == off].copy()
        if do.empty:
            continue
        fire = (do["slot_start_s"].to_numpy() + off) * 1_000_000
        c = np.array([asof(close, t) for t in fire])
        e50 = np.array([asof(ema50, t) for t in fire])
        e800 = np.array([asof(ema800, t) for t in fire])
        do["c"], do["e50"], do["e800"] = c, e50, e800
        for dirn in ("DOWN", "UP"):
            if dirn == "DOWN":
                fired = do[(do["c"] < do["e50"]) & (do["c"] < do["e800"]) & do["d_ok"]].copy()
                side_vwap, side_ask, side_bid, side_sh, side_usd = "d_vwap", "d_ask0", "d_bid0", "d_shares", "d_usd"
                winval = "Down"
            else:
                fired = do[(do["c"] > do["e50"]) & (do["c"] > do["e800"]) & do["u_ok"]].copy()
                side_vwap, side_ask, side_bid, side_sh, side_usd = "u_vwap", "u_ask0", "u_bid0", "u_shares", "u_usd"
                winval = "Up"
            # entry px gate (same as validated): 0.55-0.92
            fired = fired[(fired[side_vwap] >= 0.55) & (fired[side_vwap] <= 0.92)]
            if len(fired) < 15:
                continue
            won = (fired["outcome_truth"] == winval).values
            vwap = fired[side_vwap].values
            pnl = settle_real(won, fired[side_sh].values, fired[side_usd].values, vwap)
            implied = (fired[side_vwap] / (fired["u_vwap"] + fired["d_vwap"])).values
            wri = won.astype(float) - implied
            wri_lo, _ = boot_ci(wri)
            blo = block_ci_lo(fired.assign(pnl=pnl))
            # OOS train60/test40 by time
            order = fired["slot_start_s"].argsort().values
            cut = int(len(order) * 0.6)
            te = order[cut:]
            oos = pnl[te].mean() if len(te) else float("nan")
            # FILLABLE subset (live spread gate passes)
            spr = (fired[side_ask] - fired[side_bid]).values
            fillable = spr <= SPREAD_BTC
            fpct = fillable.mean()
            fpnl = pnl[fillable].mean() if fillable.sum() >= 1 else float("nan")
            fwr = won[fillable].mean() if fillable.sum() >= 1 else float("nan")
            rows.append({
                "offset": off, "dir": dirn, "n": len(fired), "wr": round(won.mean(), 3),
                "mean_pnl": round(float(pnl.mean()), 3), "wr_minus_impl": round(float(wri.mean()), 4),
                "wri_ci_lo": round(wri_lo, 4), "block_lo": round(blo, 3), "oos_pnl": round(float(oos), 3),
                "spread_pass_pct": round(float(fpct), 3), "n_fillable": int(fillable.sum()),
                "fillable_wr": round(float(fwr), 3) if fwr == fwr else None,
                "fillable_pnl": round(float(fpnl), 3) if fpnl == fpnl else None,
            })

    out = pd.DataFrame(rows)
    out.to_csv(RES / "ema_offset_fillability_btc15m.csv", index=False)
    pd.set_option("display.width", 200)
    print("\n=== btc-15m ema50_ema800 — edge vs FILLABILITY by offset ===")
    print(out.to_string(index=False))
    print("\nKEY: deployable = wr_minus_impl>0 & block_lo>0 & oos_pnl>0 AND high spread_pass_pct "
          "AND fillable_pnl>0 (the live-harvestable subset).")


if __name__ == "__main__":
    main()
