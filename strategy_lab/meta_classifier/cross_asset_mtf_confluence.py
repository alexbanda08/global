"""
Cross-asset RF + MTF (5m/15m) confluence analysis for binary up-down crypto markets.

Tasks 1-7 per CLAUDE-spec 2026-05-25:
  1. Cross-asset RF agreement (BTC/ETH/SOL rf_dir at fire_us)
  2. Multi-timeframe RF confluence (5m fire vs 15m-resampled RF)
  3. Cross-asset EMA stack confluence (tr_ema_stack_score)
  4. Combined max/strong/med confluence gates
  5. Strategy backtest on S1.5 with confluence_max / _strong
  6. S7 15m fires with cross-asset + 1h RF parent
  7. Report -> strategy_lab/reports/CROSS_ASSET_MTF_CONFLUENCE_2026_05_25.md
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\meta_classifier")
from compute_range_filter import _range_filter_loop

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
RESULTS_DIR = ROOT / "data" / "v4" / "canonical" / "_results"
REPORT_PATH = ROOT / "strategy_lab" / "reports" / "CROSS_ASSET_MTF_CONFLUENCE_2026_05_25.md"

RF_PANEL    = RESULTS_DIR / "range_filter_1s.parquet"
TR_PANEL    = RESULTS_DIR / "traders_reality_1s.parquet"
KLINES_1S   = ROOT / "data" / "v4" / "canonical" / "klines_1s" / "binance_1s_28d.parquet"
S15_FIRES   = RESULTS_DIR / "s15_with_ta_markov_rf.parquet"
S6_FIRES    = RESULTS_DIR / "s6_with_rf.parquet"
S7_FIRES    = RESULTS_DIR / "v15m_with_ta_markov_rf.parquet"

ASSETS = ("BTC", "ETH", "SOL")

# Output panels (15m / 1h resampled RF) — cache to disk for re-runs
RF_15M_PANEL = RESULTS_DIR / "range_filter_15m.parquet"
RF_1H_PANEL  = RESULTS_DIR / "range_filter_1h.parquet"


# ----------------------------- Resampled RF panel ----------------------------

def build_resampled_rf_panel(freq_us: int, n: int = 7, sn: int = 14, qty: float = 2.618,
                              tag: str = "15m") -> pd.DataFrame:
    """Resample 1s closes to `freq_us` (e.g. 15m=900_000_000 us, 1h=3_600_000_000 us)
    using LAST close per window, then run RF algorithm. Returns a panel with
    columns (asset, ts_us, rf_close, rf_dir) where ts_us is the START of the
    resampled bar (so the bar covers [ts_us, ts_us+freq_us))."""
    print(f"[rf{tag}] reading klines from {KLINES_1S.name}", flush=True)
    t0 = time.time()
    k = pd.read_parquet(KLINES_1S, columns=["symbol_id", "time_period_start_us", "price_close"])
    k = k.rename(columns={"time_period_start_us": "ts_us", "price_close": "close"})
    sym_to_asset = {
        "BINANCE_SPOT_BTC_USDT": "BTC",
        "BINANCE_SPOT_ETH_USDT": "ETH",
        "BINANCE_SPOT_SOL_USDT": "SOL",
    }
    k["asset"] = k["symbol_id"].map(sym_to_asset)
    k = k[k["asset"].notna()].copy()
    k = k.sort_values(["asset", "ts_us"]).reset_index(drop=True)
    print(f"[rf{tag}] {len(k):,} 1s rows in {time.time()-t0:.1f}s", flush=True)

    outs = []
    for asset, grp in k.groupby("asset", sort=False):
        ts = grp["ts_us"].to_numpy()
        cl = grp["close"].to_numpy(dtype=np.float64)
        # bucket: ts_us // freq_us
        buckets = ts // freq_us
        # take last close per bucket
        df = pd.DataFrame({"bucket": buckets, "close": cl})
        last = df.groupby("bucket", sort=True).agg({"close": "last"}).reset_index()
        last["bar_start_us"] = last["bucket"].astype(np.int64) * freq_us
        closes = last["close"].to_numpy(dtype=np.float64)

        rf_close, rf_hi, rf_lo, rf_r, rf_dir = _range_filter_loop(closes, n, sn, qty)

        outs.append(pd.DataFrame({
            "asset":    asset,
            "ts_us":    last["bar_start_us"].to_numpy().astype(np.int64),
            "rf_close": rf_close,
            "rf_dir":   rf_dir.astype(np.int8),
        }))
        print(f"[rf{tag}] {asset}: {len(closes):,} bars  dir+={int((rf_dir==1).sum())}  "
              f"dir-={int((rf_dir==-1).sum())}", flush=True)

    out = pd.concat(outs, ignore_index=True)
    return out


def get_or_build_resampled_rf(freq_us: int, path: Path, tag: str, n: int, sn: int) -> pd.DataFrame:
    if path.exists():
        print(f"[rf{tag}] loading cached {path.name}", flush=True)
        return pd.read_parquet(path)
    rf = build_resampled_rf_panel(freq_us, n=n, sn=sn, tag=tag)
    rf.to_parquet(path, compression="zstd", index=False)
    print(f"[rf{tag}] cached -> {path}", flush=True)
    return rf


# ----------------------------- Cross-asset merge -----------------------------

def add_xa_rf_dir(fires: pd.DataFrame, rf_panel: pd.DataFrame, freq_us: int = 1_000_000) -> pd.DataFrame:
    """For each fire, look up rf_dir of BTC, ETH, SOL at fire_us (causal, bar
    must have CLOSED before fire_us). Adds xa_btc_dir, xa_eth_dir, xa_sol_dir."""
    out = fires.copy()
    for ast in ASSETS:
        rg = rf_panel[rf_panel["asset"] == ast].copy()
        # bar covering [ts_us, ts_us+freq) closes at ts_us+freq, so key it there
        rg["key_us"] = rg["ts_us"].astype(np.int64) + int(freq_us)
        rg = rg[["key_us", "rf_dir"]].sort_values("key_us").reset_index(drop=True)
        rg = rg.rename(columns={"rf_dir": f"xa_{ast.lower()}_dir"})

        out_sorted = out.sort_values("fire_us").reset_index()
        merged = pd.merge_asof(
            out_sorted, rg,
            left_on="fire_us", right_on="key_us",
            direction="backward",
            tolerance=max(freq_us * 2, 5_000_000),
        )
        merged = merged.drop(columns=["key_us"], errors="ignore")
        merged = merged.sort_values("index").drop(columns=["index"]).reset_index(drop=True)
        out[f"xa_{ast.lower()}_dir"] = merged[f"xa_{ast.lower()}_dir"].to_numpy()
    return out


def add_xa_stack(fires: pd.DataFrame, tr_panel: pd.DataFrame) -> pd.DataFrame:
    """Add xa_btc_stack, xa_eth_stack, xa_sol_stack (tr_ema_stack_score at fire_us-1s)."""
    out = fires.copy()
    for ast in ASSETS:
        rg = tr_panel[tr_panel["asset"] == ast].copy()
        rg["key_us"] = rg["ts_us"].astype(np.int64) + 1_000_000
        rg = rg[["key_us", "tr_ema_stack_score"]].sort_values("key_us").reset_index(drop=True)
        rg = rg.rename(columns={"tr_ema_stack_score": f"xa_{ast.lower()}_stack"})

        out_sorted = out.sort_values("fire_us").reset_index()
        merged = pd.merge_asof(
            out_sorted, rg,
            left_on="fire_us", right_on="key_us",
            direction="backward",
            tolerance=5_000_000,
        )
        merged = merged.drop(columns=["key_us"], errors="ignore")
        merged = merged.sort_values("index").drop(columns=["index"]).reset_index(drop=True)
        out[f"xa_{ast.lower()}_stack"] = merged[f"xa_{ast.lower()}_stack"].to_numpy()
    return out


def add_mtf_rf(fires: pd.DataFrame, rf_panel: pd.DataFrame, freq_us: int, col_tag: str) -> pd.DataFrame:
    """Sample rf_dir at fire_us from a higher-tf resampled panel for the BET asset.
    Adds col `rf_{col_tag}_dir` (e.g. rf_15m_dir). Does NOT modify other cols."""
    out_col = f"rf_{col_tag}_dir"
    out = fires.copy()
    out[out_col] = np.nan
    for ast in fires["asset"].unique():
        rg = rf_panel[rf_panel["asset"] == ast].copy()
        rg["key_us"] = rg["ts_us"].astype(np.int64) + int(freq_us)
        rg = rg[["key_us", "rf_dir"]].sort_values("key_us").reset_index(drop=True)
        rg = rg.rename(columns={"rf_dir": "_mtf_dir"})

        mask = out["asset"] == ast
        sub = out.loc[mask, ["fire_us"]].reset_index()
        sub = sub.sort_values("fire_us")
        merged = pd.merge_asof(
            sub, rg,
            left_on="fire_us", right_on="key_us",
            direction="backward",
            tolerance=int(freq_us * 2),
        )
        merged = merged.sort_values("index")
        out.loc[merged["index"].to_numpy(), out_col] = merged["_mtf_dir"].to_numpy()
    return out


# ----------------------------- WR/PnL utilities ------------------------------

def wr_pnl(df: pd.DataFrame) -> dict:
    """Compute basic stats. Uses `won` and `pnl_legacy_usd`."""
    n = int(len(df))
    if n == 0:
        return {"n": 0, "wr": float("nan"), "sum_pnl": 0.0, "mean_pnl": float("nan")}
    won = df["won"].astype(bool)
    pnl = df["pnl_legacy_usd"].astype(float)
    return {
        "n": n,
        "wr": float(won.mean()),
        "sum_pnl": float(pnl.sum()),
        "mean_pnl": float(pnl.mean()),
    }


def cell_table(df: pd.DataFrame, mask: pd.Series, label: str,
                by_asset: bool = True, by_dir: bool = True) -> list[dict]:
    """Build a list of {label, asset, direction, n, wr, sum_pnl, mean_pnl} rows."""
    sub = df[mask].copy()
    rows = []
    rows.append({"cell": label, "asset": "ALL", "direction": "ALL", **wr_pnl(sub)})
    if by_asset:
        for ast in ASSETS:
            s = sub[sub["asset"] == ast]
            rows.append({"cell": label, "asset": ast, "direction": "ALL", **wr_pnl(s)})
    if by_dir:
        for d in ("UP", "DOWN"):
            s = sub[sub["direction"] == d]
            rows.append({"cell": label, "asset": "ALL", "direction": d, **wr_pnl(s)})
        for ast in ASSETS:
            for d in ("UP", "DOWN"):
                s = sub[(sub["asset"] == ast) & (sub["direction"] == d)]
                rows.append({"cell": label, "asset": ast, "direction": d, **wr_pnl(s)})
    return rows


# ----------------------------- Main analysis ---------------------------------

def main():
    t0 = time.time()
    print("[load] RF panel", flush=True)
    rf_1s = pd.read_parquet(RF_PANEL, columns=["asset", "ts_us", "rf_dir"])
    print(f"[load]   {len(rf_1s):,} rows", flush=True)

    print("[load] TR panel (subset)", flush=True)
    tr_1s = pd.read_parquet(TR_PANEL, columns=["asset", "ts_us", "tr_ema_stack_score"])
    print(f"[load]   {len(tr_1s):,} rows", flush=True)

    print("[load] S1.5 5m fires", flush=True)
    s15 = pd.read_parquet(S15_FIRES)
    s15 = s15[s15["rf_dir"].notna() & s15["pnl_legacy_usd"].notna()].copy()
    s15["rf_dir"] = s15["rf_dir"].astype(int)
    print(f"[load]   {len(s15):,} fires after cleanup", flush=True)

    # --------- TASK 1: cross-asset rf_dir at fire_us ---------
    print("[task1] cross-asset RF agreement on S1.5", flush=True)
    s15 = add_xa_rf_dir(s15, rf_1s, freq_us=1_000_000)
    bet_int = s15["direction"].map({"UP": 1, "DOWN": -1}).astype(int)
    s15["bet_int"] = bet_int

    # Cross-asset features
    btc_d = s15["xa_btc_dir"].fillna(0).astype(int)
    eth_d = s15["xa_eth_dir"].fillna(0).astype(int)
    sol_d = s15["xa_sol_dir"].fillna(0).astype(int)

    s15["xa_all_agree_up"]   = ((btc_d == 1) & (eth_d == 1) & (sol_d == 1))
    s15["xa_all_agree_dn"]   = ((btc_d == -1) & (eth_d == -1) & (sol_d == -1))
    s15["xa_majority_up"]    = (((btc_d == 1).astype(int) + (eth_d == 1).astype(int) + (sol_d == 1).astype(int)) >= 2)
    s15["xa_majority_dn"]    = (((btc_d == -1).astype(int) + (eth_d == -1).astype(int) + (sol_d == -1).astype(int)) >= 2)

    # bet asset RF dir IS already in rf_dir col; "others agree" = OTHER two assets agree with bet
    def others_agree_with_bet(row):
        b = row["bet_int"]
        a = row["asset"]
        d = {"BTC": row["xa_btc_dir"], "ETH": row["xa_eth_dir"], "SOL": row["xa_sol_dir"]}
        others = [int(v) if pd.notna(v) else 0 for k, v in d.items() if k != a]
        return all(o == b for o in others)

    s15["xa_self_with_others"] = s15.apply(others_agree_with_bet, axis=1)

    # xa_all_agree_with_bet (all three same direction as bet)
    s15["xa_all_with_bet"] = (
        (((btc_d == bet_int) & (eth_d == bet_int) & (sol_d == bet_int)))
    )
    # xa_majority_with_bet
    agree_cnt = ((btc_d == bet_int).astype(int)
                 + (eth_d == bet_int).astype(int)
                 + (sol_d == bet_int).astype(int))
    s15["xa_maj_with_bet"] = (agree_cnt >= 2)

    pct_all_agree = float(((s15["xa_all_agree_up"]) | (s15["xa_all_agree_dn"])).mean() * 100)
    pct_all_with_bet = float(s15["xa_all_with_bet"].mean() * 100)
    pct_maj_with_bet = float(s15["xa_maj_with_bet"].mean() * 100)
    print(f"[task1]   all 3 same dir = {pct_all_agree:.2f}%   "
          f"all3 == bet = {pct_all_with_bet:.2f}%   "
          f"majority == bet = {pct_maj_with_bet:.2f}%", flush=True)

    task1_rows = []
    task1_rows += cell_table(s15, pd.Series(True, index=s15.index), "baseline")
    task1_rows += cell_table(s15, s15["xa_all_with_bet"], "xa_all_with_bet")
    task1_rows += cell_table(s15, s15["xa_maj_with_bet"], "xa_maj_with_bet")
    task1_rows += cell_table(s15, s15["xa_self_with_others"], "xa_self_with_others")

    # --------- TASK 2: 15m-resampled RF for MTF confluence ---------
    print("[task2] building/loading 15m RF panel", flush=True)
    rf_15m = get_or_build_resampled_rf(15 * 60 * 1_000_000, RF_15M_PANEL, "15m", n=7, sn=14)

    s15 = add_mtf_rf(s15, rf_15m, freq_us=15 * 60 * 1_000_000, col_tag="15m")
    rf15_dir = s15["rf_15m_dir"].fillna(0).astype(int)
    s15["mtf_15m_with_bet"] = (rf15_dir == bet_int)
    # 5m rf_dir is in `rf_dir` already (from 1s panel)
    s15["mtf_5m_with_bet"]  = (s15["rf_dir"] == bet_int)
    s15["mtf_double_with"]  = (s15["mtf_5m_with_bet"] & s15["mtf_15m_with_bet"])

    task2_rows = []
    task2_rows += cell_table(s15, pd.Series(True, index=s15.index), "baseline")
    task2_rows += cell_table(s15, s15["mtf_5m_with_bet"], "mtf_5m_with_bet")
    task2_rows += cell_table(s15, s15["mtf_15m_with_bet"], "mtf_15m_with_bet")
    task2_rows += cell_table(s15, s15["mtf_double_with"],  "mtf_double_with")

    # --------- TASK 3: cross-asset EMA stack ---------
    print("[task3] cross-asset EMA stack on S1.5", flush=True)
    s15 = add_xa_stack(s15, tr_1s)
    btc_s = s15["xa_btc_stack"].fillna(0).astype(int)
    eth_s = s15["xa_eth_stack"].fillna(0).astype(int)
    sol_s = s15["xa_sol_stack"].fillna(0).astype(int)

    s15["xa_stack_all_bull"] = ((btc_s >= 1) & (eth_s >= 1) & (sol_s >= 1))
    s15["xa_stack_all_bear"] = ((btc_s <= -1) & (eth_s <= -1) & (sol_s <= -1))
    # stack-with-bet: stack >=1 if bet UP, <=-1 if bet DOWN
    bull_with_bet = ((bet_int == 1) & (btc_s >= 1) & (eth_s >= 1) & (sol_s >= 1))
    bear_with_bet = ((bet_int == -1) & (btc_s <= -1) & (eth_s <= -1) & (sol_s <= -1))
    s15["xa_stack_all_with_bet"] = (bull_with_bet | bear_with_bet)

    cnt_bull = ((btc_s >= 1).astype(int) + (eth_s >= 1).astype(int) + (sol_s >= 1).astype(int))
    cnt_bear = ((btc_s <= -1).astype(int) + (eth_s <= -1).astype(int) + (sol_s <= -1).astype(int))
    maj_bull_bet = ((bet_int == 1) & (cnt_bull >= 2))
    maj_bear_bet = ((bet_int == -1) & (cnt_bear >= 2))
    s15["xa_stack_maj_with_bet"] = (maj_bull_bet | maj_bear_bet)

    task3_rows = []
    task3_rows += cell_table(s15, pd.Series(True, index=s15.index), "baseline")
    task3_rows += cell_table(s15, s15["xa_stack_all_with_bet"], "xa_stack_all_with_bet")
    task3_rows += cell_table(s15, s15["xa_stack_maj_with_bet"], "xa_stack_maj_with_bet")

    # bet-asset stack agrees
    # Need to lookup bet asset's own tr_ema_stack_score — use xa_*_stack with own asset
    own_stack = pd.Series(np.nan, index=s15.index)
    for ast in ASSETS:
        mask = s15["asset"] == ast
        own_stack.loc[mask] = s15.loc[mask, f"xa_{ast.lower()}_stack"]
    s15["self_stack"] = own_stack
    bet_stack_with = (
        ((bet_int == 1) & (own_stack >= 1)) | ((bet_int == -1) & (own_stack <= -1))
    )
    s15["self_stack_with_bet"] = bet_stack_with

    # --------- TASK 4: combined confluence gates ---------
    print("[task4] confluence combo gates", flush=True)
    s15["confluence_max"]    = (s15["xa_all_with_bet"] & s15["mtf_15m_with_bet"] & s15["self_stack_with_bet"])
    s15["confluence_strong"] = (s15["xa_maj_with_bet"] & s15["self_stack_with_bet"])
    s15["confluence_med"]    = (s15["xa_self_with_others"])

    task4_rows = []
    for label in ("confluence_max", "confluence_strong", "confluence_med"):
        task4_rows += cell_table(s15, s15[label], label)

    # --------- TASK 5: standalone strategy with confluence ---------
    print("[task5] confluence-as-entry strategy", flush=True)
    # confluence_max
    task5_rows = []
    for label in ("confluence_max", "confluence_strong"):
        sub = s15[s15[label]]
        task5_rows.append({"strategy": label, "scope": "ALL", **wr_pnl(sub)})
        for ast in ASSETS:
            task5_rows.append({"strategy": label, "scope": ast, **wr_pnl(sub[sub["asset"] == ast])})
            for d in ("UP", "DOWN"):
                task5_rows.append({"strategy": label, "scope": f"{ast}_{d}",
                                   **wr_pnl(sub[(sub["asset"] == ast) & (sub["direction"] == d)])})

    # --------- TASK 6: S7 15m fires with cross-asset + 1h confluence ---------
    print("[task6] S7 15m fires with cross-asset + 1h RF", flush=True)
    s7 = pd.read_parquet(S7_FIRES)
    s7 = s7[s7["rf_dir"].notna() & s7["pnl_legacy_usd"].notna()].copy()
    s7["rf_dir"] = s7["rf_dir"].astype(int)
    s7["bet_int"] = s7["direction"].map({"UP": 1, "DOWN": -1}).astype(int)

    s7 = add_xa_rf_dir(s7, rf_1s, freq_us=1_000_000)
    btc7 = s7["xa_btc_dir"].fillna(0).astype(int)
    eth7 = s7["xa_eth_dir"].fillna(0).astype(int)
    sol7 = s7["xa_sol_dir"].fillna(0).astype(int)
    bet7 = s7["bet_int"]
    s7["xa_all_with_bet"] = (((btc7 == bet7) & (eth7 == bet7) & (sol7 == bet7)))
    agree7 = ((btc7 == bet7).astype(int) + (eth7 == bet7).astype(int) + (sol7 == bet7).astype(int))
    s7["xa_maj_with_bet"] = (agree7 >= 2)

    print("[task6] building/loading 1h RF panel", flush=True)
    rf_1h = get_or_build_resampled_rf(60 * 60 * 1_000_000, RF_1H_PANEL, "1h", n=4, sn=7)

    s7 = add_mtf_rf(s7, rf_1h, freq_us=60 * 60 * 1_000_000, col_tag="1h")
    rf1h_dir = s7["rf_1h_dir"].fillna(0).astype(int)
    s7["mtf_1h_with_bet"] = (rf1h_dir == bet7)
    s7["mtf_15m_native_with_bet"] = (s7["rf_dir"] == bet7)  # native 15m fires already have rf_dir

    task6_rows = []
    task6_rows.append({"cell": "S7_baseline", "scope": "ALL", **wr_pnl(s7)})
    for label in ("xa_all_with_bet", "xa_maj_with_bet", "mtf_1h_with_bet"):
        sub = s7[s7[label]]
        task6_rows.append({"cell": f"S7_{label}", "scope": "ALL", **wr_pnl(sub)})
        for ast in ASSETS:
            task6_rows.append({"cell": f"S7_{label}", "scope": ast,
                               **wr_pnl(sub[sub["asset"] == ast])})

    # S7 confluence combo
    s7["s7_confluence_max"]    = (s7["xa_all_with_bet"] & s7["mtf_1h_with_bet"])
    s7["s7_confluence_strong"] = (s7["xa_maj_with_bet"] & s7["mtf_1h_with_bet"])
    for label in ("s7_confluence_max", "s7_confluence_strong"):
        sub = s7[s7[label]]
        task6_rows.append({"cell": label, "scope": "ALL", **wr_pnl(sub)})
        for ast in ASSETS:
            task6_rows.append({"cell": label, "scope": ast,
                               **wr_pnl(sub[sub["asset"] == ast])})

    # --------- TASK 7: write report ---------
    print("[task7] writing report", flush=True)

    def df_md(rows: list[dict], cols: list[str]) -> str:
        if not rows:
            return "(no rows)\n"
        df = pd.DataFrame(rows)
        df = df[[c for c in cols if c in df.columns]]
        lines = []
        lines.append("| " + " | ".join(cols) + " |")
        lines.append("|" + "|".join(["---:" if c not in ("cell", "asset", "direction", "scope", "strategy") else "---"
                                     for c in cols]) + "|")
        for _, r in df.iterrows():
            vals = []
            for c in cols:
                v = r[c]
                if isinstance(v, float):
                    if c == "wr":
                        vals.append(f"{v*100:.2f}%")
                    else:
                        vals.append(f"{v:,.2f}")
                else:
                    vals.append(str(v))
            lines.append("| " + " | ".join(vals) + " |")
        return "\n".join(lines) + "\n"

    # Best confluence rule by sum_pnl (filter n>=30)
    best_rules = []
    for label in ("confluence_max", "confluence_strong", "confluence_med", "xa_all_with_bet",
                   "xa_maj_with_bet", "xa_self_with_others", "mtf_15m_with_bet",
                   "mtf_double_with", "xa_stack_all_with_bet", "xa_stack_maj_with_bet"):
        for ast in ASSETS:
            for d in ("UP", "DOWN"):
                sub = s15[(s15[label]) & (s15["asset"] == ast) & (s15["direction"] == d)]
                stats = wr_pnl(sub)
                if stats["n"] >= 30:
                    best_rules.append({"rule": label, "asset": ast, "dir": d, **stats})
    best_rules_sorted = sorted(best_rules, key=lambda r: -r["sum_pnl"])[:15]

    # Pareto: top WR rules with smallest n>=30
    pareto_rules = sorted(best_rules, key=lambda r: -r["wr"])[:15]

    # Baseline by asset/direction
    baseline_by_cell = []
    for ast in ASSETS:
        for d in ("UP", "DOWN"):
            sub = s15[(s15["asset"] == ast) & (s15["direction"] == d)]
            baseline_by_cell.append({"asset": ast, "dir": d, **wr_pnl(sub)})

    # Trending-market check: when xa_all_with_bet, what's the average BTC ret 5m before?
    # we already have rf_dist_bps, ribbon_lead_slope_bps on bet asset. Use those.
    trending_check = []
    for ast in ASSETS:
        sub_all  = s15[s15["asset"] == ast]
        sub_conf = sub_all[sub_all["xa_all_with_bet"]]
        if len(sub_all) > 0:
            base_slope = float(sub_all["ribbon_lead_slope_bps"].mean()) if "ribbon_lead_slope_bps" in sub_all.columns else float("nan")
            conf_slope = float(sub_conf["ribbon_lead_slope_bps"].mean()) if "ribbon_lead_slope_bps" in sub_conf.columns else float("nan")
            base_dist  = float(sub_all["rf_dist_bps"].abs().mean()) if "rf_dist_bps" in sub_all.columns else float("nan")
            conf_dist  = float(sub_conf["rf_dist_bps"].abs().mean()) if "rf_dist_bps" in sub_conf.columns else float("nan")
            trending_check.append({"asset": ast, "n_all": int(len(sub_all)), "n_conf": int(len(sub_conf)),
                                   "ribbon_slope_base": base_slope, "ribbon_slope_conf": conf_slope,
                                   "rf_dist_abs_base": base_dist, "rf_dist_abs_conf": conf_dist})

    # Build report
    rep = []
    rep.append("# Cross-asset & MTF confluence — S1.5 / S6 / S7  2026-05-25\n")
    rep.append("**Hypothesis**: agreement of RF/stack signals across BTC/ETH/SOL "
                "(and across 5m/15m/1h timeframes) at fire_us boosts conviction vs. "
                "bet-asset RF alone.\n")
    rep.append(f"**Universe**: S1.5 5m fires = {len(s15):,} (Apr 30 → May 22), "
                f"S7 15m fires = {len(s7):,}.\n")
    rep.append("**Fee model**: legacy 2%-on-profit (`pnl_legacy_usd`).\n")
    rep.append("**Causal**: rf/tr features at fire_us use the last fully-closed bar "
                "before fire_us (1s panel keyed at ts_us+1s; 15m panel keyed at "
                "bar_start+15m; 1h panel keyed at bar_start+1h).\n")

    rep.append("## 1. Cross-asset RF agreement frequencies\n")
    rep.append(f"- All three same direction (up OR down): **{pct_all_agree:.2f}%** of S1.5 fires\n")
    rep.append(f"- All three == bet direction: **{pct_all_with_bet:.2f}%**\n")
    rep.append(f"- Majority (2/3) == bet direction: **{pct_maj_with_bet:.2f}%**\n\n")
    rep.append("Baseline WR by (asset, direction):\n\n")
    rep.append(df_md(baseline_by_cell, ["asset", "dir", "n", "wr", "sum_pnl", "mean_pnl"]))

    rep.append("\n## 2. WR by cross-asset confluence level (S1.5)\n")
    rep.append(df_md(task1_rows, ["cell", "asset", "direction", "n", "wr", "sum_pnl", "mean_pnl"]))

    rep.append("\n## 3. MTF 5m/15m RF confluence (S1.5)\n")
    rep.append(df_md(task2_rows, ["cell", "asset", "direction", "n", "wr", "sum_pnl", "mean_pnl"]))

    rep.append("\n## 4. EMA stack cross-asset confluence (S1.5)\n")
    rep.append(df_md(task3_rows, ["cell", "asset", "direction", "n", "wr", "sum_pnl", "mean_pnl"]))

    rep.append("\n## 5. Combined confluence gates (S1.5)\n")
    rep.append(df_md(task4_rows, ["cell", "asset", "direction", "n", "wr", "sum_pnl", "mean_pnl"]))

    rep.append("\n## 6. Confluence as standalone entry strategy (S1.5)\n")
    rep.append(df_md(task5_rows, ["strategy", "scope", "n", "wr", "sum_pnl", "mean_pnl"]))

    rep.append("\n## 7. Top 15 sleeves by sum_pnl (n>=30)\n")
    rep.append(df_md(best_rules_sorted, ["rule", "asset", "dir", "n", "wr", "sum_pnl", "mean_pnl"]))

    rep.append("\n## 8. Top 15 sleeves by WR (n>=30)  — n-vs-WR Pareto\n")
    rep.append(df_md(pareto_rules, ["rule", "asset", "dir", "n", "wr", "sum_pnl", "mean_pnl"]))

    rep.append("\n## 9. S7 15m fires — cross-asset + 1h confluence\n")
    rep.append(df_md(task6_rows, ["cell", "scope", "n", "wr", "sum_pnl", "mean_pnl"]))

    rep.append("\n## 10. Trending-market check — is `xa_all_with_bet` just a trend detector?\n")
    rep.append("If `xa_all_with_bet` is mostly a re-encoding of bet-asset RF trend, the\n")
    rep.append("ribbon slope and |rf_dist_bps| should NOT diverge much between subset and base.\n\n")
    rep.append(df_md(trending_check, ["asset", "n_all", "n_conf", "ribbon_slope_base", "ribbon_slope_conf",
                                       "rf_dist_abs_base", "rf_dist_abs_conf"]))

    # Section 11: recommendation
    base_stats = wr_pnl(s15)
    conf_strong_stats = wr_pnl(s15[s15["confluence_strong"]])
    conf_max_stats    = wr_pnl(s15[s15["confluence_max"]])
    self_with_others_stats = wr_pnl(s15[s15["xa_self_with_others"]])
    mtf_double_stats  = wr_pnl(s15[s15["mtf_double_with"]])

    rep.append("\n## 11. Recommendation\n")
    rep.append(f"- **Baseline S1.5**: n={base_stats['n']}, WR={base_stats['wr']*100:.2f}%, "
                f"sum_pnl=${base_stats['sum_pnl']:.2f}, mean=${base_stats['mean_pnl']:.4f}\n")
    rep.append(f"- **xa_self_with_others**: n={self_with_others_stats['n']}, "
                f"WR={self_with_others_stats['wr']*100:.2f}%, sum=${self_with_others_stats['sum_pnl']:.2f}, "
                f"mean=${self_with_others_stats['mean_pnl']:.4f}, "
                f"WR delta vs baseline = {(self_with_others_stats['wr']-base_stats['wr'])*100:+.2f}pp\n")
    rep.append(f"- **mtf_double_with (5m+15m)**: n={mtf_double_stats['n']}, "
                f"WR={mtf_double_stats['wr']*100:.2f}%, sum=${mtf_double_stats['sum_pnl']:.2f}, "
                f"mean=${mtf_double_stats['mean_pnl']:.4f}, "
                f"WR delta vs baseline = {(mtf_double_stats['wr']-base_stats['wr'])*100:+.2f}pp\n")
    rep.append(f"- **confluence_strong**: n={conf_strong_stats['n']}, "
                f"WR={conf_strong_stats['wr']*100:.2f}%, sum=${conf_strong_stats['sum_pnl']:.2f}, "
                f"mean=${conf_strong_stats['mean_pnl']:.4f}, "
                f"WR delta vs baseline = {(conf_strong_stats['wr']-base_stats['wr'])*100:+.2f}pp\n")
    rep.append(f"- **confluence_max**: n={conf_max_stats['n']}, "
                f"WR={conf_max_stats['wr']*100:.2f}%, sum=${conf_max_stats['sum_pnl']:.2f}, "
                f"mean=${conf_max_stats['mean_pnl']:.4f}, "
                f"WR delta vs baseline = {(conf_max_stats['wr']-base_stats['wr'])*100:+.2f}pp\n")

    rep.append("\n## 12. Caveats\n")
    rep.append("- The S1.5 fires already encode a profitable filter (baseline WR is "
                "elevated because fires were pre-selected by S1.5 gates and ws_s alignment). "
                "Confluence rules add bias on top of an already-biased universe.\n")
    rep.append("- Cross-asset RF agreement is plausibly a **trending-market detector**. "
                "BTC pumps → ETH/SOL pump → all three RF=+1 simultaneously. Section 10 "
                "compares ribbon slope between the confluence subset and the full set "
                "to gauge how much of the lift is just \"market is trending\" already "
                "encoded in bet-asset features.\n")
    rep.append("- 15m and 1h RF panels were rebuilt from 1s closes with n smaller "
                "(n=7,sn=14 for 15m; n=4,sn=7 for 1h) since each bar represents 900s / 3600s "
                "of underlying movement; tuning n was NOT optimized — these are reasonable defaults.\n")
    rep.append("- All p-values would need bootstrap; this report only reports raw WR/PnL deltas.\n")
    rep.append("- Window = 2026-04-30 → 2026-05-22 (~22 days); out-of-sample validation pending.\n")

    REPORT_PATH.write_text("\n".join(rep), encoding="utf-8")
    print(f"[task7]   wrote {REPORT_PATH}", flush=True)
    print(f"[done] total {time.time()-t0:.1f}s", flush=True)

    # Echo a small summary to stdout for the parent agent
    print()
    print("==SUMMARY==")
    print(f"pct_all_with_bet     = {pct_all_with_bet:.2f}%")
    print(f"baseline_wr          = {base_stats['wr']*100:.2f}%  n={base_stats['n']}  sum_pnl={base_stats['sum_pnl']:.2f}")
    print(f"xa_all_with_bet      = {wr_pnl(s15[s15['xa_all_with_bet']])['wr']*100:.2f}%  n={wr_pnl(s15[s15['xa_all_with_bet']])['n']}  sum_pnl={wr_pnl(s15[s15['xa_all_with_bet']])['sum_pnl']:.2f}")
    print(f"xa_maj_with_bet      = {wr_pnl(s15[s15['xa_maj_with_bet']])['wr']*100:.2f}%  n={wr_pnl(s15[s15['xa_maj_with_bet']])['n']}  sum_pnl={wr_pnl(s15[s15['xa_maj_with_bet']])['sum_pnl']:.2f}")
    print(f"xa_self_with_others  = {self_with_others_stats['wr']*100:.2f}%  n={self_with_others_stats['n']}  sum_pnl={self_with_others_stats['sum_pnl']:.2f}")
    print(f"mtf_15m_with_bet     = {wr_pnl(s15[s15['mtf_15m_with_bet']])['wr']*100:.2f}%  n={wr_pnl(s15[s15['mtf_15m_with_bet']])['n']}  sum_pnl={wr_pnl(s15[s15['mtf_15m_with_bet']])['sum_pnl']:.2f}")
    print(f"mtf_double_with      = {mtf_double_stats['wr']*100:.2f}%  n={mtf_double_stats['n']}  sum_pnl={mtf_double_stats['sum_pnl']:.2f}")
    print(f"confluence_strong    = {conf_strong_stats['wr']*100:.2f}%  n={conf_strong_stats['n']}  sum_pnl={conf_strong_stats['sum_pnl']:.2f}")
    print(f"confluence_max       = {conf_max_stats['wr']*100:.2f}%  n={conf_max_stats['n']}  sum_pnl={conf_max_stats['sum_pnl']:.2f}")
    print(f"top_rule_sum_pnl     = {best_rules_sorted[0] if best_rules_sorted else None}")
    print(f"top_rule_wr          = {pareto_rules[0] if pareto_rules else None}")


if __name__ == "__main__":
    main()
