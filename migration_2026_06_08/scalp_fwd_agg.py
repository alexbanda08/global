import json, glob, random
from collections import defaultdict

rows = defaultdict(list)   # sleeve -> list of (pnl, won, vwap, exit_type, day)
firsts, lasts = {}, {}
for f in sorted(glob.glob("/var/log/tradingvenue/sniper_v5/2026-*.jsonl")):
    day = f.split("/")[-1][:10]
    with open(f) as fh:
        for line in fh:
            if "sleeve_scalp_exit" not in line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("event_type") != "sleeve_scalp_exit":
                continue
            sid = d.get("sleeve_id", "?")
            if "scalp" not in sid:
                continue
            p = d.get("pnl_usd")
            if p is None:
                continue
            rows[sid].append((float(p), bool(d.get("won")), d.get("fill_vwap"),
                              d.get("exit_type"), day))
            firsts.setdefault(sid, day)
            lasts[sid] = day


def boot_ci(xs, n=2000):
    random.seed(42)
    k = len(xs)
    if k < 2:
        return (float("nan"), float("nan"))
    means = []
    for _ in range(n):
        means.append(sum(xs[random.randrange(k)] for _ in range(k)) / k)
    means.sort()
    return (means[int(0.025 * n)], means[int(0.975 * n)])


hdr = ("sleeve", "n", "WR", "mean$", "sum$", "CI_lo", "CI_hi", "span")
print("%-52s %4s %5s %8s %9s %8s %8s  %s" % hdr)
out = []
for sid, v in rows.items():
    pnls = [x[0] for x in v]
    n = len(pnls)
    wr = sum(1 for x in v if x[1]) / n
    mean = sum(pnls) / n
    lo, hi = boot_ci(pnls)
    out.append((sid, n, wr, mean, sum(pnls), lo, hi, firsts[sid] + ".." + lasts[sid]))

for sid, n, wr, mean, tot, lo, hi, span in sorted(out, key=lambda r: -r[1]):
    print("%-52s %4d %4.0f%% %8.3f %9.1f %8.3f %8.3f  %s" %
          (sid, n, wr * 100, mean, tot, lo, hi, span))

print("TOTAL_SLEEVES", len(out), "TOTAL_EXITS", sum(r[1] for r in out))
