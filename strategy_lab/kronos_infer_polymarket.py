"""
kronos_infer_polymarket — v2: clean timestamp matching without TZ gymnastics.

Both the BTC CSV and markets.csv have timestamp info; we match in naive CEST.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("HF_HOME", "D:/hf-cache")

import pandas as pd
import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "external" / "Kronos"))
sys.path.insert(0, str(ROOT))

from model import Kronos, KronosTokenizer, KronosPredictor  # noqa: E402


CONFIG_PATH = HERE / "kronos_ft" / "config_btc_5m_3y.yaml"
MARKETS_CSV = HERE / "data" / "polymarket" / "btc_markets.csv"
HIST_CSV = HERE / "kronos_ft" / "data" / "BTCUSDT_5m_3y.csv"
APR_CSV  = HERE / "kronos_ft" / "data" / "BTCUSDT_5m_apr.csv"
OUT_CSV  = HERE / "results" / "kronos" / "kronos_polymarket_predictions_s30.csv"

LOOKBACK = 512
PRED_LEN = 3
SAMPLE_COUNT = 30    # average over 30 stochastic samples per prediction


def load_combined_btc() -> pd.DataFrame:
    a = pd.read_csv(HIST_CSV)
    a["timestamps"] = pd.to_datetime(a["timestamps"])
    b = pd.read_csv(APR_CSV)
    b["timestamps"] = pd.to_datetime(b["timestamps"])
    cutoff = a["timestamps"].max()
    b = b[b["timestamps"] > cutoff].copy()
    return pd.concat([a, b], ignore_index=True).sort_values("timestamps").reset_index(drop=True)


def load_config():
    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    mp = cfg["model_paths"]
    exp, base = mp.get("exp_name", ""), mp.get("base_path", "")
    mp["finetuned_tokenizer"] = f"{base}/{exp}/tokenizer/best_model"
    mp["finetuned_basemodel"] = f"{base}/{exp}/basemodel/best_model"
    return cfg


def main():
    cfg = load_config()
    mp = cfg["model_paths"]
    print(f"[{time.strftime('%H:%M:%S')}] Loading Kronos...", flush=True)
    tok = KronosTokenizer.from_pretrained(mp["finetuned_tokenizer"])
    mdl = Kronos.from_pretrained(mp["finetuned_basemodel"])
    predictor = KronosPredictor(mdl, tok, device="cuda:0",
                                max_context=int(cfg["data"]["max_context"]))
    print(f"[{time.strftime('%H:%M:%S')}] Model ready", flush=True)

    df = load_combined_btc()
    print(f"BTC bars: {len(df)}  {df.timestamps.min()} -> {df.timestamps.max()}", flush=True)

    # Build O(1) lookup: naive CEST timestamp -> row index
    ts_to_idx = {ts: i for i, ts in enumerate(df["timestamps"].values)}

    # Load markets. window_start_at is a string like "2026-04-22 17:30:00+02".
    # Parse, convert to Europe/Berlin (== CEST), strip tz -> naive CEST.
    markets = pd.read_csv(MARKETS_CSV)
    markets = markets[markets.entry_yes_ask.notna() & markets.entry_no_ask.notna()
                      & markets.outcome_up.notna()].reset_index(drop=True)
    ws = pd.to_datetime(markets["window_start_at"], utc=True).dt.tz_convert("Europe/Berlin").dt.tz_localize(None)
    markets["window_start_cest"] = ws
    # target ctx_end bar's timestamp = window_start - 5 min
    markets["ctx_end_cest"] = ws - pd.Timedelta(minutes=5)
    print(f"Markets to infer: {len(markets)}", flush=True)

    hits = markets["ctx_end_cest"].map(lambda t: t.to_datetime64() in ts_to_idx).sum()
    print(f"Sanity: window-start matches in BTC CSV: {hits}/{len(markets)}", flush=True)
    # Print a few diagnostic examples
    for i in range(min(3, len(markets))):
        t = markets["ctx_end_cest"].iloc[i]
        t64 = t.to_datetime64()
        print(f"  market[{i}] slug={markets.slug.iloc[i]} "
              f"ctx_end_cest={t} -> match={t64 in ts_to_idx}", flush=True)

    rows = []
    t0 = time.time()
    for k, m in markets.iterrows():
        t64 = m.ctx_end_cest.to_datetime64()
        if t64 not in ts_to_idx:
            continue
        ctx_idx = ts_to_idx[t64]  # index of last context bar
        s = ctx_idx + 1            # first prediction bar
        if s - LOOKBACK < 0 or s + PRED_LEN > len(df):
            continue
        x_df = df.iloc[s - LOOKBACK:s][["open", "high", "low", "close", "volume", "amount"]].reset_index(drop=True)
        x_ts = df.iloc[s - LOOKBACK:s]["timestamps"].reset_index(drop=True)
        y_ts = df.iloc[s:s + PRED_LEN]["timestamps"].reset_index(drop=True)
        c0 = float(x_df["close"].iloc[-1])
        try:
            pred = predictor.predict(
                df=x_df, x_timestamp=x_ts, y_timestamp=y_ts,
                pred_len=PRED_LEN, T=1.0, top_p=0.9,
                sample_count=SAMPLE_COUNT, verbose=False,
            )
        except Exception as e:
            print(f"  [{k+1}/{len(markets)}] FAIL ({m.slug}): {e}", flush=True)
            continue
        pc = pred["close"].tolist()
        rows.append({
            "slug": m.slug,
            "timeframe": m.timeframe,
            "window_start_unix": m.window_start_unix,
            "ctx_end_ts": x_ts.iloc[-1],
            "c0": c0,
            "pred_close_5m": pc[0],
            "pred_close_15m": pc[2],
            "pred_ret_5m": pc[0] / c0 - 1,
            "pred_ret_15m": pc[2] / c0 - 1,
            "pred_dir_5m": int(pc[0] > c0),
            "pred_dir_15m": int(pc[2] > c0),
        })
        if (k + 1) % 10 == 0 or k == len(markets) - 1:
            el = time.time() - t0
            rate = (k + 1) / max(el, 0.1)
            eta = (len(markets) - k - 1) / max(rate, 0.001)
            print(f"  [{k+1}/{len(markets)}] {el:.0f}s elapsed, eta {eta:.0f}s, n_rows={len(rows)}", flush=True)

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(OUT_CSV, index=False)
    print(f"\nWrote {len(rows)} predictions to {OUT_CSV}", flush=True)


if __name__ == "__main__":
    main()
