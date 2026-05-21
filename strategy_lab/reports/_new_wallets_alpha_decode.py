"""Alpha decode pipeline for 0xb27bc932 and 0x7dfc8aa2 (NEW wallets).
Output: NEW_WALLETS_ALPHA_DECODE_2026_05_18.md (same schema as MULTI_WALLET_ALPHA_DECODE_2026_05_18.md).
"""
import sys
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, 'data/v4/canonical')
from load import load_resolutions, load_klines_asof, asof_strict

REPO = Path(r"C:\Users\alexandre bandarra\Desktop\global")
CACHE = REPO / "strategy_lab/wallet_hunt/cache"
REPORT = REPO / "strategy_lab/reports/NEW_WALLETS_ALPHA_DECODE_2026_05_18.md"

USDC_E = "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb"   # USDC.e (older)
USDC   = "0x2791bca1f2de4661ed88a30c99a7a9449aa84174"   # USDC

WALLETS = [
    {"addr": "0xb27bc932", "kpnl": "$254k/day (reputed)",
     "note": "kingpin scalper — 99.98% maker for 3.4d"},
    {"addr": "0x7dfc8aa2", "kpnl": "unknown (NEW)",
     "note": "NEW — 84k fills/14.3d, 93% of fires have sum_asks>$1"},
]


def load_token_lookup():
    return pd.read_parquet(CACHE / "_token_lookup.parquet")


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


def load_transfers(w):
    p = CACHE / w / "alchemy_transfers.parquet"
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


def stats_basic(trades, fires):
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
    return out


def stats_cells(merged):
    if "mkt_asset" not in merged.columns:
        return {}
    g = merged.groupby(["mkt_asset", "market_class"], dropna=False).size()
    return {f"{a}_{c}": int(n) for (a, c), n in g.items()}


def per_slug_accumulation(merged):
    """Section 2 — per-slug shares_up/shares_dn."""
    if "slug" not in merged.columns:
        return None
    m = merged.copy()
    m["wallet_action"] = m.apply(normalize_wallet_side, axis=1)
    m["signed_size"] = np.where(m.wallet_action == "BUY", m["size"], -m["size"])
    m = m[m.market_class.fillna("").str.startswith("updown_")]
    if len(m) == 0:
        return None
    agg = m.groupby(["slug", "outcome"]).signed_size.sum().unstack(fill_value=0.0)
    if "Up" not in agg.columns: agg["Up"] = 0.0
    if "Down" not in agg.columns: agg["Down"] = 0.0
    agg["shares_up"] = agg["Up"].astype(float)
    agg["shares_dn"] = agg["Down"].astype(float)
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
    r = resolutions[["slug", "outcome"]].rename(columns={"outcome": "winner"})
    j = slug_agg.merge(r, on="slug", how="left")
    mat = j[(j.leftover_amt > 10) & j.winner.notna()].copy()
    if len(mat) == 0:
        return {"n_material": 0, "n_with_res": int(j.winner.notna().sum()),
                "mean_paired_pct": float(j.paired_pct.dropna().mean()) if j.paired_pct.notna().any() else float("nan"),
                "median_paired_pct": float(j.paired_pct.dropna().median()) if j.paired_pct.notna().any() else float("nan")}
    mat["leftover_won"] = (mat.leftover_side == mat.winner).astype(int)
    won_pct = mat.leftover_won.mean()
    w_won_pct = (mat.leftover_won * mat.leftover_amt).sum() / mat.leftover_amt.sum()
    return {
        "n_material": int(len(mat)),
        "n_with_res": int(j.winner.notna().sum()),
        "leftover_on_winner_pct": float(won_pct),
        "leftover_on_winner_pct_size_weighted": float(w_won_pct),
        "mean_paired_pct": float(j.paired_pct.dropna().mean()),
        "median_paired_pct": float(j.paired_pct.dropna().median()),
    }


def time_of_day(trades):
    if trades is None or len(trades) == 0:
        return {}
    ts = pd.to_datetime(trades.timestamp, unit="s", utc=True)
    hr = ts.dt.hour.value_counts().sort_index()
    total = hr.sum()
    by_hr = {int(h): {"trades": int(c), "pct": float(c / total)} for h, c in hr.items()}
    active_hours = int((hr > 0).sum())
    peak_hour = int(hr.idxmax())
    peak_pct = float(hr.max() / total)
    return {"by_hr": by_hr, "active_hours": active_hours, "peak_hour": peak_hour, "peak_pct": peak_pct}


def vol_filter(slug_agg, resolutions, max_compare=300):
    if slug_agg is None or len(slug_agg) == 0:
        return {}
    traded_slugs = set(slug_agg.slug)
    j = resolutions[resolutions.slug.isin(traded_slugs)]
    if len(j) == 0:
        return {"skip_reason": "no resolution overlap"}
    asset_mix = j.ticker.value_counts().to_dict()
    primary_asset = max(asset_mix, key=asset_mix.get)
    t_lo = j.slot_start_us.min()
    t_hi = j.slot_end_us.max()
    avail = resolutions[(resolutions.ticker == primary_asset) &
                        (resolutions.slot_start_us >= t_lo) &
                        (resolutions.slot_start_us <= t_hi)]
    skipped_slugs = set(avail.slug) - traded_slugs
    rng = np.random.default_rng(42)
    traded_sample = list(traded_slugs & set(avail.slug))
    if len(traded_sample) > max_compare:
        traded_sample = list(rng.choice(traded_sample, max_compare, replace=False))
    skipped_sample = list(skipped_slugs)
    if len(skipped_sample) > max_compare:
        skipped_sample = list(rng.choice(skipped_sample, max_compare, replace=False))
    try:
        end_us, prices = load_klines_asof(primary_asset, "binance-spot-ws", "1MIN")
    except Exception as e:
        return {"skip_reason": f"klines load err: {e}"}
    # quick coverage check
    k_max = end_us.max() if len(end_us) else 0
    if k_max < t_lo:
        return {"skip_reason": f"binance klines end before wallet window (k_max={pd.Timestamp(k_max,unit='us')}, t_lo={pd.Timestamp(t_lo,unit='us')})"}

    avail_indexed = avail.set_index("slug")[["slot_start_us"]]
    def vol_at(slug_):
        try:
            ts = int(avail_indexed.loc[slug_, "slot_start_us"])
        except KeyError:
            return np.nan
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


def momentum_following(fires, max_sample=500):
    """Section 6 — Binance momentum match rate for late-bucket fires.
    Wallet bought side (Up/Down): if it BOUGHT Up or SHORTED Down → benefits from price-up.
    """
    if fires is None or len(fires) == 0:
        return {}
    f = fires[fires.offset_from_slot_start_s > 240]
    if len(f) == 0:
        return {"n_late": 0}
    out = {"n_late": int(len(f))}
    for asset in f.asset_sym.dropna().unique():
        asset_str = str(asset).upper()
        if asset_str not in ("BTC", "ETH", "SOL"):
            continue
        sub = f[f.asset_sym == asset]
        if len(sub) == 0:
            continue
        if len(sub) > max_sample:
            sub = sub.sample(n=max_sample, random_state=42)
        try:
            end_us, prices = load_klines_asof(asset_str, "binance-spot-ws", "1MIN")
        except Exception as e:
            out[f"{asset_str}_err"] = str(e)
            continue
        k_max = end_us.max() if len(end_us) else 0
        sub_ts_max = int(sub.ts_us.max())
        if k_max < sub_ts_max:
            out[f"{asset_str}_kline_gap"] = f"klines end {pd.Timestamp(k_max,unit='us')}, fires end {pd.Timestamp(sub_ts_max,unit='us')}"
        ret60, ret120 = [], []
        for _, row in sub.iterrows():
            ts = int(row.ts_us)
            p0 = asof_strict(end_us, prices, ts)
            p60 = asof_strict(end_us, prices, ts - 60_000_000)
            p120 = asof_strict(end_us, prices, ts - 120_000_000)
            ret60.append(np.log(p0/p60) if p0 > 0 and p60 > 0 else np.nan)
            ret120.append(np.log(p0/p120) if p0 > 0 and p120 > 0 else np.nan)
        ret60 = np.array(ret60)
        ret120 = np.array(ret120)
        sides = sub.wallet_side.astype(str).str.upper().values
        outcomes = sub.outcome.astype(str).values
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


def usdc_cash_pnl(transfers):
    """Section 9 — USDC cash inflow/outflow per day.
    direction='to' means inbound (received), 'from' means outbound (sent)."""
    if transfers is None or len(transfers) == 0:
        return {}
    # numeric ts
    transfers = transfers.copy()
    # ts is ISO8601 string (e.g. '2026-05-12T09:56:28.000Z')
    transfers["ts"] = pd.to_datetime(transfers["ts"], utc=True, errors="coerce").astype("int64") // 10**9
    transfers = transfers[transfers.ts > 0]
    usdc_mask = transfers.raw_contract.str.lower().isin([USDC_E.lower(), USDC.lower()])
    u = transfers[usdc_mask].copy()
    if len(u) == 0:
        return {"note": "no USDC transfers"}
    inflow = float(u[u.direction == "to"].value.sum())
    outflow = float(u[u.direction == "from"].value.sum())
    net = inflow - outflow
    t_min, t_max = float(u.ts.min()), float(u.ts.max())
    days = max((t_max - t_min) / 86400, 0.01)
    return {
        "n_usdc_tx": int(len(u)),
        "usdc_inflow": inflow,
        "usdc_outflow": outflow,
        "usdc_net": net,
        "usdc_net_per_day": net / days,
        "window_days": days,
        "window_start": pd.Timestamp(t_min, unit="s").strftime("%Y-%m-%d %H:%M:%S"),
        "window_end": pd.Timestamp(t_max, unit="s").strftime("%Y-%m-%d %H:%M:%S"),
    }


def fires_microstructure(fires):
    """Diagnostics on fires_decoded — book features at fire time."""
    if fires is None or len(fires) == 0:
        return {}
    out = {"n_fires": int(len(fires))}
    if "sum_asks" in fires.columns:
        sa = fires.sum_asks.dropna()
        if len(sa):
            out["sum_asks_gt_1_pct"] = float((sa > 1.0).mean())
            out["sum_asks_median"] = float(sa.median())
    if "counterparty" in fires.columns:
        out["counterparty_mix"] = fires.counterparty.value_counts(normalize=True).head(3).to_dict()
    if "offset_from_slot_start_s" in fires.columns:
        off = fires.offset_from_slot_start_s.dropna()
        if len(off):
            out["offset_median_s"] = float(off.median())
            out["offset_pct_late_240s"] = float((off > 240).mean())
    return out


def classify_strategy(stats):
    leftover = stats.get("leftover", {})
    basic = stats.get("basic", {})
    paired = leftover.get("mean_paired_pct", float("nan"))
    leftover_won = leftover.get("leftover_on_winner_pct", float("nan"))
    maker_pct = basic.get("maker_pct", float("nan"))
    n_trades = basic.get("n_trades", 0)
    n_material = leftover.get("n_material", 0)

    usdc = stats.get("usdc", {})
    net_per_day = usdc.get("usdc_net_per_day", 0)
    is_negative = isinstance(net_per_day, (int, float)) and net_per_day < -500

    if is_negative:
        return "LOSER"
    if not math.isnan(leftover_won) and leftover_won > 0.55 and n_material > 50 \
       and (math.isnan(paired) or paired < 0.40):
        return "DIRECTIONAL"
    if not math.isnan(paired) and 0.55 < paired < 0.92 and \
       not math.isnan(leftover_won) and leftover_won > 0.55 and n_material > 50:
        return "HYBRID"
    if not math.isnan(maker_pct) and maker_pct > 0.85 and \
       not math.isnan(paired) and paired > 0.80 and \
       (math.isnan(leftover_won) or 0.42 < leftover_won < 0.58):
        return "MAKER PAIR ARB"
    if not math.isnan(maker_pct) and maker_pct < 0.30 and \
       not math.isnan(paired) and paired > 0.90 and \
       (math.isnan(leftover_won) or 0.42 < leftover_won < 0.58):
        return "TAKER PAIR ARB"
    if not math.isnan(maker_pct) and maker_pct > 0.85 and n_trades > 30000 and \
       (math.isnan(paired) or paired < 0.80):
        return "MAKER SCALPER"
    return "UNCLASSIFIED"


def recommendation(klass):
    if klass == "MAKER PAIR ARB":
        return ("COPY (high confidence). Pair-arb on maker side is self-hedging. "
                "Replication needs Polymarket maker access + L25 book + rebate-aware fee model. "
                "Reference is mint-and-sell V2 spec (MINT_AND_SELL_*_2026_05_16.md).")
    if klass == "TAKER PAIR ARB":
        return ("INVESTIGATE before copying. Taker pair-arb pays 7%×p×(1-p) per leg; usually losing or eats slippage.")
    if klass == "MAKER SCALPER":
        return ("COPY ONLY WITH FULL MAKER STACK. Requires Polymarket maker rebate, tight latency, "
                "inventory recycling pipeline.")
    if klass == "HYBRID":
        return ("COPY (medium confidence). Mix of pair-arb base + directional edge. "
                "Replicable for the paired portion; directional trigger needs separate decode.")
    if klass == "DIRECTIONAL":
        return ("DO NOT COPY (until directional signal decoded). Trigger likely requires private data.")
    if klass == "LOSER":
        return "DO NOT COPY. Net USDC outflow."
    return "INVESTIGATE FURTHER. Mixed signals; full deepdive needed."


def analyze_wallet(w_info, resolutions, token_lookup):
    w = w_info["addr"]
    print(f"\n===== {w} ({w_info['note']}) =====", flush=True)
    out = {"addr": w, "kpnl": w_info["kpnl"], "note": w_info["note"]}

    trades = load_trades(w)
    fires = load_fires(w)
    transfers = load_transfers(w)
    if trades is None and fires is None:
        out["error"] = "no data"
        return out

    out["basic"] = stats_basic(trades, fires)
    print(f"  basic: n={out['basic'].get('n_trades')}, maker={out['basic'].get('maker_pct',0):.1%}, days={out['basic'].get('window_days',0):.2f}", flush=True)

    if trades is not None:
        merged = trades.merge(
            token_lookup[["asset_id", "slug", "outcome", "mkt_asset", "market_class"]],
            left_on="asset", right_on="asset_id", how="left"
        )
        merged_m = merged[merged.slug.notna()].copy()
        out["token_match_pct"] = float(len(merged_m) / max(len(merged), 1))
        out["cells"] = stats_cells(merged_m)
        print(f"  cells: {out['cells']}", flush=True)

        slug_agg = per_slug_accumulation(merged_m)
        if slug_agg is not None:
            out["slug_agg_n"] = int(len(slug_agg))
            out["leftover"] = leftover_alpha(slug_agg, resolutions)
            print(f"  leftover: paired={out['leftover'].get('mean_paired_pct',float('nan')):.2%}, leftover_on_winner={out['leftover'].get('leftover_on_winner_pct',float('nan')):.2%}, n_material={out['leftover'].get('n_material')}", flush=True)
        else:
            out["leftover"] = {}

        out["vol_filter"] = vol_filter(slug_agg, resolutions)
        print(f"  vol_filter: {out['vol_filter']}", flush=True)

        out["slug_selection"] = slug_selection_rate(slug_agg, resolutions)
        print(f"  slug_selection: {out['slug_selection']}", flush=True)

    out["time_of_day"] = time_of_day(trades)
    if out["time_of_day"]:
        tod = out["time_of_day"]
        print(f"  time_of_day: active={tod.get('active_hours')}/24, peak {tod.get('peak_hour')}h ({tod.get('peak_pct',0):.1%})", flush=True)

    out["momentum"] = momentum_following(fires)
    print(f"  momentum: n_late={out['momentum'].get('n_late')}", flush=True)
    for k, v in out["momentum"].items():
        if isinstance(v, float):
            print(f"    {k}: {v:.3f}", flush=True)
        elif "err" in k or "gap" in k:
            print(f"    {k}: {v}", flush=True)

    out["fires_micro"] = fires_microstructure(fires)
    print(f"  fires_micro: {out['fires_micro']}", flush=True)

    out["usdc"] = usdc_cash_pnl(transfers)
    print(f"  usdc: net=${out['usdc'].get('usdc_net',0):,.0f}, per_day=${out['usdc'].get('usdc_net_per_day',0):,.0f}, days={out['usdc'].get('window_days',0):.2f}", flush=True)

    out["class"] = classify_strategy(out)
    out["recommendation"] = recommendation(out["class"])
    print(f"  CLASS: {out['class']}", flush=True)
    print(f"  REC: {out['recommendation']}", flush=True)

    return out


def render_report(results):
    lines = []
    lines.append("# New Wallets Alpha Decode — 2026-05-18")
    lines.append("")
    lines.append("Generated by `strategy_lab/reports/_new_wallets_alpha_decode.py`. "
                 "Targets two newly-collected wallets: `0xb27bc932` (kingpin scalper / 99.98% maker) "
                 "and `0x7dfc8aa2` (new). Same pipeline as `MULTI_WALLET_ALPHA_DECODE_2026_05_18.md`.")
    lines.append("")
    lines.append("## How to read")
    lines.append("- **paired_pct** = 2 × min(up,dn) / (up+dn) per slug — 1.0 = perfectly hedged, 0 = pure directional")
    lines.append("- **leftover_on_winner_pct** = of slugs with >10-share residual, what % end up on chainlink winner. 50% = no alpha")
    lines.append("- **selection_rate** = N slugs traded / N slugs available in active window+asset+timeframe")
    lines.append("- **ratio_traded_to_skipped** (vol) = mean 120s pre-slug vol for traded / skipped (1.0 = no filter)")
    lines.append("- **usdc_net_per_day** = (USDC inflow − outflow) / days in transfer window — proxy for net realized PnL (excludes erc1155 inventory value, so positive number = realized cash; negative = burning cash)")
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
            lines.append(f"- Maker %: **{b.get('maker_pct'):.2%}**, Taker %: **{b.get('taker_pct'):.2%}**")
        if not math.isnan(b.get("sum_notional", float("nan"))):
            daily = b.get("sum_notional", 0) / max(b.get("window_days", 1), 0.01)
            lines.append(f"- Sum notional: **${b.get('sum_notional'):,.0f}** ({daily/1e3:,.0f}k / day chain-volume)")
        if "token_match_pct" in r:
            lines.append(f"- Token-lookup match: {r['token_match_pct']:.1%}")
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
            if "mean_paired_pct" in lo and not math.isnan(lo.get("mean_paired_pct", float("nan"))):
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
            lines.append("### 6. Binance momentum following (late-bucket fires, offset >240s)")
            lines.append(f"- N late fires: {mom['n_late']}")
            has_any_match = False
            for k, v in mom.items():
                if "match" in k and isinstance(v, (int, float)):
                    interp = "FOLLOW" if v > 0.55 else ("FADE" if v < 0.45 else "neutral")
                    lines.append(f"- {k}: **{v:.1%}** ({interp})")
                    has_any_match = True
            for k, v in mom.items():
                if "kline_gap" in k or "_err" in k:
                    lines.append(f"- _{k}: {v}_")
            if not has_any_match:
                lines.append(f"- **No usable returns**: see kline_gap above.")
            lines.append("")

        fm = r.get("fires_micro", {})
        if fm:
            lines.append("### 6b. Fires microstructure")
            lines.append(f"- n_fires (decoded): {fm.get('n_fires')}")
            if "sum_asks_gt_1_pct" in fm:
                lines.append(f"- sum_asks > $1: **{fm['sum_asks_gt_1_pct']:.1%}** of fires (median ${fm['sum_asks_median']:.3f})")
            if "offset_median_s" in fm:
                lines.append(f"- offset median: {fm['offset_median_s']:.0f}s, % late (>240s): {fm['offset_pct_late_240s']:.1%}")
            if "counterparty_mix" in fm:
                cp = fm["counterparty_mix"]
                cp_str = ", ".join(f"{k}={v:.1%}" for k, v in cp.items())
                lines.append(f"- counterparty: {cp_str}")
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

        u = r.get("usdc", {})
        if u and "usdc_net" in u:
            lines.append("### 9. USDC cash PnL (alchemy_transfers)")
            lines.append(f"- USDC tx: {u['n_usdc_tx']}, window {u['window_start']} → {u['window_end']} ({u['window_days']:.2f}d)")
            lines.append(f"- inflow: ${u['usdc_inflow']:,.0f}, outflow: ${u['usdc_outflow']:,.0f}")
            lines.append(f"- **net: ${u['usdc_net']:,.0f}** → **${u['usdc_net_per_day']:,.0f}/day cash flow** (excludes outstanding erc1155 inventory)")
            lines.append("")

        lines.append(f"### Classification & recommendation")
        lines.append(f"- **Strategy class: {r['class']}**")
        lines.append(f"- {r['recommendation']}")
        lines.append("")
        lines.append("---")
        lines.append("")

    # cross-wallet table
    lines.append("## Cross-wallet comparison (this report)")
    lines.append("")
    lines.append("| Wallet | $/day reputed | $/day cash (USDC) | Class | Maker% | Paired% | Leftover-on-winner% | Time pattern | Vol pref | Selection | Replicable? |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in results:
        b = r.get("basic", {})
        lo = r.get("leftover", {})
        tod = r.get("time_of_day", {})
        vf = r.get("vol_filter", {})
        ss = r.get("slug_selection", {})
        u = r.get("usdc", {})
        mk = b.get("maker_pct")
        mk_str = f"{mk:.1%}" if mk is not None and not math.isnan(mk) else "—"
        paired = lo.get("mean_paired_pct")
        paired_str = f"{paired:.1%}" if paired is not None and not (isinstance(paired, float) and math.isnan(paired)) else "—"
        lw = lo.get("leftover_on_winner_pct")
        lw_str = f"{lw:.1%} (n={lo.get('n_material',0)})" if lw is not None else "—"
        ah = tod.get("active_hours", 0)
        tp = f"{ah}/24h, peak {tod.get('peak_hour','?')}h ({tod.get('peak_pct',0):.0%})" if tod else "—"
        rv = vf.get("ratio_traded_to_skipped")
        vp = f"{rv:.2f}x" if rv is not None else "—"
        sr = ss.get("selection_rate")
        sr_str = f"{sr:.1%}" if sr is not None else "—"
        cash = u.get("usdc_net_per_day")
        cash_str = f"${cash:,.0f}" if cash is not None else "—"
        repl = {
            "MAKER PAIR ARB": "YES",
            "TAKER PAIR ARB": "investigate",
            "MAKER SCALPER": "YES (needs maker stack)",
            "HYBRID": "YES (partial)",
            "DIRECTIONAL": "NO (signal undecoded)",
            "LOSER": "no",
            "UNCLASSIFIED": "?"
        }.get(r["class"], "?")
        lines.append(f"| `{r['addr']}` | {r['kpnl']} | {cash_str} | {r['class']} | {mk_str} | {paired_str} | {lw_str} | {tp} | {vp} | {sr_str} | {repl} |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Cross-report 7-wallet ranking
    lines.append("## 7-wallet replicability ranking (this report + prior reports)")
    lines.append("")
    lines.append("Aggregates this report's findings with `MULTI_WALLET_ALPHA_DECODE_2026_05_18.md` "
                 "and `WALLET_STRATEGIES_DECODED_2026_05_17.md` / `MINT_AND_SELL_*` for `0xf7f0b0b1`. "
                 "Ranked by replicability for live deploy (highest first).")
    lines.append("")
    lines.append("| Rank | Wallet | Class | $/day reputed | Maker% | Paired% | Leftover-on-winner% | Replicability | Action |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    lines.append("| 1 | `0x04b6d7e9` | MAKER PAIR ARB | $212k | 97.7% | 87.2% | 44.3% (n=228) | **HIGH** | MIMIC — clean reference for mint-and-sell V2 |")
    lines.append("| 2 | `0xf7f0b0b1` | mint-and-sell (on-chain) | $10-50k (older) | maker (on-chain mint) | ~100% | ~50% | **HIGH** | MIMIC — already decoded in `MINT_AND_SELL_*_2026_05_16.md` |")
    lines.append("| 3 | `0xb27bc932` | **MAKER PAIR ARB** (this report) | $254k reputed | **100.0%** | **93.8%** | **51.3% (n=754)** | **HIGH** | MIMIC — surprise! Not a scalper; pure pair-arb at massive scale. Same maker-bid template as #1. |")
    lines.append("| 4 | `0xeebde7a0` | HYBRID | $344k | 50.2% | 68.2% | 58.7% (n=3130) | MEDIUM | partial copy (pair-arb leg replicable, directional leg requires private signal) |")
    lines.append("| 5 | `0x89b5cdaa` | DIRECTIONAL | $10k | 100.0% | 19.2% | 59.1% (n=4389) | LOW | NO — needs slug-selector signal decode (F2 template). |")
    lines.append("| 6 | `0x7dfc8aa2` | **LOSER** (this report) | **-$7.9k cash** | 26.4% | 85.4% | 48.4% (n=382) | NONE | NO — mimics the maker pair-arb fingerprint (sum_asks≈$1.01, same counterparty mix as #3) but with 74% taker mix + 13% selectivity + strong contrarian momentum (16.7% match on 120s) it bleeds ~$8k/day cash. Likely a failed copycat of the kingpin template. |")
    lines.append("| 7 | `0xcfb103c3` | LOSER | $-39 | 10.2% | 97.0% | 42.5% (n=259) | NONE | NO — taker pair-arb that bleeds. |")
    lines.append("")
    lines.append("### Live-deploy shortlist (2-3 wallets to mimic)")
    lines.append("")
    lines.append("**1. `0x04b6d7e9`** — cleanest mint-and-sell reference. Already coded in `MINT_AND_SELL_*_2026_05_16.md` V2 spec. Per-fire view is breakeven, slug-level positive in BOTH_SIDES_PARTIALS regime.")
    lines.append("")
    lines.append("**2. `0xb27bc932`** — the biggest stunner: 100.0% maker, paired=93.8%, leftover-on-winner=51.3% (n=754, essentially noise). $254k/day reputed is NOT scalping — it's **pair-arb at industrial scale**. Same counterparty mix (0xe111180000d2663c0091e4f400237545b87b996b ≈91%) and same sum_asks≈$1.01 fingerprint as 0x04b6d7e9. Mimicking this likely just means scaling up the mint-and-sell V2 spec.")
    lines.append("")
    lines.append("**3. `0xf7f0b0b1`** — secondary mint-and-sell reference, on-chain minting variant. Use as A/B to validate that the V2 spec captures both no-mint and on-chain-mint flavors of the same template.")
    lines.append("")
    lines.append("**DO NOT mimic 0x7dfc8aa2** — USDC cash flow is **-$7,941/day** despite imitating the same fingerprint as 0xb27bc932 (same counterparty 0xe111180000d2663c0091e4f400237545b87b996b ≈89%, same sum_asks ≈$1.01 median). The crucial difference: 0xb27bc932 is **100% maker** so it earns the rebate every fill, while 0x7dfc8aa2 is **74% taker** so it pays 7%×p×(1-p) per fill. Combined with 13% selection rate (selective entries instead of broad accumulation) + contrarian momentum (29.7% match on 60s, 16.7% on 120s — significant fade) it suggests a failed-copycat or a directional taker with a misfiring signal. Whatever its intent, it loses money. Demonstrates the value of the leftover-on-winner + USDC-cash-flow combo: signal characteristics alone (high paired%, same counterparty) cannot distinguish profitable from unprofitable.")
    lines.append("")
    return "\n".join(lines)


def main():
    print("Loading canonical resolutions...", flush=True)
    resolutions = load_resolutions()
    print(f"  resolutions n={len(resolutions)}", flush=True)
    print("Loading token lookup...", flush=True)
    token_lookup = load_token_lookup()
    print(f"  tokens n={len(token_lookup)}", flush=True)

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

    print("\nRendering report...", flush=True)
    md = render_report(results)
    REPORT.write_text(md, encoding="utf-8")
    print(f"Wrote {REPORT}", flush=True)
    json_path = REPORT.with_suffix(".json")
    json_path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"Wrote {json_path}", flush=True)


if __name__ == "__main__":
    main()
