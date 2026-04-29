"""
polymarket_realfills_dashboard.py — single-file HTML dashboard for E1 results.

Reads:
  results/polymarket/realfills_validate_cells.csv
  results/polymarket/realfills_validate_per_trade.json

Writes:
  reports/POLYMARKET_REALFILLS_DASHBOARD.html

Sections:
  1. Validation panel (baseline_v2 vs realfills $1 — confirms handoff baseline)
  2. Capacity ladder (per-asset ROI vs stake)
  3. Distributions (pnl histograms, fill quality)
  4. Trade explorer (sortable, filterable table)

Vanilla JS, no external deps. Theme switcher (light/dark).
"""
from __future__ import annotations
from pathlib import Path
import json
import math
import pandas as pd

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results" / "polymarket"
OUT = HERE / "reports" / "POLYMARKET_REALFILLS_DASHBOARD.html"


def load_data():
    cells = pd.read_csv(RESULTS / "realfills_validate_cells.csv")
    with open(RESULTS / "realfills_validate_per_trade.json") as f:
        trades = json.load(f)
    return cells, trades


def fmt_money(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    return f"${v:+,.2f}" if abs(v) >= 1 else f"${v:+.4f}"


def fmt_pct(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    return f"{v*100:.1f}%" if abs(v) <= 1.1 else f"{v:.2f}%"


def build_html(cells: pd.DataFrame, trades: list) -> str:
    # Validation table: side-by-side baseline_v2 vs realfills $1 for ALL combos
    base = cells[cells["mode"] == "baseline_v2"].copy()
    real = cells[cells["mode"] == "realistic"].copy()

    val_rows = []
    for _, b in base.iterrows():
        # match realfills @ $1 stake for same asset/tf
        r1 = real[(real.asset == b.asset) & (real.tf == b.tf) & (real["notional"] == "1.0")]
        if len(r1) == 0:
            r1 = real[(real.asset == b.asset) & (real.tf == b.tf) & (real["notional"].astype(float) == 1.0)]
        r1 = r1.iloc[0] if len(r1) else None
        val_rows.append({
            "asset": b.asset, "tf": b.tf,
            "base_n": int(b.n), "base_hit": float(b.hit), "base_pnl": float(b.pnl_mean),
            "base_roi": float(b.roi_v2), "base_total": float(b.pnl_total),
            "real_n": int(r1.n) if r1 is not None else 0,
            "real_hit": float(r1.hit) if r1 is not None else None,
            "real_pnl": float(r1.pnl_mean) if r1 is not None else None,
            "real_roi_v2": float(r1.roi_v2) if r1 is not None else None,
            "real_roi_cap": float(r1.roi_capital) if r1 is not None else None,
        })

    # Capacity ladder: realistic per asset across stakes
    ladder = []
    for asset in ["btc", "eth", "sol", "ALL"]:
        for tf in ["5m", "15m", "ALL"]:
            sub = real[(real.asset == asset) & (real.tf == tf)].copy()
            sub["notional_f"] = sub["notional"].astype(float)
            sub = sub.sort_values("notional_f")
            ladder.append({
                "asset": asset, "tf": tf,
                "points": [{
                    "stake": float(r.notional_f),
                    "n": int(r.n), "hit": float(r.hit),
                    "pnl_mean": float(r.pnl_mean),
                    "roi_v2": float(r.roi_v2),
                    "roi_cap": float(r.roi_capital),
                    "thin": int(r.skipped_thin) if "skipped_thin" in r and pd.notna(r.skipped_thin) else 0,
                } for _, r in sub.iterrows()]
            })

    payload = {
        "validation": val_rows,
        "ladder": ladder,
        "trades": trades,
    }
    payload_json = json.dumps(payload).replace("</", "<\\/")

    html = """<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Polymarket Realfills Dashboard — E1</title>
<style>
:root {
  --bg: #0a0a0d; --surface: #16161b; --surface2: #1f1f26;
  --border: #2a2a32; --text: #e4e4ec; --text-secondary: #a0a0b0; --text-dim: #6a6a78;
  --accent: #5e8eef; --accent-2: #f08e5e;
  --green: #4ade80; --red: #f87171; --yellow: #fbbf24;
  --sidebar-bg: #0e0e10;
}
[data-theme="light"] {
  --bg: #f5f5f7; --surface: #ffffff; --surface2: #f0f0f2;
  --border: #e0e0e4; --text: #1a1a2e; --text-secondary: #5a5a72; --text-dim: #a0a0b0;
  --sidebar-bg: #eaeaee;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, 'Inter', sans-serif; background: var(--bg); color: var(--text); padding: 0 0 80px 0; }
.container { max-width: 1400px; margin: 0 auto; padding: 24px; }
header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid var(--border); }
h1 { font-size: 22px; font-weight: 700; letter-spacing: -0.02em; }
h1 small { font-size: 13px; font-weight: 400; color: var(--text-secondary); margin-left: 8px; }
h2 { font-size: 16px; margin: 32px 0 12px 0; font-weight: 600; color: var(--text); }
h3 { font-size: 13px; margin: 16px 0 8px 0; font-weight: 600; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.05em; }
.theme-toggle { background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 6px 12px; color: var(--text); cursor: pointer; font-size: 12px; }
.theme-toggle:hover { background: var(--surface2); }

.grid { display: grid; gap: 16px; }
.grid-3 { grid-template-columns: repeat(3, 1fr); }
.grid-4 { grid-template-columns: repeat(4, 1fr); }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
.kpi-label { font-size: 11px; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.05em; }
.kpi-value { font-size: 22px; font-weight: 700; margin-top: 4px; font-family: 'JetBrains Mono', monospace; }
.kpi-sub { font-size: 11px; color: var(--text-secondary); margin-top: 2px; }
.kpi-good { color: var(--green); }
.kpi-bad { color: var(--red); }
.kpi-warn { color: var(--yellow); }

table { width: 100%; border-collapse: collapse; font-size: 12px; font-family: 'JetBrains Mono', monospace; }
table th, table td { padding: 6px 10px; text-align: right; border-bottom: 1px solid var(--border); }
table th { font-weight: 600; color: var(--text-secondary); text-align: right; background: var(--surface2); position: sticky; top: 0; }
table th:first-child, table td:first-child { text-align: left; }
table tr:hover td { background: var(--surface2); }

.tag { display: inline-block; padding: 2px 8px; border-radius: 3px; font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; }
.tag-base { background: rgba(94, 142, 239, 0.2); color: var(--accent); }
.tag-real { background: rgba(240, 142, 94, 0.2); color: var(--accent-2); }
.tag-asset-btc { background: rgba(247, 147, 26, 0.2); color: #f7931a; }
.tag-asset-eth { background: rgba(98, 126, 234, 0.2); color: #627eea; }
.tag-asset-sol { background: rgba(20, 241, 149, 0.2); color: #14f195; }
.tag-asset-ALL { background: rgba(160, 160, 176, 0.2); color: var(--text-secondary); }
.tag-good { background: rgba(74, 222, 128, 0.15); color: var(--green); }
.tag-bad { background: rgba(248, 113, 113, 0.15); color: var(--red); }

.match-ok { color: var(--green); font-weight: 600; }
.match-bad { color: var(--red); font-weight: 600; }

.controls { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
.controls select, .controls input { background: var(--surface); border: 1px solid var(--border); color: var(--text); padding: 6px 10px; border-radius: 6px; font-size: 12px; font-family: inherit; }
.controls label { font-size: 11px; color: var(--text-secondary); display: flex; align-items: center; gap: 6px; }

.bar-row { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; font-size: 11px; font-family: 'JetBrains Mono', monospace; }
.bar-row .label { width: 64px; color: var(--text-secondary); }
.bar-row .bar { flex: 1; height: 14px; background: var(--surface2); border-radius: 3px; overflow: hidden; position: relative; }
.bar-row .bar-fill { height: 100%; background: var(--accent); }
.bar-row .bar-fill.green { background: var(--green); }
.bar-row .bar-fill.red { background: var(--red); }
.bar-row .bar-fill.yellow { background: var(--yellow); }
.bar-row .val { width: 80px; text-align: right; }

svg { display: block; }
.line { fill: none; stroke-width: 2; }
.line-btc { stroke: #f7931a; }
.line-eth { stroke: #627eea; }
.line-sol { stroke: #14f195; }
.line-ALL { stroke: var(--text-secondary); }
.dot { stroke-width: 2; fill: var(--surface); }
.axis { stroke: var(--border); stroke-width: 1; }
.axis-text { fill: var(--text-dim); font-size: 10px; font-family: 'JetBrains Mono', monospace; }
.legend { display: flex; gap: 12px; font-size: 11px; margin-top: 8px; flex-wrap: wrap; }
.legend-dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 4px; vertical-align: middle; }

.section-summary { background: var(--surface2); border-left: 3px solid var(--accent); padding: 12px 16px; margin: 12px 0; border-radius: 4px; font-size: 13px; line-height: 1.5; }
.section-summary strong { color: var(--text); }

#trades-table-wrap { max-height: 600px; overflow-y: auto; border: 1px solid var(--border); border-radius: 8px; }
#trades-table { font-size: 11px; }
#trades-table th { cursor: pointer; user-select: none; }
#trades-table th:hover { background: var(--surface); }
.pos { color: var(--green); }
.neg { color: var(--red); }
.dim { color: var(--text-dim); }
</style>
</head>
<body>
<div class="container">
<header>
  <h1>Polymarket Realfills Dashboard <small>E1 — sig_ret5m_q20 × hedge-hold rev_bp=5</small></h1>
  <button class="theme-toggle" onclick="toggleTheme()">☀ Light</button>
</header>

<!-- Headline KPIs -->
<div class="grid grid-4">
  <div class="card">
    <div class="kpi-label">Baseline v2 (per-share)</div>
    <div class="kpi-value kpi-good" id="kpi-base-roi">—</div>
    <div class="kpi-sub">ALL × 15m × q20 — matches handoff</div>
  </div>
  <div class="card">
    <div class="kpi-label">Realistic $1 stake</div>
    <div class="kpi-value kpi-good" id="kpi-real-roi">—</div>
    <div class="kpi-sub">Same cell, book-walked</div>
  </div>
  <div class="card">
    <div class="kpi-label">Realistic $250 stake</div>
    <div class="kpi-value" id="kpi-real-roi-250">—</div>
    <div class="kpi-sub">ROI/capital, BTC×ALL</div>
  </div>
  <div class="card">
    <div class="kpi-label">Trades dumped</div>
    <div class="kpi-value" id="kpi-trade-count">—</div>
    <div class="kpi-sub">ALL × ALL × 4 stakes</div>
  </div>
</div>

<h2>1. Validation — Baseline v2 (single-price level-0) vs Realistic $1 stake (book-walked)</h2>
<div class="section-summary">
  Baseline v2 cells use 1-share entry + 1-share hedge at level-0 prices (matches <code>polymarket_revbp_floor_sweep.py</code>).
  Realistic cells use $1 notional book-walked through top-10 levels.
  <strong>The handoff's baseline (n=289 / hit 75.8% / ROI +20.39% at ALL×15m) is reproduced by baseline_v2 below.</strong>
  Note: realistic n is lower because some markets lack orderbook snapshots at bucket=0 in book_depth_v3.
</div>
<div class="card" style="overflow-x:auto">
<table id="validation-table">
  <thead>
    <tr>
      <th>Asset</th>
      <th>TF</th>
      <th class="tag-base">Base n</th>
      <th class="tag-base">Base hit</th>
      <th class="tag-base">Base PnL/trade</th>
      <th class="tag-base">Base ROI</th>
      <th class="tag-real">Real n</th>
      <th class="tag-real">Real hit</th>
      <th class="tag-real">Real PnL/trade</th>
      <th class="tag-real">Real ROI(v2)</th>
      <th class="tag-real">Real ROI(cap)</th>
      <th>n delta</th>
    </tr>
  </thead>
  <tbody></tbody>
</table>
</div>

<h2>2. Capacity Ladder — ROI per trade as stake grows (per asset, TF=ALL)</h2>
<div class="section-summary">
  <strong>BTC scales clean to $250</strong> (top-of-book often holds, walks 1-3 levels).
  <strong>ETH degrades from ~$100</strong> (walks 4-6 levels, 16% underfill at $250).
  <strong>SOL caps around $25-50</strong> (76% of trades skip at $250 due to thin books).
  Numbers below are <em>ROI on capital deployed</em> per trade.
</div>
<div class="grid grid-3">
  <div class="card">
    <h3>ROI(capital) vs stake</h3>
    <div id="chart-roi"></div>
    <div class="legend">
      <span><span class="legend-dot" style="background:#f7931a"></span>BTC</span>
      <span><span class="legend-dot" style="background:#627eea"></span>ETH</span>
      <span><span class="legend-dot" style="background:#14f195"></span>SOL</span>
      <span><span class="legend-dot" style="background:#a0a0b0"></span>ALL</span>
    </div>
  </div>
  <div class="card">
    <h3>Hit rate vs stake</h3>
    <div id="chart-hit"></div>
  </div>
  <div class="card">
    <h3>Trades surviving (n) vs stake</h3>
    <div id="chart-n"></div>
  </div>
</div>

<h2>3. Per-asset capacity table (TF=ALL)</h2>
<div class="card" style="overflow-x:auto">
<table id="capacity-table">
  <thead>
    <tr>
      <th>Asset</th>
      <th>$1</th>
      <th>$25</th>
      <th>$100</th>
      <th>$250</th>
      <th>Haircut $1→$250</th>
      <th>Thin@$250</th>
    </tr>
  </thead>
  <tbody></tbody>
</table>
</div>

<h2>4. PnL distribution by stake (ALL × ALL)</h2>
<div class="card">
  <div class="controls">
    <label>Stake:
      <select id="dist-stake-sel">
        <option value="1">$1</option>
        <option value="25">$25</option>
        <option value="100" selected>$100</option>
        <option value="250">$250</option>
      </select>
    </label>
    <label>Mode:
      <select id="dist-mode-sel">
        <option value="real_pnl" selected>Realistic PnL</option>
        <option value="base_pnl">Baseline PnL</option>
        <option value="delta_pnl_pct">Delta % vs baseline</option>
      </select>
    </label>
  </div>
  <div id="chart-dist"></div>
</div>

<h2>5. Trade explorer — every trade, every detail</h2>
<div class="section-summary">
  3,751 trade rows (1014 unique markets × up to 4 stakes that filled).
  Each row shows the same market simulated under baseline (level-0 single-price) and realistic (book-walked).
  Sort by clicking column headers.
</div>
<div class="card">
  <div class="controls">
    <label>Asset:
      <select id="te-asset"><option value="">all</option><option>btc</option><option>eth</option><option>sol</option></select>
    </label>
    <label>TF:
      <select id="te-tf"><option value="">all</option><option>5m</option><option>15m</option></select>
    </label>
    <label>Stake:
      <select id="te-stake">
        <option value="">all</option>
        <option value="1">$1</option>
        <option value="25">$25</option>
        <option value="100">$100</option>
        <option value="250">$250</option>
      </select>
    </label>
    <label>Hedged:
      <select id="te-hedged"><option value="">all</option><option value="true">yes</option><option value="false">no</option></select>
    </label>
    <label>Won:
      <select id="te-won"><option value="">all</option><option value="true">yes</option><option value="false">no</option></select>
    </label>
    <label>Underfilled:
      <select id="te-uf"><option value="">all</option><option value="true">yes</option><option value="false">no</option></select>
    </label>
    <label>Search slug:
      <input type="text" id="te-search" placeholder="btc-updown-15m-..." style="width:240px"/>
    </label>
    <label>Limit:
      <select id="te-limit"><option>50</option><option selected>200</option><option>1000</option><option value="999999">all</option></select>
    </label>
  </div>
  <div id="trades-table-wrap">
    <table id="trades-table">
      <thead>
        <tr>
          <th data-sort="slug">slug</th>
          <th data-sort="asset">a</th>
          <th data-sort="tf">tf</th>
          <th data-sort="sig">sig</th>
          <th data-sort="outcome_up">out</th>
          <th data-sort="stake">$</th>
          <th data-sort="base_pnl">base PnL</th>
          <th data-sort="real_pnl">real PnL</th>
          <th data-sort="delta_pnl_pct">Δ%</th>
          <th data-sort="base_entry_p">base ent</th>
          <th data-sort="real_vwap_e">real ent</th>
          <th data-sort="real_lvls_e">lvls e</th>
          <th data-sort="real_vwap_h">real hed</th>
          <th data-sort="real_lvls_h">lvls h</th>
          <th data-sort="real_hedged">hed?</th>
          <th data-sort="real_under_e">u e</th>
          <th data-sort="real_under_h">u h</th>
          <th data-sort="trigger_bucket">trig</th>
        </tr>
      </thead>
      <tbody></tbody>
    </table>
  </div>
  <div style="font-size:11px; color: var(--text-secondary); margin-top:8px" id="te-counter"></div>
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
function fmtPct(v) { return v === null || v === undefined ? '—' : v.toFixed(2)+'%'; }
function fmtPctF(v) { return v === null || v === undefined ? '—' : (v*100).toFixed(1)+'%'; }
function fmtMoney(v) {
  if (v === null || v === undefined || !isFinite(v)) return '—';
  const sign = v >= 0 ? '+' : '';
  if (Math.abs(v) >= 1) return '$'+sign+v.toFixed(2);
  return '$'+sign+v.toFixed(4);
}
function pnclass(v) { return v > 0 ? 'pos' : (v < 0 ? 'neg' : 'dim'); }

// ---- Headline KPIs ----
function setKPIs() {
  const v = DATA.validation.find(r => r.asset==='ALL' && r.tf==='15m');
  if (v) {
    document.getElementById('kpi-base-roi').textContent = '+' + v.base_roi.toFixed(2) + '%';
    document.getElementById('kpi-base-roi').nextElementSibling.textContent =
      `n=${v.base_n} · hit ${(v.base_hit*100).toFixed(1)}% · pnl/trade ${fmtMoney(v.base_pnl)}`;
    document.getElementById('kpi-real-roi').textContent = v.real_roi_v2 ? '+' + v.real_roi_v2.toFixed(2) + '%' : '—';
    document.getElementById('kpi-real-roi').nextElementSibling.textContent =
      `n=${v.real_n} · hit ${(v.real_hit*100).toFixed(1)}% · ROI(cap) ${v.real_roi_cap.toFixed(2)}%`;
  }
  const btcAll = DATA.ladder.find(l => l.asset==='btc' && l.tf==='ALL');
  const r250 = btcAll && btcAll.points.find(p => p.stake===250);
  if (r250) {
    document.getElementById('kpi-real-roi-250').textContent = r250.roi_cap.toFixed(2)+'%';
    document.getElementById('kpi-real-roi-250').nextElementSibling.textContent =
      `n=${r250.n} · hit ${(r250.hit*100).toFixed(1)}% · pnl/trade ${fmtMoney(r250.pnl_mean)}`;
  }
  document.getElementById('kpi-trade-count').textContent = DATA.trades.length.toLocaleString();
}

// ---- Validation table ----
function buildValidation() {
  const tb = document.querySelector('#validation-table tbody');
  tb.innerHTML = '';
  for (const r of DATA.validation) {
    const tr = document.createElement('tr');
    const matchHit = (r.real_hit !== null && Math.abs(r.real_hit - r.base_hit) < 0.05) ? 'match-ok' : 'match-bad';
    const ndelta = r.real_n - r.base_n;
    tr.innerHTML = `
      <td><span class="tag tag-asset-${r.asset}">${r.asset}</span></td>
      <td>${r.tf}</td>
      <td>${r.base_n}</td>
      <td>${(r.base_hit*100).toFixed(1)}%</td>
      <td>${fmtMoney(r.base_pnl)}</td>
      <td class="kpi-good">+${r.base_roi.toFixed(2)}%</td>
      <td>${r.real_n}</td>
      <td class="${matchHit}">${r.real_hit !== null ? (r.real_hit*100).toFixed(1)+'%' : '—'}</td>
      <td>${fmtMoney(r.real_pnl)}</td>
      <td class="kpi-good">${r.real_roi_v2 !== null ? '+'+r.real_roi_v2.toFixed(2)+'%' : '—'}</td>
      <td>${r.real_roi_cap !== null ? '+'+r.real_roi_cap.toFixed(2)+'%' : '—'}</td>
      <td class="${ndelta < 0 ? 'neg' : 'dim'}">${ndelta >= 0 ? '+' : ''}${ndelta}</td>
    `;
    tb.appendChild(tr);
  }
}

// ---- Capacity table ----
function buildCapacity() {
  const tb = document.querySelector('#capacity-table tbody');
  tb.innerHTML = '';
  const allTf = DATA.ladder.filter(l => l.tf === 'ALL');
  for (const l of allTf) {
    const p = {};
    l.points.forEach(pt => p[pt.stake] = pt);
    const haircut = (p[1] && p[250]) ? (p[1].roi_cap - p[250].roi_cap) : null;
    const tr = document.createElement('tr');
    const totalAt250 = p[250] ? (p[250].n + p[250].thin) : 0;
    const thinPct = totalAt250 > 0 ? (p[250].thin / totalAt250 * 100) : 0;
    tr.innerHTML = `
      <td><span class="tag tag-asset-${l.asset}">${l.asset}</span></td>
      <td>${p[1] ? p[1].roi_cap.toFixed(2)+'%' : '—'}</td>
      <td>${p[25] ? p[25].roi_cap.toFixed(2)+'%' : '—'}</td>
      <td>${p[100] ? p[100].roi_cap.toFixed(2)+'%' : '—'}</td>
      <td>${p[250] ? p[250].roi_cap.toFixed(2)+'%' : '—'}</td>
      <td class="${haircut !== null && haircut > 10 ? 'neg' : (haircut > 5 ? '' : 'pos')}">${haircut !== null ? '−'+haircut.toFixed(2)+'pp' : '—'}</td>
      <td class="${thinPct > 30 ? 'neg' : (thinPct > 10 ? 'kpi-warn' : 'dim')}">${thinPct.toFixed(1)}%</td>
    `;
    tb.appendChild(tr);
  }
}

// ---- Line chart helper ----
function lineChart(containerId, keyFn, yFmt='%', yMin=null, yMax=null) {
  const W = 380, H = 220, M = {t:10, r:10, b:30, l:50};
  const allTf = DATA.ladder.filter(l => l.tf === 'ALL');
  const stakes = [1, 25, 100, 250];
  let yVals = [];
  allTf.forEach(l => l.points.forEach(p => yVals.push(keyFn(p))));
  const yMin0 = yMin !== null ? yMin : Math.min(0, ...yVals);
  const yMax0 = yMax !== null ? yMax : Math.max(...yVals);
  const xScale = i => M.l + (i/(stakes.length-1)) * (W - M.l - M.r);
  const yScale = v => H - M.b - ((v - yMin0)/(yMax0 - yMin0)) * (H - M.t - M.b);

  let svg = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">`;
  // axes
  svg += `<line x1="${M.l}" y1="${H-M.b}" x2="${W-M.r}" y2="${H-M.b}" class="axis"/>`;
  svg += `<line x1="${M.l}" y1="${M.t}" x2="${M.l}" y2="${H-M.b}" class="axis"/>`;
  // y ticks
  for (let i = 0; i <= 4; i++) {
    const y = M.t + i * (H - M.t - M.b) / 4;
    const v = yMax0 - i * (yMax0 - yMin0) / 4;
    svg += `<line x1="${M.l-3}" y1="${y}" x2="${M.l}" y2="${y}" class="axis"/>`;
    svg += `<text x="${M.l-6}" y="${y+3}" text-anchor="end" class="axis-text">${v.toFixed(yFmt==='%'?0:0)}${yFmt}</text>`;
  }
  // x labels
  stakes.forEach((s, i) => {
    svg += `<text x="${xScale(i)}" y="${H-M.b+14}" text-anchor="middle" class="axis-text">$${s}</text>`;
  });
  // lines per asset
  allTf.forEach(l => {
    const pts = stakes.map(s => l.points.find(p => p.stake === s));
    if (pts.some(p => !p)) return;
    const path = pts.map((p, i) => `${i===0?'M':'L'}${xScale(i)},${yScale(keyFn(p))}`).join(' ');
    svg += `<path d="${path}" class="line line-${l.asset}"/>`;
    pts.forEach((p, i) => {
      svg += `<circle cx="${xScale(i)}" cy="${yScale(keyFn(p))}" r="3" class="dot line-${l.asset}" style="stroke:var(--${l.asset==='btc'?'':''})"/>`;
    });
  });
  svg += '</svg>';
  document.getElementById(containerId).innerHTML = svg;
}

// ---- Distribution chart ----
function distChart() {
  const stake = parseFloat(document.getElementById('dist-stake-sel').value);
  const mode = document.getElementById('dist-mode-sel').value;
  const data = DATA.trades.filter(t => t.stake === stake);
  const vals = data.map(t => t[mode]).filter(v => v !== null && isFinite(v));
  if (vals.length === 0) { document.getElementById('chart-dist').innerHTML = '<div style="color:var(--text-dim)">no data</div>'; return; }
  vals.sort((a,b) => a-b);
  const lo = vals[Math.floor(vals.length*0.02)];
  const hi = vals[Math.floor(vals.length*0.98)];
  const nBins = 40;
  const binW = (hi - lo) / nBins;
  const bins = new Array(nBins).fill(0);
  vals.forEach(v => {
    const i = Math.min(nBins-1, Math.max(0, Math.floor((v - lo)/binW)));
    bins[i]++;
  });
  const W = 1200, H = 260, M = {t:10,r:20,b:30,l:50};
  const maxB = Math.max(...bins);
  let svg = `<svg width="100%" height="${H}" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">`;
  svg += `<line x1="${M.l}" y1="${H-M.b}" x2="${W-M.r}" y2="${H-M.b}" class="axis"/>`;
  svg += `<line x1="${M.l}" y1="${M.t}" x2="${M.l}" y2="${H-M.b}" class="axis"/>`;
  // zero line if 0 in range
  if (lo <= 0 && hi >= 0) {
    const x0 = M.l + (-lo / (hi - lo)) * (W - M.l - M.r);
    svg += `<line x1="${x0}" y1="${M.t}" x2="${x0}" y2="${H-M.b}" stroke="var(--text-dim)" stroke-dasharray="2,2"/>`;
  }
  bins.forEach((c, i) => {
    const x = M.l + (i / nBins) * (W - M.l - M.r);
    const w = (W - M.l - M.r) / nBins - 1;
    const h = (c / maxB) * (H - M.t - M.b);
    const center = lo + (i+0.5)*binW;
    const color = center > 0 ? 'var(--green)' : 'var(--red)';
    svg += `<rect x="${x}" y="${H-M.b-h}" width="${w}" height="${h}" fill="${color}" opacity="0.7"/>`;
  });
  // x labels
  for (let i = 0; i <= 4; i++) {
    const v = lo + i*(hi-lo)/4;
    const x = M.l + i*(W-M.l-M.r)/4;
    svg += `<text x="${x}" y="${H-M.b+14}" text-anchor="middle" class="axis-text">${v.toFixed(2)}${mode==='delta_pnl_pct'?'%':''}</text>`;
  }
  // y label max
  svg += `<text x="${M.l-6}" y="${M.t+10}" text-anchor="end" class="axis-text">${maxB}</text>`;
  svg += `<text x="${M.l-6}" y="${H-M.b}" text-anchor="end" class="axis-text">0</text>`;
  // stats
  const mean = vals.reduce((a,b)=>a+b,0)/vals.length;
  const median = vals[Math.floor(vals.length/2)];
  svg += `<text x="${W-M.r-8}" y="${M.t+12}" text-anchor="end" class="axis-text">n=${vals.length} · mean ${mean.toFixed(3)} · median ${median.toFixed(3)}</text>`;
  svg += '</svg>';
  document.getElementById('chart-dist').innerHTML = svg;
}

// ---- Trade explorer ----
let teSort = {col: 'delta_pnl_pct', dir: 1};
function applyFilters() {
  const a = document.getElementById('te-asset').value;
  const tf = document.getElementById('te-tf').value;
  const stk = document.getElementById('te-stake').value;
  const hd = document.getElementById('te-hedged').value;
  const wn = document.getElementById('te-won').value;
  const uf = document.getElementById('te-uf').value;
  const search = document.getElementById('te-search').value.toLowerCase();
  const lim = parseInt(document.getElementById('te-limit').value);
  let rows = DATA.trades.filter(t => {
    if (a && t.asset !== a) return false;
    if (tf && t.tf !== tf) return false;
    if (stk && t.stake !== parseFloat(stk)) return false;
    if (hd && (t.real_hedged ? 'true':'false') !== hd) return false;
    if (wn && (t.sig_won ? 'true':'false') !== wn) return false;
    if (uf && (t.real_under_e || t.real_under_h ? 'true':'false') !== uf) return false;
    if (search && !t.slug.toLowerCase().includes(search)) return false;
    return true;
  });
  rows.sort((a,b) => {
    const va = a[teSort.col], vb = b[teSort.col];
    if (va === null || va === undefined) return 1;
    if (vb === null || vb === undefined) return -1;
    if (typeof va === 'string') return va.localeCompare(vb) * teSort.dir;
    return (va - vb) * teSort.dir;
  });
  document.getElementById('te-counter').textContent =
    `Showing ${Math.min(lim, rows.length).toLocaleString()} of ${rows.length.toLocaleString()} matching trades (sort: ${teSort.col} ${teSort.dir>0?'↑':'↓'})`;
  rows = rows.slice(0, lim);
  const tb = document.querySelector('#trades-table tbody');
  tb.innerHTML = rows.map(t => `
    <tr>
      <td style="text-align:left;font-size:10px">${t.slug}</td>
      <td><span class="tag tag-asset-${t.asset}">${t.asset}</span></td>
      <td>${t.tf}</td>
      <td>${t.sig}</td>
      <td>${t.outcome_up}</td>
      <td>$${t.stake}</td>
      <td class="${pnclass(t.base_pnl)}">${fmtMoney(t.base_pnl)}</td>
      <td class="${pnclass(t.real_pnl)}">${fmtMoney(t.real_pnl)}</td>
      <td class="${pnclass(t.delta_pnl_pct)}">${t.delta_pnl_pct ? t.delta_pnl_pct.toFixed(1)+'%' : '—'}</td>
      <td>${fmt(t.base_entry_p, 4)}</td>
      <td>${fmt(t.real_vwap_e, 4)}</td>
      <td>${t.real_lvls_e}</td>
      <td>${t.real_vwap_h !== null ? fmt(t.real_vwap_h, 4) : '—'}</td>
      <td>${t.real_lvls_h}</td>
      <td>${t.real_hedged ? '✓' : ''}</td>
      <td class="${t.real_under_e ? 'neg' : 'dim'}">${t.real_under_e ? '!' : ''}</td>
      <td class="${t.real_under_h ? 'neg' : 'dim'}">${t.real_under_h ? '!' : ''}</td>
      <td class="dim">${t.trigger_bucket !== null ? t.trigger_bucket : '—'}</td>
    </tr>
  `).join('');
}

document.querySelectorAll('#trades-table th').forEach(th => {
  th.addEventListener('click', () => {
    const col = th.dataset.sort;
    if (teSort.col === col) teSort.dir = -teSort.dir;
    else { teSort.col = col; teSort.dir = -1; }
    applyFilters();
  });
});
['te-asset','te-tf','te-stake','te-hedged','te-won','te-uf','te-search','te-limit'].forEach(id => {
  document.getElementById(id).addEventListener('input', applyFilters);
  document.getElementById(id).addEventListener('change', applyFilters);
});
['dist-stake-sel','dist-mode-sel'].forEach(id => {
  document.getElementById(id).addEventListener('change', distChart);
});

setKPIs();
buildValidation();
buildCapacity();
lineChart('chart-roi', p => p.roi_cap, '%');
lineChart('chart-hit', p => p.hit*100, '%', 50, 75);
lineChart('chart-n',   p => p.n, '');
distChart();
applyFilters();
</script>
</body>
</html>
"""
    html = html.replace("__PAYLOAD__", payload_json)
    return html


def main():
    cells, trades = load_data()
    print(f"Loaded {len(cells)} cells, {len(trades)} trade rows")
    html = build_html(cells, trades)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    size_mb = OUT.stat().st_size / 1024 / 1024
    print(f"Wrote {OUT} ({size_mb:.2f} MB)")


if __name__ == "__main__":
    main()
