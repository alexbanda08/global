"""
V52 SHADOW TICK  — the scheduled unit of work.

Run once per closed 4h bar (UTC 00/04/08/12/16/20 + a minute or two):
  1. Incrementally append fresh HL 4h klines + hourly funding for the 5 coins.
  2. Run the optimized-V52 shadow runner (paper, no real orders).

This is the single command to put on a schedule. It is idempotent: if no new
bar exists yet, the data step is a no-op and the runner just re-snapshots state.

Schedule examples
-----------------
Windows Task Scheduler (every 4h aligned to UTC bar closes + 2 min):
    schtasks /Create /TN "V52Shadow" /SC HOURLY /MO 4 /ST 00:02 ^
      /TR "py C:\\Users\\alexandre bandarra\\Desktop\\global\\shadow_v52\\shadow_tick.py"

cron (if on a *nix box, times in UTC):
    2 0,4,8,12,16,20 * * *  cd /path/global && py shadow_v52/shadow_tick.py >> shadow_v52/tick.log 2>&1
"""
from __future__ import annotations
import sys, subprocess
from pathlib import Path
from datetime import datetime, timezone
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# Import the tested paged fetchers + paths from the ingest module
from strategy_lab.ingest_hyperliquid import (
    fetch_candles_paged, fetch_funding_paged,
    KLINE_DIR, FUNDING_DIR, COINS, INTERVAL, INTERVAL_MS,
)

HOUR_MS = 60 * 60 * 1000


def _now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def refresh_klines(coin: str) -> str:
    out_dir = KLINE_DIR / coin
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{INTERVAL}.parquet"
    now_ms = _now_ms()
    if path.exists():
        existing = pd.read_parquet(path)
        last_ms = int(existing.index.max().timestamp() * 1000)
        new = fetch_candles_paged(coin, last_ms + INTERVAL_MS, now_ms)
        if len(new):
            df = pd.concat([existing, new]).drop_duplicates().sort_index()
            df.to_parquet(path)
            return f"{coin} klines +{len(new)} -> {df.index.max()}"
        return f"{coin} klines no-new (last {existing.index.max()})"
    else:
        df = fetch_candles_paged(coin, int(datetime(2023, 4, 1, tzinfo=timezone.utc).timestamp() * 1000), now_ms)
        if len(df):
            df.to_parquet(path)
            return f"{coin} klines bootstrap {len(df)}"
        return f"{coin} klines FAILED bootstrap"


def refresh_funding(coin: str) -> str:
    FUNDING_DIR.mkdir(parents=True, exist_ok=True)
    path = FUNDING_DIR / f"{coin}_funding.parquet"
    now_ms = _now_ms()
    if path.exists():
        existing = pd.read_parquet(path)
        last_ms = int(existing.index.max().timestamp() * 1000)
        new = fetch_funding_paged(coin, last_ms + HOUR_MS, now_ms)
        if len(new):
            df = pd.concat([existing, new]).drop_duplicates().sort_index()
            df.to_parquet(path)
            return f"{coin} funding +{len(new)} -> {df.index.max()}"
        return f"{coin} funding no-new (last {existing.index.max()})"
    else:
        df = fetch_funding_paged(coin, int(datetime(2023, 4, 1, tzinfo=timezone.utc).timestamp() * 1000), now_ms)
        if len(df):
            df.to_parquet(path)
            return f"{coin} funding bootstrap {len(df)}"
        return f"{coin} funding FAILED bootstrap"


def main():
    ts = datetime.now(timezone.utc).isoformat()
    print(f"=== HL shadow tick {ts} (V52 fleet + V53 breadth + XSM) ===")
    print("--- data refresh ---")
    for coin in COINS:
        try:
            print("  " + refresh_klines(coin))
            print("  " + refresh_funding(coin))
        except Exception as e:
            print(f"  {coin} refresh ERROR: {type(e).__name__}: {e}")

    here = Path(__file__).resolve().parent

    print("--- V52 shadow run (9 sleeves) ---")
    runner = REPO / "strategy_lab" / "hl_research_2026_05_26" / "v52_v24_audit" / "v52_shadow_runner.py"
    res = subprocess.run([sys.executable, str(runner), "--backfill-days", "60"],
                         capture_output=True, text=True)
    print(res.stdout.strip())
    if res.returncode != 0:
        print("V52 RUNNER STDERR:\n" + res.stderr[-2000:])

    print("--- V53 breadth shadow run (2 families x 10 coins) ---")
    res53 = subprocess.run([sys.executable, str(here / "v53_shadow_runner.py"),
                            "--backfill-days", "60"], capture_output=True, text=True)
    print(res53.stdout.strip())
    if res53.returncode != 0:
        print("V53 RUNNER STDERR:\n" + res53.stderr[-2000:])

    print("--- XSM shadow run (basket) ---")
    res_x = subprocess.run([sys.executable, str(here / "xsm_shadow.py")],
                           capture_output=True, text=True)
    print(res_x.stdout.strip())
    if res_x.returncode != 0:
        print("XSM STDERR:\n" + res_x.stderr[-2000:])

    print("--- refresh sleeve cards ---")
    res_c = subprocess.run([sys.executable, str(here / "build_sleeve_cards.py")],
                           capture_output=True, text=True)
    print(res_c.stdout.strip())
    if res_c.returncode != 0:
        print("CARDS STDERR:\n" + res_c.stderr[-1500:])

    print("--- refresh V53 breadth cards ---")
    res_c53 = subprocess.run([sys.executable, str(here / "build_v53_cards.py")],
                             capture_output=True, text=True)
    print(res_c53.stdout.strip())
    if res_c53.returncode != 0:
        print("V53 CARDS STDERR:\n" + res_c53.stderr[-1500:])

    print("--- TV dashboard cards feed (6 cards) ---")
    res_f = subprocess.run([sys.executable, str(here / "tv_cards_feed.py")],
                           capture_output=True, text=True)
    print(res_f.stdout.strip())
    if res_f.returncode != 0:
        print("FEED STDERR:\n" + res_f.stderr[-1500:])

    if res.returncode != 0:
        sys.exit(res.returncode)


if __name__ == "__main__":
    main()
