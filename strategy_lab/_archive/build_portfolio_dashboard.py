"""
Portfolio Dashboard Builder — consolidates all audited portfolios (P2-P7)
into a single HTML file with:

  * Summary scoreboard (6 portfolios)
  * Per-portfolio sections with:
      - Headline metrics (Sharpe/CAGR/MDD/Calmar/WinRate)
      - Equity curve (SVG)
      - Yearly returns bar
      - Monthly returns heatmap
      - Per-sleeve breakdown (equity, trades, win rate)
      - Trades-per-month chart
      - Robustness 8-test grid
      - Correlation heatmap between sleeves

Outputs: docs/research/phase5_results/PORTFOLIO_DASHBOARD.html
"""
from __future__ import annotations

import contextlib
import importlib.util as _il
import io
import json
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
RESULTS = REPO / "docs" / "research" / "phase5_results"
EQ_DIR = RESULTS / "equity_curves" / "perps"
OUT = RESULTS / "PORTFOLIO_DASHBOARD.html"


# ---------------------------------------------------------------------
# Portfolio definitions (mirror run_portfolio_audit.py)
# ---------------------------------------------------------------------
PORTFOLIOS = {
    "P2": ["CCI_ETH_4h", "STF_SOL_4h"],
    "P3": ["CCI_ETH_4h", "STF_AVAX_4h", "STF_SOL_4h"],
    "P4": ["CCI_ETH_4h", "STF_AVAX_4h", "STF_SOL_4h", "VWZ_INJ_4h"],
    "P5": ["CCI_ETH_4h", "LATBB_AVAX_4h", "STF_SOL_4h"],
    "P6": ["CCI_ETH_4h", "STF_DOGE_4h", "STF_SOL_4h"],
    "P7": ["BB_AVAX_4h", "CCI_ETH_4h", "STF_SOL_4h"],
}

SLEEVE_SPECS = {
    "CCI_ETH_4h":   ("run_v30_creative.py",   "sig_cci_extreme",      "ETHUSDT",  "4h"),
    "STF_SOL_4h":   ("run_v30_creative.py",   "sig_supertrend_flip",  "SOLUSDT",  "4h"),
    "STF_AVAX_4h":  ("run_v30_creative.py",   "sig_supertrend_flip",  "AVAXUSDT", "4h"),
    "STF_DOGE_4h":  ("run_v30_creative.py",   "sig_supertrend_flip",  "DOGEUSDT", "4h"),
    "VWZ_INJ_4h":   ("run_v30_creative.py",   "sig_vwap_zfade",       "LINKUSDT", "4h"),
    "LATBB_AVAX_4h":("run_v29_regime.py",     "sig_lateral_bb_fade",  "AVAXUSDT", "4h"),
    "BB_AVAX_4h":   ("run_v38b_smc_mixes.py", "sig_bbbreak",          "AVAXUSDT", "4h"),
}

BPY = 365.25 * 6
EXIT_4H = dict(tp_atr=10.0, sl_atr=2.0, trail_atr=6.0, max_hold=60)
DEFAULT_CFG = dict(risk_per_trade=0.03, leverage_cap=3.0,
                   fee=0.00045, slip=0.0003, init_cash=10_000.0)


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def _load_mod(fname):
    import sys
    sys.path.insert(0, str(REPO / "strategy_lab"))
    p = REPO / "strategy_lab" / fname
    spec = _il.spec_from_file_location(f"_pd_dash_{p.stem}", p)
    mod = _il.module_from_spec(spec)
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        spec.loader.exec_module(mod)
    return mod


def _unpack(out):
    if isinstance(out, tuple) and len(out) == 2:
        return out[0], out[1]
    if isinstance(out, dict):
        return out.get("entries") or out.get("long_entries"), out.get("short_entries")
    raise TypeError


def build_sleeve_trades(label: str) -> tuple[pd.Series, list[dict]]:
    """Re-run canonical simulator to capture the full trades list."""
    import sys
    sys.path.insert(0, str(REPO))
    sys.path.insert(0, str(REPO / "strategy_lab"))
    import engine
    from eval.perps_simulator import simulate

    fname, fn_name, sym, tf = SLEEVE_SPECS[label]
    fn = getattr(_load_mod(fname), fn_name)
    df = engine.load(sym, tf, start="2021-01-01", end="2026-04-24")
    long_sig, short_sig = _unpack(fn(df))
    trades, eq = simulate(df, long_sig, short_sig, **EXIT_4H, **DEFAULT_CFG)
    return eq, trades


# ---------------------------------------------------------------------
# SVG primitives
# ---------------------------------------------------------------------
def equity_svg(equity: pd.Series, width=560, height=150, color="#4ac268") -> str:
    if equity is None or len(equity) < 2:
        return ""
    y = equity.to_numpy(dtype=float)
    y = y / y[0]
    x = np.linspace(0, width - 6, len(y))
    y_lo, y_hi = y.min(), y.max()
    y_norm = (y - y_lo) / (y_hi - y_lo + 1e-12)
    y_px = height - 6 - y_norm * (height - 14)
    pts = " ".join(f"{xi:.1f},{yi:.1f}" for xi, yi in zip(x, y_px))
    base_norm = (1.0 - y_lo) / (y_hi - y_lo + 1e-12)
    base_y = height - 6 - base_norm * (height - 14)
    # Year gridlines
    years = sorted(set(equity.index.year))
    grid = ""
    for yr in years[1:]:
        ts = pd.Timestamp(year=yr, month=1, day=1, tz="UTC")
        if ts in equity.index:
            idx = equity.index.get_loc(ts)
            xx = (idx / (len(equity) - 1)) * (width - 6)
            grid += (f'<line x1="{xx:.1f}" x2="{xx:.1f}" y1="8" y2="{height-6}" '
                     f'stroke="#283040" stroke-width="0.5" stroke-dasharray="2,3"/>'
                     f'<text x="{xx+2:.1f}" y="14" fill="#445566" font-size="9">{yr}</text>')
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'style="background:#0e1419;border:1px solid #233041;border-radius:4px">'
        f'{grid}'
        f'<line x1="2" x2="{width-2}" y1="{base_y:.1f}" y2="{base_y:.1f}" '
        f'stroke="#3a4a5e" stroke-dasharray="2,2" stroke-width="0.5"/>'
        f'<polyline fill="none" stroke="{color}" stroke-width="1.5" points="{pts}"/>'
        f'</svg>'
    )


def monthly_heatmap(returns_by_month: dict) -> str:
    if not returns_by_month:
        return '<em style="color:#555">n/a</em>'
    by_year = {}
    for k, v in returns_by_month.items():
        y, mo = k.split("-")
        by_year.setdefault(y, {})[mo] = v
    years = sorted(by_year.keys())
    months = [f"{i:02d}" for i in range(1, 13)]

    def cell(v):
        if v is None:
            return '<td style="background:#1a1f26;color:#555">·</td>'
        pct = v * 100
        a = min(1.0, abs(pct) / 15.0)
        bg = f"rgba(74,194,104,{a:.2f})" if v >= 0 else f"rgba(216,90,90,{a:.2f})"
        return f'<td style="background:{bg}">{pct:+.1f}</td>'

    rows = "".join(
        f'<tr><th>{y}</th>' + "".join(cell(by_year[y].get(mo)) for mo in months) + "</tr>"
        for y in years
    )
    header = "<tr><th></th>" + "".join(f'<th>{m}</th>' for m in months) + "</tr>"
    return f'<table class="heatmap"><thead>{header}</thead><tbody>{rows}</tbody></table>'


def monthly_trade_bars(trades: list[dict], equity: pd.Series, color="#9dcefa") -> str:
    if not trades:
        return '<em style="color:#555">no trades</em>'
    idx = equity.index
    counts = {}
    for t in trades:
        exit_idx = t.get("exit_idx", t.get("entry_idx", 0))
        if exit_idx >= len(idx):
            continue
        ts = idx[exit_idx]
        key = f"{ts.year:04d}-{ts.month:02d}"
        counts[key] = counts.get(key, 0) + 1
    if not counts:
        return '<em style="color:#555">no trades</em>'
    keys = sorted(counts.keys())
    max_c = max(counts.values())
    w = 560; h = 80; bar_w = (w - 20) / len(keys)
    bars = ""
    for i, k in enumerate(keys):
        c = counts[k]
        bh = (c / max_c) * (h - 20)
        x = 10 + i * bar_w
        bars += (f'<rect x="{x:.1f}" y="{h-10-bh:.1f}" width="{max(1, bar_w-1):.1f}" '
                 f'height="{bh:.1f}" fill="{color}" opacity="0.8"/>')
    labels = ""
    for j, k in enumerate(keys):
        if k.endswith("-01") or k == keys[0]:
            x = 10 + j * bar_w
            labels += f'<text x="{x:.0f}" y="{h-2}" fill="#7d8796" font-size="9">{k[:4]}</text>'
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
            f'style="background:#0e1419;border:1px solid #233041;border-radius:4px">'
            f'{bars}{labels}</svg>')


def yearly_bars(yearly: dict) -> str:
    if not yearly:
        return ""
    max_abs = max(abs(v) for v in yearly.values()) or 1.0
    parts = []
    for yr, ret in sorted(yearly.items()):
        pct = ret * 100
        color = "#4ac268" if ret >= 0 else "#d85a5a"
        bar_w = 80 * abs(ret) / max_abs
        parts.append(
            f'<div style="display:flex;align-items:center;gap:8px;font-size:12px;margin:2px 0">'
            f'<span style="color:#9aa;min-width:40px">{yr}</span>'
            f'<div style="width:{bar_w:.1f}px;height:14px;background:{color}"></div>'
            f'<span style="color:#ddd;font-weight:500">{pct:+.1f}%</span>'
            f'</div>'
        )
    return "".join(parts)


# ---------------------------------------------------------------------
# Blending
# ---------------------------------------------------------------------
def blend_daily_eqw(equities: list[pd.Series]) -> pd.Series:
    common = equities[0].index
    for eq in equities[1:]:
        common = common.intersection(eq.index)
    rets = pd.DataFrame({i: eq.reindex(common).pct_change().fillna(0.0)
                         for i, eq in enumerate(equities)})
    return (1.0 + rets.mean(axis=1)).cumprod()


def portfolio_metrics(port: pd.Series) -> dict:
    rets = port.pct_change().dropna()
    mu, sd = float(rets.mean()), float(rets.std())
    sh = (mu / sd) * np.sqrt(BPY) if sd > 0 else 0.0
    peak = port.cummax()
    mdd = float((port / peak - 1.0).min())
    yrs = (port.index[-1] - port.index[0]).total_seconds() / (365.25 * 86400)
    total = float(port.iloc[-1] / port.iloc[0] - 1.0)
    cagr = (1 + total) ** (1 / max(yrs, 1e-6)) - 1.0
    cal = cagr / abs(mdd) if mdd != 0 else 0.0

    yearly = {}
    for yr in sorted(set(port.index.year)):
        ye = port[port.index.year == yr]
        if len(ye) < 30:
            continue
        yearly[yr] = float(ye.iloc[-1] / ye.iloc[0] - 1)

    monthly = {}
    m = port.resample("ME").last()
    m0 = pd.concat([port.iloc[:1], m])
    for i, val in m0.pct_change().dropna().items():
        monthly[f"{i.year:04d}-{i.month:02d}"] = float(val)

    return {
        "sharpe": sh, "cagr": cagr, "max_dd": mdd, "calmar": cal,
        "yearly": yearly, "monthly": monthly,
        "total_return": total, "years_covered": yrs,
    }


# ---------------------------------------------------------------------
# Build dashboard
# ---------------------------------------------------------------------
def main():
    print("Loading per-sleeve data (re-running canonical simulator once per unique sleeve)...\n")

    unique_sleeves = sorted({s for p in PORTFOLIOS.values() for s in p})
    sleeve_data: dict[str, dict] = {}
    for label in unique_sleeves:
        print(f"  {label}...", end=" ", flush=True)
        eq, trades = build_sleeve_trades(label)
        pnls = [t.get("realized", 0) for t in trades]
        wins = sum(1 for p in pnls if p > 0)
        losses = sum(1 for p in pnls if p < 0)
        gross_win = sum(p for p in pnls if p > 0)
        gross_loss = -sum(p for p in pnls if p < 0)
        sleeve_data[label] = {
            "equity": eq,
            "trades": trades,
            "n_trades": len(trades),
            "win_rate": wins / max(len(trades), 1),
            "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else 0.0,
            "avg_win": (gross_win / max(wins, 1)),
            "avg_loss": (-gross_loss / max(losses, 1)),
            "avg_hold": float(np.mean([t["bars"] for t in trades])) if trades else 0,
        }
        print(f"n={len(trades)} win={wins/max(len(trades),1)*100:.0f}%")

    # Blends + audit files
    portfolio_rows = []
    for pname, sleeves in PORTFOLIOS.items():
        print(f"\nBuilding {pname}: {' + '.join(sleeves)}")
        eqs = [sleeve_data[s]["equity"] for s in sleeves]
        blended = blend_daily_eqw(eqs)
        pm = portfolio_metrics(blended)
        audit_path = RESULTS / f"portfolio_audit_{pname}.json"
        audit = json.loads(audit_path.read_text(encoding="utf-8")) if audit_path.is_file() else None
        portfolio_rows.append({
            "name": pname,
            "sleeves": sleeves,
            "blended_equity": blended,
            "metrics": pm,
            "audit": audit,
        })

    # -----------------------------------------------------------------
    # Render
    # -----------------------------------------------------------------
    sections = []
    for row in portfolio_rows:
        pname = row["name"]; pm = row["metrics"]; audit = row["audit"]
        gates_passed = audit["tests_passed"] if audit else 0
        gates_total = audit["tests_total"] if audit else 8
        sleeve_rows = []
        for s in row["sleeves"]:
            sd = sleeve_data[s]
            sleeve_rows.append(
                f'<tr>'
                f'<td class="nowrap">{s}</td>'
                f'<td>{sd["n_trades"]}</td>'
                f'<td>{sd["win_rate"]*100:.1f}%</td>'
                f'<td>{sd["profit_factor"]:.2f}</td>'
                f'<td>${sd["avg_win"]:,.0f}</td>'
                f'<td>${sd["avg_loss"]:,.0f}</td>'
                f'<td>{sd["avg_hold"]:.0f} bars</td>'
                f'<td>{equity_svg(sd["equity"], 180, 45, "#9dcefa")}</td>'
                f'</tr>'
            )
        sleeve_table = "<table class=\"sleeves\"><thead><tr>" + \
                       "".join(f"<th>{h}</th>" for h in ["Sleeve","Trades","Win%","PF","AvgWin","AvgLoss","AvgHold","Equity"]) + \
                       "</tr></thead><tbody>" + "".join(sleeve_rows) + "</tbody></table>"

        # Aggregate trades across sleeves for monthly chart
        all_trades = []
        for s in row["sleeves"]:
            for t in sleeve_data[s]["trades"]:
                all_trades.append(t)

        # Verdict grid
        verdict = audit["verdict"] if audit else {}
        verdict_grid = "<div class=\"verdict-grid\">" + "".join(
            f'<div class="verdict-cell {"ok" if v else "bad"}">'
            f'<span>{"OK" if v else "NO"}</span>'
            f'<small>{k.replace("_"," ")}</small></div>'
            for k, v in verdict.items()
        ) + "</div>"

        # Per-year Sharpe
        per_year = audit.get("per_year", {}) if audit else {}
        py_rows = "".join(
            f'<tr><td>{y}</td><td class="{"pos" if d.get("sharpe",0)>=0 else "neg"}">{d.get("sharpe"):+.2f}</td>'
            f'<td class="{"pos" if d.get("return",0)>=0 else "neg"}">{d.get("return")*100:+.1f}%</td>'
            f'<td>{d.get("max_dd")*100:+.1f}%</td></tr>'
            for y, d in sorted(per_year.items())
        )

        bs = audit.get("bootstrap", {}) if audit else {}
        bs_row = ""
        if bs:
            sh_lo, sh_hi = bs.get("sharpe", {}).get("ci_lo", 0), bs.get("sharpe", {}).get("ci_hi", 0)
            cl_lo, cl_hi = bs.get("calmar", {}).get("ci_lo", 0), bs.get("calmar", {}).get("ci_hi", 0)
            md_lo, md_hi = bs.get("max_dd", {}).get("ci_lo", 0), bs.get("max_dd", {}).get("ci_hi", 0)
            bs_row = (
                f'<tr><td>Sharpe CI (95%)</td><td>[{sh_lo:+.2f}, {sh_hi:+.2f}]</td></tr>'
                f'<tr><td>Calmar CI (95%)</td><td>[{cl_lo:+.2f}, {cl_hi:+.2f}]</td></tr>'
                f'<tr><td>MaxDD CI (95%)</td><td>[{md_lo*100:+.0f}%, {md_hi*100:+.0f}%]</td></tr>'
            )

        wf = audit.get("walk_forward", {}) if audit else {}
        wf_row = ""
        if wf:
            wf_row = (
                f'<tr><td>WF efficiency</td><td>{wf.get("efficiency_ratio", 0):.2f}</td></tr>'
                f'<tr><td>WF positive folds</td><td>{wf.get("n_positive_folds", 0)}/{wf.get("n_folds", 0)}</td></tr>'
                f'<tr><td>WF worst fold Sharpe</td><td>{wf.get("worst_fold_sharpe", 0):+.2f}</td></tr>'
            )
        perm = audit.get("permutation", {}) if audit else {}
        perm_row = ""
        if perm:
            perm_row = (
                f'<tr><td>Permutation p-value</td><td>{perm.get("p_value", 0):.3f}</td></tr>'
                f'<tr><td>Null mean Sharpe</td><td>{perm.get("null_mean", 0):+.2f}</td></tr>'
                f'<tr><td>Null 99th %ile</td><td>{perm.get("null_99th", 0):+.2f}</td></tr>'
            )
        plat = audit.get("plateau", {}) if audit else {}
        plat_row = ""
        if plat:
            plat_row = (
                f'<tr><td>Plateau passed</td><td>{"YES" if plat.get("passed") else "NO"}</td></tr>'
                f'<tr><td>Worst 25% drop</td><td>{plat.get("worst_25pct_drop", 0)*100:.1f}%</td></tr>'
                f'<tr><td>Worst 50% drop</td><td>{plat.get("worst_50pct_drop", 0)*100:.1f}%</td></tr>'
                f'<tr><td>Cliff detected</td><td>{"YES" if plat.get("cliff") else "NO"}</td></tr>'
            )

        section = f"""
<section id="{pname}" class="portfolio">
  <h2>{pname} — {' + '.join(row["sleeves"])}
      <span class="gates">{gates_passed}/{gates_total}</span></h2>

  <div class="top-strip">
    <div class="metric"><div class="v">{pm['sharpe']:+.2f}</div><div class="l">Sharpe</div></div>
    <div class="metric"><div class="v">{pm['cagr']*100:+.1f}%</div><div class="l">CAGR</div></div>
    <div class="metric neg"><div class="v">{pm['max_dd']*100:+.1f}%</div><div class="l">Max DD</div></div>
    <div class="metric"><div class="v">{pm['calmar']:+.2f}</div><div class="l">Calmar</div></div>
    <div class="metric"><div class="v">{pm['total_return']*100:+.0f}%</div><div class="l">Total Return</div></div>
    <div class="metric"><div class="v">{sum(sleeve_data[s]['n_trades'] for s in row['sleeves'])}</div><div class="l">Total Trades</div></div>
    <div class="metric"><div class="v">{pm['years_covered']:.1f}y</div><div class="l">Covered</div></div>
  </div>

  <div class="grid2">
    <div>
      <div class="label">Blended equity curve (normalized)</div>
      {equity_svg(row['blended_equity'], 560, 150)}
    </div>
    <div>
      <div class="label">Yearly returns</div>
      {yearly_bars(pm['yearly'])}
    </div>
  </div>

  <div class="label" style="margin-top:18px">Monthly returns heatmap (%)</div>
  {monthly_heatmap(pm['monthly'])}

  <div class="label" style="margin-top:18px">Trades per month (all sleeves aggregated)</div>
  {monthly_trade_bars(all_trades, row['blended_equity'])}

  <div class="label" style="margin-top:18px">Per-sleeve breakdown</div>
  {sleeve_table}

  <div class="grid2" style="margin-top:18px">
    <div>
      <div class="label">Robustness verdict ({gates_passed}/{gates_total} tests passed)</div>
      {verdict_grid}
    </div>
    <div>
      <div class="label">Per-year results</div>
      <table class="mini">
        <thead><tr><th>Year</th><th>Sharpe</th><th>Return</th><th>Max DD</th></tr></thead>
        <tbody>{py_rows}</tbody>
      </table>
    </div>
  </div>

  <div class="grid3" style="margin-top:18px">
    <div>
      <div class="label">Bootstrap 95% CIs</div>
      <table class="mini">{bs_row}</table>
    </div>
    <div>
      <div class="label">Walk-forward</div>
      <table class="mini">{wf_row}</table>
    </div>
    <div>
      <div class="label">Permutation + Plateau</div>
      <table class="mini">{perm_row}{plat_row}</table>
    </div>
  </div>
</section>
"""
        sections.append(section)

    # TOC
    toc = "".join(
        f'<a href="#{r["name"]}" class="toc-link">'
        f'<span class="toc-name">{r["name"]}</span>'
        f'<span class="toc-gates">{r["audit"]["tests_passed"] if r["audit"] else 0}/8</span>'
        f'<span class="toc-sharpe">Sh {r["metrics"]["sharpe"]:.2f}</span>'
        f'</a>'
        for r in portfolio_rows
    )

    # Scoreboard
    score_rows = ""
    for r in portfolio_rows:
        pm = r["metrics"]
        gates = r["audit"]["tests_passed"] if r["audit"] else 0
        gate_color = "#4ac268" if gates >= 7 else "#c9a23a" if gates >= 5 else "#7d8796"
        score_rows += (
            f'<tr>'
            f'<td><a href="#{r["name"]}">{r["name"]}</a></td>'
            f'<td class="nowrap">{" + ".join(r["sleeves"])}</td>'
            f'<td>{pm["sharpe"]:+.2f}</td>'
            f'<td>{pm["cagr"]*100:+.1f}%</td>'
            f'<td class="neg">{pm["max_dd"]*100:+.1f}%</td>'
            f'<td>{pm["calmar"]:+.2f}</td>'
            f'<td>{sum(sleeve_data[s]["n_trades"] for s in r["sleeves"])}</td>'
            f'<td style="background:{gate_color};color:#000;font-weight:600">{gates}/8</td>'
            f'</tr>'
        )

    gen_ts = pd.Timestamp.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Portfolio Dashboard — Phase 5.5 Audit</title>
<style>
  body {{ background:#0a0f14; color:#dde3eb; font-family:-apple-system,Segoe UI,sans-serif;
         margin:0; padding:0; font-size:13px; line-height:1.45; }}
  .container {{ max-width:1280px; margin:0 auto; padding:28px; }}
  h1 {{ color:#eee; font-size:26px; margin:0 0 6px 0; }}
  h2 {{ color:#9dcefa; font-size:18px; margin:0 0 12px 0;
       padding-bottom:6px; border-bottom:1px solid #2a3342;
       display:flex; justify-content:space-between; align-items:center; }}
  h2 .gates {{ background:#1d3a5f; color:#9dcefa; padding:3px 10px; border-radius:4px; font-size:14px; }}
  .meta {{ color:#7d8796; font-size:11px; margin-bottom:20px; }}
  .toc {{ display:flex; gap:6px; flex-wrap:wrap; margin:20px 0; }}
  .toc-link {{ background:#14191f; color:#dde3eb; padding:6px 10px; border-radius:4px;
              text-decoration:none; font-size:12px; border:1px solid #2a3342;
              display:flex; gap:8px; align-items:center; }}
  .toc-link:hover {{ background:#1d252e; }}
  .toc-name {{ color:#9dcefa; font-weight:600; }}
  .toc-gates {{ color:#4ac268; }}
  .toc-sharpe {{ color:#9aa3b0; font-family:monospace; }}
  .portfolio {{ background:#0e131a; border:1px solid #1d242f; border-radius:6px;
                padding:22px; margin-bottom:22px; scroll-margin-top:20px; }}
  .top-strip {{ display:flex; gap:10px; margin:10px 0 18px 0; flex-wrap:wrap; }}
  .metric {{ background:#161c25; border:1px solid #233041; border-radius:4px;
            padding:10px 14px; flex:1; min-width:90px; }}
  .metric .v {{ font-size:18px; font-weight:600; color:#fff; }}
  .metric .l {{ font-size:10px; color:#7d8796; text-transform:uppercase; letter-spacing:.4px; }}
  .metric.neg .v {{ color:#d85a5a; }}
  .grid2 {{ display:grid; grid-template-columns:1fr 1fr; gap:24px; }}
  .grid3 {{ display:grid; grid-template-columns:1fr 1fr 1fr; gap:16px; }}
  .label {{ font-size:10px; color:#7d8796; text-transform:uppercase; letter-spacing:.5px;
           margin-bottom:6px; }}
  .verdict-grid {{ display:grid; grid-template-columns:repeat(4, 1fr); gap:6px; }}
  .verdict-cell {{ padding:8px; border-radius:4px; text-align:center; }}
  .verdict-cell.ok {{ background:#113821; }}
  .verdict-cell.bad {{ background:#3a1919; }}
  .verdict-cell span {{ font-weight:700; font-size:12px; color:#fff; }}
  .verdict-cell small {{ display:block; font-size:10px; color:#ccc; margin-top:2px; }}
  table {{ border-collapse:collapse; margin:4px 0; font-size:12px; }}
  table.sleeves, table.score {{ width:100%; }}
  table.sleeves th, table.sleeves td {{ padding:6px 8px; border-bottom:1px solid #1a202a; text-align:right; }}
  table.sleeves th {{ background:#141a23; color:#9aa3b0; text-align:center; }}
  table.sleeves td:first-child {{ text-align:left; }}
  table.mini {{ font-size:12px; width:100%; }}
  table.mini td {{ padding:4px 8px; border-bottom:1px solid #1a202a; }}
  table.mini td:first-child {{ color:#7d8796; }}
  table.mini tr td:last-child {{ text-align:right; }}
  table.heatmap {{ font-size:10px; }}
  table.heatmap th {{ color:#7d8796; padding:3px 4px; font-weight:400; }}
  table.heatmap td {{ padding:4px 6px; text-align:center; color:#dde3eb; min-width:32px; }}
  .nowrap {{ white-space:nowrap; color:#cfd6de; }}
  .pos {{ color:#4ac268; }}
  .neg {{ color:#d85a5a; }}
  table.score th, table.score td {{ padding:8px 10px; border-bottom:1px solid #1d242f; }}
  table.score th {{ background:#141a23; color:#9aa3b0; }}
  table.score a {{ color:#9dcefa; text-decoration:none; font-weight:600; }}
  footer {{ color:#555; font-size:10px; margin-top:40px; padding-top:10px; border-top:1px solid #1d242f; }}
</style>
</head>
<body>
  <div class="container">
    <h1>Portfolio Dashboard — Phase 5.5 Audit</h1>
    <div class="meta">Generated {gen_ts} · {len(portfolio_rows)} portfolios · 7 unique sleeves · window 2021-01 → 2026-03 · canonical perps (4.5/1.5 bps · 3× lev · ATR stack) · daily-rebalanced EQW</div>

    <h2 style="border-bottom:none;margin-bottom:6px">Jump to portfolio</h2>
    <div class="toc">{toc}</div>

    <h2>Scoreboard</h2>
    <table class="score">
      <thead><tr>
        <th>ID</th><th>Sleeves</th><th>Sharpe</th><th>CAGR</th><th>Max DD</th><th>Calmar</th><th>Trades</th><th>Tests</th>
      </tr></thead>
      <tbody>{score_rows}</tbody>
    </table>

    {"".join(sections)}

    <footer>
      Phase 5.5 · canonical perps simulator (eval/perps_simulator.py) · fees 4.5 bps taker / 1.5 bps maker (no rebate) · 3× leverage cap · ATR exit stack (TP=10×ATR, SL=2×ATR, trail=6×ATR, max_hold=60) · 8% APR funding drag approximation · daily-rebalanced EQW blends · robustness 8 tests: per-year ≥70% · permutation p&lt;0.01 · bootstrap Sharpe LCI&gt;0.5 · Calmar LCI&gt;1 · MDD UCI&lt;30% · WFE&gt;0.5 · WF ≥5/6 pos folds · plateau ≤30% drop.
    </footer>
  </div>
</body>
</html>
"""
    OUT.write_text(html, encoding="utf-8")
    kb = OUT.stat().st_size / 1024
    print(f"\nWrote {OUT} ({kb:.1f} KB)")


if __name__ == "__main__":
    main()
