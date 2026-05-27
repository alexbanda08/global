"""Quantify the regime panel lookahead leak.

Regime panel rows have ts_us = slot_start, but features (close, ADX, regime_label)
are computed over the FULL slot [slot_start, slot_start+5min]. When merged with
merge_asof backward, fires inside the slot see features computed with future data.

Test: compare regime_label / regime_score / ADX from the CURRENT (leaky) bar vs
the PRIOR bar (causal) for fires. If they differ a lot, the leak is significant.
"""
import pandas as pd
import numpy as np

mp = pd.read_parquet("data/v4/canonical/_results/master_gate_features_v2.parquet")
rp = pd.read_parquet("data/v4/canonical/_results/regime_panel_5m.parquet")

# Focus on BTC 5m
mp_btc = mp[(mp.asset=='BTC') & (mp.tf=='5m')].drop_duplicates(['slug','fire_us','direction']).copy()
mp_btc['slot_start_us'] = (mp_btc.fire_us // 300_000_000) * 300_000_000
mp_btc['fire_offset_s'] = (mp_btc.fire_us - mp_btc.slot_start_us)/1e6

# Now compute CAUSAL regime by looking at the PRIOR bar (ts_us = slot_start - 300s)
rp_btc = rp[rp.asset=='BTC'].sort_values('ts_us').reset_index(drop=True)
# Index by ts_us for fast lookup
rp_idx = {int(ts): i for i,ts in enumerate(rp_btc.ts_us)}

leaky_vals = []
causal_vals = []
for _,row in mp_btc.head(1000).iterrows():
    slot = int(row.slot_start_us)
    prior = slot - 300_000_000
    leaky_i = rp_idx.get(slot)
    causal_i = rp_idx.get(prior)
    if leaky_i is not None and causal_i is not None:
        leaky_vals.append({
            "adx14": rp_btc.iloc[leaky_i].adx_14,
            "regime_label": rp_btc.iloc[leaky_i].regime_label,
            "regime_score": rp_btc.iloc[leaky_i].regime_score,
            "stack": rp_btc.iloc[leaky_i].tr_ema_stack_score,
        })
        causal_vals.append({
            "adx14": rp_btc.iloc[causal_i].adx_14,
            "regime_label": rp_btc.iloc[causal_i].regime_label,
            "regime_score": rp_btc.iloc[causal_i].regime_score,
            "stack": rp_btc.iloc[causal_i].tr_ema_stack_score,
        })

lv = pd.DataFrame(leaky_vals)
cv = pd.DataFrame(causal_vals)
print(f"N samples: {len(lv)}")
print()
print("Disagreement rate on regime_label (leaky vs causal):")
print(f"  {(lv.regime_label != cv.regime_label).mean()*100:.1f}% disagree")
print()
print("Correlation adx14 (leaky, causal):", lv.adx14.corr(cv.adx14))
print("Mean diff adx14:", (lv.adx14 - cv.adx14).abs().mean())
print()
print("Correlation regime_score (leaky, causal):", lv.regime_score.corr(cv.regime_score))
print()
print("Crosstab regime_label leaky vs causal:")
print(pd.crosstab(lv.regime_label, cv.regime_label, margins=True).to_string())

# Now: does the LEAK favor predictability? compare WR of using leaky vs causal regime
# WR by leaky regime_label
fired = mp_btc.head(1000).copy().reset_index(drop=True).iloc[:len(lv)]
fired['leaky_regime'] = lv.regime_label.values
fired['causal_regime'] = cv.regime_label.values
print()
print("WR by leaky_regime:")
print(fired.groupby('leaky_regime').won_int.agg(['mean','count']).to_string())
print()
print("WR by causal_regime:")
print(fired.groupby('causal_regime').won_int.agg(['mean','count']).to_string())
