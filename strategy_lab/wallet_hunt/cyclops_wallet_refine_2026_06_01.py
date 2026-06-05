"""CYCLOPS WALLET REFINE 2026-06-01 — tighten the match to discriminate a true
directional executor bot from market-maker noise.

A real cyclops executor should, PER signal slug:
 - buy ONLY the signaled side (directional, not both sides like an MM)
 - fill near entry_cents (tight)
 - fire at a consistent, tight offset after post_ts (low-variance latency)

Reuses cached /trades from cyclops_wallet_hunt_2026_06_01 (cache/_cyclops_hunt/).
Run: C:/Python314/python.exe strategy_lab/wallet_hunt/cyclops_wallet_refine_2026_06_01.py
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

TAG = "CYCLOPS_WALLET_REFINE_2026_06_01"
print(TAG, "OUTPUT START", flush=True)

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
WH = ROOT / "strategy_lab" / "wallet_hunt"
CSV = WH / "cyclops_signals_fresh_2026_06_01.csv"
CACHE = WH / "cache" / "_cyclops_hunt"
DATA = "https://data-api.polymarket.com"
UA = {"User-Agent": "global-strategy-lab/1.0", "Accept": "application/json"}
EXCLUDE = {
    "0xe111180000d2663c0091e4f400237545b87b996b",
    "0xc5d563a36ae78145c45a50134d48a1215220f80a",
    "0x84ba896235059fe27727eaa2695a9f99220d9a7e",
    "0xd91e80cf2e7be2e162c6513ced06f1dd0da35296",
    "0x4d97dcd97ec945f40cf65f87097ace5ea0476045",
}
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


def _cget(name):
    fp = CACHE / f"{name}.json"
    if fp.exists():
        try:
            return json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


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


# rebuild signals
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
TOKEN = {"UP": "Up", "DOWN": "Down"}

# Per (wallet, slug) aggregate: net side, fills near entry, exec offset
# A directional executor BUYS one side only per slug.
rec = []  # one row per (wallet, slug) where wallet has BUY activity
sig_with_cid = []
for _, r in sig.iterrows():
    slug = r["slug"]
    if r["slot_start"] not in cid_map:
        continue
    sig_with_cid.append(slug)
    post_ts = int(r["post_dt"].timestamp())
    want = TOKEN.get(r["dir"])
    ec = r["entry_c"]
    trades = fetch_trades_cached(slug)
    # group this slug's BUY trades by wallet
    per_w = defaultdict(lambda: {"up_qty": 0.0, "dn_qty": 0.0, "up_n": 0, "dn_n": 0,
                                 "want_fills": [], "want_offsets": []})
    for t in trades:
        w = str(t.get("proxyWallet", "")).lower()
        if not w.startswith("0x") or w in EXCLUDE:
            continue
        if str(t.get("side", "")).upper() != "BUY":
            continue
        outc = str(t.get("outcome", ""))
        try:
            price = float(t.get("price")); ts = int(t.get("timestamp"))
            size = float(t.get("size", 0))
        except Exception:
            continue
        d = per_w[w]
        if outc == "Up":
            d["up_qty"] += size; d["up_n"] += 1
        elif outc == "Down":
            d["dn_qty"] += size; d["dn_n"] += 1
        if outc == want:
            d["want_fills"].append(price)
            d["want_offsets"].append(ts - post_ts)
    for w, d in per_w.items():
        net = d["up_qty"] - d["dn_qty"]
        # directional on signaled side?
        if want == "Up":
            directional = d["up_qty"] > 0 and d["dn_qty"] == 0
        else:
            directional = d["dn_qty"] > 0 and d["up_qty"] == 0
        # tight executor match: bought ONLY signaled side, a fill in [post-10,post+120], near entry
        in_win = [o for o in d["want_offsets"] if -10 <= o <= 120]
        near = [f for f in d["want_fills"] if (np.isnan(ec) or abs(f * 100 - ec) <= 2.0)]
        tight = directional and len(in_win) > 0 and len(near) > 0
        rec.append({"wallet": w, "slug": slug, "want": want, "directional": directional,
                    "tight": tight,
                    "best_off": min(in_win, default=None) if in_win else None})

R = pd.DataFrame(rec)
n_cid = len(set(sig_with_cid))
print(f"signals with cid (cached trades): {n_cid}")

# rank by TIGHT directional matches
agg = R.groupby("wallet").agg(
    n_slugs_active=("slug", "nunique"),
    n_directional=("directional", "sum"),
    n_tight=("tight", "sum"),
).reset_index()
agg["tight_rate"] = agg["n_tight"] / n_cid
# offset consistency for tight matches
offs = R[R["tight"]].dropna(subset=["best_off"]).groupby("wallet")["best_off"]
agg = agg.merge(offs.median().rename("off_med"), on="wallet", how="left")
agg = agg.merge(offs.std().rename("off_std"), on="wallet", how="left")
agg = agg.merge(offs.count().rename("off_n"), on="wallet", how="left")
agg = agg.sort_values(["n_tight", "n_directional"], ascending=False)

print("\n--- TIGHT directional executor ranking (bought ONLY signaled side, near entry, in window) ---")
print(agg.head(20).to_string(index=False))

# also: which wallets are active on the MOST signal slugs (any side) = MMs
mm = R.groupby("wallet")["slug"].nunique().sort_values(ascending=False)
print("\n--- most-active wallets on signal slugs (any side, = market makers) ---")
print(mm.head(10).to_string())

agg.to_csv(CACHE / "refine_ranking.csv", index=False)

# DOMINANCE: is there a wallet whose TIGHT directional match dominates?
print("\n--- DOMINANCE TEST ---")
top = agg.iloc[0]
second = agg.iloc[1] if len(agg) > 1 else None
print(f"top: {top['wallet']} n_tight={top['n_tight']} ({top['tight_rate']*100:.1f}%) "
      f"n_directional={top['n_directional']}/{top['n_slugs_active']} "
      f"off_med={top['off_med']} off_std={top['off_std']} off_n={top['off_n']}")
if second is not None:
    print(f"2nd: {second['wallet']} n_tight={second['n_tight']} ({second['tight_rate']*100:.1f}%)")

print("\n", TAG, "OUTPUT END", flush=True)
