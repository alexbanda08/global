"""Multi-wallet alpha decode pipeline. Runs sections 1-7 per wallet, writes report."""
import sys
import json
import math
from pathlib import Path
from collections import defaultdict

import numpy as np
import pandas as pd

sys.path.insert(0, 'data/v4/canonical')
from load import load_resolutions, load_klines_asof, asof_strict

REPO = Path(r"C:\Users\alexandre bandarra\Desktop\global")
CACHE = REPO / "strategy_lab/wallet_hunt/cache"
REPORT = REPO / "strategy_lab/reports/MULTI_WALLET_ALPHA_DECODE_2026_05_18.md"

WALLETS = [
    {"addr": "0x04b6d7e9", "kpnl": "$212k/day", "note": "pair-arb (reference)"},
    {"addr": "0xcfb103c3", "kpnl": "$-39/day", "note": "loser"},
    {"addr": "0xb27bc932", "kpnl": "$254k/day", "note": "scalper (partial cache, no trades_chain)"},
    {"addr": "0x89b5cdaa", "kpnl": "$10k/day", "note": "directional"},
    {"addr": "0xeebde7a0", "kpnl": "$344k/day", "note": "hybrid"},
]


def load_token_lookup():
    tok = pd.read_parquet(CACHE / "_token_lookup.parquet")
    return tok


def load_trades(w):
    p = CACHE / w / "trades_chain.parquet"
    if p.exists():
        return pd.read_parquet(p)
    return None


def load_fires(w):
    p = CACHE / w / "fires_decoded.parquet"
    if p.exists():
        return pd.read_parquet(p)
    return None


def normalize_wallet_side(row):
    """When wallet_is_maker AND side=SELL → wallet posted bid → wallet BOUGHT.
       When wallet_is_maker AND side=BUY  → wallet posted ask → wallet SOLD.
       When wallet_is_taker → side reflects what they did directly."""
    if row.wallet_is_maker:
        return "BUY" if row.side == "SELL" else "SELL"
    return row.side


def stats_basic(trades, fires, w):
    """Section 1 — basic stats."""
    out = {}
    if trades is not None and len(trades) > 0:
        out["n_trades"] = int(len(trades))
        out["maker_pct"] = float(trades.wallet_is_maker.mean())
        out["taker_pct"] = float(trades.wallet_is_taker.mean())
        out["window_start"] = pd.Timestamp(trades.timestamp.min(), unit="s").strftime("%Y-%m-%d %H:%M:%S")
        out["window_end"] = pd.Timestamp(trades.timestamp.max(), unit="s").strftime("%Y-%m-%d %H:%M:%S")
        out["window_days"] = float((trades.timestamp.max() - trades.timestamp.min()) / 86400)
        out["sum_notional"] = float(trades.usdc_notional.sum())
    elif fires is not None:
        # fires_decoded only — fall back
        out["n_trades"] = int(len(fires))
        # fires_decoded.counterparty=='maker' means wallet's counterparty was maker (so wallet was taker)
        # But often in fires the wallet_side is the wallet's BUY direction directly.
        out["maker_pct"] = float("nan")
        out["taker_pct"] = float("nan")
        out["window_start"] = pd.Timestamp(fires.ts_us.min() / 1e6, unit="s").strftime("%Y-%m-%d %H:%M:%S")
        out["window_end"] = pd.Timestamp(fires.ts_us.max() / 1e6, unit="s").strftime("%Y-%m-%d %H:%M:%S")
        out["window_days"] = float((fires.ts_us.max() - fires.ts_us.min()) / 1e6 / 86400)
        out["sum_notional"] = float("nan")
    return out


def stats_cells(merged):
    """Cell breakdown — mkt_asset x market_class."""
    if "mkt_asset" not in merged.columns:
        return {}
    g = merged.groupby(["mkt_asset", "market_class"], dropna=False).size()
    return {f"{a}_{c}": int(n) for (a, c), n in g.items()}


def per_slug_accumulation(merged):
    """Section 2 — per-slug shares_up/shares_dn."""
    if "slug" not in merged.columns:
        return None
    # wallet_buys: net shares wallet ACQUIRED (BUY) per slug+outcome
    m = merged.copy()
    m["wallet_action"] = m.apply(normalize_wallet_side, axis=1)
    m["signed_size"] = np.where(m.wallet_action == "BUY", m["size"], -m["size"])
    # filter to up-down markets only
    m = m[m.market_class.fillna("").str.startswith("updown_")]
    if len(m) == 0:
        return None
    agg = m.groupby(["slug", "outcome"]).signed_size.sum().unstack(fill_value=0.0)
    # ensure both Up/Down cols
    if "Up" not in agg.columns: agg["Up"] = 0.0
    if "Down" not in agg.columns: agg["Down"] = 0.0
    agg["shares_up"] = agg["Up"].astype(float)
    agg["shares_dn"] = agg["Down"].astype(float)
    # paired = 2*min / (sum)
    agg["min_side"] = agg[["shares_up", "shares_dn"]].clip(lower=0).min(axis=1)
    agg["sum_sides"] = agg[["shares_up", "shares_dn"]].clip(lower=0).sum(axis=1)
    agg["paired_pct"] = np.where(agg.sum_sides > 0, 2 * agg.min_side / agg.sum_sides, np.nan)
    agg["leftover_amt"] = (agg.shares_up - agg.shares_dn).abs()
    agg["leftover_side"] = np.where(agg.shares_up > agg.shares_dn, "Up", "Down")
    return agg.reset_index()[["slug", "shares_up", "shares_dn", "paired_pct", "leftover_amt", "leftover_side"]]


def leftover_alpha(slug_agg, resolutions):
    """Section 3 — leftover side vs winning outcome."""
    if slug_agg is None or len(slug_agg) == 0:
        return {}
    # merge with chainlink outcome
    r = resolutions[["slug", "outcome"]].rename(columns={"outcome": "winner"})
    j = slug_agg.merge(r, on="slug", how="left")
    # filter to material leftover + has resolution
    mat = j[(j.leftover_amt > 10) & j.winner.notna()].copy()
    if len(mat) == 0:
        return {"n_material": 0}
    mat["leftover_won"] = (mat.leftover_side == mat.winner).astype(int)
    n = len(mat)
    won_pct = mat.leftover_won.mean()
    # bin notional-weighted by leftover_amt
    w_won_pct = (mat.leftover_won * mat.leftover_amt).sum() / mat.leftover_amt.sum()
    return {
        "n_material": int(n),
        "n_with_res": int(j.winner.notna().sum()),
        "leftover_on_winner_pct": float(won_pct),
        "leftover_on_winner_pct_size_weighted": float(w_won_pct),
        "mean_paired_pct": float(j.paired_pct.dropna().mean()),
        "median_paired_pct": float(j.paired_pct.dropna().median()),
    }


def time_of_day(trades):
    """Section 4 — UTC hour distribution."""
    if trades is None or len(trades) == 0:
        return {}
    ts = pd.to_datetime(trades.timestamp, unit="s", utc=True)
    hr = ts.dt.hour.value_counts().sort_index()
    total = hr.sum()
    by_hr = {int(h): {"trades": int(c), "pct": float(c / total)} for h, c in hr.items()}
    # entropy-like measure: 24/7 → ~uniform → ~0.042 each; concentrated → spikes
    active_hours = int((hr > 0).sum())
    peak_hour = int(hr.idxmax())
    peak_pct = float(hr.max() / total)
    return {"by_hr": by_hr, "active_hours": active_hours, "peak_hour": peak_hour, "peak_pct": peak_pct}


def vol_filter(slug_agg, resolutions, max_compare=300):
    """Section 5 — pre-slug binance vol for traded vs skipped slugs."""
    if slug_agg is None or len(slug_agg) == 0:
        return {}
    # determine asset_sym from slug prefix
    traded_slugs = set(slug_agg.slug)
    # restrict to traded mkt + window
    j = resolutions[resolutions.slug.isin(traded_slugs)]
    if len(j) == 0:
        return {"skip_reason": "no resolution overlap"}
    # asset mix
    asset_mix = j.ticker.value_counts().to_dict()
    primary_asset = max(asset_mix, key=asset_mix.get)
    # active window for traded
    t_lo = j.slot_start_us.min()
    t_hi = j.slot_end_us.max()
    # all slugs available in window
    avail = resolutions[(resolutions.ticker == primary_asset) &
                        (resolutions.slot_start_us >= t_lo) &
                        (resolutions.slot_start_us <= t_hi)]
    skipped_slugs = set(avail.slug) - traded_slugs
    # sample
    rng = np.random.default_rng(42)
    traded_sample = list(traded_slugs & set(avail.slug))
    if len(traded_sample) > max_compare:
        traded_sample = list(rng.choice(traded_sample, max_compare, replace=False))
    skipped_sample = list(skipped_slugs)
    if len(skipped_sample) > max_compare:
        skipped_sample = list(rng.choice(skipped_sample, max_compare, replace=False))
    # compute pre-slug vol_120s using binance asof
    try:
        end_us, prices = load_klines_asof(primary_asset, "binance-spot-ws", "1MIN")
    except Exception as e:
        return {"skip_reason": f"klines load err: {e}"}
    def vol_at(slug_):
        row = avail[avail.slug == slug_].iloc[0]
        ts = int(row.slot_start_us)
        # 120s pre-slug returns: 1m returns over 2 minutes
        pts = []
        for off_s in range(0, 121, 60):
            p = asof_strict(end_us, prices, ts - off_s * 1_000_000)
            if p > 0:
                pts.append(p)
        if len(pts) < 2:
            return np.nan
        rets = np.diff(np.log(pts))
        return float(np.std(rets))
    traded_vols = np.array([vol_at(s) for s in traded_sample])
    skipped_vols = np.array([vol_at(s) for s in skipped_sample])
    traded_vols = traded_vols[~np.isnan(traded_vols)]
    skipped_vols = skipped_vols[~np.isnan(skipped_vols)]
    if len(traded_vols) < 5 or len(skipped_vols) < 5:
        return {"skip_reason": "insufficient samples", "n_traded": len(traded_vols), "n_skipped": len(skipped_vols)}
    return {
        "primary_asset": primary_asset,
        "n_traded": int(len(traded_vols)),
        "n_skipped": int(len(skipped_vols)),
        "traded_vol_mean": float(traded_vols.mean()),
        "skipped_vol_mean": float(skipped_vols.mean()),
        "traded_vol_median": float(np.median(traded_vols)),
        "skipped_vol_median": float(np.median(skipped_vols)),
        "ratio_traded_to_skipped": float(traded_vols.mean() / max(skipped_vols.mean(), 1e-12)),
    }


def momentum_following(fires, max_sample=200):
    """Section 6 — Binance momentum match rate for late-bucket fires."""
    if fires is None or len(fires) == 0:
        return {}
    f = fires[fires.offset_from_slot_start_s > 0.8 * 300]  # 5m bucket; use > 0.8*300=240s
    # Actually offset_frac — column is offset_from_slot_start_s in seconds.
    # Need slot length: ~300 for 5m, ~900 for 15m. Use a flat 240s threshold
    f = fires[fires.offset_from_slot_start_s > 240]
    if len(f) == 0:
        return {"n_late": 0}
    # if binance_ret_60s/120s all zero, recompute
    # Group by asset
    out = {}
    asset_map = {"BTC": "BTC", "ETH": "ETH", "SOL": "SOL"}
    out["n_late"] = int(len(f))
    for asset in f.asset_sym.dropna().unique():
        asset_str = str(asset).upper()
        if asset_str not in asset_map:
            continue
        sub = f[f.asset_sym == asset]
        if len(sub) == 0:
            continue
        if len(sub) > max_sample:
            sub = sub.sample(n=max_sample, random_state=42)
        ret60 = sub.binance_ret_60s.values
        ret120 = sub.binance_ret_120s.values
        # If all zero, recompute
        if np.all(ret60 == 0) or np.all(np.isnan(ret60)):
            try:
                end_us, prices = load_klines_asof(asset_str, "binance-spot-ws", "1MIN")
                ret60 = []
                ret120 = []
                for _, row in sub.iterrows():
                    ts = int(row.ts_us)
                    p0 = asof_strict(end_us, prices, ts)
                    p60 = asof_strict(end_us, prices, ts - 60_000_000)
                    p120 = asof_strict(end_us, prices, ts - 120_000_000)
                    ret60.append(np.log(p0/p60) if p0 > 0 and p60 > 0 else np.nan)
                    ret120.append(np.log(p0/p120) if p0 > 0 and p120 > 0 else np.nan)
                ret60 = np.array(ret60)
                ret120 = np.array(ret120)
                sub = sub.assign(_ret60=ret60, _ret120=ret120)
            except Exception as e:
                out[f"{asset_str}_err"] = str(e)
                continue
        # match rate: bought_side == sign(ret)
        # wallet_side = BUY/SELL on a specific outcome (Up/Down). Combine the two to derive bought_up.
        sides = sub.wallet_side.astype(str).str.upper().values
        outcomes = sub.outcome.astype(str).values
        # BUY Up → long Up; SELL Up → short Up == long Down; BUY Down → long Down; SELL Down → long Up
        bought_up = np.array([
            (s == "BUY" and o == "Up") or (s == "SELL" and o == "Down")
            for s, o in zip(sides, outcomes)
        ])
        match60 = ((bought_up & (ret60 > 0)) | (~bought_up & (ret60 < 0)))
        valid60 = ~np.isnan(ret60) & (ret60 != 0)
        match120 = ((bought_up & (ret120 > 0)) | (~bought_up & (ret120 < 0)))
        valid120 = ~np.isnan(ret120) & (ret120 != 0)
        if valid60.sum() > 0:
            out[f"{asset_str}_n_late"] = int(valid60.sum())
            out[f"{asset_str}_match_ret60s"] = float(match60[valid60].mean())
        if valid120.sum() > 0:
            out[f"{asset_str}_match_ret120s"] = float(match120[valid120].mean())
    return out


def slug_selection_rate(slug_agg, resolutions):
    """Section 7 — N traded / N available."""
    if slug_agg is None or len(slug_agg) == 0:
        return {}
    traded_slugs = set(slug_agg.slug)
    j = resolutions[resolutions.slug.isin(traded_slugs)]
    if len(j) == 0:
        return {}
    primary_asset = j.ticker.value_counts().idxmax()
    primary_tf = j.timeframe.value_counts().idxmax()
    t_lo = j.slot_start_us.min()
    t_hi = j.slot_end_us.max()
    avail = resolutions[(resolutions.ticker == primary_asset) &
                        (resolutions.timeframe == primary_tf) &
                        (resolutions.slot_start_us >= t_lo) &
                        (resolutions.slot_start_us <= t_hi)]
    n_avail = len(avail)
    n_traded = len(set(avail.slug) & traded_slugs)
    rate = n_traded / max(n_avail, 1)
    return {
        "primary_asset": primary_asset,
        "primary_tf": primary_tf,
        "n_traded_in_window": int(n_traded),
        "n_avail_in_window": int(n_avail),
        "selection_rate": float(rate),
    }


def classify_strategy(stats):
    """Combine metrics to assign a class.

    Decision tree (in order):
      1. LOSER: reported $/day in $-range, or leftover-on-winner clearly adverse + low net
      2. DIRECTIONAL: low paired + high leftover-on-winner (taking sides, winning)
      3. HYBRID: medium paired + above-50% leftover-on-winner (mix base+edge)
      4. MAKER PAIR ARB: high maker% + high paired + ~50% leftover
      5. TAKER PAIR ARB: low maker% (high taker) + high paired + ~50% leftover
      6. MAKER SCALPER: high maker% but moderate paired (recycling inventory)
      7. UNCLASSIFIED otherwise
    """
    leftover = stats.get("leftover", {})
    basic = stats.get("basic", {})
    paired = leftover.get("mean_paired_pct", float("nan"))
    leftover_won = leftover.get("leftover_on_winner_pct", float("nan"))
    leftover_won_w = leftover.get("leftover_on_winner_pct_size_weighted", float("nan"))
    maker_pct = basic.get("maker_pct", float("nan"))
    n_trades = basic.get("n_trades", 0)
    n_material = leftover.get("n_material", 0)
    notional = basic.get("sum_notional", 0)
    days = max(basic.get("window_days", 1), 0.01)
    chain_daily = (notional or 0) / days

    # Reported PnL (from the wallet's known reputation)
    kpnl_str = stats.get("kpnl", "")
    is_negative_reported = kpnl_str.startswith("$-") or "-39" in kpnl_str

    # 1. Explicit LOSER (caller-supplied or strong adverse + high churn)
    if is_negative_reported:
        return "LOSER"

    # 2. DIRECTIONAL: heavy directional positioning with >55% winner rate
    if not math.isnan(leftover_won) and leftover_won > 0.55 and n_material > 50 \
       and (math.isnan(paired) or paired < 0.40):
        return "DIRECTIONAL"

    # 3. HYBRID: paired base + directional edge
    if not math.isnan(paired) and 0.55 < paired < 0.92 and \
       not math.isnan(leftover_won) and leftover_won > 0.55 and n_material > 50:
        return "HYBRID"

    # 4. MAKER PAIR ARB
    if not math.isnan(maker_pct) and maker_pct > 0.85 and \
       not math.isnan(paired) and paired > 0.80 and \
       (math.isnan(leftover_won) or 0.42 < leftover_won < 0.58):
        return "MAKER PAIR ARB"

    # 5. TAKER PAIR ARB (high paired but mostly hitting books)
    if not math.isnan(maker_pct) and maker_pct < 0.30 and \
       not math.isnan(paired) and paired > 0.90 and \
       (math.isnan(leftover_won) or 0.42 < leftover_won < 0.58):
        return "TAKER PAIR ARB"

    # 6. MAKER SCALPER (broad maker presence, partial pairing)
    if not math.isnan(maker_pct) and maker_pct > 0.85 and n_trades > 30000 and \
       (math.isnan(paired) or paired < 0.80):
        return "MAKER SCALPER"

    return "UNCLASSIFIED"


def recommendation(klass, stats, kpnl):
    """Trade-the-wallet recommendation."""
    if klass == "MAKER PAIR ARB":
        return (f"COPY (high confidence). Pair-arb on maker side is self-hedging — directional risk minimal. "
                f"Replication needs Polymarket maker access + L25 book + rebate-aware fee model. "
                f"Reference is the mint-and-sell V2 spec (MINT_AND_SELL_*_2026_05_16.md).")
    if klass == "TAKER PAIR ARB":
        return (f"INVESTIGATE before copying. Pair-arb done as taker is unusual (pays 7%×p×(1-p) per leg). "
                f"Most likely losing or accepting slippage to defend hedge. Look at PnL trajectory.")
    if klass == "MAKER SCALPER":
        return (f"COPY ONLY WITH FULL MAKER STACK. Requires Polymarket maker rebate, tight latency, "
                f"inventory recycling pipeline. Spec at-risk if rebate model shifts.")
    if klass == "HYBRID":
        return (f"COPY (medium confidence). Mix of pair-arb base + directional edge. "
                f"Replicable for the paired portion; directional trigger needs separate decode.")
    if klass == "DIRECTIONAL":
        return (f"DO NOT COPY (until directional signal decoded). Has alpha but trigger likely "
                f"requires private data (CLOB tape, slug-selector signal). See F2 verdict for analogue.")
    if klass == "LOSER":
        return (f"DO NOT COPY. Underperforms. Reported {kpnl}. Note: high chain volume "
                f"can be misleading — net PnL is what matters.")
    return (f"INVESTIGATE FURTHER. Mixed signals; full deepdive needed.")


def analyze_wallet(w_info, resolutions, token_lookup):
    w = w_info["addr"]
    print(f"\n===== {w} ({w_info['note']}) =====")
    out = {"addr": w, "kpnl": w_info["kpnl"], "note": w_info["note"]}

    trades = load_trades(w)
    fires = load_fires(w)
    if trades is None and fires is None:
        out["error"] = "no data"
        return out

    # Section 1
    out["basic"] = stats_basic(trades, fires, w)
    print(f"  basic: {out['basic']}")

    # merge trades with token lookup
    if trades is not None:
        merged = trades.merge(
            token_lookup[["asset_id", "slug", "outcome", "mkt_asset", "market_class"]],
            left_on="asset", right_on="asset_id", how="left"
        )
        # drop unmatched for downstream slug-aware sections
        merged_m = merged[merged.slug.notna()].copy()
        out["cells"] = stats_cells(merged_m)
        print(f"  cells: {out['cells']}")

        # Section 2 + 3
        slug_agg = per_slug_accumulation(merged_m)
        if slug_agg is not None:
            out["slug_agg_n"] = int(len(slug_agg))
            out["leftover"] = leftover_alpha(slug_agg, resolutions)
            print(f"  leftover: {out['leftover']}")
        else:
            slug_agg = None
            out["leftover"] = {}

        # Section 5
        out["vol_filter"] = vol_filter(slug_agg, resolutions)
        print(f"  vol_filter: {out['vol_filter']}")

        # Section 7
        out["slug_selection"] = slug_selection_rate(slug_agg, resolutions)
        print(f"  slug_selection: {out['slug_selection']}")
    else:
        merged_m = None
        slug_agg = None

    # Section 4
    out["time_of_day"] = time_of_day(trades if trades is not None else None)
    if out["time_of_day"]:
        print(f"  time_of_day: active_hours={out['time_of_day'].get('active_hours')}, "
              f"peak={out['time_of_day'].get('peak_hour')}h ({out['time_of_day'].get('peak_pct'):.1%})")

    # Section 6 (requires fires_decoded)
    out["momentum"] = momentum_following(fires)
    print(f"  momentum: {out['momentum']}")

    # Classify
    out["kpnl"] = w_info["kpnl"]  # used by classifier
    out["class"] = classify_strategy(out)
    out["recommendation"] = recommendation(out["class"], out, w_info["kpnl"])
    print(f"  CLASS: {out['class']}")
    print(f"  REC: {out['recommendation']}")

    return out


def render_report(results):
    lines = []
    lines.append("# Multi-Wallet Alpha Decode — 2026-05-18")
    lines.append("")
    lines.append("Generated by `strategy_lab/reports/_multi_wallet_alpha_decode.py`. "
                 "Window per wallet = whatever the cache covers (1.6 – 6.2 days). "
                 "Trades joined to slugs via `_token_lookup.parquet`. "
                 "Outcomes from chainlink-only canonical resolutions.")
    lines.append("")
    lines.append("## How to read")
    lines.append("- **paired_pct** = 2 × min(up,dn) / (up+dn) per slug — 1.0 = perfectly hedged, 0 = pure directional")
    lines.append("- **leftover_on_winner_pct** = of slugs with >10-share residual, what % end up on chainlink winner. 50% = no alpha")
    lines.append("- **selection_rate** = N slugs traded / N slugs available in active window+asset+timeframe")
    lines.append("- **ratio_traded_to_skipped** (vol) = mean 120s pre-slug vol for traded / skipped (1.0 = no filter)")
    lines.append("")

    for r in results:
        lines.append(f"## {r['addr']} — {r['note']} ({r['kpnl']})")
        b = r.get("basic", {})
        if not b:
            lines.append(f"_no data_")
            lines.append("")
            continue
        lines.append("")
        lines.append("### 1. Basic")
        lines.append(f"- N trades: **{b.get('n_trades')}**, window {b.get('window_start')} → {b.get('window_end')} ({b.get('window_days', 0):.2f}d)")
        if not math.isnan(b.get("maker_pct", float("nan"))):
            lines.append(f"- Maker %: **{b.get('maker_pct'):.1%}**, Taker %: **{b.get('taker_pct'):.1%}**")
        if not math.isnan(b.get("sum_notional", float("nan"))):
            daily = b.get("sum_notional", 0) / max(b.get("window_days", 1), 0.01)
            lines.append(f"- Sum notional: **${b.get('sum_notional'):,.0f}** ({daily/1e3:.0f}k / day chain-volume)")
        lines.append("")
        cells = r.get("cells", {})
        if cells:
            lines.append("### Cells")
            for k, v in sorted(cells.items(), key=lambda kv: -kv[1])[:6]:
                lines.append(f"- `{k}`: {v}")
            lines.append("")

        lo = r.get("leftover", {})
        if lo:
            lines.append("### 2-3. Per-slug accumulation & leftover alpha")
            lines.append(f"- N slugs traded: {r.get('slug_agg_n')}")
            lines.append(f"- N w/ resolution: {lo.get('n_with_res')}; N with material (>10-share) leftover: **{lo.get('n_material')}**")
            if "leftover_on_winner_pct" in lo:
                lines.append(f"- **leftover_on_winner_pct: {lo['leftover_on_winner_pct']:.1%}** "
                             f"(size-weighted: {lo['leftover_on_winner_pct_size_weighted']:.1%})")
            if "mean_paired_pct" in lo:
                lines.append(f"- mean paired_pct: **{lo['mean_paired_pct']:.1%}**, median: {lo['median_paired_pct']:.1%}")
            lines.append("")

        tod = r.get("time_of_day", {})
        if tod:
            lines.append("### 4. Time of day (UTC)")
            lines.append(f"- active_hours: {tod.get('active_hours')}/24, peak hour: **{tod.get('peak_hour')}h** "
                         f"({tod.get('peak_pct'):.1%} of trades)")
            by = tod.get("by_hr", {})
            top5 = sorted(by.items(), key=lambda kv: -kv[1]["trades"])[:5]
            top5_str = ", ".join("{:02d}h={:.1%}".format(h, d["pct"]) for h, d in top5)
            lines.append(f"- top 5 hours: {top5_str}")
            lines.append("")

        vf = r.get("vol_filter", {})
        if vf and "ratio_traded_to_skipped" in vf:
            lines.append("### 5. Volatility filter")
            lines.append(f"- {vf['primary_asset']}: traded vol_120s mean={vf['traded_vol_mean']:.5f} "
                         f"(n={vf['n_traded']}), skipped={vf['skipped_vol_mean']:.5f} (n={vf['n_skipped']})")
            r_v = vf['ratio_traded_to_skipped']
            interp = "prefers HIGH vol" if r_v > 1.15 else ("prefers LOW vol" if r_v < 0.85 else "no clear preference")
            lines.append(f"- ratio traded/skipped: **{r_v:.2f}** ({interp})")
            lines.append("")
        elif vf:
            lines.append(f"### 5. Volatility filter — _{vf}_")
            lines.append("")

        mom = r.get("momentum", {})
        if mom and "n_late" in mom and mom["n_late"] > 0:
            lines.append("### 6. Binance momentum following (late-bucket fires)")
            lines.append(f"- N late fires (offset >240s): {mom['n_late']}")
            has_any_match = False
            for k, v in mom.items():
                if "match" in k and isinstance(v, (int, float)):
                    interp = "FOLLOW" if v > 0.55 else ("FADE" if v < 0.45 else "neutral")
                    lines.append(f"- {k}: **{v:.1%}** ({interp})")
                    has_any_match = True
            if not has_any_match:
                lines.append(f"- **No usable returns**: fires window is after binance-kline max ts "
                             f"(canonical klines end 2026-05-16 03:47); all 1-min returns computed as 0. "
                             f"Needs fresher klines for this wallet's fire window.")
            lines.append("")

        ss = r.get("slug_selection", {})
        if ss and "selection_rate" in ss:
            lines.append("### 7. Slug selection rate")
            lines.append(f"- {ss['primary_asset']} {ss['primary_tf']}: **{ss['n_traded_in_window']}/{ss['n_avail_in_window']}** "
                         f"= {ss['selection_rate']:.1%}")
            interp = "BROAD (~hits everything)" if ss['selection_rate'] > 0.8 else (
                "SELECTIVE" if ss['selection_rate'] < 0.3 else "moderate")
            lines.append(f"- regime: **{interp}**")
            lines.append("")

        lines.append(f"### Classification & recommendation")
        lines.append(f"- **Strategy class: {r['class']}**")
        lines.append(f"- {r['recommendation']}")
        lines.append("")
        lines.append("---")
        lines.append("")

    # cross-wallet table
    lines.append("## Cross-wallet comparison")
    lines.append("")
    lines.append("| Wallet | $/day (reported) | Class | Paired% | Leftover-on-winner% | Time pattern | Vol pref | Selection | Replicable? |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for r in results:
        b = r.get("basic", {})
        lo = r.get("leftover", {})
        tod = r.get("time_of_day", {})
        vf = r.get("vol_filter", {})
        ss = r.get("slug_selection", {})
        paired = lo.get("mean_paired_pct")
        paired_str = f"{paired:.1%}" if paired is not None and not math.isnan(paired) else "—"
        lw = lo.get("leftover_on_winner_pct")
        lw_str = f"{lw:.1%} (n={lo.get('n_material',0)})" if lw is not None else "—"
        ah = tod.get("active_hours", 0)
        tp = f"{ah}/24h, peak {tod.get('peak_hour','?')}h ({tod.get('peak_pct',0):.0%})" if tod else "—"
        rv = vf.get("ratio_traded_to_skipped")
        vp = f"{rv:.2f}x" if rv is not None else "—"
        sr = ss.get("selection_rate")
        sr_str = f"{sr:.1%} ({ss.get('n_traded_in_window','?')}/{ss.get('n_avail_in_window','?')})" if sr is not None else "—"
        repl = {
            "MAKER PAIR ARB": "YES",
            "TAKER PAIR ARB": "investigate",
            "MAKER SCALPER": "YES (needs maker stack)",
            "HYBRID": "YES (partial)",
            "DIRECTIONAL": "NO (signal undecoded)",
            "LOSER": "no",
            "UNCLASSIFIED": "?"
        }.get(r["class"], "?")
        lines.append(f"| `{r['addr']}` | {r['kpnl']} | {r['class']} | {paired_str} | {lw_str} | {tp} | {vp} | {sr_str} | {repl} |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Notes & caveats")
    lines.append("- Cache windows are short (1.6 – 6.2 days). Stats with n<50 in any cell are weak.")
    lines.append("- `0xb27bc932` has only `fires_decoded.parquet` (600 fires, 12-minute slice). All trades_chain-derived sections (1, 2, 3, 5, 7) are SKIPPED. Only sec 6 momentum is reportable.")
    lines.append("- Token-lookup match rate ~97% — unmatched tokens dropped from slug-aware sections.")
    lines.append("- `binance_ret_*` columns in `fires_decoded.parquet` were all-zero for `0x89b5cdaa` and `0xeebde7a0`. Re-derivation attempted via `load_klines_asof` but the canonical binance/coinbase/kraken/okx klines end at **2026-05-16 03:47** while both wallets' fire-cache windows extend to 06:40 → 09:50 UTC. Result: section 6 momentum unavailable for those two wallets. Fix = pull fresh binance klines to cover 03:47 → 09:50 then re-run section 6 only.")
    lines.append("- Cross-validate any 'COPY' verdict against a longer window before committing capital. See `MINT_AND_SELL_*` reports for the pair-arb deploy spec, and `F2_FINAL_VERDICT_2026_05_18.md` for the directional-decode template.")
    lines.append("- This report does **not** compute Polymarket-fee-adjusted PnL per wallet — only signal characteristics. Net-PnL replication study is the next step before live capital.")
    return "\n".join(lines)


def main():
    print("Loading canonical resolutions...")
    resolutions = load_resolutions()
    print(f"  resolutions n={len(resolutions)}")
    print("Loading token lookup...")
    token_lookup = load_token_lookup()
    print(f"  tokens n={len(token_lookup)}")

    results = []
    for w_info in WALLETS:
        try:
            results.append(analyze_wallet(w_info, resolutions, token_lookup))
        except Exception as e:
            import traceback
            traceback.print_exc()
            results.append({"addr": w_info["addr"], "kpnl": w_info["kpnl"], "note": w_info["note"],
                            "error": f"{type(e).__name__}: {e}", "class": "ERROR",
                            "recommendation": "errored — see traceback"})

    print("\nRendering report...")
    md = render_report(results)
    REPORT.write_text(md, encoding="utf-8")
    print(f"Wrote {REPORT}")
    # Also write json for downstream
    json_path = REPORT.with_suffix(".json")
    json_path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"Wrote {json_path}")


if __name__ == "__main__":
    main()
