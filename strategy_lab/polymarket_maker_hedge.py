"""
polymarket_maker_hedge.py — extend maker-entry to also place HEDGE as limit (not taker).

Building on polymarket_maker_entry.py:
  - Entry: limit at held_bid+1tick, wait 30s, fallback to taker
  - Hedge (NEW): when rev_bp triggers, limit at other_bid+1tick, wait HEDGE_WAIT_S, fallback to taker

Variants tested:
  T_T  : taker entry, taker hedge (= original baseline, control)
  M_T  : maker entry, taker hedge (= polymarket_maker_entry.py best variant)
  T_M  : taker entry, maker hedge (NEW — isolate hedge effect)
  M_M  : maker entry, maker hedge (NEW — both sides cheap)

Hedge wait window sweep: 20s, 40s, 60s.

Risk: in a real reversal, the OTHER side is rising fast. Maker limit at other_bid+1tick
may not fill, leaving us exposed if we don't fall back to taker.
Therefore ALL maker-hedge variants use fallback_to_taker=True (no skip option).

Reads: features_v3 + trajectories_v3 + binance klines.
Outputs:
  results/polymarket/maker_hedge.csv
  reports/POLYMARKET_MAKER_HEDGE.md
"""
from __future__ import annotations
from pathlib import Path
import sys
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from polymarket_signal_grid_v2 import load_features, load_trajectories, load_klines_1m

RNG = np.random.default_rng(42)
ASSETS = ["btc", "eth", "sol"]
REV_BP = 5
FEE_RATE = 0.02
TICK = 0.01
ENTRY_TICK = 0.01
ENTRY_WAIT_BUCKETS = 3  # 30s — best from earlier sweep

OUT_CSV = HERE / "results" / "polymarket" / "maker_hedge.csv"
OUT_MD = HERE / "reports" / "POLYMARKET_MAKER_HEDGE.md"


def add_q10_signal(df):
    df = df.copy()
    df["signal"] = -1
    for asset in df.asset.unique():
        for tf in df.timeframe.unique():
            m = (df.asset == asset) & (df.timeframe == tf)
            r_abs = df.loc[m, "ret_5m"].abs()
            thr = r_abs.quantile(0.90)
            sel = m & (df.ret_5m.abs() >= thr) & df.ret_5m.notna()
            df.loc[sel, "signal"] = (df.loc[sel, "ret_5m"] > 0).astype(int)
    return df[df.signal != -1].copy()


def asof_close(k1m, ts):
    idx = k1m.ts_s.searchsorted(ts, side="right") - 1
    return float("nan") if idx < 0 else float(k1m.price_close.iloc[idx])


def simulate_combined(row, traj_g, k1m, rev_bp,
                     entry_mode, hedge_mode,
                     entry_wait_buckets, hedge_wait_buckets):
    """
    entry_mode: 'taker' or 'maker' (limit at held_bid+1tick, fallback to taker if no fill)
    hedge_mode: 'taker' or 'maker' (limit at other_bid+1tick, fallback to taker if no fill)
    """
    sig = int(row.signal)

    # ---- ENTRY ----
    bucket0 = traj_g[traj_g.bucket_10s == 0]
    if bucket0.empty:
        return None
    b0 = bucket0.iloc[0]

    if sig == 1:
        held_bid_first = b0.get("up_bid_first", float("nan"))
        held_ask_at_ws = float(row.entry_yes_ask) if pd.notna(row.entry_yes_ask) else float("nan")
        held_ask_min_col = "up_ask_min"
        other_bid_col = "dn_bid_first"   # bid of other (DOWN) side at hedge bucket
        other_ask_min_col = "dn_ask_min" # ask of other side
        other_bid_max_col = "dn_bid_max"
    else:
        held_bid_first = b0.get("dn_bid_first", float("nan"))
        held_ask_at_ws = float(row.entry_no_ask) if pd.notna(row.entry_no_ask) else float("nan")
        held_ask_min_col = "dn_ask_min"
        other_bid_col = "up_bid_first"
        other_ask_min_col = "up_ask_min"
        other_bid_max_col = "up_bid_max"

    if not (np.isfinite(held_bid_first) and 0 < held_bid_first < 1):
        return None
    if not (np.isfinite(held_ask_at_ws) and 0 < held_ask_at_ws < 1):
        return None

    fill_bucket_entry = 0
    if entry_mode == "taker":
        entry_used = held_ask_at_ws
        filled_entry_as_maker = False
    else:  # maker
        our_entry_limit = float(held_bid_first) + ENTRY_TICK
        if our_entry_limit >= held_ask_at_ws:
            # spread already at tick → taker fallback
            entry_used = held_ask_at_ws
            filled_entry_as_maker = False
        else:
            cand = traj_g[(traj_g.bucket_10s >= 0) & (traj_g.bucket_10s < entry_wait_buckets)].sort_values("bucket_10s")
            filled_entry_as_maker = False
            for _, b in cand.iterrows():
                m = b.get(held_ask_min_col, float("nan"))
                if pd.notna(m) and m <= our_entry_limit + 1e-9:
                    filled_entry_as_maker = True
                    fill_bucket_entry = int(b.bucket_10s)
                    break
            if filled_entry_as_maker:
                entry_used = our_entry_limit
            else:
                # taker fallback at deadline
                entry_used = held_ask_at_ws
                fill_bucket_entry = entry_wait_buckets

    # ---- HEDGE LOGIC ----
    ws = int(row.window_start_unix)
    btc_at_ws = asof_close(k1m, ws)
    hedge_p = None
    filled_hedge_as_maker = False
    trigger_bucket = None

    for _, b in traj_g.iterrows():
        bucket = int(b.bucket_10s)
        if bucket <= fill_bucket_entry:
            continue
        if rev_bp is None or not np.isfinite(btc_at_ws):
            continue
        ts_in = ws + bucket * 10
        btc_now = asof_close(k1m, ts_in)
        if not np.isfinite(btc_now):
            continue
        bp = (btc_now - btc_at_ws) / btc_at_ws * 10000
        reverted = (sig == 1 and bp <= -rev_bp) or (sig == 0 and bp >= rev_bp)
        if not reverted:
            continue

        # rev_bp triggered at bucket B
        trigger_bucket = bucket

        if hedge_mode == "taker":
            oa = b.get(other_ask_min_col, float("nan"))
            if pd.notna(oa) and 0 < oa < 1:
                hedge_p = float(oa)
            break

        # ---- MAKER HEDGE ----
        # Place limit at other_bid_first[trigger_bucket] + 1 tick
        other_bid_at_trigger = b.get(other_bid_col, float("nan"))
        if not (pd.notna(other_bid_at_trigger) and 0 < other_bid_at_trigger < 1):
            # No bid info — taker fallback at trigger
            oa = b.get(other_ask_min_col, float("nan"))
            if pd.notna(oa) and 0 < oa < 1:
                hedge_p = float(oa)
            break

        # Read other-side ask at trigger as ceiling for our limit
        oa_at_trigger = b.get(other_ask_min_col, float("nan"))
        if not (pd.notna(oa_at_trigger) and 0 < oa_at_trigger < 1):
            break  # no ask — fall through unhedged

        our_hedge_limit = float(other_bid_at_trigger) + TICK
        if our_hedge_limit >= oa_at_trigger:
            # spread at tick → taker fallback
            hedge_p = float(oa_at_trigger)
            break

        # Walk forward up to hedge_wait_buckets — see if other_ask drops to our limit
        wait_end = trigger_bucket + hedge_wait_buckets
        hedge_cand = traj_g[(traj_g.bucket_10s > trigger_bucket) & (traj_g.bucket_10s <= wait_end)].sort_values("bucket_10s")
        for _, hb in hedge_cand.iterrows():
            ask_min_h = hb.get(other_ask_min_col, float("nan"))
            if pd.notna(ask_min_h) and ask_min_h <= our_hedge_limit + 1e-9:
                hedge_p = our_hedge_limit
                filled_hedge_as_maker = True
                break

        if not filled_hedge_as_maker:
            # taker fallback at deadline bucket — use ask at deadline (or if none, last seen ask)
            deadline_row = traj_g[traj_g.bucket_10s == wait_end]
            if not deadline_row.empty:
                fb_ask = deadline_row.iloc[0].get(other_ask_min_col, float("nan"))
                if pd.notna(fb_ask) and 0 < fb_ask < 1:
                    hedge_p = float(fb_ask)
            if hedge_p is None:
                # use ask at trigger as fallback (we hesitated, paid the original taker price)
                hedge_p = float(oa_at_trigger)
        break  # only one hedge per slot

    # ---- PnL ----
    sig_won = (sig == int(row.outcome_up))
    if hedge_p is None:
        # Held to resolution unhedged
        if sig_won:
            payout = 1.0 - (1.0 - entry_used) * FEE_RATE
            pnl = payout - entry_used
        else:
            pnl = -entry_used
        cost = entry_used
        return {"pnl": pnl, "cost": cost, "entry_used": entry_used,
                "hedge_p": None, "hedged": False, "sig_won": sig_won,
                "filled_entry_as_maker": filled_entry_as_maker,
                "filled_hedge_as_maker": False,
                "trigger_bucket": None}

    if sig_won:
        payout = 1.0 - (1.0 - entry_used) * FEE_RATE
    else:
        payout = 1.0 - (1.0 - hedge_p) * FEE_RATE
    pnl = payout - entry_used - hedge_p
    cost = entry_used + hedge_p
    return {"pnl": pnl, "cost": cost, "entry_used": entry_used,
            "hedge_p": hedge_p, "hedged": True, "sig_won": sig_won,
            "filled_entry_as_maker": filled_entry_as_maker,
            "filled_hedge_as_maker": filled_hedge_as_maker,
            "trigger_bucket": trigger_bucket}


def stat_block(rows):
    pnls = np.array([r["pnl"] for r in rows])
    n = len(pnls)
    if n == 0:
        return {"n": 0, "hit": float("nan"), "roi": float("nan"),
                "ci_lo": 0, "ci_hi": 0, "mean_cost": 0,
                "entry_fill_rate": float("nan"), "hedge_fill_rate": float("nan"),
                "hedge_trigger_rate": float("nan")}
    boot = RNG.choice(pnls, size=(2000, n), replace=True).sum(axis=1)
    entry_fills = sum(1 for r in rows if r.get("filled_entry_as_maker"))
    hedge_fills = sum(1 for r in rows if r.get("filled_hedge_as_maker"))
    hedge_triggers = sum(1 for r in rows if r.get("hedged"))
    return {
        "n": n,
        "hit": float((pnls > 0).mean()),
        "roi": float(pnls.mean() * 100),
        "ci_lo": float(np.quantile(boot, 0.025)),
        "ci_hi": float(np.quantile(boot, 0.975)),
        "mean_cost": float(np.mean([r["cost"] for r in rows])),
        "entry_fill_rate": float(entry_fills / n),
        "hedge_fill_rate": float(hedge_fills / hedge_triggers) if hedge_triggers else 0.0,
        "hedge_trigger_rate": float(hedge_triggers / n),
    }


def main():
    print("Loading...")
    feats = pd.concat([load_features(a) for a in ASSETS], ignore_index=True)
    traj = {a: load_trajectories(a) for a in ASSETS}
    k1m = {a: load_klines_1m(a) for a in ASSETS}
    feats_q10 = add_q10_signal(feats)
    print(f"q10 markets: {len(feats_q10)}")

    # 4 entry/hedge combinations × 3 hedge wait windows = 12 variants
    variants = []
    for ent in ["taker", "maker"]:
        for hed in ["taker", "maker"]:
            for hwait in [2, 4, 6]:  # 20s, 40s, 60s
                if hed == "taker" and hwait != 2:
                    continue  # no need to vary hwait for taker hedge
                variants.append({
                    "entry_mode": ent, "hedge_mode": hed,
                    "hedge_wait_buckets": hwait,
                    "label": f"{ent[0].upper()}entry / {hed[0].upper()}hedge {hwait*10 if hed=='maker' else 0}s",
                })

    rows_csv = []
    per_variant_rows = {}
    for v in variants:
        sim_rows = []
        for _, row in feats_q10.iterrows():
            traj_g = traj[row.asset].get(row.slug)
            if traj_g is None or traj_g.empty:
                continue
            r = simulate_combined(row, traj_g, k1m[row.asset],
                                   REV_BP, v["entry_mode"], v["hedge_mode"],
                                   ENTRY_WAIT_BUCKETS, v["hedge_wait_buckets"])
            if r is not None and np.isfinite(r["pnl"]):
                r["asset"] = row.asset; r["tf"] = row.timeframe; r["slug"] = row.slug
                r["sig"] = int(row.signal); r["ws"] = int(row.window_start_unix)
                sim_rows.append(r)
        per_variant_rows[v["label"]] = sim_rows
        s = stat_block(sim_rows)
        rows_csv.append({"variant": v["label"], **s})
        print(f"  {v['label']:30s}: n={s['n']:>3d} hit={s['hit']*100:5.1f}% ROI={s['roi']:+6.2f}% "
              f"mean_cost=${s['mean_cost']:.4f} "
              f"entry_fill={s['entry_fill_rate']*100:.0f}% "
              f"hedge_trig={s['hedge_trigger_rate']*100:.0f}% hedge_fill={s['hedge_fill_rate']*100:.0f}%")

    # Pick baseline (T/T) and best
    baseline = next(r for r in rows_csv if r["variant"].startswith("Tentry / Thedge"))
    others = [r for r in rows_csv if r["variant"] != baseline["variant"]]
    for r in others:
        r["lift_vs_baseline_pp"] = r["roi"] - baseline["roi"]
        r["mean_cost_savings"] = baseline["mean_cost"] - r["mean_cost"]
    others.sort(key=lambda x: x["roi"], reverse=True)
    best = others[0]
    print(f"\nBaseline (T/T): ROI={baseline['roi']:+.2f}% mean_cost=${baseline['mean_cost']:.4f}")
    print(f"Best variant:   {best['variant']}: ROI={best['roi']:+.2f}% (lift {best['lift_vs_baseline_pp']:+.2f}pp)")

    # Cross-asset breakdown for best variant
    best_rows = per_variant_rows[best["variant"]]
    base_rows = per_variant_rows[baseline["variant"]]

    md = ["# Maker Hedge Strategy — extending maker-entry with maker-side hedge orders\n",
          f"q10 universe (n={len(feats_q10)}). hedge-hold rev_bp={REV_BP}. Entry-side wait = 30s (best from prior sweep).",
          f"Hedge wait windows tested: 20s / 40s / 60s. Tick improvement: 1¢. Fallback to taker on no-fill.\n",
          "## Variant grid\n",
          "| Variant | n | Hit% | ROI | vs T/T baseline | Entry fill | Hedge trigger | Hedge fill | Mean cost |",
          "|---|---|---|---|---|---|---|---|---|"]
    for r in rows_csv:
        is_baseline = r["variant"].startswith("Tentry / Thedge")
        marker = " (baseline)" if is_baseline else (" ★" if r["variant"] == best["variant"] else "")
        lift = r.get("lift_vs_baseline_pp", 0.0)
        md.append(f"| {r['variant']}{marker} | {r['n']} | "
                  f"{r['hit']*100 if not np.isnan(r['hit']) else 0:.1f}% | "
                  f"{r['roi']:+.2f}% | "
                  f"{lift:+.2f}pp | "
                  f"{r['entry_fill_rate']*100 if not np.isnan(r['entry_fill_rate']) else 0:.0f}% | "
                  f"{r['hedge_trigger_rate']*100 if not np.isnan(r['hedge_trigger_rate']) else 0:.0f}% | "
                  f"{r['hedge_fill_rate']*100 if not np.isnan(r['hedge_fill_rate']) else 0:.0f}% | "
                  f"${r['mean_cost']:.4f} |")

    md.append(f"\n## Cross-asset × timeframe — best variant `{best['variant']}` vs T/T baseline\n")
    md.append("| Asset | TF | n | Hit% | best ROI | T/T ROI | Δ |")
    md.append("|---|---|---|---|---|---|---|")
    cross_results = {}
    for asset in ["ALL", "btc", "eth", "sol"]:
        for tf in ["ALL", "5m", "15m"]:
            sub = [r for r in best_rows
                   if (asset == "ALL" or r["asset"] == asset)
                   and (tf == "ALL" or r["tf"] == tf)]
            sub_b = [r for r in base_rows
                     if (asset == "ALL" or r["asset"] == asset)
                     and (tf == "ALL" or r["tf"] == tf)]
            if not sub or not sub_b:
                continue
            s = stat_block(sub)
            t = stat_block(sub_b)
            md.append(f"| {asset} | {tf} | {s['n']} | {s['hit']*100:.1f}% | "
                      f"{s['roi']:+.2f}% | {t['roi']:+.2f}% | "
                      f"{s['roi']-t['roi']:+.2f}pp |")
            cross_results[(asset, tf)] = s["roi"] - t["roi"]

    # Day-by-day for best
    md.append(f"\n## Day-by-day — best variant `{best['variant']}` vs T/T baseline\n")
    md.append("| Date | n | best ROI | T/T ROI | Δ |")
    md.append("|---|---|---|---|---|")
    df_best = pd.DataFrame(best_rows)
    df_best["dt"] = pd.to_datetime(df_best.ws, unit="s", utc=True)
    df_best["date"] = df_best.dt.dt.date
    df_base = pd.DataFrame(base_rows)
    df_base["dt"] = pd.to_datetime(df_base.ws, unit="s", utc=True)
    df_base["date"] = df_base.dt.dt.date
    days_lift = 0
    for d in sorted(df_best.date.unique()):
        sub = df_best[df_best.date == d]
        sub_b = df_base[df_base.date == d]
        if len(sub) == 0:
            continue
        roi = sub.pnl.mean() * 100
        roi_b = sub_b.pnl.mean() * 100 if len(sub_b) else 0
        d_pp = roi - roi_b
        if d_pp > 0:
            days_lift += 1
        md.append(f"| {d} | {len(sub)} | {roi:+.2f}% | {roi_b:+.2f}% | {d_pp:+.2f}pp |")

    # Verdict
    md.append("\n## Verdict\n")
    n_criteria = 0
    if best["lift_vs_baseline_pp"] > 0:
        n_criteria += 1
    cross_lift_count = sum(1 for asset in ["btc", "eth", "sol"]
                           if cross_results.get((asset, "ALL"), 0) > 0)
    if cross_lift_count >= 2:
        n_criteria += 1
    if days_lift >= 4:
        n_criteria += 1
    md.append(f"**Criteria:**")
    md.append(f"  1. In-sample lift > 0 vs T/T baseline: "
              f"{'✅' if best['lift_vs_baseline_pp'] > 0 else '❌'} ({best['lift_vs_baseline_pp']:+.2f}pp)")
    md.append(f"  2. Cross-asset agreement (≥2/3): "
              f"{'✅' if cross_lift_count >= 2 else '❌'} ({cross_lift_count}/3)")
    md.append(f"  3. Day-by-day stability (≥4/5): "
              f"{'✅' if days_lift >= 4 else '❌'} ({days_lift}/{df_best.date.nunique()})")
    md.append(f"\n**Score: {n_criteria}/3** — forward-walk validation needed before deploy.")

    # Decompose: how much comes from entry vs hedge
    me_th = next(r for r in rows_csv if r["variant"].startswith("Mentry / Thedge"))
    te_mh = next((r for r in rows_csv if r["variant"].startswith("Tentry / Mhedge")
                  and "20s" in r["variant"]), None)
    md.append("\n## Decomposition: entry-only vs hedge-only contribution\n")
    md.append("| Source | ROI | Lift vs T/T |")
    md.append("|---|---|---|")
    md.append(f"| T/T baseline | {baseline['roi']:+.2f}% | — |")
    md.append(f"| M-entry / T-hedge | {me_th['roi']:+.2f}% | {me_th['roi']-baseline['roi']:+.2f}pp |")
    if te_mh:
        md.append(f"| T-entry / M-hedge 20s | {te_mh['roi']:+.2f}% | {te_mh['roi']-baseline['roi']:+.2f}pp |")
    md.append(f"| **{best['variant']} (best combo)** | {best['roi']:+.2f}% | {best['lift_vs_baseline_pp']:+.2f}pp |")

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows_csv).to_csv(OUT_CSV, index=False)
    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"\nWrote {OUT_CSV}")
    print(f"Wrote {OUT_MD}")


if __name__ == "__main__":
    main()
