"""Per-sleeve summary table for the 18 momo sleeves."""
import csv
import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone

ROOT = r"C:\Users\alexandre bandarra\Desktop\global"
RES_CSV = os.path.join(ROOT, "data/v4/shadow_trades_2026_05_06/momo_resolutions.csv")
EVT_CSV = os.path.join(ROOT, "data/v4/shadow_trades_2026_05_06/momo_all_events.csv")

DEPLOY_UTC = datetime(2026, 5, 6, 0, 28, 0, tzinfo=timezone.utc)
NOW_UTC = datetime.now(timezone.utc)
H_ALIVE = (NOW_UTC - DEPLOY_UTC).total_seconds() / 3600
NOTIONAL = 25.0  # paper $25 → normalize to $1 by dividing by 25

# All 18 sleeves
ASSETS = ["btc", "eth", "sol"]
TFS = ["5m", "15m"]
EXITS = ["HOLD", "HEDGE", "SELL"]
ALL = [(a, t, e) for a in ASSETS for t in TFS for e in EXITS]


def sleeve_id(a, t, e):
    return f"poly_updown_{a}_{t}_momo_{e}"


# Init counters
counts = {sid: {"sigs": 0, "ud": 0, "fills": 0, "res": 0, "wins": 0, "losses": 0, "hskp": 0, "pnl": 0.0}
          for sid in (sleeve_id(a, t, e) for a, t, e in ALL)}

# Tally events
with open(EVT_CSV, "r", encoding="utf-8") as fh:
    for r in csv.DictReader(fh):
        sid = r["sleeve_id"]
        if sid not in counts:
            continue
        c = counts[sid]
        kind = r["kind"]
        sig = r["sig"]
        reason = r["reason"]
        if kind == "poly_updown_signal":
            c["sigs"] += 1
            if sig in ("UP", "DOWN"):
                c["ud"] += 1
            if reason == "order_placed":
                c["fills"] += 1
        elif kind == "poly_updown_hedge_skip":
            c["hskp"] += 1

# Tally resolutions (PnL + W/L)
with open(RES_CSV, "r", encoding="utf-8") as fh:
    for r in csv.DictReader(fh):
        sid = r["sleeve_id"]
        if sid not in counts:
            continue
        d = json.loads(r["data"])
        c = counts[sid]
        c["res"] += 1
        c["pnl"] += float(d.get("pnl_usd") or 0)
        if d.get("won"):
            c["wins"] += 1
        else:
            c["losses"] += 1

# Print table
print(f"# 18 Momo sleeves @ +{H_ALIVE:.1f}h since deploy ({DEPLOY_UTC.strftime('%Y-%m-%d %H:%M UTC')})")
print(f"# PnL normalized to $1 notional (paper was $25 → divide by 25)\n")

hdr = ("Sleeve", "h_alive", "Sigs", "U/D", "Fills", "Res", "W", "L", "Hit%", "Hskp", "P&L $1", "$/fill", "$/res")
widths = (37, 7, 5, 5, 6, 4, 3, 3, 6, 5, 9, 9, 9)
print(" ".join(h.ljust(w) if i == 0 else h.rjust(w) for i, (h, w) in enumerate(zip(hdr, widths))))
print("-" * (sum(widths) + len(widths) - 1))

# Order: by asset, tf, exit (as listed in spec)
for a, t, e in ALL:
    sid = sleeve_id(a, t, e)
    short_id = sid.replace("poly_updown_", "")
    c = counts[sid]
    hit = (c["wins"] / c["res"] * 100) if c["res"] else 0.0
    pnl_1 = c["pnl"] / NOTIONAL
    pf = (pnl_1 / c["fills"]) if c["fills"] else 0.0
    pr = (pnl_1 / c["res"]) if c["res"] else 0.0
    row = (
        short_id,
        f"{H_ALIVE:.1f}",
        f"{c['sigs']}",
        f"{c['ud']}",
        f"{c['fills']}",
        f"{c['res']}",
        f"{c['wins']}",
        f"{c['losses']}",
        f"{hit:.1f}",
        f"{c['hskp']}",
        f"{pnl_1:+.4f}",
        f"{pf:+.4f}",
        f"{pr:+.4f}",
    )
    print(" ".join(v.ljust(w) if i == 0 else v.rjust(w) for i, (v, w) in enumerate(zip(row, widths))))

# Totals
tot = {"sigs": 0, "ud": 0, "fills": 0, "res": 0, "wins": 0, "losses": 0, "hskp": 0, "pnl": 0.0}
for c in counts.values():
    for k in tot:
        tot[k] += c[k]
hit = (tot["wins"] / tot["res"] * 100) if tot["res"] else 0.0
pnl_1 = tot["pnl"] / NOTIONAL
pf = pnl_1 / tot["fills"] if tot["fills"] else 0.0
pr = pnl_1 / tot["res"] if tot["res"] else 0.0
print("-" * (sum(widths) + len(widths) - 1))
row = (
    "TOTAL (18 sleeves)",
    f"{H_ALIVE:.1f}",
    f"{tot['sigs']}",
    f"{tot['ud']}",
    f"{tot['fills']}",
    f"{tot['res']}",
    f"{tot['wins']}",
    f"{tot['losses']}",
    f"{hit:.1f}",
    f"{tot['hskp']}",
    f"{pnl_1:+.4f}",
    f"{pf:+.4f}",
    f"{pr:+.4f}",
)
print(" ".join(v.ljust(w) if i == 0 else v.rjust(w) for i, (v, w) in enumerate(zip(row, widths))))

print()
print("Legend:")
print("  Sigs    = total signal events (incl. NONE/no_signal scans)")
print("  U/D     = signal events with direction != NONE (= candidate fires)")
print("  Fills   = signal events with reason='order_placed' (entered position)")
print("  Res     = resolution events (settled trades)")
print("  W/L     = won/lost (from chainlink settlement)")
print("  Hit%    = W / Res")
print("  Hskp    = hedge_skip events (HEDGE policy couldn't place hedge)")
print("  P&L $1  = sum(pnl_usd) / 25  (normalize from $25 paper to $1 notional)")
print("  $/fill  = P&L_$1 / Fills")
print("  $/res   = P&L_$1 / Res")
