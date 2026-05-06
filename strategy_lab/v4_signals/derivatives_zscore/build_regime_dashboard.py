"""Self-contained dashboard for the BTC Trend-Start Regime Detector findings.

Reads:  strategy_lab/reports/derivatives_zscore/regime_detector/*.csv
        strategy_lab/reports/derivatives_zscore/regime_detector/06_pine_detector.txt

Writes: strategy_lab/reports/derivatives_zscore/regime_detector/DASHBOARD.html
"""
from __future__ import annotations
from pathlib import Path
import html
import math
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
RDIR = ROOT / "strategy_lab" / "reports" / "derivatives_zscore" / "regime_detector"
OUT = RDIR / "DASHBOARD.html"


def fmt_num(v, d=2, sign=False):
    try:
        f = float(v)
        if pd.isna(f) or not math.isfinite(f):
            return "–"
        return f"{f:{'+' if sign else ''}.{d}f}"
    except Exception:
        return "–"


def fmt_pct(v, d=1, sign=False):
    try:
        f = float(v)
        if pd.isna(f) or not math.isfinite(f):
            return "–"
        return f"{f*100:{'+' if sign else ''}.{d}f}%"
    except Exception:
        return "–"


def color_by_corr(c, max_abs=0.10):
    """Background color for a correlation cell."""
    try:
        v = float(c)
        if pd.isna(v) or not math.isfinite(v):
            return "#1a1f26"
    except Exception:
        return "#1a1f26"
    a = min(1.0, abs(v) / max_abs)
    if v >= 0:
        return f"rgba(31,157,85,{a:.2f})"
    return f"rgba(194,58,58,{a:.2f})"


def color_by_mean(v, max_abs=0.5):
    """Background for sequencing/zone-mean cell."""
    try:
        f = float(v)
        if pd.isna(f) or not math.isfinite(f):
            return "#1a1f26"
    except Exception:
        return "#1a1f26"
    a = min(1.0, abs(f) / max_abs)
    if f >= 0:
        return f"rgba(31,157,85,{a:.2f})"
    return f"rgba(194,58,58,{a:.2f})"


def render_label_sweep(df: pd.DataFrame) -> str:
    rows = []
    for _, r in df.iterrows():
        bull_pct = float(r["bull_rate_pct"])
        bear_pct = float(r["bear_rate_pct"])
        is_chosen = (r["X"] == 0.03 and r["Y"] == 24 and r["Z"] == 0.010)
        cls = ' class="chosen"' if is_chosen else ""
        rows.append(
            f'<tr{cls}><td>{r["X"]*100:.0f}%</td><td>{int(r["Y"])}h</td>'
            f'<td>±{r["Z"]*100:.1f}%</td>'
            f'<td>{int(r["n_bull"])}</td><td>{int(r["n_bear"])}</td>'
            f'<td>{bull_pct:.2f}%</td><td>{bear_pct:.2f}%</td></tr>'
        )
    return (
        '<table class="data"><thead><tr>'
        '<th>X (move)</th><th>Y (window)</th><th>Z (max counter)</th>'
        '<th>Bull events</th><th>Bear events</th>'
        '<th>Bull rate</th><th>Bear rate</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table>'
        '<div class="note">Selected definition (highlighted): X=3%, Y=24h, Z=±1.0%.</div>'
    )


def render_correlations(df: pd.DataFrame) -> str:
    """Pivot indicator × horizon, color cells by sign+magnitude."""
    pivot = df.pivot_table(index="indicator", columns="horizon_h", values="pearson_corr")
    pivot["abs_max"] = pivot.abs().max(axis=1)
    pivot = pivot.sort_values("abs_max", ascending=False).drop(columns=["abs_max"])
    horizons = sorted(c for c in pivot.columns if isinstance(c, (int, float)))

    head = "<tr><th>Indicator</th>" + "".join(f"<th>{h}h</th>" for h in horizons) + "</tr>"
    body = []
    for ind, row in pivot.iterrows():
        cells = []
        for h in horizons:
            v = row[h]
            bg = color_by_corr(v, max_abs=0.10)
            cells.append(f'<td style="background:{bg}" title="{ind} @ {h}h">{fmt_num(v, 3, sign=True)}</td>')
        body.append(f"<tr><td><code>{html.escape(ind)}</code></td>{''.join(cells)}</tr>")
    return f'<table class="heatmap"><thead>{head}</thead><tbody>{"".join(body)}</tbody></table>'


def render_zone_means(df: pd.DataFrame) -> str:
    pivot = df.pivot_table(index="indicator", columns="zone", values="mean_fwd_ret_pct")
    cols = ["<-2σ", "-2 to -1", "-1 to +1", "+1 to +2", ">+2σ"]
    cols = [c for c in cols if c in pivot.columns]
    pivot = pivot[cols]

    head = "<tr><th>Indicator</th>" + "".join(f"<th>{c}</th>" for c in cols) + "</tr>"
    body = []
    for ind, row in pivot.iterrows():
        cells = []
        for c in cols:
            v = row[c]
            bg = color_by_mean(v, max_abs=0.30)
            cells.append(
                f'<td style="background:{bg}" title="zone {c}">{fmt_num(v, 2, sign=True)}%</td>'
            )
        body.append(f"<tr><td><code>{html.escape(ind)}</code></td>{''.join(cells)}</tr>")
    return f'<table class="heatmap"><thead>{head}</thead><tbody>{"".join(body)}</tbody></table>'


def render_sequencing(df: pd.DataFrame, label: str) -> str:
    sub = df[df["label"] == label]
    pivot = sub.pivot_table(index="indicator", columns="offset_h", values="mean")
    # filter inf / nan rows
    finite_mask = pivot.replace([np.inf, -np.inf], np.nan).notna().all(axis=1)
    pivot = pivot[finite_mask]
    pivot["abs_at_zero"] = pivot.get(0, pd.Series(0, index=pivot.index)).abs()
    pivot = pivot.sort_values("abs_at_zero", ascending=False).drop(columns=["abs_at_zero"])
    offsets = sorted(pivot.columns)

    head = "<tr><th>Indicator</th>" + "".join(f"<th>{o:+d}h</th>" for o in offsets) + "</tr>"
    body = []
    for ind, row in pivot.iterrows():
        cells = []
        for o in offsets:
            v = row[o]
            # use a different scale for rsi_14 (centered around 50)
            if ind == "rsi_14":
                bg = color_by_mean(float(v) - 50, max_abs=10)
                cells.append(f'<td style="background:{bg}">{fmt_num(v, 1)}</td>')
            else:
                bg = color_by_mean(v, max_abs=0.5)
                cells.append(f'<td style="background:{bg}">{fmt_num(v, 3, sign=True)}</td>')
        body.append(f"<tr><td><code>{html.escape(ind)}</code></td>{''.join(cells)}</tr>")

    return f'<table class="heatmap"><thead>{head}</thead><tbody>{"".join(body)}</tbody></table>'


def render_macro_split(df: pd.DataFrame) -> str:
    """Show indicator × regime, flagging sign flips in red border."""
    # pivot: rows=indicator, cols=(regime, horizon)
    horizons = sorted(df["horizon_h"].unique())
    regimes = sorted(df["regime"].unique())
    pivot = df.pivot_table(index="indicator", columns=["regime", "horizon_h"],
                            values="pearson_corr")
    indicators = pivot.index

    # Header: regime spans, then horizons
    head1 = "<tr><th rowspan='2'>Indicator</th>"
    for reg in regimes:
        head1 += f"<th colspan='{len(horizons)}'>{html.escape(reg)}</th>"
    head1 += "<th rowspan='2'>Sign flip?</th></tr>"
    head2 = "<tr>" + "".join(f"<th>{h}h</th>" for _ in regimes for h in horizons) + "</tr>"

    body = []
    for ind in indicators:
        cells = []
        signs = []
        for reg in regimes:
            for h in horizons:
                v = pivot.loc[ind].get((reg, h), np.nan)
                bg = color_by_corr(v, max_abs=0.30)
                cells.append(f'<td style="background:{bg}">{fmt_num(v, 3, sign=True)}</td>')
                if pd.notna(v) and math.isfinite(float(v)) and abs(float(v)) > 0.02:
                    signs.append(1 if float(v) > 0 else -1)
        flip = (len(set(signs)) > 1) if signs else False
        flag = '<span class="flip">⚠ flips</span>' if flip else '<span class="stable">stable</span>'
        body.append(f"<tr><td><code>{html.escape(ind)}</code></td>{''.join(cells)}<td>{flag}</td></tr>")

    return f'<table class="heatmap"><thead>{head1}{head2}</thead><tbody>{"".join(body)}</tbody></table>'


def build():
    sweep = pd.read_csv(RDIR / "01_label_sweep.csv")
    corrs = pd.read_csv(RDIR / "02_correlations.csv")
    zones = pd.read_csv(RDIR / "03_zone_means.csv")
    seq = pd.read_csv(RDIR / "04_sequencing.csv")
    macro = pd.read_csv(RDIR / "05_macro_regime_split.csv")
    pine_path = RDIR / "06_pine_detector.txt"
    pine_code = pine_path.read_text(encoding="utf-8") if pine_path.exists() else ""

    # Tiles
    n_bull = int(sweep[(sweep["X"] == 0.03) & (sweep["Y"] == 24) & (sweep["Z"] == 0.010)]["n_bull"].iloc[0])
    n_bear = int(sweep[(sweep["X"] == 0.03) & (sweep["Y"] == 24) & (sweep["Z"] == 0.010)]["n_bear"].iloc[0])
    top_corr = corrs.assign(abs_corr=corrs["pearson_corr"].abs()).nlargest(1, "abs_corr").iloc[0]

    # Top 5 leading indicators per side (for narrative)
    def top_lead(side: str, top: int = 5):
        sub = seq[(seq["label"] == side) & (seq["offset_h"] == 0)].copy()
        sub = sub[np.isfinite(sub["mean"])]
        sub["abs_mean"] = sub["mean"].abs()
        return sub.sort_values("abs_mean", ascending=False).head(top)

    bull_lead = top_lead("bull")
    bear_lead = top_lead("bear")

    # Macro flip count
    macro_pivot = macro.pivot_table(index="indicator", columns=["regime", "horizon_h"],
                                     values="pearson_corr")
    n_flips = 0
    for ind in macro_pivot.index:
        signs = []
        for col in macro_pivot.columns:
            v = macro_pivot.loc[ind, col]
            if pd.notna(v) and math.isfinite(float(v)) and abs(float(v)) > 0.02:
                signs.append(1 if float(v) > 0 else -1)
        if signs and len(set(signs)) > 1:
            n_flips += 1

    gen_ts = pd.Timestamp.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    # Bull/bear narrative tiles
    bull_lead_html = "".join(
        f'<li><code>{html.escape(r["indicator"])}</code> '
        f'mean={fmt_num(r["mean"], 3, sign=True)}</li>'
        for _, r in bull_lead.iterrows()
    )
    bear_lead_html = "".join(
        f'<li><code>{html.escape(r["indicator"])}</code> '
        f'mean={fmt_num(r["mean"], 3, sign=True)}</li>'
        for _, r in bear_lead.iterrows()
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>BTC Trend-Start Regime Detector · 3y Event Study</title>
<style>
  body {{ background:#0b1016; color:#dde3eb; font-family:-apple-system,Segoe UI,Roboto,sans-serif; margin:0; padding:24px; font-size:13px; line-height:1.5; }}
  h1 {{ color:#eee; font-size:22px; margin:0 0 4px 0; }}
  h2 {{ color:#9dcefa; font-size:15px; margin-top:30px; border-bottom:1px solid #2a3342; padding-bottom:4px; text-transform:uppercase; letter-spacing:0.6px; }}
  h3 {{ color:#cfd6de; font-size:13px; margin:16px 0 6px 0; }}
  .meta {{ color:#7d8796; font-size:11px; }}
  code {{ background:#1a212c; color:#e0b280; padding:1px 5px; border-radius:2px; font-size:12px; }}

  .tiles {{ display:flex; gap:14px; margin:20px 0; flex-wrap:wrap; }}
  .tile {{ background:#151b24; border:1px solid #2a3342; border-radius:5px; padding:12px 18px; min-width:140px; }}
  .tile .val {{ font-size:22px; color:#fff; font-weight:600; }}
  .tile .lab {{ font-size:10px; color:#7d8796; text-transform:uppercase; letter-spacing:0.5px; }}

  .columns {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap:18px; }}
  .panel {{ background:#0e131a; border:1px solid #1d242f; border-radius:6px; padding:14px 18px; }}
  .panel h3 {{ margin-top:0; }}

  table {{ border-collapse:collapse; width:100%; font-size:11px; margin-top:6px; }}
  table.data th, table.data td {{ padding:5px 8px; border-bottom:1px solid #1d242f; text-align:right; }}
  table.data th {{ background:#141a23; color:#9aa3b0; font-weight:600; }}
  table.data td:first-child, table.data th:first-child {{ text-align:left; }}
  table.data tr.chosen td {{ background:rgba(31,157,85,0.20); color:#fff; font-weight:600; }}

  table.heatmap {{ font-size:10px; }}
  table.heatmap th {{ background:#141a23; color:#9aa3b0; padding:4px 6px; font-weight:600; text-align:center; }}
  table.heatmap td {{ padding:3px 6px; text-align:right; color:#dde3eb; border-bottom:1px solid #1a202a; }}
  table.heatmap td:first-child {{ text-align:left; }}

  .note {{ color:#7d8796; font-size:10px; margin-top:6px; font-style:italic; }}

  pre.pine {{ background:#0a0e14; border:1px solid #1d242f; border-radius:5px; padding:12px; font-size:11px; color:#cfd6de; overflow-x:auto; max-height:600px; }}

  .lead-list {{ list-style:none; padding:0; margin:6px 0; font-size:12px; }}
  .lead-list li {{ padding:3px 0; border-bottom:1px solid #1d242f; }}
  .lead-list code {{ color:#9dcefa; }}

  .flip {{ color:#d85a5a; font-weight:600; font-size:10px; }}
  .stable {{ color:#7d8796; font-size:10px; }}
  .pos {{ color:#4ac268; }}
  .neg {{ color:#d85a5a; }}

  .playbook {{ background:#0a0e14; border-left:3px solid #2d6cb0; padding:12px 16px; margin:14px 0; font-size:12px; }}
  .playbook strong {{ color:#9dcefa; }}

  footer {{ color:#555; font-size:10px; margin-top:40px; border-top:1px solid #1d242f; padding-top:10px; }}
</style>
</head>
<body>

  <h1>BTC Trend-Start Regime Detector · 3y Event Study</h1>
  <div class="meta">Generated {gen_ts} · Window 2023-05-01 → 2026-04-29 · 5,160 hourly bars · BTCUSDT</div>

  <div class="tiles">
    <div class="tile"><div class="val">{n_bull:,}</div><div class="lab">Bull events</div></div>
    <div class="tile"><div class="val">{n_bear:,}</div><div class="lab">Bear events</div></div>
    <div class="tile"><div class="val">3% / 24h / ±1%</div><div class="lab">Selected label</div></div>
    <div class="tile"><div class="val">{fmt_num(top_corr['pearson_corr'], 3, sign=True)}</div><div class="lab">Top corr ({html.escape(top_corr['indicator'])} @ {int(top_corr['horizon_h'])}h)</div></div>
    <div class="tile"><div class="val" style="color:#d85a5a">{n_flips}</div><div class="lab">Indicators that flip sign across regimes</div></div>
  </div>

  <h2>The Playbook — Average Event Sequence</h2>
  <div class="playbook">
    <strong>Bull start (avg 24h before move):</strong>
    <code>cross_institutional_lead</code> rises (smart money in stables) →
    <code>oilsr</code> rises (OI conviction builds) →
    <code>z_oi_silent</code> peaks ~4h before (silent accumulation) →
    <code>brigalS</code> &amp; <code>z_lsr</code> collapse last 12h (retail capitulates) →
    PRICE MOVES UP.
  </div>
  <div class="playbook" style="border-left-color:#c23a3a">
    <strong>Bear start (avg 24h before move):</strong>
    <code>cross_institutional_lead</code> jumps (+0.19 → +0.54 — distribution) →
    <code>oilsr</code> rolls over →
    <code>z_lsr</code> &amp; <code>brigalS</code> rise (retail piling in long) →
    <code>z_top_lsr_count</code> climbs (top traders adding shorts) →
    PRICE MOVES DOWN.
  </div>

  <div class="columns">
    <div class="panel">
      <h3>🐂 Top 5 Bull-Side Leading Indicators (mean state @ event)</h3>
      <ul class="lead-list">{bull_lead_html}</ul>
    </div>
    <div class="panel">
      <h3>🐻 Top 5 Bear-Side Leading Indicators (mean state @ event)</h3>
      <ul class="lead-list">{bear_lead_html}</ul>
    </div>
  </div>

  <h2>1 · Label Definition Sweep — Choosing X / Y / Z</h2>
  <p style="color:#9aa3b0;font-size:12px">
    A trend-start = price moves ≥X% within Y hours <em>without ever touching</em> a counter-excursion of ±Z%. Lower Z → cleaner moves but fewer events. We picked the cell that maximizes event count while still excluding choppy markets.
  </p>
  {render_label_sweep(sweep)}

  <h2>2 · Correlation Heatmap — Indicator × Forward Horizon</h2>
  <p style="color:#9aa3b0;font-size:12px">
    Pearson correlation of each indicator with the continuous forward return (no thresholding). Green = positive predictive (higher indicator → higher fwd return), red = negative. Crypto correlations are intrinsically small at 1h scale; <code>z_dom_stables</code> is the strongest single linear predictor.
  </p>
  {render_correlations(corrs)}

  <h2>3 · Zone Means — Conditional Forward Return per ±σ Bucket (24h)</h2>
  <p style="color:#9aa3b0;font-size:12px">
    For each indicator we partition into 5 zones by σ-distance and measure the mean 24h forward return. This reveals NON-linear sweet spots that pure correlation misses.
  </p>
  {render_zone_means(zones)}

  <h2>4 · Sequencing — What Fires When (the "playbook")</h2>
  <p style="color:#9aa3b0;font-size:12px">
    For every confirmed bull/bear trend-start, we snapshot the mean state of each indicator at offsets {{−24h, −12h, −8h, −4h, −2h, −1h, 0}}. Indicators sorted by |mean at offset 0|. Watch how leading indicators (top rows) move BEFORE the event vs lagging indicators that confirm AT the event.
  </p>

  <h3>🐂 Bull trend-start (n={n_bull:,})</h3>
  {render_sequencing(seq, "bull")}

  <h3>🐻 Bear trend-start (n={n_bear:,})</h3>
  {render_sequencing(seq, "bear")}

  <h2>5 · Macro Regime Stability — Where Indicators Flip</h2>
  <p style="color:#9aa3b0;font-size:12px">
    Same correlation metric, partitioned by macro regime: <code>trending_up</code> (BTC &gt; 200d EMA), <code>below_ema50</code> (between EMA200 and EMA50), <code>trending_down</code> (BTC &lt; 200d EMA). If an indicator changes sign across regimes, it cannot be used standalone — it requires the regime filter as a prefix.
  </p>
  {render_macro_split(macro)}
  <div class="note"><strong style="color:#d85a5a">{n_flips} indicators</strong> flip sign across regimes — macro filter is mandatory.</div>

  <h2>6 · Generated Pine Script Detector</h2>
  <p style="color:#9aa3b0;font-size:12px">
    Auto-generated from sequencing thresholds (each trigger fires when an indicator crosses half its observed mean at offset 0). Requires macro filter (<code>trending_up</code> + <code>low_vol_regime</code> for bull; <code>not trending_up</code> for bear) AND ≥3 of 5 leading indicators to align.
  </p>
  <pre class="pine">{html.escape(pine_code)}</pre>

  <h2>7 · Honest Limitations</h2>
  <ul style="font-size:12px">
    <li>Absolute correlations are <strong>small</strong> (max +0.07 for <code>z_dom_stables</code> @ 48h). Typical for noisy 1h crypto data — useful as a multi-factor screen, not a single trigger.</li>
    <li><code>cross_real_money</code> and <code>cross_leverage_heat</code> contain <code>±inf</code> values from upstream stablecoin Δ zero-divides. Excluded from the Pine output. Fix in <code>compute_zscores.py</code> denominators and re-run.</li>
    <li>The label definition (3% / 24h / ±1%) was chosen for a balance between event count and signal cleanliness. Other cells in the sweep would emphasize different trade-offs (more events = noisier; cleaner events = fewer to learn from).</li>
    <li>This is a <strong>linear / contemporaneous</strong> analysis. Non-linear models (gradient boosting, HMM regime classifier) would likely surface stronger structure — left as v2 work.</li>
    <li>BTC only. Same pipeline can be re-run on ETH/SOL panels by swapping the symbol in <code>load_btc()</code>.</li>
  </ul>

  <footer>
    Source: <code>strategy_lab/v4_signals/derivatives_zscore/regime_detector_research.py</code> ·
    CSVs in <code>strategy_lab/reports/derivatives_zscore/regime_detector/</code> ·
    Pine Script: <code>06_pine_detector.txt</code>
  </footer>
</body>
</html>
"""


def main():
    html_out = build()
    OUT.write_text(html_out, encoding="utf-8")
    kb = OUT.stat().st_size / 1024
    print(f"Wrote {OUT} ({kb:.1f} KB)")


if __name__ == "__main__":
    main()
