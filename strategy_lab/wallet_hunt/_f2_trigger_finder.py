"""Find the EXACT fire trigger for the F2 cluster.

F2 = (0xa0a50783, 0x9dae874a). Both fire on BTC up-down markets with high
WR. We previously showed:
  - WR(match binance) = 87-100%
  - WR(contrary)      = 0-50%

But "match binance" doesn't explain WHEN they fire — only WHICH side they
pick GIVEN a fire. To find the trigger, we need fire-vs-control comparison
across all moments of the same slugs.

Approach:
  1. Load fires_decoded for both F2 wallets (5000 fires each, expanded sample).
  2. For each unique slug they fired on, generate CONTROL moments
     (every 5s during slug life: slot_start → slot_end).
  3. At each moment, extract features from canonical:
       - binance ret over 30s / 60s / 120s
       - rtds price + ret_60s
       - basis (binance - rtds) in bp
       - L25 book: sum_asks, sum_bids, own_ask, opp_ask, spread
       - offset_from_slot_start_s
  4. Label fires (any wallet, ±1s window) vs controls.
  5. Compare distributions + fit logistic regression.
  6. Output the discovered trigger formula.

Output: cache/_f2_trigger.json + cache/_f2_features.parquet
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
from load import (  # noqa: E402
    load_klines_asof, load_chainlink_asof,
    load_orderbook_l25_streaming, asof_strict, slug_to_ws_s,
)

CACHE = Path(__file__).resolve().parent / "cache"

F2_WALLETS = ("0xa0a50783", "0x9dae874a")
ASSETS = ("BTC", "ETH", "SOL")
WINDOW_S = {"5m": 300, "15m": 900}
CONTROL_SAMPLE_PERIOD_S = 5     # one control moment per 5 seconds of slug
FIRE_WINDOW_US = 1_000_000      # ±1s = a fire if within this of a moment

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_slug(slug: str) -> tuple[str, str, int] | None:
    """slug → (asset, tf, slot_start_s)."""
    parts = slug.split("-")
    if len(parts) != 4:
        return None
    asset_pre, _ud, tf, slot = parts
    if _ud != "updown" or tf not in WINDOW_S:
        return None
    try:
        return asset_pre.upper(), tf, int(slot)
    except ValueError:
        return None


def look_book(rec, t_us: int) -> dict | None:
    """L25 book state at t_us via searchsorted."""
    if rec is None:
        return None
    ts_arr, ap, asz, bp, bsz = rec
    if len(ts_arr) == 0:
        return None
    pos = int(np.searchsorted(ts_arr, t_us, side="right")) - 1
    if pos < 0:
        return None
    try:
        return {
            "ask": float(ap[pos][0]),
            "bid": float(bp[pos][0]),
            "asz": float(asz[pos][0]),
            "bsz": float(bsz[pos][0]),
            "dt_us": int(t_us - ts_arr[pos]),
        }
    except (IndexError, ValueError, TypeError):
        return None


def features_at(t_us: int, asset: str, slot_start_s: int,
                book_up, book_dn, klines, rtds) -> dict:
    """Compute features at moment t_us on a slug with slot_start_s."""
    end_us, prices = klines[asset]
    px_fire = asof_strict(end_us, prices, t_us)
    px_30s = asof_strict(end_us, prices, t_us - 30_000_000)
    px_60s = asof_strict(end_us, prices, t_us - 60_000_000)
    px_120s = asof_strict(end_us, prices, t_us - 120_000_000)
    ret_30s = (px_fire / px_30s - 1) if (px_fire > 0 and px_30s > 0) else float("nan")
    ret_60s = (px_fire / px_60s - 1) if (px_fire > 0 and px_60s > 0) else float("nan")
    ret_120s = (px_fire / px_120s - 1) if (px_fire > 0 and px_120s > 0) else float("nan")

    ts_arr, rt = rtds[asset]
    rtds_now = asof_strict(ts_arr, rt, t_us)
    rtds_60s = asof_strict(ts_arr, rt, t_us - 60_000_000)
    rtds_ret_60s = (rtds_now / rtds_60s - 1) if (rtds_now > 0 and rtds_60s > 0) else float("nan")
    basis_bp = ((px_fire / rtds_now - 1) * 10000) if (px_fire > 0 and rtds_now > 0) else float("nan")

    bu = look_book(book_up, t_us)
    bd = look_book(book_dn, t_us)
    sum_asks = (bu["ask"] + bd["ask"]) if (bu and bd) else float("nan")
    sum_bids = (bu["bid"] + bd["bid"]) if (bu and bd) else float("nan")

    return {
        "ts_us": t_us,
        "offset_s": (t_us // 1_000_000) - slot_start_s,
        "binance_px": px_fire,
        "binance_ret_30s": ret_30s,
        "binance_ret_60s": ret_60s,
        "binance_ret_120s": ret_120s,
        "rtds_px": rtds_now,
        "rtds_ret_60s": rtds_ret_60s,
        "basis_bp": basis_bp,
        "up_ask": bu["ask"] if bu else float("nan"),
        "up_bid": bu["bid"] if bu else float("nan"),
        "up_asz": bu["asz"] if bu else float("nan"),
        "dn_ask": bd["ask"] if bd else float("nan"),
        "dn_bid": bd["bid"] if bd else float("nan"),
        "dn_asz": bd["asz"] if bd else float("nan"),
        "sum_asks": sum_asks,
        "sum_bids": sum_bids,
    }


def main():
    # 1. Load fires_decoded for both F2 wallets
    print("Loading F2 fires_decoded ...")
    f_dfs = []
    for w in F2_WALLETS:
        p = CACHE / w / "fires_decoded.parquet"
        if not p.exists():
            print(f"  MISSING {p}")
            continue
        df = pd.read_parquet(p)
        df["wallet"] = w
        df = df[df["wallet_side"] == "BUY"].copy()   # only buys
        f_dfs.append(df)
    fires = pd.concat(f_dfs, ignore_index=True)
    print(f"  total F2 BUY fires loaded: {len(fires)}")

    # 2. Filter to BTC up-down slugs (where signal is strongest)
    fires = fires[fires.slug.str.startswith("btc-updown-")].copy()
    print(f"  BTC up-down BUYs: {len(fires)}")
    print(f"  unique slugs: {fires.slug.nunique()}")

    # 3. Slug list + slot_start map
    slugs = sorted(fires.slug.unique())
    slug_info = {s: parse_slug(s) for s in slugs}
    slugs_valid = [s for s, info in slug_info.items() if info is not None]
    print(f"  valid slugs: {len(slugs_valid)}")

    # 4. Load L25 OB for these slugs (BTC only, both sides)
    print("Loading L25 OB for fire-slugs ...")
    ob = load_orderbook_l25_streaming("btc", slugs=set(slugs_valid))
    print(f"  loaded {len(ob)} (slug, outcome) groups")

    # 5. Load binance + chainlink
    print("Loading binance klines + chainlink ...")
    klines = {a: load_klines_asof(a, "binance-spot-ws", "1MIN") for a in ASSETS}
    rtds = {a: load_chainlink_asof(a) for a in ASSETS}

    # 6. Build fire+control feature dataset
    print("Building feature dataset (fires + controls) ...")
    rows = []
    fires_by_slug = fires.groupby("slug")
    for slug in slugs_valid:
        info = slug_info[slug]
        asset, tf, slot_start_s = info
        window_s = WINDOW_S[tf]
        slot_end_s = slot_start_s + window_s
        book_up = ob.get((slug, "Up"))
        book_dn = ob.get((slug, "Down"))

        # Fire moments
        fr = fires_by_slug.get_group(slug) if slug in fires.slug.values else pd.DataFrame()
        fire_ts_us = sorted(fr["ts_us"].unique())
        fire_set = set(fire_ts_us)

        # Sample control moments at 5s intervals across the slug
        control_ts_us = list(range(
            slot_start_s * 1_000_000,
            slot_end_s * 1_000_000,
            CONTROL_SAMPLE_PERIOD_S * 1_000_000,
        ))

        # Tag each fire moment
        for t_us in fire_ts_us:
            f = features_at(t_us, asset, slot_start_s, book_up, book_dn, klines, rtds)
            # Find direction(s) picked at this fire moment
            tf_fires = fr[fr["ts_us"] == t_us]
            outcomes = sorted(tf_fires["outcome"].unique())
            f.update({
                "slug": slug,
                "is_fire": 1,
                "outcomes_picked": ",".join(outcomes),
                "n_legs_at_fire": len(tf_fires),
            })
            rows.append(f)

        # Tag controls (skip if within 1s of any fire)
        for t_us in control_ts_us:
            # Skip if too close to a fire
            close_fire = any(abs(t_us - f) < FIRE_WINDOW_US for f in fire_ts_us)
            if close_fire:
                continue
            f = features_at(t_us, asset, slot_start_s, book_up, book_dn, klines, rtds)
            f.update({
                "slug": slug, "is_fire": 0,
                "outcomes_picked": "",
                "n_legs_at_fire": 0,
            })
            rows.append(f)

    df = pd.DataFrame(rows)
    print(f"  feature rows: {len(df)} (fires={int(df.is_fire.sum())}, "
          f"controls={int((df.is_fire == 0).sum())})")

    # Save raw features
    out_parq = CACHE / "_f2_features.parquet"
    df.to_parquet(out_parq, index=False)
    print(f"  saved -> {out_parq}")

    # 7. Distribution comparison (fire vs control)
    print()
    print("=" * 80)
    print("Feature distributions — fire vs control")
    print("=" * 80)
    numeric_cols = [
        "offset_s", "binance_ret_30s", "binance_ret_60s", "binance_ret_120s",
        "rtds_ret_60s", "basis_bp", "sum_asks", "sum_bids",
        "up_ask", "up_bid", "dn_ask", "dn_bid", "up_asz", "dn_asz",
    ]
    fire = df[df.is_fire == 1]
    ctrl = df[df.is_fire == 0]
    summary = []
    for c in numeric_cols:
        f_vals = fire[c].dropna()
        c_vals = ctrl[c].dropna()
        if len(f_vals) == 0 or len(c_vals) == 0:
            continue
        summary.append({
            "feature": c,
            "fire_mean": float(f_vals.mean()),
            "ctrl_mean": float(c_vals.mean()),
            "fire_median": float(f_vals.median()),
            "ctrl_median": float(c_vals.median()),
            "fire_std": float(f_vals.std()),
            "ctrl_std": float(c_vals.std()),
            "fire_p10": float(f_vals.quantile(0.10)),
            "fire_p90": float(f_vals.quantile(0.90)),
            "ctrl_p10": float(c_vals.quantile(0.10)),
            "ctrl_p90": float(c_vals.quantile(0.90)),
            "mean_diff_z": (float(f_vals.mean()) - float(c_vals.mean())) /
                           (float(c_vals.std()) + 1e-9),
        })
    sm = pd.DataFrame(summary).sort_values("mean_diff_z", key=abs, ascending=False)
    pd.options.display.float_format = "{:.6f}".format
    print(sm.to_string(index=False))
    print()

    # 8. Logistic regression
    print("=" * 80)
    print("Logistic regression: P(fire | features)")
    print("=" * 80)
    feature_cols = [
        "offset_s", "binance_ret_60s", "binance_ret_120s",
        "rtds_ret_60s", "basis_bp",
        "sum_asks", "up_asz", "dn_asz",
    ]
    work = df[["is_fire"] + feature_cols].dropna()
    if len(work) > 100:
        try:
            from sklearn.linear_model import LogisticRegression
            from sklearn.preprocessing import StandardScaler
            X = work[feature_cols].values
            y = work["is_fire"].values
            scaler = StandardScaler()
            Xs = scaler.fit_transform(X)
            clf = LogisticRegression(max_iter=500, class_weight="balanced")
            clf.fit(Xs, y)
            coefs = pd.DataFrame({
                "feature": feature_cols,
                "coef_std": clf.coef_[0],
                "feature_mean": [float(work[c].mean()) for c in feature_cols],
                "feature_std": [float(work[c].std()) for c in feature_cols],
            }).sort_values("coef_std", key=abs, ascending=False)
            print(coefs.to_string(index=False))
            print(f"\nintercept: {float(clf.intercept_[0]):.4f}")
            print(f"train accuracy: {clf.score(Xs, y):.4f}")
            print(f"n_fire={int(y.sum())}  n_ctrl={int((y == 0).sum())}")
        except ImportError:
            print("  sklearn not installed; skipping")
    else:
        print(f"  insufficient data: {len(work)} rows after dropna")

    # 9. Direction picker (which side they buy given a fire)
    print()
    print("=" * 80)
    print("Direction picker: P(picked=Up | binance momentum)")
    print("=" * 80)
    fire_only = df[df.is_fire == 1].copy()
    # Single-leg fires: only one outcome picked
    single = fire_only[fire_only.outcomes_picked.isin(["Up", "Down"])].copy()
    print(f"  single-leg fires: {len(single)}")
    if len(single) > 50:
        single["picked_up"] = (single.outcomes_picked == "Up").astype(int)
        single["binance_up"] = (single.binance_ret_60s > 0).astype(int)
        match = (single.picked_up == single.binance_up).mean()
        print(f"  fires where pick matches sign(binance_ret_60s): {match*100:.2f}%")
        # Threshold sweep on binance_ret_60s
        for thr in (0.0, 0.0001, 0.0002, 0.0003, 0.0005, 0.001):
            sub_up = single[single.binance_ret_60s > thr]
            sub_dn = single[single.binance_ret_60s < -thr]
            if len(sub_up) == 0 and len(sub_dn) == 0:
                continue
            pct_up_when_signal_up = sub_up.picked_up.mean() if len(sub_up) > 0 else float("nan")
            pct_up_when_signal_dn = sub_dn.picked_up.mean() if len(sub_dn) > 0 else float("nan")
            print(f"  thr={thr*10000:.2f}bp  "
                  f"signal_up: n={len(sub_up):4d} pick_up={pct_up_when_signal_up:.3f}  "
                  f"signal_dn: n={len(sub_dn):4d} pick_up={pct_up_when_signal_dn:.3f}")

    # 10. Save final summary
    out_json = CACHE / "_f2_trigger.json"
    out_json.write_text(json.dumps({
        "fires": int(df.is_fire.sum()),
        "controls": int((df.is_fire == 0).sum()),
        "feature_summary": summary,
    }, indent=2, default=str))
    print(f"\nsaved -> {out_json}")


if __name__ == "__main__":
    main()
