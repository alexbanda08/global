"""
Simulate the recommended P3_invvol + P5_btc_defensive 60/40 blend to confirm
expected combined metrics. Also builds a leverage-comparison HTML dashboard.

Outputs:
  docs/research/phase5_results/LEVERAGE_COMPARISON.html
  docs/research/phase5_results/leverage_combined_60_40.json
"""
from __future__ import annotations
import json, sys, time
from pathlib import Path
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from strategy_lab.run_leverage_study import (
    SLEEVE_SPECS, PORTFOLIOS, sleeve_data, OUT, BPY,
)
from strategy_lab.run_leverage_study_v2 import simulate_lev
from strategy_lab.run_leverage_audit import (
    build_p3_calmar_opt, build_p7_calmar_opt,
    build_p3_invvol, build_p5_btc_defensive,
    eqw_blend, invvol_blend, verdict_8gate,
)

def full_metrics(eq, label):
    rets = eq.pct_change().dropna()
    mu, sd = float(rets.mean()), float(rets.std())
    sh = (mu/sd)*np.sqrt(BPY) if sd>0 else 0
    pk = eq.cummax(); mdd = float((eq/pk - 1).min())
    yrs = (eq.index[-1] - eq.index[0]).total_seconds() / (365.25*86400)
    total = float(eq.iloc[-1]/eq.iloc[0]-1)
    cagr = (1+total)**(1/max(yrs,1e-6))-1
    cal = cagr/abs(mdd) if mdd!=0 else 0
    # yearly
    yearly = {}
    for yr in sorted(set(eq.index.year)):
        e = eq[eq.index.year == yr]
        if len(e) >= 30:
            yearly[int(yr)] = round(float(e.iloc[-1]/e.iloc[0]-1), 4)
    return {
        "label": label,
        "sharpe": round(sh, 3), "cagr": round(cagr, 4),
        "max_dd": round(mdd, 4), "calmar": round(cal, 3),
        "min_yr": round(min(yearly.values()), 4) if yearly else 0,
        "pos_yrs": sum(1 for r in yearly.values() if r > 0),
        "yearly": yearly,
    }

def main():
    t0 = time.time()
    print("Warming caches...")
    for s in SLEEVE_SPECS:
        sleeve_data(s)

    # Build curves
    print("Building P3_invvol curves...")
    p3_base_curves = build_p3_invvol()
    p3_invvol_eq = invvol_blend(p3_base_curves, window=500)

    print("Building P5_btc_defensive curves...")
    p5_def_curves = build_p5_btc_defensive()
    p5_def_eq = eqw_blend(p5_def_curves)

    # Align and blend 60/40
    idx = p3_invvol_eq.index.intersection(p5_def_eq.index)
    p3_r = p3_invvol_eq.reindex(idx).pct_change().fillna(0)
    p5_r = p5_def_eq.reindex(idx).pct_change().fillna(0)
    combined_r = 0.60 * p3_r + 0.40 * p5_r
    combined_eq = (1 + combined_r).cumprod() * 10_000.0

    m_p3    = full_metrics(p3_invvol_eq, "P3_invvol")
    m_p5    = full_metrics(p5_def_eq,    "P5_btc_defensive")
    m_combo = full_metrics(combined_eq,  "COMBO_60_40")

    # baseline P3 for comparison
    p3_baseline_curves = {}
    for s in PORTFOLIOS["P3"]:
        df, le, se = sleeve_data(s)
        _, eq = simulate_lev(df, le, se, risk_per_trade=0.03, leverage_cap=3.0)
        p3_baseline_curves[s] = eq
    p3_baseline_eq = eqw_blend(p3_baseline_curves)
    m_p3_base = full_metrics(p3_baseline_eq, "P3_baseline")

    # baseline P5
    p5_baseline_curves = {}
    for s in PORTFOLIOS["P5"]:
        df, le, se = sleeve_data(s)
        _, eq = simulate_lev(df, le, se, risk_per_trade=0.03, leverage_cap=3.0)
        p5_baseline_curves[s] = eq
    p5_baseline_eq = eqw_blend(p5_baseline_curves)
    m_p5_base = full_metrics(p5_baseline_eq, "P5_baseline")

    # P3_invvol + P5_baseline (the OLD recommendation)
    idx2 = p3_baseline_eq.index.intersection(p5_baseline_eq.index)
    old_rec_r = 0.60 * p3_baseline_eq.reindex(idx2).pct_change().fillna(0) + \
                0.40 * p5_baseline_eq.reindex(idx2).pct_change().fillna(0)
    old_rec_eq = (1 + old_rec_r).cumprod() * 10_000.0
    m_old_rec = full_metrics(old_rec_eq, "OLD_REC_P3_P5_60_40")

    # verdict gates
    print("\nAuditing combined 60/40 blend...")
    combo_audit = verdict_8gate(combined_eq)
    p3_invvol_audit = verdict_8gate(p3_invvol_eq)
    p5_def_audit = verdict_8gate(p5_def_eq)

    results = {
        "P3_baseline":         m_p3_base,
        "P5_baseline":         m_p5_base,
        "OLD_REC_P3_P5_60_40": m_old_rec,
        "P3_invvol":           m_p3,
        "P5_btc_defensive":    m_p5,
        "NEW_COMBO_60_40":     m_combo,
        "combo_audit":         combo_audit,
        "p3_invvol_audit":     p3_invvol_audit,
        "p5_def_audit":        p5_def_audit,
    }

    out_path = OUT / "leverage_combined_60_40.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)

    print("\n" + "="*70)
    print("RECOMMENDED vs BASELINE COMPARISON")
    print("="*70)
    for m in [m_p3_base, m_p5_base, m_old_rec, m_p3, m_p5, m_combo]:
        print(f"  {m['label']:22s}  Sharpe={m['sharpe']}  CAGR={m['cagr']:6.3f}  "
              f"MDD={m['max_dd']:6.3f}  Calmar={m['calmar']}  "
              f"min_yr={m['min_yr']:6.3f}  pos={m['pos_yrs']}/6")

    print(f"\nNEW_COMBO_60_40 audit: {combo_audit['tests_passed']}")
    for gn, g in combo_audit["gates"].items():
        mark = "PASS" if g["pass"] is True else "FAIL" if g["pass"] is False else "skip"
        print(f"  [{mark:4s}] {gn:38s} -> {g['value']}")

    # Build HTML comparison
    print("\nBuilding LEVERAGE_COMPARISON.html...")
    build_html(
        baseline_eqs={"P3": p3_baseline_eq, "P5": p5_baseline_eq,
                      "OLD_REC_60_40": old_rec_eq},
        leveraged_eqs={"P3_invvol": p3_invvol_eq,
                       "P5_btc_defensive": p5_def_eq,
                       "NEW_COMBO_60_40": combined_eq},
        metrics=results,
    )
    print(f"\nTime {time.time()-t0:.1f}s")


# ---------------------------------------------------------------- HTML builder
def svg_equity(eq: pd.Series, w=680, h=180, color="#3b82f6"):
    """Inline SVG of equity curve, normalized."""
    vals = eq.values.astype(float)
    vals = vals / vals[0]
    n = len(vals)
    if n < 2: return ""
    vmin, vmax = float(vals.min()), float(vals.max())
    rng = vmax - vmin or 1.0
    pts = []
    for i, v in enumerate(vals):
        x = i / (n - 1) * (w - 20) + 10
        y = h - 10 - (v - vmin) / rng * (h - 20)
        pts.append(f"{x:.1f},{y:.1f}")
    path = "M " + " L ".join(pts)
    return (f'<svg viewBox="0 0 {w} {h}" width="100%" height="{h}" '
            f'xmlns="http://www.w3.org/2000/svg" style="background:#f8fafc;border-radius:8px">'
            f'<path d="{path}" fill="none" stroke="{color}" stroke-width="1.5"/>'
            f'<text x="12" y="22" font-size="11" fill="#64748b">x{vals[-1]:.2f}</text>'
            f'</svg>')

def metric_chip(label, value, positive=None):
    color = "#64748b"
    if positive is True: color = "#16a34a"
    elif positive is False: color = "#dc2626"
    return (f'<span style="display:inline-block;padding:4px 10px;margin:2px;'
            f'background:#f1f5f9;border-left:3px solid {color};font-size:12px;">'
            f'<b style="color:#475569">{label}:</b> '
            f'<span style="color:{color}">{value}</span></span>')

def build_html(baseline_eqs, leveraged_eqs, metrics):
    html = []
    html.append("""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Leverage Study Comparison</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;margin:0;padding:24px;background:#fafbfc;color:#111827;}
h1,h2,h3{color:#0f172a}
h1{border-bottom:3px solid #3b82f6;padding-bottom:12px;}
h2{margin-top:36px;border-bottom:1px solid #e5e7eb;padding-bottom:6px}
table{border-collapse:collapse;width:100%;margin:12px 0;background:white;box-shadow:0 1px 2px rgba(0,0,0,.05)}
th,td{padding:8px 12px;border-bottom:1px solid #e5e7eb;text-align:left;font-size:13px}
th{background:#f8fafc;font-weight:600;color:#475569}
tr:hover{background:#f9fafb}
.pos{color:#16a34a;font-weight:600}.neg{color:#dc2626;font-weight:600}
.win-cell{background:#dcfce7}
.lose-cell{background:#fee2e2}
.section{background:white;padding:20px;margin:16px 0;border-radius:10px;box-shadow:0 1px 3px rgba(0,0,0,.07)}
.card{display:inline-block;vertical-align:top;width:32%;margin-right:1%;padding:14px;background:white;border-radius:8px;border:1px solid #e5e7eb}
.champion{border:2px solid #16a34a;background:linear-gradient(to bottom,#f0fdf4,white)}
.warn{border:2px solid #f97316;background:linear-gradient(to bottom,#fff7ed,white)}
.nav{position:sticky;top:0;background:white;padding:12px;margin:-24px -24px 16px;box-shadow:0 2px 4px rgba(0,0,0,.08);z-index:10}
.nav a{margin-right:16px;color:#3b82f6;text-decoration:none;font-size:13px}
</style></head><body>""")

    html.append('<div class="nav">'
                '<a href="#summary">Summary</a>'
                '<a href="#champion">Champion</a>'
                '<a href="#details">Detail breakdown</a>'
                '<a href="#findings">Key findings</a>'
                '</div>')

    html.append("<h1>🏆 Leverage Study — Recommended Portfolio Comparison</h1>")
    html.append('<p style="color:#64748b">Compares the new leveraged recommendation '
                '(<b>P3_invvol + P5_btc_defensive 60/40</b>) against the baseline '
                '(<b>P3 + P5 60/40</b>) and individual components. See '
                '<code>docs/research/19_LEVERAGE_STUDY.md</code> for full methodology.</p>')

    # Summary scoreboard
    html.append('<div class="section" id="summary">')
    html.append("<h2>📊 Scoreboard</h2>")
    html.append("<table><thead><tr>"
                "<th>Portfolio</th><th>Sharpe</th><th>CAGR</th><th>Max DD</th>"
                "<th>Calmar</th><th>Min-Yr</th><th>Pos Years</th></tr></thead><tbody>")

    rows_data = [
        ("P3 baseline",      metrics["P3_baseline"],     False, False),
        ("P5 baseline",      metrics["P5_baseline"],     False, False),
        ("OLD 60/40 rec",    metrics["OLD_REC_P3_P5_60_40"], False, False),
        ("P3_invvol",        metrics["P3_invvol"],       True,  False),
        ("P5_btc_defensive", metrics["P5_btc_defensive"], True, False),
        ("NEW 60/40 rec",    metrics["NEW_COMBO_60_40"], True,  True),
    ]
    for name, m, is_lev, is_champ in rows_data:
        cls = "win-cell" if is_champ else ""
        html.append(f'<tr class="{cls}"><td><b>{name}</b></td>'
                    f'<td>{m["sharpe"]}</td>'
                    f'<td>{m["cagr"]*100:+.1f}%</td>'
                    f'<td>{m["max_dd"]*100:+.1f}%</td>'
                    f'<td>{m["calmar"]}</td>'
                    f'<td>{m["min_yr"]*100:+.1f}%</td>'
                    f'<td>{m["pos_yrs"]}/6</td></tr>')
    html.append("</tbody></table></div>")

    # Champion card
    cm = metrics["NEW_COMBO_60_40"]
    om = metrics["OLD_REC_P3_P5_60_40"]
    html.append('<div class="section champion" id="champion">')
    html.append("<h2>🥇 NEW RECOMMENDATION: P3_invvol (60%) + P5_btc_defensive (40%)</h2>")
    html.append('<table><thead><tr><th>Metric</th><th>OLD (P3+P5 eqw)</th>'
                '<th>NEW (P3_invvol+P5_btc_def)</th><th>Delta</th></tr></thead><tbody>')
    for k, lbl in [("sharpe", "Sharpe"), ("cagr", "CAGR"),
                    ("max_dd", "Max DD"), ("calmar", "Calmar"),
                    ("min_yr", "Min-Year"), ("pos_yrs", "Positive Years")]:
        oldv = om[k]; newv = cm[k]
        if k in ("cagr","max_dd","min_yr"):
            oldv_s = f"{oldv*100:+.1f}%"; newv_s = f"{newv*100:+.1f}%"
            delta_s = f"{(newv-oldv)*100:+.2f}pp"
        elif k == "pos_yrs":
            oldv_s = f"{oldv}/6"; newv_s = f"{newv}/6"; delta_s = "—"
        else:
            oldv_s = str(oldv); newv_s = str(newv); delta_s = f"{newv-oldv:+.2f}"
        better = None
        if k in ("sharpe","cagr","calmar","min_yr","pos_yrs"):
            better = newv > oldv
        elif k == "max_dd":
            better = newv > oldv   # less negative = better
        cls = "pos" if better else ("neg" if better is False else "")
        html.append(f'<tr><td><b>{lbl}</b></td><td>{oldv_s}</td>'
                    f'<td>{newv_s}</td><td class="{cls}">{delta_s}</td></tr>')
    html.append("</tbody></table>")

    html.append('<h3>Equity curve (NEW 60/40 blend)</h3>')
    html.append(svg_equity(
        pd.Series({pd.Timestamp(k):v for k,v in enumerate([])}) if False
        else list(leveraged_eqs.values())[2]  # NEW_COMBO_60_40 is third
    ))
    # Also audit box
    audit = metrics["combo_audit"]
    html.append(f'<h3>Robustness battery (8-gate)</h3>')
    html.append(f'<p><b>Tests passed: {audit["tests_passed"]}</b></p>')
    html.append("<table><thead><tr><th>Gate</th><th>Status</th><th>Value</th></tr></thead><tbody>")
    for gn, g in audit["gates"].items():
        mark = "✅" if g["pass"] is True else ("❌" if g["pass"] is False else "⏭")
        cls = "pos" if g["pass"] is True else ("neg" if g["pass"] is False else "")
        html.append(f'<tr><td>{gn}</td><td class="{cls}">{mark}</td><td>{g["value"]}</td></tr>')
    html.append("</tbody></table></div>")

    # Detail breakdown with equity curves
    html.append('<div class="section" id="details">')
    html.append("<h2>🔬 Per-portfolio breakdown</h2>")
    for name, eq in {**baseline_eqs, **leveraged_eqs}.items():
        m = metrics.get(
            "P3_baseline" if name == "P3" else
            "P5_baseline" if name == "P5" else
            name.replace("OLD_REC_60_40", "OLD_REC_P3_P5_60_40")
                .replace("NEW_COMBO_60_40", "NEW_COMBO_60_40"),
            None)
        if not m:
            continue
        is_lev = name in leveraged_eqs
        color = "#16a34a" if is_lev else "#64748b"
        html.append(f'<div class="card"><h3 style="margin-top:0">{name}</h3>')
        html.append(metric_chip("Sharpe", m["sharpe"]))
        html.append(metric_chip("CAGR", f"{m['cagr']*100:+.1f}%"))
        html.append(metric_chip("MDD", f"{m['max_dd']*100:+.1f}%"))
        html.append(metric_chip("Calmar", m["calmar"]))
        html.append(metric_chip("Min-Yr", f"{m['min_yr']*100:+.1f}%"))
        html.append("<br>")
        html.append(svg_equity(eq, color=color))
        # yearly table
        html.append('<table style="margin-top:8px"><thead><tr><th>Year</th><th>Return</th></tr></thead><tbody>')
        for yr, r in m["yearly"].items():
            cls = "pos" if r > 0 else "neg"
            html.append(f'<tr><td>{yr}</td><td class="{cls}">{r*100:+.1f}%</td></tr>')
        html.append("</tbody></table></div>")
    html.append("</div>")

    # Findings
    html.append('<div class="section" id="findings">')
    html.append("<h2>🧪 Key findings from leverage study</h2>")
    html.append("""
<ul>
<li><b>Raising leverage_cap does nothing</b> — ATR-risk sizing almost never exceeds ~2× leverage at 4h crypto. Cap is a dead parameter.</li>
<li><b>Per-sleeve leverage boosts hurt the blend</b> — amplifies correlated drawdowns even when it helps per-sleeve Sharpe.</li>
<li><b>Inverse-vol weighting is a free lunch</b> — same return, lower DD, higher Calmar.</li>
<li><b>Global BTC regime gate</b> beats per-sleeve confidence gating — market regime more robust than signal strength.</li>
<li><b>Calmar-optimized aggressive sizing</b> doubles CAGR but fails bootstrap MDD gate — satellite-only.</li>
</ul>""")
    html.append("</div>")

    html.append("</body></html>")

    out = OUT / "LEVERAGE_COMPARISON.html"
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(html))
    size_kb = out.stat().st_size / 1024
    print(f"Wrote {out} ({size_kb:.1f} KB)")

if __name__ == "__main__":
    main()
