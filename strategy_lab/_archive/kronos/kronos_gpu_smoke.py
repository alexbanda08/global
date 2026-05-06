"""
kronos_gpu_smoke — validates the D:/kronos-venv install of Kronos-base on GPU.

Run with:
  D:/kronos-venv/Scripts/python.exe strategy_lab/kronos_gpu_smoke.py

It:
  1. Confirms CUDA is visible (RTX 3060 12GB expected).
  2. Loads Kronos-Tokenizer-base + Kronos-base (102.3M params) onto cuda:0.
  3. Prints the peak VRAM used after load.
  4. Runs ONE 20-bar forecast on a synthetic random-walk OHLCV sample to
     prove the predict() path works end-to-end before the full sniff test.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("HF_HOME", "D:/hf-cache")

import numpy as np
import pandas as pd
import torch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "external" / "Kronos"))

from model import Kronos, KronosTokenizer, KronosPredictor  # noqa: E402


def main() -> None:
    assert torch.cuda.is_available(), "CUDA not available on this venv"
    dev = torch.cuda.get_device_name(0)
    vram = torch.cuda.get_device_properties(0).total_memory / 1e9
    print(f"GPU: {dev}  ({vram:.2f} GB)")
    print(f"Torch: {torch.__version__}  CUDA: {torch.version.cuda}")

    t0 = time.time()
    tok = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base")
    mdl = Kronos.from_pretrained("NeoQuasar/Kronos-base")
    predictor = KronosPredictor(mdl, tok, device="cuda:0", max_context=512)
    print(f"Load time: {time.time()-t0:.1f}s")
    print(f"VRAM after load: {torch.cuda.memory_allocated()/1e9:.2f} GB "
          f"(reserved {torch.cuda.memory_reserved()/1e9:.2f} GB)")

    # Synthesize 256 bars of random-walk OHLCV at 4h cadence.
    rng = np.random.default_rng(42)
    n = 256
    rets = rng.normal(0, 0.01, n)
    close = 50_000 * np.exp(np.cumsum(rets))
    openp = np.r_[close[0], close[:-1]]
    high = np.maximum(openp, close) * (1 + np.abs(rng.normal(0, 0.003, n)))
    low = np.minimum(openp, close) * (1 - np.abs(rng.normal(0, 0.003, n)))
    volume = rng.lognormal(5, 0.4, n)
    amount = volume * close
    idx = pd.date_range("2025-01-01", periods=n + 20, freq="4h")

    x_df = pd.DataFrame({
        "open": openp, "high": high, "low": low,
        "close": close, "volume": volume, "amount": amount,
    })
    x_ts = pd.Series(idx[:n])
    y_ts = pd.Series(idx[n:n + 20])

    t1 = time.time()
    pred = predictor.predict(
        df=x_df, x_timestamp=x_ts, y_timestamp=y_ts,
        pred_len=20, T=1.0, top_p=0.9, sample_count=4, verbose=False,
    )
    elapsed = time.time() - t1
    print(f"Forecast OK — shape={pred.shape}  elapsed={elapsed:.2f}s  "
          f"sec/call={elapsed:.2f} (4 samples, 20 bars)")
    print(pred.head())
    print(f"Peak VRAM: {torch.cuda.max_memory_allocated()/1e9:.2f} GB")


if __name__ == "__main__":
    main()
