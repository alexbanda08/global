"""Diagnose cross-token spread distribution on live V5 fires."""
import json
import statistics

path = "/var/log/tradingvenue/sniper_v5/2026-05-27.jsonl"

n_with_books = 0
n_spread_pass_live = 0
sums = []
diffs = []
samples = []

with open(path) as f:
    for line in f:
        try:
            r = json.loads(line)
        except Exception:
            continue
        bk = r.get("l25_book_snapshot")
        if not bk or bk.get("up_vwap") is None or bk.get("dn_vwap") is None:
            continue
        up_v = bk["up_vwap"]
        dn_v = bk["dn_vwap"]
        live_spread = abs(up_v - (1.0 - dn_v))
        n_with_books += 1
        sf = 0.025 if r["asset"] == "SOL" else 0.02
        if live_spread <= sf:
            n_spread_pass_live += 1
        sums.append(up_v + dn_v)
        diffs.append(live_spread)
        if len(samples) < 8:
            sleeve = r["sleeve_id"].replace("poly_sniper_v5_", "")
            samples.append((sleeve, up_v, dn_v, 1 - dn_v, live_spread, sf, live_spread <= sf))

print(f"Evals with both UP+DOWN book snapshots: {n_with_books}")
print(f"Live spread filter PASS count: {n_spread_pass_live} ({100*n_spread_pass_live/max(n_with_books,1):.1f}%)")
print()
print("Sample fires:")
for sleeve, up, dn, inv_dn, sp, sf, passed in samples:
    print(f"  {sleeve[:38]:38} up={up:.4f} dn={dn:.4f} (1-dn)={inv_dn:.4f} cross_spread={sp:.4f} sf={sf} pass={passed}")
print()
print(f"up_vwap + dn_vwap distribution (should be ~1.0 if market is fair):")
print(f"  min={min(sums):.3f} max={max(sums):.3f} mean={statistics.mean(sums):.3f} median={statistics.median(sums):.3f}")
print(f"  stdev={statistics.stdev(sums):.3f}")
print()
print(f"cross_spread distribution:")
print(f"  min={min(diffs):.4f} max={max(diffs):.4f} mean={statistics.mean(diffs):.4f} median={statistics.median(diffs):.4f}")
print()
healthy = sum(1 for d in diffs if d < 0.05)
mod = sum(1 for d in diffs if 0.05 <= d < 0.20)
extreme = sum(1 for d in diffs if d >= 0.20)
print(f"Cross-spread breakdown:")
print(f"  < 0.05 (healthy, < 5%):      {healthy:>5} ({100*healthy/len(diffs):.1f}%)")
print(f"  0.05-0.20 (moderate):        {mod:>5} ({100*mod/len(diffs):.1f}%)")
print(f"  >= 0.20 (extreme, > 20%):    {extreme:>5} ({100*extreme/len(diffs):.1f}%)")
