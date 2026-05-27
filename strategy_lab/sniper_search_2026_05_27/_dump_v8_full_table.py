"""Dump V8 per-sleeve metrics across all 6 markets."""
import pandas as pd
import os

base = 'strategy_lab/sniper_search_2026_05_27'

markets = [
    ('BTC 5m',  'btc_5m_v8/top_5_candidates_v8.csv'),
    ('ETH 5m',  'eth_5m_v8/_results/top_5_candidates_v8.csv'),
    ('SOL 5m',  'sol_5m_v8/top_5_candidates_v8.csv'),
    ('BTC 15m', 'btc_15m_v8/top_5_candidates_v8.csv'),
    ('ETH 15m', 'eth_15m_v8/top_5_candidates_v8.csv'),
    ('SOL 15m', 'sol_15m_v8/top_5_candidates_v8.csv'),
]

def fmt(x, kind='num', decimals=2):
    if pd.isna(x): return 'NA'
    try:
        v = float(x)
        if kind == 'pct':
            if v > 1.5: return f'{v:.1f}%'
            return f'{v*100:.1f}%'
        if kind == 'dollar': return f'${v:+.2f}'
        if kind == 'abs_dollar': return f'${abs(v):.0f}'
        if kind == 'p': return f'{v:.4f}'
        return f'{v:.{decimals}f}'
    except Exception: return str(x)

def get(r, *cols):
    for c in cols:
        if c in r.index and pd.notna(r.get(c)):
            return r.get(c)
    return float('nan')

print('=== V8 master dump ===\n')

for name, rel in markets:
    p = f'{base}/{rel}'
    if not os.path.exists(p):
        print(f'### {name}: MISSING\n'); continue
    df = pd.read_csv(p)
    print(f'### {name}  rows={len(df)}')
    print(f'    cols: {list(df.columns)}')
    print()

print('\n=== Per-sleeve dump ===\n')

rows_out = []
for name, rel in markets:
    p = f'{base}/{rel}'
    if not os.path.exists(p): continue
    df = pd.read_csv(p)
    print(f'\n### {name}')

    for i, r in df.iterrows():
        sid = str(r.get('sleeve_id', '?'))
        gates = str(get(r, 'gate_stack', 'gates'))
        anchor = get(r, 'anchor', 'offset', 'offset_dist')
        direction = get(r, 'direction', 'dir_constraint')
        if pd.isna(direction) or str(direction).lower() == 'nan': direction = 'BOTH'

        n_tr  = get(r, 'n_train')
        n_v   = get(r, 'n_val')
        n_lb  = get(r, 'n_lockbox', 'n_lb', 'n_l')
        n_full = get(r, 'n_full', 'n')

        wr_tr = get(r, 'wr_train')
        wr_v  = get(r, 'wr_val')
        wr_lb = get(r, 'wr_lockbox', 'wr_lb')
        wr_full = get(r, 'wr_full')

        dpt_tr  = get(r, 'dpt_25_train', 'dpt_train')
        dpt_v   = get(r, 'dpt_25_val', 'dpt_val')
        dpt_lb  = get(r, 'dpt_25_lockbox', 'dpt_25_lockbox_const', 'dpt_lockbox', 'dpt_lb', 'dpt_25_l')
        dpt_full = get(r, 'dpt_25_full', 'dpt_full')

        dd_lb = get(r, 'max_dd_25', 'max_dd_25_lockbox', 'dd_25_lockbox', 'dd_lockbox', 'dd_lb', 'max_dd_lockbox')
        ls_lb = get(r, 'loss_streak', 'loss_streak_lockbox', 'ls_lockbox', 'ls_lb', 'ls')

        sharpe = get(r, 'sharpe', 'sharpe_lockbox', 'sharpe_daily')
        bs_p = get(r, 'bootstrap_p_lockbox', 'boot_p', 'p', 'bs_p_lockbox', 'p_lockbox')

        proj_32d = get(r, 'proj_32d', 'proj_32_66d', 'sum_25_32d')
        proj_full = get(r, 'proj_full', 'proj_full_window')
        proj_honest = get(r, 'proj_honest', 'proj_min', 'projection_honest')

        # stability flag
        try:
            stab = '⚠VAL_NEG' if ((float(dpt_v) < 0 if pd.notna(dpt_v) else False) or
                                  (float(dpt_tr) < 0 if pd.notna(dpt_tr) else False)) else 'OK'
        except: stab = 'OK'

        try:
            nlb_v = int(n_lb)
            wrlb_v = float(wr_lb)
            if wrlb_v > 1.5: wrlb_v = wrlb_v / 100
            wins = int(round(nlb_v * wrlb_v))
            losses = nlb_v - wins
            wl = f'{wins}/{losses}'
        except Exception: wl = 'NA/NA'

        print(f'  [{i+1}] {sid}  [{stab}]')
        print(f'      gates : {gates[:160]}')
        print(f'      anchor: {anchor}  dir: {direction}')
        print(f'      n  tr/val/lock/full: {fmt(n_tr,"num",0)}/{fmt(n_v,"num",0)}/{fmt(n_lb,"num",0)}/{fmt(n_full,"num",0)}')
        print(f'      WR tr/val/lock/full: {fmt(wr_tr,"pct")}/{fmt(wr_v,"pct")}/{fmt(wr_lb,"pct")}/{fmt(wr_full,"pct")}    W/L_lock: {wl}')
        print(f'      $/tr tr/val/lock/full: {fmt(dpt_tr,"dollar")}/{fmt(dpt_v,"dollar")}/{fmt(dpt_lb,"dollar")}/{fmt(dpt_full,"dollar")}')
        print(f'      DD_lock={fmt(dd_lb,"abs_dollar")}  LS={fmt(ls_lb,"num",0)}  Sharpe={fmt(sharpe,"num",1)}  bs_p={fmt(bs_p,"p")}')
        print(f'      proj_32d=${fmt(proj_32d,"num",0)}  proj_full=${fmt(proj_full,"num",0)}  proj_honest=${fmt(proj_honest,"num",0)}')

        rows_out.append({
            'market': name, 'rank': i+1, 'sleeve_id': sid, 'gates': gates,
            'anchor': str(anchor), 'dir': direction, 'stability': stab,
            'n_tr': n_tr, 'n_v': n_v, 'n_lb': n_lb, 'n_full': n_full,
            'wr_tr': wr_tr, 'wr_v': wr_v, 'wr_lb': wr_lb, 'wr_full': wr_full,
            'dpt_tr': dpt_tr, 'dpt_v': dpt_v, 'dpt_lb': dpt_lb, 'dpt_full': dpt_full,
            'dd_lb': dd_lb, 'ls_lb': ls_lb, 'sharpe': sharpe, 'bs_p': bs_p,
            'proj_32d': proj_32d, 'proj_full': proj_full, 'proj_honest': proj_honest,
        })

out = pd.DataFrame(rows_out)
out.to_csv(f'{base}/_v8_full_table.csv', index=False)
print(f'\n\nSaved: {base}/_v8_full_table.csv ({len(out)} rows)')
