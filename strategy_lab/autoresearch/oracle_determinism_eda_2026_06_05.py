"""
Slug-selection scoping EDA: ORACLE-DETERMINISM near settle.

Polymarket up/down settles on Chainlink RTDS (strike=oracle@slot_start, settle=oracle@slot_end,
outcome=sign(settle-strike)). Question for slug SELECTION: how often, at T-X seconds before slot_end,
has the oracle ALREADY effectively decided the outcome (current oracle far from strike relative to the
volatility achievable in the remaining X seconds)? Those are the slugs where the settlement is ~deterministic
-> if the poly price hasn't converged, that's a structural (non-predictive) selection edge.

This measures the OPPORTUNITY: P(final outcome == sign(oracle_dist at T-X)) by |dist| bucket and X, plus the
fraction of slugs that are 'decided' early. (Poly-price divergence join is the next step; needs book/trades.)
"""
import sys, warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
sys.path.insert(0, r"data\v4\canonical")
from load import load_resolutions, load_chainlink_asof

ASSETS = ["BTC", "ETH", "SOL"]; TFS = ["5m", "15m"]
XS = [15, 30, 60, 120, 180]   # seconds before slot_end

def asof(ts, v, t):
    i = np.searchsorted(ts, t, "right") - 1
    return np.where(i >= 0, v[np.clip(i, 0, len(v) - 1)], np.nan)

cl = {a: load_chainlink_asof(a) for a in ASSETS}
res = load_resolutions(assets=ASSETS, timeframes=TFS)
res = res[res.outcome.isin(["Up", "Down"])].dropna(subset=["strike_price", "settlement_price"]).copy()
print(f"slugs: {len(res)}  {res.groupby('ticker').size().to_dict() if 'ticker' in res else ''}")

rows = []
for a in ASSETS:
    ts, v = cl[a]
    d = res[res.ticker == a] if "ticker" in res.columns else res[res.slug.str.startswith(a.lower())]
    if not len(d): continue
    strike = d.strike_price.values.astype(float)
    settle = d.settlement_price.values.astype(float)
    end_us = d.slot_end_us.values.astype("int64")
    out_up = (d.outcome.values == "Up")
    for X in XS:
        px = asof(ts, v, end_us - X * 1_000_000)
        dist_bp = (px - strike) / strike * 1e4          # signed oracle distance from strike, bps
        oracle_lead_up = dist_bp > 0
        valid = np.isfinite(dist_bp)
        for a_ in [a]:
            for lo, hi in [(0, 5), (5, 15), (15, 40), (40, 1e9)]:
                m = valid & (np.abs(dist_bp) >= lo) & (np.abs(dist_bp) < hi)
                if m.sum() < 20: continue
                acc = (oracle_lead_up[m] == out_up[m]).mean()
                rows.append(dict(asset=a, X=X, dist_bin=f"[{lo},{hi if hi<1e9 else 'inf'})",
                                 n=int(m.sum()), frac=round(m.sum()/valid.sum(), 3),
                                 acc=round(float(acc), 4)))
R = pd.DataFrame(rows)
pd.set_option("display.width", 200, "display.max_rows", 200)
print("\n=== P(final outcome == oracle-lead at T-X) by |oracle dist from strike| ===")
for X in XS:
    print(f"\n-- T-{X}s before settle --")
    print(R[R.X == X][["asset", "dist_bin", "n", "frac", "acc"]].to_string(index=False))
print("\nREAD: acc -> 1.0 = outcome already decided by oracle at T-X (deterministic-settlement slugs).")
print("      'frac' = share of slugs in that |dist| bucket = the OPPORTUNITY size. Next: join poly price of")
print("      the oracle-implied winner at T-X; trade only where poly hasn't converged (price < acc).")
