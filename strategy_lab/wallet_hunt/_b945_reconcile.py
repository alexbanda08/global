"""
B945 reconciliation: full-window ledger (Mar 28 -> Jun 10), weekly attribution,
REDEEM validation, coverage-bias check.

The saved fill_tape.parquet is the EARLY 44%-coverage build (67,859 rows, ends May 15).
The tape build log shows the final 88.4%-coverage tape was 144,589 rows Mar28->Jun10.
Rebuild it here from alchemy_transfers + token_lookup_ext.
"""
import pandas as pd
import numpy as np
import json
import sys

sys.path.insert(0, 'C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical')
from load import load_resolutions, load_resolutions_hf

CACHE = 'C:/Users/alexandre bandarra/Desktop/global/strategy_lab/wallet_hunt/cache/0xb945945d'
PM = 'C:/Users/alexandre bandarra/Desktop/global/strategy_lab/wallet_hunt/cache/_pm_portfolio/0xb945945d'
WALLET = '0xb945945d5bcaf7b56834d4da8cdf8f8f94b2db68'

# ============================================================
# 1. Rebuild FULL fill tape from alchemy transfers
# ============================================================
print("Rebuilding full fill tape (mirrors _b945_build_tape.py lookup chain)...")
ROOT = 'C:/Users/alexandre bandarra/Desktop/global'
at = pd.read_parquet(f'{CACHE}/alchemy_transfers.parquet')

# Token lookup chain: base + ext + clob_resolutions_cache token ids
known = {}
base_lk = pd.read_parquet(f'{ROOT}/strategy_lab/wallet_hunt/cache/_token_lookup.parquet')
for r in base_lk.itertuples():
    known[str(r.asset_id)] = (r.slug, r.outcome)
ext_lk = pd.read_parquet(f'{CACHE}/token_lookup_ext.parquet')
for r in ext_lk.itertuples():
    known[str(r.asset_id)] = (r.slug, r.outcome)
try:
    clob_cache = pd.read_parquet(f'{ROOT}/data/v4/canonical/clob_resolutions_cache.parquet')
    for r in clob_cache.itertuples():
        if pd.notna(getattr(r, 'up_token_id', None)):
            known.setdefault(str(r.up_token_id), (r.slug, 'Up'))
        if pd.notna(getattr(r, 'down_token_id', None)):
            known.setdefault(str(r.down_token_id), (r.slug, 'Down'))
except Exception as exc:
    print('  clob cache skip:', exc)
print(f"  lookup size: {len(known)}")

# erc1155 IN = tokens received (BUY legs); asset hex -> decimal string
e1155_in = at[(at['category'] == 'erc1155') & (at['direction'] == 'to')].copy()
e1155_in['asset_dec'] = e1155_in['asset'].map(
    lambda h: str(int(h, 16)) if isinstance(h, str) and h.startswith('0x') else str(h))

# Cash out per tx: pUSD + USDCE
usdc_out = at[(at['category'] == 'erc20') & (at['direction'] == 'from') &
              (at['asset'].isin(['pUSD', 'USDCE', 'USDC']))].groupby('tx_hash')['value'].sum()

# single-token txs only (price integrity)
tok_per_tx = e1155_in.groupby('tx_hash')['asset_dec'].nunique()
single_tok_tx = tok_per_tx[tok_per_tx == 1].index
e1 = e1155_in[e1155_in['tx_hash'].isin(single_tok_tx)]
fills = e1.groupby(['tx_hash', 'asset_dec', 'ts']).agg(shares=('value', 'sum')).reset_index()
fills['usd'] = fills['tx_hash'].map(usdc_out)
fills = fills[fills['usd'].notna() & (fills['shares'] > 0)]
fills['price'] = fills['usd'] / fills['shares']
fills = fills[(fills['price'] > 0.005) & (fills['price'] < 0.995)]

fills['slug'] = fills['asset_dec'].map(lambda t: known.get(t, (None, None))[0])
fills['outcome'] = fills['asset_dec'].map(lambda t: known.get(t, (None, None))[1])
n_unmapped = fills['slug'].isna().sum()
fills = fills[fills['slug'].notna()]
fills['ts_dt'] = pd.to_datetime(fills['ts'], utc=True, format='ISO8601')
fills = fills[fills['slug'].str.startswith('btc-updown-15m')]
print(f"  rebuilt tape: {len(fills)} fills ({n_unmapped} unmapped dropped), "
      f"{fills['slug'].nunique()} slugs, {fills['ts_dt'].min()} -> {fills['ts_dt'].max()}")
fills.to_parquet(f'{CACHE}/fill_tape_full.parquet', index=False)

# ============================================================
# 2. Resolutions: canonical + HF + REDEEM-inferred fallback
# ============================================================
res = load_resolutions()
res_btc = res[res['slug'].str.startswith('btc-updown-15m')]
print(f"  res outcome dtype/values: {res_btc['outcome'].dtype}, {res_btc['outcome'].unique()[:4]}")
def _norm_outcome(v):
    if pd.isna(v):
        return None
    s = str(v).strip().lower()
    if s in ('up', '1', 'true', 'yes'):
        return 'Up'
    if s in ('down', '0', 'false', 'no'):
        return 'Down'
    return None
res_map = {k: _norm_outcome(v) for k, v in res_btc.set_index('slug')['outcome'].to_dict().items()}
res_map = {k: v for k, v in res_map.items() if v}
try:
    res_hf = load_resolutions_hf()
    hf_map = {k: _norm_outcome(v) for k, v in
              res_hf[res_hf['slug'].str.startswith('btc-updown-15m')].set_index('slug')['outcome'].to_dict().items()}
    hf_map = {k: v for k, v in hf_map.items() if v}
except Exception as e:
    print("  resolutions_hf load failed:", e)
    hf_map = {}
print(f"  canonical res: {len(res_map)}, hf res: {len(hf_map)}")

# REDEEM events (full since Mar 19): usdcSize = winning shares redeemed
redeem = pd.DataFrame(json.load(open(f'{PM}/activity_REDEEM.json', encoding='utf-8')))
redeem_by_slug = redeem.groupby('slug')['usdcSize'].sum()

# ============================================================
# 3. Per-slug ledger over the FULL window
# ============================================================
ps = fills.groupby(['slug', 'outcome']).apply(
    lambda x: pd.Series({
        'n': len(x), 'sh': x['shares'].sum(), 'usd': x['usd'].sum(),
        'vwap': (x['price'] * x['shares']).sum() / x['shares'].sum(),
        'first_ts': x['ts_dt'].min()
    }), include_groups=False
).reset_index()
slug_up = ps[ps['outcome'] == 'Up'].set_index('slug')
slug_dn = ps[ps['outcome'] == 'Down'].set_index('slug')
led = slug_up.join(slug_dn, lsuffix='_up', rsuffix='_dn', how='outer')
for c in ['sh_up', 'sh_dn', 'usd_up', 'usd_dn', 'n_up', 'n_dn']:
    led[c] = led[c].fillna(0)
led['vwap_up'] = led['vwap_up'].fillna(0)
led['vwap_dn'] = led['vwap_dn'].fillna(0)

led['outcome_res'] = led.index.map(lambda s: res_map.get(s, hf_map.get(s)))
# REDEEM-inferred winner fallback: redeem usdc ~= shares of winning side held
led['redeem_usd'] = led.index.map(redeem_by_slug).fillna(0)


def infer_winner(row):
    if pd.notna(row['outcome_res']):
        return row['outcome_res'], 'res'
    if row['redeem_usd'] > 0 and (row['sh_up'] > 0 or row['sh_dn'] > 0):
        # winner side shares should match redeem amount most closely
        d_up = abs(row['sh_up'] - row['redeem_usd'])
        d_dn = abs(row['sh_dn'] - row['redeem_usd'])
        return ('Up', 'redeem') if d_up <= d_dn else ('Down', 'redeem')
    return None, 'none'


winner_src = led.apply(infer_winner, axis=1)
led['winner'] = [w[0] for w in winner_src]
led['winner_src'] = [w[1] for w in winner_src]
print(f"  ledger slugs: {len(led)}; winner from res: {(led['winner_src']=='res').sum()}, "
      f"from redeem: {(led['winner_src']=='redeem').sum()}, unresolved: {led['winner'].isna().sum()}")

# Paired / residual decomposition
led['paired'] = led[['sh_up', 'sh_dn']].min(axis=1)
led['pvs'] = np.where((led['sh_up'] > 0) & (led['sh_dn'] > 0),
                      led['vwap_up'] + led['vwap_dn'], np.nan)
led['won_up'] = np.where(led['winner'] == 'Up', 1.0,
                         np.where(led['winner'] == 'Down', 0.0, np.nan))


def winner_pnl(shares, vwap):
    return shares * (1 - vwap) * (1 - 0.07 * vwap)


led['paired_gross'] = np.where(
    led['won_up'] == 1,
    winner_pnl(led['paired'], led['vwap_up']) - led['paired'] * led['vwap_dn'],
    np.where(led['won_up'] == 0,
             winner_pnl(led['paired'], led['vwap_dn']) - led['paired'] * led['vwap_up'],
             np.nan))
led['residual_pnl'] = np.where(
    led['won_up'] == 1,
    winner_pnl(led['sh_up'] - led['paired'], led['vwap_up']) - (led['sh_dn'] - led['paired']) * led['vwap_dn'],
    np.where(led['won_up'] == 0,
             winner_pnl(led['sh_dn'] - led['paired'], led['vwap_dn']) - (led['sh_up'] - led['paired']) * led['vwap_up'],
             np.nan))
led['total_pnl'] = led['paired_gross'] + led['residual_pnl']
led['slot_s'] = led.index.map(lambda s: int(s.split('-')[-1]))
led['slot_dt'] = pd.to_datetime(led['slot_s'], unit='s', utc=True)
led['iso_week'] = led['slot_dt'].dt.strftime('%G-W%V')

led.to_parquet(f'{CACHE}/per_slug_paired_ledger.parquet')
print(f"  saved full ledger: {led.shape}")

# ============================================================
# 4. Weekly attribution + rebate allocation by event timestamp
# ============================================================
rebates = pd.DataFrame(json.load(open(f'{PM}/activity_MAKER_REBATE.json', encoding='utf-8')))
rebates['dt'] = pd.to_datetime(rebates['timestamp'], unit='s', utc=True)
rebates['iso_week'] = rebates['dt'].dt.strftime('%G-W%V')
reb_week = rebates.groupby('iso_week')['usdcSize'].sum()

led_s = led[led['won_up'].notna()].copy()
wk = led_s.groupby('iso_week').agg(
    n_slugs=('total_pnl', 'count'),
    paired_usd=('paired_gross', 'sum'),
    residual_usd=('residual_pnl', 'sum'),
    trade_pnl=('total_pnl', 'sum'),
    pvs_med=('pvs', 'median'),
    vol_usd_up=('usd_up', 'sum'),
    vol_usd_dn=('usd_dn', 'sum'),
).reset_index()
wk['volume'] = wk['vol_usd_up'] + wk['vol_usd_dn']
wk['rebate'] = wk['iso_week'].map(reb_week).fillna(0)
wk['net'] = wk['trade_pnl'] + wk['rebate']
wk['cum_net'] = wk['net'].cumsum()
print("\n=== WEEKLY ATTRIBUTION ===")
print(wk[['iso_week', 'n_slugs', 'paired_usd', 'residual_usd', 'trade_pnl',
          'rebate', 'net', 'cum_net', 'pvs_med', 'volume']].round(1).to_string(index=False))
print(f"\nTOTAL: trade_pnl={led_s['total_pnl'].sum():.0f}, rebates={rebates['usdcSize'].sum():.0f}, "
      f"net={led_s['total_pnl'].sum()+rebates['usdcSize'].sum():.0f}")
print(f"rebate events span: {rebates['dt'].min()} -> {rebates['dt'].max()}")

# ============================================================
# 5. REDEEM validation: our computed winner payout vs actual redeem
# ============================================================
print("\n=== REDEEM VALIDATION (slugs with canonical resolution) ===")
val = led_s[(led_s['winner_src'] == 'res') & (led_s['redeem_usd'] > 0)].copy()
val['our_winner_shares'] = np.where(val['won_up'] == 1, val['sh_up'], val['sh_dn'])
val['redeem_ratio'] = val['our_winner_shares'] / val['redeem_usd']
print(f"  n with both res + redeem: {len(val)}")
print(f"  ratio our_winner_shares / redeem_usd: median={val['redeem_ratio'].median():.3f}, "
      f"mean={val['redeem_ratio'].mean():.3f}")
print(f"  pct within 5%: {((val['redeem_ratio'] - 1).abs() < 0.05).mean():.3f}")
sample = val.sample(min(20, len(val)), random_state=42)[
    ['won_up', 'sh_up', 'sh_dn', 'redeem_usd', 'our_winner_shares', 'redeem_ratio']]
print(sample.round(2).to_string())

# ============================================================
# 6. Coverage-bias check
# ============================================================
print("\n=== COVERAGE BIAS CHECK ===")
val = val[val['redeem_ratio'].notna()]
n_off = ((val['redeem_ratio'] - 1).abs() >= 0.05).sum()
print(f"  slugs with winner-share mismatch >=5%: {n_off} / {len(val)}")
if n_off >= 8:
    off = val[(val['redeem_ratio'] - 1).abs() >= 0.05]
    print("  mismatched slugs resid mean:", off['residual_pnl'].mean(),
          "vs matched:", val[(val['redeem_ratio'] - 1).abs() < 0.05]['residual_pnl'].mean())
else:
    print("  coverage on winner side is essentially exact -> no negative residual bias from missing fills")
print(f"  corr(redeem_ratio, residual_pnl): {val['redeem_ratio'].corr(val['residual_pnl']):.3f}")

# ============================================================
# 6b. RAW CHAIN CASH-FLOW ground truth (USDC/pUSD in vs out)
# ============================================================
print("\n=== RAW CHAIN CASH FLOW (alchemy erc20) ===")
e20 = at[at['category'] == 'erc20'].copy()
e20 = e20[e20['asset'].isin(['pUSD', 'USDCE', 'USDC'])]
e20['dt'] = pd.to_datetime(e20['ts'], utc=True, format='ISO8601')
PUSD_CONTRACT = '0xf70da97812cb96acdf810712aa562db8dfa3dbef'
inn = e20[e20['direction'] == 'to']
out = e20[e20['direction'] == 'from']
deposits = inn[inn['from'] == PUSD_CONTRACT]['value'].sum()
other_in = inn[inn['from'] != PUSD_CONTRACT]
print(f"  IN total: {inn['value'].sum():.0f}  (deposits from pUSD contract: {deposits:.0f}, other: {other_in['value'].sum():.0f})")
print(f"  IN by sender (top5):")
print(inn.groupby('from')['value'].sum().sort_values(ascending=False).head(5).to_string())
print(f"  OUT total: {out['value'].sum():.0f}")
print(f"  OUT by receiver (top5):")
print(out.groupby('to')['value'].sum().sort_values(ascending=False).head(5).to_string())
chain_pnl = inn['value'].sum() - deposits - out['value'].sum()
print(f"  naive chain pnl (in - deposits - out): {chain_pnl:.0f}")
print(f"  NOTE: redeem income may arrive as erc1155-burn->usdc which may route differently; cross-check vs activity_REDEEM total {redeem['usdcSize'].sum():.0f}")
# lb profit
lb = json.load(open(f'{PM}/lb_profit.json', encoding='utf-8'))
print(f"  lb_profit.json: {lb}")

# Recompute trade pnl using REDEEM as ground truth income (instead of computed winner payout)
print("\n=== GROUND-TRUTH PNL (redeem income - usd spent, per slug, settled) ===")
led_s['gt_pnl'] = led_s['redeem_usd'] - (led_s['usd_up'] + led_s['usd_dn'])
gt = led_s[led_s['redeem_usd'] > 0]
print(f"  n slugs with redeem: {len(gt)}")
print(f"  GT pnl total: {gt['gt_pnl'].sum():.0f}  vs our computed: {gt['total_pnl'].sum():.0f}")
print(f"  GT pnl/slug: {gt['gt_pnl'].mean():.2f} vs computed: {gt['total_pnl'].mean():.2f}")
# Note: slugs where he lost everything have NO redeem -> their usd spent must be added
no_redeem = led_s[led_s['redeem_usd'] == 0]
print(f"  slugs without redeem (total loss or unredeemed): {len(no_redeem)}, "
      f"usd spent there: {-(no_redeem['usd_up'] + no_redeem['usd_dn']).sum():.0f}")
all_gt = led_s['redeem_usd'].sum() - (led_s['usd_up'] + led_s['usd_dn']).sum()
print(f"  FULL GT trade pnl (all settled slugs): {all_gt:.0f}")
print(f"  + rebates {rebates['usdcSize'].sum():.0f} = {all_gt + rebates['usdcSize'].sum():.0f}")

# ============================================================
# 7. FEE-FREE attribution (chain truth basis): redeem pays full $1/share,
#    any fee is already embedded in fill usd. The 0.07 model double-counts.
# ============================================================
led_s['paired_nofee'] = np.where(
    led_s['won_up'] == 1,
    led_s['paired'] * (1 - led_s['vwap_up']) - led_s['paired'] * led_s['vwap_dn'],
    led_s['paired'] * (1 - led_s['vwap_dn']) - led_s['paired'] * led_s['vwap_up'])
led_s['residual_nofee'] = np.where(
    led_s['won_up'] == 1,
    (led_s['sh_up'] - led_s['paired']) * (1 - led_s['vwap_up']) - (led_s['sh_dn'] - led_s['paired']) * led_s['vwap_dn'],
    (led_s['sh_dn'] - led_s['paired']) * (1 - led_s['vwap_dn']) - (led_s['sh_up'] - led_s['paired']) * led_s['vwap_up'])
led_s['total_nofee'] = led_s['paired_nofee'] + led_s['residual_nofee']
print("\n=== FEE-FREE ATTRIBUTION (chain-truth basis) ===")
print(f"  paired_nofee:   {led_s['paired_nofee'].sum():.0f} ({led_s['paired_nofee'].mean():.2f}/slug)")
print(f"  residual_nofee: {led_s['residual_nofee'].sum():.0f} ({led_s['residual_nofee'].mean():.2f}/slug)")
print(f"  total_nofee:    {led_s['total_nofee'].sum():.0f}  vs GT redeem-spent: {all_gt:.0f}")

# Save enriched ledger
led_full = led.join(led_s[['paired_nofee', 'residual_nofee', 'total_nofee', 'gt_pnl']], how='left')
led_full.to_parquet(f'{CACHE}/per_slug_paired_ledger.parquet')

# Weekly GT + fee-free attribution
print("\n=== WEEKLY GROUND-TRUTH + FEE-FREE ATTRIBUTION ===")
wk2 = wk.set_index('iso_week')
wk_extra = led_s.groupby('iso_week').agg(
    gt_pnl=('gt_pnl', 'sum'),
    paired_nf=('paired_nofee', 'sum'),
    resid_nf=('residual_nofee', 'sum'),
    pvs_median=('pvs', 'median'),
    pvs_lt1=('pvs', lambda x: (x < 1.0).mean()))
wk2 = wk2.join(wk_extra)
wk2['gt_net'] = wk2['gt_pnl'] + wk2['rebate']
wk2['gt_cum'] = wk2['gt_net'].cumsum()
cols = ['n_slugs', 'paired_nf', 'resid_nf', 'gt_pnl', 'rebate', 'gt_net', 'gt_cum', 'pvs_median', 'pvs_lt1', 'volume']
print(wk2[cols].round(3).to_string())

# Winning vs losing week diagnostics
wk2['is_win'] = wk2['gt_net'] > 0
print("\n=== WIN vs LOSS WEEK DIAGNOSTICS ===")
diag = led_s.copy()
diag['win_week'] = diag['iso_week'].map(wk2['is_win'])
print(diag.groupby('win_week').agg(
    n=('total_nofee', 'count'),
    paired_mean=('paired_nofee', 'mean'),
    resid_mean=('residual_nofee', 'mean'),
    pvs_med=('pvs', 'median'),
    pvs_lt1=('pvs', lambda x: (x < 1.0).mean()),
    avg_pair_sh=('paired', 'mean'),
    avg_resid_imb=('sh_up', lambda x: np.nan)).round(3).to_string())
# residual size and win rate of residual side
diag['resid_sh'] = (diag['sh_up'] - diag['sh_dn']).abs()
diag['resid_side_won'] = np.where(diag['sh_up'] > diag['sh_dn'], diag['won_up'] == 1, diag['won_up'] == 0)
print("\n  residual-side win rate by week group:")
print(diag.groupby('win_week').agg(
    resid_sh_mean=('resid_sh', 'mean'),
    resid_winrate=('resid_side_won', 'mean')).round(3).to_string())
print("\n  overall residual-side win rate:", round(diag['resid_side_won'].mean(), 4))

print("\nDONE")
