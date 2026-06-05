"""
Directional Up/Down strategy backtest — STAGE 2: strategy eval + gates + plateau.

Operates on the dirscan_<asset>_<tf>.parquet tables (stage 1). Cheap: every
strategy / threshold / offset is a pandas filter over recorded fills + signals.

Strategies (all = "buy the side Binance is leading toward"):
  mom_ema     : Up if ema9_slope_bps > 0 else Down
  mom_ret60   : Up if ret_60s_bps   > 0 else Down
  mom_strike  : Up if px_vs_strike_bps > 0 else Down  (binance already past strike)
  clbasis_rel : cl_basis minus its trailing baseline; Up if dev>+thr, Down if dev<-thr
                (cl_basis has a systematic +~13bps binance-vs-oracle offset, so the
                 tradeable signal is the DEVIATION from the ambient level, not sign)

Mean-reversion / fade strategies (hypothesis: pandagon wallet inverts momentum):
  fade_mom      : OPPOSITE of ema9_slope sign (Up if ema9_slope_bps < 0 else Down)
                  also covers fading ret_60s: use fade_ret60 variant
  fade_mom_cheap: same fade direction, but ONLY fires when faded side vwap < 0.55
                  (matches pandagon cheap-entry profile, px gate 0.12-0.55)

Universal gates (applied to every strategy):
  - side book must fill (u_ok / d_ok)
  - entry_px in [px_lo, px_hi]  (default 0.55-0.92 — drops late near-resolved & contrarian-cheap tails)
  - same-token spread (ask0-bid0) <= spread_thr   [asset: BTC/ETH 0.02, SOL 0.025]
  - cross-token variant ALSO reported: abs(u_vwap5-(1-d_vwap5)) <= 0.02  (live-conservative)

Robustness gates (cyclops):
  G1 mean PnL > 0 | G2 walkforward (>=75% test windows +) | G3 permutation p<0.05 | G4 bootstrap CI_lo>0
Plateau: sweep offset x px_lo x px_hi (x thr) -> fraction of cells +EV + worst cell.

Fees: LegacyConfig (2%-on-profit = production parity). LiveMimic (poly curve) reported as sensitivity.

Output: data/v4/canonical/_results/dir_eval_results.csv + per-cell plateau + JSON, and
        the report writer (write_report.py) renders markdown.

Usage:
  py -3 strategy_lab/directional_signal/eval_strategies.py            # all markets present
  py -3 strategy_lab/directional_signal/eval_strategies.py --markets btc_5m eth_15m
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
RES = ROOT / "data" / "v4" / "canonical" / "_results"

# cyclops gates (import; fallback to inline if package import fails)
try:
    from cyclops.validate.permutation import permutation_test
    from cyclops.validate.bootstrap import bootstrap_mean_ci
    from cyclops.validate.walkforward import walkforward_test
except Exception:
    def _settle_vec(won, shares, stake, fee=0.02):
        payoff = shares - stake
        return np.where(won, np.where(payoff > 0, payoff * (1 - fee), payoff), -stake)

    def permutation_test(fired, n_permutations=2000, seed=42, fee_rate=0.02):
        if fired.empty:
            return {"p_value": float("nan"), "observed_mean_pnl": float("nan"), "n_trades": 0}
        d = fired["direction"].values.astype("<U4"); o = fired["outcome_truth"].values.astype("<U4")
        sh = fired["shares"].values.astype(float); st = fired["stake_usd"].values.astype(float)
        obs = float(fired["pnl_usd"].values.mean()); rng = np.random.default_rng(seed)
        nm = np.empty(n_permutations)
        for i in range(n_permutations):
            p = rng.permutation(o)
            nm[i] = _settle_vec(d == p, sh, st, fee_rate).mean()
        return {"p_value": float((nm >= obs).sum() + 1) / (n_permutations + 1),
                "observed_mean_pnl": obs, "observed_wr": float((d == o).mean()), "n_trades": int(len(fired))}

    def bootstrap_mean_ci(fired, n_boot=10000, seed=42, alpha=0.05):
        if fired.empty:
            return {"ci_lower": float("nan"), "ci_upper": float("nan"), "observed_mean_pnl": float("nan")}
        pnl = fired["pnl_usd"].values.astype(float); n = pnl.size; rng = np.random.default_rng(seed)
        bm = pnl[rng.integers(0, n, size=(n_boot, n))].mean(axis=1)
        return {"ci_lower": float(np.quantile(bm, alpha / 2)), "ci_upper": float(np.quantile(bm, 1 - alpha / 2)),
                "observed_mean_pnl": float(pnl.mean())}

    def walkforward_test(fired, train_days=5, test_days=2, pass_threshold_frac=6 / 8):
        if fired.empty:
            return {"n_windows": 0, "n_positive": 0, "verdict": "no_trades", "frac_positive": float("nan")}
        df = fired.copy(); df["day_idx"] = (df["ws_s"] // 86400).astype(int)
        d0, d1 = df["day_idx"].min(), df["day_idx"].max(); cur = d0 + train_days; W = []
        while cur + test_days - 1 <= d1:
            sub = df[(df["day_idx"] >= cur) & (df["day_idx"] <= cur + test_days - 1)]
            if not sub.empty:
                W.append(sub["pnl_usd"].mean() > 0)
            cur += test_days
        nw = len(W); npos = sum(W)
        return {"n_windows": nw, "n_positive": npos,
                "frac_positive": (npos / nw) if nw else float("nan"),
                "verdict": "PASS" if nw >= 4 and npos / nw >= pass_threshold_frac else ("FAIL" if nw >= 4 else "insufficient_windows")}

SPREAD = {"btc": 0.02, "eth": 0.02, "sol": 0.025}
PX_LO, PX_HI = 0.55, 0.92
PRIMARY_OFFSET = {"5m": 60, "15m": 180}
FEE = 0.02


def settle_legacy(won, shares, stake, fee=FEE):
    payoff = shares - stake
    return np.where(won, np.where(payoff > 0, payoff * (1 - fee), payoff), -stake)


def settle_livemimic(won, shares, vwap, stake, rate=0.07):
    # poly_taker_curve: fee = shares*rate*p*(1-p) on entry (both legs); settlement no fee
    fee_in = shares * rate * vwap * (1 - vwap)
    gross_win = shares - stake
    return np.where(won, gross_win - fee_in, -stake - fee_in)


def settle_realistic(won, shares, vwap, stake, fee_rate=0.07, tx_cost=0.01):
    """Harsher cost model: real Polymarket taker curve fee=shares*0.07*p*(1-p)
    on entry PLUS $0.01 per trade (gas/relay/ops). Both win and lose pay entry fee.
    This is the stress-test model for Audit B — NOT the current production parity.
    Production currently uses 2%-on-profit-only (settle_legacy). See CLAUDE.md fee bullet.
    """
    fee_in = shares * fee_rate * vwap * (1 - vwap)
    gross_win = shares - stake
    return np.where(won, gross_win - fee_in, -stake - fee_in) - tx_cost


def trailing_baseline(slot, val, window=200):
    """trailing median of val ordered by slot (causal). returns aligned array."""
    s = pd.Series(val).reset_index(drop=True)
    return s.rolling(window, min_periods=20).median().shift(1).to_numpy()


def side_for(strategy, d, thr=None):
    if strategy == "mom_ema":
        return np.where(d["ema9_slope_bps"] > 0, "Up", "Down")
    if strategy == "mom_ret60":
        return np.where(d["ret_60s_bps"] > 0, "Up", "Down")
    if strategy == "mom_strike":
        return np.where(d["px_vs_strike_bps"] > 0, "Up", "Down")
    if strategy == "clbasis_rel":
        dord = d.sort_values("slot_start_s")
        base = trailing_baseline(dord["slot_start_s"].to_numpy(), dord["cl_basis_bps"].to_numpy())
        dev = pd.Series(dord["cl_basis_bps"].to_numpy() - base, index=dord.index).reindex(d.index)
        return np.where(dev > thr, "Up", np.where(dev < -thr, "Down", None))
    if strategy == "favorite":
        # buy the side the market favors (higher ask vwap = higher implied prob)
        return np.where(d["u_vwap"].fillna(0) >= d["d_vwap"].fillna(0), "Up", "Down")
    if strategy == "underdog":
        # buy the cheaper side (lower ask vwap = underdog)
        return np.where(d["u_vwap"].fillna(9) <= d["d_vwap"].fillna(9), "Up", "Down")
    if strategy == "cheap_mom":
        # buy momentum (ema9_slope) side, but ONLY when that side is cheap (<0.5)
        sgn = np.where(d["ema9_slope_bps"] > 0, "Up", "Down")
        side_px = np.where(sgn == "Up", d["u_vwap"], d["d_vwap"])
        return np.where(pd.Series(side_px, index=d.index) < 0.50, sgn, None)
    if strategy == "mom_ema_sel":
        # selective momentum: only fire when |ema9_slope| in the strong (top ~30%) trailing regime
        dord = d.sort_values("slot_start_s")
        absslope = dord["ema9_slope_bps"].abs().to_numpy()
        q = pd.Series(absslope).rolling(300, min_periods=30).quantile(0.70).shift(1).to_numpy()
        strong = pd.Series(absslope >= q, index=dord.index).reindex(d.index).fillna(False)
        sgn = np.where(d["ema9_slope_bps"] > 0, "Up", "Down")
        return np.where(strong.to_numpy(), sgn, None)
    if strategy == "fade_mom":
        # FADE ema9_slope: buy OPPOSITE side to momentum (mean-reversion hypothesis)
        return np.where(d["ema9_slope_bps"] < 0, "Up", "Down")
    if strategy == "fade_ret60":
        # FADE ret_60s: buy OPPOSITE side to 60s return
        return np.where(d["ret_60s_bps"] < 0, "Up", "Down")
    if strategy == "fade_mom_cheap":
        # FADE ema9_slope, but ONLY when the faded side is cheap (vwap < 0.55)
        # matches pandagon wallet profile: fades momentum AND enters cheap
        fade_sgn = np.where(d["ema9_slope_bps"] < 0, "Up", "Down")
        side_px = np.where(fade_sgn == "Up", d["u_vwap"].fillna(1.0), d["d_vwap"].fillna(1.0))
        return np.where(pd.Series(side_px, index=d.index) < 0.55, fade_sgn, None)
    raise ValueError(strategy)


def build_fired(d, side, asset, px_lo=PX_LO, px_hi=PX_HI, spread=None, cross_thr=None,
                cost_model="legacy"):
    """Build fired trades dataframe.
    cost_model: 'legacy' (2%-on-profit, production parity) | 'realistic' (taker-curve + $0.01 tx)
    """
    spread = SPREAD[asset] if spread is None else spread
    x = d.copy()
    x["side"] = side
    x = x[x["side"].notna() & (x["side"] != "None")].copy()
    # pick side fill
    is_up = x["side"] == "Up"
    x["ok"] = np.where(is_up, x.get("u_ok", False), x.get("d_ok", False))
    x = x[x["ok"].fillna(False)].copy()
    if x.empty:
        return x
    is_up = x["side"] == "Up"
    x["vwap"] = np.where(is_up, x["u_vwap"], x["d_vwap"])
    x["shares"] = np.where(is_up, x["u_shares"], x["d_shares"])
    x["stake_usd"] = np.where(is_up, x["u_usd"], x["d_usd"])
    x["ask0"] = np.where(is_up, x["u_ask0"], x["d_ask0"])
    x["bid0"] = np.where(is_up, x["u_bid0"], x["d_bid0"])
    # gates
    x = x[(x["vwap"] >= px_lo) & (x["vwap"] <= px_hi)]
    x = x[(x["ask0"] - x["bid0"]) <= spread]
    if cross_thr is not None and "u_vwap5" in x.columns:
        cross = (x["u_vwap5"] - (1 - x["d_vwap5"])).abs()
        x = x[cross <= cross_thr]
    if x.empty:
        return x
    x["direction"] = x["side"]
    x["won"] = x["direction"] == x["outcome_truth"]
    x["pnl_usd"] = settle_legacy(x["won"].values, x["shares"].values, x["stake_usd"].values)
    x["pnl_lm"] = settle_livemimic(x["won"].values, x["shares"].values, x["vwap"].values, x["stake_usd"].values)
    x["pnl_realistic"] = settle_realistic(x["won"].values, x["shares"].values, x["vwap"].values, x["stake_usd"].values)
    # active pnl column for gates: driven by cost_model arg
    if cost_model == "realistic":
        x["pnl_usd"] = x["pnl_realistic"]
    x["ws_s"] = x["slot_start_s"]
    return x


def run_gates(fired):
    if len(fired) < 10:
        return {"n": len(fired), "note": "n<10 (G0 fail)"}
    perm = permutation_test(fired, n_permutations=2000, seed=42)
    boot = bootstrap_mean_ci(fired, n_boot=10000, seed=42)
    wf = walkforward_test(fired, train_days=5, test_days=2)
    mean_pnl = float(fired["pnl_usd"].mean())
    # Also report legacy/realistic columns if both present
    legacy_mean = round(float(fired["pnl_usd"].mean()), 4)
    realistic_mean = round(float(fired["pnl_realistic"].mean()), 4) if "pnl_realistic" in fired.columns else None
    return {
        "n": int(len(fired)),
        "wr": round(float(fired["won"].mean()), 4),
        "mean_pnl_legacy": round(float(fired.get("pnl_usd", fired["pnl_usd"]).mean()), 4),
        "total_pnl_legacy": round(float(fired["pnl_usd"].sum()), 2),
        "mean_pnl_livemimic": round(float(fired["pnl_lm"].mean()), 4),
        "mean_pnl_realistic": realistic_mean,
        "mean_entry_px": round(float(fired["vwap"].mean()), 4),
        "G1_edge_sign": "PASS" if mean_pnl > 0 else "FAIL",
        "G2_walkforward": wf["verdict"], "G2_windows": f"{wf['n_positive']}/{wf['n_windows']}",
        "G3_perm_p": round(float(perm["p_value"]), 4),
        "G3_verdict": "PASS" if perm["p_value"] < 0.05 else "FAIL",
        "G4_ci_lo": round(float(boot["ci_lower"]), 4),
        "G4_ci_hi": round(float(boot["ci_upper"]), 4),
        "G4_verdict": "PASS" if boot["ci_lower"] > 0 else "FAIL",
    }


def plateau(d, strategy, asset, tf, offsets, thr=None, cost_model="legacy"):
    """Sweep offset x px_lo x px_hi -> grid of mean_pnl. Report frac +EV cells + worst."""
    los, his = STRAT_PLATEAU.get(strategy, ((0.50, 0.55, 0.60), (0.88, 0.92, 0.95)))
    cells = []
    for off in offsets:
        do = d[d["offset_s"] == off]
        if do.empty:
            continue
        side = side_for(strategy, do, thr=thr)
        for lo in los:
            for hi in his:
                fired = build_fired(do, side, asset, px_lo=lo, px_hi=hi, cost_model=cost_model)
                if len(fired) >= 10:
                    cells.append({"offset": off, "lo": lo, "hi": hi,
                                  "n": len(fired), "mean_pnl": round(float(fired["pnl_usd"].mean()), 4),
                                  "wr": round(float(fired["won"].mean()), 4)})
    if not cells:
        return {"n_cells": 0, "frac_positive": float("nan"), "verdict": "no_cells"}
    cg = pd.DataFrame(cells)
    frac = float((cg["mean_pnl"] > 0).mean())
    return {"n_cells": len(cg), "frac_positive": round(frac, 3),
            "worst_mean_pnl": round(float(cg["mean_pnl"].min()), 4),
            "best_mean_pnl": round(float(cg["mean_pnl"].max()), 4),
            "median_mean_pnl": round(float(cg["mean_pnl"].median()), 4),
            "verdict": "PASS" if frac >= 0.75 else ("WEAK" if frac >= 0.5 else "FAIL"),
            "cells": cells}


STRATS = ["mom_ema", "mom_ema_sel", "mom_ret60", "mom_strike", "clbasis_rel",
          "favorite", "underdog", "cheap_mom",
          "fade_mom", "fade_ret60", "fade_mom_cheap"]
CLBASIS_THR = 3.0
# strategy-specific entry-price gate (favorite lives >0.5, underdog/cheap_mom <0.5)
STRAT_PXGATE = {
    "favorite": (0.50, 0.92), "underdog": (0.12, 0.50), "cheap_mom": (0.12, 0.50),
    # fade strategies: unrestricted range for fade_mom/fade_ret60 (faded side can be any px)
    # fade_mom_cheap restricts to cheap side only
    "fade_mom_cheap": (0.12, 0.55),
}
# plateau price-range sweep per strategy (lo set, hi set)
STRAT_PLATEAU = {
    "favorite": ((0.50, 0.55, 0.60), (0.85, 0.90, 0.95)),
    "underdog": ((0.12, 0.20, 0.30), (0.45, 0.50, 0.55)),
    "cheap_mom": ((0.12, 0.20, 0.30), (0.45, 0.50, 0.55)),
    "fade_mom": ((0.50, 0.55, 0.60), (0.88, 0.92, 0.95)),
    "fade_ret60": ((0.50, 0.55, 0.60), (0.88, 0.92, 0.95)),
    "fade_mom_cheap": ((0.12, 0.20, 0.30), (0.45, 0.50, 0.55)),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--markets", nargs="+", default=None, help="e.g. btc_5m eth_15m; default=all present")
    ap.add_argument("--cost-model", choices=["legacy", "realistic"], default="legacy",
                    help="legacy=2%%-on-profit (production parity); realistic=taker-curve+$0.01tx (stress test)")
    args = ap.parse_args()
    cm = args.cost_model

    files = sorted(RES.glob("dirscan_*.parquet"))
    files = [f for f in files if "TEST" not in f.name]
    if args.markets:
        files = [f for f in files if f.stem.replace("dirscan_", "") in args.markets]
    if not files:
        print("No dirscan parquets found. Run directional_scan.py first."); return

    out_suffix = f"_{cm}" if cm != "legacy" else ""
    all_rows = []
    plateau_out = {}
    for f in files:
        mk = f.stem.replace("dirscan_", "")
        asset, tf = mk.split("_")
        d = pd.read_parquet(f)
        off = PRIMARY_OFFSET[tf]
        dp = d[d["offset_s"] == off].copy()
        print(f"\n=== {mk}  (n_slugs={d['slug'].nunique()}, primary offset={off}s, rows@off={len(dp)}, cost={cm}) ===")
        for strat in STRATS:
            thr = CLBASIS_THR if strat == "clbasis_rel" else None
            plo, phi = STRAT_PXGATE.get(strat, (PX_LO, PX_HI))
            side = side_for(strat, dp, thr=thr)
            fired = build_fired(dp, side, asset, px_lo=plo, px_hi=phi, cost_model=cm)
            g = run_gates(fired)
            # cross-token (live-conservative) variant
            fired_x = build_fired(dp, side, asset, px_lo=plo, px_hi=phi, cross_thr=0.02, cost_model=cm)
            g["n_crosstoken"] = int(len(fired_x))
            g["mean_pnl_crosstoken"] = round(float(fired_x["pnl_usd"].mean()), 4) if len(fired_x) >= 1 else None
            g.update({"market": mk, "asset": asset, "tf": tf, "strategy": strat, "cost_model": cm})
            all_rows.append(g)
            pl = plateau(d, strat, asset, tf, sorted(d["offset_s"].unique()), thr=thr, cost_model=cm)
            plateau_out[f"{mk}|{strat}"] = pl
            print(f"  {strat:12s} n={g.get('n',0):4d} WR={g.get('wr','-')} "
                  f"pnl=${g.get('mean_pnl_legacy','-')} G1={g.get('G1_edge_sign','-')} "
                  f"G3p={g.get('G3_perm_p','-')} G4lo={g.get('G4_ci_lo','-')} "
                  f"WF={g.get('G2_walkforward','-')} plateau={pl['verdict']}({pl.get('frac_positive')})")

    summary = pd.DataFrame(all_rows)
    out_csv = RES / f"dir_eval_results{out_suffix}.csv"
    out_json = RES / f"dir_eval_plateau{out_suffix}.json"
    summary.to_csv(out_csv, index=False)
    out_json.write_text(json.dumps(plateau_out, indent=2, default=str))
    print(f"\nWrote {out_csv} ({len(summary)} market-strategy rows)")
    print(f"Wrote {out_json}")


if __name__ == "__main__":
    main()
