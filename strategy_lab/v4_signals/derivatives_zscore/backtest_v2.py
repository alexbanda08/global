"""V2 backtest — parametric runner using simpler entry rules.

Tests several entry/exit configs head-to-head, all symbols, all in one shot.
Each config is long-only (short side has no edge per diagnose.py).

Configs tested:
  C1: score >= 70, no AND filters    (loosest spec-aligned)
  C2: score >= 60, no AND filters    (more trades)
  C3: z_lsr < -1.5  (single-component)
  C4: z_lsr < -1.5 AND brigalS < -1.0  (two-component AND)
  C5: score >= 60 AND z_lsr < -1.5  (composite)

Exit options per config:
  E_score: exit when score_bull_scaled < 35 OR score_bear_scaled > 60
  E_4h:    fixed 4-hour hold
  E_24h:   fixed 24-hour hold

Outputs a comparison table.
"""
from __future__ import annotations
from pathlib import Path
import argparse
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PANELS = ROOT / "data" / "v4" / "derivatives_zscore" / "panels"
SPOT = ROOT / "data" / "v4" / "derivatives_zscore" / "spot"
REPORTS = ROOT / "strategy_lab" / "reports" / "derivatives_zscore"
REPORTS.mkdir(parents=True, exist_ok=True)

FEE_BPS = 5.0


def load_h(symbol: str) -> pd.DataFrame:
    p = pd.read_parquet(PANELS / f"{symbol}_zscore.parquet")
    p_h = p.resample("1h").last()
    tag = symbol.replace("USDT", "")
    spot_p = SPOT / f"BINANCE-{tag}-1h.parquet"
    if spot_p.exists():
        spot = pd.read_parquet(spot_p).set_index("time")["close"].astype(float)
        p_h["price"] = spot.reindex(p_h.index, method="ffill")
    else:
        p_h["price"] = p_h["spot_price"]
    return p_h.dropna(subset=["price", "score_bull_scaled", "score_bear_scaled"])


# ────────────────────────────────────────────────────────────
#  Config builders
# ────────────────────────────────────────────────────────────

CONFIGS = {
    "C1_score70":         lambda r: r["score_bull_scaled"] >= 70,
    "C2_score60":         lambda r: r["score_bull_scaled"] >= 60,
    "C3_zlsr":            lambda r: r["z_lsr"] < -1.5,
    "C4_zlsr_brigalS":    lambda r: (r["z_lsr"] < -1.5) and (r["brigalS"] < -1.0),
    "C5_score60_zlsr":    lambda r: (r["score_bull_scaled"] >= 60) and (r["z_lsr"] < -1.5),
}

EXITS = {
    "E_score":  ("score-flip",   None),  # use score-based exit
    "E_4h":     ("fixed",        4),
    "E_24h":    ("fixed",        24),
}


def should_close_score(r) -> bool:
    return (r["score_bull_scaled"] < 35) or (r["score_bear_scaled"] > 60) \
        or (r["z_fund"] > 2.5) or (r["z_lsr"] > 2.5)


def run_config(df: pd.DataFrame, entry_fn, exit_kind: str, fixed_hold: int | None = None):
    """Long-only. Returns trade list + final equity multiplier."""
    pos = 0
    entry_px = None
    entry_t = None
    entry_idx = None
    cash = 1.0
    trades = []
    fee = FEE_BPS / 1e4

    rows = list(df.itertuples(index=True))
    n = len(rows)

    for i, r in enumerate(rows):
        ts, px = r.Index, r.price

        # exit logic
        if pos == 1:
            close = False
            if exit_kind == "fixed":
                if (i - entry_idx) >= fixed_hold:
                    close = True
            else:  # score
                # convert namedtuple back to dict
                row_dict = r._asdict()
                if should_close_score(row_dict):
                    close = True
            if close:
                ret = (px / entry_px) - 1 - 2 * fee
                cash *= (1 + ret)
                trades.append(dict(entry_t=entry_t, exit_t=ts, side="long",
                                   entry_px=entry_px, exit_px=px, ret=ret,
                                   hours=(ts - entry_t).total_seconds() / 3600))
                pos = 0
                entry_px = None

        # entry
        if pos == 0:
            if entry_fn(r._asdict()):
                pos = 1
                entry_px = px
                entry_t = ts
                entry_idx = i

    # close any open position at end at last price
    if pos == 1:
        ts, px = rows[-1].Index, rows[-1].price
        ret = (px / entry_px) - 1 - 2 * fee
        cash *= (1 + ret)
        trades.append(dict(entry_t=entry_t, exit_t=ts, side="long",
                           entry_px=entry_px, exit_px=px, ret=ret,
                           hours=(ts - entry_t).total_seconds() / 3600))
    return trades, cash


def stats(trades, cash, df):
    bh = df["price"].iloc[-1] / df["price"].iloc[0]
    if not trades:
        return dict(n=0, wr=np.nan, exp=0.0, pf=0.0, eq=cash, bh=bh, hold_h=np.nan)
    rets = np.array([t["ret"] for t in trades])
    wins = rets > 0
    pf = rets[wins].sum() / -rets[~wins].sum() if (~wins).any() else float("inf")
    return dict(
        n=len(trades),
        wr=float(wins.mean()),
        exp=float(rets.mean()),
        pf=float(pf),
        eq=float(cash),
        bh=float(bh),
        hold_h=float(np.median([t["hours"] for t in trades])),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    args = ap.parse_args()

    rows = []
    for sym in args.symbols:
        df = load_h(sym)
        bh = df["price"].iloc[-1] / df["price"].iloc[0]
        print(f"\n══════ {sym}  bars={len(df):,}  buy-hold={bh:.2f}× ══════")
        print(f"{'config':<20} {'exit':<10} {'n':>4} {'wr':>6} {'exp%':>7} {'pf':>5} {'hold(h)':>8} {'eq(×)':>7} {'vs B&H':>7}")
        for cname, cfn in CONFIGS.items():
            for ekey, (ekind, ehold) in EXITS.items():
                trades, cash = run_config(df, cfn, ekind, ehold)
                s = stats(trades, cash, df)
                rows.append({
                    "symbol": sym, "config": cname, "exit": ekey,
                    **s,
                })
                print(f"{cname:<20} {ekey:<10} {s['n']:>4} "
                      f"{(s['wr']*100 if not np.isnan(s['wr']) else 0):>6.1f} "
                      f"{s['exp']*100:>+7.4f} "
                      f"{s['pf']:>5.2f} "
                      f"{(s['hold_h'] if not np.isnan(s['hold_h']) else 0):>8.1f} "
                      f"{s['eq']:>7.3f} "
                      f"{(s['eq']/s['bh']):>7.3f}")

    out = pd.DataFrame(rows)
    out.to_parquet(REPORTS / "v2_summary.parquet")
    print(f"\nWrote {len(out)} rows to {REPORTS/'v2_summary.parquet'}")


if __name__ == "__main__":
    main()
