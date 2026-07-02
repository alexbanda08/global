import json, numpy as np, pandas as pd
pd.set_option("display.width",200)
D=r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/directional/_ireland_6day/"

# ================= ladder_summary =================
rows=[]
for ln in open(D+"ladder_summary.tsv",encoding="utf-8"):
    ln=ln.rstrip("\n")
    if not ln: continue
    at,sl,js=ln.split("\t",2)
    d=json.loads(js); d["at"]=at; d["sleeve"]=sl; rows.append(d)
df=pd.DataFrame(rows)
df=df.rename(columns={"at":"ts"})
df["ts"]=pd.to_datetime(df["ts"]); df["day"]=df["ts"].dt.date
num=["pvs","maker_sh","taker_sh","maker_pct","pair_frac","paired_sh","taker_pct","rebate_usd",
     "residual_sh","filled_dn_sh","filled_up_sh","flow_capture","rejected_delta","taker_completions",
     "market_sell_total_sh","paired_pnl_locked_usd","net_paired_estimate_usd"]
for c in num: df[c]=pd.to_numeric(df[c],errors="coerce")
print("TOTAL ladder_summary windows:",len(df))
print("date range:",df.ts.min(),"->",df.ts.max(),"=",round((df.ts.max()-df.ts.min()).total_seconds()/86400,1),"days")
print("\n== skipped_reason breakdown (ALL windows) ==")
print(df.skipped_reason.value_counts(dropna=False).to_string())
df["traded"]=(df.filled_up_sh>0)|(df.filled_dn_sh>0)
print("\nTRADED windows (any fill): %d / %d = %.1f%%"%(df.traded.sum(),len(df),100*df.traded.mean()))

t=df[df.traded].copy()
print("\n================ TRADED WINDOWS ONLY (n=%d) ================"%len(t))
def stat(c):
    s=t[c].dropna()
    if len(s)==0: return f"{c:24s} (empty)"
    return (f"{c:24s} mean={s.mean():9.4f} med={s.median():9.4f} p10={s.quantile(.1):8.4f} "
            f"p90={s.quantile(.9):8.4f} min={s.min():8.4f} max={s.max():9.4f} sum={s.sum():10.3f}")
for c in ["pair_frac","pvs","flow_capture","filled_up_sh","filled_dn_sh","paired_sh",
          "residual_sh","maker_pct","taker_pct","taker_completions","market_sell_total_sh",
          "rebate_usd","paired_pnl_locked_usd","net_paired_estimate_usd","rejected_delta"]:
    print(stat(c))
print("\n== residual_side dist (traded) =="); print(t.residual_side.value_counts().to_string())
print("== pvs null? ==", t.pvs.isna().sum(),"of",len(t))

print("\n== HEADLINE TOTALS (traded windows) ==")
print(f"  paired_pnl_locked_usd  TOTAL = ${t.paired_pnl_locked_usd.sum():.2f}")
print(f"  net_paired_estimate    TOTAL = ${t.net_paired_estimate_usd.sum():.2f}  (mean ${t.net_paired_estimate_usd.mean():.4f}/win)")
print(f"  rebate_usd             TOTAL = ${t.rebate_usd.sum():.2f}  (mean ${t.rebate_usd.mean():.4f}/win)")
print(f"  residual_sh            TOTAL = {t.residual_sh.sum():.1f} sh held directional (PnL NOT logged)")
diff=(t.paired_pnl_locked_usd-t.net_paired_estimate_usd)
print(f"  paired vs net: corr={t.paired_pnl_locked_usd.corr(t.net_paired_estimate_usd):.3f} maxdiff={diff.abs().max():.4f} (same metric?)")

# pair_frac buckets
print("\n== pair_frac buckets (traded) ==")
print(pd.cut(t.pair_frac,[-.01,.01,.25,.5,.75,.99,1.01]).value_counts().sort_index().to_string())

# per-day time series
print("\n================ PER-DAY (traded windows) ================")
g=t.groupby("day").agg(n=("slug","size"),pair_frac=("pair_frac","mean"),pvs=("pvs","mean"),
    flow_cap=("flow_capture","mean"),net_paired=("net_paired_estimate_usd","sum"),
    rebate=("rebate_usd","sum"),resid_sh=("residual_sh","sum"),
    fill_up=("filled_up_sh","mean"),fill_dn=("filled_dn_sh","mean"))
print(g.round(3).to_string())

# ================= feed_quality per slug =================
fq=pd.read_csv(D+"feed_quality_byslug.tsv",sep="\t",header=None,
   names=["slug","n","any_warmup","avg_book_age","max_book_age","max_rej","n_conns","lvl_upd","culled","dedup","rec_drop"])
print("\n================ FEED_QUALITY (per-slug, n=%d) ================"%len(fq))
print("windows with ANY warmup_pass=true: %d / %d = %.1f%%"%(fq.any_warmup.astype(str).isin(['t','True','true']).sum(),len(fq),
      100*fq.any_warmup.astype(str).isin(['t','True','true']).mean()))
fq["warm"]=fq.any_warmup.astype(str).isin(['t','True','true'])
print("avg_book_age_ms: warmup-pass windows  median=%.0f  mean=%.0f"%(fq[fq.warm].avg_book_age.median(),fq[fq.warm].avg_book_age.mean()))
print("avg_book_age_ms: warmup-FAIL windows   median=%.0f  mean=%.0f"%(fq[~fq.warm].avg_book_age.median(),fq[~fq.warm].avg_book_age.mean()))
print("total rejected_delta (sum of per-slug max): %.0f"%fq.max_rej.sum())
print("total level_updates_applied: %.0f"%fq.lvl_upd.sum())
print("n_conns dist:",fq.n_conns.value_counts().to_dict())
print("total dedup_first_wins (sum per-slug max): %.0f"%fq.dedup.sum())
print("total recorder_dropped: %.0f"%fq.rec_drop.sum())
print("total culled: %.0f"%fq.culled.sum())

# join: do warmup-pass slugs == traded slugs?
tset=set(t.slug); warmset=set(fq[fq.warm].slug)
print("\nslugs traded but NOT warmup-pass:",len(tset-warmset))
print("slugs warmup-pass but NOT traded:",len(warmset-tset))
print("intersection traded&warmup:",len(tset&warmset))

# ================= ladder_tick rollup =================
lt=pd.read_csv(D+"ladder_tick_byslug.tsv",sep="\t",header=None,
   names=["slug","ticks","max_fc","max_up","max_dn","max_pf","max_tc"])
print("\n================ LADDER_TICK rollup (per-slug, n=%d) ================"%len(lt))
print("total ticks:",lt.ticks.sum(),"median ticks/window:",int(lt.ticks.median()))
print("windows reaching max_pair_frac>0.5:",int((lt.max_pf>0.5).sum()))
print("max flow_capture ever in a window: %.4f"%lt.max_fc.max())
print("windows with any taker_completion>0:",int((lt.max_tc>0).sum()))
