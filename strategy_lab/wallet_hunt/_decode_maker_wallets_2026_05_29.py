"""Event-tape decode for the 4 daily/target-market maker wallets.

For each wallet, reconstruct per-conditionId (per market):
  - paired-buy mechanic: avg buy price per outcome, pair sum-cost (Up+Down)
  - exit: MERGE (instant $1/pair) vs REDEEM (hold to resolution $1) vs SELL
  - mint: SPLIT count
  - rebate income
  - classify market: paired vs single-sided; sum<$1 (true arb) vs sum>=$1
Outputs per-wallet per-market parquet + JSON summary + compact stdout.

PnL ground truth = lb-api /profit (the tape is capped at 3500/type so cash_pnl
is a lower bound on income types — we use it for MECHANIC, not PnL).
"""
from __future__ import annotations
import json, sys
from pathlib import Path
from collections import defaultdict
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from polymarket_api import fetch_lb_profit, lb_amount  # noqa
from cash_pnl import cash_pnl, maker_rebate_share       # noqa

PORT = HERE / "cache" / "_pm_portfolio"
OUT = HERE / "cache" / "_maker_decode_2026_05_29"
OUT.mkdir(parents=True, exist_ok=True)

WALLETS = {
    "0fe40e88": "0x0fe40e887acbd0022f89d996acce26ab428501b7",
    "4ee29e4e": "0x4ee29e4e7d4c380babeae5e22e5c02400c2246e1",
    "a42f127d": "0xa42f127d7e8df9f16881ffcc9ed0bc0326875f5a",
    "143732d8": "0x143732d8a06bd1596c694f7873cd493be80aacfe",
}
TYPES = ["TRADE","MERGE","SPLIT","REDEEM","MAKER_REBATE","REWARD","CONVERSION"]

def load_activity(short_full):
    short = short_full.lower()[:10]
    frames = []
    for t in TYPES:
        p = PORT / short / f"activity_{t}.json"
        if not p.exists():
            continue
        try:
            arr = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        if not arr:
            continue
        df = pd.DataFrame(arr); df["type"] = t
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True, sort=False)

def market_kind(slug):
    s = (slug or "").lower()
    if "up-or-down-on" in s: return "daily_updown"
    if "-up-or-down-" in s and any(c.isdigit() for c in s.rsplit("-",1)[-1]) and s.rsplit("-",1)[-1].isdigit() and len(s.rsplit("-",1)[-1])==10: return "intraday_updown"
    if "up-or-down" in s: return "hourly_updown"
    if "what-price-will" in s or "price-on" in s or "above-on" in s or "reach" in s: return "target_price"
    return "other"

def decode_wallet(short, full):
    df = load_activity(full)
    if df.empty:
        print(f"{short}: NO ACTIVITY"); return None
    for c in ["price","size","usdcSize","timestamp","outcomeIndex"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["slug"] = df.get("slug","").fillna("")
    df["outcome"] = df.get("outcome","").fillna("")
    df["side"] = df.get("side","").fillna("")
    df["cond"] = df.get("conditionId","").fillna("")

    # cash pnl mechanic breakdown (tape, capped) + ground truth
    res = cash_pnl(df)
    reb = maker_rebate_share(df)
    lb = fetch_lb_profit(full, use_cache=True)

    # market-kind distribution of TRADE notional
    tr = df[df["type"]=="TRADE"].copy()
    tr["kind"] = tr["slug"].map(market_kind)
    kind_notional = tr.groupby("kind")["usdcSize"].sum().sort_values(ascending=False)
    kind_n = tr["kind"].value_counts()

    # per-market (conditionId) reconstruction
    rows = []
    for cond, g in df.groupby("cond"):
        if not cond:
            continue
        gt = g[g["type"]=="TRADE"]
        slug = (gt["slug"].iloc[0] if len(gt) else g["slug"].iloc[0])
        kind = market_kind(slug)
        buys = gt[gt["side"].str.upper()=="BUY"]
        sells = gt[gt["side"].str.upper()=="SELL"]
        # per outcome buy aggregation
        oc = buys.groupby("outcome").agg(qty=("size","sum"), cost=("usdcSize","sum")).reset_index()
        oc = oc[oc["qty"]>0]
        outcomes = list(oc["outcome"])
        n_out = len(outcomes)
        # pair sum-cost = sum of avg buy price across the (up to 2) outcomes
        avgp = {r["outcome"]: (r["cost"]/r["qty"] if r["qty"] else np.nan) for _,r in oc.iterrows()}
        pair_sum = float(sum(avgp.values())) if n_out>=2 else np.nan
        n_merge = int((g["type"]=="MERGE").sum())
        n_redeem = int((g["type"]=="REDEEM").sum())
        n_split = int((g["type"]=="SPLIT").sum())
        merge_usd = float(g.loc[g["type"]=="MERGE","usdcSize"].sum())
        redeem_usd = float(g.loc[g["type"]=="REDEEM","usdcSize"].sum())
        rebate_usd = float(g.loc[g["type"]=="MAKER_REBATE","usdcSize"].sum())
        buy_usd = float(buys["usdcSize"].sum()); sell_usd = float(sells["usdcSize"].sum())
        rows.append(dict(cond=cond, slug=slug, kind=kind, n_buy=len(buys), n_sell=len(sells),
            n_outcomes=n_out, paired=(n_out>=2), pair_sum_cost=pair_sum,
            buy_usd=buy_usd, sell_usd=sell_usd, n_merge=n_merge, n_redeem=n_redeem,
            n_split=n_split, merge_usd=merge_usd, redeem_usd=redeem_usd, rebate_usd=rebate_usd))
    md = pd.DataFrame(rows)
    md.to_parquet(OUT / f"{short}_per_market.parquet", index=False)

    paired = md[md["paired"]]
    summary = {
        "short": short, "full": full,
        "lb_profit_all": lb_amount(lb,"all"), "lb_profit_30d": lb_amount(lb,"30d"),
        "lb_profit_7d": lb_amount(lb,"7d"), "lb_profit_1d": lb_amount(lb,"1d"),
        "maker_rebate_share": round(reb,4),
        "cash_breakdown": res["breakdown"],
        "n_markets": int(len(md)), "n_paired_markets": int(len(paired)),
        "pct_paired": round(100*len(paired)/max(1,len(md)),1),
        "pair_sum_cost_median": round(float(paired["pair_sum_cost"].median()),4) if len(paired) else None,
        "pair_sum_cost_p25": round(float(paired["pair_sum_cost"].quantile(.25)),4) if len(paired) else None,
        "pair_sum_cost_p75": round(float(paired["pair_sum_cost"].quantile(.75)),4) if len(paired) else None,
        "pct_pairs_sum_lt_1": round(100*float((paired["pair_sum_cost"]<1.0).mean()),1) if len(paired) else None,
        "pct_pairs_sum_lt_0995": round(100*float((paired["pair_sum_cost"]<0.995).mean()),1) if len(paired) else None,
        "trade_kind_notional": {k: round(float(v),0) for k,v in kind_notional.items()},
        "trade_kind_n": kind_n.to_dict(),
    }
    json.dump(summary, open(OUT / f"{short}_summary.json","w"), indent=2, default=str)

    print(f"\n===== {short}  ({full[:10]}) =====")
    print(f"  lb PnL: all=${summary['lb_profit_all']}  30d=${summary['lb_profit_30d']}  7d=${summary['lb_profit_7d']}")
    print(f"  maker_rebate_share={summary['maker_rebate_share']}  (>0.05 => maker)")
    print(f"  markets={summary['n_markets']}  paired={summary['n_paired_markets']} ({summary['pct_paired']}%)")
    print(f"  PAIR SUM-COST  median={summary['pair_sum_cost_median']}  p25={summary['pair_sum_cost_p25']}  p75={summary['pair_sum_cost_p75']}")
    print(f"  pct pairs sum<$1.00={summary['pct_pairs_sum_lt_1']}%   sum<$0.995={summary['pct_pairs_sum_lt_0995']}%")
    print(f"  trade notional by market-kind: {summary['trade_kind_notional']}")
    print(f"  cash breakdown (tape, capped): {res['breakdown']}")
    return summary

if __name__ == "__main__":
    for s,f in WALLETS.items():
        decode_wallet(s,f)
    print(f"\nsaved -> {OUT}")
