"""Phase 35 — 16 sniper-v5 sleeve definitions (spec §4 + §5 table).

Each entry binds an (asset, tf, direction, offsets, spread_filter, gates)
tuple to a unique sleeve_id. The controller (Plan 35-13) iterates this
list and dispatches per-sleeve evaluation at slot_start_us + offset_s
boundaries.

Source of truth: SHADOW_DEPLOY_SPEC_2026_05_27.md §4 + §5.

Per CONTEXT.md `### 16 sleeves`:
    - All 16 sleeves paper_only at deploy
    - Sleeve 06 is UP-only (operator monitors first-30-fires WR;
      auto-suspend <80%)
    - Sleeve 16 has notional_usd_override = $5 (exploratory full-window
      edge, kept small)
    - Sleeve 01 has s6_precondition = True (requires existing S6
      production sleeve fire on same slug)

Per CONTEXT.md Deferred §3: g_book_depth_supports_250 IS exported but
demoted to no-op tier (>$150 floor); only sleeve 06 uses
g_depth_250_strict for the original strict $1500/$750 thresholds.

Per CONTEXT.md Deferred §4: g_cci_strong_with NOT exported from
sniper_v5_gates and intentionally not consumed by any sleeve here.

Per CLAUDE.md inv #4: gates are pure; controller fires them BEFORE
the signal placement.

Per CLAUDE.md inv #13: no Storedata reads — all data flows through
TV-native panels passed in by the controller at runtime.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from backend.app.strategies.polymarket.sniper_v5_gates import (
    # V6 / V7 / V8 extension (2026-05-27) gates
    g_2asset_either_trending_with,
    # Phase 35 (V5) gates already in use
    g_a2_hl_short_cascade,
    g_above_1h_dailyvwap_with,
    g_b1_poly_flow_aligned,
    g_b2_poly_flow_contrarian,
    g_b2_poly_flow_NOT_opposing,
    g_b3_poly_flow_abs,
    g_bb_pos_with,
    g_BTC_adx_strong,
    g_btc_eth_divergence,
    g_btc_f7_against,
    g_btc_f7_with,
    g_BTC_slope_strong_with,
    g_BTC_slope_with,
    g_BTC_tr_stack,
    g_btc_trend_30m_with,
    g_BTC_vol_low,
    g_cci_extreme_with,
    g_cci_strong_with,
    g_cci_with,
    g_cross_asset_lag_confluence,
    g_depth_250_strict,
    g_dir_down,
    g_dir_up,
    g_entry_vwap_in_30_70,
    g_entry_vwap_in_band,
    g_entry_vwap_in_band_narrow,
    g_f7_rsi_with,
    g_f7_v7_overbought,
    g_grandparent_trend_with,
    g_hawkes_imb_loose_with,
    g_hod_european_morning,
    g_hod_us_afternoon,
    g_hurst_mp_trend_with,
    g_hurst_regime_with,
    g_hurst_reverting,
    g_hurst_trending,
    g_imb5_strong_with,
    g_J_btc_eth_vol_both_low,
    g_L_ETH_grandparent_adx_strong,
    g_mfi_strong_with,
    g_mfi_with,
    g_mp_no_extreme,
    g_mp_no_extreme_150,
    g_mp_skew_strong_with,
    g_mp_skew_with,
    g_not_us_close_hours,
    g_off_60_240,
    g_offset_early,
    g_oracle_lag_bps_ge,
    g_oracle_lag_with,
    g_parent15m_ranging,
    g_parent_15m_not_ranging,
    g_parent_15m_slope_with,
    g_pw_btc_15m_trend_with,
    g_pw_sol_15m_trend_with,
    g_pw_trend_slope_with,
    g_q_prev15m_agrees,
    g_regime_ranging_at_ws,
    g_regime_stack_with,
    g_rf_aged,
    g_rf_strict_align,
    g_rf_with,
    g_ribbon_agrees,
    g_ribbon_slope_with,
    g_slot_end_ofi_with,
    g_sms_liq_reclaim_with,
    g_sms_no_liquidity_above,
    g_stoch_with,
    g_tight_ribbon,
    g_tod_europe_us_window,
    g_top_depth_ge_median,
    g_tr_above_cloud,
    g_tr_above_ema50,
    g_tr_above_ema200,
    g_tr_above_ema800,
    g_tr_above_pp,
    g_tr_in_active_session,
    g_tr_partial_stack_with,
    g_tr_stack_full_with,
    g_tr_stack_with,
    g_trend_slope_strong_with,
    g_trend_slope_with,
    g_vol_contracting,
    g_vol_high,
    g_vwap_in_45_85,
    g_vwap_in_55_80,
    g_vwap_premium,
    g_xa_3source_trend_with,
)


@dataclass(frozen=True, slots=True)
class GateRef:
    """Static binding of a gate callable + literal kwargs.

    Runtime kwargs (panel handles, slug, token_ids, book_mirror,
    slot_start_us) are injected by the controller — they don't belong in
    the static sleeve definition.

    `name` is the audit string for shadow_log §7 `gates_evaluated` dict.
    """

    gate: Callable[..., bool]
    kwargs: tuple[tuple[str, str], ...]
    name: str

    def bound_kwargs(self) -> dict[str, str]:
        return dict(self.kwargs)


@dataclass(frozen=True, slots=True)
class SniperV5Sleeve:
    """Static descriptor for one sleeve out of the 16 in spec §4."""

    sleeve_id: str
    asset: str           # "BTC" | "ETH" | "SOL"
    tf: str              # "5m" | "15m"
    direction: str       # "BOTH" | "UP" | "DOWN"
    offsets: tuple[int, ...]
    spread_filter: Decimal
    gates: tuple[GateRef, ...]
    notional_usd_override: Decimal | None = None  # only sleeve 16 ($5)
    s6_precondition: bool = False                 # only sleeve 01
    # Exit policy (SHADOW_DEPLOY_SPEC_SLEEVE_H_HEDGELATE_2026_05_27.md).
    # "HOLD"       = hold to slot_end → oracle resolution (all 56 base sleeves).
    # "HEDGE_LATE" = at slot_end - lead_s, if the held side's sell-vwap is
    #                deep underwater (< fill_vwap × loss_ratio), cut early;
    #                else fall through to normal resolution.
    exit_policy: str = "HOLD"
    hedge_late_loss_ratio: float = 0.70
    hedge_late_check_lead_s: int = 60
    # fast_taker (TV_AGENT_SPEC_FAST_TAKER_SHADOW_AB_2026_05_29) — oracle-lag
    # directional-taker A/B sleeves. Default-valued so the existing roster is
    # unaffected (every current sleeve fires each offset, no merge book).
    #   merge_mimic=True       → Config A: route TAKE through the controller's
    #     per-slug FIFO matched-pair book; recycle collateral at $1/pair (gas 0)
    #     and hold the directional residual to chainlink resolution.
    #   one_shot_per_slug=True → Config B: fire ONCE per slug on the first
    #     qualifying early offset; later offsets for that slug are suppressed.
    merge_mimic: bool = False
    one_shot_per_slug: bool = False
    # FAST_TAKER_LAGV2 (TV_AGENT_SPEC_FAST_TAKER_LAGV2_2026_05_29) — the
    # LAG_REVERSAL_STOP exit (exit_policy="LAG_REVERSAL_STOP"): cut early iff
    # binance reverses >= reversal_stop_bps against the entry direction, polled
    # every reversal_poll_s until slot_end. Default-valued → existing roster
    # unaffected.
    reversal_stop_bps: float = 10.0
    reversal_poll_s: int = 5


# -----------------------------------------------------------------
# Per-asset spread filters (spec §0)
# -----------------------------------------------------------------

_SPREAD_BTC = Decimal("0.02")
_SPREAD_ETH = Decimal("0.02")
_SPREAD_SOL = Decimal("0.025")
# FAST_TAKER_LAGV2 (2026-05-29) — deliberately LOOSE: the lag edge lives in
# DISLOCATED wide books; tightening is INVERSE (backtested dead end). Do NOT
# lower this to the 0.02 sniper default.
_SPREAD_LAGV2 = Decimal("0.05")

# VL — spread-loose variants (SHADOW_DEPLOY_SPEC_V9_AND_VL_2026_05_27.md §4).
# Asset-conditional loosening: ETH was 0.020 → 0.025; SOL 15m was 0.025 → 0.030.
# BTC 5m + SOL 5m DEGRADE when loosened (per spec §7 caveat 2) — no VL variants
# for those asset/tfs.
_SPREAD_VL_ETH = Decimal("0.025")
_SPREAD_VL_SOL_15M = Decimal("0.030")


# -----------------------------------------------------------------
# 16 sleeves — verbatim from spec §4 + CONTEXT.md "### 16 sleeves" table
# Ordering MUST match CONTEXT.md table (tests assert exact equality)
# -----------------------------------------------------------------

SNIPER_V5_SLEEVES: Final[tuple[SniperV5Sleeve, ...]] = (
    # 01 — BTC 5m BOTH offsets=30 + S6 precondition
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_btc_5m_ts_mpskew_s6_0_60",
        asset="BTC", tf="5m", direction="BOTH",
        offsets=(30,),
        spread_filter=_SPREAD_BTC,
        s6_precondition=True,
        gates=(
            GateRef(
                g_trend_slope_strong_with,
                (("asset", "BTC"), ("tf", "5m")),
                "g_trend_slope_strong_with(BTC,5m)",
            ),
            GateRef(g_mp_skew_with, (), "g_mp_skew_with"),
        ),
    ),
    # 02 — BTC 5m BOTH offsets=30
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_btc_5m_ts_mpskew_any_off30",
        asset="BTC", tf="5m", direction="BOTH",
        offsets=(30,),
        spread_filter=_SPREAD_BTC,
        gates=(
            GateRef(
                g_trend_slope_strong_with,
                (("asset", "BTC"), ("tf", "5m")),
                "g_trend_slope_strong_with(BTC,5m)",
            ),
            GateRef(g_mp_skew_with, (), "g_mp_skew_with"),
        ),
    ),
    # 03 — ETH 5m BOTH offsets=120
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_eth_5m_tr200_mp_sms_active_off120",
        asset="ETH", tf="5m", direction="BOTH",
        offsets=(120,),
        spread_filter=_SPREAD_ETH,
        gates=(
            GateRef(g_tr_above_ema200, (("asset", "ETH"),), "g_tr_above_ema200(ETH)"),
            GateRef(g_mp_skew_with, (), "g_mp_skew_with"),
            GateRef(
                g_sms_liq_reclaim_with,
                (("asset", "ETH"), ("tf", "5m")),
                "g_sms_liq_reclaim_with(ETH,5m)",
            ),
            GateRef(
                g_tr_in_active_session,
                (("asset", "ETH"),),
                "g_tr_in_active_session(ETH)",
            ),
        ),
    ),
    # 04 — ETH 5m BOTH offsets=120
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_eth_5m_tr200_mp_mpnx_sms_off120",
        asset="ETH", tf="5m", direction="BOTH",
        offsets=(120,),
        spread_filter=_SPREAD_ETH,
        gates=(
            GateRef(g_tr_above_ema200, (("asset", "ETH"),), "g_tr_above_ema200(ETH)"),
            GateRef(g_mp_skew_with, (), "g_mp_skew_with"),
            GateRef(g_mp_no_extreme, (), "g_mp_no_extreme"),
            GateRef(
                g_sms_liq_reclaim_with,
                (("asset", "ETH"), ("tf", "5m")),
                "g_sms_liq_reclaim_with(ETH,5m)",
            ),
        ),
    ),
    # 05 — ETH 5m BOTH offsets=120
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_eth_5m_cloud_mp_sms_active_off120",
        asset="ETH", tf="5m", direction="BOTH",
        offsets=(120,),
        spread_filter=_SPREAD_ETH,
        gates=(
            GateRef(g_tr_above_cloud, (("asset", "ETH"),), "g_tr_above_cloud(ETH)"),
            GateRef(g_mp_skew_with, (), "g_mp_skew_with"),
            GateRef(
                g_sms_liq_reclaim_with,
                (("asset", "ETH"), ("tf", "5m")),
                "g_sms_liq_reclaim_with(ETH,5m)",
            ),
            GateRef(
                g_tr_in_active_session,
                (("asset", "ETH"),),
                "g_tr_in_active_session(ETH)",
            ),
        ),
    ),
    # 06 — SOL 5m UP-ONLY offsets=30,60,90 (strict depth, sleeve 06 special case)
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_sol_5m_depth_up_hod_session",
        asset="SOL", tf="5m", direction="UP",
        offsets=(30, 60, 90),
        spread_filter=_SPREAD_SOL,
        gates=(
            GateRef(g_depth_250_strict, (), "g_depth_250_strict"),
            GateRef(g_dir_up, (), "g_dir_up"),
            GateRef(g_hod_us_afternoon, (), "g_hod_us_afternoon"),
            GateRef(
                g_tr_in_active_session,
                (("asset", "SOL"),),
                "g_tr_in_active_session(SOL)",
            ),
        ),
    ),
    # 07 — SOL 5m BOTH offsets=90,120,150,180
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_sol_5m_rf_tr_pp_mid",
        asset="SOL", tf="5m", direction="BOTH",
        offsets=(90, 120, 150, 180),
        spread_filter=_SPREAD_SOL,
        gates=(
            GateRef(g_rf_strict_align, (("asset", "SOL"),), "g_rf_strict_align(SOL)"),
            GateRef(g_tr_above_ema200, (("asset", "SOL"),), "g_tr_above_ema200(SOL)"),
            GateRef(g_tr_above_pp, (("asset", "SOL"),), "g_tr_above_pp(SOL)"),
            GateRef(
                g_tr_partial_stack_with,
                (("asset", "SOL"),),
                "g_tr_partial_stack_with(SOL)",
            ),
        ),
    ),
    # 08 — SOL 5m BOTH offsets=90,120,150,180
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_sol_5m_rf_tr_partial_mid",
        asset="SOL", tf="5m", direction="BOTH",
        offsets=(90, 120, 150, 180),
        spread_filter=_SPREAD_SOL,
        gates=(
            GateRef(g_rf_strict_align, (("asset", "SOL"),), "g_rf_strict_align(SOL)"),
            GateRef(
                g_tr_partial_stack_with,
                (("asset", "SOL"),),
                "g_tr_partial_stack_with(SOL)",
            ),
        ),
    ),
    # 09 — BTC 15m DOWN-ONLY offsets=600
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_btc_15m_ts_trstack_off600_down",
        asset="BTC", tf="15m", direction="DOWN",
        offsets=(600,),
        spread_filter=_SPREAD_BTC,
        gates=(
            GateRef(g_dir_down, (), "g_dir_down"),
            GateRef(g_tr_stack_full_with, (("asset", "BTC"),), "g_tr_stack_full_with(BTC)"),
            GateRef(
                g_trend_slope_with,
                (("asset", "BTC"), ("tf", "15m")),
                "g_trend_slope_with(BTC,15m)",
            ),
        ),
    ),
    # 10 — BTC 15m UP-ONLY offsets=480
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_btc_15m_regime_trstack_off480_up",
        asset="BTC", tf="15m", direction="UP",
        offsets=(480,),
        spread_filter=_SPREAD_BTC,
        gates=(
            GateRef(g_dir_up, (), "g_dir_up"),
            GateRef(
                g_regime_stack_with,
                (("asset", "BTC"), ("tf", "15m")),
                "g_regime_stack_with(BTC,15m)",
            ),
            GateRef(g_tr_stack_full_with, (("asset", "BTC"),), "g_tr_stack_full_with(BTC)"),
        ),
    ),
    # 11 — BTC 15m DOWN-ONLY offsets=600
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_btc_15m_mpskew_trstack_off600_down",
        asset="BTC", tf="15m", direction="DOWN",
        offsets=(600,),
        spread_filter=_SPREAD_BTC,
        gates=(
            GateRef(g_dir_down, (), "g_dir_down"),
            GateRef(g_mp_skew_strong_with, (), "g_mp_skew_strong_with"),
            GateRef(g_tr_stack_full_with, (("asset", "BTC"),), "g_tr_stack_full_with(BTC)"),
        ),
    ),
    # 12 — BTC 15m DOWN-ONLY offsets=600
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_btc_15m_ema50_ema800_off600_down",
        asset="BTC", tf="15m", direction="DOWN",
        offsets=(600,),
        spread_filter=_SPREAD_BTC,
        gates=(
            GateRef(g_dir_down, (), "g_dir_down"),
            GateRef(g_tr_above_ema50, (("asset", "BTC"),), "g_tr_above_ema50(BTC)"),
            GateRef(g_tr_above_ema800, (("asset", "BTC"),), "g_tr_above_ema800(BTC)"),
        ),
    ),
    # 13 — ETH 15m BOTH offsets=0,30,60
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_eth_15m_trstack_vwap_vol_offearly",
        asset="ETH", tf="15m", direction="BOTH",
        offsets=(0, 30, 60),
        spread_filter=_SPREAD_ETH,
        gates=(
            GateRef(g_tr_stack_full_with, (("asset", "ETH"),), "g_tr_stack_full_with(ETH)"),
            GateRef(
                g_above_1h_dailyvwap_with,
                (("asset", "ETH"),),
                "g_above_1h_dailyvwap_with(ETH)",
            ),
            GateRef(g_offset_early, (), "g_offset_early"),
            GateRef(
                g_vol_high,
                (("asset", "ETH"), ("tf", "15m")),
                "g_vol_high(ETH,15m)",
            ),
        ),
    ),
    # 14 — ETH 15m BOTH offsets=0,30,60
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_eth_15m_trstack_vwap_offearly",
        asset="ETH", tf="15m", direction="BOTH",
        offsets=(0, 30, 60),
        spread_filter=_SPREAD_ETH,
        gates=(
            GateRef(g_tr_stack_full_with, (("asset", "ETH"),), "g_tr_stack_full_with(ETH)"),
            GateRef(g_offset_early, (), "g_offset_early"),
            GateRef(
                g_above_1h_dailyvwap_with,
                (("asset", "ETH"),),
                "g_above_1h_dailyvwap_with(ETH)",
            ),
        ),
    ),
    # 15 — SOL 15m BOTH offsets=120,180,240
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_sol_15m_trstack_vol_ribbon_ema_mid",
        asset="SOL", tf="15m", direction="BOTH",
        offsets=(120, 180, 240),
        spread_filter=_SPREAD_SOL,
        gates=(
            GateRef(g_tr_stack_full_with, (("asset", "SOL"),), "g_tr_stack_full_with(SOL)"),
            GateRef(
                g_vol_high,
                (("asset", "SOL"), ("tf", "15m")),
                "g_vol_high(SOL,15m)",
            ),
            GateRef(g_ribbon_agrees, (("asset", "SOL"),), "g_ribbon_agrees(SOL)"),
            GateRef(g_tr_above_ema200, (("asset", "SOL"),), "g_tr_above_ema200(SOL)"),
            GateRef(g_tr_above_ema800, (("asset", "SOL"),), "g_tr_above_ema800(SOL)"),
        ),
    ),
    # 16 — SOL 15m BOTH offsets=480,600,720,840 + $5 override (exploratory full-window edge)
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_sol_15m_rfaged_trstack_late",
        asset="SOL", tf="15m", direction="BOTH",
        offsets=(480, 600, 720, 840),
        spread_filter=_SPREAD_SOL,
        notional_usd_override=Decimal("5.0"),
        gates=(
            GateRef(g_rf_aged, (("asset", "SOL"),), "g_rf_aged(SOL)"),
            GateRef(g_tr_stack_full_with, (("asset", "SOL"),), "g_tr_stack_full_with(SOL)"),
            GateRef(g_tr_stack_with, (("asset", "SOL"),), "g_tr_stack_with(SOL)"),
        ),
    ),
    # -----------------------------------------------------------------
    # V6 (14 sleeves) — SHADOW_DEPLOY_SPEC_V6_SELECTED_2026_05_27.md §4
    # -----------------------------------------------------------------
    # V6_01 — ETH 5m BOTH offset=60 — cloud + ribbon + mp + hurst
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_eth_5m_cloud_ribbon_mp_hurst_v6",
        asset="ETH", tf="5m", direction="BOTH",
        offsets=(60,),
        spread_filter=_SPREAD_ETH,
        gates=(
            GateRef(g_tr_above_cloud, (("asset", "ETH"),), "g_tr_above_cloud(ETH)"),
            GateRef(g_ribbon_agrees, (("asset", "ETH"),), "g_ribbon_agrees(ETH)"),
            GateRef(g_mp_skew_with, (), "g_mp_skew_with"),
            GateRef(g_hurst_trending, (("asset", "ETH"), ("tf", "5m")), "g_hurst_trending(ETH,5m)"),
        ),
    ),
    # V6_02 — ETH 5m BOTH offset=120 — V5 replication (tr200 + mp + sms + active)
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_eth_5m_v5repl_off120_v6",
        asset="ETH", tf="5m", direction="BOTH",
        offsets=(120,),
        spread_filter=_SPREAD_ETH,
        gates=(
            GateRef(g_tr_above_ema200, (("asset", "ETH"),), "g_tr_above_ema200(ETH)"),
            GateRef(g_mp_skew_with, (), "g_mp_skew_with"),
            GateRef(g_sms_liq_reclaim_with, (("asset", "ETH"), ("tf", "5m")), "g_sms_liq_reclaim_with(ETH,5m)"),
            GateRef(g_tr_in_active_session, (("asset", "ETH"),), "g_tr_in_active_session(ETH)"),
        ),
    ),
    # V6_03 — ETH 5m BOTH offset=60 — bb + mp + hurst + entry vwap band [0.20,0.80]
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_eth_5m_bb_mp_hurst_band_v6",
        asset="ETH", tf="5m", direction="BOTH",
        offsets=(60,),
        spread_filter=_SPREAD_ETH,
        gates=(
            GateRef(g_bb_pos_with, (("asset", "ETH"),), "g_bb_pos_with(ETH)"),
            GateRef(g_mp_skew_with, (), "g_mp_skew_with"),
            GateRef(g_hurst_trending, (("asset", "ETH"), ("tf", "5m")), "g_hurst_trending(ETH,5m)"),
            GateRef(g_entry_vwap_in_band, (), "g_entry_vwap_in_band"),
        ),
    ),
    # V6_04 — SOL 5m BOTH offsets 30..240 — CCI strong + F7 + MFI + partial stack + VWAP 45..85
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_sol_5m_cci_f7_mfi_partial_vwap_v6",
        asset="SOL", tf="5m", direction="BOTH",
        offsets=(30, 60, 90, 120, 150, 180, 210, 240),
        spread_filter=_SPREAD_SOL,
        gates=(
            GateRef(g_cci_strong_with, (("asset", "SOL"),), "g_cci_strong_with(SOL)"),
            GateRef(g_f7_rsi_with, (("asset", "SOL"),), "g_f7_rsi_with(SOL)"),
            GateRef(g_mfi_with, (("asset", "SOL"),), "g_mfi_with(SOL)"),
            GateRef(g_tr_partial_stack_with, (("asset", "SOL"),), "g_tr_partial_stack_with(SOL)"),
            GateRef(g_vwap_in_45_85, (), "g_vwap_in_45_85"),
        ),
    ),
    # V6_05 — SOL 5m BOTH offsets 30..240 — F7 + mp_no_extreme_150 + ema200 + VWAP 55..80
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_sol_5m_f7_mp_ema200_vwap_v6",
        asset="SOL", tf="5m", direction="BOTH",
        offsets=(30, 60, 90, 120, 150, 180, 210, 240),
        spread_filter=_SPREAD_SOL,
        gates=(
            GateRef(g_f7_rsi_with, (("asset", "SOL"),), "g_f7_rsi_with(SOL)"),
            GateRef(g_mp_no_extreme_150, (), "g_mp_no_extreme_150"),
            GateRef(g_tr_above_ema200, (("asset", "SOL"),), "g_tr_above_ema200(SOL)"),
            GateRef(g_vwap_in_55_80, (), "g_vwap_in_55_80"),
        ),
    ),
    # V6_06 — SOL 5m BOTH offsets 30..240 — F7 + MFI + ema200 + VWAP 55..80
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_sol_5m_f7_mfi_ema200_vwap_v6",
        asset="SOL", tf="5m", direction="BOTH",
        offsets=(30, 60, 90, 120, 150, 180, 210, 240),
        spread_filter=_SPREAD_SOL,
        gates=(
            GateRef(g_f7_rsi_with, (("asset", "SOL"),), "g_f7_rsi_with(SOL)"),
            GateRef(g_mfi_with, (("asset", "SOL"),), "g_mfi_with(SOL)"),
            GateRef(g_tr_above_ema200, (("asset", "SOL"),), "g_tr_above_ema200(SOL)"),
            GateRef(g_vwap_in_55_80, (), "g_vwap_in_55_80"),
        ),
    ),
    # V6_07 — ETH 15m BOTH offsets {0,30,60} — trstack_full + 1h_vwap + offset_early + vol_high + vwap 30..70
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_eth_15m_trstack_vwap_vol_offearly_band_v6",
        asset="ETH", tf="15m", direction="BOTH",
        offsets=(0, 30, 60),
        spread_filter=_SPREAD_ETH,
        gates=(
            GateRef(g_tr_stack_full_with, (("asset", "ETH"),), "g_tr_stack_full_with(ETH)"),
            GateRef(g_above_1h_dailyvwap_with, (("asset", "ETH"),), "g_above_1h_dailyvwap_with(ETH)"),
            GateRef(g_offset_early, (), "g_offset_early"),
            GateRef(g_vol_high, (("asset", "ETH"), ("tf", "15m")), "g_vol_high(ETH,15m)"),
            GateRef(g_entry_vwap_in_30_70, (), "g_entry_vwap_in_30_70"),
        ),
    ),
    # V6_08 — ETH 15m BOTH offsets {0,30,60} — pre-window trend_slope + V6_07 stack
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_eth_15m_pw_trendslope_trstack_offearly_v6",
        asset="ETH", tf="15m", direction="BOTH",
        offsets=(0, 30, 60),
        spread_filter=_SPREAD_ETH,
        gates=(
            GateRef(g_tr_stack_full_with, (("asset", "ETH"),), "g_tr_stack_full_with(ETH)"),
            GateRef(g_above_1h_dailyvwap_with, (("asset", "ETH"),), "g_above_1h_dailyvwap_with(ETH)"),
            GateRef(g_offset_early, (), "g_offset_early"),
            GateRef(g_vol_high, (("asset", "ETH"), ("tf", "15m")), "g_vol_high(ETH,15m)"),
            GateRef(g_pw_trend_slope_with, (("asset", "ETH"), ("tf", "15m")), "g_pw_trend_slope_with(ETH,15m)"),
        ),
    ),
    # V6_09 — BTC 15m BOTH offset 600 — vwap premium + ema50 + mp_skew
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_btc_15m_vwapprem_ema50_mpskew_off600_v6",
        asset="BTC", tf="15m", direction="BOTH",
        offsets=(600,),
        spread_filter=_SPREAD_BTC,
        gates=(
            GateRef(g_vwap_premium, (), "g_vwap_premium"),
            GateRef(g_tr_above_ema50, (("asset", "BTC"),), "g_tr_above_ema50(BTC)"),
            GateRef(g_mp_skew_with, (), "g_mp_skew_with"),
        ),
    ),
    # V6_10 — BTC 15m DOWN-ONLY offset 600 — ema200 + mp_skew_strong + rf (DOWN)
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_btc_15m_ema200_mpskew_rf_off600_down_v6",
        asset="BTC", tf="15m", direction="DOWN",
        offsets=(600,),
        spread_filter=_SPREAD_BTC,
        gates=(
            GateRef(g_dir_down, (), "g_dir_down"),
            GateRef(g_tr_above_ema200, (("asset", "BTC"),), "g_tr_above_ema200(BTC)"),
            GateRef(g_mp_skew_strong_with, (), "g_mp_skew_strong_with"),
            GateRef(g_rf_with, (("asset", "BTC"),), "g_rf_with(BTC)"),
        ),
    ),
    # V6_11 — BTC 15m BOTH offset 840 — ema800 + ribbon_slope + hawkes (borderline)
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_btc_15m_ema800_ribslp_hawkes_off840_v6",
        asset="BTC", tf="15m", direction="BOTH",
        offsets=(840,),
        spread_filter=_SPREAD_BTC,
        gates=(
            GateRef(g_tr_above_ema800, (("asset", "BTC"),), "g_tr_above_ema800(BTC)"),
            GateRef(g_ribbon_slope_with, (("asset", "BTC"),), "g_ribbon_slope_with(BTC)"),
            GateRef(g_hawkes_imb_loose_with, (("asset", "BTC"),), "g_hawkes_imb_loose_with(BTC)"),
        ),
    ),
    # V6_12 — SOL 15m BOTH offsets {60,120,240} — HOD EU + off_60_240 + RF + tr_stack + VWAP < 0.80 (premium)
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_sol_15m_hod_eu_off60_240_rf_tr_vwap80_v6",
        asset="SOL", tf="15m", direction="BOTH",
        offsets=(60, 120, 240),
        spread_filter=_SPREAD_SOL,
        gates=(
            GateRef(g_hod_european_morning, (), "g_hod_european_morning"),
            GateRef(g_off_60_240, (), "g_off_60_240"),
            GateRef(g_rf_with, (("asset", "SOL"),), "g_rf_with(SOL)"),
            GateRef(g_tr_stack_with, (("asset", "SOL"),), "g_tr_stack_with(SOL)"),
            GateRef(g_vwap_premium, (), "g_vwap_premium"),
        ),
    ),
    # V6_13 — SOL 15m BOTH offsets {60,120,240} — HOD EU + off_60_240 + RF + tr_stack + VWAP [0.30,0.70]
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_sol_15m_hod_eu_off60_240_rf_tr_vwap30_70_v6",
        asset="SOL", tf="15m", direction="BOTH",
        offsets=(60, 120, 240),
        spread_filter=_SPREAD_SOL,
        gates=(
            GateRef(g_hod_european_morning, (), "g_hod_european_morning"),
            GateRef(g_off_60_240, (), "g_off_60_240"),
            GateRef(g_rf_with, (("asset", "SOL"),), "g_rf_with(SOL)"),
            GateRef(g_tr_stack_with, (("asset", "SOL"),), "g_tr_stack_with(SOL)"),
            GateRef(g_entry_vwap_in_30_70, (), "g_entry_vwap_in_30_70"),
        ),
    ),
    # V6_14 — SOL 15m BOTH offsets ALL — HOD EU + tight ribbon + RF + tr_stack + VWAP premium @ $5 stake
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_sol_15m_hod_eu_tightrib_rf_tr_vwap80_v6",
        asset="SOL", tf="15m", direction="BOTH",
        offsets=(60, 120, 180, 240, 300, 360, 480, 600, 720, 840),
        spread_filter=_SPREAD_SOL,
        notional_usd_override=Decimal("5.0"),
        gates=(
            GateRef(g_hod_european_morning, (), "g_hod_european_morning"),
            GateRef(g_rf_with, (("asset", "SOL"),), "g_rf_with(SOL)"),
            GateRef(g_tight_ribbon, (("asset", "SOL"),), "g_tight_ribbon(SOL)"),
            GateRef(g_tr_stack_with, (("asset", "SOL"),), "g_tr_stack_with(SOL)"),
            GateRef(g_vwap_premium, (), "g_vwap_premium"),
        ),
    ),
    # -----------------------------------------------------------------
    # V7 (12 sleeves) — SHADOW_DEPLOY_SPEC_V7_SELECTED_2026_05_27.md §4
    # -----------------------------------------------------------------
    # V7_01 — BTC 5m BOTH offsets ALL — parent_15m slope + ts_strong + mp_no_extreme
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_btc_5m_parent15m_slope_ts_mpnx_v7",
        asset="BTC", tf="5m", direction="BOTH",
        offsets=(30, 60, 90, 120, 150, 180, 210, 240, 270),
        spread_filter=_SPREAD_BTC,
        gates=(
            GateRef(g_parent_15m_slope_with, (("asset", "BTC"),), "g_parent_15m_slope_with(BTC)"),
            GateRef(g_trend_slope_strong_with, (("asset", "BTC"), ("tf", "5m")), "g_trend_slope_strong_with(BTC,5m)"),
            GateRef(g_mp_no_extreme, (), "g_mp_no_extreme"),
        ),
    ),
    # V7_02 — BTC 5m BOTH late offsets {240,270} — slot_end OFI (STUB) + ts_strong  ⚠ EXPERIMENTAL
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_btc_5m_slotend_ofi_ts_v7",
        asset="BTC", tf="5m", direction="BOTH",
        offsets=(240, 270),
        spread_filter=_SPREAD_BTC,
        gates=(
            GateRef(g_slot_end_ofi_with, (), "g_slot_end_ofi_with"),
            GateRef(g_trend_slope_strong_with, (("asset", "BTC"), ("tf", "5m")), "g_trend_slope_strong_with(BTC,5m)"),
        ),
    ),
    # V7_03 — BTC 5m BOTH offsets ALL — parent_15m not_ranging + ts_strong + mp_skew
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_btc_5m_parent15m_notrang_ts_mpskew_v7",
        asset="BTC", tf="5m", direction="BOTH",
        offsets=(30, 60, 90, 120, 150, 180, 210, 240, 270),
        spread_filter=_SPREAD_BTC,
        gates=(
            GateRef(g_parent_15m_not_ranging, (("asset", "BTC"),), "g_parent_15m_not_ranging(BTC)"),
            GateRef(g_trend_slope_strong_with, (("asset", "BTC"), ("tf", "5m")), "g_trend_slope_strong_with(BTC,5m)"),
            GateRef(g_mp_skew_with, (), "g_mp_skew_with"),
        ),
    ),
    # V7_04 — ETH 5m BOTH offset 60 — cloud + entry vwap band + hurst+mp combo
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_eth_5m_cloud_vwap_hurstmp_v7",
        asset="ETH", tf="5m", direction="BOTH",
        offsets=(60,),
        spread_filter=_SPREAD_ETH,
        gates=(
            GateRef(g_tr_above_cloud, (("asset", "ETH"),), "g_tr_above_cloud(ETH)"),
            GateRef(g_entry_vwap_in_band, (), "g_entry_vwap_in_band"),
            GateRef(g_hurst_mp_trend_with, (("asset", "ETH"),), "g_hurst_mp_trend_with(ETH)"),
        ),
    ),
    # V7_05 — ETH 5m BOTH offset 60 — ema50 + hurst_trending + parent_15m ranging
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_eth_5m_ema50_hurst_parent15mrang_v7",
        asset="ETH", tf="5m", direction="BOTH",
        offsets=(60,),
        spread_filter=_SPREAD_ETH,
        gates=(
            GateRef(g_tr_above_ema50, (("asset", "ETH"),), "g_tr_above_ema50(ETH)"),
            GateRef(g_hurst_trending, (("asset", "ETH"), ("tf", "5m")), "g_hurst_trending(ETH,5m)"),
            GateRef(g_parent15m_ranging, (("asset", "ETH"),), "g_parent15m_ranging(ETH)"),
        ),
    ),
    # V7_06 — ETH 5m BOTH offset 60 — V6_03 base + parent_15m ranging
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_eth_5m_v6c3_parent15mrang_v7",
        asset="ETH", tf="5m", direction="BOTH",
        offsets=(60,),
        spread_filter=_SPREAD_ETH,
        gates=(
            GateRef(g_tr_above_cloud, (("asset", "ETH"),), "g_tr_above_cloud(ETH)"),
            GateRef(g_ribbon_agrees, (("asset", "ETH"),), "g_ribbon_agrees(ETH)"),
            GateRef(g_mp_skew_with, (), "g_mp_skew_with"),
            GateRef(g_hurst_trending, (("asset", "ETH"), ("tf", "5m")), "g_hurst_trending(ETH,5m)"),
            GateRef(g_parent15m_ranging, (("asset", "ETH"),), "g_parent15m_ranging(ETH)"),
        ),
    ),
    # V7_07 — ETH 5m BOTH offset 90 — ema200 + entry vwap + regime_ranging@ws_s + xa_3source
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_eth_5m_ema200_vwap_regimerang_xa3_v7",
        asset="ETH", tf="5m", direction="BOTH",
        offsets=(90,),
        spread_filter=_SPREAD_ETH,
        gates=(
            GateRef(g_tr_above_ema200, (("asset", "ETH"),), "g_tr_above_ema200(ETH)"),
            GateRef(g_entry_vwap_in_band, (), "g_entry_vwap_in_band"),
            GateRef(g_regime_ranging_at_ws, (("asset", "ETH"),), "g_regime_ranging_at_ws(ETH)"),
            GateRef(g_xa_3source_trend_with, (), "g_xa_3source_trend_with"),
        ),
    ),
    # V7_08 — SOL 5m BOTH offsets ALL — BTC trend 30m + CCI extreme + hurst reverting
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_sol_5m_btctrend_cci_hurstrev_v7",
        asset="SOL", tf="5m", direction="BOTH",
        offsets=(30, 60, 90, 120, 150, 180, 210, 240),
        spread_filter=_SPREAD_SOL,
        gates=(
            GateRef(g_btc_trend_30m_with, (), "g_btc_trend_30m_with"),
            GateRef(g_cci_extreme_with, (("asset", "SOL"),), "g_cci_extreme_with(SOL)"),
            GateRef(g_hurst_reverting, (("asset", "SOL"), ("tf", "5m")), "g_hurst_reverting(SOL,5m)"),
        ),
    ),
    # V7_09 — SOL 5m BOTH offsets ALL — BTC F7 + SOL F7 overbought + ema800 + VWAP [0.45,0.85]  ⚠ EXPERIMENTAL
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_sol_5m_btcf7_f7overb_ema800_vwap_v7",
        asset="SOL", tf="5m", direction="BOTH",
        offsets=(30, 60, 90, 120, 150, 180, 210, 240),
        spread_filter=_SPREAD_SOL,
        gates=(
            GateRef(g_btc_f7_with, (), "g_btc_f7_with"),
            GateRef(g_f7_v7_overbought, (("asset", "SOL"),), "g_f7_v7_overbought(SOL)"),
            GateRef(g_tr_above_ema800, (("asset", "SOL"),), "g_tr_above_ema800(SOL)"),
            GateRef(g_vwap_in_45_85, (), "g_vwap_in_45_85"),
        ),
    ),
    # V7_10 — ETH 15m BOTH offsets {0,30,60} — V6_08 base + pw_btc_15m_trend
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_eth_15m_pi_btc15m_trend_v7",
        asset="ETH", tf="15m", direction="BOTH",
        offsets=(0, 30, 60),
        spread_filter=_SPREAD_ETH,
        gates=(
            GateRef(g_tr_stack_full_with, (("asset", "ETH"),), "g_tr_stack_full_with(ETH)"),
            GateRef(g_above_1h_dailyvwap_with, (("asset", "ETH"),), "g_above_1h_dailyvwap_with(ETH)"),
            GateRef(g_offset_early, (), "g_offset_early"),
            GateRef(g_vol_high, (("asset", "ETH"), ("tf", "15m")), "g_vol_high(ETH,15m)"),
            GateRef(g_pw_btc_15m_trend_with, (), "g_pw_btc_15m_trend_with"),
        ),
    ),
    # V7_11 — SOL 15m BOTH offsets {60,120,240} — V6_12 base + BTC slope + BTC slope strong
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_sol_15m_btc_slope_pair_v7",
        asset="SOL", tf="15m", direction="BOTH",
        offsets=(60, 120, 240),
        spread_filter=_SPREAD_SOL,
        gates=(
            GateRef(g_hod_european_morning, (), "g_hod_european_morning"),
            GateRef(g_off_60_240, (), "g_off_60_240"),
            GateRef(g_rf_with, (("asset", "SOL"),), "g_rf_with(SOL)"),
            GateRef(g_tr_stack_with, (("asset", "SOL"),), "g_tr_stack_with(SOL)"),
            GateRef(g_vwap_premium, (), "g_vwap_premium"),
            GateRef(g_BTC_slope_with, (), "g_BTC_slope_with"),
            GateRef(g_BTC_slope_strong_with, (), "g_BTC_slope_strong_with"),
        ),
    ),
    # V7_12 — SOL 15m BOTH offsets {60,120,240} — V6_12 base + BTC tr_stack + ADX strong + vol low
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_sol_15m_btc_adx_btcvollow_v7",
        asset="SOL", tf="15m", direction="BOTH",
        offsets=(60, 120, 240),
        spread_filter=_SPREAD_SOL,
        gates=(
            GateRef(g_hod_european_morning, (), "g_hod_european_morning"),
            GateRef(g_off_60_240, (), "g_off_60_240"),
            GateRef(g_rf_with, (("asset", "SOL"),), "g_rf_with(SOL)"),
            GateRef(g_tr_stack_with, (("asset", "SOL"),), "g_tr_stack_with(SOL)"),
            GateRef(g_vwap_premium, (), "g_vwap_premium"),
            GateRef(g_BTC_tr_stack, (), "g_BTC_tr_stack"),
            GateRef(g_BTC_adx_strong, (), "g_BTC_adx_strong"),
            GateRef(g_BTC_vol_low, (), "g_BTC_vol_low"),
        ),
    ),
    # -----------------------------------------------------------------
    # V8 (14 sleeves) — SHADOW_DEPLOY_SPEC_UNIFIED_V6_V7_V8_2026_05_27.md §4
    # -----------------------------------------------------------------
    # V8_01 — BTC 5m BOTH offsets ALL — 1h RF + imb5 strong + RF
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_btc_5m_l_1hrf_imb5_rf_v8",
        asset="BTC", tf="5m", direction="BOTH",
        offsets=(30, 60, 90, 120, 150, 180, 210, 240, 270),
        spread_filter=_SPREAD_BTC,
        gates=(
            GateRef(g_grandparent_trend_with, (("asset", "BTC"),), "g_grandparent_trend_with(BTC)"),
            GateRef(g_imb5_strong_with, (), "g_imb5_strong_with"),
            GateRef(g_rf_with, (("asset", "BTC"),), "g_rf_with(BTC)"),
        ),
    ),
    # V8_02 — BTC 5m BOTH offsets ALL — 1h grandparent trend + imb5 strong + ribbon
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_btc_5m_l_1hrf_imb5_ribbon_v8",
        asset="BTC", tf="5m", direction="BOTH",
        offsets=(30, 60, 90, 120, 150, 180, 210, 240, 270),
        spread_filter=_SPREAD_BTC,
        gates=(
            GateRef(g_grandparent_trend_with, (("asset", "BTC"),), "g_grandparent_trend_with(BTC)"),
            GateRef(g_imb5_strong_with, (), "g_imb5_strong_with"),
            GateRef(g_ribbon_agrees, (("asset", "BTC"),), "g_ribbon_agrees(BTC)"),
        ),
    ),
    # V8_03 — BTC 5m BOTH offsets ALL — parent 15m slope + ts strong + imb5 strong
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_btc_5m_q_parent15mslope_ts_imb5_v8",
        asset="BTC", tf="5m", direction="BOTH",
        offsets=(30, 60, 90, 120, 150, 180, 210, 240, 270),
        spread_filter=_SPREAD_BTC,
        gates=(
            GateRef(g_parent_15m_slope_with, (("asset", "BTC"),), "g_parent_15m_slope_with(BTC)"),
            GateRef(g_trend_slope_strong_with, (("asset", "BTC"), ("tf", "5m")), "g_trend_slope_strong_with(BTC,5m)"),
            GateRef(g_imb5_strong_with, (), "g_imb5_strong_with"),
        ),
    ),
    # V8_04 — ETH 5m BOTH offset 60 — ema50 + hurst_trending + 1h grandparent
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_eth_5m_l_ema50_hurst_grandparent_v8",
        asset="ETH", tf="5m", direction="BOTH",
        offsets=(60,),
        spread_filter=_SPREAD_ETH,
        gates=(
            GateRef(g_tr_above_ema50, (("asset", "ETH"),), "g_tr_above_ema50(ETH)"),
            GateRef(g_hurst_trending, (("asset", "ETH"), ("tf", "5m")), "g_hurst_trending(ETH,5m)"),
            GateRef(g_grandparent_trend_with, (("asset", "ETH"),), "g_grandparent_trend_with(ETH)"),
        ),
    ),
    # V8_05 — ETH 5m BOTH offset 120 — hurst regime + trend slope + CCI + TOD EU/US window
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_eth_5m_k_hurst_ts_cci_tod_euus_v8",
        asset="ETH", tf="5m", direction="BOTH",
        offsets=(120,),
        spread_filter=_SPREAD_ETH,
        gates=(
            GateRef(g_hurst_regime_with, (("asset", "ETH"), ("tf", "5m")), "g_hurst_regime_with(ETH,5m)"),
            GateRef(g_trend_slope_with, (("asset", "ETH"), ("tf", "5m")), "g_trend_slope_with(ETH,5m)"),
            GateRef(g_cci_with, (("asset", "ETH"),), "g_cci_with(ETH)"),
            GateRef(g_tod_europe_us_window, (), "g_tod_europe_us_window"),
        ),
    ),
    # V8_06 — ETH 5m BOTH offset 60 — ema50 + hurst regime + 1h grandparent + Path Q prev 15m agrees
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_eth_5m_lq_ema50_hurst_grandparent_prev15m_v8",
        asset="ETH", tf="5m", direction="BOTH",
        offsets=(60,),
        spread_filter=_SPREAD_ETH,
        gates=(
            GateRef(g_tr_above_ema50, (("asset", "ETH"),), "g_tr_above_ema50(ETH)"),
            GateRef(g_hurst_regime_with, (("asset", "ETH"), ("tf", "5m")), "g_hurst_regime_with(ETH,5m)"),
            GateRef(g_grandparent_trend_with, (("asset", "ETH"),), "g_grandparent_trend_with(ETH)"),
            GateRef(g_q_prev15m_agrees, (("asset", "ETH"),), "g_q_prev15m_agrees(ETH)"),
        ),
    ),
    # V8_07 — SOL 5m BOTH offsets ALL — BTC F7 against + CCI extreme + hurst reverting + MFI strong
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_sol_5m_btcf7against_cci_hurstrev_mfi_v8",
        asset="SOL", tf="5m", direction="BOTH",
        offsets=(30, 60, 90, 120, 150, 180, 210, 240),
        spread_filter=_SPREAD_SOL,
        gates=(
            GateRef(g_btc_f7_against, (), "g_btc_f7_against"),
            GateRef(g_cci_extreme_with, (("asset", "SOL"),), "g_cci_extreme_with(SOL)"),
            GateRef(g_hurst_reverting, (("asset", "SOL"), ("tf", "5m")), "g_hurst_reverting(SOL,5m)"),
            GateRef(g_mfi_strong_with, (("asset", "SOL"),), "g_mfi_strong_with(SOL)"),
        ),
    ),
    # V8_08 — SOL 5m BOTH offsets ALL — 2asset either trending + CCI extreme + RF + ema200
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_sol_5m_j_2asset_trending_cci_rf_ema200_v8",
        asset="SOL", tf="5m", direction="BOTH",
        offsets=(30, 60, 90, 120, 150, 180, 210, 240),
        spread_filter=_SPREAD_SOL,
        gates=(
            GateRef(g_2asset_either_trending_with, (), "g_2asset_either_trending_with"),
            GateRef(g_cci_extreme_with, (("asset", "SOL"),), "g_cci_extreme_with(SOL)"),
            GateRef(g_rf_with, (("asset", "SOL"),), "g_rf_with(SOL)"),
            GateRef(g_tr_above_ema200, (("asset", "SOL"),), "g_tr_above_ema200(SOL)"),
        ),
    ),
    # V8_09 — ETH 15m BOTH offsets {0,30,60} — V7_10 replicate (duplicate per spec §8)
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_eth_15m_baseline_v7_top_replicate_v8",
        asset="ETH", tf="15m", direction="BOTH",
        offsets=(0, 30, 60),
        spread_filter=_SPREAD_ETH,
        gates=(
            GateRef(g_tr_stack_full_with, (("asset", "ETH"),), "g_tr_stack_full_with(ETH)"),
            GateRef(g_above_1h_dailyvwap_with, (("asset", "ETH"),), "g_above_1h_dailyvwap_with(ETH)"),
            GateRef(g_offset_early, (), "g_offset_early"),
            GateRef(g_vol_high, (("asset", "ETH"), ("tf", "15m")), "g_vol_high(ETH,15m)"),
            GateRef(g_pw_btc_15m_trend_with, (), "g_pw_btc_15m_trend_with"),
        ),
    ),
    # V8_10 — ETH 15m BOTH offsets {0,30,60} — V7_10 + pw_sol_15m_trend
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_eth_15m_pj_btc_and_sol_trend_sep_v8",
        asset="ETH", tf="15m", direction="BOTH",
        offsets=(0, 30, 60),
        spread_filter=_SPREAD_ETH,
        gates=(
            GateRef(g_tr_stack_full_with, (("asset", "ETH"),), "g_tr_stack_full_with(ETH)"),
            GateRef(g_above_1h_dailyvwap_with, (("asset", "ETH"),), "g_above_1h_dailyvwap_with(ETH)"),
            GateRef(g_offset_early, (), "g_offset_early"),
            GateRef(g_vol_high, (("asset", "ETH"), ("tf", "15m")), "g_vol_high(ETH,15m)"),
            GateRef(g_pw_btc_15m_trend_with, (), "g_pw_btc_15m_trend_with"),
            GateRef(g_pw_sol_15m_trend_with, (), "g_pw_sol_15m_trend_with"),
        ),
    ),
    # V8_11 — SOL 15m BOTH offsets {60,120,240} — V7_11 base + ETH 1h ADX strong (stability winner)
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_sol_15m_v7s5_plus_eth1h_adx_v8",
        asset="SOL", tf="15m", direction="BOTH",
        offsets=(60, 120, 240),
        spread_filter=_SPREAD_SOL,
        gates=(
            GateRef(g_hod_european_morning, (), "g_hod_european_morning"),
            GateRef(g_off_60_240, (), "g_off_60_240"),
            GateRef(g_rf_with, (("asset", "SOL"),), "g_rf_with(SOL)"),
            GateRef(g_tr_stack_with, (("asset", "SOL"),), "g_tr_stack_with(SOL)"),
            GateRef(g_BTC_slope_with, (), "g_BTC_slope_with"),
            GateRef(g_BTC_slope_strong_with, (), "g_BTC_slope_strong_with"),
            GateRef(g_L_ETH_grandparent_adx_strong, (), "g_L_ETH_grandparent_adx_strong"),
        ),
    ),
    # V8_12 — SOL 15m BOTH offsets {60,120,240} — V7_11 replicate (duplicate per spec §8)
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_sol_15m_v7_base_s5_slope_str_v8",
        asset="SOL", tf="15m", direction="BOTH",
        offsets=(60, 120, 240),
        spread_filter=_SPREAD_SOL,
        gates=(
            GateRef(g_hod_european_morning, (), "g_hod_european_morning"),
            GateRef(g_off_60_240, (), "g_off_60_240"),
            GateRef(g_rf_with, (("asset", "SOL"),), "g_rf_with(SOL)"),
            GateRef(g_tr_stack_with, (("asset", "SOL"),), "g_tr_stack_with(SOL)"),
            GateRef(g_BTC_slope_with, (), "g_BTC_slope_with"),
            GateRef(g_BTC_slope_strong_with, (), "g_BTC_slope_strong_with"),
        ),
    ),
    # V8_13 — SOL 15m BOTH offsets {60,120,240} — V6 base + J BTC/ETH vol low + L ETH grandparent ADX
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_sol_15m_v6_j_btceth_vollow_l_ethadx_v8",
        asset="SOL", tf="15m", direction="BOTH",
        offsets=(60, 120, 240),
        spread_filter=_SPREAD_SOL,
        gates=(
            GateRef(g_hod_european_morning, (), "g_hod_european_morning"),
            GateRef(g_off_60_240, (), "g_off_60_240"),
            GateRef(g_rf_with, (("asset", "SOL"),), "g_rf_with(SOL)"),
            GateRef(g_tr_stack_with, (("asset", "SOL"),), "g_tr_stack_with(SOL)"),
            GateRef(g_J_btc_eth_vol_both_low, (), "g_J_btc_eth_vol_both_low"),
            GateRef(g_L_ETH_grandparent_adx_strong, (), "g_L_ETH_grandparent_adx_strong"),
        ),
    ),
    # V8_14 — BTC 15m UP-ONLY offset 720 — BTC/ETH divergence + Stoch + vol contracting (only stat-sig)
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_btc_15m_btceth_diverg_stoch_volcontr_v8",
        asset="BTC", tf="15m", direction="UP",
        offsets=(720,),
        spread_filter=_SPREAD_BTC,
        gates=(
            GateRef(g_dir_up, (), "g_dir_up"),
            GateRef(g_btc_eth_divergence, (), "g_btc_eth_divergence"),
            GateRef(g_stoch_with, (("asset", "BTC"),), "g_stoch_with(BTC)"),
            GateRef(g_vol_contracting, (("asset", "BTC"), ("tf", "15m")), "g_vol_contracting(BTC,15m)"),
        ),
    ),
    # =================================================================
    # VL — 11 spread-loose variants (SHADOW_DEPLOY_SPEC_V9_AND_VL §4).
    # Each VL_NN is an EXACT COPY of its parent above with:
    #   1. sleeve_id += "_vL"
    #   2. spread_filter changed to per-asset VL value
    # All other fields (asset, tf, direction, offsets, gates) IDENTICAL.
    # A/B period: 14 days side-by-side with parent. Kill _vL if WR drops
    # > 3pp below parent.
    # =================================================================

    # VL_01 — ETH 5m k_hurst_ts_cci_tod_euus_v8 (parent offsets=120, BIGGEST GAIN)
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_eth_5m_k_hurst_ts_cci_tod_euus_v8_vL",
        asset="ETH", tf="5m", direction="BOTH",
        offsets=(120,),
        spread_filter=_SPREAD_VL_ETH,
        gates=(
            GateRef(g_hurst_regime_with, (("asset", "ETH"), ("tf", "5m")), "g_hurst_regime_with(ETH,5m)"),
            GateRef(g_trend_slope_with, (("asset", "ETH"), ("tf", "5m")), "g_trend_slope_with(ETH,5m)"),
            GateRef(g_cci_with, (("asset", "ETH"),), "g_cci_with(ETH)"),
            GateRef(g_tod_europe_us_window, (), "g_tod_europe_us_window"),
        ),
    ),
    # VL_02 — ETH 5m lq_ema50_hurst_grandparent_prev15m_v8 (parent offsets=60)
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_eth_5m_lq_ema50_hurst_grandparent_prev15m_v8_vL",
        asset="ETH", tf="5m", direction="BOTH",
        offsets=(60,),
        spread_filter=_SPREAD_VL_ETH,
        gates=(
            GateRef(g_tr_above_ema50, (("asset", "ETH"),), "g_tr_above_ema50(ETH)"),
            GateRef(g_hurst_regime_with, (("asset", "ETH"), ("tf", "5m")), "g_hurst_regime_with(ETH,5m)"),
            GateRef(g_grandparent_trend_with, (("asset", "ETH"),), "g_grandparent_trend_with(ETH)"),
            GateRef(g_q_prev15m_agrees, (("asset", "ETH"),), "g_q_prev15m_agrees(ETH)"),
        ),
    ),
    # VL_03 — ETH 5m ema50_hurst_parent15mrang_v7 (parent offsets=60)
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_eth_5m_ema50_hurst_parent15mrang_v7_vL",
        asset="ETH", tf="5m", direction="BOTH",
        offsets=(60,),
        spread_filter=_SPREAD_VL_ETH,
        gates=(
            GateRef(g_tr_above_ema50, (("asset", "ETH"),), "g_tr_above_ema50(ETH)"),
            GateRef(g_hurst_trending, (("asset", "ETH"), ("tf", "5m")), "g_hurst_trending(ETH,5m)"),
            GateRef(g_parent15m_ranging, (("asset", "ETH"),), "g_parent15m_ranging(ETH)"),
        ),
    ),
    # VL_04 — ETH 5m cloud_ribbon_mp_hurst_v6 (parent offsets=60)
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_eth_5m_cloud_ribbon_mp_hurst_v6_vL",
        asset="ETH", tf="5m", direction="BOTH",
        offsets=(60,),
        spread_filter=_SPREAD_VL_ETH,
        gates=(
            GateRef(g_tr_above_cloud, (("asset", "ETH"),), "g_tr_above_cloud(ETH)"),
            GateRef(g_ribbon_agrees, (("asset", "ETH"),), "g_ribbon_agrees(ETH)"),
            GateRef(g_mp_skew_with, (), "g_mp_skew_with"),
            GateRef(g_hurst_trending, (("asset", "ETH"), ("tf", "5m")), "g_hurst_trending(ETH,5m)"),
        ),
    ),
    # VL_05 — ETH 5m v6c3_parent15mrang_v7 (parent offsets=60)
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_eth_5m_v6c3_parent15mrang_v7_vL",
        asset="ETH", tf="5m", direction="BOTH",
        offsets=(60,),
        spread_filter=_SPREAD_VL_ETH,
        gates=(
            GateRef(g_tr_above_cloud, (("asset", "ETH"),), "g_tr_above_cloud(ETH)"),
            GateRef(g_ribbon_agrees, (("asset", "ETH"),), "g_ribbon_agrees(ETH)"),
            GateRef(g_mp_skew_with, (), "g_mp_skew_with"),
            GateRef(g_hurst_trending, (("asset", "ETH"), ("tf", "5m")), "g_hurst_trending(ETH,5m)"),
            GateRef(g_parent15m_ranging, (("asset", "ETH"),), "g_parent15m_ranging(ETH)"),
        ),
    ),
    # VL_06 — ETH 5m bb_mp_hurst_band_v6 (parent offsets=60)
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_eth_5m_bb_mp_hurst_band_v6_vL",
        asset="ETH", tf="5m", direction="BOTH",
        offsets=(60,),
        spread_filter=_SPREAD_VL_ETH,
        gates=(
            GateRef(g_bb_pos_with, (("asset", "ETH"),), "g_bb_pos_with(ETH)"),
            GateRef(g_mp_skew_with, (), "g_mp_skew_with"),
            GateRef(g_hurst_trending, (("asset", "ETH"), ("tf", "5m")), "g_hurst_trending(ETH,5m)"),
            GateRef(g_entry_vwap_in_band, (), "g_entry_vwap_in_band"),
        ),
    ),
    # VL_07 — ETH 5m cloud_vwap_hurstmp_v7 (parent offsets=60)
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_eth_5m_cloud_vwap_hurstmp_v7_vL",
        asset="ETH", tf="5m", direction="BOTH",
        offsets=(60,),
        spread_filter=_SPREAD_VL_ETH,
        gates=(
            GateRef(g_tr_above_cloud, (("asset", "ETH"),), "g_tr_above_cloud(ETH)"),
            GateRef(g_entry_vwap_in_band, (), "g_entry_vwap_in_band"),
            GateRef(g_hurst_mp_trend_with, (("asset", "ETH"),), "g_hurst_mp_trend_with(ETH)"),
        ),
    ),
    # VL_08 — ETH 15m trstack_vwap_vol_offearly (parent offsets=0,30,60)
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_eth_15m_trstack_vwap_vol_offearly_vL",
        asset="ETH", tf="15m", direction="BOTH",
        offsets=(0, 30, 60),
        spread_filter=_SPREAD_VL_ETH,
        gates=(
            GateRef(g_tr_stack_full_with, (("asset", "ETH"),), "g_tr_stack_full_with(ETH)"),
            GateRef(g_above_1h_dailyvwap_with, (("asset", "ETH"),), "g_above_1h_dailyvwap_with(ETH)"),
            GateRef(g_offset_early, (), "g_offset_early"),
            GateRef(g_vol_high, (("asset", "ETH"), ("tf", "15m")), "g_vol_high(ETH,15m)"),
        ),
    ),
    # VL_09 — ETH 15m trstack_vwap_vol_offearly_band_v6 (parent offsets=0,30,60)
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_eth_15m_trstack_vwap_vol_offearly_band_v6_vL",
        asset="ETH", tf="15m", direction="BOTH",
        offsets=(0, 30, 60),
        spread_filter=_SPREAD_VL_ETH,
        gates=(
            GateRef(g_tr_stack_full_with, (("asset", "ETH"),), "g_tr_stack_full_with(ETH)"),
            GateRef(g_above_1h_dailyvwap_with, (("asset", "ETH"),), "g_above_1h_dailyvwap_with(ETH)"),
            GateRef(g_offset_early, (), "g_offset_early"),
            GateRef(g_vol_high, (("asset", "ETH"), ("tf", "15m")), "g_vol_high(ETH,15m)"),
            GateRef(g_entry_vwap_in_30_70, (), "g_entry_vwap_in_30_70"),
        ),
    ),
    # VL_10 — SOL 15m trstack_vol_ribbon_ema_mid (parent offsets=120,180,240)
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_sol_15m_trstack_vol_ribbon_ema_mid_vL",
        asset="SOL", tf="15m", direction="BOTH",
        offsets=(120, 180, 240),
        spread_filter=_SPREAD_VL_SOL_15M,
        gates=(
            GateRef(g_tr_stack_full_with, (("asset", "SOL"),), "g_tr_stack_full_with(SOL)"),
            GateRef(g_vol_high, (("asset", "SOL"), ("tf", "15m")), "g_vol_high(SOL,15m)"),
            GateRef(g_ribbon_agrees, (("asset", "SOL"),), "g_ribbon_agrees(SOL)"),
            GateRef(g_tr_above_ema200, (("asset", "SOL"),), "g_tr_above_ema200(SOL)"),
            GateRef(g_tr_above_ema800, (("asset", "SOL"),), "g_tr_above_ema800(SOL)"),
        ),
    ),
    # VL_11 — SOL 15m rfaged_trstack_late (parent offsets=480..840, $5 stake)
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_sol_15m_rfaged_trstack_late_vL",
        asset="SOL", tf="15m", direction="BOTH",
        offsets=(480, 600, 720, 840),
        spread_filter=_SPREAD_VL_SOL_15M,
        notional_usd_override=Decimal("5.0"),
        gates=(
            GateRef(g_rf_aged, (("asset", "SOL"),), "g_rf_aged(SOL)"),
            GateRef(g_tr_stack_full_with, (("asset", "SOL"),), "g_tr_stack_full_with(SOL)"),
            GateRef(g_tr_stack_with, (("asset", "SOL"),), "g_tr_stack_with(SOL)"),
        ),
    ),
    # =================================================================
    # V9 — 10 NEW-GATE sleeves (SHADOW_DEPLOY_SPEC_V9_AND_VL §3).
    # Use B1/B2/B3 Polymarket flow + A2 HL cascade gates from the V9
    # batch. Boot-defensive: when canonical parquets aren't loaded on
    # this VPS, the V9 gates return False and these sleeves stay silent
    # (no fires). Operator must populate /opt/tradingvenue/data/v4/canonical/
    # before V9 sleeves start firing.
    # =================================================================

    # V9_01 — BTC 5m BOTH offsets=30 A2 hlcascade @ $100k
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_btc_5m_a2_hlcascade100k_v9",
        asset="BTC", tf="5m", direction="BOTH",
        offsets=(30,),
        spread_filter=_SPREAD_BTC,
        gates=(
            GateRef(
                g_a2_hl_short_cascade,
                (("asset_coin", "BTC"), ("window_s", "300"), ("thresh_usd", "100000")),
                "g_a2_hl_short_cascade(BTC,300s,100k)",
            ),
        ),
    ),
    # V9_02 — BTC 5m UP-only offsets=30 A2 hlcascade @ $50k
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_btc_5m_up_a2_hlcascade50k_v9",
        asset="BTC", tf="5m", direction="UP",
        offsets=(30,),
        spread_filter=_SPREAD_BTC,
        gates=(
            GateRef(
                g_a2_hl_short_cascade,
                (("asset_coin", "BTC"), ("window_s", "300"), ("thresh_usd", "50000")),
                "g_a2_hl_short_cascade(BTC,300s,50k)",
            ),
            GateRef(g_dir_up, (), "g_dir_up"),
        ),
    ),
    # A2 hlcascade — ETH + SOL (2026-05-30). Same A2 short-liquidation cascade
    # gate as the BTC pair above, just asset_coin=ETH/SOL. Enabled now that the
    # multi-CEX liq feed carries ETH/SOL liqs + the $5k cap is removed. Scaled
    # thresholds (ETH 50k/25k, SOL 25k/15k) — PROVISIONAL, tune from shadow.
    # ETH BOTH @ $50k
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_eth_5m_a2_hlcascade50k_v9",
        asset="ETH", tf="5m", direction="BOTH",
        offsets=(30,),
        spread_filter=_SPREAD_ETH,
        gates=(
            GateRef(
                g_a2_hl_short_cascade,
                (("asset_coin", "ETH"), ("window_s", "300"), ("thresh_usd", "50000")),
                "g_a2_hl_short_cascade(ETH,300s,50k)",
            ),
        ),
    ),
    # ETH UP-only @ $25k
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_eth_5m_up_a2_hlcascade25k_v9",
        asset="ETH", tf="5m", direction="UP",
        offsets=(30,),
        spread_filter=_SPREAD_ETH,
        gates=(
            GateRef(
                g_a2_hl_short_cascade,
                (("asset_coin", "ETH"), ("window_s", "300"), ("thresh_usd", "25000")),
                "g_a2_hl_short_cascade(ETH,300s,25k)",
            ),
            GateRef(g_dir_up, (), "g_dir_up"),
        ),
    ),
    # SOL BOTH @ $25k
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_sol_5m_a2_hlcascade25k_v9",
        asset="SOL", tf="5m", direction="BOTH",
        offsets=(30,),
        spread_filter=_SPREAD_SOL,
        gates=(
            GateRef(
                g_a2_hl_short_cascade,
                (("asset_coin", "SOL"), ("window_s", "300"), ("thresh_usd", "25000")),
                "g_a2_hl_short_cascade(SOL,300s,25k)",
            ),
        ),
    ),
    # SOL UP-only @ $15k
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_sol_5m_up_a2_hlcascade15k_v9",
        asset="SOL", tf="5m", direction="UP",
        offsets=(30,),
        spread_filter=_SPREAD_SOL,
        gates=(
            GateRef(
                g_a2_hl_short_cascade,
                (("asset_coin", "SOL"), ("window_s", "300"), ("thresh_usd", "15000")),
                "g_a2_hl_short_cascade(SOL,300s,15k)",
            ),
            GateRef(g_dir_up, (), "g_dir_up"),
        ),
    ),
    # V9_03 — BTC 5m DOWN-only B2 contrarian @ 2k shares ★ TOP INCOME
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_btc_5m_down_b2_contrarian2k_v9",
        asset="BTC", tf="5m", direction="DOWN",
        offsets=(30,),
        spread_filter=_SPREAD_BTC,
        gates=(
            GateRef(
                g_b2_poly_flow_contrarian,
                (("window_s", "60"), ("thresh_shares", "2000")),
                "g_b2_poly_flow_contrarian(DOWN,60s,2000)",
            ),
            GateRef(g_dir_down, (), "g_dir_down"),
        ),
    ),
    # V9_04 — BTC 5m UP-only B2 contrarian @ 2k shares
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_btc_5m_up_b2_contrarian2k_v9",
        asset="BTC", tf="5m", direction="UP",
        offsets=(30,),
        spread_filter=_SPREAD_BTC,
        gates=(
            GateRef(
                g_b2_poly_flow_contrarian,
                (("window_s", "60"), ("thresh_shares", "2000")),
                "g_b2_poly_flow_contrarian(UP,60s,2000)",
            ),
            GateRef(g_dir_up, (), "g_dir_up"),
        ),
    ),
    # V9_05 — SOL 5m BOTH offsets=30/60/90 B1 polyflow aligned @ 500
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_sol_5m_b1_polyflow_aligned_v9",
        asset="SOL", tf="5m", direction="BOTH",
        offsets=(30, 60, 90),
        spread_filter=_SPREAD_SOL,
        gates=(
            GateRef(
                g_b1_poly_flow_aligned,
                (("window_s", "60"), ("thresh_shares", "500")),
                "g_b1_poly_flow_aligned(SOL,60s,500)",
            ),
        ),
    ),
    # V9_06 — SOL 5m DOWN-only offsets=30/60/90 B1 @ 500 (highest $/tr)
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_sol_5m_down_b1_500_v9",
        asset="SOL", tf="5m", direction="DOWN",
        offsets=(30, 60, 90),
        spread_filter=_SPREAD_SOL,
        gates=(
            GateRef(
                g_b1_poly_flow_aligned,
                (("window_s", "60"), ("thresh_shares", "500")),
                "g_b1_poly_flow_aligned(SOL,DOWN,60s,500)",
            ),
            GateRef(g_dir_down, (), "g_dir_down"),
        ),
    ),
    # V9_07 — SOL 5m DOWN-only offsets=30/60/90 B1 @ 250 (broader)
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_sol_5m_down_b1_flow250_v9",
        asset="SOL", tf="5m", direction="DOWN",
        offsets=(30, 60, 90),
        spread_filter=_SPREAD_SOL,
        gates=(
            GateRef(
                g_b1_poly_flow_aligned,
                (("window_s", "60"), ("thresh_shares", "250")),
                "g_b1_poly_flow_aligned(SOL,DOWN,60s,250)",
            ),
            GateRef(g_dir_down, (), "g_dir_down"),
        ),
    ),
    # V9_08 — SOL 5m BOTH B3 absolute @ 500 (direction-agnostic strong flow)
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_sol_5m_b3_abs500_v9",
        asset="SOL", tf="5m", direction="BOTH",
        offsets=(30, 60, 90),
        spread_filter=_SPREAD_SOL,
        gates=(
            GateRef(
                g_b3_poly_flow_abs,
                (("window_s", "60"), ("thresh_shares", "500")),
                "g_b3_poly_flow_abs(SOL,60s,500)",
            ),
        ),
    ),
    # V9_09 — SOL 5m BOTH B1 with 120s window @ 250 (smoother noise filter)
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_sol_5m_b1_120s_250_v9",
        asset="SOL", tf="5m", direction="BOTH",
        offsets=(30, 60, 90),
        spread_filter=_SPREAD_SOL,
        gates=(
            GateRef(
                g_b1_poly_flow_aligned,
                (("window_s", "120"), ("thresh_shares", "250")),
                "g_b1_poly_flow_aligned(SOL,120s,250)",
            ),
        ),
    ),
    # V9_10 — SOL 5m BOTH B3 abs500 AND NOT B2 opposing @ 500 (marginal, monitor)
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_sol_5m_b3_abs500_no_opp_v9",
        asset="SOL", tf="5m", direction="BOTH",
        offsets=(30, 60, 90),
        spread_filter=_SPREAD_SOL,
        gates=(
            GateRef(
                g_b3_poly_flow_abs,
                (("window_s", "60"), ("thresh_shares", "500")),
                "g_b3_poly_flow_abs(SOL,60s,500)",
            ),
            GateRef(
                g_b2_poly_flow_NOT_opposing,
                (("window_s", "60"), ("thresh_shares", "500")),
                "g_b2_poly_flow_NOT_opposing(SOL,60s,500)",
            ),
        ),
    ),
    # 57 — HEDGE_LATE A/B variant of #12 (SHADOW_DEPLOY_SPEC_SLEEVE_H_HEDGELATE).
    # Identical entry/gates to poly_sniper_v5_btc_15m_ema50_ema800_off600_down;
    # the ONLY difference is exit_policy=HEDGE_LATE. Fires on the SAME slugs as
    # the parent for a clean A/B (identical entries, different exits).
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_btc_15m_ema50_ema800_off600_down_H",
        asset="BTC", tf="15m", direction="DOWN",
        offsets=(600,),
        spread_filter=_SPREAD_BTC,
        gates=(
            GateRef(g_dir_down, (), "g_dir_down"),
            GateRef(g_tr_above_ema50, (("asset", "BTC"),), "g_tr_above_ema50(BTC)"),
            GateRef(g_tr_above_ema800, (("asset", "BTC"),), "g_tr_above_ema800(BTC)"),
        ),
        exit_policy="HEDGE_LATE",
    ),
    # =================================================================
    # fast_taker — oracle-lag directional taker, A/B shadow (4 sleeves).
    # TV_AGENT_SPEC_FAST_TAKER_SHADOW_AB_2026_05_29.md. BTC 5m + ETH 5m only
    # (highest edge+fill per realistic_latency.csv; SOL loses, 15m deferred).
    # Config A ($25, BOTH, merge_mimic): fire the leading side on each
    # qualifying oracle-lag signal across a dense early-weighted window so both
    # sides accumulate; FIFO-merge matched pairs ($1/pair, gas 0); hold the
    # residual to chainlink resolution. Config B ($2, one-shot, no merge): the
    # micro live candidate — fire once per slug on the first qualifying early
    # offset, hold to resolution. Fee model legacy_2pct (2%-on-winning-profit).
    # Gate g_oracle_lag_bps_ge(3.0) fires the side matching sign(price_delta_bps).
    # =================================================================
    # FT_A1 — BTC 5m merge_mimic $25
    SniperV5Sleeve(
        sleeve_id="poly_fast_taker_a25_merge_btc_5m",
        asset="BTC", tf="5m", direction="BOTH",
        offsets=(5, 10, 20, 40, 80, 160, 240),
        spread_filter=_SPREAD_BTC,
        notional_usd_override=Decimal("25.0"),
        merge_mimic=True,
        one_shot_per_slug=False,
        gates=(
            GateRef(
                g_oracle_lag_bps_ge,
                (("threshold_bps", "3.0"),),
                "g_oracle_lag_bps_ge(3.0)",
            ),
        ),
    ),
    # FT_A2 — ETH 5m merge_mimic $25
    SniperV5Sleeve(
        sleeve_id="poly_fast_taker_a25_merge_eth_5m",
        asset="ETH", tf="5m", direction="BOTH",
        offsets=(5, 10, 20, 40, 80, 160, 240),
        spread_filter=_SPREAD_ETH,
        notional_usd_override=Decimal("25.0"),
        merge_mimic=True,
        one_shot_per_slug=False,
        gates=(
            GateRef(
                g_oracle_lag_bps_ge,
                (("threshold_bps", "3.0"),),
                "g_oracle_lag_bps_ge(3.0)",
            ),
        ),
    ),
    # FT_B1 — BTC 5m no-merge $2 one-shot (micro live candidate)
    SniperV5Sleeve(
        sleeve_id="poly_fast_taker_b2_nomerge_btc_5m",
        asset="BTC", tf="5m", direction="BOTH",
        offsets=(3, 6, 9, 12),
        spread_filter=_SPREAD_BTC,
        notional_usd_override=Decimal("2.0"),
        merge_mimic=False,
        one_shot_per_slug=True,
        gates=(
            GateRef(
                g_oracle_lag_bps_ge,
                (("threshold_bps", "3.0"),),
                "g_oracle_lag_bps_ge(3.0)",
            ),
        ),
    ),
    # FT_B2 — ETH 5m no-merge $2 one-shot
    SniperV5Sleeve(
        sleeve_id="poly_fast_taker_b2_nomerge_eth_5m",
        asset="ETH", tf="5m", direction="BOTH",
        offsets=(3, 6, 9, 12),
        spread_filter=_SPREAD_ETH,
        notional_usd_override=Decimal("2.0"),
        merge_mimic=False,
        one_shot_per_slug=True,
        gates=(
            GateRef(
                g_oracle_lag_bps_ge,
                (("threshold_bps", "3.0"),),
                "g_oracle_lag_bps_ge(3.0)",
            ),
        ),
    ),
    # =================================================================
    # FAST_TAKER_LAGV2 — directional oracle-lag taker, 4 shadow sleeves.
    # TV_AGENT_SPEC_FAST_TAKER_LAGV2_2026_05_29.md. A SEPARATE family from the
    # A/B fast_taker above: 0.07 winner-only fee + chainlink resolution +
    # LAG_REVERSAL_STOP (no merge, no legacy_2pct). direction=BOTH → the
    # g_oracle_lag_with gate fires only the leading side; one_shot_per_slug
    # fires ONCE per slug on the first qualifying early offset. Gates: band
    # [3,12]bps (cap is load-bearing — >12 reverses to −EV), ex-18-23 UTC,
    # cross-asset confluence (BTC↔ETH), top-of-book depth ≥ median. BTC+ETH ×
    # 5m+15m; SOL excluded. Flat $25 shadow size (confidence-prop = phase 2).
    # =================================================================
    # LAGV2 — BTC 5m
    SniperV5Sleeve(
        sleeve_id="poly_fast_taker_lagv2_btc_5m",
        asset="BTC", tf="5m", direction="BOTH",
        offsets=(5, 10, 20, 40),
        spread_filter=_SPREAD_LAGV2,
        notional_usd_override=Decimal("25.0"),
        one_shot_per_slug=True,
        exit_policy="LAG_REVERSAL_STOP",
        reversal_stop_bps=10.0,
        gates=(
            GateRef(
                g_oracle_lag_with,
                (("lo_bps", "3.0"), ("hi_bps", "12.0")),
                "g_oracle_lag_with(3.0,12.0)",
            ),
            GateRef(g_not_us_close_hours, (), "g_not_us_close_hours"),
            GateRef(
                g_cross_asset_lag_confluence,
                (("conf_bps", "3.0"),),
                "g_cross_asset_lag_confluence(3.0)",
            ),
            GateRef(g_top_depth_ge_median, (), "g_top_depth_ge_median"),
        ),
    ),
    # LAGV2 — BTC 15m (the cleaner cell)
    SniperV5Sleeve(
        sleeve_id="poly_fast_taker_lagv2_btc_15m",
        asset="BTC", tf="15m", direction="BOTH",
        offsets=(5, 10, 20, 40),
        spread_filter=_SPREAD_LAGV2,
        notional_usd_override=Decimal("25.0"),
        one_shot_per_slug=True,
        exit_policy="LAG_REVERSAL_STOP",
        reversal_stop_bps=10.0,
        gates=(
            GateRef(
                g_oracle_lag_with,
                (("lo_bps", "3.0"), ("hi_bps", "12.0")),
                "g_oracle_lag_with(3.0,12.0)",
            ),
            GateRef(g_not_us_close_hours, (), "g_not_us_close_hours"),
            GateRef(
                g_cross_asset_lag_confluence,
                (("conf_bps", "3.0"),),
                "g_cross_asset_lag_confluence(3.0)",
            ),
            GateRef(g_top_depth_ge_median, (), "g_top_depth_ge_median"),
        ),
    ),
    # LAGV2 — ETH 5m (confluence other = BTC)
    SniperV5Sleeve(
        sleeve_id="poly_fast_taker_lagv2_eth_5m",
        asset="ETH", tf="5m", direction="BOTH",
        offsets=(5, 10, 20, 40),
        spread_filter=_SPREAD_LAGV2,
        notional_usd_override=Decimal("25.0"),
        one_shot_per_slug=True,
        exit_policy="LAG_REVERSAL_STOP",
        reversal_stop_bps=10.0,
        gates=(
            GateRef(
                g_oracle_lag_with,
                (("lo_bps", "3.0"), ("hi_bps", "12.0")),
                "g_oracle_lag_with(3.0,12.0)",
            ),
            GateRef(g_not_us_close_hours, (), "g_not_us_close_hours"),
            GateRef(
                g_cross_asset_lag_confluence,
                (("conf_bps", "3.0"),),
                "g_cross_asset_lag_confluence(3.0)",
            ),
            GateRef(g_top_depth_ge_median, (), "g_top_depth_ge_median"),
        ),
    ),
    # LAGV2 — ETH 15m
    SniperV5Sleeve(
        sleeve_id="poly_fast_taker_lagv2_eth_15m",
        asset="ETH", tf="15m", direction="BOTH",
        offsets=(5, 10, 20, 40),
        spread_filter=_SPREAD_LAGV2,
        notional_usd_override=Decimal("25.0"),
        one_shot_per_slug=True,
        exit_policy="LAG_REVERSAL_STOP",
        reversal_stop_bps=10.0,
        gates=(
            GateRef(
                g_oracle_lag_with,
                (("lo_bps", "3.0"), ("hi_bps", "12.0")),
                "g_oracle_lag_with(3.0,12.0)",
            ),
            GateRef(g_not_us_close_hours, (), "g_not_us_close_hours"),
            GateRef(
                g_cross_asset_lag_confluence,
                (("conf_bps", "3.0"),),
                "g_cross_asset_lag_confluence(3.0)",
            ),
            GateRef(g_top_depth_ge_median, (), "g_top_depth_ge_median"),
        ),
    ),
    # -----------------------------------------------------------------
    # V10 (3 sleeves) — TV_AGENT_SPEC_V10_SLEEVES_2026_05_31.md
    # ETH 5m winners + one new-gate each (in-sample on GA universe → shadow A/B
    # vs the v8/v6 parent confirms OOS). Parents kept running unchanged.
    # -----------------------------------------------------------------
    # V10_01 — clone of l_ema50_hurst_grandparent_v8 + g_sms_no_liquidity_above
    #          (Calmar 17.3→23.7, MaxDD −$25→−$15, full period).
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_eth_5m_l_ema50_hurst_grandparent_V10",
        asset="ETH", tf="5m", direction="BOTH",
        offsets=(60,),
        spread_filter=_SPREAD_ETH,
        gates=(
            GateRef(g_tr_above_ema50, (("asset", "ETH"),), "g_tr_above_ema50(ETH)"),
            GateRef(g_hurst_trending, (("asset", "ETH"), ("tf", "5m")), "g_hurst_trending(ETH,5m)"),
            GateRef(g_grandparent_trend_with, (("asset", "ETH"),), "g_grandparent_trend_with(ETH)"),
            GateRef(g_sms_no_liquidity_above, (("asset", "ETH"), ("tf", "5m")), "g_sms_no_liquidity_above(ETH,5m)"),
        ),
    ),
    # V10_02 — clone of cloud_ribbon_mp_hurst_v6 + g_tr_above_pp
    #          (MaxDD −$35→−$21, Calmar 12.0→12.3).
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_eth_5m_cloud_ribbon_mp_hurst_V10",
        asset="ETH", tf="5m", direction="BOTH",
        offsets=(60,),
        spread_filter=_SPREAD_ETH,
        gates=(
            GateRef(g_tr_above_cloud, (("asset", "ETH"),), "g_tr_above_cloud(ETH)"),
            GateRef(g_ribbon_agrees, (("asset", "ETH"),), "g_ribbon_agrees(ETH)"),
            GateRef(g_mp_skew_with, (), "g_mp_skew_with"),
            GateRef(g_hurst_trending, (("asset", "ETH"), ("tf", "5m")), "g_hurst_trending(ETH,5m)"),
            GateRef(g_tr_above_pp, (("asset", "ETH"),), "g_tr_above_pp(ETH)"),
        ),
    ),
    # V10_03 — clone of bb_mp_hurst_band_v6, swap g_entry_vwap_in_band →
    #          g_entry_vwap_in_band_narrow [0.15,0.55] (+$1.41/tr, Calmar 9.6→13.6,
    #          ~60% fewer fires — higher-conviction, lower-frequency variant).
    SniperV5Sleeve(
        sleeve_id="poly_sniper_v5_eth_5m_bb_mp_hurst_band_V10",
        asset="ETH", tf="5m", direction="BOTH",
        offsets=(60,),
        spread_filter=_SPREAD_ETH,
        gates=(
            GateRef(g_bb_pos_with, (("asset", "ETH"),), "g_bb_pos_with(ETH)"),
            GateRef(g_mp_skew_with, (), "g_mp_skew_with"),
            GateRef(g_hurst_trending, (("asset", "ETH"), ("tf", "5m")), "g_hurst_trending(ETH,5m)"),
            GateRef(g_entry_vwap_in_band_narrow, (), "g_entry_vwap_in_band_narrow"),
        ),
    ),
)


# Convenience exports
SNIPER_V5_SLEEVE_IDS: Final[tuple[str, ...]] = tuple(s.sleeve_id for s in SNIPER_V5_SLEEVES)
SNIPER_V5_PREFIXES: Final[tuple[str, ...]] = ("poly_sniper_v5_",)


__all__ = [
    "GateRef", "SniperV5Sleeve",
    "SNIPER_V5_PREFIXES", "SNIPER_V5_SLEEVES", "SNIPER_V5_SLEEVE_IDS",
]
