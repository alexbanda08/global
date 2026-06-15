"""
CAUSAL-vs-LEAKY SIGNAL ASOF — PRE-REGISTERED PAIRED ONE-SHOT (2026-06-12).

QUESTION: every scalp driver computes the delta signal with a bar-START asof on klines_1s:
    ret = asof_start(ss+5s)/asof_start(ss) - 1
  asof_start(t) picks the bar OPENING <= t, i.e. at t=ss+5 the bar [ss+5, ss+6) whose CLOSE
  is the price at ~ss+6 — ~0.9s AFTER the fire (ss+5s + 85ms). Live can only see the bar that
  CLOSED at ss+5. Verified 2026-06-12: time_period_start_us = bar open, end = start+999999.
  This was NOT fixed by the 06-10 retro (exit/size/fee bugs only); grep of reports = no prior fix.

DESIGN (declared before running, single shot):
  Window: Mar30-Apr21 BBO (full 6-coin tape). NOTE this window is BURNED for selection;
  a PAIRED arm-difference measurement is still valid because nothing is selected — we measure
  the delta between two pre-specified arms on identical data. NOT a fresh magnitude estimate.
  (Feb21-Mar24 is IMPOSSIBLE for the +5s scalp: both the L25 backfill AND the trades_hf tape
  start ~80s into each slot — recorder artifact, probed 2026-06-12: min first-trade +32.5s,
  median +83s, 0 pre-slot prints in 880k trades.)

  ARM L (leaky)  : ret_L = asof_start(ss+5s)/asof_start(ss) - 1     == every existing driver
  ARM C (causal) : ret_C = asof_end(ss+5s)/asof_end(ss) - 1
                   asof_end(t) = bar with end (= start+1s) <= t  -> close known at fire. == live.

  Identical everything else (corrected lib): fire ss+5s, LAT 85ms, $25, spread<=0.05,
  entry_fill/exit_fill from scalp_fill_lib_2026_06_10, +60s pure time sell clamped to slot_end,
  remainder held winner-only 0.07, bpnl 0.015 sold-lot proxy (operator-confirmed fee handling).

PRE-DECLARED OUTPUTS (no post-hoc cells):
  1. Per-coin + pooled, gated ev<0.55: $/tr, t, CI for each arm.
  2. Selection diff: fires L-only / C-only / both; lead-direction flips among shared slugs.
  3. PAIRED diff on shared same-lead fires (identical trade both arms -> diff==0 expected;
     the real effect is selection, reported via 1+2).
  4. VERDICT rule (declared): if ARM C gated pooled $/tr CI>0, the edge is NOT a lookahead
     artifact; magnitude delta C-L is the bias estimate to subtract from prior reports.
"""
import os, sys, warnings
from pathlib import Path
import numpy as np, pandas as pd

warnings.filterwarnings("ignore"); np.random.seed(0)
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data/v4/canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab/directional"))
from load import load_orderbook_bbo                                   # noqa: E402
from scalp_fill_lib_2026_06_10 import entry_fill, exit_fill, boot, cell  # noqa: E402

CANON = ROOT / "data/v4/canonical"
RES = ROOT / "strategy_lab/directional/_results"
SPREAD = 0.05; STAKE = 25.0; LAT_US = 85_000
COINS = os.environ.get("OOS_COINS", "BTC,ETH,SOL,DOGE,XRP,BNB").split(",")
_FULL = ("2026-03-30", "2026-04-21"); _NEW = ("2026-04-06", "2026-04-21")
WIN = {"BTC": _FULL, "ETH": _FULL, "SOL": _FULL, "DOGE": _NEW, "BNB": _NEW, "XRP": ("2026-04-07", "2026-04-21")}
BCOLS = ["timestamp_us", "slug", "outcome", "best_bid", "best_ask", "best_bid_size", "best_ask_size"]


def unified_1s(coin):
    sym = f"BINANCE_SPOT_{coin.upper()}_USDT"
    df = pd.read_parquet(CANON / "klines_1s.parquet", columns=["symbol_id", "time_period_start_us", "price_close"],
                         filters=[("symbol_id", "==", sym)])
    df = df.sort_values("time_period_start_us").drop_duplicates("time_period_start_us")
    starts = df.time_period_start_us.values.astype("int64")
    return starts, starts + 1_000_000, df.price_close.values.astype(float)   # (start, end, close)


def asof_on(ts, v, t):
    i = np.searchsorted(ts, t, "right") - 1
    return np.where(i >= 0, v[np.clip(i, 0, len(v) - 1)], np.nan)


res = pd.read_parquet(CANON / "resolutions_hf.parquet")
res = res[res.outcome.isin(["Up", "Down"]) & res.timeframe.isin(["5m", "15m"])].drop_duplicates("slug")

POOL = {"L": [], "C": []}
SEL = dict(L_only=0, C_only=0, both=0, lead_flip=0)
ALL_REC = []

for coin in COINS:
    lo = pd.Timestamp(WIN[coin][0], tz="UTC").value // 1000; hi = pd.Timestamp(WIN[coin][1], tz="UTC").value // 1000
    d = res[(res.ticker == coin) & (res.slot_start_us >= lo) & (res.slot_start_us <= hi)].copy()
    if not len(d):
        print(f"\n=== {coin}: no slugs ==="); continue
    starts, ends, close = unified_1s(coin)
    ss = d.slot_start_us.values
    ret_L = asof_on(starts, close, ss + 5_000_000) / asof_on(starts, close, ss) - 1.0
    ret_C = asof_on(ends,   close, ss + 5_000_000) / asof_on(ends,   close, ss) - 1.0
    d = d.assign(fire_us=ss + 5_000_000, slot_end=d.slot_end_us.values, ret_L=ret_L, ret_C=ret_C,
                 dL=np.abs(ret_L) * 1e4, dC=np.abs(ret_C) * 1e4,
                 leadL=np.where(ret_L > 0, "Up", "Down"), leadC=np.where(ret_C > 0, "Up", "Down"))
    okL = np.isfinite(d.ret_L) & (d.dL >= 3.0); okC = np.isfinite(d.ret_C) & (d.dC >= 3.0)
    SEL["L_only"] += int((okL & ~okC).sum()); SEL["C_only"] += int((~okL & okC).sum())
    SEL["both"] += int((okL & okC).sum())
    SEL["lead_flip"] += int((okL & okC & (d.leadL != d.leadC)).sum())
    d = d[okL | okC].reset_index(drop=True)
    print(f"\n=== {coin} {WIN[coin][0]}..{WIN[coin][1]}: cand L={int(okL.sum())} C={int(okC.sum())} "
          f"both={int((okL & okC).sum())} ===", flush=True)

    arm_pnl = {"L": [], "C": []}
    slugs = d.slug.tolist(); B = 120
    for i in range(0, len(slugs), B):
        chunk = d.iloc[i:i + B]
        cmin = int(chunk.fire_us.min()) - 2_000_000; cmax = int(chunk.slot_end.max()) + 2_000_000
        bbo = load_orderbook_bbo(coin, slugs=set(chunk.slug), min_ts_us=cmin, max_ts_us=cmax, columns=BCOLS)
        bk = {}
        for (sl, oc), g in bbo.groupby(["slug", "outcome"]):
            g = g.sort_values("timestamp_us")
            bk[(sl, oc)] = (g.timestamp_us.values.astype("int64"), g.best_ask.values.astype(float),
                            g.best_bid.values.astype(float), g.best_ask_size.values.astype(float),
                            g.best_bid_size.values.astype(float))
        for _, r in chunk.iterrows():
            for arm, ret, dlt, lead in (("L", r.ret_L, r.dL, r.leadL), ("C", r.ret_C, r.dC, r.leadC)):
                if not (np.isfinite(ret) and dlt >= 3.0):
                    continue
                key = (r.slug, lead)
                if key not in bk:
                    continue
                ts, ask, bid, asz, bsz = bk[key]
                won = (ret > 0) == (r.outcome == "Up")
                ent = entry_fill(ts, ask, asz, int(r.fire_us) + LAT_US, STAKE, SPREAD, bid)
                if ent is None:
                    continue
                ext = min(int(r.fire_us) + 60_000_000, int(r.slot_end))
                ef = exit_fill(ts, bid, bsz, ent["entry_idx"], ext, ent["shares"], ent["ev"], won)
                if ent["ev"] < 0.55:                                     # the validated gated cell
                    arm_pnl[arm].append(ef["pnl"])
                ALL_REC.append(dict(coin=coin, slug=r.slug, arm=arm, ev=ent["ev"], won=won,
                                    pnl60=ef["pnl"], delta=dlt, lead=lead, frac_held=ef["frac_held"]))
        del bbo, bk
    for a in ("L", "C"):
        POOL[a] += arm_pnl[a]
        print(f"  {a} gated ev<0.55   {cell(arm_pnl[a])}")

print("\n" + "=" * 78)
print("POOLED gated ev<0.55:")
print(f"  ARM L (leaky, all prior drivers)  {cell(POOL['L'])}")
print(f"  ARM C (causal end-asof, == live)  {cell(POOL['C'])}")
print(f"\nSELECTION DIFF (candidates, delta>=3): L-only={SEL['L_only']}  C-only={SEL['C_only']} "
      f" both={SEL['both']}  lead-flips-among-both={SEL['lead_flip']}")
A = pd.DataFrame(ALL_REC)
A.to_parquet(RES / "scalp_causal_asof_fires_2026_06_12.parquet")
sh = A.pivot_table(index=["coin", "slug"], columns="arm", values="pnl60")
sh = sh.dropna()
if len(sh) >= 5:
    diff = (sh["C"] - sh["L"]).values
    lo, hi = boot(diff)
    print(f"PAIRED C-L on shared filled fires: n={len(sh)} mean={diff.mean():+.4f} CI=[{lo:+.4f},{hi:+.4f}]"
          f"  nonzero={int((np.abs(diff) > 1e-9).sum())}")
print("\nDECLARED VERDICT RULE: ARM C gated pooled CI>0 -> edge NOT a lookahead artifact;"
      " (C-L) = bias to subtract from prior magnitude claims.")
