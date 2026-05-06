"""Dashboard em Português para os resultados do gauntlet derivatives_zscore.

Lê:     strategy_lab/reports/derivatives_zscore/gauntlet_results.csv
        strategy_lab/reports/derivatives_zscore/equity_curves/{file}.parquet
        strategy_lab/reports/derivatives_zscore/extras_{symbol}.json

Escreve: strategy_lab/reports/derivatives_zscore/resultados.html
"""
from __future__ import annotations
from pathlib import Path
import json
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
REP = ROOT / "strategy_lab" / "reports" / "derivatives_zscore"
EQ = REP / "equity_curves"
OUT = REP / "resultados.html"


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
        '<th>Ano</th><th>Sharpe</th><th>Retorno</th><th>MaxDD</th><th>Barras</th></tr></thead>'
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
               f'Sharpe IS: {wf.get("is_sharpe",0):+.2f} · Sharpe médio teste: {wf.get("avg_test_sharpe",0):+.2f} · '
               f'Eficiência: <strong style="color:{"#1f9d55" if eff>=0.5 else "#c23a3a"}">{eff:.2f}</strong> · '
               f'Folds positivos: {wf.get("n_positive_folds",0)}/{len(folds)}</div>')
    return (
        '<table class="mini"><thead><tr><th>Fold</th><th>Barras</th><th>Trades</th><th>Sharpe</th><th>Retorno</th></tr></thead>'
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
        '<table class="mini"><thead><tr><th>z_thr</th><th>hold</th><th>n</th><th>Sharpe</th><th>Retorno</th></tr></thead>'
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
        '<table class="mini"><thead><tr><th>Custo</th><th>n</th><th>PF</th><th>Retorno</th></tr></thead>'
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
        '<table class="mini"><thead><tr><th>Métrica</th><th>Média</th><th>IC inf</th><th>IC sup</th></tr></thead>'
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
      <div class="label">Curva de equity (normalizada, base 1,0)</div>
      {equity_svg(eq, 420, 110)}
      <div style="font-size:11px;color:#9aa;margin-top:4px">
        Final: <strong style="color:#fff">{row['final_equity_x']:.3f}×</strong> ·
        Buy-and-hold: <strong>{row['buy_hold_x']:.3f}×</strong> ·
        Outperform: <strong style="color:{'#1f9d55' if row['final_equity_x']>=row['buy_hold_x'] else '#c23a3a'}">{row['final_equity_x']/row['buy_hold_x']:.2f}×</strong>
      </div>
    </div>

    <div>
      <div class="label">Retornos anuais</div>
      {yearly_bars(row['yearly_returns'])}
    </div>

    <div>
      <div class="label">Métricas principais (3 anos)</div>
      <table class="mini">
        <tr><td>CAGR</td><td>{fmt_pct(row.get('oos_cagr',0), True)}</td></tr>
        <tr><td>Sharpe / Sortino</td><td>{fmt_num(row.get('oos_sharpe',0),2,sign=True)} / {fmt_num(row.get('oos_sortino',0),2,sign=True)}</td></tr>
        <tr><td>Calmar / UPI</td><td>{fmt_num(row.get('oos_calmar',0),2,sign=True)} / {fmt_num(row.get('oos_upi',0),2,sign=True)}</td></tr>
        <tr><td>Max DD / dur / rec</td><td>{fmt_pct(row.get('oos_max_dd',0))} / {int(row.get('oos_dd_duration_bars',0))}b / {int(row.get('oos_dd_recovery_bars',0))}b</td></tr>
        <tr><td>Profit factor</td><td>{fmt_num(row.get('profit_factor',0),2)}</td></tr>
        <tr><td>Win rate / hold médio</td><td>{fmt_num(row.get('win_rate',0)*100,1)}% / {fmt_num(row.get('avg_hold_h',0),1)}h</td></tr>
        <tr><td>Ganho / perda médios</td><td>{fmt_num(row.get('avg_win',0)*100,2)}% / {fmt_num(row.get('avg_loss',0)*100,2)}%</td></tr>
        <tr><td>Tail / Ulcer</td><td>{fmt_num(row.get('oos_tail_ratio',0),2)} / {fmt_num(row.get('oos_ulcer',0),2)}</td></tr>
        <tr><td>PSR / DSR</td><td>{fmt_num(row.get('oos_psr',0),3)} / {fmt_num(row.get('oos_dsr',0),3)}</td></tr>
        <tr><td>Trades</td><td>{int(row['n_trades']):,}</td></tr>
      </table>
    </div>

    <div>
      <div class="label">Resultado por ano</div>
      {trade_quartile_table(extras)}
    </div>

    <div>
      <div class="label">Walk-forward (6 folds, âncora-expansiva)</div>
      {wf_table(extras)}
    </div>

    <div>
      <div class="label">Sensibilidade de parâmetros (grid z × hold)</div>
      {param_grid_table(extras)}
    </div>

    <div>
      <div class="label">Stress de custos</div>
      {cost_grid_table(extras)}
    </div>

    <div>
      <div class="label">Intervalos de confiança do bootstrap e permutação</div>
      {boot_table(extras)}
    </div>
  </div>

  <div class="label" style="margin-top:14px">Validação dos 10 gates</div>
  <div>{gate_grid(extras.get('gates', {}))}</div>

  <div class="label" style="margin-top:14px">Retornos mensais (%)</div>
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
<title>Crypto Derivatives Z-Score · Dashboard 10 Gates · Resultados</title>
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

  .glossary {{ background:#0e131a; border:1px solid #1d242f; border-radius:6px; padding:20px 26px 24px 26px; margin-bottom:18px; line-height:1.55; }}
  .glossary h3 {{ color:#9dcefa; font-size:14px; margin-top:24px; margin-bottom:10px; text-transform:uppercase; letter-spacing:0.6px; border-left:3px solid #2d6cb0; padding-left:8px; }}
  .glossary h3:first-of-type {{ margin-top:0; }}
  .glossary dl {{ margin:0 0 10px 0; }}
  .glossary dt {{ color:#e0b280; font-weight:700; font-size:13px; margin-top:12px; font-family:-apple-system,Segoe UI,Roboto,sans-serif; }}
  .glossary dd {{ color:#cfd6de; font-size:13px; margin:3px 0 8px 0; padding-left:12px; border-left:2px solid #2a3342; }}
  .glossary dd code {{ background:#1a212c; color:#e0b280; padding:1px 5px; border-radius:2px; font-size:12px; }}
  .glossary dd em {{ color:#9aa3b0; font-style:italic; }}
  .glossary dd strong {{ color:#fff; }}
  .glossary p {{ font-size:13px; color:#cfd6de; }}
</style>
</head>
<body>
  <h1>Crypto Derivatives Z-Score · Dashboard de Validação 10 Gates</h1>
  <div class="meta">Gerado em {gen_ts} · Janela de 3 anos 2023-05-01 → 2026-04-30 · somente long, gatilho z_lsr, hold fixo</div>

  <div class="summary-tiles">
    <div class="tile"><div class="val">{total}</div><div class="lab">Células</div></div>
    <div class="tile"><div class="val" style="color:#4ac268">{pass7}</div><div class="lab">≥7/10 gates</div></div>
    <div class="tile"><div class="val" style="color:#c9a23a">{pass5}</div><div class="lab">≥5/10 gates</div></div>
    <div class="tile"><div class="val">{total_trades:,}</div><div class="lab">Trades (3 anos)</div></div>
    <div class="tile"><div class="val">{best_sharpe:+.2f}</div><div class="lab">Melhor Sharpe</div></div>
    <div class="tile"><div class="val">{best_calmar:+.2f}</div><div class="lab">Melhor Calmar</div></div>
  </div>

  <details class="explainer" open>
    <summary>📖 Referência da estratégia — como funciona (clique para recolher)</summary>

    <div class="explainer-body">

      <h3>1 · O que a estratégia faz (em um parágrafo)</h3>
      <p>
        Compra contrária na queda, somente long, deploy em Hyperliquid perps.
        <strong>v4 usa entradas filtradas por regime + saídas escaladas por volatilidade</strong>,
        após sweep de 36 configurações (6 filtros de entrada × 6 regras de saída). Padrão
        universal que emergiu: <strong>só operar em regimes de vol calma; escalar tempo
        de saída pela vol realizada</strong>.
      </p>
      <p>
        <strong>BTC (V9_lowvol)</strong>: entra quando <code>z_lsr&lt;−1,5</code> E
        <code>vol_realizada_30d &lt; mediana móvel 90d</code>; sai em
        <code>24h × clip(0,5/vol; 0,5–4)</code>.
        <strong>ETH (V10_ma200_lowvol)</strong>: igual a BTC mais filtro <code>preço &gt; MA 200d</code>.
        <strong>SOL</strong>: V10 com hold fixo de 48h (vol-escalado piora SOL — microestrutura
        diferente). Sem stop-loss em nenhuma variante — o filtro de regime é o controle de risco.
      </p>
      <p>
        Custos modelados para Hyperliquid: 4,5bp taker por lado + 1,5bp slippage estimado =
        <strong>12bp round-trip</strong> de base. O gate de stress de custos (G8) re-roda a 24bp RT
        para confirmar que o edge sobrevive a 2× o pressuposto base.
      </p>
      <p>
        Custos modelados para Hyperliquid: 4,5bp taker por lado + 1,5bp slippage estimado =
        <strong>12bp round-trip</strong> de base. O gate de stress de custos (G8) re-roda a 24bp RT
        para confirmar que o edge sobrevive a 2× o pressuposto base.
      </p>
      <p>
        A tese é que quando o posicionamento das contas da multidão fica
        extremamente <em>bearish</em> (contas pequenas net-short em relação à sua
        própria base recente), o movimento geralmente está perto de exaustão e
        reverte — um setup clássico de <em>fade the extremes</em>. Estamos apostando
        contra a cauda do dinheiro burro.
      </p>

      <h3>2 · De onde vem o sinal</h3>
      <p>
        A definição original do sinal vem do indicador Pine Script
        <em>Crypto Derivatives Z-Score</em> — um detector composto de regime de
        10 métricas. Fizemos engenharia reversa do código-fonte e reconstruímos
        cada métrica em Python para poder fazer backtest de 3 anos de dados em
        vez de olhar para um gráfico do TradingView no olho.
      </p>
      <table class="ref">
        <thead>
          <tr><th>Métrica do indicador Pine</th><th>Fórmula</th><th>Fonte de dados</th><th>Está no nosso build em Python?</th></tr>
        </thead>
        <tbody>
          <tr><td><code>z_lsr</code> ★ <em>(o sinal desta estratégia)</em></td>
              <td>Z<sub>21</sub>(Long/Short Ratio Accounts)</td>
              <td>Binance Vision <code>metrics/</code> CSVs de 5min</td><td>✓</td></tr>
          <tr><td><code>z_fund</code></td><td>Z<sub>21</sub>(Funding Rate)</td>
              <td>Binance Vision <code>fundingRate/</code></td><td>✓</td></tr>
          <tr><td><code>z_oi</code></td><td>Z<sub>21</sub>(Open Interest)</td>
              <td>Binance Vision <code>metrics/</code></td><td>✓</td></tr>
          <tr><td><code>z_oi_silent</code></td>
              <td>Z<sub>21</sub>(EMA<sub>3</sub>(z_oi_fast − z_px_fast | z_oi_fast&gt;1))</td>
              <td>derivado de OI + spot</td><td>✓</td></tr>
          <tr><td><code>brigalS</code></td><td>z(long%) − z(short%)</td>
              <td>derivado do LSR</td><td>✓</td></tr>
          <tr><td><code>z_cb_premium</code></td>
              <td>Z<sub>21</sub>(EMA<sub>3</sub>((CB<sub>BTC</sub> − BN<sub>BTC</sub>)/BN<sub>BTC</sub>))</td>
              <td>Spot REST Coinbase + Binance</td>
              <td>Apenas BTC — Coinbase não tem par líquido ETH/SOL para o cálculo de premium</td></tr>
          <tr><td><code>z_dom_stables</code></td><td>Z<sub>21</sub>(Δ mcap stable)</td>
              <td>DefiLlama <code>stablecoincharts/</code></td><td>✓</td></tr>
          <tr><td><code>cross_*</code> (lead institucional, leverage heat, risk-off, real-money)</td>
              <td>Diferenciais Δ-de-EMA entre mcaps de USDT/USDC/USDe/DAI</td>
              <td>Mcap diário DefiLlama</td><td>✓</td></tr>
          <tr><td><code>brigaliqui</code> · <code>z_liqB</code> · <code>z_liqS</code></td>
              <td>Z<sub>21</sub>(Liquidações Buy/Sell)</td>
              <td>Binance Vision <code>liquidationSnapshot/</code> — <strong>removido pela Binance</strong></td>
              <td>✗ pulado — score satura em 85/100, reescalado para 100</td></tr>
        </tbody>
      </table>
      <p style="font-size:11px;color:#9aa">
        Para os resultados do gauntlet acima, apenas <code>z_lsr</code> é usado como gatilho de entrada.
        As outras 9 métricas são calculadas e armazenadas no painel
        (<code>data/v4/derivatives_zscore/panels/{{SYM}}_zscore.parquet</code>) para que possamos
        fazer ablação, tunar, ou construir composições na v2 sem precisar refazer o fetch.
      </p>

      <h3>3 · Por que apenas z_lsr, e por que hold fixo de 24 horas</h3>
      <p>
        Ablação por componente em BTC, retorno 4 horas à frente, baseline
        +0,020% por barra:
      </p>
      <table class="ref">
        <thead><tr><th>Gatilho único</th><th>n eventos (3a)</th><th>Média fwd 4h</th><th>vs baseline</th></tr></thead>
        <tbody>
          <tr><td><code>z_lsr &lt; −1,5</code></td><td>5.012</td><td>+0,048%</td><td><strong>2,4×</strong></td></tr>
          <tr><td><code>brigalS &lt; −1,0</code></td><td>11.208</td><td>+0,040%</td><td>2,0×</td></tr>
          <tr><td><code>z_cb_premium &gt; +1,0</code></td><td>11.906</td><td>+0,033%</td><td>1,7×</td></tr>
          <tr><td><code>z_oi_silent &gt; +1,5</code></td><td>3.111</td><td>+0,032%</td><td>1,6×</td></tr>
          <tr><td><code>z_oi &gt; +1,0</code></td><td>8.030</td><td>+0,008%</td><td>0,4× (sem edge)</td></tr>
        </tbody>
      </table>
      <p>
        <code>z_lsr</code> carrega o maior edge isolado entre os componentes. Testamos todas
        as combinações de gatilho × período de hold e descobrimos que o edge
        colapsa em holds curtos (1h/4h: expectativa <strong>negativa</strong> em z_lsr sozinho —
        o sinal precisa de tempo para se desenvolver) mas se compõe num
        <strong>hold fixo de 24 horas</strong>: SOL +28% vs buy-and-hold em 887 trades,
        BTC marginalmente positivo, ETH praticamente plano.
      </p>
      <p>
        A saída original do Pine (<code>score_bull&lt;35</code> OU <code>score_bear&gt;60</code>)
        dispara rápido demais — hold mediano de 2h, saídas prematuras em ruído.
        A saída por flip de score destrói ~40% do edge bruto em comparação ao hold
        fixo de 24h.
      </p>

      <h3>4 · Por que somente long e não também short</h3>
      <p>
        Testamos o lado short da especificação Pine
        (<code>score_bear≥70 E cross_leverage_heat&gt;1,5 E z_dom_stables&gt;1,0 E abaixo_ema21</code>).
        Produziu <strong>zero trades short em 3 anos × 3 símbolos</strong> — o gate de quatro
        ANDs nunca acende junto. Afrouxando: os componentes bearish individualmente
        mostraram quase nenhum poder preditivo
        (<code>cross_leverage_heat&gt;1,5</code>: −0,021% média fwd 4h, apenas 1 bp melhor
        que o short incondicional). A janela de 3 anos é viesada para alta;
        revisitar o lado short numa amostra que inclua um bear como 2022.
      </p>

      <h3>5 · Os 10 gates que rodamos</h3>
      <table class="ref">
        <thead><tr><th>Gate</th><th>Threshold</th><th>O que testa</th></tr></thead>
        <tbody>
          <tr><td>G1 Sharpe</td><td>≥ 0,5 anualizado</td><td>Retorno ajustado ao risco é positivo (filtro básico de edge)</td></tr>
          <tr><td>G2 Calmar</td><td>≥ 1,0</td><td>CAGR / |MaxDD| — retorno cobre o pior pico-a-vale dentro de um ano</td></tr>
          <tr><td>G3 MaxDD</td><td>≥ −30%</td><td>Drawdown mais raso que 30% — teto prático de risco</td></tr>
          <tr><td>G4 Consistência por ano</td><td>≥ 70% anos positivos</td><td>Estratégia funciona em vários regimes, não foi sorte de um ano</td></tr>
          <tr><td>G5 Permutação</td><td>p &lt; 0,01 (500 reps)</td><td>Estratégia bate retornos embaralhados aleatoriamente — o edge não é só ordem sortuda das barras</td></tr>
          <tr><td>G6 Bootstrap Sharpe lo</td><td>&gt; 0 (1000 iters)</td><td>Limite inferior do IC 95% do Sharpe via block bootstrap estacionário é positivo — robusto à realização dos dados</td></tr>
          <tr><td>G7 Walk-forward efficiency</td><td>≥ 0,5 (6 folds)</td><td>Sharpe out-of-sample é pelo menos metade do in-sample — degradação mínima por overfit</td></tr>
          <tr><td>G8 Stress de custos</td><td>PF &gt; 1 a 24bp RT</td><td>Sobrevive a 2× o custo base do Hyperliquid (4,5bp×2 + slip 1,5bp×2 = 12bp; testado até 24bp)</td></tr>
          <tr><td>G9 Sensibilidade de parâmetros</td><td>Sharpe mediano &gt; 0 (grid 3×3)</td><td>(z_thr ∈ {{−1; −1,5; −2}}) × (hold ∈ {{12; 24; 48h}}) — não depende de um único ponto frágil de parâmetro</td></tr>
          <tr><td>G10 Profit factor</td><td>≥ 1,10</td><td>Ganhos brutos / perdas brutas ≥ 1,10 — expectativa positiva clara após custos</td></tr>
        </tbody>
      </table>

      <h3>6 · Como ler cada bloco por símbolo abaixo</h3>
      <ul class="readme">
        <li><strong>Curva de equity</strong> — normalizada em 1,0 no início. Verde = termina acima de 1,0, vermelho = abaixo. Valor final, valor de buy-and-hold e razão de outperform impressos abaixo.</li>
        <li><strong>Retornos anuais</strong> — uma barra por ano calendário, escalada pelo maior retorno absoluto. Visual rápido para ver se a estratégia sobreviveu a cada regime.</li>
        <li><strong>Métricas principais</strong> — CAGR, Sharpe/Sortino/Calmar, MaxDD com duração e recuperação, win rate, ganho/perda médios, tail ratio, Sharpe Probabilístico e Deflacionado.</li>
        <li><strong>Resultado por ano</strong> — Sharpe / retorno / MaxDD / nº de barras para cada ano. É o que o gate G4 lê.</li>
        <li><strong>Walk-forward</strong> — 6 folds âncora-expansiva: cada fold treina em 1 + k blocos e testa no bloco seguinte. Eficiência = Sharpe médio teste / Sharpe IS.</li>
        <li><strong>Sensibilidade de parâmetros</strong> — grid completo 3×3 de (z-threshold, horas-hold). Confirma que o edge não está numa borda frágil de parâmetro.</li>
        <li><strong>Stress de custos</strong> — re-roda a 5 / 10 / 20 bp round-trip. O PF a 20bp é o que o gate G8 lê.</li>
        <li><strong>Bootstrap e Permutação</strong> — Block bootstrap estacionário Politis-Romano (prob de bloco 0,1; 1000 iters) em Sharpe / Calmar / MaxDD; a permutação embaralha os retornos por barra da estratégia 500× e conta quantas vezes o Sharpe embaralhado supera o real (= p-valor).</li>
        <li><strong>Chips dos 10 gates</strong> — verde = passou, vermelho = falhou. Reproduzíveis a partir de <code>extras_{{SYM}}.json</code> na mesma pasta.</li>
        <li><strong>Heatmap mensal</strong> — 12 colunas × N anos. Intensidade da cor da célula = magnitude (saturada em 10%). Passe o cursor sobre qualquer célula para ver o retorno daquele mês.</li>
      </ul>

      <h3>7 · O que falta / limitações conhecidas</h3>
      <ul class="readme">
        <li><strong>Liquidações descartadas.</strong> A Binance Vision aposentou <code>liquidationSnapshot/</code>. O <code>brigaliqui</code> do indicador Pine vale 15 dos 100 pontos de score — reescalamos os 85 restantes para 100. Para recuperar isso precisaríamos de um feed pago Coinglass/CoinAnk.</li>
        <li><strong>z_cb_premium é apenas BTC.</strong> A Coinbase não lista ETH-USDT nem SOL-USDT como referência de premium. Os painéis de ETH/SOL perdem o componente de fluxo geográfico de 10pts, o que reduz materialmente a amplitude do score composto deles.</li>
        <li><strong>Spot OHLCV usado no lugar do preço perp.</strong> A base 1h spot vs 1h perp é &lt;10 bps em regimes normais — proxy aceitável. Importaria para modelagem de liquidações, irrelevante aqui.</li>
        <li><strong>Somente long.</strong> O lado short como especificado nunca dispara; variantes relaxadas não mostraram edge. Voltar a testar numa amostra mais longa ou que inclua 2022.</li>
        <li><strong>Sem filtro de regime.</strong> Todos os trades são pegos independentemente da tendência macro/spot. Adicionar um filtro &ldquo;risk-on&rdquo; baseado em MA-200 dias é a próxima alavanca óbvia para resolver os drawdowns profundos (gate G3).</li>
      </ul>

      <h3>8 · Localização do código</h3>
      <pre>strategy_lab/v4_signals/derivatives_zscore/
  fetch_data.py        # 3 anos de metrics + funding via Binance Vision
  fetch_aux.py         # Spot 1h Coinbase + Binance, stables DefiLlama
  fill_funding_gap.py  # gap-fill REST do mês corrente
  compute_zscores.py   # painel das 10 métricas (5-min)
  backtest.py          # entry/exit ingênuo da spec do Pine
  backtest_v2.py       # runner paramétrico (5 configs × 3 saídas)
  diagnose.py          # ablação de retorno fwd por componente
  gauntlet.py          # validador 10 gates, fonte de dados deste dashboard
  build_dashboard.py   # dashboard em inglês
  build_dashboard_pt.py # este dashboard

data/v4/derivatives_zscore/
  metrics/{{BTC,ETH,SOL}}USDT.parquet    # 315k linhas × 8 colunas × 3 símbolos, 5min, 3a
  funding/{{BTC,ETH,SOL}}USDT.parquet    # cadência 8h, mesclado via REST até a barra atual
  spot/BINANCE-{{BTC,ETH,SOL}}-1h.parquet
  spot/COINBASE-BTC-1h.parquet
  stables/market_caps.parquet          # 8 stablecoins via DefiLlama daily
  panels/{{BTC,ETH,SOL}}USDT_zscore.parquet  # 39 colunas × 315k linhas — painel computado completo</pre>

    </div>
  </details>

  <h2>Resumo</h2>
  <table class="summary">
    <thead><tr>
      <th>Símbolo</th><th>#Tr</th><th>Win%</th><th>PF</th>
      <th>Sharpe</th><th>Calmar</th><th>MaxDD</th><th>Sortino</th>
      <th>DSR</th><th>PSR</th>
      <th>Eq</th><th>BH</th><th>Outperf</th><th>Gates</th>
    </tr></thead>
    <tbody>{summary_table}</tbody>
  </table>

  <h2>Detalhe por símbolo (10 gates · WF · bootstrap · sensibilidade de parâmetros · stress de custos)</h2>
  {cells_block}

  <h2>📚 Glossário — todos os conceitos do dashboard explicados</h2>
  <div class="glossary">

    <p style="color:#9aa3b0;font-size:12px;margin-bottom:18px">
      Esta seção explica em linguagem simples cada termo, métrica e visualização que aparece no dashboard. Foi escrita para alguém que está vendo esses conceitos pela primeira vez. Os termos estão agrupados por tema.
    </p>

    <h3>🧱 Conceitos básicos de backtest</h3>

    <dl>
      <dt>Backtest</dt>
      <dd>Simulação de uma estratégia de trading sobre dados históricos. Pega-se a regra (&ldquo;quando isso acontecer, compre; quando aquilo, venda&rdquo;), aplica-se barra por barra no passado e mede-se quanto teria sido ganho ou perdido. NÃO é prova de que vai funcionar no futuro — é só um filtro mínimo para descartar estratégias que nem no passado funcionariam.</dd>

      <dt>Trade</dt>
      <dd>Um ciclo completo de compra → venda (ou venda → recompra para shorts). Cada trade tem um preço de entrada, preço de saída e um retorno.</dd>

      <dt>Hold (período de hold)</dt>
      <dd>Quanto tempo a posição ficou aberta. Pode ser fixo (&ldquo;sempre 24 horas&rdquo;) ou determinado por regra de saída (&ldquo;sai quando o sinal mudar&rdquo;). Aqui usamos 24 horas fixas — entrou, espera 24h, sai.</dd>

      <dt>Long / Short</dt>
      <dd><strong>Long</strong> = comprado. Ganha se o preço subir. <strong>Short</strong> = vendido. Ganha se o preço cair (você vende emprestado, recompra mais barato). Esta estratégia é <em>somente long</em>: nunca aposta na queda.</dd>

      <dt>Spot vs Perp (perpetual futures)</dt>
      <dd><strong>Spot</strong> = compra/venda do ativo real (BTC mesmo). <strong>Perp</strong> = contrato futuro perpétuo, paga &ldquo;funding rate&rdquo; e tem alavancagem. Os derivativos (LSR, OI, funding) que dão o sinal vêm do mercado perp; o preço de execução assumido aqui é spot.</dd>

      <dt>5 bps por lado / 10 bps round-trip</dt>
      <dd>Custo de transação. <strong>bp</strong> = basis point = 0,01%. 5bp por lado = 0,05% por compra + 0,05% por venda = 0,10% (10bp) por trade completo. É um custo de taker realista na Binance.</dd>

      <dt>Buy-and-hold (B&amp;H)</dt>
      <dd>Estratégia trivial de comparação: compra no início, segura até o fim, sem fazer nada. Se sua estratégia complicada não bate B&amp;H, talvez o caminho mais simples seja só comprar e esperar. <em>Outperform = Equity final / B&amp;H final</em>: se = 1,28×, sua estratégia ganhou 28% mais que comprar e segurar.</dd>
    </dl>

    <h3>📈 Curvas e retornos</h3>

    <dl>
      <dt>Curva de equity (equity curve)</dt>
      <dd>Gráfico do patrimônio da conta ao longo do tempo, normalmente normalizado em 1,0 no início. Se termina em 4,8× (como SOL), significa que cada R$ 1 virou R$ 4,80 ao final dos 3 anos. Linha verde = lucrativa no final, vermelha = no prejuízo.</dd>

      <dt>Retorno absoluto vs CAGR</dt>
      <dd><strong>Retorno absoluto</strong> = (final − início) / início. Ex.: 4,8× é 380% absoluto. <strong>CAGR</strong> (Compound Annual Growth Rate) = retorno anual equivalente composto. 380% em 3 anos vira CAGR ~70% — mais útil para comparar estratégias com janelas de tempo diferentes.</dd>

      <dt>Retornos mensais (heatmap)</dt>
      <dd>Tabela de 12 colunas (jan-dez) × N linhas (anos). Cada célula colorida pelo retorno daquele mês: verde se positivo, vermelho se negativo, intensidade da cor = magnitude. Ajuda a ver se a estratégia ganha consistentemente ou se concentra os ganhos em poucos meses.</dd>

      <dt>Retornos anuais</dt>
      <dd>Barra horizontal por ano calendário. Confirma rapidamente se a estratégia foi positiva ou negativa em cada um dos 3 anos. Estratégia decente: positiva em 2-3 dos 3 anos.</dd>
    </dl>

    <h3>📊 Métricas de qualidade ajustadas ao risco</h3>

    <dl>
      <dt>Sharpe Ratio</dt>
      <dd>A métrica clássica de risco-retorno. <em>Sharpe = (retorno médio / volatilidade) × √(barras por ano)</em>. Mede quanto retorno você ganha por unidade de volatilidade. Régua aproximada: <strong>Sharpe &lt; 0</strong> ruim, <strong>0 a 0,5</strong> medíocre, <strong>0,5 a 1</strong> aceitável, <strong>1 a 2</strong> bom, <strong>&gt; 2</strong> excelente. SOL aqui: 1,06 = bom.</dd>

      <dt>Sortino Ratio</dt>
      <dd>Variação do Sharpe que só penaliza volatilidade <strong>negativa</strong> (downside deviation). Faz sentido porque ninguém reclama de retornos &ldquo;voláteis para cima&rdquo;. Sortino &gt; Sharpe sempre que a estratégia tem mais subidas grandes que descidas grandes.</dd>

      <dt>Calmar Ratio</dt>
      <dd><em>Calmar = CAGR / |MaxDD|</em>. &ldquo;Quanto retorno anual você ganha por unidade de pior queda já vivida?&rdquo; Calmar 1,0 significa que o pior tombo foi igual ao retorno anual. Régua: <strong>&lt; 1</strong> sofrível, <strong>1-2</strong> ok, <strong>2-3</strong> bom, <strong>&gt; 3</strong> excelente. SOL: 1,30.</dd>

      <dt>Ulcer Index e UPI</dt>
      <dd><strong>Ulcer Index</strong> = raiz quadrada da média dos quadrados dos drawdowns. Penaliza drawdowns longos e profundos (não só o pior). <strong>UPI</strong> (Ulcer Performance Index) = CAGR / Ulcer Index — versão refinada do Calmar que considera todos os tombos, não só o maior.</dd>

      <dt>Tail Ratio</dt>
      <dd>Razão entre o quantil 95% (melhores retornos) e o quantil 5% (piores retornos), em valor absoluto. Tail Ratio &gt; 1 = caudas direitas (ganhos extremos) maiores que caudas esquerdas (perdas extremas) — perfil &ldquo;positivamente assimétrico&rdquo;, bom sinal.</dd>
    </dl>

    <h3>📉 Drawdown — quanto você sofreu</h3>

    <dl>
      <dt>Max Drawdown (MaxDD)</dt>
      <dd>A pior queda do pico ao vale, em percentual. Se o equity foi de 2,0× para 1,0×, o drawdown foi de 50%. É a métrica mais importante para saber se você &ldquo;aguenta&rdquo; a estratégia psicologicamente. Régua prática: <strong>&lt; 10%</strong> excelente, <strong>10-20%</strong> bom, <strong>20-30%</strong> aceitável, <strong>30-50%</strong> apenas para investidor calejado, <strong>&gt; 50%</strong> normalmente faz a pessoa abandonar a estratégia no meio.</dd>

      <dt>DD duration (duração do drawdown)</dt>
      <dd>Em quantas barras (aqui 1 barra = 1 hora) o equity ficou abaixo do pico anterior. Estratégias podem passar meses sem fazer um novo high — saber isso evita pânico no meio.</dd>

      <dt>DD recovery (recuperação do drawdown)</dt>
      <dd>Quantas barras levou para sair do fundo do poço e voltar ao pico anterior. Se demora muito, mesmo com retorno final positivo, a experiência foi sofrida.</dd>
    </dl>

    <h3>🎯 Métricas de qualidade dos trades</h3>

    <dl>
      <dt>Profit Factor (PF)</dt>
      <dd><em>PF = soma dos ganhos brutos / soma das perdas brutas</em>. PF = 1,0 significa que ganhos e perdas se cancelam (= zero líquido antes de custos). PF &gt; 1 é positivo. Régua: <strong>&lt; 1,1</strong> frágil, <strong>1,1-1,5</strong> ok, <strong>1,5-2,0</strong> bom, <strong>&gt; 2,0</strong> ótimo. PF de 1,18 (SOL) é frágil-positivo: edge real mas pequeno.</dd>

      <dt>Win Rate</dt>
      <dd>Percentual de trades vencedores. <strong>NÃO</strong> é a métrica que importa — uma estratégia com 30% win rate pode ser muito lucrativa se os ganhos forem grandes e as perdas pequenas. Mais útil ler junto com avg win / avg loss.</dd>

      <dt>Expectancy (expectativa)</dt>
      <dd>Retorno médio por trade. <em>Expectancy = Win% × média de ganho − Loss% × média de perda</em>. Tem que ser positivo após custos para a estratégia ser viável. Aqui +0,28% por trade na SOL.</dd>

      <dt>Avg win / Avg loss</dt>
      <dd>Média do retorno dos trades vencedores e perdedores. Razão win/loss &gt; 1 ajuda mesmo com win rate baixa.</dd>
    </dl>

    <h3>🔬 Métricas estatísticas avançadas</h3>

    <dl>
      <dt>PSR — Probabilistic Sharpe Ratio</dt>
      <dd>P(Sharpe verdadeiro &gt; 0 | Sharpe observado, n_obs, skewness, kurtosis). Resposta da pergunta &ldquo;qual a probabilidade do Sharpe que medi não ser sorte?&rdquo; PSR perto de 1,0 = quase certeza, 0,5 = cara ou coroa. Bailey &amp; López de Prado, 2012.</dd>

      <dt>DSR — Deflated Sharpe Ratio</dt>
      <dd>Versão do PSR que <strong>penaliza você por ter testado várias estratégias</strong>. Se você testou 100 variantes e escolheu a melhor, o Sharpe que viu pode ser pura sorte do extremo da amostragem. O DSR ajusta por isso. Com 9 trials (nosso grid 3×3), DSR &gt; PSR de jeito nenhum.</dd>

      <dt>Skewness e Kurtosis</dt>
      <dd><strong>Skewness</strong> = assimetria da distribuição de retornos (positiva = caudas direitas grandes, ganhos esporádicos enormes; negativa = perdas catastróficas raras — comum em estratégias tipo &ldquo;recolhendo trocados na frente do trator&rdquo;). <strong>Kurtosis</strong> = quão &ldquo;gordas&rdquo; são as caudas (Kurtosis 3 = normal; &gt; 3 = mais eventos extremos que o esperado).</dd>
    </dl>

    <h3>🧪 Testes de robustez (os 10 gates)</h3>

    <dl>
      <dt>Walk-forward (eficiência walk-forward)</dt>
      <dd>Os dados são divididos em N pedaços (folds) cronológicos. Em cada fold, você &ldquo;treina&rdquo; (otimiza ou apenas roda a estratégia) na parte anterior e &ldquo;testa&rdquo; na parte seguinte — sempre olhando para frente, nunca usando o futuro para prever o passado. <strong>Eficiência walk-forward</strong> = Sharpe médio dos folds de teste / Sharpe in-sample. ≥ 0,5 significa que a estratégia mantém pelo menos metade do edge fora da amostra de treino. Detector clássico de overfitting.</dd>

      <dt>Per-year breakdown (resultado por ano)</dt>
      <dd>Decompõe o resultado de 3 anos em três anos separados. Cada ano tem seu Sharpe, retorno e MaxDD. Estratégia robusta: positiva em 70%+ dos anos. Estratégia frágil: 1 ano enorme, 2 zerados/negativos.</dd>

      <dt>Permutation test (teste de permutação)</dt>
      <dd>Você pega os retornos reais barra por barra, embaralha aleatoriamente 500 vezes e mede quantas dessas permutações geram um Sharpe maior ou igual ao real. Se &lt; 1% = a ordem das barras carrega informação real, não é só sorte de uma sequência. <strong>p-valor</strong> = essa fração; menor = mais significância.</dd>

      <dt>Bootstrap (block bootstrap estacionário)</dt>
      <dd>Reamostragem dos retornos com reposição, em <em>blocos</em> (preserva a autocorrelação local). Politis-Romano, 1994. Roda 1000 versões alternativas da história e mede a distribuição de Sharpe / Calmar / MaxDD que poderia ter ocorrido. O <strong>IC 95% inferior</strong> do Sharpe diz: &ldquo;com 95% de confiança, em mundos paralelos com dados parecidos, o Sharpe ficaria pelo menos X&rdquo;. Se X &gt; 0, o resultado é robusto.</dd>

      <dt>Cost stress (stress de custos)</dt>
      <dd>Re-roda a estratégia em três níveis de custo: 5, 10, 20 bp round-trip. Se PF &gt; 1 mesmo a 20bp, a estratégia sobrevive a slippage realista de varejo. Se cai abaixo de 1 a 10bp, ela só funciona em paper trading.</dd>

      <dt>Parameter sensitivity (sensibilidade de parâmetros)</dt>
      <dd>Roda a estratégia numa grade de combinações de parâmetros (aqui: z_threshold ∈ {{−1; −1,5; −2}} × hold ∈ {{12; 24; 48h}}). Se o Sharpe é positivo em todo o entorno, o edge é &ldquo;suave&rdquo;. Se só funciona num ponto específico (cliff), provavelmente é overfitting.</dd>
    </dl>

    <h3>⚙️ Termos específicos do indicador</h3>

    <dl>
      <dt>Z-score</dt>
      <dd><em>Z = (valor atual − média móvel 21 barras) / desvio-padrão 21 barras</em>. Mede &ldquo;quão extremo é o valor atual em relação ao próprio passado recente&rdquo;. Z = +2 = dois desvios-padrão acima do normal recente (~2,5% mais alto na cauda). Z = −1,5 (nosso gatilho) = abaixo de ~93% das observações dos últimos dias.</dd>

      <dt>LSR — Long/Short Ratio Accounts</dt>
      <dd>Razão entre o número de contas com posição net-long e o número de contas com posição net-short na Binance Futures. Mede sentimento da multidão (não tamanho — uma baleia = uma conta = um pequeno trader = uma conta). Quando LSR cai bruscamente abaixo de seu próprio normal recente (z_lsr &lt; −1,5), as &ldquo;mãos pequenas&rdquo; estão capitulando — historicamente um sinal contrário de comprar.</dd>

      <dt>OI — Open Interest</dt>
      <dd>Total de contratos abertos no mercado de perpetuals. <strong>OI subindo + preço subindo</strong> = novo dinheiro entrando comprado, tendência saudável. <strong>OI caindo + preço subindo</strong> = short squeeze, fechamento de shorts, geralmente termina rápido.</dd>

      <dt>Funding Rate</dt>
      <dd>Taxa que longs pagam aos shorts (ou vice-versa) a cada 8h em contratos perp para manter o preço do perp colado ao spot. Funding positivo = longs estão pagando = mercado está em euforia comprada. Funding extremamente positivo (z_fund &gt; +2σ) = topo provável.</dd>

      <dt>Coinbase Premium</dt>
      <dd>(Preço BTC na Coinbase − Preço BTC na Binance) / Preço Binance × 100. Quando Coinbase premium é positivo, é um proxy para fluxo institucional americano comprando (Coinbase é a venue dominante de trad-fi nos EUA). Premium negativo = saída institucional.</dd>

      <dt>Stablecoin dominance</dt>
      <dd>Capitalização de mercado das stablecoins (USDT, USDC, DAI, etc.) dividida pelo total do mercado cripto. Subindo = capital saindo de cripto e indo para o &ldquo;estacionamento&rdquo; em dólar tokenizado = risk-off. Descendo = capital saindo das stables e voltando para BTC/altcoins = risk-on.</dd>
    </dl>

    <h3>📐 Conceitos estatísticos auxiliares</h3>

    <dl>
      <dt>Annualization (anualização)</dt>
      <dd>O Sharpe Ratio é multiplicado por √(N) onde N = número de barras por ano. Para barras de 1 hora num ano de 365 dias: N = 8760, √N ≈ 93,6. Permite comparar estratégias de timeframes diferentes na mesma régua &ldquo;por ano&rdquo;.</dd>

      <dt>In-sample (IS) vs Out-of-sample (OOS)</dt>
      <dd><strong>IS</strong> = a parte dos dados onde você decidiu os parâmetros. <strong>OOS</strong> = parte que a estratégia nunca viu. A diferença entre desempenho IS e OOS é o melhor detector de overfitting. Se IS Sharpe = 2,0 mas OOS Sharpe = 0,3, você ajustou demais aos dados de treino.</dd>

      <dt>p-valor (estatística inferencial)</dt>
      <dd>Probabilidade de observar o resultado (ou algo mais extremo) <strong>se a hipótese nula for verdadeira</strong> (= se a estratégia não tiver edge). Convenção: p &lt; 0,05 &ldquo;significativo&rdquo;, p &lt; 0,01 &ldquo;muito significativo&rdquo;. Não é a probabilidade de a estratégia funcionar — é a probabilidade de você ter visto o que viu por puro acaso.</dd>

      <dt>Intervalo de confiança (IC)</dt>
      <dd>Faixa numérica que, segundo um modelo, contém o &ldquo;valor verdadeiro&rdquo; de uma métrica com determinada probabilidade. IC 95% do Sharpe = [0,4; 1,3] significa &ldquo;sob nosso modelo, o Sharpe verdadeiro está entre 0,4 e 1,3 com 95% de confiança&rdquo;. Se o limite inferior é &gt; 0, a estratégia é estatisticamente positiva.</dd>

      <dt>Autocorrelação</dt>
      <dd>Correlação de uma série temporal com versões defasadas de si mesma. Retornos de cripto têm autocorrelação não-trivial em escalas curtas (clusters de volatilidade). Por isso usamos <em>block bootstrap</em> (preserva blocos contíguos) em vez de bootstrap simples (que destruiria essa estrutura).</dd>
    </dl>

    <h3>🛠 Termos da implementação</h3>

    <dl>
      <dt>Parquet</dt>
      <dd>Formato de arquivo binário columnar — comprime bem, lê rápido em pandas. Cada parquet daqui guarda uma tabela com índice de tempo e várias colunas numéricas.</dd>

      <dt>Resample 5min → 1h</dt>
      <dd>Os dados originais vêm a cada 5 minutos. Reamostramos para 1 hora pegando o último valor de cada hora — alinha tudo num grid horário consistente.</dd>

      <dt>Forward-fill (ffill)</dt>
      <dd>Quando dados de baixa frequência (funding a cada 8h, dominância de stables diária) são alinhados num grid horário, preenchemos as horas vazias com o último valor conhecido. Não usa o futuro — só propaga o presente para frente.</dd>

      <dt>EMA (Exponential Moving Average)</dt>
      <dd>Média móvel exponencial. Pondera mais as observações recentes. Usada para suavizar o premium da Coinbase e os Δ-mcap das stables antes de tirar o z-score, removendo ruído de alta frequência.</dd>
    </dl>

    <h3>🎓 Régua de bolso — &ldquo;esses números são bons?&rdquo;</h3>

    <table class="ref">
      <thead><tr><th>Métrica</th><th>Ruim</th><th>Aceitável</th><th>Bom</th><th>Excelente</th><th>SOL aqui</th></tr></thead>
      <tbody>
        <tr><td>Sharpe</td><td>&lt; 0,5</td><td>0,5 – 1,0</td><td>1,0 – 2,0</td><td>&gt; 2,0</td><td>1,06 ✓ bom</td></tr>
        <tr><td>Calmar</td><td>&lt; 0,5</td><td>0,5 – 1,0</td><td>1,0 – 2,0</td><td>&gt; 2,0</td><td>1,30 ✓ bom</td></tr>
        <tr><td>Profit factor</td><td>&lt; 1,1</td><td>1,1 – 1,3</td><td>1,3 – 1,8</td><td>&gt; 1,8</td><td>1,18 ⚠️ frágil</td></tr>
        <tr><td>MaxDD</td><td>&gt; 50%</td><td>30 – 50%</td><td>15 – 30%</td><td>&lt; 15%</td><td>−53% ✗ ruim</td></tr>
        <tr><td>Win rate</td><td>(depende)</td><td>(depende)</td><td>(depende)</td><td>(depende)</td><td>50,1%</td></tr>
        <tr><td>WFE</td><td>&lt; 0,3</td><td>0,3 – 0,5</td><td>0,5 – 0,8</td><td>&gt; 0,8</td><td>(passou) ✓</td></tr>
      </tbody>
    </table>

    <p style="color:#9aa3b0;font-size:11px;margin-top:18px">
      <strong>Tradução final do veredito SOL:</strong> a estratégia tem edge real e estatisticamente positivo (passa 7/10 gates), mas o drawdown profundo (−53%) significa que aguentar essa estratégia ao vivo é psicologicamente difícil. A mesma regra aplicada em BTC/ETH passa apenas 4/10 gates. A &ldquo;próxima alavanca&rdquo; mais óbvia é adicionar um filtro de regime (só operar quando o macro está &ldquo;risk-on&rdquo;) para reduzir os drawdowns sem matar o edge.
    </p>

  </div>

  <footer>
    Estratégia v4: entradas filtradas por regime + saídas vol-escaladas — BTC: V9_lowvol (z&lt;-1,5 em vol calma, hold vol-escalado) · ETH: V10_ma200_lowvol (V9 + preço&gt;MA 200d, hold vol-escalado) · SOL: V10 com hold fixo de 48h ·
    Custos Hyperliquid: 4,5bp taker + 1,5bp slippage por lado = 12bp RT.
    Fonte: Binance Vision metrics (5min) → reamostragem 1h · preço = fechamento BINANCE_SPOT.
    <br>Gates: G1 Sharpe≥0,5 · G2 Calmar≥1,0 · G3 MDD≥-30% · G4 ≥70% anos positivos · G5 perm p&lt;0,01 ·
    G6 boot Sharpe lo&gt;0 · G7 WFE≥0,5 · G8 PF&gt;1 a 24bp · G9 sweep param Sharpe mediano&gt;0 · G10 PF≥1,10
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
