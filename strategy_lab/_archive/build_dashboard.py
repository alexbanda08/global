"""
Dashboard builder — consolidates every Phase-5 result into a single HTML
file with sortable tables, per-cell drill-downs, equity curves (inline
SVG), monthly-returns heatmaps, and yearly-returns bars.

Reads:
  docs/research/phase5_results/phase5_matrix_results.csv
  docs/research/phase5_results/phase5_existing_book_results.csv
  docs/research/phase5_results/equity_curves/*.parquet

Writes:
  docs/research/phase5_results/DASHBOARD.html
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
RESULTS = REPO / "docs" / "research" / "phase5_results"
EQUITY_DIR = RESULTS / "equity_curves"
OUT = RESULTS / "DASHBOARD.html"


# ---------------------------------------------------------------------
# SVG equity curve (no external libs — pure inline SVG, ~1-2KB per cell)
# ---------------------------------------------------------------------
def equity_svg(equity: pd.Series, width: int = 320, height: int = 80) -> str:
    if equity is None or len(equity) < 2:
        return ""
    y = equity.to_numpy(dtype=float)
    y = y / y[0]                        # normalize to 1.0
    x = np.linspace(0, width - 4, len(y))
    y_norm = (y - y.min()) / (y.max() - y.min() + 1e-12)
    y_px = height - 4 - y_norm * (height - 8)
    pts = " ".join(f"{xi:.1f},{yi:.1f}" for xi, yi in zip(x, y_px))
    color = "#1f9d55" if y[-1] >= 1.0 else "#c23a3a"
    # 1.0 baseline
    base_norm = (1.0 - y.min()) / (y.max() - y.min() + 1e-12)
    base_y = height - 4 - base_norm * (height - 8)
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'style="background:#0f1419;border:1px solid #23303e;border-radius:3px">'
        f'<line x1="2" x2="{width-2}" y1="{base_y:.1f}" y2="{base_y:.1f}" '
        f'stroke="#3a4a5e" stroke-dasharray="2,2" stroke-width="0.5"/>'
        f'<polyline fill="none" stroke="{color}" stroke-width="1.5" points="{pts}"/>'
        f'</svg>'
    )


# ---------------------------------------------------------------------
# Monthly heatmap (year × month grid; colored by return sign & magnitude)
# ---------------------------------------------------------------------
def monthly_heatmap(monthly_json: str) -> str:
    if not isinstance(monthly_json, str) or not monthly_json.startswith("{"):
        return '<span style="color:#666">n/a</span>'
    try:
        m = json.loads(monthly_json)
    except Exception:
        return '<span style="color:#666">parse-err</span>'
    if not m:
        return '<span style="color:#666">empty</span>'
    # Group by year
    by_year: dict[str, dict[str, float]] = {}
    for k, v in m.items():
        y, mo = k.split("-")
        by_year.setdefault(y, {})[mo] = v
    years = sorted(by_year.keys())
    months = [f"{i:02d}" for i in range(1, 13)]

    def cell(v: float | None) -> str:
        if v is None:
            return '<td style="background:#1a1f26;color:#555">·</td>'
        pct = v * 100
        if v >= 0:
            alpha = min(1.0, abs(pct) / 10.0)
            bg = f"rgba(31,157,85,{alpha:.2f})"
        else:
            alpha = min(1.0, abs(pct) / 10.0)
            bg = f"rgba(194,58,58,{alpha:.2f})"
        return f'<td style="background:{bg}" title="{pct:+.1f}%">{pct:+.1f}</td>'

    rows = "".join(
        f'<tr><th style="text-align:right;padding:2px 6px">{y}</th>' +
        "".join(cell(by_year[y].get(mo)) for mo in months) + "</tr>"
        for y in years
    )
    header = "<tr><th></th>" + "".join(f'<th>{m}</th>' for m in months) + "</tr>"
    return (
        f'<table class="heatmap"><thead>{header}</thead>'
        f'<tbody>{rows}</tbody></table>'
    )


def yearly_bars(yearly_json: str) -> str:
    if not isinstance(yearly_json, str) or not yearly_json.startswith("{"):
        return '<span style="color:#666">n/a</span>'
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
        bar_w = 40 * abs(ret) / max_abs
        parts.append(
            f'<div style="display:flex;align-items:center;gap:6px;font-size:11px;margin:1px 0">'
            f'<span style="color:#9aa;min-width:40px">{yr}</span>'
            f'<div style="width:{bar_w:.1f}px;height:10px;background:{color}"></div>'
            f'<span style="color:#ddd">{pct:+.1f}%</span>'
            f'</div>'
        )
    return "".join(parts)


# ---------------------------------------------------------------------
# Table rendering helpers
# ---------------------------------------------------------------------
def fmt_pct(v):
    try:
        f = float(v)
        if pd.isna(f):
            return "–"
        return f"{f*100:+.1f}%"
    except Exception:
        return "–"


def fmt_num(v, digits=2, sign=False):
    try:
        f = float(v)
        if pd.isna(f):
            return "–"
        fmt = f"{{:{'+' if sign else ''}.{digits}f}}"
        return fmt.format(f)
    except Exception:
        return "–"


def gate_cell(gates: int | float) -> str:
    try:
        n = int(gates)
    except Exception:
        return "–"
    color = "#1f9d55" if n >= 5 else "#c99a1f" if n >= 3 else "#6b6b6b"
    return f'<span style="background:{color};color:#000;padding:2px 6px;border-radius:3px;font-weight:600">{n}/7</span>'


# ---------------------------------------------------------------------
# Main build
# ---------------------------------------------------------------------
def load_results() -> pd.DataFrame:
    frames = []
    for name, label in [
        ("phase5_matrix_results.csv",         "adaptive"),
        ("phase5_existing_book_results.csv",  "existing"),
    ]:
        p = RESULTS / name
        if p.is_file():
            df = pd.read_csv(p)
            df["bucket"] = label
            frames.append(df)
    if not frames:
        print("No CSV files found in", RESULTS)
        sys.exit(1)
    return pd.concat(frames, ignore_index=True)


def load_equity(row) -> pd.Series | None:
    name = row.get("equity_file")
    if not isinstance(name, str):
        # try conventional name
        name = f"{row['strategy_id']}__{row['symbol']}__{row['tf']}.parquet"
    p = EQUITY_DIR / name
    if not p.is_file():
        return None
    try:
        return pd.read_parquet(p)["equity"]
    except Exception:
        return None


def build() -> str:
    df = load_results()
    # Fill NaN numeric cells so the table is stable
    if "status" in df.columns:
        df = df[df["status"].isna() | (df["status"] == "ok")].copy()
    df = df[df["n_trades"].fillna(0) > 0].reset_index(drop=True)

    # Pre-render per-cell drill-down content
    svgs: list[str] = []
    heatmaps: list[str] = []
    yrs: list[str] = []
    for _, row in df.iterrows():
        eq = load_equity(row)
        svgs.append(equity_svg(eq))
        heatmaps.append(monthly_heatmap(row.get("monthly_returns", "{}")))
        yrs.append(yearly_bars(row.get("yearly_returns", "{}")))

    # Top performers section
    top = df.sort_values("gates_passed", ascending=False).head(10)

    # Totals
    total_cells = len(df)
    passing_5 = (df["gates_passed"] >= 5).sum()
    passing_4 = (df["gates_passed"] >= 4).sum()
    passing_3 = (df["gates_passed"] >= 3).sum()
    total_trades = int(df["n_trades"].fillna(0).sum())

    # Main table rows
    main_rows = []
    for i, row in df.iterrows():
        main_rows.append(f"""
<tr>
  <td><span class="bucket bucket-{row.get('bucket','?')}">{row.get('bucket','?')}</span></td>
  <td class="nowrap">{row['strategy_id']}</td>
  <td>{row['symbol']}</td>
  <td>{row['tf']}</td>
  <td>{int(row['n_trades'])}</td>
  <td>{fmt_num(row.get('win_rate',0)*100,1)}%</td>
  <td>{fmt_num(row.get('profit_factor',0),2)}</td>
  <td class="{ 'pos' if row.get('oos_sharpe',0)>=0 else 'neg' }">{fmt_num(row.get('oos_sharpe',0),2,sign=True)}</td>
  <td class="{ 'pos' if row.get('oos_calmar',0)>=0 else 'neg' }">{fmt_num(row.get('oos_calmar',0),2,sign=True)}</td>
  <td class="neg">{fmt_pct(row.get('oos_max_dd',0))}</td>
  <td>{fmt_num(row.get('oos_sortino',0),2,sign=True)}</td>
  <td>{fmt_num(row.get('oos_ulcer',0),2)}</td>
  <td>{fmt_num(row.get('oos_tail_ratio',0),2)}</td>
  <td>{fmt_num(row.get('oos_dsr',0),3)}</td>
  <td>{fmt_num(row.get('oos_psr',0),3)}</td>
  <td>{fmt_num(row.get('maker_fill_pct',0)*100,0)}%</td>
  <td>{gate_cell(row.get('gates_passed',0))}</td>
  <td><a href="#cell-{i}" class="drill">details</a></td>
</tr>
""")
    main_table = "\n".join(main_rows)

    # Drill-down sections
    details = []
    for i, row in df.iterrows():
        regime_sh = row.get("regime_sharpes", "{}")
        try:
            rs = json.loads(regime_sh) if isinstance(regime_sh, str) else {}
        except Exception:
            rs = {}
        regime_rows = "".join(
            f'<tr><td>{k}</td><td class="{"pos" if v>=0 else "neg"}">{v:+.2f}</td></tr>'
            for k, v in rs.items()
        )
        regime_table = (
            f'<table class="mini"><thead><tr><th>regime</th><th>Sharpe</th></tr></thead>'
            f'<tbody>{regime_rows}</tbody></table>' if rs else '<em style="color:#666">no regime data</em>'
        )
        details.append(f"""
<section id="cell-{i}" class="cell">
  <h3>{row['strategy_id']} · {row['symbol']} · {row['tf']} <span style="color:#666;font-weight:400">({row.get('bucket','')})</span></h3>
  <div class="cell-grid">
    <div>
      <div class="label">Equity (normalized)</div>
      {svgs[i]}
    </div>
    <div>
      <div class="label">Yearly returns</div>
      {yrs[i]}
    </div>
    <div>
      <div class="label">Regime-conditional Sharpe (OOS)</div>
      {regime_table}
    </div>
    <div>
      <div class="label">Key metrics (OOS)</div>
      <table class="mini">
        <tr><td>CAGR</td><td>{fmt_pct(row.get('oos_cagr',0))}</td></tr>
        <tr><td>Sharpe / Sortino</td><td>{fmt_num(row.get('oos_sharpe',0),2)} / {fmt_num(row.get('oos_sortino',0),2)}</td></tr>
        <tr><td>Calmar / UPI</td><td>{fmt_num(row.get('oos_calmar',0),2)} / {fmt_num(row.get('oos_upi',0),2)}</td></tr>
        <tr><td>Max DD / duration / recovery</td><td>{fmt_pct(row.get('oos_max_dd',0))} / {int(row.get('oos_dd_duration_bars',0))}b / {int(row.get('oos_dd_recovery_bars',0))}b</td></tr>
        <tr><td>Win rate / avg hold</td><td>{fmt_num(row.get('win_rate',0)*100,1)}% / {fmt_num(row.get('avg_hold_bars',0),1)}h</td></tr>
        <tr><td>Profit factor</td><td>{fmt_num(row.get('profit_factor',0),2)}</td></tr>
        <tr><td>Maker % / Unfilled %</td><td>{fmt_num(row.get('maker_fill_pct',0)*100,0)}% / {fmt_num(row.get('unfilled_pct',0)*100,0)}%</td></tr>
        <tr><td>Total fees</td><td>${fmt_num(row.get('total_fee_paid',0),0)}</td></tr>
        <tr><td>ρ vs buy-and-hold</td><td>{fmt_num(row.get('rho_buy_hold_oos',0),2,sign=True)}</td></tr>
        <tr><td>Worst 3-month mean</td><td>{fmt_pct(row.get('worst3_months_mean',0))}</td></tr>
        <tr><td>Gates passed</td><td>{gate_cell(row.get('gates_passed',0))}</td></tr>
      </table>
    </div>
  </div>
  <div class="label" style="margin-top:10px">Monthly returns (%)</div>
  {heatmaps[i]}
</section>
""")
    details_html = "\n".join(details)

    # Top-10 mini table
    top_rows = []
    for _, row in top.iterrows():
        top_rows.append(
            f'<tr><td>{row["strategy_id"]}</td><td>{row["symbol"]}</td>'
            f'<td>{row["tf"]}</td>'
            f'<td class="pos">{fmt_num(row.get("oos_sharpe",0),2,sign=True)}</td>'
            f'<td class="pos">{fmt_num(row.get("oos_calmar",0),2,sign=True)}</td>'
            f'<td class="neg">{fmt_pct(row.get("oos_max_dd",0))}</td>'
            f'<td>{gate_cell(row.get("gates_passed",0))}</td></tr>'
        )
    top_html = "\n".join(top_rows)

    # Generation time
    gen_ts = pd.Timestamp.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Strategy Lab — Phase 5 Dashboard</title>
<style>
  body {{ background:#0b1016; color:#dde3eb; font-family:-apple-system,Segoe UI,Roboto,sans-serif; margin:0; padding:24px; font-size:13px; }}
  h1 {{ color:#eee; font-size:22px; margin:0 0 4px 0; }}
  h2 {{ color:#9dcefa; font-size:16px; margin-top:30px; border-bottom:1px solid #2a3342; padding-bottom:4px; }}
  h3 {{ color:#cfd6de; font-size:14px; margin:0 0 8px 0; }}
  .meta {{ color:#7d8796; font-size:11px; }}
  .summary-tiles {{ display:flex; gap:16px; margin:20px 0; }}
  .tile {{ background:#151b24; border:1px solid #2a3342; border-radius:5px; padding:12px 16px; min-width:110px; }}
  .tile .val {{ font-size:22px; color:#fff; font-weight:600; }}
  .tile .lab {{ font-size:10px; color:#7d8796; text-transform:uppercase; letter-spacing:0.5px; }}
  table {{ border-collapse:collapse; margin:10px 0; }}
  table.main, table.top {{ width:100%; font-size:12px; }}
  table.main th, table.main td, table.top th, table.top td {{ padding:5px 7px; text-align:right; border-bottom:1px solid #1d242f; }}
  table.main th, table.top th {{ background:#141a23; color:#9aa3b0; text-align:center; font-weight:600; border-bottom:2px solid #2a3342; position:sticky; top:0; }}
  table.main tbody tr:hover {{ background:#121820; }}
  table.main td:nth-child(2), table.main td:nth-child(3), table.main td:nth-child(4),
  table.top td:nth-child(1), table.top td:nth-child(2), table.top td:nth-child(3) {{ text-align:left; color:#cfd6de; }}
  table.mini {{ font-size:11px; }}
  table.mini td {{ padding:2px 8px; border-bottom:1px solid #1a202a; }}
  table.mini td:first-child {{ color:#7d8796; }}
  table.heatmap {{ font-size:10px; }}
  table.heatmap th {{ color:#7d8796; padding:2px 4px; font-weight:400; }}
  table.heatmap td {{ padding:3px 5px; text-align:center; color:#dde3eb; }}
  .pos {{ color:#4ac268; }}
  .neg {{ color:#d85a5a; }}
  .nowrap {{ white-space:nowrap; }}
  .bucket {{ font-size:10px; padding:1px 5px; border-radius:2px; }}
  .bucket-adaptive {{ background:#1d3a5f; color:#9dcefa; }}
  .bucket-existing {{ background:#3f3320; color:#e0b280; }}
  .cell {{ background:#0e131a; border:1px solid #1d242f; border-radius:5px; padding:14px; margin-bottom:14px; }}
  .cell-grid {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap:16px; }}
  .label {{ font-size:10px; color:#7d8796; text-transform:uppercase; letter-spacing:0.5px; margin-bottom:4px; }}
  a.drill {{ color:#9dcefa; font-size:11px; text-decoration:none; }}
  a.drill:hover {{ text-decoration:underline; }}
  footer {{ color:#555; font-size:10px; margin-top:40px; border-top:1px solid #1d242f; padding-top:10px; }}
</style>
</head>
<body>
  <h1>Strategy Lab — Phase 5 Dashboard</h1>
  <div class="meta">Generated {gen_ts} · {total_cells} cells · {total_trades:,} total OOS trades</div>

  <div class="summary-tiles">
    <div class="tile"><div class="val">{total_cells}</div><div class="lab">cells</div></div>
    <div class="tile"><div class="val" style="color:#4ac268">{passing_5}</div><div class="lab">5/7 gates</div></div>
    <div class="tile"><div class="val" style="color:#c9a23a">{passing_4}</div><div class="lab">4/7 gates</div></div>
    <div class="tile"><div class="val" style="color:#9dcefa">{passing_3}</div><div class="lab">3/7 gates</div></div>
    <div class="tile"><div class="val">{total_trades:,}</div><div class="lab">trades</div></div>
  </div>

  <h2>Top 10 (by gates passed)</h2>
  <table class="top">
    <thead><tr>
      <th>Strategy</th><th>Sym</th><th>TF</th>
      <th>Sharpe</th><th>Calmar</th><th>MaxDD</th><th>Gates</th>
    </tr></thead>
    <tbody>{top_html}</tbody>
  </table>

  <h2>Full matrix ({total_cells} cells)</h2>
  <table class="main">
    <thead><tr>
      <th>Book</th><th>Strategy</th><th>Sym</th><th>TF</th>
      <th>#Tr</th><th>Win</th><th>PF</th>
      <th>Sharpe</th><th>Calmar</th><th>MaxDD</th>
      <th>Sortino</th><th>Ulcer</th><th>Tail</th><th>DSR</th><th>PSR</th>
      <th>Maker</th><th>Gates</th><th></th>
    </tr></thead>
    <tbody>{main_table}</tbody>
  </table>

  <h2>Per-cell drill-down</h2>
  {details_html}

  <footer>
    Phase 5 matrix · adaptive strategies executed in <code>mode=limit</code> ·
    existing book executed in <code>mode=v1</code> for baseline parity ·
    metrics per <code>strategy_lab/eval/metrics.py</code> ·
    gates: MDD&lt;20%, Calmar&gt;1.5, DSR&gt;1, DSR-prob&gt;0.95, ≥2 profitable regimes, |ρ_BH|&lt;0.5, maker≥60%
  </footer>
</body>
</html>
"""


def main():
    html = build()
    OUT.write_text(html, encoding="utf-8")
    size_kb = OUT.stat().st_size / 1024
    print(f"Wrote {OUT} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
