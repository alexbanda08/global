"""F2 strategy V2 — trade-flow-burst trigger.

DISCOVERED via Polymarket trade-tape analysis (see
_f2_trade_flow_trigger.py output):

  Trigger:
    n_trades_5s >= 50            (active trade burst)
    AND |flow_imbalance_5s| >= 0.3  (one-sided flow)
    AND sum_asks >= 1.005

  Direction (CONTRARIAN to recent flow):
    Down if flow_imbalance > 0  (buyers favored Up → fade)
    Up   if flow_imbalance < 0  (buyers favored Down → fade)

  flow_imbalance = (net_up_$ - net_dn_$) / (|net_up_$| + |net_dn_$|)
  where net_X_$ = buy_volume - sell_volume on side X over the window

Fill: buy at top-of-book ask of chosen direction.
Hold to chainlink settlement. Real Polymarket fees applied.
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
    load_chainlink_asof, asof_strict,
    load_orderbook_l25_streaming, load_trades,
)

WINDOW_S = {"5m": 300, "15m": 900}
FEE_RATE = 0.07


def real_fee_per_share(p): return FEE_RATE * p * (1.0 - p) if 0 < p < 1 else 0.0


def hold_pnl_per_share(entry_px, won):
    fee = real_fee_per_share(entry_px)
    return (1.0 - entry_px - fee) if won else (-entry_px - fee)


def parse_slug(slug):
    parts = slug.split("-")
    if len(parts) != 4 or parts[1] != "updown":
        return None
    return parts[0].upper(), parts[2], int(parts[3])


def derive_outcome(slug, rtds_cache):
    info = parse_slug(slug)
    if info is None: return None
    asset, tf, slot_start = info
    slot_end = slot_start + WINDOW_S[tf]
    ts, px = rtds_cache.get(asset, (None, None))
    if ts is None or len(ts) == 0: return None
    strike = asof_strict(ts, px, slot_start * 1_000_000)
    settle = asof_strict(ts, px, slot_end * 1_000_000)
    if not (strike > 0 and settle > 0): return None
    return "Up" if settle > strike else "Down"


def book_at(rec, t_us):
    if rec is None: return None
    ts_arr, ap, asz, bp, bsz = rec
    if len(ts_arr) == 0: return None
    pos = int(np.searchsorted(ts_arr, t_us, side="right")) - 1
    if pos < 0: return None
    try:
        return {
            "ask": float(ap[pos][0]), "asz": float(asz[pos][0]),
            "bid": float(bp[pos][0]), "bsz": float(bsz[pos][0]),
        }
    except (IndexError, ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Trigger
# ---------------------------------------------------------------------------

def compute_flow(slug_trades_df: pd.DataFrame,
                  t_us: int, win_us: int) -> tuple[int, float]:
    """Return (n_trades, flow_imbalance) over [t_us-win_us, t_us)."""
    lo = t_us - win_us
    sub = slug_trades_df[
        (slug_trades_df.timestamp_us > lo)
        & (slug_trades_df.timestamp_us < t_us)
    ]
    if sub.empty:
        return 0, 0.0
    up = sub[sub.outcome == "Up"]
    dn = sub[sub.outcome == "Down"]
    up_buy = float((up[up.side == "buy"].size * up[up.side == "buy"].price).sum())
    up_sell = float((up[up.side == "sell"].size * up[up.side == "sell"].price).sum())
    dn_buy = float((dn[dn.side == "buy"].size * dn[dn.side == "buy"].price).sum())
    dn_sell = float((dn[dn.side == "sell"].size * dn[dn.side == "sell"].price).sum())
    net_up = up_buy - up_sell
    net_dn = dn_buy - dn_sell
    denom = abs(net_up) + abs(net_dn) + 1e-9
    flow_imb = (net_up - net_dn) / denom
    return len(sub), flow_imb


def evaluate_slug(slug, asset, tf, slot_start_s,
                   book_up, book_dn, slug_trades, winner, params):
    """Walk through the slug and fire when trigger met."""
    slot_end_s = slot_start_s + WINDOW_S[tf]
    fire_start_s = slot_start_s + params["min_offset_s"]
    fire_end_s = slot_end_s
    fires = []
    last_fire_us = -1
    win_us = params["flow_window_s"] * 1_000_000

    # Walk at 1s intervals
    for t_s in range(fire_start_s, fire_end_s):
        t_us = t_s * 1_000_000

        # Trigger 1: trade-flow burst
        n_trades, flow_imb = compute_flow(slug_trades, t_us, win_us)
        if n_trades < params["min_n_trades"]:
            continue
        if abs(flow_imb) < params["min_flow_imbalance"]:
            continue

        # Trigger 2: book state
        bu = book_at(book_up, t_us)
        bd = book_at(book_dn, t_us)
        if bu is None or bd is None:
            continue
        sum_asks = bu["ask"] + bd["ask"]
        if sum_asks < params["min_sum_asks"]:
            continue

        # Direction — contrarian to flow
        if flow_imb > 0:
            direction = "Down"
            entry_px = bd["ask"]
            entry_size = bd["asz"]
        else:
            direction = "Up"
            entry_px = bu["ask"]
            entry_size = bu["asz"]
        if not (0 < entry_px < 1):
            continue

        # Cooldown
        if (t_us - last_fire_us) < params["fire_cooldown_s"] * 1_000_000:
            continue
        if len(fires) >= params["max_fires_per_slug"]:
            break

        # Size
        stake = params["stake_usd"]
        shares = min(stake / entry_px, entry_size)
        if shares <= 0:
            continue
        actual_stake = shares * entry_px

        won = (direction == winner) if winner else None
        pnl = (shares * hold_pnl_per_share(entry_px, bool(won))) if won is not None else float("nan")

        fires.append({
            "slug": slug, "asset": asset, "tf": tf,
            "slot_start_s": slot_start_s, "fire_ts_us": t_us,
            "offset_s": t_s - slot_start_s,
            "n_trades_5s": n_trades, "flow_imbalance_5s": flow_imb,
            "up_ask": bu["ask"], "dn_ask": bd["ask"], "sum_asks": sum_asks,
            "direction": direction, "entry_px": entry_px,
            "shares": shares, "stake_usd": actual_stake,
            "winner": winner, "outcome_truth": winner,
            "won": won, "pnl_usd": pnl, "fired": True,
            "ws_s": slot_start_s,
        })
        last_fire_us = t_us

    return fires


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

DEFAULTS = {
    "min_n_trades": 50,
    "min_flow_imbalance": 0.3,
    "min_sum_asks": 1.005,
    "min_offset_s": 60,
    "max_fires_per_slug": 5,
    "fire_cooldown_s": 5,
    "flow_window_s": 5,
    "stake_usd": 1.0,
    "fee_rate": 0.07,
}


def run_backtest(asset="BTC", tf="5m", start_iso=None, end_iso=None,
                  max_slugs=None, out_path=None, **overrides):
    params = dict(DEFAULTS); params.update(overrides)
    print(f"[f2v2] params: {params}")

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
    print(f"[f2v2] universe: {len(res)} slugs")

    rtds = {a: load_chainlink_asof(a) for a in ("BTC", "ETH", "SOL")}
    canon = dict(zip(res.slug.values, res.outcome.values))

    print(f"[f2v2] loading L25 OB for {len(res)} slugs ...")
    ob = load_orderbook_l25_streaming(asset.lower(), slugs=set(res.slug.values))
    print(f"[f2v2]   loaded {len(ob)} groups")

    print(f"[f2v2] loading Polymarket {asset} trade tape (this may take a minute)...")
    tr = load_trades(asset.lower())
    tr = tr[tr.slug.isin(set(res.slug.values))].copy()
    tr_by_slug = {sl: g for sl, g in tr.groupby("slug", sort=False)}
    print(f"[f2v2]   trades on universe slugs: {len(tr):,}  ({len(tr_by_slug)} slugs)")

    print(f"[f2v2] evaluating ...")
    all_fires = []
    for i, row in enumerate(res.itertuples(index=False)):
        info = parse_slug(row.slug)
        if info is None: continue
        a, ttf, slot_start = info
        book_up = ob.get((row.slug, "Up"))
        book_dn = ob.get((row.slug, "Down"))
        if book_up is None or book_dn is None:
            continue
        slug_tr = tr_by_slug.get(row.slug)
        if slug_tr is None or len(slug_tr) < 10:
            continue
        winner = canon.get(row.slug) or derive_outcome(row.slug, rtds)
        if winner is None: continue
        fires = evaluate_slug(row.slug, a, ttf, slot_start,
                              book_up, book_dn, slug_tr, winner, params)
        all_fires.extend(fires)
        if (i + 1) % 500 == 0:
            print(f"[f2v2]   {i+1}/{len(res)}  fires={len(all_fires)}")

    df = pd.DataFrame(all_fires)
    if out_path:
        df.to_csv(out_path, index=False)
        print(f"[f2v2] saved -> {out_path}")

    if not df.empty:
        wr = df.won.mean()
        mean_pnl = df.pnl_usd.mean()
        total = df.pnl_usd.sum()
        print()
        print("=" * 60)
        print(f"  n fires:    {len(df)}")
        print(f"  WR:         {wr*100:.2f}%")
        print(f"  mean entry: ${df.entry_px.mean():.4f}")
        print(f"  mean PnL:   ${mean_pnl:+.4f}  (stake=${params['stake_usd']})")
        print(f"  total PnL:  ${total:+.2f}  (=${total*25:+.2f} @ $25)")
        for d in ("Up", "Down"):
            sub = df[df.direction == d]
            if not sub.empty:
                print(f"  {d:5s}: n={len(sub):4d}  WR={sub.won.mean()*100:5.2f}%  "
                      f"mean=${sub.pnl_usd.mean():+.4f}  total=${sub.pnl_usd.sum():+.2f}")
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", default="BTC")
    ap.add_argument("--tf", default="5m")
    ap.add_argument("--start"); ap.add_argument("--end")
    ap.add_argument("--max-slugs", type=int)
    ap.add_argument("--notional", type=float, default=1.0)
    ap.add_argument("--min-n-trades", type=int, default=50)
    ap.add_argument("--min-flow", type=float, default=0.3)
    ap.add_argument("--min-sum-asks", type=float, default=1.005)
    ap.add_argument("--min-offset-s", type=int, default=60)
    ap.add_argument("--max-fires-per-slug", type=int, default=5)
    ap.add_argument("--fire-cooldown-s", type=int, default=5)
    ap.add_argument("--flow-window-s", type=int, default=5)
    ap.add_argument("--out", type=Path,
                    default=Path("strategy_lab/f2_replica/_results") /
                            "f2_v2_tradeflow.csv")
    args = ap.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    run_backtest(asset=args.asset, tf=args.tf,
                 start_iso=args.start, end_iso=args.end,
                 max_slugs=args.max_slugs, out_path=args.out,
                 stake_usd=args.notional,
                 min_n_trades=args.min_n_trades,
                 min_flow_imbalance=args.min_flow,
                 min_sum_asks=args.min_sum_asks,
                 min_offset_s=args.min_offset_s,
                 max_fires_per_slug=args.max_fires_per_slug,
                 fire_cooldown_s=args.fire_cooldown_s,
                 flow_window_s=args.flow_window_s)


if __name__ == "__main__":
    main()
