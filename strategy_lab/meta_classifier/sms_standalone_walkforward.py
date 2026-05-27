"""Walk-forward validation of best STANDALONE SMS rules.

For each top standalone sleeve from sms_standalone_results.csv (filtered by n>=200,
dpt>0), run a 14d train / 8d test + 200-shuffle bootstrap and report PASS/FAIL.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
RES = ROOT / "data" / "v4" / "canonical" / "_results"
sys.path.insert(0, str(ROOT / "strategy_lab" / "meta_classifier"))
from sms_standalone_backtest import signal_from_rule  # type: ignore

S15_PATH = RES / "s15_with_sms.parquet"
S6_PATH = RES / "s6_with_sms.parquet"
V15M_PATH = RES / "v15m_with_sms.parquet"
TOP_PATH = RES / "sms_standalone_results.csv"
OUT = RES / "sms_standalone_walk_forward.csv"

WIN_TRAIN_END = pd.Timestamp("2026-05-14 00:00", tz="UTC").value // 1_000
N_BOOT = 200


def bootstrap_dpt(pnl: np.ndarray, n_boot: int = N_BOOT, seed: int = 42):
    if len(pnl) == 0:
        return np.nan, np.nan, np.nan
    rng = np.random.default_rng(seed)
    n = len(pnl)
    samples = rng.choice(pnl, size=(n_boot, n), replace=True)
    dpts = samples.mean(axis=1)
    return float(np.percentile(dpts, 5)), float(np.percentile(dpts, 50)), float(np.percentile(dpts, 95))


def load_with_sms(tf_label):
    if tf_label == "s15_5m":
        return pd.read_parquet(S15_PATH)
    if tf_label == "s6_5m":
        return pd.read_parquet(S6_PATH)
    if tf_label == "v15m_15m":
        return pd.read_parquet(V15M_PATH)


def main():
    print("[load + filter sleeves]")
    tops = pd.read_csv(TOP_PATH)
    # filter: per (asset, tf, offset, rule) — n>=200, dpt>0, NOT 'ALL' aggregates
    cand = tops[(tops["n"] >= 200) & (tops["dollar_per_trade"] > 0) &
                (tops["offset_s"] != "ALL") & (tops["asset"] != "ALL")].copy()
    cand = cand.sort_values("dollar_per_trade", ascending=False).head(15)
    print(f"  {len(cand)} sleeves to walk-forward")
    print(cand[["asset","tf","offset_s","rule","n","WR","dollar_per_trade"]].to_string(index=False))

    DFS = {tf: load_with_sms(tf) for tf in cand["tf"].unique()}
    for k, v in DFS.items():
        v = v[v["bos_buy"].notna()].copy()
        # cast SMS dtypes consistently
        for c in ("bos_buy","bos_sell","choch_buy","choch_sell","rsi_bullish_div",
                  "rsi_bearish_div","liquidity_up","liquidity_dn"):
            v[c] = v[c].fillna(0).astype(np.int8)
        for c in ("bars_since_bos_buy","bars_since_bos_sell","bars_since_choch_buy",
                  "bars_since_choch_sell"):
            v[c] = v[c].fillna(-1).astype(np.int32)
        v["trend_strength_raw"] = v["trend_strength_raw"].fillna(0).astype(int)
        v["system_confidence"] = v["system_confidence"].fillna(50).astype(int)
        v["cvd_level"] = v["cvd_level"].fillna(0).astype(int)
        v["cvd_sign"] = v["cvd_sign"].fillna(0).astype(int)
        DFS[k] = v

    rows = []
    for _, r in cand.iterrows():
        df = DFS[r["tf"]]
        # filter to asset + offset
        mask = (df["asset"] == r["asset"]) & (df["fire_offset_s"].astype(int) == int(r["offset_s"]))
        sub = df[mask].copy()
        if len(sub) == 0:
            continue
        sig = signal_from_rule(sub, r["rule"])
        # match the bet direction
        sel = sub[(sig == sub["direction"]) & (sig != "NONE")].copy()
        train = sel[sel["fire_us"] < WIN_TRAIN_END]
        test = sel[sel["fire_us"] >= WIN_TRAIN_END]
        if len(train) == 0 or len(test) == 0:
            continue
        tr_dpt = train["pnl_legacy_usd"].mean()
        te_dpt = test["pnl_legacy_usd"].mean()
        tr_wr = train["won"].mean()
        te_wr = test["won"].mean()
        te_p5, te_p50, te_p95 = bootstrap_dpt(test["pnl_legacy_usd"].values, N_BOOT)
        passed = (len(test) >= 30) and (te_dpt > 0) and (te_p5 > 0)
        rows.append({
            "asset": r["asset"], "tf": r["tf"], "offset_s": int(r["offset_s"]),
            "rule": r["rule"],
            "train_n": len(train), "train_WR": tr_wr, "train_dpt": tr_dpt,
            "test_n": len(test), "test_WR": te_wr, "test_dpt": te_dpt,
            "test_dpt_p5": te_p5, "test_dpt_p50": te_p50, "test_dpt_p95": te_p95,
            "passes_g4": passed,
        })

    out = pd.DataFrame(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index=False)
    pd.set_option("display.width", 220)
    print(f"\nwrote {OUT} ({len(out)} rows)")
    print("\n=== STANDALONE walk-forward ===")
    print(out.to_string(index=False))
    n_pass = int(out["passes_g4"].sum())
    print(f"\nPASS: {n_pass} / {len(out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
