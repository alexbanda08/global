"""Generic strategy fingerprinter for a Polymarket wallet.

NO ASSUMPTIONS about which strategy a wallet runs. Reports behavioral
features and classifies into a taxonomy:

  TAKER_SINGLE_FIRE   — one BUY per market, no scaling, holds to resolution
  TAKER_PYRAMID       — many BUYs per market, scales across prices
  MAKER_MM            — both BUYs and SELLs per market, tight spread captured
  MAKER_SCALPER       — fast BUY/SELL alternation, sub-second
  LATE_FAVORITE       — buys at price >= 0.85, holds to resolution
  DEEP_VALUE          — buys at price <= 0.15
  CLOSE_BEFORE_RESOLVE — most positions closed before settlement (no holds)
  HYBRID              — mix of behaviors

For each wallet, emits a fingerprint JSON + a per-leg parquet so downstream
can build replicas.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))

CACHE = Path(__file__).resolve().parent / "cache"


SLUG_RE_UD = re.compile(r"^(btc|eth|sol)-updown-(5m|15m)-(\d+)$")


def classify_slug(slug):
    if not isinstance(slug, str):
        return ("unknown", None, None, None)
    m = SLUG_RE_UD.match(slug)
    if m:
        return (f"updown_{m.group(2)}", m.group(1).upper(), m.group(2), int(m.group(3)))
    if isinstance(slug, str) and "up-or-down" in slug:
        return ("updown_long", None, None, None)
    return ("other", None, None, None)


def fingerprint_wallet(wallet: str) -> dict:
    w = wallet.lower()
    short = w[:10]
    odir = CACHE / short
    if not (odir / "trades.parquet").exists():
        return {"wallet": w, "error": "no trades cached"}
    trades = pd.read_parquet(odir / "trades.parquet")
    pos = pd.read_parquet(odir / "positions.parquet") if (odir / "positions.parquet").exists() else pd.DataFrame()
    try:
        with open(odir / "value.json") as f:
            value_obj = json.load(f)
        portfolio_value = float(value_obj.get("value", 0))
    except Exception:
        portfolio_value = None

    # Basic activity stats
    span_h = (trades.timestamp.max() - trades.timestamp.min()) / 3600.0
    span_s = (trades.timestamp.max() - trades.timestamp.min())
    out = {
        "wallet": w,
        "short": short,
        "n_trades": int(len(trades)),
        "time_span_hours": round(float(span_h), 2),
        "trades_per_minute": round(float(len(trades)) / max(span_s, 1) * 60, 3),
        "first_trade_ts": int(trades.timestamp.min()),
        "last_trade_ts": int(trades.timestamp.max()),
        "first_trade_utc": pd.to_datetime(int(trades.timestamp.min()), unit="s", utc=True).isoformat(),
        "last_trade_utc": pd.to_datetime(int(trades.timestamp.max()), unit="s", utc=True).isoformat(),
        "portfolio_value_now": portfolio_value,
        "open_positions": int(len(pos)),
    }

    # Side breakdown
    side_counts = trades.side.value_counts().to_dict()
    out["side_BUY_pct"] = round(100.0 * side_counts.get("BUY", 0) / len(trades), 1)
    out["side_SELL_pct"] = round(100.0 * side_counts.get("SELL", 0) / len(trades), 1)

    # Market class
    cls = trades.slug.map(classify_slug)
    trades = trades.copy()
    trades["market_class"] = cls.map(lambda x: x[0])
    trades["mkt_asset"] = cls.map(lambda x: x[1])
    trades["tf"] = cls.map(lambda x: x[2])
    trades["slot_start_s"] = cls.map(lambda x: x[3])

    mc_pct = (trades.market_class.value_counts(normalize=True) * 100).round(1).to_dict()
    out["market_class_pct"] = mc_pct
    out["up_down_focus_pct"] = round(
        sum(v for k, v in mc_pct.items() if k.startswith("updown_")), 1
    )

    # Notional + price stats
    trades["usd_notional"] = trades["size"] * trades["price"]
    out["notional_p25_usd"] = round(float(trades.usd_notional.quantile(0.25)), 2)
    out["notional_med_usd"] = round(float(trades.usd_notional.median()), 2)
    out["notional_p75_usd"] = round(float(trades.usd_notional.quantile(0.75)), 2)
    out["notional_p95_usd"] = round(float(trades.usd_notional.quantile(0.95)), 2)
    out["notional_max_usd"] = round(float(trades.usd_notional.max()), 2)
    out["price_p25"] = round(float(trades["price"].quantile(0.25)), 4)
    out["price_med"] = round(float(trades["price"].median()), 4)
    out["price_p75"] = round(float(trades["price"].quantile(0.75)), 4)
    out["price_p95_buying_high"] = round(float(trades.loc[trades.side == "BUY", "price"].quantile(0.95) if (trades.side == "BUY").any() else 0), 4)
    out["price_p05_buying_low"] = round(float(trades.loc[trades.side == "BUY", "price"].quantile(0.05) if (trades.side == "BUY").any() else 0), 4)

    # Per-leg behaviour (only updown markets where we know window structure)
    ud = trades[trades.market_class.str.startswith("updown_") & trades.slot_start_s.notna()].copy()
    out["n_updown_trades"] = int(len(ud))
    if len(ud) == 0:
        out["strategy_class"] = "NON_UPDOWN_FOCUSED"
        out["replication_recipe"] = None
        return out
    ud["slot_start_s"] = ud.slot_start_s.astype("int64")
    ud["window_s"] = ud.tf.map({"5m": 300, "15m": 900})
    ud["offset_s"] = ud.timestamp.astype("int64") - ud.slot_start_s
    ud["signed_sz"] = np.where(ud.side == "BUY", ud["size"], -ud["size"])

    grp = ud.groupby(["conditionId", "outcome"])
    legs = grp.agg(
        n_trades=("side", "size"),
        n_buys=("side", lambda s: (s == "BUY").sum()),
        n_sells=("side", lambda s: (s == "SELL").sum()),
        buy_shares=("size", lambda s: ud.loc[s.index].loc[ud.side == "BUY", "size"].sum()),
        sell_shares=("size", lambda s: ud.loc[s.index].loc[ud.side == "SELL", "size"].sum()),
        avg_buy_px=("price", lambda s: ud.loc[s.index].loc[ud.side == "BUY", "price"].mean()),
        avg_sell_px=("price", lambda s: ud.loc[s.index].loc[ud.side == "SELL", "price"].mean()),
        first_offset=("offset_s", "min"),
        last_offset=("offset_s", "max"),
        first_ts=("timestamp", "min"),
        last_ts=("timestamp", "max"),
        market_class=("market_class", "first"),
        mkt_asset=("mkt_asset", "first"),
        tf=("tf", "first"),
        slot_start_s=("slot_start_s", "first"),
        window_s=("window_s", "first"),
    ).reset_index()
    legs["hold_span_s"] = legs.last_ts - legs.first_ts
    legs["leftover_shares"] = legs.buy_shares - legs.sell_shares

    out["n_legs"] = int(len(legs))
    out["legs_per_market_avg"] = round(float(legs.groupby("conditionId").size().mean()), 2)
    out["unique_markets_traded"] = int(legs.conditionId.nunique())
    out["avg_trades_per_leg"] = round(float(legs.n_trades.mean()), 2)
    out["leg_pct_with_only_buys"] = round(100 * (legs.n_sells == 0).mean(), 1)
    out["leg_pct_with_only_sells"] = round(100 * (legs.n_buys == 0).mean(), 1)
    out["leg_pct_with_both_sides"] = round(100 * ((legs.n_buys > 0) & (legs.n_sells > 0)).mean(), 1)
    out["leg_pct_single_trade"] = round(100 * (legs.n_trades == 1).mean(), 1)
    out["hold_span_med_s"] = round(float(legs.hold_span_s.median()), 1)
    out["first_offset_med_s"] = round(float(legs.first_offset.median()), 1)
    out["last_offset_med_s"] = round(float(legs.last_offset.median()), 1)

    # Closure behavior
    legs_with_leftover = (legs.leftover_shares.abs() > 0.5).sum()
    out["leg_pct_held_to_resolution"] = round(100 * legs_with_leftover / max(len(legs), 1), 1)

    # Avg-buy price tells us late-favorite vs deep-value
    bought_legs = legs[legs.buy_shares > 0]
    if len(bought_legs):
        out["avg_buy_px_p25"] = round(float(bought_legs.avg_buy_px.quantile(0.25)), 4)
        out["avg_buy_px_med"] = round(float(bought_legs.avg_buy_px.median()), 4)
        out["avg_buy_px_p75"] = round(float(bought_legs.avg_buy_px.quantile(0.75)), 4)

    # Inter-trade gap inside a leg (only for multi-trade legs)
    multi = ud[ud.conditionId.isin(legs[legs.n_trades > 3].conditionId)]
    if len(multi):
        gaps = multi.sort_values(["conditionId", "timestamp"]).groupby("conditionId").timestamp.diff().dropna()
        out["intra_leg_gap_med_s"] = round(float(gaps.median()), 2)
        out["intra_leg_gap_p95_s"] = round(float(gaps.quantile(0.95)), 2)

    # ---------------- Strategy classification ----------------
    cls_label = []
    # Maker MM if many legs have both sides
    if out.get("leg_pct_with_both_sides", 0) > 30:
        cls_label.append("MAKER_BOTH_SIDES")
    # Pyramid if avg trades/leg >> 1 AND mostly buy-only
    if out.get("avg_trades_per_leg", 0) >= 5 and out.get("leg_pct_with_only_buys", 0) > 70:
        cls_label.append("PYRAMID_TAKER")
    # Single-fire taker if most legs have exactly 1 trade
    if out.get("leg_pct_single_trade", 0) > 50:
        cls_label.append("SINGLE_FIRE_TAKER")
    # Late favorite if median avg_buy_px >= 0.85
    if out.get("avg_buy_px_med", 0) >= 0.85:
        cls_label.append("LATE_FAVORITE")
    # Deep value if median avg_buy_px <= 0.15
    if out.get("avg_buy_px_med", 1) <= 0.15:
        cls_label.append("DEEP_VALUE_UNDERDOG")
    # CLOSE_BEFORE_RESOLVE if low held-to-resolution %
    if out.get("leg_pct_held_to_resolution", 100) < 20:
        cls_label.append("CLOSE_BEFORE_RESOLVE")
    # SCALPER if median intra-leg gap < 5s
    if out.get("intra_leg_gap_med_s", 100) < 5:
        cls_label.append("SCALPER")

    out["strategy_class"] = "|".join(cls_label) if cls_label else "UNCLASSIFIED"

    # Save annotated legs for downstream
    legs.to_parquet(odir / "per_leg.parquet", index=False)

    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wallets", nargs="+", required=True)
    args = ap.parse_args()
    all_fp = []
    for w in args.wallets:
        try:
            fp = fingerprint_wallet(w)
        except Exception as e:
            fp = {"wallet": w, "error": str(e)}
            import traceback; traceback.print_exc()
        all_fp.append(fp)
        print(f"\n=== {w}")
        for k, v in fp.items():
            if isinstance(v, dict):
                print(f"  {k}:")
                for kk, vv in v.items():
                    print(f"     {kk}: {vv}")
            else:
                print(f"  {k}: {v}")

    out_path = CACHE / "_fingerprints.json"
    with open(out_path, "w") as f:
        json.dump(all_fp, f, indent=2, default=str)
    print(f"\n--> saved: {out_path}")


if __name__ == "__main__":
    main()
