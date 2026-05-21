"""
v3-style deep-dive on ALL 16 reference wallets (the ones we built our 3
strategy specs from). NO new wallets. NO extrapolation from sports counterparties.

Map per the 2026-05-18 pickup classifications:
  PURE PAIR ARB → ACC-M reference (0x04b6d7e9, 0xb27bc932)
  HYBRID maker+taker → ACC-H reference (0xeebde7a0)
  MINT-AND-SELL → MAS reference (0xf7f0b0b1, 0xd44e2993)
  DIRECTIONAL → not deployed (0x89b5cdaa)
  TAKER mispricing F2 cluster → counterparty (0xa0a50783, 0x9dae874a, 0x7f599984)
  LOSERS → studied as anti-patterns (0xcfb103c3, 0x7dfc8aa2, 0xce25e214)
  Misc → other (0x0fe40e88, 0x3e6bfd2f, 0xeefe46de, 0xf247584e, 0xf3cfb6a6)

Key questions for re-audit:
1. What's the actual merge rate of our reference makers?
2. What does 0xf7f0b0b1 / 0xd44e2993 actually do (= what MAS should look like)?
3. What's 0xeebde7a0's BUY/SELL ratio over a LONGER window than 1h?
4. What's the actual size + slug-velocity of each reference wallet?
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

UPDOWN_SHORT_RE = re.compile(
    r"^(btc|eth|sol|doge|xrp|bnb|ada|link|matic|avax|sui|hype|ltc|pepe|wif|tao)-updown-(\d+)(m|h)-(\d+)$",
    re.I,
)
UPDOWN_LONG_RE = re.compile(
    r"^(bitcoin|ethereum|solana|dogecoin|xrp|cardano|polygon|avalanche)-up-or-down-",
    re.I,
)

# Map: short -> (full_addr, label, original_strategy_role, pickup_$/day)
REFERENCES = {
    "0x04b6d7e9": ("0x04b6d7e930cf9e493c5e6ef24b496294f95594c8", "0x04b6d7e9", "ACC-M-ref",         212_000),
    "0xb27bc932": ("0xb27bc932bf8110d8f78e55da7d5f0497a18b5b82", "0xb27bc932", "ACC-M-scale-ref",   254_000),
    "0xeebde7a0": ("0xeebde7a0e019a63e6b476eb425505b7b3e6eba30", "Bonereaper", "ACC-H-ref",        344_000),
    "0x89b5cdaa": ("0x89b5cdaaa4866c1e738406712012a630b4078beb", "ohanism",   "DIRECTIONAL-ref",    10_000),
    "0xf7f0b0b1": ("0xf7f0b0b1e9c0fe02ccad926916ee31aef74b912c", "wapol",     "MAS-ref",            30_000),
    "0xd44e2993": ("0xd44e29936409019f93993de8bd603ef6cb1bb15e", "sherlockhomie", "MAS-mini-ref",   25_000),
    "0xcfb103c3": ("0xcfb103c37c0234f524c632d964ed31f117b5f694", "xuanxuan008", "LOSER-anti-pattern", -39),
    "0x7dfc8aa2": ("0x7dfc8aa22f2d4d6f9cbf55cf86682a4d2477f54e", "CramSchoolClub01", "LOSER-anti-pattern", -7_900),
    "0xce25e214": ("0xce25e214d5cfe4f459cf67f08df581885aae7fdc", "0xce25e214", "LOSER-anti-pattern", -295_000),
    "0x9dae874a": ("0x9dae874a2e804349e3004ccc98107799f15f97a2", "Prgovindu1", "F2-taker",            5_900),
    "0xa0a50783": ("0xa0a5078359dad63993a868f6d2db82d3a7b3606f", "0xa0a50783",  "F2-taker",            6_000),
    "0x7f599984": ("0x7f59998477864871448e312011fa5cc6b210b636", "0x7f599984",  "F2-taker",            6_300),
    "0xeefe46de": ("0xeefe46deee8da83bf67dc95b6bc8b8f73e77be43", "hqhjqoqggg",  "small-taker",            94),
    "0x0fe40e88": ("0x0fe40e887acbd0022f89d996acce26ab428501b7", "gobblewobble", "non-updown",     19_000),
    "0x3e6bfd2f": ("0x3e6bfd2f791a10cf2404e09542c2a82e3e7b6d63", "btcbeliver01", "non-updown",    166_000),
    "0xf3cfb6a6": ("0xf3cfb6a6ebfeb51876289eb235719eb1c65252b0", "relay",       "infra-relay",        None),
}


def fetch_all_activity(addr: str, max_total: int = 5000) -> list[dict]:
    out = []
    offset = 0
    while len(out) < max_total:
        try:
            r = requests.get(f"{DATA}/activity",
                             params={"user": addr, "limit": 500, "offset": offset},
                             timeout=15)
            if r.status_code != 200:
                break
            j = r.json()
            if not isinstance(j, list) or not j:
                break
            out.extend(j)
            if len(j) < 500:
                break
            offset += len(j)
        except Exception:
            break
    return out


def classify_slug(slug: str):
    if not slug:
        return False, "", ""
    m = UPDOWN_SHORT_RE.match(slug)
    if m:
        return True, m.group(1).lower(), f"{m.group(2)}{m.group(3).lower()}"
    m = UPDOWN_LONG_RE.match(slug)
    if m:
        amap = {"bitcoin": "btc", "ethereum": "eth", "solana": "sol",
                "dogecoin": "doge", "cardano": "ada", "avalanche": "avax",
                "polygon": "matic"}
        return True, amap.get(m.group(1).lower(), m.group(1).lower()), "long"
    return False, "", ""


def analyze(short: str, addr: str, label: str, role: str, pickup_per_day) -> dict:
    activity = fetch_all_activity(addr, max_total=5000)
    if not activity:
        return {"short": short, "label": label, "role": role, "error": "NO_ACTIVITY"}

    df = pd.DataFrame(activity)
    df["slug"] = df.get("slug", "").astype(str)
    df["type"] = df.get("type", "").astype(str)
    df["side"] = df.get("side", "").astype(str)
    df["outcomeIndex"] = pd.to_numeric(df.get("outcomeIndex"), errors="coerce")
    df["usdcSize"] = pd.to_numeric(df.get("usdcSize"), errors="coerce")
    df["price"] = pd.to_numeric(df.get("price"), errors="coerce")
    df["timestamp"] = pd.to_numeric(df.get("timestamp"), errors="coerce")

    # event types
    n = len(df)
    n_rebate = int((df["type"] == "MAKER_REBATE").sum())
    n_redeem = int((df["type"] == "REDEEM").sum())
    n_split  = int((df["type"] == "SPLIT").sum())
    n_merge  = int((df["type"] == "MERGE").sum())

    trades = df[df["type"] == "TRADE"].copy()
    n_trades = len(trades)
    classified = trades["slug"].apply(classify_slug)
    trades["is_updown"] = classified.apply(lambda x: x[0])
    trades["asset"] = classified.apply(lambda x: x[1])
    trades["tf"] = classified.apply(lambda x: x[2])
    upd = trades[trades["is_updown"]].copy()
    n_upd = len(upd)
    pct_updown = n_upd / max(n_trades, 1) * 100

    # window
    t0 = int(df["timestamp"].min())
    t1 = int(df["timestamp"].max())
    span_h = (t1 - t0) / 3600
    if n_upd > 1:
        upd_span_h = (int(upd["timestamp"].max()) - int(upd["timestamp"].min())) / 3600
    else:
        upd_span_h = 0

    if n_upd == 0:
        return {"short": short, "label": label, "role": role,
                "pickup_per_day": pickup_per_day,
                "verdict": "NOT_UPDOWN_RECENT",
                "n_activity": n, "n_trades": n_trades, "pct_updown": 0,
                "n_merge": n_merge, "n_split": n_split, "n_rebate": n_rebate,
                "n_redeem": n_redeem, "span_h": round(span_h, 2)}

    # slug+outcome grouping
    per_so = upd.groupby(["slug", "outcomeIndex"]).agg(
        n_trades=("side", "count"),
        n_buys=("side", lambda s: (s == "BUY").sum()),
        n_sells=("side", lambda s: (s == "SELL").sum()),
        sum_usdc=("usdcSize", "sum"),
    ).reset_index()
    per_slug = per_so.groupby("slug").agg(
        n_outcomes=("outcomeIndex", "nunique"),
        outcomes_with_buys=("n_buys", lambda s: int((s > 0).sum())),
        outcomes_with_sells=("n_sells", lambda s: int((s > 0).sum())),
        total_buys=("n_buys", "sum"),
        total_sells=("n_sells", "sum"),
        total_usdc=("sum_usdc", "sum"),
    ).reset_index()
    n_slugs = len(per_slug)
    per_slug["paired_buy"]   = per_slug["outcomes_with_buys"] >= 2
    per_slug["paired_sell"]  = per_slug["outcomes_with_sells"] >= 2
    per_slug["both_sides"]   = (per_slug["total_buys"] > 0) & (per_slug["total_sells"] > 0)
    per_slug["only_buy"]     = (per_slug["total_buys"] > 0) & (per_slug["total_sells"] == 0)
    per_slug["only_sell"]    = (per_slug["total_buys"] == 0) & (per_slug["total_sells"] > 0)
    per_slug["single_outcome"] = per_slug["n_outcomes"] == 1

    pct_paired_buy = per_slug["paired_buy"].sum() / n_slugs * 100
    pct_paired_sell = per_slug["paired_sell"].sum() / n_slugs * 100
    pct_both_sides = per_slug["both_sides"].sum() / n_slugs * 100
    pct_only_buy = per_slug["only_buy"].sum() / n_slugs * 100
    pct_only_sell = per_slug["only_sell"].sum() / n_slugs * 100
    pct_single_outcome = per_slug["single_outcome"].sum() / n_slugs * 100

    # side balance overall
    pct_buy = (upd["side"] == "BUY").sum() / n_upd * 100
    pct_sell = (upd["side"] == "SELL").sum() / n_upd * 100

    # Outcome bias (only meaningful for non-paired wallets)
    out_idx = upd["outcomeIndex"].value_counts().to_dict()
    n_up = int(out_idx.get(0, 0))
    n_dn = int(out_idx.get(1, 0))
    up_pct = n_up / max(n_up + n_dn, 1) * 100

    # mix
    asset_mix = upd["asset"].value_counts().to_dict()
    tf_mix = upd["tf"].value_counts().to_dict()

    # notional + price
    px_med = float(upd["price"].median())
    px_p25 = float(upd["price"].quantile(0.25))
    px_p75 = float(upd["price"].quantile(0.75))
    sz_med = float(upd["usdcSize"].median())
    sz_p75 = float(upd["usdcSize"].quantile(0.75))
    sz_p95 = float(upd["usdcSize"].quantile(0.95))

    # rates per hour
    trades_per_hour = n_upd / max(upd_span_h, 0.01)
    slugs_per_hour = n_slugs / max(upd_span_h, 0.01)
    merge_per_hour = n_merge / max(span_h, 0.01)
    split_per_hour = n_split / max(span_h, 0.01)
    rebate_per_hour = n_rebate / max(span_h, 0.01)
    redeem_per_hour = n_redeem / max(span_h, 0.01)

    merge_per_slug = n_merge / max(n_slugs, 1)
    split_per_slug = n_split / max(n_slugs, 1)

    # CLASSIFICATION
    if pct_paired_buy > 60 and pct_buy > 95:
        verdict = "PURE_PAIR_ARB_MAKER"
    elif pct_paired_buy > 40 and pct_buy > 85:
        verdict = "MIXED_PAIR_ARB"
    elif pct_paired_sell > 30 and n_split > n_trades * 0.05:
        verdict = "MINT_AND_SELL"
    elif pct_both_sides > 30:
        verdict = "MIXED_MAKER_BIDS_AND_ASKS"
    elif pct_single_outcome > 70 and pct_buy > 95:
        verdict = "DIRECTIONAL_TAKER_BALANCED" if abs(up_pct - 50) < 15 else "DIRECTIONAL_TAKER_BIASED"
    elif pct_buy > 95:
        verdict = "TAKER_MULTI_OUTCOMES"
    elif pct_sell > 60:
        verdict = "ASK_HEAVY"
    else:
        verdict = "UNCLEAR"

    return {
        "short": short,
        "label": label,
        "role": role,
        "pickup_per_day": pickup_per_day,
        "verdict": verdict,
        "n_activity": n,
        "n_trades": n_trades,
        "n_updown": n_upd,
        "pct_updown": round(pct_updown, 1),
        "n_slugs": int(n_slugs),
        "pct_paired_buy": round(pct_paired_buy, 1),
        "pct_paired_sell": round(pct_paired_sell, 1),
        "pct_both_sides": round(pct_both_sides, 1),
        "pct_only_buy": round(pct_only_buy, 1),
        "pct_only_sell": round(pct_only_sell, 1),
        "pct_buy": round(pct_buy, 1),
        "pct_sell": round(pct_sell, 1),
        "up_pct": round(up_pct, 1),
        "asset_mix": asset_mix,
        "tf_mix": tf_mix,
        "px_med": round(px_med, 3),
        "px_p25": round(px_p25, 3),
        "px_p75": round(px_p75, 3),
        "sz_med": round(sz_med, 2),
        "sz_p75": round(sz_p75, 2),
        "sz_p95": round(sz_p95, 2),
        "n_rebate": n_rebate,
        "n_redeem": n_redeem,
        "n_split": n_split,
        "n_merge": n_merge,
        "merge_per_slug": round(merge_per_slug, 3),
        "split_per_slug": round(split_per_slug, 3),
        "trades_per_hour": round(trades_per_hour, 0),
        "slugs_per_hour": round(slugs_per_hour, 1),
        "merge_per_hour": round(merge_per_hour, 1),
        "split_per_hour": round(split_per_hour, 1),
        "rebate_per_hour": round(rebate_per_hour, 1),
        "redeem_per_hour": round(redeem_per_hour, 1),
        "span_h": round(span_h, 2),
        "upd_span_h": round(upd_span_h, 2),
    }


def main():
    results = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {
            ex.submit(analyze, s, full, label, role, pd_per_day):
                (s, full, label, role, pd_per_day)
            for s, (full, label, role, pd_per_day) in REFERENCES.items()
        }
        for fut in as_completed(futs):
            try:
                results.append(fut.result())
                r = results[-1]
                print(f"  {r.get('short', '?'):14s}  {r.get('role', '?'):22s}  {r.get('verdict', 'ERR'):30s}")
            except Exception as e:
                print(f"  ERR: {e}")

    # Save JSON
    (CACHE / "_lb_refs_only_v3.json").write_text(json.dumps(results, default=str, indent=2))

    # Flat csv
    flat = []
    for r in results:
        f = {k: v for k, v in r.items() if not isinstance(v, (dict, list))}
        f["asset_mix"] = json.dumps(r.get("asset_mix", {}))
        f["tf_mix"] = json.dumps(r.get("tf_mix", {}))
        flat.append(f)
    df = pd.DataFrame(flat)
    # Sort by role for readability
    role_order = ["ACC-M-ref", "ACC-M-scale-ref", "ACC-H-ref", "MAS-ref", "MAS-mini-ref",
                  "DIRECTIONAL-ref", "F2-taker", "LOSER-anti-pattern",
                  "small-taker", "non-updown", "infra-relay"]
    df["role_order"] = df["role"].apply(lambda r: role_order.index(r) if r in role_order else 999)
    df = df.sort_values("role_order").drop(columns=["role_order"])
    df.to_csv(CACHE / "_lb_refs_only_v3.csv", index=False)

    print()
    print("=" * 100)
    print("REFERENCE WALLETS — v3 deep-dive (the wallets that built our strategies)")
    print("=" * 100)
    cols = ["short", "label", "role", "verdict", "pct_updown", "n_slugs",
            "pct_paired_buy", "pct_paired_sell", "pct_both_sides", "pct_buy",
            "px_med", "sz_med", "n_merge", "n_split", "n_rebate",
            "merge_per_slug", "trades_per_hour", "slugs_per_hour", "asset_mix", "tf_mix"]
    cols = [c for c in cols if c in df.columns]
    print(df[cols].to_string(index=False))


if __name__ == "__main__":
    main()
