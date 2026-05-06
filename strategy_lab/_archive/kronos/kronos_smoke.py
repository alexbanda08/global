"""Smoke test: load Kronos and predict ONE bar. Must complete in <60s."""
from __future__ import annotations
import os, sys, time
from pathlib import Path

os.environ.setdefault("HF_HOME", "D:/hf-cache")
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

print(f"[{time.strftime('%H:%M:%S')}] start", flush=True)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "external" / "Kronos"))
sys.path.insert(0, str(ROOT))

print(f"[{time.strftime('%H:%M:%S')}] importing torch...", flush=True)
import torch
print(f"[{time.strftime('%H:%M:%S')}] torch={torch.__version__}  cuda={torch.cuda.is_available()}", flush=True)

print(f"[{time.strftime('%H:%M:%S')}] importing kronos...", flush=True)
from model import Kronos, KronosTokenizer, KronosPredictor

print(f"[{time.strftime('%H:%M:%S')}] loading tokenizer...", flush=True)
tok_path = "D:/kronos-ft/BTCUSDT_5m_3y_polymarket_short/tokenizer/best_model"
tok = KronosTokenizer.from_pretrained(tok_path)
print(f"[{time.strftime('%H:%M:%S')}] tokenizer ok", flush=True)

print(f"[{time.strftime('%H:%M:%S')}] loading basemodel...", flush=True)
mdl_path = "D:/kronos-ft/BTCUSDT_5m_3y_polymarket_short/basemodel/best_model"
mdl = Kronos.from_pretrained(mdl_path)
print(f"[{time.strftime('%H:%M:%S')}] basemodel ok", flush=True)

print(f"[{time.strftime('%H:%M:%S')}] building predictor...", flush=True)
predictor = KronosPredictor(mdl, tok, device="cuda:0", max_context=512)
print(f"[{time.strftime('%H:%M:%S')}] predictor ok", flush=True)

print(f"[{time.strftime('%H:%M:%S')}] running ONE prediction...", flush=True)
import pandas as pd
df = pd.read_csv("strategy_lab/kronos_ft/data/BTCUSDT_5m_ext.csv")
df["timestamps"] = pd.to_datetime(df["timestamps"])
window = df.iloc[-515:-3]  # 512 bars context
y_ts = df.iloc[-3:]["timestamps"].reset_index(drop=True)
x_df = window[["open","high","low","close","volume","amount"]].reset_index(drop=True)
x_ts = window["timestamps"].reset_index(drop=True)

t0 = time.time()
pred = predictor.predict(df=x_df, x_timestamp=x_ts, y_timestamp=y_ts,
                         pred_len=3, T=1.0, top_p=0.9, sample_count=1, verbose=False)
print(f"[{time.strftime('%H:%M:%S')}] predict took {time.time()-t0:.1f}s", flush=True)
print(f"  pred close: {pred['close'].tolist()}", flush=True)
print(f"  c0 (last actual): {x_df['close'].iloc[-1]}", flush=True)
print("DONE", flush=True)
