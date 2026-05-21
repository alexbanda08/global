"""
Strategy H -- CLOB Mispricing vs binance-momentum "fair" probability.

Hypothesis: at fire time, the CLOB-implied probability of Up differs from a
"fair" probability derived from binance momentum. Bet the gap.

At fire_us (ws_s + 120s for the EARLY variant; slot_end - 60s for LATE-15m):
  p_clob_up = mid_up                              # mid of Up-side book = (bid_0+ask_0)/2
  z         = ret_window / sigma_recent           # binance return z-score
  fair_p_up = clamp( 0.5 + 0.5 * tanh(2*z), 0.10, 0.90 )
  edge      = fair_p_up - p_clob_up
  signal    = UP if edge >  threshold AND spread OK
            = DOWN if edge < -threshold AND spread OK
            = SKIP otherwise

Sweep edge threshold ∈ {0.02, 0.05, 0.10, 0.15}.

Fill: walk asks for $25 notional on the chosen side. Spread filter applied.
PnL: hold to settlement. 2% on profit only. Fee model from harness.

Universe: 5m + 15m markets where L25 is available (Apr 22 onward).
Slugs batched in 500s for memory.

Anchor: ws_s + 120  (EARLY)  /  slot_end - 60 (LATE-15m).
Outcome = chainlink.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))
sys.path.insert(0, str(ROOT / "strategy_lab" / "discovery_2026_05_16"))

from load import (  # type: ignore
    load_resolutions, load_klines_asof, asof_strict, slug_to_ws_s,
)
from harness import (  # type: ignore
    hold_pnl_no_book, walk_asks, get_book_at, SPREAD_FILTER, NOTIONAL, FEE_RATE,
    load_book_subset, get_klines,
)


OUT = ROOT / "strategy_lab" / "discovery_2026_05_16"
OUT.mkdir(parents=True, exist_ok=True)

BATCH_SIZE = 500
RECENT_SIGMA_WINDOW_S = 30 * 60   # 30 minutes recent std for z-score


def compute_binance_features(res: pd.DataFrame):
    """For each row, compute binance ret over the observation window AND
    recent realized std (so we can z-score the ret).

    EARLY:  ret = pct_change over [ws_s, ws_s+120].   sigma = std of 30 min trailing 1MIN returns ending at ws_s.
    LATE15: ret = pct_change over [slot_start, slot_end-60]. sigma = same trailing as EARLY but ending at slot_start.
    """
    out = res.copy().reset_index(drop=True)
    out["ret_obs_early"] = np.nan
    out["ret_obs_late15"] = np.nan
    out["sigma_recent_early"] = np.nan
    out["sigma_recent_late15"] = np.nan
    out["fire_us_early"] = -1
    out["fire_us_late15"] = -1

    for asset in ["BTC", "ETH", "SOL"]:
        end_us, prices = get_klines(asset, "binance-spot-ws", "1MIN")
        # Build 1-minute return series for sigma estimation.
        # end_us[i] corresponds to bar ending at end_us[i] ; close = prices[i].
        if len(prices) > 1:
            rets = np.diff(prices) / prices[:-1]
            rets_end_us = end_us[1:]
        else:
            rets = np.array([])
            rets_end_us = np.array([])

        mask = out.ticker == asset
        idxs = out.index[mask].tolist()
        for i in idxs:
            slug = out.at[i, "slug"]
            tf = out.at[i, "timeframe"]
            ws_s = slug_to_ws_s(slug, tf)
            # EARLY
            fire_us_e = int((ws_s + 120) * 1_000_000)
            out.at[i, "fire_us_early"] = fire_us_e
            p_ws = asof_strict(end_us, prices, int(ws_s) * 1_000_000)
            p_fire_e = asof_strict(end_us, prices, fire_us_e)
            if np.isfinite(p_ws) and p_ws > 0 and np.isfinite(p_fire_e):
                out.at[i, "ret_obs_early"] = (p_fire_e - p_ws) / p_ws
            sigma_e = _trailing_sigma(rets, rets_end_us, int(ws_s) * 1_000_000, RECENT_SIGMA_WINDOW_S)
            out.at[i, "sigma_recent_early"] = sigma_e

            if tf == "15m":
                slot_start_us = int(out.at[i, "slot_start_us"])
                slot_end_us = int(out.at[i, "slot_end_us"])
                fire_us_l = slot_end_us - 60 * 1_000_000
                out.at[i, "fire_us_late15"] = fire_us_l
                p_ss = asof_strict(end_us, prices, slot_start_us)
                p_fire_l = asof_strict(end_us, prices, fire_us_l)
                if np.isfinite(p_ss) and p_ss > 0 and np.isfinite(p_fire_l):
                    out.at[i, "ret_obs_late15"] = (p_fire_l - p_ss) / p_ss
                sigma_l = _trailing_sigma(rets, rets_end_us, slot_start_us, RECENT_SIGMA_WINDOW_S)
                out.at[i, "sigma_recent_late15"] = sigma_l
    return out


def _trailing_sigma(rets: np.ndarray, rets_end_us: np.ndarray, t_us: int, window_s: int) -> float:
    if len(rets) == 0:
        return float("nan")
    lo = t_us - window_s * 1_000_000
    i_hi = int(np.searchsorted(rets_end_us, t_us, side="right"))
    i_lo = int(np.searchsorted(rets_end_us, lo, side="left"))
    if i_hi - i_lo < 5:
        return float("nan")
    seg = rets[i_lo:i_hi]
    return float(np.std(seg))


def fair_p_from_z(z: float) -> float:
    """Map z to a probability in [0.10, 0.90] via tanh squash."""
    if not np.isfinite(z):
        return float("nan")
    p = 0.5 + 0.5 * np.tanh(2.0 * z)
    return max(0.10, min(0.90, p))


def evaluate_one_asset(asset: str, df_asset: pd.DataFrame, variant: str, edge_thresholds: list[float]):
    """variant: 'early' or 'late15'.
    Loads L25 books for slugs of this asset and computes fills.
    Returns list of dicts (row results, one per fired trade) and aggregates per threshold.
    """
    fire_col = "fire_us_early" if variant == "early" else "fire_us_late15"
    ret_col = "ret_obs_early" if variant == "early" else "ret_obs_late15"
    sig_col = "sigma_recent_early" if variant == "early" else "sigma_recent_late15"

    df = df_asset[df_asset[ret_col].notna() & df_asset[sig_col].notna()].copy()
    df = df[df[fire_col] > 0]
    if variant == "late15":
        df = df[df.timeframe == "15m"]
    if len(df) == 0:
        return [], {}

    slugs = df.slug.unique().tolist()
    print(f"   [H] {asset}/{variant}: {len(df)} candidate rows, {len(slugs)} unique slugs.")

    # batch-load books
    results = []  # one dict per (row, threshold) candidate (post-fill, with edge stored)
    per_row_baseline = []  # one dict per row with edge & p_clob (for inspection)

    n_batches = (len(slugs) + BATCH_SIZE - 1) // BATCH_SIZE
    for b in range(n_batches):
        sb = set(slugs[b * BATCH_SIZE:(b + 1) * BATCH_SIZE])
        print(f"   [H] {asset}/{variant}: loading L25 batch {b+1}/{n_batches} ({len(sb)} slugs)...")
        try:
            books = load_book_subset(asset, sb)
        except Exception as e:
            print(f"   [H] !! batch {b} load failed: {e}")
            continue

        rows_in_batch = df[df.slug.isin(sb)]
        for _, r in rows_in_batch.iterrows():
            slug = r.slug
            fire_us = int(r[fire_col])
            ret = float(r[ret_col])
            sigma = float(r[sig_col])
            if sigma <= 0 or not np.isfinite(sigma):
                continue
            z = ret / sigma
            fair_p_up = fair_p_from_z(z)
            if not np.isfinite(fair_p_up):
                continue

            # Get Up-side book to derive p_clob (mid of Up book) at fire.
            snap_up = get_book_at(books, slug, "Up", fire_us)
            if snap_up is None:
                continue
            ap_u, asz_u, bp_u, bsz_u = snap_up
            if not (np.isfinite(ap_u[0]) and np.isfinite(bp_u[0])):
                continue
            spread_up = ap_u[0] - bp_u[0]
            if spread_up > SPREAD_FILTER[asset]:
                # spread bad -- skip but log
                continue
            p_clob_up = (ap_u[0] + bp_u[0]) / 2.0
            edge = fair_p_up - p_clob_up

            per_row_baseline.append({
                "slug": slug, "ticker": asset, "timeframe": r.timeframe,
                "outcome": r.outcome, "fair_p_up": fair_p_up, "p_clob_up": p_clob_up,
                "edge": edge, "z": z, "ret_obs": ret, "sigma": sigma, "fire_us": fire_us,
            })

            for thr in edge_thresholds:
                if edge > thr:
                    signal = "UP"
                elif edge < -thr:
                    signal = "DOWN"
                else:
                    continue
                # fill on signal side
                side = "Up" if signal == "UP" else "Down"
                snap_side = get_book_at(books, slug, side, fire_us)
                if snap_side is None:
                    continue
                ap_s, asz_s, bp_s, bsz_s = snap_side
                if not (np.isfinite(ap_s[0]) and np.isfinite(bp_s[0])):
                    continue
                if (ap_s[0] - bp_s[0]) > SPREAD_FILTER[asset]:
                    continue
                vwap, shares, spent, under = walk_asks(list(ap_s), list(asz_s), NOTIONAL)
                if under or not np.isfinite(vwap) or vwap <= 0 or vwap >= 1:
                    continue
                pnl = hold_pnl_no_book(signal, r.outcome, vwap, notional=NOTIONAL)
                results.append({
                    "thr": thr, "slug": slug, "ticker": asset, "timeframe": r.timeframe,
                    "variant": variant, "outcome": r.outcome, "signal": signal,
                    "edge": edge, "vwap": vwap, "shares": shares, "pnl": pnl,
                    "won": int(signal == r.outcome.upper()),
                })
    return results, per_row_baseline


def summarize_results(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    g = (
        df.groupby(["variant", "thr"])
        .agg(n=("won", "size"), hit=("won", "mean"), pnl=("pnl", "sum"), pnl_mean=("pnl", "mean"))
        .round(4)
        .reset_index()
    )
    return g


def per_asset_summary(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    g = (
        df.groupby(["variant", "thr", "ticker", "timeframe"])
        .agg(n=("won", "size"), hit=("won", "mean"), pnl=("pnl", "sum"))
        .round(4)
        .reset_index()
    )
    return g


def main():
    print("[H] Loading resolutions universe...")
    res = load_resolutions()
    # Drop markets before L25 starts (Apr 18 -- inside resolutions Apr 24 so OK)
    res = res[res.slot_start_us >= int(pd.Timestamp("2026-04-22", tz="UTC").timestamp() * 1e6)].copy()
    print(f"[H] {len(res)} markets after L25-window filter.")

    print("[H] Computing binance features (ret + recent sigma) per row...")
    res = compute_binance_features(res)
    print(f"[H] ret_obs_early coverage: {res.ret_obs_early.notna().sum()}/{len(res)}")
    print(f"[H] sigma_recent_early coverage: {res.sigma_recent_early.notna().sum()}/{len(res)}")

    edge_thrs = [0.02, 0.05, 0.10, 0.15]

    all_results = []
    all_baselines = []

    print("\n[H] === EARLY variant (fire @ ws_s + 120s) ===")
    for asset in ["BTC", "ETH", "SOL"]:
        sub = res[res.ticker == asset]
        rows_h, baselines = evaluate_one_asset(asset, sub, "early", edge_thrs)
        all_results.extend(rows_h)
        all_baselines.extend(baselines)
        print(f"[H] {asset}/early: {len(rows_h)} fired trades across all thresholds.")

    print("\n[H] === LATE-15m variant (fire @ slot_end - 60s) ===")
    for asset in ["BTC", "ETH", "SOL"]:
        sub = res[(res.ticker == asset) & (res.timeframe == "15m")]
        rows_h, baselines = evaluate_one_asset(asset, sub, "late15", edge_thrs)
        all_results.extend(rows_h)
        all_baselines.extend(baselines)
        print(f"[H] {asset}/late15: {len(rows_h)} fired trades across all thresholds.")

    if not all_results:
        print("[H] NO TRADES FIRED. Check L25 coverage or thresholds.")
        return

    summary = summarize_results(all_results)
    print("\n[H] === overall sweep ===")
    print(summary.to_string())
    summary.to_csv(OUT / "H_sweep_overall.csv", index=False)

    pa = per_asset_summary(all_results)
    print("\n[H] === per-asset/timeframe ===")
    print(pa.to_string())
    pa.to_csv(OUT / "H_sweep_per_asset.csv", index=False)

    # Save trades
    pd.DataFrame(all_results).to_parquet(OUT / "H_trades.parquet")
    pd.DataFrame(all_baselines).to_parquet(OUT / "H_baselines.parquet")

    # Verdict: best config by total PnL with n >= 100
    best = None
    df_sum = summary
    cand = df_sum[df_sum.n >= 100]
    if len(cand):
        best = cand.sort_values("pnl", ascending=False).iloc[0].to_dict()
        print(f"\n[H] best config: variant={best['variant']} thr={best['thr']} "
              f"n={best['n']} hit={best['hit']:.4f} pnl=${best['pnl']:.2f}")
    verdict = "NULL"
    if best:
        if best["hit"] >= 0.55 and best["pnl"] > 0:
            verdict = "ALPHA-CANDIDATE"
        elif best["hit"] >= 0.52 and best["pnl"] > 0:
            verdict = "WEAK-POSITIVE"
        elif best["pnl"] < 0:
            verdict = "NULL-NEGATIVE-PNL"
    elif df_sum.n.max() < 50:
        verdict = "INCONCLUSIVE-LOW-N"
    print(f"[H] verdict: {verdict}")

    # No-lookahead sanity: print 5 random fires
    print("\n[H] === NO-LOOKAHEAD SANITY (5 random fires) ===")
    tr = pd.DataFrame(all_results).sample(min(5, len(all_results)), random_state=0)
    for _, r in tr.iterrows():
        print(f"  slug={r.slug} variant={r.variant} fire_signal={r.signal} edge={r.edge:.4f} "
              f"vwap={r.vwap:.4f}")

    return {"best": best, "verdict": verdict}


if __name__ == "__main__":
    main()
