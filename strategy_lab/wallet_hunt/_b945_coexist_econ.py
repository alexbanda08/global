"""
B945 COEXIST scenario — honest new-entrant economics.

We do NOT inherit b945's queue. We compete WITH b945 + the other resting makers
for the SAME taker-sell flow, so our per-level capture < his. We re-run his exact
per-slug paired economics with our (reduced) capture and report net PnL + bootstrap CI.

DATA (all reconciled to the Measure phase + audit this session):
  D:/tmp_qp/capture_buckets.parquet  — per (slug, outcome, 1c price bucket pc):
      his_shares, his_usd  = b945's on-chain maker BUYS at that level (ground truth)
      tape_shares, tape_usd = canonical taker-SELL flow at that level (the pie we compete for)
      winner_side          = 'winner'/'loser' (chainlink-derived per per_slug_paired_ledger)
  Reconciles: tape flow $4,313.58/slug, his cost $819.08/slug, his $-share 18.99%,
              his FULL fill PnL +$3.25/slug (== calibrated gt_pnl +$3.45), shares 1725/slug.

THE COEXIST MODEL
-----------------
Available pie at a (slug, outcome, price) level = tape_shares (the realized taker-SELL flow
that crossed at that price; a side='sell' print = a taker hitting a resting bid; b945 is one
of the makers whose bid got hit).

  his_capture_rate at a level (pooled raw share-wtd) = his_shares / tape_shares = 0.1375 overall.
  => the level is SHARED: ~86% of the flow goes to OTHER resting makers, not him.
  => implied effective # of equal "b945-sized" maker slots K_eff = 1 / 0.1375 ≈ 7.27.

When WE enter as the (K_eff+1)-th maker bringing one b945-equivalent of resting size, our share
of the flow at each level = our_size / (his_size + others_size + our_size). Modeled as:

  our_capture_share (of the WHOLE level's tape flow) = his_capture_rate × q
        where q = our_queue_share relative to b945 himself.

  q < 1 because (a) we split his slice with him and (b) we have NO early-GTC time-priority moat.
  We sweep q over a defensible range and report a base case.

REACHABILITY HAIRCUT (the honest new-entrant constraint):
  b945 fills 33% of his shares BELOW the contemporaneous best bid (resting time-priority) —
  those are the `left_only` buckets with NO tape sell flow. A NEW entrant with no queue moat
  CANNOT reach them. So our capturable universe = ONLY buckets where tape_shares>0 (the `both`
  + `right_only` flow). We do NOT get his off-tape below-bid fills. This is already enforced
  because our capture = his_capture_rate × q × tape_shares, which is 0 where tape_shares==0.

CLIP / BUDGET / INVENTORY assumptions (explicit):
  - clip_size = $5  (small maker clip, matches the queue-sim arms and a realistic new-entrant unit).
  - per-slug budget cap = b945's own mean deployment $819/slug (we do not out-size the incumbent;
    if our modeled fill cost exceeds it we scale down proportionally — "inventory cap").
  - rung levels = his exact 1c price buckets that have tape flow (we quote where the flow is,
    same price grid he uses). We do NOT add rungs he didn't use.
  - hold to resolution (no taker exit), winner leg redeems $1/share, loser leg → $0.
  - maker rebate = +0.0015/share INCOME on our filled shares (same tier used in the ladder sim;
    reported both with and without).
  - fees: maker side pays $0 taker fee (validated this session — never apply taker fee to maker fills).

PnL per slug:
  our_shares(level)  = his_capture_rate_level × q × tape_shares(level), capped by inventory budget
  our_cost           = sum(our_shares × price)
  our_payout         = sum(our_shares × 1[winner_side=='winner'])
  net_pnl(slug)      = our_payout − our_cost + rebate
  paired_pnl / residual_pnl decomposed via min(up_shares, dn_shares) at the slug level.

OUTPUT: per-slug net PnL, paired/residual split, pair fraction, pvs, bootstrap CI95,
        vs his +$10.65/slug and vs the −$1.8..−$2.8 FIFO static-ladder prior.
"""
import sys, warnings, numpy as np, pandas as pd
warnings.filterwarnings("ignore")
np.random.seed(945)

CB = "D:/tmp_qp/capture_buckets.parquet"
CLIP = 5.0
REBATE_PER_SH = 0.0015
HIS_BUDGET_CAP = 819.08   # b945 mean fill-cost/slug; we don't out-size the incumbent

cb = pd.read_parquet(CB)
both = cb[cb.tape_shares > 0].copy()           # our reachable universe = tape flow only
both["price"] = both.pc / 100.0
both["win_leg"] = (both.winner_side == "winner").astype(int)
# per-level his capture rate (raw share-wtd), clipped to <=1 (tape is a lossy lower bound of flow;
# where his>tape the tape under-records — cap rate at 1.0 so we never "capture" >100% of observed flow)
both["his_rate"] = np.minimum(both.his_shares / both.tape_shares, 1.0)

OVERALL_HIS_RATE = both.his_shares.sum() / both.tape_shares.sum()   # 0.1375
K_EFF = 1.0 / OVERALL_HIS_RATE                                       # ~7.27 equal slots

def run_scenario(q, label, rebate=True):
    """q = our queue share relative to b945. our_capture = his_rate * q of each level's tape flow."""
    d = both.copy()
    # our raw modeled shares at each level (before inventory cap)
    d["our_sh_raw"] = d.his_rate * q * d.tape_shares
    d["our_cost_raw"] = d.our_sh_raw * d.price
    # inventory cap per slug: scale so our fill cost <= HIS_BUDGET_CAP (we don't out-deploy incumbent)
    cost_by_slug = d.groupby("slug").our_cost_raw.sum()
    scale = (HIS_BUDGET_CAP / cost_by_slug).clip(upper=1.0)          # only scale DOWN
    d = d.merge(scale.rename("scale"), left_on="slug", right_index=True)
    d["our_sh"] = d.our_sh_raw * d.scale
    d["our_cost"] = d.our_sh * d.price
    d["our_payout"] = d.our_sh * d.win_leg
    d["reb"] = d.our_sh * REBATE_PER_SH if rebate else 0.0

    g = d.groupby("slug")
    payout = g.our_payout.sum()
    cost = g.our_cost.sum()
    reb = g.reb.sum()
    net = payout - cost + reb

    # paired / residual decomposition (slug-level min(up_sh, dn_sh))
    up_sh = d[d.outcome == "Up"].groupby("slug").our_sh.sum()
    dn_sh = d[d.outcome == "Down"].groupby("slug").our_sh.sum()
    idx = net.index
    up_sh = up_sh.reindex(idx, fill_value=0.0)
    dn_sh = dn_sh.reindex(idx, fill_value=0.0)
    paired_sh = np.minimum(up_sh, dn_sh)
    tot_sh = up_sh + dn_sh
    # paired cost = paired_sh * (vwap_up + vwap_dn); paired pays out exactly $1/pair (one wins)
    vwap_up = (d[d.outcome=="Up"].groupby("slug").apply(lambda x:(x.our_sh*x.price).sum()/max(x.our_sh.sum(),1e-9))).reindex(idx,fill_value=0.0)
    vwap_dn = (d[d.outcome=="Down"].groupby("slug").apply(lambda x:(x.our_sh*x.price).sum()/max(x.our_sh.sum(),1e-9))).reindex(idx,fill_value=0.0)
    pvs = vwap_up + vwap_dn   # paired vwap sum (only meaningful where both sides held)
    paired_pnl = paired_sh * (1.0 - pvs)   # each pair returns $1, costs pvs
    # residual = the unbalanced leg held to resolution
    res_up = (up_sh - paired_sh)
    res_dn = (dn_sh - paired_sh)
    won_up = d[d.outcome=="Up"].groupby("slug").win_leg.max().reindex(idx,fill_value=0).astype(float)
    won_dn = d[d.outcome=="Down"].groupby("slug").win_leg.max().reindex(idx,fill_value=0).astype(float)
    residual_pnl = res_up*(won_up - vwap_up) + res_dn*(won_dn - vwap_dn)
    # both-sided flag
    both_sided = (up_sh>0) & (dn_sh>0)

    pf = (paired_sh.sum()*2) / max(tot_sh.sum(), 1e-9)   # paired fraction of total shares

    # bootstrap CI95 on mean net/slug
    arr = net.values
    n = len(arr)
    B = 5000
    boots = np.array([arr[np.random.randint(0,n,n)].mean() for _ in range(B)])
    lo, hi = np.percentile(boots, [2.5, 97.5])
    tstat = arr.mean()/(arr.std(ddof=1)/np.sqrt(n))
    # ex-top2 outlier robustness (mandatory project rigor): drop the 2 best slugs
    extop2 = np.sort(arr)[:-2].mean()
    winrate = (arr>0).mean()

    res = dict(
        label=label, q=q, n_slugs=n, rebate=rebate,
        net_mean=net.mean(), net_med=net.median(),
        paired_mean=paired_pnl[both_sided].mean() if both_sided.any() else 0.0,
        residual_mean=residual_pnl.mean(),
        pvs_med=pvs[both_sided].median() if both_sided.any() else np.nan,
        pair_frac=pf,
        both_sided_frac=both_sided.mean(),
        our_cost_mean=cost.mean(), our_sh_mean=(up_sh+dn_sh).mean(),
        reb_mean=reb.mean(),
        ci_lo=lo, ci_hi=hi, tstat=tstat, extop2=extop2, winrate=winrate,
    )
    return res, net

print(f"=== CALIBRATION ===")
print(f"overall his capture rate (raw share-wtd) = {OVERALL_HIS_RATE:.4f}")
print(f"implied K_eff (equal b945-sized slots at his levels) = {K_EFF:.2f}")
print(f"tape flow/slug = ${both.groupby('slug').tape_usd.sum().mean():.0f}  his cost/slug = ${both.his_usd.groupby(both.slug).sum().mean():.0f}")
print()

# q grid: q=1.0 = we match b945's own slice (unrealistic upper bound, ignores his time-priority moat).
# Honest base case: as the (K_eff+1)-th equal maker we shrink the per-maker slice from 1/K_eff to 1/(K_eff+1),
#   so q_base = K_eff/(K_eff+1) = 7.27/8.27 = 0.879 of his slice IF we had equal standing.
# But we have NO early-GTC time-priority (his documented moat), so we are queue-LAST: realistic q < that.
# Sweep q in {0.125, 0.25, 0.5, 0.879(equal-entrant), 1.0(upper)}.
rows = []
nets = {}
q_equal = K_EFF/(K_EFF+1.0)
for q,lab in [(0.125,"q=1/8 (queue-last, 8th maker)"),
              (0.25,"q=1/4"),
              (0.50,"q=1/2"),
              (q_equal,f"q={q_equal:.3f} (equal new entrant, K_eff+1 split)"),
              (1.0,"q=1.0 (match his slice; upper bound)")]:
    r,net = run_scenario(q, lab, rebate=True)
    rows.append(r); nets[lab]=net

R = pd.DataFrame(rows)
pd.set_option("display.width",220, "display.max_columns",30)
print("=== COEXIST scenario table (WITH maker rebate +0.0015/sh) ===")
print(R[["label","q","n_slugs","net_mean","net_med","paired_mean","residual_mean","pvs_med","pair_frac","our_cost_mean","reb_mean","ci_lo","ci_hi","tstat","extop2","winrate"]].round(4).to_string(index=False))
print()
# no-rebate variant for base case
rows_nr=[]
for q,lab in [(0.125,"q=1/8"),(q_equal,f"q={q_equal:.3f} equal")]:
    r,_=run_scenario(q,lab,rebate=False); rows_nr.append(r)
print("=== same, NO rebate (fill-margin only) ===")
print(pd.DataFrame(rows_nr)[["label","q","net_mean","net_med","ci_lo","ci_hi"]].round(4).to_string(index=False))
print()
print("=== RECONCILE ===")
print(f"his audited LB net = +$10.65/slug (incl $3645 rebate + full redeem coverage over all-time)")
print(f"his fill-based (this dataset, no rebate) = +$3.25/slug; +rebate +$5.84/slug")
print(f"prior FIFO static-ladder (no competition modeled) = -$1.8..-$2.8/slug")
