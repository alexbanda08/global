"""
kronos_sniff_test_base — Phase 0 viability test using Kronos-base (102.3M) on GPU.

Same methodology as kronos_sniff_test.py, but:
  * Model:        NeoQuasar/Kronos-base  (102.3M params, ~4x Kronos-small)
  * Tokenizer:    NeoQuasar/Kronos-Tokenizer-base
  * Device:       cuda:0  (RTX 3060 12GB)
  * Sample count: 16       (plenty of VRAM headroom, tighter MC estimate)
  * Output files are suffixed with "_base" so the small-model run is kept intact.

Run:
  D:/kronos-venv/Scripts/python.exe strategy_lab/kronos_sniff_test_base.py
"""
from __future__ import annotations

import os
import sys
import json
import time
from pathlib import Path

os.environ.setdefault("HF_HOME", "D:/hf-cache")

import numpy as np
import pandas as pd
import torch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "external" / "Kronos"))
sys.path.insert(0, str(ROOT))

from model import Kronos, KronosTokenizer, KronosPredictor  # noqa: E402

# Inline parquet loader — avoids importing strategy_lab.run_v34_expand,
# which depends on talib (not installed in the D:/kronos-venv).
_FEAT_DIR = ROOT / "strategy_lab" / "features" / "multi_tf"
_SINCE = pd.Timestamp("2020-01-01", tz="UTC")

def _load(sym: str, tf: str) -> pd.DataFrame:
    p = _FEAT_DIR / f"{sym}_{tf}.parquet"
    if not p.exists():
        raise FileNotFoundError(p)
    df = pd.read_parquet(p).dropna(subset=["open", "high", "low", "close", "volume"])
    return df[df.index >= _SINCE]

OUT_DIR = HERE / "results" / "kronos"
OUT_DIR.mkdir(parents=True, exist_ok=True)
REPORT  = HERE / "reports" / "KRONOS_SNIFF_TEST_BASE.md"
REPORT.parent.mkdir(parents=True, exist_ok=True)

# -- Config ------------------------------------------------------------
SYM           = "BTCUSDT"
TF            = "4h"
LOOKBACK      = 256
PRED_LEN      = 20
TEST_START    = "2025-10-01"
TEST_END      = "2026-03-31"
SAMPLE_COUNT  = 16           # bumped from 8 — RTX 3060 has headroom
TEMPERATURE   = 1.0
TOP_P         = 0.9
TOKENIZER_HF  = "NeoQuasar/Kronos-Tokenizer-base"
MODEL_HF      = "NeoQuasar/Kronos-base"
DEVICE        = "cuda:0"


def prepare_df(sym: str, tf: str) -> pd.DataFrame:
    df = _load(sym, tf).copy()
    df["amount"] = df["volume"] * df["close"]
    df = df.reset_index().rename(columns={"open_time": "timestamps"})
    return df[["timestamps", "open", "high", "low", "close", "volume", "amount"]]


def run_sniff(predictor: KronosPredictor, df: pd.DataFrame) -> pd.DataFrame:
    test_mask = (df["timestamps"] >= TEST_START) & (df["timestamps"] < TEST_END)
    test_idx_arr = df.index[test_mask].to_numpy()
    if len(test_idx_arr) < PRED_LEN + LOOKBACK:
        raise ValueError(f"Not enough bars in test window: {len(test_idx_arr)}")

    rows = []
    earliest_start = max(LOOKBACK, int(test_idx_arr[0]))
    n = len(df)
    starts = list(range(earliest_start, n - PRED_LEN, PRED_LEN))
    starts = [s for s in starts
              if s >= int(test_idx_arr[0]) and s + PRED_LEN <= int(test_idx_arr[-1])]
    print(f"  Will run {len(starts)} non-overlapping forecast windows.")

    t0 = time.time()
    for k, s in enumerate(starts):
        ctx_lo = s - LOOKBACK
        x_df         = df.iloc[ctx_lo:s][["open", "high", "low", "close", "volume", "amount"]].reset_index(drop=True)
        x_timestamp  = df.iloc[ctx_lo:s]["timestamps"].reset_index(drop=True)
        y_timestamp  = df.iloc[s:s + PRED_LEN]["timestamps"].reset_index(drop=True)
        actual       = df.iloc[s:s + PRED_LEN]["close"].reset_index(drop=True)

        try:
            pred_df = predictor.predict(
                df=x_df, x_timestamp=x_timestamp, y_timestamp=y_timestamp,
                pred_len=PRED_LEN, T=TEMPERATURE, top_p=TOP_P,
                sample_count=SAMPLE_COUNT, verbose=False,
            )
        except Exception as e:
            print(f"  [{k+1}/{len(starts)}] FAIL @ {x_timestamp.iloc[-1]}: {e}")
            continue

        last_ctx_close   = float(x_df["close"].iloc[-1])
        pred_last_close  = float(pred_df["close"].iloc[-1])
        actual_last      = float(actual.iloc[-1])

        pred_ret   = pred_last_close / last_ctx_close - 1.0
        actual_ret = actual_last     / last_ctx_close - 1.0

        rows.append({
            "window":           k,
            "ctx_end_time":     x_timestamp.iloc[-1],
            "horizon_end_time": y_timestamp.iloc[-1],
            "last_ctx_close":   last_ctx_close,
            "pred_close":       pred_last_close,
            "actual_close":     actual_last,
            "pred_ret":         pred_ret,
            "actual_ret":       actual_ret,
            "abs_err_pct":      abs(pred_last_close - actual_last) / last_ctx_close,
            "direction_match":  int(np.sign(pred_ret) == np.sign(actual_ret)),
        })

        if (k + 1) % 5 == 0 or k == len(starts) - 1:
            elapsed = time.time() - t0
            eta     = elapsed / (k + 1) * (len(starts) - k - 1)
            vram    = torch.cuda.memory_allocated() / 1e9
            print(f"  [{k+1}/{len(starts)}] {x_timestamp.iloc[-1]}: "
                  f"pred {pred_ret*100:+.2f}%  actual {actual_ret*100:+.2f}%  "
                  f"({elapsed:.0f}s elapsed, ~{eta:.0f}s remaining, VRAM {vram:.1f}GB)")

    return pd.DataFrame(rows)


def summary(res: pd.DataFrame) -> dict:
    if len(res) < 5:
        return {"n": len(res), "note": "insufficient samples"}
    pearson  = float(res["pred_ret"].corr(res["actual_ret"]))
    spearman = float(res["pred_ret"].corr(res["actual_ret"], method="spearman"))
    dir_acc  = float(res["direction_match"].mean())
    mae      = float(res["abs_err_pct"].mean())
    bias_dir = float((res["actual_ret"] > 0).mean())
    return {
        "n":                int(len(res)),
        "pearson_corr":     round(pearson, 4),
        "spearman_corr":    round(spearman, 4),
        "direction_acc":    round(dir_acc, 4),
        "actual_pos_bias":  round(bias_dir, 4),
        "mean_abs_err_pct": round(mae, 4),
        "passes_gate":      bool(pearson > 0.10 and dir_acc > 0.52),
    }


def main() -> None:
    print(f"Phase 0 sniff test — Kronos-base on {SYM} {TF} (GPU)")
    print(f"  test window: {TEST_START} -> {TEST_END}")
    print(f"  lookback:    {LOOKBACK} bars  pred_len: {PRED_LEN}  sample_count: {SAMPLE_COUNT}")
    print(f"  device:      {DEVICE}")
    print()

    assert torch.cuda.is_available(), "CUDA not available; check the D:/kronos-venv install"
    print(f"  GPU: {torch.cuda.get_device_name(0)}  "
          f"VRAM {torch.cuda.get_device_properties(0).total_memory/1e9:.2f} GB")

    print("Loading Kronos-base + tokenizer ...")
    t0 = time.time()
    tokenizer = KronosTokenizer.from_pretrained(TOKENIZER_HF)
    model     = Kronos.from_pretrained(MODEL_HF)
    predictor = KronosPredictor(model, tokenizer, device=DEVICE, max_context=512)
    print(f"  loaded in {time.time()-t0:.1f}s  "
          f"(VRAM alloc {torch.cuda.memory_allocated()/1e9:.2f} GB)")

    print(f"Loading {SYM} {TF} OHLCV ...")
    df = prepare_df(SYM, TF)
    print(f"  {len(df):,} bars  {df['timestamps'].iloc[0]} -> {df['timestamps'].iloc[-1]}")

    print("\nRunning hold-out forecast walk ...")
    res = run_sniff(predictor, df)

    out_csv = OUT_DIR / f"sniff_test_{SYM}_{TF}_base.csv"
    res.to_csv(out_csv, index=False)
    print(f"\nWrote {out_csv}  ({len(res)} forecast windows)")

    s = summary(res)
    print("\n=== SUMMARY ===")
    print(json.dumps(s, indent=2, default=str))

    md = []
    md.append(f"# Kronos Phase 0 Sniff Test (base) — {SYM} {TF}\n")
    md.append(f"**Window**: {TEST_START} -> {TEST_END}  ")
    md.append(f"**Lookback**: {LOOKBACK} bars  **Pred len**: {PRED_LEN}  ")
    md.append(f"**Sample count**: {SAMPLE_COUNT}  **Model**: `{MODEL_HF}`  ")
    md.append(f"**Device**: `{DEVICE}`\n")
    md.append("## Result\n")
    md.append("| Metric | Value |\n|---|---:|")
    for k, v in s.items():
        md.append(f"| {k} | {v} |")
    md.append("\n## Verdict\n")
    if s.get("passes_gate"):
        md.append(f"PASS — Pearson {s['pearson_corr']} > 0.10 and direction "
                  f"accuracy {s['direction_acc']} > 0.52. Proceed to Phase 1.")
    else:
        md.append(f"FAIL — raw Kronos-base has no usable edge on BTC 4h. "
                  "Consider fine-tuning or trying a different timeframe.")
    md.append(f"\nSee [`results/kronos/sniff_test_{SYM}_{TF}_base.csv`]"
              f"(../results/kronos/sniff_test_{SYM}_{TF}_base.csv).")
    REPORT.write_text("\n".join(md), encoding="utf-8")
    print(f"\nWrote {REPORT}")


if __name__ == "__main__":
    main()
