"""Overlay F7, Markov, F7+Markov to EVERY shadow sleeve (post-F7 23.5h window).

For sleeves that don't natively have F7 (sniper, v3, v4, volume), compute
F7 from RSI(14) at ws_s anchor. Then apply all 3 gate combos and report
per-sleeve.

ws_s = slot_start - window_s. Strike anchor for F7.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, "strategy_lab/markov_filter")
from markov_regime_micro import (  # noqa: E402
    build_labels_for_asset, regime_at_us, BEAR, SIDEWAYS, BULL,
)
from post_f7_real_compare_v2 import classify_strategy  # noqa: E402

EVENTS_CSV = "strategy_lab/markov_filter/_vps3_pull/post_f7_events.csv"
FRESH_KLINES = "strategy_lab/markov_filter/_vps3_pull/binance_1m_fresh.csv"
MARKETS_CSV = "strategy_lab/markov_filter/_vps3_pull/market_resolutions_recent.csv"
OUT_DIR = Path("strategy_lab/markov_filter/_results/post_f7_all_sleeves_overlay")
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
BEST_MARKOV_PER_TF = {"5m": "w20_1m_fixed", "15m": "w20_5m_voladaptive"}


# --------------------------------------------------------------------------- #
# RSI(14) Wilder on binance 1m
# --------------------------------------------------------------------------- #
def build_rsi_cache():
    """For each asset, pre-compute end_us + RSI(14) series."""
    print("[Pre] Building RSI(14) cache from fresh 1m klines...")
    kdf = pd.read_csv(FRESH_KLINES)
    cache = {}
    for asset in ("BTC", "ETH", "SOL"):
        sym = f"BINANCE_SPOT_{asset}_USDT"
        sub = kdf[kdf["symbol_id"] == sym].drop_duplicates("time_period_start_us") \
                                            .sort_values("time_period_start_us")
        closes = sub["price_close"].values.astype("float64")
        end_us = sub["time_period_start_us"].values.astype("int64") + 60_000_000
        # Wilder RSI(14): rolling Wilder smoother
        diffs = np.diff(closes)
        gains = np.where(diffs > 0, diffs, 0.0)
        losses = np.where(diffs < 0, -diffs, 0.0)
        # Compute Wilder smoothing
        n = len(closes)
        rsi = np.full(n, np.nan)
        if n > 14:
            avg_g = gains[:14].mean()
            avg_l = losses[:14].mean()
            for i in range(14, n - 1):
                rsi[i + 1] = 100.0 if avg_l == 0 else 100.0 - 100.0 / (1.0 + avg_g / avg_l)
                # smooth next
                avg_g = (avg_g * 13 + gains[i]) / 14
                avg_l = (avg_l * 13 + losses[i]) / 14
        cache[asset] = (end_us, rsi)
        print(f"   {asset}: bars={n}, RSI finite={np.isfinite(rsi).sum()}")
    return cache


def rsi_asof(end_us: np.ndarray, rsi: np.ndarray, target_us: int) -> float:
    idx = int(np.searchsorted(end_us, target_us, side="right")) - 1
    if idx < 0 or idx >= len(rsi):
        return float("nan")
    return float(rsi[idx])


# --------------------------------------------------------------------------- #
# Load fires
# --------------------------------------------------------------------------- #
def load_fires() -> pd.DataFrame:
    print("[1] Loading VPS3 events...")
    ev = pd.read_csv(EVENTS_CSV)
    ev["at"] = pd.to_datetime(ev["at"], utc=True, format="mixed")

    sig = ev[ev["kind"] == "poly_updown_signal"].copy()
    sig = sig[sig["data"].str.contains('"order_placed"', na=False)]
    print(f"[2] {len(sig)} order_placed signals")
    parsed = sig["data"].map(json.loads)
    fires = pd.DataFrame({
        "fire_us": (sig["at"].astype("int64") // 1000).values,
        "sleeve_id": sig["sleeve_id"].values,
        "signal": parsed.map(lambda d: d.get("signal")).values,
        "condition_id": parsed.map(lambda d: d.get("condition_id")).values,
        "ret_2m_at_signal": parsed.map(lambda d: d.get("ret_2m_at_signal")).values,
        "entry_phase": parsed.map(lambda d: d.get("entry_phase")).values,
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

    cls = df["sleeve_id"].map(classify_strategy)
    df["family"] = [c["family"] for c in cls]
    df["symbol"] = [c["symbol"] for c in cls]
    df["tf"]     = [c["tf"] for c in cls]
    df["version"] = [c["version"] for c in cls]
    df["is_f7"]  = [c["is_f7"] for c in cls]
    # Compute slot_start_s from slug + window_s + ws_s
    def slot_from_cid(cid):
        # condition_id is the polymarket condition hash, not the slug. Need actual slug...
        return np.nan
    # Better: get slug from the original event. Actually we already have it in sig.data
    return df, ev


def add_slug_and_ws_s(df: pd.DataFrame, ev: pd.DataFrame) -> pd.DataFrame:
    """Map condition_id → slug via VPS3 market_resolutions_v2. Derive ws_s."""
    mr = pd.read_csv(MARKETS_CSV)
    df = df.merge(mr[["market_id","slug","slot_start_us"]],
                  left_on="condition_id", right_on="market_id", how="left")
    df["slot_start_s"] = (df["slot_start_us"] / 1_000_000).astype("Int64")
    df["window_s"] = df["tf"].map({"5m": 300, "15m": 900})
    df["ws_s"]    = df["slot_start_s"] - df["window_s"]
    df["ws_us"]   = df["ws_s"].astype("float64") * 1_000_000
    n_have_slug = df["slug"].notna().sum()
    print(f"[4] {n_have_slug}/{len(df)} fires now have slug via VPS3 mapping")
    return df


def add_gates(df: pd.DataFrame, rsi_cache, markov_cache) -> pd.DataFrame:
    # RSI lookup
    print(f"[5] RSI(14) lookup for {len(df)} fires...")
    rsis = []
    for _, r in df.iterrows():
        if pd.isna(r["ws_us"]):
            rsis.append(np.nan); continue
        end_us, rsi = rsi_cache[r["symbol"]]
        rsis.append(rsi_asof(end_us, rsi, int(r["ws_us"])))
    df["rsi_14"] = rsis
    # F7 = signal-aligned with RSI direction
    df["f7_pass"] = (
        ((df["signal"] == "UP")   & (df["rsi_14"] > 50)) |
        ((df["signal"] == "DOWN") & (df["rsi_14"] < 50))
    )
    n_rsi = df["rsi_14"].notna().sum()
    print(f"   RSI finite: {n_rsi}/{len(df)}  F7 pass: {df.f7_pass.sum()} ({df.f7_pass.mean()*100:.1f}%)")

    print(f"[6] Markov regime lookup ×{len(MARKOV_VARIANTS)} variants...")
    for vname, _ in MARKOV_VARIANTS:
        regs = []
        for _, r in df.iterrows():
            end_us, labels = markov_cache[(vname, r["symbol"])]
            regs.append(regime_at_us(end_us, labels, int(r["fire_us"])))
        df[f"regime_{vname}"] = regs
        df[f"markov_pass_{vname}"] = (
            ((df["signal"] == "UP")   & (df[f"regime_{vname}"] == BULL)) |
            ((df["signal"] == "DOWN") & (df[f"regime_{vname}"] == BEAR))
        )
    return df


def build_markov_cache():
    print("[Pre] Building Markov label cache...")
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
    return cache


def summarize(g, label):
    n = len(g)
    if n == 0:
        return {"filter": label, "n": 0, "wr": 0.0, "avg": 0.0, "sum": 0.0}
    return {"filter": label, "n": n,
            "wr": round(g["won"].mean() * 100, 2),
            "avg": round(g["pnl_usd"].mean(), 3),
            "sum": round(g["pnl_usd"].sum(), 2)}


def report(df: pd.DataFrame):
    """Per-sleeve summary across 4 gate modes."""
    # Sleeve key: combine sleeve_id stripped of _f7 + policy
    df["base_sleeve"] = df["sleeve_id"].str.replace("_f7", "", regex=False)
    # For momo we want to merge HOLD/HEDGE/SELL into one sleeve (same entry)
    # since exit policy differs but entry is shared
    def normalize(sid):
        for tail in ("_HOLD", "_HEDGE", "_SELL"):
            if sid.endswith(tail):
                return sid[:-len(tail)]
        return sid
    df["sleeve_key"] = df["base_sleeve"].apply(normalize)

    sleeves = sorted(df["sleeve_key"].unique())
    print(f"\n=== Per-sleeve overlay ({len(sleeves)} sleeves) ===")
    all_rows = []
    for sleeve in sleeves:
        sub = df[df["sleeve_key"] == sleeve]
        if len(sub) < 5:
            continue
        rows = [
            summarize(sub, "BASELINE_ALL"),
            summarize(sub[sub["f7_pass"]], "F7_only"),
        ]
        for vname, _ in MARKOV_VARIANTS:
            mk = f"markov_pass_{vname}"
            rows.append(summarize(sub[sub[mk]], f"MARKOV:{vname}"))
            rows.append(summarize(sub[sub["f7_pass"] & sub[mk]], f"F7+MARKOV:{vname}"))
        # Best gate (n>=5)
        tbl = pd.DataFrame(rows)
        best = tbl[tbl["n"] >= 5].loc[tbl[tbl["n"] >= 5]["sum"].idxmax()] if (tbl["n"] >= 5).any() else None
        print(f"\n--- {sleeve}  n={len(sub)} ---")
        print(tbl[tbl["n"] >= 5].to_string(index=False))
        if best is not None:
            print(f"   → BEST: {best['filter']}  n={int(best['n'])} WR={best['wr']:.1f}% avg=${best['avg']:+.2f} sum=${best['sum']:+.2f}")
        tbl["sleeve"] = sleeve
        all_rows.append(tbl)
    if all_rows:
        out = pd.concat(all_rows, ignore_index=True)[
            ["sleeve","filter","n","wr","avg","sum"]
        ]
        out.to_csv(OUT_DIR / "per_sleeve_all_gates.csv", index=False)
        print(f"\nwrote {OUT_DIR/'per_sleeve_all_gates.csv'}")


def main():
    rsi_cache = build_rsi_cache()
    markov_cache = build_markov_cache()
    df, ev = load_fires()
    df = add_slug_and_ws_s(df, ev)
    df = add_gates(df, rsi_cache, markov_cache)
    df.to_csv(OUT_DIR / "fires_with_all_gates.csv", index=False)
    print(f"\nwrote {OUT_DIR / 'fires_with_all_gates.csv'}")
    report(df)


if __name__ == "__main__":
    main()
