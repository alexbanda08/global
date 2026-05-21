"""Pull 2-day chain history for all 6 wallets in sequence."""
import subprocess
import sys
from pathlib import Path

WALLETS = [
    "0xeebde7a0e019a63e6b476eb425505b7b3e6eba30",
    "0xce25e214d5cfe4f459cf67f08df581885aae7fdc",
    "0x89b5cdaaa4866c1e738406712012a630b4078beb",
    "0x7cde1da9d380bf8002ccbe8e0cb9474c4d71e48e",
    "0xcfb103c37c0234f524c632d964ed31f117b5f694",
    "0x04b6d7e930cf9e493c5e6ef24b496294f95594c8",
]
DAYS = 2

ROOT = Path(__file__).resolve().parents[2]
script = ROOT / "strategy_lab" / "wallet_hunt" / "fetch_chain.py"

for i, w in enumerate(WALLETS, 1):
    print(f"\n{'=' * 60}")
    print(f"[{i}/{len(WALLETS)}] {w}")
    print(f"{'=' * 60}")
    r = subprocess.run(
        [sys.executable, "-X", "utf8", "-u", str(script), "--wallet", w, "--days", str(DAYS)],
        capture_output=False, text=True
    )
    print(f"  exit code: {r.returncode}")
print("\nALL DONE")
