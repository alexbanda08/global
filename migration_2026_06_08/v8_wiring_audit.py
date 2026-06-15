import json, glob
from collections import Counter
SID = "poly_sniper_v5_eth_5m_l_ema50_hurst_grandparent_v8"
EXPECT_GATES = {"g_tr_above_ema50(ETH)", "g_hurst_trending(ETH,5m)", "g_grandparent_trend_with(ETH)"}

ev = Counter()
offsets = Counter()
fills = Counter()
dirs = Counter()
gate_sets = Counter()
skip = Counter()
placed_all_pass = [0, 0]   # [pass, total]
asset_tf = Counter()
bad_gate = 0
pnls, wons = [], 0

for f in sorted(glob.glob("/var/log/tradingvenue/sniper_v5/2026-06-0[4-9].jsonl")):
    for line in open(f):
        if "grandparent_v8\"" not in line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("sleeve_id") != SID:
            continue
        et = d.get("event_type", "?")
        ev[et] += 1
        ge = d.get("gates_evaluated")
        if isinstance(ge, dict):
            gate_sets[tuple(sorted(ge.keys()))] += 1
            if set(ge.keys()) != EXPECT_GATES:
                bad_gate += 1
        if et == "sleeve_fire_placed":
            offsets[d.get("fire_offset_s")] += 1
            fills[d.get("fill_method")] += 1
            dirs[d.get("direction")] += 1
            asset_tf[(d.get("asset"), d.get("tf"))] += 1
            placed_all_pass[1] += 1
            if d.get("all_gates_passed"):
                placed_all_pass[0] += 1
        if et == "sleeve_fire_eval" and not d.get("all_gates_passed", True):
            skip[str(d.get("skip_reason"))] += 1
        if et == "sleeve_fire_resolved":
            p = d.get("pnl_usd")
            if p is not None:
                pnls.append(float(p)); wons += 1 if d.get("won") else 0

print("=== v8 base wiring audit (VPS3 shadow, Jun4-9) ===")
print("event_types:", dict(ev))
print("placed asset×tf:", dict(asset_tf), "  (spec: ETH 5m)")
print("placed offsets:", dict(offsets), "  (spec: 60)")
print("placed directions:", dict(dirs), "  (spec: BOTH = UP+DOWN)")
print("fill_method:", dict(fills), "  (spec: l25_walk/live, NO synthetic)")
print(f"placed all_gates_passed: {placed_all_pass[0]}/{placed_all_pass[1]}  (spec: 100%)")
print("gate-set variants seen:")
for gs, c in gate_sets.most_common():
    ok = "OK" if set(gs) == EXPECT_GATES else "!! UNEXPECTED"
    print(f"   {c:5d}  {ok}  {gs}")
print(f"records with non-spec gate set: {bad_gate}")
print("\ntop skip_reasons (confirms gates+spread applied):")
for r, c in skip.most_common(10):
    print(f"   {c:5d}  {r}")
if pnls:
    print(f"\nresolved: n={len(pnls)} WR={wons/len(pnls)*100:.1f}% total=${sum(pnls):+.1f} mean=${sum(pnls)/len(pnls):+.3f}")
