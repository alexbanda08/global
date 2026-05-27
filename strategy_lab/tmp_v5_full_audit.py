"""Full audit of V5 fires today — identify synthetic-fill bug + stake anomalies."""
import json
from collections import Counter, defaultdict
from statistics import median

path = "/var/log/tradingvenue/sniper_v5/2026-05-27.jsonl"

placed = []
resolved = []
evals = []
all_intended_sizes = []
all_placed_sizes = []

# Per-sleeve breakdown
by_sleeve_placed = defaultdict(list)
by_sleeve_resolved = defaultdict(list)
by_sleeve_intended = defaultdict(set)
by_sleeve_book_state = defaultdict(lambda: {"both_books": 0, "only_dn": 0, "only_up": 0, "neither": 0})

with open(path) as f:
    for line in f:
        try:
            r = json.loads(line)
        except Exception:
            continue
        et = r.get("event_type")
        sid = r.get("sleeve_id", "?")
        intended = r.get("intended_size_usd")
        placed_size = r.get("placed_size_usd")

        if intended is not None:
            all_intended_sizes.append(intended)
            by_sleeve_intended[sid].add(intended)
        if placed_size is not None:
            all_placed_sizes.append(placed_size)

        if et == "sleeve_fire_eval":
            evals.append(r)
        elif et == "sleeve_fire_placed":
            placed.append(r)
            by_sleeve_placed[sid].append(r)
        elif et == "sleeve_fire_resolved":
            resolved.append(r)
            by_sleeve_resolved[sid].append(r)

        # Book state classification
        bk = r.get("l25_book_snapshot")
        if bk:
            up_v = bk.get("up_vwap")
            dn_v = bk.get("dn_vwap")
            if up_v is not None and dn_v is not None:
                by_sleeve_book_state[sid]["both_books"] += 1
            elif up_v is None and dn_v is not None:
                by_sleeve_book_state[sid]["only_dn"] += 1
            elif up_v is not None and dn_v is None:
                by_sleeve_book_state[sid]["only_up"] += 1
            else:
                by_sleeve_book_state[sid]["neither"] += 1

print(f"=== TOTALS ===")
print(f"Evals: {len(evals)}")
print(f"Placed: {len(placed)}")
print(f"Resolved: {len(resolved)}")
print()

print(f"=== STAKE SIZE DISTRIBUTION ===")
print(f"intended_size_usd unique values: {sorted(set(all_intended_sizes))}")
print(f"  count distribution: {Counter(all_intended_sizes).most_common()}")
print()
if all_placed_sizes:
    placed_only = [x for x in all_placed_sizes if x is not None]
    if placed_only:
        print(f"placed_size_usd values (only when fill happened): {sorted(set(placed_only))}")
print()

print(f"=== PER-SLEEVE INTENDED STAKE (looking for anomalies) ===")
for sid in sorted(by_sleeve_intended.keys()):
    sizes = sorted(by_sleeve_intended[sid])
    print(f"  {sid[:60]:60} intended_sizes={sizes}")
print()

print(f"=== PLACED FIRES (full data) ===")
for r in placed:
    sid = r["sleeve_id"]
    bk = r.get("l25_book_snapshot") or {}
    print(f"  {sid}")
    print(f"    dir={r['direction']} fill_vwap={r.get('fill_vwap')} fill_shares={r.get('fill_shares')}")
    print(f"    intended_size_usd={r.get('intended_size_usd')} placed_size_usd={r.get('placed_size_usd')}")
    print(f"    book: up_vwap={bk.get('up_vwap')} dn_vwap={bk.get('dn_vwap')}")
    print(f"          up_depth_usd={bk.get('up_depth_usd')} dn_depth_usd={bk.get('dn_depth_usd')}")
print()

print(f"=== RESOLVED FIRES (full data) ===")
for r in resolved:
    sid = r["sleeve_id"]
    bk = r.get("l25_book_snapshot") or {}
    print(f"  {sid}")
    print(f"    dir={r['direction']} outcome={r.get('outcome')} pnl_usd={r.get('pnl_usd')}")
    print(f"    fill_vwap={r.get('fill_vwap')} fill_shares={r.get('fill_shares')}")
    print(f"    intended_size_usd={r.get('intended_size_usd')} placed_size_usd={r.get('placed_size_usd')}")
    print(f"    book: up_vwap={bk.get('up_vwap')} dn_vwap={bk.get('dn_vwap')}")
    print(f"          up_depth_usd={bk.get('up_depth_usd')} dn_depth_usd={bk.get('dn_depth_usd')}")
print()

print(f"=== BOOK STATE CLASSIFICATION (per sleeve, top 20) ===")
for sid in sorted(by_sleeve_book_state.keys())[:20]:
    bs = by_sleeve_book_state[sid]
    total = sum(bs.values())
    short = sid.replace("poly_sniper_v5_", "")
    if total > 0:
        print(f"  {short[:55]:55} both={bs['both_books']}/{total} only_dn={bs['only_dn']} only_up={bs['only_up']} neither={bs['neither']}")
