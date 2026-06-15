"""SHORT-SIDE ARB SCAN (sum_bid > 1) — the half we never looked at.
arXiv 2508.03474: shorting (split $1 -> sell BOTH legs above $1) reportedly MORE profitable than the
long (sum_ask<1) side. b945 does NOT do this (0 splitPosition) -> NEW candidate, not a replica.
Scan: how often does (bid_up + bid_dn) > 1 on btc-15m, at what depth, net of fees + the split?

MECHANIC: splitPosition $1 -> 1 Up + 1 Down (CTF, ~$0.01 gas, NO trading fee). Sell both into bids;
selling = taker, fee 0.07·p·(1−p)/share/leg. Net/pair = sum_bid − 1 − [0.07·pu(1−pu)+0.07·pd(1−pd)] − gas.
Need sum_bid > ~1.035 at mid prices.

PRE-REG thresholds {1.00, 1.02, 1.035(fee-breakeven), 1.05}; depth = min(bid_size L0); NATIVE books.
DECISION: PURSUE if net-of-fee (sum_bid>1.035) exists in >10% of OOS windows with ≥$5 sellable depth.
Reuses engine m.load_books (validated loader). Checkpoint cache/_mm_shortside_scan.parquet.
"""
import sys, os, time
sys.path.insert(0, "data/v4/canonical"); sys.path.insert(0, os.path.dirname(__file__))
import importlib.util, numpy as np, pandas as pd

spec = importlib.util.spec_from_file_location("inv", os.path.join(os.path.dirname(__file__), "_mm_inv_engine.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
CACHE = os.path.join(os.path.dirname(__file__), "cache")
THRESH = [1.00, 1.02, 1.035, 1.05]
GAS = 0.01

def main():
    t0 = time.time()
    print("="*74); print("SHORT-SIDE ARB SCAN (sum_bid>1)"); print("="*74)
    print(f"PRE-REG thresholds {THRESH}; fee-breakeven ~1.035; native books")
    res = m.load_resolutions()
    res = res[res.slug.str.startswith("btc-updown-15m")]
    slot_map = dict(zip(res.slug, res.slot_start_s))
    out_map = dict(zip(res.slug, res.outcome))
    slug_set = set(res.slug)
    print(f"btc-15m slugs {len(slug_set)}", flush=True)
    tob = m.load_books(slug_set); print(f"books {len(tob)} t={time.time()-t0:.0f}s", flush=True)

    rows = []
    for slug in sorted(slug_set):
        ss = slot_map.get(slug)
        if ss is None: continue
        s0 = int(ss * 1e6); s1 = int((ss + 900) * 1e6)
        up = tob.get((slug, "Up")); dn = tob.get((slug, "Down"))
        if up is None or dn is None: continue
        tu, bpu, bsu = up["ts"], up["bp"][:, 0], up["bs"][:, 0]
        td, bpd, bsd = dn["ts"], dn["bp"][:, 0], dn["bs"][:, 0]
        win = (tu >= s0) & (tu < s1)
        tu, bpu, bsu = tu[win], bpu[win], bsu[win]
        if len(tu) == 0: continue
        # asof: most-recent Down bid at each Up ts
        j = np.searchsorted(td, tu, "right") - 1
        ok = j >= 0
        tu, bpu, bsu, j = tu[ok], bpu[ok], bsu[ok], j[ok]
        if len(tu) == 0: continue
        bpd_a, bsd_a = bpd[j], bsd[j]
        good = np.isfinite(bpu) & np.isfinite(bpd_a) & (bpu > 0) & (bpd_a > 0)
        if good.sum() == 0: continue
        bpu, bsu, bpd_a, bsd_a = bpu[good], bsu[good], bpd_a[good], bsd_a[good]
        sb = bpu + bpd_a
        depth = np.minimum(np.nan_to_num(bsu), np.nan_to_num(bsd_a))
        fee = 0.07 * bpu * (1 - bpu) + 0.07 * bpd_a * (1 - bpd_a)
        net_ps = sb - 1.0 - fee
        rec = dict(slug=slug, is_oos="IS" if s0 < m.IS_CUTOFF_US else "OOS",
                   n=len(sb), max_sb=float(sb.max()), med_sb=float(np.median(sb)))
        for th in THRESH:
            mk = sb > th
            rec[f"frac_{th}"] = float(mk.mean())
            cap_mask = mk & (net_ps > 0)
            # capturable $ = net/pair * sellable depth, minus one gas per opportunity-tick (bounded)
            rec[f"cap_{th}"] = float(np.sum(np.clip(net_ps[cap_mask], 0, None) * depth[cap_mask] - GAS * cap_mask.sum() / max(1, cap_mask.sum())))
        rows.append(rec)
    df = pd.DataFrame(rows)
    df.to_parquet(os.path.join(CACHE, "_mm_shortside_scan.parquet"), index=False)
    print(f"scanned {len(df)} slugs t={time.time()-t0:.0f}s")
    if len(df) == 0:
        print("NO DATA"); return
    for tag, sub in [("ALL", df), ("IS", df[df.is_oos == "IS"]), ("OOS", df[df.is_oos == "OOS"])]:
        print(f"\n--- {tag} (n={len(sub)}) ---")
        print(f"  per-slug median(max sum_bid)={sub.max_sb.median():.4f}  median(med sum_bid)={sub.med_sb.median():.4f}  "
              f"global max={sub.max_sb.max():.4f}")
        for th in THRESH:
            fr = sub[f"frac_{th}"].mean(); anyf = (sub[f"frac_{th}"] > 0).mean()
            cap = sub[f"cap_{th}"]
            print(f"  sum_bid>{th}: time-frac={100*fr:.3f}%  slugs-with-any={100*anyf:.1f}%  "
                  f"cap $/slug med={cap.median():.3f} mean={cap.mean():.3f}")
    th = 1.035; oos = df[df.is_oos == "OOS"]
    pursue = (oos[f"frac_{th}"] > 0).mean() > 0.10 and oos[f"cap_{th}"].median() > 1.0
    print(f"\nVERDICT (net-of-fee sum_bid>{th}, OOS): slugs-with-any={100*(oos[f'frac_{th}']>0).mean():.1f}%  "
          f"cap$/slug median={oos[f'cap_{th}'].median():.3f}  -> {'PURSUE' if pursue else 'PARK'}")
    print("="*74)

if __name__ == "__main__":
    main()
