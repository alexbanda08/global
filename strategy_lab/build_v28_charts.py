"""Generate charts for the V28 PDF."""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

ROOT = Path(__file__).resolve().parent
OUT  = ROOT / "results" / "v28"
CHD  = OUT / "charts"
CHD.mkdir(parents=True, exist_ok=True)

plt.rcParams.update({
    "figure.figsize": (10, 5.5),
    "figure.dpi": 130,
    "savefig.dpi": 130,
    "font.size": 10,
    "axes.grid": True,
    "grid.alpha": 0.25,
})

PORTS = {
    "P1_2coin_SOL_SUI":          "P1: SUI + SOL",
    "P2_3coin_SOL_SUI_ETHdonch": "P2: SUI + SOL + ETH Donchian (recommended)",
    "P3_3coin_SOL_SUI_TONliq":   "P3: SUI + SOL + TON LiqSweep",
    "P4_4coin_SOL_SUI_TON_AVAX": "P4: SUI + SOL + TON + AVAX",
}

# 1. Blended equity curves of all 4 portfolios (log scale)
fig, ax = plt.subplots(figsize=(10, 5.5))
for key, label in PORTS.items():
    df = pd.read_csv(OUT / f"{key}_equity.csv", index_col=0, parse_dates=True)
    s = df.iloc[:, 0]
    ax.plot(s.index, s.values, label=label, linewidth=1.4)
ax.set_yscale("log")
ax.set_title("V28 blended portfolios — equity curves (log $1 start, yearly-rebalanced EW)")
ax.set_ylabel("Equity ($, log scale)")
ax.legend(loc="upper left", fontsize=9)
ax.xaxis.set_major_locator(mdates.YearLocator())
ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
fig.tight_layout()
fig.savefig(CHD / "v28_portfolio_equity.png")
plt.close(fig)

# 2. Per-year CAGR bar chart (stacked per portfolio)
import json
data = json.load(open(OUT / "winner_summary.json"))
years = [2020, 2021, 2022, 2023, 2024, 2025]
fig, ax = plt.subplots(figsize=(11, 5.5))
x = np.arange(len(years))
width = 0.2
for i, (key, label) in enumerate(PORTS.items()):
    ym = data[key]["year_metrics"]
    vals = [ym.get(str(y), ym.get(y, {"port_cagr": 0})).get("port_cagr", 0) for y in years]
    ax.bar(x + i*width - 1.5*width, vals, width, label=label)
ax.set_xticks(x)
ax.set_xticklabels([str(y) for y in years])
ax.axhline(100, color="red", linestyle="--", linewidth=1.2, label="100% target")
ax.set_ylabel("Portfolio CAGR (%)")
ax.set_title("V28 per-year CAGR — all 4 candidate portfolios vs 100% bar")
ax.legend(loc="upper left", fontsize=9)
fig.tight_layout()
fig.savefig(CHD / "v28_peryear_cagr.png")
plt.close(fig)

# 3. Per-sleeve 2023/24/25 CAGR heatmap for P2 (the recommended blend)
import json
fig, ax = plt.subplots(figsize=(9, 3.2))
sleeves = ["V23 SUI BBBreak 4h", "V23 SOL BBBreak 4h", "V27 ETH Donchian 4h"]
years = [2023, 2024, 2025]
mat = []
ym_p2 = data["P2_3coin_SOL_SUI_ETHdonch"]["year_metrics"]
for s in sleeves:
    row = []
    for y in years:
        v = ym_p2.get(str(y), ym_p2.get(y, {"members": {}}))["members"].get(s)
        row.append(v if v is not None else 0)
    mat.append(row)
mat = np.array(mat)
im = ax.imshow(mat, cmap="RdYlGn", aspect="auto", vmin=-50, vmax=400)
ax.set_xticks(range(len(years))); ax.set_xticklabels([str(y) for y in years])
ax.set_yticks(range(len(sleeves))); ax.set_yticklabels(sleeves)
for i in range(mat.shape[0]):
    for j in range(mat.shape[1]):
        ax.text(j, i, f"{mat[i,j]:+.1f}%", ha="center", va="center",
                color="black" if abs(mat[i,j]) < 200 else "white", fontsize=11)
ax.set_title("P2 per-sleeve per-year CAGR — diversification carries each year")
fig.colorbar(im, ax=ax, shrink=0.8, label="CAGR (%)")
fig.tight_layout()
fig.savefig(CHD / "v28_p2_heatmap.png")
plt.close(fig)

# 4. V27 Donchian winners table chart
df_v27 = pd.read_csv(ROOT / "results" / "v27" / "v27_oos_summary.csv")
# Only HTF_Donchian winners
wn = df_v27[(df_v27["family"]=="HTF_Donchian") & (df_v27["verdict"]=="✓ OOS holds")].copy()
fig, ax = plt.subplots(figsize=(10, 3.5))
x = np.arange(len(wn))
width = 0.35
ax.bar(x - width/2, wn["is_sh"], width, label="IS Sharpe (2020-23)", color="#3b82f6")
ax.bar(x + width/2, wn["oos_sh"], width, label="OOS Sharpe (2024-25)", color="#f59e0b")
ax.set_xticks(x); ax.set_xticklabels(wn["sym"])
ax.set_ylabel("Sharpe"); ax.set_title("V27 HTF Donchian 4h — IS vs OOS Sharpe (5 winners)")
ax.legend(loc="upper right")
ax.axhline(0, color="black", linewidth=0.6)
fig.tight_layout()
fig.savefig(CHD / "v27_donchian_winners.png")
plt.close(fig)

# 5. V26 OB leak illustration (before vs after fix) — from the audit CSV
audit = pd.read_csv(OUT / "peryear_audit.csv")
ob = audit[audit["family"]=="Order_Block"].copy()
if len(ob):
    fig, ax = plt.subplots(figsize=(10, 4))
    for _, r in ob.iterrows():
        label = f"{r['sym']} {r['tf']} (LEAKY)"
        ax.bar([f"{r['sym']}\n{r['tf']}"], [r["full_cagr"]], label=label)
    ax.set_yscale("log")
    ax.set_ylabel("Full-period CAGR (%)  [LOG SCALE]")
    ax.set_title("V26 Order Block — pre-fix numbers (all collapse to 0 after leak fix)")
    fig.tight_layout()
    fig.savefig(CHD / "v26_ob_leak.png")
    plt.close(fig)

# 6. Knowledge progression: full-period CAGR of winners per round
fig, ax = plt.subplots(figsize=(10, 4.5))
history = [
    ("V23 core (9 coins)",          [77.98, 124.42, 139.26, 63.52, 166.25, 160.41, 29.27, 77.53, 37.43]),
    ("V25 overlays (post-fix)",     [64.3,  20, 32.9,  19.4,  160]),
    ("V26 survivors (post-OB fix)", [64.3, 50.3]),
    ("V27 Donchian survivors",      [63.2, 58.4, 51.3, 44.7, 15.6]),
]
pos = np.arange(len(history))
for i, (lbl, cagrs) in enumerate(history):
    mn, mx, av = min(cagrs), max(cagrs), np.mean(cagrs)
    ax.scatter([i]*len(cagrs), cagrs, alpha=0.6, s=60)
    ax.plot([i, i], [mn, mx], alpha=0.3, color="black")
    ax.scatter([i], [av], marker="_", s=250, color="red", zorder=5)
ax.set_xticks(pos); ax.set_xticklabels([h[0] for h in history])
ax.set_ylabel("Full-period CAGR (net, %)")
ax.set_title("Strategy catalog growth — per-round individual CAGRs (red mark = avg)")
fig.tight_layout()
fig.savefig(CHD / "catalog_history.png")
plt.close(fig)

print("Charts written to", CHD)
for p in sorted(CHD.glob("*.png")):
    print(" ", p.name, p.stat().st_size, "bytes")
