"""
lag_taker_stoploss_sizing_ph2b_2026_05_29.py — PHASE 2B stop-loss + sizing sweep.

Foundation (PHASE 2A): BTC+ETH, |delta_bps|>=3, fire slot_start+5s, $25 L25 walk +
85ms + spread<=0.05, hold-to-resolution, 0.07 winner-only fee. Base: +$2.39/tr,
WR 65.4%, total +$2934, maxDD ~ -$492 (chrono).

This phase:
  1. STOP-LOSS sweep — track held-token mark intra-slot (L25 top-bid + chainlink-implied
     prob), test price-floor / binance-reversal / time stops. Exit = sell at current bid
     with 0.07-curve taker fee on the sale; if sell book empty -> hold to resolution.
  2. SIZING sweep — flat $25/$50/$100, kelly-tiered by delta_bps, confidence-proportional.

Fee (0.07 winner-only, matches foundation):
  pnl_won  = (1-vwap)*shares*(1-0.07*vwap)
  pnl_loss = -vwap*shares
Stop-sale pnl (realize at sell-vwap before resolution):
  pnl_sale = (sell_vwap - entry_vwap)*shares - 0.07*sell_vwap*(1-sell_vwap)*shares
  (taker fee on the SALE leg via the canonical poly curve; no winner-only logic on a
   mid-slot sale because it's just a position close, not a settlement).

NOTE: entry side already paid no separate fee in the foundation pnl_007 (winner-only).
For a stop SALE we still charge the realistic 0.07-curve taker fee on the exit notional,
per task constraint "0.07-curve taker fee on the sale".

Anchors / conventions: slug suffix = slot_start (s). slot_end = slot_start + WIN[tf].
fire_us = (slot_start+5)*1e6. Causal: only books/klines with ts <= probe_us used.

Usage: C:/Python314/python.exe strategy_lab/directional/lag_taker_stoploss_sizing_ph2b_2026_05_29.py
"""
from __future__ import annotations
import sys
import time
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))
from load import load_orderbook_l25_streaming, load_chainlink_asof  # noqa: E402

CANON = ROOT / "data" / "v4" / "canonical"
OUT = ROOT / "strategy_lab" / "directional" / "_results"
OUT.mkdir(parents=True, exist_ok=True)
FIRES = ROOT / "strategy_lab" / "lag_taker_fires_2026_05_29.parquet"

WIN = {"5m": 300, "15m": 900}
SYM = {"BTC": "BINANCE_SPOT_BTC_USDT", "ETH": "BINANCE_SPOT_ETH_USDT"}
ASSETS = ["BTC", "ETH"]
FEE_RATE = 0.07
SPREAD = 0.05
BASE_NOTIONAL = 25.0
LAT_US = 85_000           # 85ms entry latency (match foundation)
PROBE_STEP_S = 5          # intra-slot mark probe cadence (seconds)
MAX_STALE_US = 60_000_000

# stop-loss grids
PRICE_FLOORS = [0.10, 0.15, 0.20, 0.25]      # exit if held mark drops entry - floor
REV_BPS = [10, 20, 40]                        # binance reverses >= X bps vs entry dir
TIME_STOP_LEAD = 60                           # exit at slot_end - 60s if underwater


# ----------------------------------------------------------------------------
def binance_1s(asset):
    df = pd.read_parquet(CANON / "klines_1s.parquet",
                         columns=["time_period_start_us", "price_close", "symbol_id", "source", "period_id"])
    df = df[(df.symbol_id == SYM[asset]) & (df.source == "binance-spot-ws")
            & (df.period_id == "1SEC")].sort_values("time_period_start_us")
    return (df.time_period_start_us.values.astype(np.int64) + 1_000_000), df.price_close.values.astype(float)


def asof(ts, v, t):
    """Causal at-or-before lookup. t scalar or array (int64 us)."""
    t = np.atleast_1d(np.asarray(t, dtype=np.int64))
    i = np.searchsorted(ts, t, side="right") - 1
    out = np.full(len(t), np.nan)
    ok = i >= 0
    out[ok] = v[i[ok]]
    return out


def best_bid_asof(books, slug, outcome, probe_us):
    """Top-of-book bid (held-token mark) at-or-before probe_us. None if no snap/stale."""
    rec = books.get((slug, outcome))
    if rec is None:
        return None
    ts, ap, asz, bp, bsz = rec
    if len(ts) == 0:
        return None
    pos = int(np.searchsorted(ts, int(probe_us), side="right"))
    if pos == 0:
        return None
    i = pos - 1
    if int(probe_us) - int(ts[i]) > MAX_STALE_US:
        return None
    b = float(bp[i][0]) if (len(bp[i]) and np.isfinite(bp[i][0])) else np.nan
    return b


def sell_walk_bid(books, slug, outcome, probe_us, shares):
    """Walk bid side at-or-before probe_us for up to `shares`. Returns (vwap, sold, usd)."""
    rec = books.get((slug, outcome))
    if rec is None:
        return None
    ts, ap, asz, bp, bsz = rec
    if len(ts) == 0:
        return None
    pos = int(np.searchsorted(ts, int(probe_us), side="right"))
    if pos == 0:
        return None
    i = pos - 1
    if int(probe_us) - int(ts[i]) > MAX_STALE_US:
        return None
    prices, sizes = bp[i], bsz[i]
    rem = float(shares); tu = 0.0; tsh = 0.0
    for p, s in zip(prices, sizes):
        p = float(p); s = float(s)
        if not (np.isfinite(p) and np.isfinite(s)) or s <= 0 or p <= 0 or p >= 1:
            break
        take = min(s, rem)
        tu += take * p; tsh += take; rem -= take
        if rem <= 1e-9:
            break
    if tsh <= 1e-9:
        return None
    return tu / tsh, tsh, tu


def hold_pnl_007(vwap, shares, won):
    if won:
        return (1.0 - vwap) * shares * (1.0 - FEE_RATE * vwap)
    return -vwap * shares


def sale_pnl_007(entry_vwap, sell_vwap, shares):
    """Close position at sell_vwap before resolution; 0.07-curve taker fee on the sale."""
    fee = FEE_RATE * sell_vwap * (1.0 - sell_vwap) * shares
    return (sell_vwap - entry_vwap) * shares - fee


def max_dd(pnl):
    if len(pnl) == 0:
        return 0.0
    cum = np.cumsum(pnl); peak = np.maximum.accumulate(cum)
    return float((cum - peak).min())


def summ(pnl, label):
    pnl = np.asarray(pnl, dtype=float)
    n = len(pnl)
    m = float(pnl.mean()) if n else np.nan
    sd = float(pnl.std(ddof=1)) if n > 1 else np.nan
    se = sd / np.sqrt(n) if (n > 1 and sd) else np.nan
    t = (m / se) if se else np.nan
    w5 = float(np.mean(np.sort(pnl)[:max(1, int(0.05 * n))])) if n else np.nan
    sharpe = (m / sd) if (sd and sd > 0) else np.nan
    return dict(rule=label, n=n, wr=np.nan, dollar_tr=round(m, 4),
                total=round(float(pnl.sum()), 1), maxDD=round(max_dd(pnl), 1),
                worst5=round(w5, 3), sharpe=round(sharpe, 4),
                tot_neg=int((pnl < 0).sum()))


# ----------------------------------------------------------------------------
def main():
    t0 = time.time()
    F = pd.read_parquet(FIRES)
    F = F[(F.asset.isin(ASSETS)) & (F.delta_bps >= 3)].copy()
    F = F.sort_values("fire_us").reset_index(drop=True)
    print(f"[load] {len(F)} BTC+ETH >=3bps fires  t={time.time()-t0:.0f}s", flush=True)

    bz = {a: binance_1s(a) for a in ASSETS}
    cl = {a: load_chainlink_asof(a) for a in ASSETS}  # (ts_us, price)

    # Load books per asset (need bid side intra-slot, native 10Hz)
    books = {}
    for a in ASSETS:
        slugs = set(F[F.asset == a].slug)
        books[a] = load_orderbook_l25_streaming(a.lower(), slugs=slugs, subsample_1hz=False)
        print(f"[books {a}] {len(slugs)} slugs loaded  t={time.time()-t0:.0f}s", flush=True)

    # ---- per-fire intra-slot trajectory & precompute exit triggers ----
    recs = []
    for r in F.itertuples():
        a = r.asset
        slug = r.slug; outc = r.direction       # held token = the leading side we bought
        won = bool(r.won)
        entry_vwap = float(r.entry_vwap); shares = float(r.shares)
        slot_start = int(r.slot_start); slot_end = slot_start + WIN[r.tf]
        fire_us = int(r.fire_us)
        be, bc = bz[a]
        clts, clpx = cl[a]

        # binance ref price at fire (for reversal stop) + entry direction
        px_fire = float(asof(be, bc, fire_us)[0])
        is_up = (outc == "Up")

        # probe grid: fire_us+5s ... slot_end (intra-slot)
        probe_s = list(range(slot_start + 10, slot_end + 1, PROBE_STEP_S))
        probe_us = [(s * 1_000_000) + LAT_US for s in probe_s]

        # track held-token best-bid (mark) and binance reversal over the slot
        marks = []          # (probe_us, best_bid)
        rev_hit = {b: None for b in REV_BPS}    # first probe_us where reversal >= b bps
        floor_hit = {f: None for f in PRICE_FLOORS}  # first probe_us mark <= entry - f
        for ps, pu in zip(probe_s, probe_us):
            bid = best_bid_asof(books[a], slug, outc, pu)
            if bid is not None and np.isfinite(bid):
                marks.append((pu, bid))
                for f in PRICE_FLOORS:
                    if floor_hit[f] is None and bid <= (entry_vwap - f):
                        floor_hit[f] = pu
            # binance reversal: move AGAINST entry dir since fire
            pb = float(asof(be, bc, pu)[0])
            if np.isfinite(pb) and np.isfinite(px_fire) and px_fire > 0:
                mv_bps = (pb / px_fire - 1.0) * 1e4
                adverse = (-mv_bps) if is_up else (mv_bps)   # adverse = move against held dir
                for b in REV_BPS:
                    if rev_hit[b] is None and adverse >= b:
                        rev_hit[b] = pu

        # time-stop: at slot_end - TIME_STOP_LEAD, is mark underwater (< entry)?
        ts_probe_us = (slot_end - TIME_STOP_LEAD) * 1_000_000 + LAT_US
        ts_bid = best_bid_asof(books[a], slug, outc, ts_probe_us)

        recs.append(dict(
            idx=r.Index, asset=a, slug=slug, tf=r.tf, delta_bps=float(r.delta_bps),
            entry_vwap=entry_vwap, shares=shares, won=won,
            base_pnl=hold_pnl_007(entry_vwap, shares, won),
            slot_end=slot_end, outc=outc,
            floor_hit=floor_hit, rev_hit=rev_hit,
            ts_probe_us=ts_probe_us, ts_bid=(float(ts_bid) if ts_bid is not None else np.nan),
        ))
    print(f"[trajectory] {len(recs)} fires probed  t={time.time()-t0:.0f}s", flush=True)

    # ---------- helper: realize a stop at a given exit_us (sell at bid there) ----------
    def realize_stop(rec, exit_us):
        """Sell held shares at bid asof exit_us. Returns pnl, or hold pnl if no book."""
        sw = sell_walk_bid(books[rec["asset"]], rec["slug"], rec["outc"], exit_us, rec["shares"])
        if sw is None:
            return rec["base_pnl"], False    # cannot exit -> hold
        sv, sold, _ = sw
        # if partial fill of bid book: realize sold portion at sale, remainder holds
        rem = rec["shares"] - sold
        pnl = sale_pnl_007(rec["entry_vwap"], sv, sold)
        if rem > 1e-6:
            pnl += hold_pnl_007(rec["entry_vwap"], rem, rec["won"])
        return pnl, True

    # ================= STOP-LOSS SWEEP =================
    sl_rows = []
    base_pnls = np.array([rc["base_pnl"] for rc in recs])
    sl_rows.append({**summ(base_pnls, "HOLD-to-resolution (base)"),
                    "wr": round(100 * np.mean([rc["won"] for rc in recs]), 1),
                    "n_stopped": 0})

    # price-floor stops
    for f in PRICE_FLOORS:
        pnls = []; n_stop = 0; wins = 0
        for rc in recs:
            eu = rc["floor_hit"][f]
            if eu is not None:
                p, ok = realize_stop(rc, eu)
                if ok:
                    n_stop += 1
                pnls.append(p)
            else:
                pnls.append(rc["base_pnl"]); wins += int(rc["won"])
        pnls = np.array(pnls)
        row = summ(pnls, f"price-floor stop @ entry-{f:.2f}")
        row["wr"] = round(100 * (pnls > 0).mean(), 1)
        row["n_stopped"] = n_stop
        sl_rows.append(row)

    # binance-reversal stops
    for b in REV_BPS:
        pnls = []; n_stop = 0
        for rc in recs:
            eu = rc["rev_hit"][b]
            if eu is not None:
                p, ok = realize_stop(rc, eu)
                if ok:
                    n_stop += 1
                pnls.append(p)
            else:
                pnls.append(rc["base_pnl"])
        pnls = np.array(pnls)
        row = summ(pnls, f"binance-reversal stop >= {b}bps")
        row["wr"] = round(100 * (pnls > 0).mean(), 1)
        row["n_stopped"] = n_stop
        sl_rows.append(row)

    # time stop: exit at slot_end-60s if underwater (mark < entry_vwap)
    pnls = []; n_stop = 0
    for rc in recs:
        if np.isfinite(rc["ts_bid"]) and rc["ts_bid"] < rc["entry_vwap"]:
            p, ok = realize_stop(rc, rc["ts_probe_us"])
            if ok:
                n_stop += 1
            pnls.append(p)
        else:
            pnls.append(rc["base_pnl"])
    pnls = np.array(pnls)
    row = summ(pnls, f"time stop @ slot_end-{TIME_STOP_LEAD}s if underwater")
    row["wr"] = round(100 * (pnls > 0).mean(), 1)
    row["n_stopped"] = n_stop
    sl_rows.append(row)

    SL = pd.DataFrame(sl_rows)[["rule", "n", "n_stopped", "wr", "dollar_tr", "total",
                                "maxDD", "worst5", "sharpe"]]
    SL.to_csv(OUT / "ph2b_stoploss.csv", index=False)

    # pick best stop = lowest |maxDD| with dollar_tr >= 2.0
    cand = SL[(SL.dollar_tr >= 2.0) & (SL.rule != "HOLD-to-resolution (base)")]
    if len(cand):
        best_stop_label = cand.loc[cand.maxDD.idxmax(), "rule"]   # idxmax of negative = least negative
    else:
        best_stop_label = "HOLD-to-resolution (base)"

    # rebuild best-stop pnl vector (per-fire) for sizing-on-best-stop
    def stop_pnl_vector(label):
        if label.startswith("HOLD"):
            return base_pnls.copy(), None
        out = []
        for rc in recs:
            eu = None
            if label.startswith("price-floor"):
                f = float(label.split("entry-")[1])
                eu = rc["floor_hit"][f]
            elif label.startswith("binance-reversal"):
                b = int(label.split(">= ")[1].replace("bps", ""))
                eu = rc["rev_hit"][b]
            elif label.startswith("time stop"):
                if np.isfinite(rc["ts_bid"]) and rc["ts_bid"] < rc["entry_vwap"]:
                    eu = rc["ts_probe_us"]
            if eu is not None:
                p, _ = realize_stop(rc, eu)
                out.append(p)
            else:
                out.append(rc["base_pnl"])
        return np.array(out), label

    best_stop_pnl, _ = stop_pnl_vector(best_stop_label)

    # ================= SIZING SWEEP =================
    # Sizing scales pnl linearly with notional (book-walk vwap ~stable at $25-100 on these
    # books; we scale shares -> pnl proportionally as a first-order model, NOTED as caveat).
    delta = np.array([rc["delta_bps"] for rc in recs])
    wons = np.array([rc["won"] for rc in recs])

    def kelly_tier_mult(d):
        if d < 5:   return 1.0
        if d < 8:   return 2.0
        if d < 12:  return 3.0
        return 4.0
    ktier = np.array([kelly_tier_mult(d) for d in delta])

    # confidence-proportional: size ∝ (pred_WR - breakeven). pred_WR from delta-bucket WR
    # (in-sample bucket WR as the confidence proxy); breakeven ~ mean vwap.
    bucket_edges = [3, 5, 8, 12, 1e9]
    bwr = {}
    for lo, hi in zip(bucket_edges[:-1], bucket_edges[1:]):
        m = (delta >= lo) & (delta < hi)
        bwr[(lo, hi)] = wons[m].mean() if m.sum() else np.nan
    mean_vwap = np.mean([rc["entry_vwap"] for rc in recs])
    conf_mult = []
    for d in delta:
        for lo, hi in zip(bucket_edges[:-1], bucket_edges[1:]):
            if lo <= d < hi:
                edge = max(0.0, (bwr[(lo, hi)] - mean_vwap))
                conf_mult.append(1.0 + 6.0 * edge)   # scale: 0 edge ->1x, 0.10 edge ->1.6x
                break
    conf_mult = np.array(conf_mult)

    def sizing_summary(pnl_at_25, mult, scheme):
        scaled = pnl_at_25 * mult
        d = summ(scaled, scheme)
        # growth-optimal check: realized log-growth on a bankroll where each bet is the
        # scaled notional; approximate cumulative multiplicative growth on $10k bankroll.
        bank = 10000.0; eq = [bank]
        for p in scaled:
            bank += p; eq.append(bank)
        growth = round(bank / 10000.0, 4)
        avg_notional = round(BASE_NOTIONAL * float(np.mean(mult)), 1)
        return dict(scheme=scheme, n=d["n"], total=d["total"], dollar_tr=d["dollar_tr"],
                    maxDD=d["maxDD"], sharpe=d["sharpe"], final_bank=round(bank, 0),
                    growth_x=growth, avg_notional=avg_notional)

    ones = np.ones(len(recs))
    sz_rows = []
    for base_lbl, pvec in [("base HOLD", base_pnls), (f"best-stop[{best_stop_label}]", best_stop_pnl)]:
        sz_rows.append({**sizing_summary(pvec, ones * 1.0, f"{base_lbl} | flat $25"), "on": base_lbl})
        sz_rows.append({**sizing_summary(pvec, ones * 2.0, f"{base_lbl} | flat $50"), "on": base_lbl})
        sz_rows.append({**sizing_summary(pvec, ones * 4.0, f"{base_lbl} | flat $100"), "on": base_lbl})
        sz_rows.append({**sizing_summary(pvec, ktier, f"{base_lbl} | kelly-tier delta"), "on": base_lbl})
        sz_rows.append({**sizing_summary(pvec, conf_mult, f"{base_lbl} | confidence-prop"), "on": base_lbl})
    SZ = pd.DataFrame(sz_rows)[["scheme", "n", "total", "dollar_tr", "maxDD", "sharpe",
                                "avg_notional", "final_bank", "growth_x"]]
    SZ.to_csv(OUT / "ph2b_sizing.csv", index=False)

    # delta-bucket WR table (supports kelly-tier rationale)
    bk_rows = []
    for (lo, hi) in zip(bucket_edges[:-1], bucket_edges[1:]):
        m = (delta >= lo) & (delta < hi)
        if m.sum() == 0:
            continue
        bp = base_pnls[m]
        bk_rows.append(dict(bucket=f"[{lo},{hi if hi < 1e8 else 'inf'})", n=int(m.sum()),
                            wr=round(100 * wons[m].mean(), 1), dollar_tr=round(bp.mean(), 3),
                            kelly_mult=kelly_tier_mult(lo)))
    BK = pd.DataFrame(bk_rows)
    BK.to_csv(OUT / "ph2b_delta_buckets.csv", index=False)

    # ---------- console ----------
    pd.set_option("display.width", 220)
    print("\n" + "=" * 96)
    print("STOP-LOSS SWEEP (BTC+ETH >=3bps, 0.07 fee on sales)")
    print("=" * 96)
    print(SL.to_string(index=False))
    print(f"\n>>> best stop (|maxDD| min with $tr>=2.0): {best_stop_label}")
    print("\n" + "=" * 96)
    print("DELTA-BUCKET WR (kelly-tier rationale)")
    print("=" * 96)
    print(BK.to_string(index=False))
    print(f"  (mean entry vwap = {mean_vwap:.3f}; bucket WR = confidence proxy)")
    print("\n" + "=" * 96)
    print("SIZING SWEEP (linear-scaled pnl; bankroll $10k)")
    print("=" * 96)
    print(SZ.to_string(index=False))
    print(f"\nwrote {OUT/'ph2b_stoploss.csv'}, ph2b_sizing.csv, ph2b_delta_buckets.csv")
    print(f"total {time.time()-t0:.0f}s")

    # return artifacts dict for the report writer
    return SL, SZ, BK, best_stop_label


if __name__ == "__main__":
    main()
