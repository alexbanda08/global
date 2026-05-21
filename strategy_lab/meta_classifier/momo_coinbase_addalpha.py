"""Momo + Coinbase add-alpha test — Phase 16 §B real test.

Reuses the proven momo_full_universe_validation.py pipeline (which already
established HOLD_baseline = +$12,846 / 949 trades / +$13.54/trade).

Question: does adding coinbase-derived features lift the existing baseline?

Coinbase variants (each modifies the gate; signal direction follows gate input):
  B0 baseline           (canonical: |bin_ret_2m| ≥ q90, sign(bin_ret_2m))
  F1 premium-aligned    (sign(premium_ws) == sign(signal))
  F2 premium-magnitude  (|premium_ws| > 5bp)
  F3 premium-zscore     (|z(premium, 7d)| > 1.5)
  F4 premium-velocity   (premium_d2m × signal > 0)
  F5 cross-venue-agree  (sign(bin_ret_2m) == sign(coin_ret_2m))
  E1 ensemble-gate      (gate by 0.5*bin_ret + 0.5*coin_ret, signal=sign of ensemble)
  E2 coin-only-gate     (gate by coin_ret_2m alone — negative control)
  E3 premium-as-signal  (gate by |premium|, sign(premium) = direction)

Policies tested per variant:
  HOLD            — no exit (baseline)
  HEDGE_5bp       — Binance rev_bp ≥ 5 → walk opposite-asks
  SELL_V1_5bp     — Binance rev_bp ≥ 5, anchor=close@ws (production v1)
  SELL_V2_5bp     — Binance rev_bp ≥ 5, anchor=close@fire (v2 tighter stop)

Output:
  data/v4/refresh_2026_05_09/coinbase_addalpha/per_trade.csv
  data/v4/refresh_2026_05_09/coinbase_addalpha/summary.csv
  data/v4/refresh_2026_05_09/coinbase_addalpha/lift.csv
  strategy_lab/reports/MOMO_COINBASE_ADDALPHA_2026_05_09.md
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "strategy_lab"))
sys.path.insert(0, str(ROOT / "strategy_lab" / "meta_classifier"))

from book_walk import book_walk_fill                                       # noqa: E402
from momo_full_universe_validation import (                                # noqa: E402
    load_klines, load_universe, compute_ret_2m, compute_thresholds,
    load_l25_for_asset, find_book, sell_at_bid_partial, asof_strict,
    NOTIONAL, FEE, SPREAD_FILTER, TICK_S,
    REFRESH_NEW,
)
# Phase 16 add-alpha — fire offset is locked at +60 (production momo_v2 t_plus_60).
# Older momo_full_universe_validation versions exported FIRE_OFFSET_S=60 directly;
# newer versions moved to per-sleeve SLEEVE_FIRE dict with ws=end semantics.
# We continue to use ws=start internally (mirroring production controller's ws_s),
# so fire_offset = +60 is the strike+60 fire time either way.
FIRE_OFFSET_S = 60

OUT_DIR = REFRESH_NEW / "coinbase_addalpha"
OUT_DIR.mkdir(parents=True, exist_ok=True)
REPORT = ROOT / "strategy_lab" / "reports" / "MOMO_COINBASE_ADDALPHA_2026_05_09.md"

ASSET_COIN = {"BTC": "COINBASE_SPOT_BTC_USD",
              "ETH": "COINBASE_SPOT_ETH_USD",
              "SOL": "COINBASE_SPOT_SOL_USD"}

PREMIUM_5BP = 0.0005
Z_THRESHOLD = 1.5
Z_WINDOW_DAYS = 7

VARIANTS = ["B0", "F1", "F2", "F3", "F4", "F5", "E1", "E2", "E3"]
POLICIES = ["HOLD", "HEDGE_5bp", "SELL_V1_5bp", "SELL_V2_5bp"]


# ---------------------------------------------------------------------------
# Coinbase loader (matches load_klines() shape: dict[asset] -> (end_us, price_close))
# ---------------------------------------------------------------------------

def load_coinbase_klines() -> dict:
    """1MIN coinbase closes per asset from cex_klines_vps2.csv → searchsorted-ready arrays."""
    df = pd.read_csv(REFRESH_NEW / "cex_klines_vps2.csv",
                     usecols=["symbol_id", "period_id", "source",
                              "time_period_start_us", "price_close"])
    df = df[(df.period_id == "1MIN") & (df.source == "coinbase-spot-ws")].copy()
    df["ts_s"] = (df.time_period_start_us // 1_000_000).astype("int64")
    out = {}
    for a in ("BTC", "ETH", "SOL"):
        sub = df[df.symbol_id == ASSET_COIN[a]].sort_values("ts_s").reset_index(drop=True)
        end_us = (sub.ts_s.values.astype("int64") + 60) * 1_000_000
        price_close = sub.price_close.values.astype("float64")
        out[a] = (end_us, price_close)
        print(f"    coinbase/{a}: {len(sub)} 1m bars")
    return out


# ---------------------------------------------------------------------------
# Coinbase features
# ---------------------------------------------------------------------------

def attach_coinbase_features(uni: pd.DataFrame, bin_klines: dict, coin_klines: dict) -> pd.DataFrame:
    n = len(uni)
    coin_ret_2m = np.full(n, np.nan)
    premium_ws = np.full(n, np.nan)
    premium_d2m = np.full(n, np.nan)
    for i, (asset, ws) in enumerate(zip(uni.asset.values, uni.ws.values)):
        ws = int(ws)
        b_pre = asof_strict(bin_klines[asset], ws - 60)
        b_post = asof_strict(bin_klines[asset], ws + 60)
        b_at = asof_strict(bin_klines[asset], ws)
        c_pre = asof_strict(coin_klines[asset], ws - 60)
        c_post = asof_strict(coin_klines[asset], ws + 60)
        c_at = asof_strict(coin_klines[asset], ws)
        if math.isfinite(c_pre) and math.isfinite(c_post) and c_pre > 0 and c_post > 0:
            coin_ret_2m[i] = math.log(c_post / c_pre)
        if math.isfinite(b_at) and math.isfinite(c_at) and b_at > 0 and c_at > 0:
            premium_ws[i] = math.log(c_at / b_at)
        if (math.isfinite(b_pre) and math.isfinite(c_pre) and b_pre > 0 and c_pre > 0
                and math.isfinite(b_post) and math.isfinite(c_post) and b_post > 0 and c_post > 0):
            premium_d2m[i] = math.log(c_post / b_post) - math.log(c_pre / b_pre)
    uni = uni.copy()
    uni["coin_ret_2m"] = coin_ret_2m
    uni["premium_ws"] = premium_ws
    uni["premium_d2m"] = premium_d2m
    # rolling 7d z-score of premium per asset
    uni["premium_z_7d"] = np.nan
    win_s = Z_WINDOW_DAYS * 86400
    uni_sorted = uni.sort_values("ws").reset_index(drop=False)
    for asset, sub in uni_sorted.groupby("asset"):
        ws_arr = sub.ws.values.astype("int64")
        prem = sub.premium_ws.values
        z = np.full(len(sub), np.nan)
        for i in range(len(sub)):
            ws_i = ws_arr[i]
            mask = (ws_arr < ws_i) & (ws_arr >= ws_i - win_s) & np.isfinite(prem)
            prior = prem[mask]
            if len(prior) >= 100:
                mu = float(prior.mean()); sd = float(prior.std())
                if sd > 0:
                    z[i] = (prem[i] - mu) / sd
        uni.loc[sub["index"].values, "premium_z_7d"] = z
    return uni


# ---------------------------------------------------------------------------
# Variant gating — returns gated subset with `signal` column ("UP"/"DOWN")
# ---------------------------------------------------------------------------

def gate_baseline(uni: pd.DataFrame, ret_col: str, day_thr_dict: dict) -> pd.DataFrame:
    df = uni.copy()
    df["abs_target"] = df[ret_col].abs()
    df["threshold"] = df.apply(
        lambda r: day_thr_dict.get((r.asset, r.tf, str(r.day.date())), float("nan")),
        axis=1,
    )
    g = df[(df.abs_target.notna()) & (df.threshold.notna()) &
           (df.abs_target >= df.threshold) & df[ret_col].notna()].copy()
    g["signal"] = g[ret_col].apply(lambda x: "UP" if x > 0 else "DOWN")
    return g


def apply_variant(uni: pd.DataFrame, variant: str) -> pd.DataFrame:
    """Returns gated subset with 'signal' column, filtered per variant."""
    # Always start by computing baseline q90 thresholds on bin_ret_2m
    thr_bin = compute_thresholds(uni)
    if variant == "B0":
        return gate_baseline(uni, "ret_2m", thr_bin)

    if variant.startswith("F"):
        gated = gate_baseline(uni, "ret_2m", thr_bin)
        sig_int = gated.signal.map({"UP": 1, "DOWN": -1})
        if variant == "F1":   # premium aligned with signal
            keep = (np.sign(gated.premium_ws) == sig_int) & gated.premium_ws.notna()
        elif variant == "F2": # premium magnitude > 5bp
            keep = gated.premium_ws.abs() > PREMIUM_5BP
        elif variant == "F3": # |z(premium,7d)| > 1.5
            keep = gated.premium_z_7d.abs() > Z_THRESHOLD
        elif variant == "F4": # premium velocity in signal direction
            keep = (gated.premium_d2m * sig_int) > 0
        elif variant == "F5": # cross-venue agreement
            keep = (np.sign(gated.ret_2m) == np.sign(gated.coin_ret_2m)) & gated.coin_ret_2m.notna()
        else:
            raise ValueError(f"unknown F variant {variant!r}")
        return gated[keep.fillna(False)].copy()

    if variant == "E1":  # ensemble gate
        df = uni.copy()
        df["ens_ret_2m"] = 0.5 * df.ret_2m + 0.5 * df.coin_ret_2m
        df_e = df.copy(); df_e["abs_ret_2m"] = df_e.ens_ret_2m.abs()
        thr_ens = compute_thresholds(df_e)
        return gate_baseline(df, "ens_ret_2m", thr_ens)

    if variant == "E2":  # coin-only gate
        df = uni.copy()
        df_e = df.copy(); df_e["abs_ret_2m"] = df_e.coin_ret_2m.abs()
        thr_coin = compute_thresholds(df_e)
        return gate_baseline(df, "coin_ret_2m", thr_coin)

    if variant == "E3":  # premium-as-signal
        df = uni.copy()
        df_e = df.copy(); df_e["abs_ret_2m"] = df_e.premium_ws.abs()
        thr_prem = compute_thresholds(df_e)
        return gate_baseline(df, "premium_ws", thr_prem)

    raise ValueError(f"unknown variant {variant!r}")


# ---------------------------------------------------------------------------
# Simulator (extends momo_full_universe_validation with SELL_V2 anchor=fire)
# ---------------------------------------------------------------------------

def simulate_with_policy(r, klines, books, policy: str) -> dict | None:
    """Returns {pnl, vwap_e, shares_e, usd_e, exit_reason, fired} or None."""
    asset = r["asset"]
    held = "Up" if r["signal"] == "UP" else "Down"
    other = "Down" if r["signal"] == "UP" else "Up"
    idx = books[asset]
    mid = r["condition_id"]

    fire_us = int(r["ws"] + FIRE_OFFSET_S) * 1_000_000

    entry = find_book(idx, mid, held, fire_us)
    if entry is None:
        return None
    ap_e, as_e, bp_e, bs_e, _ = entry
    ask0 = float(ap_e[0]) if math.isfinite(ap_e[0]) else float("nan")
    bid0 = float(bp_e[0]) if math.isfinite(bp_e[0]) else float("nan")
    if math.isfinite(ask0) and math.isfinite(bid0) and (ask0 - bid0) > SPREAD_FILTER[asset]:
        return None
    vwap_e, shares_e, usd_e, _, under = book_walk_fill(
        [float(x) for x in ap_e], [float(x) for x in as_e], NOTIONAL
    )
    if shares_e <= 0 or (under and usd_e < NOTIONAL * 0.5):
        return None

    won = (r["signal"] == "UP" and r["outcome"] == "Up") or \
          (r["signal"] == "DOWN" and r["outcome"] == "Down")

    def hold_pnl():
        if won:
            profit = shares_e * 1.0 - usd_e
            return profit - (profit * FEE if profit > 0 else 0.0)
        return -usd_e

    if policy == "HOLD":
        return dict(exit_reason="hold", vwap_e=vwap_e, shares_e=shares_e,
                    usd_e=usd_e, pnl=hold_pnl(), fired=False)

    # rev_bp anchor: HEDGE & SELL_V1 use close@ws; SELL_V2 uses close@fire
    if policy in ("HEDGE_5bp", "SELL_V1_5bp"):
        anchor_ts = int(r["ws"])
    elif policy == "SELL_V2_5bp":
        anchor_ts = int(r["ws"] + FIRE_OFFSET_S)
    else:
        raise ValueError(f"unknown policy {policy!r}")

    anchor = asof_strict(klines[asset], anchor_ts)
    if not math.isfinite(anchor) or anchor <= 0:
        return dict(exit_reason="hold_no_anchor", vwap_e=vwap_e, shares_e=shares_e,
                    usd_e=usd_e, pnl=hold_pnl(), fired=False)

    resolve_us = int(r["ws"] + r["window_s"] - 60) * 1_000_000
    triggered_at_us = None
    t_us = fire_us + TICK_S * 1_000_000
    while t_us <= resolve_us:
        a_now = asof_strict(klines[asset], t_us // 1_000_000)
        if math.isfinite(a_now):
            rev_bp = (a_now - anchor) / anchor * 1e4
            if (r["signal"] == "UP" and rev_bp <= -5) or \
               (r["signal"] == "DOWN" and rev_bp >= 5):
                triggered_at_us = t_us
                break
        t_us += TICK_S * 1_000_000

    if triggered_at_us is None:
        return dict(exit_reason="hold_no_trigger", vwap_e=vwap_e, shares_e=shares_e,
                    usd_e=usd_e, pnl=hold_pnl(), fired=False)

    if policy == "HEDGE_5bp":
        opp = find_book(idx, mid, other, triggered_at_us)
        if opp is None:
            return dict(exit_reason="hold_hedge_failed", vwap_e=vwap_e, shares_e=shares_e,
                        usd_e=usd_e, pnl=hold_pnl(), fired=False)
        ap_o, as_o, _, _, _ = opp
        top_ask = float(ap_o[0]) if math.isfinite(ap_o[0]) else float("nan")
        if not (math.isfinite(top_ask) and 0 < top_ask < 1):
            return dict(exit_reason="hold_hedge_failed", vwap_e=vwap_e, shares_e=shares_e,
                        usd_e=usd_e, pnl=hold_pnl(), fired=False)
        target_h_usd = shares_e * top_ask
        vwap_h, shares_h, usd_h, _, _ = book_walk_fill(
            [float(x) for x in ap_o], [float(x) for x in as_o], target_h_usd
        )
        if shares_h <= 0:
            return dict(exit_reason="hold_hedge_failed", vwap_e=vwap_e, shares_e=shares_e,
                        usd_e=usd_e, pnl=hold_pnl(), fired=False)
        held_g = shares_e * 1.0 if won else 0.0
        hedge_g = shares_h * 1.0 if not won else 0.0
        cost = usd_e + usd_h
        profit = (held_g + hedge_g) - cost
        fee = profit * FEE if profit > 0 else 0.0
        return dict(exit_reason="hedge", vwap_e=vwap_e, shares_e=shares_e,
                    usd_e=usd_e, pnl=profit - fee, fired=True)

    # SELL_V1 / SELL_V2 — both walk own bids, only anchor differs (already handled above)
    own = find_book(idx, mid, held, triggered_at_us)
    if own is None:
        return dict(exit_reason="hold_sell_failed", vwap_e=vwap_e, shares_e=shares_e,
                    usd_e=usd_e, pnl=hold_pnl(), fired=False)
    _, _, bp_o, bs_o, _ = own
    vwap_s, shares_s, gross_s = sell_at_bid_partial(bp_o, bs_o, shares_e)
    if shares_s <= 0:
        return dict(exit_reason="hold_sell_failed", vwap_e=vwap_e, shares_e=shares_e,
                    usd_e=usd_e, pnl=hold_pnl(), fired=False)
    remainder = shares_e - shares_s
    remainder_g = remainder * 1.0 if won else 0.0
    gross = gross_s + remainder_g
    profit = gross - usd_e
    fee = profit * FEE if profit > 0 else 0.0
    return dict(exit_reason=f"sell_{policy.split('_')[1].lower()}",
                vwap_e=vwap_e, shares_e=shares_e, usd_e=usd_e,
                pnl=profit - fee, fired=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=== Momo + Coinbase Add-Alpha ===\n")
    print("[1] Loading klines (binance/okx + coinbase)...")
    bin_klines = load_klines()
    coin_klines = load_coinbase_klines()

    print("[2] Loading universe...")
    uni = load_universe()
    uni["ret_2m"] = compute_ret_2m(uni, bin_klines)
    uni["abs_ret_2m"] = uni.ret_2m.abs()
    print(f"    universe: {len(uni)} markets ({uni.day.min().date()} → {uni.day.max().date()})")

    print("[3] Attaching coinbase features (premium, coin_ret, d2m, z_7d)...")
    uni = attach_coinbase_features(uni, bin_klines, coin_klines)
    print(f"    coin_ret_2m  finite: {uni.coin_ret_2m.notna().sum()}")
    print(f"    premium_ws   finite: {uni.premium_ws.notna().sum()}")
    print(f"    premium_d2m  finite: {uni.premium_d2m.notna().sum()}")
    print(f"    premium_z_7d finite: {uni.premium_z_7d.notna().sum()}")

    print("\n[4] Computing variant gates...")
    gated_per_variant: dict[str, pd.DataFrame] = {}
    for v in VARIANTS:
        g = apply_variant(uni, v)
        gated_per_variant[v] = g
        n_up = int((g.signal == "UP").sum())
        n_down = int((g.signal == "DOWN").sum())
        print(f"    {v:>3}: gated={len(g)} (UP={n_up}, DOWN={n_down})")

    # union of condition_ids across variants for L25 prefetch per asset
    print("\n[5] Loading L25 books per asset (one-pass per asset across all variants)...")
    rows_all = []
    for asset in ("BTC", "ETH", "SOL"):
        gated_mids = set()
        for v in VARIANTS:
            sub = gated_per_variant[v]
            gated_mids |= set(sub[sub.asset == asset].condition_id.unique())
        if not gated_mids:
            print(f"    {asset}: no gated mids, skip")
            continue
        print(f"    [{asset}] mids={len(gated_mids)}")
        books_a, _ = load_l25_for_asset(asset, gated_mids=gated_mids)
        if not books_a:
            print(f"    {asset}: no books loaded, skip")
            continue
        books = {asset: books_a}
        print(f"    [{asset}] simulating {len(VARIANTS)} variants × {len(POLICIES)} policies...")
        for v in VARIANTS:
            sub = gated_per_variant[v]
            sub = sub[sub.asset == asset]
            if sub.empty:
                continue
            for p in POLICIES:
                for r in sub.to_dict("records"):
                    res = simulate_with_policy(r, bin_klines, books, p)
                    if res is None:
                        continue
                    rows_all.append({
                        "variant": v, "policy": p,
                        "slug": r["slug"], "asset": asset, "tf": r["tf"],
                        "ws": int(r["ws"]), "day": str(r["day"].date()),
                        "signal": r["signal"], "outcome": r["outcome"],
                        "ret_2m": r["ret_2m"],
                        "premium_ws": r.get("premium_ws"),
                        "coin_ret_2m": r.get("coin_ret_2m"),
                        **res,
                    })
        del books_a, books
        print(f"    [{asset}] done — total per-trade rows so far: {len(rows_all)}")

    print(f"\n[6] {len(rows_all)} per-trade rows total — aggregating...")
    df = pd.DataFrame(rows_all)
    df.to_csv(OUT_DIR / "per_trade.csv", index=False)

    summary = df.groupby(["variant", "policy"]).agg(
        n=("pnl", "size"),
        n_fired=("fired", "sum"),
        fire_pct=("fired", lambda s: round(100 * s.sum() / max(len(s), 1), 1)),
        hit=("pnl", lambda s: round(100 * (s > 0).mean(), 2)),
        pnl_total=("pnl", lambda s: round(s.sum(), 2)),
        pnl_mean=("pnl", lambda s: round(s.mean(), 4)),
        avg_vwap=("vwap_e", "mean"),
    ).reset_index()
    summary.to_csv(OUT_DIR / "summary.csv", index=False)

    # Lift over baseline (B0 × matching policy)
    base = summary[summary.variant == "B0"].set_index("policy")
    lift_rows = []
    for v in VARIANTS:
        if v == "B0":
            continue
        for p in POLICIES:
            sub = summary[(summary.variant == v) & (summary.policy == p)]
            if sub.empty or p not in base.index:
                continue
            r = sub.iloc[0]
            b = base.loc[p]
            lift_rows.append({
                "variant": v, "policy": p,
                "n": int(r.n), "n_base": int(b.n),
                "n_pct_of_base": round(100 * r.n / max(b.n, 1), 1),
                "hit_pct": float(r.hit), "hit_base_pct": float(b.hit),
                "hit_lift_pp": round(r.hit - b.hit, 2),
                "pnl_total": float(r.pnl_total),
                "pnl_total_base": float(b.pnl_total),
                "pnl_total_lift": round(r.pnl_total - b.pnl_total, 2),
                "pnl_mean": float(r.pnl_mean),
                "pnl_mean_base": float(b.pnl_mean),
                "pnl_mean_lift": round(r.pnl_mean - b.pnl_mean, 4),
            })
    lift = pd.DataFrame(lift_rows)
    lift.to_csv(OUT_DIR / "lift.csv", index=False)

    print("\n=== Summary (variant × policy) ===")
    print(summary.to_string(index=False))
    print("\n=== Lift over B0 baseline (same policy) ===")
    if not lift.empty:
        print(lift.sort_values(["policy", "pnl_total_lift"],
                                  ascending=[True, False]).to_string(index=False))

    print("\n[7] Writing report...")
    write_report(summary, lift, gated_per_variant)
    print(f"    wrote {REPORT}")


def write_report(summary: pd.DataFrame, lift: pd.DataFrame, gated: dict):
    lines = [
        "# Momo + Coinbase Add-Alpha — does coinbase lift the winning baseline?",
        "_Generated: 2026-05-09_",
        "",
        "## Setup",
        "- Baseline (B0): canonical momo gate (|bin_ret_2m| ≥ rolling 14d q90, sign(bin_ret_2m) direction).",
        "- Reuses `momo_full_universe_validation.py` simulator + L25 cache (refresh_2026_05_06).",
        f"- Entry: $25 L25 ASK walk at fire_offset={FIRE_OFFSET_S}s.",
        "- Policies: HOLD / HEDGE_5bp / SELL_V1_5bp (anchor=close@ws) / SELL_V2_5bp (anchor=close@fire).",
        "",
        "## Coinbase variants",
        "- **B0** baseline (no coinbase)",
        "- **F1** filter: sign(premium@ws) == sign(signal)",
        f"- **F2** filter: |premium@ws| > {PREMIUM_5BP*1e4:.0f} bp",
        f"- **F3** filter: |z(premium, {Z_WINDOW_DAYS}d)| > {Z_THRESHOLD}",
        "- **F4** filter: (premium@ws+60 − premium@ws−60) × signal > 0",
        "- **F5** filter: sign(bin_ret_2m) == sign(coin_ret_2m)",
        "- **E1** ensemble gate: 0.5×bin_ret_2m + 0.5×coin_ret_2m",
        "- **E2** coinbase-only gate: coin_ret_2m (negative control)",
        "- **E3** premium-as-signal: |premium@ws| gate, sign(premium) direction",
        "",
        "## Gate coverage",
        "| Variant | n_gated |",
        "|---|---:|",
    ]
    for v in VARIANTS:
        lines.append(f"| {v} | {len(gated[v])} |")
    lines += ["", "## Headline (variant × policy)", "",
              summary.to_markdown(index=False) if not summary.empty else "_no rows_",
              "", "## Lift vs B0 baseline (same policy)", ""]
    if not lift.empty:
        lines.append(lift.sort_values(["policy", "pnl_total_lift"],
                                          ascending=[True, False]).to_markdown(index=False))
    else:
        lines.append("_no lift rows_")
    lines += ["", "## Verdict", ""]
    if not lift.empty:
        for policy, sub in lift.groupby("policy"):
            top = sub.sort_values("pnl_total_lift", ascending=False).iloc[0]
            sign = "+" if top.pnl_total_lift > 0 else ""
            lines.append(
                f"- **{policy}**: best variant `{top.variant}` "
                f"(Δpnl={sign}${top.pnl_total_lift:+.2f} vs ${top.pnl_total_base:+.2f} base, "
                f"n={int(top.n)} vs {int(top.n_base)}, hit Δ{top.hit_lift_pp:+.2f}pp)"
            )
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
