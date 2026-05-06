"""
kronos_sniff_test — Phase 0 viability test of Kronos as a crypto indicator.

Question: does pre-trained Kronos-small (trained on Chinese A-share equities)
produce ANY usable signal on Binance BTC 4h data without fine-tuning?

Method:
  * Hold-out window: 2025-10-01 -> 2026-03-31 (~6 months OOS).
  * For each non-overlapping 20-bar segment, take the prior 256 bars as
    context and call Kronos predict(pred_len=20, sample_count=8).
  * Compare predicted N-bar return vs actual N-bar return.

Pass gate: Pearson(pred_ret, actual_ret) > 0.10 AND direction accuracy > 0.52.

Outputs:
  strategy_lab/results/kronos/sniff_test_BTC_4h.csv  -- per-window forecasts
  strategy_lab/reports/KRONOS_SNIFF_TEST.md          -- one-page result
"""
from __future__ import annotations
import sys, json, time
from pathlib import Path

import numpy as np
import pandas as pd

# Vendor Kronos from external/
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "external" / "Kronos"))
sys.path.insert(0, str(ROOT))

from model import Kronos, KronosTokenizer, KronosPredictor  # noqa: E402
from strategy_lab.run_v34_expand import _load                # noqa: E402

OUT_DIR = HERE / "results" / "kronos"
OUT_DIR.mkdir(parents=True, exist_ok=True)
REPORT  = HERE / "reports" / "KRONOS_SNIFF_TEST.md"


# -- Config ------------------------------------------------------------
SYM           = "BTCUSDT"
TF            = "4h"
LOOKBACK      = 256          # bars of context (max_context=512 for Kronos-small)
PRED_LEN      = 20           # forecast 20 bars (~3.3 days at 4h)
TEST_START    = "2025-10-01"
TEST_END      = "2026-03-31"
SAMPLE_COUNT  = 8            # average across 8 stochastic paths for stability
TEMPERATURE   = 1.0
TOP_P         = 0.9
TOKENIZER_HF  = "NeoQuasar/Kronos-Tokenizer-base"
MODEL_HF      = "NeoQuasar/Kronos-small"


def prepare_df(sym: str, tf: str) -> pd.DataFrame:
    """Load OHLCV, synthesize 'amount' = volume * close (quote-volume proxy)."""
    df = _load(sym, tf).copy()
    df["amount"] = df["volume"] * df["close"]
    df = df.reset_index().rename(columns={"open_time": "timestamps"})
    return df[["timestamps", "open", "high", "low", "close", "volume", "amount"]]


def run_sniff(predictor: KronosPredictor, df: pd.DataFrame) -> pd.DataFrame:
    """Walk through the hold-out window in non-overlapping PRED_LEN segments."""
    test_mask = (df["timestamps"] >= TEST_START) & (df["timestamps"] < TEST_END)
    test_idx_arr = df.index[test_mask].to_numpy()
    if len(test_idx_arr) < PRED_LEN + LOOKBACK:
        raise ValueError(f"Not enough bars in test window: {len(test_idx_arr)}")

    rows = []
    # Iterate non-overlapping windows — start of each forecast window must
    # have at least LOOKBACK history available BEFORE it.
    earliest_start = max(LOOKBACK, int(test_idx_arr[0]))
    n = len(df)
    starts = list(range(earliest_start, n - PRED_LEN, PRED_LEN))
    starts = [s for s in starts if s >= int(test_idx_arr[0]) and s + PRED_LEN <= int(test_idx_arr[-1])]
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
            "window":          k,
            "ctx_end_time":    x_timestamp.iloc[-1],
            "horizon_end_time": y_timestamp.iloc[-1],
            "last_ctx_close":  last_ctx_close,
            "pred_close":      pred_last_close,
            "actual_close":    actual_last,
            "pred_ret":        pred_ret,
            "actual_ret":      actual_ret,
            "abs_err_pct":     abs(pred_last_close - actual_last) / last_ctx_close,
            "direction_match": int(np.sign(pred_ret) == np.sign(actual_ret)),
        })

        if (k + 1) % 5 == 0 or k == len(starts) - 1:
            elapsed = time.time() - t0
            eta     = elapsed / (k + 1) * (len(starts) - k - 1)
            print(f"  [{k+1}/{len(starts)}] {x_timestamp.iloc[-1]}: "
                  f"pred {pred_ret*100:+.2f}%  actual {actual_ret*100:+.2f}%  "
                  f"({elapsed:.0f}s elapsed, ~{eta:.0f}s remaining)")

    return pd.DataFrame(rows)


def summary(res: pd.DataFrame) -> dict:
    if len(res) < 5:
        return {"n": len(res), "note": "insufficient samples"}
    pearson = float(res["pred_ret"].corr(res["actual_ret"]))
    spearman = float(res["pred_ret"].corr(res["actual_ret"], method="spearman"))
    dir_acc  = float(res["direction_match"].mean())
    mae      = float(res["abs_err_pct"].mean())
    # Naive baseline: always predict 0% return → direction accuracy of buying-and-holding bias
    bias_dir = float((res["actual_ret"] > 0).mean())
    return {
        "n":                 int(len(res)),
        "pearson_corr":      round(pearson, 4),
        "spearman_corr":     round(spearman, 4),
        "direction_acc":     round(dir_acc, 4),
        "actual_pos_bias":   round(bias_dir, 4),
        "mean_abs_err_pct":  round(mae, 4),
        "passes_gate":       bool(pearson > 0.10 and dir_acc > 0.52),
    }


def main():
    print(f"Phase 0 sniff test — Kronos-small on {SYM} {TF}")
    print(f"  test window: {TEST_START} -> {TEST_END}")
    print(f"  lookback:    {LOOKBACK} bars  pred_len: {PRED_LEN}  sample_count: {SAMPLE_COUNT}")
    print()

    print("Loading model + tokenizer from HuggingFace ...")
    t0 = time.time()
    tokenizer = KronosTokenizer.from_pretrained(TOKENIZER_HF)
    model     = Kronos.from_pretrained(MODEL_HF)
    predictor = KronosPredictor(model, tokenizer, max_context=512)
    print(f"  loaded in {time.time()-t0:.1f}s")

    print(f"Loading {SYM} {TF} OHLCV ...")
    df = prepare_df(SYM, TF)
    print(f"  {len(df):,} bars  {df['timestamps'].iloc[0]} -> {df['timestamps'].iloc[-1]}")

    print("\nRunning hold-out forecast walk ...")
    res = run_sniff(predictor, df)

    out_csv = OUT_DIR / f"sniff_test_{SYM}_{TF}.csv"
    res.to_csv(out_csv, index=False)
    print(f"\nWrote {out_csv}  ({len(res)} forecast windows)")

    s = summary(res)
    print("\n=== SUMMARY ===")
    print(json.dumps(s, indent=2, default=str))

    md = []
    md.append(f"# Kronos Phase 0 Sniff Test — {SYM} {TF}\n")
    md.append(f"**Window**: {TEST_START} -> {TEST_END}  ")
    md.append(f"**Lookback**: {LOOKBACK} bars  **Pred len**: {PRED_LEN}  ")
    md.append(f"**Sample count**: {SAMPLE_COUNT}  **Model**: `{MODEL_HF}`\n")
    md.append("## Result\n")
    md.append("| Metric | Value |\n|---|---:|")
    for k, v in s.items():
        md.append(f"| {k} | {v} |")
    md.append("\n## Verdict\n")
    if s.get("passes_gate"):
        md.append(f"✅ **PASS** — Pearson {s['pearson_corr']} > 0.10 and direction "
                  f"accuracy {s['direction_acc']} > 0.52. Proceed to Phase 1.")
    else:
        md.append(f"❌ **FAIL** — raw model has no usable edge on this universe. "
                  "Either fine-tune Kronos-small on Binance 4h (Phase 3), "
                  "try a different timeframe, or drop the idea.")
    md.append("\n## Per-window forecasts\n")
    md.append(f"See [`results/kronos/sniff_test_{SYM}_{TF}.csv`](../results/kronos/sniff_test_{SYM}_{TF}.csv).")
    REPORT.write_text("\n".join(md), encoding="utf-8")
    print(f"\nWrote {REPORT}")


if __name__ == "__main__":
    main()
