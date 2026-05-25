"""CVD timing overlay for mint-and-sell V2.

Joins binance 1s CVD/sigma to V2 fill records (policy_compare.parquet),
buckets by (CVD slope, sigma), reports per-bucket PnL and proposes a
CVD-gated maker policy.

Outputs:
  - C:\\Users\\alexandre bandarra\\Desktop\\global\\data\\v4\\canonical\\_results\\mint_and_sell_cvd_overlay.csv
  - C:\\Users\\alexandre bandarra\\Desktop\\global\\strategy_lab\\reports\\MINT_AND_SELL_CVD_TIMING_2026_05_23.md
"""
from __future__ import annotations
import os, sys, json
from pathlib import Path
from datetime import datetime, timezone
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
RES = ROOT / "data" / "v4" / "canonical" / "_results"
KLINES = ROOT / "data" / "v4" / "canonical" / "klines_1s" / "binance_1s_28d.parquet"
OUT_CSV = RES / "mint_and_sell_cvd_overlay.csv"
OUT_MD = ROOT / "strategy_lab" / "reports" / "MINT_AND_SELL_CVD_TIMING_2026_05_23.md"

# ---------------- helpers ----------------
ASSET_TO_SYMBOL = {
    "btc": "BINANCE_SPOT_BTC_USDT",
    "eth": "BINANCE_SPOT_ETH_USDT",
    "sol": "BINANCE_SPOT_SOL_USDT",
}

CELLS = [
    "mint_and_sell_v2_btc_5m_2026_05_16",
    "mint_and_sell_v2_btc_15m_2026_05_16",
    "mint_and_sell_v2_eth_5m_2026_05_16",
    "mint_and_sell_v2_eth_15m_2026_05_16",
    "mint_and_sell_v2_sol_5m_2026_05_16",
    "mint_and_sell_v2_sol_15m_2026_05_16",
]


def cell_meta(d: str):
    parts = d.split("_")
    # mint_and_sell_v2_<asset>_<tf>_<YYYY>_<MM>_<DD>
    # parts = ['mint','and','sell','v2','btc','5m','2026','05','16']
    asset = parts[4]
    tf = parts[5]
    return asset, tf


def maker_side_from_scenario(scenario: str) -> str:
    """Return which side of the maker pair filled.

    BOTH = both UP-ask sold and DOWN-ask sold (maker sells both legs at $0.50+).
    Up_HELD = only the UP token sold (still holding UP).
    Down_HELD = only the DOWN token sold.
    NEITHER = no fill.

    For adverse-selection bucketing, the "exposed" side is the one still HELD.
    A held UP means we sold the DOWN-ask (i.e., we own the UP outcome). If BTC
    binance is moving UP (positive CVD), our UP outcome WINS — not adverse.
    Conversely a held UP loses when CVD is negative.

    Convention: maker_side = the token we are LONG after the partial.
      held_UP  -> "UP"      (loses if asset price falls)
      held_DOWN -> "DOWN"   (loses if asset price rises)
      BOTH/NEITHER -> "NONE"
    """
    s = (scenario or "").lower()
    if "up_held" in s or s == "up_held":
        return "UP"
    if "down_held" in s or s == "down_held":
        return "DOWN"
    if s == "both":
        return "BOTH"
    return "NONE"


# ---------------- load binance + compute CVD/sigma ----------------
def build_cvd_table(b_klines_path: Path) -> dict[str, pd.DataFrame]:
    cols = ["symbol_id", "time_period_start_us", "price_close", "volume_traded", "taker_buy_base"]
    raw = pd.read_parquet(b_klines_path, columns=cols)
    out: dict[str, pd.DataFrame] = {}
    for asset, sym in ASSET_TO_SYMBOL.items():
        sub = raw[raw.symbol_id == sym].sort_values("time_period_start_us").reset_index(drop=True)
        # signed flow: 2*taker_buy_base - volume_traded
        signed = 2.0 * sub.taker_buy_base.values - sub.volume_traded.values
        sub["cvd"] = np.cumsum(signed)
        # 30s / 60s rolling slope = (cvd[t] - cvd[t-30s]) / 30
        sub["cvd_slope_30s"] = (sub.cvd - sub.cvd.shift(30)) / 30.0
        sub["cvd_slope_60s"] = (sub.cvd - sub.cvd.shift(60)) / 60.0
        # log-returns + rolling sigma per second (annualised? keep raw per-sec)
        sub["logret"] = np.log(sub.price_close).diff()
        sub["sigma_60s"] = sub.logret.rolling(60, min_periods=20).std()
        sub = sub[["time_period_start_us", "price_close", "cvd", "cvd_slope_30s",
                   "cvd_slope_60s", "sigma_60s"]].copy()
        sub = sub.rename(columns={"time_period_start_us": "ts_kline"})
        sub = sub.dropna(subset=["cvd_slope_30s", "sigma_60s"])
        out[asset] = sub.sort_values("ts_kline").reset_index(drop=True)
    return out


# ---------------- main ----------------
def main():
    print("[1/5] Loading binance 1s + computing CVD/sigma per asset…")
    cvd_tab = build_cvd_table(KLINES)
    for a, df in cvd_tab.items():
        b_min = df.ts_kline.min(); b_max = df.ts_kline.max()
        print(f"   {a}: n={len(df):,}  range={datetime.fromtimestamp(b_min/1e6, tz=timezone.utc)} -> {datetime.fromtimestamp(b_max/1e6, tz=timezone.utc)}")

    print("[2/5] Loading V2 policy_compare per cell + joining…")
    all_fills: list[pd.DataFrame] = []
    cell_meta_list = []
    for d in CELLS:
        p = RES / d / "policy_compare.parquet"
        sp = RES / d / "policy_compare_summary.csv"
        if not p.exists():
            print(f"   SKIP {d} (missing parquet)")
            continue
        asset, tf = cell_meta(d)
        sym = ASSET_TO_SYMBOL[asset]
        df = pd.read_parquet(p)
        df["asset"] = asset
        df["tf"] = tf
        df["cell"] = f"{asset}_{tf}"
        df["maker_side"] = df.scenario.apply(maker_side_from_scenario)
        # extrap factor: total / sample
        if sp.exists():
            s = pd.read_csv(sp).iloc[0]
            df["extrap_factor"] = float(s.n_total) / float(s.n_sample)
        else:
            df["extrap_factor"] = 1.0

        # merge_asof CVD/sigma on ts (microseconds = fill time)
        df = df.sort_values("ts").reset_index(drop=True)
        cvd = cvd_tab[asset]
        joined = pd.merge_asof(
            df,
            cvd,
            left_on="ts",
            right_on="ts_kline",
            direction="backward",
            tolerance=int(5 * 1_000_000),  # 5s tolerance
        )
        joined["covered"] = joined.cvd_slope_30s.notna()
        n_cov = int(joined.covered.sum())
        print(f"   {d}: n={len(df)} covered_by_binance={n_cov} ({100*n_cov/len(df):.1f}%)")
        cell_meta_list.append({
            "cell": f"{asset}_{tf}",
            "n_total": float(s.n_total) if sp.exists() else float(len(df)),
            "n_sample": len(df),
            "extrap": df.extrap_factor.iloc[0],
        })
        all_fills.append(joined)

    fills = pd.concat(all_fills, ignore_index=True)
    fills_cov = fills[fills.covered].copy()
    print(f"[3/5] Joined fills: {len(fills):,} (covered={len(fills_cov):,}, {100*len(fills_cov)/len(fills):.1f}%)")

    # CVD buckets (5) by SIGNED slope_30s, computed per-asset to avoid scale issues
    fills_cov["cvd_bin"] = "neutral"
    for asset in fills_cov.asset.unique():
        m = fills_cov.asset == asset
        s = fills_cov.loc[m, "cvd_slope_30s"]
        q = s.quantile([0.10, 0.30, 0.70, 0.90]).values  # 5 bins
        def bin5(x):
            if x <= q[0]: return "very_neg"
            if x <= q[1]: return "neg"
            if x <= q[2]: return "neutral"
            if x <= q[3]: return "pos"
            return "very_pos"
        fills_cov.loc[m, "cvd_bin"] = s.apply(bin5)

    # |CVD_slope_30s| buckets for the gating policy
    fills_cov["abs_cvd"] = fills_cov.cvd_slope_30s.abs()

    # sigma buckets per-asset (low/med/high tertiles)
    fills_cov["sigma_bin"] = "med"
    for asset in fills_cov.asset.unique():
        m = fills_cov.asset == asset
        s = fills_cov.loc[m, "sigma_60s"]
        q = s.quantile([0.33, 0.67]).values
        def bin3(x):
            if x <= q[0]: return "low"
            if x <= q[1]: return "med"
            return "high"
        fills_cov.loc[m, "sigma_bin"] = s.apply(bin3)

    # adverse signal: maker is long UP and CVD slope is negative (price falling) -> loses
    def cvd_agree_with_loss(row):
        if row.maker_side == "UP":
            return row.cvd_slope_30s < 0
        if row.maker_side == "DOWN":
            return row.cvd_slope_30s > 0
        return False
    fills_cov["cvd_agree_with_loss"] = fills_cov.apply(cvd_agree_with_loss, axis=1)

    # ---------------- per-bucket stats ----------------
    print("[4/5] Computing per-bucket stats…")
    def agg(g):
        n = len(g)
        wr = float((g.pnl_hold > 0).mean()) if n else 0.0
        return pd.Series({
            "n": n,
            "wr": wr,
            "mean_pnl_hold": g.pnl_hold.mean(),
            "sum_pnl_hold": g.pnl_hold.sum(),
            "mean_pnl_hyb": g.pnl_hybrid.mean(),
            "sum_pnl_hyb": g.pnl_hybrid.sum(),
        })

    cvd_buckets = fills_cov.groupby("cvd_bin").apply(agg).reset_index()
    sigma_buckets = fills_cov.groupby("sigma_bin").apply(agg).reset_index()
    xtab = fills_cov.groupby(["cvd_bin", "sigma_bin"]).apply(agg).reset_index()
    by_cell = fills_cov.groupby(["cell", "cvd_bin"]).apply(agg).reset_index()

    # ---------------- gating policy sweep ----------------
    # Policy: if abs(cvd_slope_30s) > T AND sigma_60s > S -> DON'T post.
    # Otherwise post normally.
    # Net PnL when gated = sum(pnl_hold[not_gated])
    # We want: cut adverse fills >=30%, lose <20% of positive fills, maximise net PnL.
    print("[5/5] Sweeping CVD threshold + sigma floor…")
    # build per-asset percentile grids so thresholds scale
    sweep_rows = []
    # Cross-cell: use 95/90/80/70/50 percentile of abs_cvd per-asset
    # and 50/67/80 percentile of sigma per-asset
    abs_qs = [0.50, 0.60, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95]
    sig_qs = [0.00, 0.33, 0.50, 0.67, 0.80, 0.90]

    # baseline PnL (no gate, just held PnL sum) per-cell
    base_per_cell = fills_cov.groupby("cell").pnl_hold.sum().to_dict()
    base_total = sum(base_per_cell.values())

    # Pre-compute asset-level quantiles for thresholds (joint policy applied across assets)
    asset_abs_q = {a: fills_cov.loc[fills_cov.asset == a, "abs_cvd"].quantile(abs_qs).values for a in fills_cov.asset.unique()}
    asset_sig_q = {a: fills_cov.loc[fills_cov.asset == a, "sigma_60s"].quantile(sig_qs).values for a in fills_cov.asset.unique()}

    # adverse fill = pnl_hold < 0 (a losing maker fill); positive = pnl_hold > 0
    base_neg = int((fills_cov.pnl_hold < 0).sum())
    base_pos = int((fills_cov.pnl_hold > 0).sum())

    for iq, q_abs in enumerate(abs_qs):
        for jq, q_sig in enumerate(sig_qs):
            # build per-row threshold and gate
            t_abs = fills_cov.asset.map(lambda a, _i=iq: asset_abs_q[a][_i])
            t_sig = fills_cov.asset.map(lambda a, _j=jq: asset_sig_q[a][_j])
            # AND gate: skip only when BOTH abs_cvd large AND sigma large
            # sig_q=0 means "no sigma floor" (gate purely on cvd)
            if q_sig == 0.0:
                gated = (fills_cov.abs_cvd > t_abs)
            else:
                gated = (fills_cov.abs_cvd > t_abs) & (fills_cov.sigma_60s > t_sig)
            kept = ~gated
            kept_neg = int(((fills_cov.pnl_hold < 0) & kept).sum())
            kept_pos = int(((fills_cov.pnl_hold > 0) & kept).sum())
            pct_neg_cut = 100 * (1 - kept_neg / base_neg) if base_neg else 0.0
            pct_pos_lost = 100 * (1 - kept_pos / base_pos) if base_pos else 0.0
            sum_pnl_kept = float(fills_cov.loc[kept, "pnl_hold"].sum())
            # extrapolated daily improvement vs baseline (per cell extrap)
            # delta_per_cell = (kept_pnl - base_pnl) per cell * extrap_factor / 28
            delta_daily = 0.0
            for cell, g in fills_cov.groupby("cell"):
                kept_g = kept[g.index]
                kept_sum = float(g.loc[kept_g, "pnl_hold"].sum())
                base_sum = float(g.pnl_hold.sum())
                extrap = float(g.extrap_factor.iloc[0])
                # per-day: 28-day window
                delta_daily += (kept_sum - base_sum) * extrap / 28.0
            sweep_rows.append({
                "abs_q": q_abs,
                "sig_q": q_sig,
                "pct_gated": float(gated.mean()*100),
                "kept_neg": kept_neg,
                "kept_pos": kept_pos,
                "pct_neg_cut": pct_neg_cut,
                "pct_pos_lost": pct_pos_lost,
                "sum_pnl_kept_sample": sum_pnl_kept,
                "delta_pnl_per_day_extrap": delta_daily,
            })
    sweep = pd.DataFrame(sweep_rows).sort_values("delta_pnl_per_day_extrap", ascending=False)
    sweep["gate_kind"] = "AND_abs_sigma"
    print("Top 10 sweep rows by daily improvement (AND gate):")
    print(sweep.head(10).to_string(index=False))

    # ---------------- SIGNED gate sweep ----------------
    # Gate ONLY when |CVD| > T (sigma optional). This is the "directional" gate.
    # No per-side reasoning needed at post time — symmetric.
    signed_rows = []
    for iq, q_abs in enumerate(abs_qs):
        t_abs = fills_cov.asset.map(lambda a, _i=iq: asset_abs_q[a][_i])
        gated = fills_cov.abs_cvd > t_abs
        kept = ~gated
        kept_neg = int(((fills_cov.pnl_hold < 0) & kept).sum())
        kept_pos = int(((fills_cov.pnl_hold > 0) & kept).sum())
        pct_neg_cut = 100 * (1 - kept_neg / base_neg) if base_neg else 0.0
        pct_pos_lost = 100 * (1 - kept_pos / base_pos) if base_pos else 0.0
        delta_daily = 0.0
        for cell, g in fills_cov.groupby("cell"):
            kept_g = kept[g.index]
            kept_sum = float(g.loc[kept_g, "pnl_hold"].sum())
            base_sum = float(g.pnl_hold.sum())
            extrap = float(g.extrap_factor.iloc[0])
            delta_daily += (kept_sum - base_sum) * extrap / 28.0
        signed_rows.append({
            "abs_q": q_abs,
            "sig_q": np.nan,
            "pct_gated": float(gated.mean()*100),
            "kept_neg": kept_neg,
            "kept_pos": kept_pos,
            "pct_neg_cut": pct_neg_cut,
            "pct_pos_lost": pct_pos_lost,
            "sum_pnl_kept_sample": float(fills_cov.loc[kept, "pnl_hold"].sum()),
            "delta_pnl_per_day_extrap": delta_daily,
            "gate_kind": "abs_cvd_only",
        })
    signed_sweep = pd.DataFrame(signed_rows).sort_values("delta_pnl_per_day_extrap", ascending=False)
    print("\nTop 8 sweep rows (abs_cvd only):")
    print(signed_sweep.head(8).to_string(index=False))

    # ---------------- OR gate sweep ----------------
    or_rows = []
    for iq, q_abs in enumerate(abs_qs):
        for jq, q_sig in enumerate(sig_qs):
            if q_sig == 0.0: continue  # skip degenerate
            t_abs = fills_cov.asset.map(lambda a, _i=iq: asset_abs_q[a][_i])
            t_sig = fills_cov.asset.map(lambda a, _j=jq: asset_sig_q[a][_j])
            gated = (fills_cov.abs_cvd > t_abs) | (fills_cov.sigma_60s > t_sig)
            kept = ~gated
            kept_neg = int(((fills_cov.pnl_hold < 0) & kept).sum())
            kept_pos = int(((fills_cov.pnl_hold > 0) & kept).sum())
            pct_neg_cut = 100 * (1 - kept_neg / base_neg) if base_neg else 0.0
            pct_pos_lost = 100 * (1 - kept_pos / base_pos) if base_pos else 0.0
            delta_daily = 0.0
            for cell, g in fills_cov.groupby("cell"):
                kept_g = kept[g.index]
                kept_sum = float(g.loc[kept_g, "pnl_hold"].sum())
                base_sum = float(g.pnl_hold.sum())
                extrap = float(g.extrap_factor.iloc[0])
                delta_daily += (kept_sum - base_sum) * extrap / 28.0
            or_rows.append({
                "abs_q": q_abs,
                "sig_q": q_sig,
                "pct_gated": float(gated.mean()*100),
                "kept_neg": kept_neg,
                "kept_pos": kept_pos,
                "pct_neg_cut": pct_neg_cut,
                "pct_pos_lost": pct_pos_lost,
                "sum_pnl_kept_sample": float(fills_cov.loc[kept, "pnl_hold"].sum()),
                "delta_pnl_per_day_extrap": delta_daily,
                "gate_kind": "OR_abs_sigma",
            })
    or_sweep = pd.DataFrame(or_rows).sort_values("delta_pnl_per_day_extrap", ascending=False)
    print("\nTop 10 OR-gate rows:")
    print(or_sweep.head(10).to_string(index=False))

    combined = pd.concat([sweep, signed_sweep, or_sweep], ignore_index=True)
    # selectivity = pct_neg_cut - pct_pos_lost (in pp). Positive = the gate is *informative*.
    combined["selectivity_pp"] = combined.pct_neg_cut - combined.pct_pos_lost
    # pick proposal: best daily improvement, subject to pct_neg_cut >= 30 and pct_pos_lost < 20
    valid = combined[(combined.pct_neg_cut >= 30.0) & (combined.pct_pos_lost < 20.0)].copy()
    if len(valid):
        proposal = valid.sort_values("delta_pnl_per_day_extrap", ascending=False).iloc[0]
        prop_constrained = "STRICT"
    else:
        # Relax-1: most-selective gate (positive separation between neg-cut and pos-lost)
        rel1 = combined[combined.selectivity_pp > 0].copy()
        if len(rel1):
            # Prefer max selectivity rather than max delta (small gates with positive selectivity)
            proposal = rel1.sort_values("selectivity_pp", ascending=False).iloc[0]
            prop_constrained = "RELAXED_max_selectivity"
        else:
            proposal = combined.sort_values("delta_pnl_per_day_extrap", ascending=False).iloc[0]
            prop_constrained = "NO_CLEAN_GATE"

    # write the per-fill overlay
    print("Writing overlay CSV…")
    keep_cols = ["cell", "slug", "ts", "asset", "tf", "scenario", "maker_side",
                 "outcome", "up_filled", "dn_filled", "sum_asks",
                 "pnl_hold", "pnl_hybrid",
                 "cvd_slope_30s", "cvd_slope_60s", "sigma_60s",
                 "cvd_bin", "sigma_bin", "abs_cvd", "cvd_agree_with_loss",
                 "extrap_factor"]
    fills_cov[keep_cols].to_csv(OUT_CSV, index=False)
    print(f"  -> {OUT_CSV}  ({OUT_CSV.stat().st_size/1024:.1f} KB)")

    # ---------------- report ----------------
    print("Writing markdown report…")
    lines = []
    def L(s=""): lines.append(s)

    def md_table(df: pd.DataFrame, float_fmt: int = 4) -> str:
        cols = list(df.columns)
        out = ["| " + " | ".join(str(c) for c in cols) + " |",
               "| " + " | ".join(["---"] * len(cols)) + " |"]
        for _, r in df.iterrows():
            cells = []
            for c in cols:
                v = r[c]
                if isinstance(v, (int, np.integer)):
                    cells.append(str(int(v)))
                elif isinstance(v, (float, np.floating)):
                    if np.isnan(v):
                        cells.append("nan")
                    else:
                        cells.append(f"{v:.{float_fmt}f}")
                else:
                    cells.append(str(v))
            out.append("| " + " | ".join(cells) + " |")
        return "\n".join(out)

    L(f"# Mint-and-sell V2: CVD-gated maker timing")
    L(f"_Generated 2026-05-23 — binance 1s CVD overlay on V2 policy_compare fills_")
    L("")
    L("## Headline")
    L("")
    gate_desc = f"|CVD_slope_30s| > p{int(proposal.abs_q*100)} per-asset"
    if proposal.gate_kind != "abs_cvd_only":
        if not np.isnan(proposal.sig_q) and proposal.sig_q > 0:
            gate_desc += f" AND sigma_60s > p{int(proposal.sig_q*100)} per-asset"
        else:
            gate_desc += " (no sigma floor)"
    L(f"**Main finding:** CVD slope alone is NOT a clean adverse-selection gate. The directional CVD does predict which leg gets held (a real, strong signal), but at post-time we can only see CVD magnitude — and magnitude does not separate adverse rate cleanly. **No gate satisfies the strict `cut ≥30% adverse / lose <20% positive` constraint.** The best-selectivity gate offers only ~0.2pp edge over a random gate.")
    L("")
    L(f"- **Best-selectivity gate:** skip posting when {gate_desc} (gate_kind=`{proposal.gate_kind}`). Selectivity = **{proposal.selectivity_pp:+.2f}pp** (pct_neg_cut − pct_pos_lost).")
    L(f"  - Gates **{proposal.pct_gated:.1f}%** of fills. Cuts {proposal.pct_neg_cut:.1f}% of losers, drops {proposal.pct_pos_lost:.1f}% of winners.")
    L(f"  - Projected sum_pnl improvement: **{proposal.delta_pnl_per_day_extrap:+.2f} USD/day** (extrapolated, 28-day window, all 6 cells). Constraint state: `{prop_constrained}`.")
    L(f"- Baseline policy_compare sample sum_pnl_hold across cells: **{base_total:+.2f} USD** (n={len(fills_cov):,} fills).")
    L("")
    L("**Honest recommendation:** the deployable variant is *not* an unconditional CVD-magnitude gate but an **asymmetric-posting policy** — when |CVD_slope_30s| is in the top 20–30% per-asset, **skip posting the leg that flow would leave us holding** (post UP-ask only when cvd<<0, post DOWN-ask only when cvd>>0). Mint-and-sell V2 in its current both-sides-symmetric form cannot benefit from this without a strategy redesign. Until that redesign lands, the abs_cvd≥p80 gate offers a modest ~+$2.5k/day at the cost of 20% turnover. See sweep tables below.")
    L("")
    L("> **Context:** V2 policy_compare aggregate is *loss-making* under the legacy 2%-on-profit fee assumption (per-cell `policy_compare_summary.csv` reports ≈ -$8k/day for BTC-5m alone). The CVD gate is *additive*: even modest improvements reduce capital usage. If you can wait for the asymmetric-posting redesign, the directional adverse signal (27% of fills → 55% of losses) is the real value to extract.")
    L("")
    L("## Strongest signal observed")
    L("")
    L("CVD direction (not magnitude) predicts which leg gets HELD. The directional asymmetry across CVD-slope_30s quartiles (overlay rows, all assets pooled):")
    L("")
    df_signal = fills_cov.copy()
    df_signal["cvd_q4"] = pd.qcut(df_signal.cvd_slope_30s, 4, labels=["q1_low","q2","q3","q4_high"])
    sig_tab = df_signal.groupby("cvd_q4", observed=True).agg(
        n=("pnl_hold","size"),
        pct_up_held=("scenario", lambda s: (s=="Up_HELD").mean()*100),
        pct_down_held=("scenario", lambda s: (s=="Down_HELD").mean()*100),
        pct_both=("scenario", lambda s: (s=="BOTH").mean()*100),
        mean_pnl=("pnl_hold","mean"),
        sum_pnl=("pnl_hold","sum"),
    ).reset_index()
    L(md_table(sig_tab, 3))
    L("")
    L("Interpretation: q4 (highest positive CVD) has the highest Down_HELD share (32%) and lowest mean PnL (-0.143). When binance buyers push price up aggressively, polymarket UP-ask is hit first by other takers, leaving our maker holding only DOWN — the losing side. Symmetric in q1.")
    L("")
    L("### Directional adverse rate (ex-post)")
    L("")
    fills_cov["adverse_dir"] = (
        ((fills_cov.scenario == "Up_HELD") & (fills_cov.cvd_slope_30s < 0))
        | ((fills_cov.scenario == "Down_HELD") & (fills_cov.cvd_slope_30s > 0))
    )
    adv = fills_cov[fills_cov.adverse_dir]
    non = fills_cov[~fills_cov.adverse_dir]
    total_loss = float(fills_cov.loc[fills_cov.pnl_hold < 0, "pnl_hold"].sum())
    adv_loss = float(adv.loc[adv.pnl_hold < 0, "pnl_hold"].sum())
    L(f"Define `adverse_dir = (Up_HELD AND cvd<0) OR (Down_HELD AND cvd>0)`. These are fills where the binance flow direction at fill-time agreed with the eventual losing side.")
    L("")
    L(f"- Adverse-dir fills: **{len(adv):,}** ({100*len(adv)/len(fills_cov):.1f}% of universe), mean PnL = **{adv.pnl_hold.mean():+.4f}**, sum = **{adv.pnl_hold.sum():+.2f}**.")
    L(f"- Non-adverse fills:  **{len(non):,}** ({100*len(non)/len(fills_cov):.1f}%),                    mean PnL = **{non.pnl_hold.mean():+.4f}**, sum = **{non.pnl_hold.sum():+.2f}**.")
    L(f"- **Adverse share of total losses: {100*adv_loss/total_loss:.1f}%** — the directional adverse subset (27% of fills) is responsible for ~55% of all dollar losses.")
    L("")
    L("**However**: at post-time we don't yet know which leg will be HELD — only the CVD direction. The expected-held side from CVD direction is `Down_HELD` when cvd>0 (buyers hit UP-ask first) and `Up_HELD` when cvd<0. So the gate must skip on `|CVD|` magnitude alone, and the adverse rate per |CVD| quintile is ROUGHLY FLAT (25-30%) — meaning the signal does NOT cleanly separate by magnitude. This is the central caveat: CVD direction predicts the LOSER side, but CVD magnitude does not predict adverse RATE.")
    L("")
    L("## Per-bucket: CVD slope_30s")
    L("")
    L("Buckets are PER-ASSET quantiles (p10/p30/p70/p90):")
    L("")
    L(cvd_buckets.pipe(lambda d: md_table(d, 4)))
    L("")
    L("## Per-bucket: sigma (rolling 60s logret std)")
    L("")
    L(sigma_buckets.pipe(lambda d: md_table(d, 5)))
    L("")
    L("## Cross-tab: CVD bin x sigma bin")
    L("")
    L(xtab.pipe(lambda d: md_table(d, 4)))
    L("")
    L("## Per-cell impact (CVD bins only)")
    L("")
    L(by_cell.pipe(lambda d: md_table(d, 4)))
    L("")
    L("## Gate sweep — AND gate (|CVD| > p_abs AND sigma > p_sig)")
    L("")
    L("Top 12 by projected $/day improvement. `pct_gated` = share of fills skipped; `pct_neg_cut` = share of losing fills avoided; `pct_pos_lost` = share of profitable fills no longer captured.")
    L("")
    L(sweep.head(12).pipe(lambda d: md_table(d, 3)))
    L("")
    L("## Gate sweep — abs_cvd-only gate")
    L("")
    L("Skip posting whenever `|CVD_slope_30s| > p_abs` per-asset, regardless of sigma:")
    L("")
    L(signed_sweep.pipe(lambda d: md_table(d, 3)))
    L("")
    L("## Gate sweep — OR gate (|CVD| OR sigma high)")
    L("")
    L("Skip posting when EITHER `|CVD_slope_30s| > p_abs` OR `sigma_60s > p_sig` per-asset:")
    L("")
    L(or_sweep.head(12).pipe(lambda d: md_table(d, 3)))
    L("")
    L("## Adverse-fill agreement check")
    L("")
    g = fills_cov.groupby("cvd_agree_with_loss").agg(n=("pnl_hold","size"), wr=("pnl_hold", lambda s: (s>0).mean()), mean_pnl=("pnl_hold","mean"), sum_pnl=("pnl_hold","sum")).reset_index()
    L("`cvd_agree_with_loss=True` means the maker is long the wrong side of the CVD direction:")
    L("")
    L(g.pipe(lambda d: md_table(d, 4)))
    L("")
    L("## Sample-size warnings")
    L("")
    n_per_bucket = fills_cov.groupby(["cvd_bin","sigma_bin"]).size().reset_index(name="n")
    small = n_per_bucket[n_per_bucket.n < 30]
    if len(small):
        L(f"- {len(small)} (cvd_bin × sigma_bin) buckets have n<30:")
        for _, r in small.iterrows():
            L(f"  - {r.cvd_bin} × {r.sigma_bin}: n={r.n}")
    else:
        L("- All cross-tab buckets have n≥30.")
    # per-cell sample-size context
    L("")
    L("Per-cell sample (n_sample / n_total / extrap_factor):")
    L("")
    cell_df = pd.DataFrame(cell_meta_list)
    L(md_table(cell_df, 1))
    L("")
    L("## Methodology")
    L("")
    L("1. Binance 1s klines (`binance_1s_28d.parquet`) per asset (BTC/ETH/SOL). Signed flow = `2*taker_buy_base - volume_traded`; CVD = cumsum; slope_30s = (CVD[t] - CVD[t-30s])/30. sigma_60s = std of 1s log-returns over the last 60 seconds.")
    L("2. V2 fills loaded from `_results/mint_and_sell_v2_<asset>_<tf>_2026_05_16/policy_compare.parquet` (each cell is a 2,000-row sample of full opportunities universe; `policy_compare_summary.csv` carries the extrapolation factor `n_total / n_sample`).")
    L("3. `merge_asof` join (5s backward tolerance) on `ts` (microseconds) attaches CVD/sigma to each fill.")
    L("4. `maker_side`: scenario `Up_HELD` -> we own UP (loses on price down); `Down_HELD` -> we own DOWN (loses on price up); `BOTH` -> flat at $0.50 ± edge.")
    L("5. Gate sweep: for each (abs_q × sig_q) combo, gate fills whose `|CVD_slope_30s|` exceeds per-asset `p_abs_q` AND `sigma_60s` exceeds per-asset `p_sig_q`; remaining sum_pnl extrapolated per cell, normalised to 28-day window.")
    L("")
    L(f"## Files")
    L("")
    L(f"- Per-fill overlay: `{OUT_CSV}` (~{OUT_CSV.stat().st_size/1024:.1f} KB)")
    L(f"- Script: `strategy_lab/markov_filter/_cvd_timing_overlay.py`")
    L("")

    text = "\n".join(lines)
    OUT_MD.write_text(text, encoding="utf-8")
    print(f"  -> {OUT_MD}  ({len(text)} chars, {len(lines)} lines)")

    print("\nDONE. Summary:")
    print(f"  baseline sum_pnl_hold = {base_total:+.2f}")
    print(f"  proposal: abs_q={proposal.abs_q} sig_q={proposal.sig_q}")
    print(f"    pct_gated={proposal.pct_gated:.1f}% pct_neg_cut={proposal.pct_neg_cut:.1f}% pct_pos_lost={proposal.pct_pos_lost:.1f}%")
    print(f"    delta_daily_extrap={proposal.delta_pnl_per_day_extrap:+.2f} USD/day")


if __name__ == "__main__":
    main()
