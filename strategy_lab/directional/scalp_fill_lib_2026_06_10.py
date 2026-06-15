"""
SCALP FILL LIB — corrected canonical entry/exit model (2026-06-10).

Fixes two confirmed bugs in the scalp_oos_bbo family:
  BUG 1 (outcome-leak exit fallback): the old code did
      sell = bid[jx] if (0<=jx<len(ts) and finite(bid[jx])) else (1.0 if won else 0.0)
    i.e. when no finite bid existed at exit time it used the RESOLVED OUTCOME as a
    mid-window SELL PRICE (lookahead). It also carried a stale bid forward with no age cap.
  BUG 2 (no sell-size cap): entry was capped at best_ask_size but the exit sold the FULL
    position at best_bid regardless of best_bid_size.

CORRECTED EXIT MODEL (exit_fill):
  - ext = min(t_fire+60s, slot_end). jx = last index with ts<=ext.
  - Quote VALID iff jx>=entry_idx AND finite(bid[jx]) AND (ext-ts[jx]) <= stale_us (default 120e6).
  - VALID: sold_sh = min(shares, best_bid_size[jx]); pnl_sold = bpnl(bid[jx], ev, sold_sh).
           rem = shares-sold_sh HELD TO RESOLUTION at winner-only 0.07 settlement valuation
           (NOT lookahead: valuing a held-to-expiry position at settlement is faithful to live).
  - NOT VALID: whole position held to resolution (held_full=True), frac_held=1.0.
  - Held valuation: won -> rem*(1-ev)*(1-0.07*ev); lost -> -rem*ev   (winner-only fee).

  pnl_sold fee term (round-trip 0.015 proxy, unchanged): (sell-ev)*sh - 0.015*sh*(ev*(1-ev)+sell*(1-sell)).

AMENDMENT 2026-06-10b — size==0 is a COLLECTOR ARTIFACT, not real zero depth.
  Verified on raw BBO (SOL 3h sample, 5,340 rows): 47.2% of rows have BOTH best_bid_size==0 AND
  best_ask_size==0 while prices are ALWAYS present; sized rows show 5,210-8,800 shares depth
  (p10-p90) ~ 100x our ~62-share orders. So size==0/NaN = UNKNOWN (price-only update), resolved by
  resolve_size(): carry forward the last POSITIVE size within 300s before the quote row, else the
  next positive size within 300s after, else assume DEEP (no cap). The 120s PRICE-staleness guard,
  missing-bid -> held-to-resolution, fees, and ALL/CLEAN dual reporting are unchanged. Entry keeps
  the original underfill rule but resolves artifact ask sizes the same way (entry_size_carried tag).
"""
import numpy as np

STALE_US = 120_000_000        # 120s asof-staleness guard on the exit quote PRICE
SIZE_WINDOW_US = 300_000_000  # 300s carry window for resolving artifact (==0/NaN) sizes


def resolve_size(ts, sz, idx, window_us=SIZE_WINDOW_US):
    """Depth estimate at row idx, treating size==0/NaN as UNKNOWN (collector artifact).

    Order: (1) size at idx if positive; (2) last POSITIVE size strictly before idx within
    window_us of ts[idx]; (3) next positive size within window_us after; (4) DEEP (inf —
    sized-row depth is ~100x order size on this tape). Returns (size, carried).
    """
    s = sz[idx]
    if np.isfinite(s) and s > 0:
        return float(s), False
    t0 = ts[idx]
    lo = np.searchsorted(ts, t0 - window_us, "left")
    seg = sz[lo:idx]
    pos = np.where(np.isfinite(seg) & (seg > 0))[0]
    if len(pos):
        return float(seg[pos[-1]]), True
    hi = np.searchsorted(ts, t0 + window_us, "right")
    seg = sz[idx + 1:hi]
    pos = np.where(np.isfinite(seg) & (seg > 0))[0]
    if len(pos):
        return float(seg[pos[0]]), True
    return float("inf"), True


def bpnl(sell, ev, sh):
    """round-trip 0.015 fee proxy on a SOLD lot (matches the family's existing bpnl)."""
    return (sell - ev) * sh - 0.015 * sh * (ev * (1 - ev) + sell * (1 - sell))


def held_value(rem, entry_price, won):
    """winner-only 0.07 settlement valuation of a position HELD to resolution.

    won  -> rem*(1-ev)*(1-0.07*ev)   (winner-only fee)
    lost -> -rem*ev                  (no fee on the losing leg)
    """
    if rem <= 0:
        return 0.0
    return rem * (1 - entry_price) * (1 - 0.07 * entry_price) if won else -rem * entry_price


def entry_fill(ts, ask, asksz, t_us, stake, spread, bid):
    """Top-of-book size-capped entry asof t_us+0 (caller passes already-latency-shifted t).

    NOTE: callers historically searchsorted at fire+LAT before calling; to keep that
    behaviour identical we expect t_us to ALREADY include the latency offset.
    Artifact ask sizes (==0/NaN) are resolved via resolve_size (carry-forward positive within
    300s, else next, else DEEP) so entries aren't dropped on price-only collector rows; the
    original underfill rule (skip if shares*ask < stake*0.5) is kept for comparability.
    Returns dict(entry_idx, ev, shares, a0, b0, entry_size_carried) or None (skip).
    """
    je = np.searchsorted(ts, t_us, "right") - 1
    if je < 0 or je >= len(ts):
        return None
    a0, b0 = ask[je], bid[je]
    # round() guards the float-boundary artifact (0.51-0.46=0.05000000000000004 > 0.05)
    # that silently rejected exact-5c spreads — same fix as live tv-engine 2026-06-11.
    if not (np.isfinite(a0) and np.isfinite(b0)) or round(float(a0 - b0), 4) > spread:
        return None
    s0, carried = resolve_size(ts, asksz, je)
    shares = min(stake / a0, s0)
    if shares * a0 < stake * 0.5:
        return None
    return dict(entry_idx=je, ev=float(a0), shares=float(shares), a0=float(a0), b0=float(b0),
                entry_size_carried=bool(carried))


def exit_fill(ts, bid, bidsz, entry_idx, ext_us, shares, entry_price, won, stale_us=STALE_US):
    """Corrected exit at ext_us. Returns dict:
        pnl_sold   : PnL from the sold lot (0 if no valid quote)
        pnl_held   : settlement value of the held remainder (whole position if invalid)
        pnl        : pnl_sold + pnl_held  (convenience combined)
        frac_held  : rem/shares (1.0 if no valid quote)
        sell_px    : bid used for the sold lot (nan if held_full)
        valid_quote: bool
        held_full  : bool (no usable quote -> whole position held)
        sold_sh    : shares actually sold on the book
        exit_size_carried: bool (bid size at the quote row was an artifact, resolved via carry)
    """
    jx = np.searchsorted(ts, ext_us, "right") - 1
    valid = (jx >= entry_idx) and (0 <= jx < len(ts)) and np.isfinite(bid[jx]) \
        and ((ext_us - ts[jx]) <= stale_us)
    if not valid:
        pnl_held = held_value(shares, entry_price, won)
        return dict(pnl_sold=0.0, pnl_held=pnl_held, pnl=pnl_held, frac_held=1.0,
                    sell_px=np.nan, valid_quote=False, held_full=True, sold_sh=0.0,
                    exit_size_carried=False)
    bsz, carried = resolve_size(ts, bidsz, jx)
    sold_sh = min(shares, bsz)
    rem = shares - sold_sh
    sell_px = float(bid[jx])
    pnl_sold = bpnl(sell_px, entry_price, sold_sh) if sold_sh > 0 else 0.0
    pnl_held = held_value(rem, entry_price, won)
    held_full = (sold_sh <= 0)
    return dict(pnl_sold=pnl_sold, pnl_held=pnl_held, pnl=pnl_sold + pnl_held,
                frac_held=(rem / shares if shares > 0 else 1.0), sell_px=sell_px,
                valid_quote=True, held_full=held_full, sold_sh=sold_sh,
                exit_size_carried=bool(carried))


def boot(v, nb=5000):
    v = np.asarray(v); v = v[np.isfinite(v)]
    if len(v) < 5:
        return (np.nan, np.nan)
    i = np.random.randint(0, len(v), (nb, len(v)))
    return tuple(np.percentile(v[i].mean(1), [2.5, 97.5]))


def cell(v):
    v = np.asarray(v); v = v[np.isfinite(v)]
    if len(v) < 5:
        return f"n={len(v):4d} (few)"
    t = v.mean() / v.std(ddof=1) * np.sqrt(len(v)) if v.std() > 0 else np.nan
    lo, hi = boot(v)
    return f"n={len(v):4d} $/tr={v.mean():+.3f} t={t:+.2f} CI=[{lo:+.3f},{hi:+.3f}]"
