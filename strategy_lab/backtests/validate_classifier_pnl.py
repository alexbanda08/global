"""
Validate per-wallet classifiers via PnL.

Hypothesis (from NEXT_SESSION_PICKUP_2026_05_20.md):
  Wallets profit because they pick profitable slugs. If we apply ACC-M only
  to the slugs our classifier predicts a wallet would engage, ACC-M PnL on
  that subset should beat random baseline and approach wallet-actual edge.

For each wallet:
  - Full-universe baseline    : mean PnL on all slugs in wallet's window
  - Classifier-top@20% / @50% : mean PnL on top-ranked slugs by classifier
  - Wallet-actual engagement  : mean PnL on slugs wallet actually engaged
  - Random baseline           : mean PnL on random subset of same size

Strategies: PAT+ACC-M (winner), ACC-M-sz20 (alone), MAS, ACC-PC.

Inputs:
  _fast_full_btc_full_btc5m.csv  + _fast_full_btc_full_btc15m.csv
  _wallet_selected_slugs.csv     (wallet, slug, engaged, prob_lr, prob_gb)
  _wallet_profile_per_slug_agg.csv

Output:
  _classifier_pnl_validation.csv  (one row per wallet × strategy × selection)

Usage:
    py -3 -X utf8 strategy_lab/backtests/validate_classifier_pnl.py
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "strategy_lab" / "backtests"

STRAT_FILES = {
    "5m": OUT_DIR / "_fast_full_btc_full_btc5m.csv",
    "15m": OUT_DIR / "_fast_full_btc_full_btc15m.csv",
}

# Which strategies to validate (must match strategy column values in fast_full_backtest CSVs)
STRATEGIES = ["PAT+ACC-M", "ACC-M-sz5", "ACC-M-sz20", "ACC-M-sz50",
              "ACC-M-sz100", "MAS-pre30", "ACC-PC"]


def load_strategy_pnl() -> pd.DataFrame:
    """Combine 5m + 15m strategy outputs into one frame."""
    parts = []
    for tf, p in STRAT_FILES.items():
        if not p.exists():
            print(f"  WARN missing {p}")
            continue
        df = pd.read_csv(p)
        df["tf"] = tf
        parts.append(df)
    if not parts:
        raise SystemExit("No fast_full_backtest outputs found")
    return pd.concat(parts, ignore_index=True)


def random_baseline_window(slugs_in_window: list, slugs_pnl: pd.DataFrame,
                            strategy: str, k: int, seed=42, n_trials=200):
    """Random-k baseline: pick k slugs from window uniformly, compute expected PnL.
    Non-firing slugs contribute $0 (expected PnL per slug)."""
    rng = np.random.default_rng(seed)
    pnl_map = slugs_pnl[slugs_pnl["strategy"] == strategy].set_index("slug")["pnl"].to_dict()
    arr = np.array(slugs_in_window)
    if len(arr) <= k:
        # use full set
        total = sum(pnl_map.get(s, 0.0) for s in arr) / max(len(arr), 1)
        return total, 0.0
    means = []
    for _ in range(n_trials):
        idx = rng.choice(len(arr), size=k, replace=False)
        means.append(np.mean([pnl_map.get(arr[i], 0.0) for i in idx]))
    return float(np.mean(means)), float(np.std(means))


def evaluate_subset(slugs_pnl: pd.DataFrame, strategy: str,
                    slug_subset: set, label: str) -> dict:
    """Evaluate expected PnL per slug: non-fires count as $0.
    Returns both fire-conditional and per-slug (expected) PnL."""
    sub = slugs_pnl[(slugs_pnl["strategy"] == strategy) &
                    (slugs_pnl["slug"].isin(slug_subset))]
    n_subset = len(slug_subset)
    n_fires = len(sub)
    if n_subset == 0:
        return {"label": label, "strategy": strategy, "n_subset": 0,
                "n_fires": 0, "fire_rate_pct": float("nan"),
                "pnl_per_slug_expected": float("nan"),
                "pnl_per_fire": float("nan"),
                "pnl_sum": float("nan")}
    pnl_sum = float(sub["pnl"].sum()) if not sub.empty else 0.0
    return {
        "label": label,
        "strategy": strategy,
        "n_subset": int(n_subset),
        "n_fires": int(n_fires),
        "fire_rate_pct": round(n_fires / n_subset * 100, 2),
        "pnl_per_slug_expected": round(pnl_sum / n_subset, 4),
        "pnl_per_fire": round(float(sub["pnl"].mean()) if not sub.empty else float("nan"), 4),
        "pnl_sum": round(pnl_sum, 2),
        "n_wins": int((sub["pnl"] > 0).sum()) if not sub.empty else 0,
        "win_rate_pct_fires": round(float((sub["pnl"] > 0).mean() * 100), 2) if not sub.empty else float("nan"),
    }


def main():
    print(f"[1/4] Loading strategy PnL ...")
    strat = load_strategy_pnl()
    print(f"      {len(strat)} (slug, strategy) rows across "
          f"{strat['strategy'].nunique()} strategies, "
          f"{strat['slug'].nunique()} unique slugs")

    print(f"[2/4] Loading classifier outputs ...")
    sel = pd.read_csv(OUT_DIR / "_wallet_selected_slugs.csv")
    prof = pd.read_csv(OUT_DIR / "_wallet_profile_per_slug_agg.csv")
    prof = prof[prof["asset_sym"] == "BTC"].copy()

    # Use prob_gb if present, fallback to prob_lr
    prob_col = "prob_gb" if "prob_gb" in sel.columns else "prob_lr"
    print(f"      Using probability column: {prob_col}")

    rows = []
    wallets = sel["wallet"].unique().tolist()

    print(f"[3/4] Evaluating per wallet × strategy × subset ...")
    for w in wallets:
        wsel = sel[sel["wallet"] == w].copy().sort_values(prob_col, ascending=False)
        n_total = len(wsel)
        n_eng = int(wsel["engaged"].sum())
        eng_slugs = set(wsel[wsel["engaged"] == 1]["slug"])
        all_slugs = set(wsel["slug"])

        print(f"\n  {w}: {n_eng}/{n_total} engaged, {n_total} slugs in window")

        for strategy in STRATEGIES:
            # 1. Wallet-window universe (apples-to-apples baseline)
            row = evaluate_subset(strat, strategy, all_slugs, "wallet_window_all")
            row["wallet"] = w
            row["pct_of_window"] = 100.0
            rows.append(row)

            # 2. Wallet-actual engagement
            row = evaluate_subset(strat, strategy, eng_slugs, "wallet_actual_engaged")
            row["wallet"] = w
            row["pct_of_window"] = round(n_eng / n_total * 100, 2)
            rows.append(row)

            # 3. Classifier top-k (k = 20% and 50% of window, and = n_eng)
            for k_pct in [10, 20, 30, 50]:
                k = max(1, int(k_pct / 100 * n_total))
                top_slugs = set(wsel.head(k)["slug"])
                row = evaluate_subset(strat, strategy, top_slugs,
                                      f"classifier_top@{k_pct}pct")
                row["wallet"] = w
                row["pct_of_window"] = k_pct
                rows.append(row)

            # 4. Classifier-matched-size (top-k where k = n_eng)
            top_n_slugs = set(wsel.head(n_eng)["slug"])
            row = evaluate_subset(strat, strategy, top_n_slugs,
                                  "classifier_top@n_engaged")
            row["wallet"] = w
            row["pct_of_window"] = round(n_eng / n_total * 100, 2)
            rows.append(row)

            # 5. Random baseline @ n_engaged — k random slugs from window, $0 for non-fires
            r_mean, r_std = random_baseline_window(
                list(all_slugs), strat, strategy, k=n_eng, seed=42)
            rows.append({
                "wallet": w, "strategy": strategy,
                "label": "random@n_engaged",
                "n_subset": n_eng, "n_fires": -1,
                "fire_rate_pct": float("nan"),
                "pnl_per_slug_expected": round(r_mean, 4),
                "pnl_per_fire": float("nan"),
                "pnl_sum": round(r_mean * n_eng, 2),
                "n_wins": -1, "win_rate_pct_fires": float("nan"),
                "pct_of_window": round(n_eng / n_total * 100, 2),
            })

    df = pd.DataFrame(rows)
    # Normalize column order (some labels missing fields filled with NaN)
    for col in ["wallet", "strategy", "label", "n_subset", "n_fires",
                "fire_rate_pct", "pct_of_window",
                "pnl_per_slug_expected", "pnl_per_fire", "pnl_sum",
                "n_wins", "win_rate_pct_fires"]:
        if col not in df.columns:
            df[col] = float("nan")
    df = df[["wallet", "strategy", "label", "n_subset", "n_fires",
             "fire_rate_pct", "pct_of_window",
             "pnl_per_slug_expected", "pnl_per_fire", "pnl_sum",
             "n_wins", "win_rate_pct_fires"]]

    out_p = OUT_DIR / "_classifier_pnl_validation.csv"
    df.to_csv(out_p, index=False)

    print(f"\n[4/4] Wrote {out_p}")

    # Pivot per wallet × strategy — EXPECTED PnL per slug (the apples-to-apples metric)
    print(f"\n{'='*100}")
    print("VALIDATION: Expected PnL per slug (non-fires count as $0)")
    print(f"{'='*100}")
    for w in wallets:
        print(f"\n--- {w} ---")
        sub = df[df["wallet"] == w].copy()
        piv = sub.pivot_table(index="label", columns="strategy",
                              values="pnl_per_slug_expected", aggfunc="first")
        order = ["wallet_window_all", "random@n_engaged",
                 "wallet_actual_engaged", "classifier_top@n_engaged",
                 "classifier_top@10pct", "classifier_top@20pct",
                 "classifier_top@30pct", "classifier_top@50pct"]
        order = [o for o in order if o in piv.index]
        piv = piv.reindex(order)
        print(piv.round(3).to_string())

    # Also pivot fire-rate
    print(f"\n{'='*100}")
    print("VALIDATION: Strategy fire-rate per subset (%)")
    print(f"{'='*100}")
    for w in wallets:
        print(f"\n--- {w} ---")
        sub = df[df["wallet"] == w].copy()
        piv = sub.pivot_table(index="label", columns="strategy",
                              values="fire_rate_pct", aggfunc="first")
        order = ["wallet_window_all", "wallet_actual_engaged",
                 "classifier_top@n_engaged",
                 "classifier_top@10pct", "classifier_top@20pct",
                 "classifier_top@30pct", "classifier_top@50pct"]
        order = [o for o in order if o in piv.index]
        piv = piv.reindex(order)
        print(piv.round(1).to_string())


if __name__ == "__main__":
    main()
