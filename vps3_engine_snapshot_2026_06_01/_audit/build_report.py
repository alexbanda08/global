import json, collections

d = json.load(open("all_findings.json", encoding="utf-8"))

SEV = {"critical":0, "high":1, "medium":2, "low":3, "none":4}
FAM_LABEL = {
 "snv5_eth_5m":"Sniper-V5 ETH 5m","snv5_eth_15m":"Sniper-V5 ETH 15m","snv5_btc_5m":"Sniper-V5 BTC 5m",
 "snv5_btc_15m":"Sniper-V5 BTC 15m","snv5_sol_5m":"Sniper-V5 SOL 5m","snv5_sol_15m":"Sniper-V5 SOL 15m",
 "kalshi":"Kalshi sniper","fast_taker":"Fast-taker","shadow_updown":"shadow_poly_updown",
 "updown_momo_v1":"Updown momo v1","updown_momo_v2":"Updown momo v2","updown_v3v4":"Updown v3/v4",
 "updown_inverse":"Updown INV_NIGHT","updown_sniper_hod":"Updown sniper_hod","updown_vwap_off":"Updown vwap_off",
}

# index verify verdicts per sleeve
verify = {}   # sleeve_id -> verdict dict (last one wins)
for r in d:
    for v in r.get("verifications", []):
        vd = v.get("verdict") or {}
        verify[v["sleeve_id"]] = vd

rows = []  # flattened sleeve rows w/ family + post-verify
for r in d:
    fam = r["fam"]
    for s in (r.get("audit") or {}).get("sleeves", []):
        sid = s["sleeve_id"]
        vd = verify.get(sid)
        post_sev = s["severity"]; post_status = s["status"]; vnote=""
        if vd:
            verdict = vd.get("verdict")
            if verdict == "DOWNGRADED":
                post_sev = vd.get("severity", post_sev); vnote = f"[verify:DOWNGRADED] {vd.get('note','')}"
            elif verdict == "REFUTED":
                post_status = "OK"; post_sev="none"; vnote = f"[verify:REFUTED] {vd.get('note','')}"
            elif verdict == "CONFIRMED":
                post_sev = vd.get("severity", post_sev); vnote = f"[verify:CONFIRMED] {vd.get('note','')}"
            elif verdict == "NEEDS_LIVE_DATA":
                vnote = f"[verify:NEEDS_LIVE_DATA] {vd.get('note','')}"
        rows.append({"fam":fam,"sid":sid,"status":s["status"],"severity":s["severity"],
                     "post_status":post_status,"post_sev":post_sev,"summary":s.get("summary",""),
                     "evidence":s.get("evidence",""),"backtest_ref":s.get("backtest_ref",""),
                     "live_wr":s.get("live_wr",""),"expected_wr":s.get("expected_wr",""),
                     "verdict": (vd or {}).get("verdict",""), "vnote":vnote})

# tallies
by_status = collections.Counter(x["status"] for x in rows)
by_post_sev = collections.Counter(x["post_sev"] for x in rows)
print("=== status (pre-verify) ===", dict(by_status))
print("=== post-verify severity ===", dict(by_post_sev))

def sevkey(x): return (SEV.get(x["post_sev"],9), x["fam"])

# CRITICAL + HIGH after verify, excluding refuted/OK
top = sorted([x for x in rows if x["post_sev"] in ("critical","high") and x["post_status"]!="OK"], key=sevkey)
print(f"\n=== TOP (critical+high, post-verify): {len(top)} ===")
for x in top:
    print(f"[{x['post_sev'].upper():8}] {x['sid']}  ({x['status']}{'/'+x['verdict'] if x['verdict'] else ''})")
    print(f"    {x['summary']}")

# ---- write master report ----
out = []
W = out.append
W("# Shadow Sleeve Implementation Audit — 2026-06-01")
W("")
W("_Live VPS3 tradingvenue engine (snapshot `vps3_engine_snapshot_2026_06_01/`) audited sleeve-by-sleeve against the "
  "creating engine / written spec / validation backtest in the global repo. 154 distinct sleeves firing in shadow over "
  "the trailing 7 days (source: `trading.events` kind=`poly_updown_resolution`). Method: 15 family agents → adversarial "
  "verify on every critical/high finding. Maker sleeves (acc/mas/pat) excluded — 0 fires in window._")
W("")
W("## Tally")
W("")
W(f"- **Pre-verify status:** OK {by_status.get('OK',0)} · BUG {by_status.get('BUG',0)} · "
  f"DISCREPANCY {by_status.get('DISCREPANCY',0)} · DATA_GAP {by_status.get('DATA_GAP',0)} · "
  f"UNVERIFIABLE {by_status.get('UNVERIFIABLE',0)}  (total 154)")
nver = sum(1 for x in rows if x['verdict'])
print_conf = collections.Counter(x['verdict'] for x in rows if x['verdict'])
W(f"- **Adversarial verify** ran on {nver} critical/high findings: "
  f"CONFIRMED {print_conf.get('CONFIRMED',0)} · DOWNGRADED {print_conf.get('DOWNGRADED',0)} · "
  f"REFUTED {print_conf.get('REFUTED',0)} · NEEDS_LIVE_DATA {print_conf.get('NEEDS_LIVE_DATA',0)}")
W(f"- **Post-verify severity:** critical {by_post_sev.get('critical',0)} · high {by_post_sev.get('high',0)} · "
  f"medium {by_post_sev.get('medium',0)} · low {by_post_sev.get('low',0)} · none/OK {by_post_sev.get('none',0)}")
W("")

W("## 🔴 Critical & high findings (post-verify, problem-confirmed)")
W("")
W("| sev | sleeve | type | live WR | finding |")
W("|-----|--------|------|---------|---------|")
for x in top:
    summ = x['summary'].replace("|","\\|")[:220]
    typ = x['status'] + (f"→{x['verdict']}" if x['verdict'] else "")
    W(f"| {x['post_sev']} | `{x['sid']}` | {typ} | {x['live_wr']} | {summ} |")
W("")

# detailed evidence for critical+high
W("## Evidence detail (critical & high)")
W("")
for x in top:
    W(f"### `{x['sid']}`  — {x['post_sev'].upper()} ({x['status']})")
    W(f"- **Family:** {FAM_LABEL.get(x['fam'],x['fam'])}  ·  **live WR:** {x['live_wr']}  ·  **expected:** {x['expected_wr']}")
    W(f"- **Finding:** {x['summary']}")
    if x['evidence']: W(f"- **Evidence:** {x['evidence']}")
    if x['backtest_ref']: W(f"- **Backtest ref:** {x['backtest_ref']}")
    if x['vnote']: W(f"- **Verify:** {x['vnote']}")
    W("")

# DATA GAPS
gaps = sorted([x for x in rows if x["status"]=="DATA_GAP"], key=sevkey)
W(f"## 🟡 Data gaps ({len(gaps)})")
W("")
W("| sev | sleeve | gap |")
W("|-----|--------|-----|")
for x in gaps:
    W(f"| {x['post_sev']} | `{x['sid']}` | {x['summary'].replace('|','\\|')[:200]} |")
W("")

# medium discrepancies/bugs (compact)
med = sorted([x for x in rows if x["post_sev"]=="medium" and x["post_status"] not in ("OK",) and x["status"]!="DATA_GAP"], key=sevkey)
W(f"## 🟠 Medium discrepancies/bugs ({len(med)})")
W("")
W("| sleeve | type | finding |")
W("|--------|------|---------|")
for x in med:
    W(f"| `{x['sid']}` | {x['status']} | {x['summary'].replace('|','\\|')[:180]} |")
W("")

# OK list
oks = [x for x in rows if x["post_status"]=="OK"]
W(f"## ✅ Implemented as expected ({len(oks)})")
W("")
W(", ".join(f"`{x['sid']}`" for x in oks))
W("")

# per-family engine summaries + invariant fails
W("## Per-family engine mechanics + invariant check")
W("")
for r in d:
    a = r.get("audit") or {}
    W(f"### {FAM_LABEL.get(r['fam'],r['fam'])} (`{r['fam']}`)")
    if a.get("engine_summary"): W(f"- **Live mechanics:** {a['engine_summary']}")
    inv = a.get("invariant_findings", [])
    fails = [i for i in inv if i.get("status") in ("fail","mismatch")]
    if fails:
        for i in fails:
            W(f"  - ⚠️ **{i['invariant']}** — {i['status']}: {i['detail']}")
    else:
        W("  - invariants: no fail/mismatch flagged")
    if a.get("spec_files_found"): W(f"- specs: {', '.join(a['spec_files_found'][:6])}")
    if a.get("backtest_files_found"): W(f"- backtests: {', '.join(a['backtest_files_found'][:6])}")
    W("")

open("../../strategy_lab/reports/SHADOW_SLEEVE_AUDIT_2026_06_01.md","w",encoding="utf-8").write("\n".join(out))
print("\nWROTE strategy_lab/reports/SHADOW_SLEEVE_AUDIT_2026_06_01.md  (",len(out),"lines )")
