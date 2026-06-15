"""
Cross-timeframe relative-value / arb test: 5m vs 15m Polymarket BTC/ETH/SOL.

Key insight: the LAST 5m window [T+10m, T+15m] shares settle time with the 15m
window [T, T+15m]. At t=T+10m:
  - 15m-Up resolves P(T+15) > P(T)        [P(T) = 15m strike, known]
  - 5m-Up resolves  P(T+15) > P(T+10)     [P(T+10) = 5m strike, known]
  - gap g = P(T+10) - P(T) is KNOWN from Binance 1s klines

Signal A (oracle-lag / determinism): if |g| is large relative to typical 5m move,
  the 15m outcome is near-certain (e.g. g >> 0 => 15m-Up ~certain).
  If 15m-Up ask is STILL lagging (< threshold), buy it and hold to settlement.
  => Tests whether Polymarket prices lag known Binance mid-window price data.

Signal B (cross-market consistency): at t=T+10, the 15m-Up price and 5m-Up price
  should be mutually consistent given g. Specifically:
    - 15m-Up needs P(T+15) > P(T)     => threshold = P(T)
    - 5m-Up  needs P(T+15) > P(T+10)  => threshold = P(T+10) = P(T)+g
  Both are bets on the SAME P(T+15). If g>0 (price rose), 15m-Up is easier to win
  (lower bar P(T)) than 5m-Up (higher bar P(T+10)). So 15m-Up price should be > 5m-Up.
  When 15m_ask < 5m_bid (inverted), it's a mispricing: the 15m-Up is CHEAPER than
  the 5m-Up despite being easier to win. Buy 15m-Up, (optionally short 5m-Up).

Both signals are evaluated with the 0.07 winner-only fee curve, bootstrap CI over slugs.
"""

import sys, os
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pyarrow.compute as pc

ROOT = 'C:/Users/alexandre bandarra/Desktop/global'
sys.path.insert(0, f'{ROOT}/data/v4/canonical')
sys.path.insert(0, f'{ROOT}/strategy_lab')
from load import load_resolutions, load_orderbook_l25_streaming

OUTDIR = f'{ROOT}/strategy_lab/directional/_results'
os.makedirs(OUTDIR, exist_ok=True)

# ── Config ─────────────────────────────────────────────────────────────────────
ASSETS = ['BTC', 'ETH', 'SOL']
ASSET_SYM = {'BTC': 'BINANCE_SPOT_BTC_USDT', 'ETH': 'BINANCE_SPOT_ETH_USDT', 'SOL': 'BINANCE_SPOT_SOL_USDT'}
T_START = pd.Timestamp('2026-05-20', tz='UTC')
T_END   = pd.Timestamp('2026-06-05', tz='UTC')
# Decision offset: we look at book at t = 15m_slot_start + 600s (= 5m slot_start for last window)
# Add a 2s buffer for Binance 1s kline to be confirmed
DECISION_OFFSET_S = 600   # seconds after 15m slot_start
L25_CHUNK = 120           # slugs per L25 load
NOTIONAL = 25.0           # $25 per trade
FEE_RATE = 0.07
N_BOOT = 2000
SEED = 42

print("=== Cross-Timeframe Arb Analysis ===")
print(f"Window: {T_START.date()} -> {T_END.date()}")

# ── Load resolutions ───────────────────────────────────────────────────────────
print("\nLoading resolutions...")
res = load_resolutions(assets=ASSETS, timeframes=['5m', '15m'])
t0_us = int(T_START.value // 1000)
t1_us = int(T_END.value // 1000)
res = res[(res['slot_start_us'] >= t0_us) & (res['slot_start_us'] < t1_us)].copy()
print(f"  Resolutions: {res.shape[0]} rows  ({res['timeframe'].value_counts().to_dict()})")

m15 = res[res['timeframe'] == '15m'].copy()
m5  = res[res['timeframe'] == '5m'].copy()

# ── Load Binance 1s klines for window ─────────────────────────────────────────
print("\nLoading Binance 1s klines...")
kl1s_path = f'{ROOT}/data/v4/canonical/klines_1s.parquet'

def load_klines_asset(sym, t0_us, t1_us):
    """Load 1s klines for one symbol in window, return dataframe sorted by ts."""
    filters = [
        ('symbol_id', '=', sym),
        ('period_id', '=', '1SEC'),
        ('time_period_start_us', '>=', t0_us - 120_000_000),  # 2 min buffer
        ('time_period_start_us', '<',  t1_us + 120_000_000),
    ]
    tbl = pq.read_table(kl1s_path, columns=['time_period_start_us','price_close'], filters=filters)
    df = tbl.to_pandas().sort_values('time_period_start_us').reset_index(drop=True)
    return df

klines = {}
for asset in ASSETS:
    sym = ASSET_SYM[asset]
    klines[asset] = load_klines_asset(sym, t0_us, t1_us)
    print(f"  {asset}: {len(klines[asset])} rows, ts range {klines[asset]['time_period_start_us'].min()//1e6:.0f}-{klines[asset]['time_period_start_us'].max()//1e6:.0f}")

def get_price_at_us(kdf, target_us, tol_us=2_000_000):
    """Return price_close of bar starting closest to and <= target_us."""
    # kdf sorted by time_period_start_us
    arr = kdf['time_period_start_us'].values
    idx = np.searchsorted(arr, target_us, side='right') - 1
    if idx < 0:
        return np.nan
    ts = arr[idx]
    if target_us - ts > tol_us:
        return np.nan
    return kdf['price_close'].iloc[idx]

# ── Build matched pairs table ──────────────────────────────────────────────────
print("\nBuilding matched pairs (15m <-> last 5m)...")
rows = []
for asset in ASSETS:
    a15 = m15[m15['ticker'] == asset].copy()
    a5  = m5[m5['ticker'] == asset].copy()
    kdf = klines[asset].reset_index(drop=True)

    # For each 15m slug, find the last 5m (slot_start = 15m_slot_end - 5m = 15m_slot_start + 600s)
    for _, r15 in a15.iterrows():
        last5m_start_us = r15['slot_start_us'] + 10 * 60 * 1_000_000  # T+10m
        # Find matching 5m
        match = a5[a5['slot_start_us'] == last5m_start_us]
        if len(match) == 0:
            continue
        r5 = match.iloc[0]

        # Verify they share slot_end
        if r5['slot_end_us'] != r15['slot_end_us']:
            continue

        # Get prices from Binance 1s
        # P(T) = price at 15m slot_start (= 15m strike, available from resolutions)
        p_T  = r15['strike_price']  # chainlink-derived strike at T

        # P(T+10) = price at 5m slot_start (= 5m strike)
        p_T10 = r5['strike_price']  # chainlink-derived

        # Binance mid-window price at T+10 (for oracle-lag check)
        # Use binance 1s price_close of bar ending at T+10 (+- 2s tolerance)
        p_T10_binance = get_price_at_us(kdf, last5m_start_us, tol_us=5_000_000)

        # gap g = P(T+10) - P(T) in bp
        if p_T > 0 and not np.isnan(p_T10):
            g = p_T10 - p_T
            g_bp = g / p_T * 10000  # basis points
        else:
            g = np.nan
            g_bp = np.nan

        # Decision time for book lookup: t = 15m_slot_start + 600s + small buffer
        decision_us = r15['slot_start_us'] + (DECISION_OFFSET_S + 5) * 1_000_000

        rows.append({
            'asset': asset,
            'slug_15m': r15['slug'],
            'slug_5m': r5['slug'],
            'slot_start_us': r15['slot_start_us'],
            'slot_end_us': r15['slot_end_us'],
            'outcome_15m': r15['outcome'],
            'outcome_5m': r5['outcome'],
            'p_T': p_T,
            'p_T10': p_T10,
            'p_T10_binance': p_T10_binance,
            'g': g,
            'g_bp': g_bp,
            'decision_us': decision_us,
            # placeholders for book data
            'ask_15m_up': np.nan,
            'bid_15m_up': np.nan,
            'ask_5m_up': np.nan,
            'bid_5m_up': np.nan,
            'ask_15m_dn': np.nan,
            'bid_15m_dn': np.nan,
        })

pairs = pd.DataFrame(rows)
print(f"  Matched pairs: {len(pairs)}  per-asset: {pairs['asset'].value_counts().to_dict()}")
print(f"  g_bp stats: mean={pairs['g_bp'].mean():.1f} std={pairs['g_bp'].std():.1f} min={pairs['g_bp'].min():.1f} max={pairs['g_bp'].max():.1f}")

# ── Load L25 books and fill ask/bid at decision_us ────────────────────────────
print("\nLoading L25 book data (chunked by asset)...")

def get_best_ask_bid(books, slug, outcome, fire_us):
    """Get best ask and bid at fire_us from books dict."""
    key = (slug, outcome)
    if key not in books:
        return np.nan, np.nan
    ts_arr, ap, asz, bp, bsz = books[key]
    # find index closest to fire_us (search sorted)
    idx = np.searchsorted(ts_arr, fire_us, side='right') - 1
    if idx < 0:
        return np.nan, np.nan
    if fire_us - ts_arr[idx] > 10_000_000:  # 10s stale
        return np.nan, np.nan
    return float(ap[idx, 0]), float(bp[idx, 0])

for asset in ASSETS:
    print(f"  {asset}...")
    asset_pairs = pairs[pairs['asset'] == asset].copy()

    # Get all slugs needed
    all_slugs = set(asset_pairs['slug_15m']) | set(asset_pairs['slug_5m'])
    slug_list = sorted(all_slugs)

    # Load in chunks
    asset_books = {}
    for i in range(0, len(slug_list), L25_CHUNK):
        chunk = set(slug_list[i:i+L25_CHUNK])
        b = load_orderbook_l25_streaming(
            asset.lower(),
            slugs=chunk,
            subsample_1hz=False,
        )
        asset_books.update(b)
        del b

    print(f"    Loaded {len(asset_books)} book entries for {len(slug_list)} slugs")

    # Fill ask/bid for each pair
    for idx_pair, row in asset_pairs.iterrows():
        dec_us = int(row['decision_us'])
        a15_ask, a15_bid = get_best_ask_bid(asset_books, row['slug_15m'], 'Up', dec_us)
        a15_dn_ask, a15_dn_bid = get_best_ask_bid(asset_books, row['slug_15m'], 'Down', dec_us)
        a5_ask,  a5_bid  = get_best_ask_bid(asset_books, row['slug_5m'],  'Up', dec_us)
        pairs.at[idx_pair, 'ask_15m_up'] = a15_ask
        pairs.at[idx_pair, 'bid_15m_up'] = a15_bid
        pairs.at[idx_pair, 'ask_5m_up']  = a5_ask
        pairs.at[idx_pair, 'bid_5m_up']  = a5_bid
        pairs.at[idx_pair, 'ask_15m_dn'] = a15_dn_ask
        pairs.at[idx_pair, 'bid_15m_dn'] = a15_dn_bid

    del asset_books

# ── Save raw pairs ─────────────────────────────────────────────────────────────
out_pairs = f'{OUTDIR}/cross_tf_arb_pairs_2026_06_05.parquet'
pairs.to_parquet(out_pairs, index=False)
print(f"\nSaved pairs to {out_pairs}")

# ── PnL helper ─────────────────────────────────────────────────────────────────
def pnl_07(entry_price, won, notional=NOTIONAL):
    """Winner-only 0.07 curve. entry_price = ask we paid."""
    shares = notional / entry_price
    if won:
        return shares * (1 - entry_price) * (1 - FEE_RATE * entry_price)
    else:
        return -shares * entry_price  # = -notional

def bootstrap_ci(values, n=N_BOOT, alpha=0.05, seed=SEED):
    """Bootstrap mean CI."""
    rng = np.random.default_rng(seed)
    vals = np.array(values)
    if len(vals) == 0:
        return np.nan, np.nan, np.nan
    means = [rng.choice(vals, len(vals), replace=True).mean() for _ in range(n)]
    return np.mean(vals), np.percentile(means, 100*alpha/2), np.percentile(means, 100*(1-alpha/2))

# ── SIGNAL A: Oracle-lag / determinism test ───────────────────────────────────
# When |g_bp| > K, the 15m outcome is nearly determined.
# If 15m-Up ask is still < threshold, buy it.
print("\n=== SIGNAL A: Oracle-lag / determinism (15m) ===")
print("At t=T+10m, if gap g=P(T+10)-P(T) is large and the 15m-Up token lags...\n")

# Signal A: g_bp > K (price moved up strongly) AND ask_15m_up < ask_threshold
# => buy 15m-Up, expect to win (outcome_15m should be Up)
# We test multiple K thresholds; ask threshold is the natural "fair" level

def signal_a_results(df, g_thresh_bp, side='up', max_ask=0.92):
    """
    side='up': g_bp > g_thresh_bp => 15m-Up should win, buy ask_15m_up < max_ask
    side='dn': g_bp < -g_thresh_bp => 15m-Down should win
    """
    valid = df.dropna(subset=['ask_15m_up', 'ask_15m_dn', 'g_bp', 'outcome_15m'])
    if side == 'up':
        fires = valid[(valid['g_bp'] > g_thresh_bp) & (valid['ask_15m_up'] < max_ask)]
        fires = fires.copy()
        fires['won'] = (fires['outcome_15m'] == 'Up')
        fires['entry'] = fires['ask_15m_up']
    else:
        fires = valid[(valid['g_bp'] < -g_thresh_bp) & (valid['ask_15m_dn'] < max_ask)]
        fires = fires.copy()
        fires['won'] = (fires['outcome_15m'] == 'Down')
        fires['entry'] = fires['ask_15m_dn']
    if len(fires) == 0:
        return None
    fires['pnl'] = fires.apply(lambda r: pnl_07(r['entry'], r['won']), axis=1)
    mean_pnl, ci_lo, ci_hi = bootstrap_ci(fires['pnl'].values)
    wr = fires['won'].mean()
    return {
        'side': side,
        'g_thresh_bp': g_thresh_bp,
        'n': len(fires),
        'wr': wr,
        'mean_entry': fires['entry'].mean(),
        'pnl_mean': mean_pnl,
        'ci_lo': ci_lo,
        'ci_hi': ci_hi,
        'expected_fair_pnl': wr * (NOTIONAL/fires['entry'].mean()) * (1 - fires['entry'].mean()) - (1-wr) * NOTIONAL,
    }

rows_a = []
for asset in ASSETS + ['ALL']:
    df_ = pairs if asset == 'ALL' else pairs[pairs['asset'] == asset]
    for K in [5, 10, 20, 30, 50, 80, 100]:
        for side in ['up', 'dn']:
            r = signal_a_results(df_, K, side=side)
            if r and r['n'] >= 10:
                r['asset'] = asset
                rows_a.append(r)

sig_a = pd.DataFrame(rows_a)
if len(sig_a) > 0:
    cols = ['asset', 'side', 'g_thresh_bp', 'n', 'wr', 'mean_entry', 'pnl_mean', 'ci_lo', 'ci_hi']
    print(sig_a[cols].to_string(index=False, float_format=lambda x: f'{x:.3f}'))

# ── SIGNAL B: Cross-market consistency / relative-value ───────────────────────
# When g>0 (price rose), 15m-Up bar is lower (P(T)) => should be more likely to win.
# Rational: 15m_up_price should be >= 5m_up_price when g>0.
# Anomaly: 15m_up_ask < 5m_up_bid (inverted) => buy 15m-Up cheap.
# Also: when g<0, 5m-Up easier => 5m_up_price > 15m_up_price expected.
print("\n=== SIGNAL B: Cross-market consistency (relative-value) ===")
print("Buy whichever is mispriced given known gap g\n")

def signal_b_results(df, min_gap_bp=5.0, inversion_thresh=0.02):
    """
    When g_bp > min_gap_bp:  15m-Up should be >= 5m-Up.
      Anomaly: ask_15m_up < bid_5m_up - inversion_thresh => buy 15m-Up
    When g_bp < -min_gap_bp: 5m-Up should be >= 15m-Up.
      Anomaly: ask_5m_up < bid_15m_up - inversion_thresh => buy 5m-Up
    """
    valid = df.dropna(subset=['ask_15m_up', 'bid_15m_up', 'ask_5m_up', 'bid_5m_up',
                               'g_bp', 'outcome_15m', 'outcome_5m'])
    fire_rows = []

    # Case 1: g>0, 15m easier, but 15m_ask < 5m_bid (15m cheaper than it should be)
    c1 = valid[(valid['g_bp'] > min_gap_bp) &
               (valid['ask_15m_up'] < valid['bid_5m_up'] - inversion_thresh)]
    for _, r in c1.iterrows():
        won = (r['outcome_15m'] == 'Up')
        pnl = pnl_07(r['ask_15m_up'], won)
        fire_rows.append({
            'case': 'g>0_buy_15m', 'asset': r['asset'],
            'g_bp': r['g_bp'], 'entry': r['ask_15m_up'],
            'inversion': r['bid_5m_up'] - r['ask_15m_up'],
            'won': won, 'pnl': pnl,
            'slug': r['slug_15m'],
        })

    # Case 2: g<0, 5m easier, but 5m_ask < 15m_bid (5m cheaper than it should be)
    c2 = valid[(valid['g_bp'] < -min_gap_bp) &
               (valid['ask_5m_up'] < valid['bid_15m_up'] - inversion_thresh)]
    for _, r in c2.iterrows():
        won = (r['outcome_5m'] == 'Up')
        pnl = pnl_07(r['ask_5m_up'], won)
        fire_rows.append({
            'case': 'g<0_buy_5m', 'asset': r['asset'],
            'g_bp': r['g_bp'], 'entry': r['ask_5m_up'],
            'inversion': r['bid_15m_up'] - r['ask_5m_up'],
            'won': won, 'pnl': pnl,
            'slug': r['slug_5m'],
        })

    return pd.DataFrame(fire_rows)

rows_b = []
for min_gap in [5, 10, 20]:
    for inv_thr in [0.0, 0.01, 0.02, 0.05]:
        fb = signal_b_results(pairs, min_gap_bp=min_gap, inversion_thresh=inv_thr)
        if len(fb) >= 5:
            mean_pnl, ci_lo, ci_hi = bootstrap_ci(fb['pnl'].values)
            rows_b.append({
                'min_gap_bp': min_gap,
                'inversion_thr': inv_thr,
                'n': len(fb),
                'n_c1': (fb['case']=='g>0_buy_15m').sum(),
                'n_c2': (fb['case']=='g<0_buy_5m').sum(),
                'wr': fb['won'].mean(),
                'mean_entry': fb['entry'].mean(),
                'pnl_mean': mean_pnl,
                'ci_lo': ci_lo,
                'ci_hi': ci_hi,
            })

sig_b = pd.DataFrame(rows_b)
if len(sig_b) > 0:
    cols = ['min_gap_bp', 'inversion_thr', 'n', 'n_c1', 'n_c2', 'wr', 'mean_entry', 'pnl_mean', 'ci_lo', 'ci_hi']
    print(sig_b[cols].to_string(index=False, float_format=lambda x: f'{x:.3f}'))
else:
    print("No signal B fires found.")

# ── SIGNAL C: Implied-probability consistency check ───────────────────────────
# Given g and the typical 5m-window vol, we can compute what the 15m-Up price
# SHOULD be if the 5m-Up price is rational (and vice versa).
# Simpler version: given g_bp, define "g_normalized" = g / (typical_5m_std_bp).
# If g_normalized > z, 15m-Up rational price ~ N(z, 1) CDF = high.
# Test if actual 15m_ask < rational_price - slack.
print("\n=== SIGNAL C: Implied-prob consistency (normalized gap) ===\n")

# Estimate 5m-window std from data
from scipy import stats as sp_stats

def signal_c_results(df, slack=0.05, min_gap_sigma=1.5):
    """
    Normalize g by asset's empirical 5m-window std.
    If g_sigma > min_gap_sigma, 15m-Up rational_prob > 0.93.
    Buy if ask_15m_up < rational_prob - slack.
    """
    results = []
    for asset in ASSETS:
        adf = df[df['asset'] == asset].dropna(subset=['g_bp', 'ask_15m_up', 'outcome_15m'])
        if len(adf) < 20:
            continue
        # use p_T10 - p_T from chainlink (g) as the 5m-window move
        # estimate std of g in bp
        g_std = adf['g_bp'].std()
        if g_std <= 0:
            continue
        adf = adf.copy()
        adf['g_sigma'] = adf['g_bp'] / g_std

        # rational 15m-Up prob = P(X > 0 | X ~ N(g_sigma, 1)) where X is final move in sigma units
        # i.e., P(Z > -g_sigma) = 1 - N(-g_sigma) = N(g_sigma) ... assuming random walk from T+10
        # But this ignores mean reversion / drift. Simple: N(g_sigma) is an upper bound.
        adf['rational_15m_up'] = sp_stats.norm.cdf(adf['g_sigma'])

        # fire: rational > 0.5 + min_gap_sigma*0.15 and ask_15m_up < rational - slack
        # just use g_sigma > min_gap_sigma as filter
        fires = adf[(adf['g_sigma'].abs() > min_gap_sigma)].copy()

        # For g_sigma > 0: buy 15m-Up
        up_fires = fires[fires['g_sigma'] > min_gap_sigma].copy()
        up_fires['won'] = (up_fires['outcome_15m'] == 'Up')
        up_fires['entry'] = up_fires['ask_15m_up']
        up_fires = up_fires.dropna(subset=['entry'])
        up_fires = up_fires[up_fires['entry'] < up_fires['rational_15m_up'] - slack]

        # For g_sigma < -min_gap_sigma: buy 15m-Down
        dn_fires = fires[fires['g_sigma'] < -min_gap_sigma].copy()
        if 'ask_15m_dn' in dn_fires.columns:
            dn_fires['won'] = (dn_fires['outcome_15m'] == 'Down')
            dn_fires['entry'] = dn_fires['ask_15m_dn']
            dn_fires = dn_fires.dropna(subset=['entry'])
            dn_fires = dn_fires[dn_fires['entry'] < (1 - dn_fires['rational_15m_up']) - slack]
        else:
            dn_fires = pd.DataFrame()

        all_fires = pd.concat([up_fires.assign(side='up'), dn_fires.assign(side='dn')], ignore_index=True)
        if len(all_fires) == 0:
            continue

        all_fires['pnl'] = all_fires.apply(lambda r: pnl_07(r['entry'], r['won']), axis=1)
        mean_pnl, ci_lo, ci_hi = bootstrap_ci(all_fires['pnl'].values)
        results.append({
            'asset': asset,
            'g_std_bp': g_std,
            'min_gap_sigma': min_gap_sigma,
            'slack': slack,
            'n': len(all_fires),
            'wr': all_fires['won'].mean(),
            'mean_entry': all_fires['entry'].mean(),
            'pnl_mean': mean_pnl,
            'ci_lo': ci_lo,
            'ci_hi': ci_hi,
        })
    return pd.DataFrame(results)

try:
    from scipy import stats as sp_stats
    rows_c = []
    for sigma in [1.0, 1.5, 2.0, 2.5]:
        for slack in [0.03, 0.05, 0.08]:
            rc = signal_c_results(pairs, slack=slack, min_gap_sigma=sigma)
            if len(rc):
                rows_c.append(rc)
    sig_c = pd.concat(rows_c, ignore_index=True) if rows_c else pd.DataFrame()
    if len(sig_c) > 0:
        cols = ['asset', 'g_std_bp', 'min_gap_sigma', 'slack', 'n', 'wr', 'mean_entry', 'pnl_mean', 'ci_lo', 'ci_hi']
        print(sig_c[cols].to_string(index=False, float_format=lambda x: f'{x:.3f}'))
    else:
        print("No signal C fires.")
except ImportError:
    print("scipy not available; skipping signal C")

# ── Descriptive stats on pricing gap ──────────────────────────────────────────
print("\n=== Descriptive: How 15m-Up and 5m-Up prices compare given g ===\n")
valid = pairs.dropna(subset=['ask_15m_up','ask_5m_up','g_bp','outcome_15m','outcome_5m'])
print(f"Valid pairs with both books: {len(valid)} / {len(pairs)}")
print(f"\nCorrelation ask_15m_up vs ask_5m_up: {valid['ask_15m_up'].corr(valid['ask_5m_up']):.3f}")
print(f"Mean ask_15m_up: {valid['ask_15m_up'].mean():.3f}  Mean ask_5m_up: {valid['ask_5m_up'].mean():.3f}")
print(f"\nWhen g_bp > 20:  n={( valid['g_bp']>20).sum()}  15m_ask={(valid.loc[valid['g_bp']>20,'ask_15m_up'].mean()):.3f}  5m_ask={(valid.loc[valid['g_bp']>20,'ask_5m_up'].mean()):.3f}")
print(f"When g_bp < -20: n={(valid['g_bp']<-20).sum()}  15m_ask={(valid.loc[valid['g_bp']<-20,'ask_15m_up'].mean()):.3f}  5m_ask={(valid.loc[valid['g_bp']<-20,'ask_5m_up'].mean()):.3f}")

# 15m outcome given g_bp bucket
print("\n15m-Up win rate by g_bp bucket:")
valid_up = valid.copy()
valid_up['g_bucket'] = pd.cut(valid_up['g_bp'], bins=[-np.inf,-50,-20,-5,5,20,50,np.inf],
                               labels=['<-50','-50:-20','-20:-5','-5:5','5:20','20:50','>50'])
bucket_stats = valid_up.groupby('g_bucket', observed=True).agg(
    n=('outcome_15m','count'),
    wr_15m_up=('outcome_15m', lambda x: (x=='Up').mean()),
    wr_5m_up=('outcome_5m', lambda x: (x=='Up').mean()),
    mean_ask_15m=('ask_15m_up','mean'),
    mean_ask_5m=('ask_5m_up','mean'),
).round(3)
print(bucket_stats.to_string())

# ── Save results ───────────────────────────────────────────────────────────────
out_sig_a = f'{OUTDIR}/cross_tf_sig_a_2026_06_05.parquet'
out_sig_b = f'{OUTDIR}/cross_tf_sig_b_2026_06_05.parquet'
if len(sig_a) > 0:
    sig_a.to_parquet(out_sig_a, index=False)
    print(f"\nSaved signal A to {out_sig_a}")
if len(sig_b) > 0:
    sig_b.to_parquet(out_sig_b, index=False)
    print(f"Saved signal B to {out_sig_b}")

print("\n=== DONE ===")
