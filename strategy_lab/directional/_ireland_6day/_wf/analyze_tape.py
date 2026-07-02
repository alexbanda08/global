import json, sys
from datetime import datetime, timezone
from collections import defaultdict

path = r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\directional\_ireland_6day\vps3_scalp_exits_clean.tsv"

rows = []
with open(path, "r", encoding="utf-8") as f:
    for line in f:
        line = line.rstrip("\n")
        if not line.strip():
            continue
        if line.startswith("SET"):
            continue
        parts = line.split("\t", 1)
        if len(parts) != 2:
            continue
        ts_str, js = parts
        try:
            data = json.loads(js)
        except Exception as e:
            print("PARSE FAIL:", e, line[:80])
            continue
        rows.append((ts_str, data))

print(f"Total rows parsed: {len(rows)}")

# only real fills (sleeve_scalp_exit), not counterfactual
fills = [(ts, d) for ts, d in rows if d.get("event_type") == "sleeve_scalp_exit"]
print(f"sleeve_scalp_exit rows: {len(fills)}")

# parse timestamps -> use 'at' field (ts_str) as fire time proxy; but better use fire_us from data
def parse_at(ts_str):
    # format: 2026-06-11 02:21:05.789619+02
    # normalize timezone offset +02 -> +02:00
    s = ts_str.strip()
    if len(s) > 6 and (s[-3] in "+-") and ":" not in s[-3:]:
        s = s + ":00"
    return datetime.fromisoformat(s)

records = []
for ts, d in fills:
    at = parse_at(ts)
    fire_us = d.get("fire_us")
    fire_dt = datetime.fromtimestamp(fire_us/1e6, tz=timezone.utc) if fire_us else None
    se = d.get("scalp_exit", {})
    pnl = se.get("scalp_pnl_usd", d.get("pnl_usd"))
    entry_vwap = se.get("entry_vwap")
    exit_vwap = se.get("exit_vwap")
    shares = se.get("shares")
    exit_depth = se.get("exit_book_depth")
    exit_trigger = se.get("exit_trigger")
    placed_size = d.get("placed_size_usd")
    records.append(dict(at=at, fire_dt=fire_dt, pnl=pnl, entry_vwap=entry_vwap,
                         exit_vwap=exit_vwap, shares=shares, exit_depth=exit_depth,
                         exit_trigger=exit_trigger, placed_size=placed_size, slug=d.get("slug")))

records.sort(key=lambda r: r["fire_dt"])

print("\n=== First/last fire ===")
print(records[0]["fire_dt"], "->", records[-1]["fire_dt"])
span_days = (records[-1]["fire_dt"] - records[0]["fire_dt"]).total_seconds()/86400
print(f"Span: {span_days:.2f} days")

# active days (distinct calendar dates with >=1 fire) -- for fires/day cadence
active_dates = sorted(set(r["fire_dt"].date() for r in records))
print(f"\nDistinct active dates: {len(active_dates)} -> {active_dates}")

# fires/day using distinct active days
n = len(records)
fires_per_day_active = n / len(active_dates)
print(f"\nfires/day (n / distinct active days) = {n} / {len(active_dates)} = {fires_per_day_active:.2f}")
fires_per_day_span = n / span_days if span_days > 0 else float('nan')
print(f"fires/day (n / full calendar span incl gaps) = {n} / {span_days:.2f} = {fires_per_day_span:.2f}")

# gap analysis: identify contiguous "runs" (shadow was likely only intermittently running)
gaps = []
for i in range(1, len(records)):
    dt = (records[i]["fire_dt"] - records[i-1]["fire_dt"]).total_seconds()
    gaps.append(dt)
import statistics
gaps_hours = [g/3600 for g in gaps]
print(f"\nGap stats (hours): min={min(gaps_hours):.2f} median={statistics.median(gaps_hours):.2f} max={max(gaps_hours):.2f}")
# count gaps > 6h as "downtime" breaks
big_gaps = [g for g in gaps_hours if g > 6]
print(f"Gaps > 6h: {len(big_gaps)} (sum {sum(big_gaps):.1f}h)")

# max concurrent open positions: position open window = [fire_us, fire_us+60s] (or up to 5 min if held)
# use fire_dt + 60s as close, but some may resolve at 5min (window resolution) -- check exit_trigger
triggers = defaultdict(int)
for r in records:
    triggers[r["exit_trigger"]] += 1
print(f"\nExit trigger breakdown: {dict(triggers)}")

# compute overlap: does any fire start within 60s of previous fire's start?
overlaps = 0
overlap_pairs = []
for i in range(1, len(records)):
    dt = (records[i]["fire_dt"] - records[i-1]["fire_dt"]).total_seconds()
    if dt < 60:
        overlaps += 1
        overlap_pairs.append((records[i-1]["fire_dt"], records[i]["fire_dt"], dt))
print(f"\nFires within 60s of prior fire (2-way overlap events): {overlaps}")
for p in overlap_pairs[:20]:
    print("  ", p)

# max concurrent via sweep (assume hold = 60s for time60 exits, 300s cap for others)
events = []
for r in records:
    start = r["fire_dt"]
    hold_s = 60
    if r["exit_trigger"] not in ("time60", None):
        hold_s = 300  # conservative cap for window-resolution holds
    end = start.timestamp() + hold_s
    events.append((start.timestamp(), 1))
    events.append((end, -1))
events.sort(key=lambda x: (x[0], -x[1]))  # opens before closes at same ts
cur = 0
maxc = 0
for ts, delta in events:
    cur += delta
    maxc = max(maxc, cur)
print(f"\nMax concurrent open positions (sweep, hold=60s/300s): {maxc}")

# PnL stats
pnls = [r["pnl"] for r in records if r["pnl"] is not None]
print(f"\n=== PnL stats (n={len(pnls)}) at observed $5 clip ===")
mean_pnl = statistics.mean(pnls)
stdev_pnl = statistics.stdev(pnls) if len(pnls) > 1 else 0
print(f"mean = {mean_pnl:.4f}")
print(f"stdev = {stdev_pnl:.4f}")
print(f"sum = {sum(pnls):.2f}")
print(f"min = {min(pnls):.4f}  max = {max(pnls):.4f}")
wins = [p for p in pnls if p > 0]
losses = [p for p in pnls if p <= 0]
print(f"win rate = {len(wins)}/{len(pnls)} = {len(wins)/len(pnls)*100:.1f}%")
print(f"avg win = {statistics.mean(wins) if wins else 0:.4f}  avg loss = {statistics.mean(losses) if losses else 0:.4f}")

# daily pnl series & drawdown at $5 clip (use actual placed_size to confirm $5)
sizes = set(r["placed_size"] for r in records)
print(f"\nplaced_size_usd values seen: {sizes}")

daily = defaultdict(float)
for r in records:
    if r["pnl"] is not None:
        daily[r["fire_dt"].date()] += r["pnl"]
days_sorted = sorted(daily.keys())
print("\n=== Daily PnL ===")
cum = 0
peak = 0
maxdd = 0
curve = []
for d in days_sorted:
    cum += daily[d]
    peak = max(peak, cum)
    dd = peak - cum
    maxdd = max(maxdd, dd)
    curve.append((d, daily[d], cum, dd))
    print(f"{d}  daily={daily[d]:+.2f}  cum={cum:+.2f}  dd={dd:.2f}")
print(f"\nMax drawdown (daily-agg, $5 clip): ${maxdd:.2f}")

# also trade-level (intra-day) running drawdown, more granular
cum2 = 0
peak2 = 0
maxdd2 = 0
for r in records:
    if r["pnl"] is None:
        continue
    cum2 += r["pnl"]
    peak2 = max(peak2, cum2)
    dd2 = peak2 - cum2
    maxdd2 = max(maxdd2, dd2)
print(f"Max drawdown (trade-level running equity, $5 clip): ${maxdd2:.2f}")

# exit_book_depth vs 25x shares check (depth ceiling for $25 clip)
print("\n=== Exit book depth vs scaled clip check ===")
depths = [r["exit_depth"] for r in records if r["exit_depth"] is not None]
shares5 = [r["shares"] for r in records if r["shares"] is not None]
print(f"exit_book_depth: min={min(depths):.0f} median={statistics.median(depths):.0f} max={max(depths):.0f}")
# at $5 clip, shares ~ 5/entry_vwap ~ 8-10 shares. At $25 clip, shares would be 5x -> ~40-50 shares
# check what fraction of exit vwap value the $25-scaled notional represents vs depth
ratios = []
for r in records:
    if r["exit_depth"] and r["shares"] and r["exit_vwap"]:
        scaled_notional_25 = r["shares"] * 5 * r["exit_vwap"]  # 5x shares at $25 clip, valued at exit vwap
        ratio = scaled_notional_25 / r["exit_depth"]
        ratios.append(ratio)
print(f"$25-clip scaled exit notional / exit_book_depth: mean={statistics.mean(ratios)*100:.1f}% median={statistics.median(ratios)*100:.1f}% max={max(ratios)*100:.1f}%")

# bootstrap: probability of CI>0 at N=100/200/400 given observed per-trade distribution
import random
random.seed(42)
def bootstrap_ci_positive_prob(pnls, N, n_boot=5000):
    successes = 0
    for _ in range(n_boot):
        sample = [random.choice(pnls) for _ in range(N)]
        m = statistics.mean(sample)
        s = statistics.stdev(sample) if len(sample) > 1 else 0
        se = s / (N ** 0.5)
        ci_low = m - 1.96 * se
        if ci_low > 0:
            successes += 1
    return successes / n_boot

for N in [100, 200, 400]:
    p = bootstrap_ci_positive_prob(pnls, N)
    print(f"P(95% CI lower bound > 0) at N={N}: {p*100:.1f}%")

# days to reach 200/400 fires at observed cadence
for target in [200, 400]:
    days_active = target / fires_per_day_active
    print(f"Days to reach {target} fires (active-day cadence {fires_per_day_active:.2f}/day): {days_active:.1f} days")
