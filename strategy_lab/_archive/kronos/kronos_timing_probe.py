"""Time a single Kronos predict() call to verify GPU is doing the work."""
import os
os.environ.setdefault("HF_HOME", "D:/hf-cache")
import sys, time
from pathlib import Path
import pandas as pd
import torch
import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "external" / "Kronos"))
sys.path.insert(0, str(HERE.parent))
from model import Kronos, KronosTokenizer, KronosPredictor

with open(HERE / "kronos_ft" / "config_btc_5m_3y.yaml") as f:
    cfg = yaml.safe_load(f)
mp = cfg["model_paths"]
base = mp["base_path"]
exp = mp["exp_name"]
tok_path = f"{base}/{exp}/tokenizer/best_model"
mdl_path = f"{base}/{exp}/basemodel/best_model"

print(f"[{time.strftime('%H:%M:%S')}] Loading model...")
t0 = time.time()
tok = KronosTokenizer.from_pretrained(tok_path)
mdl = Kronos.from_pretrained(mdl_path)
pred = KronosPredictor(mdl, tok, device="cuda:0", max_context=512)
print(f"Load took {time.time()-t0:.1f}s")
print(f"Device: cuda is_available={torch.cuda.is_available()}, device_name={torch.cuda.get_device_name() if torch.cuda.is_available() else 'N/A'}")
print(f"Model device: {next(mdl.parameters()).device}")

# Load data
df = pd.read_csv(HERE / "kronos_ft" / "data" / "BTCUSDT_5m_apr.csv")
df["timestamps"] = pd.to_datetime(df["timestamps"])
x_df = df.iloc[-512 - 3:-3][["open","high","low","close","volume","amount"]].reset_index(drop=True)
x_ts = df.iloc[-512 - 3:-3]["timestamps"].reset_index(drop=True)
y_ts = df.iloc[-3:]["timestamps"].reset_index(drop=True)

# Warm-up call (first call has PyTorch kernel compilation overhead)
print(f"\n[{time.strftime('%H:%M:%S')}] Warm-up call (pred_len=3)...")
t0 = time.time()
_ = pred.predict(df=x_df, x_timestamp=x_ts, y_timestamp=y_ts, pred_len=3, T=1.0, top_p=0.9, sample_count=1, verbose=False)
torch.cuda.synchronize()
print(f"Warm-up: {time.time()-t0:.3f}s")

# Timing runs
for n in range(5):
    t0 = time.time()
    result = pred.predict(df=x_df, x_timestamp=x_ts, y_timestamp=y_ts, pred_len=3, T=1.0, top_p=0.9, sample_count=1, verbose=False)
    torch.cuda.synchronize()
    dt = time.time() - t0
    close_preds = result["close"].tolist()
    print(f"Run {n+1}: {dt:.3f}s, pred_closes={close_preds}")

# Also time a pred_len=9 to compare
print(f"\n[{time.strftime('%H:%M:%S')}] Timing pred_len=9:")
y_ts9 = df.iloc[-9:]["timestamps"].reset_index(drop=True) if len(df) >= 9 else y_ts
for n in range(3):
    t0 = time.time()
    result = pred.predict(df=x_df, x_timestamp=x_ts, y_timestamp=y_ts9, pred_len=9, T=1.0, top_p=0.9, sample_count=1, verbose=False)
    torch.cuda.synchronize()
    dt = time.time() - t0
    print(f"Run {n+1}: {dt:.3f}s")

# GPU memory check
print(f"\nGPU mem allocated: {torch.cuda.memory_allocated()/1024**2:.1f} MB")
print(f"GPU mem reserved:  {torch.cuda.memory_reserved()/1024**2:.1f} MB")
