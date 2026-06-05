import json, glob, os

TDIR = r"C:/Users/alexandre bandarra/.claude/projects/C--Users-alexandre-bandarra-Desktop-global/2cb4dcb2-f579-40c2-8ef6-8168864764ce/subagents/workflows/wf_8256a2bf-f8d"

audits = []   # objects with 'sleeves'
verdicts = [] # objects with 'verdict'

def consider(inp):
    if not isinstance(inp, dict): return
    if "sleeves" in inp and "family" in inp:
        audits.append(inp)
    elif "verdict" in inp and "sleeve_id" in inp:
        verdicts.append(inp)

for f in glob.glob(os.path.join(TDIR, "agent-*.jsonl")):
    for line in open(f, encoding="utf-8"):
        line=line.strip()
        if not line: continue
        if "sleeves" not in line and '"verdict"' not in line: continue
        try: o=json.loads(line)
        except: continue
        msg = o.get("message") or {}
        content = msg.get("content")
        blocks = content if isinstance(content, list) else []
        for b in blocks:
            if isinstance(b, dict) and b.get("type")=="tool_use":
                consider(b.get("input"))

# dedup audits by family (keep the one with most sleeves)
best = {}
for a in audits:
    fam = a.get("family","?")
    if fam not in best or len(a.get("sleeves",[])) > len(best[fam].get("sleeves",[])):
        best[fam]=a
# dedup verdicts by sleeve_id (keep last)
vbest={}
for v in verdicts:
    vbest[v["sleeve_id"]]=v

print("recovered audit families:", len(best))
tot=0
for fam,a in best.items():
    n=len(a.get("sleeves",[])); tot+=n
    print(f"  {fam:18s} sleeves={n}")
print("TOTAL sleeve rows recovered:", tot)
print("verdicts recovered:", len(vbest))

# write reconstructed all_findings.json in the original shape: [{fam, audit, verifications}]
# map family label/key: audit['family'] may be the label, not the key. Normalize via known keys.
KEYS = ["snv5_eth_5m","snv5_eth_15m","snv5_btc_5m","snv5_btc_15m","snv5_sol_5m","snv5_sol_15m","kalshi",
        "fast_taker","shadow_updown","updown_momo_v1","updown_momo_v2","updown_v3v4","updown_inverse",
        "updown_sniper_hod","updown_vwap_off"]
def norm_key(famval, sleeves):
    # try to match by sleeve prefixes
    sids=[s.get("sleeve_id","") for s in sleeves]
    j=" ".join(sids)
    if famval in KEYS: return famval
    # heuristic from sleeves
    import re
    if any(s.startswith("kalshi") for s in sids): return "kalshi"
    if any(s.startswith("poly_fast_taker") for s in sids): return "fast_taker"
    if any(s.startswith("shadow_poly_updown") for s in sids): return "shadow_updown"
    if any("sniper_v5_eth_5m" in s for s in sids): return "snv5_eth_5m"
    if any("sniper_v5_eth_15m" in s for s in sids): return "snv5_eth_15m"
    if any("sniper_v5_btc_5m" in s for s in sids): return "snv5_btc_5m"
    if any("sniper_v5_btc_15m" in s for s in sids): return "snv5_btc_15m"
    if any("sniper_v5_sol_5m" in s for s in sids): return "snv5_sol_5m"
    if any("sniper_v5_sol_15m" in s for s in sids): return "snv5_sol_15m"
    if any("_momo_v2" in s for s in sids): return "updown_momo_v2"
    if any("_momo" in s for s in sids): return "updown_momo_v1"
    if any("INV_NIGHT" in s for s in sids): return "updown_inverse"
    if any("_sniper_hod" in s for s in sids): return "updown_sniper_hod"
    if any("_vwap_" in s for s in sids): return "updown_vwap_off"
    if any("_v3" in s or "_v4" in s for s in sids): return "updown_v3v4"
    return famval

out=[]
used=set()
for fam,a in best.items():
    sleeves=a.get("sleeves",[])
    key=norm_key(fam, sleeves)
    verifs=[{"sleeve_id":s["sleeve_id"],"verdict":vbest[s["sleeve_id"]]} for s in sleeves if s["sleeve_id"] in vbest]
    out.append({"fam":key,"audit":a,"verifications":verifs})
    used.add(key)

json.dump(out, open("all_findings.json","w",encoding="utf-8"), indent=1)
print("REWROTE all_findings.json with", sum(len(r['audit']['sleeves']) for r in out), "sleeve rows across", len(out), "families")
