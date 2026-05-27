"""Generate the master catalog markdown report from the audited CSV.

Output: strategy_lab/reports/MASTER_SLEEVE_CATALOG_AUDITED_2026_05_26.md
"""
from __future__ import annotations

from pathlib import Path
import math
import pandas as pd

ROOT = Path("C:/Users/alexandre bandarra/Desktop/global")
RES = ROOT / "data" / "v4" / "canonical" / "_results"
CSV = RES / "master_sleeve_catalog_audited.csv"
OUT = ROOT / "strategy_lab" / "reports" / "MASTER_SLEEVE_CATALOG_AUDITED_2026_05_26.md"


def offset_bin(s):
    if not isinstance(s, str):
        return "unknown"
    s = s.strip()
    if s in ("all", ""):
        return "all"
    if "-" in s:
        try:
            lo = int(s.split("-")[0])
        except Exception:
            return s
        if lo <= 60:
            return "0-60"
        if lo <= 150:
            return "60-150"
        if lo <= 240:
            return "150-240"
        if lo <= 300:
            return "240-300"
        if lo <= 480:
            return "300-480"
        if lo <= 720:
            return "480-840"
        return "840+"
    # single number
    try:
        lo = int(s)
        if lo <= 60:
            return "0-60"
        if lo <= 150:
            return "60-150"
        if lo <= 240:
            return "150-240"
        if lo <= 300:
            return "240-300"
        if lo <= 480:
            return "300-480"
        if lo <= 720:
            return "480-840"
        return "840+"
    except Exception:
        return s


def normalize_tf(tf):
    if not isinstance(tf, str):
        return tf
    if tf in ("s15_5m", "s6_5m", "v15m_5m"):
        return "5m"
    return tf


def fmt_money(x):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "—"
    return f"${x:,.0f}"


def fmt_dpt(x):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "—"
    return f"${x:.2f}"


def fmt_pct(x):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "—"
    return f"{x:.1f}%"


def fmt_int(x):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "—"
    return f"{int(x):,}"


def fmt_p(x):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "—"
    return f"{x:.3f}"


def short(s, n=58):
    if not isinstance(s, str):
        return ""
    return s if len(s) <= n else s[: n - 1] + "…"


def main():
    df = pd.read_csv(CSV)
    df["tf"] = df["tf"].apply(normalize_tf)
    df["offset_bin"] = df["offset_range_s"].apply(offset_bin)

    # Stats
    by_round = df["discovery_round"].value_counts().to_dict()
    by_status = df["deploy_status"].value_counts().to_dict()
    by_grade = df["confidence_grade"].value_counts().to_dict()
    n_total = len(df)

    # Deploy roster (status=DEPLOY)
    deploy = df[df["deploy_status"] == "DEPLOY"].sort_values(
        "sum_pnl_28d", ascending=False
    )
    paper = df[df["deploy_status"] == "PAPER_FIRST"].sort_values(
        "sum_pnl_28d", ascending=False
    )
    skips = df[df["deploy_status"].isin(["SKIP_OVERLAP", "SKIP_NEGATIVE_PNL"])]
    candidates = df[df["deploy_status"] == "CANDIDATE"]

    # Per-market best sleeves
    markets = [
        ("BTC", "5m", "0-60"),
        ("BTC", "5m", "60-150"),
        ("BTC", "5m", "150-240"),
        ("BTC", "5m", "240-300"),
        ("ETH", "5m", "0-60"),
        ("ETH", "5m", "60-150"),
        ("ETH", "5m", "150-240"),
        ("ETH", "5m", "240-300"),
        ("SOL", "5m", "0-60"),
        ("SOL", "5m", "60-150"),
        ("SOL", "5m", "150-240"),
        ("SOL", "5m", "240-300"),
        ("BTC", "15m", "60-150"),
        ("BTC", "15m", "150-240"),
        ("BTC", "15m", "240-300"),
        ("BTC", "15m", "300-480"),
        ("BTC", "15m", "480-840"),
        ("ETH", "15m", "60-150"),
        ("ETH", "15m", "150-240"),
        ("ETH", "15m", "240-300"),
        ("ETH", "15m", "300-480"),
        ("ETH", "15m", "480-840"),
        ("SOL", "15m", "60-150"),
        ("SOL", "15m", "150-240"),
        ("SOL", "15m", "240-300"),
        ("SOL", "15m", "300-480"),
        ("SOL", "15m", "480-840"),
        ("POOL", "15m", "60-150"),
        ("POOL", "15m", "150-240"),
        ("POOL", "15m", "240-300"),
        ("POOL", "15m", "300-480"),
        ("POOL", "15m", "480-840"),
    ]

    # Build text
    md = []
    md.append("# Master Sleeve Catalog — Audited — 2026-05-26")
    md.append("")
    md.append("**Date:** 2026-05-26  ")
    md.append("**Window:** Apr 24 → May 25 2026 UTC (32d canonical, chainlink-resolved)  ")
    md.append("**Fee model:** LegacyConfig (2%-on-profit-only, matches VPS3 production)  ")
    md.append("**Outcome truth:** Chainlink Data Streams (canonical `resolutions.parquet`)  ")
    md.append("**Hold policy:** to slot_end, no SL/TP  ")
    md.append("**Anchor convention:** `ws_s = slot_start - window_s` (see CLAUDE.md §F7)  ")
    md.append("**Source CSV:** `data/v4/canonical/_results/master_sleeve_catalog_audited.csv`  ")
    md.append("**Build script:** `strategy_lab/master_catalog_2026_05_26/build_master_catalog.py`  ")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## 0. Executive summary")
    md.append("")
    md.append(f"- **Total sleeves catalogued:** {n_total} across 7 discovery rounds.")
    md.append(
        "- **R6 dedup-validated deploy roster:** "
        f"{by_status.get('DEPLOY', 0)} DEPLOY, "
        f"{by_status.get('PAPER_FIRST', 0)} PAPER_FIRST, "
        f"{by_status.get('SKIP_OVERLAP', 0)} SKIP_OVERLAP, "
        f"{by_status.get('SKIP_NEGATIVE_PNL', 0)} SKIP_NEGATIVE_PNL, "
        f"{by_status.get('CANDIDATE', 0)} CANDIDATE (R3-R7 add-ons pending integration into the manifest)."
    )
    md.append("")
    md.append("### Bottom-line deployable estimate (post-R6+R7 audit)")
    md.append("")
    md.append("| Notional | Daily | Weekly | 28-day | Annual | Confidence |")
    md.append("|---|--:|--:|--:|--:|---|")
    md.append("| **$25** | $732 | $5,125 | **$20,501** | $267,310 | **HIGH** — Agent PP dedup, OOS-filtered, 12 DEPLOY + 4 PAPER_FIRST sleeves |")
    md.append("| **$250** | $7,322 | $51,253 | $205,010 | **$2,673,098** | **HIGH** — linear scaling, fits book depth |")
    md.append("| **$2,500** (op-max) | $73,217 | $512,525 | $2,050,100 | $26.7M | MEDIUM — book depth limits, 10× scaling |")
    md.append("")
    md.append("**R7 WS-poly2 upside (PAPER_FIRST, pending 2nd-lockbox confirm):**")
    md.append("- Agent WW post-dedup estimate: **$127k/28d OOS-only at $25 = $1.27M/28d at $250 = $16.5M/year**")
    md.append("- 4-day lockbox extrapolation fragile — daily PnL shifted ~12× between val and lockbox. Likely $80-200k/28d range.")
    md.append("- Replacing binary AND with WS-poly2 on 7 sleeves: 2.3× lift confirmed apples-to-apples.")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## 1. Audit findings summary")
    md.append("")
    md.append("### 1.1 Verified")
    md.append("- **Fee model**: Production charges 2% on profit only (winning leg). Verified vs 25,900 `poly_updown_resolution` events 2026-05-22 — median diff = 0 from naive-no-fee on losses, exact match on wins with 0.98 multiplier. Use `engine_v2.LegacyConfig`, NOT the `poly_taker_curve` (0.07·p·(1-p)) formula.")
    md.append("- **Anchor convention**: F7 RSI verified ws_s anchor (94.7% match across 1,331 production fires).")
    md.append("- **Production tradingvenue book source**: WS-only (Phase 18.6 Wave 1). REST/Storedata are fallbacks. Live `paper.book_fetched` confirms `source='ws_mirror'`.")
    md.append("")
    md.append("### 1.2 Bug fix from prior rounds")
    md.append("- **Naive-sum overlap inflation**: R1-R5 reports SUMMED per-sleeve PnL across overlapping fires. Agent PP showed Jaccard 0.4-1.0 between BTC 5m sleeves. Real combined PnL is ~22% of naive sum.")
    md.append("- **Authoritative number**: $20,501/28d @ $25 (vs prior $85-95k naive). Single source of truth: `final_deploy_manifest.csv`.")
    md.append("- **R5 ETH S6 + lm_high_stat / R5 hawkes ETH** flagged as overfit — moved to SKIP list.")
    md.append("")
    md.append("### 1.3 Open caveats")
    md.append("- **WS-poly2 11.6× val→lockbox step-up**: Agent WW's $127k/28d is from 4-day lockbox extrapolation that shows daily PnL jumping from ~$937/day (val 7d) to ~$10,895/day (lockbox 4d). Could be: (a) genuine regime shift, (b) lucky window, or (c) panel-window normalization issue (PP-R6 manifest covered only 4d but normalized as 28/32 days). Until validated with a 2nd lockbox, treat WS-poly2 numbers as B-grade not A.")
    md.append("- **S6 calibration is poor** (TT). Isotonic regression fixes calibration error 0.18→0.03 but LOWERS lockbox PnL by 3.8%. Production should keep S6 thresholds conservative.")
    md.append("- **15m R4 trend_slope sleeves** look strong on full window but **the 4 already in deploy manifest as 15m are SKIP_NEGATIVE_PNL** in OOS. The remaining 178 R4 trend_slope deployable rows are CANDIDATE — need a 2nd lockbox before promotion.")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## 2. Confidence grade distribution")
    md.append("")
    md.append("| Grade | Count | Criterion |")
    md.append("|---|--:|---|")
    md.append(f"| **A** | {by_grade.get('A', 0)} | strict 3-way pass + dedup-validated + high marginal contribution + OOS PASS + lockbox WR ≥ 60% & $/tr > $1 |")
    md.append(f"| **B** | {by_grade.get('B', 0)} | walk-forward pass + OOS PASS + positive lockbox |")
    md.append(f"| **C** | {by_grade.get('C', 0)} | single-window only, or borderline OOS, or small-n (n_lock < 50) |")
    md.append(f"| **F** | {by_grade.get('F', 0)} | OOS FAIL — do-not-deploy |")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## 3. Per-market best sleeves")
    md.append("")
    md.append("For each (asset, tf, offset_bin) we list the top 1-3 sleeves by 28-day PnL among grade A/B with OOS PASS. Cells with no grade A/B sleeves omitted.")
    md.append("")
    md.append("| Market | Offset bin | Best sleeve | Round | n | WR | $/tr | sum/28d | Grade | Status |")
    md.append("|---|---|---|---|--:|--:|--:|--:|---|---|")
    for asset, tf, ob in markets:
        cell = df[(df["asset"] == asset) & (df["tf"] == tf) & (df["offset_bin"] == ob)]
        cell = cell[
            (cell["confidence_grade"].isin(["A", "B"]))
            & (cell["oos_status"] == "PASS")
            & (cell["sum_pnl_28d"].fillna(-1) > 0)
        ].sort_values("sum_pnl_28d", ascending=False).head(3)
        if len(cell) == 0:
            continue
        for i, (_, r) in enumerate(cell.iterrows()):
            label = f"{asset} {tf}" if i == 0 else ""
            ob_label = ob if i == 0 else ""
            md.append(
                f"| {label} | {ob_label} | `{short(str(r['sleeve_id']), 55)}` | {r['discovery_round']} | "
                f"{fmt_int(r['n_total'])} | {fmt_pct(r['wr_total'])} | {fmt_dpt(r['dollar_per_trade'])} | "
                f"{fmt_money(r['sum_pnl_28d'])} | **{r['confidence_grade']}** | {r['deploy_status']} |"
            )
    md.append("")
    md.append("---")
    md.append("")
    md.append("## 4. Full DEPLOY roster (post-audit)")
    md.append("")
    md.append("These are the sleeves Agent PP's overlap audit promoted to DEPLOY status (12 entries from `final_deploy_manifest.csv`), plus the 4 PAPER_FIRST diversifiers.")
    md.append("")
    md.append("### 4.1 DEPLOY (Phase 1 — full notional, OOS-validated)")
    md.append("")
    md.append("| # | Sleeve | Asset/TF | Offset | n | WR | $/tr | sum/28d | Marginal/28d | Overlap% | Grade | Notes |")
    md.append("|--:|---|---|---|--:|--:|--:|--:|--:|--:|---|---|")
    for i, (_, r) in enumerate(deploy.iterrows(), 1):
        marg = ""
        notes = r.get("notes")
        if isinstance(notes, str) and "marginal_28d" in notes:
            try:
                # Parse "marginal_28d=$X..."
                seg = notes.split("marginal_28d=")[1].split(" ")[0]
                marg = seg
            except Exception:
                pass
        md.append(
            f"| {i} | `{r['sleeve_id']}` | {r['asset']} {r['tf']} | {r['offset_range_s']} | "
            f"{fmt_int(r['n_total'])} | {fmt_pct(r['wr_total'])} | {fmt_dpt(r['dollar_per_trade'])} | "
            f"{fmt_money(r['sum_pnl_28d'])} | {marg or '—'} | "
            f"{fmt_pct(r['slug_overlap_pct_with_primary']) if r['slug_overlap_pct_with_primary'] is not None else '—'} | "
            f"**{r['confidence_grade']}** | {short(str(r.get('notes', '')), 50)} |"
        )
    md.append("")
    md.append("### 4.2 PAPER_FIRST (0.5× notional, validate live before scaling)")
    md.append("")
    md.append("| # | Sleeve | Asset/TF | Offset | n | WR | $/tr | sum/28d | Grade | Notes |")
    md.append("|--:|---|---|---|--:|--:|--:|--:|---|---|")
    for i, (_, r) in enumerate(paper.iterrows(), 1):
        md.append(
            f"| {i} | `{r['sleeve_id']}` | {r['asset']} {r['tf']} | {r['offset_range_s']} | "
            f"{fmt_int(r['n_total'])} | {fmt_pct(r['wr_total'])} | {fmt_dpt(r['dollar_per_trade'])} | "
            f"{fmt_money(r['sum_pnl_28d'])} | **{r['confidence_grade']}** | {short(str(r.get('notes', '')), 70)} |"
        )
    md.append("")
    md.append("### 4.3 R7 WS-poly2 PAPER_FIRST candidates (pending 2nd lockbox)")
    md.append("")
    md.append("Per Agent WW: replace binary AND with weighted-scoring Logistic Poly2 on these 7 sleeves. Pairwise Jaccard <0.30 (vs 0.4-1.0 for AND clusters) — all 7 add orthogonal alpha. 2.3× lift vs PP-R6 on common 4d window.")
    md.append("")
    ws = df[df["sleeve_id"].str.startswith("R7_WS_", na=False)].sort_values("sum_pnl_28d", ascending=False)
    md.append("| Sleeve | Asset/TF | n | WR | $/tr | sum/28d | n_lock | WR_lock | sum_lock | Grade |")
    md.append("|---|---|--:|--:|--:|--:|--:|--:|--:|---|")
    for _, r in ws.iterrows():
        md.append(
            f"| `{r['sleeve_id']}` | {r['asset']} {r['tf']} | {fmt_int(r['n_total'])} | {fmt_pct(r['wr_total'])} | "
            f"{fmt_dpt(r['dollar_per_trade'])} | {fmt_money(r['sum_pnl_28d'])} | "
            f"{fmt_int(r['n_lockbox'])} | {fmt_pct(r['wr_lockbox'])} | {fmt_money(r['sum_lockbox'])} | "
            f"**{r['confidence_grade']}** |"
        )
    md.append("")
    md.append("**Operational note**: WS-poly2 inference needs ~52 continuous features at fire_us. Production tradingvenue has ~30 of these. Productionizing requires (a) backfill continuous values into Tier-1 cache OR (b) live-compute at fire decision (5-50ms add). Inference itself is microseconds (~150 polynomial features × scalar weights).")
    md.append("")
    md.append("**Calibration note**: S6 sleeves (BTC/ETH/SOL S6) are poorly calibrated (reliability error 0.17-0.31). Isotonic regression fixes calibration but lowers PnL 3.8%. For initial deploy: keep uncalibrated thresholds.")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## 5. DO-NOT-DEPLOY list")
    md.append("")
    md.append("### 5.1 SKIP_NEGATIVE_PNL (would lose money in OOS)")
    md.append("")
    md.append("| Sleeve | Round | Asset/TF | Reason | OOS sum |")
    md.append("|---|---|---|---|--:|")
    skip_neg = skips[skips["deploy_status"] == "SKIP_NEGATIVE_PNL"].sort_values(
        "sum_pnl_28d", na_position="last"
    ).head(30)
    for _, r in skip_neg.iterrows():
        md.append(
            f"| `{short(str(r['sleeve_id']), 60)}` | {r['discovery_round']} | "
            f"{r['asset']} {r['tf']} | OOS PnL negative | {fmt_money(r['sum_lockbox'])} |"
        )
    md.append("")
    md.append("### 5.2 SKIP_OVERLAP (≥ 90% identical fires to a higher-priority sleeve)")
    md.append("")
    md.append("| Sleeve | Round | Asset/TF | Overlap% with primary | Notes |")
    md.append("|---|---|---|--:|---|")
    skip_ov = skips[skips["deploy_status"] == "SKIP_OVERLAP"]
    for _, r in skip_ov.iterrows():
        md.append(
            f"| `{r['sleeve_id']}` | {r['discovery_round']} | "
            f"{r['asset']} {r['tf']} | {fmt_pct(r['slug_overlap_pct_with_primary'])} | "
            f"{short(str(r.get('notes', '')), 70)} |"
        )
    md.append("")
    md.append("### 5.3 Specifically flagged by audit agents")
    md.append("")
    md.append("- **R2 SMS standalone** — R3 OOS collapse from $20.68/tr → $0.14/tr (`05_btc_5m_off120_sms_liq`). Single gate vs validation collapses.")
    md.append("- **R2 SOL DRZ res_down** — -$35,730 lockbox (`14_sol_5m_drz_res_down`). Direction-pick inverted on fresh data.")
    md.append("- **R2 BTC xa_down** — cross-asset inverted (`09_btc_5m_xa_down`). -$8,869 OOS.")
    md.append("- **R4 trend_slope 15m sleeves (4)** — passed R4 walk-forward but failed R6 lockbox: `R4_ETH_15m_60_120_trstack_trendslope` (-$110), `R4_POOL_15m_120_240_trendslope` (-$1,120), `R4_POOL_15m_240_360_trendslope_vwap` (-$2,268), and `R5_btc_s15_v1_plus_mp_no_extreme` (marginal $0).")
    md.append("- **R5 Hawkes ETH** — asymmetric. BTC hawkes works, ETH hawkes fails OOS (-$468). Per Agent VV anomaly flag.")
    md.append("- **R5 ETH S6 + mp_no_extreme** — overfit (-$309 OOS, despite passing R5 strict).")
    md.append("- **R5 BTC S6 + lm_high_stat** — n=8 insufficient, lockbox -$7. Per Agent NN check.")
    md.append("- **R7 anomalies** flagged by Agent VV in cleanup: `R5_eth_s6_v1_plus_mp_change_with` (marginal -$102), `R5_hawkes_sol_5m_off120` (marginal -$207). Both currently DEPLOY in manifest but should demote to PAPER_FIRST.")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## 6. Deployable summary by notional and asset/tf")
    md.append("")
    md.append("### 6.1 Combined deploy roster — slug-overlap deduplicated")
    md.append("")
    md.append("Mode A (greedy union of 12 DEPLOY sleeves + 4 PAPER_FIRST at 0.5×):")
    md.append("")
    md.append("| Component | $/28d @ $25 | $/28d @ $250 | $/year @ $250 |")
    md.append("|---|--:|--:|--:|")
    md.append("| Mode A union (12 DEPLOY) | $19,023 | $190,225 | $2,478,200 |")
    md.append("| S2 fade BTC/ETH (paper-first, 0.5×) | $1,229 | $12,292 | $160,143 |")
    md.append("| R1 lite/top2 paper-first (0.5× marginal) | $249 | $2,493 | $32,484 |")
    md.append("| **REALISTIC COMBINED** | **$20,501** | **$205,010** | **$2,672,455** |")
    md.append("")
    md.append("### 6.2 Per-asset/tf breakdown (DEPLOY sleeves only)")
    md.append("")
    md.append("| Asset | TF | n DEPLOY | sum_28d @ $25 | sum_28d @ $250 | Top sleeve |")
    md.append("|---|---|--:|--:|--:|---|")
    dep = df[df["deploy_status"] == "DEPLOY"].copy()
    for (asset, tf), grp in dep.groupby(["asset", "tf"]):
        if grp["sum_pnl_28d"].sum() <= 0:
            continue
        top = grp.sort_values("sum_pnl_28d", ascending=False).iloc[0]["sleeve_id"]
        total = grp["sum_pnl_28d"].sum()
        md.append(
            f"| {asset} | {tf} | {len(grp)} | {fmt_money(total)} | {fmt_money(total * 10)} | `{short(top, 50)}` |"
        )
    md.append("")
    md.append("### 6.3 R7 WS-poly2 upside (if 2nd lockbox confirms)")
    md.append("")
    md.append("| Scope | $/28d @ $25 | $/28d @ $250 | $/year @ $250 |")
    md.append("|---|--:|--:|--:|")
    md.append("| Conservative (post-dedup OOS Mode A) | $127,628 | $1,276,280 | $16.6M |")
    md.append("| 4-day lockbox extrap (fragile) | $314,225 | $3,142,250 | $40.8M |")
    md.append("| Unanimity mode (Mode C, ~75% fewer fires) | $53,000 | $530,000 | $6.9M |")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## 7. Operational notes per deploy sleeve")
    md.append("")
    md.append("### 7.1 Phase 1 — DEPLOY (Week 1-2)")
    md.append("")
    md.append("1. **`R2_btc_5m_s1_5_3bps`** — highest single sum_28d ($7,055). 3-gate stack (`g_within_dev&g_rf_strong&g_ribbon_agrees`). 57% overlap with primary BTC universe so marginal contribution is $1,767.")
    md.append("2. **`R5_microprice_univ_5m_rf_ribbon`** — large-n volume play ($6,697). Uses microprice no-extreme + rf_with + ribbon. ⚠ Note: marginal is -$718 (PnL on slugs not already claimed is negative). Keep in DEPLOY only because it's the orthogonal microstructure signal — review after 14d.")
    md.append("3. **`S7_btc_5m_base`** — Cyclops base ($5,674). Offset 120-300 distinguishes it from S6 cluster.")
    md.append("4. **`R1_eth_5m_s6_tight_pos_cloud`** — BEST DIVERSIFIER, +$3,569 marginal (20.5% overlap). The single highest-marginal-PnL ETH sleeve.")
    md.append("5. **`poly_updown_btc_5m_s6_hybrid_v1`** — current production sleeve, $4,266. 96% overlap with primary — marginal only $273 but it IS the current production code path.")
    md.append("6. **`poly_updown_btc_5m_s15_hybrid_v1`** — BTC S15 extension to longer offset (150-240s), $3,250. Marginal +$1,163.")
    md.append("7. **`poly_updown_sol_5m_s6_hybrid_v1`** — SOL asset-disjoint, +$876 marginal. WR 71.0%.")
    md.append("8. **`R5_btc_s15_v1_plus_mp_no_extreme`** — $2,029 in-sample, marginal $0 (100% overlap). Effectively a quality overlay on existing S15.")
    md.append("9. **`R5_hawkes_btc_5m_off120`** — Hawkes BTC, $1,001. 83% overlap (BTC universe) but +$85 marginal.")
    md.append("10. **`R5_eth_s6_v1_plus_mp_change_with`** — $566 in-sample but marginal -$102 (would LOSE money on slugs not already claimed). **DEMOTE to PAPER_FIRST.**")
    md.append("11. **`R5_hawkes_sol_5m_off120`** — $231 in-sample but marginal -$207. **DEMOTE to PAPER_FIRST.**")
    md.append("12. **`R4_POOL_15m_600_720_ribbon_slope_vwap`** — only 15m survivor. $199, 0% overlap (15m is fully disjoint from 5m universe).")
    md.append("")
    md.append("### 7.2 Phase 2 — PAPER_FIRST (Week 3-4)")
    md.append("")
    md.append("- **`S2_fade_momo_btc_mag2_0`** / **`_eth_mag2_0`** — contrarian (fires on momo exhaustion). 0% overlap with momo sleeves by construction. n=299/202 small, paper first at 0.5× notional.")
    md.append("- **`R1_btc_5m_s6_lite/top2`** — large in-sample sum ($6,534/$6,239) but 85-97% overlap with the deployed S6 family. Marginal $350/$149 only. Paper-first at 0.5× to confirm overlap math.")
    md.append("- **R7 WS-poly2 sleeves (7)** — see §4.3. PAPER_FIRST until 2nd lockbox.")
    md.append("- **R7 BTC S15 + Asia-session filter** — +$0.25/tr on existing S15 ema800. PAPER_FIRST.")
    md.append("")
    md.append("### 7.3 Phase 3 — Operational improvements (no new sleeves needed)")
    md.append("")
    md.append("- **S3 HoD refresh** on existing 11 production sleeves → +$15,900/28d. 5-min config edit, zero new code. Highest-leverage operation available.")
    md.append("- **S2 Fade Momo BTC patch** in `momo.py` (4-line edit) → +$1,216/28d.")
    md.append("- **B.7.1 sleeve #2 fix** (drop m5va) → +$745/28d.")
    md.append("- **R7 global threshold recalibration**: g_mp_no_extreme 50bps→100bps, g_hawkes_imb 0.3→0.15, g_hurst_trending 0.55→0.50, g_vol_contracting 0.7→0.85. Apply to ALL existing sleeves: +$3-5k/28d aggregate.")
    md.append("")
    md.append("### 7.4 Universal operational caveats")
    md.append("")
    md.append("- **`book_walk_fill` fill quality** at $250 notional: needs verification that L25 mid-quote depth supports fills at projected rates. Current $25 deploy is comfortably within depth.")
    md.append("- **S6 calibration** is poor — production sleeves are trained on uncalibrated probabilities. Isotonic regression improves calibration but lowers PnL. Keep current.")
    md.append("- **Weekly auto-revalidation** pipeline: use `migration_2026_05_25/{pull_delta, convert_and_merge, merge_to_canonical}` cadence. Refresh canonical every Monday, re-run R6 dedup + lockbox audit, demote any sleeve whose 7-day rolling sum goes negative.")
    md.append("- **Lockbox cadence**: rotate the 4d lockbox forward by 7d weekly (sliding window). A sleeve must pass 2 consecutive lockboxes to keep DEPLOY status.")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## 8. Discovery rounds — quick reference")
    md.append("")
    md.append("| Round | Theme | # sleeves catalogued | Best contribution |")
    md.append("|---|---|--:|---|")
    md.append(f"| R1 | Initial hybrid + S2/S5/S6/S7/S15 base | {by_round.get('R1', 0) + by_round.get('R1-R5', 0)} | R1 ETH S6 tight_pos_cloud (best diversifier) |")
    md.append(f"| R2 | Hybrid stacking + cross-asset RF | {by_round.get('R2', 0)} | R2 BTC S1.5 3bps (top single contributor) |")
    md.append(f"| R3 | DRZ/QR/SMS walk-forward | {by_round.get('R3', 0)} | DRZ A_standalone variants (R3 DRZ_015 = $14k/28d) |")
    md.append(f"| R4 | 178 trend_slope 15m sweep + sleeve hunt | {by_round.get('R4', 0)} | POOL 15m 600-720 (only 15m DEPLOY survivor) |")
    md.append(f"| R5 | Microstructure (microprice/LM/Hawkes/VPIN) | {by_round.get('R5', 0)} | Microprice univ_5m_rf_ribbon, Hawkes BTC off120 |")
    md.append(f"| R6 | Master combinatorial + slug-overlap audit | {by_round.get('R6', 0)} | THE DEDUP AUDIT — $20.5k/28d truth |")
    md.append(f"| R7 | Cross-cut: regime/threshold/asymmetric/voting/session | {by_round.get('R7', 0)} | TT WS-poly2 weighted-scoring (17× lockbox lift, post-dedup 2.3×) |")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## 9. Files inventory")
    md.append("")
    md.append("### Authoritative")
    md.append("- **`data/v4/canonical/_results/master_sleeve_catalog_audited.csv`** — this catalog (all R1-R7 sleeves, normalized).")
    md.append("- **`data/v4/canonical/_results/final_deploy_manifest.csv`** — R6 PP dedup manifest (26 rows).")
    md.append("- **`strategy_lab/ws_poly2_dedup_2026_05_26/final_deploy_manifest_v2.csv`** — R7 WW combined WS+PP manifest.")
    md.append("- **`strategy_lab/reports/ROUND6_SYNTHESIS_2026_05_26.md`** — overlap audit narrative.")
    md.append("- **`strategy_lab/reports/ROUND7_SYNTHESIS_2026_05_26.md`** — cross-cut synthesis.")
    md.append("- **`strategy_lab/reports/SLUG_OVERLAP_DEPLOY_MANIFEST_2026_05_26.md`** — Agent PP methodology.")
    md.append("- **`strategy_lab/reports/WS_POLY2_DEDUP_VALIDATION_2026_05_26.md`** — Agent WW validation.")
    md.append("- **`strategy_lab/reports/NAIVE_SUM_CORRECTIONS_2026_05_26.md`** — corrections single-source-of-truth.")
    md.append("- **`strategy_lab/reports/FINAL_DEPLOY_READY_2026_05_26.pdf`** — deploy doc (cover number matches this catalog).")
    md.append("")
    md.append("### Source CSVs by round")
    md.append("- R1: `hybrid_gate_search.csv`, `new_sleeves_per_sleeve_metrics.csv`, `fade_momo_5m.csv`, `z_contra_5m.csv`, `spike_entry_5m.csv`")
    md.append("- R2: `sleeve_hunt_15m_deployable.csv`, `new_indicator_sleeves_per_market.csv`, `new_indicator_sleeves_15m.csv`")
    md.append("- R3: `drz_walk_forward.csv`, `qr_walk_forward.csv`, `sms_walk_forward.csv`")
    md.append("- R4: `full_window_all_sleeves_results.csv`, `sleeve_hunt_15m_v2_deployable.csv`, `full_window_gate_search.csv`")
    md.append("- R5: `microprice_panel.parquet`, `lee_mykland_panel.parquet`, `vpin_hawkes_validation_HA.csv`")
    md.append("- R6: `final_deploy_manifest.csv`, `master_combinatorial_deployable.csv`, `_overlap_audit_2026_05_26/`")
    md.append("- R7: `weighted_voting_2026_05_26/`, `ws_poly2_dedup_2026_05_26/`, `threshold_sweep.csv`, `direction_asymmetric_stacks.csv`, `regime_*.csv`")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## 10. Action items for next session")
    md.append("")
    md.append("1. **Demote 2 sleeves to PAPER_FIRST** in manifest (per Agent VV): `R5_eth_s6_v1_plus_mp_change_with`, `R5_hawkes_sol_5m_off120`.")
    md.append("2. **Run 2nd lockbox** on WS-poly2 (rotate window forward 7d). Confirm or reject the 11.6× val→lockbox step-up.")
    md.append("3. **Apply R7 global threshold recalibration** to current production sleeves (5-min config edit).")
    md.append("4. **Apply S3 HoD refresh** on existing 11-sleeve baseline (+$15.9k/28d for free).")
    md.append("5. **Live shadow deploy** Phase 1 (6 sleeves: R2_btc_s1_5_3bps, S7_btc_base, R1_eth_tight_pos_cloud, poly_updown_btc_s6_v1, poly_updown_btc_s15_v1, poly_updown_sol_s6_v1) at $25 notional for 7-14 days.")
    md.append("6. **Set up weekly auto-pull + auto-revalidate** pipeline using `migration_2026_05_25` pattern.")
    md.append("")
    md.append("## End")
    md.append("")

    out_text = "\n".join(md)
    OUT.write_text(out_text, encoding="utf-8")
    print(f"Wrote: {OUT}")
    print(f"  lines: {len(md)}")


if __name__ == "__main__":
    main()
