"""
For every NEW leaderboard wallet, pull recent /activity from data-api and
classify by market focus + maker/taker ratio. Filter for crypto-updown focus.

Output: cache/_lb_new_wallet_classification.csv
        cache/_lb_new_updown_focused.csv  (subset)
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

UPDOWN_RE = re.compile(r"(btc|eth|sol|xrp|doge|sui|hype|ltc|bnb|ada|link|matic|atom|dot|trx|avax|near|uni|aave|tao|ftt|fil|apt|inj|render|sei|tia|wif|fet|kas|imx|stx|ondo|grt|jto|pendle|axs|sand|man|chiliz|crv|comp|mkr|theta|enj|gmt|woo|qnt|gala|sushi|1inch|yfi|bal|knc|enj|lrc|ankr|bnt|zrx|rsr|sxp|bake|btt|chr|alice|cake|reef|skl|lina|atom|grt|stmx|ant|tomo|reef|ant|paxg|ach|alpha|akro|ar|arpa|astr|axs|badger|band|bat|bch|beam|bel|big|blok|blz|bnt|bond|bsw|btg|btt|cake|celo|cfx|cgpt|chess|chr|chz|cocos|coti|crv|ctk|ctxc|cvc|cvx|dao|dar|dash|dent|dexe|dgb|dia|dock|dydx|edu|egld|elf|enj|eos|epx|ern|eth|etc|euro|fida|fil|firo|flm|flow|flux|forth|fortune|forth|front|ftm|ftt|fun|fxs|gala|gas|glm|glmr|gmt|gmx|gns|grt|gtc|gxs|hbar|hft|high|hifi|hive|hnt|hook|hot|icp|icx|id|idex|ilv|imx|inj|iost|iota|iotx|ip|jasmy|joe|jto|jup|kava|kda|key|klay|kmd|knc|kp3r|ksm|lazio|lcx|ldo|leo|lever|lina|linker|linkleo|lit|loka|loom|lpt|lqty|lrc|lsk|luna|magic|mana|mantle|mantra|mask|mbox|mc|mdt|mdx|metis|mfg|mft|mina|mir|mln|mob|mtl|nano|near|nebl|neo|nexo|nft|nkn|nmr|nuls|ocean|og|ogn|okb|om|omg|one|ong|ont|ooki|ops|orca|orn|oxt|oxy|paxg|people|pepe|pera|perp|pha|phb|phx|pivx|pixel|pln|pnt|poly|pond|portal|poro|powr|pros|prq|psg|pundix|qi|qkc|qnt|qtum|quack|raca|rad|rail|rare|rari|ray|rdnt|reef|rei|ren|renbtc|req|rep|reverse|rev|rgt|rif|rlc|rndr|rose|rpl|rsr|rune|rvn|sand|sandbox|sc|scrt|sei|sfp|shib|sia|skl|slf|slp|smt|snm|snt|snx|soc|sol|spell|spk|srm|stark|stx|sui|sun|super|sushi|sxp|sys|t|tao|tel|tfuel|tia|tlm|tomo|trb|tribe|troy|tru|trx|tsmt|tusd|tvk|twt|uft|uma|umee|undefined|uni|unfi|usdt|ust|usti|usu|val|valor|vanry|vibe|vidt|vite|voxel|vra|vrtx|vtho|w|waves|wbtc|win|wing|wld|wnxm|woo|wrx|wxt|xai|xch|xec|xem|xlm|xmr|xno|xrp|xtz|xvg|xvs|yfi|yfii|ygg|zec|zen|zil|zk|zrx)-up-down", re.I)


def fetch_activity(addr: str, limit: int = 500) -> list[dict]:
    """Pull up to `limit` activity items."""
    out = []
    offset = 0
    page_size = 500
    while offset < limit:
        want = min(page_size, limit - offset)
        try:
            r = requests.get(f"{DATA}/activity",
                             params={"user": addr, "limit": want, "offset": offset},
                             timeout=10)
            if r.status_code != 200:
                break
            j = r.json()
            if not isinstance(j, list) or not j:
                break
            out.extend(j)
            if len(j) < want:
                break
            offset += len(j)
        except Exception:
            break
    return out


def fetch_value(addr: str) -> float | None:
    try:
        r = requests.get(f"{DATA}/value", params={"user": addr}, timeout=8)
        if r.status_code == 200:
            j = r.json()
            if isinstance(j, list) and j:
                return j[0].get("value")
    except Exception:
        pass
    return None


def classify(addr: str, pseudonym: str, lb_summary: dict) -> dict:
    """Pull activity and compute taxonomy features."""
    activity = fetch_activity(addr, limit=500)
    value = fetch_value(addr)

    if not activity:
        return {
            "proxy_wallet": addr,
            "pseudonym": pseudonym,
            "activity_count": 0,
            "value_now": value,
            "verdict": "NO_ACTIVITY",
        }

    df = pd.DataFrame(activity)
    n = len(df)
    df["slug"] = df.get("slug", "")
    df["type"] = df.get("type", "")
    df["side"] = df.get("side", "")

    # ACTUAL slug format: "bitcoin-up-or-down-...", "ethereum-up-or-down-...", "solana-up-or-down-..."
    slug_s = df["slug"].astype(str)
    df["is_updown"] = slug_s.str.contains(r"-up-or-down-", case=False, na=False, regex=True)
    df["is_btc_updown"] = slug_s.str.contains(r"^bitcoin-up-or-down-", case=False, na=False, regex=True)
    df["is_eth_updown"] = slug_s.str.contains(r"^ethereum-up-or-down-", case=False, na=False, regex=True)
    df["is_sol_updown"] = slug_s.str.contains(r"^solana-up-or-down-", case=False, na=False, regex=True)
    n_updown = int(df["is_updown"].sum())
    pct_updown = n_updown / n * 100 if n else 0
    asset_mix = {
        "btc": int(df["is_btc_updown"].sum()),
        "eth": int(df["is_eth_updown"].sum()),
        "sol": int(df["is_sol_updown"].sum()),
    }

    # MAKER signal: MAKER_REBATE events are the only direct signal in activity feed
    # (TRADE events don't have maker/taker flag exposed). Rebates indicate market making.
    n_rebate = int((df["type"] == "MAKER_REBATE").sum())
    # Approx maker% from rebate count ratio (rough proxy)
    pct_maker = n_rebate / max(n, 1) * 100
    n_maker = n_rebate
    n_taker = max(0, n - n_rebate)

    # other categories
    type_counts = df["type"].astype(str).value_counts().head(8).to_dict()

    # size stats
    if "usdcSize" in df.columns:
        sz = pd.to_numeric(df["usdcSize"], errors="coerce")
    elif "size" in df.columns:
        sz = pd.to_numeric(df["size"], errors="coerce")
    else:
        sz = pd.Series(dtype=float)
    med_notional = float(sz.median()) if len(sz) else 0
    sum_notional = float(sz.sum()) if len(sz) else 0

    # market focus
    n_markets = df["slug"].astype(str).replace("", pd.NA).dropna().nunique()
    n_mlb = int(df["slug"].astype(str).str.startswith("mlb-").sum())
    n_nba = int(df["slug"].astype(str).str.startswith("nba-").sum())
    n_nhl = int(df["slug"].astype(str).str.startswith("nhl-").sum())
    n_election = int(df["slug"].astype(str).str.contains("election|president|primary", case=False, na=False).sum())

    # window
    if "timestamp" in df.columns:
        ts = pd.to_numeric(df["timestamp"], errors="coerce")
        t0 = int(ts.min()) if ts.notna().any() else None
        t1 = int(ts.max()) if ts.notna().any() else None
        span_h = (t1 - t0) / 3600 if t0 and t1 else 0
    else:
        t0, t1, span_h = None, None, 0

    # Verdict
    if pct_updown >= 60:
        verdict = "UPDOWN_FOCUSED"
    elif pct_updown >= 20:
        verdict = "UPDOWN_MIXED"
    elif n_mlb / max(n, 1) > 0.4:
        verdict = "SPORTS_MLB"
    elif (n_mlb + n_nba + n_nhl) / max(n, 1) > 0.4:
        verdict = "SPORTS_MIXED"
    elif n_election > n * 0.4:
        verdict = "POLITICAL"
    else:
        verdict = "OTHER"

    return {
        "proxy_wallet": addr,
        "pseudonym": pseudonym,
        "activity_count": n,
        "n_unique_markets": n_markets,
        "value_now": value,
        "pct_updown": round(pct_updown, 1),
        "asset_mix_updown": json.dumps(asset_mix),
        "pct_maker": round(pct_maker, 1),
        "n_maker": n_maker,
        "n_taker": n_taker,
        "n_rebate": n_rebate,
        "type_counts": json.dumps(type_counts),
        "med_notional": round(med_notional, 2),
        "sum_notional_recent": round(sum_notional, 2),
        "n_mlb": n_mlb,
        "n_nba": n_nba,
        "n_nhl": n_nhl,
        "n_election": n_election,
        "window_hours": round(span_h, 1),
        "verdict": verdict,
        **lb_summary,
    }


def main():
    # Load new candidates
    cand = pd.read_csv(CACHE / "_lb_new_candidates.csv")
    # Sort by quality signal: appearances desc + profit_30d desc
    cand["sort_score"] = (
        cand.get("appearances", 0).fillna(0) * 1_000_000
        + cand.get("profit_30d", 0).fillna(0).clip(lower=0)
    )
    cand = cand.sort_values("sort_score", ascending=False)
    print(f"Total new candidates: {len(cand)}")
    print(f"Will analyze ALL {len(cand)} (sorted by appearances + 30d profit)")
    top = cand

    # Build LB summary dict to merge in
    def lb_row(r):
        return {
            "lb_appearances": r.get("appearances"),
            "lb_best_rank": r.get("best_rank"),
            "lb_profit_all": r.get("profit_all"),
            "lb_profit_30d": r.get("profit_30d"),
            "lb_profit_7d": r.get("profit_7d"),
            "lb_profit_1d": r.get("profit_1d"),
            "lb_volume_all": r.get("volume_all"),
            "lb_volume_30d": r.get("volume_30d"),
        }

    results = []
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = {
            ex.submit(classify, r["proxy_wallet"], str(r["pseudonym"]), lb_row(r)): r["proxy_wallet"]
            for _, r in top.iterrows()
        }
        for fut in as_completed(futs):
            try:
                results.append(fut.result())
            except Exception as e:
                print(f"  ERR {futs[fut]}: {e}")

    df = pd.DataFrame(results)
    df = df.sort_values(["verdict", "lb_profit_30d"], ascending=[True, False])

    # Save
    out_all = CACHE / "_lb_new_wallet_classification.csv"
    df.to_csv(out_all, index=False)

    updown = df[df["verdict"].isin(["UPDOWN_FOCUSED", "UPDOWN_MIXED"])]
    out_ud = CACHE / "_lb_new_updown_focused.csv"
    updown.to_csv(out_ud, index=False)

    # Display
    show_cols = [
        "pseudonym", "proxy_wallet", "verdict", "pct_updown", "asset_mix_updown",
        "pct_maker", "lb_profit_30d", "lb_profit_7d", "lb_profit_1d", "lb_appearances",
        "activity_count", "value_now", "med_notional", "n_mlb", "n_election",
    ]
    show_cols = [c for c in show_cols if c in df.columns]

    print()
    print("=" * 80)
    print(f"VERDICT BREAKDOWN ({len(df)} wallets analyzed)")
    print("=" * 80)
    print(df["verdict"].value_counts())

    print()
    print("=" * 80)
    print(f"UPDOWN-FOCUSED ({len(updown)})")
    print("=" * 80)
    if len(updown):
        print(updown[show_cols].to_string(index=False))

    print()
    print("=" * 80)
    print("TOP 10 BY 30d PROFIT (all verdicts)")
    print("=" * 80)
    top30 = df.sort_values("lb_profit_30d", ascending=False).head(10)
    print(top30[show_cols].to_string(index=False))

    print(f"\nSaved: {out_all}")
    print(f"Saved: {out_ud}")


if __name__ == "__main__":
    main()
