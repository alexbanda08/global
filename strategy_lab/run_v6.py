"""
V6 mean-reversion sweep: test RSI 20/65 on 5m / 15m / 1h for BTC + ETH + SOL.
Each ($10k) asset is simulated independently.  We report trade-level stats
in one compact table.
"""
from __future__ import annotations
import json, time
from pathlib import Path
import numpy as np
import pandas as pd
from strategy_lab import engine
from strategy_lab.strategies_v6 import v6_rsi_2065

OUT = Path(__file__).resolve().parent / "results"

SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
TFS  = ["5m", "15m", "1h"]
START, END = "2018-01-01", "2026-04-01"


def _consec(pnl: np.ndarray):
    mw = cw = ml = cl = 0
    for p in pnl:
        if p > 0: cw += 1; cl = 0
        elif p < 0: cl += 1; cw = 0
        else: cw = cl = 0
        mw = max(mw, cw); ml = max(ml, cl)
    return mw, ml


def run_one(sym: str, tf: str, **kw) -> dict:
    df = engine.load(sym, tf, START, END)
    sig = v6_rsi_2065(df, **kw)
    res = engine.run_backtest(
        df,
        entries=sig["entries"], exits=sig["exits"],
        short_entries=sig["short_entries"], short_exits=sig["short_exits"],
        sl_stop=sig["sl_stop"], tp_stop=sig["tp_stop"],
        init_cash=10_000.0, label=f"{sym}|{tf}",
    )
    pf = res.pf
    m = res.metrics
    tr = pf.trades.records_readable.rename(columns=lambda c: c.strip())
    if len(tr) == 0:
        return {"symbol": sym, "tf": tf, **m, "n_wins":0, "n_losses":0,
                "profit_factor": 0, "avg_win_pct":0, "avg_loss_pct":0,
                "max_cw":0, "max_cl":0}
    pnl_usd = tr["PnL"].astype(float).values
    pnl_pct = tr["Return"].astype(float).values
    w_mask, l_mask = pnl_usd > 0, pnl_usd < 0
    gp = float(pnl_usd[w_mask].sum()) if w_mask.any() else 0
    gl = float(pnl_usd[l_mask].sum()) if l_mask.any() else 0
    pf_ratio = gp / abs(gl) if gl else 0
    avg_w = float(pnl_pct[w_mask].mean()) if w_mask.any() else 0
    avg_l = float(pnl_pct[l_mask].mean()) if l_mask.any() else 0
    mcw, mcl = _consec(pnl_usd)
    return {
        "symbol": sym, "tf": tf, "bars": len(df),
        **{k: round(v, 4) if isinstance(v, float) else v for k, v in m.items()
           if k not in ("label",)},
        "n_wins": int(w_mask.sum()), "n_losses": int(l_mask.sum()),
        "profit_factor": round(pf_ratio, 3),
        "avg_win_pct": round(avg_w, 4),
        "avg_loss_pct": round(avg_l, 4),
        "max_cw": int(mcw), "max_cl": int(mcl),
    }


def main():
    rows = []
    t0 = time.time()
    for tf in TFS:
        for sym in SYMS:
            print(f"  {sym} / {tf} ...", flush=True)
            try:
                r = run_one(sym, tf)
                rows.append(r)
                print(f"     trades={r['n_trades']}  CAGR={r['cagr']*100:+.2f}%  "
                      f"Sharpe={r['sharpe']:.2f}  DD={r['max_dd']*100:+.2f}%  "
                      f"WinRate={r['win_rate']*100:.1f}%  PF={r['profit_factor']}")
            except Exception as e:
                print(f"     ERR {e}")

    df = pd.DataFrame(rows)
    cols = ["symbol","tf","bars","n_trades","n_wins","n_losses","win_rate",
            "profit_factor","avg_win_pct","avg_loss_pct",
            "max_cw","max_cl","total_return","cagr","sharpe","sortino",
            "calmar","max_dd","final_equity","bh_return"]
    cols = [c for c in cols if c in df.columns]
    df = df[cols]
    out = OUT / "V6_meanrev_sweep.csv"
    df.to_csv(out, index=False)
    print(f"\nSaved {out}  ({time.time()-t0:.1f}s)")

    print("\n=== TOP BY CALMAR ===")
    print(df.sort_values("calmar", ascending=False).to_string(index=False))


if __name__ == "__main__":
    main()
