"""
V37 minimal smoke test.

Proves the LLM call layer works end-to-end with what's installed in Python 3.12:
  - pandas + pyarrow (read parquet)
  - v37_claude_trader.build_snapshot (no vectorbt/talib needed)
  - v37_providers.ClaudeCLIProvider (subprocess to `claude` CLI)
  - Decision JSON parses

This intentionally does NOT import strategy_lab.engine or run_v16_1h_hunt
(which require vectorbt and talib that aren't installed yet).

Usage:
    py -3.12 strategy_lab/smoke_v37.py
    py -3.12 strategy_lab/smoke_v37.py --provider openrouter --model "z-ai/glm-4.5"
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Force UTF-8 for stdout BEFORE any other imports/prints (Windows default
# cp1252 chokes on → arrows in our snapshot text).
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import pandas as pd

# Make the package importable when run as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from strategy_lab.v37_claude_trader import (
    build_snapshot, snapshot_hash, load_system_prompt, LOOKBACK_BARS,
)
from strategy_lab.v37_providers import make_provider

# Self-managed log so we don't depend on shell redirects (Git Bash on Windows
# mangles `>` and `2>&1` when running through certain wrappers).
LOG_PATH = Path(__file__).resolve().parent / "smoke_v37.log"


def log(msg: str) -> None:
    """Print AND append to log file. Flush immediately."""
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    sys.stdout.write(line + "\n")
    sys.stdout.flush()
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()


PARQUET_ROOT = Path(__file__).resolve().parent.parent / "data" / "binance" / "parquet"


def load_parquet(symbol: str, tf: str, start: str = "2024-01-01") -> pd.DataFrame:
    """Tiny re-implementation of engine.load() that doesn't need vectorbt."""
    folder = PARQUET_ROOT / symbol / tf
    if not folder.exists():
        raise FileNotFoundError(folder)
    parts = sorted(folder.glob("year=*/part.parquet"))
    df = pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)
    df = (df.drop_duplicates("open_time")
            .sort_values("open_time")
            .set_index("open_time"))
    df = df[df.index >= pd.Timestamp(start, tz="UTC")]
    return df[["open", "high", "low", "close", "volume"]].astype("float64")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coin", default="SOLUSDT")
    ap.add_argument("--tf", default="4h")
    ap.add_argument("--provider", default="claude-cli",
                    choices=["claude-cli", "anthropic-api", "openrouter"])
    ap.add_argument("--model", default=None,
                    help="claude-cli: 'sonnet'/'haiku'; "
                         "anthropic-api: 'claude-sonnet-4-6'; "
                         "openrouter: e.g. 'z-ai/glm-4.5'")
    args = ap.parse_args()

    log(f"=== V37 smoke test ===")
    log(f"  coin={args.coin}  tf={args.tf}  provider={args.provider}  "
          f"model={args.model or '(default)'}")

    # 1. Load data
    df = load_parquet(args.coin, args.tf)
    log(f"\n[1/4] Loaded {len(df):,} bars  "
          f"{df.index[0].date()} → {df.index[-1].date()}")

    # 2. Build snapshot (latest LOOKBACK_BARS bars, strict past)
    if len(df) < LOOKBACK_BARS:
        log(f"  ! only {len(df)} bars — need {LOOKBACK_BARS}")
        return 1
    df_hist = df.iloc[-LOOKBACK_BARS:]
    snap = build_snapshot(df_hist, args.coin)
    log(f"[2/4] Snapshot built: {len(snap):,} chars  "
          f"hash={snapshot_hash(snap)}")
    log(f"  preview (first 400 chars):\n  {snap[:400]!s}\n  ...")

    # 3. Build provider
    kwargs = {}
    if args.model:
        kwargs["model"] = args.model
    provider = make_provider(args.provider, **kwargs)
    log(f"\n[3/4] Provider ready: {provider.name}")

    # 4. Call LLM and parse
    system = load_system_prompt()
    log(f"  system prompt: {len(system):,} chars")
    log(f"  calling {provider.name}...")
    decision = provider.decide(snap, system)
    log(f"\n[4/4] Decision returned:")
    log(f"  regime     : {decision.regime}")
    log(f"  strategy   : {decision.strategy}")
    log(f"  direction  : {decision.direction}")
    log(f"  size_mult  : {decision.size_mult}")
    log(f"  confidence : {decision.confidence}")
    log(f"  rationale  : {decision.rationale}")
    log(f"\nSMOKE TEST PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
