"""Sim-vs-live reconciliation — diagnose the 30-pp hit-rate gap.

For each VPS3 V2 resolution, compute what the HEDGE_HOLD simulator would have
done (signal direction from local ret_5m, ride to resolution, no bid-exit)
and compare to what live actually did (HYBRID, with bid-exit fallback).

Decompose the gap into 4 buckets:
  A. Markets where sim & live agree on direction AND both held to resolution
     -> any PnL gap = fill-price slippage
  B. Markets where live exited at bid (HYBRID branch) -> sim would have held
     -> compute counterfactual: would sim's hold have won?
     -> this is the bid-exit cost
  C. Markets where sim & live disagree on direction (different ret_5m feed
     produces different sign)
     -> feed lead-lag cost
  D. Live skipped, sim would have fired (or vice versa)
     -> trigger threshold mismatch
"""
from __future__ import annotations
import json
from pathlib import Path
import pandas as pd
import numpy as np
from strategy_lab.v2_signals.common import load_features, ASSETS, DATA_DIR


SHADOW_VPS2 = DATA_DIR / "polymarket" / "vps2_v1_shadow.csv"
SHADOW_VPS3 = DATA_DIR / "polymarket" / "vps3_v2_shadow.csv"


def parse_shadow(path: Path) -> pd.DataFrame:
    rows = []
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        next(f)
        for line in f:
            parts = line.rstrip().split(",", 3)
            if len(parts) < 4:
                continue
            at, sleeve, kind, data = parts
            if data.startswith('"') and data.endswith('"'):
                data = data[1:-1].replace('""', '"')
            try:
                d = json.loads(data) if data.startswith("{") else {}
                rows.append({"at": at, "sleeve": sleeve, "kind": kind, **d})
            except Exception:
                pass
    df = pd.DataFrame(rows)
    return df


def load_all_features() -> pd.DataFrame:
    parts = []
    for a in ASSETS:
        df = load_features(a)
        if "asset" not in df.columns:
            df["asset"] = a
        parts.append(df)
    return pd.concat(parts, ignore_index=True)


def asset_from_sleeve(s: str) -> str | None:
    # poly_updown_btc_5m -> btc, poly_updown_eth_15m -> eth, etc.
    parts = s.split("_")
    if len(parts) >= 4 and parts[0] == "poly" and parts[1] == "updown":
        return parts[2]
    return None


def reconcile(name: str, shadow_path: Path, feats: pd.DataFrame):
    print(f"\n{'=' * 68}")
    print(f"=== {name}: {shadow_path.name}")
    print('=' * 68)

    tape = parse_shadow(shadow_path)
    res = tape[tape.kind == "poly_updown_resolution"].copy()
    if len(res) == 0:
        print("  no resolutions")
        return

    # Coerce types
    res["asset"] = res.sleeve.apply(asset_from_sleeve)
    res["won_bool"] = res["won"].astype(str).map({
        "True": True, "False": False, "1": True, "0": False
    })
    res["pnl_usd_num"] = pd.to_numeric(res["pnl_usd"], errors="coerce")
    res["entry_price_num"] = pd.to_numeric(res["entry_price"], errors="coerce")
    if "exited_at_bid" in res.columns:
        res["exited_at_bid_bool"] = res["exited_at_bid"].astype(str).map({
            "True": True, "False": False, "1": True, "0": False, "nan": False
        }).fillna(False)
    else:
        res["exited_at_bid_bool"] = False

    # Reconstruct expected slug from (asset, tf, at_unix - tf_seconds rounded down).
    # 5m markets have slot_start at multiples of 300, 15m at multiples of 900.
    # The resolution event 'at' is approximately slot_end (= slot_start + tf_seconds).
    res["at_unix"] = pd.to_datetime(res["at"], utc=True, errors="coerce").astype("int64") // 10**9
    tf_secs_map = {"5m": 300, "15m": 900}
    res["tf_seconds"] = res["tf"].map(tf_secs_map).fillna(300).astype(int)
    res["slot_start_est"] = res["at_unix"] - res["tf_seconds"]
    # Round DOWN to the nearest tf-multiple (slots align on tf boundaries):
    res["slot_start_aligned"] = (res["slot_start_est"] // res["tf_seconds"]) * res["tf_seconds"]
    res["expected_slug"] = res.apply(
        lambda r: f"{r['asset']}-updown-{r['tf']}-{r['slot_start_aligned']}" if pd.notna(r["asset"]) else None,
        axis=1
    )
    # Exact slug match
    feats_indexed = feats.set_index("slug")
    matched_idx = res["expected_slug"].isin(feats_indexed.index)
    print(f"  Slug match rate: {matched_idx.sum()}/{len(res)} ({matched_idx.sum()/len(res)*100:.1f}%)")
    sim_lookup = feats_indexed.loc[res.loc[matched_idx, "expected_slug"]][["ret_5m", "strike_price", "outcome_up"]]
    sim_lookup.columns = ["sim_ret_5m", "sim_strike", "sim_outcome_up"]
    sim_lookup = sim_lookup.reset_index(drop=True)
    sim_lookup.index = res.loc[matched_idx].index
    res["sim_ret_5m"] = float("nan")
    res["sim_strike"] = float("nan")
    res["sim_outcome_up"] = float("nan")
    for col in ["sim_ret_5m", "sim_strike", "sim_outcome_up"]:
        res.loc[matched_idx, col] = sim_lookup[col]
    joined = res.copy()

    # Sim's predicted direction (sign of its ret_5m)
    joined["sim_dir"] = joined["sim_ret_5m"].apply(
        lambda r: "UP" if pd.notna(r) and r > 0 else ("DOWN" if pd.notna(r) and r < 0 else "SKIP")
    )
    joined["live_dir"] = joined["signal"]

    # Bucket the markets
    matched = joined[joined["sim_ret_5m"].notna()]
    n_total = len(joined)
    n_matched = len(matched)
    print(f"  Total resolutions: {n_total} (matched to features: {n_matched})")

    # Direction agreement
    dir_match = (matched["sim_dir"] == matched["live_dir"]).sum()
    dir_mismatch = (matched["sim_dir"] != matched["live_dir"]).sum()
    print(f"  Direction agreement (sim vs live): {dir_match}/{n_matched} ({dir_match/n_matched*100:.1f}%)")

    # Live hit rate
    live_won = matched["won_bool"].sum()
    print(f"  Live hit rate: {live_won}/{n_matched} = {live_won/n_matched*100:.1f}%")
    print(f"  Live total PnL: ${matched['pnl_usd_num'].sum():.2f}")

    # Sim hit rate (sim direction == actual outcome)
    actual_up = matched["outcome"] == "Up"
    sim_predicted_up = matched["sim_dir"] == "UP"
    sim_predicted_dn = matched["sim_dir"] == "DOWN"
    sim_hit = ((sim_predicted_up & actual_up) | (sim_predicted_dn & ~actual_up))
    sim_hit_count = sim_hit.sum()
    sim_acted = sim_predicted_up.sum() + sim_predicted_dn.sum()
    if sim_acted > 0:
        print(f"  Sim hit rate (counterfactual): {sim_hit_count}/{sim_acted} = {sim_hit_count/sim_acted*100:.1f}%")

    # === Bid-exit cost (the HYBRID-specific bleed) ===
    bid_exits = matched[matched["exited_at_bid_bool"] == True].copy()
    print(f"\n  --- Bucket B: live exited at bid ({len(bid_exits)} markets) ---")
    if len(bid_exits) > 0:
        bid_exits_pnl = bid_exits["pnl_usd_num"].sum()
        # Counterfactual: derive resolution direction from chainlink settle vs strike
        # (the `outcome` column is "exited_at_bid", not Up/Down, for these rows)
        bid_exits["strike_num"] = pd.to_numeric(bid_exits["strike_price"], errors="coerce")
        bid_exits["settle_num"] = pd.to_numeric(bid_exits["settlement_price"], errors="coerce")
        bid_exits["resolved_up"] = bid_exits["settle_num"] > bid_exits["strike_num"]
        cf_won = ((bid_exits["live_dir"] == "UP") & (bid_exits["resolved_up"])) | \
                 ((bid_exits["live_dir"] == "DOWN") & (~bid_exits["resolved_up"]))
        cf_won_count = cf_won.sum()
        # Approximate counterfactual PnL per market: if won, +qty*(1 - entry_px); if lost, -qty*entry_px
        bid_exits["entry_qty_num"] = pd.to_numeric(bid_exits["entry_qty"], errors="coerce")
        cf_pnl_per = (
            bid_exits["entry_qty_num"] * (1.0 - bid_exits["entry_price_num"]) * cf_won.astype(int)
            - bid_exits["entry_qty_num"] * bid_exits["entry_price_num"] * (~cf_won).astype(int)
        )
        cf_pnl = cf_pnl_per.sum()
        print(f"    Live PnL on these: ${bid_exits_pnl:.2f}")
        print(f"    Counterfactual hold-to-resolution wins: {cf_won_count}/{len(bid_exits)} = "
              f"{cf_won_count/len(bid_exits)*100:.1f}%")
        print(f"    Counterfactual PnL (hold-to-resolution): ${cf_pnl:.2f}")
        savings = cf_pnl - bid_exits_pnl
        print(f"    Bid-exit branch impact (cf - live): ${savings:+.2f} "
              f"({'cost' if savings > 0 else 'savings'} of bid-exit)")

    # === Held to resolution by both sim and live ===
    held = matched[matched["exited_at_bid_bool"] == False]
    print(f"\n  --- Bucket A: live held to resolution ({len(held)} markets) ---")
    if len(held) > 0:
        held_won = held["won_bool"].sum()
        print(f"    Live hit rate: {held_won}/{len(held)} = {held_won/len(held)*100:.1f}%")
        print(f"    Live PnL: ${held['pnl_usd_num'].sum():.2f}")

    # === Direction disagreement ===
    print(f"\n  --- Bucket C: direction mismatch (sim vs live feed differ) ---")
    mismatches = matched[matched["sim_dir"] != matched["live_dir"]]
    print(f"    {len(mismatches)} markets, "
          f"live PnL on these: ${mismatches['pnl_usd_num'].sum():.2f}")
    if len(mismatches) > 0:
        sample_dir_mismatch = mismatches.head(5)[["asset", "live_dir", "sim_dir", "won_bool", "pnl_usd_num"]]
        print(f"    Sample (5 rows):\n{sample_dir_mismatch.to_string(index=False)}")


def main():
    feats = load_all_features()
    print(f"Loaded features: {len(feats)} markets across {feats.asset.nunique()} assets")
    reconcile("VPS2 V1 (HEDGE_HOLD)", SHADOW_VPS2, feats)
    reconcile("VPS3 V2 (HYBRID)", SHADOW_VPS3, feats)


if __name__ == "__main__":
    main()
