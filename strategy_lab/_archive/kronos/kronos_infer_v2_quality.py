"""
kronos_infer_v2_quality — high-quality re-run at sample_count=30 for overnight.

Same model + universe as kronos_infer_v3_universe.py, but sample_count=30 (vs 5)
for proper Monte-Carlo averaging. Output to a separate file so the v1 results stay
intact for comparison.

Expected runtime: ~6h on RTX 3060 for 4,673 markets.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("HF_HOME", "D:/hf-cache")
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

import pandas as pd
import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "external" / "Kronos"))
sys.path.insert(0, str(ROOT))

from model import Kronos, KronosTokenizer, KronosPredictor  # noqa: E402

CONFIG_PATH = HERE / "kronos_ft" / "config_btc_5m_3y.yaml"
MARKETS_CSV = ROOT / "data" / "v4" / "refresh_2026_05_02" / "btc_markets_minimal.csv"
HIST_CSV = HERE / "kronos_ft" / "data" / "BTCUSDT_5m_ext.csv"
OUT_CSV = HERE / "results" / "kronos" / "kronos_btc_predictions_full_s30.csv"

LOOKBACK = 512
PRED_LEN = 3
SAMPLE_COUNT = 30


def load_btc_5m() -> pd.DataFrame:
    df = pd.read_csv(HIST_CSV)
    df["timestamps"] = pd.to_datetime(df["timestamps"])
    return df.sort_values("timestamps").reset_index(drop=True)


def load_config():
    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    mp = cfg["model_paths"]
    exp, base = mp.get("exp_name", ""), mp.get("base_path", "")
    mp["finetuned_tokenizer"] = f"{base}/{exp}/tokenizer/best_model"
    mp["finetuned_basemodel"] = f"{base}/{exp}/basemodel/best_model"
    return cfg


def load_markets() -> pd.DataFrame:
    m = pd.read_csv(MARKETS_CSV)
    m = m.dropna(subset=["window_start_unix", "outcome_up"]).copy()
    m["window_start_at_utc"] = pd.to_datetime(m["window_start_unix"], unit="s", utc=True)
    m["ctx_end_cest"] = (
        m["window_start_at_utc"].dt.tz_convert("Europe/Berlin").dt.tz_localize(None)
        - pd.Timedelta(minutes=5)
    )
    cols = ["slug", "timeframe", "window_start_unix", "outcome_up", "ctx_end_cest"]
    return m[cols].reset_index(drop=True)


def load_existing_output() -> set[str]:
    if not OUT_CSV.exists():
        return set()
    try:
        prev = pd.read_csv(OUT_CSV)
        return set(prev["slug"].tolist())
    except Exception:
        return set()


def main():
    cfg = load_config()
    mp = cfg["model_paths"]
    print(f"[{time.strftime('%H:%M:%S')}] Loading Kronos (sample_count={SAMPLE_COUNT}) ...", flush=True)
    tok = KronosTokenizer.from_pretrained(mp["finetuned_tokenizer"])
    mdl = Kronos.from_pretrained(mp["finetuned_basemodel"])
    predictor = KronosPredictor(mdl, tok, device="cuda:0",
                                max_context=int(cfg["data"]["max_context"]))
    print(f"[{time.strftime('%H:%M:%S')}] Model ready", flush=True)

    df = load_btc_5m()
    print(f"BTC 5m bars: {len(df):,}  {df.timestamps.min()} -> {df.timestamps.max()}", flush=True)
    ts_to_idx = {ts: i for i, ts in enumerate(df["timestamps"].values)}

    markets = load_markets()
    print(f"Markets: {len(markets)}", flush=True)

    done = load_existing_output()
    if done:
        print(f"Resume: {len(done)} already done, skipping", flush=True)
        markets = markets[~markets["slug"].isin(done)].reset_index(drop=True)
        print(f"Remaining: {len(markets)}", flush=True)

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    write_header = not OUT_CSV.exists()

    rows = []
    skipped = 0
    failed = 0
    t0 = time.time()
    flush_every = 25

    for k, m in markets.iterrows():
        t64 = m.ctx_end_cest.to_datetime64()
        if t64 not in ts_to_idx:
            skipped += 1
            continue
        ctx_idx = ts_to_idx[t64]
        s = ctx_idx + 1
        if s - LOOKBACK < 0 or s + PRED_LEN > len(df):
            skipped += 1
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
            failed += 1
            print(f"  [{k+1}/{len(markets)}] FAIL ({m.slug}): {e}", flush=True)
            continue
        pc = pred["close"].tolist()
        rows.append({
            "slug": m.slug,
            "timeframe": m.timeframe,
            "window_start_unix": int(m.window_start_unix),
            "ctx_end_ts": x_ts.iloc[-1],
            "c0": c0,
            "pred_close_5m": pc[0],
            "pred_close_15m": pc[2],
            "pred_ret_5m": pc[0] / c0 - 1,
            "pred_ret_15m": pc[2] / c0 - 1,
            "pred_dir_5m": int(pc[0] > c0),
            "pred_dir_15m": int(pc[2] > c0),
            "outcome_up": int(m.outcome_up),
        })
        if (k + 1) % flush_every == 0:
            chunk = pd.DataFrame(rows)
            chunk.to_csv(OUT_CSV, mode="a", header=write_header, index=False)
            write_header = False
            rows = []
            el = time.time() - t0
            rate = (k + 1) / max(el, 0.1)
            eta = (len(markets) - k - 1) / max(rate, 0.001)
            print(f"  [{k+1}/{len(markets)}] el={el:.0f}s rate={rate:.2f}/s eta={eta/60:.1f}min "
                  f"skipped={skipped} failed={failed}", flush=True)

    if rows:
        chunk = pd.DataFrame(rows)
        chunk.to_csv(OUT_CSV, mode="a", header=write_header, index=False)
    el = time.time() - t0
    print(f"\nDone in {el/60:.1f}min. skipped={skipped} failed={failed}", flush=True)


if __name__ == "__main__":
    main()
