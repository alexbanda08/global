"""
polymarket_alt_dashboard.py — single-file HTML dashboard for alt-strategy hunt.

Combines:
  - alt_signal_grid.csv     (signal variants)
  - time_of_day_*.csv       (hour/session/dow/asset_hourbin/per_trade)
  - strategy_stacks.csv     (q × time stacks)
  - signal_grid_v2.csv      (locked baseline reference)

Outputs:
  reports/POLYMARKET_ALT_STRATEGIES_DASHBOARD.html
"""
from __future__ import annotations
from pathlib import Path
import json
import pandas as pd

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results" / "polymarket"
OUT = HERE / "reports" / "POLYMARKET_ALT_STRATEGIES_DASHBOARD.html"


def load():
    return {
        "alt": pd.read_csv(RESULTS/"alt_signal_grid.csv"),
        "stacks": pd.read_csv(RESULTS/"strategy_stacks.csv"),
        "tod_hourly": pd.read_csv(RESULTS/"time_of_day_hourly.csv"),
        "tod_session": pd.read_csv(RESULTS/"time_of_day_session.csv"),
        "tod_dow": pd.read_csv(RESULTS/"time_of_day_dow.csv"),
        "tod_asset_hb": pd.read_csv(RESULTS/"time_of_day_asset_hourbin.csv"),
        "tod_trades": pd.read_csv(RESULTS/"time_of_day_per_trade.csv"),
    }


def build_html(d) -> str:
    payload = {
        "alt":      d["alt"].fillna(0).to_dict(orient="records"),
        "stacks":   d["stacks"].fillna(0).to_dict(orient="records"),
        "tod_hour": d["tod_hourly"].fillna(0).to_dict(orient="records"),
        "tod_sess": d["tod_session"].fillna(0).to_dict(orient="records"),
        "tod_dow":  d["tod_dow"].fillna(0).to_dict(orient="records"),
        "tod_ahb":  d["tod_asset_hb"].fillna(0).to_dict(orient="records"),
    }
    payload_json = json.dumps(payload).replace("</", "<\\/")

    html = """<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Polymarket Alt-Strategies — Hunt Dashboard</title>
<style>
:root {
  --bg: #0a0a0d; --surface: #16161b; --surface2: #1f1f26;
  --border: #2a2a32; --text: #e4e4ec; --text-secondary: #a0a0b0; --text-dim: #6a6a78;
  --accent: #5e8eef; --accent-2: #f08e5e;
  --green: #4ade80; --red: #f87171; --yellow: #fbbf24;
}
[data-theme="light"] {
  --bg: #f5f5f7; --surface: #ffffff; --surface2: #f0f0f2;
  --border: #e0e0e4; --text: #1a1a2e; --text-secondary: #5a5a72; --text-dim: #a0a0b0;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, 'Inter', sans-serif; background: var(--bg); color: var(--text); padding: 0 0 80px 0; }
.container { max-width: 1500px; margin: 0 auto; padding: 24px; }
header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid var(--border); }
h1 { font-size: 22px; font-weight: 700; letter-spacing: -0.02em; }
h1 small { font-size: 13px; font-weight: 400; color: var(--text-secondary); margin-left: 8px; }
h2 { font-size: 16px; margin: 32px 0 12px 0; font-weight: 600; }
h3 { font-size: 13px; margin: 16px 0 8px 0; font-weight: 600; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.05em; }
.theme-toggle { background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 6px 12px; color: var(--text); cursor: pointer; font-size: 12px; }

.grid { display: grid; gap: 16px; }
.grid-3 { grid-template-columns: repeat(3, 1fr); }
.grid-4 { grid-template-columns: repeat(4, 1fr); }
.grid-2 { grid-template-columns: 1fr 1fr; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
.kpi-label { font-size: 11px; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.05em; }
.kpi-value { font-size: 22px; font-weight: 700; margin-top: 4px; font-family: 'JetBrains Mono', monospace; }
.kpi-sub { font-size: 11px; color: var(--text-secondary); margin-top: 2px; }
.kpi-good { color: var(--green); }
.kpi-bad { color: var(--red); }
.kpi-warn { color: var(--yellow); }

table { width: 100%; border-collapse: collapse; font-size: 12px; font-family: 'JetBrains Mono', monospace; }
table th, table td { padding: 6px 10px; text-align: right; border-bottom: 1px solid var(--border); }
table th { font-weight: 600; color: var(--text-secondary); background: var(--surface2); position: sticky; top: 0; cursor: pointer; user-select: none; }
table th:first-child, table td:first-child { text-align: left; }
table tr:hover td { background: var(--surface2); }
.tag { display: inline-block; padding: 2px 8px; border-radius: 3px; font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; }
.tag-asset-btc { background: rgba(247, 147, 26, 0.2); color: #f7931a; }
.tag-asset-eth { background: rgba(98, 126, 234, 0.2); color: #627eea; }
.tag-asset-sol { background: rgba(20, 241, 149, 0.2); color: #14f195; }
.tag-asset-ALL { background: rgba(160, 160, 176, 0.2); color: var(--text-secondary); }
.row-baseline { background: rgba(94, 142, 239, 0.05); }
.row-baseline td { font-weight: 600; }

.section-summary { background: var(--surface2); border-left: 3px solid var(--accent); padding: 12px 16px; margin: 12px 0; border-radius: 4px; font-size: 13px; line-height: 1.5; }
.section-summary strong { color: var(--text); }
.section-summary code { font-family: 'JetBrains Mono', monospace; background: var(--bg); padding: 1px 5px; border-radius: 3px; font-size: 11px; }

.controls { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
.controls select, .controls input { background: var(--surface); border: 1px solid var(--border); color: var(--text); padding: 6px 10px; border-radius: 6px; font-size: 12px; font-family: inherit; }
.controls label { font-size: 11px; color: var(--text-secondary); display: flex; align-items: center; gap: 6px; }

svg { display: block; }
.line { fill: none; stroke-width: 2; }
.line-btc { stroke: #f7931a; }
.line-eth { stroke: #627eea; }
.line-sol { stroke: #14f195; }
.line-ALL { stroke: var(--text-secondary); }
.dot { stroke-width: 2; fill: var(--surface); }
.axis { stroke: var(--border); stroke-width: 1; }
.axis-text { fill: var(--text-dim); font-size: 10px; font-family: 'JetBrains Mono', monospace; }
.legend { display: flex; gap: 12px; font-size: 11px; margin-top: 8px; flex-wrap: wrap; color: var(--text-secondary); }
.legend-dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 4px; vertical-align: middle; }

/* heatmap */
.heatmap-cell { stroke: var(--bg); stroke-width: 1; }
.heat-text { fill: var(--text); font-family: 'JetBrains Mono', monospace; font-size: 9px; pointer-events: none; }
.heat-text-dark { fill: #0a0a0d; }

.pos { color: var(--green); }
.neg { color: var(--red); }
.dim { color: var(--text-dim); }

#stacks-table th, #alt-table th { cursor: pointer; }

.bar-row { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; font-size: 11px; font-family: 'JetBrains Mono', monospace; }
.bar-row .label { width: 220px; color: var(--text-secondary); }
.bar-row .bar { flex: 1; height: 18px; background: var(--surface2); border-radius: 3px; overflow: hidden; position: relative; }
.bar-row .bar-fill { height: 100%; background: var(--accent); }
.bar-row .bar-fill.green { background: var(--green); }
.bar-row .bar-fill.red { background: var(--red); }
.bar-row .bar-fill.yellow { background: var(--yellow); }
.bar-row .val { width: 130px; text-align: right; font-size: 11px; }
</style>
</head>
<body>
<div class="container">
<header>
  <h1>Polymarket Alt-Strategies <small>q-tightening × time-of-day × signal variants</small></h1>
  <button class="theme-toggle" onclick="toggleTheme()">☀ Light</button>
</header>

<!-- Headline KPIs -->
<div class="grid grid-4">
  <div class="card">
    <div class="kpi-label">Locked baseline</div>
    <div class="kpi-value">+20.23%</div>
    <div class="kpi-sub">q20 × no filter · n=1152 · hit 73.8%</div>
  </div>
  <div class="card">
    <div class="kpi-label">Best stacked (practical)</div>
    <div class="kpi-value kpi-good">+29.40%</div>
    <div class="kpi-sub">q10 × good hours · n=293 · hit 86.0%</div>
  </div>
  <div class="card">
    <div class="kpi-label">Best stacked (precision)</div>
    <div class="kpi-value kpi-good">+32.96%</div>
    <div class="kpi-sub">q10 × europe · n=90 · hit 90.0%</div>
  </div>
  <div class="card">
    <div class="kpi-label">Sweet spot single hour</div>
    <div class="kpi-value kpi-good">09:00 UTC</div>
    <div class="kpi-sub">+32.10% · 89.4% hit · n=47</div>
  </div>
</div>

<h2>1. Alt-signal grid — different signal definitions, same exit (hedge-hold rev_bp=5)</h2>
<div class="section-summary">
  <strong>Tighter quintiles win across the board.</strong>
  Locked baseline <code>sig_ret5m_q20</code> (top/bot 20% of |ret_5m|) is beaten by <code>sig_ret5m_q10</code> in every cell.
  <code>q5</code> (top/bot 5%) goes higher still but sample sizes drop to 25-218.
  Long-horizon variants (<code>ret_15m</code>, <code>ret_1h</code>) underperform — confirms 5m horizon is right.
  <code>smart_minus_retail</code> alone is weak (53-60% hit) but as a co-filter (<code>combo</code>) it sometimes helps.
</div>
<div class="controls">
  <label>Asset:
    <select id="alt-asset"><option value="">all</option><option>ALL</option><option>btc</option><option>eth</option><option>sol</option></select>
  </label>
  <label>TF:
    <select id="alt-tf"><option value="">all</option><option>ALL</option><option>15m</option><option>5m</option></select>
  </label>
  <label>Min n:
    <input type="number" id="alt-min-n" value="0" style="width:80px"/>
  </label>
</div>
<div class="card" style="overflow-x:auto">
  <table id="alt-table">
    <thead>
      <tr>
        <th data-sort="asset">Asset</th>
        <th data-sort="timeframe">TF</th>
        <th data-sort="signal">Signal</th>
        <th data-sort="n">n</th>
        <th data-sort="hit">Hit%</th>
        <th data-sort="pnl_mean">PnL/trade</th>
        <th data-sort="roi_pct">ROI</th>
        <th data-sort="ci_lo">95% CI lo</th>
        <th data-sort="ci_hi">95% CI hi</th>
      </tr>
    </thead>
    <tbody></tbody>
  </table>
</div>

<h2>2. Time-of-day — UTC hour stratification of the locked baseline</h2>
<div class="section-summary">
  Each market's <code>window_start</code> bucketed by UTC hour. The locked baseline performs very differently across sessions:
  <strong>Asia overnight (00-08 UTC)</strong> = weakest (66% hit / +16% ROI),
  <strong>Europe morning (08-13 UTC)</strong> = strongest (77% hit / +27% ROI).
  Best single hour is <strong>09:00 UTC</strong> (89.4% hit / +32.10% ROI).
  Bad hours to skip: <code>{0, 2, 4, 7, 16}</code>.
</div>
<div class="grid grid-2">
  <div class="card">
    <h3>ROI by UTC hour (★ = above baseline ROI)</h3>
    <div id="chart-tod-hourly"></div>
  </div>
  <div class="card">
    <h3>Hit rate by UTC hour</h3>
    <div id="chart-tod-hourly-hit"></div>
  </div>
</div>

<div class="card" style="margin-top:16px">
  <h3>Heatmap — ROI by asset × 4-hour UTC bin</h3>
  <div id="chart-heatmap"></div>
  <div class="legend">
    <span><span class="legend-dot" style="background:#4ade80"></span>high ROI</span>
    <span><span class="legend-dot" style="background:#fbbf24"></span>mid</span>
    <span><span class="legend-dot" style="background:#f87171"></span>low / negative</span>
  </div>
</div>

<div class="grid grid-2" style="margin-top:16px">
  <div class="card">
    <h3>By session</h3>
    <div id="bar-session"></div>
  </div>
  <div class="card">
    <h3>By day of week</h3>
    <div id="bar-dow"></div>
  </div>
</div>

<h2>3. Strategy stacks — q-tightening × time-of-day combinations</h2>
<div class="section-summary">
  <strong>Stacking IS multiplicative.</strong> q10 alone gives +4.35pp, good_hours alone gives +5.32pp,
  combined gives <strong>+9.17pp</strong>. Best stack <code>europe_q10</code> = <strong>+12.73pp</strong> ROI lift
  (90 trades / 90% hit / +32.96% ROI).
  <strong>Caveat:</strong> 5-day data window — forward-walk validation needed before live deployment.
</div>
<div class="controls">
  <label>Asset:
    <select id="stk-asset"><option value="">all</option><option>ALL</option><option>btc</option><option>eth</option><option>sol</option></select>
  </label>
  <label>TF:
    <select id="stk-tf"><option value="">all</option><option>ALL</option><option>15m</option><option>5m</option></select>
  </label>
</div>
<div class="card" style="overflow-x:auto">
  <table id="stacks-table">
    <thead>
      <tr>
        <th data-sort="asset">Asset</th>
        <th data-sort="tf">TF</th>
        <th data-sort="stack">Stack</th>
        <th data-sort="n">n</th>
        <th data-sort="hit">Hit%</th>
        <th data-sort="pnl_mean">PnL/trade</th>
        <th data-sort="roi">ROI</th>
        <th data-sort="ci_lo">95% CI lo</th>
        <th data-sort="ci_hi">95% CI hi</th>
        <th data-sort="vs_base">vs baseline</th>
      </tr>
    </thead>
    <tbody></tbody>
  </table>
</div>

<h2>4. Action recommendations</h2>
<div class="card">
  <h3>For live deployment — choose your trade-off</h3>
  <div class="bar-row"><span class="label"><strong>Volume-friendly</strong> · q20 + bad-hour exclusion</span><div class="bar"><div class="bar-fill green" style="width:81%"></div></div><span class="val">81% volume / +22.83%</span></div>
  <div class="bar-row"><span class="label"><strong>Balanced</strong> · q10 + bad-hour exclusion</span><div class="bar"><div class="bar-fill green" style="width:41%"></div></div><span class="val">41% volume / +27.00%</span></div>
  <div class="bar-row"><span class="label"><strong>Practical sweet spot</strong> · q10 + good hours</span><div class="bar"><div class="bar-fill green" style="width:25%"></div></div><span class="val">25% volume / +29.40%</span></div>
  <div class="bar-row"><span class="label"><strong>Max precision</strong> · q10 + europe hours</span><div class="bar"><div class="bar-fill green" style="width:8%"></div></div><span class="val">8% volume / +32.96%</span></div>
  <div class="bar-row"><span class="label">Locked baseline (current TV plan)</span><div class="bar"><div class="bar-fill" style="width:100%"></div></div><span class="val">100% volume / +20.23%</span></div>

  <h3 style="margin-top:24px">Open questions</h3>
  <ul style="font-size:13px; line-height:1.7; color: var(--text-secondary); padding-left:24px">
    <li><strong>Forward-walk validation</strong>: 5-day in-sample window. Time-of-day filter could be overfit. Run holdout test before shipping.</li>
    <li><strong>Why does 16:00 UTC underperform?</strong> 90 trades / 64.4% hit / +8.6% ROI — a structural anomaly worth investigating.</li>
    <li><strong>Does this stack with realistic fills?</strong> E1 showed BTC scales to $250 cleanly — re-run E1 on q10+good_hours stack to confirm capacity.</li>
    <li><strong>Composite signal</strong>: <code>combo_q20</code> (ret_5m AND smart_minus_retail) hit 81.2% on BTC×15m (n=48). Stack with hours?</li>
  </ul>
</div>

</div>

<script>
const DATA = __PAYLOAD__;

function toggleTheme() {
  const t = document.documentElement;
  const cur = t.getAttribute('data-theme');
  const nxt = cur === 'dark' ? 'light' : 'dark';
  t.setAttribute('data-theme', nxt);
  document.querySelector('.theme-toggle').textContent = nxt === 'dark' ? '☀ Light' : '🌙 Dark';
}

function fmt(v, d=4) {
  if (v === null || v === undefined || (typeof v === 'number' && !isFinite(v))) return '—';
  if (typeof v === 'number') return v.toFixed(d);
  return v;
}
function fmtMoney(v) {
  if (v === null || !isFinite(v)) return '—';
  const sign = v >= 0 ? '+' : '';
  if (Math.abs(v) >= 1) return '$'+sign+v.toFixed(2);
  return '$'+sign+v.toFixed(4);
}
function pncolor(v) { return v > 0 ? 'pos' : (v < 0 ? 'neg' : 'dim'); }

// ===== Alt-signal table =====
let altSort = {col: 'roi_pct', dir: -1};
function buildAltTable() {
  const a = document.getElementById('alt-asset').value;
  const tf = document.getElementById('alt-tf').value;
  const minN = parseInt(document.getElementById('alt-min-n').value || 0);
  let rows = DATA.alt.filter(r =>
    (!a || r.asset === a) && (!tf || r.timeframe === tf) && r.n >= minN
  );
  rows.sort((x, y) => {
    const va = x[altSort.col], vb = y[altSort.col];
    if (typeof va === 'string') return va.localeCompare(vb) * altSort.dir;
    return ((va || 0) - (vb || 0)) * altSort.dir;
  });
  const tb = document.querySelector('#alt-table tbody');
  tb.innerHTML = rows.map(r => `
    <tr class="${r.signal === 'sig_ret5m_q20' ? 'row-baseline' : ''}">
      <td><span class="tag tag-asset-${r.asset}">${r.asset}</span></td>
      <td>${r.timeframe}</td>
      <td>${r.signal}${r.signal==='sig_ret5m_q20'?' ★':''}</td>
      <td>${r.n}</td>
      <td>${(r.hit*100).toFixed(1)}%</td>
      <td>${fmtMoney(r.pnl_mean)}</td>
      <td class="${r.roi_pct > 20.23 ? 'pos' : 'dim'}">${r.roi_pct.toFixed(2)}%</td>
      <td>${fmtMoney(r.ci_lo)}</td>
      <td>${fmtMoney(r.ci_hi)}</td>
    </tr>
  `).join('');
}

// ===== Stacks table =====
let stkSort = {col: 'roi', dir: -1};
function buildStacksTable() {
  const a = document.getElementById('stk-asset').value;
  const tf = document.getElementById('stk-tf').value;
  let rows = DATA.stacks.filter(r => (!a || r.asset === a) && (!tf || r.tf === tf));
  // compute baseline per cell for delta
  const base = {};
  DATA.stacks.forEach(r => {
    if (r.stack === 'baseline_q20') base[`${r.asset}/${r.tf}`] = r.roi;
  });
  rows = rows.map(r => ({...r, vs_base: r.roi - (base[`${r.asset}/${r.tf}`] || 0)}));
  rows.sort((x, y) => {
    const va = x[stkSort.col], vb = y[stkSort.col];
    if (typeof va === 'string') return va.localeCompare(vb) * stkSort.dir;
    return ((va || 0) - (vb || 0)) * stkSort.dir;
  });
  const tb = document.querySelector('#stacks-table tbody');
  tb.innerHTML = rows.map(r => `
    <tr class="${r.stack === 'baseline_q20' ? 'row-baseline' : ''}">
      <td><span class="tag tag-asset-${r.asset}">${r.asset}</span></td>
      <td>${r.tf}</td>
      <td>${r.stack}${r.stack==='baseline_q20'?' ★':''}</td>
      <td>${r.n}</td>
      <td>${r.n > 0 ? (r.hit*100).toFixed(1)+'%' : '—'}</td>
      <td>${fmtMoney(r.pnl_mean)}</td>
      <td class="${r.roi > 20.23 ? 'pos' : 'dim'}">${r.roi.toFixed(2)}%</td>
      <td>${fmtMoney(r.ci_lo)}</td>
      <td>${fmtMoney(r.ci_hi)}</td>
      <td class="${r.vs_base > 0 ? 'pos' : (r.vs_base < 0 ? 'neg' : 'dim')}">${r.vs_base > 0 ? '+' : ''}${r.vs_base.toFixed(2)}pp</td>
    </tr>
  `).join('');
}

// ===== TOD hourly chart =====
function todHourlyChart() {
  const W = 600, H = 240, M = {t:10, r:10, b:30, l:50};
  const data = DATA.tod_hour;
  const overall = 20.23;
  const ymax = Math.max(40, ...data.map(d => d.roi));
  const ymin = Math.min(0, ...data.map(d => d.roi));
  const xScale = i => M.l + (i / 23) * (W - M.l - M.r);
  const yScale = v => H - M.b - ((v - ymin) / (ymax - ymin)) * (H - M.t - M.b);

  let svg = `<svg width="100%" height="${H}" viewBox="0 0 ${W} ${H}">`;
  svg += `<line x1="${M.l}" y1="${H-M.b}" x2="${W-M.r}" y2="${H-M.b}" class="axis"/>`;
  svg += `<line x1="${M.l}" y1="${M.t}" x2="${M.l}" y2="${H-M.b}" class="axis"/>`;
  // baseline reference line
  const yBase = yScale(overall);
  svg += `<line x1="${M.l}" y1="${yBase}" x2="${W-M.r}" y2="${yBase}" stroke="var(--text-dim)" stroke-dasharray="3,3"/>`;
  svg += `<text x="${W-M.r-4}" y="${yBase-3}" text-anchor="end" class="axis-text">baseline ${overall}%</text>`;
  // bars
  data.forEach((d, i) => {
    const x = xScale(i) - 10;
    const y = yScale(Math.max(d.roi, 0));
    const h = Math.abs(yScale(d.roi) - yScale(0));
    const color = d.roi >= overall ? 'var(--green)' : (d.roi >= overall - 5 ? 'var(--yellow)' : 'var(--red)');
    svg += `<rect x="${x}" y="${d.roi >= 0 ? y : yScale(0)}" width="20" height="${h}" fill="${color}" opacity="0.8"/>`;
    if (i % 3 === 0) {
      svg += `<text x="${xScale(i)}" y="${H-M.b+14}" text-anchor="middle" class="axis-text">${i.toString().padStart(2, '0')}</text>`;
    }
  });
  // y ticks
  for (let i = 0; i <= 4; i++) {
    const y = M.t + i * (H - M.t - M.b) / 4;
    const v = ymax - i * (ymax - ymin) / 4;
    svg += `<text x="${M.l-6}" y="${y+3}" text-anchor="end" class="axis-text">${v.toFixed(0)}%</text>`;
  }
  svg += '</svg>';
  document.getElementById('chart-tod-hourly').innerHTML = svg;
}

function todHourlyHitChart() {
  const W = 600, H = 240, M = {t:10, r:10, b:30, l:50};
  const data = DATA.tod_hour;
  const overall = 73.8;
  const xScale = i => M.l + (i / 23) * (W - M.l - M.r);
  const yScale = v => H - M.b - ((v - 40) / 60) * (H - M.t - M.b);
  let svg = `<svg width="100%" height="${H}" viewBox="0 0 ${W} ${H}">`;
  svg += `<line x1="${M.l}" y1="${H-M.b}" x2="${W-M.r}" y2="${H-M.b}" class="axis"/>`;
  svg += `<line x1="${M.l}" y1="${M.t}" x2="${M.l}" y2="${H-M.b}" class="axis"/>`;
  const yBase = yScale(overall);
  svg += `<line x1="${M.l}" y1="${yBase}" x2="${W-M.r}" y2="${yBase}" stroke="var(--text-dim)" stroke-dasharray="3,3"/>`;
  svg += `<text x="${W-M.r-4}" y="${yBase-3}" text-anchor="end" class="axis-text">baseline ${overall}%</text>`;
  data.forEach((d, i) => {
    const x = xScale(i) - 10;
    const hitPct = d.hit * 100;
    const y = yScale(hitPct);
    const h = Math.max(0, yScale(40) - y);
    const color = hitPct >= overall + 5 ? 'var(--green)' : (hitPct >= overall - 5 ? 'var(--yellow)' : 'var(--red)');
    svg += `<rect x="${x}" y="${y}" width="20" height="${h}" fill="${color}" opacity="0.8"/>`;
    if (i % 3 === 0) {
      svg += `<text x="${xScale(i)}" y="${H-M.b+14}" text-anchor="middle" class="axis-text">${i.toString().padStart(2, '0')}</text>`;
    }
  });
  for (let i = 0; i <= 4; i++) {
    const y = M.t + i * (H - M.t - M.b) / 4;
    const v = 100 - i * 60 / 4;
    svg += `<text x="${M.l-6}" y="${y+3}" text-anchor="end" class="axis-text">${v.toFixed(0)}%</text>`;
  }
  svg += '</svg>';
  document.getElementById('chart-tod-hourly-hit').innerHTML = svg;
}

// ===== Heatmap asset × hour bin =====
function heatmap() {
  const data = DATA.tod_ahb;
  const assets = ['btc', 'eth', 'sol'];
  const bins = ['00-04', '04-08', '08-12', '12-16', '16-20', '20-24'];
  const W = 1000, H = 220, M = {t:30, r:20, b:30, l:60};
  const cw = (W - M.l - M.r) / bins.length;
  const ch = (H - M.t - M.b) / assets.length;
  const allRois = data.map(d => d.roi);
  const rmin = Math.min(...allRois), rmax = Math.max(...allRois);
  function color(v) {
    const norm = (v - rmin) / (rmax - rmin);
    if (norm > 0.66) return '#4ade80';
    if (norm > 0.33) return '#fbbf24';
    return '#f87171';
  }
  let svg = `<svg width="100%" height="${H}" viewBox="0 0 ${W} ${H}">`;
  // x labels
  bins.forEach((b, i) => {
    svg += `<text x="${M.l + cw*i + cw/2}" y="${M.t-8}" text-anchor="middle" class="axis-text">${b}</text>`;
  });
  // y labels + cells
  assets.forEach((a, ai) => {
    svg += `<text x="${M.l-8}" y="${M.t + ch*ai + ch/2 + 4}" text-anchor="end" class="axis-text">${a}</text>`;
    bins.forEach((b, bi) => {
      const r = data.find(d => d.asset === a && d.hour_bin === b);
      if (!r) return;
      const x = M.l + cw*bi;
      const y = M.t + ch*ai;
      svg += `<rect x="${x}" y="${y}" width="${cw}" height="${ch}" fill="${color(r.roi)}" class="heatmap-cell"/>`;
      svg += `<text x="${x+cw/2}" y="${y+ch/2}" text-anchor="middle" class="heat-text-dark" style="font-weight:600">${r.roi.toFixed(1)}%</text>`;
      svg += `<text x="${x+cw/2}" y="${y+ch/2+12}" text-anchor="middle" class="heat-text-dark" style="font-size:8px">${(r.hit*100).toFixed(0)}% n=${r.n}</text>`;
    });
  });
  svg += '</svg>';
  document.getElementById('chart-heatmap').innerHTML = svg;
}

// ===== Bar charts for session/dow =====
function barChart(containerId, data, labelKey, vKey, baseline) {
  const max = Math.max(...data.map(d => d[vKey]));
  let html = '';
  data.forEach(d => {
    const pct = (d[vKey] / max) * 100;
    const color = d[vKey] > baseline ? 'green' : (d[vKey] >= baseline - 5 ? 'yellow' : 'red');
    html += `<div class="bar-row"><span class="label">${d[labelKey]}</span><div class="bar"><div class="bar-fill ${color}" style="width:${pct}%"></div></div><span class="val">${d[vKey].toFixed(2)}% · n=${d.n} · ${(d.hit*100).toFixed(1)}%</span></div>`;
  });
  document.getElementById(containerId).innerHTML = html;
}

function setupSorts() {
  document.querySelectorAll('#alt-table th').forEach(th => {
    th.addEventListener('click', () => {
      const col = th.dataset.sort;
      if (altSort.col === col) altSort.dir = -altSort.dir;
      else { altSort.col = col; altSort.dir = -1; }
      buildAltTable();
    });
  });
  document.querySelectorAll('#stacks-table th').forEach(th => {
    th.addEventListener('click', () => {
      const col = th.dataset.sort;
      if (stkSort.col === col) stkSort.dir = -stkSort.dir;
      else { stkSort.col = col; stkSort.dir = -1; }
      buildStacksTable();
    });
  });
  ['alt-asset','alt-tf','alt-min-n'].forEach(id =>
    document.getElementById(id).addEventListener('change', buildAltTable)
  );
  ['alt-min-n'].forEach(id =>
    document.getElementById(id).addEventListener('input', buildAltTable)
  );
  ['stk-asset','stk-tf'].forEach(id =>
    document.getElementById(id).addEventListener('change', buildStacksTable)
  );
}

setupSorts();
buildAltTable();
buildStacksTable();
todHourlyChart();
todHourlyHitChart();
heatmap();
barChart('bar-session', DATA.tod_sess, 'session', 'roi', 20.23);
barChart('bar-dow', DATA.tod_dow.filter(d => d.n > 0), 'dow_name', 'roi', 20.23);
</script>
</body>
</html>
"""
    return html.replace("__PAYLOAD__", payload_json)


def main():
    d = load()
    print(f"loaded: alt={len(d['alt'])}, stacks={len(d['stacks'])}, tod_hour={len(d['tod_hourly'])}")
    html = build_html(d)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    size_mb = OUT.stat().st_size / 1024 / 1024
    print(f"Wrote {OUT} ({size_mb:.2f} MB)")


if __name__ == "__main__":
    main()
