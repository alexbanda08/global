import json, glob
from collections import defaultdict
targets = ["poly_fast_taker_lagv2_btc_5m","poly_fast_taker_lagv2_btc_15m",
           "poly_fast_taker_lagv2_eth_5m","poly_fast_taker_lagv2_eth_15m"]
res = defaultdict(list); placed = defaultdict(int); ev = defaultdict(int)
for fp in glob.glob("/var/log/tradingvenue/sniper_v5/*.jsonl"):
    with open(fp) as f:
        for line in f:
            try: r = json.loads(line)
            except: continue
            sid = r.get("sleeve_id")
            if sid not in targets: continue
            et = r.get("event_type")
            if et == "sleeve_fire_eval": ev[sid] += 1
            elif et == "sleeve_fire_placed": placed[sid] += 1
            elif et == "sleeve_fire_resolved": res[sid].append(r)
for sid in targets:
    rr = res[sid]
    if not rr:
        print(sid, "evals=%d placed=%d resolved=0" % (ev[sid], placed[sid])); continue
    def won(r):
        if r.get("won") is True: return True
        return (r.get("outcome") or "").lower() == (r.get("direction") or "").lower()
    w = sum(1 for r in rr if won(r))
    aligned = checked = 0
    for r in rr:
        bps = r.get("price_delta_bps"); d = r.get("direction")
        if bps is not None and d:
            checked += 1
            lead = "UP" if bps > 0 else "DOWN"
            if d == lead: aligned += 1
    print("%s evals=%d placed=%d resolved=%d WIN=%d WR=%.1f%%" % (sid, ev[sid], placed[sid], len(rr), w, 100*w/len(rr)))
    print("   direction==leading(sign delta_bps): %d/%d" % (aligned, checked))
    for r in rr[:5]:
        print("   dir=%s delta_bps=%s outcome=%s fill_vwap=%s pnl=%s offset=%s" % (
            r.get("direction"), r.get("price_delta_bps"), r.get("outcome"),
            r.get("fill_vwap"), r.get("pnl_usd"), r.get("fire_offset_s")))
