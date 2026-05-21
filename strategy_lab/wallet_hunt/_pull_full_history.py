"""Pull 7-day chain history for all 6 wallets sequentially.

Designed for unattended run — explicit logging per wallet, robust to RPC
hiccups, writes parquets atomically so partial progress isn't lost.
"""
import subprocess
import sys
import time
from pathlib import Path

WALLETS = [
    "0xeebde7a0e019a63e6b476eb425505b7b3e6eba30",
    "0xce25e214d5cfe4f459cf67f08df581885aae7fdc",
    "0x89b5cdaaa4866c1e738406712012a630b4078beb",
    "0x7cde1da9d380bf8002ccbe8e0cb9474c4d71e48e",
    "0xcfb103c37c0234f524c632d964ed31f117b5f694",
    "0x04b6d7e930cf9e493c5e6ef24b496294f95594c8",
]
DAYS = 7

ROOT = Path(__file__).resolve().parents[2]
script = ROOT / "strategy_lab" / "wallet_hunt" / "fetch_chain.py"

for i, w in enumerate(WALLETS, 1):
    t0 = time.time()
    print(f"\n{'#' * 70}")
    print(f"# [{i}/{len(WALLETS)}] {w} — {DAYS} days")
    print(f"{'#' * 70}", flush=True)
    r = subprocess.run(
        [sys.executable, "-X", "utf8", "-u", str(script),
         "--wallet", w, "--days", str(DAYS)],
        capture_output=False, text=True,
    )
    dt = time.time() - t0
    print(f"# exit={r.returncode}  elapsed={dt:.0f}s", flush=True)

print(f"\n{'#' * 70}")
print("# ALL 6 WALLETS DONE")
print(f"{'#' * 70}", flush=True)
