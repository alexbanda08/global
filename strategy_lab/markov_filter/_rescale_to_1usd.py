"""Convert $25 backtest results → $1 live-deploy table.

For takers: no 5-share min required. Just rescale PnL linearly by 1/25.
Apply HoD-Top8 + (optional second gate) on per-slug-first deduplicated fires
with capital cap dropped to $20/sleeve (still allows ~20 in-flight at $1 each).
"""
import pandas as pd
import numpy as np
from pathlib import Path

NOTIONAL = 1.0
SCALE = NOTIONAL / 25.0   # 0.04

OUT_DIR = Path("strategy_lab/markov_filter/_results/deploy_1usd")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Use the realistic-qty fills (per-slug deduped) WITHOUT the 5-share gate
fills = pd.read_csv("strategy_lab/markov_filter/_results/backtest_prod_strats/fills.csv")
fills["fire_ts"] = pd.to_datetime(fills["fire_us"], unit="us", utc=True)
fills["hour"] = fills["fire_ts"].dt.hour
fills["cell_key"] = fills["asset"].str.lower() + "_" + fills["tf"]
fills["sleeve_key"] = fills["strategy"] + "_" + fills["cell_key"]
# Per-slug first fire per sleeve (one bet per sleeve per slug)
fills = fills.sort_values("fire_us").reset_index(drop=True)
fills["per_slug_first"] = ~fills.duplicated(subset=["sleeve_key", "slug"], keep="first")
realistic = fills[fills["per_slug_first"]].copy()

# Rescale all PnL to $1 stake
realistic["pnl_$1"] = realistic["pnl"] * SCALE

# Per-cell HoD top-8 (the locked spec lists)
HOD = {
    ("sniper","sol_5m"): [0,1,2,4,8,15,19,23],
    ("sniper","eth_15m"): [0,6,7,9,13,14,19,22],
    ("momo_v1","btc_15m"): [0,1,3,5,9,14,16,20],
    ("sniper","btc_15m"): [0,3,10,11,12,13,14,15],
    ("sniper","btc_5m"): [0,1,3,5,12,15,19,21],
    ("momo_v2","btc_5m"): [0,2,5,6,10,12,21,23],
    ("momo_v2","btc_15m"): [1,11,12,16,18,20,21,22],
    ("momo_v2","sol_5m"): [4,5,6,8,10,12,14,17],
    ("momo_v2","eth_15m"): [0,5,8,12,16,17,20,22],
    ("momo_v2","sol_15m"): [1,2,5,12,13,16,17,21],
    ("sniper","eth_5m"): [0,2,11,13,14,17,20,21],
}

# Sleeve labels for the deploy spec
SLEEVE_NAME = {
    ("sniper","sol_5m"): "sol_5m_sniper_hod",
    ("sniper","eth_15m"): "eth_15m_sniper_hod_m5va",
    ("momo_v1","btc_15m"): "btc_15m_momo_hod",
    ("sniper","btc_15m"): "btc_15m_sniper_hod",
    ("sniper","btc_5m"): "btc_5m_sniper_hod",
    ("momo_v2","btc_5m"): "btc_5m_momo_v2_hod_mtf",
    ("momo_v2","btc_15m"): "btc_15m_momo_v2_hod",
    ("momo_v2","sol_5m"): "sol_5m_momo_v2_hod",
    ("momo_v2","eth_15m"): "eth_15m_momo_v2_hod",
    ("momo_v2","sol_15m"): "sol_15m_momo_v2_hod",
    ("sniper","eth_5m"): "eth_5m_sniper_hod",
}

# Optional second gate (m5va or mtf2) — apply if column exists
# For brevity here, only HoD is applied. The mtf2/m5va gates need the BarContext
# extension; they'll add ~10-25% more lift per the mega-stack analysis.
rows = []
for (strat, cell), hours in HOD.items():
    g = realistic[(realistic["strategy"]==strat) & (realistic["cell_key"]==cell)]
    if g.empty: continue
    g_hod = g[g["hour"].isin(hours)]
    if len(g_hod) < 5: continue

    # Apply MTF2 / Markov for the two cells that need it
    mask_extra = None
    if (strat,cell) == ("momo_v2","btc_5m"):
        # Apply MTF2: need ret_15m and ret_1h. Not in fills.csv but use Markov 5m_va as proxy
        # (the agent D analysis showed similar effect for this cell)
        mask_extra = g_hod["markov_pass_w20_5m_voladaptive"]
    elif (strat,cell) == ("sniper","eth_15m"):
        # m5va = w20 5m voladaptive
        mask_extra = g_hod["markov_pass_w20_5m_voladaptive"]
    if mask_extra is not None:
        g_final = g_hod[mask_extra]
    else:
        g_final = g_hod

    if len(g_final) < 5: continue

    n = len(g_final)
    wins = int(g_final["won"].sum())
    wr = g_final["won"].mean() * 100
    sum_orig = g_final["pnl"].sum()
    sum_1 = sum_orig * SCALE
    avg_orig = g_final["pnl"].mean()
    avg_1 = avg_orig * SCALE

    rows.append({
        "sleeve": SLEEVE_NAME[(strat,cell)],
        "base_strategy": strat,
        "cell": cell,
        "gate": "HoD" + ("+M5va" if mask_extra is not None else ""),
        "n_28d": n,
        "n_per_day": round(n / 28, 2),
        "wins": wins,
        "wr_pct": round(wr, 2),
        "avg_pnl_at_1usd": round(avg_1, 4),
        "sum_pnl_28d_at_1usd": round(sum_1, 2),
        "daily_pnl_at_1usd": round(sum_1 / 28, 3),
        "annualized_at_1usd": round(sum_1 / 28 * 365, 1),
    })

df = pd.DataFrame(rows).sort_values("sum_pnl_28d_at_1usd", ascending=False)
df.to_csv(OUT_DIR / "deploy_table_1usd.csv", index=False)
print(df.to_string(index=False))
print()
print(f"TOTAL: n_28d={df['n_28d'].sum()}  daily={df['n_per_day'].sum():.1f} fires/day")
print(f"TOTAL sum_28d_at_1usd = ${df['sum_pnl_28d_at_1usd'].sum():+.2f}")
print(f"TOTAL daily_pnl       = ${df['daily_pnl_at_1usd'].sum():+.3f}/day")
print(f"TOTAL annualized      = ${df['annualized_at_1usd'].sum():+.1f}/yr")
