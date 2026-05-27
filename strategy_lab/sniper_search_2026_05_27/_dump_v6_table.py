"""Dump unified V6 metrics across all 6 markets."""
import pandas as pd
import os

base = 'strategy_lab/sniper_search_2026_05_27'
markets = [
    ('btc_5m_v6',  'BTC 5m',  'btc_5m_v6/top_5_candidates_v6.csv'),
    ('eth_5m_v6',  'ETH 5m',  'eth_5m_v6/_results/top_5_candidates_v6.csv'),
    ('sol_5m_v6',  'SOL 5m',  'sol_5m_v6/top_5_candidates_v6.csv'),
    ('btc_15m_v6', 'BTC 15m', 'btc_15m_v6/top_5_candidates_v6.csv'),
    ('eth_15m_v6', 'ETH 15m', 'eth_15m_v6/top_5_candidates_v6.csv'),
    ('sol_15m_v6', 'SOL 15m', 'sol_15m_v6/top_5_candidates_v6.csv'),
]

def num(x, fmt='{:.2f}'):
    if pd.isna(x): return 'NA'
    try: return fmt.format(float(x))
    except: return str(x)

def pct(x):
    if pd.isna(x): return 'NA'
    try:
        v = float(x)
        if v > 1.5: return f'{v:.1f}%'
        return f'{v*100:.1f}%'
    except: return 'NA'

def absn(x):
    if pd.isna(x): return 'NA'
    try: return f'{abs(float(x)):.0f}'
    except: return 'NA'

DOLLAR = '$'

for _, name, rel in markets:
    p = f'{base}/{rel}'
    if not os.path.exists(p):
        print(f'### {name}: MISSING'); continue
    df = pd.read_csv(p)
    print(f'\n### {name}  (file: {rel})')
    for i, r in df.iterrows():
        sid = str(r.get('sleeve_id', '?'))
        gs = str(r.get('gate_stack', '?'))
        # anchor: pick best available
        anchor = '?'
        for col in ('anchor', 'offset', 'offset_dist'):
            if col in df.columns and pd.notna(r.get(col)):
                anchor = r.get(col); break
        # counts
        n_tr  = r.get('n_train',  'NA')
        n_v   = r.get('n_val',    'NA')
        n_lb  = r.get('n_lockbox','NA')
        n_full = r.get('n_full', n_lb)
        # WR
        wr_tr = r.get('wr_train',  'NA')
        wr_v  = r.get('wr_val',    'NA')
        wr_lb = r.get('wr_lockbox','NA')
        # dpt
        dpt_lb = 'NA'
        for col in ('dpt_25_lockbox', 'dpt_25_lockbox_const'):
            if col in df.columns and pd.notna(r.get(col)):
                dpt_lb = r.get(col); break
        # DD + streak
        dd = 'NA'
        for col in ('max_dd_25', 'max_dd_25_lockbox', 'dd_25_lockbox'):
            if col in df.columns and pd.notna(r.get(col)):
                dd = r.get(col); break
        ls = 'NA'
        for col in ('loss_streak', 'loss_streak_lockbox'):
            if col in df.columns and pd.notna(r.get(col)):
                ls = r.get(col); break
        # Sharpe + bs_p
        sharpe = 'NA'
        for col in ('sharpe', 'sharpe_lockbox', 'sharpe_daily'):
            if col in df.columns and pd.notna(r.get(col)):
                sharpe = r.get(col); break
        bp = r.get('bootstrap_p_lockbox', 'NA')
        # 28d const
        sum28 = 'NA'
        for col in ('sum_25_28d_const', 'sum_25_lb_const'):
            if col in df.columns and pd.notna(r.get(col)):
                sum28 = r.get(col); break
        # direction
        direction = 'BOTH'
        for col in ('direction', 'dir_constraint'):
            if col in df.columns and pd.notna(r.get(col)):
                direction = r.get(col); break
        # wins/losses lockbox
        try:
            nlb_v  = int(float(n_lb))
            wrlb_v = float(wr_lb)
            if wrlb_v > 1.5: wrlb_v = wrlb_v / 100
            wins   = int(round(nlb_v * wrlb_v))
            losses = nlb_v - wins
            wl = f'{wins}/{losses}'
        except Exception:
            wl = 'NA/NA'
        print(f'  [{i+1}] {sid}')
        print(f'      gates : {gs}')
        print(f'      anchor: {anchor}  dir: {direction}')
        print(f'      n  tr/val/lock: {n_tr}/{n_v}/{n_lb}  (full={n_full})  W/L lock: {wl}')
        print(f'      WR tr/val/lock: {pct(wr_tr)}/{pct(wr_v)}/{pct(wr_lb)}')
        print(f'      $/tr_lock @ $25: {DOLLAR}{num(dpt_lb)}    DD_lock: {DOLLAR}{absn(dd)}    loss_streak: {ls}')
        print(f'      Sharpe: {num(sharpe)}    bs_p_lock: {num(bp, "{:.4f}")}')
        print(f'      28d const PnL @ $25: {DOLLAR}{num(sum28, "{:.0f}")}')
