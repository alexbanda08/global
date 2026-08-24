# Fill-by-fill debug traces for hand verification of the simulator.
# Window 1787319900 (Aug 21 13:45 UTC) is the external anchor: live tape showed
# real maker fills building 35 Up / 35 Dn by +67s at pvs ~0.93 (Up won).
import gzip, csv, sys
from sim_ladder_policies import sim_window, load_resolutions

DIR = r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\ladder_sim_2026_08_21"
TARGETS = sys.argv[1:] or ["btc-updown-5m-1787319900"]

res = load_resolutions()
need = set(TARGETS)
by_slug = {s: [] for s in need}
with gzip.open(DIR + r"\btc5m_trades_2wk.csv.gz", "rt", newline="") as fh:
    rd = csv.reader(fh)
    h = next(rd); ix = {c: i for i, c in enumerate(h)}
    for row in rd:
        if row[ix["slug"]] in need:
            by_slug[row[ix["slug"]]].append((
                int(row[ix["timestamp_us"]]) / 1e6, row[ix["outcome"]][0] == "U",
                float(row[ix["price"]]), float(row[ix["size"]]), row[ix["side"]] == "sell"))

for slug in TARGETS:
    meta = res[slug]; t0 = meta["slot_start_s"]; wu = meta["winner"] == "Up"
    prints = sorted(by_slug[slug])
    print(f"\n===== {slug} winner={meta['winner']} prints={len(prints)} "
          f"in-window={sum(1 for p in prints if t0 <= p[0] < t0+300)}")
    inwin = [p for p in prints if t0 - 30 <= p[0] < t0 + 300]
    print("tape (from T-30s; t, token, px, sz, taker-side):")
    for (t, u, px, sz, s) in inwin[:120]:
        print(f"  {t-t0:+7.1f}s {'Up' if u else 'Dn'} {px:.2f} x{sz:7.1f} {'SELL' if s else 'buy'}")
    if len(inwin) > 120:
        print(f"  ... {len(inwin)-120} more")
    for pol, ew in [("nolimit", 60), ("guard1", 60)]:
        r = sim_window(prints, t0, wu, pol, entry_window_s=ew)
        print(f"-- {pol} ew=60: pnl {r['pnl']:+.2f} up {r['up_sh']:.0f}@ dn {r['dn_sh']:.0f} "
              f"paired {r['paired']:.0f} pvs {r['pvs']} resid {r['resid']:.0f} won={r['resid_won']}")
        for (dt, side, q) in r["fills"]:
            print(f"     FILL {dt:+7.1f}s {side} @ {q:.2f} x5")
