"""
KALSHI scalp maker-exit test — does a maker SELL beat the taker exit on kalshi_scalp_exit_btc_15m_d3_v1?
Replicate the live Kalshi scalp: KXBTC15M, fire @ window_start+60s, buy the LEADING side (binance 1s lag) at the
Kalshi ask, entry_band (0,0.55), δ∈[3,12]. Exit at +60s (= window_start+120). Compare:
  (1) TAKER exit: sell by crossing the Kalshi BID at +60s; pay Kalshi TAKER fee.
  (2) MAKER exit: rest a sell at target; fill if the leading-contract BID rises to >= target within [fire,+60]
      (proxy: a buyer lifting our offer) -> sell at target, Kalshi maker fee = $0 (taker-only model), NO rebate;
      else taker-cross the bid at +60.
Kalshi fee = round_up(0.07*C*P*(1-P)) on the TAKER only -> maker saves it. Kalshi spreads are WIDE (more to capture)
but books are THIN (fill rate uncertain). Data: kalshi_markets/orderbook (Jun2-5) + binance 1s. Bootstrap CI.
"""
import sys, warnings
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings("ignore"); np.random.seed(0)
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data/v4/canonical"))
from load import load_kalshi_markets, load_kalshi_orderbook
CANON = ROOT / "data/v4/canonical"

km = load_kalshi_markets("BTC"); km = km[(km.series == "KXBTC15M") & (km.status == "finalized")].copy()
ko = load_kalshi_orderbook("BTC").dropna(subset=["yes_bid", "yes_ask", "no_bid", "no_ask"]).sort_values("time_us")
# binance 1s
b = pd.read_parquet(CANON / "klines_1s.parquet", columns=["symbol_id", "time_period_start_us", "price_close"],
                    filters=[("symbol_id", "==", "BINANCE_SPOT_BTC_USDT")]).sort_values("time_period_start_us").drop_duplicates("time_period_start_us")
be, bc = b.time_period_start_us.values.astype("int64"), b.price_close.values.astype(float)
def asof(ts, v, t):
    i = np.searchsorted(ts, t, "right") - 1
    return np.where(i >= 0, v[np.clip(i, 0, len(v) - 1)], np.nan)
kfee = lambda p: np.ceil(0.07 * p * (1 - p) * 100) / 100   # Kalshi taker fee (round up to cent), per contract
kidx = {mt: g for mt, g in ko.groupby("market_ticker")}
print(f"KXBTC15M finalized: {len(km)}  with quotes: {sum(mt in kidx for mt in km.market_ticker)}")

recs = []
for _, m in km.iterrows():
    ws = int(m.open_time_us); fire = ws + 60_000_000; deadline = fire + 60_000_000
    # lag at fire (binance 5s return)
    ret = float(asof(be, bc, fire) / asof(be, bc, fire - 5_000_000) - 1.0)
    if not np.isfinite(ret): continue
    db = abs(ret) * 1e4
    if db < 3.0: continue
    lead_up = ret > 0                       # Yes=up leads if binance up
    kq = kidx.get(m.market_ticker)
    if kq is None: continue
    t = kq.time_us.values
    bid = kq.yes_bid.values if lead_up else kq.no_bid.values
    ask = kq.yes_ask.values if lead_up else kq.no_ask.values
    # entry at fire: buy leading contract at its ask
    je = np.searchsorted(t, fire, "right") - 1
    if je < 0: continue
    ev = float(ask[je])
    if not np.isfinite(ev) or ev <= 0 or ev >= 0.55: continue   # entry_band (0,0.55)
    won_lead = (m.result == "yes") == lead_up                    # did the leading side win
    # window mask [fire, deadline]
    win = (t > fire) & (t <= deadline)
    tw, bidw = t[win], bid[win]
    jd = np.searchsorted(t, deadline, "right") - 1
    bid_dead = float(bid[jd]) if jd >= 0 and np.isfinite(bid[jd]) else (1.0 if won_lead else 0.0)
    # (1) taker exit: sell at bid_dead, pay kalshi taker fee
    taker = (bid_dead - ev) - kfee(bid_dead)
    rec = dict(mt=m.market_ticker, ev=ev, won=won_lead, bid_dead=bid_dead, taker=taker, db=db, spread=float(ask[je]-bid[je]))
    # (2) maker exit @ targets: fill if leading BID >= target in (fire,deadline]
    for tgt in [0.55, 0.60, 0.65, 0.70]:
        filled = bool(np.any(bidw >= tgt - 1e-9)) if len(bidw) else False
        rec[f"maker_{int(round(tgt*100))}"] = (tgt - ev) - 0.0 if filled else taker   # maker: no fee, no rebate; else taker fallback
    recs.append(rec)
D = pd.DataFrame(recs)
D.to_parquet(ROOT / "strategy_lab/directional/_results/kalshi_scalp_maker_exit_2026_06_06.parquet")
print(f"gated Kalshi scalp fires (delta>=3, entry<0.55): {len(D)}  mean entry={D.ev.mean():.3f} mean spread={D.spread.mean():.3f} won={D.won.mean():.3f}")
def boot(v, nb=5000):
    v=np.asarray(v);
    if len(v)<5: return (np.nan,np.nan)
    i=np.random.randint(0,len(v),(nb,len(v))); return tuple(np.percentile(v[i].mean(1),[2.5,97.5]))
def show(col,label):
    v=D[col].dropna().values
    if len(v)<5: print(f"  {label:30s} n={len(v)} (few)"); return None
    t=v.mean()/v.std(ddof=1)*np.sqrt(len(v)) if v.std()>0 else np.nan; lo,hi=boot(v)
    print(f"  {label:30s} n={len(v):3d} $/contract={v.mean():+.4f} t={t:+.2f} CI=[{lo:+.4f},{hi:+.4f}]"); return v
print("\n=== KALSHI scalp exit comparison (per 1 contract = $1 notional) ===")
show("taker","(1) TAKER exit +60")
for tgt in [55,60,65,70]: show(f"maker_{tgt}", f"(2) MAKER exit @0.{tgt}")
print("\n=== paired: maker - taker ===")
for tgt in [55,60,65,70]:
    d=(D[f"maker_{tgt}"]-D["taker"]).dropna().values; lo,hi=boot(d)
    sig = "SIG+" if lo>0 else ("SIG-" if hi<0 else "ns")
    print(f"  maker@0.{tgt} - taker: mean={d.mean():+.4f} CI=[{lo:+.4f},{hi:+.4f}] {sig}  fill_rate={ (D[f'maker_{tgt}']!=D['taker']).mean():.2f}")
print("\nCAVEAT: maker fill = leading BID reaches target (book proxy; no Kalshi trade tape) -> ignores queue;")
print("Kalshi fee TAKER-only so maker saves it; NO rebate. Short sample (Jun2-5). Entry lag = binance 5s proxy.")
