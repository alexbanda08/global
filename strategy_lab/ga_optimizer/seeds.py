"""
Known-good seed individuals derived from the manual fade-scan winners
(DEPLOYMENT_FINAL.md). GA polishes from these instead of starting from random.

Hour-mask encoding: bit i = 1 means hour i is active. 24-bit int.
DOW-mask: bit i = 1 means day i is active. Mon=0..Sun=6. 7-bit int.
"""

DOW_ALL = 0b1111111      # Mon-Sun
DOW_WEEKDAY = 0b0011111  # Mon-Fri
DOW_WEEKEND = 0b1100000

# Hour masks
ALL_HOURS = (1 << 24) - 1                 # 0-23
ACTIVE_HOURS = 0; ACTIVE_HOURS = sum(1 << h for h in range(6, 24))   # 06-23 UTC
NIGHT_HOURS = sum(1 << h for h in range(0, 6))                       # 00-05
EU_MORNING = sum(1 << h for h in range(6, 12))                       # 06-11
US_AFTERNOON = sum(1 << h for h in range(12, 18))                    # 12-17
US_EVENING = sum(1 << h for h in range(18, 23))                      # 18-22 (excl 23)


# Phenotype: a complete individual dict
def momo_5m_seeds():
    return [
        # Production-style: fire same direction as ret_2m, no time/vwap filters
        dict(ret_2m_threshold_bp=5.0, direction_mode="same", spread_max=0.02,
             vwap_lo=0.05, vwap_hi=0.95, hour_mask=ALL_HOURS, dow_mask=DOW_ALL,
             sigma_window_min=30, notional_usd=25.0),
        # SOL momo KEEP-style (best live performer): tight params, all hours
        dict(ret_2m_threshold_bp=10.0, direction_mode="same", spread_max=0.025,
             vwap_lo=0.10, vwap_hi=0.90, hour_mask=ALL_HOURS, dow_mask=DOW_ALL,
             sigma_window_min=30, notional_usd=25.0),
        # BTC momo DOWN @ 18-22 UTC FADE (top fade alpha): direction_mode=fade,
        # restrict to US evening weekdays
        dict(ret_2m_threshold_bp=10.0, direction_mode="fade", spread_max=0.02,
             vwap_lo=0.30, vwap_hi=0.70, hour_mask=US_EVENING, dow_mask=DOW_WEEKDAY,
             sigma_window_min=30, notional_usd=25.0),
        # Active-hours + weekday + medium ret threshold
        dict(ret_2m_threshold_bp=8.0, direction_mode="same", spread_max=0.02,
             vwap_lo=0.30, vwap_hi=0.70, hour_mask=ACTIVE_HOURS, dow_mask=DOW_WEEKDAY,
             sigma_window_min=30, notional_usd=25.0),
    ]


def momo_15m_seeds():
    return [
        dict(ret_2m_threshold_bp=5.0, direction_mode="same", spread_max=0.02,
             vwap_lo=0.05, vwap_hi=0.95, hour_mask=ALL_HOURS, dow_mask=DOW_ALL,
             sigma_window_min=30, notional_usd=25.0),
        # ETH momo DOWN @ 12-17 UTC FADE
        dict(ret_2m_threshold_bp=10.0, direction_mode="fade", spread_max=0.02,
             vwap_lo=0.30, vwap_hi=0.70, hour_mask=US_AFTERNOON, dow_mask=DOW_WEEKDAY,
             sigma_window_min=30, notional_usd=25.0),
        # volume_INV_NIGHT UP @ 06-11 UTC FADE (the strongest Bonferroni cut)
        dict(ret_2m_threshold_bp=8.0, direction_mode="fade", spread_max=0.02,
             vwap_lo=0.20, vwap_hi=0.80, hour_mask=EU_MORNING, dow_mask=DOW_ALL,
             sigma_window_min=30, notional_usd=25.0),
    ]


def mispricing_15m_seeds():
    return [
        dict(edge_threshold=0.08, anchor_offset_s=300, obs_horizon_s=600,
             vwap_lo=0.30, vwap_hi=0.70, hour_mask=ALL_HOURS, dow_mask=DOW_ALL,
             sigma_window_min=30, fair_p_z_scale=2.0, notional_usd=25.0),
        dict(edge_threshold=0.08, anchor_offset_s=300, obs_horizon_s=600,
             vwap_lo=0.40, vwap_hi=0.60, hour_mask=ACTIVE_HOURS,
             dow_mask=DOW_WEEKDAY, sigma_window_min=30, fair_p_z_scale=2.0,
             notional_usd=25.0),
    ]


SEEDS = {
    "momo_5m":        momo_5m_seeds,
    "momo_15m":       momo_15m_seeds,
    "mispricing_15m": mispricing_15m_seeds,
}
