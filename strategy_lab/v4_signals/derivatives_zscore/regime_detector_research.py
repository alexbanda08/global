"""Trend-start regime detector — event-study analysis on BTC 1h, 3 years.

Pipeline (mirrors the user spec):
  STEP 1 — Mathematical trend-start labels via (X% move in Y hours, max excursion ≤ Z%) sweep.
  STEP 2 — Collect indicator state at every bar.
  STEP 3 — Compute forward returns at 4h / 12h / 24h / 48h.
  STEP 4 — For each clean event, snapshot indicator state at offsets [-24, -12, -4, -1, 0].
  STEP 5 — Tables: correlation indicator × horizon, mean-by-zone, mean-state-by-offset (sequencing).
  STEP 6 — Validate per macro regime (above EMA200 / between EMA50-EMA200 / below EMA200).
  STEP 7 — Emit Pine Script detector code.

Output:
  strategy_lab/reports/derivatives_zscore/regime_detector/
    01_label_sweep.csv             — (X, Y, Z) → n_events, clean_rate
    02_correlations.csv            — indicator × horizon
    03_zone_means.csv              — mean fwd return per indicator zone
    04_sequencing.csv              — indicator state at offsets [-24, -12, -4, -1, 0]
    05_macro_regime_split.csv      — same correlations partitioned by macro regime
    06_pine_detector.txt           — generated Pine Script
    SUMMARY.md                     — narrative findings
"""
from __future__ import annotations
from pathlib import Path
import sys
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "strategy_lab"))

PANELS = ROOT / "data" / "v4" / "derivatives_zscore" / "panels"
SPOT = ROOT / "data" / "v4" / "derivatives_zscore" / "spot"
OUT_BASE = ROOT / "strategy_lab" / "reports" / "derivatives_zscore" / "regime_detector"
OUT_BASE.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────
#  Step 1+2: load 1h panel + price-derived features
# ─────────────────────────────────────────

def load_symbol(symbol: str) -> pd.DataFrame:
    p = pd.read_parquet(PANELS / f"{symbol}_zscore.parquet").resample("1h").last()
    tag = symbol.replace("USDT", "")
    spot = pd.read_parquet(SPOT / f"BINANCE-{tag}-1h.parquet").set_index("time")
    for c in ["open", "high", "low", "close"]:
        p[c] = spot[c].astype(float).reindex(p.index, method="ffill")
    p["ema_21"] = p["close"].ewm(span=21, adjust=False).mean()
    p["ema_50"] = p["close"].ewm(span=50 * 24, adjust=False).mean()  # 50-day in 1h bars
    p["ema_200"] = p["close"].ewm(span=200 * 24, adjust=False).mean()
    # RSI 14
    delta = p["close"].diff()
    up = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    dn = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    p["rsi_14"] = 100 - 100 / (1 + rs)
    # ATR-normalized
    tr1 = p["high"] - p["low"]
    tr2 = (p["high"] - p["close"].shift()).abs()
    tr3 = (p["low"] - p["close"].shift()).abs()
    p["atr_14"] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1).rolling(14).mean()
    p["atr_pct"] = p["atr_14"] / p["close"]
    # Macro regime label
    p["regime"] = "lateral"
    p.loc[p["close"] > p["ema_200"], "regime"] = "trending_up"
    p.loc[p["close"] < p["ema_50"], "regime"] = "below_ema50"
    p.loc[p["close"] < p["ema_200"], "regime"] = "trending_down"
    return p.dropna(subset=["z_lsr", "z_fund", "z_oi", "close", "ema_200"])


# ─────────────────────────────────────────
#  Step 1: sweep label definitions
# ─────────────────────────────────────────

def label_trend_starts(df: pd.DataFrame, X: float, Y: int, Z: float) -> tuple[pd.Series, pd.Series]:
    """Return (bull_start, bear_start) boolean series.

    Bull: close[T+1..T+Y] reaches ≥ close[T]*(1+X) without ever touching close[T]*(1-Z) along the way.
    Bear: close[T+1..T+Y] reaches ≤ close[T]*(1-X) without ever touching close[T]*(1+Z) along the way.
    """
    n = len(df)
    close = df["close"].to_numpy()
    high = df["high"].to_numpy()
    low = df["low"].to_numpy()
    bull = np.zeros(n, dtype=bool)
    bear = np.zeros(n, dtype=bool)
    for i in range(n - Y):
        c0 = close[i]
        bull_target = c0 * (1 + X)
        bull_floor = c0 * (1 - Z)
        bear_target = c0 * (1 - X)
        bear_ceil = c0 * (1 + Z)
        # Walk forward 1..Y
        bull_seen = False
        bull_clean = True
        bear_seen = False
        bear_clean = True
        for j in range(i + 1, i + Y + 1):
            if low[j] <= bull_floor:
                bull_clean = False
            if high[j] >= bull_target and bull_clean and not bull_seen:
                bull_seen = True
            if high[j] >= bear_ceil:
                bear_clean = False
            if low[j] <= bear_target and bear_clean and not bear_seen:
                bear_seen = True
            if not bull_clean and not bear_clean:
                break
        bull[i] = bull_seen and bull_clean
        bear[i] = bear_seen and bear_clean
    return pd.Series(bull, index=df.index), pd.Series(bear, index=df.index)


def step1_label_sweep(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for X in [0.02, 0.03, 0.05]:
        for Y in [12, 24, 48]:
            for Z in [0.005, 0.010, 0.015]:
                bull, bear = label_trend_starts(df, X, Y, Z)
                rows.append({
                    "X": X, "Y": Y, "Z": Z,
                    "n_bull": int(bull.sum()), "n_bear": int(bear.sum()),
                    "bull_rate_pct": float(bull.sum() / len(df) * 100),
                    "bear_rate_pct": float(bear.sum() / len(df) * 100),
                })
    return pd.DataFrame(rows)


# ─────────────────────────────────────────
#  Step 4: correlations & zone analysis
# ─────────────────────────────────────────

INDICATORS = [
    "z_lsr", "z_fund", "z_oi", "z_oi_silent", "z_cb_premium",
    "z_dom_stables", "z_top_lsr_count", "z_top_lsr_sum", "z_taker_ratio",
    "brigalS", "oilsr",
    "cross_institutional_lead", "cross_leverage_heat", "cross_risk_off", "cross_real_money",
    "rsi_14", "atr_pct",
]


def step4_correlations(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for h in [4, 12, 24, 48]:
        fwd = df["close"].shift(-h) / df["close"] - 1
        for ind in INDICATORS:
            if ind not in df.columns:
                continue
            s = df[ind].dropna()
            r = fwd.dropna()
            joined = pd.concat([s, r], axis=1, join="inner").dropna()
            if len(joined) < 100:
                continue
            corr = joined.iloc[:, 0].corr(joined.iloc[:, 1])
            rows.append({"indicator": ind, "horizon_h": h, "pearson_corr": float(corr),
                         "n": len(joined)})
    return pd.DataFrame(rows)


def step4_zone_means(df: pd.DataFrame, horizon_h: int = 24) -> pd.DataFrame:
    """For each indicator, mean forward return in 5 zones: <-2σ, -2 to -1, -1 to +1, +1 to +2, >+2."""
    fwd = df["close"].shift(-horizon_h) / df["close"] - 1
    rows = []
    bins = [-np.inf, -2, -1, 1, 2, np.inf]
    bin_labels = ["<-2σ", "-2 to -1", "-1 to +1", "+1 to +2", ">+2σ"]
    for ind in INDICATORS:
        if ind not in df.columns:
            continue
        s = df[ind]
        # Skip non-z-score inds (rsi, atr) — different scales
        if ind in ("rsi_14", "atr_pct"):
            continue
        for lo, hi, lab in zip(bins[:-1], bins[1:], bin_labels):
            mask = (s >= lo) & (s < hi)
            if mask.sum() < 50:
                continue
            r = fwd[mask].dropna()
            if len(r) < 30:
                continue
            rows.append({
                "indicator": ind, "zone": lab, "n": len(r),
                "mean_fwd_ret_pct": float(r.mean() * 100),
                "hit_rate_pct": float((r > 0).mean() * 100),
            })
    return pd.DataFrame(rows)


# ─────────────────────────────────────────
#  Step 4 (sequencing): mean indicator state at offsets [-24, -12, -4, -1, 0]
# ─────────────────────────────────────────

def step4_sequencing(df: pd.DataFrame, event_mask: pd.Series, label: str,
                     offsets=(-24, -12, -8, -4, -2, -1, 0)) -> pd.DataFrame:
    """For each event, average indicator state at each offset before the event."""
    event_idx = np.where(event_mask.to_numpy())[0]
    rows = []
    for ind in INDICATORS:
        if ind not in df.columns:
            continue
        col = df[ind].to_numpy()
        for off in offsets:
            samples = []
            for i in event_idx:
                j = i + off
                if 0 <= j < len(col) and not np.isnan(col[j]):
                    samples.append(col[j])
            if not samples:
                continue
            rows.append({
                "label": label,
                "indicator": ind,
                "offset_h": off,
                "n_samples": len(samples),
                "mean": float(np.mean(samples)),
                "median": float(np.median(samples)),
                "std": float(np.std(samples)),
            })
    return pd.DataFrame(rows)


# ─────────────────────────────────────────
#  Step 6: macro-regime split
# ─────────────────────────────────────────

def step6_macro_regime_corrs(df: pd.DataFrame) -> pd.DataFrame:
    """Compute corr × indicator × horizon, partitioned by macro regime."""
    rows = []
    for regime in df["regime"].unique():
        sub = df[df["regime"] == regime]
        if len(sub) < 500:
            continue
        for h in [4, 24]:
            fwd = sub["close"].shift(-h) / sub["close"] - 1
            for ind in INDICATORS:
                if ind not in sub.columns:
                    continue
                joined = pd.concat([sub[ind], fwd], axis=1, join="inner").dropna()
                if len(joined) < 100:
                    continue
                corr = joined.iloc[:, 0].corr(joined.iloc[:, 1])
                rows.append({"regime": regime, "indicator": ind, "horizon_h": h,
                             "n": len(joined), "pearson_corr": float(corr)})
    return pd.DataFrame(rows)


# ─────────────────────────────────────────
#  Step 7: emit Pine Script
# ─────────────────────────────────────────

def emit_pine_detector(seq_bull: pd.DataFrame, seq_bear: pd.DataFrame, corrs: pd.DataFrame) -> str:
    """Generate a Pine Script detector based on the strongest leading indicators
    for bull and bear trend starts (those with biggest mean shift at offset 0).
    """
    # Indicators NOT renderable in Pine's z-scale framing (or numerically unstable):
    EXCLUDE = {"rsi_14", "atr_pct", "cross_leverage_heat", "cross_real_money"}

    def rank_top(seq_df: pd.DataFrame, top: int = 5):
        last = seq_df[seq_df["offset_h"] == 0].copy()
        last = last[~last["indicator"].isin(EXCLUDE)]
        last = last[np.isfinite(last["mean"])]
        last["abs_mean"] = last["mean"].abs()
        last = last.sort_values("abs_mean", ascending=False).head(top)
        return last[["indicator", "mean"]].to_dict("records")

    bull_lead = rank_top(seq_bull)
    bear_lead = rank_top(seq_bear)

    pine = []
    pine.append("// ════════════════════════════════════════════════════════════════")
    pine.append("// BTC Trend-Start Regime Detector  —  generated from 3y event study")
    pine.append("// Source: strategy_lab/v4_signals/derivatives_zscore/regime_detector_research.py")
    pine.append("// ════════════════════════════════════════════════════════════════")
    pine.append("//@version=6")
    pine.append('indicator("BTC Trend-Start Regime Detector (DZS-EventStudy v1)", overlay=true)')
    pine.append("import TradingView/Request/2 as req")
    pine.append("")
    pine.append("// ── Inputs ──")
    pine.append('grpCfg = "Config"')
    pine.append('zLen   = input.int(21,           "Z-Score Length",  group=grpCfg, minval=5)')
    pine.append('exch   = input.string("BINANCE", "Exchange",        group=grpCfg, options=["BINANCE","BYBIT","OKX"])')
    pine.append('oi_sym = input.symbol("BINANCE:BTCUSDT.P_OI", "OI Symbol")')
    pine.append("")
    pine.append("// ── Symbol resolution ──")
    pine.append("base = str.replace(syminfo.ticker, \"USDT\", \"\")")
    pine.append("base := str.replace(base, \"USD\", \"\")")
    pine.append("base := str.replace(base, \".P\", \"\")")
    pine.append('sym = exch + ":" + base + "USDT.P"')
    pine.append("")
    pine.append("// ── Data ──")
    pine.append('lsr_acc  = req.cryptoDerivativeMetric(sym, "Long/Short Ratio Accounts", "")')
    pine.append('funding  = req.cryptoDerivativeMetric(sym, "Funding Rate", "")')
    pine.append("oi       = request.security(oi_sym, timeframe.period, close)")
    pine.append('btc_cb   = request.security("COINBASE:BTCUSD",   "", close)')
    pine.append('btc_bn   = request.security("BINANCE:BTCUSDT",   "", close)')
    pine.append('stablecd = request.security("CRYPTOCAP:STABLE.C.D","", close)')
    pine.append("")
    pine.append("// ── Z-score helper ──")
    pine.append("f_z(src, len) =>")
    pine.append("    m = ta.sma(src, len)")
    pine.append("    s = ta.stdev(src, len)")
    pine.append("    na(src) or na(s) or s == 0 ? na : (src - m) / s")
    pine.append("")
    pine.append("z_lsr  = f_z(lsr_acc,  zLen)")
    pine.append("z_fund = f_z(funding,  zLen)")
    pine.append("z_oi   = f_z(oi,       zLen)")
    pine.append("z_doms = f_z(stablecd, zLen)")
    pine.append("cb_prem_pct = (btc_cb - btc_bn) / btc_bn * 100")
    pine.append("z_cb   = f_z(ta.ema(cb_prem_pct, 3), zLen)")
    pine.append("// OI silent")
    pine.append("oi_roc3   = ta.roc(oi, 3)")
    pine.append("px_roc3   = ta.roc((btc_cb + btc_bn) / 2, 3)")
    pine.append("z_oi_fast = f_z(oi_roc3, zLen)")
    pine.append("z_px_fast = f_z(px_roc3, zLen)")
    pine.append("oi_silent_raw = z_oi_fast > 1.0 ? z_oi_fast - z_px_fast : 0.0")
    pine.append("z_oi_silent = f_z(ta.ema(oi_silent_raw, 3), zLen)")
    pine.append("")
    pine.append("// ── Macro regime filter ──")
    pine.append("price_ema200 = ta.ema(close, 200)")
    pine.append("realized_vol_30d = ta.stdev(ta.change(close)/close, 720) * math.sqrt(8760)")
    pine.append("vol_median_90d   = ta.median(realized_vol_30d, 2160)")
    pine.append("low_vol_regime   = realized_vol_30d < vol_median_90d")
    pine.append("trending_up      = close > price_ema200")
    pine.append("")
    # Precompute composite series in pine that aren't directly there
    pine.append("// ── Computed composites (for sequencing-derived triggers) ──")
    pine.append("brigalS = f_z(req.cryptoDerivativeMetric(sym,\"Long Accounts\",\"\"), zLen) - "
                "f_z(req.cryptoDerivativeMetric(sym,\"Short Accounts\",\"\"), zLen)")
    pine.append("oilsr   = z_oi - z_lsr")
    pine.append("// Top-trader LSR z-scores (used in some triggers)")
    pine.append("z_top_lsr_count = f_z(req.cryptoDerivativeMetric(sym,\"Top Trader Long/Short Ratio Accounts\",\"\"), zLen)")
    pine.append("z_top_lsr_sum   = f_z(req.cryptoDerivativeMetric(sym,\"Top Trader Long/Short Ratio Positions\",\"\"), zLen)")
    pine.append("z_taker_ratio   = f_z(req.cryptoDerivativeMetric(sym,\"Taker Buy/Sell Volume Ratio\",\"\"), zLen)")
    pine.append("// cross_institutional_lead — proxy via USDC.D Δ - USDT.D Δ")
    pine.append("usdcd = request.security(\"CRYPTOCAP:USDC.D\", \"\", close)")
    pine.append("usdtd = request.security(\"CRYPTOCAP:USDT.D\", \"\", close)")
    pine.append("d_usdc = (ta.ema(usdcd,3) - ta.ema(usdcd,3)[14]) / ta.ema(usdcd,3)[14] * 100")
    pine.append("d_usdt = (ta.ema(usdtd,3) - ta.ema(usdtd,3)[14]) / ta.ema(usdtd,3)[14] * 100")
    pine.append("cross_inst_lead = d_usdc - d_usdt")
    pine.append("cross_risk_off  = (ta.ema(stablecd,3) - ta.ema(stablecd,3)[14]) / ta.ema(stablecd,3)[14] * 100 - (d_usdt*0.6 + d_usdc*0.4)")
    pine.append("")
    pine.append("// ── BULL trigger composite (sequencing-derived thresholds at offset 0) ──")

    def fmt_var(ind: str) -> str:
        return {"z_dom_stables": "z_doms",
                "cross_institutional_lead": "cross_inst_lead"}.get(ind, ind)

    pine.append("bull_score = 0")
    for entry in bull_lead:
        ind, mean = entry["indicator"], entry["mean"]
        sign = ">" if mean > 0 else "<"
        thr = round(mean * 0.5, 3)  # half the observed mean — directional, not extreme
        pine.append(f"bull_score := bull_score + ({fmt_var(ind)} {sign} {thr:+.3f} ? 1 : 0)")
    pine.append("// Require macro filters AND ≥3 of the 5 leading inds firing")
    pine.append("bull_signal = trending_up and low_vol_regime and bull_score >= 3")
    pine.append("")
    pine.append("// ── BEAR trigger composite ──")
    pine.append("bear_score = 0")
    for entry in bear_lead:
        ind, mean = entry["indicator"], entry["mean"]
        sign = ">" if mean > 0 else "<"
        thr = round(mean * 0.5, 3)
        pine.append(f"bear_score := bear_score + ({fmt_var(ind)} {sign} {thr:+.3f} ? 1 : 0)")
    pine.append("bear_signal = (not trending_up) and bear_score >= 3")
    pine.append("")
    pine.append("// ── Plot ──")
    pine.append("plotshape(bull_signal, title=\"Bull Trend Start\", "
                "style=shape.triangleup, location=location.belowbar, "
                "color=color.green, size=size.normal)")
    pine.append("plotshape(bear_signal, title=\"Bear Trend Start\", "
                "style=shape.triangledown, location=location.abovebar, "
                "color=color.red, size=size.normal)")
    pine.append("")
    pine.append("alertcondition(bull_signal, title=\"BULL trend start\", message=\"BTC Trend-Start Detector — BULL\")")
    pine.append("alertcondition(bear_signal, title=\"BEAR trend start\", message=\"BTC Trend-Start Detector — BEAR\")")

    return "\n".join(pine)


# ─────────────────────────────────────────
#  Driver
# ─────────────────────────────────────────

def run_for_symbol(symbol: str, OUT: Path):
    print(f"\n══════════════════ {symbol} ══════════════════")
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"Loading {symbol} 3y panel ...")
    df = load_symbol(symbol)
    print(f"  rows={len(df):,}  range {df.index.min()} → {df.index.max()}")

    # ── STEP 1: label sweep ──
    print("\n[1/6] Label sweep (X, Y, Z) ...")
    sweep = step1_label_sweep(df)
    sweep.to_csv(OUT / "01_label_sweep.csv", index=False)
    print(sweep.to_string(index=False))

    # Pick a "clean" definition: maximize n_events while keeping the bar moving (3% in 24h, 1% drawdown floor)
    X, Y, Z = 0.03, 24, 0.010
    print(f"\nSelected definition: X={X*100:.0f}% in {Y}h, max excursion ±{Z*100:.1f}%")
    bull, bear = label_trend_starts(df, X, Y, Z)
    print(f"  bull events: {int(bull.sum())} ({bull.sum() / len(df) * 100:.2f}% of bars)")
    print(f"  bear events: {int(bear.sum())} ({bear.sum() / len(df) * 100:.2f}% of bars)")

    # ── STEP 4: correlations ──
    print("\n[2/6] Correlation table (indicator × horizon) ...")
    corrs = step4_correlations(df)
    corrs.to_csv(OUT / "02_correlations.csv", index=False)
    pivot = corrs.pivot(index="indicator", columns="horizon_h", values="pearson_corr")
    print(pivot.round(3).to_string())

    # ── STEP 4b: zone means ──
    print("\n[3/6] Zone means @ 24h fwd return ...")
    zones = step4_zone_means(df, horizon_h=24)
    zones.to_csv(OUT / "03_zone_means.csv", index=False)
    pivz = zones.pivot_table(index="indicator", columns="zone", values="mean_fwd_ret_pct").round(3)
    print(pivz.to_string())

    # ── STEP 4c: sequencing (mean state at offsets) ──
    print("\n[4/6] Sequencing — mean indicator state before bull/bear events ...")
    seq_bull = step4_sequencing(df, bull, "bull")
    seq_bear = step4_sequencing(df, bear, "bear")
    seq = pd.concat([seq_bull, seq_bear], ignore_index=True)
    seq.to_csv(OUT / "04_sequencing.csv", index=False)
    # Print bull pivot
    print("\nBULL trend-start sequencing (mean):")
    pseq_b = seq_bull.pivot_table(index="indicator", columns="offset_h", values="mean").round(3)
    print(pseq_b.to_string())
    print("\nBEAR trend-start sequencing (mean):")
    pseq_be = seq_bear.pivot_table(index="indicator", columns="offset_h", values="mean").round(3)
    print(pseq_be.to_string())

    # ── STEP 6: macro-regime split ──
    print("\n[5/6] Per-regime correlation split ...")
    regimes = step6_macro_regime_corrs(df)
    regimes.to_csv(OUT / "05_macro_regime_split.csv", index=False)
    pr = regimes.pivot_table(index=["regime", "indicator"], columns="horizon_h",
                             values="pearson_corr").round(3)
    print(pr.to_string())

    # ── STEP 7: Pine Script detector ──
    print("\n[6/6] Generating Pine Script detector ...")
    pine = emit_pine_detector(seq_bull, seq_bear, corrs)
    (OUT / "06_pine_detector.txt").write_text(pine)
    print(f"  → {OUT/'06_pine_detector.txt'} ({len(pine)} chars)")

    # SUMMARY note
    summary = []
    summary.append(f"# {symbol} Trend-Start Regime Detector — 3y Event Study")
    summary.append(f"\n**Window:** {df.index.min()} → {df.index.max()}  ({len(df):,} hourly bars)")
    summary.append(f"\n**Trend-start label used:** ≥{X*100:.0f}% move in {Y}h with max counter-excursion ≤{Z*100:.1f}%.")
    summary.append(f"\n- Bull events: **{int(bull.sum())}** ({bull.sum()/len(df)*100:.2f}% of bars)")
    summary.append(f"- Bear events: **{int(bear.sum())}** ({bear.sum()/len(df)*100:.2f}% of bars)")
    # Top 5 leading indicators by abs corr at h=24
    h24 = corrs[corrs["horizon_h"] == 24].copy()
    h24["abs_corr"] = h24["pearson_corr"].abs()
    top = h24.sort_values("abs_corr", ascending=False).head(5)
    summary.append("\n## Top 5 leading indicators by |corr| @ 24h fwd return\n")
    summary.append("| Indicator | Pearson corr | n samples |")
    summary.append("|---|---|---|")
    for _, r in top.iterrows():
        summary.append(f"| `{r['indicator']}` | {r['pearson_corr']:+.4f} | {r['n']:,} |")
    # Sequencing — pick bull-side movers
    summary.append("\n## Bull-side sequencing (mean state @ offset)\n")
    summary.append("Indicators are sorted by |mean at offset 0|. Negative offsets = before event.\n")
    pivb = seq_bull.pivot_table(index="indicator", columns="offset_h", values="mean")
    pivb["abs_at_zero"] = pivb[0].abs()
    pivb = pivb.sort_values("abs_at_zero", ascending=False).drop(columns=["abs_at_zero"]).round(3)
    summary.append("```")
    summary.append(pivb.to_string())
    summary.append("```")
    summary.append("\n## Bear-side sequencing (mean state @ offset)\n```")
    pivbe = seq_bear.pivot_table(index="indicator", columns="offset_h", values="mean")
    pivbe["abs_at_zero"] = pivbe[0].abs()
    pivbe = pivbe.sort_values("abs_at_zero", ascending=False).drop(columns=["abs_at_zero"]).round(3)
    summary.append(pivbe.to_string())
    summary.append("```")
    summary.append("\n## Macro-regime stability\n")
    summary.append("Pearson correlations split by macro regime. If a number flips sign or shrinks 50%+ across regimes, the indicator is regime-dependent and needs the macro filter.\n```")
    summary.append(pr.to_string())
    summary.append("```")
    summary.append("\n## Files\n")
    summary.append("- `01_label_sweep.csv` — full (X, Y, Z) grid output")
    summary.append("- `02_correlations.csv` — indicator × horizon Pearson")
    summary.append("- `03_zone_means.csv` — mean fwd return per ±σ zone")
    summary.append("- `04_sequencing.csv` — pre-event indicator snapshots")
    summary.append("- `05_macro_regime_split.csv` — corr partitioned by macro regime")
    summary.append("- `06_pine_detector.txt` — generated Pine Script v6 detector")
    (OUT / "SUMMARY.md").write_text("\n".join(summary))
    print(f"SUMMARY: {OUT / 'SUMMARY.md'}")


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    args = ap.parse_args()

    for sym in args.symbols:
        # First symbol writes to legacy root for backward compat with existing dashboard
        if sym == "BTCUSDT" and len(args.symbols) == 3:
            out_dir = OUT_BASE  # writes to regime_detector/ root (BTC-only legacy path)
        else:
            out_dir = OUT_BASE / sym  # subdirs for ETH / SOL
        run_for_symbol(sym, out_dir)


if __name__ == "__main__":
    main()
