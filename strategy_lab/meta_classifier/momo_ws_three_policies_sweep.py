"""
DEPRECATED FEE MODEL — DO NOT QUOTE PnL FROM THIS FILE FORWARD.

This file uses the legacy `FEE_RATE = 0.02` ("2% on profit only, winning leg")
approximation. The real Polymarket fee is:

    fee = C × feeRate × p × (1 − p)

charged on EVERY fill (not just the winner). For crypto markets feeRate = 0.07.
Use `strategy_lab/fees.py` (`poly_fee_usd`, `poly_maker_rebate_usd`) instead.

Kept here for historical reproducibility only. Numbers produced by this file
diverge materially from real Polymarket settlements — re-run via
`engine_v2.fill_at_book` + `fees.poly_fee_usd` before any decision.
"""

"""Momo backtest — sweep fire-time offsets × 3 exit policies (HOLD / HEDGE / SELL).

Uses 25-level WS L25 parquet books. Strict asof.

Exit policies (mirrors production controller):
  HOLD       — buy at fire, hold to chainlink resolve.
  HEDGE_HOLD — buy at fire. On_tick (10s): if Binance asset reverts ≥5bp from
               close@ws, walk opposite-outcome ASKs for ``shares * top_ask`` USD
               to lock equal payoff regardless of resolution. If hedge can't
               fill (book empty or shallow), fall through to HOLD.
  SELL_BID   — buy at fire. On_tick (10s): if reverted ≥5bp, walk own-outcome
               BIDs for ``shares`` to liquidate at the bid. If can't fill, HOLD.

Fee model: 2% on positive profit only (winning side).

Fire offsets to sweep: {0, 30, 60, 90, 120, 150, 180}
  Note: offsets 0 & 30 require ret_2m at (ws-60, ws+60) — earliest valid is +60s
  wall-clock. Earlier rows still simulated for reference but flagged invalid.
"""
from __future__ import annotations
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "strategy_lab"))
from book_walk import book_walk_fill  # noqa

REFRESH = ROOT / "data" / "v4" / "refresh_2026_05_06"
CACHE = REFRESH / "cache"
OUT = ROOT / "strategy_lab" / "results" / "meta_classifier"
OUT.mkdir(parents=True, exist_ok=True)

LEVELS = 25
NOTIONAL = 25.0
FEE = 0.02
SPREAD_FILTER = {"BTC": 0.02, "ETH": 0.02, "SOL": 0.025}
GATE_Q = 0.90
LOOKBACK = 14
OFFSETS_S = [0, 30, 60, 90, 120, 150, 180]
TICK_S = 10
REV_BP_THRESHOLD = 5.0  # production default

ASSET_BIN = {"BTC": "BINANCE_SPOT_BTC_USDT", "ETH": "BINANCE_SPOT_ETH_USDT", "SOL": "BINANCE_SPOT_SOL_USDT"}
ASSET_OKX = {"BTC": "OKX_SPOT_BTC_USDT", "ETH": "OKX_SPOT_ETH_USDT", "SOL": "OKX_SPOT_SOL_USDT"}


def load_klines() -> dict[str, pd.DataFrame]:
    df = pd.read_csv(REFRESH / "klines_full.csv")
    df["ts_s"] = (df.time_period_start_us // 1_000_000).astype("int64")
    out = {}
    for a in ("BTC","ETH","SOL"):
        b = df[df.symbol_id == ASSET_BIN[a]][["ts_s","price_close"]].copy(); b["src"]="b"
        o = df[df.symbol_id == ASSET_OKX[a]][["ts_s","price_close"]].copy(); o["src"]="o"
        c = pd.concat([b,o]).sort_values(["ts_s","src"]).drop_duplicates("ts_s",keep="first").sort_values("ts_s").reset_index(drop=True)
        out[a] = c[["ts_s","price_close"]]
    return out


def asof_strict(k, ts):
    end_us = (k.ts_s.astype("int64") + 60).values * 1_000_000
    target = int(ts) * 1_000_000
    idx = int(np.searchsorted(end_us, target, side="right")) - 1
    return float("nan") if idx < 0 else float(k.price_close.iloc[idx])


def load_universe() -> pd.DataFrame:
    m = pd.read_csv(REFRESH / "markets_full.csv")
    r = pd.read_csv(REFRESH / "market_resolutions_full.csv")[["slug","outcome"]]
    df = m.merge(r, on="slug", how="inner", suffixes=("_m","")).copy()
    df = df.dropna(subset=["outcome"])
    df = df[df.ticker.isin(["BTC","ETH","SOL"]) & df.timeframe.isin(["5m","15m"])].copy()
    df["ws"] = df.slug.str.extract(r"-(\d+)$")[0].astype("int64")
    df["asset"] = df.ticker
    df["tf"] = df.timeframe
    df["window_s"] = df.tf.map({"5m": 300, "15m": 900})
    return df[["slug","asset","tf","ws","window_s","outcome"]].reset_index(drop=True)


def compute_ret_2m(uni, klines):
    out = []
    for asset, ws in zip(uni.asset.values, uni.ws.values):
        c0 = asof_strict(klines[asset], int(ws) - 60)
        c2 = asof_strict(klines[asset], int(ws) + 60)
        if math.isfinite(c0) and math.isfinite(c2) and c0 > 0 and c2 > 0:
            out.append(math.log(c2 / c0))
        else:
            out.append(float("nan"))
    return out


def compute_thresholds(uni: pd.DataFrame) -> dict:
    out: dict = {}
    uni = uni.copy(); uni["day"] = pd.to_datetime(uni.ws, unit="s").dt.floor("D")
    for (a, t), g in uni.groupby(["asset","tf"]):
        g = g.sort_values("ws").reset_index(drop=True)
        for day, _ in g.groupby("day"):
            cutoff_lo = day - pd.Timedelta(days=LOOKBACK)
            train = g[(g.day >= cutoff_lo) & (g.day < day)]
            samples = train["abs_ret_2m"].dropna().values
            out[(a,t,str(day.date()))] = float(np.quantile(samples, GATE_Q)) if len(samples) >= 50 else float("nan")
    return out


def load_books_for_slugs(asset: str, slugs: set) -> dict:
    """Returns {(slug, outcome): (ts_us[N], ask_p[N,25], ask_s[N,25], bid_p[N,25], bid_s[N,25])}"""
    pf = pq.ParquetFile(CACHE / f"{asset.lower()}_orderbook_L25.parquet")
    cols_keep = ["timestamp_us","slug","outcome"] + \
                [f"ask_price_{i}" for i in range(LEVELS)] + [f"ask_size_{i}" for i in range(LEVELS)] + \
                [f"bid_price_{i}" for i in range(LEVELS)] + [f"bid_size_{i}" for i in range(LEVELS)]
    chunks = []
    for batch in pf.iter_batches(batch_size=500_000, columns=cols_keep):
        df = batch.to_pandas()
        flt = df[df.slug.isin(slugs)]
        if len(flt):
            chunks.append(flt)
    raw = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()
    if raw.empty:
        return {}
    out: dict = {}
    cols_ap = [f"ask_price_{i}" for i in range(LEVELS)]
    cols_as = [f"ask_size_{i}"  for i in range(LEVELS)]
    cols_bp = [f"bid_price_{i}" for i in range(LEVELS)]
    cols_bs = [f"bid_size_{i}"  for i in range(LEVELS)]
    raw = raw.sort_values(["slug","outcome","timestamp_us"])
    for (slug, oc), sub in raw.groupby(["slug","outcome"]):
        ts = sub.timestamp_us.values.astype("int64")
        ap = sub[cols_ap].to_numpy(dtype=float); as_ = sub[cols_as].to_numpy(dtype=float)
        bp = sub[cols_bp].to_numpy(dtype=float); bs = sub[cols_bs].to_numpy(dtype=float)
        out[(slug, oc)] = (ts, ap, as_, bp, bs)
    return out


def find_book(idx, slug, outcome, target_us, max_dt_us=10_000_000):
    rec = idx.get((slug, outcome))
    if rec is None:
        return None
    ts, ap, as_, bp, bs = rec
    pos = int(np.searchsorted(ts, target_us))
    candidates = []
    if pos > 0: candidates.append(pos-1)
    if pos < len(ts): candidates.append(pos)
    best_i = None; best_dt = float("inf")
    for i in candidates:
        dt = abs(int(ts[i]) - target_us)
        if dt < best_dt:
            best_dt = dt; best_i = i
    if best_i is None or best_dt > max_dt_us:
        return None
    return ap[best_i], as_[best_i], bp[best_i], bs[best_i], best_dt


def sell_at_bid(bid_p, bid_s, shares):
    """Walk BIDs to liquidate `shares` at best price (descending bids)."""
    remaining = float(shares); total_usd = 0.0; total_shares = 0.0
    for p, s in zip(bid_p, bid_s):
        if not (math.isfinite(p) and math.isfinite(s)) or s <= 0 or p <= 0 or p >= 1:
            break
        if s >= remaining:
            total_usd += remaining * p; total_shares += remaining; remaining = 0; break
        total_usd += s * p; total_shares += s; remaining -= s
    if total_shares <= 0:
        return float("nan"), 0.0, 0.0
    return total_usd / total_shares, total_shares, total_usd


def simulate_trade(r, klines, books_idx, offset_s, policy):
    """Simulate one trade at given offset and policy. Returns dict or None if skip."""
    fire_us = int(r.ws + offset_s) * 1_000_000
    held = "Up" if r.signal == "UP" else "Down"
    other = "Down" if r.signal == "UP" else "Up"
    asset_idx = books_idx[r.asset]

    # ENTRY: walk asks at fire-time for held outcome
    b = find_book(asset_idx, r.slug, held, fire_us)
    if b is None:
        return None
    ap, as_, bp, bs, dt_entry = b
    ask0 = ap[0] if math.isfinite(ap[0]) else float("nan")
    bid0 = bp[0] if math.isfinite(bp[0]) else float("nan")
    if math.isfinite(ask0) and math.isfinite(bid0) and (ask0 - bid0) > SPREAD_FILTER[r.asset]:
        return None
    vwap_e, shares_e, usd_e, _, under = book_walk_fill(ap, as_, NOTIONAL)
    if shares_e <= 0 or (under and usd_e < NOTIONAL * 0.5):
        return None

    # No exit policy → HOLD
    won = (r.signal == "UP" and r.outcome == "Up") or (r.signal == "DOWN" and r.outcome == "Down")
    if policy == "HOLD":
        if won:
            profit = shares_e * 1.0 - usd_e
            fee = profit * FEE if profit > 0 else 0.0
            pnl = profit - fee
        else:
            pnl = -usd_e
        return dict(slug=r.slug, asset=r.asset, tf=r.tf, ws=int(r.ws), offset_s=offset_s, policy=policy,
                    signal=r.signal, outcome=r.outcome, won=int(won), exit_reason="hold",
                    vwap_e=vwap_e, shares=shares_e, usd_spent=usd_e, exit_at_t=None, pnl=pnl)

    # HEDGE_HOLD or SELL_BID — iterate ticks, check rev_bp on Binance
    asset_at_ws = asof_strict(klines[r.asset], int(r.ws))  # rev_bp anchor = close@ws (production convention)
    if not math.isfinite(asset_at_ws) or asset_at_ws <= 0:
        # fall back to HOLD
        if won:
            profit = shares_e * 1.0 - usd_e
            fee = profit * FEE if profit > 0 else 0.0; pnl = profit - fee
        else:
            pnl = -usd_e
        return dict(slug=r.slug, asset=r.asset, tf=r.tf, ws=int(r.ws), offset_s=offset_s, policy=policy,
                    signal=r.signal, outcome=r.outcome, won=int(won), exit_reason="hold_no_anchor",
                    vwap_e=vwap_e, shares=shares_e, usd_spent=usd_e, exit_at_t=None, pnl=pnl)

    resolve_us = int(r.ws + r.window_s - 60) * 1_000_000  # resolves at ws+window-60
    exit_event = None
    t_us = fire_us + TICK_S * 1_000_000
    while t_us <= resolve_us:
        a_now = asof_strict(klines[r.asset], t_us // 1_000_000)
        if not math.isfinite(a_now):
            t_us += TICK_S * 1_000_000; continue
        rev_bp = (a_now - asset_at_ws) / asset_at_ws * 1e4
        triggered = (r.signal == "UP" and rev_bp <= -REV_BP_THRESHOLD) or \
                    (r.signal == "DOWN" and rev_bp >= REV_BP_THRESHOLD)
        if triggered:
            if policy == "HEDGE_HOLD":
                opp = find_book(asset_idx, r.slug, other, t_us)
                if opp is not None:
                    h_ap, h_as, _, _, _ = opp
                    h_top = h_ap[0] if math.isfinite(h_ap[0]) else float("nan")
                    if math.isfinite(h_top) and 0 < h_top < 1:
                        target_h_usd = shares_e * float(h_top)
                        vwap_h, shares_h, usd_h, _, _ = book_walk_fill(h_ap, h_as, target_h_usd)
                        if shares_h > 0:
                            exit_event = ("hedge", t_us, vwap_h, shares_h, usd_h); break
            elif policy == "SELL_BID":
                own = find_book(asset_idx, r.slug, held, t_us)
                if own is not None:
                    _, _, sb_p, sb_s, _ = own
                    vwap_s, shares_s, gross_s = sell_at_bid(sb_p, sb_s, shares_e)
                    if shares_s > 0:
                        exit_event = ("sell", t_us, vwap_s, shares_s, gross_s); break
        t_us += TICK_S * 1_000_000

    # Compute PnL based on exit
    if exit_event is None:
        if won:
            profit = shares_e * 1.0 - usd_e
            fee = profit * FEE if profit > 0 else 0.0; pnl = profit - fee
        else:
            pnl = -usd_e
        return dict(slug=r.slug, asset=r.asset, tf=r.tf, ws=int(r.ws), offset_s=offset_s, policy=policy,
                    signal=r.signal, outcome=r.outcome, won=int(won), exit_reason="hold",
                    vwap_e=vwap_e, shares=shares_e, usd_spent=usd_e, exit_at_t=None, pnl=pnl)
    kind, t_exit, vwap_x, shares_x, val_x = exit_event
    if kind == "hedge":
        cost_total = usd_e + val_x
        if won:
            gross = shares_e * 1.0
        else:
            gross = shares_x * 1.0
        profit = gross - cost_total
        fee = profit * FEE if profit > 0 else 0.0
        pnl = profit - fee
        return dict(slug=r.slug, asset=r.asset, tf=r.tf, ws=int(r.ws), offset_s=offset_s, policy=policy,
                    signal=r.signal, outcome=r.outcome, won=int(won), exit_reason=kind,
                    vwap_e=vwap_e, shares=shares_e, usd_spent=usd_e,
                    exit_at_t=int(t_exit), exit_vwap=vwap_x, hedge_shares=shares_x, hedge_usd=val_x, pnl=pnl)
    # SELL
    profit = val_x - usd_e
    fee = profit * FEE if profit > 0 else 0.0
    pnl = profit - fee
    return dict(slug=r.slug, asset=r.asset, tf=r.tf, ws=int(r.ws), offset_s=offset_s, policy=policy,
                signal=r.signal, outcome=r.outcome, won=int(won), exit_reason=kind,
                vwap_e=vwap_e, shares=shares_e, usd_spent=usd_e,
                exit_at_t=int(t_exit), exit_vwap=vwap_x, sell_gross=val_x, pnl=pnl)


def main():
    print("[1] klines + universe + ret_2m…")
    klines = load_klines()
    uni = load_universe()
    uni["ret_2m"] = compute_ret_2m(uni, klines)
    uni["abs_ret_2m"] = uni.ret_2m.abs()

    print("[2] thresholds…")
    thr = compute_thresholds(uni)
    uni["day"] = pd.to_datetime(uni.ws, unit="s").dt.floor("D")
    uni["threshold"] = uni.apply(lambda r: thr.get((r.asset, r.tf, str(r.day.date())), float("nan")), axis=1)
    gated = uni[(uni.abs_ret_2m >= uni.threshold)].copy()
    gated["signal"] = gated.ret_2m.apply(lambda x: "UP" if x > 0 else "DOWN")
    print(f"    gated: {len(gated)}")

    print("[3] streaming parquet books per asset (this is slow — ~3 min)…")
    books_idx = {}
    for a in ("BTC","ETH","SOL"):
        slugs = set(gated[gated.asset == a].slug.unique())
        print(f"    {a}: {len(slugs)} slugs…")
        books_idx[a] = load_books_for_slugs(a, slugs)
        n_keys = len(books_idx[a])
        n_total_snaps = sum(len(rec[0]) for rec in books_idx[a].values())
        print(f"      {n_keys} (slug,outcome) keys, {n_total_snaps:,} snapshots")

    print("[4] simulating across {len(OFFSETS_S)} offsets × 3 policies…")
    rows = []
    for off in OFFSETS_S:
        for policy in ("HOLD", "HEDGE_HOLD", "SELL_BID"):
            n_sim = 0
            for r in gated.itertuples(index=False):
                res = simulate_trade(r, klines, books_idx, off, policy)
                if res is not None:
                    rows.append(res); n_sim += 1
            print(f"    offset={off:>3}s policy={policy:<10} fires={n_sim}")
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "momo_ws_three_policies_sweep_per_trade.csv", index=False)

    # Aggregate per (asset, tf, offset, policy)
    agg = df.groupby(["asset","tf","offset_s","policy"]).agg(
        n=("pnl","size"), wins=("won","sum"), hit=("won","mean"),
        pnl_total=("pnl","sum"), pnl_mean=("pnl","mean"), pnl_std=("pnl","std"),
        avg_vwap=("vwap_e","mean"),
    ).reset_index()
    agg.to_csv(OUT / "momo_ws_three_policies_sweep_aggregated.csv", index=False)

    # Cross-policy summary at each offset
    print(f"\n=== TOTAL PnL across all 6 cells, by offset × policy ===")
    pivot = df.groupby(["offset_s","policy"]).pnl.sum().unstack().round(0)
    print(pivot.to_string())

    print(f"\n=== Mean PnL/trade across all 6 cells, by offset × policy ===")
    pivot_mean = df.groupby(["offset_s","policy"]).pnl.mean().unstack().round(3)
    print(pivot_mean.to_string())

    print(f"\n=== Per-cell PnL_total, offset=60s (recommended fire-time) ===")
    sub60 = df[df.offset_s == 60]
    pivot60 = sub60.groupby(["asset","tf","policy"]).pnl.sum().unstack().round(0)
    print(pivot60.to_string())

    # Exit-event breakdown for HEDGE/SELL at offset=60
    print(f"\n=== Exit reasons at offset=60s ===")
    print(sub60.groupby(["policy","exit_reason"]).size().unstack(fill_value=0))


if __name__ == "__main__":
    main()
