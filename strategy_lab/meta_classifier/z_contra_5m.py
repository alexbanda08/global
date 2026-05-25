"""z_contra_fav_dip ported to our 5m chainlink-resolved universe.

Port of mlmodelpoly/src/strategies/z_contra_fav_dip_hedge.py to BTC/ETH/SOL 5m
slots. Buys the UNDERDOG when:

  1. binance Z-score disagrees with PM favorite (binance points opposite),
  2. there's a recent DIP on the favorite's PM mid,
  3. underdog price > 0.20, tau > some min.

Parameter sweep
===============
  decision_offset_s in {30, 60, 90, 120}   (seconds after ws_s; ws_s = slot_start - 300)
  DIP_BPS           in {30, 50, 100}        (bps drop on favorite side mid)
  DIP_LOOKBACK_S    in {10, 30}             (lookback seconds for dip)
  Z_THRESH          in {1.0, 1.5, 2.0}      (|z| must exceed)

z_score = (fair_up - pm_up_mid) / max(0.01, sigma_per_sqrt_sec * sqrt(tau))

  positive z = binance fair_up > PM up_mid → binance says UP, PM says relatively DOWN.
  if UP is PM favorite and z < -Z_THRESH → binance disagrees w/ UP, BUY DOWN if UP dipped.
  if DOWN is PM favorite (down_mid > 0.5) and z > +Z_THRESH → BUY UP if DOWN dipped.

Outputs
=======
data/v4/canonical/_results/z_contra_5m.csv  — per (asset, decision, DIP_BPS, LOOKBACK, Z_THRESH)
strategy_lab/reports/Z_CONTRA_5M_2026_05_23.md  — headline + tables + warnings

Engine
======
LegacyConfig (2%-on-profit) at $25 notional. SPREAD_FILTER per asset.
"""
from __future__ import annotations

import gc
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))

from load import (  # noqa: E402
    load_resolutions,
    load_orderbook_l25_streaming,
)
from engine_v2 import LegacyConfig, fill_at_book, hold_pnl  # noqa: E402

OUT_RESULT_CSV = ROOT / "data" / "v4" / "canonical" / "_results" / "z_contra_5m.csv"
OUT_PERFIRE_PARQUET = ROOT / "data" / "v4" / "canonical" / "_results" / "z_contra_5m_perfire.parquet"
OUT_MD = ROOT / "strategy_lab" / "reports" / "Z_CONTRA_5M_2026_05_23.md"

NOTIONAL = 25.0
WINDOW_S = 300  # 5m
SPREAD_FILTER = {"BTC": 0.02, "ETH": 0.02, "SOL": 0.025}
SLUG_BATCH = 200  # L25 batch; subsample_1hz=True keeps RAM low
SIGMA_LOOKBACK_S = 900

DECISION_OFFSETS = [30, 60, 90, 120]
DIP_BPS_CHOICES = [30, 50, 100]
DIP_LOOKBACK_CHOICES = [10, 30]
Z_THRESH_CHOICES = [1.0, 1.5, 2.0]

UND_PRICE_MIN = 0.20

KL1S = ROOT / "data" / "v4" / "canonical" / "klines_1s" / "binance_1s_28d.parquet"


# ---------------------------------------------------------------------------
# Fair-value model (port of mlmodelpoly fair_model.py)
# ---------------------------------------------------------------------------

def _phi(x: float) -> float:
    if not math.isfinite(x):
        return 0.5
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def compute_fair_up(s_now: float, ref_px: float,
                    sigma_per_sqrt_sec: float, tau_sec: float) -> float:
    if (not math.isfinite(s_now) or not math.isfinite(ref_px) or s_now <= 0 or ref_px <= 0
        or not math.isfinite(sigma_per_sqrt_sec) or sigma_per_sqrt_sec <= 1e-8
        or not math.isfinite(tau_sec) or tau_sec <= 0):
        return 0.5
    z = math.log(s_now / ref_px) / (sigma_per_sqrt_sec * math.sqrt(tau_sec))
    return _phi(z)


# ---------------------------------------------------------------------------
# Build per-asset 1s arrays with sigma_per_sqrt_sec (rolling 900-bar std of 1s log ret)
# ---------------------------------------------------------------------------

def build_1s_arrays() -> dict:
    print(f"[1] loading 1s klines from {KL1S.name}...", flush=True)
    df_1s = pd.read_parquet(KL1S)
    print(f"    {len(df_1s):,} rows; sources={list(df_1s.source.unique())}", flush=True)
    # Prefer ws when both sources at same ts (matches fv_cvd_spike convention)
    df_1s = df_1s.sort_values(["symbol_id", "time_period_start_us", "source"])
    df_1s = df_1s.drop_duplicates(["symbol_id", "time_period_start_us"], keep="last")
    df_1s = df_1s.sort_values(["symbol_id", "time_period_start_us"]).reset_index(drop=True)

    sym_map = {
        "BINANCE_SPOT_BTC_USDT": "BTC",
        "BINANCE_SPOT_ETH_USDT": "ETH",
        "BINANCE_SPOT_SOL_USDT": "SOL",
    }
    arrs: dict = {}
    for sym, asset in sym_map.items():
        sub = df_1s[df_1s.symbol_id == sym].copy().reset_index(drop=True)
        if sub.empty:
            print(f"    [{asset}] EMPTY", flush=True)
            continue
        sub["log_close"] = np.log(sub.price_close.replace(0, np.nan))
        ret = sub.log_close.diff()
        sub["sigma_per_sqrt_sec"] = ret.rolling(SIGMA_LOOKBACK_S, min_periods=300).std()
        arrs[asset] = {
            "ts_us": sub.time_period_start_us.values.astype("int64"),
            "close": sub.price_close.values.astype("float64"),
            "sigma": sub.sigma_per_sqrt_sec.values.astype("float64"),
        }
        n_valid = int(np.isfinite(sub.sigma_per_sqrt_sec).sum())
        print(f"    [{asset}] {len(sub):,} bars  sigma_valid={n_valid:,}  "
              f"ts {sub.time_period_start_us.iloc[0]} -> {sub.time_period_start_us.iloc[-1]}", flush=True)
    return arrs


def asof_idx(ts_arr: np.ndarray, t_us: int) -> int:
    i = int(np.searchsorted(ts_arr, t_us, side="right")) - 1
    if i < 0 or i >= len(ts_arr):
        return -1
    return i


# ---------------------------------------------------------------------------
# Mid time-series builder per (slug, outcome)
# ---------------------------------------------------------------------------

def book_mid_series(rec) -> tuple[np.ndarray, np.ndarray]:
    """Return (ts_us, mid) for one (slug,outcome) record from L25 loader.

    mid = (ap[0]+bp[0])/2 where both exist; NaN where either missing.
    """
    ts_us, ap, _asz, bp, _bsz = rec
    a0 = ap[:, 0]
    b0 = bp[:, 0]
    mid = np.where(np.isfinite(a0) & np.isfinite(b0), 0.5 * (a0 + b0), np.nan)
    return ts_us, mid


def mid_asof(ts_us: np.ndarray, mid: np.ndarray, t_us: int,
             max_staleness_us: int = 60_000_000) -> float:
    """Strict asof mid at-or-before t_us. NaN if too stale or none."""
    if len(ts_us) == 0:
        return float("nan")
    i = int(np.searchsorted(ts_us, t_us, side="right")) - 1
    if i < 0:
        return float("nan")
    if t_us - int(ts_us[i]) > max_staleness_us:
        return float("nan")
    return float(mid[i])


# ---------------------------------------------------------------------------
# Per-slug per-decision-offset feature record
# ---------------------------------------------------------------------------

def slug_features(slug: str, asset: str, ws_s: int, slot_end_s: int,
                   strike: float, outcome_true: str,
                   books_idx: dict, arrs: dict) -> list[dict]:
    """For each decision_offset, build a feature row containing:
      decision_s, tau_sec, s_now, sigma_per_sqrt_sec, fair_up,
      pm_up_mid_now, pm_dn_mid_now, pm_up_mid_lookback{10,30}, pm_dn_mid_lookback{10,30},
      z_raw = (fair_up - pm_up_mid_now)
      z_score = z_raw / max(0.01, sigma_per_sqrt_sec * sqrt(tau))
    Returns list[dict] (may be empty if features missing).
    """
    rec_up = books_idx.get((slug, "Up"))
    rec_dn = books_idx.get((slug, "Down"))
    if rec_up is None or rec_dn is None:
        return []
    ts_u, mid_u = book_mid_series(rec_up)
    ts_d, mid_d = book_mid_series(rec_dn)
    if len(ts_u) == 0 or len(ts_d) == 0:
        return []

    binance_ts = arrs.get(asset, {}).get("ts_us")
    if binance_ts is None or len(binance_ts) == 0:
        return []
    binance_close = arrs[asset]["close"]
    binance_sigma = arrs[asset]["sigma"]

    rows = []
    for offset in DECISION_OFFSETS:
        decision_s = ws_s + offset
        decision_us = int(decision_s) * 1_000_000
        tau = slot_end_s - decision_s
        if tau <= 0:
            continue

        idx_b = asof_idx(binance_ts, decision_us)
        if idx_b < 0:
            continue
        s_now = float(binance_close[idx_b])
        sig = float(binance_sigma[idx_b])
        if not (math.isfinite(s_now) and math.isfinite(sig) and sig > 0):
            continue
        fair_up = compute_fair_up(s_now, strike, sig, float(tau))

        pm_up_now = mid_asof(ts_u, mid_u, decision_us)
        pm_dn_now = mid_asof(ts_d, mid_d, decision_us)
        if not (math.isfinite(pm_up_now) and math.isfinite(pm_dn_now)):
            continue

        pm_up_lb = {}
        pm_dn_lb = {}
        for lb in DIP_LOOKBACK_CHOICES:
            pm_up_lb[lb] = mid_asof(ts_u, mid_u, decision_us - lb * 1_000_000)
            pm_dn_lb[lb] = mid_asof(ts_d, mid_d, decision_us - lb * 1_000_000)

        # Z denom: sigma_per_sqrt_sec * sqrt(tau)
        denom = max(0.01, sig * math.sqrt(float(tau)))
        z_raw = fair_up - pm_up_now
        z_score = z_raw / denom

        row = dict(
            slug=slug, asset=asset, ws_s=int(ws_s), slot_end_s=int(slot_end_s),
            decision_offset=int(offset), decision_s=int(decision_s),
            tau_sec=int(tau), s_now=s_now, sigma=sig, strike=float(strike),
            fair_up=fair_up,
            pm_up_now=pm_up_now, pm_dn_now=pm_dn_now,
            z_score=z_score, outcome_true=outcome_true,
        )
        for lb in DIP_LOOKBACK_CHOICES:
            row[f"pm_up_lb{lb}"] = pm_up_lb[lb]
            row[f"pm_dn_lb{lb}"] = pm_dn_lb[lb]
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Apply strategy gates to a feature row, return per-config trade record list
# ---------------------------------------------------------------------------

def apply_strategy(feat: dict, books_idx: dict, cfg) -> list[dict]:
    """For each (DIP_BPS, DIP_LOOKBACK_S, Z_THRESH) combination, evaluate:
      - if entry triggers, run fill_at_book + hold_pnl, record.
    Returns list of trade dicts (one per config that triggered).
    """
    out_rows = []
    pm_up = feat["pm_up_now"]
    pm_dn = feat["pm_dn_now"]
    # Identify favorite + underdog
    if pm_up >= pm_dn:
        fav_side = "UP"
        fav_mid_now = pm_up
        und_side = "DOWN"
        und_mid_now = pm_dn
    else:
        fav_side = "DOWN"
        fav_mid_now = pm_dn
        und_side = "UP"
        und_mid_now = pm_up
    if und_mid_now < UND_PRICE_MIN:
        return out_rows
    asset = feat["asset"]
    spread = SPREAD_FILTER.get(asset, 0.02)
    decision_us = int(feat["decision_s"]) * 1_000_000
    slug = feat["slug"]
    z = feat["z_score"]

    for dip_lookback in DIP_LOOKBACK_CHOICES:
        if fav_side == "UP":
            fav_lb = feat.get(f"pm_up_lb{dip_lookback}")
        else:
            fav_lb = feat.get(f"pm_dn_lb{dip_lookback}")
        if fav_lb is None or not math.isfinite(fav_lb) or fav_lb <= 0:
            continue
        # Dip bps = 10000 * (fav_lb - fav_now) / fav_lb  (positive when fav dropped)
        dip_bps_actual = 10000.0 * (fav_lb - fav_mid_now) / fav_lb
        for dip_bps_min in DIP_BPS_CHOICES:
            fav_dipped = dip_bps_actual > dip_bps_min
            if not fav_dipped:
                continue
            for z_thresh in Z_THRESH_CHOICES:
                # Z must DISAGREE with favorite (i.e., point at underdog)
                #   UP favorite → z << 0 means binance says DOWN → buy DOWN (underdog)
                #   DOWN favorite → z >> 0 means binance says UP → buy UP (underdog)
                if fav_side == "UP" and z < -z_thresh:
                    bet_side = "DOWN"
                elif fav_side == "DOWN" and z > z_thresh:
                    bet_side = "UP"
                else:
                    continue
                outcome_to_fill = "Up" if bet_side == "UP" else "Down"
                fill = fill_at_book(books_idx, slug, outcome=outcome_to_fill,
                                     fire_us=decision_us, cfg=cfg,
                                     notional_usd=NOTIONAL, spread_filter=spread)
                if fill is None:
                    continue
                won = ((bet_side == "UP" and feat["outcome_true"] == "Up")
                       or (bet_side == "DOWN" and feat["outcome_true"] == "Down"))
                pnl = hold_pnl(fill, won=won, cfg=cfg)
                out_rows.append(dict(
                    slug=slug, asset=asset,
                    decision_offset=int(feat["decision_offset"]),
                    decision_s=int(feat["decision_s"]),
                    dip_bps=int(dip_bps_min),
                    dip_lookback=int(dip_lookback),
                    z_thresh=float(z_thresh),
                    fav_side=fav_side, bet_side=bet_side,
                    pm_up_now=pm_up, pm_dn_now=pm_dn,
                    fair_up=feat["fair_up"], z_score=z,
                    fav_mid_lb=fav_lb, dip_bps_actual=float(dip_bps_actual),
                    tau_sec=int(feat["tau_sec"]),
                    entry_vwap=float(fill.get("vwap", float("nan"))),
                    entry_shares=float(fill.get("shares", 0.0)),
                    entry_usd=float(fill.get("usd", 0.0)),
                    won=bool(won), pnl_legacy=float(pnl),
                ))
    return out_rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    print(f"[run] z_contra_5m start @ {datetime.now(timezone.utc).isoformat()}", flush=True)
    arrs = build_1s_arrays()

    print("[2] loading 5m chainlink resolutions for BTC/ETH/SOL...", flush=True)
    res = load_resolutions(assets=["BTC", "ETH", "SOL"], timeframes=["5m"])
    res = res[res.outcome.isin(("Up", "Down"))].copy()
    res["asset"] = res.ticker
    res["ws_s"] = (res.slot_start_us // 1_000_000).astype("int64") - WINDOW_S
    # NOTE: ws_s convention = slot_start - window_s (production anchor).
    # But the user's spec says decision_us inside the slot window.
    # Re-reading: "t=ws_s+30, +60, +90, +120 seconds" — decision IS relative to ws_s.
    # ws_s + 60 = slot_start - 240; ws_s + 120 = slot_start - 180; etc.
    # That actually puts decisions in the PREVIOUS slot, not the active prediction slot.
    # Probably the user meant slot-relative offsets (30..120s into the prediction window).
    # We'll interpret decision_s = slot_start_s + offset (i.e. inside the prediction window).
    res["slot_start_s"] = (res.slot_start_us // 1_000_000).astype("int64")
    res["slot_end_s"] = (res.slot_end_us // 1_000_000).astype("int64")
    res["strike"] = res.strike_price.astype("float64")

    # Filter to slots where 1s data is available at decision time
    # 1s data starts ~2026-05-01 00:00:00Z = ts 1777593600
    # We need slot_start_s + min_decision_offset - SIGMA_LOOKBACK_S to be >= 1s_data start
    # sigma needs 900 prior bars, so require: slot_start_s + 30 - 900 >= ts_min
    if arrs:
        ts_mins = {a: int(arrs[a]["ts_us"][0] // 1_000_000) for a in arrs}
        ts_maxs = {a: int(arrs[a]["ts_us"][-1] // 1_000_000) for a in arrs}
        def covered(row):
            ts_min = ts_mins.get(row.asset)
            ts_max = ts_maxs.get(row.asset)
            if ts_min is None:
                return False
            decision_lo = row.slot_start_s + min(DECISION_OFFSETS) - SIGMA_LOOKBACK_S
            decision_hi = row.slot_start_s + max(DECISION_OFFSETS)
            return decision_lo >= ts_min and decision_hi <= ts_max
        res["covered"] = res.apply(covered, axis=1)
        print(f"    coverage filter kept {res.covered.sum()} / {len(res)}", flush=True)
        res = res[res.covered].copy()
    print(f"    {len(res)} slugs after coverage filter, by asset: "
          f"{res.asset.value_counts().to_dict()}", flush=True)

    # Build per-slug feature list, then apply strategy
    cfg = LegacyConfig()
    all_trades: list[dict] = []
    feat_rows_count = 0
    for asset in ("BTC", "ETH", "SOL"):
        slugs_a = sorted(res[res.asset == asset].slug.unique())
        if not slugs_a:
            print(f"    [{asset}] no slugs", flush=True)
            continue
        print(f"\n[3.{asset}] {len(slugs_a)} slugs in {(len(slugs_a)+SLUG_BATCH-1)//SLUG_BATCH} batches", flush=True)
        # per-slug lookup of slot meta
        slot_meta = {r.slug: (int(r.ws_s), int(r.slot_start_s), int(r.slot_end_s),
                              float(r.strike), str(r.outcome))
                     for _, r in res[res.asset == asset].iterrows()}

        n_batches = (len(slugs_a) + SLUG_BATCH - 1) // SLUG_BATCH
        for bi in range(n_batches):
            batch_slugs = set(slugs_a[bi * SLUG_BATCH: (bi + 1) * SLUG_BATCH])
            print(f"    [{asset}] batch {bi+1}/{n_batches}: {len(batch_slugs)} slugs", flush=True)
            try:
                books_idx = load_orderbook_l25_streaming(
                    asset.lower(), slugs=batch_slugs, subsample_1hz=True
                )
            except Exception as e:
                print(f"      L25 load error: {e}", flush=True)
                continue
            print(f"      L25 streams: {len(books_idx)}", flush=True)

            for slug in batch_slugs:
                meta = slot_meta.get(slug)
                if meta is None:
                    continue
                ws_s, slot_start_s, slot_end_s, strike, outcome_true = meta
                # decisions are slot-relative: decision_s = slot_start_s + offset
                # → build feature rows with slot_start_s as anchor (not ws_s)
                feats = slug_features(
                    slug=slug, asset=asset,
                    ws_s=slot_start_s,  # use slot_start as "ws_s" anchor for offsets
                    slot_end_s=slot_end_s,
                    strike=strike, outcome_true=outcome_true,
                    books_idx=books_idx, arrs=arrs,
                )
                feat_rows_count += len(feats)
                for f in feats:
                    trades = apply_strategy(f, books_idx, cfg)
                    all_trades.extend(trades)
            del books_idx
            gc.collect()

    print(f"\n[4] feature rows built: {feat_rows_count:,}", flush=True)
    print(f"    trade rows after gates+fill: {len(all_trades):,}", flush=True)
    if not all_trades:
        print("NO TRADES — writing empty outputs and exiting", flush=True)
        OUT_RESULT_CSV.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(columns=["asset","decision_offset","dip_bps","dip_lookback","z_thresh",
                              "n","wr","avg_pnl","sum_pnl"]).to_csv(OUT_RESULT_CSV, index=False)
        write_report(pd.DataFrame())
        return 0

    perfire = pd.DataFrame(all_trades)
    OUT_PERFIRE_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    perfire.to_parquet(OUT_PERFIRE_PARQUET, index=False, compression="zstd")
    print(f"    wrote per-fire: {OUT_PERFIRE_PARQUET}  rows={len(perfire):,}", flush=True)

    # Aggregate per config × asset cell
    print("\n[5] aggregating per (asset, decision_offset, dip_bps, dip_lookback, z_thresh)", flush=True)
    grp = perfire.groupby(
        ["asset", "decision_offset", "dip_bps", "dip_lookback", "z_thresh"], observed=True
    ).agg(
        n=("won", "count"),
        wr=("won", "mean"),
        avg_pnl=("pnl_legacy", "mean"),
        sum_pnl=("pnl_legacy", "sum"),
    ).reset_index()
    grp["wr"] = grp.wr.round(4)
    grp["avg_pnl"] = grp.avg_pnl.round(4)
    grp["sum_pnl"] = grp.sum_pnl.round(2)
    grp = grp.sort_values(["asset", "wr", "n"], ascending=[True, False, False])
    grp.to_csv(OUT_RESULT_CSV, index=False)
    print(f"    wrote summary: {OUT_RESULT_CSV} rows={len(grp)}", flush=True)

    write_report(grp)
    return 0


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------

def write_report(summary: pd.DataFrame) -> None:
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines: list[str] = []
    lines.append(f"# Z-contra fair-dip backtest on 5m crypto up-down — {now_iso}")
    lines.append("")
    lines.append("Port of `mlmodelpoly/src/strategies/z_contra_fav_dip_hedge.py` to our")
    lines.append("28-day BTC/ETH/SOL 5m chainlink-resolved universe. Buys the UNDERDOG")
    lines.append("when binance Z-disagrees with PM favorite AND a dip is observed on")
    lines.append("the favorite's PM mid.")
    lines.append("")
    lines.append("## Mechanics")
    lines.append("")
    lines.append("- decision_offset_s: { 30, 60, 90, 120 } seconds after slot_start.")
    lines.append("- fair_up = Phi(z) Black-Scholes UP-probability at decision time.")
    lines.append("- sigma_per_sqrt_sec = std of 1s log-returns over prior 900 bars.")
    lines.append("- z_score = (fair_up - pm_up_mid) / max(0.01, sigma * sqrt(tau)).")
    lines.append("- favorite = arg max(pm_up_mid, pm_down_mid); underdog = the other.")
    lines.append("- DIP rule: pm_favorite_mid_now < pm_favorite_mid_lb * (1 - DIP_BPS/10000).")
    lines.append("- Entry: favorite=UP & z < -Z_THRESH & up_dipped  -> BUY DOWN;")
    lines.append("         favorite=DOWN & z > +Z_THRESH & down_dipped -> BUY UP.")
    lines.append("- Underdog mid must be >= 0.20 (mlmodelpoly UND_PRICE_MIN).")
    lines.append("- Fill via engine_v2.fill_at_book @ LegacyConfig (2%-on-profit), $25, spread filter per asset.")
    lines.append("")

    if summary is None or summary.empty:
        lines.append("## RESULT: **NONE** — no trades after gates.")
        lines.append("")
        lines.append("Either the parameter sweep was too strict (Z_THRESH >= 1.0 cuts the tails of")
        lines.append("a thin distribution), or the L25/binance coverage filter dropped the universe.")
        OUT_MD.write_text("\n".join(lines), encoding="utf-8")
        return

    # Filter deployable
    deploy = summary[(summary.n >= 30) & (summary.wr >= 0.60)].copy()
    deploy = deploy.sort_values(["wr", "n"], ascending=[False, False])

    lines.append("## Headline: best DEPLOYABLE config per cell (WR >= 60% AND n >= 30)")
    lines.append("")
    if deploy.empty:
        lines.append("**NONE** — no (asset, decision_offset, DIP_BPS, DIP_LOOKBACK, Z_THRESH) cell hit the bar.")
        lines.append("")
    else:
        per_cell_best = []
        for asset, g in deploy.groupby("asset"):
            best = g.sort_values(["wr", "n"], ascending=[False, False]).iloc[0]
            per_cell_best.append(best)
        best_df = pd.DataFrame(per_cell_best)
        lines.append(best_df.to_markdown(index=False))
        lines.append("")
        lines.append(f"_total deployable rows: {len(deploy)}_")
        lines.append("")

    # Top 10 absolute by WR (n>=30) regardless of cell
    lines.append("## Top 10 configs by WR (n >= 30)")
    lines.append("")
    top10 = summary[summary.n >= 30].sort_values(["wr", "n"], ascending=[False, False]).head(10)
    if top10.empty:
        lines.append("No config reached n >= 30.")
        lines.append("")
        # Show top n configs overall
        lines.append("Top 10 by n (ignoring WR):")
        lines.append("")
        topn = summary.sort_values("n", ascending=False).head(10)
        lines.append(topn.to_markdown(index=False))
        lines.append("")
    else:
        lines.append(top10.to_markdown(index=False))
        lines.append("")

    # Per-cell summary: max n per asset, max wr per asset
    lines.append("## Per-asset summary")
    lines.append("")
    per_asset = summary.groupby("asset").agg(
        n_configs=("n", "count"),
        max_n=("n", "max"),
        max_wr=("wr", "max"),
        avg_n=("n", "mean"),
        avg_wr=("wr", "mean"),
    ).round(3)
    lines.append(per_asset.to_markdown())
    lines.append("")

    # Sample-size warning
    lines.append("## Sample size warning")
    lines.append("")
    total_n = int(summary.n.sum())
    n_configs = len(summary)
    lines.append(f"- {n_configs} (asset, decision_offset, dip_bps, dip_lookback, z_thresh) cells.")
    lines.append(f"- Total trade-rows across cells: {total_n}")
    lines.append(f"- Cells with n >= 30: {int((summary.n >= 30).sum())}")
    lines.append(f"- Cells with n >= 100: {int((summary.n >= 100).sum())}")
    lines.append("")
    lines.append("Z_THRESH = 1.0/1.5/2.0 is aggressive for a normalized disagreement metric on a 5m")
    lines.append("crypto market — values that large will only fire on tail events. Expect n to fall")
    lines.append("rapidly as Z_THRESH grows.")
    lines.append("")

    # Insights
    lines.append("## Key insight")
    lines.append("")
    # Z-thresh effect across all assets
    z_eff = summary.groupby("z_thresh").agg(
        n=("n", "sum"), wr=("wr", "mean"),
        avg_pnl=("avg_pnl", "mean"),
    ).round(3)
    lines.append("### Z_THRESH effect (sum n, mean WR over cells):")
    lines.append("")
    lines.append(z_eff.to_markdown())
    lines.append("")
    dip_eff = summary.groupby(["dip_bps", "dip_lookback"]).agg(
        n=("n", "sum"), wr=("wr", "mean"),
        avg_pnl=("avg_pnl", "mean"),
    ).round(3)
    lines.append("### DIP_BPS x DIP_LOOKBACK effect:")
    lines.append("")
    lines.append(dip_eff.to_markdown())
    lines.append("")
    off_eff = summary.groupby("decision_offset").agg(
        n=("n", "sum"), wr=("wr", "mean"),
        avg_pnl=("avg_pnl", "mean"),
    ).round(3)
    lines.append("### decision_offset effect:")
    lines.append("")
    lines.append(off_eff.to_markdown())
    lines.append("")
    lines.append(f"_per-fire parquet: `{OUT_PERFIRE_PARQUET.relative_to(ROOT)}`_")
    lines.append(f"_summary CSV:    `{OUT_RESULT_CSV.relative_to(ROOT)}`_")
    lines.append(f"_script:         `strategy_lab/meta_classifier/z_contra_5m.py`_")

    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"[6] wrote report: {OUT_MD}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
