import csv, collections, datetime as dt

SNAP=".."
def load(p): return [r for r in csv.DictReader(open(p,encoding="utf-8")) if r.get("condition_id")]
ire=load(f"{SNAP}/momo_ireland_7d.csv")
v3 =load(f"{SNAP}/momo_vps3_7d.csv")

def fl(x):
    try:return float(x)
    except:return None
def won(r): return str(r.get("won")).lower()=="true"
def stake(r):
    p,q=fl(r.get("entry_price")),fl(r.get("entry_qty"))
    return p*q if (p is not None and q is not None) else None
def parse_at(s):
    try:return dt.datetime.strptime(s.split(".")[0].replace("+00","").replace("+02","").strip(),"%Y-%m-%d %H:%M:%S")
    except:return None

def summ(rows,label):
    n=len(rows); w=sum(won(r) for r in rows)
    up=sum(1 for r in rows if str(r.get("signal","")).upper()=="UP")
    stk=[stake(r) for r in rows if stake(r) is not None]
    pnl=sum(fl(r.get("pnl_usd")) or 0 for r in rows)
    totstk=sum(stk) if stk else 0
    eps=[fl(r.get("entry_price")) for r in rows if fl(r.get("entry_price")) is not None]
    print(f"{label}: n={n} WR={w/n:.3f} signalUP={up}({up/n:.2f}) "
          f"mean_stake=${sum(stk)/len(stk):.2f} mean_entry={sum(eps)/len(eps):.3f} "
          f"totPnL={pnl:.2f} pnl/fire={pnl/n:+.3f} pnl/$stake={pnl/totstk:+.4f}")
    return dict(n=n)

print("="*80)
summ(ire,"IRELAND live ")
summ(v3 ,"VPS3   shadow")

# time coverage
def span(rows):
    ts=[parse_at(r["at"]) for r in rows if parse_at(r["at"])]
    return min(ts),max(ts)
i0,i1=span(ire); s0,s1=span(v3)
print(f"\nIreland span: {i0} .. {i1}")
print(f"VPS3    span: {s0} .. {s1}")

# join on condition_id
def bycid(rows):
    d=collections.defaultdict(list)
    for r in rows: d[r["condition_id"]].append(r)
    return d
I=bycid(ire); S=bycid(v3)
dupI=sum(1 for k in I if len(I[k])>1); dupS=sum(1 for k in S if len(S[k])>1)
common=set(I)&set(S)
print(f"\nCONDITION_ID JOIN: ireland markets={len(I)} (dups={dupI})  vps3 markets={len(S)} (dups={dupS})")
print(f"  common={len(common)}  live-only={len(set(I)-set(S))}  shadow-only={len(set(S)-set(I))}")

if common:
    sig=out=wn=0
    for k in common:
        a=I[k][0]; b=S[k][0]
        if a.get("signal")==b.get("signal"): sig+=1
        if str(a.get("outcome","")).upper()==str(b.get("outcome","")).upper(): out+=1
        if won(a)==won(b): wn+=1
    print(f"  on common: same_signal={sig}/{len(common)}  same_outcome={out}/{len(common)}  same_win={wn}/{len(common)}")

# characterize live-only and shadow-only: by day + signal
def char(keys, src, label):
    rows=[src[k][0] for k in keys]
    byday=collections.Counter(parse_at(r["at"]).strftime("%m-%d") if parse_at(r["at"]) else "?" for r in rows)
    sig=collections.Counter(str(r.get("signal","")).upper() for r in rows)
    w=sum(won(r) for r in rows)
    print(f"  {label}: n={len(rows)} WR={w/len(rows):.3f} signal={dict(sig)} by_day={dict(byday)}")
print("\nDIVERGENCE CHARACTERIZATION:")
char(set(I)-set(S), I, "LIVE-ONLY  (live fired, shadow didn't)")
char(set(S)-set(I), S, "SHADOW-ONLY(shadow fired, live didn't)")

# hourly fire pattern (UTC hour) to spot a gating/uptime gap
def hours(rows):
    return collections.Counter(parse_at(r["at"]).hour for r in rows if parse_at(r["at"]))
print("\nHourly fire counts (UTC):")
hi=hours(ire); hs=hours(v3)
print("  hour:  "+" ".join(f"{h:02d}" for h in range(24)))
print("  live:  "+" ".join(f"{hi.get(h,0):2d}" for h in range(24)))
print("  shad:  "+" ".join(f"{hs.get(h,0):2d}" for h in range(24)))
