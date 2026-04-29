"""S2 Covered-Call Backtest.

Per market: simulate (long BTC perp at L leverage) + (short YES on Polymarket = buy NO).

PnL accounting:
  perp_pnl = L * (settle/strike - 1) * notional_perp
  no_pnl   = shares * ( (1 if settle <= strike else 0) - entry_no_ask )
           where shares = notional_no / entry_no_ask
  total    = perp_pnl + no_pnl

Parameter sweeps:
  leverage     : [1, 2, 5, 10, 30, 60]
  size_mode    : matched | delta1
  signal_filter: all | q10 (top 10% |ret_5m|)

Output: results/polymarket/covered_call_backtest.csv plus reports markdown.

NOTE: this is paper-only. Liquidation modeling at 60x is approximate (assumes
position would be force-closed at the unfavorable mid-window move and we lose
the full margin if intra-window range exceeds 1.5% / leverage). We use simple
"final-settle" PnL with a `liquidated` flag for cells where leverage x peak
adverse move exceeds 100%.
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd
from strategy_lab.v2_signals.common import load_features, ASSETS

HERE = Path(__file__).resolve().parent.parent
RESULTS = HERE / "results" / "polymarket"
REPORTS = HERE / "reports"

LEVERAGES = [1, 2, 5, 10, 30, 60]
NOTIONAL = 25.0  # $25 per leg (matches sniper q10 sizing)
LIQ_BUFFER = 1.0  # liquidate when leverage * |move| >= 100% of margin


def load_all() -> pd.DataFrame:
    parts = []
    for a in ASSETS:
        df = load_features(a)
        if "asset" not in df.columns:
            df["asset"] = a
        parts.append(df)
    out = pd.concat(parts, ignore_index=True)
    # Drop rows missing essential fields
    cols = ["strike_price", "settlement_price", "entry_no_ask", "outcome_up", "timeframe", "asset"]
    return out.dropna(subset=cols).copy()


def simulate(df: pd.DataFrame, leverage: int, size_mode: str = "matched") -> pd.DataFrame:
    """Return per-market PnL DataFrame.

    size_mode:
      "matched" - perp notional = no notional = NOTIONAL
      "delta1"  - perp notional = NOTIONAL * (1 - entry_no_ask) so that a small
                  spot move offsets the no-leg's max-loss component proportionally.
    """
    out = df[["asset", "timeframe", "slug", "ret_5m", "strike_price",
              "settlement_price", "entry_no_ask", "outcome_up"]].copy()
    out["leverage"] = leverage
    out["size_mode"] = size_mode

    spot_pct = (out["settlement_price"] / out["strike_price"]) - 1.0
    out["spot_pct"] = spot_pct

    # Perp leg
    if size_mode == "matched":
        notional_perp = NOTIONAL
    elif size_mode == "delta1":
        # Scale perp notional by (1 - no_ask) so worst-case NO loss ($no_ask*shares)
        # is offset by perp's gain on a 1*(1-no_ask)/leverage spot move.
        notional_perp = NOTIONAL * (1.0 - out["entry_no_ask"])
    else:
        raise ValueError(size_mode)

    perp_raw_pnl = leverage * spot_pct * notional_perp
    # Liquidation check: if leverage * |spot_pct| >= LIQ_BUFFER, the perp is wiped.
    # Approximation: we treat settle as the closing tick; intra-window worst case
    # is unobserved, but for short tenors (5m/15m) settle is a reasonable proxy.
    liquidated = (leverage * spot_pct.abs()) >= LIQ_BUFFER
    out["liquidated"] = liquidated
    perp_pnl = np.where(liquidated, -notional_perp, perp_raw_pnl)
    out["perp_pnl"] = perp_pnl

    # NO leg: buy NO at entry_no_ask, size = NOTIONAL / entry_no_ask shares.
    # If outcome_up == 0 (NO wins), each share pays $1.
    # PnL per share = (1 - outcome_up) - entry_no_ask
    shares = NOTIONAL / out["entry_no_ask"]
    no_pnl_per_share = (1.0 - out["outcome_up"]) - out["entry_no_ask"]
    out["no_pnl"] = shares * no_pnl_per_share

    # Total
    out["total_pnl"] = out["perp_pnl"] + out["no_pnl"]
    out["entry_cost_total"] = NOTIONAL + (NOTIONAL if size_mode == "matched"
                                          else NOTIONAL * (1.0 - out["entry_no_ask"]))
    return out


def summarize(sim: pd.DataFrame, signal_filter: str = "all") -> dict:
    df = sim.copy()
    if signal_filter == "q10":
        # Top 10% by |ret_5m| globally (could also stratify by asset+tf)
        thr = df["ret_5m"].abs().quantile(0.90)
        df = df[df["ret_5m"].abs() >= thr]
    n = len(df)
    if n == 0:
        return {}
    pnl = df["total_pnl"]
    won = (pnl > 0).mean()
    avg = pnl.mean()
    total = pnl.sum()
    sharpe = pnl.mean() / pnl.std() * np.sqrt(252) if pnl.std() > 0 else 0
    cum = pnl.cumsum()
    dd = (cum - cum.cummax()).min()
    liq_rate = df["liquidated"].mean() if "liquidated" in df.columns else 0
    cost = df["entry_cost_total"].sum()
    roi = total / cost * 100 if cost > 0 else 0
    return {
        "n": n,
        "hit_pct": round(won * 100, 1),
        "avg_pnl": round(avg, 2),
        "total_pnl": round(total, 2),
        "roi_pct": round(roi, 2),
        "sharpe": round(sharpe, 2),
        "max_dd": round(dd, 2),
        "liq_rate_pct": round(liq_rate * 100, 1),
    }


def main():
    feats = load_all()
    print(f"Loaded {len(feats)} markets across {feats.asset.nunique()} assets, {feats.timeframe.nunique()} tfs")

    rows = []
    for L in LEVERAGES:
        for size_mode in ("matched", "delta1"):
            sim = simulate(feats, L, size_mode)
            for sig_filter in ("all", "q10"):
                # Per (asset, tf) and ALL aggregations
                for asset in (*ASSETS, "ALL"):
                    for tf in ("5m", "15m", "ALL"):
                        sub = sim
                        if asset != "ALL":
                            sub = sub[sub["asset"] == asset]
                        if tf != "ALL":
                            sub = sub[sub["timeframe"] == tf]
                        s = summarize(sub, signal_filter=sig_filter)
                        if s:
                            rows.append({
                                "leverage": L,
                                "size_mode": size_mode,
                                "filter": sig_filter,
                                "asset": asset,
                                "timeframe": tf,
                                **s,
                            })

    df = pd.DataFrame(rows)
    RESULTS.mkdir(parents=True, exist_ok=True)
    out_csv = RESULTS / "covered_call_backtest.csv"
    df.to_csv(out_csv, index=False)
    print(f"Wrote {out_csv}")

    # Top cells
    print("\n=== Top 15 cells by ROI (filter=all, asset=ALL or specific, tf=ALL or specific) ===")
    top = df[df["asset"] != "ALL"].nlargest(15, "roi_pct")
    print(top.to_string(index=False))

    print("\n=== Top 15 cells by ROI (filter=q10) ===")
    topq = df[(df["filter"] == "q10")].nlargest(15, "roi_pct")
    print(topq.to_string(index=False))

    print("\n=== Best cells per leverage (filter=q10, asset=ALL) ===")
    bestL = df[(df["filter"] == "q10") & (df["asset"] == "ALL") & (df["timeframe"] == "ALL")]
    print(bestL[["leverage", "size_mode", "n", "hit_pct", "roi_pct", "sharpe", "max_dd", "liq_rate_pct"]].to_string(index=False))


if __name__ == "__main__":
    main()
