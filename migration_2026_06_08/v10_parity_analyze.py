"""Parity diagnosis: VPS3 shadow-placed V10 fires vs Ireland live-placed, and WHY Ireland
skipped the ones VPS3 fired. Slug-set algebra across 4 sources."""
import csv, re, os
D = os.path.dirname(__file__)


def slugs(path, col=0, want_eth=True):
    out = set()
    with open(os.path.join(D, path)) as f:
        for row in csv.reader(f):
            if not row:
                continue
            s = row[col].strip()
            if want_eth and not s.startswith("eth-updown-5m-"):
                continue
            if s:
                out.add(s)
    return out


def rows(path):
    with open(os.path.join(D, path)) as f:
        return [r for r in csv.reader(f) if r and r[0].startswith("eth-updown-5m-")]


vps3 = rows("v10_vps3_placed.csv")          # slug,dir,vwap,cross_spread,won,pnl,day
vps3_slugs = {r[0] for r in vps3}
ire_live = rows("ire_live.csv")             # slug,dir,pnl,won,entry
ire_live_slugs = {r[0] for r in ire_live}
ire_paper_sig = slugs("ire_paper_sig.csv")  # Ireland-host gates DID pass (paper)
ire_live_sig = slugs("ire_live_sig.csv")    # live-path signaled

print("=== COUNTS (last 5d, eth-updown-5m slugs) ===")
print(f"  VPS3 shadow PLACED       : {len(vps3_slugs)}")
print(f"  Ireland LIVE PLACED      : {len(ire_live_slugs)}")
print(f"  Ireland PAPER signaled   : {len(ire_paper_sig)}")
print(f"  Ireland LIVE-path signaled: {len(ire_live_sig)}")

both = vps3_slugs & ire_live_slugs
only_vps3 = vps3_slugs - ire_live_slugs
print(f"\n=== OVERLAP ===")
print(f"  placed by BOTH           : {len(both)}")
print(f"  VPS3 placed, Ireland-live DID NOT: {len(only_vps3)}")
print(f"  Ireland-live placed, VPS3 did not: {len(ire_live_slugs - vps3_slugs)}")

# WHY did Ireland-live skip the only_vps3 ones?
in_paper = only_vps3 & ire_paper_sig       # Ireland gates passed but live didn't place
in_livesig = only_vps3 & ire_live_sig      # live path signaled but didn't place (exec drop)
not_signaled = only_vps3 - ire_paper_sig - ire_live_sig  # Ireland never signaled (feed/gate divergence)
print(f"\n=== WHY Ireland-live skipped the {len(only_vps3)} VPS3-only fires ===")
print(f"  (A) Ireland NEVER signaled (cross-host gate/feed divergence): {len(not_signaled)}")
print(f"  (B) Ireland signaled (paper or live) but did NOT place live  : {len(only_vps3 & (ire_paper_sig | ire_live_sig))}")
print(f"        - of which live-path signaled (exec layer drop)        : {len(in_livesig)}")
print(f"        - of which only paper-signaled                          : {len(in_paper - ire_live_sig)}")

# spread profile of VPS3-only fires (the books VPS3 accepted)
cross = [float(r[3]) for r in vps3 if r[0] in only_vps3 and r[3] not in ("", "None")]
if cross:
    cross.sort()
    import statistics as st
    print(f"\n  VPS3-only fires cross_spread: n={len(cross)} median={st.median(cross):.3f} "
          f"p90={cross[int(.9*len(cross))]:.3f} (live cross-token gate ~0.02 rejects wide)")

# PnL of the divergence: what VPS3 earned on fires Ireland-live missed
pnl_vps3only = [float(r[5]) for r in vps3 if r[0] in only_vps3 and r[5] not in ("", "None")]
if pnl_vps3only:
    import statistics as st
    print(f"  VPS3 PnL on Ireland-missed fires: n={len(pnl_vps3only)} total=${sum(pnl_vps3only):+.1f} "
          f"mean=${st.mean(pnl_vps3only):+.3f} wins={sum(1 for p in pnl_vps3only if p>0)}")
