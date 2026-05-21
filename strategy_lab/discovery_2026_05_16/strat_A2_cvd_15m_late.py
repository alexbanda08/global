"""Strategy A2 — LATE-entry CVD on 15m markets.

User ask: "enter in the latest 15 min" -> fire late in the 15m window using CVD
accumulated over the market so far.

For each 15m market:
  slot_start_us, slot_end_us from resolutions.
  variant ENTRY = slot_end_us - {60, 180}e6   (1 min before settle / 3 min before)
  variant OBS_WIN_MODE:
    "full"  -> observe [slot_start_us, entry_us)
    "last5" -> observe [entry_us - 300e6, entry_us)
  Up-side CVD over obs window (signed $-notional). signal = UP if cvd > +T else
  DOWN if cvd < -T else SKIP. Compare to outcome.

NO LOOKAHEAD: all trades used have timestamp_us < entry_us.
"""
from __future__ import annotations
import sys, time
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))

from load import load_resolutions, load_trades  # type: ignore
from discovery_2026_05_16.harness import hold_pnl_no_book  # type: ignore

THRESHOLDS = [0, 100, 500, 1000, 5000]
ASSETS = ["BTC", "ETH", "SOL"]
PRE_SETTLE_OFFSETS_S = [60, 180]    # 1min / 3min before slot_end
OBS_MODES = ["full", "last5"]


def run_asset(asset: str, sample_n: int | None = None, examples_out: list | None = None):
    print(f"\n=== {asset} 15m ===", flush=True)
    t0 = time.time()
    res = load_resolutions(assets=[asset], timeframes=["15m"]).copy()
    print(f"  universe: {len(res)} markets", flush=True)
    if sample_n is not None and len(res) > sample_n:
        res = res.sample(n=sample_n, random_state=42).reset_index(drop=True)
        print(f"  SAMPLED to {len(res)}", flush=True)

    trades = load_trades(asset.lower())
    print(f"  trades loaded: {len(trades):,}  ({time.time()-t0:.1f}s)", flush=True)
    trades_up = trades[trades["outcome"] == "Up"][["slug","timestamp_us","price","size","side"]].copy()
    trades_up = trades_up.sort_values(["slug","timestamp_us"])
    print(f"  Up trades: {len(trades_up):,}", flush=True)

    by_slug: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for slug, grp in trades_up.groupby("slug", sort=False):
        ts = grp["timestamp_us"].to_numpy()
        price = grp["price"].astype(float).to_numpy()
        size = grp["size"].astype(float).to_numpy()
        side = grp["side"].astype(str).str.upper().to_numpy()
        notional = price * size
        signed = np.where(side == "BUY", notional, -notional)
        by_slug[slug] = (ts, signed)
    print(f"  indexed {len(by_slug)} slugs  ({time.time()-t0:.1f}s)", flush=True)

    slugs = res["slug"].to_numpy()
    slot_start = res["slot_start_us"].to_numpy().astype(np.int64)
    slot_end = res["slot_end_us"].to_numpy().astype(np.int64)

    rows = []
    examples_collected = 0
    for entry_off_s in PRE_SETTLE_OFFSETS_S:
        entry_us_arr = slot_end - int(entry_off_s) * 1_000_000
        for obs_mode in OBS_MODES:
            if obs_mode == "full":
                lo_us = slot_start
            else:  # last5
                lo_us = entry_us_arr - 300 * 1_000_000
            cvd_arr = np.zeros(len(res), dtype=float)
            n_used = np.zeros(len(res), dtype=int)
            for i in range(len(res)):
                rec = by_slug.get(slugs[i])
                if rec is None:
                    continue
                ts, signed = rec
                a = np.searchsorted(ts, int(lo_us[i]), side="left")
                b = np.searchsorted(ts, int(entry_us_arr[i]), side="left")
                if b > a:
                    cvd_arr[i] = signed[a:b].sum()
                    n_used[i] = b - a

            # lookahead example collection
            if examples_out is not None and examples_collected < 1:
                idx = np.where(n_used >= 5)[0]
                if len(idx) > 0:
                    j = int(idx[0])
                    slug = slugs[j]
                    sub = trades[(trades["slug"] == slug) & (trades["outcome"] == "Up")]
                    sub_used = sub[(sub["timestamp_us"] >= int(lo_us[j])) &
                                   (sub["timestamp_us"] < int(entry_us_arr[j]))]
                    if len(sub_used) > 0:
                        examples_out.append({
                            "asset": asset, "slug": slug,
                            "entry_off_s": entry_off_s,
                            "obs_mode": obs_mode,
                            "lo_us": int(lo_us[j]),
                            "entry_us": int(entry_us_arr[j]),
                            "slot_end_us": int(slot_end[j]),
                            "max_trade_ts_us": int(sub_used["timestamp_us"].max()),
                            "max_lt_entry": int(sub_used["timestamp_us"].max()) < int(entry_us_arr[j]),
                            "n_used": int(len(sub_used)),
                        })
                        examples_collected += 1

            for T in THRESHOLDS:
                sig = np.where(cvd_arr > T, "UP", np.where(cvd_arr < -T, "DOWN", "SKIP"))
                fired_mask = sig != "SKIP"
                n = int(fired_mask.sum())
                if n == 0:
                    rows.append({
                        "asset": asset, "entry_off_s": entry_off_s,
                        "obs_mode": obs_mode, "threshold": T,
                        "n_fires": 0, "hit_rate": np.nan,
                        "pnl_flat_0.5": 0.0, "n_up": 0, "n_down": 0,
                    })
                    continue
                outcomes = res["outcome"].to_numpy()
                won = ((sig == "UP") & (outcomes == "Up")) | ((sig == "DOWN") & (outcomes == "Down"))
                hit = float(won[fired_mask].mean())
                # flat 0.5 entry: shares = 25/0.5 = 50; pnl_per_win = 50*(1-0.5)*0.98 = 24.5; pnl_per_loss = -25
                # 2% fee on profit only.
                n_win = int(won[fired_mask].sum())
                n_lose = n - n_win
                pnl_total = n_win * (25.0 - 25.0 * 0.02) - n_lose * 25.0
                rows.append({
                    "asset": asset,
                    "entry_off_s": entry_off_s,
                    "obs_mode": obs_mode,
                    "threshold": T,
                    "n_fires": n,
                    "hit_rate": round(hit, 4),
                    "pnl_flat_0.5": round(pnl_total, 2),
                    "n_up": int(((sig == "UP") & fired_mask).sum()),
                    "n_down": int(((sig == "DOWN") & fired_mask).sum()),
                })
    df = pd.DataFrame(rows)
    print(f"  --- {asset} 15m results ---", flush=True)
    print(df.to_string(index=False), flush=True)
    return df


def main():
    examples = []
    all_results = []
    for asset in ASSETS:
        df = run_asset(asset, examples_out=examples)
        all_results.append(df)
    combined = pd.concat(all_results, ignore_index=True)
    # cross-asset agg
    agg = combined.groupby(["entry_off_s","obs_mode","threshold"]).apply(
        lambda g: pd.Series({
            "n_fires": int(g["n_fires"].sum()),
            "hit_rate": float((g["hit_rate"] * g["n_fires"]).sum() / max(g["n_fires"].sum(), 1)),
            "pnl_flat_0.5": float(g["pnl_flat_0.5"].sum()),
        })
    ).reset_index()
    print("\n=== A2 COMBINED (all assets) ===", flush=True)
    print(agg.to_string(index=False), flush=True)

    print("\n=== A2 NO-LOOKAHEAD EXAMPLES (max trade ts_us must be < entry_us) ===", flush=True)
    for ex in examples[:3]:
        print(f"  {ex['asset']} slug={ex['slug']} off={ex['entry_off_s']}s mode={ex['obs_mode']}", flush=True)
        print(f"    lo_us={ex['lo_us']} entry_us={ex['entry_us']} slot_end_us={ex['slot_end_us']}", flush=True)
        print(f"    n_used={ex['n_used']} max_trade_ts_us={ex['max_trade_ts_us']} OK={ex['max_lt_entry']}", flush=True)

    out_dir = ROOT / "strategy_lab" / "discovery_2026_05_16"
    combined.to_csv(out_dir / "_A2_per_asset_threshold.csv", index=False)
    agg.to_csv(out_dir / "_A2_combined.csv", index=False)
    print(f"\nWrote: {out_dir/'_A2_per_asset_threshold.csv'}", flush=True)


if __name__ == "__main__":
    main()
