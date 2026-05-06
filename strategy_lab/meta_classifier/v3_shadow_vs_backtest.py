"""V3 shadow vs backtest reconciliation.

Goal: compare LIVE VPS3 shadow performance of V3 sleeves against the V3_alone
backtest result from `v3_btc_union_realfills.py` (n=322, hit=61.5%,
total=$642, ROI=+11.5%/trade).

Caveats:
  - Backtest period: Apr 22 → Apr 29 (V3 features available)
  - Shadow period:   Apr 30 → May 5 (V3 sleeve deployment began Apr 30)
  - Different time windows — this is forward-walk validation, not reproduction.
  - Production uses bar-engine signal (live prob_stack), not the cached
    btc_features_v3.csv used by backtest.
  - Production fee assumption: 2% taker (matches our backtest).

Reads:
  data/v4/shadow_trades_2026_05_05_live/v3_resolutions_latest.csv

Outputs:
  strategy_lab/results/meta_classifier/v3_shadow_vs_backtest.csv
  strategy_lab/reports/V3_SHADOW_VS_BACKTEST.md
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
SHADOW = ROOT / "data" / "v4" / "shadow_trades_2026_05_05_live" / "v3_resolutions_latest.csv"
OUT_CSV = ROOT / "strategy_lab" / "results" / "meta_classifier" / "v3_shadow_vs_backtest.csv"
REPORT  = ROOT / "strategy_lab" / "reports" / "V3_SHADOW_VS_BACKTEST.md"


def parse_shadow(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["data_obj"] = df["data"].apply(json.loads)
    flat = pd.json_normalize(df["data_obj"])
    flat["sleeve_id"] = df["sleeve_id"]
    flat["at"] = pd.to_datetime(df["at"])
    # Coerce types
    for c in ["pnl_usd", "entry_qty", "entry_price", "hedge_price",
              "strike_price", "settlement_price"]:
        flat[c] = pd.to_numeric(flat[c], errors="coerce")
    flat["won_b"] = flat["won"] == True   # noqa: E712
    flat["hedged_b"] = flat["hedged"] == True   # noqa: E712
    return flat


def aggregate(df: pd.DataFrame, label: str) -> dict:
    n = len(df)
    if n == 0:
        return {"label": label, "n": 0}
    pnl = df["pnl_usd"].astype(float).values
    cost = (df["entry_qty"] * df["entry_price"]).astype(float).values
    cost = np.where(cost > 0, cost, 25.0)  # fall back to $25 default
    boot = np.random.default_rng(42).choice(pnl, size=(2000, n), replace=True).sum(axis=1)
    return dict(
        label=label,
        n=n,
        wins=int(df["won_b"].sum()),
        losses=int((~df["won_b"]).sum()),
        hit=float(df["won_b"].mean()),
        hedged=int(df["hedged_b"].sum()),
        pnl_total=float(pnl.sum()),
        pnl_mean=float(pnl.mean()),
        roi_pct=float((pnl / cost).mean() * 100),
        ci_lo=float(np.quantile(boot, 0.025)),
        ci_hi=float(np.quantile(boot, 0.975)),
        avg_entry_px=float(df["entry_price"].dropna().mean()),
        avg_qty=float(df["entry_qty"].dropna().mean()),
        first_at=str(df["at"].min()),
        last_at=str(df["at"].max()),
    )


def main():
    print(f"[load] {SHADOW.relative_to(ROOT)}")
    flat = parse_shadow(SHADOW)
    print(f"  rows={len(flat)}  sleeves={flat.sleeve_id.nunique()}")

    # Top-line aggregation
    rows = [aggregate(flat, "ALL V3 sleeves")]
    # By family (v3 vs v3_1, v3_2, v3_3 — sniper variants)
    flat["family"] = flat["sleeve_id"].str.replace(r"^poly_updown_", "", regex=True)
    rows.append(aggregate(flat[flat["sleeve_id"].str.endswith("_v3")], "V3 base (no variant)"))
    rows.append(aggregate(flat[flat["sleeve_id"].str.contains("_v3_")], "V3 variants (v3_1/2/3)"))

    # By symbol
    for sym in ["BTC", "ETH", "SOL"]:
        rows.append(aggregate(flat[flat["symbol"] == sym], f"{sym} only"))
        for tf in ["5m", "15m"]:
            rows.append(aggregate(flat[(flat["symbol"] == sym) & (flat["tf"] == tf)], f"{sym} {tf}"))

    # Per-sleeve breakdown
    for sl, sub in flat.groupby("sleeve_id"):
        rows.append(aggregate(sub, f"sleeve={sl}"))

    df_res = pd.DataFrame(rows)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df_res.to_csv(OUT_CSV, index=False)
    print(f"[csv] wrote {OUT_CSV}")

    # ───────────────────────────────────────────────────────────────────────
    # Backtest comparison block (V3_alone numbers from V3_BTC_UNION_REALFILLS.md)
    # ───────────────────────────────────────────────────────────────────────
    BACKTEST = {
        "V3_alone — ALL":  dict(n=322, hit=0.615, pnl_total=641.97,  pnl_mean=1.9937, roi=11.51, period="Apr 22 → Apr 29"),
        "V3_alone — 5m":   dict(n=238, hit=0.643, pnl_total=449.12,  pnl_mean=1.8870, roi=9.73,  period="Apr 22 → Apr 29"),
        "V3_alone — 15m":  dict(n=84,  hit=0.536, pnl_total=192.86,  pnl_mean=2.2959, roi=16.53, period="Apr 22 → Apr 29"),
        "BTC_only — ALL":  dict(n=454, hit=0.855, pnl_total=4931.64, pnl_mean=10.86,  roi=42.65, period="Apr 22 → May 4"),
    }

    L = [
        "# V3 Shadow vs Backtest — VPS3 Live Reconciliation\n",
        "_Generated: 2026-05-05_\n",
        "## Setup\n",
        "Pulled all V3-family resolutions from VPS3 `trading.events` "
        "(kind=`poly_updown_resolution`, sleeve_id LIKE `poly_updown_%_v3%`).\n",
        f"- Source: VPS3 (root@185.190.143.7) → /tmp/v3_resolutions_latest.csv → SCP local",
        f"- Total rows: {len(flat)}",
        f"- Sleeves observed: {flat.sleeve_id.nunique()} ({', '.join(sorted(flat.sleeve_id.unique()))})",
        f"- Date range: {flat['at'].min()} → {flat['at'].max()}",
        f"- Mode: {flat['mode'].value_counts().to_dict()}",
        "",
        "## Production execution semantics observed in shadow\n",
        f"- Entry price (median):  ${flat['entry_price'].median():.4f}  (range ${flat['entry_price'].min():.3f} – ${flat['entry_price'].max():.3f})",
        f"- Entry qty (median):    {flat['entry_qty'].median():.2f} shares",
        f"- Notional (qty×price):  ${(flat['entry_qty']*flat['entry_price']).median():.2f} per trade",
        f"- Hedged trades:         {int(flat['hedged_b'].sum())} / {len(flat)} ({flat['hedged_b'].mean()*100:.1f}%)",
        "",
        "## Shadow performance — top-line\n",
        "| Slice | n | wins | hit% | hedged | total PnL | mean PnL | ROI/trade | avg entry px | range |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for r in rows:
        if r["n"] == 0:
            continue
        if not r["label"].startswith("sleeve="):
            L.append(
                f"| {r['label']} | {r['n']} | {r.get('wins',0)} | {r['hit']*100:.1f}% | "
                f"{r.get('hedged',0)} | ${r['pnl_total']:+.2f} | ${r['pnl_mean']:+.4f} | "
                f"{r['roi_pct']:+.2f}% | ${r.get('avg_entry_px',0):.3f} | "
                f"{r.get('first_at','')[:10]}→{r.get('last_at','')[:10]} |"
            )

    L.append("\n### Per-sleeve breakdown\n")
    L.append("| Sleeve | n | hit% | total PnL | mean PnL | ROI/trade | hedged |")
    L.append("|---|---:|---:|---:|---:|---:|---:|")
    for r in rows:
        if not r["label"].startswith("sleeve=") or r["n"] == 0:
            continue
        sleeve = r["label"].replace("sleeve=", "")
        L.append(
            f"| {sleeve} | {r['n']} | {r['hit']*100:.1f}% | ${r['pnl_total']:+.2f} | "
            f"${r['pnl_mean']:+.4f} | {r['roi_pct']:+.2f}% | {r['hedged']} |"
        )

    L += [
        "",
        "## Backtest comparison\n",
        "Backtest numbers from `V3_BTC_UNION_REALFILLS.md` ($25 stake, real book, hedge-hold rev_bp=5, 2% fee):\n",
        "| Source | Period | n | hit% | total PnL | mean PnL | ROI/trade |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for k, v in BACKTEST.items():
        L.append(
            f"| Backtest {k} | {v['period']} | {v['n']} | {v['hit']*100:.1f}% | "
            f"${v['pnl_total']:+.2f} | ${v['pnl_mean']:+.4f} | {v['roi']:+.2f}% |"
        )
    # Now shadow ALL row
    r_all = next(r for r in rows if r["label"] == "ALL V3 sleeves")
    L.append(
        f"| **Shadow ALL V3** | Apr 30 → May 5 | {r_all['n']} | {r_all['hit']*100:.1f}% | "
        f"${r_all['pnl_total']:+.2f} | ${r_all['pnl_mean']:+.4f} | {r_all['roi_pct']:+.2f}% |"
    )

    # Reconciliation analysis
    bt = BACKTEST["V3_alone — ALL"]
    bt_5m = BACKTEST["V3_alone — 5m"]
    sh_5m = next((r for r in rows if r["label"] == "BTC 5m"), None)

    L += [
        "",
        "## Reconciliation\n",
        "**Same engine, different periods + slightly different gate**:\n",
        "- Backtest **V3_alone** uses cached `prob_stack` from `btc_features_v3.csv` (Apr 22 → Apr 29) at threshold ≥ 0.65, BTC only.",
        "- Shadow **V3 family** uses live `prob_stack` from BarEngine across BTC + ETH + SOL on 5m sleeves, with multiple thresholds (v3_1/2/3 = sniper variants at higher quantile q90/q80).",
        f"- Backtest BTC ALL: hit {bt['hit']*100:.1f}%, mean ${bt['pnl_mean']:+.4f}/trade",
        f"- Shadow ALL V3:  hit {r_all['hit']*100:.1f}%, mean ${r_all['pnl_mean']:+.4f}/trade",
        "",
    ]

    # delta analysis
    delta_hit = r_all["hit"] - bt["hit"]
    delta_pnl_mean = r_all["pnl_mean"] - bt["pnl_mean"]
    L.append(f"**Hit rate delta**: {delta_hit*100:+.1f}pp (shadow vs backtest BTC-only)")
    L.append(f"**Mean PnL delta**: ${delta_pnl_mean:+.4f}/trade")

    if r_all["hit"] >= bt["hit"] - 0.05 and r_all["pnl_mean"] >= bt["pnl_mean"] - 0.5:
        L.append("\n→ **Shadow performance ≈ backtest** (within ~5pp hit, ~$0.50 mean PnL). V3 forward-walks consistently with backfill.")
    elif r_all["pnl_mean"] > bt["pnl_mean"]:
        L.append(f"\n→ **Shadow OUTPERFORMS backtest** by ${delta_pnl_mean:.2f}/trade — likely because shadow includes ETH/SOL where backtest didn't.")
    else:
        L.append(f"\n→ **Shadow UNDERPERFORMS backtest** by ${-delta_pnl_mean:.2f}/trade — forward-walk degradation; investigate before scaling.")

    # 5m subset comparison if available
    btc_5m_shadow = next((r for r in rows if r["label"] == "BTC 5m"), None)
    if btc_5m_shadow and btc_5m_shadow["n"] > 0:
        L += [
            "",
            "### BTC-5m subset (cleanest apples-to-apples)\n",
            f"- **Backtest V3_alone — 5m**: n={bt_5m['n']}, hit={bt_5m['hit']*100:.1f}%, mean ${bt_5m['pnl_mean']:+.4f}/trade",
            f"- **Shadow BTC 5m**:           n={btc_5m_shadow['n']}, hit={btc_5m_shadow['hit']*100:.1f}%, mean ${btc_5m_shadow['pnl_mean']:+.4f}/trade",
            f"- **Hit Δ**: {(btc_5m_shadow['hit']-bt_5m['hit'])*100:+.1f}pp   **Mean PnL Δ**: ${btc_5m_shadow['pnl_mean']-bt_5m['pnl_mean']:+.4f}",
        ]

    # Comparison vs BTC_only (the big winner from backtest)
    bt_btc = BACKTEST["BTC_only — ALL"]
    L += [
        "",
        "## Vs the BTC_only candidate (backtest only — not yet deployed)\n",
        f"- Backtest **BTC_only** (top-10% \\|btc_ret_2m\\|, t+120s entry): n={bt_btc['n']}, hit={bt_btc['hit']*100:.1f}%, mean ${bt_btc['pnl_mean']:+.4f}/trade, ROI {bt_btc['roi']:+.2f}%/trade",
        f"- Shadow **V3 family** total: n={r_all['n']}, hit={r_all['hit']*100:.1f}%, mean ${r_all['pnl_mean']:+.4f}/trade, ROI {r_all['roi_pct']:+.2f}%/trade",
        f"- BTC_only outperforms V3 by **${bt_btc['pnl_mean']/max(r_all['pnl_mean'],0.01):.1f}×** per-trade in mean PnL.",
        "",
        "**Recommendation**: deploy BTC_only sleeve (top-10% \\|btc_ret_2m\\|, sign = direction, "
        "entry @ bucket 12) in shadow mode alongside V3 to forward-walk validate the backtest "
        "result before scaling.",
        "",
    ]

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(L), encoding="utf-8")
    print(f"[report] wrote {REPORT}")


if __name__ == "__main__":
    main()
