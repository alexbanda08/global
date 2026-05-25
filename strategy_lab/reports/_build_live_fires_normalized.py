"""Build canonical live-fires CSV by joining production trading.events signals
to resolutions, augmenting with slug lookup and Ireland shadow CSVs.

Output: data/v4/canonical/_results/live_fires_normalized.csv

Schema:
  at_us, sleeve_id, strategy, asset, tf, f7_mode, slug, ws_s, signal,
  vwap, shares, usd, won, pnl_usd, fire_us

Inputs:
  - data/v4/canonical/trading_events_30d.parquet  (production trading.events)
  - data/v4/canonical/resolutions_from_rtds.parquet  (condition_id -> slug map)
  - migration_ireland_shadow_2026_05_21/maker_csvs/pat-shadow_2026-05-2{0,1}.csv
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
CANON = ROOT / "data" / "v4" / "canonical"
OUT = CANON / "_results" / "live_fires_normalized.csv"

sys.path.insert(0, str(CANON))
from load import load_resolutions, load_trading_events  # noqa: E402


_WINDOW_S = {"5m": 300, "15m": 900}


def parse_at_to_us(at_str: str) -> int:
    """Parse an at-string like '2026-05-07 02:10:06.410624+02' to UTC microseconds."""
    ts = pd.to_datetime(at_str, utc=True, errors="coerce")
    if pd.isna(ts):
        return -1
    return int(ts.value // 1000)  # ns -> us


def derive_strategy(sleeve_id: str) -> str:
    """Derive coarse strategy bucket from sleeve_id."""
    s = sleeve_id.lower()
    if "mint_sell" in s or "pat_shadow" in s:
        return "mint_sell"
    if "momo_v2" in s:
        return "momo_v2"
    if "momo" in s:
        return "momo_v1"
    if "sniper_inv" in s:
        return "sniper_inv"
    if "sniper" in s:
        return "sniper"
    if "volume" in s:
        return "volume"
    if "_v4" in s:
        return "v4"
    if "_v3" in s:
        return "v3"
    return "other"


def derive_asset(sleeve_id: str) -> str | None:
    s = sleeve_id.lower()
    for a in ("btc", "eth", "sol"):
        if f"_{a}_" in s:
            return a.upper()
    return None


def derive_tf(sleeve_id: str) -> str | None:
    s = sleeve_id.lower()
    if "_5m" in s:
        return "5m"
    if "_15m" in s:
        return "15m"
    return None


def main() -> None:
    print(">> loading trading_events_30d ...", flush=True)
    df = load_trading_events()
    df["at_us"] = df["at"].astype(str).map(parse_at_to_us)
    print(f"   {len(df):,} rows, at_us range {df.at_us.min()} -> {df.at_us.max()}")

    # ------------------------------------------------------------------
    # 1) Fired signals (poly_updown order_placed)
    # ------------------------------------------------------------------
    print(">> extracting fired poly_updown signals ...", flush=True)
    sig = df[df.kind == "poly_updown_signal"]
    sig = sig[sig.data.str.contains("order_placed", regex=False, na=False)].copy()
    print(f"   {len(sig):,} fired signals")

    def expand_signal_row(s: str) -> dict:
        try:
            d = json.loads(s)
        except Exception:
            return {}
        return d

    sig_payload = sig["data"].map(expand_signal_row)
    sig["signal"] = sig_payload.map(lambda d: d.get("signal"))
    sig["asset_from_data"] = sig_payload.map(lambda d: d.get("symbol"))
    sig["tf_from_data"] = sig_payload.map(lambda d: d.get("tf"))
    sig["vwap"] = pd.to_numeric(sig_payload.map(lambda d: d.get("fill_price")), errors="coerce")
    sig["shares"] = pd.to_numeric(sig_payload.map(lambda d: d.get("fill_qty")), errors="coerce")
    sig["condition_id"] = sig_payload.map(lambda d: d.get("condition_id"))
    sig["strategy_mode"] = sig_payload.map(lambda d: d.get("strategy_mode"))
    sig["f7_filter_mode"] = sig_payload.map(lambda d: d.get("f7_filter_mode"))
    sig["f7_decision"] = sig_payload.map(lambda d: d.get("f7_decision"))
    sig["fill_status"] = sig_payload.map(lambda d: d.get("fill_status"))
    sig["usd"] = sig["vwap"] * sig["shares"]
    # f7_mode: off / basic / extreme
    sig["f7_mode"] = sig["f7_filter_mode"].fillna("off")

    # ------------------------------------------------------------------
    # 2) Resolutions — extract won/pnl + fill_event_id
    # ------------------------------------------------------------------
    print(">> extracting poly_updown resolutions ...", flush=True)
    res = df[df.kind == "poly_updown_resolution"].copy()
    res_payload = res["data"].map(expand_signal_row)
    res["won"] = res_payload.map(lambda d: d.get("won"))
    res["pnl_usd"] = pd.to_numeric(res_payload.map(lambda d: d.get("pnl_usd")), errors="coerce")
    res["fill_event_id"] = res_payload.map(lambda d: d.get("fill_event_id"))
    res["outcome"] = res_payload.map(lambda d: d.get("outcome"))
    print(f"   {len(res):,} resolutions, {res.fill_event_id.notna().sum():,} with fill_event_id")

    # Build res_by_fill_event for fast lookup
    res_keep = res[["fill_event_id", "won", "pnl_usd", "outcome"]].dropna(subset=["fill_event_id"])
    res_by_fid = res_keep.drop_duplicates("fill_event_id", keep="last").set_index("fill_event_id")

    # ------------------------------------------------------------------
    # 3) Slug lookup: condition_id -> slug (via canonical resolutions)
    # ------------------------------------------------------------------
    print(">> loading canonical resolutions for slug map ...", flush=True)
    canon_res = load_resolutions()
    slug_map = canon_res.drop_duplicates("market_id").set_index("market_id")["slug"]
    print(f"   {len(slug_map):,} condition_id -> slug entries")

    # ------------------------------------------------------------------
    # 4) Compose normalized rows for poly_updown signals
    # ------------------------------------------------------------------
    print(">> composing normalized fire rows (poly_updown) ...", flush=True)
    out = pd.DataFrame({
        "at_us": sig["at_us"].values,
        "fire_us": sig["at_us"].values,
        "sleeve_id": sig["sleeve_id"].values,
        "event_id": sig["event_id"].values,
        "strategy": [derive_strategy(s) for s in sig["sleeve_id"].values],
        "asset": sig["asset_from_data"].fillna(sig["sleeve_id"].map(derive_asset)).values,
        "tf": sig["tf_from_data"].fillna(sig["sleeve_id"].map(derive_tf)).values,
        "f7_mode": sig["f7_mode"].values,
        "signal": sig["signal"].values,
        "vwap": sig["vwap"].values,
        "shares": sig["shares"].values,
        "usd": sig["usd"].values,
        "condition_id": sig["condition_id"].values,
        "strategy_mode": sig["strategy_mode"].values,
        "f7_decision": sig["f7_decision"].values,
        "fill_status": sig["fill_status"].values,
    })

    # Slug from condition_id
    out["slug"] = out["condition_id"].map(slug_map)

    # ws_s from slug suffix - window
    def slug_to_ws_s(row) -> int | None:
        sl, tf = row["slug"], row["tf"]
        if not isinstance(sl, str) or tf not in _WINDOW_S:
            return None
        try:
            slot_start = int(sl.rsplit("-", 1)[1])
        except Exception:
            return None
        return slot_start - _WINDOW_S[tf]

    out["ws_s"] = out.apply(slug_to_ws_s, axis=1)

    # Join resolutions by event_id (the signal's event_id matches res.fill_event_id)
    res_lookup = res_by_fid[["won", "pnl_usd", "outcome"]]
    out = out.merge(res_lookup, left_on="event_id", right_index=True, how="left")

    # ------------------------------------------------------------------
    # 5) Add mint_sell v2 fires (poly_mint_sell_v2_fire kind) + their resolutions
    # ------------------------------------------------------------------
    print(">> extracting mint_sell v2 fires ...", flush=True)
    ms_fire = df[df.kind == "poly_mint_sell_v2_fire"].copy()
    ms_payload = ms_fire["data"].map(expand_signal_row)
    # signal/asset/tf derived from sleeve_id (the v2 fire payload has no symbol)
    ms_out = pd.DataFrame({
        "at_us": ms_fire["at_us"].values,
        "fire_us": ms_fire["at_us"].values,
        "sleeve_id": ms_fire["sleeve_id"].values,
        "event_id": ms_fire["event_id"].values,
        "strategy": [derive_strategy(s) for s in ms_fire["sleeve_id"].values],
        "asset": ms_fire["sleeve_id"].map(derive_asset).values,
        "tf": ms_fire["sleeve_id"].map(derive_tf).values,
        "f7_mode": "off",
        "signal": "BOTH",  # mint-and-sell posts both legs
        "vwap": np.nan,
        "shares": pd.to_numeric(
            ms_payload.map(lambda d: d.get("desired_up_qty")), errors="coerce"
        ).values,
        "usd": np.nan,
        "condition_id": None,
        "strategy_mode": "mint_sell_v2",
        "f7_decision": None,
        "fill_status": "v2_fire",
    })
    # mint_sell_resolution carries fire_event_id (not fill_event_id)
    ms_res = df[df.kind == "poly_mint_sell_resolution"].copy()
    ms_res_payload = ms_res["data"].map(expand_signal_row)
    ms_res["won"] = ms_res_payload.map(lambda d: d.get("won"))
    ms_res["pnl_usd"] = pd.to_numeric(ms_res_payload.map(lambda d: d.get("pnl_usd")), errors="coerce")
    ms_res["outcome"] = ms_res_payload.map(lambda d: d.get("outcome"))
    ms_res["fire_event_id"] = ms_res_payload.map(lambda d: d.get("fire_event_id"))
    ms_res["slug_from_data"] = ms_res_payload.map(lambda d: d.get("slug"))
    ms_lookup = (ms_res.dropna(subset=["fire_event_id"])
                 .drop_duplicates("fire_event_id", keep="last")
                 .set_index("fire_event_id")[["won", "pnl_usd", "outcome", "slug_from_data"]])
    ms_out = ms_out.merge(ms_lookup, left_on="event_id", right_index=True, how="left")
    ms_out["slug"] = ms_out["slug_from_data"]
    ms_out["ws_s"] = ms_out.apply(slug_to_ws_s, axis=1)
    ms_out = ms_out.drop(columns=["slug_from_data"])
    print(f"   {len(ms_out):,} mint_sell v2 fires")

    # ------------------------------------------------------------------
    # 6) Combine + add Ireland pat-shadow fires (FILL rows only — one per
    #    completed leg). Aggregate to per-slug rows to align with "one row
    #    per fire" semantics.
    # ------------------------------------------------------------------
    print(">> appending Ireland pat-shadow fires ...", flush=True)
    pat_files = [
        ROOT / "migration_ireland_shadow_2026_05_21" / "maker_csvs" / "pat-shadow_2026-05-20.csv",
        ROOT / "migration_ireland_shadow_2026_05_21" / "maker_csvs" / "pat-shadow_2026-05-21.csv",
    ]
    pat_rows = []
    for pf in pat_files:
        if not pf.exists():
            continue
        try:
            d = pd.read_csv(pf)
        except pd.errors.ParserError:
            # CSV has mid-file column-count change (sleeve_id added). Use python
            # engine + on_bad_lines='skip' to bypass malformed rows; we mainly
            # need the rows with sleeve_id column populated.
            d = pd.read_csv(pf, engine="python", on_bad_lines="skip")
        # only FILL rows have realized PnL state; use slug-level aggregation:
        # use action=='FILL' to count one per leg fill, then group by slug+strategy
        # we want one row per fire = one row per slug per sleeve
        g = d[d.action.isin(["TAKE", "FILL"])].copy()
        if g.empty:
            continue
        # take first ts per slug as fire_us (TAKE event)
        first_take = (g[g.action == "TAKE"]
                      .sort_values("ts_us")
                      .drop_duplicates("slug", keep="first"))
        first_take = first_take.set_index("slug")
        # final cash_recovered + slug_pnl_so_far = realized pnl per slug
        last_fill = (g.sort_values("ts_us")
                     .drop_duplicates("slug", keep="last"))
        last_fill = last_fill.set_index("slug")
        merged = first_take.join(
            last_fill[["slug_pnl_so_far", "cash_recovered"]].rename(
                columns={"slug_pnl_so_far": "pnl_final",
                          "cash_recovered": "cash_recovered_final"}),
            how="left",
        )
        for slug, r in merged.iterrows():
            tf = r.get("tf")
            asset = r.get("asset")
            # ws_s from slug
            try:
                slot_start = int(slug.rsplit("-", 1)[1])
                window = _WINDOW_S.get(tf, 0)
                ws_s = slot_start - window if window else None
            except Exception:
                ws_s = None
            sleeve_id = r.get("sleeve_id") if isinstance(r.get("sleeve_id"), str) else "poly_pat_shadow_unknown"
            pnl = r.get("pnl_final")
            pat_rows.append({
                "at_us": int(r["ts_us"]),
                "fire_us": int(r["ts_us"]),
                "sleeve_id": sleeve_id,
                "event_id": r.get("order_id"),
                "strategy": "pat_shadow",
                "asset": asset,
                "tf": tf,
                "f7_mode": "off",
                "signal": "BOTH",
                "vwap": np.nan,
                "shares": pd.to_numeric(r.get("size"), errors="coerce"),
                "usd": pd.to_numeric(r.get("notional"), errors="coerce"),
                "condition_id": None,
                "strategy_mode": "pat_shadow",
                "f7_decision": None,
                "fill_status": "pat_shadow",
                "slug": slug,
                "ws_s": ws_s,
                "won": pd.notna(pnl) and pnl > 0 if pnl is not None else None,
                "pnl_usd": pnl,
                "outcome": "pat_shadow",
            })
    pat_df = pd.DataFrame(pat_rows) if pat_rows else pd.DataFrame()
    print(f"   {len(pat_df):,} pat-shadow fires")

    # ------------------------------------------------------------------
    # 7) Concatenate, finalize columns, write CSV
    # ------------------------------------------------------------------
    base_cols = ["at_us", "fire_us", "sleeve_id", "strategy", "asset", "tf",
                  "f7_mode", "slug", "ws_s", "signal", "vwap", "shares", "usd",
                  "won", "pnl_usd", "outcome", "condition_id", "strategy_mode",
                  "f7_decision", "fill_status", "event_id"]
    for c in base_cols:
        if c not in out.columns:
            out[c] = None
        if c not in ms_out.columns:
            ms_out[c] = None
        if not pat_df.empty and c not in pat_df.columns:
            pat_df[c] = None

    frames = [out[base_cols], ms_out[base_cols]]
    if not pat_df.empty:
        frames.append(pat_df[base_cols])
    final = pd.concat(frames, ignore_index=True)
    # Order by fire time
    final = final.sort_values("at_us").reset_index(drop=True)

    print(f">> writing {len(final):,} normalized fire rows -> {OUT}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    final.to_csv(OUT, index=False)

    # ------------------------------------------------------------------
    # 8) Print summary stats so caller sees the headline numbers
    # ------------------------------------------------------------------
    print()
    print("=== summary ===")
    print(f"total fires:     {len(final):,}")
    print(f"poly_updown:     {len(out):,}")
    print(f"mint_sell v2:    {len(ms_out):,}")
    print(f"pat_shadow:      {len(pat_df):,}")
    print(f"with pnl_usd:    {final.pnl_usd.notna().sum():,} ({final.pnl_usd.notna().mean()*100:.1f}%)")
    print(f"won (where set): {final.won.fillna(False).sum():,}")
    print()
    print("fires per sleeve (top 30 by count):")
    print(final.groupby("sleeve_id").size().sort_values(ascending=False).head(30).to_string())


if __name__ == "__main__":
    main()
