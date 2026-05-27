"""Smoking-gun test: is the 11.6x step-up explained by fire-count inflation?

Strategy: take S7_BTC_5m_base sleeve. Filter to fire_offset_s in {60,120,180,240}
(matching base panel cadence) on BOTH val and lockbox. Compare per-day PnL.
"""
import pandas as pd
import numpy as np
import sys
sys.path.insert(0, "data/v4/canonical")

mp = pd.read_parquet("data/v4/canonical/_results/master_gate_features_v2.parquet")
mp['day'] = pd.to_datetime(mp.fire_us/1e6, unit='s').dt.date
mp['split'] = np.where(mp.day < pd.Timestamp('2026-05-15').date(), 'train',
              np.where(mp.day < pd.Timestamp('2026-05-22').date(), 'val', 'lockbox'))

# Get S7 sleeve slice
s = mp[(mp.asset=='BTC') & (mp.tf=='5m') & (mp.sleeve_id.astype(str).str.startswith('s15_5m'))].copy()
s = s.drop_duplicates(['slug','fire_us','direction'])

# Count offsets present in val vs lockbox
print("=== TASK: Offset density analysis ===")
print("Val offsets:")
print(s[s.split=='val'].fire_offset_s.value_counts().sort_index().to_string())
print()
print("Lockbox offsets:")
print(s[s.split=='lockbox'].fire_offset_s.value_counts().sort_index().to_string())
print()

# Standard offsets that exist in both (matching base panel cadence)
common_offsets = [60, 120, 180, 240]
print(f"\n=== Restricted to common offsets {common_offsets} ===")
s_common = s[s.fire_offset_s.isin(common_offsets)].copy()

# Apply hybrid_v1 AND gates (s15_5m gates)
hybrid_v1_gates_s7 = ["g_tr_stack_with","g_tr_above_ema800","g_ribbon_agrees","g_tight_ribbon","g_stoch_with","g_tr_above_ema200"]
def apply_v1(df, gates):
    mask = pd.Series(True, index=df.index)
    for g in gates:
        if g in df.columns:
            mask &= df[g].fillna(0).astype(bool)
        else:
            mask &= False
    return df[mask]

print("\n=== hybrid_v1 AND, common offsets only ===")
for split in ['val','lockbox']:
    sub = s_common[s_common.split==split]
    sub_v1 = apply_v1(sub, hybrid_v1_gates_s7)
    days = 7 if split=='val' else 4
    sum_pnl = sub_v1.pnl_legacy_usd.sum()
    print(f"{split}: n={len(sub_v1)}, n_universe={len(sub)}, sum_pnl=${sum_pnl:.0f}, dpt=${sub_v1.pnl_legacy_usd.mean():.3f}, WR={sub_v1.won_int.mean():.3f}")
    print(f"  $/day: ${sum_pnl/days:.0f}, fires/day: {len(sub_v1)/days:.0f}")
print()

print("\n=== FULL universe (no offset filter), hybrid_v1 AND ===")
for split in ['val','lockbox']:
    sub = s[s.split==split]
    sub_v1 = apply_v1(sub, hybrid_v1_gates_s7)
    days = 7 if split=='val' else 4
    sum_pnl = sub_v1.pnl_legacy_usd.sum()
    print(f"{split}: n={len(sub_v1)}, n_universe={len(sub)}, sum_pnl=${sum_pnl:.0f}, dpt=${sub_v1.pnl_legacy_usd.mean():.3f}, WR={sub_v1.won_int.mean():.3f}")
    print(f"  $/day: ${sum_pnl/days:.0f}, fires/day: {len(sub_v1)/days:.0f}")

# Apples-to-apples PER-SLUG metric: max 1 fire per (slug, direction) — pick first offset
print("\n=== Per-(slug,direction): keep first offset (apples-to-apples) ===")
for split in ['val','lockbox']:
    sub = s[s.split==split].sort_values('fire_offset_s').drop_duplicates(['slug','direction'], keep='first')
    sub_v1 = apply_v1(sub, hybrid_v1_gates_s7)
    days = 7 if split=='val' else 4
    sum_pnl = sub_v1.pnl_legacy_usd.sum()
    print(f"{split}: n={len(sub_v1)}, n_universe={len(sub)}, sum_pnl=${sum_pnl:.0f}, dpt=${sub_v1.pnl_legacy_usd.mean():.3f}, WR={sub_v1.won_int.mean():.3f}")
    print(f"  $/day: ${sum_pnl/days:.0f}")
