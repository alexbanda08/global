"""Self-contained dashboard for derivatives_zscore gauntlet results.

Reads:  strategy_lab/reports/derivatives_zscore/gauntlet_results.csv
        strategy_lab/reports/derivatives_zscore/equity_curves/{file}.parquet
        strategy_lab/reports/derivatives_zscore/extras_{symbol}.json

Writes: strategy_lab/reports/derivatives_zscore/DASHBOARD.html
"""
from __future__ import annotations
from pathlib import Path
import json
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
REP = ROOT / "strategy_lab" / "reports" / "derivatives_zscore"
EQ = REP / "equity_curves"
OUT = REP / "DASHBOARD.html"


# ───────────────────────── helpers ─────────────────────────

def fmt_pct(v, sign=False):
    try:
        f = float(v)
        if pd.isna(f):
            return "–"
        return f"{f*100:{'+' if sign else ''}.1f}%"
    except Exception:
        return "–"


def fmt_num(v, d=2, sign=False):
    try:
        f = float(v)
        if pd.isna(f):
            return "–"
        return f"{f:{'+' if sign else ''}.{d}f}"
    except Exception:
        return "–"


def equity_svg(eq: pd.Series, w=420, h=110) -> str:
    if eq is None or len(eq) < 2:
        return ""
    y = eq.to_numpy(dtype=float)
    y = y / y[0]
    x = np.linspace(0, w - 4, len(y))
    y_norm = (y - y.min()) / (y.max() - y.min() + 1e-12)
    y_px = h - 4 - y_norm * (h - 8)
    pts = " ".join(f"{xi:.1f},{yi:.1f}" for xi, yi in zip(x, y_px))
    color = "#1f9d55" if y[-1] >= 1.0 else "#c23a3a"
    base = (1.0 - y.min()) / (y.max() - y.min() + 1e-12)
    base_y = h - 4 - base * (h - 8)
    return (
        f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
        f'style="background:#0f1419;border:1px solid #23303e;border-radius:3px">'
        f'<line x1="2" x2="{w-2}" y1="{base_y:.1f}" y2="{base_y:.1f}" '
        f'stroke="#3a4a5e" stroke-dasharray="2,2" stroke-width="0.5"/>'
        f'<polyline fill="none" stroke="{color}" stroke-width="1.5" points="{pts}"/>'
        f'</svg>'
    )


def monthly_heatmap(monthly_json: str) -> str:
    if not monthly_json:
        return '<span style="color:#666">n/a</span>'
    try:
        m = json.loads(monthly_json)
    except Exception:
        return ""
    if not m:
        return ""
    by_year: dict[str, dict[str, float]] = {}
    for k, v in m.items():
        y, mo = k.split("-")
        by_year.setdefault(y, {})[mo] = v
    years = sorted(by_year.keys())
    months = [f"{i:02d}" for i in range(1, 13)]

    def cell(v):
        if v is None:
            return '<td style="background:#1a1f26;color:#555">·</td>'
        pct = v * 100
        if v >= 0:
            a = min(1.0, abs(pct) / 10.0)
            bg = f"rgba(31,157,85,{a:.2f})"
        else:
            a = min(1.0, abs(pct) / 10.0)
            bg = f"rgba(194,58,58,{a:.2f})"
        return f'<td style="background:{bg}" title="{pct:+.1f}%">{pct:+.1f}</td>'

    rows = "".join(
        f'<tr><th style="text-align:right;padding:2px 6px">{y}</th>' +
        "".join(cell(by_year[y].get(mo)) for mo in months) + "</tr>"
        for y in years
    )
    header = "<tr><th></th>" + "".join(f'<th>{m}</th>' for m in months) + "</tr>"
    return f'<table class="heatmap"><thead>{header}</thead><tbody>{rows}</tbody></table>'


def yearly_bars(yearly_json: str) -> str:
    if not yearly_json:
        return ""
    try:
        y = json.loads(yearly_json)
    except Exception:
        return ""
    if not y:
        return ""
    max_abs = max(abs(v) for v in y.values()) or 1.0
    parts = []
    for yr, ret in sorted(y.items()):
        pct = ret * 100
        color = "#1f9d55" if ret >= 0 else "#c23a3a"
        bar_w = 60 * abs(ret) / max_abs
        parts.append(
            f'<div style="display:flex;align-items:center;gap:6px;font-size:11px;margin:1px 0">'
            f'<span style="color:#9aa;min-width:40px">{yr}</span>'
            f'<div style="width:{bar_w:.1f}px;height:10px;background:{color}"></div>'
            f'<span style="color:#ddd">{pct:+.1f}%</span></div>'
        )
    return "".join(parts)


def gate_grid(gates: dict) -> str:
    """Render 10 gates as colored chips."""
    parts = []
    for name, passed in gates.items():
        color = "#1f9d55" if passed else "#c23a3a"
        label = name.replace("_", " ")
        parts.append(
            f'<span style="background:{color};color:#fff;padding:3px 8px;border-radius:3px;'
            f'font-size:10px;margin:2px;display:inline-block;font-family:monospace">{label}</span>'
        )
    return "".join(parts)


def gate_count(n: int, total: int = 10) -> str:
    color = "#1f9d55" if n >= 7 else "#c9a23a" if n >= 5 else "#9b6a40" if n >= 3 else "#6b6b6b"
    return f'<span style="background:{color};color:#000;padding:3px 9px;border-radius:3px;font-weight:700">{n}/{total}</span>'


def trade_quartile_table(extras: dict) -> str:
    py = extras.get("per_year", {})
    if not py:
        return '<em style="color:#666">no per-year data</em>'
    rows = []
    for yr, info in sorted(py.items()):
        sh = info.get("sharpe", 0)
        ret = info.get("return", 0)
        dd = info.get("max_dd", 0)
        rows.append(
            f'<tr><td>{yr}</td>'
            f'<td class="{"pos" if sh>=0 else "neg"}">{sh:+.2f}</td>'
            f'<td class="{"pos" if ret>=0 else "neg"}">{ret*100:+.1f}%</td>'
            f'<td class="neg">{dd*100:+.1f}%</td>'
            f'<td>{info.get("n_bars",0):,}</td></tr>'
        )
    return (
        '<table class="mini"><thead><tr>'
        '<th>Year</th><th>Sharpe</th><th>Ret</th><th>MaxDD</th><th>Bars</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table>'
    )


def wf_table(extras: dict) -> str:
    wf = extras.get("walk_forward", {})
    folds = wf.get("folds", [])
    if not folds:
        return '<em style="color:#666">no WF data</em>'
    rows = []
    for f in folds:
        sh = f.get("sharpe", 0)
        ret = f.get("return", 0)
        rows.append(
            f'<tr><td>{f["fold"]}</td>'
            f'<td>{f["n_bars"]:,}</td>'
            f'<td>{f["n_trades"]}</td>'
            f'<td class="{"pos" if sh>=0 else "neg"}">{sh:+.2f}</td>'
            f'<td class="{"pos" if ret>=0 else "neg"}">{ret*100:+.1f}%</td></tr>'
        )
    eff = wf.get("efficiency_ratio", 0)
    summary = (f'<div style="margin-top:6px;font-size:11px;color:#9aa">'
               f'IS Sharpe: {wf.get("is_sharpe",0):+.2f} · Avg test Sharpe: {wf.get("avg_test_sharpe",0):+.2f} · '
               f'Efficiency: <strong style="color:{"#1f9d55" if eff>=0.5 else "#c23a3a"}">{eff:.2f}</strong> · '
               f'Positive folds: {wf.get("n_positive_folds",0)}/{len(folds)}</div>')
    return (
        '<table class="mini"><thead><tr><th>Fold</th><th>Bars</th><th>Trades</th><th>Sharpe</th><th>Ret</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table>{summary}'
    )


def param_grid_table(extras: dict) -> str:
    g = extras.get("parameter_sensitivity", {}).get("grid", [])
    if not g:
        return '<em style="color:#666">no grid</em>'
    rows = []
    for x in g:
        sh = x.get("sharpe", 0)
        ret = x.get("return", 0)
        rows.append(
            f'<tr><td>{x["z_thr"]:+.1f}</td><td>{x["hold_h"]}h</td><td>{x["n_trades"]}</td>'
            f'<td class="{"pos" if sh>=0 else "neg"}">{sh:+.2f}</td>'
            f'<td class="{"pos" if ret>=0 else "neg"}">{ret*100:+.1f}%</td></tr>'
        )
    return (
        '<table class="mini"><thead><tr><th>z_thr</th><th>hold</th><th>n</th><th>Sharpe</th><th>Ret</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table>'
    )


def cost_grid_table(extras: dict) -> str:
    g = extras.get("cost_stress", {}).get("grid", [])
    if not g:
        return '<em style="color:#666">no cost data</em>'
    rows = []
    for x in g:
        pf = x.get("pf", 0)
        ret = x.get("return", 0)
        rows.append(
            f'<tr><td>{x["bps_rt"]} bps</td><td>{x["n"]}</td>'
            f'<td class="{"pos" if pf>=1 else "neg"}">{pf:.2f}</td>'
            f'<td class="{"pos" if ret>=0 else "neg"}">{ret*100:+.1f}%</td></tr>'
        )
    return (
        '<table class="mini"><thead><tr><th>Cost</th><th>n</th><th>PF</th><th>Ret</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table>'
    )


def boot_table(extras: dict) -> str:
    bs = extras.get("bootstrap", {})
    if not bs:
        return '<em style="color:#666">no bootstrap</em>'
    rows = []
    for metric in ["sharpe", "calmar", "max_dd"]:
        d = bs.get(metric, {})
        if not d:
            continue
        rows.append(
            f'<tr><td>{metric}</td>'
            f'<td>{d.get("mean",0):+.3f}</td>'
            f'<td>{d.get("ci_lo",0):+.3f}</td>'
            f'<td>{d.get("ci_hi",0):+.3f}</td></tr>'
        )
    perm = extras.get("perm", {})
    perm_row = (f'<tr><td>perm_p</td><td colspan="3">'
                f'p={perm.get("p_value",0):.4f}  (n={perm.get("n_iter",0)})</td></tr>') if perm else ""
    return (
        '<table class="mini"><thead><tr><th>Metric</th><th>Mean</th><th>CI lo</th><th>CI hi</th></tr></thead>'
        f'<tbody>{"".join(rows)}{perm_row}</tbody></table>'
    )


# ───────────────────────── main ─────────────────────────

def build() -> str:
    df = pd.read_csv(REP / "gauntlet_results.csv")

    total = len(df)
    pass7 = (df["gates_passed"] >= 7).sum()
    pass5 = (df["gates_passed"] >= 5).sum()
    total_trades = int(df["n_trades"].sum())
    best_calmar = df["oos_calmar"].max()
    best_sharpe = df["oos_sharpe"].max()

    # Per-cell content
    cells_html = []
    for _, row in df.iterrows():
        sym = row["symbol"]
        # equity
        eq_path = EQ / row["equity_file"]
        eq = pd.read_parquet(eq_path)["equity"] if eq_path.exists() else None
        # extras
        ex_path = REP / f"extras_{sym}.json"
        extras = json.loads(ex_path.read_text()) if ex_path.exists() else {}

        cells_html.append(f"""
<section class="cell">
  <div class="cell-head">
    <h3>{sym} · 1h · z_lsr&lt;{row['z_thr']:+.1f} hold {int(row['hold_h'])}h</h3>
    <div>{gate_count(int(row['gates_passed']))}</div>
  </div>

  <div class="cell-grid">
    <div>
      <div class="label">Equity (normalized, 1.0 baseline)</div>
      {equity_svg(eq, 420, 110)}
      <div style="font-size:11px;color:#9aa;margin-top:4px">
        Final: <strong style="color:#fff">{row['final_equity_x']:.3f}×</strong> ·
        Buy-hold: <strong>{row['buy_hold_x']:.3f}×</strong> ·
        Outperform: <strong style="color:{'#1f9d55' if row['final_equity_x']>=row['buy_hold_x'] else '#c23a3a'}">{row['final_equity_x']/row['buy_hold_x']:.2f}×</strong>
      </div>
    </div>

    <div>
      <div class="label">Yearly returns</div>
      {yearly_bars(row['yearly_returns'])}
    </div>

    <div>
      <div class="label">Core metrics (3y)</div>
      <table class="mini">
        <tr><td>CAGR</td><td>{fmt_pct(row.get('oos_cagr',0), True)}</td></tr>
        <tr><td>Sharpe / Sortino</td><td>{fmt_num(row.get('oos_sharpe',0),2,sign=True)} / {fmt_num(row.get('oos_sortino',0),2,sign=True)}</td></tr>
        <tr><td>Calmar / UPI</td><td>{fmt_num(row.get('oos_calmar',0),2,sign=True)} / {fmt_num(row.get('oos_upi',0),2,sign=True)}</td></tr>
        <tr><td>Max DD / dur / rec</td><td>{fmt_pct(row.get('oos_max_dd',0))} / {int(row.get('oos_dd_duration_bars',0))}b / {int(row.get('oos_dd_recovery_bars',0))}b</td></tr>
        <tr><td>Profit factor</td><td>{fmt_num(row.get('profit_factor',0),2)}</td></tr>
        <tr><td>Win rate / avg hold</td><td>{fmt_num(row.get('win_rate',0)*100,1)}% / {fmt_num(row.get('avg_hold_h',0),1)}h</td></tr>
        <tr><td>Avg win / loss</td><td>{fmt_num(row.get('avg_win',0)*100,2)}% / {fmt_num(row.get('avg_loss',0)*100,2)}%</td></tr>
        <tr><td>Tail / Ulcer</td><td>{fmt_num(row.get('oos_tail_ratio',0),2)} / {fmt_num(row.get('oos_ulcer',0),2)}</td></tr>
        <tr><td>PSR / DSR</td><td>{fmt_num(row.get('oos_psr',0),3)} / {fmt_num(row.get('oos_dsr',0),3)}</td></tr>
        <tr><td>Trades</td><td>{int(row['n_trades']):,}</td></tr>
      </table>
    </div>

    <div>
      <div class="label">Per-year breakdown</div>
      {trade_quartile_table(extras)}
    </div>

    <div>
      <div class="label">Walk-forward (6 folds, anchored)</div>
      {wf_table(extras)}
    </div>

    <div>
      <div class="label">Parameter sensitivity (z × hold grid)</div>
      {param_grid_table(extras)}
    </div>

    <div>
      <div class="label">Cost stress</div>
      {cost_grid_table(extras)}
    </div>

    <div>
      <div class="label">Bootstrap CIs &amp; Permutation</div>
      {boot_table(extras)}
    </div>
  </div>

  <div class="label" style="margin-top:14px">10-Gate validation</div>
  <div>{gate_grid(extras.get('gates', {}))}</div>

  <div class="label" style="margin-top:14px">Monthly returns (%)</div>
  {monthly_heatmap(row['monthly_returns'])}
</section>
""")

    cells_block = "\n".join(cells_html)

    # Top table
    top_rows = []
    for _, row in df.sort_values("gates_passed", ascending=False).iterrows():
        outperf = row['final_equity_x'] / row['buy_hold_x']
        top_rows.append(f"""
<tr>
  <td><strong>{row['symbol']}</strong></td>
  <td>{int(row['n_trades'])}</td>
  <td>{fmt_num(row['win_rate']*100,1)}%</td>
  <td>{fmt_num(row['profit_factor'],2)}</td>
  <td class="{'pos' if row['oos_sharpe']>=0 else 'neg'}">{fmt_num(row['oos_sharpe'],2,sign=True)}</td>
  <td class="{'pos' if row['oos_calmar']>=0 else 'neg'}">{fmt_num(row['oos_calmar'],2,sign=True)}</td>
  <td class="neg">{fmt_pct(row['oos_max_dd'])}</td>
  <td>{fmt_num(row['oos_sortino'],2,sign=True)}</td>
  <td>{fmt_num(row['oos_dsr'],3)}</td>
  <td>{fmt_num(row['oos_psr'],3)}</td>
  <td>{fmt_num(row['final_equity_x'],3)}×</td>
  <td>{fmt_num(row['buy_hold_x'],3)}×</td>
  <td class="{'pos' if outperf>=1 else 'neg'}">{outperf:.2f}×</td>
  <td>{gate_count(int(row['gates_passed']))}</td>
</tr>""")
    summary_table = "\n".join(top_rows)

    gen_ts = pd.Timestamp.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Crypto Derivatives Z-Score · 10-Gate Dashboard</title>
<style>
  body {{ background:#0b1016; color:#dde3eb; font-family:-apple-system,Segoe UI,Roboto,sans-serif; margin:0; padding:24px; font-size:13px; }}
  h1 {{ color:#eee; font-size:24px; margin:0 0 4px 0; }}
  h2 {{ color:#9dcefa; font-size:16px; margin-top:30px; border-bottom:1px solid #2a3342; padding-bottom:4px; }}
  h3 {{ color:#cfd6de; font-size:15px; margin:0; }}
  .meta {{ color:#7d8796; font-size:11px; }}
  .summary-tiles {{ display:flex; gap:14px; margin:20px 0; flex-wrap:wrap; }}
  .tile {{ background:#151b24; border:1px solid #2a3342; border-radius:5px; padding:12px 18px; min-width:120px; }}
  .tile .val {{ font-size:24px; color:#fff; font-weight:600; }}
  .tile .lab {{ font-size:10px; color:#7d8796; text-transform:uppercase; letter-spacing:0.5px; }}
  table {{ border-collapse:collapse; }}
  table.summary {{ width:100%; font-size:12px; }}
  table.summary th, table.summary td {{ padding:6px 9px; text-align:right; border-bottom:1px solid #1d242f; }}
  table.summary th {{ background:#141a23; color:#9aa3b0; text-align:center; font-weight:600; border-bottom:2px solid #2a3342; }}
  table.summary tbody tr:hover {{ background:#121820; }}
  table.summary td:first-child {{ text-align:left; color:#cfd6de; }}
  table.mini {{ font-size:11px; }}
  table.mini th {{ background:#141a23; color:#9aa3b0; padding:3px 8px; text-align:right; font-weight:600; }}
  table.mini th:first-child {{ text-align:left; }}
  table.mini td {{ padding:3px 8px; border-bottom:1px solid #1a202a; text-align:right; }}
  table.mini td:first-child {{ color:#7d8796; text-align:left; }}
  table.heatmap {{ font-size:10px; }}
  table.heatmap th {{ color:#7d8796; padding:2px 4px; font-weight:400; }}
  table.heatmap td {{ padding:3px 5px; text-align:center; color:#dde3eb; }}
  .pos {{ color:#4ac268; }}
  .neg {{ color:#d85a5a; }}
  .cell {{ background:#0e131a; border:1px solid #1d242f; border-radius:5px; padding:18px; margin-bottom:18px; }}
  .cell-head {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:14px; }}
  .cell-grid {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap:18px; }}
  .label {{ font-size:10px; color:#7d8796; text-transform:uppercase; letter-spacing:0.5px; margin-bottom:6px; font-weight:600; }}
  footer {{ color:#555; font-size:10px; margin-top:40px; border-top:1px solid #1d242f; padding-top:10px; }}

  details.explainer {{ background:#0e131a; border:1px solid #2a3342; border-radius:6px; padding:0; margin:18px 0; }}
  details.explainer summary {{ padding:14px 20px; cursor:pointer; color:#9dcefa; font-size:14px; font-weight:600; user-select:none; outline:none; }}
  details.explainer summary:hover {{ background:#141a23; }}
  details.explainer[open] summary {{ border-bottom:1px solid #1d242f; }}
  .explainer-body {{ padding:16px 24px 24px 24px; line-height:1.55; color:#cfd6de; }}
  .explainer-body h3 {{ color:#9dcefa; font-size:13px; margin-top:22px; margin-bottom:8px; text-transform:uppercase; letter-spacing:0.6px; border-left:3px solid #2d6cb0; padding-left:8px; }}
  .explainer-body h3:first-child {{ margin-top:0; }}
  .explainer-body p {{ margin:8px 0; font-size:13px; }}
  .explainer-body code {{ background:#1a212c; color:#e0b280; padding:1px 5px; border-radius:2px; font-size:12px; }}
  .explainer-body pre {{ background:#0a0e14; border:1px solid #1d242f; border-radius:4px; padding:12px; font-size:11px; color:#cfd6de; overflow-x:auto; }}
  .explainer-body em {{ color:#9aa3b0; font-style:italic; }}
  .explainer-body strong {{ color:#fff; }}
  table.ref {{ width:100%; font-size:12px; margin:8px 0 10px 0; }}
  table.ref th {{ background:#141a23; color:#9aa3b0; padding:6px 9px; text-align:left; font-weight:600; border-bottom:2px solid #2a3342; }}
  table.ref td {{ padding:5px 9px; border-bottom:1px solid #1a202a; vertical-align:top; }}
  table.ref td:first-child {{ color:#dde3eb; white-space:nowrap; }}
  ul.readme {{ font-size:13px; padding-left:20px; }}
  ul.readme li {{ margin:5px 0; }}
</style>
</head>
<body>
  <h1>Crypto Derivatives Z-Score · 10-Gate Validation Dashboard</h1>
  <div class="meta">Generated {gen_ts} · 3-year window 2023-05-01 → 2026-04-30 · long-only z_lsr-trigger fixed-hold</div>

  <div class="summary-tiles">
    <div class="tile"><div class="val">{total}</div><div class="lab">Cells</div></div>
    <div class="tile"><div class="val" style="color:#4ac268">{pass7}</div><div class="lab">≥7/10 gates</div></div>
    <div class="tile"><div class="val" style="color:#c9a23a">{pass5}</div><div class="lab">≥5/10 gates</div></div>
    <div class="tile"><div class="val">{total_trades:,}</div><div class="lab">Trades (3y)</div></div>
    <div class="tile"><div class="val">{best_sharpe:+.2f}</div><div class="lab">Best Sharpe</div></div>
    <div class="tile"><div class="val">{best_calmar:+.2f}</div><div class="lab">Best Calmar</div></div>
  </div>

  <details class="explainer" open>
    <summary>📖 Strategy reference — how it works (click to collapse)</summary>

    <div class="explainer-body">

      <h3>1 · What the strategy does (one paragraph)</h3>
      <p>
        Long-only contrarian dip-buy on Hyperliquid perps. <strong>v4 uses regime-filtered entries
        with vol-scaled exits</strong> after a 36-config sweep (6 entry filters × 6 exit rules).
        Universal pattern that emerged: <strong>only trade in calm-vol regimes; scale exit timing
        by realized volatility</strong>.
      </p>
      <p>
        <strong>BTC (V9_lowvol)</strong>: enter when <code>z_lsr&lt;−1.5</code> AND
        <code>realized_vol_30d &lt; 90d-rolling-median</code>; exit at <code>24h × clip(0.5/vol, 0.5–4)</code>.
        <strong>ETH (V10_ma200_lowvol)</strong>: same as BTC plus <code>price &gt; 200d MA</code> filter.
        <strong>SOL</strong>: V10 with fixed 48h hold (vol-scaled hurts SOL — different microstructure).
        No stop-loss needed in any variant — the regime filter is the risk control.
      </p>
      <p>
        Costs modeled for Hyperliquid: 4.5bp taker per side + 1.5bp slippage estimate =
        <strong>12bp round-trip baseline</strong>. Cost-stress gate (G8) re-runs at 24bp RT to confirm
        edge survives 2× our baseline assumption.
      </p>
      <p>
        Costs modeled for Hyperliquid: 4.5bp taker per side + 1.5bp slippage estimate =
        <strong>12bp round-trip baseline</strong>. Cost-stress gate (G8) re-runs at 24bp RT to confirm
        edge survives 2× our baseline assumption.
      </p>
      <p>
        The thesis is that when crowd-account positioning becomes extreme bearish
        (small accounts net-short relative to their own recent baseline), the move
        is often near-exhausted and reverts — a classic
        <em>fade the extremes</em> setup. We&rsquo;re betting against the dumb-money tail.
      </p>

      <h3>2 · Where the signal comes from</h3>
      <p>
        The original signal definition is the Pine Script
        <em>Crypto Derivatives Z-Score</em> indicator — a 10-metric composite
        regime detector. We reverse-engineered it from the source and rebuilt
        every metric in Python so we could backtest 3 years of data instead of
        eyeballing a TradingView chart.
      </p>
      <table class="ref">
        <thead>
          <tr><th>Pine indicator metric</th><th>Formula</th><th>Source data</th><th>In our Python build?</th></tr>
        </thead>
        <tbody>
          <tr><td><code>z_lsr</code> ★ <em>(this strategy&rsquo;s signal)</em></td>
              <td>Z<sub>21</sub>(Long/Short Ratio Accounts)</td>
              <td>Binance Vision <code>metrics/</code> 5-min CSVs</td><td>✓</td></tr>
          <tr><td><code>z_fund</code></td><td>Z<sub>21</sub>(Funding Rate)</td>
              <td>Binance Vision <code>fundingRate/</code></td><td>✓</td></tr>
          <tr><td><code>z_oi</code></td><td>Z<sub>21</sub>(Open Interest)</td>
              <td>Binance Vision <code>metrics/</code></td><td>✓</td></tr>
          <tr><td><code>z_oi_silent</code></td>
              <td>Z<sub>21</sub>(EMA<sub>3</sub>(z_oi_fast − z_px_fast | z_oi_fast&gt;1))</td>
              <td>derived from OI + spot</td><td>✓</td></tr>
          <tr><td><code>brigalS</code></td><td>z(long%) − z(short%)</td>
              <td>derived from LSR</td><td>✓</td></tr>
          <tr><td><code>z_cb_premium</code></td>
              <td>Z<sub>21</sub>(EMA<sub>3</sub>((CB<sub>BTC</sub> − BN<sub>BTC</sub>)/BN<sub>BTC</sub>))</td>
              <td>Coinbase + Binance spot REST</td>
              <td>BTC only — Coinbase has no liquid ETH/SOL pair for premium calc</td></tr>
          <tr><td><code>z_dom_stables</code></td><td>Z<sub>21</sub>(Δ stable mcap)</td>
              <td>DefiLlama <code>stablecoincharts/</code></td><td>✓</td></tr>
          <tr><td><code>cross_*</code> (institutional lead, leverage heat, risk-off, real-money)</td>
              <td>Δ-of-EMA differentials between USDT/USDC/USDe/DAI mcaps</td>
              <td>DefiLlama daily mcap</td><td>✓</td></tr>
          <tr><td><code>brigaliqui</code> · <code>z_liqB</code> · <code>z_liqS</code></td>
              <td>Z<sub>21</sub>(Liquidations Buy/Sell)</td>
              <td>Binance Vision <code>liquidationSnapshot/</code> — <strong>removed by Binance</strong></td>
              <td>✗ skipped — score caps at 85/100, rescaled to 100</td></tr>
        </tbody>
      </table>
      <p style="font-size:11px;color:#9aa">
        For the gauntlet results above, only <code>z_lsr</code> is used as the entry trigger.
        The other 9 metrics are computed and stored in the panel
        (<code>data/v4/derivatives_zscore/panels/{{SYM}}_zscore.parquet</code>) so we can
        ablate, tune, or build composites in v2 without re-fetching anything.
      </p>

      <h3>3 · Why z_lsr alone, and why a 24-hour fixed hold</h3>
      <p>
        Component-level ablation on BTC, 4-hour forward return, baseline
        +0.020% per bar:
      </p>
      <table class="ref">
        <thead><tr><th>Single trigger</th><th>n events (3y)</th><th>Mean fwd 4h</th><th>vs baseline</th></tr></thead>
        <tbody>
          <tr><td><code>z_lsr &lt; −1.5</code></td><td>5,012</td><td>+0.048%</td><td><strong>2.4×</strong></td></tr>
          <tr><td><code>brigalS &lt; −1.0</code></td><td>11,208</td><td>+0.040%</td><td>2.0×</td></tr>
          <tr><td><code>z_cb_premium &gt; +1.0</code></td><td>11,906</td><td>+0.033%</td><td>1.7×</td></tr>
          <tr><td><code>z_oi_silent &gt; +1.5</code></td><td>3,111</td><td>+0.032%</td><td>1.6×</td></tr>
          <tr><td><code>z_oi &gt; +1.0</code></td><td>8,030</td><td>+0.008%</td><td>0.4× (no edge)</td></tr>
        </tbody>
      </table>
      <p>
        <code>z_lsr</code> carries the strongest single-component edge. We then tested
        every combination of trigger × hold-period and found the
        edge collapses on short holds (1h/4h: <strong>negative</strong> expectancy on z_lsr alone — the
        signal needs time to play out) but compounds on a <strong>24-hour fixed hold</strong>:
        SOL +28% vs buy-and-hold across 887 trades, BTC marginally positive,
        ETH flat-to-down.
      </p>
      <p>
        Pine&rsquo;s spec exit (<code>score_bull&lt;35</code> OR <code>score_bear&gt;60</code>)
        triggers too fast — median hold 2h, premature exits on noise. Score-flip
        exit destroys ~40% of the gross edge versus the 24h fixed hold.
      </p>

      <h3>4 · Why long-only and not also short</h3>
      <p>
        We tested the Pine spec&rsquo;s short side
        (<code>score_bear≥70 AND cross_leverage_heat&gt;1.5 AND z_dom_stables&gt;1.0 AND below_ema21</code>).
        It produced <strong>zero short trades in 3 years × 3 symbols</strong> — the four-AND
        gate never co-fires. Loosening it: the bearish components individually
        showed almost no predictive power
        (<code>cross_leverage_heat&gt;1.5</code>: −0.021% mean fwd 4h, only 1 bp better than
        the unconditional short). The 3-year window is bull-biased; revisit
        short-side on a 2022-style bear sample.
      </p>

      <h3>5 · The 10 gates we ran</h3>
      <table class="ref">
        <thead><tr><th>Gate</th><th>Threshold</th><th>What it tests</th></tr></thead>
        <tbody>
          <tr><td>G1 Sharpe</td><td>≥ 0.5 ann.</td><td>Risk-adjusted return is positive (low bar — basic edge filter)</td></tr>
          <tr><td>G2 Calmar</td><td>≥ 1.0</td><td>CAGR / |MaxDD| — return covers worst peak-to-trough loss within a year</td></tr>
          <tr><td>G3 MaxDD</td><td>≥ −30%</td><td>Drawdown shallower than 30% — practical risk ceiling</td></tr>
          <tr><td>G4 Per-year consistency</td><td>≥ 70% pos years</td><td>Strategy works across regimes, not one-year fluke</td></tr>
          <tr><td>G5 Permutation</td><td>p &lt; 0.01 (500 reps)</td><td>Strategy beats randomly-shuffled returns — edge is not just lucky bar ordering</td></tr>
          <tr><td>G6 Bootstrap Sharpe lo</td><td>&gt; 0 (1000 iters)</td><td>Stationary block bootstrap 95%-CI lower bound on Sharpe is positive — robust to data realization</td></tr>
          <tr><td>G7 Walk-forward efficiency</td><td>≥ 0.5 (6 folds)</td><td>Out-of-sample Sharpe is at least half the in-sample — minimal overfit decay</td></tr>
          <tr><td>G8 Cost stress</td><td>PF &gt; 1 at 24bp RT</td><td>Survives 2× the Hyperliquid taker base (4.5bp×2 + slip 1.5bp×2 = 12bp; tested up to 24bp)</td></tr>
          <tr><td>G9 Parameter sensitivity</td><td>median Sharpe &gt; 0 (3×3 grid)</td><td>(z_thr ∈ {{−1, −1.5, −2}}) × (hold ∈ {{12, 24, 48h}}) — not on a single fragile parameter point</td></tr>
          <tr><td>G10 Profit factor</td><td>≥ 1.10</td><td>Gross wins / gross losses ≥ 1.10 — clear positive expectancy after costs</td></tr>
        </tbody>
      </table>

      <h3>6 · How to read each per-symbol cell below</h3>
      <ul class="readme">
        <li><strong>Equity curve</strong> — normalized to 1.0 at start. Green = ends above 1.0, red = below. Final value, buy-hold value, and outperform-ratio printed underneath.</li>
        <li><strong>Yearly returns</strong> — bar per calendar year, scaled to the largest absolute return. Quick visual on whether the strategy survived every regime.</li>
        <li><strong>Core metrics</strong> — CAGR, Sharpe/Sortino/Calmar, MaxDD with duration and recovery, win rate, avg win/loss, tail ratio, Probabilistic and Deflated Sharpe.</li>
        <li><strong>Per-year breakdown</strong> — Sharpe / return / MaxDD / bar-count for each year. This is what gate G4 reads.</li>
        <li><strong>Walk-forward</strong> — 6 anchored expanding folds: each fold trains on 1 + k chunks and tests on the next chunk. Efficiency = avg test Sharpe / IS Sharpe.</li>
        <li><strong>Parameter sensitivity</strong> — full 3×3 grid of (z-threshold, hold-hours). Confirms the edge isn&rsquo;t cliff-edged on one parameter point.</li>
        <li><strong>Cost stress</strong> — re-runs at 5 / 10 / 20 bp round-trip. The PF at 20bp is what gate G8 reads.</li>
        <li><strong>Bootstrap &amp; Permutation</strong> — Politis-Romano stationary block bootstrap (block prob 0.1, 1000 iters) on Sharpe / Calmar / MaxDD; permutation shuffles bar-by-bar strategy returns 500× and counts how often shuffled Sharpe exceeds real (= p-value).</li>
        <li><strong>10-gate chips</strong> — green = pass, red = fail. Reproducible from <code>extras_{{SYM}}.json</code> in the same folder.</li>
        <li><strong>Monthly heatmap</strong> — 12 columns × N years. Cell color intensity = magnitude (capped at 10%). Click any cell for the underlying month return.</li>
      </ul>

      <h3>7 · What's missing / known limitations</h3>
      <ul class="readme">
        <li><strong>Liquidations dropped.</strong> Binance Vision retired <code>liquidationSnapshot/</code>. The Pine indicator&rsquo;s <code>brigaliqui</code> contributes 15 of 100 score points — we rescale the remaining 85 to 100. To recover this we&rsquo;d need a paid Coinglass/CoinAnk feed.</li>
        <li><strong>z_cb_premium is BTC-only.</strong> Coinbase doesn&rsquo;t list ETH-USDT or SOL-USDT as the premium reference. ETH/SOL panels miss the 10pt geographic-flow component, which materially reduces their composite score amplitude.</li>
        <li><strong>Spot OHLCV used in place of perp price.</strong> 1h spot vs 1h perp basis is &lt;10 bps in normal regimes — acceptable proxy. Would matter for liquidation modeling, irrelevant here.</li>
        <li><strong>Long-only.</strong> Short side as spec&rsquo;d never fires; relaxed short variants showed no edge. Would re-test on a longer or 2022-inclusive sample.</li>
        <li><strong>No regime filter.</strong> All trades taken regardless of macro/spot trend. Adding a 200-day-MA &ldquo;risk-on&rdquo; filter is the next obvious lever to fix the deep drawdowns (gate G3).</li>
      </ul>

      <h3>8 · Code locations</h3>
      <pre>strategy_lab/v4_signals/derivatives_zscore/
  fetch_data.py        # 3y of metrics + funding from Binance Vision
  fetch_aux.py         # Coinbase + Binance spot 1h, DefiLlama stables
  fill_funding_gap.py  # current-month REST gap-fill
  compute_zscores.py   # the 10-metric panel (5-min)
  backtest.py          # naive Pine-spec entry/exit
  backtest_v2.py       # parametric runner (5 configs × 3 exits)
  diagnose.py          # component-level forward-return ablation
  gauntlet.py          # 10-gate validator, this dashboard&rsquo;s data source
  build_dashboard.py   # this dashboard

data/v4/derivatives_zscore/
  metrics/{{BTC,ETH,SOL}}USDT.parquet    # 315k rows × 8 cols × 3 symbols, 5min, 3y
  funding/{{BTC,ETH,SOL}}USDT.parquet    # 8h cadence, REST-merged through current bar
  spot/BINANCE-{{BTC,ETH,SOL}}-1h.parquet
  spot/COINBASE-BTC-1h.parquet
  stables/market_caps.parquet          # 8 stablecoins via DefiLlama daily
  panels/{{BTC,ETH,SOL}}USDT_zscore.parquet  # 39 cols × 315k rows — full computed panel</pre>

    </div>
  </details>

  <h2>Summary</h2>
  <table class="summary">
    <thead><tr>
      <th>Symbol</th><th>#Tr</th><th>Win%</th><th>PF</th>
      <th>Sharpe</th><th>Calmar</th><th>MaxDD</th><th>Sortino</th>
      <th>DSR</th><th>PSR</th>
      <th>Eq</th><th>BH</th><th>Outperf</th><th>Gates</th>
    </tr></thead>
    <tbody>{summary_table}</tbody>
  </table>

  <h2>Per-symbol detail (10 gates · WF · bootstrap · param sensitivity · cost stress)</h2>
  {cells_block}

  <footer>
    Strategy v4: regime-filtered entries + vol-scaled exits — BTC: V9_lowvol (z&lt;-1.5 in calm-vol regime, vol-scaled hold) · ETH: V10_ma200_lowvol (V9 + price&gt;200d MA, vol-scaled hold) · SOL: V10 with 48h fixed hold ·
    Hyperliquid fees: 4.5bp taker + 1.5bp slippage per side = 12bp RT.
    Source: Binance Vision metrics (5min) → 1h resample · price = BINANCE_SPOT close.
    <br>Gates: G1 Sharpe≥0.5 · G2 Calmar≥1.0 · G3 MDD≥-30% · G4 ≥70% pos years · G5 perm p&lt;0.01 ·
    G6 boot Sharpe lo&gt;0 · G7 WFE≥0.5 · G8 PF&gt;1 at 24bp · G9 param-sweep median Sharpe&gt;0 · G10 PF≥1.10
  </footer>
</body>
</html>
"""


def main():
    html = build()
    OUT.write_text(html, encoding="utf-8")
    kb = OUT.stat().st_size / 1024
    print(f"Wrote {OUT} ({kb:.1f} KB)")


if __name__ == "__main__":
    main()
