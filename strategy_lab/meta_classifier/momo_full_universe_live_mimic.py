"""Full-universe momo backtest — live-mimic mode (uses engine_v2 primitives).

Same as `momo_full_universe_canonical.py` but every fill goes through
`engine_v2.fill_at_book` with:
  - real Polymarket fee curve  `0.07 × p × (1-p)` on EVERY fill (both legs)
  - +85ms latency between fire_us and book lookup (PMXT default)
  - min_book_events=25 filter (drops sparse-book markets)
  - strict-asof book lookup (same as Phase 3+4)

Diff against `full_universe_2026_05_16/` answers: "what does the strategy
look like once production migrates from REST to WS book?"

Outputs:
  data/v4/canonical/_results/full_universe_live_mimic_<date>/per_trade.csv
  data/v4/canonical/_results/full_universe_live_mimic_<date>/summary.csv
  data/v4/canonical/_results/full_universe_live_mimic_<date>/diff_vs_legacy.csv
"""
from __future__ import annotations

import argparse
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))
sys.path.insert(0, str(ROOT / "strategy_lab" / "meta_classifier"))

from load import (  # noqa: E402
    load_resolutions, load_klines_asof, load_orderbook_l25_streaming,
)
from engine_v2 import (  # noqa: E402
    EngineConfig, LegacyConfig, LiveMimicConfig,
    fill_at_book, hold_pnl, sell_at_bid_partial, sell_pnl,
    book_event_count,
)

# Pull the same anchor + variant config the canonical script uses
import momo_full_universe_validation as _v509  # noqa: E402

SLEEVE_ANCHORS = _v509.SLEEVE_ANCHORS
SLEEVE_FIRE = _v509.SLEEVE_FIRE
VARIANTS = _v509.VARIANTS
SPREAD_FILTER = _v509.SPREAD_FILTER
GATE_Q = _v509.GATE_Q
LOOKBACK_DAYS = _v509.LOOKBACK_DAYS
NOTIONAL = _v509.NOTIONAL


# ---------------------------------------------------------------------------
# Engine-v2 simulate_trade — replaces the legacy hardcoded simulator
# ---------------------------------------------------------------------------

def simulate_trade_v2(r, klines, books_idx, params, cfg: EngineConfig):
    """Same external contract as `_v509.simulate_trade`. Uses engine_v2 inside.

    Routes every fill through `fill_at_book` (latency + fee + spread filter)
    and every PnL calc through `hold_pnl` / `sell_pnl` (correct fee curve).
    """
    asset = r["asset"]
    held = "Up" if r["signal"] == "UP" else "Down"
    other = "Down" if r["signal"] == "UP" else "Up"
    mid = r["condition_id"]

    fire_offset_s = int(r["fire_offset_s"])
    fire_us = (int(r["ws"]) + fire_offset_s) * 1_000_000

    # ENTRY: fill_at_book applies latency, spread filter, walks asks for $25.
    entry = fill_at_book(books_idx, mid, held, fire_us,
                         cfg=cfg, spread_filter=SPREAD_FILTER[asset])
    if entry is None:
        return None

    won = (r["signal"] == "UP" and r["outcome"] == "Up") or \
          (r["signal"] == "DOWN" and r["outcome"] == "Down")

    if params["trigger"] == "none":
        return dict(exit_reason="hold", vwap_e=entry["vwap"], shares_e=entry["shares"],
                    usd_e=entry["usd"], fee_in=entry["fee_in"],
                    pnl=hold_pnl(entry, won=won, cfg=cfg), fired=False)

    # Anchor for rev_bp triggers — kept identical to legacy.
    from load import asof_strict  # noqa
    end_us, prices = klines[asset]
    asset_at_fire = asof_strict(end_us, prices, (int(r["ws"]) + fire_offset_s) * 1_000_000)
    if not math.isfinite(asset_at_fire) or asset_at_fire <= 0:
        return dict(exit_reason="hold_no_anchor", vwap_e=entry["vwap"], shares_e=entry["shares"],
                    usd_e=entry["usd"], fee_in=entry["fee_in"],
                    pnl=hold_pnl(entry, won=won, cfg=cfg), fired=False)

    resolve_us = (int(r["ws"]) - 60) * 1_000_000   # stop monitoring 60s before resolution
    trigger = params["trigger"]                       # 'none' | 'rev_bp' | 'stop' | 'any'
    side = params.get("exit", "sell")                 # 'hedge' | 'sell'
    rev_bp_thresh = float(params.get("rev_bp", 5))
    stop_ratio = float(params.get("stop_ratio", 0.5))
    sign_required = 1 if r["signal"] == "UP" else -1

    from engine_v2 import find_book_strict
    t_us = fire_us + 10 * 1_000_000  # 10s tick
    while t_us <= resolve_us:
        # Apply exit-side latency too
        lookup_us = t_us + int(cfg.latency_ms * 1_000) if cfg.apply_latency_to_exit else t_us
        # Asset price for rev_bp triggers
        px = asof_strict(end_us, prices, lookup_us)
        if not (math.isfinite(px) and px > 0):
            t_us += 10 * 1_000_000
            continue

        # rev_bp check (only meaningful for trigger in {'rev_bp','any'})
        rev_bp = (px - asset_at_fire) / asset_at_fire * 10_000.0
        adverse_revbp = ((-rev_bp if sign_required > 0 else rev_bp) >= rev_bp_thresh) \
                         if trigger in ("rev_bp", "any") else False

        # stop check (only meaningful for trigger in {'stop','any'})
        stop_triggered = False
        if trigger in ("stop", "any"):
            book = find_book_strict(books_idx, mid, held, lookup_us,
                                     max_staleness_us=cfg.max_book_staleness_us)
            if book is not None:
                bid_now = float(book["bp"][0]) if (len(book["bp"]) and math.isfinite(book["bp"][0])) else float("nan")
                if math.isfinite(bid_now) and bid_now <= stop_ratio * entry["vwap"]:
                    stop_triggered = True

        if adverse_revbp or stop_triggered:
            # Exit side: walk the bid for sell, or buy the OTHER side for hedge.
            if side == "sell":
                book = find_book_strict(books_idx, mid, held, lookup_us,
                                         max_staleness_us=cfg.max_book_staleness_us)
                if book is None:
                    t_us += 10 * 1_000_000
                    continue
                sv, ss, su = sell_at_bid_partial(
                    [float(x) for x in book["bp"]],
                    [float(x) for x in book["bsz"]],
                    entry["shares"],
                )
                if ss <= 0:
                    t_us += 10 * 1_000_000
                    continue
                pnl = sell_pnl(entry, sv, ss, su, cfg=cfg)
                return dict(exit_reason=f"sell_{int(rev_bp_thresh)}bp" if not stop_triggered else "stop_sell",
                            vwap_e=entry["vwap"], shares_e=entry["shares"], usd_e=entry["usd"],
                            fee_in=entry["fee_in"], pnl=pnl, fired=True)
            elif side == "hedge":
                # Buy the OTHER outcome for same $ notional — locks PnL at resolution.
                hedge = fill_at_book(books_idx, mid, other, lookup_us,
                                       cfg=cfg, spread_filter=SPREAD_FILTER[asset])
                if hedge is None:
                    t_us += 10 * 1_000_000
                    continue
                won_hedge = not won  # the other side wins if held lost
                pnl_held  = hold_pnl(entry, won=won,       cfg=cfg)
                pnl_hedge = hold_pnl(hedge, won=won_hedge, cfg=cfg)
                return dict(exit_reason=f"hedge_{int(rev_bp_thresh)}bp" if not stop_triggered else "stop_hedge",
                            vwap_e=entry["vwap"], shares_e=entry["shares"], usd_e=entry["usd"],
                            fee_in=entry["fee_in"], pnl=pnl_held + pnl_hedge, fired=True)
        t_us += 10 * 1_000_000

    # No trigger fired — held to resolution.
    return dict(exit_reason="hold_no_trigger", vwap_e=entry["vwap"],
                shares_e=entry["shares"], usd_e=entry["usd"],
                fee_in=entry["fee_in"], pnl=hold_pnl(entry, won=won, cfg=cfg),
                fired=False)


# ---------------------------------------------------------------------------
# Universe + gating helpers (same as canonical script)
# ---------------------------------------------------------------------------

def load_klines() -> dict:
    out = {}
    for a in ("BTC", "ETH", "SOL"):
        end_us, prices = load_klines_asof(a, source="binance-spot-ws", period_id="1MIN")
        out[a] = (end_us.astype("int64"), prices.astype("float64"))
    return out


def load_universe() -> pd.DataFrame:
    res = load_resolutions(assets=["BTC", "ETH", "SOL"], timeframes=["5m", "15m"])
    res = res[res.outcome.isin(("Up", "Down"))].copy()
    res["ws"] = res.slug.str.extract(r"-(\d+)$")[0].astype("int64")
    res["asset"] = res.ticker
    res["tf"] = res.timeframe
    res["window_s"] = res.tf.map({"5m": 300, "15m": 900})
    res["day"] = pd.to_datetime(res.ws, unit="s").dt.floor("D")
    res["condition_id"] = res.slug
    return res[["slug", "condition_id", "asset", "tf", "ws", "window_s",
                 "day", "outcome"]].reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("live_mimic", "legacy"), default="live_mimic",
                    help="live_mimic uses real fees + latency; legacy reproduces 2026-05-16 numbers")
    ap.add_argument("--out-suffix", default=None, help="override OUT dir suffix")
    ap.add_argument("--invert-signal", action="store_true",
                    help="FADE binance ret_2m (signal = DOWN when ret_2m > 0). "
                         "Replicates the contrarian wallet 0xeebde7a0 strategy.")
    ap.add_argument("--filter-tf", choices=("5m", "15m"), default=None,
                    help="Restrict universe to one timeframe (e.g. 15m for the wallet replications)")
    ap.add_argument("--filter-asset", choices=("BTC", "ETH", "SOL"), default=None,
                    help="Restrict universe to one asset")
    args = ap.parse_args()

    cfg: EngineConfig = LiveMimicConfig() if args.mode == "live_mimic" else LegacyConfig()
    suffix = args.out_suffix or (cfg.name + "_" + datetime.now(timezone.utc).strftime("%Y_%m_%d"))
    OUT = ROOT / "data" / "v4" / "canonical" / "_results" / f"full_universe_{suffix}"
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"=== mode={cfg.name}, fee={cfg.fee_model}, "
          f"latency={cfg.latency_ms}ms, min_book_events={cfg.min_book_events}")
    print(f"=== OUT={OUT}")

    print("[1] load canonical klines + universe...")
    klines = load_klines()
    base = load_universe()
    if args.filter_tf:
        base = base[base.tf == args.filter_tf].reset_index(drop=True)
        print(f"    filter-tf={args.filter_tf}: {len(base)} markets")
    if args.filter_asset:
        base = base[base.asset == args.filter_asset].reset_index(drop=True)
        print(f"    filter-asset={args.filter_asset}: {len(base)} markets")
    print(f"    universe: {len(base)} markets, {base.day.min().date()} → {base.day.max().date()}")

    print("[2] build per-(version, tf) ret_2m + gating...")
    uni_frames = []
    for (version, tf), (off0, off1) in SLEEVE_ANCHORS.items():
        sub = base[base.tf == tf].copy()
        sub["version"] = version
        sub["anchor_off0_s"] = off0
        sub["anchor_off1_s"] = off1
        sub["fire_offset_s"] = SLEEVE_FIRE[(version, tf)]
        sub["ret_2m"] = _v509.compute_ret_2m(sub, klines, off0, off1)
        sub["abs_ret_2m"] = sub.ret_2m.abs()
        uni_frames.append(sub)
    uni = pd.concat(uni_frames, ignore_index=True)

    thr = _v509.compute_thresholds(uni)
    uni["threshold"] = uni.apply(
        lambda r: thr.get((r.version, r.asset, r.tf, str(r.day.date())), float("nan")), axis=1
    )
    gated = uni[(uni.abs_ret_2m.notna()) & (uni.threshold.notna()) &
                (uni.abs_ret_2m >= uni.threshold)].copy()
    if args.invert_signal:
        gated["signal"] = gated.ret_2m.apply(lambda x: "DOWN" if x > 0 else "UP")
        print("    🔄 SIGNAL INVERTED (contrarian / fade-binance-momentum)")
    else:
        gated["signal"] = gated.ret_2m.apply(lambda x: "UP" if x > 0 else "DOWN")
    print(f"    gated: {len(gated)} rows; by (version, tf) = "
          f"{gated.groupby(['version','tf']).size().to_dict()}")
    gated.to_csv(OUT / "gated_universe.csv", index=False)

    print("[3] running variants per asset via engine_v2...")
    all_rows = []
    for asset in ("BTC", "ETH", "SOL"):
        sub = gated[gated.asset == asset]
        if len(sub) == 0:
            continue
        slugs = set(sub.slug.unique())
        print(f"  [{asset}] loading L25 books for {len(slugs)} slugs...")
        books = load_orderbook_l25_streaming(asset.lower(), slugs=slugs, subsample_1hz=True)
        print(f"    {len(books)} (slug,outcome) streams; "
              f"{sum(len(v[0]) for v in books.values()):,} snapshots")

        # Sparse-book filter (skip if cfg.min_book_events == 0)
        if cfg.min_book_events > 0:
            keep = []
            for _, r in sub.iterrows():
                held = "Up" if r["ret_2m"] > 0 else "Down"
                fire_us = (int(r["ws"]) + int(r["fire_offset_s"])) * 1_000_000
                # Window: from fire_us - 60s to slot_end
                win_start = fire_us - 60_000_000
                win_end = int(r["ws"]) * 1_000_000
                n = book_event_count(books, r["slug"], held, win_start, win_end)
                if n >= cfg.min_book_events:
                    keep.append(r.name)
            sub_pre = len(sub); sub = sub.loc[keep]
            print(f"    min_book_events={cfg.min_book_events}: kept {len(sub)}/{sub_pre} rows")

        print(f"    simulating {len(VARIANTS)} variants × {len(sub)} trades...")
        for vname, params in VARIANTS:
            for r in sub.to_dict("records"):
                res = simulate_trade_v2(r, klines, books, params, cfg=cfg)
                if res is None:
                    continue
                all_rows.append({
                    "variant": vname,
                    "version": r["version"],
                    "fire_offset_s": int(r["fire_offset_s"]),
                    "slug": r["slug"], "asset": asset, "tf": r["tf"], "ws": int(r["ws"]),
                    "day": str(r["day"].date()),
                    "signal": r["signal"], "outcome": r["outcome"], "ret_2m": r["ret_2m"],
                    **res,
                })
        del books
        print(f"    {asset} done ({len(all_rows)} rows total)")

    df = pd.DataFrame(all_rows)
    df.to_csv(OUT / "per_trade.csv", index=False)
    print(f"\n[4] wrote {len(df)} per-trade rows → {OUT / 'per_trade.csv'}")

    # HOLD baseline + summary
    hold = df[df.variant == "HOLD_baseline"]
    print(f"\n=== HOLD_baseline ({cfg.name}) ===")
    print(f"  overall:  n={len(hold)}  pnl/trade=${hold.pnl.mean():.4f}  "
          f"hit%={(hold.pnl > 0).mean()*100:.1f}  total=${hold.pnl.sum():.2f}")
    for v in ("v1", "v2"):
        h = hold[hold.version == v]
        if len(h):
            print(f"  {v}:      n={len(h)}  pnl/trade=${h.pnl.mean():.4f}  "
                  f"hit%={(h.pnl > 0).mean()*100:.1f}  total=${h.pnl.sum():.2f}")

    summary = df.groupby(["version", "variant"]).agg(
        n=("pnl", "size"),
        n_fired=("fired", "sum"),
        fire_pct=("fired", lambda s: round(100 * s.sum() / max(len(s), 1), 1)),
        pnl_total=("pnl", lambda s: round(s.sum(), 2)),
        pnl_mean=("pnl", lambda s: round(s.mean(), 4)),
    ).sort_values(["version", "pnl_total"], ascending=[True, False])
    summary.to_csv(OUT / "summary.csv")
    print("\n=== Summary by (version, variant) ===")
    print(summary.to_string())

    # Diff vs legacy run if present
    legacy_summary = ROOT / "data/v4/canonical/_results/full_universe_2026_05_16/summary.csv"
    if cfg.name == "live_mimic" and legacy_summary.exists():
        leg = pd.read_csv(legacy_summary)
        leg = leg.set_index(["version", "variant"])
        joined = summary.join(leg.rename(columns=lambda c: c + "_legacy"), how="outer")
        joined["pnl_total_delta"] = joined["pnl_total"] - joined["pnl_total_legacy"]
        joined["pnl_mean_delta"] = joined["pnl_mean"] - joined["pnl_mean_legacy"]
        joined.to_csv(OUT / "diff_vs_legacy.csv")
        print(f"\n=== Diff vs legacy (data/v4/canonical/_results/full_universe_2026_05_16/) ===")
        print(joined[["pnl_mean", "pnl_mean_legacy", "pnl_mean_delta",
                      "pnl_total", "pnl_total_legacy", "pnl_total_delta"]].to_string())

    print(f"\nDone. Outputs in: {OUT}")


if __name__ == "__main__":
    main()
