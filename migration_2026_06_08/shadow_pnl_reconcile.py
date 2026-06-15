"""Step 1 — reconcile shadow pnl_usd accounting. For resolved sniper fires, recompute pnl
from (fill_vwap, fill_shares, won) under: (a) 0.07 winner-only fee, (b) no fee,
(c) legacy 2%-on-profit. Report which formula matches the logged pnl_usd."""
import json, glob

SID = "poly_sniper_v5_eth_5m_l_ema50_hurst_grandparent_v8"
rows = []
for f in sorted(glob.glob("/var/log/tradingvenue/sniper_v5/2026-06-0[5-8].jsonl")):
    for line in open(f):
        if SID not in line or "sleeve_fire_resolved" not in line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("sleeve_id") != SID or d.get("event_type") != "sleeve_fire_resolved":
            continue
        v, sh, w, p = d.get("fill_vwap"), d.get("fill_shares"), d.get("won"), d.get("pnl_usd")
        if None in (v, sh, w, p):
            continue
        rows.append((float(v), float(sh), bool(w), float(p)))
        if len(rows) >= 300:
            break

ok = {"fee07": 0, "nofee": 0, "legacy2": 0, "none": 0}
examples = []
for v, sh, w, p in rows:
    if w:
        fee07 = sh * (1 - v) * (1 - 0.07 * v)
        nofee = sh * (1 - v)
        legacy = sh * (1 - v) * 0.98
    else:
        fee07 = nofee = legacy = -sh * v
    cands = {"fee07": fee07, "nofee": nofee, "legacy2": legacy}
    hit = None
    for k, val in cands.items():
        if abs(val - p) < 0.005:
            hit = k; break
    ok[hit or "none"] += 1
    if hit is None and len(examples) < 3:
        examples.append((v, sh, w, p, cands))

print(f"reconciled {len(rows)} resolved v8 shadow fires:")
for k, c in ok.items():
    print(f"  {k:8s}: {c}")
for e in examples:
    print("  unmatched example:", e)
