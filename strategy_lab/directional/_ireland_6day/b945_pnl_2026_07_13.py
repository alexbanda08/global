import pandas as pd, numpy as np, json, ast

buys = pd.read_csv('b945_buys_parsed_2026_07_13.csv')
with open('b945_resolutions_2026_07_13.json') as f:
    res = json.load(f)

def parse_prices(v):
    if v is None: return None
    if isinstance(v, str):
        try:
            return ast.literal_eval(v)
        except Exception:
            return None
    return v

rows = []
for slug, g in buys.groupby('eventSlug' if 'eventSlug' in buys.columns else 'slug'):
    r = res.get(slug)
    if not r or not r.get('outcomePrices'):
        continue
    op = parse_prices(r['outcomePrices'])
    outcomes = parse_prices(r['outcomes'])
    if op is None or outcomes is None or len(op) != 2:
        continue
    price_map = {outcomes[i]: float(op[i]) for i in range(len(outcomes))}
    up_final = price_map.get('Up')
    dn_final = price_map.get('Down')
    if up_final is None or dn_final is None:
        continue
    # winner side price ~1, loser ~0
    won_side = 'Up' if up_final > dn_final else 'Down'

    up_g = g[g['outcome']=='Up']
    dn_g = g[g['outcome']=='Down']
    up_cost = (up_g['price']*up_g['size']).sum()
    dn_cost = (dn_g['price']*dn_g['size']).sum()
    up_sh = up_g['size'].sum()
    dn_sh = dn_g['size'].sum()
    total_cost = up_cost + dn_cost

    if won_side == 'Up':
        win_sh = up_sh
        win_px_avg = (up_cost/up_sh) if up_sh>0 else np.nan
    else:
        win_sh = dn_sh
        win_px_avg = (dn_cost/dn_sh) if dn_sh>0 else np.nan

    gross = win_sh - total_cost
    fee = 0.07 * win_px_avg * (1-win_px_avg) * win_sh if win_sh>0 and not np.isnan(win_px_avg) else 0.0
    net = gross - fee

    coin = g['coin'].iloc[0]
    tf = g['tf'].iloc[0]
    slot_start = g['slot_start'].iloc[0]

    rows.append({
        'slug': slug, 'coin': coin, 'tf': tf, 'slot_start': slot_start,
        'n_fills': len(g), 'up_cost': up_cost, 'dn_cost': dn_cost,
        'up_sh': up_sh, 'dn_sh': dn_sh, 'total_cost': total_cost,
        'won_side': won_side, 'win_sh': win_sh, 'win_px_avg': win_px_avg,
        'gross_pnl': gross, 'fee_est': fee, 'net_pnl': net,
    })

out = pd.DataFrame(rows)
out.to_csv('b945_per_slug_2026_07_13.csv', index=False)
print("saved b945_per_slug_2026_07_13.csv, n slugs:", len(out))

print("\n=== TOTALS ===")
print("total net PnL:", out['net_pnl'].sum())
print("total gross PnL:", out['gross_pnl'].sum())
print("n slugs:", len(out))

# window span
ts = buys['timestamp']
days = (ts.max()-ts.min())/86400
print(f"window span days: {days:.2f}")
print(f"$/day (net): {out['net_pnl'].sum()/days:.2f}")

print("\n=== by coin x tf ===")
g2 = out.groupby(['coin','tf']).agg(n=('slug','count'), net_sum=('net_pnl','sum'), net_mean=('net_pnl','mean'),
                                     wr=('net_pnl', lambda x: (x>0).mean()))
print(g2)

print("\nslug WR overall:", (out['net_pnl']>0).mean())
