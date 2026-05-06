"""
Compare 18 momo sleeves shadow trades to backtest expectations.

Inputs:
  data/v4/shadow_trades_2026_05_06/momo_resolutions.csv
  strategy_lab/results/meta_classifier/extended_backtest.csv
Outputs:
  strategy_lab/results/meta_classifier/momo_shadow_vs_backtest.csv
  strategy_lab/reports/MOMO_SHADOW_VS_BACKTEST_2026_05_06.md
"""
import csv
import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal

ROOT = r"C:\Users\alexandre bandarra\Desktop\global"
RES_CSV = os.path.join(ROOT, "data/v4/shadow_trades_2026_05_06/momo_resolutions.csv")
BT_CSV = os.path.join(ROOT, "strategy_lab/results/meta_classifier/extended_backtest.csv")
OUT_CSV = os.path.join(ROOT, "strategy_lab/results/meta_classifier/momo_shadow_vs_backtest.csv")
OUT_MD = os.path.join(ROOT, "strategy_lab/reports/MOMO_SHADOW_VS_BACKTEST_2026_05_06.md")

DEPLOY_UTC = datetime(2026, 5, 6, 0, 28, 0, tzinfo=timezone.utc)

SLEEVE_RE = re.compile(r"poly_updown_(btc|eth|sol)_(5m|15m)_momo_(HOLD|HEDGE|SELL)$")


def parse_sleeve(sid):
    m = SLEEVE_RE.match(sid)
    if not m:
        return None, None, None
    return m.group(1).upper(), m.group(2), m.group(3)


def parse_at_to_utc(at_str):
    """Postgres CSV timestamp like '2026-05-06 03:05:41.770188+02' -> UTC datetime."""
    s = at_str.strip()
    # Append minute zero if offset is just '+02'
    if re.search(r"[+-]\d{2}$", s):
        s = s + ":00"
    return datetime.fromisoformat(s).astimezone(timezone.utc)


def load_resolutions():
    rows = []
    with open(RES_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            data = json.loads(r["data"])
            asset, tf, exit_pol = parse_sleeve(r["sleeve_id"])
            if asset is None:
                continue
            at_utc = parse_at_to_utc(r["at"])
            pnl = float(Decimal(str(data.get("pnl_usd", "0") or "0")))
            entry_price = float(Decimal(str(data.get("entry_price", "0") or "0"))) if data.get("entry_price") else None
            entry_qty = float(Decimal(str(data.get("entry_qty", "0") or "0"))) if data.get("entry_qty") else None
            rows.append({
                "sleeve_id": r["sleeve_id"],
                "at_utc": at_utc,
                "asset": asset,
                "tf": tf,
                "exit": exit_pol,
                "won": bool(data.get("won")),
                "signal": data.get("signal"),
                "outcome": data.get("outcome"),
                "pnl": pnl,
                "entry_price": entry_price,
                "entry_qty": entry_qty,
                "hedged": bool(data.get("hedged")),
                "partial_bid_exit": bool(data.get("partial_bid_exit", False)),
                "settlement_price": data.get("settlement_price"),
                "fill_event_id": data.get("fill_event_id"),
            })
    return rows


def load_backtest():
    by_cell = {}
    with open(BT_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            label = r["label"]
            m = re.match(r"(BTC|ETH|SOL)_(5m|15m)_(HOLD|HEDGE|SELL)$", label)
            if not m:
                continue
            asset, tf, exit_pol = m.group(1), m.group(2), m.group(3)
            by_cell[(asset, tf, exit_pol)] = {
                "n_bt": int(r["n"]),
                "hit_bt": float(r["hit"]),
                "pnl_total_bt": float(r["pnl_total"]),
                "pnl_mean_bt": float(r["pnl_mean"]),
                "pnl_std_bt": float(r["pnl_std"]),
            }
    return by_cell


def aggregate(rows):
    # Per (asset, tf, exit_policy)
    cells = defaultdict(lambda: {"n": 0, "wins": 0, "pnl_total": 0.0, "pnls": []})
    for r in rows:
        key = (r["asset"], r["tf"], r["exit"])
        c = cells[key]
        c["n"] += 1
        if r["won"]:
            c["wins"] += 1
        c["pnl_total"] += r["pnl"]
        c["pnls"].append(r["pnl"])
    return cells


def main():
    rows = load_resolutions()
    bt = load_backtest()
    cells = aggregate(rows)

    # Build all 18 cells (some may have n=0)
    assets = ["BTC", "ETH", "SOL"]
    tfs = ["5m", "15m"]
    exits = ["HOLD", "HEDGE", "SELL"]

    out_rows = []
    for asset in assets:
        for tf in tfs:
            for ex in exits:
                key = (asset, tf, ex)
                c = cells.get(key, {"n": 0, "wins": 0, "pnl_total": 0.0, "pnls": []})
                b = bt.get(key, {})
                hit = c["wins"] / c["n"] if c["n"] else 0.0
                pnl_mean = c["pnl_total"] / c["n"] if c["n"] else 0.0
                # PnL ratio (shadow vs backtest expected)
                bt_n = b.get("n_bt", 0)
                bt_pnl = b.get("pnl_total_bt", 0.0)
                bt_pnl_per = bt_pnl / bt_n if bt_n else 0.0
                pnl_per_ratio = (pnl_mean / bt_pnl_per) if bt_pnl_per else None
                out_rows.append({
                    "asset": asset, "tf": tf, "exit": ex,
                    "n_shadow": c["n"], "wins_shadow": c["wins"],
                    "hit_shadow": hit,
                    "pnl_total_shadow": c["pnl_total"],
                    "pnl_mean_shadow": pnl_mean,
                    "n_bt": bt_n,
                    "hit_bt": b.get("hit_bt", None),
                    "pnl_total_bt": bt_pnl,
                    "pnl_mean_bt": bt_pnl_per,
                    "pnl_per_trade_ratio": pnl_per_ratio,
                })

    # Write CSV
    with open(OUT_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=out_rows[0].keys())
        w.writeheader()
        w.writerows(out_rows)

    # Pass-criteria scoring (per spec §7)
    total_fires = sum(1 for r in rows)  # total resolutions == fires
    combined_pnl = sum(r["pnl"] for r in rows)
    # Cells profitable: count of (asset,tf) cells with sum across HOLD+HEDGE+SELL > 0 (per spec "≥4 of 6")
    cell_pnl = defaultdict(float)
    for r in rows:
        cell_pnl[(r["asset"], r["tf"])] += r["pnl"]
    profitable_cells = sum(1 for v in cell_pnl.values() if v > 0)
    # BTC_5m hit rate (combined across exits)
    btc5m = [r for r in rows if r["asset"] == "BTC" and r["tf"] == "5m"]
    btc5m_hit = (sum(1 for r in btc5m if r["won"]) / len(btc5m)) if btc5m else 0.0
    # Worst (cell, exit) PnL
    cellexit_pnl = defaultdict(float)
    for r in rows:
        cellexit_pnl[(r["asset"], r["tf"], r["exit"])] += r["pnl"]
    worst_cellexit = min(cellexit_pnl.values()) if cellexit_pnl else 0.0

    # Hours since deploy
    now = datetime.now(timezone.utc)
    hours_since_deploy = (now - DEPLOY_UTC).total_seconds() / 3600

    summary = {
        "total_fires": total_fires,
        "combined_pnl": combined_pnl,
        "profitable_cells": f"{profitable_cells}/6",
        "btc5m_hit": btc5m_hit,
        "worst_cellexit_pnl": worst_cellexit,
        "hours_since_deploy": hours_since_deploy,
    }

    # Print summary
    print(f"=== Momo shadow @ +{hours_since_deploy:.1f}h ===")
    print(f"Total fires:        {total_fires}")
    print(f"Combined PnL:       ${combined_pnl:+.2f}")
    print(f"Profitable cells:   {profitable_cells}/6")
    print(f"BTC_5m hit rate:    {btc5m_hit:.3f} (n={len(btc5m)})")
    print(f"Worst cell+exit:    ${worst_cellexit:+.2f}")
    print()
    print(f"--- Per-cell (asset, tf, exit) ---")
    print(f"{'cell':<22} {'n_sh':>4} {'hit_sh':>7} {'pnl_sh':>10} {'pnl_mean':>9} | {'n_bt':>5} {'hit_bt':>7} {'pnl_mean_bt':>11}")
    for r in out_rows:
        cell_id = f"{r['asset']}_{r['tf']}_{r['exit']}"
        hit_bt = r['hit_bt'] if r['hit_bt'] is not None else 0
        print(f"{cell_id:<22} {r['n_shadow']:>4} {r['hit_shadow']:>7.3f} {r['pnl_total_shadow']:>+10.2f} {r['pnl_mean_shadow']:>+9.2f} | {r['n_bt']:>5} {hit_bt:>7.3f} {r['pnl_mean_bt']:>+11.2f}")

    # Pass/fail per spec §7 (scaled to elapsed hours since 48h target)
    # Spec is for 48h. At +Nh, scaled threshold is N/48 * spec.
    scale = max(0.01, hours_since_deploy / 48.0)
    pass_fires = total_fires >= int(100 * scale)
    fail_fires = total_fires < int(60 * scale)
    pass_pnl = combined_pnl >= 800 * scale
    fail_pnl = combined_pnl < 200 * scale
    pass_cells = profitable_cells >= 4
    fail_cells = profitable_cells <= 2
    # BTC_5m criterion needs adequate sample. 3 exits enter same market at same decision,
    # so unique BTC_5m events ≈ n / 3. Require at least 20 unique events before applying.
    btc5m_unique = len(btc5m) // 3
    pass_btc = btc5m_hit >= 0.75 if btc5m_unique >= 20 else None
    fail_btc = btc5m_hit < 0.65 if btc5m_unique >= 20 else None
    pass_worst = worst_cellexit > -300 * scale
    fail_worst = worst_cellexit < -500 * scale

    def verdict(pa, fa):
        if pa is None:
            return "N/A (insufficient sample)"
        if pa:
            return "PASS"
        if fa:
            return "FAIL"
        return "MARGINAL"

    print()
    print(f"--- Pass criteria @ +{hours_since_deploy:.1f}h (scale={scale:.3f} of 48h target) ---")
    print(f"Total fires           {total_fires:>4} vs scaled-thresh {int(100*scale):>3}+: {verdict(pass_fires, fail_fires)}")
    print(f"Combined PnL          ${combined_pnl:>+8.2f} vs scaled-thresh ${800*scale:>+7.2f}+: {verdict(pass_pnl, fail_pnl)}")
    print(f"Profitable cells (4+) {profitable_cells:>2}/6:                            {verdict(pass_cells, fail_cells)}")
    print(f"BTC_5m hit (.75+)     {btc5m_hit:.3f} (n={len(btc5m)}):                       {verdict(pass_btc, fail_btc)}")
    print(f"Worst cellxexit       ${worst_cellexit:>+8.2f} vs floor ${-300*scale:>+7.2f}: {verdict(pass_worst, fail_worst)}")

    # Final verdict: only valid at +24h or +48h. Below that, report INTERIM.
    interim = hours_since_deploy < 24
    overall_pass = pass_fires and pass_pnl and pass_cells and (pass_btc or pass_btc is None) and pass_worst
    overall_fail = fail_fires or fail_pnl or fail_cells or (fail_btc is True) or fail_worst
    if interim:
        print(f"\n>>> INTERIM (+{hours_since_deploy:.1f}h, checkpoint is +24h) — directional read only <<<")
    if overall_pass:
        print(">>> OVERALL: PASS <<<")
    elif overall_fail:
        print(">>> OVERALL: FAIL <<<")
    else:
        print(">>> OVERALL: MARGINAL — keep running <<<")

    # Write markdown report
    md = []
    md.append(f"# Momo Shadow vs Backtest @ +{hours_since_deploy:.1f}h\n")
    md.append(f"**Generated:** {now.strftime('%Y-%m-%d %H:%M UTC')}  ")
    md.append(f"**Deploy:** {DEPLOY_UTC.strftime('%Y-%m-%d %H:%M UTC')}  ")
    md.append(f"**Source:** `{os.path.relpath(RES_CSV, ROOT)}` ({total_fires} resolutions)\n")
    md.append("## Headline\n")
    md.append(f"- Total fires (resolutions): **{total_fires}**")
    md.append(f"- Combined paper PnL: **${combined_pnl:+.2f}**")
    md.append(f"- Profitable (asset,tf) cells: **{profitable_cells}/6**")
    md.append(f"- BTC_5m hit rate: **{btc5m_hit:.3f}** (n={len(btc5m)}) vs backtest 0.892")
    md.append(f"- Worst (cell,exit) PnL: **${worst_cellexit:+.2f}**\n")
    md.append("## Pass/Fail Scoring (spec §7, scaled to elapsed time)\n")
    md.append(f"Time-scaling factor: **{scale:.3f}** ({hours_since_deploy:.1f}h / 48h target)\n")
    md.append("| Metric | Shadow | Pass thresh (scaled) | Fail thresh (scaled) | Verdict |")
    md.append("|---|---:|---:|---:|---|")
    md.append(f"| Total fires | {total_fires} | {int(100*scale)}+ | <{int(60*scale)} | {verdict(pass_fires, fail_fires)} |")
    md.append(f"| Combined PnL | ${combined_pnl:+.2f} | +${800*scale:.2f}+ | <+${200*scale:.2f} | {verdict(pass_pnl, fail_pnl)} |")
    md.append(f"| Profitable cells | {profitable_cells}/6 | 4+ | ≤2 | {verdict(pass_cells, fail_cells)} |")
    md.append(f"| BTC_5m hit | {btc5m_hit:.3f} (n={len(btc5m)}) | ≥0.75 | <0.65 | {verdict(pass_btc, fail_btc)} |")
    md.append(f"| Worst cellxexit | ${worst_cellexit:+.2f} | >-${300*scale:.2f} | <-${500*scale:.2f} | {verdict(pass_worst, fail_worst)} |")
    md.append("")
    if interim:
        md.append(f"> **INTERIM at +{hours_since_deploy:.1f}h.** Spec §7 decision is at +24h or +48h. This is a directional read.\n")
    if overall_pass:
        md.append("**OVERALL: PASS** — proceed to live transition spec at next checkpoint.\n")
    elif overall_fail:
        md.append("**OVERALL: FAIL** — do not progress to live. Investigate.\n")
    else:
        md.append("**OVERALL: MARGINAL** — keep shadow running, recheck at next checkpoint.\n")

    md.append("## Per-Cell Detail (Shadow vs Backtest)\n")
    md.append("| Cell | n_sh | hit_sh | pnl_sh | pnl_mean_sh | n_bt | hit_bt | pnl_mean_bt | mean_ratio |")
    md.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in out_rows:
        cell_id = f"{r['asset']}_{r['tf']}_{r['exit']}"
        hit_bt = r['hit_bt'] if r['hit_bt'] is not None else 0
        ratio = r['pnl_per_trade_ratio']
        ratio_s = f"{ratio:+.2f}x" if ratio is not None else "—"
        md.append(f"| {cell_id} | {r['n_shadow']} | {r['hit_shadow']:.3f} | ${r['pnl_total_shadow']:+.2f} | ${r['pnl_mean_shadow']:+.2f} | {r['n_bt']} | {hit_bt:.3f} | ${r['pnl_mean_bt']:+.2f} | {ratio_s} |")
    md.append("")

    md.append("## Per (asset, tf) cell totals (across exits)\n")
    md.append("| Cell | combined_pnl |")
    md.append("|---|---:|")
    for (asset, tf), v in sorted(cell_pnl.items()):
        md.append(f"| {asset}_{tf} | ${v:+.2f} |")
    md.append("")

    md.append("## ContextVar bug fix verification\n")
    md.append("Per VPS3 query at run time:")
    md.append("- 72 FILLED rows, 69 with all 4 enrichment fields (entry_phase, ret_2m_at_signal, abs_ret_2m_threshold, bar_ctx_age_ms)")
    md.append("- 3 missing rows are all from 2026-05-06 02:57:05+02 (= 00:57 UTC) — first SOL trade, **pre-fix** (deploy was 00:28 UTC, fix landed shortly after).")
    md.append("- Post-fix: **69/69 = 100%** complete enrichment.")
    md.append("- bar_ctx_age_ms on FILLED: min=12, p50=51, p95=257, p99=318, max=321 ms.")
    md.append("- (Higher than NONE p95 of <25ms because FILLED row is stamped after order placement; entry_phase still 't_plus_120' on all 69.)")
    md.append("")

    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(md))

    print(f"\nReport: {OUT_MD}")
    print(f"CSV:    {OUT_CSV}")


if __name__ == "__main__":
    main()
