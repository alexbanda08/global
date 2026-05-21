"""
Deployment-ready decision function for H_refined strategy.

USAGE
-----
At slot_end - 300s on a BTC or ETH 15m market:
    decision = h_refined_decide(slug, ticker, slot_start_us, slot_end_us,
                                book_snapshot, klines_func)
    if decision.signal != "SKIP":
        # Fire decision.signal at decision.entry_us, fill via L25 walk
        ...

INPUTS at fire time
-------------------
    book_snapshot   :  dict {(slug, "Up"|"Down") -> (ts[N], ap[N,25], asz[N,25],
                                                     bp[N,25], bsz[N,25])}
                       (the standard L25 streaming shape)
    klines_func     :  callable (asset, venue, period) -> (end_us, prices)
                       (same shape as data/v4/canonical/load.load_klines_asof)

CONFIG (locked from refinement, 2026-05-16)
-------------------------------------------
    timeframe         = "15m"
    anchor_offset_s   = 300        (entry = slot_end - 300s)
    obs_horizon_s     = 600        (binance momentum over last 10 min)
    sigma_lookback_s  = 30*60      (30-min realized std of 1MIN log-returns)
    edge_threshold    = 0.08       (|fair_p - p_clob_up| > 0.08)
    vwap_filter       = (0.30, 0.70)
    spread_filter     = 0.02       (BTC/ETH max)
    notional_usd      = 25
    fee_rate          = 0.02       (on positive PnL only)
    allowed_assets    = {"BTC", "ETH"}    (SOL excluded — too noisy)

VALIDATION (24,438 markets, Apr 24 → May 16 2026)
-------------------------------------------------
    n=574  hit=64.3%  total_pnl=+$1,393  $/trade=+$2.43
    permutation p (PnL, 1000 draws): 0.004
    OOS (held-out May 6+): n=261, hit=66.3%, +$2.29/trade, p=0.033
    Annualized Sharpe: 9.2     Max DD: -$282
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np

CONFIG = dict(
    # base v1
    anchor_offset_s   = 300,
    obs_horizon_s     = 600,
    sigma_lookback_min= 30,
    edge_threshold    = 0.08,
    vwap_lo           = 0.40,    # v2: tightened from 0.30
    vwap_hi           = 0.60,    # v2: tightened from 0.70
    spread_filter     = 0.02,
    notional_usd      = 25.0,
    fee_rate          = 0.02,
    allowed_assets    = {"BTC", "ETH"},
    # v2 compound filters
    active_hours_utc  = (6, 24),  # [06:00, 24:00) UTC; skip 00-05 UTC
    weekday_only      = True,     # Mon-Fri only
)


@dataclass
class Decision:
    signal: str          # "UP" | "DOWN" | "SKIP"
    reason: str          # explanation
    entry_us: int        # fire timestamp
    vwap: float | None   # planned fill price
    shares: float | None
    edge: float | None
    fair_p: float | None
    p_clob_up: float | None


def _asof(end_us: np.ndarray, prices: np.ndarray, target_us: int) -> float:
    i = int(np.searchsorted(end_us, target_us, side="right") - 1)
    if i < 0:
        return float("nan")
    return float(prices[i])


def _walk_asks(prices, sizes, dollars: float):
    spent = 0.0
    shares = 0.0
    for p, s in zip(prices, sizes):
        if not np.isfinite(p) or p <= 0 or s <= 0:
            continue
        cost_full = p * s
        if spent + cost_full >= dollars:
            need = (dollars - spent) / p
            shares += need
            spent += need * p
            return spent / shares, shares, spent, False
        shares += s
        spent += cost_full
    if shares <= 0:
        return float("nan"), 0.0, 0.0, True
    return spent / shares, shares, spent, spent < dollars * 0.5


def _sigma_30min(end_us, prices, fire_us, lookback_min: int = 30) -> float:
    i = int(np.searchsorted(end_us, fire_us, side="right") - 1)
    if i < lookback_min:
        return 0.0
    sl = prices[i - lookback_min + 1: i + 1]
    if len(sl) < 5:
        return 0.0
    rets = np.diff(np.log(sl))
    rets = rets[np.isfinite(rets)]
    return float(np.std(rets)) if len(rets) >= 5 else 0.0


def _fair_p_up(ret: float, sigma_norm: float) -> float:
    if not np.isfinite(ret) or sigma_norm <= 0:
        return 0.5
    z = ret / sigma_norm
    p = 0.5 + 0.5 * np.tanh(2.0 * z)
    return float(np.clip(p, 0.10, 0.90))


def h_refined_decide(
    slug: str,
    ticker: str,
    slot_start_us: int,
    slot_end_us: int,
    book_snapshot: dict,
    klines_func,        # (asset, venue, period) -> (end_us, prices)
) -> Decision:
    import datetime
    cfg = CONFIG
    if ticker.upper() not in cfg["allowed_assets"]:
        return Decision("SKIP", f"asset {ticker} not in allowed set", 0,
                        None, None, None, None, None)

    # v2 time gates
    ts_utc = datetime.datetime.fromtimestamp(slot_start_us / 1e6, tz=datetime.timezone.utc)
    h_lo, h_hi = cfg["active_hours_utc"]
    if not (h_lo <= ts_utc.hour < h_hi):
        return Decision("SKIP", f"outside active hours (hour={ts_utc.hour} UTC)",
                        slot_end_us - cfg["anchor_offset_s"] * 1_000_000,
                        None, None, None, None, None)
    if cfg["weekday_only"] and ts_utc.weekday() >= 5:
        return Decision("SKIP", f"weekend (dow={ts_utc.weekday()})",
                        slot_end_us - cfg["anchor_offset_s"] * 1_000_000,
                        None, None, None, None, None)

    entry_us = slot_end_us - cfg["anchor_offset_s"] * 1_000_000
    if entry_us <= slot_start_us:
        return Decision("SKIP", "entry would precede slot_start", entry_us,
                        None, None, None, None, None)

    # ----- fair_p from binance -----
    end_us, prices = klines_func(ticker.upper(), "binance-spot-ws", "1MIN")
    obs_lo_us = max(slot_start_us, entry_us - cfg["obs_horizon_s"] * 1_000_000)
    p_now = _asof(end_us, prices, entry_us)
    p_then = _asof(end_us, prices, obs_lo_us)
    if not (np.isfinite(p_now) and np.isfinite(p_then) and p_then > 0):
        return Decision("SKIP", "missing kline data", entry_us, None, None, None, None, None)
    ret_obs = p_now / p_then - 1.0
    sigma = _sigma_30min(end_us, prices, entry_us, cfg["sigma_lookback_min"])
    fair_p = _fair_p_up(ret_obs, sigma)

    # ----- p_clob_up from Up-side book -----
    key_up = (slug, "Up")
    if key_up not in book_snapshot:
        return Decision("SKIP", "no Up book", entry_us, None, None, None, fair_p, None)
    ts_up, ap_up, asz_up, bp_up, bsz_up = book_snapshot[key_up]
    i_up = int(np.searchsorted(ts_up, entry_us, side="right") - 1)
    if i_up < 0:
        return Decision("SKIP", "no book before entry", entry_us, None, None, None, fair_p, None)
    ap0_up = float(ap_up[i_up][0])
    bp0_up = float(bp_up[i_up][0])
    if not (np.isfinite(ap0_up) and np.isfinite(bp0_up)):
        return Decision("SKIP", "missing top-of-book", entry_us, None, None, None, fair_p, None)
    if (ap0_up - bp0_up) > cfg["spread_filter"]:
        return Decision("SKIP", f"spread {ap0_up-bp0_up:.4f} too wide", entry_us,
                        None, None, None, fair_p, None)
    p_clob_up = (ap0_up + bp0_up) / 2
    edge = fair_p - p_clob_up

    if abs(edge) < cfg["edge_threshold"]:
        return Decision("SKIP", f"edge {edge:+.4f} below threshold", entry_us,
                        None, None, edge, fair_p, p_clob_up)

    # ----- select fill side + walk -----
    if edge > 0:
        signal = "UP"
        ap, asz = list(ap_up[i_up]), list(asz_up[i_up])
    else:
        signal = "DOWN"
        key_dn = (slug, "Down")
        if key_dn not in book_snapshot:
            return Decision("SKIP", "no Down book", entry_us, None, None, edge, fair_p, p_clob_up)
        ts_dn, ap_dn, asz_dn, _, _ = book_snapshot[key_dn]
        i_dn = int(np.searchsorted(ts_dn, entry_us, side="right") - 1)
        if i_dn < 0:
            return Decision("SKIP", "no Down book before entry", entry_us,
                            None, None, edge, fair_p, p_clob_up)
        ap, asz = list(ap_dn[i_dn]), list(asz_dn[i_dn])
    vwap, shares, spent, under = _walk_asks(ap, asz, cfg["notional_usd"])
    if under or not np.isfinite(vwap):
        return Decision("SKIP", f"underfilled (spent ${spent:.2f})",
                        entry_us, vwap, shares, edge, fair_p, p_clob_up)

    # vwap filter — THE critical gate
    if not (cfg["vwap_lo"] < vwap < cfg["vwap_hi"]):
        return Decision("SKIP", f"vwap {vwap:.4f} outside [{cfg['vwap_lo']},{cfg['vwap_hi']}]",
                        entry_us, vwap, shares, edge, fair_p, p_clob_up)

    return Decision(signal, "fire", entry_us, vwap, shares, edge, fair_p, p_clob_up)
