"""Validation gauntlet for the 3-sleeve portfolio.

Gates:
  G1 - Permutation test: randomize outcome_up labels. Edge should vanish.
  G2 - Block bootstrap: 1000 resamples (1-day blocks) on holdout PnL.
  G3 - Realistic L10 book-walk fills: replace top-of-ask with book-walk VWAP.
  G4 - Multiple chronological splits: 60/40, 70/30, 80/20, 90/10.
  G5 - Per-day breakdown: how concentrated is PnL?
  G6 - Sample-size sensitivity: use 50/75/100% of train data.
  G7 - Magnitude robustness: BTC q8/q10/q12, ETH q3/q5/q7, SOL q12/q15/q18.
  G8 - Multi-horizon variants in portfolio: replace 1 sleeve with multi-horizon equivalent.
  G9 - Maker entry overlay: apply maker tick=0.01 wait=30s to portfolio cells.
  G10 - Stratified placebo: shuffle ret_5m within each (asset, day) bucket. Edge should vanish.
"""
from __future__ import annotations
import sys
sys.path.insert(0, ".")
from pathlib import Path
import numpy as np
import pandas as pd
from strategy_lab.v2_signals.common import load_features, ASSETS, chronological_split, DATA_DIR
from strategy_lab.book_walk import book_walk_fill

NOTIONAL = 25.0
FEE = 0.02

BEST_CELLS = {
    "btc_5m": {"asset": "btc", "tf": "5m", "mag": 0.10, "selector": "mag_only"},
    "eth_5m_q5": {"asset": "eth", "tf": "5m", "mag": 0.05, "selector": "mag_only"},
    "sol_5m": {"asset": "sol", "tf": "5m", "mag": 0.15, "selector": "mag_only"},
}


def filter_features(feats, cell):
    if cell["tf"] != "ALL":
        feats = feats[feats["timeframe"] == cell["tf"]]
    if cell["selector"] == "multi_horizon":
        same = ((feats["ret_5m"] > 0) & (feats["ret_15m"] > 0) & (feats["ret_1h"] > 0)) | \
               ((feats["ret_5m"] < 0) & (feats["ret_15m"] < 0) & (feats["ret_1h"] < 0))
        feats = feats[same]
    return feats


def apply_threshold(train, test, cell):
    if cell["mag"] > 0:
        thr = train["ret_5m"].abs().quantile(1 - cell["mag"])
        train_f = train[train["ret_5m"].abs() >= thr]
        test_f = test[test["ret_5m"].abs() >= thr]
    else:
        train_f, test_f = train, test
    return train_f, test_f


def evaluate_pnl(df, fill_col_yes="entry_yes_ask", fill_col_no="entry_no_ask"):
    if len(df) == 0:
        return df.assign(pnl_after=0.0, hit=False)
    pred_up = df["ret_5m"] > 0
    actual_up = df["outcome_up"] == 1
    hit = ((pred_up & actual_up) | (~pred_up & ~actual_up))
    cost = np.where(pred_up, df[fill_col_yes], df[fill_col_no])
    shares = NOTIONAL / cost
    payoff = np.where(hit, 1.0 - cost, -cost)
    pnl = shares * payoff
    pnl_after = np.where(pnl > 0, pnl * (1 - FEE), pnl)
    return df.assign(pnl_after=pnl_after, hit=hit)


def run_portfolio(cells, label="portfolio", outcome_override=None, ret_override=None):
    """Run the portfolio. Returns (train_df, holdout_df) with pnl + hit columns."""
    train_pieces, holdout_pieces = [], []
    for sleeve_name, cell in cells.items():
        feats = load_features(cell["asset"]).dropna(
            subset=["outcome_up", "ret_5m", "ret_15m", "ret_1h", "entry_yes_ask", "entry_no_ask"]
        )
        if outcome_override is not None:
            feats = feats.copy()
            feats["outcome_up"] = np.random.permutation(feats["outcome_up"].values)
        if ret_override is not None:
            feats = feats.copy()
            feats["ret_5m"] = np.random.permutation(feats["ret_5m"].values)
        feats = filter_features(feats, cell)
        if len(feats) < 50:
            continue
        train, holdout = chronological_split(feats)
        train_f, holdout_f = apply_threshold(train, holdout, cell)
        tr = evaluate_pnl(train_f).assign(sleeve=sleeve_name, split="train")
        ho = evaluate_pnl(holdout_f).assign(sleeve=sleeve_name, split="holdout")
        train_pieces.append(tr)
        holdout_pieces.append(ho)
    return (
        pd.concat(train_pieces, ignore_index=True) if train_pieces else pd.DataFrame(),
        pd.concat(holdout_pieces, ignore_index=True) if holdout_pieces else pd.DataFrame(),
    )


def summarize(df, label=""):
    if len(df) == 0:
        return {"label": label, "n": 0, "ROI": 0, "hit": 0, "pnl": 0}
    n = len(df)
    pnl = df["pnl_after"].sum()
    return {
        "label": label,
        "n": n,
        "ROI": round(pnl / (NOTIONAL * n) * 100, 2),
        "hit": round(df["hit"].sum() / n * 100, 1),
        "pnl": round(pnl, 2),
    }


# ============================================================
# Gates
# ============================================================

def g1_permutation(n_perms=200):
    """G1: Randomize outcome_up labels. Real ROI should crash to ~0."""
    print("\n[G1] Permutation test on outcome_up...")
    np.random.seed(42)
    base_ho_pnls = []
    for _ in range(n_perms):
        _, ho = run_portfolio(BEST_CELLS, outcome_override=True)
        base_ho_pnls.append(ho["pnl_after"].sum() if len(ho) else 0)
    base_ho_pnls = np.array(base_ho_pnls)
    real_tr, real_ho = run_portfolio(BEST_CELLS)
    real_pnl = real_ho["pnl_after"].sum()
    p_value = (base_ho_pnls >= real_pnl).mean()
    print(f"  Real holdout PnL: ${real_pnl:.2f}")
    print(f"  Permuted distribution: mean=${base_ho_pnls.mean():.2f}, std=${base_ho_pnls.std():.2f}")
    print(f"  Permutations >= real: {(base_ho_pnls >= real_pnl).sum()}/{n_perms} → p = {p_value:.4f}")
    return {"gate": "G1_permutation", "p_value": float(p_value), "real_pnl": real_pnl,
            "perm_mean": float(base_ho_pnls.mean()), "perm_std": float(base_ho_pnls.std())}


def g2_block_bootstrap(n_resamples=1000, block_days=1):
    """G2: Block-bootstrap by day. 95% CI on holdout PnL."""
    print("\n[G2] Block-bootstrap (1-day blocks) on holdout...")
    _, ho = run_portfolio(BEST_CELLS)
    if len(ho) == 0:
        return {"gate": "G2_bootstrap", "ci_low": 0, "ci_high": 0}
    ho = ho.copy()
    ho["window_start_dt"] = pd.to_datetime(ho["window_start_unix"], unit="s")
    ho["day"] = ho["window_start_dt"].dt.date
    days = ho["day"].unique()
    n_days = len(days)
    boot_pnls = []
    rng = np.random.default_rng(42)
    for _ in range(n_resamples):
        sample_days = rng.choice(days, size=n_days, replace=True)
        sampled = pd.concat([ho[ho["day"] == d] for d in sample_days])
        boot_pnls.append(sampled["pnl_after"].sum())
    ci_low, ci_high = np.percentile(boot_pnls, [2.5, 97.5])
    median = np.median(boot_pnls)
    print(f"  N holdout days: {n_days}, n markets: {len(ho)}")
    print(f"  Bootstrap median PnL: ${median:.2f}")
    print(f"  95% CI: [${ci_low:.2f}, ${ci_high:.2f}]")
    return {"gate": "G2_bootstrap", "median": float(median),
            "ci_low": float(ci_low), "ci_high": float(ci_high), "n_days": int(n_days)}


def g3_realistic_fills():
    """G3: Apply L10 book-walk fills using book_depth top levels."""
    print("\n[G3] Realistic L10 book-walk fills...")
    train_total, ho_total = 0, 0
    train_n, ho_n = 0, 0
    for sleeve_name, cell in BEST_CELLS.items():
        asset = cell["asset"]
        feats = load_features(asset).dropna(
            subset=["outcome_up", "ret_5m", "entry_yes_ask", "entry_no_ask"]
        )
        feats = filter_features(feats, cell)
        train, holdout = chronological_split(feats)
        thr = train["ret_5m"].abs().quantile(1 - cell["mag"])
        train_f = train[train["ret_5m"].abs() >= thr]
        holdout_f = holdout[holdout["ret_5m"].abs() >= thr]

        # Load book depth for this asset
        bd = pd.read_csv(DATA_DIR / "polymarket" / f"{asset}_book_depth_v3.csv")
        bd0 = bd[bd["bucket_10s"] == 0]
        bd_yes = bd0[bd0["outcome"] == "Up"].set_index("slug")
        bd_no = bd0[bd0["outcome"] == "Down"].set_index("slug")

        for split_label, df in [("train", train_f), ("holdout", holdout_f)]:
            tot_pnl = 0
            n_filled = 0
            for _, row in df.iterrows():
                slug = row["slug"]
                pred_up = row["ret_5m"] > 0
                bd_side = bd_yes if pred_up else bd_no
                if slug not in bd_side.index:
                    continue
                bdrow = bd_side.loc[slug]
                if isinstance(bdrow, pd.DataFrame):
                    bdrow = bdrow.iloc[0]
                ask_p = [bdrow.get(f"ask_price_{i}", np.nan) for i in range(10)]
                ask_s = [bdrow.get(f"ask_size_{i}", np.nan) for i in range(10)]
                vwap, shares, usd, _, _ = book_walk_fill(ask_p, ask_s, NOTIONAL)
                if shares == 0 or vwap == 0:
                    continue
                actual_up = row["outcome_up"] == 1
                hit = (pred_up and actual_up) or (not pred_up and not actual_up)
                payoff_per_share = (1.0 - vwap) if hit else (-vwap)
                pnl = shares * payoff_per_share
                if pnl > 0:
                    pnl *= (1 - FEE)
                tot_pnl += pnl
                n_filled += 1
            if split_label == "train":
                train_total += tot_pnl
                train_n += n_filled
            else:
                ho_total += tot_pnl
                ho_n += n_filled
    train_roi = train_total / (NOTIONAL * train_n) * 100 if train_n else 0
    ho_roi = ho_total / (NOTIONAL * ho_n) * 100 if ho_n else 0
    print(f"  Train: n={train_n}, PnL=${train_total:.2f}, ROI={train_roi:.2f}%")
    print(f"  Holdout: n={ho_n}, PnL=${ho_total:.2f}, ROI={ho_roi:.2f}%")
    return {"gate": "G3_real_fills", "train_roi": train_roi, "ho_roi": ho_roi,
            "train_n": train_n, "ho_n": ho_n}


def g4_multiple_splits():
    """G4: Test stability across different chronological split fractions."""
    print("\n[G4] Multiple chronological splits...")
    results = []
    for split_frac in [0.6, 0.7, 0.8, 0.9]:
        train_pnl_total, ho_pnl_total = 0, 0
        train_n_total, ho_n_total = 0, 0
        for cell in BEST_CELLS.values():
            feats = load_features(cell["asset"]).dropna(
                subset=["outcome_up", "ret_5m", "ret_15m", "ret_1h", "entry_yes_ask", "entry_no_ask"]
            )
            feats = filter_features(feats, cell)
            train, holdout = chronological_split(feats, train_frac=split_frac)
            thr = train["ret_5m"].abs().quantile(1 - cell["mag"]) if cell["mag"] > 0 else 0
            tr = train[train["ret_5m"].abs() >= thr]
            ho = holdout[holdout["ret_5m"].abs() >= thr]
            tr_e = evaluate_pnl(tr)
            ho_e = evaluate_pnl(ho)
            train_pnl_total += tr_e["pnl_after"].sum()
            ho_pnl_total += ho_e["pnl_after"].sum()
            train_n_total += len(tr_e)
            ho_n_total += len(ho_e)
        tr_roi = train_pnl_total / (NOTIONAL * train_n_total) * 100 if train_n_total else 0
        ho_roi = ho_pnl_total / (NOTIONAL * ho_n_total) * 100 if ho_n_total else 0
        print(f"  split={split_frac}: train n={train_n_total} ROI={tr_roi:.2f}% | "
              f"holdout n={ho_n_total} ROI={ho_roi:.2f}%")
        results.append({"split_frac": split_frac, "train_roi": tr_roi, "ho_roi": ho_roi,
                       "train_n": train_n_total, "ho_n": ho_n_total})
    return {"gate": "G4_multi_split", "splits": results}


def g5_per_day():
    """G5: Per-day breakdown of holdout PnL."""
    print("\n[G5] Per-day holdout breakdown...")
    _, ho = run_portfolio(BEST_CELLS)
    if len(ho) == 0:
        return {"gate": "G5_per_day"}
    ho = ho.copy()
    ho["day"] = pd.to_datetime(ho["window_start_unix"], unit="s").dt.date
    daily = ho.groupby("day").agg(
        n=("pnl_after", "count"),
        hit_pct=("hit", lambda x: round(x.sum() / len(x) * 100, 1)),
        pnl=("pnl_after", "sum"),
    ).round(2)
    print(daily.to_string())
    return {"gate": "G5_per_day", "days": daily.reset_index().to_dict(orient="records")}


def g6_sample_size():
    """G6: train on 50/75/100% of training, eval on full holdout."""
    print("\n[G6] Sample-size sensitivity...")
    for frac_of_train in [0.5, 0.75, 1.0]:
        ho_total = 0
        ho_n = 0
        for cell in BEST_CELLS.values():
            feats = load_features(cell["asset"]).dropna(
                subset=["outcome_up", "ret_5m", "ret_15m", "ret_1h", "entry_yes_ask", "entry_no_ask"]
            )
            feats = filter_features(feats, cell)
            train, holdout = chronological_split(feats)
            sub_train = train.iloc[-int(len(train) * frac_of_train):]
            thr = sub_train["ret_5m"].abs().quantile(1 - cell["mag"])
            ho_f = holdout[holdout["ret_5m"].abs() >= thr]
            ho_e = evaluate_pnl(ho_f)
            ho_total += ho_e["pnl_after"].sum()
            ho_n += len(ho_e)
        roi = ho_total / (NOTIONAL * ho_n) * 100 if ho_n else 0
        print(f"  train_frac_of_train={frac_of_train}: HO n={ho_n}, ROI={roi:.2f}%")


def g7_magnitude_robustness():
    """G7: Sensitivity of HO ROI to ±2pp magnitude."""
    print("\n[G7] Magnitude robustness (per-asset ±2pp)...")
    sensitivity = {
        "btc_5m": [0.08, 0.10, 0.12],
        "eth_5m": [0.03, 0.05, 0.07],
        "sol_5m": [0.12, 0.15, 0.18],
    }
    for sleeve, mags in sensitivity.items():
        cell_base = BEST_CELLS[next(k for k in BEST_CELLS if k.startswith(sleeve.split('_')[0]))]
        for m in mags:
            cell = {**cell_base, "mag": m}
            feats = load_features(cell["asset"]).dropna(
                subset=["outcome_up", "ret_5m", "ret_15m", "ret_1h", "entry_yes_ask", "entry_no_ask"]
            )
            feats = filter_features(feats, cell)
            train, holdout = chronological_split(feats)
            thr = train["ret_5m"].abs().quantile(1 - m)
            ho_f = holdout[holdout["ret_5m"].abs() >= thr]
            ho_e = evaluate_pnl(ho_f)
            n = len(ho_e)
            pnl = ho_e["pnl_after"].sum() if n else 0
            roi = pnl / (NOTIONAL * n) * 100 if n else 0
            hit = ho_e["hit"].sum() / n * 100 if n else 0
            print(f"  {cell['asset']} mag={m:.2f}: HO n={n} hit={hit:.1f}% ROI={roi:.2f}%")


def g8_multi_horizon_swap():
    """G8: Replace each sleeve with multi-horizon equivalent. Does it improve?"""
    print("\n[G8] Multi-horizon swap test...")
    for swap_sleeve, _ in BEST_CELLS.items():
        cells_swap = {**BEST_CELLS}
        cells_swap[swap_sleeve] = {**cells_swap[swap_sleeve], "selector": "multi_horizon"}
        _, ho = run_portfolio(cells_swap)
        roi = ho["pnl_after"].sum() / (NOTIONAL * len(ho)) * 100 if len(ho) else 0
        print(f"  swap {swap_sleeve} → multi_horizon: HO n={len(ho)}, ROI={roi:.2f}%")


def g9_maker_overlay():
    """G9: Apply maker entry overlay (tick=0.01, wait=30s, fb=taker)."""
    print("\n[G9] Maker entry overlay (tick=0.01, wait=30s, fb=taker)...")
    train_total, ho_total = 0, 0
    train_n, ho_n = 0, 0
    for sleeve_name, cell in BEST_CELLS.items():
        asset = cell["asset"]
        feats = load_features(asset).dropna(
            subset=["outcome_up", "ret_5m", "entry_yes_ask", "entry_no_ask"]
        )
        feats = filter_features(feats, cell)
        train, holdout = chronological_split(feats)
        thr = train["ret_5m"].abs().quantile(1 - cell["mag"])
        train_f = train[train["ret_5m"].abs() >= thr]
        holdout_f = holdout[holdout["ret_5m"].abs() >= thr]

        bd = pd.read_csv(DATA_DIR / "polymarket" / f"{asset}_book_depth_v3.csv")
        # Maker logic: try to buy at bid_0 + 0.01 in the 30s after window-start.
        # If ask drops to that level by bucket 3 (30s) -> fill at bid+0.01.
        # Else fall back to taker at original entry_yes_ask / entry_no_ask.
        bd_yes_window = bd[(bd["outcome"] == "Up") & (bd["bucket_10s"].isin([1, 2, 3]))]
        bd_no_window = bd[(bd["outcome"] == "Down") & (bd["bucket_10s"].isin([1, 2, 3]))]
        min_yes_in_window = bd_yes_window.groupby("slug")["ask_price_0"].min()
        min_no_in_window = bd_no_window.groupby("slug")["ask_price_0"].min()
        bd0_yes = bd[(bd["outcome"] == "Up") & (bd["bucket_10s"] == 0)].set_index("slug")["bid_price_0"]
        bd0_no = bd[(bd["outcome"] == "Down") & (bd["bucket_10s"] == 0)].set_index("slug")["bid_price_0"]

        for split_label, df in [("train", train_f), ("holdout", holdout_f)]:
            tot = 0
            n_done = 0
            for _, row in df.iterrows():
                slug = row["slug"]
                pred_up = row["ret_5m"] > 0
                actual_up = row["outcome_up"] == 1
                if pred_up:
                    bid0 = bd0_yes.get(slug)
                    min_ask = min_yes_in_window.get(slug)
                    taker_px = row["entry_yes_ask"]
                else:
                    bid0 = bd0_no.get(slug)
                    min_ask = min_no_in_window.get(slug)
                    taker_px = row["entry_no_ask"]
                if pd.isna(bid0) or pd.isna(taker_px):
                    continue
                quote_px = bid0 + 0.01
                if pd.notna(min_ask) and min_ask <= quote_px:
                    fill_px = quote_px  # maker filled
                else:
                    fill_px = taker_px  # taker fallback
                if fill_px <= 0 or fill_px >= 1:
                    continue
                shares = NOTIONAL / fill_px
                hit = (pred_up and actual_up) or (not pred_up and not actual_up)
                payoff = (1.0 - fill_px) if hit else (-fill_px)
                pnl = shares * payoff
                if pnl > 0:
                    pnl *= (1 - FEE)
                tot += pnl
                n_done += 1
            if split_label == "train":
                train_total += tot
                train_n += n_done
            else:
                ho_total += tot
                ho_n += n_done
    tr_roi = train_total / (NOTIONAL * train_n) * 100 if train_n else 0
    ho_roi = ho_total / (NOTIONAL * ho_n) * 100 if ho_n else 0
    print(f"  Train: n={train_n}, ROI={tr_roi:.2f}%")
    print(f"  Holdout: n={ho_n}, ROI={ho_roi:.2f}%")
    return {"gate": "G9_maker", "train_roi": tr_roi, "ho_roi": ho_roi}


def g10_ret_permutation():
    """G10: shuffle ret_5m within each (asset, day) bucket. The directional signal
    is destroyed but the magnitude distribution + outcomes are preserved."""
    print("\n[G10] Stratified ret_5m permutation (kills direction, preserves magnitude)...")
    np.random.seed(42)
    perms = []
    for _ in range(100):
        train_pnls, ho_pnls = [], []
        train_n, ho_n = 0, 0
        for cell in BEST_CELLS.values():
            feats = load_features(cell["asset"]).dropna(
                subset=["outcome_up", "ret_5m", "ret_15m", "ret_1h", "entry_yes_ask", "entry_no_ask"]
            ).copy()
            # Stratified shuffle of ret_5m within each day
            feats["day"] = pd.to_datetime(feats["window_start_unix"], unit="s").dt.date
            for day, idx in feats.groupby("day").groups.items():
                vals = feats.loc[idx, "ret_5m"].values
                feats.loc[idx, "ret_5m"] = np.random.permutation(vals)
            feats = filter_features(feats, cell)
            train, holdout = chronological_split(feats)
            thr = train["ret_5m"].abs().quantile(1 - cell["mag"])
            ho_f = holdout[holdout["ret_5m"].abs() >= thr]
            ho_e = evaluate_pnl(ho_f)
            ho_pnls.append(ho_e["pnl_after"].sum())
            ho_n += len(ho_e)
        perms.append(sum(ho_pnls))
    perms = np.array(perms)
    real_tr, real_ho = run_portfolio(BEST_CELLS)
    real_pnl = real_ho["pnl_after"].sum()
    p_value = (perms >= real_pnl).mean()
    print(f"  Real holdout PnL: ${real_pnl:.2f}")
    print(f"  Stratified-permuted distribution: mean=${perms.mean():.2f}, std=${perms.std():.2f}")
    print(f"  p_value: {p_value:.4f}")
    return {"gate": "G10_ret_perm", "p_value": float(p_value), "real_pnl": real_pnl,
            "perm_mean": float(perms.mean()), "perm_std": float(perms.std())}


def main():
    print("=" * 72)
    print("PORTFOLIO VALIDATION GAUNTLET — 3 sleeves: BTC q10 + ETH q5 + SOL q15")
    print("=" * 72)
    results = []
    results.append(g1_permutation(n_perms=200))
    results.append(g2_block_bootstrap(n_resamples=1000))
    results.append(g3_realistic_fills())
    results.append(g4_multiple_splits())
    results.append(g5_per_day())
    g6_sample_size()
    g7_magnitude_robustness()
    g8_multi_horizon_swap()
    results.append(g9_maker_overlay())
    results.append(g10_ret_permutation())

    print("\n" + "=" * 72)
    print("SUMMARY")
    print("=" * 72)
    for r in results:
        print(r)


if __name__ == "__main__":
    main()
