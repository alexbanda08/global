"""PnL audit — are extreme wins real or book-staleness artifacts?

User's concern: $1,200 max single-trade PnL on a $25 stake doesn't match the
binary settlement math. If we paid avg ~$0.51/share, $25 stake = ~49 shares,
max win = $49 × 1 = $49 → mean profit ≈ $24. A $1,200 win means we filled
~1,250 shares at ~$0.02 — which would only happen if the book had a deep
bid at $0.02 that we walked into.

That's plausible IF Polymarket's book was genuinely showing $0.02 asks at
bucket 12 (2 min into market) for the YES side, AND the trade actually
filled at that price. It's UNREALISTIC if those quotes were stale snapshots
that would have moved before a real order reached the venue.

This script:
  1. Re-runs BTC_only HOLD with PER-TRADE pnl/vwap/shares output.
  2. Distribution audit:
     - top 10 PnL outliers
     - bottom 10 (losses)
     - vwap_e histogram
     - shares_e histogram
     - vwap_e × hit-rate matrix
  3. WINSORIZED re-run: cap shares_e × (1 - vwap_e) at $50 (so max single-
     trade win is $50 - $25 = $25 — i.e. forces avg ask ≥ $0.50). This
     simulates "what if the book is actually quoted around mid?"
  4. Reports HOW MUCH of the headline number comes from outliers vs typical
     trades.

Outputs:
  strategy_lab/results/meta_classifier/pnl_audit_per_trade.csv
  strategy_lab/reports/PNL_AUDIT.md
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "strategy_lab"))

from book_walk import book_walk_fill  # noqa: E402

LEVELS = 10
NOTIONAL_USD = 25.0
FEE_RATE = 0.02
ENTRY_BUCKET = 12
SPREAD_FILTER = 0.02

REFRESH = ROOT / "data" / "v4" / "refresh_2026_05_02"
KLINES = REFRESH / "binance_spot_1min_full.csv"
BOOK_BTC = REFRESH / "btc_book_depth_v3_full.csv"
UNIV_BTC = REFRESH / "btc_markets_minimal.csv"

OUT_CSV = ROOT / "strategy_lab" / "results" / "meta_classifier" / "pnl_audit_per_trade.csv"
REPORT  = ROOT / "strategy_lab" / "reports" / "PNL_AUDIT.md"


def load_book(path: Path) -> dict:
    cols_ap = [f"ask_price_{i}" for i in range(LEVELS)]
    cols_as = [f"ask_size_{i}"  for i in range(LEVELS)]
    cols_bp = [f"bid_price_{i}" for i in range(LEVELS)]
    cols_bs = [f"bid_size_{i}"  for i in range(LEVELS)]
    keep = ["slug", "bucket_10s", "outcome"] + cols_ap + cols_as + cols_bp + cols_bs
    df = pd.read_csv(path, usecols=keep)
    asks_p = df[cols_ap].to_numpy(dtype=float); asks_s = df[cols_as].to_numpy(dtype=float)
    bids_p = df[cols_bp].to_numpy(dtype=float); bids_s = df[cols_bs].to_numpy(dtype=float)
    out: dict = {}
    for i in range(len(df)):
        slug = df.slug.iat[i]
        if slug not in out: out[slug] = {}
        out[slug][(int(df.bucket_10s.iat[i]), df.outcome.iat[i])] = (asks_p[i], asks_s[i], bids_p[i], bids_s[i])
    return out


def load_btc_1m() -> pd.DataFrame:
    df = pd.read_csv(KLINES)
    df = df[df.symbol_id == "BINANCE_SPOT_BTC_USDT"].copy()
    df["ts_s"] = (df.time_period_start_us // 1_000_000).astype("int64")
    return df.sort_values("ts_s").reset_index(drop=True)[["ts_s", "price_close"]]


def asof(k1m: pd.DataFrame, ts: int) -> float:
    idx = k1m.ts_s.searchsorted(ts, side="right") - 1
    return float("nan") if idx < 0 else float(k1m.price_close.iloc[idx])


def main():
    print("[1] load…")
    k1m = load_btc_1m()
    book = load_book(BOOK_BTC)
    uni = pd.read_csv(UNIV_BTC).dropna(subset=["window_start_unix", "outcome_up"])
    uni["outcome_up"] = uni["outcome_up"].astype(int)
    uni["asset_ret_2m"] = uni["window_start_unix"].astype("int64").apply(
        lambda w: np.log(asof(k1m, int(w) + 120) / asof(k1m, int(w))))

    active = uni[uni["asset_ret_2m"].notna() & (uni.timeframe == "5m")].copy()
    thr = active["asset_ret_2m"].abs().quantile(0.90)
    fired = active[active["asset_ret_2m"].abs() >= thr].copy()
    fired["signal"] = (fired["asset_ret_2m"] > 0).astype(int)
    print(f"    BTC_only_5m fires: {len(fired)}")

    rows = []
    for _, r in fired.iterrows():
        sig = int(r.signal)
        held = "Up" if sig == 1 else "Down"
        if r.slug not in book:
            continue
        sb = book[r.slug]
        if (ENTRY_BUCKET, held) not in sb:
            continue
        ask_p, ask_s, bid_p, bid_s = sb[(ENTRY_BUCKET, held)]
        spread = (ask_p[0] - bid_p[0]) if (np.isfinite(ask_p[0]) and np.isfinite(bid_p[0])) else float("nan")
        if np.isfinite(spread) and spread > SPREAD_FILTER:
            continue
        vwap_e, shares_e, usd_e, lvls_e, under_e = book_walk_fill(ask_p, ask_s, NOTIONAL_USD)
        if shares_e <= 0:
            continue
        if under_e and usd_e < NOTIONAL_USD * 0.5:
            continue
        won = (sig == int(r.outcome_up))
        if won:
            profit = shares_e * 1.0 - usd_e
            fee = profit * FEE_RATE if profit > 0 else 0
            pnl = profit - fee
        else:
            pnl = -usd_e
        # WINSORIZED: cap entry shares such that max win <= $25 (i.e. force vwap >= $0.50)
        shares_capped = min(shares_e, NOTIONAL_USD / 0.50)  # max 50 shares per $25 stake
        if won:
            profit_w = shares_capped * 1.0 - usd_e
            fee_w = profit_w * FEE_RATE if profit_w > 0 else 0
            pnl_winsor = profit_w - fee_w
        else:
            pnl_winsor = -usd_e
        rows.append(dict(
            slug=r.slug, signal=sig, won=won,
            ask_0=ask_p[0] if np.isfinite(ask_p[0]) else None,
            bid_0=bid_p[0] if np.isfinite(bid_p[0]) else None,
            spread=spread,
            vwap_e=vwap_e, shares_e=shares_e, usd_e=usd_e,
            lvls_e=lvls_e, under_e=under_e,
            pnl=pnl, pnl_winsor=pnl_winsor,
        ))

    df = pd.DataFrame(rows)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_CSV, index=False)
    print(f"    {len(df)} trades persisted")

    # Stats
    n = len(df)
    pnls = df.pnl.values
    pnls_w = df.pnl_winsor.values
    median_pnl = float(np.median(pnls))
    median_pnl_w = float(np.median(pnls_w))
    mean_pnl = float(pnls.mean())
    mean_pnl_w = float(pnls_w.mean())
    total_pnl = float(pnls.sum())
    total_pnl_w = float(pnls_w.sum())

    # Outliers
    top10 = df.nlargest(10, "pnl")
    # Trades with vwap < 0.20 (deeply mispriced)
    cheap = df[df.vwap_e < 0.20]
    # Trades where shares_e > 100 (only possible if avg fill < $0.25)
    huge = df[df.shares_e > 100]
    # Tail contribution
    sorted_pnl = np.sort(pnls)[::-1]
    top10_total = float(sorted_pnl[:10].sum())
    top1_total = float(sorted_pnl[:1].sum())
    bottom_30_total = float(sorted_pnl[-30:].sum())  # 30 losses worth ~-$25

    L = [
        "# PnL Audit — are the BTC_only HOLD numbers real?\n",
        "_Generated: 2026-05-05_\n",
        "## User's concern\n",
        "BTC_only_5m HOLD reported total $+3,054, mean $+11.15, **max single-trade $+1,200.50**.\n",
        "Theoretically, $25 stake at avg ask $0.51 → 49 shares → max win = $49 - $25 - 2%fee ≈ $23.50.\n",
        "A $1,200 win implies ~1,250 shares filled, which means avg ask ~$0.02. Is the book actually "
        "quoting that, or is this a lookahead artifact?\n",
        "## Per-trade audit\n",
        f"- Total trades: {n}",
        f"- Wins / losses: {df.won.sum()} / {(~df.won).sum()}",
        f"- Hit rate: {df.won.mean()*100:.1f}%",
        "",
        "### PnL distribution\n",
        f"| Stat | Raw | Winsorized (cap shares ≤ 50 = max $25 win) |",
        f"|---|---:|---:|",
        f"| Total | ${total_pnl:+.2f} | ${total_pnl_w:+.2f} |",
        f"| Mean  | ${mean_pnl:+.4f} | ${mean_pnl_w:+.4f} |",
        f"| Median | ${median_pnl:+.4f} | ${median_pnl_w:+.4f} |",
        f"| Std   | ${pnls.std():.2f} | ${pnls_w.std():.2f} |",
        f"| Min   | ${pnls.min():+.2f} | ${pnls_w.min():+.2f} |",
        f"| Max   | ${pnls.max():+.2f} | ${pnls_w.max():+.2f} |",
        "",
        "### Outlier contribution\n",
        f"- Top 1 trade: **${top1_total:+.2f}** ({top1_total/total_pnl*100:.1f}% of total PnL)",
        f"- Top 10 trades: **${top10_total:+.2f}** ({top10_total/total_pnl*100:.1f}% of total PnL)",
        f"- All {n - df.won.sum()} losses: ${bottom_30_total:+.2f}",
        "",
        "**If a single trade contributes >20% of total PnL, the strategy depends on extreme outliers.**",
        "",
        "### Top 10 winners\n",
        "| slug | sig | won | vwap_e | shares_e | usd_e | lvls | underfilled | pnl |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for _, t in top10.iterrows():
        L.append(
            f"| {t.slug} | {'UP' if t.signal==1 else 'DN'} | {'✓' if t.won else '✗'} | "
            f"${t.vwap_e:.4f} | {t.shares_e:.1f} | ${t.usd_e:.2f} | {int(t.lvls_e)} | "
            f"{t.under_e} | ${t.pnl:+.2f} |"
        )

    L += [
        "",
        f"### Trades with `vwap_e < 0.20` (deeply mispriced YES/NO buy)\n",
        f"- count: **{len(cheap)} of {n}** ({len(cheap)/n*100:.1f}%)",
        f"- sum of these trades' PnL: **${cheap.pnl.sum():+.2f}** ({cheap.pnl.sum()/total_pnl*100:.1f}% of total)",
        f"- if ALL these trades won: max possible PnL contribution = ${(cheap.shares_e - cheap.usd_e).sum():+.2f}",
        "",
        f"### Trades with `shares_e > 100` (avg fill price < $0.25)\n",
        f"- count: **{len(huge)} of {n}** ({len(huge)/n*100:.1f}%)",
        f"- sum: **${huge.pnl.sum():+.2f}** ({huge.pnl.sum()/total_pnl*100:.1f}% of total)",
        "",
        "## Vwap distribution (entry book quality)\n",
        f"| Bucket | count | %  |",
        f"|---|---:|---:|",
    ]
    bins = [(0, 0.10), (0.10, 0.20), (0.20, 0.30), (0.30, 0.40), (0.40, 0.50),
            (0.50, 0.60), (0.60, 0.70), (0.70, 0.80), (0.80, 0.90), (0.90, 1.0)]
    for lo, hi in bins:
        c = ((df.vwap_e >= lo) & (df.vwap_e < hi)).sum()
        L.append(f"| ${lo:.2f}–${hi:.2f} | {c} | {c/n*100:.1f}% |")

    L += [
        "",
        "## Verdict\n",
    ]
    if len(cheap) / n > 0.05 and cheap.pnl.sum() / total_pnl > 0.30:
        L.append(
            f"⚠️ **{len(cheap)} trades ({len(cheap)/n*100:.1f}%) entered at vwap < $0.20**, "
            f"contributing ${cheap.pnl.sum():.0f} ({cheap.pnl.sum()/total_pnl*100:.0f}%) of total PnL. "
            "These are the suspect entries. In live trading, deep-out-of-money asks rarely sit in the book "
            "long enough to fill — they're either stale snapshots or get arbitraged in milliseconds. "
            "**The honest projection is the WINSORIZED total: "
            f"${total_pnl_w:+.2f} (mean ${mean_pnl_w:+.4f}/trade)** — "
            f"a {(1 - total_pnl_w/total_pnl)*100:.0f}% haircut from raw."
        )
    else:
        L.append(
            f"✅ Outlier impact is bounded: top-10 trades contribute "
            f"{top10_total/total_pnl*100:.0f}% of total PnL. The strategy edge is broad-based, not "
            "carried by a few extreme entries."
        )
    L += [
        "",
        "## What this means for shadow projections\n",
        "- **Raw backtest** assumed the orderbook quotes are real, fillable, and stable.",
        "- **Live trading** would NOT capture deep-mispricing wins because (a) those quotes are usually "
        "stale snapshots, (b) when real, they're consumed by arbitrage bots in <1s, (c) Polymarket "
        "matching engine may slip the fill.",
        f"- **Realistic projection** = winsorized total ${total_pnl_w:+.2f} on {n} trades = "
        f"${mean_pnl_w:+.4f}/trade. Apply this haircut to all earlier headline numbers.",
        "",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(L), encoding="utf-8")
    print(f"[report] wrote {REPORT}")
    print(f"[csv] wrote {OUT_CSV}")
    print(f"\nRAW       : total ${total_pnl:+.2f}, mean ${mean_pnl:+.4f}/trade, max ${pnls.max():+.2f}")
    print(f"WINSORIZED: total ${total_pnl_w:+.2f}, mean ${mean_pnl_w:+.4f}/trade, max ${pnls_w.max():+.2f}")
    print(f"Cheap entries (vwap<0.20): {len(cheap)} trades, ${cheap.pnl.sum():+.2f} PnL "
          f"({cheap.pnl.sum()/total_pnl*100:.1f}% of total)")


if __name__ == "__main__":
    main()
