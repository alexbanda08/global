"""BTC -> ETH/SOL lead-lag strategy on 5m chainlink markets.

For each ETH 5m slug (and SOL 5m slug separately):
  For each fire offset_s in {30, 60, 90}:
    t = slot_start + offset_s
    btc_ret_30s = 10000 * log(BTC@t / BTC@(t-30s))
    btc_ret_60s = 10000 * log(BTC@t / BTC@(t-60s))
    btc_cvd_30s = sum_{t-30s..t}(2*taker_buy_BTC - vol_BTC)
    asset_ret_30s_back = same direction back-window on ETH/SOL

V1: |btc_ret_30s| > THR_BPS -> bet WITH btc direction
V2: |btc_ret_30s| > THR_BPS AND sign(btc_cvd_30s) == sign(btc_ret_30s) -> bet WITH
V3: |btc_ret_30s| > THR_BPS AND |asset_ret_30s_back| < 10 -> bet WITH (catch-up)

Holds to slot close. Uses engine_v2.LegacyConfig (production-equivalent fees).

Outputs:
  data/v4/canonical/_results/btc_lead_lag_5m.csv
  strategy_lab/reports/BTC_LEAD_LAG_5M_2026_05_23.md
"""
from __future__ import annotations

import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))

from load import load_resolutions, load_orderbook_l25_streaming  # noqa: E402
from engine_v2 import LegacyConfig, fill_at_book, hold_pnl  # noqa: E402

KL1S = ROOT / "data" / "v4" / "canonical" / "klines_1s" / "binance_1s_28d.parquet"
OUT_CSV = ROOT / "data" / "v4" / "canonical" / "_results" / "btc_lead_lag_5m.csv"
OUT_PT = ROOT / "data" / "v4" / "canonical" / "_results" / "btc_lead_lag_5m_per_fire.parquet"
OUT_MD = ROOT / "strategy_lab" / "reports" / "BTC_LEAD_LAG_5M_2026_05_23.md"
S1_PT = ROOT / "data" / "v4" / "canonical" / "_results" / "vwap_continuation_5m_per_fire.parquet"

FIRE_OFFSETS_S = (30, 60, 90)
THRESHES_BPS = (10, 20, 30, 50)
SLOT_WINDOW_S = 300
SPREAD_FILTER = {"BTC": 0.02, "ETH": 0.02, "SOL": 0.025}

SYM_MAP = {
    "BINANCE_SPOT_BTC_USDT": "BTC",
    "BINANCE_SPOT_ETH_USDT": "ETH",
    "BINANCE_SPOT_SOL_USDT": "SOL",
}


def asof_idx(ts: np.ndarray, target_us: int) -> int:
    i = int(np.searchsorted(ts, target_us, side="right")) - 1
    if i < 0 or i >= len(ts):
        return -1
    return i


def load_per_asset() -> dict:
    df = pd.read_parquet(KL1S)
    df = df.sort_values(["symbol_id", "time_period_start_us", "source"])
    df = df.drop_duplicates(["symbol_id", "time_period_start_us"], keep="last")
    df["asset"] = df["symbol_id"].map(SYM_MAP)
    out = {}
    for asset in ("BTC", "ETH", "SOL"):
        sub = df[df.asset == asset].copy().sort_values("time_period_start_us").reset_index(drop=True)
        ts = sub.time_period_start_us.values.astype("int64")
        cl = sub.price_close.values.astype("float64")
        vol = sub.volume_traded.fillna(0).values.astype("float64")
        tbb = sub.taker_buy_base.fillna(0).values.astype("float64")
        cvd_delta = 2.0 * tbb - vol  # per-second taker imbalance in base units
        out[asset] = {"ts": ts, "cl": cl, "vol": vol, "cvd": cvd_delta}
        print(f"  {asset}: {len(ts):,} 1s rows")
    return out


def ret_bps(px_now: float, px_then: float) -> float:
    if not (math.isfinite(px_now) and math.isfinite(px_then) and px_now > 0 and px_then > 0):
        return float("nan")
    return 10_000.0 * math.log(px_now / px_then)


def cvd_window_sum(arr: dict, t_us: int, window_s: int) -> float:
    ts = arr["ts"]
    cvd = arr["cvd"]
    i_end = asof_idx(ts, t_us)
    i_start = asof_idx(ts, t_us - window_s * 1_000_000)
    if i_end < 0 or i_start < 0 or i_end <= i_start:
        return float("nan")
    return float(cvd[i_start + 1 : i_end + 1].sum())


def main() -> int:
    print("[1] loading 1s data...")
    arrs = load_per_asset()
    btc = arrs["BTC"]
    min_ts = min(arrs[a]["ts"][0] for a in arrs)
    max_ts = max(arrs[a]["ts"][-1] for a in arrs)

    print("[2] loading 5m chainlink resolutions (ETH + SOL only)...")
    res = load_resolutions()
    res = res.rename(columns={"ticker": "asset", "timeframe": "tf"})
    res = res[(res.asset.isin(("ETH", "SOL"))) & (res.tf == "5m")].copy()
    res = res[(res.slot_start_us >= min_ts) & (res.slot_start_us <= max_ts)].copy()
    res["slot_start_s"] = (res.slot_start_us // 1_000_000).astype("int64")
    res["slot_end_s"] = (res.slot_end_us // 1_000_000).astype("int64")
    print(f"    {len(res):,} ETH+SOL 5m slugs (ETH={len(res[res.asset=='ETH'])} SOL={len(res[res.asset=='SOL'])})")

    print("[3] generating candidate fires per (slug, offset)...")
    rows = []
    for _, r in res.iterrows():
        asset = str(r.asset)
        slot_start_s = int(r.slot_start_s)
        slot_end_s = int(r.slot_end_s)
        outcome = str(r.outcome)
        slug = r.slug
        a = arrs[asset]
        for off in FIRE_OFFSETS_S:
            fire_s = slot_start_s + off
            if fire_s >= slot_end_s:
                continue
            fire_us = fire_s * 1_000_000
            # BTC features at fire time
            i_btc = asof_idx(btc["ts"], fire_us)
            i_btc_m30 = asof_idx(btc["ts"], fire_us - 30 * 1_000_000)
            i_btc_m60 = asof_idx(btc["ts"], fire_us - 60 * 1_000_000)
            if i_btc < 0 or i_btc_m30 < 0 or i_btc_m60 < 0:
                continue
            btc_30 = ret_bps(btc["cl"][i_btc], btc["cl"][i_btc_m30])
            btc_60 = ret_bps(btc["cl"][i_btc], btc["cl"][i_btc_m60])
            btc_cvd_30 = cvd_window_sum(btc, fire_us, 30)
            # asset features (back-window for catch-up rule)
            i_a = asof_idx(a["ts"], fire_us)
            i_a_m30 = asof_idx(a["ts"], fire_us - 30 * 1_000_000)
            if i_a < 0 or i_a_m30 < 0:
                continue
            asset_30_back = ret_bps(a["cl"][i_a], a["cl"][i_a_m30])
            if not (math.isfinite(btc_30) and math.isfinite(btc_60)):
                continue
            rows.append((slug, asset, fire_s, fire_us, off,
                         btc_30, btc_60, btc_cvd_30, asset_30_back,
                         outcome, slot_end_s - fire_s))
    cands = pd.DataFrame(rows, columns=[
        "slug", "asset", "fire_s", "fire_us", "fire_offset_s",
        "btc_ret_30s", "btc_ret_60s", "btc_cvd_30s", "asset_ret_30s_back",
        "outcome", "tau_sec",
    ])
    print(f"    {len(cands):,} fire candidates")

    # Filter to anything where |btc_30| >= 10 (smallest THR considered) — saves work
    cands = cands[cands.btc_ret_30s.abs() >= 10].copy()
    print(f"    {len(cands):,} after |btc_ret_30s|>=10bps prefilter")

    # Determine direction
    cands["direction"] = np.where(cands.btc_ret_30s > 0, "UP", "DOWN")
    cands["abs_btc_30s"] = cands.btc_ret_30s.abs()
    cands["btc_dir_sign"] = np.where(cands.btc_ret_30s > 0, 1, -1)
    cands["cvd_dir_sign"] = np.where(cands.btc_cvd_30s > 0, 1, np.where(cands.btc_cvd_30s < 0, -1, 0))
    cands["cvd_confirms"] = cands.btc_dir_sign == cands.cvd_dir_sign
    cands["asset_quiet"] = cands.asset_ret_30s_back.abs() < 10

    print(f"\n    fires by asset/dir/offset:")
    print(cands.groupby(["asset", "direction", "fire_offset_s"]).size().to_string())

    # Load L25 books per asset
    print("\n[4] loading L25 books (1Hz subsample)...")
    books_idx: dict = {}
    for asset in ("ETH", "SOL"):
        slugs_asset = set(cands[cands.asset == asset]["slug"].unique())
        if not slugs_asset:
            continue
        print(f"    {asset}: loading {len(slugs_asset):,} slugs...")
        try:
            ab = load_orderbook_l25_streaming(asset, slugs=slugs_asset, subsample_1hz=True)
            books_idx.update(ab)
            print(f"      loaded {len(ab):,} (slug, outcome) keys")
        except Exception as e:
            print(f"      [ERROR] {asset}: {e}")
    print(f"    total books_idx keys: {len(books_idx):,}")

    # Fill via engine_v2.LegacyConfig
    print("\n[5] running L25 fills via LegacyConfig...")
    cfg = LegacyConfig()
    entry_vwap = np.full(len(cands), np.nan)
    pnl_legacy = np.full(len(cands), np.nan)
    won_arr = np.zeros(len(cands), dtype=bool)
    cands = cands.reset_index(drop=True)
    n_filled = 0
    for idx, r in cands.iterrows():
        outcome_to_fill = "Up" if r.direction == "UP" else "Down"
        try:
            fill = fill_at_book(
                books_idx, r.slug, outcome_to_fill, int(r.fire_us),
                cfg=cfg, spread_filter=SPREAD_FILTER[r.asset],
            )
        except Exception:
            fill = None
        if fill is None:
            continue
        won = (r.outcome == "Up") if r.direction == "UP" else (r.outcome == "Down")
        pnl = hold_pnl(fill, won=won, cfg=cfg)
        entry_vwap[idx] = float(fill["vwap"])
        pnl_legacy[idx] = float(pnl)
        won_arr[idx] = bool(won)
        n_filled += 1
        if (idx + 1) % 5000 == 0:
            print(f"    progress: {idx+1}/{len(cands)}  filled so far: {n_filled}")
    cands["entry_vwap"] = entry_vwap
    cands["pnl_legacy_usd"] = pnl_legacy
    cands["won"] = won_arr
    filled = cands[cands.pnl_legacy_usd.notna()].copy()
    print(f"    filled: {len(filled):,} / {len(cands):,}")

    OUT_PT.parent.mkdir(parents=True, exist_ok=True)
    filled.to_parquet(OUT_PT, index=False, compression="zstd")
    print(f"    wrote {OUT_PT}")

    # Aggregate per variant × asset × offset × threshold
    print("\n[6] aggregating per variant × asset × offset × thr...")
    agg_rows = []
    for thr in THRESHES_BPS:
        for variant in ("V1", "V2", "V3"):
            for asset in ("ETH", "SOL"):
                for off in FIRE_OFFSETS_S:
                    sub = filled[(filled.asset == asset)
                                 & (filled.fire_offset_s == off)
                                 & (filled.abs_btc_30s >= thr)].copy()
                    if variant == "V2":
                        sub = sub[sub.cvd_confirms]
                    elif variant == "V3":
                        sub = sub[sub.asset_quiet]
                    if len(sub) == 0:
                        continue
                    agg_rows.append({
                        "variant": variant,
                        "asset": asset,
                        "fire_offset_s": off,
                        "thr_bps": thr,
                        "n": int(len(sub)),
                        "wr": float(sub.won.mean()),
                        "avg_pnl_usd": float(sub.pnl_legacy_usd.mean()),
                        "sum_pnl_usd": float(sub.pnl_legacy_usd.sum()),
                        "avg_entry_vwap": float(sub.entry_vwap.mean()),
                    })
    g = pd.DataFrame(agg_rows)
    g = g.sort_values(["variant", "asset", "fire_offset_s", "thr_bps"]).reset_index(drop=True)
    g["wr"] = g.wr.round(4)
    g["avg_pnl_usd"] = g.avg_pnl_usd.round(4)
    g["sum_pnl_usd"] = g.sum_pnl_usd.round(2)
    g["avg_entry_vwap"] = g.avg_entry_vwap.round(4)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    g.to_csv(OUT_CSV, index=False)
    print(f"    wrote {OUT_CSV}")

    # Deployable
    deploy = g[(g.n >= 30) & (g.wr >= 0.60) & (g.avg_pnl_usd > 0)].copy().sort_values(
        ["avg_pnl_usd"], ascending=False
    ).reset_index(drop=True)
    print(f"\n--- Deployable (n>=30, WR>=60%, +EV): {len(deploy)} configs ---")
    if len(deploy) > 0:
        print(deploy.head(40).to_string(index=False))

    # Overlap with S1
    print("\n[7] overlap with S1 (VWAP continuation)...")
    overlap_md = ""
    if S1_PT.exists():
        s1 = pd.read_parquet(S1_PT)
        s1 = s1[s1.asset.isin(["ETH", "SOL"])]
        # Strict slug-level: a slug is "fired by S1" if any S1 fire passes the S1 +EV deploy gate
        # We use S1 fires with dev_bps > 5 already filtered in template.
        s1_fired = set(s1.slug.unique())
        # All slugs ETH/SOL we have in our universe
        all_eth_sol = set(res.slug.unique())
        ll_slugs_v1 = {}
        for asset in ("ETH", "SOL"):
            for variant in ("V1", "V2", "V3"):
                # Best config per asset/variant if any deployable
                v_deploy = deploy[(deploy.asset == asset) & (deploy.variant == variant)]
                if len(v_deploy) == 0:
                    continue
                best = v_deploy.iloc[0]
                sub = filled[(filled.asset == asset)
                             & (filled.fire_offset_s == best.fire_offset_s)
                             & (filled.abs_btc_30s >= best.thr_bps)].copy()
                if variant == "V2": sub = sub[sub.cvd_confirms]
                elif variant == "V3": sub = sub[sub.asset_quiet]
                ll_slugs = set(sub.slug.unique())
                s1_asset = set(s1[s1.asset == asset].slug.unique())
                overlap = ll_slugs & s1_asset
                only_ll = ll_slugs - s1_asset
                only_s1 = s1_asset - ll_slugs
                ll_slugs_v1[(asset, variant)] = (ll_slugs, overlap, only_ll, only_s1)
                print(f"  {asset} {variant} best (off={best.fire_offset_s}, thr={best.thr_bps}): "
                      f"lead-lag slugs={len(ll_slugs)}, S1 slugs={len(s1_asset)}, "
                      f"overlap={len(overlap)} ({100*len(overlap)/max(len(ll_slugs),1):.1f}% of LL), "
                      f"only_LL={len(only_ll)}, only_S1={len(only_s1)}")
                overlap_md += (f"- **{asset} {variant}** (off={best.fire_offset_s}s, thr={best.thr_bps}bps): "
                               f"{len(ll_slugs)} slugs fired by lead-lag, {len(s1_asset)} by S1, "
                               f"overlap={len(overlap)} ({100*len(overlap)/max(len(ll_slugs),1):.1f}% of LL fires), "
                               f"unique to LL={len(only_ll)}, unique to S1={len(only_s1)}\n")
    else:
        print(f"    S1 parquet not found at {S1_PT}, skipping overlap check")
        overlap_md = "_(S1 results parquet not available — overlap analysis skipped)_"

    # Markdown report
    print("\n[8] writing markdown report...")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    md = []
    md.append(f"# BTC → ETH/SOL lead-lag — 5m markets ({now})")
    md.append("")
    md.append("**Hypothesis tested**: BTC moves in last 30/60s predict ETH/SOL moves in next 30/60s "
              "well enough to seed an early fire on ETH/SOL 5m chainlink markets.")
    md.append("")
    md.append("**Fee model**: engine_v2.LegacyConfig (2%-on-profit only) — production-equivalent.")
    md.append(f"**Notional**: $25. **Spread filter**: BTC {SPREAD_FILTER['BTC']}, "
              f"ETH {SPREAD_FILTER['ETH']}, SOL {SPREAD_FILTER['SOL']}.")
    md.append(f"**Universe**: {len(res[res.asset=='ETH']):,} ETH + {len(res[res.asset=='SOL']):,} SOL 5m slugs "
              "(chainlink-resolved, Apr 24 → May 21 28d).")
    md.append("")
    md.append("## Headline")
    md.append("")
    if len(deploy) == 0:
        md.append("**NONE** — no configuration cleared the deployable bar (n≥30, WR≥60%, +EV).")
    else:
        md.append(f"**{len(deploy)} deployable configs** across the 3 variants × 2 assets × 3 offsets × 4 thresholds = "
                  f"{3*2*3*4} cells tested.")
        md.append("")
        md.append("### Best deployable configs")
        md.append("")
        md.append(deploy.head(20).to_markdown(index=False))
    md.append("")
    md.append("## Lead-lag correlation (1000-sample probe)")
    md.append("")
    md.append("Computed against random timestamps over the same 28d window (probe script "
              "`strategy_lab/meta_classifier/_lead_lag_corr_probe.py`):")
    md.append("")
    md.append("| pair | correlation |")
    md.append("| --- | --- |")
    md.append("| BTC_ret_30s ↔ ETH_ret_30s_FWD | **+0.1115** |")
    md.append("| BTC_ret_60s ↔ ETH_ret_30s_FWD | +0.0870 |")
    md.append("| BTC_ret_30s ↔ ETH_ret_60s_FWD | +0.0967 |")
    md.append("| BTC_ret_30s ↔ SOL_ret_30s_FWD | **+0.1489** |")
    md.append("| BTC_ret_60s ↔ SOL_ret_30s_FWD | +0.1065 |")
    md.append("| BTC_ret_30s ↔ SOL_ret_60s_FWD | +0.1252 |")
    md.append("| BTC_CVD_30s ↔ ETH_ret_30s_FWD | **+0.1500** |")
    md.append("| BTC_CVD_30s ↔ SOL_ret_30s_FWD | **+0.1569** |")
    md.append("| BTC_ret_30s ↔ ETH_ret_30s_BACK (contemporaneous, sanity) | +0.8878 |")
    md.append("| BTC_ret_30s ↔ SOL_ret_30s_BACK (contemporaneous, sanity) | +0.8194 |")
    md.append("")
    md.append("Contemporaneous BTC↔ETH/SOL correlation is ~0.83-0.89 (very high). "
              "Predictive lead-lag is **+0.10 to +0.16** — small but positive. "
              "BTC CVD is the strongest predictor (+0.15-0.16). Worth threshold-conditional backtest.")
    md.append("")
    md.append("## All variants summary (n≥30)")
    md.append("")
    md.append(g[g.n >= 30].sort_values(["variant", "asset", "wr"], ascending=[True, True, False]).to_markdown(index=False))
    md.append("")
    md.append("## Per-asset breakdown")
    md.append("")
    for asset in ("ETH", "SOL"):
        md.append(f"### {asset}")
        md.append("")
        sub = g[(g.asset == asset) & (g.n >= 30)].sort_values("wr", ascending=False).head(20)
        if len(sub) == 0:
            md.append(f"_no configs with n≥30 for {asset}_")
        else:
            md.append(sub.to_markdown(index=False))
        md.append("")
    md.append("## Variant interpretation")
    md.append("")
    md.append("- **V1 (raw BTC threshold)**: fire when |BTC_ret_30s| ≥ THR_BPS, bet WITH BTC direction.")
    md.append("- **V2 (CVD-confirmed)**: V1 AND BTC taker-CVD sign agrees with BTC return sign.")
    md.append("- **V3 (catch-up)**: V1 AND |asset_ret_30s_back| < 10bps (asset hasn't caught up to BTC yet).")
    md.append("")
    md.append("## Overlap with S1 (VWAP continuation) on the same slugs")
    md.append("")
    md.append(overlap_md if overlap_md else "_no overlap analysis (no deployable configs)_")
    md.append("")
    md.append("## Files")
    md.append("")
    md.append(f"- aggregated CSV: `data/v4/canonical/_results/btc_lead_lag_5m.csv`")
    md.append(f"- per-fire parquet: `data/v4/canonical/_results/btc_lead_lag_5m_per_fire.parquet`")
    md.append(f"- script: `strategy_lab/meta_classifier/btc_lead_lag_5m.py`")
    md.append(f"- correlation probe: `strategy_lab/meta_classifier/_lead_lag_corr_probe.py`")
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"    wrote {OUT_MD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
