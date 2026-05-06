"""4h-timeframe strategy using GB-validated cross-asset signals.

Plugs the regime_detector_v2 GB winners (cross_institutional_lead + z_top_lsr_count
+ brigalS) into the existing perps_simulator_adaptive_exit engine. Adds the
R_3loss_pause equity-curve filter (from research_v5) as a thin wrapper around
the engine — the engine itself is NOT modified.

Differences from the v1 strategy_4h.py in this directory:
  - uses perps_simulator_adaptive_exit (per-vol-regime SL/TP/trail/hold)
  - threshold-continuum sweep instead of named-composite sweep (288 configs/sym)
  - integrated 10-gate gauntlet on the picked champion
  - tighter MDD target: -15% (handoff goal) instead of the original -30%

Usage:
    python strategy_lab/v4_signals/derivatives_zscore/strategy_4h_adaptive.py
    python strategy_lab/v4_signals/derivatives_zscore/strategy_4h_adaptive.py --symbols BTCUSDT
    python strategy_lab/v4_signals/derivatives_zscore/strategy_4h_adaptive.py --skip-gauntlet

Outputs (strategy_lab/reports/derivatives_zscore/4h_adaptive/):
    results.csv          — every sweep row
    champions.csv        — best variant per asset
    equity/{sym}.parquet
    gates_{sym}.json     — full 10-gate breakdown for the champion
    SUMMARY.md
"""
from __future__ import annotations

import argparse
import json
import sys
import warnings
from dataclasses import dataclass
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=RuntimeWarning)
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from strategy_lab.eval.perps_simulator_adaptive_exit import (
    REGIME_EXITS_4H,
    simulate_adaptive_exit,
)

PANELS = ROOT / "data" / "v4" / "derivatives_zscore" / "panels"
SPOT = ROOT / "data" / "v4" / "derivatives_zscore" / "spot"
OUT = ROOT / "strategy_lab" / "reports" / "derivatives_zscore" / "4h_adaptive"
EQ_DIR = OUT / "equity"
OUT.mkdir(parents=True, exist_ok=True)
EQ_DIR.mkdir(parents=True, exist_ok=True)

BARS_PER_DAY = 6
BARS_PER_YEAR = 6 * 365
FEE_HL_BPS_RT = 12.0  # Hyperliquid round-trip taker (4.5bp × 2 + 1.5bp slip × 2)


# ─────────────────────────────────────────────────────────────────────
# Data load
# ─────────────────────────────────────────────────────────────────────
def load_4h(symbol: str) -> pd.DataFrame:
    panel = pd.read_parquet(PANELS / f"{symbol}_zscore.parquet")
    panel_4h = panel.resample("4h").last()

    sym_short = symbol.replace("USDT", "")
    spot = pd.read_parquet(SPOT / f"BINANCE-{sym_short}-1h.parquet")
    spot = spot.set_index(pd.to_datetime(spot["time"], utc=True)).drop(columns=["time"])
    spot_4h = spot.resample("4h").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna()

    df = spot_4h.join(panel_4h, how="inner")
    df["price"] = df["close"]
    df["ret_4h"] = df["close"].pct_change()
    df["realized_vol_30d"] = (
        df["ret_4h"].rolling(30 * BARS_PER_DAY, min_periods=10 * BARS_PER_DAY).std()
        * np.sqrt(BARS_PER_YEAR)
    )
    df["vol_median"] = (
        df["realized_vol_30d"]
        .rolling(90 * BARS_PER_DAY, min_periods=30 * BARS_PER_DAY)
        .median()
    )
    df["ma_200d"] = df["close"].rolling(200 * BARS_PER_DAY).mean()
    return df.dropna(subset=["price", "z_lsr"])


def regime_labels_volquintile(df: pd.DataFrame) -> pd.Series:
    rv = df["realized_vol_30d"]
    q = rv.rank(pct=True)
    out = pd.Series("MedVol", index=df.index, dtype=object)
    out[q < 0.20] = "LowVol"
    out[(q >= 0.20) & (q < 0.40)] = "MedLowVol"
    out[(q >= 0.40) & (q < 0.60)] = "MedVol"
    out[(q >= 0.60) & (q < 0.80)] = "MedHighVol"
    out[q >= 0.80] = "HighVol"
    return out


# ─────────────────────────────────────────────────────────────────────
# Composite entry signal
# ─────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class SignalConfig:
    z_top_thr: float
    brigals_thr: float
    ci_thr: float
    use_ma200: bool
    use_lowvol: bool
    eqfilter: str  # "none" | "3loss" | "dd10" | "dd15"

    @property
    def use_eqfilter(self) -> bool:
        return self.eqfilter != "none"

    def name(self) -> str:
        parts = [
            f"zT{self.z_top_thr:+.1f}",
            f"bS{self.brigals_thr:+.1f}",
            f"ci{self.ci_thr:+.1f}",
        ]
        if self.use_ma200:
            parts.append("ma200")
        if self.use_lowvol:
            parts.append("lv")
        if self.eqfilter != "none":
            parts.append(self.eqfilter)
        return "_".join(parts)


def composite_signal(df: pd.DataFrame, cfg: SignalConfig) -> pd.Series:
    sig = (
        (df["z_top_lsr_count"] < cfg.z_top_thr)
        & (df["brigalS"] < cfg.brigals_thr)
        & (df["cross_institutional_lead"] > cfg.ci_thr)
    )
    if cfg.use_ma200:
        sig = sig & (df["price"] > df["ma_200d"])
    if cfg.use_lowvol:
        sig = sig & (df["realized_vol_30d"] < df["vol_median"])
    return sig.fillna(False).astype(bool)


# ─────────────────────────────────────────────────────────────────────
# Equity-curve filter wrappers — the only new feature on top of the engine
# ─────────────────────────────────────────────────────────────────────
def _sim_dde(df, sig, regime, fee_per_side):
    return simulate_adaptive_exit(
        df=df, long_entries=sig, short_entries=None,
        regime_labels=regime, fee=fee_per_side,
    )


def _apply_3loss_mask(trades: list[dict], long_entries: pd.Series) -> pd.Series | None:
    """Find the first 3-consecutive-losses streak and mask entries from that
    trade's exit bar onward. Returns None if no streak — caller should keep
    original results.

    Per research_v5.rm_apply, R_3loss_pause is a one-way circuit-breaker (once
    triggered, no new trade can land to refresh the buffer), so a single cutoff
    is the correct semantic.
    """
    if len(trades) < 3:
        return None
    for i in range(2, len(trades)):
        if all(t["ret"] < 0 for t in trades[i - 2 : i + 1]):
            cutoff_bar = trades[i]["exit_idx"]
            masked = long_entries.copy()
            masked.iloc[cutoff_bar:] = False
            return masked
    return None


def simulate_with_eqfilter(
    df: pd.DataFrame,
    long_entries: pd.Series,
    regime_labels: pd.Series,
    fee_bps_rt: float = FEE_HL_BPS_RT,
    eqfilter: str = "none",
    dd_max_iters: int = 6,
) -> tuple[list[dict], pd.Series]:
    """Wrap simulate_adaptive_exit with an equity-curve filter.

    eqfilter:
      "none"   — no filter (engine raw)
      "3loss"  — R_3loss_pause: stop after 3 consecutive losses (one-way)
      "dd10"   — R_dd_pause at -10%: block entries while equity DD < -10%,
                 unblock when DD recovers above -10% (recoverable, iterative)
      "dd15"   — same as dd10 but threshold -15%
    """
    fee_per_side = (fee_bps_rt / 2.0) / 10_000.0

    if eqfilter == "none":
        return _sim_dde(df, long_entries, regime_labels, fee_per_side)

    if eqfilter == "3loss":
        trades, eq = _sim_dde(df, long_entries, regime_labels, fee_per_side)
        masked = _apply_3loss_mask(trades, long_entries)
        if masked is None:
            return trades, eq
        return _sim_dde(df, masked, regime_labels, fee_per_side)

    if eqfilter in ("dd10", "dd15"):
        # Iterative entry-mask: each pass uses the previous pass's DD to decide
        # which bars to block. Converges in 2-6 iters since masking entries
        # monotonically reduces (or holds) the trade set.
        dd_thr = -0.10 if eqfilter == "dd10" else -0.15
        sig = long_entries.copy().astype(bool)
        prev_count = -1
        for _ in range(dd_max_iters):
            trades, eq = _sim_dde(df, sig, regime_labels, fee_per_side)
            peak = eq.cummax()
            dd = (eq - peak) / peak.replace(0, np.nan)
            # mask entry bars where the prev-pass equity DD breached the floor
            new_sig = (long_entries.astype(bool)) & (dd > dd_thr).reindex(long_entries.index).fillna(True)
            cnt = int(new_sig.sum())
            if cnt == prev_count:
                break
            prev_count = cnt
            sig = new_sig
        return trades, eq

    raise ValueError(f"unknown eqfilter: {eqfilter}")


# Back-compat alias (used by walk-forward / param-sens)
def simulate_with_3loss_pause(
    df, long_entries, regime_labels, fee_bps_rt=FEE_HL_BPS_RT, use_eqfilter=True
):
    return simulate_with_eqfilter(
        df, long_entries, regime_labels, fee_bps_rt,
        eqfilter="3loss" if use_eqfilter else "none",
    )


def apply_idle_carry(
    eq: pd.Series, trades: list[dict], idx: pd.DatetimeIndex,
    apr: float = 0.05,
) -> pd.Series:
    """Post-process equity to add stablecoin-carry yield on idle bars.

    On bars where no position is open, the cash that's NOT in margin earns
    `apr` annualized (compounded per 4h bar). Approximation: assumes 100% of
    equity earns yield on idle bars (true since pos is closed = all is cash),
    and 0% during open positions (conservative — real margin is ~33% so 67% of
    cash would still earn).
    """
    if apr <= 0 or len(eq) == 0:
        return eq

    n = len(idx)
    bar_yield = (1.0 + apr) ** (1.0 / BARS_PER_YEAR) - 1.0
    in_trade = np.zeros(n, dtype=bool)
    for t in trades:
        i0 = max(0, int(t["entry_idx"]))
        i1 = min(n - 1, int(t["exit_idx"]))
        in_trade[i0 : i1 + 1] = True

    eq_arr = eq.to_numpy(dtype=float)
    out = np.empty(n, dtype=float)
    out[0] = eq_arr[0]
    for i in range(1, n):
        delta = eq_arr[i] - eq_arr[i - 1]
        if in_trade[i]:
            out[i] = out[i - 1] + delta
        else:
            out[i] = out[i - 1] * (1.0 + bar_yield) + delta
    return pd.Series(out, index=idx, name="equity")


def simulate_with_eqfilter_and_carry(
    df, long_entries, regime_labels,
    fee_bps_rt: float = FEE_HL_BPS_RT,
    eqfilter: str = "none",
    idle_apr: float = 0.0,
) -> tuple[list[dict], pd.Series]:
    trades, eq = simulate_with_eqfilter(df, long_entries, regime_labels, fee_bps_rt, eqfilter)
    if idle_apr > 0:
        eq = apply_idle_carry(eq, trades, df.index, apr=idle_apr)
    return trades, eq


# ─────────────────────────────────────────────────────────────────────
# Stats / metrics
# ─────────────────────────────────────────────────────────────────────
def core_stats(eq: pd.Series, trades: list[dict], df: pd.DataFrame) -> dict:
    bh = float(df["close"].iloc[-1] / df["close"].iloc[0])
    if not trades:
        return {
            "n_trades": 0, "win_rate": 0.0, "profit_factor": 0.0,
            "sharpe": 0.0, "calmar": 0.0, "max_dd": 0.0, "cagr": 0.0,
            "final_eq_x": float(eq.iloc[-1] / eq.iloc[0]),
            "buy_hold_x": bh,
            "outperform": float(eq.iloc[-1] / eq.iloc[0]) / bh,
            "median_hold_h": 0.0, "expectancy": 0.0,
        }

    rets = np.array([t["ret"] for t in trades])
    wins = rets > 0
    pf_num = rets[wins].sum() if wins.any() else 0.0
    pf_den = -rets[~wins].sum() if (~wins).any() else 0.0
    pf = float(pf_num / pf_den) if pf_den > 0 else (float("inf") if pf_num > 0 else 0.0)

    daily = eq.resample("1D").last().dropna()
    drets = daily.pct_change().dropna()
    sharpe = float(drets.mean() / drets.std() * np.sqrt(365)) if drets.std() > 0 else 0.0

    peak = eq.cummax()
    dd = (eq - peak) / peak
    mdd = float(dd.min())

    years = max(1e-6, (eq.index[-1] - eq.index[0]).total_seconds() / (365.25 * 86400))
    total_ret = float(eq.iloc[-1] / eq.iloc[0]) - 1
    cagr = float((1 + total_ret) ** (1 / years) - 1)
    cal = float(cagr / abs(mdd)) if mdd < 0 else 0.0

    return {
        "n_trades": len(trades),
        "win_rate": float(wins.mean()),
        "profit_factor": pf,
        "sharpe": sharpe,
        "calmar": cal,
        "max_dd": mdd,
        "cagr": cagr,
        "final_eq_x": float(eq.iloc[-1] / eq.iloc[0]),
        "buy_hold_x": bh,
        "outperform": float(eq.iloc[-1] / eq.iloc[0]) / bh,
        "median_hold_h": float(np.median([t["bars"] for t in trades])) * 4.0,
        "expectancy": float(rets.mean()),
    }


# ─────────────────────────────────────────────────────────────────────
# 10-gate evaluation
# ─────────────────────────────────────────────────────────────────────
def permutation_test(rets: pd.Series, n_iter: int = 500, seed: int = 42) -> dict:
    if len(rets) < 100 or rets.std() == 0:
        return {"p_value": 1.0, "real_sharpe": 0.0}
    rng = np.random.default_rng(seed)
    real = float(rets.mean() / rets.std() * np.sqrt(365))
    arr = rets.to_numpy().copy()
    cnt = 0
    for _ in range(n_iter):
        rng.shuffle(arr)
        s = pd.Series(arr)
        sh = float(s.mean() / s.std() * np.sqrt(365)) if s.std() > 0 else 0.0
        if sh >= real:
            cnt += 1
    return {"p_value": (cnt + 1) / (n_iter + 1), "real_sharpe": real}


def block_bootstrap_sharpe_ci(rets: pd.Series, n_iter: int = 1000, block: int = 24) -> dict:
    if len(rets) < block * 4:
        return {"ci_lo": -1.0, "ci_hi": 1.0}
    rng = np.random.default_rng(42)
    arr = rets.to_numpy()
    n = len(arr)
    n_blocks = max(1, n // block)
    sharpes = []
    for _ in range(n_iter):
        starts = rng.integers(0, max(1, n - block), size=n_blocks)
        sample = np.concatenate([arr[s : s + block] for s in starts])
        s = pd.Series(sample)
        sh = float(s.mean() / s.std() * np.sqrt(365)) if s.std() > 0 else 0.0
        sharpes.append(sh)
    sharpes = np.array(sharpes)
    return {"ci_lo": float(np.quantile(sharpes, 0.05)),
            "ci_hi": float(np.quantile(sharpes, 0.95))}


def per_year_stats(eq: pd.Series) -> dict:
    daily = eq.resample("1D").last().dropna()
    drets = daily.pct_change().dropna()
    out = {}
    for y, sub in drets.groupby(drets.index.year):
        sh = float(sub.mean() / sub.std() * np.sqrt(365)) if sub.std() > 0 else 0.0
        out[int(y)] = {"sharpe": sh, "n_days": len(sub)}
    return out


def walk_forward_efficiency(
    df: pd.DataFrame, cfg: SignalConfig, regime: pd.Series, n_folds: int = 6
) -> dict:
    n = len(df)
    fold = n // (n_folds + 1)
    folds = []
    full_sig = composite_signal(df, cfg)
    for k in range(n_folds):
        lo = (k + 1) * fold
        hi = min((k + 2) * fold, n)
        if hi <= lo + 100:
            continue
        sub = df.iloc[lo:hi]
        tr, eq = simulate_with_eqfilter(
            sub, full_sig.loc[sub.index], regime.loc[sub.index],
            eqfilter=cfg.eqfilter,
        )
        d = eq.resample("1D").last().dropna().pct_change().dropna()
        sh = float(d.mean() / d.std() * np.sqrt(365)) if d.std() > 0 else 0.0
        folds.append({"fold": k + 1, "sharpe": sh, "n_trades": len(tr)})

    full_tr, full_eq = simulate_with_eqfilter(df, full_sig, regime, eqfilter=cfg.eqfilter)
    full_d = full_eq.resample("1D").last().dropna().pct_change().dropna()
    is_sh = float(full_d.mean() / full_d.std() * np.sqrt(365)) if full_d.std() > 0 else 0.0
    avg_test = float(np.mean([f["sharpe"] for f in folds])) if folds else 0.0
    eff = float(avg_test / is_sh) if is_sh > 0 else 0.0
    return {"folds": folds, "efficiency_ratio": eff,
            "avg_test_sharpe": avg_test, "is_sharpe": is_sh}


def parameter_sensitivity(
    df: pd.DataFrame, cfg: SignalConfig, regime: pd.Series
) -> dict:
    grid = []
    for dz in [-0.3, 0.0, +0.3]:
        for dbri in [-0.3, 0.0, +0.3]:
            for dci in [-0.2, 0.0, +0.2]:
                pcfg = SignalConfig(
                    z_top_thr=cfg.z_top_thr + dz,
                    brigals_thr=cfg.brigals_thr + dbri,
                    ci_thr=cfg.ci_thr + dci,
                    use_ma200=cfg.use_ma200,
                    use_lowvol=cfg.use_lowvol,
                    eqfilter=cfg.eqfilter,
                )
                tr, eq = simulate_with_eqfilter(
                    df, composite_signal(df, pcfg), regime,
                    eqfilter=pcfg.eqfilter,
                )
                d = eq.resample("1D").last().dropna().pct_change().dropna()
                sh = float(d.mean() / d.std() * np.sqrt(365)) if d.std() > 0 else 0.0
                grid.append({"dz": dz, "dbri": dbri, "dci": dci,
                             "sharpe": sh, "n_trades": len(tr)})
    sharpes = [g["sharpe"] for g in grid]
    return {
        "median_sharpe": float(np.median(sharpes)),
        "min_sharpe": float(np.min(sharpes)),
        "max_sharpe": float(np.max(sharpes)),
        "n_cells": len(grid),
    }


def cost_stress_pf(df, cfg, regime, fee_bps_rt: float) -> float:
    tr, eq = simulate_with_eqfilter(
        df, composite_signal(df, cfg), regime,
        fee_bps_rt=fee_bps_rt, eqfilter=cfg.eqfilter,
    )
    if not tr:
        return 0.0
    rets = np.array([t["ret"] for t in tr])
    wins = rets > 0
    pf_num = rets[wins].sum() if wins.any() else 0.0
    pf_den = -rets[~wins].sum() if (~wins).any() else 0.0
    return float(pf_num / pf_den) if pf_den > 0 else 0.0


def run_gauntlet(df: pd.DataFrame, cfg: SignalConfig, regime: pd.Series) -> dict:
    """Compute all 10 gates. G3 set to maxdd>=-15% per handoff goal."""
    sig = composite_signal(df, cfg)
    trades, eq = simulate_with_eqfilter(df, sig, regime, eqfilter=cfg.eqfilter)
    stats = core_stats(eq, trades, df)

    daily = eq.resample("1D").last().dropna()
    drets = daily.pct_change().dropna()

    perm = permutation_test(drets, n_iter=500)
    bs = block_bootstrap_sharpe_ci(drets)
    py = per_year_stats(eq)
    yrs_pos = sum(1 for v in py.values() if v["sharpe"] > 0)
    n_yrs = len(py)
    wf = walk_forward_efficiency(df, cfg, regime)
    psen = parameter_sensitivity(df, cfg, regime)
    pf_24 = cost_stress_pf(df, cfg, regime, fee_bps_rt=24.0)

    gates = {
        "G1_sharpe>=0.5":       stats["sharpe"] >= 0.5,
        "G2_calmar>=1.0":       stats["calmar"] >= 1.0,
        "G3_maxdd>=-15%":       stats["max_dd"] >= -0.15,
        "G4_per_year_pos>=70%": (yrs_pos / max(1, n_yrs)) >= 0.70 and n_yrs >= 2,
        "G5_perm_p<0.01":       perm["p_value"] < 0.01,
        "G6_boot_sh_lo>0":      bs["ci_lo"] > 0,
        "G7_wfe>=0.5":          wf["efficiency_ratio"] >= 0.5,
        "G8_pf_at_24bp>1.0":    pf_24 > 1.0,
        "G9_psen_med_sh>0":     psen["median_sharpe"] > 0,
        "G10_pf>=1.10":         stats["profit_factor"] >= 1.10,
    }
    return {
        "config": cfg.__dict__,
        "core_stats": stats,
        "gates": gates,
        "gates_passed": sum(int(v) for v in gates.values()),
        "permutation": perm,
        "bootstrap_sharpe": bs,
        "per_year": {str(k): v for k, v in py.items()},
        "walk_forward": wf,
        "parameter_sensitivity": psen,
        "pf_at_24bp": pf_24,
    }


# ─────────────────────────────────────────────────────────────────────
# Sweep + champion picker
# ─────────────────────────────────────────────────────────────────────
def build_sweep_grid() -> list[SignalConfig]:
    return [
        SignalConfig(ztt, brt, cit, ma, lv, eqf)
        for ztt, brt, cit, ma, lv, eqf in product(
            [-1.5, -1.0, -0.5],
            [-1.5, -1.0, -0.5],
            [-0.5, 0.0, +0.5, +1.0],
            [False, True],
            [False, True],
            ["none", "3loss", "dd10", "dd15"],
        )
    ]  # 576 configs/sym


def run_sweep(symbol: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    print(f"\n══════════ {symbol} ══════════", flush=True)
    df = load_4h(symbol)
    print(f"  4h panel: {len(df)} bars  {df.index[0]} → {df.index[-1]}", flush=True)
    regime = regime_labels_volquintile(df)
    rd = regime.value_counts().to_dict()
    print(f"  Regime distribution: {rd}", flush=True)

    rows = []
    grid = build_sweep_grid()
    for i, cfg in enumerate(grid):
        sig = composite_signal(df, cfg)
        n_sig = int(sig.sum())
        if n_sig < 10:
            continue
        trades, eq = simulate_with_eqfilter(df, sig, regime, eqfilter=cfg.eqfilter)
        stats = core_stats(eq, trades, df)
        rows.append({
            "symbol": symbol, "variant": cfg.name(),
            "z_top_thr": cfg.z_top_thr, "brigals_thr": cfg.brigals_thr,
            "ci_thr": cfg.ci_thr, "use_ma200": cfg.use_ma200,
            "use_lowvol": cfg.use_lowvol, "eqfilter": cfg.eqfilter,
            "n_signal_bars": n_sig, **stats,
        })
        if (i + 1) % 50 == 0:
            print(f"  [{i+1}/{len(grid)}] tested", flush=True)

    out = pd.DataFrame(rows)
    print(f"  swept {len(out)} configs", flush=True)
    return out, df, regime


def pick_champion(rows: pd.DataFrame) -> tuple[SignalConfig, dict]:
    """Tier-1: hit ALL of {MDD<15%, beat B&H, PF>=1.10, n>=10}. Tier-2: drop B&H.
    Tier-3: drop MDD-strict. Fallback: best Sharpe with n>=20.

    Lower n_trades floor (10) for tier-1/2 is intentional: R_3loss_pause is a
    one-way circuit-breaker, so eqfilter variants legitimately produce ~10-15
    trades over 3 years.
    """
    fallback = ""
    elig = rows[
        (rows["n_trades"] >= 10)
        & (rows["max_dd"] >= -0.15)
        & (rows["outperform"] >= 1.0)
        & (rows["profit_factor"] >= 1.10)
    ].copy()
    tier = "T1: MDD<15% + beats B&H + PF>=1.1"
    if len(elig) == 0:
        elig = rows[
            (rows["n_trades"] >= 10)
            & (rows["max_dd"] >= -0.15)
            & (rows["profit_factor"] >= 1.10)
        ].copy()
        tier = "T2: MDD<15% + PF>=1.1 (B&H not met)"
        fallback = "fell back: no config beats B&H at MDD<15%"
    if len(elig) == 0:
        elig = rows[
            (rows["n_trades"] >= 30)
            & (rows["max_dd"] >= -0.25)
            & (rows["outperform"] >= 1.0)
            & (rows["profit_factor"] >= 1.10)
        ].copy()
        tier = "T3: MDD<25% + beats B&H + PF>=1.1 (MDD>15%)"
        fallback = "fell back: no MDD<15% config beats B&H or hits PF>=1.1"
    if len(elig) == 0:
        elig = rows[rows["n_trades"] >= 20].copy()
        tier = "T4: best Sharpe (n>=20)"
        fallback = "fell back: no constraint set satisfied — picking best Sharpe"
    if len(elig) == 0:
        elig = rows.copy()
        tier = "T5: best Sharpe (any n)"
        fallback = "fell back: no constraints applied"

    elig = elig.copy()
    if "T4" in tier or "T5" in tier:
        elig["score"] = elig["sharpe"]
    else:
        # Composite: outperform × calmar gives credit to both Sharpe-at-low-DD AND total return
        elig["score"] = elig["outperform"].clip(lower=0.01) * elig["calmar"].clip(lower=0.01)
    best = elig.sort_values("score", ascending=False).iloc[0]
    cfg = SignalConfig(
        z_top_thr=float(best["z_top_thr"]),
        brigals_thr=float(best["brigals_thr"]),
        ci_thr=float(best["ci_thr"]),
        use_ma200=bool(best["use_ma200"]),
        use_lowvol=bool(best["use_lowvol"]),
        eqfilter=str(best["eqfilter"]),
    )
    bd = dict(best)
    bd["fallback_note"] = fallback
    bd["tier"] = tier
    return cfg, bd


# ─────────────────────────────────────────────────────────────────────
# Main + reporting
# ─────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    ap.add_argument("--skip-gauntlet", action="store_true")
    args = ap.parse_args()

    all_rows = []
    champions = []

    for sym in args.symbols:
        rows, df, regime = run_sweep(sym)
        all_rows.append(rows)

        cfg, best = pick_champion(rows)
        print(f"  [pick_champion] tier: {best.get('tier','?')}", flush=True)
        if best.get("fallback_note"):
            print(f"  [pick_champion] {best['fallback_note']}", flush=True)
        print(f"\n  CHAMPION: {cfg.name()}", flush=True)
        print(f"    n_trades={best['n_trades']}  WR={best['win_rate']*100:.1f}%  "
              f"PF={best['profit_factor']:.2f}  Sharpe={best['sharpe']:+.2f}  "
              f"Calmar={best['calmar']:.2f}  MDD={best['max_dd']*100:+.1f}%  "
              f"eq={best['final_eq_x']:.2f}× ({best['outperform']:.2f}× B&H)", flush=True)

        sig = composite_signal(df, cfg)
        trades, eq = simulate_with_eqfilter(df, sig, regime, eqfilter=cfg.eqfilter)
        eq.to_frame("equity").to_parquet(EQ_DIR / f"{sym}_4h.parquet")
        if trades:
            tdf = pd.DataFrame(trades)
            tdf["entry_time"] = df.index[tdf["entry_idx"].clip(0, len(df) - 1)]
            tdf["exit_time"] = df.index[tdf["exit_idx"].clip(0, len(df) - 1)]
            tdf.to_csv(EQ_DIR / f"{sym}_trades.csv", index=False)

        if not args.skip_gauntlet:
            print(f"  running 10-gate gauntlet…", flush=True)
            g = run_gauntlet(df, cfg, regime)
            (OUT / f"gates_{sym}.json").write_text(json.dumps(g, indent=2, default=str))
            print(f"  GATES PASSED: {g['gates_passed']}/10", flush=True)
            for gname, gv in g["gates"].items():
                print(f"    {'✓' if gv else '✗'} {gname}", flush=True)
            champions.append({
                "symbol": sym, "variant": cfg.name(),
                "z_top_thr": cfg.z_top_thr, "brigals_thr": cfg.brigals_thr,
                "ci_thr": cfg.ci_thr, "use_ma200": cfg.use_ma200,
                "use_lowvol": cfg.use_lowvol, "eqfilter": cfg.eqfilter,
                **g["core_stats"],
                "gates_passed": g["gates_passed"],
                "perm_p": g["permutation"]["p_value"],
                "boot_sharpe_lo": g["bootstrap_sharpe"]["ci_lo"],
                "wfe": g["walk_forward"]["efficiency_ratio"],
                "psen_median_sh": g["parameter_sensitivity"]["median_sharpe"],
                "pf_at_24bp": g["pf_at_24bp"],
            })
        else:
            champions.append({"symbol": sym, "variant": cfg.name(), **best})

    full = pd.concat(all_rows, ignore_index=True)
    full.to_csv(OUT / "results.csv", index=False)
    print(f"\nFull sweep: {OUT/'results.csv'} ({len(full)} rows)", flush=True)

    cdf = pd.DataFrame(champions)
    cdf.to_csv(OUT / "champions.csv", index=False)
    print(f"Champions: {OUT/'champions.csv'}", flush=True)

    write_summary(cdf, args.skip_gauntlet)


def write_summary(champs: pd.DataFrame, skipped_gauntlet: bool):
    lines = ["# 4h Strategy — GB-validated cross-asset signals + R_3loss_pause", ""]
    lines.append(f"**Generated:** {pd.Timestamp.now(tz='UTC').isoformat()}")
    lines.append("")
    lines.append("## Engine")
    lines.append("- `strategy_lab/eval/perps_simulator_adaptive_exit.py` — UNMODIFIED.")
    lines.append("- Per-vol-quintile exit profiles (LowVol → loose TP/long hold; "
                 "HighVol → tight TP/short hold).")
    lines.append("- Fees: Hyperliquid 12bp round-trip.")
    lines.append("- Single new feature: `simulate_with_3loss_pause` mask-and-rerun "
                 "wrapper for R_3loss_pause.")
    lines.append("")
    lines.append("## Composite signal")
    lines.append("```")
    lines.append("entry = (z_top_lsr_count < z_top_thr)")
    lines.append("      & (brigalS         < brigals_thr)")
    lines.append("      & (cross_institutional_lead > ci_thr)")
    lines.append("      [& price > MA200d]   # optional")
    lines.append("      [& realized_vol_30d < 90d_median]   # optional")
    lines.append("```")
    lines.append("")
    lines.append("## Champions per asset")
    lines.append("")
    cols = ["symbol", "variant", "n_trades", "win_rate", "profit_factor",
            "sharpe", "calmar", "max_dd", "final_eq_x", "buy_hold_x", "outperform"]
    if "gates_passed" in champs.columns:
        cols.append("gates_passed")
    show = champs[cols].copy()
    show["win_rate"] = (show["win_rate"] * 100).round(1).astype(str) + "%"
    show["max_dd"] = (show["max_dd"] * 100).round(1).astype(str) + "%"
    for c in ["profit_factor", "sharpe", "calmar", "final_eq_x", "buy_hold_x", "outperform"]:
        show[c] = show[c].round(2)
    lines.append(show.to_markdown(index=False))
    lines.append("")

    if not skipped_gauntlet and "gates_passed" in champs.columns:
        lines.append("## 10-gate breakdown")
        lines.append("")
        for _, r in champs.iterrows():
            lines.append(f"### {r['symbol']} — {r['variant']}")
            lines.append(f"- gates passed: **{r['gates_passed']}/10**")
            lines.append(f"- permutation p={r['perm_p']:.4f}")
            lines.append(f"- bootstrap Sharpe 5%-CI lo={r['boot_sharpe_lo']:+.2f}")
            lines.append(f"- walk-forward efficiency={r['wfe']:.2f}")
            lines.append(f"- param-sensitivity median Sharpe={r['psen_median_sh']:+.2f}")
            lines.append(f"- PF at 24bp cost-stress={r['pf_at_24bp']:.2f}")
            lines.append("")

    lines.append("## Goal scoring (HANDOFF.md goal)")
    lines.append("")
    lines.append("Goal was: ≥9/10 gates AND beat buy-and-hold AND MDD < 15%.")
    lines.append("")
    if "gates_passed" in champs.columns:
        for _, r in champs.iterrows():
            cks = []
            cks.append(("≥9/10 gates", int(r["gates_passed"]) >= 9))
            cks.append(("beats B&H", float(r["outperform"]) > 1.0))
            cks.append(("MDD < 15%", float(r["max_dd"]) >= -0.15))
            mark = "✅" if all(c[1] for c in cks) else "⚠"
            lines.append(f"- {mark} **{r['symbol']}**  " +
                         "  ".join(f"{n}={'✓' if v else '✗'}" for n, v in cks))
    lines.append("")
    lines.append("## Files")
    lines.append("- `results.csv` — full sweep (all configs)")
    lines.append("- `champions.csv` — picked variant per asset")
    lines.append("- `equity/{sym}_4h.parquet` — champion equity curve")
    lines.append("- `equity/{sym}_trades.csv` — champion trade log")
    lines.append("- `gates_{sym}.json` — full 10-gate breakdown")

    (OUT / "SUMMARY.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Summary: {OUT/'SUMMARY.md'}", flush=True)


if __name__ == "__main__":
    main()
