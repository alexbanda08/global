"""Deep inspect — find candidates passing core targets, examine per-day fire histograms."""
import pandas as pd, numpy as np

UNIV = "data/v4/canonical/_results/_sniper_eth5m_v3_universe.parquet"
RES = "strategy_lab/sniper_search_2026_05_27/eth_5m/_results"

df = pd.read_parquet(UNIV)
all_c = pd.read_csv(f"{RES}/all_candidates.csv")

# Sort by WR_lockbox * n_lockbox * dpt
all_c["score"] = all_c["lockbox_wr"] * all_c["lockbox_dpt_25"] * np.log(all_c["lockbox_n"].clip(lower=2))

print("== Top 30 by score (lockbox_n>=10 AND wr_lockbox>=0.75) ==")
m = (all_c["lockbox_n"] >= 10) & (all_c["lockbox_wr"] >= 0.75) & (all_c["lockbox_dpt_25"] >= 0)
sub = all_c[m].copy().sort_values("score", ascending=False).head(30)
cols = ["sleeve_id","offset_label","lockbox_n","lockbox_wr","lockbox_dpt_25","lockbox_sum_25",
        "lockbox_dd_25","lockbox_loss_streak","lockbox_sharpe","bootstrap_p_lockbox",
        "train_wr","train_n","val_wr","val_n","val_dpt_25"]
for _, r in sub.iterrows():
    print(f"  WR_lb={r['lockbox_wr']:.3f}  $/tr_lb=+{r['lockbox_dpt_25']:.2f}  n_lb={r['lockbox_n']}  dd=${r['lockbox_dd_25']:.1f}  ls={r['lockbox_loss_streak']}  sh={r['lockbox_sharpe']:.2f}  p={r['bootstrap_p_lockbox']:.3f}  | train WR={r['train_wr']:.3f} n={r['train_n']}  val WR={r['val_wr']:.3f} n={r['val_n']}  $/tr_v={r['val_dpt_25']:.2f}")
    print(f"    {r['sleeve_id']}")

print()
print("== Top 30 surviving ALL strict gates (n_lb 8-500, WR>=0.75, dpt>=3, dd>=-300, ls<=6, sh>=2, p<=0.05) ==")
m_all = (
    (all_c["lockbox_n"] >= 8) & (all_c["lockbox_n"] <= 500) &
    (all_c["lockbox_wr"] >= 0.75) &
    (all_c["lockbox_dpt_25"] >= 3.0) &
    (all_c["lockbox_dd_25"] >= -300) &
    (all_c["lockbox_loss_streak"] <= 6) &
    (all_c["lockbox_sharpe"] >= 2.0) &
    (all_c["bootstrap_p_lockbox"] <= 0.05)
)
print(f"  count: {m_all.sum()}")
for _, r in all_c[m_all].sort_values("score", ascending=False).head(30).iterrows():
    print(f"  WR_lb={r['lockbox_wr']:.3f}  $/tr_lb=+{r['lockbox_dpt_25']:.2f}  n_lb={r['lockbox_n']}  dd=${r['lockbox_dd_25']:.1f}  ls={r['lockbox_loss_streak']}  sh={r['lockbox_sharpe']:.2f}  p={r['bootstrap_p_lockbox']:.3f}")
    print(f"    {r['sleeve_id']}")

# also reverse-engineer the bootstrap p — it's failing because sharpe=0 → one-day distribution
# meaning all fires fall on a single day in lockbox. Let me look at per-day distribution for the top sleeve.
print()
print("== Per-day fire histogram for top candidate: ==")
def parse_gates(s):
    if "|" not in s: return []
    return s.split("|")[2].split("&")
if len(sub):
    top = sub.iloc[0]
    gates = parse_gates(top["sleeve_id"])
    print(f"Sleeve: {top['sleeve_id']}")
    print(f"Gates: {gates}")
    label = top["offset_label"]
    if label.startswith("bin_"):
        df_pool = df[df["offset_bin"] == label.replace("bin_", "")]
    elif label.startswith("off_"):
        df_pool = df[df["fire_offset_s"] == int(label.replace("off_", ""))]
    m_g = np.ones(len(df_pool), dtype=bool)
    for g in gates:
        m_g &= (df_pool[g].astype("float").fillna(0).values >= 1)
    sub_g = df_pool[m_g]
    print(f"Total fires across 33d: {len(sub_g)}")
    g = sub_g.groupby("day").agg(n=("won","count"), wr=("won","mean"), sum_pnl=("pnl_legacy_usd","sum")).round(3)
    print(g.to_string())
