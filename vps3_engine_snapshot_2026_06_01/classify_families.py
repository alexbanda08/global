import csv, json, re, collections

rows = list(csv.DictReader(open("firing_sleeves_7d.csv")))
rows = [r for r in rows if r.get("sleeve_id")]

def family(s):
    # order matters
    if s.startswith("poly_sniper_v5_eth_5m"): return "snv5_eth_5m"
    if s.startswith("poly_sniper_v5_eth_15m"): return "snv5_eth_15m"
    if s.startswith("poly_sniper_v5_btc_5m"): return "snv5_btc_5m"
    if s.startswith("poly_sniper_v5_btc_15m"): return "snv5_btc_15m"
    if s.startswith("poly_sniper_v5_sol_5m"): return "snv5_sol_5m"
    if s.startswith("poly_sniper_v5_sol_15m"): return "snv5_sol_15m"
    if s.startswith("kalshi_sniper"): return "kalshi"
    if s.startswith("poly_fast_taker"): return "fast_taker"
    if s.startswith("shadow_poly_updown"): return "shadow_updown"
    if s.startswith("poly_updown"):
        if "_momo_v2" in s: return "updown_momo_v2"
        if "_momo" in s: return "updown_momo_v1"
        if "_v3" in s or "_v4" in s: return "updown_v3v4"
        if "INV_NIGHT" in s or "_volume_" in s: return "updown_inverse"
        if "_sniper_hod" in s: return "updown_sniper_hod"
        if "_vwap_" in s: return "updown_vwap_off"
        return "updown_other"
    return "UNCLASSIFIED"

buckets = collections.defaultdict(list)
for r in rows:
    buckets[family(r["sleeve_id"])].append({
        "sleeve_id": r["sleeve_id"], "fires": int(r["fires"]),
        "wr": r["wr"], "pnl": float(r["pnl"])})

out = {k: sorted(v, key=lambda x:-x["fires"]) for k,v in buckets.items()}
json.dump(out, open("families.json","w"), indent=2)

total = sum(len(v) for v in buckets.values())
print(f"total sleeves classified: {total}")
for k in sorted(buckets, key=lambda k:-len(buckets[k])):
    n=len(buckets[k]); pnl=sum(x['pnl'] for x in buckets[k])
    print(f"  {k:20s} {n:3d} sleeves  netPnL={pnl:9.2f}")
if "UNCLASSIFIED" in buckets:
    print("UNCLASSIFIED:", [x['sleeve_id'] for x in buckets['UNCLASSIFIED']])
