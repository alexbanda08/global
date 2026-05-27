"""Dump complete V6 per-sleeve metrics with proper train/val/lockbox per-split breakdown."""
import pandas as pd
import os

base = 'strategy_lab/sniper_search_2026_05_27'

# Per-market source files. BTC 5m needs to be enriched from all_candidates_v6.csv.
markets = [
    ('BTC 5m', 'btc_5m_v6/top_5_candidates_v6.csv', 'btc_5m_v6/all_candidates_v6.csv'),
    ('ETH 5m', 'eth_5m_v6/_results/top_5_candidates_v6.csv', None),
    ('SOL 5m', 'sol_5m_v6/top_5_candidates_v6.csv', None),
    ('BTC 15m', 'btc_15m_v6/top_5_candidates_v6.csv', None),
    ('ETH 15m', 'eth_15m_v6/top_5_candidates_v6.csv', None),
    ('SOL 15m', 'sol_15m_v6/top_5_candidates_v6.csv', None),
]

def fmt(x, kind='num', decimals=2):
    if pd.isna(x): return 'NA'
    try:
        v = float(x)
        if kind == 'pct':
            if v > 1.5: return f'{v:.1f}%'
            return f'{v*100:.1f}%'
        if kind == 'dollar':
            return f'${v:+.2f}'
        if kind == 'abs_dollar':
            return f'${abs(v):.0f}'
        if kind == 'p':
            return f'{v:.4f}'
        return f'{v:.{decimals}f}'
    except Exception:
        return str(x)

def get(r, *cols):
    for c in cols:
        if c in r.index and pd.notna(r.get(c)):
            return r.get(c)
    return float('nan')

rows_out = []

for name, top5_path, all_path in markets:
    p_top = f'{base}/{top5_path}'
    if not os.path.exists(p_top):
        print(f'### {name}: MISSING'); continue
    df = pd.read_csv(p_top)
    # If we have an all-candidates supplement, merge per sleeve_id
    if all_path:
        all_df = pd.read_csv(f'{base}/{all_path}')
        df = df.merge(
            all_df[['sleeve_id','n_train','n_val','wr_train','wr_val','dpt_25_train','dpt_25_val']],
            on='sleeve_id', how='left', suffixes=('', '_all')
        )

    for i, r in df.iterrows():
        sid    = str(r.get('sleeve_id', '?'))
        gates  = str(r.get('gate_stack', '?'))
        anchor = get(r, 'anchor', 'offset', 'offset_dist')
        direction = get(r, 'direction', 'dir_constraint')
        if pd.isna(direction) or str(direction).lower() == 'nan': direction = 'BOTH'

        n_tr = get(r, 'n_train')
        n_v  = get(r, 'n_val')
        n_lb = get(r, 'n_lockbox')
        n_full = get(r, 'n_full')

        wr_tr = get(r, 'wr_train')
        wr_v  = get(r, 'wr_val')
        wr_lb = get(r, 'wr_lockbox')
        wr_full = get(r, 'wr_full')

        dpt_tr = get(r, 'dpt_25_train', 'dpt_train')
        dpt_v  = get(r, 'dpt_25_val',   'dpt_val')
        dpt_lb = get(r, 'dpt_25_lockbox', 'dpt_25_lockbox_const')
        dpt_full = get(r, 'dpt_25_full')

        dd_lb = get(r, 'max_dd_25', 'max_dd_25_lockbox', 'dd_25_lockbox')
        ls_lb = get(r, 'loss_streak', 'loss_streak_lockbox')

        sharpe = get(r, 'sharpe', 'sharpe_lockbox', 'sharpe_daily')
        bs_p = get(r, 'bootstrap_p_lockbox')

        sum28 = get(r, 'sum_25_28d_const', 'sum_25_lb_const', 'sum_25_const_lockbox', 'sum_25_lockbox_const')

        # Compute wins/losses lockbox
        try:
            nlb_v = int(n_lb)
            wrlb_v = float(wr_lb)
            if wrlb_v > 1.5: wrlb_v = wrlb_v / 100
            wins = int(round(nlb_v * wrlb_v))
            losses = nlb_v - wins
            wl = f'{wins}/{losses}'
        except Exception:
            wl = 'NA/NA'

        rows_out.append({
            'market': name,
            'rank': i+1,
            'sleeve_id': sid,
            'gates': gates,
            'anchor': anchor,
            'dir': direction,
            'n_tr': fmt(n_tr, 'num', 0),
            'n_v':  fmt(n_v, 'num', 0),
            'n_lb': fmt(n_lb, 'num', 0),
            'n_full': fmt(n_full, 'num', 0) if not pd.isna(n_full) else fmt(n_lb, 'num', 0),
            'WR_tr': fmt(wr_tr, 'pct'),
            'WR_v':  fmt(wr_v, 'pct'),
            'WR_lb': fmt(wr_lb, 'pct'),
            'WR_full': fmt(wr_full, 'pct') if not pd.isna(wr_full) else fmt(wr_lb, 'pct'),
            'WL_lb': wl,
            'dpt_tr':  fmt(dpt_tr, 'dollar'),
            'dpt_v':   fmt(dpt_v, 'dollar'),
            'dpt_lb':  fmt(dpt_lb, 'dollar'),
            'dpt_full': fmt(dpt_full, 'dollar') if not pd.isna(dpt_full) else fmt(dpt_lb, 'dollar'),
            'DD_lb':   fmt(dd_lb, 'abs_dollar'),
            'LS_lb':   fmt(ls_lb, 'num', 0),
            'Sharpe':  fmt(sharpe, 'num', 1),
            'bs_p':    fmt(bs_p, 'p'),
            'sum_28d': fmt(sum28, 'num', 0) if not pd.isna(sum28) else 'NA',
        })

# Print per-market grouped
import io
out = pd.DataFrame(rows_out)
out.to_csv(f'{base}/_v6_full_table.csv', index=False)
print(f'Saved unified table: {base}/_v6_full_table.csv  ({len(out)} rows)')
print()

for market in out.market.unique():
    sub = out[out.market == market]
    print(f'### {market}')
    for _, r in sub.iterrows():
        print(f'  [{r["rank"]}] {r["sleeve_id"]}')
        print(f'      gates : {r["gates"]}')
        print(f'      anchor: {r["anchor"]}  dir: {r["dir"]}')
        print(f'      n   tr/val/lock/full: {r["n_tr"]}/{r["n_v"]}/{r["n_lb"]}/{r["n_full"]}')
        print(f'      WR  tr/val/lock/full: {r["WR_tr"]}/{r["WR_v"]}/{r["WR_lb"]}/{r["WR_full"]}    W/L_lock: {r["WL_lb"]}')
        print(f'      $/tr tr/val/lock/full: {r["dpt_tr"]}/{r["dpt_v"]}/{r["dpt_lb"]}/{r["dpt_full"]}')
        print(f'      DD_lock={r["DD_lb"]}  LS_lock={r["LS_lb"]}  Sharpe={r["Sharpe"]}  bs_p={r["bs_p"]}  28d_const_sum=${r["sum_28d"]}')
    print()
