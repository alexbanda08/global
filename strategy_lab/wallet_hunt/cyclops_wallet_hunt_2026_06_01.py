"""CYCLOPS WALLET HUNT 2026-06-01 — match last-2-day cyclops_signals to on-chain
Polymarket trades to find the executor wallet (if any).

Run: C:/Python314/python.exe strategy_lab/wallet_hunt/cyclops_wallet_hunt_2026_06_01.py

Pipeline:
 1. parse last-2-day SIGNALs (post_ts >= 2026-05-30) from fresh CSV
 2. reconstruct slug btc-updown-5m-<slot_start_unix> (EDT=UTC-4)
 3. WR: channel WIN/LOSS labels + our chainlink truth (load_resolutions)
 4. resolve each slug -> condition_id (canonical market_id; gamma fallback)
 5. pull /trades?market=<condition_id>; match BUY + signaled side + price + time window
 6. rank wallets by # signals matched, validate top candidate
 7. profile top candidate (lb profit/volume/activity)

HTTP is cached to cache/_cyclops_hunt/.
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

TAG = "CYCLOPS_WALLET_HUNT_2026_06_01"
print(TAG, "OUTPUT START", flush=True)

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
WH = ROOT / "strategy_lab" / "wallet_hunt"
CSV = WH / "cyclops_signals_fresh_2026_06_01.csv"
CACHE = WH / "cache" / "_cyclops_hunt"
CACHE.mkdir(parents=True, exist_ok=True)

DATA = "https://data-api.polymarket.com"
GAMMA = "https://gamma-api.polymarket.com"
UA = {"User-Agent": "global-strategy-lab/1.0", "Accept": "application/json"}

# infra / exchange contracts to exclude (from harvest_market_wallets.py)
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
    m = re.search(r"([A-Z][a-z]{2})\s+(\d{1,2})\s+(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})\s*(AM|PM)\s*ET", str(raw))
    if not m:
        return None
    mon, day, h1, mi1, h2, mi2, ampm = m.groups()
    h1, mi1, day, mon = int(h1), int(mi1), int(day), MONTHS[mon]
    hh = h1 % 12
    if ampm == "PM":
        hh += 12
    et = dt.datetime(2026, mon, day, hh, mi1, tzinfo=dt.timezone(dt.timedelta(hours=-4)))  # EDT
    return int(et.astimezone(dt.timezone.utc).timestamp())


def entry_cents(raw):
    m = re.search(r"Entry\s+(\d+)¢", str(raw))
    return int(m.group(1)) if m else None


# ---------------- cached HTTP ----------------
def _cget(name, url, params):
    fp = CACHE / f"{name}.json"
    if fp.exists():
        try:
            return json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            pass
    time.sleep(0.25)
    try:
        r = requests.get(url, params=params, headers=UA, timeout=15)
        if r.status_code != 200:
            obj = {"_status": r.status_code, "_text": r.text[:200]}
        else:
            obj = r.json()
    except Exception as e:
        obj = {"_err": str(e)}
    fp.write_text(json.dumps(obj, default=str), encoding="utf-8")
    return obj


def fetch_trades(cid, slug):
    """All trades on a market. data-api /trades REQUIRES conditionId (slug ignored)."""
    out = []
    for p in range(4):  # up to 2000 trades; 5m markets rarely exceed this
        page = _cget(f"trades_{slug}_p{p}", f"{DATA}/trades",
                     {"market": cid, "limit": 500, "offset": p * 500})
        if not isinstance(page, list) or not page:
            break
        out.extend(page)
        if len(page) < 500:
            break
    return out


def gamma_condition_id(slug):
    """Fallback slug->conditionId via gamma /markets?slug=."""
    j = _cget(f"gamma_{slug}", f"{GAMMA}/markets", {"slug": slug})
    if isinstance(j, list) and j and isinstance(j[0], dict):
        return j[0].get("conditionId") or j[0].get("condition_id")
    if isinstance(j, dict):
        return j.get("conditionId") or j.get("condition_id")
    return None


# ========================= 1. PARSE SIGNALS =========================
df = pd.read_csv(CSV)
df["post_dt"] = pd.to_datetime(df["post_ts"], utc=True, errors="coerce")
CUTOFF = pd.Timestamp("2026-05-30T00:00:00Z")

sig = df[(df["type"] == "SIGNAL") & (df["post_dt"] >= CUTOFF)].copy()
sig["slot_start"] = sig["raw"].map(parse_slot_et)
sig["entry_c"] = sig.apply(
    lambda r: r["entry_cents"] if pd.notna(r["entry_cents"]) and str(r["entry_cents"]).strip() not in ("", "nan")
    else entry_cents(r["raw"]), axis=1)
sig["entry_c"] = pd.to_numeric(sig["entry_c"], errors="coerce")
sig["dir"] = sig["direction"].str.upper().str.strip()
sig = sig.dropna(subset=["slot_start"]).copy()
sig["slot_start"] = sig["slot_start"].astype(int)
sig["slug"] = "btc-updown-5m-" + sig["slot_start"].astype(str)

print(f"\n--- 1. LAST-2-DAY SIGNALS (post_ts >= 2026-05-30) ---")
print(f"n signals = {len(sig)}  | dir counts = {sig['dir'].value_counts().to_dict()}")
print(f"entry_c parsed = {sig['entry_c'].notna().sum()}  | "
      f"post_ts range {sig['post_dt'].min()} -> {sig['post_dt'].max()}")

# ========================= 2. WR =========================
res = load_resolutions(assets=["BTC"], timeframes=["5m"]).copy()
res["slot_s"] = (res["slot_start_us"] // 1_000_000).astype(int)
res_map = res.set_index("slot_s")[["outcome", "market_id", "slug"]].to_dict("index")

# (a) channel WIN/LOSS labels for these slots
wl = df[df["type"].isin(["WIN", "LOSS"])].copy()
wl["slot_start"] = wl["raw"].map(parse_slot_et)
wl = wl.dropna(subset=["slot_start"]).copy()
wl["slot_start"] = wl["slot_start"].astype(int)
sig_slots = set(sig["slot_start"])
wl_recent = wl[wl["slot_start"].isin(sig_slots)].copy()
n_win = (wl_recent["type"] == "WIN").sum()
n_loss = (wl_recent["type"] == "LOSS").sum()
chan_wr = n_win / (n_win + n_loss) * 100 if (n_win + n_loss) else float("nan")

# (b) our chainlink truth
sig["cl_outcome"] = sig["slot_start"].map(lambda s: res_map.get(s, {}).get("outcome"))
sig["cl_cid"] = sig["slot_start"].map(lambda s: res_map.get(s, {}).get("market_id"))
m = sig[sig["cl_outcome"].notna()].copy()
m["bot_dir"] = m["dir"].str.title()
m["cl_win"] = (m["bot_dir"] == m["cl_outcome"])
cl_wr = m["cl_win"].mean() * 100 if len(m) else float("nan")

print(f"\n--- 2. WIN RATE (last 2 days) ---")
print(f"(a) CHANNEL labels on signal slots: {n_win}W {n_loss}L = {chan_wr:.1f}%  (n={n_win+n_loss})")
print(f"(b) OUR CHAINLINK truth on signals: {m['cl_win'].sum()}W "
      f"{(~m['cl_win']).sum()}L = {cl_wr:.1f}%  (n={len(m)} of {len(sig)} signals matched to chainlink)")
print(f"    signals NOT in chainlink (too recent): {sig['cl_outcome'].isna().sum()}")

# ========================= 3. RESOLVE CID + PULL TRADES + MATCH =========================
print(f"\n--- 3. RESOLVE CONDITION_ID + PULL TRADES ---", flush=True)
TOKEN_OF = {"UP": "Up", "DOWN": "Down"}
PRICE_TOL = 0.03
W_PRE, W_POST = 10, 120  # seconds around post_ts

wallet_matched_slugs = defaultdict(set)   # wallet -> set(slug) matched on right side+price+time
wallet_side = defaultdict(lambda: defaultdict(int))  # wallet -> {Up:n, Down:n} matched side
wallet_offsets = defaultdict(list)        # wallet -> [exec_ts - post_ts]
wallet_all_slugs = defaultdict(set)       # wallet -> any BUY on these slugs
wallet_anyside = defaultdict(lambda: defaultdict(int))  # all BUY outcome counts on these slugs

per_signal = []
n_cid_canon = n_cid_gamma = n_cid_none = 0
n_trades_total = 0

for i, (_, r) in enumerate(sig.iterrows()):
    slug = r["slug"]
    cid = r["cl_cid"]
    src = "canon"
    if not (isinstance(cid, str) and cid.startswith("0x")):
        cid = gamma_condition_id(slug)
        src = "gamma"
    if isinstance(cid, str) and cid.startswith("0x"):
        if src == "canon":
            n_cid_canon += 1
        else:
            n_cid_gamma += 1
    else:
        n_cid_none += 1
        per_signal.append({"slug": slug, "dir": r["dir"], "entry_c": r["entry_c"],
                           "cid": None, "n_trades": 0, "n_match": 0})
        continue

    trades = fetch_trades(cid, slug)
    n_trades_total += len(trades)
    post_ts = int(r["post_dt"].timestamp())
    want_side = TOKEN_OF.get(r["dir"])
    ec = r["entry_c"]
    matched_wallets = set()

    for t in trades:
        w = str(t.get("proxyWallet", "")).lower()
        if not w.startswith("0x") or w in EXCLUDE:
            continue
        side = str(t.get("side", "")).upper()
        outcome = str(t.get("outcome", ""))  # 'Up'/'Down'
        price = t.get("price")
        ts = t.get("timestamp")
        try:
            price = float(price); ts = int(ts)
        except Exception:
            continue
        if side != "BUY":
            continue
        # any BUY on this slug
        wallet_all_slugs[w].add(slug)
        wallet_anyside[w][outcome] += 1
        # match: right side + price + time window
        if outcome != want_side:
            continue
        price_ok = (ec is None) or (abs(price * 100 - ec) <= PRICE_TOL * 100)
        time_ok = (post_ts - W_PRE) <= ts <= (post_ts + W_POST)
        if price_ok and time_ok:
            matched_wallets.add(w)
            wallet_matched_slugs[w].add(slug)
            wallet_side[w][outcome] += 1
            wallet_offsets[w].append(ts - post_ts)

    per_signal.append({"slug": slug, "dir": r["dir"], "entry_c": ec,
                       "cid": cid, "src": src, "n_trades": len(trades),
                       "n_match_wallets": len(matched_wallets)})
    if (i + 1) % 15 == 0:
        print(f"  processed {i+1}/{len(sig)} signals, {n_trades_total} trades, "
              f"{len(wallet_matched_slugs)} candidate wallets", flush=True)

ps = pd.DataFrame(per_signal)
n_sig_with_cid = (ps["cid"].notna()).sum()
n_sig_matched = (ps["n_match_wallets"] > 0).sum()
print(f"\ncondition_id resolved: canon={n_cid_canon} gamma={n_cid_gamma} none={n_cid_none}")
print(f"signals with >=1 matching wallet: {n_sig_matched}/{n_sig_with_cid} (with cid)")
print(f"total trades pulled: {n_trades_total}")

# ========================= 4. RANK WALLETS =========================
print(f"\n--- 4. RANKED CANDIDATE WALLETS (by # signals matched) ---")
rows = []
for w, slugs in wallet_matched_slugs.items():
    offs = wallet_offsets[w]
    up = wallet_side[w].get("Up", 0); dn = wallet_side[w].get("Down", 0)
    rows.append({
        "wallet": w,
        "n_matched": len(slugs),
        "match_rate": len(slugs) / n_sig_with_cid if n_sig_with_cid else 0,
        "side_Up": up, "side_Down": dn,
        "n_all_buy_slugs": len(wallet_all_slugs[w]),
        "off_med": float(np.median(offs)) if offs else None,
        "off_min": int(min(offs)) if offs else None,
        "off_max": int(max(offs)) if offs else None,
    })
rank = pd.DataFrame(rows).sort_values("n_matched", ascending=False)
print(rank.head(20).to_string(index=False))

rank.to_csv(CACHE / "ranked_wallets.csv", index=False)
ps.to_csv(CACHE / "per_signal.csv", index=False)

# ========================= 5. VALIDATE TOP CANDIDATE =========================
print(f"\n--- 5. VALIDATE TOP CANDIDATE ---")
verdict = "signal-only / no single executor"
top = None
if len(rank):
    top = rank.iloc[0]
    w = top["wallet"]
    print(f"top wallet: {w}")
    print(f"  matched {top['n_matched']}/{n_sig_with_cid} signals (rate {top['match_rate']*100:.1f}%)")
    print(f"  side split on matches: Up={top['side_Up']} Down={top['side_Down']}")
    print(f"  exec offset from post_ts (s): med={top['off_med']} min={top['off_min']} max={top['off_max']}")
    # side-consistency: of all its BUY trades on these slugs, fraction on signaled dir
    # check direction alignment per slug
    slug_dir = dict(zip(sig["slug"], sig["dir"].map(lambda d: TOKEN_OF.get(d))))
    # count this wallet's anyside vs signaled
    consist = top["n_matched"] / top["n_all_buy_slugs"] if top["n_all_buy_slugs"] else 0
    print(f"  side-consistency (matched / all-BUY slugs): {consist*100:.1f}%")
    # dominance test
    if top["match_rate"] >= 0.5 and (top["n_matched"] >= 2 * (rank.iloc[1]["n_matched"] if len(rank) > 1 else 0)):
        verdict = f"SINGLE EXECUTOR: {w}"
    elif top["match_rate"] >= 0.6:
        verdict = f"SINGLE EXECUTOR: {w}"
    else:
        verdict = "signal-only / no single dominant executor"

print(f"\n>>> VERDICT: {verdict}")

# ========================= 6. PROFILE TOP =========================
prof = {}
if top is not None and ("SINGLE EXECUTOR" in verdict):
    w = top["wallet"]
    print(f"\n--- 6. PROFILE {w} ---", flush=True)
    lbp = {}
    for win in ["all", "30d", "7d", "1d"]:
        lbp[win] = _cget(f"profit_{w}_{win}", "http://lb-api.polymarket.com/profit",
                         {"window": win, "address": w})
    lbv = {}
    for win in ["all", "30d", "7d"]:
        lbv[win] = _cget(f"volume_{w}_{win}", "http://lb-api.polymarket.com/volume",
                         {"window": win, "address": w})
    def amt(p):
        if isinstance(p, list) and p and isinstance(p[0], dict):
            return p[0].get("amount")
        return None
    prof = {win: amt(lbp[win]) for win in lbp}
    print("  lb profit:", prof)
    print("  lb volume:", {win: amt(lbv[win]) for win in lbv})

print("\n", TAG, "OUTPUT END", flush=True)

# stash summary for report writing
summary = {
    "n_signals": int(len(sig)),
    "dir_counts": sig["dir"].value_counts().to_dict(),
    "chan_w": int(n_win), "chan_l": int(n_loss), "chan_wr": round(float(chan_wr), 1),
    "cl_w": int(m["cl_win"].sum()), "cl_l": int((~m["cl_win"]).sum()),
    "cl_n": int(len(m)), "cl_wr": round(float(cl_wr), 1),
    "n_cid_canon": n_cid_canon, "n_cid_gamma": n_cid_gamma, "n_cid_none": n_cid_none,
    "n_sig_with_cid": int(n_sig_with_cid), "n_sig_matched": int(n_sig_matched),
    "n_trades_total": int(n_trades_total),
    "verdict": verdict,
    "top": (rank.head(10).to_dict("records") if len(rank) else []),
    "profile": prof,
}
(CACHE / "summary.json").write_text(json.dumps(summary, default=str, indent=2), encoding="utf-8")
print("summary saved:", CACHE / "summary.json")
