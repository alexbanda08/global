"""V8 SOL 15m universe = V7 + (Path J 2-asset confluence ensembles, Path K TOD-4bucket,
   Path L 1h grandparent regime, Path O HL funding/OI/liq for SOL).

Starts from V7 universe (already has BTC/ETH 15m cross-asset panels, vol_hurst, prewindow).

NEW V8 gates:
- Path J: 2-asset AND/OR confluence ensembles (BTC AND ETH agree on slope, ADX, vol, RF, regime)
- Path J: 3-asset unanimity (BTC + ETH + SOL agree)
- Path K: 4 TOD buckets (asia_morning, european_morning, us_afternoon, us_evening)
- Path L: 1h grandparent regime (built from 1m binance klines, resampled to 1h)
- Path O: HL SOL funding extreme + OI change + liq cascade (lockbox HL coverage limited, but informative)

Output: sol_15m_v8_universe.parquet
"""
import os, time, warnings
warnings.filterwarnings('ignore')
import pandas as pd
import numpy as np

t0 = time.time()
def log(m): print(f"[{time.time()-t0:7.1f}s] {m}", flush=True)

ROOT = r"C:/Users/alexandre bandarra/Desktop/global"
OUT  = r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/sniper_search_2026_05_27/sol_15m_v8"

log("loading V7 universe")
df = pd.read_parquet(f"{ROOT}/strategy_lab/sniper_search_2026_05_27/sol_15m_v7/sol_15m_v7_universe.parquet")
df = df.sort_values('fire_us').reset_index(drop=True)
log(f"V7 universe: {len(df):,} rows, {len(df.columns)} cols")
df['dir_int'] = np.where(df['direction']=='UP', 1, -1)
df['ws_s_us'] = df['slot_start_us'] - 900 * 1_000_000
ds = df['dir_int']

# Capture V7 cols for diff at end
v7_cols = set(df.columns)

# =================== PATH J — 2-asset confluence ensembles ===================
log("=== PATH J: 2-asset confluence ensembles ===")

# J1: BTC AND ETH slope both align with direction (already have unanimity_with, add OR variant + strict variant)
sBTC = df['BTC_slope_30m']
sETH = df['ETH_slope_30m']
nan_mask = sBTC.isna() | sETH.isna()
df['g_J_btc_eth_slope_unan_strong'] = np.where(nan_mask, np.nan,
    (((ds>0) & (sBTC>0.5) & (sETH>0.5)) | ((ds<0) & (sBTC<-0.5) & (sETH<-0.5))).astype(float))
df['g_J_btc_eth_slope_unan_either'] = np.where(nan_mask, np.nan,
    (((sBTC>0) & (sETH>0)) | ((sBTC<0) & (sETH<0))).astype(float))  # both same sign regardless of dir

# J2: BTC AND ETH ADX both strong
aBTC = df['BTC_adx']; aETH = df['ETH_adx']
nm = aBTC.isna() | aETH.isna()
df['g_J_btc_eth_adx_both_strong'] = np.where(nm, np.nan, ((aBTC>25) & (aETH>25)).astype(float))
df['g_J_btc_eth_adx_both_v_strong'] = np.where(nm, np.nan, ((aBTC>30) & (aETH>30)).astype(float))
df['g_J_btc_eth_adx_either_strong'] = np.where(nm, np.nan, ((aBTC>25) | (aETH>25)).astype(float))

# J3: BTC AND ETH vol both low (calm baseline)
rvBTC = df['BTC_rv60']; rvETH = df['ETH_rv60']
nm = rvBTC.isna() | rvETH.isna()
rv_btc_med = rvBTC.median(); rv_eth_med = rvETH.median()
df['g_J_btc_eth_vol_both_low'] = np.where(nm, np.nan, ((rvBTC<=rv_btc_med) & (rvETH<=rv_eth_med)).astype(float))
df['g_J_btc_eth_vol_both_high'] = np.where(nm, np.nan, ((rvBTC>rv_btc_med) & (rvETH>rv_eth_med)).astype(float))
df['g_J_btc_eth_vol_split'] = np.where(nm, np.nan,  # BTC calm but ETH active or vice versa
    (((rvBTC<=rv_btc_med) & (rvETH>rv_eth_med)) | ((rvBTC>rv_btc_med) & (rvETH<=rv_eth_med))).astype(float))

# J4: BTC AND ETH tr_stack both align with direction
tBTC = df['BTC_tr_stack']; tETH = df['ETH_tr_stack']
nm = tBTC.isna() | tETH.isna()
df['g_J_btc_eth_tr_stack_unan_with'] = np.where(nm, np.nan,
    (((ds>0) & (tBTC>0) & (tETH>0)) | ((ds<0) & (tBTC<0) & (tETH<0))).astype(float))

# J5: BTC AND ETH regime trending and aligned (already exists as g_xa_btc_eth_regime_trend_with),
# add weaker variant: either trending and direction-aligned
rBTC = df['BTC_reg']; rETH = df['ETH_reg']
nm = rBTC.isna() | rETH.isna()
df['g_J_btc_eth_regime_at_least_one_trend_with'] = np.where(nm, np.nan,
    ((((ds>0) & (rBTC=='trending_up')) | ((ds<0) & (rBTC=='trending_dn')) |
      ((ds>0) & (rETH=='trending_up')) | ((ds<0) & (rETH=='trending_dn')))).astype(float))

# J6: 3-asset MP skew unanimity (already exists), add strict (both strong)
mp_btc = df['BTC_mp_skew']; mp_eth = df['ETH_mp_skew']; mp_sol = df['mp_skew_at_ws']
nm = mp_btc.isna() | mp_eth.isna() | mp_sol.isna()
df['g_J_3asset_mp_strong_unan_with'] = np.where(nm, np.nan,
    (((ds>0) & (mp_btc>0.05) & (mp_eth>0.05) & (mp_sol>0)) |
     ((ds<0) & (mp_btc<-0.05) & (mp_eth<-0.05) & (mp_sol<0))).astype(float))
# 2-asset BTC+ETH MP unanimity
nm2 = mp_btc.isna() | mp_eth.isna()
df['g_J_btc_eth_mp_unan_with'] = np.where(nm2, np.nan,
    (((ds>0) & (mp_btc>0) & (mp_eth>0)) | ((ds<0) & (mp_btc<0) & (mp_eth<0))).astype(float))

# J7: 2-asset composite "all signals confirm" (slope AND adx AND tr_stack all aligned for both BTC + ETH)
nm = sBTC.isna() | sETH.isna() | aBTC.isna() | aETH.isna() | tBTC.isna() | tETH.isna()
def _compose_unan(d_pos):
    sgn = 1 if d_pos else -1
    return ((ds==sgn) & (sBTC*sgn>0) & (sETH*sgn>0) & (aBTC>25) & (aETH>25) & (tBTC*sgn>0) & (tETH*sgn>0))
df['g_J_btc_eth_triple_unan_with'] = np.where(nm, np.nan,
    (_compose_unan(True) | _compose_unan(False)).astype(float))

# J8: cross-asset "weak BTC, strong ETH" and vice versa
# - SOL might respond more to ETH leadership when BTC is dead
df['g_J_eth_leads_btc_quiet'] = np.where(sBTC.isna() | sETH.isna() | aETH.isna(), np.nan,
    ((aETH>25) & (sBTC.abs() < 0.3) &
     (((ds>0) & (sETH>0)) | ((ds<0) & (sETH<0)))).astype(float))
df['g_J_btc_leads_eth_quiet'] = np.where(sBTC.isna() | sETH.isna() | aBTC.isna(), np.nan,
    ((aBTC>25) & (sETH.abs() < 0.3) &
     (((ds>0) & (sBTC>0)) | ((ds<0) & (sBTC<0)))).astype(float))

# J rates
for g in ['g_J_btc_eth_slope_unan_strong','g_J_btc_eth_adx_both_strong','g_J_btc_eth_adx_both_v_strong',
          'g_J_btc_eth_vol_both_low','g_J_btc_eth_vol_both_high',
          'g_J_btc_eth_tr_stack_unan_with','g_J_btc_eth_triple_unan_with',
          'g_J_btc_eth_regime_at_least_one_trend_with','g_J_3asset_mp_strong_unan_with',
          'g_J_btc_eth_mp_unan_with','g_J_eth_leads_btc_quiet','g_J_btc_leads_eth_quiet']:
    rate = df[g].mean()
    nn = df[g].notna().mean()
    log(f"  {g}: rate={rate:.3f} nonnull={nn:.3f}")

# =================== PATH K — Time-of-day 4 buckets ===================
log("=== PATH K: TOD 4 buckets ===")
# fire_dt
df['fire_dt'] = pd.to_datetime(df['fire_us'], unit='us', utc=True)
df['hour_utc_v8'] = df['fire_dt'].dt.hour

# 4 TOD buckets (V8 brief §2 Path K)
def tod_bucket(h):
    if 0 <= h < 7: return 'asia_morning'
    elif 7 <= h < 13: return 'european_morning'
    elif 13 <= h < 19: return 'us_afternoon'
    else: return 'us_evening'
df['tod_v8'] = df['hour_utc_v8'].apply(tod_bucket)
for b in ['asia_morning','european_morning','us_afternoon','us_evening']:
    df[f'g_K_tod_{b}'] = (df['tod_v8'] == b).astype(float)
    log(f"  g_K_tod_{b}: rate={df[f'g_K_tod_{b}'].mean():.3f}")
# Also 8 narrower buckets for finer slicing (3-hour each)
for start in range(0, 24, 3):
    df[f'g_K_h{start:02d}_{(start+3) % 24:02d}'] = ((df['hour_utc_v8']>=start) & (df['hour_utc_v8']<start+3)).astype(float)

# =================== PATH L — 1h grandparent regime panel ===================
log("=== PATH L: building 1h grandparent regime from binance 1m ===")
# Resample binance 1m to 1h, compute regime features.
k = pd.read_parquet(f"{ROOT}/data/v4/canonical/klines_1m.parquet")
k1m = k[(k['period_id']=='1MIN') & (k['source']=='binance-spot-ws')].copy()
log(f"  binance 1m rows: {len(k1m):,}")

# Map symbol_id -> asset
sym_map = {
    'BINANCE_SPOT_BTC_USDT': 'BTC',
    'BINANCE_SPOT_ETH_USDT': 'ETH',
    'BINANCE_SPOT_SOL_USDT': 'SOL',
}
k1m['asset'] = k1m['symbol_id'].map(sym_map)
k1m = k1m[k1m['asset'].notna()].copy()

def build_1h_regime(asset):
    sub = k1m[k1m['asset']==asset].copy()
    sub = sub.sort_values('time_period_start_us').reset_index(drop=True)
    sub['ts'] = pd.to_datetime(sub['time_period_start_us'], unit='us', utc=True)
    sub = sub.set_index('ts')
    # Aggregate to 1h
    h = sub[['price_open','price_high','price_low','price_close','volume_traded']].resample('1h').agg({
        'price_open':'first','price_high':'max','price_low':'min','price_close':'last','volume_traded':'sum'
    }).dropna()
    if len(h) < 50:
        return None
    # Compute features
    # 1) ADX-14
    h['tr'] = (h['price_high'] - h['price_low']).combine_first(
        ((h['price_high'] - h['price_close'].shift()).abs()).combine_first(
            ((h['price_low']  - h['price_close'].shift()).abs())))
    h['plus_dm']  = np.where((h['price_high'].diff() > h['price_low'].shift().diff().abs()) & (h['price_high'].diff() > 0), h['price_high'].diff(), 0)
    h['minus_dm'] = np.where((h['price_low'].shift().diff().abs() > h['price_high'].diff()) & (h['price_low'].diff() < 0), -h['price_low'].diff(), 0)
    n = 14
    atr_n = h['tr'].rolling(n).mean()
    plus_di_n  = 100 * (h['plus_dm'].rolling(n).mean() / atr_n)
    minus_di_n = 100 * (h['minus_dm'].rolling(n).mean() / atr_n)
    dx = 100 * (plus_di_n - minus_di_n).abs() / (plus_di_n + minus_di_n).replace(0, np.nan)
    h['adx_1h'] = dx.rolling(n).mean()
    h['plus_di_1h'] = plus_di_n
    h['minus_di_1h'] = minus_di_n
    # 2) slope_4h (linreg over 4 bars)
    def slope(arr):
        if len(arr) < 4 or np.isnan(arr).any():
            return np.nan
        x = np.arange(len(arr))
        y = np.array(arr)
        return np.polyfit(x, y, 1)[0]
    h['slope_4h'] = h['price_close'].rolling(4).apply(slope, raw=True)
    # 3) realized_vol_6h
    h['logret'] = np.log(h['price_close'] / h['price_close'].shift())
    h['rv_6h'] = h['logret'].rolling(6).std() * np.sqrt(6)
    # 4) regime label (simple): trending_up if slope_4h > +0.05% and ADX > 20
    h['regime_1h'] = np.where(
        (h['adx_1h']>20) & (h['slope_4h']>0), 'trending_up',
        np.where((h['adx_1h']>20) & (h['slope_4h']<0), 'trending_dn',
        np.where(h['adx_1h']<15, 'ranging', 'transitional'))
    )
    h = h.reset_index()
    h['ts_us'] = (h['ts'].astype('int64') // 1000).astype(np.int64)
    h['asset'] = asset
    return h[['asset','ts_us','price_close','adx_1h','plus_di_1h','minus_di_1h','slope_4h','rv_6h','regime_1h']]

panels = []
for a in ['BTC','ETH','SOL']:
    panel = build_1h_regime(a)
    if panel is not None:
        log(f"  {a} 1h panel: {len(panel)} rows, regime counts: {panel['regime_1h'].value_counts().to_dict()}")
        panels.append(panel)

regime_1h = pd.concat(panels, ignore_index=True).sort_values(['asset','ts_us']).reset_index(drop=True)
regime_1h.to_parquet(f"{OUT}/regime_panel_1h.parquet", index=False)
log(f"  wrote regime_panel_1h.parquet ({len(regime_1h)} rows)")

# Asof-join 1h panel per asset at SOL's ws_s
for src in ['BTC','ETH','SOL']:
    pa = regime_1h[regime_1h['asset']==src][['ts_us','adx_1h','slope_4h','rv_6h','regime_1h']].copy()
    pa.columns = ['ts_us', f'{src}_adx_1h', f'{src}_slope_4h', f'{src}_rv_6h', f'{src}_reg_1h']
    pa = pa.sort_values('ts_us').reset_index(drop=True)
    df = pd.merge_asof(df.sort_values('ws_s_us'),
                       pa,
                       left_on='ws_s_us', right_on='ts_us',
                       direction='backward', allow_exact_matches=True,
                       tolerance=int(2*3600*1e6))  # 2h tolerance
    if 'ts_us' in df.columns:
        df = df.drop(columns=['ts_us'])
    df = df.sort_values('fire_us').reset_index(drop=True)
    log(f"    {src}_adx_1h non-null={df[f'{src}_adx_1h'].notna().mean()*100:.1f}%")

# 1h grandparent gates
ds = df['dir_int']
for src in ['BTC','ETH','SOL']:
    sl = df[f'{src}_slope_4h']
    df[f'g_L_{src}_grandparent_slope_with'] = np.where(sl.isna(), np.nan,
        (((ds>0) & (sl>0)) | ((ds<0) & (sl<0))).astype(float))
    rl = df[f'{src}_reg_1h']
    df[f'g_L_{src}_grandparent_trend_with'] = np.where(rl.isna(), np.nan,
        (((ds>0) & (rl=='trending_up')) | ((ds<0) & (rl=='trending_dn'))).astype(float))
    df[f'g_L_{src}_grandparent_ranging'] = np.where(rl.isna(), np.nan,
        (rl=='ranging').astype(float))
    df[f'g_L_{src}_grandparent_adx_strong'] = np.where(df[f'{src}_adx_1h'].isna(), np.nan,
        (df[f'{src}_adx_1h']>20).astype(float))

# Cross-tf confluence: 15m parent trend AND 1h grandparent trend (BTC) aligned
df['g_L_15m_1h_btc_align_with'] = np.where(
    df['BTC_reg'].isna() | df['BTC_reg_1h'].isna(), np.nan,
    (((ds>0) & ((df['BTC_reg']=='trending_up') | (df['BTC_slope_30m']>0)) & (df['BTC_reg_1h']=='trending_up')) |
     ((ds<0) & ((df['BTC_reg']=='trending_dn') | (df['BTC_slope_30m']<0)) & (df['BTC_reg_1h']=='trending_dn'))).astype(float))

for g in ['g_L_BTC_grandparent_slope_with','g_L_ETH_grandparent_slope_with','g_L_SOL_grandparent_slope_with',
          'g_L_BTC_grandparent_trend_with','g_L_BTC_grandparent_ranging',
          'g_L_BTC_grandparent_adx_strong','g_L_15m_1h_btc_align_with']:
    log(f"  {g}: rate={df[g].mean():.3f} nonnull={df[g].notna().mean():.3f}")

# =================== PATH O — HL funding/OI/liq for SOL ===================
log("=== PATH O: HL panels for SOL ===")
# HL funding
hl_f = pd.read_parquet(f"{ROOT}/data/v4/canonical/hyperliquid_funding.parquet")
hl_f = hl_f[hl_f['symbol']=='SOL'].sort_values('funding_time_us').reset_index(drop=True)
hl_f['funding_rate'] = pd.to_numeric(hl_f['funding_rate'], errors='coerce')
log(f"  HL SOL funding rows: {len(hl_f):,}")
# asof at ws_s
hl_fj = hl_f[['funding_time_us','funding_rate']].rename(columns={'funding_time_us':'ts_us','funding_rate':'hl_sol_funding'})
df = pd.merge_asof(df.sort_values('ws_s_us'),
                   hl_fj.sort_values('ts_us'),
                   left_on='ws_s_us', right_on='ts_us',
                   direction='backward', allow_exact_matches=True,
                   tolerance=int(48*3600*1e6))  # 48h tolerance (funding is hourly)
if 'ts_us' in df.columns: df = df.drop(columns=['ts_us'])
df = df.sort_values('fire_us').reset_index(drop=True)
log(f"  hl_sol_funding non-null: {df['hl_sol_funding'].notna().mean()*100:.1f}%")
log(f"  hl_sol_funding describe: {df['hl_sol_funding'].describe().to_dict()}")

# HL metrics (mark, OI) — but only thru May 16
hl_m = pd.read_parquet(f"{ROOT}/data/v4/canonical/hyperliquid_metrics.parquet")
hl_m_sol = hl_m[hl_m['symbol']=='SOL'].copy()
hl_m_sol['open_interest'] = pd.to_numeric(hl_m_sol['open_interest'], errors='coerce')
hl_m_sol['mark_price'] = pd.to_numeric(hl_m_sol['mark_price'], errors='coerce')
hl_m_sol = hl_m_sol.sort_values('time_exchange_us').reset_index(drop=True)
log(f"  HL SOL metrics rows: {len(hl_m_sol):,}")
hl_mj = hl_m_sol[['time_exchange_us','mark_price','open_interest']].rename(columns={
    'time_exchange_us':'ts_us','mark_price':'hl_sol_mark','open_interest':'hl_sol_oi'})
df = pd.merge_asof(df.sort_values('ws_s_us'),
                   hl_mj.sort_values('ts_us'),
                   left_on='ws_s_us', right_on='ts_us',
                   direction='backward', allow_exact_matches=True,
                   tolerance=int(15*60*1e6))
if 'ts_us' in df.columns: df = df.drop(columns=['ts_us'])
df = df.sort_values('fire_us').reset_index(drop=True)
log(f"  hl_sol_oi non-null: {df['hl_sol_oi'].notna().mean()*100:.1f}%")

# OI change (1h)
hl_mj2 = hl_m_sol[['time_exchange_us','open_interest']].rename(columns={
    'time_exchange_us':'ts_us','open_interest':'hl_sol_oi_1h'})
df['ws_minus_1h_us'] = df['ws_s_us'] - 3600 * 1_000_000
df = pd.merge_asof(df.sort_values('ws_minus_1h_us'),
                   hl_mj2.sort_values('ts_us'),
                   left_on='ws_minus_1h_us', right_on='ts_us',
                   direction='backward', allow_exact_matches=True,
                   tolerance=int(15*60*1e6))
if 'ts_us' in df.columns: df = df.drop(columns=['ts_us'])
df = df.sort_values('fire_us').reset_index(drop=True)
df['hl_sol_oi_chg_1h_pct'] = ((df['hl_sol_oi'] - df['hl_sol_oi_1h']) / df['hl_sol_oi_1h'].replace(0, np.nan))

# HL gates
# Funding extreme (top/bot 20% quantiles)
fund = df['hl_sol_funding']
f_q80 = fund.quantile(0.80)
f_q20 = fund.quantile(0.20)
f_q90 = fund.quantile(0.90)
f_q10 = fund.quantile(0.10)
log(f"  HL funding q10={f_q10:.6f} q20={f_q20:.6f} q80={f_q80:.6f} q90={f_q90:.6f}")

# Contrarian gates: extreme positive funding → DOWN; extreme negative funding → UP
df['g_O_hl_funding_extreme_contra'] = np.where(fund.isna(), np.nan,
    (((ds<0) & (fund>f_q80)) | ((ds>0) & (fund<f_q20))).astype(float))
df['g_O_hl_funding_extreme_with'] = np.where(fund.isna(), np.nan,
    (((ds>0) & (fund>f_q80)) | ((ds<0) & (fund<f_q20))).astype(float))
df['g_O_hl_funding_v_extreme_contra'] = np.where(fund.isna(), np.nan,
    (((ds<0) & (fund>f_q90)) | ((ds>0) & (fund<f_q10))).astype(float))
df['g_O_hl_funding_near_zero'] = np.where(fund.isna(), np.nan,
    ((fund.abs() < fund.abs().quantile(0.30))).astype(float))

# OI change gates
oi_chg = df['hl_sol_oi_chg_1h_pct']
df['g_O_hl_oi_expansion_with'] = np.where(oi_chg.isna(), np.nan,
    (oi_chg > 0.02).astype(float))
df['g_O_hl_oi_contraction'] = np.where(oi_chg.isna(), np.nan,
    (oi_chg < -0.02).astype(float))

# HL liquidations: SOL liq volume in last 1h before fire
log("  loading HL SOL liquidations (last-1h volume)")
hl_l = pd.read_parquet(f"{ROOT}/data/v4/canonical/hyperliquid_liquidations_30d.parquet")
hl_l_sol = hl_l[hl_l['coin']=='SOL'].copy()
hl_l_sol['size'] = pd.to_numeric(hl_l_sol['size'], errors='coerce')
hl_l_sol['price'] = pd.to_numeric(hl_l_sol['price'], errors='coerce')
hl_l_sol['notional'] = hl_l_sol['size'] * hl_l_sol['price']
hl_l_sol = hl_l_sol.dropna(subset=['notional']).sort_values('time_exchange_us').reset_index(drop=True)
log(f"  HL SOL liq rows: {len(hl_l_sol):,}")
# For each fire, sum notional in [ws_s-3600s, ws_s] - direction split
# We need: long_liq (longs liquidated, mark dropping) vs short_liq (shorts liquidated, mark rising)
# side='B' (buy = short being closed = short liq), 'S' (sell = long being closed = long liq)
# In HL data: dir column may indicate. Let me check.
print(f"  HL liq dir counts: {hl_l_sol['dir'].value_counts().to_dict() if 'dir' in hl_l_sol.columns else 'no dir'}")
print(f"  HL liq side counts: {hl_l_sol['side'].value_counts().to_dict() if 'side' in hl_l_sol.columns else 'no side'}")
# dir column indicates if it was a long or short liq
# We'll just aggregate total notional and pure "magnitude"
# Compute rolling 1h sum by walking forward
liq_t = hl_l_sol['time_exchange_us'].values
liq_n = hl_l_sol['notional'].values
# For each fire ws_s_us, do binary search for window [ws_s-3600s_us, ws_s_us]
import bisect
ws_arr = df['ws_s_us'].values
liq_1h_sum = np.zeros(len(ws_arr))
WIN_US = 3600 * 1_000_000
liq_t_list = list(liq_t)
for i, ws in enumerate(ws_arr):
    lo = bisect.bisect_left(liq_t_list, ws - WIN_US)
    hi = bisect.bisect_right(liq_t_list, ws)
    if hi > lo:
        liq_1h_sum[i] = liq_n[lo:hi].sum()
df['hl_sol_liq_1h_notional'] = liq_1h_sum
liq_q75 = pd.Series(liq_1h_sum[liq_1h_sum>0]).quantile(0.75) if (liq_1h_sum>0).any() else 0
liq_q90 = pd.Series(liq_1h_sum[liq_1h_sum>0]).quantile(0.90) if (liq_1h_sum>0).any() else 0
log(f"  HL SOL liq_1h_notional q75={liq_q75:.0f} q90={liq_q90:.0f}")
df['g_O_hl_liq_spike_q75'] = (df['hl_sol_liq_1h_notional'] > liq_q75).astype(float)
df['g_O_hl_liq_spike_q90'] = (df['hl_sol_liq_1h_notional'] > liq_q90).astype(float)
df['g_O_hl_liq_calm'] = (df['hl_sol_liq_1h_notional'] < pd.Series(liq_1h_sum).quantile(0.25)).astype(float)

# Mark HL data nullity (lockbox has no HL coverage)
log(f"  hl_sol_funding non-null by split:")
df['fire_dt_v8'] = pd.to_datetime(df['fire_us'], unit='us', utc=True)
total_days = (df['fire_dt_v8'].max() - df['fire_dt_v8'].min()).total_seconds() / 86400
train_end = df['fire_dt_v8'].min() + pd.Timedelta(days=int(total_days*0.6))
val_end   = df['fire_dt_v8'].min() + pd.Timedelta(days=int(total_days*0.8))
df['split_v8'] = pd.cut(df['fire_dt_v8'],
    bins=[df['fire_dt_v8'].min()-pd.Timedelta(seconds=1), train_end, val_end, df['fire_dt_v8'].max()+pd.Timedelta(seconds=1)],
    labels=['train','val','lockbox'])
for s in ['train','val','lockbox']:
    sub = df[df['split_v8']==s]
    log(f"    split={s}: n={len(sub)}, hl_funding_nn={sub['hl_sol_funding'].notna().mean()*100:.1f}%, "
        f"hl_oi_nn={sub['hl_sol_oi'].notna().mean()*100:.1f}%, "
        f"hl_liq_1h_med={sub['hl_sol_liq_1h_notional'].median():.0f}")

# Cleanup intermediate cols
for c in ['hl_sol_oi_1h','ws_minus_1h_us']:
    if c in df.columns: df = df.drop(columns=[c])

# Save universe
new_gs = sorted([c for c in df.columns if c.startswith('g_') and c not in v7_cols])
new_panels = sorted([c for c in df.columns if not c.startswith('g_') and c not in v7_cols])
log(f"V8 NEW gates ({len(new_gs)}): {new_gs}")
log(f"V8 NEW panel cols ({len(new_panels)}): {new_panels}")

df.to_parquet(f"{OUT}/sol_15m_v8_universe.parquet", index=False)
log(f"WROTE {OUT}/sol_15m_v8_universe.parquet ({len(df):,} rows, {len(df.columns)} cols)")
log("DONE")
