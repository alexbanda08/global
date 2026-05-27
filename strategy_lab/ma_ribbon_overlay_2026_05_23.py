"""MA Ribbon overlay analysis on S1.5 + S6 fires (2026-05-23).

Tests whether Madrid Ribbon (20 EMAs 5..100) improves WR on existing S1.5/S6 sleeves.

Inputs:
  - data/v4/canonical/_results/s15_with_ta.parquet (33,323 fires)
  - data/v4/canonical/_results/s6_with_ta.parquet  (11,336 fires)

Outputs:
  - data/v4/canonical/_results/ma_ribbon_overlay.csv  (long-form bucket stats)
  - strategy_lab/reports/MA_RIBBON_OVERLAY_2026_05_23.md
"""
from __future__ import annotations

import os
import sys
import math
import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
S15 = ROOT / "data/v4/canonical/_results/s15_with_ta.parquet"
S6  = ROOT / "data/v4/canonical/_results/s6_with_ta.parquet"
OUT_CSV = ROOT / "data/v4/canonical/_results/ma_ribbon_overlay.csv"
OUT_MD  = ROOT / "strategy_lab/reports/MA_RIBBON_OVERLAY_2026_05_23.md"

UP_COLORS   = {1, 4}   # lime, green
DOWN_COLORS = {2, 3}   # maroon, red

def load() -> tuple[pd.DataFrame, pd.DataFrame]:
    s15 = pd.read_parquet(S15)
    s6  = pd.read_parquet(S6)
    # Coerce ribbon_color to int (S1.5 has nans)
    for df in (s15, s6):
        df['ribbon_color'] = df['ribbon_color'].astype('Int64')
    # Drop rows missing ribbon (very few)
    s15 = s15.dropna(subset=['ribbon_color','ribbon_alignment_pct','ribbon_compression_bps']).copy()
    s6  = s6.dropna(subset=['ribbon_color','ribbon_alignment_pct','ribbon_compression_bps']).copy()
    s15['ribbon_color'] = s15['ribbon_color'].astype(int)
    s6['ribbon_color']  = s6['ribbon_color'].astype(int)
    # Build agreement flag
    for df in (s15, s6):
        up_ok   = df['ribbon_color'].isin(list(UP_COLORS))   & (df['direction'] == 'UP')
        down_ok = df['ribbon_color'].isin(list(DOWN_COLORS)) & (df['direction'] == 'DOWN')
        df['ribbon_agrees'] = (up_ok | down_ok).astype(bool)
        # Direction implied by color
        df['ribbon_dir']  = np.where(df['ribbon_color'].isin(list(UP_COLORS)), 'UP',
                              np.where(df['ribbon_color'].isin(list(DOWN_COLORS)), 'DOWN', 'NA'))
    return s15, s6


def color_label(c: int) -> str:
    return {0:'gray',1:'lime',2:'maroon',3:'red',4:'green'}.get(int(c), str(c))


def agg_stats(df: pd.DataFrame) -> dict:
    n = len(df)
    if n == 0:
        return dict(n=0, wins=0, wr=np.nan, mean_pnl=np.nan, sum_pnl=0.0, med_pnl=np.nan)
    wins = int(df['won'].sum())
    return dict(
        n=n,
        wins=wins,
        wr=wins/n,
        mean_pnl=float(df['pnl_legacy_usd'].mean()),
        sum_pnl=float(df['pnl_legacy_usd'].sum()),
        med_pnl=float(df['pnl_legacy_usd'].median()),
    )


def bucket_alignment(v: float) -> str:
    if v < 25:   return '00-25'
    if v < 50:   return '25-50'
    if v < 75:   return '50-75'
    if v < 95:   return '75-95'
    return '95-100'


def bucket_compression(v: float) -> str:
    if v < 2:    return '<2'
    if v < 5:    return '2-5'
    if v < 10:   return '5-10'
    if v < 20:   return '10-20'
    return '>20'


def long_rows(rows: list[dict], sleeve: str, analysis: str, df: pd.DataFrame, group_cols: list[str]) -> None:
    """Append per-bucket stats to rows. group_cols is list of bucket dimensions."""
    for keys, sub in df.groupby(group_cols, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        s = agg_stats(sub)
        rec = dict(sleeve=sleeve, analysis=analysis)
        for k, v in zip(group_cols, keys):
            rec[k] = v
        rec.update(s)
        rows.append(rec)


def main():
    s15, s6 = load()
    print(f"S15 loaded: {len(s15):,} fires after dropna")
    print(f"S6  loaded: {len(s6):,} fires after dropna")

    rows: list[dict] = []

    # -----------------------------
    # ANALYSIS A: color x direction
    # -----------------------------
    for sleeve, df in [('S1.5', s15), ('S6', s6)]:
        df = df.copy()
        df['color_label'] = df['ribbon_color'].map(color_label)
        long_rows(rows, sleeve, 'color_direction', df, ['asset', 'color_label', 'direction'])
        # Global (all-asset) color x direction
        long_rows(rows, sleeve, 'color_direction_all', df, ['color_label', 'direction'])

    # -----------------------------
    # ANALYSIS B: alignment tiers
    # -----------------------------
    for sleeve, df in [('S1.5', s15), ('S6', s6)]:
        df = df.copy()
        df['align_tier'] = df['ribbon_alignment_pct'].map(bucket_alignment)
        long_rows(rows, sleeve, 'alignment_x_asset', df, ['asset', 'align_tier'])
        long_rows(rows, sleeve, 'alignment_x_agree', df, ['align_tier', 'ribbon_agrees'])
        long_rows(rows, sleeve, 'alignment_all',    df, ['align_tier'])

    # -----------------------------
    # ANALYSIS C: compression tiers
    # -----------------------------
    for sleeve, df in [('S1.5', s15), ('S6', s6)]:
        df = df.copy()
        df['compr_tier'] = df['ribbon_compression_bps'].map(bucket_compression)
        long_rows(rows, sleeve, 'compression_x_asset', df, ['asset', 'compr_tier'])
        long_rows(rows, sleeve, 'compression_x_agree', df, ['compr_tier', 'ribbon_agrees'])
        long_rows(rows, sleeve, 'compression_all',    df, ['compr_tier'])

    # -----------------------------
    # ANALYSIS D: ribbon_agrees gate
    # -----------------------------
    for sleeve, df in [('S1.5', s15), ('S6', s6)]:
        long_rows(rows, sleeve, 'agree_x_asset', df, ['asset', 'ribbon_agrees'])
        long_rows(rows, sleeve, 'agree_all',    df, ['ribbon_agrees'])

    # -----------------------------
    # ANALYSIS E: per-config gate boost (configs = asset+fire_offset+tier dim)
    # -----------------------------
    boost_rows = []

    # S1.5: bucket by asset + fire_offset + dev_tier
    s15c = s15.copy()
    def dev_tier(v):
        a = abs(v)
        if a < 5: return '0-5'
        if a < 10: return '5-10'
        if a < 20: return '10-20'
        if a < 30: return '20-30'
        return '30+'
    s15c['dev_tier'] = s15c['dev_bps_vwap'].map(dev_tier)
    for (asset, foff, dev), sub in s15c.groupby(['asset','fire_offset_s','dev_tier']):
        base = agg_stats(sub)
        gated = agg_stats(sub[sub['ribbon_agrees']])
        excl  = agg_stats(sub[~sub['ribbon_agrees']])
        if base['n'] >= 30 and gated['n'] >= 30:
            boost_rows.append(dict(
                sleeve='S1.5', asset=asset, fire_offset_s=foff, tier=dev,
                n_base=base['n'], wr_base=base['wr'], pnl_base=base['mean_pnl'], sum_base=base['sum_pnl'],
                n_gated=gated['n'], wr_gated=gated['wr'], pnl_gated=gated['mean_pnl'], sum_gated=gated['sum_pnl'],
                n_excl=excl['n'], wr_excl=excl['wr'], pnl_excl=excl['mean_pnl'],
                wr_delta_pp=(gated['wr']-base['wr'])*100 if not math.isnan(gated['wr']) else np.nan,
                pnl_delta=gated['mean_pnl']-base['mean_pnl'] if not math.isnan(gated['mean_pnl']) else np.nan,
            ))

    # S6: bucket by asset + fire_offset + tier (definition tier already in col)
    s6c = s6.copy()
    if 'tier' in s6c.columns:
        s6c['tier_str'] = s6c['tier'].astype(str)
    else:
        s6c['tier_str'] = 'ALL'
    for (asset, foff, tier), sub in s6c.groupby(['asset','fire_offset_s','tier_str']):
        base = agg_stats(sub)
        gated = agg_stats(sub[sub['ribbon_agrees']])
        excl  = agg_stats(sub[~sub['ribbon_agrees']])
        if base['n'] >= 30 and gated['n'] >= 30:
            boost_rows.append(dict(
                sleeve='S6', asset=asset, fire_offset_s=foff, tier=tier,
                n_base=base['n'], wr_base=base['wr'], pnl_base=base['mean_pnl'], sum_base=base['sum_pnl'],
                n_gated=gated['n'], wr_gated=gated['wr'], pnl_gated=gated['mean_pnl'], sum_gated=gated['sum_pnl'],
                n_excl=excl['n'], wr_excl=excl['wr'], pnl_excl=excl['mean_pnl'],
                wr_delta_pp=(gated['wr']-base['wr'])*100 if not math.isnan(gated['wr']) else np.nan,
                pnl_delta=gated['mean_pnl']-base['mean_pnl'] if not math.isnan(gated['mean_pnl']) else np.nan,
            ))

    boost_df = pd.DataFrame(boost_rows)
    print("Boost configs evaluated:", len(boost_df))

    # -----------------------------
    # ANALYSIS F: ULTRA-strict candidates
    # -----------------------------
    ultra = []
    if len(boost_df):
        ultra_mask = (boost_df['n_gated'] >= 50) & (boost_df['wr_gated'] >= 0.80) & (boost_df['pnl_gated'] >= 1.0)
        ultra = boost_df[ultra_mask].sort_values('pnl_gated', ascending=False)

    # Write long CSV
    long_df = pd.DataFrame(rows)
    # also append boost stats as analysis='config_boost'
    if len(boost_df):
        bd = boost_df.copy()
        bd['sleeve'] = bd['sleeve']
        bd['analysis'] = 'config_boost'
        # rename for unified schema
        long_df = pd.concat([long_df, bd.assign(
            n=bd['n_gated'], wr=bd['wr_gated'], mean_pnl=bd['pnl_gated'], sum_pnl=bd['sum_gated'],
        )], ignore_index=True)

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    long_df.to_csv(OUT_CSV, index=False)
    print("Wrote", OUT_CSV, "rows=", len(long_df))

    # ===============================
    # Build markdown report
    # ===============================
    md = []
    md.append("# MA Ribbon Overlay on S1.5 / S6 Fires — 2026-05-23")
    md.append("")
    md.append("**Inputs**: `s15_with_ta.parquet` (33,323 fires after dropna={}); `s6_with_ta.parquet` (11,336 fires after dropna={})."
              .format(len(s15), len(s6)))
    md.append("")
    md.append("**Color encoding**: 0=gray, 1=lime (lead-up + above ref), 2=maroon (lead-down + above ref), "
              "3=red (lead-down + below ref), 4=green (lead-up + below ref).  "
              "**UP-colors** = {lime, green}.  **DOWN-colors** = {maroon, red}.")
    md.append("")

    # Headline
    s15_base_wr = s15['won'].mean()
    s6_base_wr  = s6['won'].mean()
    s15_agree = s15[s15['ribbon_agrees']]
    s15_disagr = s15[~s15['ribbon_agrees']]
    s6_agree = s6[s6['ribbon_agrees']]
    s6_disagr = s6[~s6['ribbon_agrees']]
    md.append("## Headline")
    md.append("")
    md.append("| Sleeve | n | Baseline WR | WR agree | WR disagree | Δ (agree − disagree) | Δ (agree − baseline) |")
    md.append("|---|---|---|---|---|---|---|")
    md.append(f"| S1.5 | {len(s15):,} | {s15_base_wr*100:.2f}% | {s15_agree['won'].mean()*100:.2f}% (n={len(s15_agree):,}) | {s15_disagr['won'].mean()*100:.2f}% (n={len(s15_disagr):,}) | **{(s15_agree['won'].mean()-s15_disagr['won'].mean())*100:+.2f} pp** | {(s15_agree['won'].mean()-s15_base_wr)*100:+.2f} pp |")
    md.append(f"| S6   | {len(s6):,} | {s6_base_wr*100:.2f}%  | {s6_agree['won'].mean()*100:.2f}% (n={len(s6_agree):,})  | {s6_disagr['won'].mean()*100:.2f}% (n={len(s6_disagr):,}) | **{(s6_agree['won'].mean()-s6_disagr['won'].mean())*100:+.2f} pp** | {(s6_agree['won'].mean()-s6_base_wr)*100:+.2f} pp |")
    md.append("")
    md.append("| Sleeve | $/tr agree | $/tr disagree | sum agree | sum disagree |")
    md.append("|---|---|---|---|---|")
    md.append(f"| S1.5 | ${s15_agree['pnl_legacy_usd'].mean():.3f} | ${s15_disagr['pnl_legacy_usd'].mean():.3f} | ${s15_agree['pnl_legacy_usd'].sum():,.0f} | ${s15_disagr['pnl_legacy_usd'].sum():,.0f} |")
    md.append(f"| S6   | ${s6_agree['pnl_legacy_usd'].mean():.3f} | ${s6_disagr['pnl_legacy_usd'].mean():.3f} | ${s6_agree['pnl_legacy_usd'].sum():,.0f} | ${s6_disagr['pnl_legacy_usd'].sum():,.0f} |")
    md.append("")

    # Verdict
    s15_lift = (s15_agree['won'].mean() - s15_disagr['won'].mean()) * 100
    s6_lift  = (s6_agree['won'].mean()  - s6_disagr['won'].mean())  * 100
    s15_pnl_lift = s15_agree['pnl_legacy_usd'].mean() - s15_disagr['pnl_legacy_usd'].mean()
    s6_pnl_lift  = s6_agree['pnl_legacy_usd'].mean()  - s6_disagr['pnl_legacy_usd'].mean()
    def verdict_line(name, wr_pp, pnl_d, n_agree):
        if abs(wr_pp) < 1 and abs(pnl_d) < 0.05:
            return f"- **{name}**: ribbon color is **NOT predictive** at sleeve level (Δ WR = {wr_pp:+.2f} pp, Δ $/tr = ${pnl_d:+.3f})."
        elif wr_pp > 0:
            return f"- **{name}**: ribbon **AGREES = HIGHER WR** (+{wr_pp:.2f} pp, +${pnl_d:.3f}/tr on n={n_agree:,}). Gate is useful."
        else:
            return f"- **{name}**: ribbon agreement **HURTS** WR ({wr_pp:+.2f} pp, ${pnl_d:+.3f}/tr). Counter-intuitive — investigate."
    md.append("### Verdict")
    md.append(verdict_line("S1.5", s15_lift, s15_pnl_lift, len(s15_agree)))
    md.append(verdict_line("S6",   s6_lift,  s6_pnl_lift,  len(s6_agree)))
    md.append("")

    # ===========================
    # Per-asset color x direction
    # ===========================
    for sleeve, df in [('S1.5', s15), ('S6', s6)]:
        md.append(f"## {sleeve}: color × direction × asset")
        md.append("")
        md.append("| asset | color | direction | n | WR | $/tr | sum |")
        md.append("|---|---|---|---|---|---|---|")
        df = df.copy()
        df['color_label'] = df['ribbon_color'].map(color_label)
        for (asset, color, drn), sub in df.groupby(['asset','color_label','direction']):
            if len(sub) < 30:
                continue
            s = agg_stats(sub)
            md.append(f"| {asset} | {color} | {drn} | {s['n']:,} | {s['wr']*100:.2f}% | ${s['mean_pnl']:.3f} | ${s['sum_pnl']:,.0f} |")
        md.append("")

    # ===========================
    # Alignment tiers
    # ===========================
    for sleeve, df in [('S1.5', s15), ('S6', s6)]:
        md.append(f"## {sleeve}: alignment tier × ribbon_agrees")
        md.append("")
        md.append("| tier | agrees | n | WR | $/tr | sum |")
        md.append("|---|---|---|---|---|---|")
        df = df.copy()
        df['align_tier'] = df['ribbon_alignment_pct'].map(bucket_alignment)
        for (tier, agr), sub in df.groupby(['align_tier','ribbon_agrees']):
            s = agg_stats(sub)
            if s['n'] < 20:
                continue
            md.append(f"| {tier} | {'Y' if agr else 'N'} | {s['n']:,} | {s['wr']*100:.2f}% | ${s['mean_pnl']:.3f} | ${s['sum_pnl']:,.0f} |")
        md.append("")
        # Per-asset alignment for sleeve (only top tiers)
        md.append(f"### {sleeve}: alignment tier × asset (agreeing fires only)")
        md.append("")
        md.append("| asset | tier | n | WR | $/tr | sum |")
        md.append("|---|---|---|---|---|---|")
        sub_ag = df[df['ribbon_agrees']]
        for (asset, tier), sub in sub_ag.groupby(['asset','align_tier']):
            if len(sub) < 30:
                continue
            s = agg_stats(sub)
            md.append(f"| {asset} | {tier} | {s['n']:,} | {s['wr']*100:.2f}% | ${s['mean_pnl']:.3f} | ${s['sum_pnl']:,.0f} |")
        md.append("")

    # ===========================
    # Compression tiers
    # ===========================
    for sleeve, df in [('S1.5', s15), ('S6', s6)]:
        md.append(f"## {sleeve}: compression tier × ribbon_agrees")
        md.append("")
        md.append("| tier (bps) | agrees | n | WR | $/tr | sum |")
        md.append("|---|---|---|---|---|---|")
        df = df.copy()
        df['compr_tier'] = df['ribbon_compression_bps'].map(bucket_compression)
        for (tier, agr), sub in df.groupby(['compr_tier','ribbon_agrees']):
            s = agg_stats(sub)
            if s['n'] < 20:
                continue
            md.append(f"| {tier} | {'Y' if agr else 'N'} | {s['n']:,} | {s['wr']*100:.2f}% | ${s['mean_pnl']:.3f} | ${s['sum_pnl']:,.0f} |")
        md.append("")
        md.append(f"### {sleeve}: compression tier × asset (agreeing fires only)")
        md.append("")
        md.append("| asset | tier (bps) | n | WR | $/tr | sum |")
        md.append("|---|---|---|---|---|---|")
        sub_ag = df[df['ribbon_agrees']]
        for (asset, tier), sub in sub_ag.groupby(['asset','compr_tier']):
            if len(sub) < 30:
                continue
            s = agg_stats(sub)
            md.append(f"| {asset} | {tier} | {s['n']:,} | {s['wr']*100:.2f}% | ${s['mean_pnl']:.3f} | ${s['sum_pnl']:,.0f} |")
        md.append("")

    # ===========================
    # TOP 10 boost configs
    # ===========================
    md.append("## Top configs where ribbon_agrees gate boosts WR by ≥3pp (n_gated ≥ 30)")
    md.append("")
    if len(boost_df):
        candidates = boost_df[(boost_df['wr_delta_pp'] >= 3.0) & (boost_df['n_gated'] >= 30)].copy()
        candidates = candidates.sort_values(['wr_delta_pp','sum_gated'], ascending=[False, False]).head(10)
        if len(candidates) == 0:
            md.append("_No configs found with ≥3pp lift and n_gated ≥ 30._")
        else:
            md.append("| sleeve | asset | fire_offset | tier | n_base | WR_base | n_gated | WR_gated | Δ pp | $/tr_gated | sum_gated |")
            md.append("|---|---|---|---|---|---|---|---|---|---|---|")
            for _, r in candidates.iterrows():
                md.append(f"| {r['sleeve']} | {r['asset']} | {int(r['fire_offset_s'])} | {r['tier']} | {int(r['n_base'])} | {r['wr_base']*100:.2f}% | {int(r['n_gated'])} | {r['wr_gated']*100:.2f}% | **{r['wr_delta_pp']:+.2f}** | ${r['pnl_gated']:.3f} | ${r['sum_gated']:,.0f} |")
    md.append("")
    md.append("## Top 10 configs by total PnL after ribbon_agrees gate (n_gated ≥ 50)")
    md.append("")
    if len(boost_df):
        top_pnl = boost_df[boost_df['n_gated'] >= 50].sort_values('sum_gated', ascending=False).head(10)
        if len(top_pnl):
            md.append("| sleeve | asset | fire_offset | tier | n_gated | WR_gated | Δ pp | $/tr_gated | sum_gated |")
            md.append("|---|---|---|---|---|---|---|---|---|")
            for _, r in top_pnl.iterrows():
                md.append(f"| {r['sleeve']} | {r['asset']} | {int(r['fire_offset_s'])} | {r['tier']} | {int(r['n_gated'])} | {r['wr_gated']*100:.2f}% | {r['wr_delta_pp']:+.2f} | ${r['pnl_gated']:.3f} | ${r['sum_gated']:,.0f} |")
    md.append("")

    # ===========================
    # ULTRA-strict
    # ===========================
    md.append("## ULTRA-strict candidates (n_gated ≥ 50, WR_gated ≥ 80%, $/tr_gated ≥ $1)")
    md.append("")
    if isinstance(ultra, pd.DataFrame) and len(ultra):
        md.append(f"Found **{len(ultra)}** configs.")
        md.append("")
        md.append("| sleeve | asset | fire_offset | tier | n_gated | WR_gated | Δ pp | $/tr_gated | sum_gated |")
        md.append("|---|---|---|---|---|---|---|---|---|")
        for _, r in ultra.head(30).iterrows():
            md.append(f"| {r['sleeve']} | {r['asset']} | {int(r['fire_offset_s'])} | {r['tier']} | {int(r['n_gated'])} | {r['wr_gated']*100:.2f}% | {r['wr_delta_pp']:+.2f} | ${r['pnl_gated']:.3f} | ${r['sum_gated']:,.0f} |")
    else:
        md.append("_None found._")
    md.append("")

    # ===========================
    # Recommendations
    # ===========================
    md.append("## Deployable gate recommendations")
    md.append("")
    rec_lines = []
    if s15_lift >= 1.0 or s15_pnl_lift >= 0.05:
        rec_lines.append(f"- **S1.5**: add `ribbon_agrees` filter — keeps {len(s15_agree):,}/{len(s15):,} fires "
                         f"({len(s15_agree)/len(s15)*100:.1f}%), WR {s15_agree['won'].mean()*100:.2f}% vs baseline {s15_base_wr*100:.2f}%, "
                         f"$/tr ${s15_agree['pnl_legacy_usd'].mean():.3f} vs ${s15['pnl_legacy_usd'].mean():.3f}.")
    else:
        rec_lines.append(f"- **S1.5**: ribbon_agrees gate yields only {s15_lift:+.2f}pp WR lift / {s15_pnl_lift:+.3f} $/tr — NOT worth the loss of {len(s15_disagr):,} fires.")
    if s6_lift >= 1.0 or s6_pnl_lift >= 0.05:
        rec_lines.append(f"- **S6**: add `ribbon_agrees` filter — keeps {len(s6_agree):,}/{len(s6):,} fires "
                         f"({len(s6_agree)/len(s6)*100:.1f}%), WR {s6_agree['won'].mean()*100:.2f}% vs baseline {s6_base_wr*100:.2f}%, "
                         f"$/tr ${s6_agree['pnl_legacy_usd'].mean():.3f} vs ${s6['pnl_legacy_usd'].mean():.3f}.")
    else:
        rec_lines.append(f"- **S6**: ribbon_agrees gate yields only {s6_lift:+.2f}pp WR lift / {s6_pnl_lift:+.3f} $/tr — NOT worth filter.")

    # Alignment tier rec — pick tier with BEST WR among agreeing fires (n>=50)
    for sleeve, df in [('S1.5', s15), ('S6', s6)]:
        df = df.copy()
        df['align_tier'] = df['ribbon_alignment_pct'].map(bucket_alignment)
        sub_ag = df[df['ribbon_agrees']]
        if len(sub_ag) == 0:
            continue
        align_grp = sub_ag.groupby('align_tier').agg(n=('won','size'), wr=('won','mean'), mean_pnl=('pnl_legacy_usd','mean'), sum_pnl=('pnl_legacy_usd','sum')).reset_index()
        base_wr = df['won'].mean()
        # Best-WR tier (with non-trivial n) and best-$/tr tier
        best_wr   = align_grp[align_grp['n'] >= 50].sort_values('wr', ascending=False).head(1)
        best_pnl  = align_grp[align_grp['n'] >= 50].sort_values('mean_pnl', ascending=False).head(1)
        for _, r in best_wr.iterrows():
            rec_lines.append(f"- **{sleeve} alignment tier {r['align_tier']}% + ribbon_agrees (best WR)**: n={int(r['n']):,}, WR={r['wr']*100:.2f}%, $/tr=${r['mean_pnl']:.3f}, sum=${r['sum_pnl']:,.0f} (vs sleeve baseline {base_wr*100:.2f}% / ${df['pnl_legacy_usd'].mean():.3f}).")
        for _, r in best_pnl.iterrows():
            if best_wr.empty or r['align_tier'] != best_wr.iloc[0]['align_tier']:
                rec_lines.append(f"- **{sleeve} alignment tier {r['align_tier']}% + ribbon_agrees (best $/tr)**: n={int(r['n']):,}, WR={r['wr']*100:.2f}%, $/tr=${r['mean_pnl']:.3f}, sum=${r['sum_pnl']:,.0f}.")

    # Compression tier rec — pick tier with BEST WR among agreeing fires (n>=50)
    for sleeve, df in [('S1.5', s15), ('S6', s6)]:
        df = df.copy()
        df['compr_tier'] = df['ribbon_compression_bps'].map(bucket_compression)
        sub_ag = df[df['ribbon_agrees']]
        if len(sub_ag) == 0:
            continue
        compr_grp = sub_ag.groupby('compr_tier').agg(n=('won','size'), wr=('won','mean'), mean_pnl=('pnl_legacy_usd','mean'), sum_pnl=('pnl_legacy_usd','sum')).reset_index()
        base_wr = df['won'].mean()
        best_wr   = compr_grp[compr_grp['n'] >= 50].sort_values('wr', ascending=False).head(1)
        best_pnl  = compr_grp[compr_grp['n'] >= 50].sort_values('mean_pnl', ascending=False).head(1)
        for _, r in best_wr.iterrows():
            rec_lines.append(f"- **{sleeve} compression {r['compr_tier']}bps + ribbon_agrees (best WR)**: n={int(r['n']):,}, WR={r['wr']*100:.2f}%, $/tr=${r['mean_pnl']:.3f}, sum=${r['sum_pnl']:,.0f}.")
        for _, r in best_pnl.iterrows():
            if best_wr.empty or r['compr_tier'] != best_wr.iloc[0]['compr_tier']:
                rec_lines.append(f"- **{sleeve} compression {r['compr_tier']}bps + ribbon_agrees (best $/tr)**: n={int(r['n']):,}, WR={r['wr']*100:.2f}%, $/tr=${r['mean_pnl']:.3f}, sum=${r['sum_pnl']:,.0f}.")

    md.extend(rec_lines)
    md.append("")
    md.append("## Notes & caveats")
    md.append("")
    md.append("- All PnL uses the legacy 2%-on-profit fee model (production-equivalent per CLAUDE.md verification 2026-05-22).")
    md.append("- Color encoding interpreted per task brief; verify against Pine Script reference if results look inverted.")
    md.append(f"- {33323 - len(s15)} S1.5 rows and {11336 - len(s6)} S6 rows dropped due to missing ribbon features (mostly first-day rows with insufficient EMA warmup).")
    md.append("- `dev_tier` in S1.5 boost analysis = |dev_bps_vwap| binned {0-5, 5-10, 10-20, 20-30, 30+}.")
    md.append("- Long-form CSV at `data/v4/canonical/_results/ma_ribbon_overlay.csv` for further drill-down.")

    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(md), encoding='utf-8')
    print("Wrote", OUT_MD, "lines=", len(md))

    # Print quick summary (ASCII-only for Windows console)
    print("\n=== HEADLINE ===")
    print(f"S1.5: agree WR {s15_agree['won'].mean()*100:.2f}% (n={len(s15_agree):,}) vs disagree WR {s15_disagr['won'].mean()*100:.2f}% (n={len(s15_disagr):,}) | delta={s15_lift:+.2f}pp delta_pnl={s15_pnl_lift:+.3f}")
    print(f"S6:   agree WR {s6_agree['won'].mean()*100:.2f}% (n={len(s6_agree):,}) vs disagree WR {s6_disagr['won'].mean()*100:.2f}% (n={len(s6_disagr):,}) | delta={s6_lift:+.2f}pp delta_pnl={s6_pnl_lift:+.3f}")
    print(f"ULTRA configs: {len(ultra) if isinstance(ultra, pd.DataFrame) else 0}")
    print(f"Boost configs evaluated: {len(boost_df)}")
    if len(boost_df):
        candidates = boost_df[(boost_df['wr_delta_pp'] >= 3.0) & (boost_df['n_gated'] >= 30)]
        print(f"Configs with ≥3pp WR lift: {len(candidates)}")


if __name__ == "__main__":
    main()
