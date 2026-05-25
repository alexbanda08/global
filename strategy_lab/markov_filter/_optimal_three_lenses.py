"""Pick optimal notional per sleeve under three different lenses."""
import pandas as pd

df = pd.read_csv('strategy_lab/markov_filter/_results/capacity_sweep_per_sleeve.csv')


def pick_max_sum(g):
    g = g[g['mean_fill_rate'] >= 0.95]
    if g.empty: return None
    return g.loc[g['sum_pnl_usd'].idxmax()]


def pick_practical(g):
    g = g[g['share_underfilled'] < 10.0]
    if g.empty: return None
    peak = g['per_trade_pnl'].max()
    g = g[g['per_trade_pnl'] >= 0.80 * peak]
    return g.sort_values('notional_target', ascending=False).iloc[0]


def pick_microstructure(g, frac=0.25):
    cap = g['median_depth_usd'].iloc[0] * frac
    eligible = g[g['notional_target'] <= cap]
    if eligible.empty:
        eligible = g[g['notional_target'] == g['notional_target'].min()]
    return eligible.sort_values('notional_target', ascending=False).iloc[0]


rows = []
for sleeve, g in df.groupby('sleeve'):
    ms = pick_max_sum(g)
    pr = pick_practical(g)
    mc = pick_microstructure(g)
    rows.append({
        'sleeve': sleeve,
        'wr_pct': g['wr_pct'].iloc[0],
        'L25_depth_med': g['median_depth_usd'].iloc[0],
        'maxsum_notional':  int(ms['notional_target']) if ms is not None else None,
        'maxsum_pnl':       float(ms['sum_pnl_usd'])     if ms is not None else None,
        'maxsum_pertr':     float(ms['per_trade_pnl'])   if ms is not None else None,
        'maxsum_slip_bp':   float(ms['mean_slippage_bp']) if ms is not None else None,
        'maxsum_under_pct': float(ms['share_underfilled']) if ms is not None else None,
        'prac_notional':    int(pr['notional_target']) if pr is not None else None,
        'prac_pnl':         float(pr['sum_pnl_usd'])     if pr is not None else None,
        'prac_pertr':       float(pr['per_trade_pnl'])   if pr is not None else None,
        'prac_slip_bp':     float(pr['mean_slippage_bp']) if pr is not None else None,
        'micro_notional':   int(mc['notional_target']),
        'micro_pnl':        float(mc['sum_pnl_usd']),
        'micro_pertr':      float(mc['per_trade_pnl']),
        'micro_slip_bp':    float(mc['mean_slippage_bp']),
    })

opt = pd.DataFrame(rows).sort_values('maxsum_pnl', ascending=False)
opt.to_csv('strategy_lab/markov_filter/_results/capacity_optimal_three_lenses.csv', index=False)

pd.set_option('display.max_columns', None)
pd.set_option('display.width', 250)
print(opt.to_string(index=False))
print()
print(f"Aggregate max-sum:   {opt['maxsum_pnl'].sum():,.0f} USD over 11 sleeves")
print(f"Aggregate practical: {opt['prac_pnl'].sum():,.0f} USD over 11 sleeves")
print(f"Aggregate micro-25:  {opt['micro_pnl'].sum():,.0f} USD over 11 sleeves")
print(f"(baseline 25 USD:    6,962 USD)")
