"""
v3 deep-dive — groups by (slug, outcomeIndex) for correct pair-arb-maker detection.

Pair-arb-maker signature:
  - 100% updown
  - 100% BUY (maker BIDs fill -> wallet receives shares)
  - >70% of slugs have BUY on BOTH outcomes (Up + Down)
  - MERGE events present (NegRiskAdapter.mergePositions)
  - Up notional ≈ Down notional per slug

Mint-and-sell signature:
  - 100% updown
  - Mix of BUY (mint via SPLIT) and SELL (offload via maker ASK)
  - >30% of slugs have BOTH BUY and SELL on SAME outcome
  - SPLIT events present (CTF.splitPosition)

Directional taker signature:
  - 100% BUY
  - 100% of slugs are ONE outcome only (no paired)
  - Bias toward one side (more Up than Down across slugs)
  - No MERGE / SPLIT
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

UPDOWN_SHORT_RE = re.compile(
    r"^(btc|eth|sol|doge|xrp|bnb|ada|link|matic|avax|sui|hype|ltc|pepe|wif|tao)-updown-(\d+)(m|h)-(\d+)$",
    re.I,
)
UPDOWN_LONG_RE = re.compile(
    r"^(bitcoin|ethereum|solana|dogecoin|xrp|cardano|polygon|avalanche)-up-or-down-",
    re.I,
)

TARGETS = [
    # New top winners (from counterparty mining)
    ("0xb55fa1296e6ec55d0ce53d93b9237389f11764d4", "anon-217k", "WINNER"),
    ("0xe0229e10a858860218b6132f4234602c47bd6603", "JetFadil", "WINNER"),
    ("0x48ac40fc545cf327edd5365435c3a9f385614a7e", "anon-19k", "WINNER"),
    ("0xd9013df863c1ba932780857b020dfdeacedf8e14", "anon-14k", "WINNER"),
    ("0xfb0f17657c9c24293b918adb86362a4d8fc90b02", "aoe2gamer", "WINNER-allcross"),
    ("0xee55214ee3a9ee22a404663c76ca832577df7b04", "sixx7", "WINNER"),
    ("0xd44e29936409019f93993de8bd603ef6cb1bb15e", "sherlockhomie", "WINNER"),
    # Losers
    ("0xe9076a87c5ed90ef16e6fe6529c943baeca0cff6", "BIG_LOSER", "LOSER"),
    ("0x76d4d4703add6e94cfdb1107f3d991d85ff2c512", "loser2", "LOSER"),
    ("0xf8e35e78265c83de7e18204502b3842710bcfd17", "hydroflask", "LOSER"),
    # Reference: our known wallets (calibration set)
    ("0xb27bc932bf8110d8f78e55da7d5f0497a18b5b82", "0xb27bc932_KNOWN", "REF_PAIR_ARB"),
    ("0x04b6d7e930cf9e493c5e6ef24b496294f95594c8", "0x04b6d7e9_KNOWN", "REF_PAIR_ARB"),
    ("0xeebde7a0e019a63e6b476eb425505b7b3e6eba30", "0xeebde7a0_KNOWN", "REF_HYBRID"),
    ("0x89b5cdaaa4866c1e738406712012a630b4078beb", "0x89b5cdaa_KNOWN", "REF_DIRECTIONAL"),
]


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


def classify_slug(slug: str) -> tuple[bool, str, str]:
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
        asset = amap.get(m.group(1).lower(), m.group(1).lower())
        return True, asset, "long"
    return False, "", ""


def deepdive(addr: str, label: str, kind: str) -> dict:
    activity = fetch_all_activity(addr, max_total=5000)
    if not activity:
        return {"addr": addr, "label": label, "kind": kind, "error": "NO_ACTIVITY"}

    df = pd.DataFrame(activity)
    df["slug"] = df.get("slug", "").astype(str)
    df["type"] = df.get("type", "").astype(str)
    df["side"] = df.get("side", "").astype(str)
    df["outcomeIndex"] = pd.to_numeric(df.get("outcomeIndex"), errors="coerce")
    df["outcome"] = df.get("outcome", "").astype(str)
    df["usdcSize"] = pd.to_numeric(df.get("usdcSize"), errors="coerce")
    df["price"] = pd.to_numeric(df.get("price"), errors="coerce")
    df["timestamp"] = pd.to_numeric(df.get("timestamp"), errors="coerce")

    # Type counts
    n = len(df)
    n_rebate = int((df["type"] == "MAKER_REBATE").sum())
    n_redeem = int((df["type"] == "REDEEM").sum())
    n_split  = int((df["type"] == "SPLIT").sum())
    n_merge  = int((df["type"] == "MERGE").sum())
    n_trade  = int((df["type"] == "TRADE").sum())

    trades = df[df["type"] == "TRADE"].copy()
    classified = trades["slug"].apply(classify_slug)
    trades["is_updown"] = classified.apply(lambda x: x[0])
    trades["asset"] = classified.apply(lambda x: x[1])
    trades["tf"] = classified.apply(lambda x: x[2])

    upd = trades[trades["is_updown"]].copy()
    if len(upd) == 0:
        return {"addr": addr, "label": label, "kind": kind,
                "verdict": "NOT_UPDOWN", "n_trades": n_trade, "pct_updown": 0,
                "n_merge": n_merge, "n_split": n_split, "n_rebate": n_rebate}

    # ============================================================
    # KEY: group by (slug, outcomeIndex) — PAIR-ARB DETECTION
    # ============================================================
    upd["slug_outcome"] = upd["slug"] + "|" + upd["outcomeIndex"].astype(str)

    per_so = upd.groupby(["slug", "outcomeIndex"]).agg(
        n_trades=("side", "count"),
        n_buys=("side", lambda s: (s == "BUY").sum()),
        n_sells=("side", lambda s: (s == "SELL").sum()),
        sum_usdc=("usdcSize", "sum"),
        first_ts=("timestamp", "min"),
        last_ts=("timestamp", "max"),
    ).reset_index()

    # For each slug, count how many distinct outcomes were touched + if BOTH have BUYs
    per_slug = per_so.groupby("slug").agg(
        n_outcomes_touched=("outcomeIndex", "nunique"),
        outcomes_with_buys=("n_buys", lambda s: int((s > 0).sum())),
        outcomes_with_sells=("n_sells", lambda s: int((s > 0).sum())),
        total_buys=("n_buys", "sum"),
        total_sells=("n_sells", "sum"),
        total_usdc=("sum_usdc", "sum"),
    ).reset_index()

    n_slugs = len(per_slug)
    # PAIRED: BUYs on BOTH outcomes of same slug (pair-arb signature)
    per_slug["is_paired_buy"] = per_slug["outcomes_with_buys"] >= 2
    # MINT-AND-SELL: BUYs AND SELLs (whichever outcome)
    per_slug["has_both_sides"] = (per_slug["total_buys"] > 0) & (per_slug["total_sells"] > 0)
    # DIRECTIONAL: only one outcome touched
    per_slug["single_outcome"] = per_slug["n_outcomes_touched"] == 1

    pct_paired = per_slug["is_paired_buy"].sum() / n_slugs * 100
    pct_both_sides_legacy = per_slug["has_both_sides"].sum() / n_slugs * 100
    pct_single_outcome = per_slug["single_outcome"].sum() / n_slugs * 100

    # Side breakdown (overall)
    pct_buy = (upd["side"] == "BUY").sum() / len(upd) * 100
    pct_sell = (upd["side"] == "SELL").sum() / len(upd) * 100

    # Asset / TF mix
    asset_mix = upd["asset"].value_counts().to_dict()
    tf_mix = upd["tf"].value_counts().to_dict()

    # Outcome bias (Up=0 vs Down=1)
    out_bias = upd["outcomeIndex"].value_counts().to_dict()
    n_up = int(out_bias.get(0, 0))
    n_down = int(out_bias.get(1, 0))
    up_pct = n_up / max(n_up + n_down, 1) * 100

    # Notional stats
    notional_med = float(upd["usdcSize"].median())
    notional_p75 = float(upd["usdcSize"].quantile(0.75))
    notional_p95 = float(upd["usdcSize"].quantile(0.95))

    # Price stats
    px_med = float(upd["price"].median())
    pct_cheap = (upd["price"] < 0.10).sum() / len(upd) * 100
    pct_high = (upd["price"] >= 0.60).sum() / len(upd) * 100

    # Merge/split density per slug
    merge_per_slug = n_merge / max(n_slugs, 1)
    split_per_slug = n_split / max(n_slugs, 1)
    rebate_per_slug = n_rebate / max(n_slugs, 1)

    # ============================================================
    # CLASSIFICATION
    # ============================================================
    if pct_paired > 60 and pct_buy > 95:
        # bought both outcomes on most slugs = pair-arb maker
        verdict = "PURE_PAIR_ARB_MAKER"
    elif pct_paired > 40 and pct_buy > 80:
        verdict = "MIXED_PAIR_ARB"
    elif pct_both_sides_legacy > 30 and n_split > n_trade * 0.05:
        verdict = "MINT_AND_SELL"
    elif pct_both_sides_legacy > 30:
        verdict = "MIXED_MAKER_BIDS_AND_ASKS"
    elif pct_single_outcome > 80 and pct_buy > 95:
        if abs(up_pct - 50) < 15:
            verdict = "DIRECTIONAL_TAKER_BALANCED"  # 50/50 up/down — many slugs
        else:
            verdict = "DIRECTIONAL_TAKER_BIASED"   # leans up or down
    elif pct_buy > 95:
        verdict = "TAKER_MIXED_OUTCOMES"
    elif pct_sell > 60:
        verdict = "ASK_HEAVY_MAKER"
    else:
        verdict = "UNCLEAR"

    return {
        "addr": addr,
        "label": label,
        "kind": kind,
        "verdict": verdict,
        "n_trades": n_trade,
        "n_updown_trades": len(upd),
        "pct_updown": round(len(upd) / max(n_trade, 1) * 100, 1),
        "n_merge": n_merge,
        "n_split": n_split,
        "n_redeem": n_redeem,
        "n_rebate": n_rebate,
        "n_slugs": int(n_slugs),
        "pct_slugs_paired_buy": round(pct_paired, 1),
        "pct_slugs_both_sides": round(pct_both_sides_legacy, 1),
        "pct_slugs_single_outcome": round(pct_single_outcome, 1),
        "pct_buy": round(pct_buy, 1),
        "pct_sell": round(pct_sell, 1),
        "up_pct": round(up_pct, 1),
        "asset_mix": asset_mix,
        "timeframe_mix": tf_mix,
        "notional_med": round(notional_med, 2),
        "notional_p75": round(notional_p75, 2),
        "notional_p95": round(notional_p95, 2),
        "price_med": round(px_med, 4),
        "pct_cheap_lt_10c": round(pct_cheap, 1),
        "pct_high_gt_60c": round(pct_high, 1),
        "merge_per_slug": round(merge_per_slug, 3),
        "split_per_slug": round(split_per_slug, 3),
        "rebate_per_slug": round(rebate_per_slug, 3),
    }


def main():
    results = []
    print(f"v3 deep-dive: {len(TARGETS)} wallets, threaded fetch...\n")
    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = {ex.submit(deepdive, a, l, k): (a, l, k) for a, l, k in TARGETS}
        for fut in as_completed(futs):
            try:
                r = fut.result()
                results.append(r)
                print(f"  done: {r.get('label', '?'):30s} {r.get('verdict', 'ERROR')}")
            except Exception as e:
                a, l, k = futs[fut]
                print(f"  ERR: {l}: {e}")

    # save
    out_path = CACHE / "_lb_new_wallets_deepdive_v3.json"
    out_path.write_text(json.dumps(results, default=str, indent=2))

    # flat csv
    flat = []
    for r in results:
        f = {k: v for k, v in r.items() if not isinstance(v, (dict, list))}
        f["asset_mix"] = json.dumps(r.get("asset_mix", {}))
        f["timeframe_mix"] = json.dumps(r.get("timeframe_mix", {}))
        flat.append(f)
    df = pd.DataFrame(flat).sort_values("verdict")
    df.to_csv(CACHE / "_lb_new_wallets_deepdive_v3.csv", index=False)

    print()
    print("=" * 80)
    print("v3 VERDICT SUMMARY")
    print("=" * 80)
    cols = ["label", "kind", "verdict", "pct_updown", "n_updown_trades",
            "n_slugs", "pct_slugs_paired_buy", "pct_slugs_both_sides",
            "pct_slugs_single_outcome", "pct_buy", "up_pct", "n_merge", "n_split",
            "notional_med", "price_med", "asset_mix", "timeframe_mix"]
    cols = [c for c in cols if c in df.columns]
    print(df[cols].to_string(index=False))


if __name__ == "__main__":
    main()
