"""Kalshi sniper sleeve descriptors (Phase 36-06 Task 1).

Ports the Poly D-07 reference sleeve 1:1 to Kalshi. Reuses the
SniperV5Sleeve / GateRef dataclasses and the sniper_v5_gates pure
functions unchanged — they operate on TV-native panels, not on venue
order-book data, so the same gate logic applies to both Poly and Kalshi.

CLAUDE.md invariants honored:
- inv #4: gates are pure functions evaluated BEFORE placement.
- inv #13: panels come from TV-native price data (per MEMORY: HL/TV-native,
  NOT Storedata). The Kalshi book comes from KalshiMarketDataFeed.
- D-05: ZERO Storedata reads here or at call time.

Series mapping: sleeve_id -> Kalshi series ticker (RESEARCH §D-04).
The controller uses SLEEVE_SERIES to call client.get_open_markets(series).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Final

from backend.app.strategies.polymarket.sniper_v5_gates import (
    g_dir_down,
    g_tr_above_ema50,
    g_tr_above_ema800,
)
from backend.app.strategies.polymarket.sniper_v5_sleeves import (
    GateRef,
    SniperV5Sleeve,
)

# ---------------------------------------------------------------------------
# Reference sleeve: 1:1 port of poly_sniper_v5_btc_15m_ema50_ema800_off600_down
# (RESEARCH §"Reference strategy port (D-07)"; 36-06 PLAN.md must_haves)
# ---------------------------------------------------------------------------

# Marker suffix identifying the S4 prewindow port (TV_AGENT port of the Poly
# shadow_poly_updown_ALL_15m_S4_prewindow sleeve). The Kalshi controller detects
# this suffix and runs the PrewindowS4Strategy signal (fair-value edge + CVD +
# VWAP-deviation) over a Kalshi-built aux instead of the g_* gate loop. Wave 1
# fires at offset=60 (earliest legal — the loop boundary guard rejects <60s);
# Wave 2 will add true pre-window (slot_start-120) negative-offset firing.
S4_PREWINDOW_SUFFIX: Final[str] = "_s4_prewindow"

# Faithful to the Poly original: ONE ``ALL`` sleeve that fans out across all
# three crypto 15m series (NOT three per-symbol sleeves). The controller's
# eval_and_fire_all iterates this map, runs the SAME S4 rule per symbol, and
# fires whichever symbol's signal triggers — all under the one sleeve_id.
S4_ALL_SERIES: Final[dict[str, str]] = {
    "BTC": "KXBTC15M",
    "ETH": "KXETH15M",
    "SOL": "KXSOL15M",
}


KALSHI_SNIPER_SLEEVES: Final[tuple[SniperV5Sleeve, ...]] = (
    SniperV5Sleeve(
        sleeve_id="kalshi_sniper_btc_15m_ema50_ema800_off600_down",
        asset="BTC",
        tf="15m",
        direction="DOWN",
        offsets=(600,),
        spread_filter=Decimal("0.02"),
        gates=(
            GateRef(g_dir_down, (), "g_dir_down"),
            GateRef(
                g_tr_above_ema50,
                (("asset", "BTC"),),
                "g_tr_above_ema50(BTC)",
            ),
            GateRef(
                g_tr_above_ema800,
                (("asset", "BTC"),),
                "g_tr_above_ema800(BTC)",
            ),
        ),
    ),
    # S4 prewindow port — ONE ALL sleeve fanning out across BTC/ETH/SOL 15m
    # (Poly ALL_15m_S4_prewindow → Kalshi). asset="ALL" signals the fan-out;
    # the controller fires the same S4 rule on each series. No g_* gates — the
    # S4 logic is PrewindowS4Strategy.signal over a per-symbol Kalshi aux.
    SniperV5Sleeve(
        sleeve_id=f"kalshi_sniper_all_15m{S4_PREWINDOW_SUFFIX}",
        asset="ALL",
        tf="15m",
        direction="BOTH",      # signal-driven; controller fires sign(dev_bps)
        offsets=(60,),         # earliest legal offset (Wave 1); Wave 2 = prewindow
        spread_filter=Decimal("0.02"),
        gates=(),
    ),
    # HEDGE_LATE A/B variant — IDENTICAL entry to the DOWN reference sleeve
    # above (same gates/offset/series), but exit_policy=HEDGE_LATE: at
    # window_end - lead_s the controller checks the held NO book and cuts early
    # if deep underwater (< fill_vwap × loss_ratio), else holds to settlement.
    # Clean A/B: same entries, HOLD vs HEDGE_LATE exit (Poly _H model).
    SniperV5Sleeve(
        sleeve_id="kalshi_sniper_btc_15m_ema50_ema800_off600_down_H",
        asset="BTC",
        tf="15m",
        direction="DOWN",
        offsets=(600,),
        spread_filter=Decimal("0.02"),
        gates=(
            GateRef(g_dir_down, (), "g_dir_down"),
            GateRef(g_tr_above_ema50, (("asset", "BTC"),), "g_tr_above_ema50(BTC)"),
            GateRef(g_tr_above_ema800, (("asset", "BTC"),), "g_tr_above_ema800(BTC)"),
        ),
        exit_policy="HEDGE_LATE",
    ),
)

KALSHI_SNIPER_SLEEVE_IDS: Final[tuple[str, ...]] = tuple(
    s.sleeve_id for s in KALSHI_SNIPER_SLEEVES
)

# Maps each FIXED-series sleeve to the Kalshi series it trades. The ALL
# fan-out sleeve is NOT here — it uses S4_ALL_SERIES via eval_and_fire_all.
# Discovery: controller calls client.get_open_markets(SLEEVE_SERIES[sleeve_id])
# to find the currently-open 15m market ticker (RESEARCH §D-04).
SLEEVE_SERIES: Final[dict[str, str]] = {
    "kalshi_sniper_btc_15m_ema50_ema800_off600_down": "KXBTC15M",
    "kalshi_sniper_btc_15m_ema50_ema800_off600_down_H": "KXBTC15M",
}

__all__ = [
    "GateRef",
    "KALSHI_SNIPER_SLEEVE_IDS",
    "KALSHI_SNIPER_SLEEVES",
    "S4_ALL_SERIES",
    "S4_PREWINDOW_SUFFIX",
    "SLEEVE_SERIES",
    "SniperV5Sleeve",
]
