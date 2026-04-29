"""
V37 — Historical backtest runner: LLM-as-Trader.

Three providers (pick with --provider):
  claude-cli      Subprocess to your `claude` CLI. $0 if you're on Max/Pro.
                   Sequential, paced, slow. Best for first validation.
  anthropic-api   Official SDK + Batch API (50% off, async). Token-billed.
                   Best for full 5-coin daily-cadence runs.
  openrouter      OpenAI-compatible endpoint at openrouter.ai. Lets you swap
                   to GLM-4.5 / Kimi K2 / DeepSeek / Sonnet on the same code.

Examples:
    # 1. Smoke test (no API spend, just builds snapshots)
    py -m strategy_lab.run_v37_claude_trader --coin SOLUSDT --dry-run

    # 2. Use your Max 20× subscription, weekly cadence, SOL only
    py -m strategy_lab.run_v37_claude_trader --coin SOLUSDT \
        --provider claude-cli --model sonnet --cadence weekly

    # 3. Full 5-coin daily-cadence run via API + Batch (token-billed)
    py -m strategy_lab.run_v37_claude_trader \
        --provider anthropic-api --model claude-sonnet-4-6 --cadence daily

    # 4. Cheap parallelism via OpenRouter + GLM-4.5
    py -m strategy_lab.run_v37_claude_trader --coin SOLUSDT \
        --provider openrouter --model "z-ai/glm-4.5"
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from strategy_lab import engine
from strategy_lab.run_v16_1h_hunt import simulate, metrics
from strategy_lab.v37_claude_trader import (
    LOOKBACK_BARS,
    DECISION_CADENCE_BARS,
    Decision,
    build_snapshot,
    snapshot_hash,
    load_system_prompt,
    build_entries_from_decisions,
    load_cache,
    save_cache,
    decision_to_row,
    RESULTS_DIR,
)
from strategy_lab.v37_providers import make_provider, AnthropicAPIProvider

# ─── Coins & window ────────────────────────────────────────────────
# TONUSDT has no parquet under data/binance/parquet/ in this repo (audited
# 2026-04-22). Swapped for LINKUSDT which does have 15m/1h/4h data.
COINS = ["SOLUSDT", "ETHUSDT", "AVAXUSDT", "DOGEUSDT", "LINKUSDT"]
TIMEFRAME = "4h"
START = "2022-12-01"
END = "2026-03-01"

# Cadence presets — bars on 4h timeframe
CADENCE_BARS = {
    "4h":      1,        # every bar (very expensive)
    "daily":   6,        # 6 × 4h = 1d
    "biweekly": 21,      # ≈ 3.5 days
    "weekly":  42,       # 7 days  (default for subscription mode)
    "monthly": 180,      # ≈ 30 days
}

# V34 4h exits (matches the V34 deployment blueprint)
TP_ATR, SL_ATR, TRAIL_ATR, MAX_HOLD = 10, 2.0, 5.0, 40
RISK_PER_TRADE = 0.05
LEVERAGE_CAP = 3.0
FEE = 0.00045   # Hyperliquid taker/side


# ─── Snapshot enumeration ──────────────────────────────────────────
def build_decision_points(df: pd.DataFrame, coin: str,
                           cadence_bars: int,
                           lookback: int = LOOKBACK_BARS,
                           cached_hashes: set[str] | None = None,
                           ) -> list[tuple[int, str]]:
    """Yield (bar_ix, snapshot_text) for every cadence-bar that is NOT cached."""
    cached_hashes = cached_hashes or set()
    out: list[tuple[int, str]] = []
    for i in range(lookback, len(df), cadence_bars):
        df_hist = df.iloc[i - lookback: i]   # strict past-only slice
        snap = build_snapshot(df_hist, coin)
        if snapshot_hash(snap) in cached_hashes:
            continue
        out.append((i, snap))
    return out


def decisions_from_cache(coin: str) -> dict[int, Decision]:
    cache = load_cache(coin)
    return {
        int(row["bar_ix"]): Decision.model_validate_json(row["decision_json"])
        for _, row in cache.iterrows()
    }


# ─── One-coin pipeline ─────────────────────────────────────────────
def run_one_coin(coin: str,
                  provider_name: str,
                  model: str | None,
                  cadence: str,
                  dry_run: bool,
                  pace_seconds: float | None) -> dict:
    df = engine.load(coin, TIMEFRAME, start=START, end=END)
    cadence_bars = CADENCE_BARS[cadence]
    n_decisions = max(0, (len(df) - LOOKBACK_BARS) // cadence_bars)
    print(f"\n=== {coin}  {TIMEFRAME}  bars={len(df)}  "
          f"{df.index[0].date()} → {df.index[-1].date()}  "
          f"cadence={cadence} ({cadence_bars} bars)  decisions={n_decisions} ===")

    cache = load_cache(coin)
    cached_hashes = set(cache["input_hash"].astype(str).tolist())
    pending = build_decision_points(df, coin, cadence_bars, cached_hashes=cached_hashes)
    print(f"Cached: {len(cache)}    pending: {len(pending)}")

    if dry_run:
        print("[dry-run] not calling the LLM.")
        decisions = decisions_from_cache(coin)
        if not decisions:
            print("(no cached decisions — backtest will be skipped)")
            return {"coin": coin, "skipped": True, "n_decisions": 0}
    elif pending:
        provider_kwargs: dict = {}
        if model:
            provider_kwargs["model"] = model
        if pace_seconds is not None and provider_name in ("claude-cli", "openrouter"):
            provider_kwargs["pace_seconds"] = pace_seconds
        provider = make_provider(provider_name, **provider_kwargs)
        system_prompt = load_system_prompt()

        # Anthropic API: use Batch API (50% off + async). Everyone else: sequential.
        if isinstance(provider, AnthropicAPIProvider):
            snapshots_by_id = {f"{coin}:{ix}": snap for ix, snap in pending}
            got = provider.batch_decide(snapshots_by_id, system_prompt)
            new_rows = [
                decision_to_row(int(cid.split(":")[1]),
                                snapshots_by_id[cid],
                                got[cid])
                for cid in snapshots_by_id if cid in got
            ]
        else:
            new_rows = []
            for n, (bar_ix, snap) in enumerate(pending, 1):
                print(f"  [{n}/{len(pending)}] bar_ix={bar_ix} "
                      f"ts={df.index[bar_ix]}", end=" ", flush=True)
                try:
                    d = provider.decide(snap, system_prompt)
                    print(f"→ {d.regime}/{d.strategy}/{d.direction} "
                          f"size={d.size_mult:.2f} conf={d.confidence:.2f}")
                    new_rows.append(decision_to_row(bar_ix, snap, d))
                except Exception as e:
                    print(f"ERROR {type(e).__name__}: {e!r}", file=sys.stderr)
                # Periodically flush cache to survive interrupts
                if n % 10 == 0 and new_rows:
                    cache_now = pd.concat([cache, pd.DataFrame(new_rows)],
                                           ignore_index=True)
                    save_cache(coin, cache_now)

        if new_rows:
            cache = pd.concat([cache, pd.DataFrame(new_rows)], ignore_index=True)
            save_cache(coin, cache)
            print(f"Cached {len(new_rows)} new decisions for {coin}.")
        decisions = decisions_from_cache(coin)
    else:
        decisions = decisions_from_cache(coin)

    if not decisions:
        return {"coin": coin, "skipped": True}

    long_e, short_e = build_entries_from_decisions(df, decisions)
    print(f"Entries: {int(long_e.sum())} long, {int(short_e.sum())} short  "
          f"from {len(decisions)} decisions")

    trades, eq = simulate(
        df, long_entries=long_e, short_entries=short_e,
        tp_atr=TP_ATR, sl_atr=SL_ATR, trail_atr=TRAIL_ATR, max_hold=MAX_HOLD,
        risk_per_trade=RISK_PER_TRADE, leverage_cap=LEVERAGE_CAP, fee=FEE,
    )
    m = metrics(f"V37_{coin}", eq, trades)
    print(f"→ {coin}:  {m}")

    out_dir = RESULTS_DIR / coin
    out_dir.mkdir(parents=True, exist_ok=True)
    pd.Series(eq, index=df.index[:len(eq)]).to_csv(out_dir / "equity.csv")
    pd.DataFrame(trades).to_csv(out_dir / "trades.csv", index=False)
    pd.DataFrame([
        {"bar_ix": i, "timestamp": str(df.index[i]),
         "strategy": d.strategy, "direction": d.direction,
         "regime": d.regime, "size_mult": d.size_mult,
         "confidence": d.confidence, "rationale": d.rationale}
        for i, d in sorted(decisions.items())
    ]).to_csv(out_dir / "decision_trace.csv", index=False)

    row = {"coin": coin, "n_decisions": len(decisions),
           "entries_l": int(long_e.sum()), "entries_s": int(short_e.sum())}
    row.update(m if isinstance(m, dict) else {"metric": str(m)})
    return row


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--coin", default=None,
                    help=f"Single coin (default: all of {COINS})")
    ap.add_argument("--provider", default="claude-cli",
                    choices=["claude-cli", "anthropic-api", "openrouter"],
                    help="LLM call layer (default: claude-cli — uses your subscription)")
    ap.add_argument("--model", default=None,
                    help="Provider-specific model id "
                         "(claude-cli: 'sonnet'/'opus'/'haiku'; "
                         "anthropic-api: 'claude-sonnet-4-6'; "
                         "openrouter: e.g. 'z-ai/glm-4.5')")
    ap.add_argument("--cadence", default="weekly",
                    choices=list(CADENCE_BARS),
                    help="Decision cadence on the 4h timeframe (default: weekly)")
    ap.add_argument("--pace", type=float, default=None,
                    help="Seconds to sleep between calls (claude-cli/openrouter only). "
                         "claude-cli default 4.0; openrouter default 0.5.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Skip LLM calls; backtest from cache only.")
    args = ap.parse_args()

    targets = [args.coin] if args.coin else COINS
    rows = []
    for coin in targets:
        try:
            rows.append(run_one_coin(
                coin, args.provider, args.model, args.cadence,
                args.dry_run, args.pace,
            ))
        except Exception as e:
            print(f"[{coin}] ERROR: {type(e).__name__}: {e!r}", file=sys.stderr)
            rows.append({"coin": coin, "error": repr(e)})

    summary = pd.DataFrame(rows)
    summary_path = RESULTS_DIR / "v37_summary.csv"
    summary.to_csv(summary_path, index=False)
    print(f"\n=== V37 summary → {summary_path} ===")
    print(summary)


if __name__ == "__main__":
    main()
