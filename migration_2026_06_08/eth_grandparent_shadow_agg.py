import json, glob
from collections import defaultdict

W = {"poly_sniper_v5_eth_5m_l_ema50_hurst_grandparent_v8": "v8",
     "poly_sniper_v5_eth_5m_l_ema50_hurst_grandparent_V10": "v10"}
agg = defaultdict(lambda: {"n": 0, "won": 0, "pnl": 0.0, "vw": 0.0, "first": None, "last": None})
for f in sorted(glob.glob("/var/log/tradingvenue/sniper_v5/2026-*.jsonl")):
    day = f.split("/")[-1][:10]
    with open(f) as fh:
        for line in fh:
            if "grandparent" not in line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("event_type") != "sleeve_fire_resolved":
                continue
            sid = d.get("sleeve_id", "")
            if sid not in W:
                continue
            p = d.get("pnl_usd")
            if p is None:
                continue
            a = agg[W[sid]]
            a["n"] += 1
            a["won"] += 1 if d.get("won") else 0
            a["pnl"] += float(p)
            a["vw"] += float(d.get("fill_vwap") or d.get("entry_vwap") or 0)
            a["first"] = a["first"] or day
            a["last"] = day

print("ETH grandparent sleeve — SHADOW realized fires (VPS3, OOS vs GA window):")
for tag in ("v8", "v10"):
    a = agg.get(tag)
    if not a:
        print(f"  {tag}: none"); continue
    n = a["n"]
    print(f"  {tag:4s} n={n:5d} WR={a['won']/n*100:5.1f}% total=${a['pnl']:+8.1f} "
          f"mean=${a['pnl']/n:+.3f} avg_vwap={a['vw']/n:.3f} span={a['first']}..{a['last']}")
