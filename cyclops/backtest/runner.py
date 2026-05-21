"""Cyclops P2 backtest runner.

Wires together: canonical loaders → 3 axes → conflict filter → L25 walk →
chainlink settlement. The only integration point in the package.

Phase 1 simplifications (documented in spec §13 + below):
  - Momentum axis uses the L5 imbalance on the Up-outcome's tier1 snapshot
    AT fire_us only. CVD/aggressor terms require Polymarket trades which are
    stale through May 6; they are wired but skipped in P2.
  - Sizing is fixed $25 (sizing.fixed). No risk pause yet (P4).
  - No pre-flight guards yet (P3).
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from strategy_lab.book_walk import book_walk_fill

from ..axes import levels as axis_levels
from ..axes import momentum as axis_momentum
from ..axes import trend as axis_trend
from ..conventions import (
    FEE_RATE,
    FIRE_OFFSET_S,
    NOTIONAL_USD,
    RESULTS_DIR,
    SLEEVE_ID,
    TREND_EPS_FRAC,
)
from ..data_io import (
    asof_strict,
    load_klines,
    load_resampled_kline_arrays,
    load_signal_streams,
    load_tier1_entries,
    load_universe,
)
from ..filters.blowoff_guard import bollinger_position, is_blowoff_skip, rsi
from ..filters.conflict import apply_conflict_filter
from ..filters.hours_guard import is_trading_hour
from ..filters.ob_manipulation import _imbalance_score, is_ob_manipulated
from ..filters.reentry_lock import ReentryLock
from ..filters.vwap_guard import is_vwap_too_low
from ..risk.drawdown_manager import DrawdownManager
from ..sizing.fixed import fixed_size
from .settlement import settle_legacy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_tier1_index(t1: pd.DataFrame) -> dict:
    """Map (slug, outcome) → row index in tier1_entries."""
    out: dict = {}
    for i, (s, o) in enumerate(zip(t1["slug"].values, t1["outcome"].values)):
        out[(s, o)] = i
    return out


def _l25_levels_from_row(row: pd.Series, side: str) -> tuple[list, list]:
    """Return (prices, sizes) for the requested side ('ask' / 'bid') of a
    tier1_entries row, levels 0..24."""
    pcol = f"{side}_price_"
    scol = f"{side}_size_"
    prices = [row[f"{pcol}{i}"] for i in range(25)]
    sizes = [row[f"{scol}{i}"] for i in range(25)]
    return prices, sizes


def _momentum_from_tier1_up_side(t1: pd.DataFrame, idx: dict, slug: str) -> tuple[int, float]:
    """Compute the momentum vote using only the L5 imbalance on the Up-outcome
    tier1 snapshot. Returns (vote, score).

    Sign convention: positive imbalance on the Up side ⇒ Up-bullish ⇒ vote +1.

    DEGRADED — kept for backward-compat ablation. The full-depth path is
    `_momentum_from_streams_up_side` below.
    """
    key = (slug, "Up")
    if key not in idx:
        return 0, 0.0
    row = t1.iloc[idx[key]]
    bid_sum = sum(float(row[f"bid_size_{i}"]) for i in range(5))
    ask_sum = sum(float(row[f"ask_size_{i}"]) for i in range(5))
    total = bid_sum + ask_sum
    if total <= 0:
        return 0, 0.0
    imb = (bid_sum - ask_sum) / total           # ∈ [-1, +1]
    # In the absence of trades, the composite score collapses to W_IMB * imb.
    score = axis_momentum.MOMENTUM_W_IMBALANCE_L5 * imb
    score = max(-1.0, min(1.0, score))
    return axis_momentum.momentum_vote(score), score


def _momentum_from_streams_up_side(
    ob_by_slug: dict,
    trades_by_slug: dict,
    slug: str,
    fire_us: int,
) -> tuple[int, float, dict]:
    """Full-depth momentum axis (spec §4.5).

    Composite of three normalized features on the Up-outcome side:
      - imb_l5      = top-5-level imbalance at the latest snapshot ≤ fire_us
      - cvd_1m      = signed buy/sell volume over last MOMENTUM_WINDOW_S
      - aggressor_30s = signed flow over last MOMENTUM_AGGRESSOR_WINDOW_S

    Returns (vote, score, components_dict). Falls back gracefully when
    OB or trades are missing — `vote=0` if all components are zero.
    """
    components = {"imb_l5": 0.0, "cvd_norm": 0.0, "aggressor": 0.0}

    ob = ob_by_slug.get(slug)
    if ob is not None:
        ts_us, ap, asz, bp, bsz = ob
        if ts_us.size > 0:
            idx = int(np.searchsorted(ts_us, int(fire_us), side="right")) - 1
            if idx >= 0:
                bid_sum = float(np.nansum(bsz[idx, :5]))
                ask_sum = float(np.nansum(asz[idx, :5]))
                tot = bid_sum + ask_sum
                if tot > 0:
                    components["imb_l5"] = max(-1.0, min(1.0, (bid_sum - ask_sum) / tot))

    tr = trades_by_slug.get(slug)
    if tr is not None and tr["ts_us"].size > 0:
        ts_t = tr["ts_us"]
        sz = tr["size"]
        sn = tr["side_sign"].astype("float64")

        win_lo = int(fire_us) - axis_momentum.MOMENTUM_WINDOW_S * 1_000_000
        mask = (ts_t > win_lo) & (ts_t <= int(fire_us))
        if mask.any():
            cvd_usd = float(((sz * sn)[mask]).sum())
            components["cvd_norm"] = max(-1.0, min(
                1.0, cvd_usd / axis_momentum.MOMENTUM_CVD_CAP_USD
            ))

        agg_lo = int(fire_us) - axis_momentum.MOMENTUM_AGGRESSOR_WINDOW_S * 1_000_000
        mask30 = (ts_t > agg_lo) & (ts_t <= int(fire_us))
        if mask30.any():
            sub_sz = sz[mask30]
            sub_sn = sn[mask30]
            buy_usd = float(sub_sz[sub_sn > 0].sum())
            sell_usd = float(sub_sz[sub_sn < 0].sum())
            total = buy_usd + sell_usd
            if total > 0:
                components["aggressor"] = max(-1.0, min(
                    1.0, (buy_usd - sell_usd) / total
                ))

    score = (
        axis_momentum.MOMENTUM_W_IMBALANCE_L5 * components["imb_l5"]
        + axis_momentum.MOMENTUM_W_CVD_1M * components["cvd_norm"]
        + axis_momentum.MOMENTUM_W_AGGRESSOR_30S * components["aggressor"]
    )
    score = max(-1.0, min(1.0, score))
    return axis_momentum.momentum_vote(score), score, components


def _ob_5s_window_for_guard(ob_by_slug: dict, slug: str, fire_us: int):
    """Slice OB snapshots in (fire_us - OB_VOL_WINDOW_S, fire_us] and return
    them as the (bsz_l5, asz_l5) pairs that ob_manipulation expects."""
    ob = ob_by_slug.get(slug)
    if ob is None:
        return None
    ts_us, _ap, asz, _bp, bsz = ob
    if ts_us.size == 0:
        return None
    from ..conventions import OB_VOLATILITY_WINDOW_S
    lo_us = int(fire_us) - OB_VOLATILITY_WINDOW_S * 1_000_000
    mask = (ts_us > lo_us) & (ts_us <= int(fire_us))
    if not mask.any():
        return None
    bsz_l5 = bsz[mask][:, :5]
    asz_l5 = asz[mask][:, :5]
    return [(bsz_l5[i], asz_l5[i]) for i in range(bsz_l5.shape[0])]


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run_backtest(
    asset: str = "BTC",
    timeframe: str = "5m",
    start_iso: Optional[str] = None,
    end_iso: Optional[str] = None,
    max_markets: Optional[int] = None,
    notional_usd: float = NOTIONAL_USD,
    fee_rate: float = FEE_RATE,
    eps_frac: float = TREND_EPS_FRAC,
    vwap_min: float = 0.0,
    require_momentum_abstain: bool = False,
    start_balance: float = 0.0,
    risk_enabled: bool = False,
    max_drawdown_pct: float = 5.0,
    daily_loss_pct: float = 2.0,
    hours_guard_enabled: bool = False,
    hours_start_utc: float = 0.0,
    hours_stop_utc: float = 24.0,
    weekend_off: bool = False,
    blowoff_guard_enabled: bool = False,
    reentry_lock_enabled: bool = False,
    full_depth: bool = False,
    ob_manipulation_guard: bool = False,
    verbose: bool = True,
) -> pd.DataFrame:
    """Run a Cyclops backtest over the chainlink-resolved universe.

    Returns a DataFrame where every row represents one *evaluation* (fired or
    skipped). Use df[df.fired] for filled-trade analyses.
    """
    asset_l = asset.lower()
    asset_u = asset.upper()

    # Universe
    univ = load_universe(asset_u, timeframe)
    if start_iso:
        start_s = int(datetime.fromisoformat(start_iso).replace(tzinfo=timezone.utc).timestamp())
        univ = univ[univ.ws_s >= start_s]
    if end_iso:
        end_s = int(datetime.fromisoformat(end_iso).replace(tzinfo=timezone.utc).timestamp())
        univ = univ[univ.ws_s < end_s]
    univ = univ.sort_values("ws_s").reset_index(drop=True)
    if max_markets is not None:
        univ = univ.head(max_markets)
    if verbose:
        print(f"[runner] universe: n={len(univ)} {asset_u} {timeframe} markets")

    # Klines: 1MIN + resampled
    bars = load_resampled_kline_arrays(asset_u, "binance-spot-ws")
    end_us_1m = bars["1m"]["end_us"]
    close_1m = bars["1m"]["close"]
    bars_1h = (bars["1h"]["end_us"], bars["1h"]["close"])
    bars_15m_close = (bars["15m"]["end_us"], bars["15m"]["close"])
    bars_5m_close = (bars["5m"]["end_us"], bars["5m"]["close"])
    bars_15m_ohlc = (
        bars["15m"]["end_us"], bars["15m"]["high"],
        bars["15m"]["low"], bars["15m"]["close"],
    )
    if verbose:
        print(f"[runner] klines: 1m={len(end_us_1m)} 5m={len(bars_5m_close[0])} "
              f"15m={len(bars_15m_ohlc[0])} 1h={len(bars_1h[0])}")

    # Tier1 L25 book at t+120
    t1 = load_tier1_entries(asset_l)
    t1_idx = _build_tier1_index(t1)
    if verbose:
        print(f"[runner] tier1 rows: {len(t1)}")

    # Full-depth: load streaming L25 OB + trades for the universe's slugs.
    ob_by_slug: dict = {}
    trades_by_slug: dict = {}
    if full_depth or ob_manipulation_guard:
        if verbose:
            print(f"[runner] full_depth: loading streaming OB + trades for "
                  f"{len(univ)} slugs (Up side) — this may take 30-90s ...")
        ob_by_slug, trades_by_slug = load_signal_streams(
            asset=asset_l, slugs=set(univ["slug"].values),
            outcome="Up", verbose=verbose,
        )

    rows = []
    balance = float(start_balance)
    fired = 0
    wins = 0
    sum_pnl = 0.0

    risk: Optional[DrawdownManager] = None
    if risk_enabled:
        if start_balance <= 0:
            raise ValueError("risk_enabled requires start_balance > 0")
        risk = DrawdownManager(
            start_balance=start_balance,
            max_drawdown_pct=max_drawdown_pct,
            daily_loss_limit_pct=daily_loss_pct,
        )

    reentry: Optional[ReentryLock] = ReentryLock() if reentry_lock_enabled else None

    # Pre-compute 5m close array for BB/RSI lookups (used by blowoff guard).
    bars_5m_full_end_us = bars["5m"]["end_us"]
    bars_5m_full_close = bars["5m"]["close"]

    for _, mkt in univ.iterrows():
        slug = mkt.slug
        ws_s = int(mkt.ws_s)
        fire_us = (ws_s + FIRE_OFFSET_S) * 1_000_000
        outcome_truth = mkt.outcome

        # Risk manager check FIRST (cheap, before any computation).
        if risk is not None:
            risk.update(balance, ws_s)
            halted, halt_reason = risk.is_halted(balance)
            if halted:
                rows.append({"fired": False, "skip_reason": halt_reason,
                             "slug": slug, "ws_s": ws_s,
                             "outcome_truth": outcome_truth,
                             "balance_cum_usd": balance})
                continue

        # Hours guard — pre-check before any axis math.
        if hours_guard_enabled:
            allowed, hours_reason = is_trading_hour(
                ws_s + FIRE_OFFSET_S,
                start_utc=hours_start_utc, stop_utc=hours_stop_utc,
                weekend_off=weekend_off,
            )
            if not allowed:
                rows.append({"fired": False, "skip_reason": hours_reason,
                             "slug": slug, "ws_s": ws_s,
                             "outcome_truth": outcome_truth})
                continue

        # Reentry lock — only triggers if the same slug fires twice; cheap.
        if reentry is not None:
            blocked, lock_reason = reentry.block_if_locked(slug, fire_us)
            if blocked:
                rows.append({"fired": False, "skip_reason": lock_reason,
                             "slug": slug, "ws_s": ws_s,
                             "outcome_truth": outcome_truth})
                continue

        current_px = asof_strict(end_us_1m, close_1m, fire_us)
        if not (current_px > 0):
            rows.append({"fired": False, "skip_reason": "no_kline_asof",
                         "slug": slug, "ws_s": ws_s, "outcome_truth": outcome_truth})
            continue

        # Axes
        alignment = axis_trend.compute_trend_axis(
            bars_1h, bars_15m_close, bars_5m_close, fire_us, eps_frac=eps_frac
        )
        v_trend = axis_trend.trend_vote(alignment)

        p_up = axis_levels.compute_levels_p_up(bars_15m_ohlc, fire_us, current_px)
        v_levels = axis_levels.levels_vote(p_up)

        if full_depth:
            v_momentum, m_score, m_components = _momentum_from_streams_up_side(
                ob_by_slug, trades_by_slug, slug, fire_us,
            )
        else:
            v_momentum, m_score = _momentum_from_tier1_up_side(t1, t1_idx, slug)
            m_components = {"imb_l5": float("nan"), "cvd_norm": float("nan"),
                            "aggressor": float("nan")}

        # Conflict filter
        fire, direction, reason = apply_conflict_filter(
            v_trend, v_levels, v_momentum,
            require_momentum_abstain=require_momentum_abstain,
        )

        # Blowoff exhaustion check — applies only after direction is set.
        bb_pos = "no_data"
        rsi_val = float("nan")
        if fire and blowoff_guard_enabled and direction is not None:
            bb_pos, _bb_up, _bb_dn = bollinger_position(
                bars_5m_full_close, bars_5m_full_end_us, fire_us,
            )
            rsi_val = rsi(bars_5m_full_close, bars_5m_full_end_us, fire_us)
            blow_skip, blow_reason = is_blowoff_skip(
                direction=direction,
                bb_position=bb_pos,
                rsi_value=rsi_val,
                mtf_abs=abs(alignment),
            )
            if blow_skip:
                fire = False
                reason = blow_reason

        row = {
            "slug": slug, "ws_s": ws_s, "outcome_truth": outcome_truth,
            "current_px": current_px, "trend_align": alignment,
            "v_trend": v_trend, "v_levels": v_levels, "v_momentum": v_momentum,
            "p_up_levels": p_up, "score_momentum": m_score,
            "mom_imb_l5": m_components["imb_l5"],
            "mom_cvd_norm": m_components["cvd_norm"],
            "mom_aggressor": m_components["aggressor"],
            "bb_position": bb_pos, "rsi14": rsi_val,
            "fired": False, "skip_reason": reason,
        }

        if not fire:
            rows.append(row)
            continue

        # OB manipulation guard — needs streaming snapshots in last 5s.
        if ob_manipulation_guard:
            snaps = _ob_5s_window_for_guard(ob_by_slug, slug, fire_us)
            ob_skip, ob_reason = is_ob_manipulated(snaps)
            if ob_skip:
                row["skip_reason"] = ob_reason
                rows.append(row)
                continue

        # Fill at L25 — ASK side of chosen direction (we buy that outcome's shares)
        key = (slug, direction)
        if key not in t1_idx:
            row["skip_reason"] = "no_l25_entry"
            rows.append(row)
            continue
        t1row = t1.iloc[t1_idx[key]]
        ask_p, ask_s = _l25_levels_from_row(t1row, "ask")

        # Vwap pre-flight guard: skip extreme-low-price markets (P2 forensics).
        skip_vw, vw_reason = is_vwap_too_low(ask_p[0], vwap_min)
        if skip_vw:
            row["skip_reason"] = vw_reason
            rows.append(row)
            continue

        stake = fixed_size(balance=balance)
        vwap, shares, usd, hit_levels, underfilled = book_walk_fill(
            ask_p, ask_s, stake, side="buy",
        )
        if usd <= 0 or shares <= 0:
            row["skip_reason"] = "no_fill"
            rows.append(row)
            continue

        won = (direction == outcome_truth)
        pnl = settle_legacy(won, shares, usd, fee_rate=fee_rate)
        balance += pnl
        fired += 1
        wins += int(won)
        sum_pnl += pnl

        row.update({
            "fired": True,
            "skip_reason": None,
            "direction": direction,
            "stake_usd": usd,
            "vwap_entry": vwap,
            "shares": shares,
            "hit_levels": hit_levels,
            "underfilled": bool(underfilled),
            "won": bool(won),
            "pnl_usd": pnl,
            "balance_cum_usd": balance,
        })
        rows.append(row)

    df = pd.DataFrame(rows)
    if verbose:
        n_eval = len(df)
        wr = (wins / fired) if fired else float("nan")
        avg = (sum_pnl / fired) if fired else float("nan")
        print(f"[runner] eval={n_eval}  fired={fired}  wins={wins}  "
              f"WR={wr:.3f}  mean_pnl=${avg:+.4f}  total=${sum_pnl:+.2f}")
        if risk is not None:
            s = risk.stats()
            print(f"[risk]   start=${s['start_balance']:.2f}  peak=${s['peak']:.2f}  "
                  f"final=${balance:.2f}  pauses[dd={s['n_pauses_drawdown']}, "
                  f"daily={s['n_pauses_daily']}]")
    return df


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _gate_g0(df: pd.DataFrame) -> tuple[bool, str]:
    n = int(df["fired"].sum())
    return (n >= 10, f"G0 smoke: fired={n} (need ≥10)")


def _gate_g1(df: pd.DataFrame) -> tuple[bool, str]:
    sub = df[df["fired"]]
    if sub.empty:
        return (False, "G1 edge sign: no fired trades")
    mean = float(sub["pnl_usd"].mean())
    return (mean > 0, f"G1 edge sign: mean_pnl=${mean:+.4f} (need >0)")


def main():
    ap = argparse.ArgumentParser(description="Cyclops P2 backtest")
    ap.add_argument("--asset", default="BTC")
    ap.add_argument("--tf", default="5m")
    ap.add_argument("--start", help="ISO date, e.g. 2026-04-24")
    ap.add_argument("--end", help="ISO date (exclusive), e.g. 2026-05-15")
    ap.add_argument("--max", type=int, default=None, help="cap on # markets")
    ap.add_argument("--out", type=Path, default=None, help="CSV output path")
    ap.add_argument("--eps", type=float, default=TREND_EPS_FRAC,
                    help="trend axis window-fraction threshold")
    ap.add_argument("--vwap-min", type=float, default=0.0,
                    help="skip markets whose level-0 ASK < this threshold "
                         "(P2 forensics: 0.30 removes the doom zone)")
    ap.add_argument("--require-mom-abstain", action="store_true",
                    help="demote momentum to a hard veto: fire only when "
                         "momentum_vote == 0 and trend+levels are coherent "
                         "(2-of-2 coherence required, no abstentions)")
    ap.add_argument("--risk", action="store_true",
                    help="enable the drawdown/daily-loss risk manager")
    ap.add_argument("--start-balance", type=float, default=1000.0,
                    help="starting bankroll for risk-manager calculations "
                         "(only used when --risk is on)")
    ap.add_argument("--max-dd-pct", type=float, default=5.0,
                    help="max drawdown pct from session peak before halt")
    ap.add_argument("--daily-loss-pct", type=float, default=2.0,
                    help="max daily loss pct from day-start before halt")
    ap.add_argument("--hours-guard", action="store_true",
                    help="enable weekday/business-hours fire window")
    ap.add_argument("--hours-start", type=float, default=13.0)
    ap.add_argument("--hours-stop", type=float, default=21.0)
    ap.add_argument("--weekend-off", action="store_true",
                    help="block fires on Sat+Sun UTC")
    ap.add_argument("--blowoff-guard", action="store_true",
                    help="enable BB+RSI+MTF blowoff skip (asymmetric)")
    ap.add_argument("--reentry-lock", action="store_true",
                    help="enable per-slug reentry cooldown")
    ap.add_argument("--full-depth", action="store_true",
                    help="use streaming L25 OB + trades for momentum axis "
                         "(loads 5+ GB; takes 30-90s extra startup)")
    ap.add_argument("--ob-guard", action="store_true",
                    help="enable ob_manipulation guard (needs streaming OB; "
                         "auto-enables --full-depth loader)")
    args = ap.parse_args()

    df = run_backtest(
        asset=args.asset, timeframe=args.tf,
        start_iso=args.start, end_iso=args.end,
        max_markets=args.max, eps_frac=args.eps,
        vwap_min=args.vwap_min,
        require_momentum_abstain=args.require_mom_abstain,
        start_balance=(args.start_balance if args.risk else 0.0),
        risk_enabled=args.risk,
        max_drawdown_pct=args.max_dd_pct,
        daily_loss_pct=args.daily_loss_pct,
        hours_guard_enabled=args.hours_guard,
        hours_start_utc=args.hours_start,
        hours_stop_utc=args.hours_stop,
        weekend_off=args.weekend_off,
        blowoff_guard_enabled=args.blowoff_guard,
        reentry_lock_enabled=args.reentry_lock,
        full_depth=args.full_depth,
        ob_manipulation_guard=args.ob_guard,
    )

    out_path = args.out or (
        RESULTS_DIR / f"p2_backtest_{args.asset.lower()}_{args.tf}.csv"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    print(f"[runner] wrote {out_path}  ({len(df)} rows)")

    print(f"\n[sleeve] {SLEEVE_ID}")
    for ok, msg in (_gate_g0(df), _gate_g1(df)):
        print(f"  [{'PASS' if ok else 'FAIL'}] {msg}")

    # Per-skip-reason breakdown
    sk = df[~df["fired"]]["skip_reason"].value_counts().to_dict()
    print("[skip-reason counts]")
    for k, v in sk.items():
        print(f"  {k:32s} {v}")


if __name__ == "__main__":
    main()
