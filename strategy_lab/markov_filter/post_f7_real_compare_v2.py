"""Per-strategy-family + per-sleeve F7 vs Markov comparison on real VPS3 fires.

Critical fix vs v1: separate by strategy FAMILY (momo / sniper / v3 / v4 /
volume / inverse), not just by 'v1/v2'. F7 only applies to momo families;
other strategies have no F7 variant, so they shouldn't be in the "baseline
no_F7" bucket for momo analysis.
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, "data/v4/canonical")
sys.path.insert(0, "strategy_lab/markov_filter")
from markov_regime_micro import (  # noqa: E402
    build_labels_for_asset, regime_at_us, BEAR, SIDEWAYS, BULL,
)

EVENTS_CSV = "strategy_lab/markov_filter/_vps3_pull/post_f7_events.csv"
FRESH_KLINES = "strategy_lab/markov_filter/_vps3_pull/binance_1m_fresh.csv"
OUT_DIR = Path("strategy_lab/markov_filter/_results/post_f7_real_compare_v2")
OUT_DIR.mkdir(parents=True, exist_ok=True)

MARKOV_VARIANTS = [
    ("w20_1m_voladaptive", {"window_bars": 20, "bar_minutes": 1, "mode": "vol_adaptive"}),
    ("w20_5m_voladaptive", {"window_bars": 20, "bar_minutes": 5, "mode": "vol_adaptive"}),
    ("w20_1m_fixed",       {"window_bars": 20, "bar_minutes": 1, "mode": "fixed"}),
    ("w20_5m_fixed",       {"window_bars": 20, "bar_minutes": 5, "mode": "fixed"}),
]
FIXED_THRESHOLDS = {
    1: {"BTC": 0.003, "ETH": 0.004, "SOL": 0.006},
    5: {"BTC": 0.005, "ETH": 0.007, "SOL": 0.010},
}


# --------------------------------------------------------------------------- #
# Strategy family classifier
# --------------------------------------------------------------------------- #
def classify_strategy(sleeve_id: str) -> dict:
    """Parse sleeve_id like 'poly_updown_btc_5m_momo_v2_HOLD_f7' into:
       symbol, tf, family, version, policy, is_f7.
    Family ∈ {momo, sniper, sniper_INV, sniper_DOWN_INV, v3, v4,
              volume_INV_NIGHT, unknown}.
    """
    s = sleeve_id.replace("poly_updown_", "")
    is_f7 = s.endswith("_f7")
    if is_f7:
        s = s[:-3]

    # symbol + tf are the first 2 tokens
    m = re.match(r"^(btc|eth|sol)_(5m|15m)_(.+)$", s)
    if not m:
        return {"family": "unknown", "version": None, "policy": None,
                "is_f7": is_f7, "symbol": None, "tf": None}
    symbol, tf, rest = m.group(1).upper(), m.group(2), m.group(3)

    # Family detection (specific → general)
    if "volume_INV_NIGHT" in rest:
        family = "volume_INV_NIGHT"; version = None; policy = None
    elif "sniper_DOWN_INV" in rest:
        family = "sniper_DOWN_INV"; version = None; policy = None
    elif "sniper_INV" in rest:
        family = "sniper_INV"; version = None; policy = None
    elif "sniper" in rest:
        family = "sniper"; version = None; policy = None
    elif "momo_v2" in rest:
        family = "momo"; version = "v2"
        # rest looks like "momo_v2_HOLD" → policy = HOLD
        parts = rest.split("_")
        policy = parts[-1] if parts[-1] in ("HOLD","HEDGE","SELL") else None
    elif "momo" in rest:
        family = "momo"; version = "v1"
        parts = rest.split("_")
        policy = parts[-1] if parts[-1] in ("HOLD","HEDGE","SELL") else None
    elif re.search(r"^v3(_\d)?$", rest):
        family = "v3"; version = rest; policy = None
    elif rest == "v4":
        family = "v4"; version = "v4"; policy = None
    else:
        family = "unknown"; version = None; policy = None
    return {"family": family, "version": version, "policy": policy,
            "is_f7": is_f7, "symbol": symbol, "tf": tf}


def load_fires_and_outcomes(ev: pd.DataFrame) -> pd.DataFrame:
    sig = ev[ev["kind"] == "poly_updown_signal"].copy()
    sig = sig[sig["data"].str.contains('"order_placed"', na=False)]
    print(f"[2] {len(sig)} order_placed signals")
    parsed = sig["data"].map(json.loads)
    fires = pd.DataFrame({
        "fire_us": (sig["at"].astype("int64") // 1000).values,
        "sleeve_id": sig["sleeve_id"].values,
        "signal": parsed.map(lambda d: d.get("signal")).values,
        "condition_id": parsed.map(lambda d: d.get("condition_id")).values,
    })

    res = ev[ev["kind"] == "poly_updown_resolution"].copy()
    rparsed = res["data"].map(json.loads)
    resdf = pd.DataFrame({
        "sleeve_id": res["sleeve_id"].values,
        "condition_id": rparsed.map(lambda d: d.get("condition_id")).values,
        "won": rparsed.map(lambda d: bool(d.get("won", False))).values,
        "pnl_usd": pd.to_numeric(rparsed.map(lambda d: d.get("pnl_usd", 0.0)),
                                 errors="coerce").values,
    })

    df = fires.merge(resdf, on=["sleeve_id", "condition_id"], how="inner")
    print(f"[3] {len(df)} fire-resolution pairs")
    df = df.dropna(subset=["signal", "pnl_usd", "fire_us"])

    # Strategy classification
    cls = df["sleeve_id"].map(classify_strategy)
    df["family"]  = [c["family"]  for c in cls]
    df["version"] = [c["version"] for c in cls]
    df["policy"]  = [c["policy"]  for c in cls]
    df["is_f7"]   = [c["is_f7"]   for c in cls]
    df["symbol"]  = [c["symbol"]  for c in cls]
    df["tf"]      = [c["tf"]      for c in cls]
    return df


def add_markov(df: pd.DataFrame):
    print(f"[4] Building Markov label cache...")
    cache = {}
    for vname, params in MARKOV_VARIANTS:
        for asset in ("BTC", "ETH", "SOL"):
            kw = dict(window_bars=params["window_bars"],
                      bar_minutes=params["bar_minutes"], mode=params["mode"],
                      fresh_klines_csv=FRESH_KLINES)
            if params["mode"] == "fixed":
                kw["fixed_threshold"] = FIXED_THRESHOLDS[params["bar_minutes"]][asset]
            end_us, _c, labels = build_labels_for_asset(asset, **kw)
            cache[(vname, asset)] = (end_us, labels)
    print(f"[5] Regime lookup for {len(df)} fires × {len(MARKOV_VARIANTS)} variants...")
    for vname, _ in MARKOV_VARIANTS:
        regs = []
        for _, r in df.iterrows():
            end_us, labels = cache[(vname, r["symbol"])]
            regs.append(regime_at_us(end_us, labels, int(r["fire_us"])))
        df[f"regime_{vname}"] = regs
        df[f"markov_pass_{vname}"] = (
            ((df["signal"] == "UP")   & (df[f"regime_{vname}"] == BULL)) |
            ((df["signal"] == "DOWN") & (df[f"regime_{vname}"] == BEAR))
        )
    return df


def summarize(g: pd.DataFrame, label: str) -> dict:
    n = len(g)
    if n == 0:
        return {"filter": label, "n": 0, "wr": 0.0, "avg": 0.0, "sum": 0.0}
    return {"filter": label, "n": n,
            "wr": round(g["won"].mean() * 100, 2),
            "avg": round(g["pnl_usd"].mean(), 3),
            "sum": round(g["pnl_usd"].sum(), 2)}


def report_per_family(df: pd.DataFrame):
    """Per-strategy-family per-sleeve table."""
    df["sleeve"] = df["symbol"].str.lower() + "_" + df["tf"]
    if df["version"].notna().any():
        df.loc[df["version"].notna(), "sleeve"] += "_" + df["version"]

    all_rows = []
    for family in sorted(df["family"].unique()):
        fam_df = df[df["family"] == family]
        has_f7 = fam_df["is_f7"].any()
        n_total = len(fam_df)
        print(f"\n{'='*70}")
        print(f"FAMILY: {family}   n_total={n_total}   has F7 variant: {has_f7}")
        print(f"{'='*70}")

        # Per-sleeve breakdown
        for sleeve in sorted(fam_df["sleeve"].unique()):
            sub = fam_df[fam_df["sleeve"] == sleeve]
            if len(sub) < 5:
                continue
            f7_sub = sub[sub["is_f7"]]
            no_sub = sub[~sub["is_f7"]]
            rows = [summarize(sub, "ALL")]
            if has_f7:
                rows.append(summarize(no_sub, "no_F7 (baseline)"))
                rows.append(summarize(f7_sub, "F7_only"))
            for vname, _ in MARKOV_VARIANTS:
                mk = f"markov_pass_{vname}"
                rows.append(summarize(sub[sub[mk]], f"MARKOV:{vname}"))
                if has_f7:
                    rows.append(summarize(f7_sub[f7_sub[mk]],
                                          f"F7+MARKOV:{vname}"))
                    rows.append(summarize(no_sub[no_sub[mk]],
                                          f"noF7+MARKOV:{vname}"))
            tbl = pd.DataFrame(rows)
            print(f"\n--- {family} / {sleeve}  (n={len(sub)}, f7={len(f7_sub)}, no_f7={len(no_sub)}) ---")
            print(tbl[tbl["n"] >= 5].to_string(index=False))
            tbl["family"] = family; tbl["sleeve"] = sleeve
            all_rows.append(tbl)
    if all_rows:
        out = pd.concat(all_rows, ignore_index=True)
        out = out[["family","sleeve","filter","n","wr","avg","sum"]]
        out.to_csv(OUT_DIR / "per_family_sleeve.csv", index=False)
        print(f"\nwrote {OUT_DIR/'per_family_sleeve.csv'}")


def main():
    print("[1] Loading VPS3 events...")
    ev = pd.read_csv(EVENTS_CSV)
    ev["at"] = pd.to_datetime(ev["at"], utc=True, format="mixed")
    print(f"    {len(ev):,} events")

    df = load_fires_and_outcomes(ev)
    if df.empty:
        print("NO FIRES"); return

    # Show family breakdown first
    print("\n=== Strategy family breakdown (post-F7 window, fires only) ===")
    fam_summary = (df.groupby(["family", "is_f7"])
                     .agg(n=("won","size"), wr=("won","mean"),
                          pnl=("pnl_usd","sum"), avg=("pnl_usd","mean"))
                     .round({"wr":3, "pnl":2, "avg":3}))
    fam_summary["wr"] = (fam_summary["wr"]*100).round(2)
    print(fam_summary.to_string())

    df = add_markov(df)
    df.to_csv(OUT_DIR / "fires_with_gates.csv", index=False)
    print(f"\nwrote {OUT_DIR / 'fires_with_gates.csv'}")

    report_per_family(df)


if __name__ == "__main__":
    main()
