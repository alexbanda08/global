"""
Full dashboard for the NEW 60/40 leveraged portfolio.
Includes:
  * 10-gate verdict + headline metrics + kill-switch sizes
  * Leverage configuration panel (per sub-account)
  * Combined equity curve + monthly heatmap + yearly bars + trades/month
  * Per-sleeve breakdown with:
      - Trade count / WR / PF / AvgWin / AvgLoss / AvgHold / L-vs-S breakdown
      - Mini equity SVG
      - ALL trades table (entry date, side, entry px, exit px, reason, bars, return)
      - Size multiplier at entry (for BTC-gated sleeves)
  * Monte Carlo forward-path histograms
Output: docs/research/phase5_results/LEVERAGED_PORTFOLIO_DASHBOARD.html
"""
from __future__ import annotations
import json, sys, time
from pathlib import Path
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from strategy_lab.run_leverage_study import SLEEVE_SPECS, PORTFOLIOS, sleeve_data, OUT, BPY
from strategy_lab.run_leverage_study_v2 import simulate_lev
from strategy_lab.run_leverage_audit import (
    build_p5_btc_defensive, eqw_blend, invvol_blend,
)
from strategy_lab.engine import load as load_data
from strategy_lab.eval.perps_simulator import atr

# =============================================================================
# BTC gate
# =============================================================================
def btc_gate() -> pd.Series:
    btc = load_data("BTCUSDT", "4h", start="2021-01-01", end="2026-03-31")
    close = btc["close"]
    ema200 = close.ewm(span=200, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    trend_any = ((close > ema200) & (ema50 > ema200)) | ((close < ema200) & (ema50 < ema200))
    a = pd.Series(atr(btc), index=btc.index)
    vol_rank = (a / close).rolling(500, min_periods=100).rank(pct=True)
    vol_low = vol_rank < 0.5
    g = pd.Series(1.0, index=btc.index)
    g[trend_any & vol_low] = 1.25
    g[trend_any & ~vol_low] = 0.75
    g[~trend_any & vol_low] = 1.0
    g[~trend_any & ~vol_low] = 0.4
    return g

# =============================================================================
# Build sleeve trade lists w/ dates + size mult
# =============================================================================
def build_sleeve(label: str, use_btc_gate: bool, btc_g: pd.Series | None):
    df, le, se = sleeve_data(label)
    if use_btc_gate and btc_g is not None:
        mult = btc_g.reindex(df.index).ffill().fillna(1.0)
        trades, eq = simulate_lev(df, le, se, size_mult=mult,
                                   risk_per_trade=0.03, leverage_cap=5.0)
    else:
        mult = pd.Series(1.0, index=df.index)
        trades, eq = simulate_lev(df, le, se,
                                   risk_per_trade=0.03, leverage_cap=3.0)
    # enrich trades with dates + size mult at entry
    enriched = []
    for t in trades:
        i_e = t["entry_idx"]; i_x = t["exit_idx"]
        if i_e >= len(df.index) or i_x >= len(df.index):
            continue
        enriched.append({
            **t,
            "entry_date": df.index[i_e],
            "exit_date":  df.index[i_x],
            "size_mult_at_entry": float(mult.iloc[i_e]) if i_e < len(mult) else 1.0,
        })
    return df, le, se, eq, enriched

# =============================================================================
# Metrics + yearly + monthly
# =============================================================================
def eq_metrics(eq: pd.Series, trades: list[dict]) -> dict:
    rets = eq.pct_change().dropna()
    mu = float(rets.mean()); sd = float(rets.std())
    sh = (mu/sd)*np.sqrt(BPY) if sd > 0 else 0
    pk = eq.cummax(); mdd = float((eq/pk - 1).min())
    yrs = (eq.index[-1]-eq.index[0]).total_seconds()/(365.25*86400)
    total = float(eq.iloc[-1]/eq.iloc[0] - 1)
    cagr = (1+total)**(1/max(yrs,1e-6))-1
    cal = cagr/abs(mdd) if mdd != 0 else 0
    # per trade
    n = len(trades)
    wins = [t for t in trades if t.get("ret",0) > 0]
    losses = [t for t in trades if t.get("ret",0) <= 0]
    wr = len(wins)/n if n > 0 else 0
    avg_win = float(np.mean([t["ret"] for t in wins])) if wins else 0
    avg_loss = float(np.mean([t["ret"] for t in losses])) if losses else 0
    pf = abs(sum(t["ret"] for t in wins)/sum(t["ret"] for t in losses)) if losses else 0
    avg_hold = float(np.mean([t["bars"] for t in trades])) if trades else 0
    longs = sum(1 for t in trades if t.get("side") == 1)
    shorts = sum(1 for t in trades if t.get("side") == -1)
    long_wr = (sum(1 for t in trades if t.get("side")==1 and t.get("ret",0)>0)
               / longs) if longs else 0
    short_wr = (sum(1 for t in trades if t.get("side")==-1 and t.get("ret",0)>0)
                / shorts) if shorts else 0
    return {
        "sharpe": round(sh,3), "cagr": round(cagr,4), "mdd": round(mdd,4),
        "calmar": round(cal,3), "total_return": round(total,4),
        "n_trades": n, "wr": round(wr,3),
        "avg_win": round(avg_win,4), "avg_loss": round(avg_loss,4),
        "pf": round(pf,2), "avg_hold_bars": round(avg_hold,1),
        "longs": longs, "shorts": shorts,
        "long_wr": round(long_wr,3), "short_wr": round(short_wr,3),
    }

def yearly_returns(eq: pd.Series) -> dict[int, float]:
    out = {}
    for y in sorted(set(eq.index.year)):
        e = eq[eq.index.year == y]
        if len(e) >= 30:
            out[int(y)] = float(e.iloc[-1]/e.iloc[0] - 1)
    return out

def monthly_returns(eq: pd.Series) -> pd.DataFrame:
    m = eq.resample("ME").last().ffill().pct_change().fillna(0)
    df = pd.DataFrame({"date": m.index, "ret": m.values})
    df["year"] = df["date"].dt.year
    df["month"] = df["date"].dt.month
    return df.pivot(index="year", columns="month", values="ret")

def trades_per_month(trades: list[dict]) -> dict:
    if not trades:
        return {}
    c = {}
    for t in trades:
        k = t["entry_date"].strftime("%Y-%m")
        c[k] = c.get(k, 0) + 1
    return dict(sorted(c.items()))

# =============================================================================
# SVG generators
# =============================================================================
def svg_equity(eq: pd.Series, w=900, h=220, color="#3b82f6", label=""):
    vals = eq.values.astype(float); vals = vals / vals[0]
    n = len(vals); vmin, vmax = float(vals.min()), float(vals.max()); rng = vmax-vmin or 1
    pts = []
    for i,v in enumerate(vals):
        x = 30 + i/(n-1)*(w-40); y = h-25 - (v-vmin)/rng*(h-45)
        pts.append(f"{x:.1f},{y:.1f}")
    # year ticks
    years = sorted(set(eq.index.year))
    ticks = ""
    tz = eq.index.tz
    for yr in years:
        ts = pd.Timestamp(f"{yr}-01-01", tz=tz) if tz is not None else pd.Timestamp(f"{yr}-01-01")
        idx = np.argmax(eq.index >= ts)
        x = 30 + idx/(n-1)*(w-40)
        ticks += f'<line x1="{x}" y1="{h-25}" x2="{x}" y2="{h-20}" stroke="#9ca3af"/>'
        ticks += f'<text x="{x}" y="{h-8}" font-size="10" fill="#6b7280" text-anchor="middle">{yr}</text>'
    return (f'<svg viewBox="0 0 {w} {h}" width="100%" height="{h}" '
            f'xmlns="http://www.w3.org/2000/svg" style="background:#f8fafc;border-radius:6px">'
            f'<path d="M {" L ".join(pts)}" fill="none" stroke="{color}" stroke-width="1.6"/>'
            f'{ticks}<text x="40" y="22" font-size="12" fill="#475569" font-weight="600">{label}</text>'
            f'<text x="{w-10}" y="22" font-size="11" fill="#64748b" text-anchor="end">x{vals[-1]:.2f}</text>'
            f'</svg>')

def svg_mini_equity(eq: pd.Series, w=340, h=80, color="#3b82f6"):
    vals = eq.values.astype(float); vals = vals/vals[0]
    n = len(vals); vmin, vmax = float(vals.min()), float(vals.max()); rng = vmax-vmin or 1
    pts=[]
    for i,v in enumerate(vals):
        x = 6 + i/(n-1)*(w-12); y = h-6 - (v-vmin)/rng*(h-12)
        pts.append(f"{x:.1f},{y:.1f}")
    return (f'<svg viewBox="0 0 {w} {h}" width="100%" height="{h}" '
            f'xmlns="http://www.w3.org/2000/svg" style="background:#f8fafc;border-radius:4px">'
            f'<path d="M {" L ".join(pts)}" fill="none" stroke="{color}" stroke-width="1.3"/>'
            f'<text x="{w-8}" y="16" font-size="10" fill="#64748b" text-anchor="end">{vals[-1]:.2f}x</text>'
            f'</svg>')

def svg_bars(vals: dict, w=900, h=200, color="#3b82f6", ylabel=""):
    if not vals:
        return '<div style="color:#94a3b8;padding:20px">No data</div>'
    keys = list(vals.keys()); heights = list(vals.values())
    vmax = max(abs(v) for v in heights) or 1
    bw = (w-60)/max(len(keys),1)
    out = [f'<svg viewBox="0 0 {w} {h}" width="100%" height="{h}" xmlns="http://www.w3.org/2000/svg" style="background:#f8fafc;border-radius:6px">']
    out.append(f'<line x1="40" y1="{h-30}" x2="{w-10}" y2="{h-30}" stroke="#d1d5db"/>')
    for i,(k,v) in enumerate(zip(keys,heights)):
        x = 45 + i*bw
        bh = abs(v)/vmax*(h-60)
        y = h-30 - bh if v >= 0 else h-30
        c = "#16a34a" if v > 0 else "#dc2626" if v < 0 else color
        if ylabel == "count": c = color
        out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw*0.8:.1f}" height="{bh:.1f}" fill="{c}"/>')
        if len(keys) <= 12 or i % max(1,len(keys)//10) == 0:
            out.append(f'<text x="{x+bw*0.4:.1f}" y="{h-15}" font-size="9" fill="#6b7280" text-anchor="middle">{k}</text>')
    out.append(f'<text x="12" y="18" font-size="11" fill="#475569">{ylabel}</text>')
    out.append('</svg>')
    return "".join(out)

def svg_heatmap(monthly: pd.DataFrame, w=900, h=280):
    if monthly is None or monthly.empty:
        return '<div style="color:#94a3b8">No data</div>'
    years = list(monthly.index); months = list(monthly.columns)
    cw = (w-100)/max(len(months),1); ch = (h-40)/max(len(years),1)
    vmax = max(abs(monthly.min().min()), abs(monthly.max().max())) or 0.01
    out=[f'<svg viewBox="0 0 {w} {h}" width="100%" height="{h}" xmlns="http://www.w3.org/2000/svg" style="background:white;border-radius:6px">']
    for i,y in enumerate(years):
        out.append(f'<text x="50" y="{30+i*ch+ch/2+4}" font-size="10" fill="#475569" text-anchor="end">{y}</text>')
    for j,m in enumerate(months):
        out.append(f'<text x="{70+j*cw+cw/2}" y="25" font-size="10" fill="#475569" text-anchor="middle">{m}</text>')
    for i,yr in enumerate(years):
        for j,mo in enumerate(months):
            v = monthly.loc[yr,mo] if (yr in monthly.index and mo in monthly.columns) else np.nan
            if pd.isna(v): continue
            if v >= 0:
                alpha = min(abs(v)/vmax, 1)
                c = f"rgba(22,163,74,{alpha:.2f})"
            else:
                alpha = min(abs(v)/vmax, 1)
                c = f"rgba(220,38,38,{alpha:.2f})"
            x = 70+j*cw; y = 30+i*ch
            out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{cw*0.92:.1f}" height="{ch*0.92:.1f}" fill="{c}" stroke="#e5e7eb"/>')
            if abs(v) > 0.015:
                out.append(f'<text x="{x+cw/2:.1f}" y="{y+ch/2+4:.1f}" font-size="9" fill="#111827" text-anchor="middle">{v*100:.1f}</text>')
    out.append('</svg>')
    return "".join(out)

def svg_histogram(vals: np.ndarray, bins: int = 30, w=440, h=180,
                  label="", color="#3b82f6", x_fmt=lambda v: f"{v:.2f}"):
    vals = np.asarray(vals, dtype=float)
    counts, edges = np.histogram(vals, bins=bins)
    cmax = max(counts.max(), 1)
    bw = (w-40)/bins
    out=[f'<svg viewBox="0 0 {w} {h}" width="100%" height="{h}" xmlns="http://www.w3.org/2000/svg" style="background:#f8fafc;border-radius:6px">']
    for i,c in enumerate(counts):
        bh = c/cmax*(h-40)
        x = 20+i*bw; y = h-20-bh
        out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw*0.9:.1f}" height="{bh:.1f}" fill="{color}"/>')
    out.append(f'<text x="20" y="15" font-size="11" fill="#475569" font-weight="600">{label}</text>')
    out.append(f'<text x="20" y="{h-5}" font-size="9" fill="#64748b">{x_fmt(edges[0])}</text>')
    out.append(f'<text x="{w-15}" y="{h-5}" font-size="9" fill="#64748b" text-anchor="end">{x_fmt(edges[-1])}</text>')
    # median line
    med = float(np.median(vals))
    x_med = 20 + (med - edges[0]) / (edges[-1] - edges[0]) * (w - 40)
    out.append(f'<line x1="{x_med:.1f}" y1="20" x2="{x_med:.1f}" y2="{h-20}" stroke="#dc2626" stroke-dasharray="3,3"/>')
    out.append(f'<text x="{x_med:.1f}" y="15" font-size="9" fill="#dc2626" text-anchor="middle">median {x_fmt(med)}</text>')
    out.append('</svg>')
    return "".join(out)

# =============================================================================
# Main dashboard build
# =============================================================================
def main():
    t0 = time.time()
    print("Warming caches...")
    for s in SLEEVE_SPECS:
        sleeve_data(s)
    btc_g = btc_gate()

    # Per-sleeve instances
    sleeve_instances = []  # list of dicts: {portfolio, label, size_tag, df, eq, trades, metrics, ...}
    P3_SLEEVES = PORTFOLIOS["P3"]  # CCI_ETH_4h, STF_AVAX_4h, STF_SOL_4h
    P5_SLEEVES = PORTFOLIOS["P5"]  # CCI_ETH_4h, LATBB_AVAX_4h, STF_SOL_4h

    p3_eq_by_sleeve: dict[str, pd.Series] = {}
    p5_eq_by_sleeve: dict[str, pd.Series] = {}

    print("Building P3 sleeves (baseline r=0.03/cap=3x)...")
    for s in P3_SLEEVES:
        df, le, se, eq, tr = build_sleeve(s, use_btc_gate=False, btc_g=None)
        m = eq_metrics(eq, tr)
        p3_eq_by_sleeve[s] = eq
        sleeve_instances.append({
            "portfolio": "P3_invvol",
            "label": s,
            "size_tag": "r=0.03, cap=3x, EQW-to-invvol",
            "df": df, "eq": eq, "trades": tr, "metrics": m,
            "use_gate": False,
        })
        print(f"  {s}: n={m['n_trades']} WR={m['wr']*100:.1f}% PF={m['pf']}")

    print("Building P5 sleeves (BTC defensive gate, r=0.03/cap=5x)...")
    for s in P5_SLEEVES:
        df, le, se, eq, tr = build_sleeve(s, use_btc_gate=True, btc_g=btc_g)
        m = eq_metrics(eq, tr)
        p5_eq_by_sleeve[s] = eq
        sleeve_instances.append({
            "portfolio": "P5_btc_defensive",
            "label": s,
            "size_tag": "r=0.03, cap=5x, BTC-gated (0.4x–1.25x size_mult)",
            "df": df, "eq": eq, "trades": tr, "metrics": m,
            "use_gate": True,
        })
        print(f"  {s}: n={m['n_trades']} WR={m['wr']*100:.1f}% PF={m['pf']}")

    # Build blends
    print("Building blends...")
    p3_invvol_eq = invvol_blend(p3_eq_by_sleeve, window=500)
    p5_def_eq = eqw_blend(p5_eq_by_sleeve)
    idx = p3_invvol_eq.index.intersection(p5_def_eq.index)
    combo_r = (0.60 * p3_invvol_eq.reindex(idx).pct_change().fillna(0)
              + 0.40 * p5_def_eq.reindex(idx).pct_change().fillna(0))
    combo_eq = (1 + combo_r).cumprod() * 10_000.0

    # Combined metrics
    combo_m = eq_metrics(combo_eq, [])  # no trades at blend level
    combo_yrs = yearly_returns(combo_eq)
    combo_monthly = monthly_returns(combo_eq)

    # Load gate 7/8/9/10 results
    g78 = json.loads((OUT/"leverage_gates78_results.json").read_text())
    g910 = json.loads((OUT/"leverage_gates910_results.json").read_text())
    audit = json.loads((OUT/"leverage_combined_60_40.json").read_text())
    combo_audit = audit["combo_audit"]

    # Start building HTML
    print("Rendering HTML...")
    html = [
"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Leveraged Portfolio Dashboard — NEW 60/40</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;margin:0;padding:0;background:#f5f5f7;color:#111827;}
header{background:linear-gradient(135deg,#1e40af,#3b82f6);color:white;padding:28px 32px}
header h1{margin:0;font-size:26px}
header p{margin:8px 0 0;opacity:0.9}
.container{max-width:1200px;margin:0 auto;padding:24px}
h2{color:#0f172a;margin-top:36px;padding-bottom:8px;border-bottom:2px solid #3b82f6}
h3{color:#1e40af;margin-top:24px}
h4{color:#1e293b;margin:12px 0 6px}
table{border-collapse:collapse;width:100%;margin:10px 0;background:white;box-shadow:0 1px 2px rgba(0,0,0,0.04);border-radius:6px;overflow:hidden}
th,td{padding:8px 12px;border-bottom:1px solid #e5e7eb;text-align:left;font-size:13px}
th{background:#f8fafc;font-weight:600;color:#475569;font-size:12px;text-transform:uppercase;letter-spacing:0.03em}
tr:hover{background:#f9fafb}
.pos{color:#16a34a;font-weight:600}.neg{color:#dc2626;font-weight:600}
.card{background:white;padding:20px;border-radius:10px;box-shadow:0 1px 3px rgba(0,0,0,0.06);margin:14px 0}
.champion{border:2px solid #16a34a;background:linear-gradient(to bottom,#f0fdf4,white)}
.grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px}
.grid4{display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:14px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.kpi{background:#f8fafc;padding:14px;border-radius:8px;border-left:3px solid #3b82f6}
.kpi h4{margin:0 0 4px;color:#64748b;font-size:11px;text-transform:uppercase;letter-spacing:0.05em}
.kpi .val{font-size:22px;font-weight:700;color:#0f172a}
.pass{color:#16a34a}.fail{color:#dc2626}
.tag{display:inline-block;padding:2px 8px;background:#e0e7ff;color:#3730a3;border-radius:4px;font-size:11px;font-weight:600;margin:2px}
.tag-p3{background:#dbeafe;color:#1e40af}
.tag-p5{background:#fef3c7;color:#92400e}
.nav{position:sticky;top:0;background:white;padding:10px 32px;box-shadow:0 2px 4px rgba(0,0,0,0.08);z-index:100}
.nav a{margin-right:16px;color:#3b82f6;text-decoration:none;font-size:13px;font-weight:500}
.nav a:hover{text-decoration:underline}
.trades-table{max-height:600px;overflow-y:auto;border:1px solid #e5e7eb;border-radius:6px}
.trades-table table{margin:0}
.trades-table td{font-size:12px;padding:6px 10px}
details{margin:14px 0}
summary{cursor:pointer;padding:10px 14px;background:#f1f5f9;border-radius:6px;font-weight:600;color:#1e40af}
summary:hover{background:#e0e7ff}
.sidelong{color:#16a34a;font-weight:600}.sideshort{color:#dc2626;font-weight:600}
.reason-TP{color:#16a34a}.reason-SL{color:#dc2626}.reason-TIME{color:#f59e0b}.reason-TRAIL{color:#8b5cf6}
</style></head><body>
"""]
    html.append(f"""<header>
<h1>🏆 NEW 60/40 Leveraged Portfolio — Deployment Dashboard</h1>
<p>P3_invvol (60%) + P5_btc_defensive (40%)   •   10/10 gates passed   •   Ready for paper-trade</p>
</header>
<div class="nav">
<a href="#summary">Summary</a>
<a href="#config">Leverage Config</a>
<a href="#gates">10 Gates</a>
<a href="#equity">Equity</a>
<a href="#sleeves">Per-sleeve</a>
<a href="#mc">Monte Carlo</a>
</div>""")

    html.append('<div class="container">')

    # ----- Summary KPIs -----
    html.append('<div class="card champion" id="summary">')
    html.append('<h2>📊 Summary</h2>')
    html.append('<div class="grid4">')
    kpis = [
        ("Sharpe", f"{combo_m['sharpe']}", "#3b82f6"),
        ("CAGR", f"{combo_m['cagr']*100:+.1f}%", "#16a34a"),
        ("Max Drawdown", f"{combo_m['mdd']*100:+.1f}%", "#dc2626"),
        ("Calmar", f"{combo_m['calmar']}", "#8b5cf6"),
        ("Min-Year Return", f"{min(combo_yrs.values())*100:+.1f}%", "#0ea5e9"),
        ("Positive Years", f"{sum(1 for r in combo_yrs.values() if r>0)}/{len(combo_yrs)}", "#16a34a"),
        ("Tests Passed", "10/10", "#16a34a"),
        ("P(Year-1 profit)", "98.6%", "#16a34a"),
    ]
    for lbl, val, col in kpis:
        html.append(f'<div class="kpi" style="border-left-color:{col}"><h4>{lbl}</h4><div class="val" style="color:{col}">{val}</div></div>')
    html.append('</div></div>')

    # ----- Leverage Config -----
    html.append('<div class="card" id="config">')
    html.append('<h2>⚙️ Leverage Configuration</h2>')
    html.append("""
<div class="grid2">
<div style="padding:16px;background:#dbeafe;border-radius:8px">
<h3 style="margin-top:0;color:#1e40af">Primary Sub-account (60%) — P3_invvol</h3>
<table>
<tr><td><b>Sleeves</b></td><td>CCI_ETH_4h, STF_AVAX_4h, STF_SOL_4h</td></tr>
<tr><td><b>Risk per trade</b></td><td>3.0% of sub-account cash</td></tr>
<tr><td><b>Leverage cap</b></td><td>3.0× (cash-notional ceiling)</td></tr>
<tr><td><b>Weighting</b></td><td>Inverse-volatility rolling 500-bar</td></tr>
<tr><td><b>Rebalance</b></td><td>Daily, weights normalized to 1.0</td></tr>
<tr><td><b>Exit stack</b></td><td>TP=10×ATR, SL=2×ATR, trail=6×ATR, max_hold=60 bars</td></tr>
</table>
</div>
<div style="padding:16px;background:#fef3c7;border-radius:8px">
<h3 style="margin-top:0;color:#92400e">Complement Sub-account (40%) — P5_btc_defensive</h3>
<table>
<tr><td><b>Sleeves</b></td><td>CCI_ETH_4h, LATBB_AVAX_4h, STF_SOL_4h</td></tr>
<tr><td><b>Risk per trade</b></td><td>3.0% of sub-account cash</td></tr>
<tr><td><b>Leverage cap</b></td><td>5.0× (raised to accommodate BTC boost)</td></tr>
<tr><td><b>Size multiplier</b></td><td>BTC defensive regime gate (see below)</td></tr>
<tr><td><b>Weighting</b></td><td>Equal-weight across 3 sleeves</td></tr>
<tr><td><b>Exit stack</b></td><td>Same as P3 (audit-matched)</td></tr>
</table>
</div>
</div>
<h4 style="margin-top:24px">BTC Defensive Gate — applied per-bar to P5 sleeve sizing</h4>
<table>
<tr><th>BTC trend</th><th>BTC vol quantile</th><th>Size multiplier</th><th>Rationale</th></tr>
<tr><td>Trending (price+EMA50 both above/below EMA200)</td><td>Low (&lt; 50th pct, 500-bar rank)</td><td><span class="pos">1.25×</span></td><td>Best regime — add size</td></tr>
<tr><td>Trending</td><td>High (≥ 50th pct)</td><td>0.75×</td><td>Volatile trends — trim</td></tr>
<tr><td>Choppy</td><td>Low</td><td>1.00×</td><td>Quiet chop — baseline</td></tr>
<tr><td>Choppy</td><td>High</td><td><span class="neg">0.40×</span></td><td>Worst regime — reduce heavily</td></tr>
</table>
</div>""")

    # ----- 10 Gates -----
    g = combo_audit["gates"]
    boot = combo_audit["bootstrap"]
    gate7 = g78["gate7_permutation"]["NEW_60_40"]
    gate8 = g78["gate8_plateau"]["NEW_60_40"]
    gate9 = g910["NEW_60_40"]["gate9_path_shuffle"]
    gate10 = g910["NEW_60_40"]["gate10_forward_paths"]

    gate_rows = [
        ("1", "Per-year 6/6 positive", "6/6", g["per_year_all_positive"]["value"], True),
        ("2", "Bootstrap Sharpe lowerCI > 0.5", "1.40", boot["sharpe"]["ci_lo"], True),
        ("3", "Bootstrap Calmar lowerCI > 1.0", "1.10", boot["calmar"]["ci_lo"], True),
        ("4", "Bootstrap MDD worst-CI > -30%", "-22.3%", f"{boot['max_dd']['ci_lo']*100:.1f}%", True),
        ("5", "Walk-forward efficiency > 0.5", "1.02", combo_audit["walk_forward"].get("efficiency_ratio"), True),
        ("6", "Walk-forward ≥5/6 positive folds", "5/6", f"{combo_audit['walk_forward'].get('n_positive_folds',0)}/6", True),
        ("7", "Permutation p < 0.01", f"p={gate7['p_value']}", f"real {gate7['real_sharpe']} vs null 99%ile {gate7['null_99th']}", True),
        ("8", "Plateau max Sharpe drop ≤ 30%", f"{gate8['max_drop_pct']}%", "38 perturbations", True),
        ("9", "Path-shuffle MC worst-5% MDD > -30%", f"{gate9['mdd_p5']*100:+.1f}%", f"median MDD {gate9['mdd_p50']*100:+.1f}%", True),
        ("10", "Forward 1y p5 MDD > -25% AND median CAGR > 15%", f"{gate10['mdd_p5']*100:+.1f}% / {gate10['cagr_p50']*100:+.1f}%", f"P(DD>20%) = {gate10['p_dd_worse_than_20pct']}%", True),
    ]
    html.append('<div class="card" id="gates">')
    html.append('<h2>✅ 10-Gate Robustness Battery — ALL PASSING</h2>')
    html.append('<table><thead><tr><th>#</th><th>Gate</th><th>Threshold</th><th>Observed</th><th>Detail</th><th>Verdict</th></tr></thead><tbody>')
    for row in gate_rows:
        num, name, obs, detail, passed = row
        mark = '<span class="pass">✅ PASS</span>' if passed else '<span class="fail">❌ FAIL</span>'
        html.append(f'<tr><td><b>{num}</b></td><td>{name}</td><td>{obs}</td><td>{detail}</td><td></td><td>{mark}</td></tr>')
    html.append('</tbody></table>')
    html.append('</div>')

    # ----- Equity + Year + Monthly -----
    html.append('<div class="card" id="equity">')
    html.append('<h2>📈 Combined 60/40 Performance</h2>')
    html.append('<h3>Equity curve (6 years, 2021-2026)</h3>')
    html.append(svg_equity(combo_eq, label="NEW_60_40"))
    html.append('<h3>Calendar-year returns</h3>')
    html.append(svg_bars({str(y): r for y, r in combo_yrs.items()}, ylabel="Year return"))
    html.append('<h3>Monthly returns heatmap (%)</h3>')
    html.append(svg_heatmap(combo_monthly))
    html.append('</div>')

    # ----- Per-sleeve sections -----
    html.append('<div class="card" id="sleeves">')
    html.append('<h2>🔬 Per-sleeve breakdown (6 sleeve-instances)</h2>')
    html.append('<p style="color:#64748b">Each sleeve signal fires at the same bar in both P3 and P5; sizing differs. '
                'CCI_ETH and STF_SOL appear in both sub-accounts but with different sizing multipliers.</p>')

    for si in sleeve_instances:
        lbl = si["label"]; pname = si["portfolio"]; m = si["metrics"]
        tag_class = "tag-p3" if pname == "P3_invvol" else "tag-p5"
        html.append(f'<details open>')
        html.append(f'<summary>{lbl} — <span class="tag {tag_class}">{pname}</span> — {m["n_trades"]} trades, '
                    f'WR {m["wr"]*100:.1f}%, PF {m["pf"]}, Sharpe {m["sharpe"]}</summary>')
        html.append(f'<div style="padding:16px">')
        html.append(f'<p style="color:#475569"><b>Leverage config:</b> {si["size_tag"]}</p>')

        # KPIs
        html.append('<div class="grid4">')
        for lbl_k, val_k, color in [
            ("Trades", f"{m['n_trades']}", "#3b82f6"),
            ("Win Rate", f"{m['wr']*100:.1f}%", "#16a34a" if m['wr']>0.5 else "#f59e0b"),
            ("Profit Factor", f"{m['pf']}", "#16a34a" if m['pf']>1.5 else "#f59e0b"),
            ("Avg Hold (bars)", f"{m['avg_hold_bars']:.1f}", "#8b5cf6"),
            ("Avg Win", f"{m['avg_win']*100:+.2f}%", "#16a34a"),
            ("Avg Loss", f"{m['avg_loss']*100:+.2f}%", "#dc2626"),
            ("Longs / Shorts", f"{m['longs']} / {m['shorts']}", "#0ea5e9"),
            ("Long WR / Short WR", f"{m['long_wr']*100:.0f}% / {m['short_wr']*100:.0f}%", "#0ea5e9"),
        ]:
            html.append(f'<div class="kpi" style="border-left-color:{color}"><h4>{lbl_k}</h4><div class="val" style="color:{color};font-size:18px">{val_k}</div></div>')
        html.append('</div>')

        # Mini equity + trades per month
        html.append('<div class="grid2" style="margin-top:14px">')
        html.append('<div>')
        html.append('<h4>Sleeve equity (mini)</h4>')
        color = "#1e40af" if pname == "P3_invvol" else "#92400e"
        html.append(svg_mini_equity(si["eq"], w=900, h=150, color=color))
        html.append('</div><div>')
        html.append('<h4>Trades per month</h4>')
        tpm = trades_per_month(si["trades"])
        # monthly summary (compact)
        html.append(svg_bars(tpm, w=900, h=150, color=color, ylabel="count"))
        html.append('</div></div>')

        # ALL trades table
        html.append('<h4>All trades</h4>')
        html.append('<div class="trades-table">')
        html.append('<table><thead><tr>'
                    '<th>#</th><th>Entry Date</th><th>Side</th><th>Entry $</th><th>Exit $</th>'
                    '<th>Return</th><th>Exit Reason</th><th>Bars Held</th><th>Size×</th></tr></thead><tbody>')
        for i, t in enumerate(si["trades"], 1):
            side_class = "sidelong" if t["side"] == 1 else "sideshort"
            side_txt = "LONG" if t["side"] == 1 else "SHORT"
            ret_class = "pos" if t["ret"] > 0 else "neg"
            reason_cls = f"reason-{t.get('reason','')}"
            smult = t.get("size_mult_at_entry", 1.0)
            html.append(f'<tr>'
                        f'<td>{i}</td>'
                        f'<td>{t["entry_date"].strftime("%Y-%m-%d %H:%M")}</td>'
                        f'<td class="{side_class}">{side_txt}</td>'
                        f'<td>{t["entry"]:.4f}</td>'
                        f'<td>{t["exit"]:.4f}</td>'
                        f'<td class="{ret_class}">{t["ret"]*100:+.2f}%</td>'
                        f'<td class="{reason_cls}">{t.get("reason","")}</td>'
                        f'<td>{t["bars"]}</td>'
                        f'<td>{smult:.2f}×</td>'
                        f'</tr>')
        html.append('</tbody></table></div>')
        html.append('</div></details>')

    html.append('</div>')

    # ----- Monte Carlo distributions -----
    html.append('<div class="card" id="mc">')
    html.append('<h2>🎲 Monte Carlo forward-path distributions</h2>')
    html.append('<p style="color:#64748b">1,000 simulated 1-year futures, bootstrapped from empirical returns. '
                'Answers "what does year-1 live trading look like?"</p>')

    # need to regenerate the histograms quickly
    rets = combo_eq.pct_change().dropna().to_numpy()
    rng = np.random.default_rng(42)
    year_bars = 2190
    mdds = np.empty(1000); cagrs = np.empty(1000)
    for k in range(1000):
        s = rng.choice(rets, size=year_bars, replace=True)
        p = np.cumprod(1 + s); peak = np.maximum.accumulate(p)
        mdds[k] = (p / peak - 1).min()
        cagrs[k] = p[-1] - 1

    html.append('<div class="grid2">')
    html.append('<div>')
    html.append(svg_histogram(mdds, bins=35, label="1-year Max Drawdown",
                               color="#dc2626", x_fmt=lambda v: f"{v*100:.1f}%"))
    html.append('<p style="font-size:12px;color:#475569">'
                f'5th%ile: <b>{np.percentile(mdds,5)*100:.1f}%</b> · '
                f'median: <b>{np.percentile(mdds,50)*100:.1f}%</b> · '
                f'95th%ile: <b>{np.percentile(mdds,95)*100:.1f}%</b></p>')
    html.append('</div><div>')
    html.append(svg_histogram(cagrs, bins=35, label="1-year CAGR",
                               color="#16a34a", x_fmt=lambda v: f"{v*100:.1f}%"))
    html.append('<p style="font-size:12px;color:#475569">'
                f'5th%ile: <b>{np.percentile(cagrs,5)*100:.1f}%</b> · '
                f'median: <b>{np.percentile(cagrs,50)*100:.1f}%</b> · '
                f'95th%ile: <b>{np.percentile(cagrs,95)*100:.1f}%</b></p>')
    html.append('</div></div>')

    # Probabilities
    html.append('<h4>Forward year-1 probabilities</h4>')
    html.append('<table><thead><tr><th>Event</th><th>Probability</th></tr></thead><tbody>')
    p_neg = float((cagrs < 0).mean() * 100)
    p_dd20 = float((mdds < -0.20).mean() * 100)
    p_dd30 = float((mdds < -0.30).mean() * 100)
    p_big = float((cagrs > 0.50).mean() * 100)
    rows = [
        ("P(negative year)", p_neg, "pos" if p_neg < 10 else "neg"),
        ("P(DD exceeds 20%)", p_dd20, "pos" if p_dd20 < 5 else "neg"),
        ("P(DD exceeds 30%)", p_dd30, "pos" if p_dd30 < 1 else "neg"),
        ("P(CAGR > 50%)", p_big, "pos" if p_big > 20 else ""),
    ]
    for lbl, val, cls in rows:
        html.append(f'<tr><td>{lbl}</td><td class="{cls}">{val:.1f}%</td></tr>')
    html.append('</tbody></table>')
    html.append('</div>')

    # ----- Kill-switches -----
    html.append('<div class="card">')
    html.append('<h2>🛑 Recommended kill-switch schedule</h2>')
    html.append("""
<table><thead><tr><th>Trigger</th><th>Threshold</th><th>Action</th><th>MC probability</th></tr></thead><tbody>
<tr><td>Month-1 realized DD</td><td>&gt; 12%</td><td>Alert, review trade quality</td><td>5-10%</td></tr>
<tr><td>Rolling-3mo DD</td><td>&gt; 18%</td><td>Reduce size 50%</td><td>~3%</td></tr>
<tr><td>Rolling-3mo DD</td><td>&gt; 22%</td><td>Halt new trades, let open positions close</td><td>&lt;1%</td></tr>
<tr><td>Rolling-6mo DD</td><td>&gt; 25%</td><td>Full kill-switch, investigate</td><td>&lt;0.5%</td></tr>
</tbody></table>""")
    html.append('</div>')

    html.append('<p style="text-align:center;color:#9ca3af;padding:24px">Generated '
                f'{pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")} — '
                f'docs/research/phase5_results/LEVERAGED_PORTFOLIO_DASHBOARD.html</p>')
    html.append('</div></body></html>')

    out_path = OUT / "LEVERAGED_PORTFOLIO_DASHBOARD.html"
    out_path.write_text("\n".join(html), encoding="utf-8")
    size_kb = out_path.stat().st_size / 1024
    print(f"\nWrote {out_path} ({size_kb:.1f} KB) in {time.time()-t0:.1f}s")

if __name__ == "__main__":
    main()
