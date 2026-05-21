"""F2 strategy backtest — fade-rally-late-in-slug.

Trigger:
  - offset_from_slot_start >= 240s (last 60s of 5m slug; for 15m: window-60)
  - sum_asks >= 1.005
  - max(up_asz, dn_asz) >= 200
  - |binance_ret_60s| >= 2 bp
Direction:
  - "Down" if binance_ret_60s > 0  (fade rally — the +EV leg)
  - "Up"   if binance_ret_60s < 0  (fade dip — losing leg; controlled by flag)

Fill model:
  - Buy at top-of-book ask of chosen direction
  - Pay real Polymarket fee: 0.07 × p × (1-p) per share on entry
  - Hold to chainlink settlement
  - Win pays $1/share, loss pays $0

Output: per-trade CSV like cyclops/backtest/runner.py, ready for validation
gates (permutation, bootstrap, walkforward).

CLI:
    py -3 -X utf8 -m strategy_lab.f2_replica.runner \\
        --asset BTC --tf 5m --start 2026-04-24 --end 2026-05-15 \\
        --notional 25 --out f2_replica_run.csv
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
from load import (  # noqa: E402
    load_resolutions, add_ws_s,
    load_klines_asof, load_chainlink_asof, asof_strict,
    load_orderbook_l25_streaming,
)

# ---------------------------------------------------------------------------
# Strategy parameters (operator-tunable; defaults from trigger sweep)
# ---------------------------------------------------------------------------

DEFAULT = {
    "fire_offset_from_end_s": 60,     # fire in last 60s of slug
    "min_sum_asks":           1.005,
    "min_max_asz":            200.0,
    "min_ret_60s_bp":         2.0,
    "fade_rallies": True,             # fire when binance ret > 0 → buy Down
    "fade_dips":    False,            # fire when binance ret < 0 → buy Up
    "max_fires_per_slug": 3,          # cap to avoid grinding the same slug
    "fire_cooldown_s": 10,            # min seconds between fires on same slug
    "fee_rate":     0.07,             # real Polymarket crypto fee
    "stake_usd":    1.0,              # default $1 stake; CLI overrides
}

WINDOW_S = {"5m": 300, "15m": 900}


def real_fee_per_share(p: float, fee_rate: float) -> float:
    if not (0 < p < 1):
        return 0.0
    return fee_rate * p * (1.0 - p)


def hold_pnl_per_share(entry_px: float, won: bool, fee_rate: float) -> float:
    fee = real_fee_per_share(entry_px, fee_rate)
    if won:
        return 1.0 - entry_px - fee
    return -entry_px - fee


def parse_slug(slug: str):
    parts = slug.split("-")
    if len(parts) != 4 or parts[1] != "updown":
        return None
    return parts[0].upper(), parts[2], int(parts[3])


def book_at(rec, t_us: int) -> Optional[dict]:
    """L25 top-of-book at t_us."""
    if rec is None:
        return None
    ts_arr, ap, asz, bp, bsz = rec
    if len(ts_arr) == 0:
        return None
    pos = int(np.searchsorted(ts_arr, t_us, side="right")) - 1
    if pos < 0:
        return None
    try:
        return {
            "ts_us": int(ts_arr[pos]),
            "ask": float(ap[pos][0]),
            "asz": float(asz[pos][0]),
            "bid": float(bp[pos][0]),
            "bsz": float(bsz[pos][0]),
        }
    except (IndexError, ValueError, TypeError):
        return None


def derive_outcome(slug: str, rtds_cache: dict) -> Optional[str]:
    info = parse_slug(slug)
    if info is None:
        return None
    asset, tf, slot_start = info
    slot_end = slot_start + WINDOW_S[tf]
    ts, px = rtds_cache.get(asset, (None, None))
    if ts is None or len(ts) == 0:
        return None
    strike = asof_strict(ts, px, slot_start * 1_000_000)
    settle = asof_strict(ts, px, slot_end * 1_000_000)
    if not (strike > 0 and settle > 0):
        return None
    return "Up" if settle > strike else "Down"


# ---------------------------------------------------------------------------
# Per-slug evaluator
# ---------------------------------------------------------------------------

def evaluate_slug(slug, asset, tf, slot_start_s,
                   book_up, book_dn,
                   end_us_kline, prices_kline,
                   winner, params) -> list[dict]:
    """Walk through the slug's last-60s window, fire when trigger met."""
    slot_end_s = slot_start_s + WINDOW_S[tf]
    fire_start_s = slot_end_s - params["fire_offset_from_end_s"]
    fires_recorded = []
    last_fire_us = -1

    # Walk at 1s resolution over the firing window
    for t_s in range(fire_start_s, slot_end_s):
        t_us = t_s * 1_000_000

        # Book state
        bu = book_at(book_up, t_us)
        bd = book_at(book_dn, t_us)
        if bu is None or bd is None:
            continue
        sum_asks = bu["ask"] + bd["ask"]
        if sum_asks < params["min_sum_asks"]:
            continue
        max_asz = max(bu["asz"], bd["asz"])
        if max_asz < params["min_max_asz"]:
            continue

        # Binance momentum
        px_now = asof_strict(end_us_kline, prices_kline, t_us)
        px_60s = asof_strict(end_us_kline, prices_kline, t_us - 60_000_000)
        if not (px_now > 0 and px_60s > 0):
            continue
        ret_60s = px_now / px_60s - 1.0
        if abs(ret_60s) * 10000 < params["min_ret_60s_bp"]:
            continue

        # Direction (asymmetric per config)
        if ret_60s > 0:
            if not params["fade_rallies"]:
                continue
            direction = "Down"
            entry_px = bd["ask"]
            entry_size_avail = bd["asz"]
        else:
            if not params["fade_dips"]:
                continue
            direction = "Up"
            entry_px = bu["ask"]
            entry_size_avail = bu["asz"]

        # Cooldown + per-slug fire cap
        if (t_us - last_fire_us) < params["fire_cooldown_s"] * 1_000_000:
            continue
        if len(fires_recorded) >= params["max_fires_per_slug"]:
            break
        if not (0 < entry_px < 1):
            continue

        # Compute hold PnL using chainlink outcome
        won = (direction == winner) if winner else None

        # Allocate $stake at this ask (taker buy, no slippage past top)
        stake_usd = params["stake_usd"]
        shares = stake_usd / entry_px
        # Cap by available top-of-book size
        shares = min(shares, entry_size_avail)
        if shares <= 0:
            continue
        actual_stake = shares * entry_px

        if won is None:
            pnl_usd = float("nan")
        else:
            pnl_usd = shares * hold_pnl_per_share(
                entry_px, won, params["fee_rate"]
            )

        fires_recorded.append({
            "slug": slug, "asset": asset, "tf": tf,
            "slot_start_s": slot_start_s, "fire_ts_us": t_us,
            "offset_s": t_s - slot_start_s,
            "binance_px": px_now, "binance_ret_60s": ret_60s,
            "up_ask": bu["ask"], "up_asz": bu["asz"],
            "dn_ask": bd["ask"], "dn_asz": bd["asz"],
            "sum_asks": sum_asks, "max_asz": max_asz,
            "direction": direction, "entry_px": entry_px,
            "shares": shares, "stake_usd": actual_stake,
            "winner": winner, "won": won, "pnl_usd": pnl_usd,
            "fired": True, "skip_reason": None,
        })
        last_fire_us = t_us

    return fires_recorded


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run_backtest(asset: str = "BTC", tf: str = "5m",
                  start_iso: Optional[str] = None,
                  end_iso: Optional[str] = None,
                  max_slugs: Optional[int] = None,
                  out_path: Optional[Path] = None,
                  **params_override) -> pd.DataFrame:
    params = dict(DEFAULT)
    params.update(params_override)

    # 1. Load resolved universe
    print(f"[f2] universe: {asset} {tf}")
    res = load_resolutions(assets=[asset.upper()], timeframes=[tf])
    res = add_ws_s(res)
    if start_iso:
        ts = int(datetime.fromisoformat(start_iso).replace(tzinfo=timezone.utc).timestamp())
        res = res[res.ws_s >= ts]
    if end_iso:
        ts = int(datetime.fromisoformat(end_iso).replace(tzinfo=timezone.utc).timestamp())
        res = res[res.ws_s < ts]
    res = res.sort_values("ws_s").reset_index(drop=True)
    if max_slugs:
        res = res.head(max_slugs)
    print(f"[f2] universe size: n={len(res)} slugs")

    # 2. Chainlink for outcome derivation (fallback for non-canonical)
    rtds_cache = {a: load_chainlink_asof(a) for a in ("BTC", "ETH", "SOL")}
    canon_outcomes = dict(zip(res.slug.values, res.outcome.values))

    # 3. Binance klines
    end_us_kline, prices_kline = load_klines_asof(
        asset.upper(), "binance-spot-ws", "1MIN",
    )
    print(f"[f2] 1MIN klines: {len(end_us_kline)} bars")

    # 4. L25 OB streaming (filter to universe slugs to bound memory)
    print(f"[f2] loading L25 OB for {len(res)} slugs ...")
    ob = load_orderbook_l25_streaming(asset.lower(), slugs=set(res.slug.values))
    print(f"[f2]   loaded {len(ob)} (slug, outcome) groups")

    # 5. Walk each slug
    print(f"[f2] evaluating ...")
    all_fires = []
    skipped = []
    for i, row in enumerate(res.itertuples(index=False)):
        info = parse_slug(row.slug)
        if info is None:
            continue
        a, ttf, slot_start = info
        book_up = ob.get((row.slug, "Up"))
        book_dn = ob.get((row.slug, "Down"))
        if book_up is None or book_dn is None:
            skipped.append((row.slug, "no_ob"))
            continue
        winner = canon_outcomes.get(row.slug) or derive_outcome(row.slug, rtds_cache)
        if winner is None:
            skipped.append((row.slug, "no_outcome"))
            continue
        fires = evaluate_slug(
            row.slug, a, ttf, slot_start,
            book_up, book_dn, end_us_kline, prices_kline,
            winner, params,
        )
        all_fires.extend(fires)
        if (i + 1) % 500 == 0:
            print(f"[f2]   processed {i+1}/{len(res)} slugs, "
                  f"fires so far: {len(all_fires)}")

    print(f"[f2] complete: n_fires={len(all_fires)}  skipped={len(skipped)}")
    if all_fires:
        df = pd.DataFrame(all_fires)
        # Add outcome_truth column (for compatibility with cyclops validators)
        df["outcome_truth"] = df["winner"]
    else:
        df = pd.DataFrame()

    if out_path:
        df.to_csv(out_path, index=False)
        print(f"[f2] saved -> {out_path}")

    # 6. Quick summary
    if not df.empty:
        wr = df["won"].mean()
        total_pnl = df["pnl_usd"].sum()
        mean_pnl = df["pnl_usd"].mean()
        n = len(df)
        print()
        print("=" * 60)
        print(f"  n_fires:   {n}")
        print(f"  WR:        {wr*100:.2f}%")
        print(f"  mean PnL:  ${mean_pnl:+.4f}  ({params['stake_usd']} stake)")
        print(f"  total PnL: ${total_pnl:+.2f}")
        if "fade_rallies" in params and params["fade_rallies"]:
            sub = df[df.direction == "Down"]
            if not sub.empty:
                print(f"  Down (fade rally) n={len(sub)} "
                      f"WR={sub.won.mean()*100:.2f}% "
                      f"mean=${sub.pnl_usd.mean():+.4f}")
        if "fade_dips" in params and params["fade_dips"]:
            sub = df[df.direction == "Up"]
            if not sub.empty:
                print(f"  Up (fade dip)     n={len(sub)} "
                      f"WR={sub.won.mean()*100:.2f}% "
                      f"mean=${sub.pnl_usd.mean():+.4f}")

    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", default="BTC")
    ap.add_argument("--tf", default="5m")
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--max-slugs", type=int, default=None)
    ap.add_argument("--notional", type=float, default=1.0,
                    help="stake per fire (USD)")
    ap.add_argument("--fade-dips", action="store_true",
                    help="also fire on dips (default: only rallies)")
    ap.add_argument("--min-ret-60s-bp", type=float, default=2.0)
    ap.add_argument("--min-asz", type=float, default=200.0)
    ap.add_argument("--min-sum-asks", type=float, default=1.005)
    ap.add_argument("--last-n-s", type=int, default=60,
                    help="fire only in last N seconds of slug")
    ap.add_argument("--max-fires-per-slug", type=int, default=3)
    ap.add_argument("--out", type=Path,
                    default=Path("strategy_lab/f2_replica/_results") /
                            "f2_replica.csv")
    args = ap.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)

    df = run_backtest(
        asset=args.asset, tf=args.tf,
        start_iso=args.start, end_iso=args.end,
        max_slugs=args.max_slugs,
        out_path=args.out,
        stake_usd=args.notional,
        fade_dips=args.fade_dips,
        min_ret_60s_bp=args.min_ret_60s_bp,
        min_max_asz=args.min_asz,
        min_sum_asks=args.min_sum_asks,
        fire_offset_from_end_s=args.last_n_s,
        max_fires_per_slug=args.max_fires_per_slug,
    )


if __name__ == "__main__":
    main()
