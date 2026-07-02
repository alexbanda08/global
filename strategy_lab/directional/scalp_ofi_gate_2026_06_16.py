"""
SCALP × BINANCE 1s TAKER-OFI GATE (2026-06-16).

Hypothesis (5-lens audit #2): the deployed lag-scalp buys the lagging Poly token after a Binance move and
sells +60s. If the move was driven by genuine AGGRESSOR flow (high taker-order-flow-imbalance) it should
persist → the +60s sell wins more; if it was a thin spike (low |OFI|) it reverts → the scalp loses. OFI
reads the CAUSE of the move (taker_buy/total), unlike Poly-CVD which reads the priced-in consequence.

DATA: klines_1s `taker_buy_base`/`volume_traded` (NEVER extracted before). Populated only on live-WS rows
(binance-spot-ws), i.e. the PRODUCTION window (Apr22+); vision-backfill rows are NULL → the OOS BBO window
can't be used. So this is the PRODUCTION (in-sample) window — honest framing: a microstructure DOSE-RESPONSE
(does signed-OFI predict scalp $/tr), which is more transportable than the base edge; deploy verdict = live.

MODEL (the deployed scalp, causal):
  signal: causal bar-END 5s return at slot_start (|ret|·1e4 ≥ 3bp, lead=sign(ret)); fire ss+5s.
  entry: L25 book-walk $25 on lead ask at ss+5s+85ms; gate ev<0.55, top-of-book spread ≤ 0.05.
  exit: +60s (clamp slot_end) sell on L25 bid; pnl = bpnl(sell_vwap,ev,sold) + held_value(rem,ev,won).
  OFI: over the SIGNAL window [ss, ss+5s], aggregate taker_buy + volume across 1s bars with non-null
       taker_buy → ofi = 2·(Σtaker_buy/Σvol) − 1 ∈ [−1,1]; ofi_aligned = ofi·sign(ret)
       (>0 = aggressor flow CONFIRMS the lead direction; <0 = move not flow-backed = suspect).

OUTPUT: per coin/tf + pooled, gated ev<0.55:
  - dose-response: $/tr by ofi_aligned quintile (monotone ↑ → OFI predicts → gate works)
  - gate test: $/tr for ofi_aligned > {−0.2,0,0.2} vs the ungated base; trimmed-fires count
  - bootstrap CI; honest in-sample caveat.
"""
import os, sys, warnings
from pathlib import Path
import numpy as np, pandas as pd

warnings.filterwarnings("ignore"); np.random.seed(0)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data/v4/canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab")); sys.path.insert(0, str(ROOT / "strategy_lab/directional"))
from load import load_orderbook_l25_streaming, load_resolutions   # noqa: E402
from engine_v2 import sell_at_bid_partial                         # noqa: E402
from book_walk import book_walk_fill                              # noqa: E402
from scalp_fill_lib_2026_06_10 import bpnl, held_value, boot       # noqa: E402

CANON = ROOT / "data/v4/canonical"; RES = ROOT / "strategy_lab/directional/_results"
LAT_US = 85_000; STAKE = 25.0; SPREAD = 0.05; THR = 3.0
COINS = os.environ.get("SP_COINS", "BTC,ETH,SOL").split(",")
TFS = ["5m", "15m"]; WIN_S = {"5m": 300, "15m": 900}
SAMPLE = int(os.environ.get("SP_SAMPLE", "1400"))


def cell(v):
    v = np.asarray(v, float); v = v[np.isfinite(v)]
    if len(v) < 5: return f"n={len(v):4d} (few)"
    t = v.mean() / v.std(ddof=1) * np.sqrt(len(v)) if v.std() > 0 else np.nan
    lo, hi = boot(v)
    return f"n={len(v):4d} $/tr={v.mean():+.3f} t={t:+.2f} CI=[{lo:+.3f},{hi:+.3f}]"


def klines_1s_arrays(coin):
    """Return (starts, ends, close, taker_buy, volume) for production-window 1s bars (taker_buy may be NaN)."""
    sym = f"BINANCE_SPOT_{coin}_USDT"
    df = pd.read_parquet(CANON / "klines_1s.parquet",
                         columns=["symbol_id", "time_period_start_us", "price_close", "taker_buy_base", "volume_traded"],
                         filters=[("symbol_id", "==", sym)])
    # prefer the live-WS row (carries taker_buy) over vision (null) on duplicate seconds.
    df["_tb"] = df.taker_buy_base.notna()
    df = df.sort_values(["time_period_start_us", "_tb"]).drop_duplicates("time_period_start_us", keep="last")
    s = df.time_period_start_us.values.astype("int64")
    return s, s + 1_000_000, df.price_close.values.astype(float), \
        df.taker_buy_base.values.astype(float), df.volume_traded.values.astype(float)


def asof_end(ends, close, t):
    i = np.searchsorted(ends, t, "right") - 1
    return close[i] if i >= 0 else np.nan


def ofi_window(starts, tb, vol, t0, t1):
    """Signed OFI over [t0,t1): 2·Σtaker_buy/Σvol − 1, using bars with non-null taker_buy. None if no flow."""
    lo = np.searchsorted(starts, t0, "left"); hi = np.searchsorted(starts, t1, "left")
    if hi <= lo: return None
    tbw = tb[lo:hi]; vw = vol[lo:hi]
    m = np.isfinite(tbw) & np.isfinite(vw) & (vw > 0)
    V = vw[m].sum()
    if V <= 0: return None
    return 2.0 * tbw[m].sum() / V - 1.0


REC = []
for coin in COINS:
    rdf = load_resolutions(assets=[coin], timeframes=TFS)
    rdf = rdf[rdf.outcome.isin(["Up", "Down"])].drop_duplicates("slug")
    st, en, cl, tb, vol = klines_1s_arrays(coin)
    for tf in TFS:
        d = rdf[rdf.timeframe == tf].copy()
        sl_all = sorted(d.slug)
        if len(sl_all) > SAMPLE:
            step = len(sl_all) / SAMPLE
            sl_all = set(sl_all[int(i * step)] for i in range(SAMPLE))
        else:
            sl_all = set(sl_all)
        d = d[d.slug.isin(sl_all)]
        outc = dict(zip(d.slug, d.outcome))
        print(f"=== {coin} {tf}: {len(d)} slugs — scanning L25 + OFI ===", flush=True)
        slugs = sorted(sl_all); CH = 150
        for i in range(0, len(slugs), CH):
            chunk = set(slugs[i:i + CH])
            books = load_orderbook_l25_streaming(coin.lower(), slugs=chunk, subsample_1hz=False)
            for slug in chunk:
                if slug not in outc: continue
                ss = int(slug.rsplit("-", 1)[1]) * 1_000_000
                fire = ss + 5_000_000
                p_now = asof_end(en, cl, fire); p_prev = asof_end(en, cl, ss)
                if not (np.isfinite(p_now) and np.isfinite(p_prev) and p_prev > 0): continue
                ret = p_now / p_prev - 1.0; dbps = abs(ret) * 1e4
                if dbps < THR: continue
                lead = "Up" if ret > 0 else "Down"
                rec = books.get((slug, lead))
                if rec is None: continue
                ts, ap, asz, bp, bsz = rec
                # entry
                je = int(np.searchsorted(ts, fire + LAT_US, "right") - 1)
                if je < 0 or je >= len(ts): continue
                a0 = ap[je, 0]; b0 = bp[je, 0]
                if not (np.isfinite(a0) and np.isfinite(b0)) or round(float(a0 - b0), 4) > SPREAD: continue
                ev, shares, usd, _l, _u = book_walk_fill(list(ap[je]), list(asz[je]), STAKE, side="buy")
                if shares <= 0 or ev <= 0 or ev >= 0.55: continue
                won = (lead == outc[slug])
                # exit +60s
                ext = min(fire + 60_000_000, ss + WIN_S[tf] * 1_000_000) + LAT_US
                jx = int(np.searchsorted(ts, ext, "right") - 1)
                if jx >= je and 0 <= jx < len(ts) and np.isfinite(bp[jx, 0]):
                    vx, sold, _ = sell_at_bid_partial(list(bp[jx]), list(bsz[jx]), shares)
                else:
                    vx, sold = np.nan, 0.0
                rem = shares - sold
                pnl = (bpnl(vx, ev, sold) if sold > 0 else 0.0) + held_value(rem, ev, won)
                # OFI over the signal window
                ofi = ofi_window(st, tb, vol, ss, fire)
                ofi_al = ofi * np.sign(ret) if ofi is not None else np.nan
                REC.append((coin, tf, slug, ev, won, pnl, dbps, ofi_al))
            del books

A = pd.DataFrame(REC, columns=["coin", "tf", "slug", "ev", "won", "pnl", "delta", "ofi_al"])
A.to_parquet(RES / "scalp_ofi_gate_2026_06_16.parquet")
G = A[A.ev < 0.55].copy()
GO = G[np.isfinite(G.ofi_al)]
print("\n" + "=" * 90)
print(f"SCALP × OFI GATE (production window, gated ev<0.55). fires={len(G)}, with OFI={len(GO)} "
      f"({100*len(GO)/max(1,len(G)):.0f}%)")
print(f"\nBASE (ungated by OFI):           {cell(G.pnl.values)}")
print("\n--- DOSE-RESPONSE: $/tr by ofi_aligned quintile (pooled) ---")
GO = GO.assign(q=pd.qcut(GO.ofi_al, 5, labels=False, duplicates="drop"))
for q, gg in GO.groupby("q"):
    print(f"  Q{int(q)+1} ofi_al∈[{gg.ofi_al.min():+.2f},{gg.ofi_al.max():+.2f}]  {cell(gg.pnl.values)}  won={gg.won.mean():.2f}")
print("\n--- GATE TEST: $/tr for ofi_aligned > threshold (pooled) ---")
for thr in [-0.2, 0.0, 0.2, 0.4]:
    sub = GO[GO.ofi_al > thr]
    kept = 100 * len(sub) / max(1, len(GO))
    print(f"  ofi_al > {thr:+.1f}  (keep {kept:>4.0f}%)  {cell(sub.pnl.values)}")
print("\n--- per-coin/tf: base vs ofi_al>0 ---")
for (coin, tf), gg in GO.groupby(["coin", "tf"]):
    b = gg.pnl.values; g = gg[gg.ofi_al > 0].pnl.values
    print(f"  {coin} {tf}:  base {cell(b)}  |  ofi>0 {cell(g)}")
print("\nREAD: monotone-↑ dose-response + ofi_al>0 $/tr > base = OFI gate trims losers → deploy shadow, judge live.")
print("CAVEAT: production (in-sample) window — taker_buy only on live-WS rows; OOS BBO window has it NULL.")
