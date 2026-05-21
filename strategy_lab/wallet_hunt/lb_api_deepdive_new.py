"""
Deep-dive 6 new wallets via data-api /activity. No chain pull — fast path.

Compute taxonomy features:
  - updown% + asset mix (BTC / ETH / SOL / other crypto)
  - market timeframe focus (5m / 15m / 1h / 4h ET / "long")
  - maker% proxy (MAKER_REBATE / total)
  - REDEEM rate (settlements)
  - SPLIT / MERGE events (mint-and-sell signature)
  - avg notional + p25/p50/p75/p95
  - side (BUY/SELL) ratio
  - price distribution (where they trade — extreme cheap = mint-and-sell sells)
  - time-of-day pattern (UTC hour histogram)
  - hold-span (time from first to last fill per slug)
  - leftover-on-winner rate (positional alpha)

Targets (highest priority):
  - 0xb55fa129...  ($217k 30d profit, anon, top counterparty)
  - 0xe0229e10...  (JetFadil, $22k 30d, 6,654 crosses)
  - 0x48ac40fc...  ($19k 30d, anon)
  - 0xfb0f1765...  (aoe2gamer, $13k 30d, crossed with ALL 7 of our wallets)
  - 0xe9076a87...  (big LOSER -$397k 30d - the food)
  - 0x76d4d470...  (medium LOSER -$27k 30d)
"""
from __future__ import annotations
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests

CACHE = Path(r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\wallet_hunt\cache")
DATA = "https://data-api.polymarket.com"

TARGETS = [
    ("0xb55fa1296e6ec55d0ce53d93b9237389f11764d4", "anon-217k", "WINNER"),
    ("0xe0229e10a858860218b6132f4234602c47bd6603", "JetFadil", "WINNER"),
    ("0x48ac40fc545cf327edd5365435c3a9f385614a7e", "anon-19k", "WINNER"),
    ("0xd9013df863c1ba932780857b020dfdeacedf8e14", "anon-14k", "WINNER"),
    ("0xfb0f17657c9c24293b918adb86362a4d8fc90b02", "aoe2gamer", "WINNER-allcross"),
    ("0xee55214ee3a9ee22a404663c76ca832577df7b04", "sixx7", "WINNER"),
    ("0xe9076a87c5ed90ef16e6fe6529c943baeca0cff6", "anon-LOSER", "BIG_LOSER"),
    ("0x76d4d4703add6e94cfdb1107f3d991d85ff2c512", "anon-loser2", "MEDIUM_LOSER"),
    ("0xf8e35e78265c83de7e18204502b3842710bcfd17", "hydroflask", "SMALL_LOSER"),
    ("0xd44e29936409019f93993de8bd603ef6cb1bb15e", "sherlockhomie", "MINT_AND_SELL_d44"),
]


def fetch_all_activity(addr: str, max_total: int = 5000) -> list[dict]:
    """Page through /activity until exhausted or max_total."""
    out: list[dict] = []
    offset = 0
    page = 500
    while len(out) < max_total:
        try:
            r = requests.get(f"{DATA}/activity",
                             params={"user": addr, "limit": page, "offset": offset},
                             timeout=15)
            if r.status_code != 200:
                break
            j = r.json()
            if not isinstance(j, list) or not j:
                break
            out.extend(j)
            if len(j) < page:
                break
            offset += len(j)
        except Exception:
            break
    return out


def parse_timeframe(slug: str) -> str:
    """Bucket slug into 5m / 15m / 1h / 4h (4PM ET) / other."""
    s = slug.lower()
    if not s:
        return "unknown"
    if re.search(r"\bup-or-down-(\d+m)\b", s):
        m = re.search(r"\bup-or-down-(\d+m)\b", s)
        return m.group(1) if m else "unknown"
    if "-4pm-et" in s or "-4-pm-et" in s:
        return "4pm-et"
    if "-1h-" in s or "-1-hour" in s:
        return "1h"
    if re.search(r"-\d{1,2}-?(am|pm)-?et", s):
        return "hourly-et"
    if re.search(r"-up-or-down-(may|june|april|march)", s):
        return "daily-4pm-et"
    return "other-updown" if "up-or-down" in s else "not-updown"


def classify_one(addr: str, label: str, kind: str) -> dict:
    print(f"\n=== {addr[:10]}... [{label}] [{kind}]")
    activity = fetch_all_activity(addr, max_total=5000)
    if not activity:
        return {"addr": addr, "label": label, "kind": kind, "error": "NO_ACTIVITY"}

    df = pd.DataFrame(activity)
    n = len(df)
    print(f"  activity records: {n}")
    df["slug"] = df.get("slug", "").astype(str)
    df["type"] = df.get("type", "").astype(str)
    df["side"] = df.get("side", "").astype(str)
    df["size"] = pd.to_numeric(df.get("size"), errors="coerce")
    df["price"] = pd.to_numeric(df.get("price"), errors="coerce")
    df["usdcSize"] = pd.to_numeric(df.get("usdcSize"), errors="coerce")
    df["timestamp"] = pd.to_numeric(df.get("timestamp"), errors="coerce")

    # Filter to TRADES only for trading stats
    trades = df[df["type"] == "TRADE"].copy()
    n_trades = len(trades)
    n_rebate = int((df["type"] == "MAKER_REBATE").sum())
    n_redeem = int((df["type"] == "REDEEM").sum())
    n_split = int((df["type"] == "SPLIT").sum())
    n_merge = int((df["type"] == "MERGE").sum())
    other_types = df["type"].value_counts().head(8).to_dict()

    # Updown classification
    trades["is_updown"] = trades["slug"].str.contains("-up-or-down-", case=False, na=False)
    trades["asset"] = trades["slug"].str.extract(
        r"^(bitcoin|ethereum|solana|dogecoin|xrp)-up-or-down-",
        expand=False, flags=re.I
    ).str.lower()
    trades["timeframe"] = trades["slug"].apply(parse_timeframe)

    n_updown = int(trades["is_updown"].sum())
    pct_updown = n_updown / max(n_trades, 1) * 100
    asset_mix = trades.loc[trades["is_updown"], "asset"].value_counts().to_dict()
    tf_mix = trades.loc[trades["is_updown"], "timeframe"].value_counts().to_dict()

    # Sport / non-crypto breakdown
    n_mlb = int(trades["slug"].str.startswith("mlb-").sum())
    n_nba = int(trades["slug"].str.startswith("nba-").sum())
    n_nhl = int(trades["slug"].str.startswith("nhl-").sum())
    n_election = int(trades["slug"].str.contains("election|primary|congress", case=False, na=False).sum())

    # Trade stats (updown subset)
    upd = trades[trades["is_updown"]].copy()
    pct_buy = (upd["side"] == "BUY").sum() / max(len(upd), 1) * 100
    pct_sell = (upd["side"] == "SELL").sum() / max(len(upd), 1) * 100

    if len(upd):
        sz_p = upd["usdcSize"].describe()
        px = upd["price"].describe()
        # Price buckets
        pct_cheap = (upd["price"] < 0.10).sum() / len(upd) * 100
        pct_mid = ((upd["price"] >= 0.10) & (upd["price"] < 0.60)).sum() / len(upd) * 100
        pct_high = (upd["price"] >= 0.60).sum() / len(upd) * 100
    else:
        sz_p = {}
        px = {}
        pct_cheap = pct_mid = pct_high = 0.0

    # Per-slug stats: holdings, hold span, leftover
    if len(upd):
        upd["ts"] = pd.to_datetime(upd["timestamp"], unit="s", utc=True)
        upd = upd.sort_values("timestamp")
        per_slug = upd.groupby("slug").agg(
            n_trades=("side", "count"),
            n_buys=("side", lambda s: (s == "BUY").sum()),
            n_sells=("side", lambda s: (s == "SELL").sum()),
            first_ts=("timestamp", "min"),
            last_ts=("timestamp", "max"),
            net_size=("usdcSize", lambda s: s.sum()),
        )
        per_slug["hold_span_s"] = per_slug["last_ts"] - per_slug["first_ts"]
        per_slug["both_sides"] = (per_slug["n_buys"] > 0) & (per_slug["n_sells"] > 0)
        per_slug["only_buys"] = (per_slug["n_buys"] > 0) & (per_slug["n_sells"] == 0)
        n_slugs = len(per_slug)
        pct_both_sides = per_slug["both_sides"].sum() / n_slugs * 100
        pct_only_buys = per_slug["only_buys"].sum() / n_slugs * 100
        hold_span_med = float(per_slug["hold_span_s"].median())
        hold_span_p75 = float(per_slug["hold_span_s"].quantile(0.75))
    else:
        n_slugs = 0
        pct_both_sides = pct_only_buys = hold_span_med = hold_span_p75 = 0

    # Time-of-day pattern (UTC hour histogram)
    if len(upd):
        hour = pd.to_datetime(upd["timestamp"], unit="s", utc=True).dt.hour.value_counts().sort_index()
        hour_dist = {int(h): int(c) for h, c in hour.items()}
    else:
        hour_dist = {}

    # Window
    t0 = int(df["timestamp"].min()) if df["timestamp"].notna().any() else None
    t1 = int(df["timestamp"].max()) if df["timestamp"].notna().any() else None
    span_h = (t1 - t0) / 3600 if t0 and t1 else 0

    out = {
        "addr": addr,
        "label": label,
        "kind": kind,
        "activity_total": n,
        "n_trades": n_trades,
        "n_maker_rebate": n_rebate,
        "n_redeem": n_redeem,
        "n_split": n_split,
        "n_merge": n_merge,
        "type_breakdown": other_types,
        "pct_updown": round(pct_updown, 1),
        "asset_mix": asset_mix,
        "timeframe_mix": tf_mix,
        "n_mlb": n_mlb,
        "n_nba": n_nba,
        "n_nhl": n_nhl,
        "n_election": n_election,
        "pct_buy_updown": round(pct_buy, 1),
        "pct_sell_updown": round(pct_sell, 1),
        "price_mean": float(px.get("mean", 0)) if hasattr(px, "get") else 0,
        "price_med": float(px.get("50%", 0)) if hasattr(px, "get") else 0,
        "price_min": float(px.get("min", 0)) if hasattr(px, "get") else 0,
        "price_max": float(px.get("max", 0)) if hasattr(px, "get") else 0,
        "pct_cheap_lt_10c": round(pct_cheap, 1),
        "pct_mid_10_60c": round(pct_mid, 1),
        "pct_high_gt_60c": round(pct_high, 1),
        "n_slugs": n_slugs,
        "pct_slugs_both_sides": round(pct_both_sides, 1),
        "pct_slugs_only_buys": round(pct_only_buys, 1),
        "hold_span_med_s": hold_span_med,
        "hold_span_p75_s": hold_span_p75,
        "notional_med": float(sz_p.get("50%", 0)) if hasattr(sz_p, "get") else 0,
        "notional_p75": float(sz_p.get("75%", 0)) if hasattr(sz_p, "get") else 0,
        "notional_p95": float(sz_p.get("count", 0)) and float(upd["usdcSize"].quantile(0.95)) if len(upd) else 0,
        "hour_distribution": hour_dist,
        "window_hours": round(span_h, 1),
    }

    # Live print
    print(f"  TRADES: {n_trades}  updown%={pct_updown:.1f}  assets={asset_mix}  TFs={tf_mix}")
    print(f"  Other types: rebates={n_rebate} redeems={n_redeem} splits={n_split} merges={n_merge}")
    print(f"  BUY%={pct_buy:.1f}  SELL%={pct_sell:.1f}  Price: med=${out['price_med']:.3f}  range=[${out['price_min']:.3f}–${out['price_max']:.3f}]")
    print(f"  Price buckets: <10c={pct_cheap:.0f}%  10-60c={pct_mid:.0f}%  >60c={pct_high:.0f}%")
    print(f"  Slugs: {n_slugs}  both_sides={pct_both_sides:.0f}%  only_buys={pct_only_buys:.0f}%  hold_span_med={hold_span_med:.0f}s")
    if hour_dist:
        peak_h = max(hour_dist, key=hour_dist.get)
        print(f"  Peak hour UTC: {peak_h}:00 ({hour_dist[peak_h]} trades)")
    print(f"  Window: {span_h:.1f}h")
    print(f"  STRATEGY HEURISTIC: ", end="")
    if pct_updown < 30:
        print("NOT UPDOWN — sports/political bettor")
    elif pct_both_sides > 70 and n_rebate > n_trades * 0.1:
        print("PAIR_ARB_MAKER (both sides + many rebates)")
    elif pct_both_sides > 50:
        print("MIXED / MARKET_MAKING")
    elif pct_cheap > 30 and pct_sell > 40:
        print("MINT_AND_SELL (high cheap + sells)")
    elif pct_only_buys > 70:
        print("DIRECTIONAL TAKER (one-shot buys)")
    else:
        print("UNCLEAR")

    return out


def main():
    results = []
    for addr, label, kind in TARGETS:
        try:
            res = classify_one(addr, label, kind)
            results.append(res)
        except Exception as e:
            print(f"  ERROR for {addr}: {e}")

    # Save full JSON
    out_path = CACHE / "_lb_new_wallets_deepdive.json"
    out_path.write_text(json.dumps(results, default=str, indent=2))

    # Flat CSV (drop nested fields)
    flat = []
    for r in results:
        f = {k: v for k, v in r.items() if not isinstance(v, dict)}
        f["asset_mix_json"] = json.dumps(r.get("asset_mix", {}))
        f["timeframe_mix_json"] = json.dumps(r.get("timeframe_mix", {}))
        f["hour_distribution_json"] = json.dumps(r.get("hour_distribution", {}))
        flat.append(f)
    pd.DataFrame(flat).to_csv(CACHE / "_lb_new_wallets_deepdive.csv", index=False)

    print(f"\nSaved JSON: {out_path}")
    print(f"Saved CSV:  {CACHE / '_lb_new_wallets_deepdive.csv'}")


if __name__ == "__main__":
    main()
