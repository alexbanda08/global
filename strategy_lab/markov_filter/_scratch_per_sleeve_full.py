"""Per-sleeve full gate matrix.

Each sleeve = (asset, tf, version) gets its own table with all 10 filter modes.
Don't aggregate across sleeves — they're independent strategies.
"""
import pandas as pd
import numpy as np

f = pd.read_csv('strategy_lab/markov_filter/_results/full_universe_gate_compare/fires_with_gates.csv')
f["won"] = ((f["signal"] == "UP") & (f["outcome"] == "Up")) | \
          ((f["signal"] == "DOWN") & (f["outcome"] == "Down"))
f["pnl"] = np.where(f["won"], f["shares_e"] - f["usd_e"] - f["fee_in"],
                    -f["usd_e"] - f["fee_in"])

f["sleeve"] = f["asset"].str.lower() + "_" + f["tf"] + "_" + f["version"]

MARKOV_VARIANTS = ["w20_1m_voladaptive", "w20_1m_fixed",
                   "w20_5m_voladaptive", "w20_5m_fixed"]


def filter_buckets(sub):
    return [
        ("NO_FILTER",                         sub),
        ("F7_only",                           sub[sub.f7_pass]),
        ("MARKOV:w20_1m_voladaptive",         sub[sub.markov_pass_w20_1m_voladaptive]),
        ("MARKOV:w20_1m_fixed",               sub[sub.markov_pass_w20_1m_fixed]),
        ("MARKOV:w20_5m_voladaptive",         sub[sub.markov_pass_w20_5m_voladaptive]),
        ("MARKOV:w20_5m_fixed",               sub[sub.markov_pass_w20_5m_fixed]),
        ("F7+MARKOV:w20_1m_voladaptive",      sub[sub.f7_pass & sub.markov_pass_w20_1m_voladaptive]),
        ("F7+MARKOV:w20_1m_fixed",            sub[sub.f7_pass & sub.markov_pass_w20_1m_fixed]),
        ("F7+MARKOV:w20_5m_voladaptive",      sub[sub.f7_pass & sub.markov_pass_w20_5m_voladaptive]),
        ("F7+MARKOV:w20_5m_fixed",            sub[sub.f7_pass & sub.markov_pass_w20_5m_fixed]),
        # Inverse-F7 buckets (since F7 anti-correlates on backtest)
        ("notF7",                             sub[~sub.f7_pass]),
        ("notF7+MARKOV:w20_1m_voladaptive",   sub[~sub.f7_pass & sub.markov_pass_w20_1m_voladaptive]),
        ("notF7+MARKOV:w20_5m_voladaptive",   sub[~sub.f7_pass & sub.markov_pass_w20_5m_voladaptive]),
    ]


SLEEVES = sorted(f["sleeve"].unique())
print(f"Sleeves: {SLEEVES}")
print()

all_rows = []
for sleeve in SLEEVES:
    sub = f[f["sleeve"] == sleeve]
    n_total = len(sub)
    if n_total < 5:
        print(f"=== {sleeve} (n={n_total} — TOO SMALL, skipping) ===\n")
        continue
    print(f"=== {sleeve}  (n_base={n_total}) ===")
    rows = []
    for label, g in filter_buckets(sub):
        n = len(g)
        wins = int(g["won"].sum())
        pnl = float(g["pnl"].sum())
        rows.append({
            "filter": label, "n": n,
            "wr%": round(wins / n * 100, 2) if n else 0.0,
            "avg$": round(pnl / n, 3) if n else 0.0,
            "sum$": round(pnl, 2),
            "keep%": round(n / n_total * 100, 1),
        })
    df_sleeve = pd.DataFrame(rows)
    print(df_sleeve.to_string(index=False))
    # Best by sum$ with n>=10
    candidates = df_sleeve[df_sleeve["n"] >= 10]
    if not candidates.empty:
        best = candidates.loc[candidates["sum$"].idxmax()]
        baseline = df_sleeve[df_sleeve["filter"] == "NO_FILTER"].iloc[0]
        print(f"  → best (n>=10): {best['filter']}  "
              f"sum=${best['sum$']:+.2f}  avg=${best['avg$']:+.3f}  "
              f"(baseline=${baseline['avg$']:+.3f}, lift=${best['avg$'] - baseline['avg$']:+.3f}/trade)")
    print()

    # Track for cross-sleeve CSV
    for row in rows:
        row["sleeve"] = sleeve
        all_rows.append(row)

# Save combined CSV
out = pd.DataFrame(all_rows)[["sleeve","filter","n","wr%","avg$","sum$","keep%"]]
out.to_csv("strategy_lab/markov_filter/_results/full_universe_gate_compare/per_sleeve_full.csv", index=False)
print(f"wrote per_sleeve_full.csv ({len(out)} rows)")
