# Do the professional wallets buy the LOSING (displaced-against) side when the
# price is far from strike? Do they cut it? Same measurement for our live fills.
# Displacement at fill time from Binance 1s closes; winner truth from Chainlink
# resolutions; fills from data-api activity caches (union of tags, deduped).
import json, gzip, csv, glob, os
from collections import defaultdict

DIR = r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\ladder_sim_2026_08_21"
CACHE = os.path.join(DIR, "..", "wallet_hunt", "cache", "_pm_portfolio")
WALLETS = [("ours", "0x51a5f36d"), ("b27", "0xb27bc932"), ("b945", "0xb945945d"),
           ("pbot6", "0x21d0a97a"), ("pbot5", "0x1b58d3de"),
           ("pbot2", "0x095fd7cc"), ("pbot3", "0x74a2b82f")]
T0 = 1785801600          # Aug 4 (klines warm from Aug 3 16:00)
D_EDGES = [0, 10, 25, 50, 75, 100, 150, 250, float("inf")]
def dbucket(d):
    for i in range(len(D_EDGES) - 1):
        if D_EDGES[i] <= d < D_EDGES[i + 1]:
            return i
    return len(D_EDGES) - 2
DLAB = ["0-10", "10-25", "25-50", "50-75", "75-100", "100-150", "150-250", "250+"]

# price lookup
ts_l, cl_l = [], []
with gzip.open(DIR + r"\btc_1s_2wk.csv.gz", "rt", newline="") as fh:
    rd = csv.reader(fh); next(rd)
    for row in rd:
        ts_l.append(int(row[0]) // 1_000_000); cl_l.append(float(row[1]))
PX = dict(zip(ts_l, cl_l)); PLO, PHI = ts_l[0], ts_l[-1]
def px_at(t):
    for k in range(int(t), max(PLO, int(t) - 30) - 1, -1):
        v = PX.get(k)
        if v is not None:
            return v
    return None

RES = {}
for f, dur in ((r"\btc5m_resolutions_2wk.csv", 300), (r"\btc15m_resolutions_2wk.csv", 900)):
    with open(DIR + f, newline="") as fh:
        for row in csv.DictReader(fh):
            RES[row["slug"]] = (int(row["slot_start_us"]) // 1_000_000, dur, row["outcome"])

def load_wallet(short):
    d = os.path.join(CACHE, short)
    seen, fills = set(), []
    for path in sorted(glob.glob(os.path.join(d, "activity_TRADE_2026_08_*.json"))):
        try:
            recs = json.load(open(path))
        except Exception:
            continue
        for r in recs:
            slug = r.get("slug", "")
            if not (slug.startswith("btc-updown-5m-") or slug.startswith("btc-updown-15m-")):
                continue
            ts = r["timestamp"]
            if ts < T0:
                continue
            k = (r.get("transactionHash"), r.get("asset"), r.get("side"),
                 int(float(r.get("size") or 0) * 100), ts)
            if k in seen:
                continue
            seen.add(k)
            fills.append((ts, slug, r["side"], r["outcome"] == "Up",
                          float(r["price"]), float(r["size"])))
    return fills

def analyze(name, fills, tf_dur):
    B = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])   # db -> [loser_sh, winner_sh_sameD, loser_cost, loser_win_sh]
    sells = defaultdict(lambda: [0.0, 0.0])          # cut-loser sh, sell-winner sh (elapsed>=60)
    n_in = 0
    for (ts, slug, side, is_up, prc, sh) in fills:
        meta = RES.get(slug)
        if not meta:
            continue
        start, dur, outc = meta
        if dur != tf_dur:
            continue
        el = ts - start
        if el < 30 or el >= dur:      # skip open ambiguity + out-of-window
            continue
        b0 = px_at(start); b = px_at(ts)
        if b0 is None or b is None:
            continue
        d = b - b0
        if abs(d) < 1:
            continue
        leader_up = d > 0
        buying_loser = (is_up != leader_up)
        db = dbucket(abs(d))
        n_in += 1
        if side == "BUY":
            if buying_loser:
                B[db][0] += sh; B[db][2] += sh * prc
                if (outc == "Up") == is_up:
                    B[db][3] += sh
            else:
                B[db][1] += sh
        else:
            if buying_loser:  # selling the token whose side is the LOSER = cutting
                sells[db][0] += sh
            else:
                sells[db][1] += sh
    return B, sells, n_in

for tf_dur, tf_name in ((300, "5m"), (900, "15m")):
    print(f"\n================ btc-updown-{tf_name} ================")
    print(f"{'wallet':7s} {'|d| bucket':>8s} {'loser_sh':>9s} {'ldr_sh':>8s} {'%loser':>7s} {'loser_vwap':>10s} {'loserWR':>8s} {'edge c/sh':>9s} | {'cut_sh':>7s} {'sellW_sh':>8s}")
    for name, short in WALLETS:
        fills = load_wallet(short)
        B, sells, n_in = analyze(name, fills, tf_dur)
        if n_in == 0:
            continue
        for db in range(len(DLAB)):
            lsh, wsh, lcost, lwin = B[db]
            csh, swsh = sells[db]
            if lsh + wsh < 20:
                continue
            vw = lcost / lsh if lsh else 0
            wr = lwin / lsh if lsh else 0
            edge = (wr - vw) * 100 if lsh else 0
            print(f"{name:7s} {DLAB[db]:>8s} {lsh:9.0f} {wsh:8.0f} {100*lsh/(lsh+wsh):6.1f}% "
                  f"{vw:10.3f} {100*wr:7.1f}% {edge:+9.1f} | {csh:7.0f} {swsh:8.0f}")
        print()
