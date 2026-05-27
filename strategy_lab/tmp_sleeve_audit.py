"""Audit per-sleeve activity in V5 JSONL — find which sleeves are firing vs silent."""
import json
from collections import Counter, defaultdict

path = "/var/log/tradingvenue/sniper_v5/2026-05-27.jsonl"

evals_by_sleeve = Counter()
placed_by_sleeve = Counter()
resolved_by_sleeve = Counter()
skip_reasons_by_sleeve = defaultdict(Counter)
gates_pass_count_by_sleeve = defaultdict(Counter)  # gate_name -> times True
gates_fail_count_by_sleeve = defaultdict(Counter)  # gate_name -> times False
first_event_us_by_sleeve = {}
last_event_us_by_sleeve = {}

with open(path) as f:
    for line in f:
        try:
            r = json.loads(line)
        except Exception:
            continue
        sid = r.get("sleeve_id", "?")
        et = r.get("event_type", "?")
        fire_us = r.get("fire_us")

        if et == "sleeve_fire_eval":
            evals_by_sleeve[sid] += 1
        elif et == "sleeve_fire_placed":
            placed_by_sleeve[sid] += 1
        elif et == "sleeve_fire_resolved":
            resolved_by_sleeve[sid] += 1

        sr = r.get("skip_reason")
        if sr:
            skip_reasons_by_sleeve[sid][sr[:60]] += 1

        gates = r.get("gates_evaluated") or {}
        for gname, passed in gates.items():
            if passed:
                gates_pass_count_by_sleeve[sid][gname] += 1
            else:
                gates_fail_count_by_sleeve[sid][gname] += 1

        if fire_us:
            if sid not in first_event_us_by_sleeve or fire_us < first_event_us_by_sleeve[sid]:
                first_event_us_by_sleeve[sid] = fire_us
            if sid not in last_event_us_by_sleeve or fire_us > last_event_us_by_sleeve[sid]:
                last_event_us_by_sleeve[sid] = fire_us

# Pull canonical sleeve roster from sniper_v5_sleeves.py via grep approach
import subprocess
roster_raw = subprocess.run(
    ["grep", "-oE", 'sleeve_id=\"[^\"]+\"', "/opt/tradingvenue/backend/app/strategies/polymarket/sniper_v5_sleeves.py"],
    capture_output=True, text=True,
)
roster_ids = set()
for line in roster_raw.stdout.splitlines():
    sid = line.split('"')[1]
    roster_ids.add(sid)

active_ids = set(evals_by_sleeve.keys())
silent_ids = roster_ids - active_ids
unknown_ids = active_ids - roster_ids  # sleeves in log but NOT in roster file

print(f"=== ROSTER vs ACTIVE ===")
print(f"Roster (defined in sleeves.py): {len(roster_ids)}")
print(f"Active (had >=1 event today):   {len(active_ids)}")
print(f"Silent (in roster, ZERO events): {len(silent_ids)}")
print(f"Unknown (in log, not in roster): {len(unknown_ids)}")
print()

if silent_ids:
    print(f"=== SILENT SLEEVES (in roster but ZERO events today) ===")
    for sid in sorted(silent_ids):
        print(f"  {sid}")
    print()

if unknown_ids:
    print(f"=== UNKNOWN SLEEVES (in log but NOT in roster) ===")
    for sid in sorted(unknown_ids):
        print(f"  {sid}")
    print()

# Active sleeves: classify by activity level
print(f"=== ACTIVITY LEVELS ===")
tiers = {"PLACED+RESOLVED": [], "EVALS_NO_PLACE": [], "ACTIVE_LOW_VOL": []}
for sid in active_ids:
    n_eval = evals_by_sleeve[sid]
    n_place = placed_by_sleeve[sid]
    n_resolve = resolved_by_sleeve[sid]
    if n_place > 0:
        tiers["PLACED+RESOLVED"].append((sid, n_eval, n_place, n_resolve))
    elif n_eval > 50:
        tiers["EVALS_NO_PLACE"].append((sid, n_eval, n_place, n_resolve))
    else:
        tiers["ACTIVE_LOW_VOL"].append((sid, n_eval, n_place, n_resolve))

for tier, items in tiers.items():
    print(f"\n--- {tier} ({len(items)} sleeves) ---")
    for sid, n_e, n_p, n_r in sorted(items, key=lambda x: -x[1])[:30]:
        short = sid.replace("poly_sniper_v5_", "")
        print(f"  {short[:55]:55} evals={n_e:>5} placed={n_p:>3} resolved={n_r:>3}")

# For sleeves with evals but no place, show top skip reasons
print(f"\n=== WHY EVALS_NO_PLACE SLEEVES DON'T PLACE ===")
for sid, n_e, n_p, n_r in tiers["EVALS_NO_PLACE"][:10]:
    short = sid.replace("poly_sniper_v5_", "")
    print(f"\n{short} ({n_e} evals)")
    for reason, count in skip_reasons_by_sleeve[sid].most_common(5):
        pct = 100 * count / n_e
        print(f"  {reason}: {count} ({pct:.1f}%)")

# For ACTIVE_LOW_VOL — these may indicate slot discovery issues
print(f"\n=== ACTIVE_LOW_VOL SLEEVES (< 50 evals — may have slot discovery issues) ===")
for sid, n_e, n_p, n_r in tiers["ACTIVE_LOW_VOL"]:
    short = sid.replace("poly_sniper_v5_", "")
    first_ts = first_event_us_by_sleeve.get(sid)
    last_ts = last_event_us_by_sleeve.get(sid)
    if first_ts and last_ts:
        span_h = (last_ts - first_ts) / 3_600_000_000
        print(f"  {short[:55]:55} evals={n_e:>4} span={span_h:.1f}h placed={n_p}")
