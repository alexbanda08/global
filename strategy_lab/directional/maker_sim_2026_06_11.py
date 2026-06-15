"""
CONSERVATIVE MAKER-FILL SIMULATION — Polymarket binary up/down (2026-06-11).

Two pre-registered maker strategies, rebate income modeled, conservative (under-filling) fill rule.
BBO window Mar30-Apr21; coins BTC/ETH/SOL/XRP (only these have aliplayer trades).

DATA (verified schemas this session):
  - load_orderbook_bbo(coin, slugs=, min_ts_us=, max_ts_us=, columns=) -> top-of-book quotes.
    cols: timestamp_us, slug, outcome(token Up/Down), best_bid, best_ask, best_bid_size, best_ask_size.
    ~47% of size==0 = COLLECTOR ARTIFACT -> resolve via resolve_size (carry-forward, 300s).
  - load_trades_hf(coin, bbo=True) -> aliplayer ticks (Mar30-Apr21, on D:). cols:
    timestamp_us, slug, outcome(token), side(BUY/SELL), price(token price 0-1), size_usdc, spot_price, timeframe.
    VERIFIED THIS SESSION: `side` is the TAKER aggressor side (BUY prints 63% >= ask; SELL prints 68% <= bid).
    shares = size_usdc / price.
  - resolutions_hf.parquet: slug, ticker, timeframe, slot_start_us, slot_end_us, outcome(Up/Down).
  - klines_1s.parquet filtered BINANCE_SPOT_{COIN}_USDT for lag signal (5s return -> delta_bps, lead).

CONSERVATIVE MAKER FILL RULE (under-fills on purpose):
  A resting BUY at price P, size Q (shares), posted at t0:
    fills only from TAKER SELL prints (side=='SELL') with trade_price <= P AND timestamp > t0.
    QUEUE_AHEAD = resting best_bid_size at t0 (resolve_size) if P == best_bid (we JOIN behind it);
                  0 if P > best_bid (we IMPROVE; requires P < best_ask).
    Our fill = max(0, cumulative SELL-print shares with price<=P after t0 - QUEUE_AHEAD), capped at Q.
  Symmetric for resting SELL vs taker BUY prints at price >= P, queue = best_ask_size at t0.
  Partial fills tracked. (side IS usable here -> no all-prints fallback needed.)

REBATE: rebate_per_filled_share = k * 0.07 * P * (1-P), k in {0, 0.05, 0.20}. Maker pays $0 fee.
  (k=0.20 = sole-maker ceiling of the 20% crypto pool; k=0.05 ~ competitive.)

EXPERIMENTS:
  A. Maker ENTRY for the open scalp (re-test 06-05 "maker entry dead" w/ rebate + corrected exit).
     Candidates: delta_bps>=3, fire=slot_start+5s, lead side. Post JOIN bid at best_bid on lead token
     at fire+85ms, $25, rest to fire+30s, cancel unfilled. If filled >=50%: exit via corrected exit_fill
     (taker sell at fire+60s) on FILLED shares. Compare to TAKER baseline on SAME candidate set.
  B. Late-window thin-book maker bid on the FAVORED (oracle) side. At T-60s and T-30s before slot_end,
     z = ln(px/strike)/(sigma*sqrt(tau)); if |z|>=2 post bid on favored token at min(best_bid,0.95)
     (variant: best_bid-0.01), $25, rest to slot_end-5s, cancel unfilled. Fills -> hold to resolution
     (winner-only 0.07 fee + rebate).

OUTPUTS: fill_rate; WR(filled) vs WR(all candidates) [adverse-selection delta]; maker $/tr at k grid;
  taker baseline (A); per coin-tf + pooled; time-split halves (B). Checkpoints to _results/.
"""
import sys, os, math, warnings
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings("ignore"); np.random.seed(0)
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data/v4/canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab/directional"))
from load import load_orderbook_bbo, load_trades_hf
from scalp_fill_lib_2026_06_10 import resolve_size, exit_fill, held_value, bpnl, boot, cell
from scipy.stats import norm
CANON = ROOT / "data/v4/canonical"
RES = ROOT / "strategy_lab/directional/_results"
RES.mkdir(parents=True, exist_ok=True)

SPREAD = 0.05; STAKE = 25.0; LAT_US = 85_000
A_REST_US = 30_000_000       # A: rest window 30s
B_REST_END_OFF_US = 5_000_000  # B: cancel at slot_end-5s
VOL_LB = 300; SPREAD_LATE = 0.10
K_GRID = [0.0, 0.05, 0.20]
COINS = os.environ.get("MK_COINS", "BTC,ETH,SOL,XRP").split(",")
LIMIT = int(os.environ.get("MK_LIMIT", "0"))   # first N slugs per coin (smoke)
TAG = os.environ.get("MK_TAG", "")
WIN = {"BTC": ("2026-03-30", "2026-04-21"), "ETH": ("2026-03-30", "2026-04-21"),
       "SOL": ("2026-03-30", "2026-04-21"), "XRP": ("2026-04-07", "2026-04-21")}
BCOLS = ["timestamp_us", "slug", "outcome", "best_bid", "best_ask", "best_bid_size", "best_ask_size"]


def rebate(P, sh, k):
    return k * 0.07 * P * (1.0 - P) * sh


def klines(coin):
    sym = f"BINANCE_SPOT_{coin.upper()}_USDT"
    df = pd.read_parquet(CANON / "klines_1s.parquet",
                         columns=["symbol_id", "time_period_start_us", "price_close"],
                         filters=[("symbol_id", "==", sym)])
    df = df.sort_values("time_period_start_us").drop_duplicates("time_period_start_us")
    return df.time_period_start_us.values.astype("int64"), df.price_close.values.astype(float)


def asof(ts, v, t):
    i = np.searchsorted(ts, t, "right") - 1
    return np.where(i >= 0, v[np.clip(i, 0, len(v) - 1)], np.nan)


def maker_buy_fill(P, Q, t0_us, queue_ahead, sell_ts, sell_px, sell_sh, deadline_us):
    """Conservative resting-BUY fill from taker SELL prints (price<=P after t0).
    Returns (filled_conservative, filled_upperbound):
      - conservative: subtract FULL queue_ahead (spec rule, lower bound on fills).
      - upperbound:   queue_ahead=0 (we are at front / IMPROVE), upper bound on fills.
    Both capped at Q."""
    if not np.isfinite(P) or Q <= 0:
        return 0.0, 0.0
    m = (sell_ts > t0_us) & (sell_ts <= deadline_us) & (sell_px <= P + 1e-9)
    if not m.any():
        return 0.0, 0.0
    cum = sell_sh[m].sum()
    cons = float(min(Q, max(0.0, cum - max(0.0, queue_ahead))))
    ub = float(min(Q, cum))
    return cons, ub


def maker_sell_fill(P, Q, t0_us, queue_ahead, buy_ts, buy_px, buy_sh, deadline_us):
    """Conservative resting-SELL fill from taker BUY prints (price>=P)."""
    if not np.isfinite(P) or Q <= 0:
        return 0.0
    m = (buy_ts > t0_us) & (buy_ts <= deadline_us) & (buy_px >= P - 1e-9)
    if not m.any():
        return 0.0
    cum = buy_sh[m].sum()
    avail = max(0.0, cum - max(0.0, queue_ahead))
    return float(min(Q, avail))


def kcells(pnl_base, P_arr, sh_arr, lab):
    """Print $/tr at each k (pnl_base is the no-rebate per-trade PnL array; add k-rebate per trade)."""
    out = []
    for k in K_GRID:
        reb = k * 0.07 * P_arr * (1.0 - P_arr) * sh_arr
        v = pnl_base + reb
        out.append((k, cell(v)))
    s = "  ".join(f"k={k}:{c}" for k, c in out)
    print(f"  {lab:30s} {s}")


# ============================ load resolutions ============================
res = pd.read_parquet(CANON / "resolutions_hf.parquet")
res = res[res.outcome.isin(["Up", "Down"]) & res.timeframe.isin(["5m", "15m"])].drop_duplicates("slug")

A_ROWS = []   # experiment A per-fire records
B_ROWS = []   # experiment B per-candidate records

for coin in COINS:
    lo = pd.Timestamp(WIN[coin][0], tz="UTC").value // 1000
    hi = pd.Timestamp(WIN[coin][1], tz="UTC").value // 1000
    d = res[(res.ticker == coin) & (res.slot_start_us >= lo) & (res.slot_start_us <= hi)].copy()
    if not len(d):
        print(f"\n=== {coin}: no slugs ==="); continue
    ts_k, px_k = klines(coin); lpx = np.log(px_k)
    ss = d.slot_start_us.values
    ret = asof(ts_k, px_k, ss + 5_000_000) / asof(ts_k, px_k, ss) - 1.0
    d = d.assign(fire_us=ss + 5_000_000, slot_end=d.slot_end_us.values, slot_start=ss,
                 ret=ret, delta_bps=np.abs(ret) * 1e4, lead=np.where(ret > 0, "Up", "Down"))
    d = d.reset_index(drop=True)
    if LIMIT > 0:
        d = d.iloc[:LIMIT].reset_index(drop=True)
    print(f"\n=== {coin} {WIN[coin][0]}..{WIN[coin][1]}: {len(d)} slugs ===", flush=True)

    # trades for this coin (whole file; filter per chunk)
    tr = load_trades_hf(coin.lower(), bbo=True)
    tr = tr[tr.slug.isin(set(d.slug))].copy()
    tr["sh"] = tr.size_usdc.values / np.clip(tr.price.values, 1e-6, None)
    tr_buy = tr[tr.side == "BUY"]; tr_sell = tr[tr.side == "SELL"]
    buy_by = {sl: (g.timestamp_us.values.astype("int64"), g.price.values.astype(float), g.sh.values.astype(float),
                   g.outcome.values) for sl, g in tr_buy.groupby("slug")}
    sell_by = {sl: (g.timestamp_us.values.astype("int64"), g.price.values.astype(float), g.sh.values.astype(float),
                    g.outcome.values) for sl, g in tr_sell.groupby("slug")}

    slugs = d.slug.tolist(); B = 120
    a_cands = a_filled = b_cands = b_filled = 0
    for i in range(0, len(slugs), B):
        chunk = d.iloc[i:i + B]
        cmin = int(chunk.slot_start.min()) - 5_000_000
        cmax = int(chunk.slot_end.max()) + 5_000_000
        bbo = load_orderbook_bbo(coin, slugs=set(chunk.slug), min_ts_us=cmin, max_ts_us=cmax, columns=BCOLS)
        bk = {}
        for (sl, oc), g in bbo.groupby(["slug", "outcome"]):
            g = g.sort_values("timestamp_us")
            bk[(sl, oc)] = (g.timestamp_us.values.astype("int64"), g.best_ask.values.astype(float),
                            g.best_bid.values.astype(float), g.best_ask_size.values.astype(float),
                            g.best_bid_size.values.astype(float))
        for _, r in chunk.iterrows():
            # token-specific taker prints for the LEAD/favored token
            def token_prints(side_by, slug, token):
                arr = side_by.get(slug)
                if arr is None:
                    return (np.empty(0, "int64"), np.empty(0), np.empty(0))
                pts, ppx, psh, poc = arr
                m = poc == token
                return pts[m], ppx[m], psh[m]

            # ---------------- EXPERIMENT A: maker entry for the open scalp ----------------
            if r.delta_bps >= 3.0 and np.isfinite(r.ret):
                key = (r.slug, r.lead)
                if key in bk:
                    ts, ask, bid, asz, bsz = bk[key]
                    won = (r.ret > 0) == (r.outcome == "Up")
                    t0 = int(r.fire_us) + LAT_US
                    je = np.searchsorted(ts, t0, "right") - 1
                    if 0 <= je < len(ts) and np.isfinite(bid[je]) and np.isfinite(ask[je]):
                        a_cands += 1
                        b0 = float(bid[je]); a0 = float(ask[je])
                        # JOIN bid at best_bid (we want to buy the lead token cheap; ev<0.55 gate later)
                        P = b0
                        qa, _ = resolve_size(ts, bsz, je)   # resting bid size = queue ahead
                        Q = STAKE / P if P > 0 else 0.0
                        s_ts, s_px, s_sh = token_prints(sell_by, r.slug, r.lead)
                        deadline = int(r.fire_us) + A_REST_US
                        filled, filled_ub = maker_buy_fill(P, Q, t0, qa, s_ts, s_px, s_sh, deadline)
                        fillfrac = filled / Q if Q > 0 else 0.0
                        fillfrac_ub = filled_ub / Q if Q > 0 else 0.0
                        ext = min(int(r.fire_us) + 60_000_000, int(r.slot_end))
                        rec = dict(coin=coin, tf=r.timeframe, slug=r.slug, hour=(int(r.fire_us)//1_000_000%86400)//3600,
                                   P=P, ask0=a0, Q=Q, queue_ahead=qa, filled=filled, fillfrac=fillfrac,
                                   filled_ub=filled_ub, fillfrac_ub=fillfrac_ub, won=won,
                                   delta=r.delta_bps, fire_us=int(r.fire_us))
                        # taker baseline on SAME candidate (buy at ask now, exit +60 taker)
                        s0, _ = resolve_size(ts, asz, je)
                        tk_sh = min(STAKE / a0, s0)
                        tk_ef = exit_fill(ts, bid, bsz, je, ext, tk_sh, a0, won)
                        rec["taker_pnl"] = tk_ef["pnl"]; rec["taker_ev"] = a0; rec["taker_sh"] = tk_sh
                        rec["maker_ev"] = P
                        # maker exit PnL evaluated on whichever fill is >0 (same exit_fill path).
                        rec["maker_filled"] = bool(fillfrac >= 0.50 and filled > 0)
                        rec["maker_filled_ub"] = bool(fillfrac_ub >= 0.50 and filled_ub > 0)
                        rec["maker_pnl"] = (exit_fill(ts, bid, bsz, je, ext, filled, P, won)["pnl"]
                                            if rec["maker_filled"] else np.nan)
                        rec["maker_sh"] = filled
                        rec["maker_pnl_ub"] = (exit_fill(ts, bid, bsz, je, ext, filled_ub, P, won)["pnl"]
                                               if rec["maker_filled_ub"] else np.nan)
                        rec["maker_sh_ub"] = filled_ub
                        a_filled += int(rec["maker_filled"])
                        A_ROWS.append(rec)

            # ---------------- EXPERIMENT B: late-window favored-side maker bid ----------------
            ss_us = int(r.slot_start); send = int(r.slot_end)
            si = np.searchsorted(ts_k, ss_us, "right") - 1
            if si >= VOL_LB + 5:
                strike = px_k[si]
                if strike > 0:
                    for off in (60, 30):
                        t = send - off * 1_000_000
                        ti = np.searchsorted(ts_k, t, "right") - 1
                        if ti < VOL_LB or ti >= len(px_k):
                            continue
                        sigma = np.std(np.diff(lpx[ti - VOL_LB:ti + 1]))
                        if not sigma > 0:
                            continue
                        z = math.log(px_k[ti] / strike) / (sigma * math.sqrt(off))
                        if abs(z) < 2.0:
                            continue
                        favored = "Up" if z > 0 else "Down"
                        key = (r.slug, favored)
                        if key not in bk:
                            continue
                        ts, ask, bid, asz, bsz = bk[key]
                        t0 = t + LAT_US
                        je = np.searchsorted(ts, t0, "right") - 1
                        if je < 0 or je >= len(ts) or not (np.isfinite(bid[je]) and np.isfinite(ask[je])):
                            continue
                        if (t0 - ts[je]) > 30_000_000:
                            continue
                        b0 = float(bid[je]); a0 = float(ask[je])
                        if round(a0 - b0, 4) > SPREAD_LATE:
                            continue
                        won = (r.outcome == favored)
                        s_ts, s_px, s_sh = token_prints(sell_by, r.slug, favored)
                        deadline = send - B_REST_END_OFF_US
                        for vlab, P in (("join", min(b0, 0.95)), ("improve_m1c", min(b0, 0.95) - 0.01)):
                            if not (0.0 < P < 1.0):
                                continue
                            # queue ahead: if P==b0 (join) use bid size; if P<b0 (improve down) we are
                            # WORSE than best bid -> queue ahead = full visible bid book at/above P.
                            # conservative: still subtract resting best_bid_size (we sit deeper, fill later).
                            qa, _ = resolve_size(ts, bsz, je)
                            Q = STAKE / P if P > 0 else 0.0
                            filled, filled_ub = maker_buy_fill(P, Q, t0, qa, s_ts, s_px, s_sh, deadline)
                            fillfrac = filled / Q if Q > 0 else 0.0
                            b_cands += (vlab == "join")  # count candidates once
                            pnl_held = held_value(filled, P, won) if filled > 0 else np.nan
                            pnl_held_ub = held_value(filled_ub, P, won) if filled_ub > 0 else np.nan
                            if filled > 0 and vlab == "join":
                                b_filled += 1
                            B_ROWS.append(dict(coin=coin, tf=r.timeframe, slug=r.slug, variant=vlab,
                                               off=off, z=abs(z), favored=favored, P=P, b0=b0, a0=a0,
                                               Q=Q, queue_ahead=qa, filled=filled, fillfrac=fillfrac,
                                               filled_ub=filled_ub, won=won,
                                               pnl_held=pnl_held, pnl_held_ub=pnl_held_ub,
                                               hour=(t // 1_000_000 % 86400) // 3600,
                                               slot_start=ss_us))
        del bbo, bk
    print(f"  A: candidates={a_cands} filled(>=50%)={a_filled}  "
          f"B: candidates(|z|>=2)={b_cands} filled(join)={b_filled}", flush=True)
    # checkpoint per coin
    if A_ROWS:
        pd.DataFrame([x for x in A_ROWS if x['coin'] == coin]).to_parquet(
            RES / f"maker_sim_2026_06_11{TAG}_A_{coin}.parquet")
    if B_ROWS:
        pd.DataFrame([x for x in B_ROWS if x['coin'] == coin]).to_parquet(
            RES / f"maker_sim_2026_06_11{TAG}_B_{coin}.parquet")
    del tr, tr_buy, tr_sell, buy_by, sell_by

A = pd.DataFrame(A_ROWS); B = pd.DataFrame(B_ROWS)
A.to_parquet(RES / f"maker_sim_2026_06_11{TAG}_A_all.parquet")
B.to_parquet(RES / f"maker_sim_2026_06_11{TAG}_B_all.parquet")
print(f"\n##### saved A n={len(A)}  B n={len(B)} #####")

# ============================ EXPERIMENT A ANALYSIS ============================
print("\n" + "=" * 78)
print("EXPERIMENT A — MAKER ENTRY (open scalp). Gate: maker entry price ev<0.55, delta>=3")
print("=" * 78)
if len(A):
    Ag = A[(A.P < 0.55) & (A.delta >= 3.0)].copy()
    print(f"candidates(gated)={len(Ag)}  fill_rate(>=50%)={Ag.maker_filled.mean():.3f}")
    filledA = Ag[Ag.maker_filled]
    wr_all = Ag.won.mean(); wr_fill = filledA.won.mean() if len(filledA) else float('nan')
    print(f"WR(all candidates)={wr_all:.3f}  WR(filled)={wr_fill:.3f}  "
          f"ADVERSE-SELECTION DELTA = WR(filled)-WR(all) = {wr_fill-wr_all:+.3f}")
    print(f"\n-- MAKER $/tr (filled only, n={len(filledA)}), rebate at k grid --")
    if len(filledA) >= 5:
        kcells(filledA.maker_pnl.values, filledA.maker_ev.values, filledA.maker_sh.values, "maker(filled)")
    print(f"\n-- TAKER baseline $/tr (SAME candidate set, n={len(Ag)}) --")
    print(f"  {'taker(all candidates)':30s} {cell(Ag.taker_pnl.values)}")
    print(f"  {'taker(on filled-subset)':30s} {cell(Ag[Ag.maker_filled].taker_pnl.values)}")
    print("\n-- PAIRED maker - taker on the FILLED subset (apples-to-apples) --")
    if len(filledA) >= 5:
        for k in K_GRID:
            reb = k * 0.07 * filledA.maker_ev.values * (1 - filledA.maker_ev.values) * filledA.maker_sh.values
            diff = (filledA.maker_pnl.values + reb) - filledA.taker_pnl.values
            lo_, hi_ = boot(diff)
            sig = "SIG+" if lo_ > 0 else ("SIG-" if hi_ < 0 else "ns")
            print(f"  k={k}: maker-taker mean={diff.mean():+.4f} CI=[{lo_:+.4f},{hi_:+.4f}] {sig}")
    print("\n-- per coin-tf (maker filled $/tr at k=0.05 vs taker) --")
    for (c, tf), g in Ag.groupby(["coin", "tf"]):
        gf = g[g.maker_filled]
        if len(gf) >= 5:
            reb = 0.05 * 0.07 * gf.maker_ev.values * (1 - gf.maker_ev.values) * gf.maker_sh.values
            print(f"  {c} {tf}: fill={g.maker_filled.mean():.2f} maker(k.05) {cell(gf.maker_pnl.values+reb)} "
                  f"| taker {cell(g.taker_pnl.values)} | advsel={gf.won.mean()-g.won.mean():+.3f}")
    # ---- UPPER-BOUND fill scenario (queue_ahead=0; front-of-queue / improve) ----
    print(f"\n-- [UPPER-BOUND fill: queue=0] fill_rate={Ag.maker_filled_ub.mean():.3f} --")
    fub = Ag[Ag.maker_filled_ub]
    if len(fub) >= 5:
        print(f"  WR(filled_ub)={fub.won.mean():.3f} advsel={fub.won.mean()-Ag.won.mean():+.3f}")
        kcells(fub.maker_pnl_ub.values, fub.maker_ev.values, fub.maker_sh_ub.values, "maker_ub(filled)")
        for k in K_GRID:
            reb = k * 0.07 * fub.maker_ev.values * (1 - fub.maker_ev.values) * fub.maker_sh_ub.values
            diff = (fub.maker_pnl_ub.values + reb) - fub.taker_pnl.values
            lo_, hi_ = boot(diff)
            sig = "SIG+" if lo_ > 0 else ("SIG-" if hi_ < 0 else "ns")
            print(f"  k={k}: maker_ub-taker mean={diff.mean():+.4f} CI=[{lo_:+.4f},{hi_:+.4f}] {sig}")

# ============================ EXPERIMENT B ANALYSIS ============================
print("\n" + "=" * 78)
print("EXPERIMENT B — LATE-WINDOW FAVORED-SIDE MAKER BID (oracle-snipe pocket, maker version)")
print("=" * 78)
if len(B):
    for variant in ("join", "improve_m1c"):
        Bv = B[B.variant == variant].copy()
        if not len(Bv):
            continue
        filledB = Bv[Bv.filled > 0]
        wr_all = Bv.won.mean(); wr_fill = filledB.won.mean() if len(filledB) else float('nan')
        print(f"\n### variant={variant}  candidates={len(Bv)} fill_rate={ (Bv.filled>0).mean():.3f}")
        print(f"  WR(candidates)={wr_all:.3f}  WR(filled)={wr_fill:.3f}  "
              f"ADVERSE-SELECTION DELTA={wr_fill-wr_all:+.3f}")
        if len(filledB) >= 5:
            print("  -- POOLED maker $/tr (filled, hold-to-resolution) at k grid --")
            kcells(filledB.pnl_held.values, filledB.P.values, filledB.filled.values, "pooled")
            print("  -- per coin-tf (k=0.05) --")
            for (c, tf), g in filledB.groupby(["coin", "tf"]):
                if len(g) >= 5:
                    reb = 0.05 * 0.07 * g.P.values * (1 - g.P.values) * g.filled.values
                    gall = Bv[(Bv.coin == c) & (Bv.tf == tf)]
                    print(f"    {c} {tf}: fill={ (gall.filled>0).mean():.2f} "
                          f"{cell(g.pnl_held.values + reb)} advsel={g.won.mean()-gall.won.mean():+.3f}")
            print("  -- time-split halves (k=0.05) --")
            med = filledB.slot_start.median()
            for half, hb in [("H1", filledB.slot_start <= med), ("H2", filledB.slot_start > med)]:
                g = filledB[hb]
                if len(g) >= 5:
                    reb = 0.05 * 0.07 * g.P.values * (1 - g.P.values) * g.filled.values
                    print(f"    {half}: {cell(g.pnl_held.values + reb)}")
        # ---- UPPER-BOUND fill (queue=0) ----
        fub = Bv[Bv.filled_ub > 0]
        print(f"  -- [UPPER-BOUND fill: queue=0] fill_rate={(Bv.filled_ub>0).mean():.3f} n_filled={len(fub)} --")
        if len(fub) >= 5:
            print(f"    WR(filled_ub)={fub.won.mean():.3f} advsel={fub.won.mean()-Bv.won.mean():+.3f}")
            kcells(fub.pnl_held_ub.values, fub.P.values, fub.filled_ub.values, "pooled_ub")

print("\nVERDICTS:")
print("  A: maker WINS only if maker(k=0.05) $/tr > taker baseline w/ paired CI>0 (else taker stays).")
print("  B: pocket real-as-maker iff filled $/tr>0 CI>0 AND adverse-sel delta not strongly negative.")
print("CAVEATS: conservative fill = LOWER BOUND on fills (queue-ahead full, side-true prints only);")
print("  trades coverage Mar30-Apr21 (XRP Apr7+); BBO top-of-book (no L25 depth); Mar30-Apr21 OOS window")
print("  is BURNED for the open-scalp (used in 06-05 OOS) -> A is a fill/economics test, not fresh OOS.")
