"""Full backtest using PRODUCTION strategy code + qty_compute gate + L25 fills.

Uses MomoStrategy / MomoV2Strategy / Updown5mStrategy / Updown15mStrategy /
f7_passes EXACTLY as deployed on VPS3. Adds Markov overlay. Applies the
[0.05, 0.95] qty_compute gate via L25 best_ask check. Sub-second book walk
for fills. LiveMimicConfig fees + latency.

Outputs per-sleeve scorecard with 4 gate modes:
  - NO_FILTER:  prod-strategy + qty_compute only
  - F7:         prod-strategy + F7 gate + qty_compute
  - MARKOV:     prod-strategy + Markov gate + qty_compute
  - F7+MARKOV:  prod-strategy + F7 + Markov + qty_compute
"""
from __future__ import annotations
import gc
import sys
from decimal import Decimal
from pathlib import Path
import numpy as np
import pandas as pd

# Wire production strategy shim
sys.path.insert(0, "strategy_lab/markov_filter/_prod_shim")
sys.path.insert(0, "data/v4/canonical")
sys.path.insert(0, "strategy_lab")
sys.path.insert(0, "strategy_lab/markov_filter")

from backend.app.strategies.polymarket.momo import MomoStrategy
from backend.app.strategies.polymarket.momo_v2 import MomoV2Strategy
from backend.app.strategies.polymarket.updown_5m import Updown5mStrategy
from backend.app.strategies.polymarket.f7_gate import f7_passes

from load import load_orderbook_l25_streaming
from engine_v2 import (
    LiveMimicConfig, find_book_strict, book_event_count,
)
from book_walk import book_walk_fill
from fees import poly_taker_fee_per_share
from markov_regime_micro import (
    build_labels_for_asset, regime_at_us, BULL, BEAR,
)

FRESH_KLINES = "strategy_lab/markov_filter/_vps3_pull/binance_1m_fresh.csv"
RESOL_CSV    = "strategy_lab/markov_filter/_vps3_pull/all_resolutions_apr22_may22.csv"
OUT_DIR      = Path("strategy_lab/markov_filter/_results/backtest_prod_strats")
OUT_DIR.mkdir(parents=True, exist_ok=True)

ASSETS     = ("BTC", "ETH", "SOL")
TIMEFRAMES = {"5m": 300, "15m": 900}

# Production qty_compute clamp (Phase 18.1 D-12)
QTY_MIN_PRICE = 0.05
QTY_MAX_PRICE = 0.95

MARKOV_VARIANTS = [
    ("w20_1m_voladaptive", {"window_bars": 20, "bar_minutes": 1, "mode": "vol_adaptive"}),
    ("w20_1m_fixed",       {"window_bars": 20, "bar_minutes": 1, "mode": "fixed"}),
    ("w20_5m_voladaptive", {"window_bars": 20, "bar_minutes": 5, "mode": "vol_adaptive"}),
    ("w20_5m_fixed",       {"window_bars": 20, "bar_minutes": 5, "mode": "fixed"}),
]
FIXED_THRESHOLDS = {
    1: {"BTC": 0.003, "ETH": 0.004, "SOL": 0.006},
    5: {"BTC": 0.005, "ETH": 0.007, "SOL": 0.010},
}


def wilder_rsi_logret(closes: np.ndarray, period: int = 14) -> np.ndarray:
    """Production-matching log-return Wilder RSI (per VPS3 rsi.py)."""
    n = len(closes)
    rsi = np.full(n, np.nan)
    if n <= period:
        return rsi
    lr = np.log(closes[1:] / closes[:-1])
    g = np.where(lr > 0, lr, 0.0)
    l = np.where(lr < 0, -lr, 0.0)
    for i in range(period, n - 1):
        ag = g[i - period + 1:i + 1].mean()
        al = l[i - period + 1:i + 1].mean()
        if al == 0:
            rsi[i + 1] = 100.0
        elif ag == 0:
            rsi[i + 1] = 0.0
        else:
            rsi[i + 1] = 100.0 - 100.0 / (1.0 + ag / al)
    return rsi


def asof_value(end_us: np.ndarray, values: np.ndarray, target_us: int) -> float:
    i = int(np.searchsorted(end_us, int(target_us), side="right")) - 1
    if i < 0 or i >= len(values):
        return float("nan")
    return float(values[i])


def load_klines():
    print("[1] Loading binance 1m klines...")
    k = pd.read_csv(FRESH_KLINES)
    cache = {}
    for asset in ASSETS:
        sym = f"BINANCE_SPOT_{asset}_USDT"
        sub = k[k["symbol_id"] == sym].drop_duplicates("time_period_start_us") \
                                       .sort_values("time_period_start_us")
        end_us = sub["time_period_start_us"].values.astype("int64") + 60_000_000
        close = sub["price_close"].values.astype("float64")
        rsi = wilder_rsi_logret(close, 14)
        cache[asset] = (end_us, close, rsi)
        print(f"   {asset}: {len(close):,} bars  RSI finite={np.isfinite(rsi).sum()}")
    return cache


def load_universe():
    print("[2] Loading fresh resolutions universe...")
    r = pd.read_csv(RESOL_CSV)
    r["slot_start_s"] = (r["slot_start_us"] // 1_000_000).astype("int64")
    r["slot_end_s"]   = (r["slot_end_us"] // 1_000_000).astype("int64")
    r["asset"] = r["ticker"].str.replace("CRYPTO_", "", regex=False).str.upper()
    r = r[r["asset"].isin(ASSETS)].copy()
    r["tf"] = r["timeframe"]
    r = r[r["tf"].isin(["5m", "15m"])].copy()
    r["window_s"] = r["tf"].map(TIMEFRAMES)
    r["ws_s"] = r["slot_start_s"] - r["window_s"]
    print(f"   {len(r):,} slugs after filter")
    print(f"   Range: {pd.Timestamp(r['slot_start_s'].min(), unit='s', tz='UTC')} → "
          f"{pd.Timestamp(r['slot_start_s'].max(), unit='s', tz='UTC')}")
    return r


def build_aux_per_slug(r: pd.DataFrame, kcache: dict) -> pd.DataFrame:
    """Compute aux fields per slug for ALL strategies."""
    print("[3] Building aux per slug (ret_v1, ret_v2, ret_w, rsi_14)...")
    n = len(r)
    ret_v1 = np.full(n, np.nan)
    ret_v2 = np.full(n, np.nan)
    ret_w  = np.full(n, np.nan)
    rsi_at_ws = np.full(n, np.nan)
    for i, row in enumerate(r.itertuples(index=False)):
        end_us, c, rsi = kcache[row.asset]
        ws_us = int(row.ws_s) * 1_000_000
        # v1: log(c@ws+120 / c@ws)
        c0 = asof_value(end_us, c, ws_us)
        c120 = asof_value(end_us, c, ws_us + 120_000_000)
        if np.isfinite(c0) and np.isfinite(c120) and c0 > 0:
            ret_v1[i] = float(np.log(c120 / c0))
        # v2: log(c@ws+60 / c@ws-60)
        cm60 = asof_value(end_us, c, ws_us - 60_000_000)
        c60  = asof_value(end_us, c, ws_us + 60_000_000)
        if np.isfinite(cm60) and np.isfinite(c60) and cm60 > 0:
            ret_v2[i] = float(np.log(c60 / cm60))
        # sniper (per prod controller poly_updown_loop.py:1127-1147 +
        # base.py:38-46): ret_5m = log(BTC@ws_s / BTC@(ws_s − 300)) with
        # FIXED 300s lookback for BOTH 5m AND 15m.
        cs  = asof_value(end_us, c, ws_us)
        csb = asof_value(end_us, c, ws_us - 300_000_000)
        if np.isfinite(cs) and np.isfinite(csb) and csb > 0:
            ret_w[i] = float(np.log(cs / csb))
        # RSI at ws_s (asof)
        rsi_at_ws[i] = asof_value(end_us, rsi, ws_us)
        if (i + 1) % 5000 == 0:
            print(f"   {i+1:,}/{n:,}")
    r = r.copy()
    r["ret_v1"] = ret_v1
    r["ret_v2"] = ret_v2
    r["ret_w"]  = ret_w
    r["rsi_14"] = rsi_at_ws
    return r


def add_thresholds(r: pd.DataFrame):
    print("[4] Computing thresholds per (asset, tf)...")
    r = r.sort_values("slot_start_s").reset_index(drop=True).copy()
    r["thr_v1"] = np.nan
    r["thr_v2"] = np.nan
    r["thr_w"]  = np.nan
    LB = 14 * 86400
    for (asset, tf), idxs in r.groupby(["asset", "tf"]).groups.items():
        sub = r.loc[idxs]
        ss = sub["slot_start_s"].values
        abs_v1 = np.abs(sub["ret_v1"].values)
        abs_v2 = np.abs(sub["ret_v2"].values)
        abs_w  = np.abs(sub["ret_w"].values)
        q_w = 0.90 if tf == "5m" else 0.80
        thr_v1 = np.full(len(sub), np.nan)
        thr_v2 = np.full(len(sub), np.nan)
        thr_w  = np.full(len(sub), np.nan)
        for j in range(len(sub)):
            t = ss[j]
            mask = (ss >= t - LB) & (ss < t)
            if mask.sum() < 50:
                continue
            v1 = abs_v1[mask]; v1 = v1[~np.isnan(v1)]
            v2 = abs_v2[mask]; v2 = v2[~np.isnan(v2)]
            wv = abs_w[mask];  wv = wv[~np.isnan(wv)]
            if len(v1) >= 50: thr_v1[j] = float(np.quantile(v1, 0.90))
            if len(v2) >= 50: thr_v2[j] = float(np.quantile(v2, 0.90))
            if len(wv) >= 50: thr_w[j]  = float(np.quantile(wv, q_w))
        r.loc[idxs, "thr_v1"] = thr_v1
        r.loc[idxs, "thr_v2"] = thr_v2
        r.loc[idxs, "thr_w"]  = thr_w
    return r


def build_markov_cache():
    print("[5] Building Markov label cache...")
    cache = {}
    for vname, params in MARKOV_VARIANTS:
        for asset in ASSETS:
            kw = dict(window_bars=params["window_bars"],
                      bar_minutes=params["bar_minutes"], mode=params["mode"],
                      fresh_klines_csv=FRESH_KLINES)
            if params["mode"] == "fixed":
                kw["fixed_threshold"] = FIXED_THRESHOLDS[params["bar_minutes"]][asset]
            end_us, _c, labels = build_labels_for_asset(asset, **kw)
            cache[(vname, asset)] = (end_us, labels)
    return cache


def call_strategy_signal(strategy_name: str, row, f7_mode: str = "off") -> str:
    """Call production strategy with appropriate aux per spec.
    Returns 'UP' | 'DOWN' | 'NONE'."""
    if strategy_name == "momo_v1":
        if not (np.isfinite(row.ret_v1) and np.isfinite(row.thr_v1)):
            return "NONE"
        aux = {
            "bar_ctx_phase": "t_plus_120",
            "ret_2m": float(row.ret_v1),
            "abs_ret_2m_threshold": float(row.thr_v1),
            "rsi_14": float(row.rsi_14) if np.isfinite(row.rsi_14) else None,
            "f7_filter_mode": f7_mode,
        }
        return MomoStrategy().signal([], None, aux)
    if strategy_name == "momo_v2":
        if not (np.isfinite(row.ret_v2) and np.isfinite(row.thr_v2)):
            return "NONE"
        aux = {
            "bar_ctx_phase": "t_plus_60",
            "ret_2m": float(row.ret_v2),
            "abs_ret_2m_threshold": float(row.thr_v2),
            "rsi_14": float(row.rsi_14) if np.isfinite(row.rsi_14) else None,
            "f7_filter_mode": f7_mode,
        }
        return MomoV2Strategy().signal([], None, aux)
    if strategy_name == "sniper":
        if not (np.isfinite(row.ret_w) and np.isfinite(row.thr_w)):
            return "NONE"
        aux = {
            "ret_5m": float(row.ret_w),
            "abs_ret_5m_threshold": float(row.thr_w),
        }
        return Updown5mStrategy(mode="sniper").signal([], None, aux)
    return "NONE"


def fire_us_for(strategy: str, ws_s: int, slot_start_s: int) -> int:
    if strategy == "momo_v1": return (ws_s + 120) * 1_000_000
    if strategy == "momo_v2": return (ws_s + 60)  * 1_000_000
    return slot_start_s * 1_000_000  # sniper fires at bar close


def main():
    cfg = LiveMimicConfig()
    print(f"Engine: {cfg.name}, fee={cfg.fee_model}, latency={cfg.latency_ms}ms, "
          f"notional=${cfg.notional_usd}, min_book_events={cfg.min_book_events}")

    kcache = load_klines()
    r = load_universe()
    r = build_aux_per_slug(r, kcache)
    r = add_thresholds(r)
    r.to_csv(OUT_DIR / "universe.csv", index=False)

    mk_cache = build_markov_cache()

    # For each strategy × (f7_mode), compute signal for every slug
    print("\n[6] Generating signals per (strategy, f7_mode)...")
    strats = ["momo_v1", "momo_v2", "sniper"]
    sig_df = []
    for strat in strats:
        for f7_mode in ("off", "basic"):
            sigs = np.empty(len(r), dtype=object)
            for i, row in enumerate(r.itertuples(index=False)):
                sigs[i] = call_strategy_signal(strat, row, f7_mode=f7_mode)
            tmp = r[["asset", "tf", "slot_start_s", "slot_end_s", "ws_s",
                     "window_s", "slug", "outcome",
                     "ret_v1","ret_v2","ret_w","rsi_14"]].copy()
            tmp["strategy"] = strat
            tmp["f7_mode"]  = f7_mode
            tmp["signal"]   = sigs
            sig_df.append(tmp[tmp["signal"].isin(["UP","DOWN"])])
    fires = pd.concat(sig_df, ignore_index=True)
    print(f"   {len(fires):,} pre-fill fires (signal in UP/DOWN)")
    fires["cell"] = fires["asset"].str.lower() + "_" + fires["tf"]
    fires["fire_us"] = fires.apply(
        lambda x: fire_us_for(x["strategy"], int(x["ws_s"]), int(x["slot_start_s"])), axis=1
    )
    fires["outcome_side"] = np.where(fires["signal"] == "UP", "Up", "Down")
    fires["won"] = (
        ((fires["signal"] == "UP")   & (fires["outcome"] == "Up")) |
        ((fires["signal"] == "DOWN") & (fires["outcome"] == "Down"))
    )

    print("\n[7] Markov regime lookup per fire...")
    for vname, _ in MARKOV_VARIANTS:
        regs = np.full(len(fires), -1, dtype=np.int8)
        for i, row in enumerate(fires.itertuples(index=False)):
            end_us, labels = mk_cache[(vname, row.asset)]
            regs[i] = regime_at_us(end_us, labels, int(row.fire_us))
        fires[f"regime_{vname}"] = regs
        fires[f"markov_pass_{vname}"] = (
            ((fires["signal"] == "UP")   & (regs == BULL)) |
            ((fires["signal"] == "DOWN") & (regs == BEAR))
        )

    # ----- L25 fills (one asset at a time) -----
    print("\n[8] L25 fills (sub-second book walk, qty_compute filter)...")
    results = []
    for asset in ASSETS:
        sub = fires[fires["asset"] == asset].copy()
        if sub.empty: continue
        slugs = set(sub["slug"].unique())
        print(f"\n   [{asset}] loading L25 for {len(slugs):,} slugs...")
        books = load_orderbook_l25_streaming(
            asset, slugs=slugs, subsample_1hz=True,
            min_ts_us=int(sub["slot_start_s"].min() - 1800) * 1_000_000,
            max_ts_us=int(sub["slot_end_s"].max() + 60) * 1_000_000,
        )
        print(f"   [{asset}] {len(books):,} (slug, outcome) book series")

        n_fired = 0; n_skip_book = 0; n_skip_qty = 0; n_skip_sparse = 0
        for r2 in sub.itertuples(index=False):
            # Sparse-book filter
            n_events = book_event_count(
                books, r2.slug, r2.outcome_side,
                int(r2.slot_start_s) * 1_000_000,
                int(r2.slot_end_s) * 1_000_000,
            )
            if n_events < cfg.min_book_events:
                n_skip_sparse += 1; continue
            # Latency-shifted asof book
            book = find_book_strict(
                books, r2.slug, r2.outcome_side,
                int(r2.fire_us) + int(cfg.latency_ms * 1_000),
                max_staleness_us=cfg.max_book_staleness_us,
            )
            if book is None:
                n_skip_book += 1; continue
            ap = [float(x) for x in book["ap"]]
            asz = [float(x) for x in book["asz"]]
            best_ask = ap[0] if ap and np.isfinite(ap[0]) else float("nan")
            # Production qty_compute filter: best_ask must be in [0.05, 0.95]
            if not np.isfinite(best_ask) or best_ask < QTY_MIN_PRICE or best_ask > QTY_MAX_PRICE:
                n_skip_qty += 1; continue
            # Spread filter
            bp = [float(x) for x in book["bp"]]
            bid0 = bp[0] if bp and np.isfinite(bp[0]) else float("nan")
            if np.isfinite(best_ask) and np.isfinite(bid0) and (best_ask - bid0) > 0.02:
                n_skip_qty += 1; continue
            # Book walk for $25 notional
            vwap, shares, usd, levels, under = book_walk_fill(
                ap, asz, float(cfg.notional_usd), side="buy",
            )
            if shares <= 0 or (under and usd < cfg.notional_usd * 0.5):
                n_skip_qty += 1; continue
            fee_in = shares * poly_taker_fee_per_share(vwap, cfg.poly_fee_rate)
            won = bool(r2.won)
            # hold pnl
            if won:
                pnl = shares * 1.0 - usd - fee_in
            else:
                pnl = -usd - fee_in
            results.append({
                "asset": asset, "tf": r2.tf, "cell": r2.cell,
                "strategy": r2.strategy, "f7_mode": r2.f7_mode,
                "slug": r2.slug, "ws_s": int(r2.ws_s),
                "signal": r2.signal, "outcome": r2.outcome, "won": won,
                "fire_us": int(r2.fire_us),
                "vwap": float(vwap), "shares": float(shares),
                "usd": float(usd), "fee_in": float(fee_in),
                "best_ask": float(best_ask), "bid0": float(bid0),
                "pnl": float(pnl),
                "markov_pass_w20_1m_voladaptive": bool(r2.markov_pass_w20_1m_voladaptive),
                "markov_pass_w20_1m_fixed":       bool(r2.markov_pass_w20_1m_fixed),
                "markov_pass_w20_5m_voladaptive": bool(r2.markov_pass_w20_5m_voladaptive),
                "markov_pass_w20_5m_fixed":       bool(r2.markov_pass_w20_5m_fixed),
            })
            n_fired += 1
        print(f"   [{asset}] fired={n_fired}, sparse_skip={n_skip_sparse}, "
              f"book_skip={n_skip_book}, qty_skip={n_skip_qty}")
        del books; gc.collect()

    fills = pd.DataFrame(results)
    fills.to_csv(OUT_DIR / "fills.csv", index=False)
    print(f"\n   total fills: {len(fills):,}")

    # ----- Scorecard -----
    print("\n[9] Per-sleeve scorecard (4 gate modes)...")
    if fills.empty:
        print("NO FILLS — abort"); return

    def summarize(g, label):
        n = len(g)
        if n == 0: return {"filter": label, "n": 0, "wr": 0.0, "avg": 0.0, "sum": 0.0}
        return {"filter": label, "n": n,
                "wr": round(g["won"].mean() * 100, 2),
                "avg": round(g["pnl"].mean(), 3),
                "sum": round(g["pnl"].sum(), 2)}

    rows = []
    for (strat, cell), g_all in fills.groupby(["strategy", "cell"]):
        # NO_FILTER = f7_mode=off rows
        g_no = g_all[g_all["f7_mode"] == "off"]
        # F7 = f7_mode=basic rows
        g_f7 = g_all[g_all["f7_mode"] == "basic"]
        rows.append({"strategy":strat,"cell":cell, **summarize(g_no, "NO_FILTER")})
        rows.append({"strategy":strat,"cell":cell, **summarize(g_f7, "F7")})
        for vname, _ in MARKOV_VARIANTS:
            mk = f"markov_pass_{vname}"
            short = vname.replace("w20_", "")
            rows.append({"strategy":strat,"cell":cell,
                         **summarize(g_no[g_no[mk]], f"MARKOV:{short}")})
            rows.append({"strategy":strat,"cell":cell,
                         **summarize(g_f7[g_f7[mk]], f"F7+MARKOV:{short}")})
    sc = pd.DataFrame(rows)
    sc.to_csv(OUT_DIR / "scorecard.csv", index=False)

    # Print 70%+ WR cells
    print("\n=== Cells hitting WR ≥ 70% (n>=20) ===")
    hot = sc[(sc["wr"] >= 70) & (sc["n"] >= 20)].sort_values("sum", ascending=False)
    print(hot.to_string(index=False))

    # Also show top by sum$
    print("\n=== Top 25 by sum$ (n>=30) ===")
    top = sc[sc["n"] >= 30].sort_values("sum", ascending=False).head(25)
    print(top.to_string(index=False))


if __name__ == "__main__":
    main()
