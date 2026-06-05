"""CYCLOPS WALLET VALIDATE 2026-06-01 — deep validation of the prime candidate
0xf69af0b9af9c92a342b682e5dee262dbc39e7b5c (tightest-latency directional wallet).

For every last-2-day signal slug, dump this wallet's BUY trades and check:
 (a) does it take the SIGNALED direction every time?
 (b) what is its fill price vs entry_cents?
 (c) what is its exec-time offset from post_ts (latency)?
 (d) PnL/volume profile.

Run: C:/Python314/python.exe strategy_lab/wallet_hunt/cyclops_wallet_validate_2026_06_01.py
"""
from __future__ import annotations
import sys, io, re, json, time
import datetime as dt
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import numpy as np
import pandas as pd
import requests
from load import load_resolutions

TAG = "CYCLOPS_WALLET_VALIDATE_2026_06_01"
print(TAG, "OUTPUT START", flush=True)

CAND = "0xf69af0b9af9c92a342b682e5dee262dbc39e7b5c"
CAND2 = "0x0c7c5204404e9d5402d258fedac59c7212bae4cb"  # cross-check the noisy #1
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
WH = ROOT / "strategy_lab" / "wallet_hunt"
CSV = WH / "cyclops_signals_fresh_2026_06_01.csv"
CACHE = WH / "cache" / "_cyclops_hunt"
DATA = "https://data-api.polymarket.com"
LB = "http://lb-api.polymarket.com"
UA = {"User-Agent": "global-strategy-lab/1.0", "Accept": "application/json"}
MONTHS = {"Jan":1,"Feb":2,"Mar":3,"Apr":4,"May":5,"Jun":6,"Jul":7,"Aug":8,
          "Sep":9,"Oct":10,"Nov":11,"Dec":12}


def parse_slot_et(raw):
    mm = re.search(r"([A-Z][a-z]{2})\s+(\d{1,2})\s+(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})\s*(AM|PM)\s*ET", str(raw))
    if not mm:
        return None
    mon, day, h1, mi1, h2, mi2, ampm = mm.groups()
    h1, mi1, day, mon = int(h1), int(mi1), int(day), MONTHS[mon]
    hh = h1 % 12
    if ampm == "PM":
        hh += 12
    et = dt.datetime(2026, mon, day, hh, mi1, tzinfo=dt.timezone(dt.timedelta(hours=-4)))
    return int(et.astimezone(dt.timezone.utc).timestamp())


def _cget(name, url=None, params=None):
    fp = CACHE / f"{name}.json"
    if fp.exists():
        try:
            return json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            pass
    if url is None:
        return None
    time.sleep(0.25)
    try:
        r = requests.get(url, params=params, headers=UA, timeout=15)
        obj = r.json() if r.status_code == 200 else {"_status": r.status_code}
    except Exception as e:
        obj = {"_err": str(e)}
    fp.write_text(json.dumps(obj, default=str), encoding="utf-8")
    return obj


def fetch_trades_cached(slug):
    out = []
    for p in range(4):
        page = _cget(f"trades_{slug}_p{p}")
        if not isinstance(page, list) or not page:
            break
        out.extend(page)
        if len(page) < 500:
            break
    return out


df = pd.read_csv(CSV)
df["post_dt"] = pd.to_datetime(df["post_ts"], utc=True, errors="coerce")
sig = df[(df["type"] == "SIGNAL") & (df["post_dt"] >= pd.Timestamp("2026-05-30T00:00:00Z"))].copy()
sig["slot_start"] = sig["raw"].map(parse_slot_et)
sig = sig.dropna(subset=["slot_start"]).copy()
sig["slot_start"] = sig["slot_start"].astype(int)
sig["slug"] = "btc-updown-5m-" + sig["slot_start"].astype(str)
sig["dir"] = sig["direction"].str.upper().str.strip()
def ec_of(r):
    v = r["entry_cents"]
    if pd.notna(v) and str(v).strip() not in ("", "nan"):
        return float(v)
    m = re.search(r"Entry\s+(\d+)¢", str(r["raw"]))
    return float(m.group(1)) if m else np.nan
sig["entry_c"] = sig.apply(ec_of, axis=1)

res = load_resolutions(assets=["BTC"], timeframes=["5m"]).copy()
res["slot_s"] = (res["slot_start_us"] // 1_000_000).astype(int)
cid_map = res.set_index("slot_s")["market_id"].to_dict()
out_map = res.set_index("slot_s")["outcome"].to_dict()
TOKEN = {"UP": "Up", "DOWN": "Down"}


def analyze(cand):
    print(f"\n========== CANDIDATE {cand} ==========")
    rows = []
    for _, r in sig.iterrows():
        slug = r["slug"]
        if r["slot_start"] not in cid_map:
            continue
        post_ts = int(r["post_dt"].timestamp())
        want = TOKEN.get(r["dir"])
        ec = r["entry_c"]
        trades = [t for t in fetch_trades_cached(slug)
                  if str(t.get("proxyWallet", "")).lower() == cand
                  and str(t.get("side", "")).upper() == "BUY"]
        if not trades:
            rows.append({"slug": slug, "sig_dir": want, "ec": ec, "active": False,
                         "bought_up": 0, "bought_dn": 0, "took_signaled": None,
                         "off": None, "fill_px": None})
            continue
        up = [t for t in trades if str(t.get("outcome")) == "Up"]
        dn = [t for t in trades if str(t.get("outcome")) == "Down"]
        up_qty = sum(float(t.get("size", 0)) for t in up)
        dn_qty = sum(float(t.get("size", 0)) for t in dn)
        side_trades = up if want == "Up" else dn
        took = (len(side_trades) > 0) and ((up_qty > 0) != (dn_qty > 0))  # one side only
        # earliest fill on signaled side
        fill_px = off = None
        if side_trades:
            st = sorted(side_trades, key=lambda t: int(t.get("timestamp", 0)))
            first = st[0]
            off = int(first.get("timestamp")) - post_ts
            fill_px = float(first.get("price")) * 100
        rows.append({"slug": slug, "sig_dir": want, "ec": ec, "active": True,
                     "bought_up": round(up_qty, 1), "bought_dn": round(dn_qty, 1),
                     "took_signaled": took, "off": off, "fill_px": round(fill_px, 1) if fill_px else None})
    A = pd.DataFrame(rows)
    act = A[A["active"]].copy()
    print(f"signals total={len(A)}  active on={len(act)}  ({len(act)/len(A)*100:.0f}%)")
    # took signaled side (one-sided on the signaled dir)?
    onesided = act[(act['bought_up'] > 0) != (act['bought_dn'] > 0)]
    print(f"one-sided slugs (bought exactly one outcome): {len(onesided)}/{len(act)}")
    took = act["took_signaled"].fillna(False)
    print(f"took SIGNALED direction (one-sided AND on signaled side): {took.sum()}/{len(act)} = {took.mean()*100:.1f}%")
    # of one-sided slugs, what fraction match the signaled direction?
    os2 = onesided.copy()
    os2["side"] = np.where(os2["bought_up"] > 0, "Up", "Down")
    os2["matches_sig"] = (os2["side"] == os2["sig_dir"])
    print(f"of one-sided slugs, side==signal: {os2['matches_sig'].sum()}/{len(os2)} = {os2['matches_sig'].mean()*100:.1f}%")
    # latency on signaled-side fills
    offs = act["off"].dropna()
    if len(offs):
        print(f"exec offset from post_ts (s): n={len(offs)} med={offs.median():.0f} "
              f"mean={offs.mean():.1f} std={offs.std():.1f} min={offs.min():.0f} max={offs.max():.0f}")
        print(f"  offset in [-10,30]: {((offs>=-10)&(offs<=30)).mean()*100:.0f}%")
    # fill px vs entry
    fp = act.dropna(subset=["fill_px", "ec"]).copy()
    fp["px_minus_ec"] = fp["fill_px"] - fp["ec"]
    if len(fp):
        print(f"fill_px - entry_cents: n={len(fp)} med={fp['px_minus_ec'].median():.1f}c "
              f"mean={fp['px_minus_ec'].mean():.1f}c  within±3c={((fp['px_minus_ec'].abs()<=3)).mean()*100:.0f}%")
    A.to_csv(CACHE / f"validate_{cand[:10]}.csv", index=False)
    return A, took.sum(), len(act), (offs.std() if len(offs) else None)


A1, took1, nact1, std1 = analyze(CAND)
A2, took2, nact2, std2 = analyze(CAND2)

# profile candidate
def profile(cand):
    print(f"\n--- PROFILE {cand} ---")
    for win in ["all", "30d", "7d", "1d"]:
        p = _cget(f"profit_{cand}_{win}", f"{LB}/profit", {"window": win, "address": cand})
        v = _cget(f"volume_{cand}_{win}", f"{LB}/volume", {"window": win, "address": cand})
        def amt(x):
            return x[0].get("amount") if isinstance(x, list) and x and isinstance(x[0], dict) else x
        print(f"  {win}: profit={amt(p)}  volume={amt(v)}")
    # activity: does it ONLY trade btc 5m updown? sample recent TRADE activity
    act = _cget(f"act_trade_{cand}", f"{DATA}/activity",
                {"user": cand, "limit": 500, "type": "TRADE"})
    if isinstance(act, list) and act:
        slugs = [str(a.get("slug", "")) for a in act]
        import collections
        kinds = collections.Counter()
        for s in slugs:
            mm = re.match(r"([a-z]+)-updown-(\d+[mh])", s)
            kinds[(mm.group(1), mm.group(2)) if mm else ("other", s[:20])] += 1
        print(f"  recent {len(act)} TRADE events by market type: {dict(list(kinds.most_common(8)))}")

profile(CAND)
profile(CAND2)

print("\n", TAG, "OUTPUT END", flush=True)
