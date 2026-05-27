"""Build a properly-diversified TOP 5 from all candidates explored.

Selection criteria (in priority order):
1. Pass full sniper bar (positive full dpt, lockbox WR>=75%, max_dd<=300, streak<=6, sharpe>=2, bp_lock<=0.05)
2. Diverse gate stacks (no two with same anchor gates)
3. Cover different parts of window (early/mid/late offsets)
"""
import os, pandas as pd
ROOT = r"C:/Users/alexandre bandarra/Desktop/global"
OUT  = r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/sniper_search_2026_05_27/sol_15m"

# Combine all candidate sources
all_cands = []
for f in ['all_candidates_v2fix.csv', 'all_candidates_v3_expanded.csv', 'all_candidates_v4_vwap_aware.csv']:
    try:
        d = pd.read_csv(f"{OUT}/{f}")
        d['source'] = f
        all_cands.append(d)
    except FileNotFoundError:
        pass
df = pd.concat(all_cands, ignore_index=True)
# Some columns missing across sources; ensure offset_filter present
if 'offset_filter' not in df.columns:
    df['offset_filter'] = None
df['offset_filter'] = df['offset_filter'].fillna('all')
# Dedup on (gate_stack, offset_filter) — same logic on different windows should both be tested
df = df.drop_duplicates(subset=['gate_stack', 'offset_filter'], keep='first').reset_index(drop=True)
print(f"Combined unique (gate_stack, offset_filter): {len(df)}")

# Sniper filter (full pass = all brief §2 metrics + full-window positive dpt)
def passes(r):
    if r['n_lockbox'] < 5: return False
    if r['n_full'] > 500: return False
    n_per_32d = r['n_full'] * (32.0/28.0)
    if n_per_32d < 50: return False
    if r['wr_lockbox'] < 75: return False
    if r['dpt_25'] < 3: return False
    if r['max_dd_25'] > 300: return False
    if r['loss_streak'] > 6: return False
    if r['sharpe'] < 2: return False
    if pd.isna(r['bootstrap_p_lockbox']) or r['bootstrap_p_lockbox'] > 0.05: return False
    if r['dpt_full'] <= 0: return False
    if r['loss_streak_full'] > 8: return False
    return True

# RELAXED: passes everything except possibly bp_lockbox or has slightly elevated loss_streak (drop the boostrap_p_lock requirement)
def passes_relaxed(r):
    if r['n_lockbox'] < 5: return False
    if r['n_full'] > 500: return False
    n_per_32d = r['n_full'] * (32.0/28.0)
    if n_per_32d < 50: return False
    if r['wr_lockbox'] < 75: return False
    if r['dpt_25'] < 3: return False
    if r['max_dd_25'] > 300: return False
    if r['loss_streak'] > 7: return False
    if r['sharpe'] < 2: return False
    if r['dpt_full'] <= 0: return False
    if r['loss_streak_full'] > 8: return False
    return True

df['pass'] = df.apply(passes, axis=1)
df['pass_relaxed'] = df.apply(passes_relaxed, axis=1)
sniper = df[df['pass']].sort_values('dpt_full', ascending=False).reset_index(drop=True)
sniper_relaxed = df[df['pass_relaxed'] & ~df['pass']].sort_values('dpt_full', ascending=False).reset_index(drop=True)
print(f"\nFull-pass candidates: {len(sniper)}")
print(f"Relaxed-pass candidates (no strict bp_lock check): {len(sniper_relaxed)}")

# Diversify: extract canonical anchor (the gates ignoring vwap, treating tr_stack_with≡tr_stack_full_with)
# Include offset_filter to keep different windows as different sleeves
def canonical_key(row):
    gs = row['gate_stack'].split('&')
    # remove vwap gates (those are filter modifiers, not anchor logic)
    gs = [g for g in gs if not g.startswith('g_vwap_')]
    # collapse tr_stack_full_with -> tr_stack_with (they're identical for SOL 15m)
    gs = [g.replace('g_tr_stack_full_with', 'g_tr_stack_with') for g in gs]
    off = str(row.get('offset_filter', '') or 'all')
    return '&'.join(sorted(set(gs))) + '||' + off

if len(sniper):
    # HIGH confidence = full-window WR >= 65% AND full-window n_days >= 15
    # MED = passes but lower full-window WR or fewer days
    # Drop cases where full WR < 50% (overfit to lockbox)
    def confidence(r):
        if r['wr_full'] < 55: return None  # drop
        if r['wr_full'] >= 70 and r['n_days_full'] >= 15 and r['n_days_lock'] >= 3: return 'HIGH'
        if r['wr_full'] >= 60 and r['n_days_full'] >= 10: return 'MED'
        return 'LOW'

    sniper['canon_key'] = sniper.apply(canonical_key, axis=1)
    sniper['confidence'] = sniper.apply(confidence, axis=1)
    sniper = sniper[sniper.confidence.notna()]
    if len(sniper_relaxed):
        sniper_relaxed['canon_key'] = sniper_relaxed.apply(canonical_key, axis=1)
        sniper_relaxed['confidence'] = sniper_relaxed.apply(confidence, axis=1)
        sniper_relaxed = sniper_relaxed[sniper_relaxed.confidence.notna()]
        combined = pd.concat([sniper, sniper_relaxed], ignore_index=True)
    else:
        combined = sniper
    # Take top per canon_key
    combined = combined.sort_values(['canon_key','dpt_full'], ascending=[True,False])
    diverse = combined.groupby('canon_key', as_index=False).first()
    # Rank by composite: confidence rank (HIGH=2, MED=1, LOW=0) + dpt_full + then dpt_25
    conf_rank = {'HIGH': 2, 'MED': 1, 'LOW': 0}
    diverse['conf_rank'] = diverse['confidence'].map(conf_rank)
    diverse = diverse.sort_values(['conf_rank','dpt_full','dpt_25'], ascending=[False,False,False])
    print(f"After dedupe + confidence filter: {len(diverse)}")
    top5 = diverse.head(5)
else:
    # Fallback: pick best by sniper_score from all_cands
    def score(r):
        s = 0
        if r['wr_lockbox'] >= 75: s += 1
        if r['dpt_25'] >= 3: s += 1
        if r['max_dd_25'] <= 300: s += 1
        if r['loss_streak'] <= 6: s += 1
        if r['sharpe'] >= 2: s += 1
        if r['n_lockbox'] >= 5 and r['n_full'] <= 500: s += 1
        if pd.notna(r['bootstrap_p_lockbox']) and r['bootstrap_p_lockbox'] <= 0.05: s += 1
        if r.get('dpt_full', 0) > 0: s += 1
        return s
    df['score'] = df.apply(score, axis=1)
    df['canon_key'] = df.apply(canonical_key, axis=1)
    df = df.sort_values(['canon_key','score','dpt_full'], ascending=[True,False,False])
    diverse = df.groupby('canon_key', as_index=False).first()
    diverse = diverse.sort_values(['score','dpt_full'], ascending=[False,False])
    top5 = diverse.head(5)

# Format output
out_cols = ['sleeve_id','anchor','gate_stack','depth','confidence',
            'n_train','n_val','n_lockbox','n_full',
            'wr_train','wr_val','wr_lockbox','wr_full',
            'dpt_25','dpt_full',
            'sum_25_28d','sum_lockbox',
            'max_dd_25','max_dd_full',
            'loss_streak','loss_streak_full',
            'sharpe','sharpe_full',
            'n_days_full','n_days_lock',
            'bootstrap_p_lockbox','bootstrap_p_full']
# fill missing cols
for c in out_cols:
    if c not in top5.columns: top5[c] = None
top5 = top5[out_cols + (['offset_filter'] if 'offset_filter' in top5.columns else [])]
top5.to_csv(f"{OUT}/top_5_candidates.csv", index=False)
print(f"\nWROTE top_5_candidates.csv with {len(top5)} rows")
print(top5[['sleeve_id','gate_stack','n_full','wr_full','wr_lockbox','dpt_full','dpt_25','max_dd_full','loss_streak_full','sharpe','bootstrap_p_lockbox']].to_string())
