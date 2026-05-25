"""Compare production logged ret_2m_at_signal vs clean recompute for the same slugs.

If they diverge, the bug is in production's _build_signal_aux. If they agree,
the bug is downstream (signal classification, F7 gate, or fire-event accounting).
"""
import json
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, "data/v4/canonical")
from load import load_resolutions  # noqa: E402

FRESH_KLINES = "strategy_lab/markov_filter/_vps3_pull/binance_1m_fresh.csv"


def close_at(end_us, close, target_us):
    i = int(np.searchsorted(end_us, int(target_us), side="right")) - 1
    if i < 0 or i >= len(close): return float("nan")
    return float(close[i])


def main():
    # 1. Load production audit rows for eth_5m_v2 _f7 fires
    ev = pd.read_csv("strategy_lab/markov_filter/_vps3_pull/post_f7_events.csv")
    ev["at"] = pd.to_datetime(ev["at"], utc=True, format="mixed")

    # Get all order_placed signal events for the broken sleeves
    BROKEN = ["eth_5m_momo_v2", "btc_15m_momo_v2"]

    # Load slug → market_id mapping
    mr = pd.read_csv("strategy_lab/markov_filter/_vps3_pull/market_resolutions_recent.csv")
    cid_to_slug = mr.set_index("market_id")["slug"].to_dict()
    cid_to_slot_start = mr.set_index("market_id")["slot_start_us"].to_dict()

    # Load fresh klines
    k = pd.read_csv(FRESH_KLINES)
    kcache = {}
    for asset in ("BTC","ETH","SOL"):
        sym = f"BINANCE_SPOT_{asset}_USDT"
        sub = k[k["symbol_id"]==sym].drop_duplicates("time_period_start_us") \
                                     .sort_values("time_period_start_us")
        kcache[asset] = (
            sub["time_period_start_us"].values.astype("int64") + 60_000_000,
            sub["price_close"].values.astype("float64"),
        )

    rows = []
    sig = ev[(ev["kind"]=="poly_updown_signal") &
              ev["data"].str.contains('"order_placed"', na=False)]
    for _, r in sig.iterrows():
        try: d = json.loads(r["data"])
        except: continue
        sleeve = r["sleeve_id"]
        if not any(b in sleeve for b in BROKEN):
            continue
        # production logged values
        prod_ret_2m = d.get("ret_2m_at_signal")
        prod_thr    = d.get("abs_ret_2m_threshold")
        prod_signal = d.get("signal")
        prod_symbol = d.get("symbol")
        prod_tf     = d.get("tf")
        cid         = d.get("condition_id")
        # clean recompute
        slot_start_us = cid_to_slot_start.get(cid)
        if slot_start_us is None: continue
        window_s = 300 if prod_tf == "5m" else 900
        ws_s = (slot_start_us / 1_000_000) - window_s
        end_us, c = kcache[prod_symbol]
        c_minus_60 = close_at(end_us, c, int((ws_s - 60) * 1_000_000))
        c_plus_60  = close_at(end_us, c, int((ws_s + 60) * 1_000_000))
        if not (np.isfinite(c_minus_60) and np.isfinite(c_plus_60) and c_minus_60 > 0):
            continue
        clean_ret_2m = float(np.log(c_plus_60 / c_minus_60))
        clean_signal = "UP" if clean_ret_2m > 0 else "DOWN"
        rows.append({
            "sleeve": sleeve, "ws_s": int(ws_s),
            "prod_ret_2m": prod_ret_2m,
            "clean_ret_2m": clean_ret_2m,
            "delta_ret": (prod_ret_2m - clean_ret_2m) if prod_ret_2m is not None else None,
            "prod_signal": prod_signal,
            "clean_signal": clean_signal,
            "sig_match": prod_signal == clean_signal,
            "c_minus_60": c_minus_60,
            "c_plus_60":  c_plus_60,
            "prod_thr": prod_thr,
        })
    out = pd.DataFrame(rows)
    print(f"Total compared fires: {len(out)}")
    if out.empty:
        print("No matches"); return

    print("\n=== Production ret_2m vs clean ret_2m ===")
    print(f"Sign matches: {out['sig_match'].sum()}/{len(out)}")
    if not out["delta_ret"].dropna().empty:
        print(f"Delta stats: mean={out['delta_ret'].mean():+.6f} std={out['delta_ret'].std():.6f}")
        print(f"Delta range: [{out['delta_ret'].min():+.6f}, {out['delta_ret'].max():+.6f}]")
    # Per sleeve
    for sleeve, g in out.groupby(out["sleeve"].str.replace("_HOLD","").str.replace("_HEDGE","").str.replace("_SELL","").str.replace("_f7","")):
        n = len(g)
        match_n = g["sig_match"].sum()
        print(f"\n{sleeve}  n={n}  sig_match={match_n} ({match_n/n*100:.1f}%)")
        # Show mismatches
        mm = g[~g["sig_match"]]
        if len(mm):
            print(f"  {len(mm)} mismatches — first 5:")
            print(mm[["ws_s","prod_ret_2m","clean_ret_2m","prod_signal","clean_signal","c_minus_60","c_plus_60"]].head(5).to_string(index=False))
    out.to_csv("strategy_lab/markov_filter/_results/prod_vs_clean_ret_2m.csv", index=False)


if __name__ == "__main__":
    main()
