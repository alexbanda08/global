"""
Shared trigger / slug-selection decode harness for directional Up/Down wallets.

Produces, for one wallet x (asset, timeframe), three things:
  1. ENTRY/DIRECTION features per fire (causal, anchored at the wallet's ACTUAL
     entry time fire_us = first buy on the held side of the slug). We reverse-
     engineer "why did they enter THIS side HERE".
  2. SLUG-SELECTION control: features at slot-open (slot_start_us) for engaged
     slugs vs a control sample of NON-engaged slugs in the same window. Reverse-
     engineers "why did they pick THIS window at all".
  3. Summary json: WR, top discriminating features (engaged vs control,
     Up vs Down, win vs loss), each as standardized mean-difference + AUC-ish.

CONVENTIONS (per root CLAUDE.md — do not violate):
  - External wallet decode anchors on the wallet's REAL entry time (fire_us),
    strictly causal. We are NOT comparing to production F7, so the ws_s anchor
    is not used for the wallet's own features; we DO record slot_start for
    slug-level (slot-open) features.
  - Outcome truth = canonical resolutions `outcome` (chainlink-derived).
  - asof lookups are causal (last bar ended <= target).
  - Indicators on-the-fly from 1MIN binance-spot-ws klines (cover full window to
    ~May 27). Precomputed 1s TA (ta_indicators_1s.parquet) only covers <=May 23,
    so we recompute the core set here for full coverage.
  - RSI = simple-mean Wilder (matches production rsi.py per CLAUDE.md).

Usage:
  py -3 strategy_lab/wallet_hunt/trigger_decode_harness.py --wallet 0x.. --asset btc --tf 5m
  py -3 strategy_lab/wallet_hunt/trigger_decode_harness.py --wallet 0x.. --asset eth --tf 15m --max-control 2000
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
from load import load_resolutions, load_klines_asof, load_chainlink_asof  # noqa: E402

CACHE = Path(__file__).resolve().parent / "cache"
DUST = 1.0
WINDOW_S = {"5m": 300, "15m": 900, "1h": 3600, "3m": 180, "1m": 60}


# ----------------------------------------------------------------- fires
def load_fires(wallet: str, asset: str, tf: str, res: pd.DataFrame) -> pd.DataFrame:
    short = wallet.lower()[:10]
    fp = CACHE / short / "trades.parquet"
    if not fp.exists():
        raise FileNotFoundError(f"no trades cache for {short}; run fetch first")
    tr = pd.read_parquet(fp)
    tr["slug"] = tr["slug"].astype(str)
    pref = f"{asset.lower()}-updown-{tf.lower()}-"
    tr = tr[tr["slug"].str.startswith(pref)].copy()
    if tr.empty:
        return pd.DataFrame()
    tr["side"] = tr["side"].astype(str).str.upper()
    tr["outcome"] = tr["outcome"].astype(str)
    tr["size"] = pd.to_numeric(tr["size"], errors="coerce").fillna(0.0)
    tr["price"] = pd.to_numeric(tr["price"], errors="coerce")
    tr["timestamp"] = pd.to_numeric(tr["timestamp"], errors="coerce")
    tr["buy_sz"] = np.where(tr["side"] == "BUY", tr["size"], 0.0)
    tr["sell_sz"] = np.where(tr["side"] == "SELL", tr["size"], 0.0)

    g = tr.groupby(["slug", "outcome"], as_index=False).agg(
        buy_sz=("buy_sz", "sum"), sell_sz=("sell_sz", "sum"),
        buy_notional=("buy_sz", lambda s: 0.0),  # placeholder, recompute below
    )
    # weighted entry px + first-buy ts per (slug, outcome)
    tr["buy_notional"] = tr["buy_sz"] * tr["price"]
    bn = tr.groupby(["slug", "outcome"], as_index=False).agg(
        buy_notional=("buy_notional", "sum"),
        first_buy_us=("timestamp", lambda s: int(s[tr.loc[s.index, "side"] == "BUY"].min()) * 1_000_000
                      if (tr.loc[s.index, "side"] == "BUY").any() else np.nan),
    )
    g = g.drop(columns=["buy_notional"]).merge(bn, on=["slug", "outcome"])
    g["net_qty"] = g["buy_sz"] - g["sell_sz"]
    g["avg_buy_px"] = np.where(g["buy_sz"] > 0, g["buy_notional"] / g["buy_sz"], np.nan)

    rows = []
    for slug, grp in g.groupby("slug"):
        longs = grp[grp["net_qty"] > DUST]
        if len(longs) != 1:
            continue  # not directional
        r = longs.iloc[0]
        rows.append({
            "slug": slug, "held_side": r["outcome"], "net_qty": float(r["net_qty"]),
            "entry_px": float(r["avg_buy_px"]), "fire_us": float(r["first_buy_us"]),
        })
    bets = pd.DataFrame(rows)
    if bets.empty:
        return bets
    bets["slot_start_s"] = bets["slug"].str.rsplit("-", n=1).str[-1].astype(np.int64)
    bets["slot_start_us"] = bets["slot_start_s"] * 1_000_000
    win = res[["slug", "outcome", "strike_price"]].rename(columns={"outcome": "winner"})
    bets = bets.merge(win, on="slug", how="inner")  # resolved only
    bets["won"] = bets["held_side"].str.lower() == bets["winner"].str.lower()
    bets["fire_offset_s"] = (bets["fire_us"] - bets["slot_start_us"]) / 1e6
    return bets


# ----------------------------------------------------------------- indicators
def _rsi_wilder_simple(closes: np.ndarray, n: int = 14) -> float:
    if len(closes) < n + 1:
        return np.nan
    d = np.diff(closes[-(n + 1):])
    gain = d[d > 0].sum() / n
    loss = -d[d < 0].sum() / n
    if loss == 0:
        return 100.0
    rs = gain / loss
    return 100.0 - 100.0 / (1.0 + rs)


def _ema_last(x: np.ndarray, span: int) -> float:
    if len(x) == 0:
        return np.nan
    a = 2.0 / (span + 1.0)
    e = x[0]
    for v in x[1:]:
        e = a * v + (1 - a) * e
    return e


def indicators_at(end_us: np.ndarray, close: np.ndarray, targets_us: np.ndarray,
                  lookback: int = 60) -> pd.DataFrame:
    """Causal 1MIN-bar indicators at each target_us. end_us sorted asc."""
    out = {k: np.full(len(targets_us), np.nan) for k in [
        "px", "rsi14", "macd", "macd_sig", "macd_hist",
        "ema9", "ema21", "ema9_slope_bps", "px_vs_ema21_bps",
        "ret_1m", "ret_3m", "ret_5m", "ret_15m", "ret_30m", "rv_15m_bps",
    ]}
    idx = np.searchsorted(end_us, targets_us.astype(np.int64), side="right") - 1
    for i, j in enumerate(idx):
        if j < lookback:
            continue
        w = close[j - lookback + 1: j + 1]
        px = w[-1]
        out["px"][i] = px
        out["rsi14"][i] = _rsi_wilder_simple(w, 14)
        e12 = _ema_last(w, 12); e26 = _ema_last(w, 26)
        macd = e12 - e26
        # signal = EMA9 of the macd line over the window (approx, causal)
        macd_series = np.array([_ema_last(w[:k + 1], 12) - _ema_last(w[:k + 1], 26)
                                for k in range(max(0, len(w) - 12), len(w))])
        sig = _ema_last(macd_series, 9)
        out["macd"][i] = macd; out["macd_sig"][i] = sig; out["macd_hist"][i] = macd - sig
        e9 = _ema_last(w, 9); e21 = _ema_last(w, 21)
        out["ema9"][i] = e9; out["ema21"][i] = e21
        e9_prev = _ema_last(w[:-3], 9) if len(w) > 3 else e9
        out["ema9_slope_bps"][i] = (e9 - e9_prev) / e9_prev * 1e4 if e9_prev else np.nan
        out["px_vs_ema21_bps"][i] = (px - e21) / e21 * 1e4 if e21 else np.nan
        for h, key in [(1, "ret_1m"), (3, "ret_3m"), (5, "ret_5m"),
                       (15, "ret_15m"), (30, "ret_30m")]:
            if len(w) > h:
                out[key][i] = (px / w[-1 - h] - 1) * 1e4  # bps
        if len(w) > 15:
            rets = np.diff(np.log(w[-16:]))
            out["rv_15m_bps"][i] = rets.std() * 1e4
    return pd.DataFrame(out)


def chainlink_at(asset: str, targets_us: np.ndarray) -> np.ndarray:
    ce, cc = load_chainlink_asof(asset)
    idx = np.searchsorted(ce, targets_us.astype(np.int64), side="right") - 1
    out = np.full(len(targets_us), np.nan)
    ok = idx >= 0
    out[ok] = cc[idx[ok]]
    return out


# ----------------------------------------------------------------- control
def build_control(asset: str, tf: str, res: pd.DataFrame, engaged_slugs: set,
                  lo_slot: int, hi_slot: int, max_control: int, seed: int = 7) -> pd.DataFrame:
    pref = f"{asset.lower()}-updown-{tf.lower()}-"
    r = res[res["slug"].str.startswith(pref)].copy()
    r["slot_start_s"] = r["slug"].str.rsplit("-", n=1).str[-1].astype(np.int64)
    r = r[(r["slot_start_s"] >= lo_slot) & (r["slot_start_s"] <= hi_slot)]
    r["engaged"] = r["slug"].isin(engaged_slugs)
    ctrl = r[~r["engaged"]]
    if len(ctrl) > max_control:
        ctrl = ctrl.sample(max_control, random_state=seed)
    ctrl = ctrl.copy()
    ctrl["slot_start_us"] = ctrl["slot_start_s"] * 1_000_000
    return ctrl[["slug", "slot_start_s", "slot_start_us", "outcome", "strike_price", "engaged"]]


# ----------------------------------------------------------------- discriminators
def discriminate(df: pd.DataFrame, mask: pd.Series, feats: list[str]) -> list[dict]:
    """Standardized mean diff (Cohen's d-ish) + group means for mask=True vs False."""
    out = []
    mask = mask.astype(bool)
    a = df[mask]; b = df[~mask]
    if len(a) < 5 or len(b) < 5:
        return out
    for f in feats:
        if f not in df.columns:
            continue
        xa = a[f].dropna(); xb = b[f].dropna()
        if len(xa) < 5 or len(xb) < 5:
            continue
        pooled = np.sqrt((xa.var(ddof=1) + xb.var(ddof=1)) / 2) or np.nan
        d = (xa.mean() - xb.mean()) / pooled if pooled and not np.isnan(pooled) else np.nan
        out.append({"feature": f, "mean_true": round(float(xa.mean()), 4),
                    "mean_false": round(float(xb.mean()), 4),
                    "cohens_d": round(float(d), 3) if d == d else None})
    out.sort(key=lambda z: abs(z["cohens_d"]) if z["cohens_d"] is not None else -1, reverse=True)
    return out


FEATS = ["rsi14", "macd", "macd_hist", "ema9_slope_bps", "px_vs_ema21_bps",
         "ret_1m", "ret_3m", "ret_5m", "ret_15m", "ret_30m", "rv_15m_bps",
         "cl_basis_bps", "px_vs_strike_bps", "utc_hour"]


def add_common_features(df: pd.DataFrame, asset: str, target_col: str) -> pd.DataFrame:
    e, c = load_klines_asof(asset, source="binance-spot-ws", period_id="1MIN")
    ind = indicators_at(e, c, df[target_col].to_numpy())
    df = pd.concat([df.reset_index(drop=True), ind.reset_index(drop=True)], axis=1)
    cl = chainlink_at(asset, df[target_col].to_numpy())
    df["cl_px"] = cl
    df["cl_basis_bps"] = (df["px"] - df["cl_px"]) / df["cl_px"] * 1e4
    df["px_vs_strike_bps"] = (df["px"] - df["strike_price"]) / df["strike_price"] * 1e4
    ts = pd.to_datetime(df[target_col].astype("int64"), unit="us", utc=True)
    df["utc_hour"] = ts.dt.hour
    df["dow"] = ts.dt.dayofweek
    return df


# ----------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wallet", required=True)
    ap.add_argument("--asset", required=True)
    ap.add_argument("--tf", required=True)
    ap.add_argument("--max-control", type=int, default=2000)
    args = ap.parse_args()

    asset, tf = args.asset.lower(), args.tf.lower()
    short = args.wallet.lower()[:10]
    odir = CACHE / short
    odir.mkdir(parents=True, exist_ok=True)

    res = load_resolutions()
    res["slug"] = res["slug"].astype(str)

    fires = load_fires(args.wallet, asset, tf, res)
    if fires.empty:
        print(f"{short} {asset}-{tf}: no directional resolved fires"); return
    print(f"{short} {asset}-{tf}: {len(fires)} directional fires, "
          f"WR {fires['won'].mean()*100:.1f}%, entry_px {fires['entry_px'].mean():.3f}")

    # ENTRY features at fire_us
    fires = add_common_features(fires, asset, "fire_us")
    # also slot-open features for engaged (for selection comparison)
    fires_open = add_common_features(fires[["slug", "slot_start_us", "strike_price"]].copy(),
                                     asset, "slot_start_us")

    lo, hi = int(fires["slot_start_s"].min()), int(fires["slot_start_s"].max())
    ctrl = build_control(asset, tf, res, set(fires["slug"]), lo, hi, args.max_control)
    if not ctrl.empty:
        ctrl = add_common_features(ctrl, asset, "slot_start_us")
    print(f"  control slugs (non-engaged, same window): {len(ctrl)}")

    # ---- discriminators
    summary = {"wallet": short, "asset": asset, "tf": tf,
               "n_fires": int(len(fires)), "wr": round(float(fires["won"].mean()), 4),
               "entry_px_mean": round(float(fires["entry_px"].mean()), 4),
               "up_bias": round(float((fires["held_side"].str.lower() == "up").mean()), 4),
               "window": [lo, hi]}

    # SLUG SELECTION: engaged (slot-open) vs control (slot-open)
    if not ctrl.empty:
        sel = pd.concat([fires_open.assign(engaged=True), ctrl.assign(engaged=False)],
                        ignore_index=True)
        summary["slug_selection_engaged_vs_control"] = discriminate(
            sel, sel["engaged"], [f for f in FEATS if f != "px_vs_strike_bps"] + ["px_vs_strike_bps"])

    # DIRECTION PICKER: Up vs Down (at fire)
    summary["direction_up_vs_down"] = discriminate(
        fires, fires["held_side"].str.lower() == "up", FEATS)

    # OUTCOME: win vs loss (at fire) — is the edge real or luck?
    summary["outcome_win_vs_loss"] = discriminate(fires, fires["won"], FEATS)

    # save
    fp_fires = odir / f"trigger_{asset}_{tf}.parquet"
    fires.to_parquet(fp_fires, index=False)
    if not ctrl.empty:
        ctrl.to_parquet(odir / f"control_{asset}_{tf}.parquet", index=False)
    fp_sum = odir / f"_trigger_{asset}_{tf}_summary.json"
    fp_sum.write_text(json.dumps(summary, indent=2, default=str))

    # console
    print("\n  TOP slug-selection discriminators (engaged vs control):")
    for d in summary.get("slug_selection_engaged_vs_control", [])[:6]:
        print(f"    {d['feature']:18s} d={d['cohens_d']}  eng={d['mean_true']} ctrl={d['mean_false']}")
    print("  TOP direction (Up vs Down):")
    for d in summary["direction_up_vs_down"][:6]:
        print(f"    {d['feature']:18s} d={d['cohens_d']}  up={d['mean_true']} dn={d['mean_false']}")
    print("  TOP win vs loss:")
    for d in summary["outcome_win_vs_loss"][:6]:
        print(f"    {d['feature']:18s} d={d['cohens_d']}  win={d['mean_true']} loss={d['mean_false']}")
    print(f"\n  -> {fp_fires}\n  -> {fp_sum}")


if __name__ == "__main__":
    main()
