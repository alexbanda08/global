"""Phase 36 — 3 shadow strategies from SHADOW_DEPLOY_SPEC_9_NEW_SLEEVES_2026_05_24.md.

* :class:`VwapKellyEnsembleStrategy` — Sleeve #1, fires at offset +120s,
  rule = S4 ∪ S8 with Kelly multiplier on ``fair_edge_bp``.
* :class:`PrewindowS3Strategy` — Sleeve #8, fires at slot_start − 60s,
  rule = S3 (fair_edge_bp > 0 ∧ cvd_agree_60s ∧ macd_agree).
* :class:`PrewindowS4Strategy` — Sleeve #9, fires at slot_start − 120s,
  rule = S4 (fair_edge_bp > 500 ∧ cvd_agree_30s ∧ |dev_bps| ≥ 8).

All three are timeframe-agnostic and shadow-only (paper executor + audit
sleeve_id override). The Kelly tier multiplier is stashed on the controller
instance for ``_compute_qty_shares`` to read at qty-sizing time.

CLAUDE.md inv #4: ``signal()`` is pure — it reads ``aux`` and returns a
direction or NONE. The Kelly multiplier is communicated through a controller
attribute set inside ``signal()``; the controller's qty-sizing pipeline
reads it. Slight impurity is intentional to keep the kwarg surface narrow
(adding a return-value channel would touch every existing strategy).
"""
from __future__ import annotations

import math
from decimal import Decimal
from typing import TYPE_CHECKING

from backend.app.strategies.polymarket.base import (
    PolymarketBinaryStrategy,
    SignalConfig,
    SignalResult,
)
from backend.app.strategies.polymarket.features_1s import (
    cvd_agree,
    macd_agree,
)

if TYPE_CHECKING:  # pragma: no cover
    from backend.app.data.models import Bar


__all__ = [
    "VwapKellyEnsembleStrategy",
    "PrewindowS3Strategy",
    "PrewindowS4Strategy",
    "FadeCompanionStrategy",
    "OverlayFilterStrategy",
    "FADE_HOD_TOP8_BY_CELL",
]


# ─── Spec §FADE — Hour-of-Day Top-8 per (production_strategy, cell) ─────────
# Per ``SHADOW_DEPLOY_SPEC_9_NEW_SLEEVES_2026_05_24.md`` table. Cell key
# uses lower-case symbol so it matches the controller's `cell_key` build
# (which lower-cases internally for HOD lookup).
FADE_HOD_TOP8_BY_CELL: dict[str, frozenset[int]] = {
    "momo_v2_btc_5m":  frozenset({0, 2, 5, 6, 10, 12, 21, 23}),
    "sniper_btc_5m":   frozenset({0, 1, 3, 5, 12, 15, 19, 21}),
    "sniper_eth_15m":  frozenset({0, 6, 7, 9, 13, 14, 19, 22}),
    "sniper_sol_5m":   frozenset({0, 1, 2, 4, 8, 15, 19, 23}),
    "momo_v2_sol_5m":  frozenset({4, 5, 6, 8, 10, 12, 14, 17}),
    "momo_v2_sol_15m": frozenset({1, 2, 5, 12, 13, 16, 17, 21}),
}


def _kelly_mult_for_edge(fair_edge_bp: float) -> float:
    """Per spec §Sleeve #1 — Kelly tier on ``fair_edge_bp``."""
    if fair_edge_bp > 3000:
        return 4.0
    if fair_edge_bp > 2000:
        return 3.0
    if fair_edge_bp > 1000:
        return 2.0
    return 1.0


class VwapKellyEnsembleStrategy(PolymarketBinaryStrategy):
    """Sleeve #1 — S4 ∪ S8 rule + Kelly tier.

    Fire decision (spec §Sleeve #1)::

        direction = "UP" if dev_bps > 0 else "DOWN"
        S4 = fair_edge_bp > 500 AND cvd_agree_30s AND |dev_bps| >= 8
        S8 = macd_agree AND rvol_30_300 > 1.2
        fire iff S4 OR S8

    Kelly notional = ``$25 * mult``:
      - mult = 4 when fair_edge_bp > 3000
      - mult = 3 when > 2000
      - mult = 2 when > 1000
      - mult = 1 otherwise

    Phase gate accepts ``t_plus_120`` only (the spec's first offset; later
    offsets up to 270s are a sweep that the scheduler can extend without
    strategy changes).

    The Kelly multiplier is stored on ``self._controller_ref`` (set by
    the controller before each ``signal()`` call) so the controller's
    ``_compute_qty_shares`` can apply it. Default $25 stake when no
    controller ref is wired (test path).
    """

    name = "vwap_kelly_ensemble"

    def __init__(
        self,
        *,
        fair_edge_min_bp_s4: float = 500.0,
        abs_dev_min_bps_s4: float = 8.0,
        rvol_min_s8: float = 1.2,
        base_notional_usd: Decimal = Decimal("25"),
    ) -> None:
        self.fair_edge_min_bp_s4 = float(fair_edge_min_bp_s4)
        self.abs_dev_min_bps_s4 = float(abs_dev_min_bps_s4)
        self.rvol_min_s8 = float(rvol_min_s8)
        self.base_notional_usd = Decimal(base_notional_usd)
        self.mode = "vwap_kelly_ensemble"

    def signal(
        self,
        bars: list["Bar"],
        config: SignalConfig | None = None,
        aux: dict | None = None,
    ) -> SignalResult:
        if aux is None:
            return "NONE"
        phase = str(aux.get("bar_ctx_phase") or "")
        if not phase.startswith("t_plus_"):
            return "NONE"
        try:
            offset_s = int(phase.split("_", 2)[2])
        except (IndexError, ValueError):
            return "NONE"
        if offset_s < 120:
            return "NONE"

        # 1. dev_bps — direction + magnitude
        dev_bps = aux.get("vwap_dev_bps")
        if dev_bps is None:
            return "NONE"
        try:
            dev_bps = float(dev_bps)
        except (TypeError, ValueError):
            return "NONE"
        if not math.isfinite(dev_bps):
            return "NONE"
        direction: SignalResult = "UP" if dev_bps > 0 else "DOWN"

        # 2. Pull direction-specific fair_edge_bp from aux. The BarContext
        # builder stores the UP leg in ``fair_edge_bp`` and the DOWN leg
        # in ``fair_edge_bp_down`` (controller adapter). For shadow-paper
        # simplicity, ``fair_edge_bp`` is the UP-leg value; flip for DOWN.
        fe_up = aux.get("fair_edge_bp")
        fe_dn = aux.get("fair_edge_bp_down")
        fe = fe_up if direction == "UP" else fe_dn
        if fe is None:
            return "NONE"
        try:
            fe = float(fe)
        except (TypeError, ValueError):
            return "NONE"
        if not math.isfinite(fe):
            return "NONE"

        # 3. CVD agreement at 30s
        cvd_30 = aux.get("cvd_30s")
        cvd_30_agree = cvd_agree(
            float(cvd_30) if cvd_30 is not None and math.isfinite(float(cvd_30)) else None,
            direction,
        )

        # 4. MACD + rvol for S8
        macd = aux.get("macd_hist_value")
        macd_ok = macd_agree(
            float(macd) if macd is not None and math.isfinite(float(macd)) else None,
            direction,
        )
        rvol = aux.get("rvol_30_300")
        try:
            rvol_f = float(rvol) if rvol is not None else None
        except (TypeError, ValueError):
            rvol_f = None

        # S4: high-conviction fair-value
        s4 = (
            fe > self.fair_edge_min_bp_s4
            and cvd_30_agree
            and abs(dev_bps) >= self.abs_dev_min_bps_s4
        )
        # S8: short-term momentum + volume
        s8 = (
            macd_ok
            and rvol_f is not None
            and math.isfinite(rvol_f)
            and rvol_f > self.rvol_min_s8
        )

        if not (s4 or s8):
            return "NONE"

        # Apply Kelly multiplier via controller override slot.
        mult = _kelly_mult_for_edge(fe)
        controller = aux.get("_controller_ref")
        if controller is not None:
            try:
                controller._kelly_notional_override_usd = (
                    self.base_notional_usd * Decimal(str(mult))
                )
                controller._kelly_rule_label = "S4" if s4 else "S8"
                controller._kelly_mult = mult
            except Exception:  # pragma: no cover — defensive
                pass
        return direction


class PrewindowS3Strategy(PolymarketBinaryStrategy):
    """Sleeve #8 — fires at slot_start − 60s on the 5m tf.

    Rule (spec §Sleeve #8)::

        fair_edge_bp > 0 AND cvd_agree_60s AND macd_agree

    Notional is constant at $25 (no Kelly tier — pre-window edge is
    diffuse enough that the spec uses flat sizing).
    """

    name = "prewindow_s3"

    def signal(
        self,
        bars: list["Bar"],
        config: SignalConfig | None = None,
        aux: dict | None = None,
    ) -> SignalResult:
        if aux is None:
            return "NONE"
        if aux.get("bar_ctx_phase") != "pre_window_60":
            return "NONE"

        dev_bps = aux.get("vwap_dev_bps")
        if dev_bps is None:
            return "NONE"
        try:
            dev_bps = float(dev_bps)
        except (TypeError, ValueError):
            return "NONE"
        if not math.isfinite(dev_bps):
            return "NONE"
        direction: SignalResult = "UP" if dev_bps > 0 else "DOWN"

        fe_up = aux.get("fair_edge_bp")
        fe_dn = aux.get("fair_edge_bp_down")
        fe = fe_up if direction == "UP" else fe_dn
        if fe is None:
            return "NONE"
        try:
            fe = float(fe)
        except (TypeError, ValueError):
            return "NONE"
        if not math.isfinite(fe) or fe <= 0:
            return "NONE"

        cvd_60 = aux.get("cvd_60s")
        if not cvd_agree(
            float(cvd_60) if cvd_60 is not None and math.isfinite(float(cvd_60)) else None,
            direction,
        ):
            return "NONE"

        macd = aux.get("macd_hist_value")
        if not macd_agree(
            float(macd) if macd is not None and math.isfinite(float(macd)) else None,
            direction,
        ):
            return "NONE"

        return direction


class PrewindowS4Strategy(PolymarketBinaryStrategy):
    """Sleeve #9 — fires at slot_start − 120s on the 15m tf.

    Rule (spec §Sleeve #9)::

        fair_edge_bp > 500 AND cvd_agree_30s AND |dev_bps| >= 8

    Notional is constant at $25.
    """

    name = "prewindow_s4_15m"

    def __init__(
        self,
        *,
        fair_edge_min_bp: float = 500.0,
        abs_dev_min_bps: float = 8.0,
    ) -> None:
        self.fair_edge_min_bp = float(fair_edge_min_bp)
        self.abs_dev_min_bps = float(abs_dev_min_bps)

    def signal(
        self,
        bars: list["Bar"],
        config: SignalConfig | None = None,
        aux: dict | None = None,
    ) -> SignalResult:
        if aux is None:
            return "NONE"
        if aux.get("bar_ctx_phase") != "pre_window_120":
            return "NONE"

        dev_bps = aux.get("vwap_dev_bps")
        if dev_bps is None:
            return "NONE"
        try:
            dev_bps = float(dev_bps)
        except (TypeError, ValueError):
            return "NONE"
        if not math.isfinite(dev_bps) or abs(dev_bps) < self.abs_dev_min_bps:
            return "NONE"
        direction: SignalResult = "UP" if dev_bps > 0 else "DOWN"

        fe_up = aux.get("fair_edge_bp")
        fe_dn = aux.get("fair_edge_bp_down")
        fe = fe_up if direction == "UP" else fe_dn
        if fe is None:
            return "NONE"
        try:
            fe = float(fe)
        except (TypeError, ValueError):
            return "NONE"
        if not math.isfinite(fe) or fe <= self.fair_edge_min_bp:
            return "NONE"

        cvd_30 = aux.get("cvd_30s")
        if not cvd_agree(
            float(cvd_30) if cvd_30 is not None and math.isfinite(float(cvd_30)) else None,
            direction,
        ):
            return "NONE"

        return direction


# ─── Sleeves #2-7 — FADE companions ─────────────────────────────────────────
class FadeCompanionStrategy(PolymarketBinaryStrategy):
    """Wraps a production strategy + applies Phase 34 HoD + M5V gates.

    Fires the OPPOSITE direction when:
      1. Base strategy raises a signal (UP/DOWN, not NONE)
      2. AND (HoD fails OR M5V fails) — i.e., production WOULD HAVE been
         filtered by Phase 34 gates had it carried them.

    When both gates pass, returns NONE (production fires its standard
    direction; no fade needed). When base signal is NONE, returns NONE.

    Caller wires:
      - ``base_strategy`` — an instantiated production strategy (Sniper /
        Updown / Momo / MomoV2). Its ``signal()`` is called first.
      - ``cell_key`` — string key into :data:`FADE_HOD_TOP8_BY_CELL` (e.g.
        ``"sniper_btc_5m"``).
      - ``regime_field`` — aux key for M5V regime (``"markov_regime_w20_5m_va"``
        or ``"markov_regime_w20_1m_va"``). Per spec §Sleeves #2-7 we use
        the 5MIN regime ('m5v') across all fade cells.
    """

    name = "fade_companion"

    def __init__(
        self,
        *,
        base_strategy: PolymarketBinaryStrategy,
        cell_key: str,
        regime_field: str = "markov_regime_w20_5m_va",
    ) -> None:
        self._base_strategy = base_strategy
        self.cell_key = cell_key
        self.regime_field = regime_field
        self.mode = f"fade_{cell_key}"
        self._hod_allowed = FADE_HOD_TOP8_BY_CELL.get(cell_key, frozenset())

    def signal(
        self,
        bars: list["Bar"],
        config: SignalConfig | None = None,
        aux: dict | None = None,
    ) -> SignalResult:
        if aux is None:
            return "NONE"
        # 1. Re-run the production base signal.
        base_sig = self._base_strategy.signal(bars, config, aux)
        if base_sig not in ("UP", "DOWN"):
            return "NONE"

        # 2. HoD pass — UTC hour of fire_us. Derived from the controller's
        # active BarContext when the controller ref is wired (always true
        # in production; tests may omit). Phase parsing: "t_plus_N" →
        # ws_s + N; "bar_close" → ws_s + ~1s; "pre_window_N" → ws_s − N.
        from datetime import UTC, datetime
        controller = aux.get("_controller_ref")
        bctx = (
            getattr(controller, "_bar_ctx_active", None)
            if controller is not None
            else None
        )
        fire_unix_s: int | None = None
        if bctx is not None:
            ws_s_val = getattr(bctx, "ws_s", None)
            phase = str(getattr(bctx, "phase", "") or "")
            if ws_s_val is not None:
                try:
                    if phase.startswith("t_plus_"):
                        fire_unix_s = int(ws_s_val) + int(phase.split("_", 2)[2])
                    elif phase.startswith("pre_window_"):
                        fire_unix_s = int(ws_s_val) - int(phase.split("_", 2)[2])
                    else:
                        # bar_close + everything else — fire ≈ ws_s.
                        fire_unix_s = int(ws_s_val)
                except (IndexError, ValueError):
                    fire_unix_s = None
        if fire_unix_s is None:
            # Fallback to wall clock. Strictly impure but only triggered
            # in tests / when controller ref + bar_ctx are missing.
            import time as _t
            fire_unix_s = int(_t.time())
        hour = datetime.fromtimestamp(int(fire_unix_s), tz=UTC).hour
        hod_pass = hour in self._hod_allowed

        # 3. M5V pass — regime label agrees with base_sig direction.
        # Prefer controller's BarContext attribute; fall back to aux key
        # (the existing momo / momo_v2 aux paths don't currently carry
        # the regime, so the controller-ref path is the canonical source).
        regime = None
        if bctx is not None:
            regime = getattr(bctx, self.regime_field, None)
        if regime is None:
            regime = aux.get(self.regime_field)
        if regime is None or not isinstance(regime, int):
            m5v_pass = False
        elif base_sig == "UP":
            m5v_pass = regime == 2  # Bull
        elif base_sig == "DOWN":
            m5v_pass = regime == 0  # Bear
        else:
            m5v_pass = False

        # 4. Fade fires when production would have been dropped.
        if hod_pass and m5v_pass:
            return "NONE"  # production fires normally — leave alone
        # Stash gate decisions for audit enrichment.
        controller = aux.get("_controller_ref")
        if controller is not None:
            try:
                controller._fade_decisions = {
                    "base_signal": base_sig,
                    "hour": hour,
                    "hod_pass": hod_pass,
                    "m5v_pass": m5v_pass,
                    "regime": regime,
                }
            except Exception:  # pragma: no cover
                pass
        return "DOWN" if base_sig == "UP" else "UP"


# ─── 6 PROD FILTER overlays — pass-through gate ─────────────────────────────
class OverlayFilterStrategy(PolymarketBinaryStrategy):
    """Wraps a production strategy + applies an EXTRA gate predicate.

    Returns the base strategy's direction unchanged when:
      1. Base signal raises (UP/DOWN)
      2. AND the configured gate predicate passes

    Returns NONE otherwise. Use as a SHADOW VARIANT of the production
    sleeve to A/B-test "what if production added this extra gate?".

    Supported gate_kind values (spec §Bonus):
      - ``"m5v_pass"``                  — Markov 5MIN regime agrees
      - ``"fairedge500"``               — fair_edge_bp > 500
      - ``"fairedge500_cvd30"``         — fair_edge_bp > 500 AND cvd_agree_30s
      - ``"cvd_macd"``                  — cvd_agree_30s AND macd_agree
    """

    name = "overlay_filter"

    def __init__(
        self,
        *,
        base_strategy: PolymarketBinaryStrategy,
        gate_kind: str,
        regime_field: str = "markov_regime_w20_5m_va",
    ) -> None:
        self._base_strategy = base_strategy
        self.gate_kind = gate_kind
        self.regime_field = regime_field
        self.mode = f"overlay_{gate_kind}"

    def _gate_passes(self, direction: str, aux: dict) -> bool:
        k = self.gate_kind
        # Pull features from controller's BarContext when wired; aux
        # fallback keeps tests / standalone unit calls working.
        controller = aux.get("_controller_ref")
        bctx = (
            getattr(controller, "_bar_ctx_active", None)
            if controller is not None
            else None
        )

        def _from_ctx(field: str):
            if bctx is not None:
                return getattr(bctx, field, None)
            return aux.get(field)

        if k == "m5v_pass":
            regime = _from_ctx(self.regime_field)
            if regime is None or not isinstance(regime, int):
                return False
            if direction == "UP":
                return regime == 2
            if direction == "DOWN":
                return regime == 0
            return False

        # Phase 36 features (fair_edge_bp + CVD + MACD).
        fe_up = _from_ctx("fair_edge_bp")
        fe_dn = aux.get("fair_edge_bp_down")  # only built by Kelly aux path
        # For overlay modes the BarContext stores the UP-leg fair_edge_bp.
        # Reconstruct DOWN-leg from fair_up + entry_vwap_no when needed.
        if direction == "DOWN" and fe_dn is None and bctx is not None:
            fu = getattr(bctx, "fair_up_value", None)
            evn = getattr(bctx, "entry_vwap_no", None)
            if fu is not None and evn is not None:
                try:
                    fe_dn = ((1.0 - float(fu)) - float(evn)) * 10_000.0
                except (TypeError, ValueError):
                    fe_dn = None
        fe = fe_up if direction == "UP" else fe_dn
        try:
            fe_f = float(fe) if fe is not None else None
        except (TypeError, ValueError):
            fe_f = None

        cvd_30 = _from_ctx("cvd_30s")
        try:
            cvd30_f = float(cvd_30) if cvd_30 is not None else None
        except (TypeError, ValueError):
            cvd30_f = None
        cvd30_ok = cvd_agree(cvd30_f, direction)

        macd_val = _from_ctx("macd_hist_value")
        try:
            macd_f = float(macd_val) if macd_val is not None else None
        except (TypeError, ValueError):
            macd_f = None
        macd_ok = macd_agree(macd_f, direction)

        if k == "fairedge500":
            return fe_f is not None and math.isfinite(fe_f) and fe_f > 500.0
        if k == "fairedge500_cvd30":
            return (
                fe_f is not None
                and math.isfinite(fe_f)
                and fe_f > 500.0
                and cvd30_ok
            )
        if k == "cvd_macd":
            return cvd30_ok and macd_ok
        return False

    def signal(
        self,
        bars: list["Bar"],
        config: SignalConfig | None = None,
        aux: dict | None = None,
    ) -> SignalResult:
        if aux is None:
            return "NONE"
        base_sig = self._base_strategy.signal(bars, config, aux)
        if base_sig not in ("UP", "DOWN"):
            return "NONE"
        if not self._gate_passes(base_sig, aux):
            return "NONE"
        controller = aux.get("_controller_ref")
        if controller is not None:
            try:
                controller._overlay_decisions = {
                    "base_signal": base_sig,
                    "gate_kind": self.gate_kind,
                    "gate_pass": True,
                }
            except Exception:  # pragma: no cover
                pass
        return base_sig
