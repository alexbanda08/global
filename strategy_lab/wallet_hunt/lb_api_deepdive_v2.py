"""
v2 deep-dive — CORRECTED slug regex.

Real updown slug formats:
  short-form (5m/15m/1h):  ^(btc|eth|sol|doge|xrp|...)-updown-(\d+(m|h))-(\d+)$
  long-form (4PM ET daily): ^(bitcoin|ethereum|solana|...)-up-or-down-...

This version classifies CORRECTLY by both patterns.
"""
from __future__ import annotations
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests

CACHE = Path(r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\wallet_hunt\cache")
DATA = "https://data-api.polymarket.com"

# Short-form: btc-updown-5m-1778820000
UPDOWN_SHORT_RE = re.compile(
    r"^(btc|eth|sol|doge|xrp|bnb|ada|link|matic|avax|sui|hype|ltc|pepe|wif|tao)-updown-(\d+)(m|h)-(\d+)$",
    re.I,
)
# Long-form: bitcoin-up-or-down-may-18-2026-4pm-et
UPDOWN_LONG_RE = re.compile(
    r"^(bitcoin|ethereum|solana|dogecoin|xrp|cardano|polygon|avalanche)-up-or-down-",
    re.I,
)

TARGETS = [
    # New high-PnL counterparty wallets to deep-dive
    ("0xb55fa1296e6ec55d0ce53d93b9237389f11764d4", "anon-217k", "WINNER"),
    ("0xe0229e10a858860218b6132f4234602c47bd6603", "JetFadil", "WINNER"),
    ("0x48ac40fc545cf327edd5365435c3a9f385614a7e", "anon-19k", "WINNER"),
    ("0xd9013df863c1ba932780857b020dfdeacedf8e14", "anon-14k", "WINNER"),
    ("0xfb0f17657c9c24293b918adb86362a4d8fc90b02", "aoe2gamer", "WINNER-allcross"),
    ("0xee55214ee3a9ee22a404663c76ca832577df7b04", "sixx7", "WINNER"),
    ("0xd44e29936409019f93993de8bd603ef6cb1bb15e", "sherlockhomie", "MINT_AND_SELL_d44"),
    # Losers (the food)
    ("0xe9076a87c5ed90ef16e6fe6529c943baeca0cff6", "anon-LOSER", "BIG_LOSER"),
    ("0x76d4d4703add6e94cfdb1107f3d991d85ff2c512", "anon-loser2", "MEDIUM_LOSER"),
    ("0xf8e35e78265c83de7e18204502b3842710bcfd17", "hydroflask", "SMALL_LOSER"),
    # Reference known winner for calibration
    ("0xb27bc932bf8110d8f78e55da7d5f0497a18b5b82", "0xb27bc932_known", "REFERENCE_PURE_PAIR_ARB"),
]


def fetch_all_activity(addr: str, max_total: int = 5000) -> list[dict]:
    out = []
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


def classify_slug(slug: str) -> tuple[bool, str, str]:
    """Returns (is_updown, asset, timeframe)."""
    if not slug:
        return False, "", ""
    m = UPDOWN_SHORT_RE.match(slug)
    if m:
        asset = m.group(1).lower()
        tf = f"{m.group(2)}{m.group(3).lower()}"
        return True, asset, tf
    m = UPDOWN_LONG_RE.match(slug)
    if m:
        asset = m.group(1).lower()
        # asset name → ticker
        amap = {"bitcoin": "btc", "ethereum": "eth", "solana": "sol",
                "dogecoin": "doge", "cardano": "ada", "avalanche": "avax",
                "polygon": "matic"}
        asset = amap.get(asset, asset)
        if "-4pm-et" in slug or "-4-pm-et" in slug:
            tf = "long-4pm-et"
        elif re.search(r"-\d{1,2}-?(am|pm)-?et", slug):
            tf = "long-hourly-et"
        else:
            tf = "long-other"
        return True, asset, tf
    return False, "", ""


def classify_one(addr: str, label: str, kind: str) -> dict:
    print(f"\n=== {addr[:10]}... [{label}] [{kind}]")
    activity = fetch_all_activity(addr, max_total=5000)
    if not activity:
        return {"addr": addr, "label": label, "kind": kind, "error": "NO_ACTIVITY"}

    df = pd.DataFrame(activity)
    n = len(df)
    df["slug"] = df.get("slug", "").astype(str)
    df["type"] = df.get("type", "").astype(str)
    df["side"] = df.get("side", "").astype(str)
    df["usdcSize"] = pd.to_numeric(df.get("usdcSize"), errors="coerce")
    df["size"] = pd.to_numeric(df.get("size"), errors="coerce")
    df["price"] = pd.to_numeric(df.get("price"), errors="coerce")
    df["timestamp"] = pd.to_numeric(df.get("timestamp"), errors="coerce")

    # Classify each row
    classified = df["slug"].apply(classify_slug)
    df["is_updown"] = classified.apply(lambda x: x[0])
    df["asset"] = classified.apply(lambda x: x[1])
    df["timeframe"] = classified.apply(lambda x: x[2])

    # Type counts
    n_trade = int((df["type"] == "TRADE").sum())
    n_rebate = int((df["type"] == "MAKER_REBATE").sum())
    n_redeem = int((df["type"] == "REDEEM").sum())
    n_split = int((df["type"] == "SPLIT").sum())
    n_merge = int((df["type"] == "MERGE").sum())

    # Filter to TRADES only for trading stats
    trades = df[df["type"] == "TRADE"].copy()
    n_trades = len(trades)
    n_updown = int(trades["is_updown"].sum())
    pct_updown = n_updown / max(n_trades, 1) * 100

    asset_mix = trades.loc[trades["is_updown"], "asset"].value_counts().to_dict()
    tf_mix = trades.loc[trades["is_updown"], "timeframe"].value_counts().to_dict()

    # Trade stats on updown subset
    upd = trades[trades["is_updown"]].copy()
    if not len(upd):
        return {
            "addr": addr, "label": label, "kind": kind,
            "activity_total": n, "n_trades": n_trades,
            "pct_updown": 0, "verdict": "NOT_UPDOWN",
            "n_merge": n_merge, "n_rebate": n_rebate, "n_redeem": n_redeem,
        }

    pct_buy = (upd["side"] == "BUY").sum() / len(upd) * 100
    pct_sell = (upd["side"] == "SELL").sum() / len(upd) * 100

    sz_p = upd["usdcSize"].describe()
    px = upd["price"].describe()
    pct_cheap = (upd["price"] < 0.10).sum() / len(upd) * 100
    pct_mid = ((upd["price"] >= 0.10) & (upd["price"] < 0.60)).sum() / len(upd) * 100
    pct_high = (upd["price"] >= 0.60).sum() / len(upd) * 100

    # Per-slug
    upd_sorted = upd.sort_values("timestamp")
    per_slug = upd_sorted.groupby("slug").agg(
        n_trades=("side", "count"),
        n_buys=("side", lambda s: (s == "BUY").sum()),
        n_sells=("side", lambda s: (s == "SELL").sum()),
        first_ts=("timestamp", "min"),
        last_ts=("timestamp", "max"),
        sum_usdc=("usdcSize", "sum"),
    )
    per_slug["hold_span_s"] = per_slug["last_ts"] - per_slug["first_ts"]
    per_slug["both_sides"] = (per_slug["n_buys"] > 0) & (per_slug["n_sells"] > 0)
    per_slug["only_buys"] = (per_slug["n_buys"] > 0) & (per_slug["n_sells"] == 0)
    per_slug["only_sells"] = (per_slug["n_buys"] == 0) & (per_slug["n_sells"] > 0)
    n_slugs = len(per_slug)
    pct_both = per_slug["both_sides"].sum() / n_slugs * 100
    pct_only_b = per_slug["only_buys"].sum() / n_slugs * 100
    pct_only_s = per_slug["only_sells"].sum() / n_slugs * 100
    hold_med = float(per_slug["hold_span_s"].median())

    # Time of day
    hour_dist = pd.to_datetime(upd["timestamp"], unit="s", utc=True).dt.hour.value_counts().sort_index()
    hour_dist_d = {int(h): int(c) for h, c in hour_dist.items()}
    peak_h = max(hour_dist_d, key=hour_dist_d.get) if hour_dist_d else None

    # Window
    span_h = (int(df["timestamp"].max()) - int(df["timestamp"].min())) / 3600
    upd_span_h = (int(upd["timestamp"].max()) - int(upd["timestamp"].min())) / 3600 if len(upd) > 1 else 0

    # VERDICT (uses corrected classification)
    rebate_ratio = n_rebate / max(n_trades, 1)
    merge_ratio = n_merge / max(n_trades, 1)
    split_ratio = n_split / max(n_trades, 1)

    if pct_updown < 20:
        verdict = "NOT_UPDOWN"
    elif pct_both > 60 and (rebate_ratio > 0.001 or merge_ratio > 0.01):
        verdict = "PAIR_ARB_MAKER"
    elif pct_only_s > 30 and split_ratio > 0.05:
        verdict = "MINT_AND_SELL"
    elif pct_only_b > 70 and pct_cheap < 30:
        verdict = "DIRECTIONAL_TAKER"
    elif pct_only_b > 70 and pct_cheap > 30:
        verdict = "CHEAP_BUYER_TAKER"
    elif pct_both > 50:
        verdict = "MIXED_MAKER"
    else:
        verdict = "UNCLEAR"

    out = {
        "addr": addr, "label": label, "kind": kind,
        "activity_total": n, "n_trades": n_trades,
        "n_merge": n_merge, "n_split": n_split, "n_rebate": n_rebate, "n_redeem": n_redeem,
        "pct_updown": round(pct_updown, 1),
        "asset_mix": asset_mix, "timeframe_mix": tf_mix,
        "pct_buy_updown": round(pct_buy, 1),
        "pct_sell_updown": round(pct_sell, 1),
        "price_med": round(float(px["50%"]), 4),
        "price_min": round(float(px["min"]), 4),
        "price_max": round(float(px["max"]), 4),
        "pct_cheap_lt_10c": round(pct_cheap, 1),
        "pct_mid_10_60c": round(pct_mid, 1),
        "pct_high_gt_60c": round(pct_high, 1),
        "n_slugs": int(n_slugs),
        "pct_slugs_both_sides": round(pct_both, 1),
        "pct_slugs_only_buys": round(pct_only_b, 1),
        "pct_slugs_only_sells": round(pct_only_s, 1),
        "hold_span_med_s": int(hold_med),
        "notional_med": round(float(sz_p["50%"]), 2),
        "notional_p75": round(float(sz_p["75%"]), 2),
        "notional_p95": round(float(upd["usdcSize"].quantile(0.95)), 2),
        "peak_hour_utc": peak_h,
        "window_total_h": round(span_h, 2),
        "window_updown_h": round(upd_span_h, 2),
        "merge_per_trade": round(merge_ratio, 4),
        "split_per_trade": round(split_ratio, 4),
        "rebate_per_trade": round(rebate_ratio, 4),
        "verdict": verdict,
    }

    print(f"  TRADES: {n_trades}  updown%={pct_updown:.1f}  assets={asset_mix}")
    print(f"  TFs: {tf_mix}")
    print(f"  Other types: rebates={n_rebate} redeems={n_redeem} splits={n_split} merges={n_merge}")
    print(f"  BUY%={pct_buy:.1f}  SELL%={pct_sell:.1f}  price_med=${out['price_med']}  range=[${out['price_min']}–${out['price_max']}]")
    print(f"  Price buckets: <10c={pct_cheap:.0f}%  10-60c={pct_mid:.0f}%  >60c={pct_high:.0f}%")
    print(f"  Slugs: {n_slugs}  both={pct_both:.0f}%  only_buy={pct_only_b:.0f}%  only_sell={pct_only_s:.0f}%  hold_med={hold_med:.0f}s")
    print(f"  Window: {upd_span_h:.1f}h updown / {span_h:.1f}h total | Peak: UTC {peak_h}:00")
    print(f"  Notional med=${out['notional_med']}  p75=${out['notional_p75']}  p95=${out['notional_p95']}")
    print(f"  -> VERDICT: {verdict}")
    return out


def main():
    results = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(classify_one, a, l, k): (a, l, k) for a, l, k in TARGETS}
        for fut in as_completed(futs):
            try:
                results.append(fut.result())
            except Exception as e:
                print(f"ERR: {e}")

    # Save JSON + flat CSV
    (CACHE / "_lb_new_wallets_deepdive_v2.json").write_text(
        json.dumps(results, default=str, indent=2)
    )
    flat = []
    for r in results:
        f = {k: v for k, v in r.items() if not isinstance(v, (dict, list))}
        f["asset_mix_json"] = json.dumps(r.get("asset_mix", {}))
        f["timeframe_mix_json"] = json.dumps(r.get("timeframe_mix", {}))
        flat.append(f)
    pd.DataFrame(flat).to_csv(CACHE / "_lb_new_wallets_deepdive_v2.csv", index=False)

    print(f"\nSaved: {CACHE / '_lb_new_wallets_deepdive_v2.json'}")
    print(f"Saved: {CACHE / '_lb_new_wallets_deepdive_v2.csv'}")

    print()
    print("=" * 80)
    print("VERDICT SUMMARY")
    print("=" * 80)
    df = pd.DataFrame([{
        "label": r["label"], "verdict": r.get("verdict", "?"),
        "pct_updown": r.get("pct_updown", 0),
        "tf_mix": json.dumps(r.get("timeframe_mix", {}))[:50],
        "asset_mix": json.dumps(r.get("asset_mix", {}))[:40],
        "pct_both": r.get("pct_slugs_both_sides", 0),
        "pct_only_buy": r.get("pct_slugs_only_buys", 0),
        "pct_only_sell": r.get("pct_slugs_only_sells", 0),
        "merge/trade": r.get("merge_per_trade", 0),
        "split/trade": r.get("split_per_trade", 0),
    } for r in results])
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
