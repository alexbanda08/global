"""
kronos_ft_sniff_5m — Post-training sniff test for the fine-tuned Kronos-base
on a 5m-timeframe symbol. Evaluates MULTIPLE horizons from a single forecast:

    bar 1  -> 5-min  Polymarket up/down
    bar 3  -> 15-min Polymarket up/down
    bar 6  -> 30-min Polymarket up/down
    bar 9  -> 45-min Polymarket up/down

For each horizon we report direction accuracy, edge over the majority-bet
baseline, and return correlations on the held-out tail.

Usage:
  D:/kronos-venv/Scripts/python.exe strategy_lab/kronos_ft_sniff_5m.py \
      --config strategy_lab/kronos_ft/config_btc_5m_3y.yaml
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("HF_HOME", "D:/hf-cache")

import numpy as np
import pandas as pd
import torch
import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "external" / "Kronos"))
sys.path.insert(0, str(ROOT))

from model import Kronos, KronosTokenizer, KronosPredictor  # noqa: E402

DEFAULT_HORIZONS = [
    ("5m", 1),
    ("15m", 3),
    ("30m", 6),
    ("45m", 9),
]


def load_config(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    mp = cfg.get("model_paths", {})
    exp, base = mp.get("exp_name", ""), mp.get("base_path", "")
    if not mp.get("base_save_path"):
        mp["base_save_path"] = f"{base}/{exp}"
    if not mp.get("finetuned_tokenizer"):
        mp["finetuned_tokenizer"] = f"{base}/{exp}/tokenizer/best_model"
    mp["finetuned_basemodel"] = f"{base}/{exp}/basemodel/best_model"
    return cfg


def slice_test(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    data = cfg["data"]
    n = len(df)
    tr = int(n * float(data["train_ratio"]))
    va = int(n * float(data["val_ratio"]))
    test_start = tr + va
    return df.iloc[test_start:].reset_index(drop=True)


def evaluate_horizon(rows: list[dict], horizon_bars: int) -> dict:
    """Build per-horizon stats from forecast rows."""
    data = [r for r in rows if len(r["pred"]) >= horizon_bars and len(r["actual"]) >= horizon_bars]
    if not data:
        return {"n": 0}
    df = pd.DataFrame({
        "c0":         [r["c0"] for r in data],
        "pred_close": [r["pred"][horizon_bars - 1] for r in data],
        "actual":     [r["actual"][horizon_bars - 1] for r in data],
    })
    df["pred_ret"]   = df["pred_close"] / df["c0"] - 1.0
    df["actual_ret"] = df["actual"]     / df["c0"] - 1.0
    df["dir_match"]  = (np.sign(df["pred_ret"]) == np.sign(df["actual_ret"])).astype(int)
    pearson = float(df["pred_ret"].corr(df["actual_ret"]))
    try:
        spearman = float(df["pred_ret"].corr(df["actual_ret"], method="spearman"))
    except Exception:
        spearman = None
    dir_acc = float(df["dir_match"].mean())
    bias = float((df["actual_ret"] > 0).mean())
    majority_bet_acc = max(bias, 1 - bias)
    edge = dir_acc - majority_bet_acc
    mae_pct = float(((df["pred_close"] - df["actual"]).abs() / df["c0"]).mean())
    return {
        "n":                int(len(df)),
        "pearson_corr":     round(pearson, 4),
        "spearman_corr":    round(spearman, 4) if spearman is not None else None,
        "direction_acc":    round(dir_acc, 4),
        "actual_pos_bias":  round(bias, 4),
        "majority_bet_acc": round(majority_bet_acc, 4),
        "edge_pp":          round(edge * 100, 2),
        "mean_abs_err_pct": round(mae_pct, 4),
        "passes_gate":      bool(edge > 0.02 and pearson > 0.05),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--sample-count", type=int, default=8)
    ap.add_argument("--max-windows", type=int, default=500)
    args = ap.parse_args()

    cfg = load_config(Path(args.config))
    data_cfg = cfg["data"]
    mp = cfg["model_paths"]

    lookback = int(data_cfg["lookback_window"])
    pred_len = int(data_cfg["predict_window"])

    print(f"Loading fine-tuned tokenizer: {mp['finetuned_tokenizer']}")
    print(f"Loading fine-tuned predictor: {mp['finetuned_basemodel']}")
    tok = KronosTokenizer.from_pretrained(mp["finetuned_tokenizer"])
    mdl = Kronos.from_pretrained(mp["finetuned_basemodel"])
    predictor = KronosPredictor(mdl, tok, device="cuda:0",
                                max_context=int(data_cfg["max_context"]))

    df = pd.read_csv(data_cfg["data_path"])
    df["timestamps"] = pd.to_datetime(df["timestamps"])
    test = slice_test(df, cfg)
    print(f"Test slice: {len(test):,} rows  "
          f"{test['timestamps'].iloc[0]} -> {test['timestamps'].iloc[-1]}")

    horizons = [(name, bars) for name, bars in DEFAULT_HORIZONS if bars <= pred_len]
    print(f"Horizons evaluated: {[h[0] for h in horizons]}")

    test_start_in_full = len(df) - len(test)
    starts = list(range(test_start_in_full, len(df) - pred_len, pred_len))
    starts = [s for s in starts if s - lookback >= 0]
    if args.max_windows and len(starts) > args.max_windows:
        step = max(1, len(starts) // args.max_windows)
        starts = starts[::step][: args.max_windows]
    print(f"Windows to evaluate: {len(starts)}")

    rows = []
    t0 = time.time()
    for k, s in enumerate(starts):
        ctx_lo = s - lookback
        x_df = df.iloc[ctx_lo:s][["open", "high", "low", "close", "volume", "amount"]].reset_index(drop=True)
        x_ts = df.iloc[ctx_lo:s]["timestamps"].reset_index(drop=True)
        y_ts = df.iloc[s:s + pred_len]["timestamps"].reset_index(drop=True)
        actual = df.iloc[s:s + pred_len]["close"].tolist()
        try:
            pred = predictor.predict(
                df=x_df, x_timestamp=x_ts, y_timestamp=y_ts,
                pred_len=pred_len, T=1.0, top_p=0.9,
                sample_count=args.sample_count, verbose=False,
            )
        except Exception as e:
            print(f"  [{k+1}/{len(starts)}] FAIL: {e}")
            continue
        c0 = float(x_df["close"].iloc[-1])
        rows.append({
            "ctx_end": x_ts.iloc[-1],
            "c0": c0,
            "pred":  pred["close"].tolist(),
            "actual": actual,
        })
        if (k + 1) % 25 == 0 or k == len(starts) - 1:
            el = time.time() - t0
            eta = el / (k + 1) * (len(starts) - k - 1)
            print(f"  [{k+1}/{len(starts)}] {el:.0f}s elapsed, eta {eta:.0f}s")

    per_horizon = {name: evaluate_horizon(rows, bars) for name, bars in horizons}

    exp = mp["exp_name"]
    out_dir = HERE / "results" / "kronos"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Persist per-window forecasts for downstream analysis.
    flat = []
    for r in rows:
        for i, (pp, aa) in enumerate(zip(r["pred"], r["actual"]), start=1):
            flat.append({
                "ctx_end": r["ctx_end"], "c0": r["c0"],
                "bar": i, "pred_close": pp, "actual_close": aa,
                "pred_ret": pp / r["c0"] - 1, "actual_ret": aa / r["c0"] - 1,
            })
    pd.DataFrame(flat).to_csv(out_dir / f"ft_sniff_{exp}.csv", index=False)

    summary = {"experiment": exp, "n_windows": len(rows), "per_horizon": per_horizon}
    print("\n=== SUMMARY ===")
    print(json.dumps(summary, indent=2, default=str))

    report = HERE / "reports" / f"KRONOS_FT_SNIFF_{exp}.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Kronos fine-tuned sniff — {exp}\n",
        f"**Model**: `{mp['finetuned_basemodel']}`  \n",
        f"**Tokenizer**: `{mp['finetuned_tokenizer']}`  \n",
        f"**Lookback**: {lookback}  **Pred len**: {pred_len}  "
        f"**Sample count**: {args.sample_count}  **Windows**: {len(rows)}\n",
        "## Per-horizon results\n",
        "| Horizon | n | Pearson | Dir Acc | Pos Bias | Majority-bet | **Edge (pp)** | MAE% | Passes |",
        "|---|---:|---:|---:|---:|---:|---:|---:|:---:|",
    ]
    for name, bars in horizons:
        s = per_horizon[name]
        if s.get("n", 0) == 0:
            lines.append(f"| {name} | 0 | — | — | — | — | — | — | — |"); continue
        mark = "PASS" if s["passes_gate"] else "fail"
        lines.append(
            f"| {name} | {s['n']} | {s['pearson_corr']} | {s['direction_acc']} | "
            f"{s['actual_pos_bias']} | {s['majority_bet_acc']} | **{s['edge_pp']:+.2f}** | "
            f"{s['mean_abs_err_pct']:.4f} | {mark} |"
        )
    lines.append("\n## Polymarket read\n")
    lines.append(
        "`Edge (pp)` = direction accuracy − always-bet-majority baseline. "
        "Positive = model beats naive. PASS gate requires edge > 2pp AND Pearson > 0.05."
    )
    lines.append("\n")
    lines.append(f"Per-window forecasts at `results/kronos/ft_sniff_{exp}.csv`.")
    report.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWrote {report}")


if __name__ == "__main__":
    main()
