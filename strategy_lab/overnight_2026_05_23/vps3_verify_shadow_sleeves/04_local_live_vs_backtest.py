"""Local live-vs-backtest comparison after VPS3 refresh.

Uses fresh trading_events_30d.parquet to compare each shadow sleeve's
LIVE 24h performance to the backtest expectation. Also checks FADE direction
sanity by joining shadow_*_fade_* events to the parent momo/sniper events
by slug + timing.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
EVENTS = ROOT / "data" / "v4" / "canonical" / "trading_events_30d.parquet"
OUT = ROOT / "data" / "v4" / "canonical" / "_results" / "live_shadow_vs_backtest.csv"


EXPECTED = {
    # backtest expectations from PHASE2_FINAL_FINDINGS / SHADOW_DEPLOY_SPEC
    "shadow_poly_updown_ALL_5m_phase1_kelly":              (167, 84.4, 5.50,  927.0),
    "shadow_poly_updown_btc_5m_fade_momo_v2":              (35,  51.9, 0.86,   22.0),
    "shadow_poly_updown_btc_5m_fade_sniper":               (30,  53.0, 0.80,   18.0),
    "shadow_poly_updown_eth_15m_fade_sniper":              (15,  52.6, 1.02,   12.0),
    "shadow_poly_updown_sol_5m_fade_sniper":               (17,  50.8, 0.45,    6.0),
    "shadow_poly_updown_sol_5m_fade_momo_v2":              (17,  50.1, 0.55,    7.0),
    "shadow_poly_updown_sol_15m_fade_momo_v2":             ( 4,  52.4, 1.88,    6.0),
    "shadow_poly_updown_ALL_5m_S3_prewindow":              (95,  52.8, 0.83,   78.0),
    "shadow_poly_updown_ALL_15m_S4_prewindow":             (11,  54.6, 2.26,   25.0),
    # 6 overlay shadows (slightly less precise expectations)
    "shadow_poly_updown_eth_15m_sniper_m5v":               (4,   63.2, 7.15,   29.0),
    "shadow_poly_updown_btc_5m_momo_v2_fairedge500":       (15,  52.9, 0.34,   29.0),
    "shadow_poly_updown_btc_15m_momo_v2_fairedge500_cvd30":(3,   63.2, 5.54,   17.0),
    "shadow_poly_updown_sol_15m_sniper_fairedge500":       (2,   65.6, 8.06,   14.0),
    "shadow_poly_updown_sol_5m_momo_v1_m5v":               (3,   62.5, 4.99,   17.0),
    "shadow_poly_updown_sol_5m_momo_v2_cvd_macd":          (5,   57.3, 2.13,   17.0),
}


def parse(s):
    if s is None or (isinstance(s, float) and np.isnan(s)): return {}
    try: return json.loads(s) if isinstance(s, str) else s
    except Exception: return {}


def main():
    d = pd.read_parquet(EVENTS)
    d["at_ts"] = pd.to_datetime(d["at"], utc=True, format="mixed")
    print(f"[load] {len(d):,} rows, latest {d.at_ts.max()}")

    sh = d[d["sleeve_id"].astype(str).str.startswith("shadow_", na=False)].copy()
    sh["_d"] = sh["data"].apply(parse)
    sh["signal"] = sh["_d"].apply(lambda x: str(x.get("signal", "")))
    sh["reason"] = sh["_d"].apply(lambda x: str(x.get("reason", "")))
    sh["slug"]   = sh["_d"].apply(lambda x: str(x.get("slug", "") or x.get("condition_id", "")))
    sh["pnl"]    = sh["_d"].apply(lambda x: float(x.get("pnl_usd", 0)) if str(x.get("pnl_usd", "")).strip() not in ("nan", "None", "") else 0.0)
    sh["won"]    = sh["_d"].apply(lambda x: bool(x.get("won", False)))
    sh["symbol"] = sh["_d"].apply(lambda x: str(x.get("symbol", "")))
    sh["tf"]     = sh["_d"].apply(lambda x: str(x.get("tf", "")))
    sh["fill_price"] = sh["_d"].apply(lambda x: float(x.get("fill_price", 0)) if str(x.get("fill_price","")).strip() not in ("nan","None","") else 0.0)
    sh["fill_qty"]   = sh["_d"].apply(lambda x: float(x.get("fill_qty", 0)) if str(x.get("fill_qty","")).strip() not in ("nan","None","") else 0.0)

    print(f"[shadow events] {len(sh):,} total")
    # Real fires (signal in UP/DOWN, not heartbeat)
    fires = sh[sh["signal"].isin(["UP", "DOWN"])].copy()
    print(f"[real fires] {len(fires):,}  ({len(fires)/len(sh)*100:.1f}% of shadow events)")

    # Resolutions
    res = sh[sh["kind"] == "poly_updown_resolution"].copy()
    print(f"[resolutions] {len(res):,}")

    span_h = (sh["at_ts"].max() - sh["at_ts"].min()).total_seconds() / 3600
    print(f"[span] {span_h:.1f} hours")

    # Per-sleeve live stats
    rows = []
    for sid, (exp_fpd, exp_wr, exp_pt, exp_spd) in EXPECTED.items():
        ssub_f = fires[fires["sleeve_id"] == sid]
        ssub_r = res  [res["sleeve_id"] == sid]
        live_fires = len(ssub_f)
        live_fpd   = live_fires * 24 / max(1, span_h)
        if len(ssub_r) > 0:
            wr_live = float(ssub_r["won"].mean()) * 100
            sum_pnl = float(ssub_r["pnl"].sum())
            per_tr  = sum_pnl / len(ssub_r)
            spd_live = sum_pnl * 24 / max(1, span_h)
        else:
            wr_live = 0; sum_pnl = 0; per_tr = 0; spd_live = 0
        # verdict
        if live_fires == 0:
            verdict = "MISSING_NO_FIRES"
        elif live_fpd < 0.5 * exp_fpd:
            verdict = "LOW_FIRES"
        elif live_fpd > 2.0 * exp_fpd:
            verdict = "HIGH_FIRES"
        elif len(ssub_r) >= 10 and spd_live < 0.0:
            verdict = "PNL_NEGATIVE"
        elif len(ssub_r) >= 10 and abs(wr_live - exp_wr) > 10:
            verdict = "WR_OUT_OF_BAND"
        elif len(ssub_r) < 10:
            verdict = "TOO_FEW_RES"
        else:
            verdict = "OK"
        rows.append({
            "sleeve": sid,
            "live_fires": live_fires, "live_fires_per_day": round(live_fpd, 1),
            "exp_fires_per_day": exp_fpd,
            "live_resolutions": len(ssub_r),
            "live_wr_pct": round(wr_live, 2), "exp_wr_pct": exp_wr,
            "live_per_tr": round(per_tr, 3),  "exp_per_tr": exp_pt,
            "live_sum_pnl": round(sum_pnl, 2),
            "live_$_per_day": round(spd_live, 2),
            "exp_$_per_day": exp_spd,
            "verdict": verdict,
        })
    out = pd.DataFrame(rows).sort_values("live_$_per_day").reset_index(drop=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index=False)
    pd.set_option("display.max_columns", None); pd.set_option("display.width", 240)
    pd.set_option("display.max_colwidth", 55)
    print()
    print(out.to_string(index=False))
    print()
    print(f"[write] {OUT}")

    # FADE direction sanity — join fade shadow signals to production momo/sniper signals on slug + ws_s
    print()
    print("=== FADE direction sanity ===")
    # Pull prod momo/sniper events (non-shadow, kind=poly_updown_signal)
    prod = d[(d["kind"] == "poly_updown_signal")
              & (d["sleeve_id"].astype(str).str.startswith("poly_updown_", na=False))
              & (~d["sleeve_id"].astype(str).str.startswith("shadow_", na=False))].copy()
    prod["_d"] = prod["data"].apply(parse)
    prod["slug"] = prod["_d"].apply(lambda x: str(x.get("slug", "") or x.get("condition_id", "")))
    prod["signal"] = prod["_d"].apply(lambda x: str(x.get("signal", "")))
    prod = prod[prod["signal"].isin(["UP","DOWN"])][["sleeve_id", "slug", "signal", "at_ts"]].copy()
    prod = prod.rename(columns={"sleeve_id": "prod_sleeve", "signal": "prod_dir", "at_ts": "prod_at"})
    fade = fires[fires["sleeve_id"].str.contains("_fade_", na=False)].copy()
    fade = fade.rename(columns={"sleeve_id": "shadow_sleeve", "signal": "shadow_dir", "at_ts": "shadow_at"})
    # Many-to-many join: prod fires same slug as shadow fade
    j = fade.merge(prod, on="slug", how="left", suffixes=("", "_p"))
    # Filter to time-aligned (prod fired within ±60s of shadow)
    j["dt_s"] = (j["shadow_at"] - j["prod_at"]).dt.total_seconds().abs()
    j = j[j["dt_s"] <= 60.0]
    j["same_dir"]    = j["shadow_dir"].str.upper() == j["prod_dir"].str.upper()
    j["opposite_dir"] = (
        ((j["shadow_dir"].str.upper() == "UP")   & (j["prod_dir"].str.upper() == "DOWN"))
        |((j["shadow_dir"].str.upper() == "DOWN") & (j["prod_dir"].str.upper() == "UP"))
    )
    by_sleeve = j.groupby("shadow_sleeve").agg(
        joined=("slug","size"),
        same=("same_dir", "sum"),
        opposite=("opposite_dir","sum")
    )
    by_sleeve["pct_opposite"] = (100*by_sleeve["opposite"]/by_sleeve["joined"]).round(1)
    print(by_sleeve.to_string())


if __name__ == "__main__":
    main()
