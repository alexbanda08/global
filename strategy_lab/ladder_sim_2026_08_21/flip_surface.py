# P(outcome flips | displacement from strike, time remaining) — the physics table —
# plus the market's implied flip probability (losing-side token price) in the same
# buckets, so "is the discounted heavy side cheap or expensive?" is answerable.
# Truth chain: displacement from Binance 1s closes (B(t) - B(slot_start)); final
# outcome from Chainlink resolutions (market_resolutions_v2). Basis caveat: Binance
# vs Chainlink level offset makes tiny |d| ambiguous -> report the sign-agreement
# diagnostic and treat the 0-10$ bucket as the ambiguity zone.
import gzip, csv, json, math
from collections import defaultdict

DIR = r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\ladder_sim_2026_08_21"
D_EDGES = [0, 10, 25, 50, 75, 100, 150, 250, float("inf")]   # $ displacement buckets
def dbucket(d):
    for i in range(len(D_EDGES) - 1):
        if D_EDGES[i] <= d < D_EDGES[i + 1]:
            return i
    return len(D_EDGES) - 2

# elapsed sample points per tf (seconds since open)
SAMPLES = {300: [60, 90, 120, 150, 180, 210, 240, 270, 285],
           900: [120, 240, 360, 480, 600, 720, 780, 840, 870]}

def load_px():
    ts, cl = [], []
    with gzip.open(DIR + r"\btc_1s_2wk.csv.gz", "rt", newline="") as fh:
        rd = csv.reader(fh); next(rd)
        for row in rd:
            ts.append(int(row[0]) // 1_000_000); cl.append(float(row[1]))
    px = dict(zip(ts, cl))
    lo, hi = ts[0], ts[-1]
    # carry-forward lookup
    def at(t):
        t = int(t)
        for k in range(t, max(lo, t - 30) - 1, -1):
            v = px.get(k)
            if v is not None:
                return v
        return None
    return at, lo, hi

def load_res(path):
    out = {}
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            out[row["slug"]] = dict(
                start=int(row["slot_start_us"]) // 1_000_000,
                end=int(row["slot_end_us"]) // 1_000_000,
                outcome=row["outcome"],
                strike=float(row["strike_price"]) if row["strike_price"] else None)
    return out

def main():
    at, lo, hi = load_px()
    res5 = load_res(DIR + r"\btc5m_resolutions_2wk.csv")
    res15 = load_res(DIR + r"\btc15m_resolutions_2wk.csv")
    print(f"px seconds {lo}..{hi}; res5 {len(res5)} res15 {len(res15)}", flush=True)

    # diagnostics: binance-vs-chainlink agreement + basis
    agree = tot = 0; basis = []
    for slug, m in res5.items():
        b0, b1 = at(m["start"]), at(m["end"] - 1)
        if b0 is None or b1 is None or m["start"] < lo + 60:
            continue
        tot += 1
        if (b1 > b0) == (m["outcome"] == "Up"):
            agree += 1
        if m["strike"]:
            basis.append(b0 - m["strike"])
    basis.sort()
    print(f"sign agreement binance-vs-chainlink (5m): {agree}/{tot} = {100*agree/tot:.1f}%")
    print(f"basis B(open)-strike: median {basis[len(basis)//2]:+.1f}$  p10 {basis[len(basis)//10]:+.1f}  p90 {basis[9*len(basis)//10]:+.1f}")

    # true flip surface
    surf = defaultdict(lambda: [0, 0])         # (tf, elapsed, dbucket) -> [n, flips]
    win_disp = {}                              # (slug, elapsed) -> (leader_up, absd) for implied pass
    for tf, res in ((300, res5), (900, res15)):
        for slug, m in res.items():
            if m["start"] < lo + 60 or m["end"] > hi:
                continue
            b0 = at(m["start"])
            if b0 is None:
                continue
            for el in SAMPLES[tf]:
                b = at(m["start"] + el)
                if b is None:
                    continue
                d = b - b0
                if d == 0:
                    continue
                leader_up = d > 0
                flip = (m["outcome"] == "Up") != leader_up
                key = (tf, el, dbucket(abs(d)))
                surf[key][0] += 1; surf[key][1] += flip
                win_disp[(slug, el)] = (leader_up, abs(d))

    for tf in (300, 900):
        print(f"\n=== TRUE P(flip) — btc-updown-{tf//60}m — rows: seconds ELAPSED (t_rem = {'{:d}'.format(tf)}-elapsed) ===")
        hdr = " ".join(f"{'{:.0f}-{:.0f}'.format(D_EDGES[i], D_EDGES[i+1]) if D_EDGES[i+1]!=float('inf') else '250+':>10s}" for i in range(len(D_EDGES) - 1))
        print(f"{'elapsed':>8s} {hdr}")
        for el in SAMPLES[tf]:
            cells = []
            for i in range(len(D_EDGES) - 1):
                n, f = surf[(tf, el, i)]
                cells.append(f"{100*f/n:6.1f}%{n:4d}" if n else " " * 10)
            print(f"{el:>7d}s " + " ".join(f"{c:>10s}" for c in cells))

    json.dump({f"{k[0]}|{k[1]}|{k[2]}": v for k, v in surf.items()}, open(DIR + r"\flip_surface.json", "w"))
    json.dump({f"{k[0]}|{k[1]}": v for k, v in win_disp.items()}, open(DIR + r"\win_disp.json", "w"))
    print("\nwrote flip_surface.json / win_disp.json", flush=True)

    # ---- market-implied: last print of LOSER token at each sample time (5m tape only)
    print("loading trades tape for implied pricing...", flush=True)
    # per (slug, elapsed) we need last price of loser token at start+el
    want = defaultdict(list)                   # slug -> sorted sample times
    for (slug, el) in win_disp:
        if slug.startswith("btc-updown-5m-"):
            want[slug].append(el)
    state = {}                                 # slug -> {True: px, False: px}
    idx = {}                                   # slug -> next sample index
    impl = defaultdict(lambda: [0, 0.0, 0.0])  # (el, db) -> [n, sum_implied, sum_true_flip]
    for v in want.values():
        v.sort()
    res5s = {s: m["start"] for s, m in res5.items()}
    with gzip.open(DIR + r"\btc5m_trades_2wk.csv.gz", "rt", newline="") as fh:
        rd = csv.reader(fh); h = next(rd); ix = {c: i for i, c in enumerate(h)}
        it, isl, io, ip = ix["timestamp_us"], ix["slug"], ix["outcome"], ix["price"]
        for row in rd:
            slug = row[isl]
            if slug not in want:
                continue
            t = int(row[it]) / 1e6
            start = res5s[slug]
            el_list = want[slug]
            i = idx.get(slug, 0)
            st = state.setdefault(slug, {})
            # flush samples passed
            while i < len(el_list) and t > start + el_list[i]:
                el = el_list[i]
                ld = win_disp.get((slug, el))
                if ld:
                    leader_up, absd = ld
                    loser_px = st.get(not leader_up)
                    if loser_px is not None and 0.0 < loser_px < 1.0:
                        m = load_res_cache5[slug]
                        flip = (m["outcome"] == "Up") != leader_up
                        k = (el, dbucket(absd))
                        impl[k][0] += 1; impl[k][1] += loser_px; impl[k][2] += flip
                i += 1
            idx[slug] = i
            st[row[io][0] == "U"] = float(row[ip])
    print(f"\n=== 5m: market price of the LOSING side vs true P(flip) (implied - true, pp; + = overpriced) ===")
    hdr = " ".join(f"{'{:.0f}-{:.0f}'.format(D_EDGES[i], D_EDGES[i+1]) if D_EDGES[i+1]!=float('inf') else '250+':>14s}" for i in range(len(D_EDGES) - 1))
    print(f"{'elapsed':>8s} {hdr}")
    for el in SAMPLES[300]:
        cells = []
        for i in range(len(D_EDGES) - 1):
            n, s_impl, s_flip = impl[(el, i)]
            if n >= 5:
                cells.append(f"{100*s_impl/n:5.1f}/{100*s_flip/n:5.1f}{n:4d}")
            else:
                cells.append(" " * 14)
        print(f"{el:>7d}s " + " ".join(f"{c:>14s}" for c in cells))
    json.dump({f"{k[0]}|{k[1]}": v for k, v in impl.items()}, open(DIR + r"\implied_surface.json", "w"))
    print("wrote implied_surface.json")

load_res_cache5 = None
if __name__ == "__main__":
    load_res_cache5 = load_res(DIR + r"\btc5m_resolutions_2wk.csv")
    main()
