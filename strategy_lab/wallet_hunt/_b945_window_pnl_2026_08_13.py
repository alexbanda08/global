"""b945 per-window P&L reconstruction from cash flows (2026-08-13).

Truth = cash: pnl_window = redeem_usd - buy_usd  (she never sells, never merges).
Attribution: paired leg = paired_sh * (1 - pvs); residual leg = the rest, with the
winner inferred from which side's holdings the redemption matches.
Rebates arrive as separate MAKER_REBATE events (not per window) - reported separately.
"""
import json, re, statistics as st, sys, time
from collections import defaultdict

SHORT = sys.argv[1] if len(sys.argv) > 1 else "0xb945945d"
ROOT = f"cache/_pm_portfolio/{SHORT}"
SLUG = re.compile(r"^(btc|eth)-updown-(5m|15m)-(\d+)$")

trades = json.load(open(f"{ROOT}/activity_TRADE_2026_08_13.json"))
redeems = json.load(open(f"{ROOT}/activity_REDEEM_2026_08_13.json"))

red_by_cond = defaultdict(lambda: [0.0, 0.0])   # cond -> [shares, usd]
for r in redeems:
    red_by_cond[r.get("conditionId")][0] += float(r.get("size") or 0)
    red_by_cond[r.get("conditionId")][1] += float(r.get("usdcSize") or 0)
max_red_ts = max(r["timestamp"] for r in redeems)

W = {}
for t in trades:
    m = SLUG.match(t.get("slug") or "")
    if not m or t.get("outcome") not in ("Up", "Down") or t["side"] != "BUY":
        continue
    coin, tf, slot = m.group(1), m.group(2), int(m.group(3))
    w = W.setdefault(t["slug"], dict(coin=coin, tf=tf, slot=slot, cond=t.get("conditionId"),
                                     sh={"Up": 0.0, "Down": 0.0}, usd={"Up": 0.0, "Down": 0.0}))
    w["sh"][t["outcome"]] += float(t["size"])
    w["usd"][t["outcome"]] += float(t["usdcSize"])

# settle-complete cutoff: window must have closed >=1h before the last redeem seen
rows = []
skipped_recent = 0
for slug, w in W.items():
    win_len = 300 if w["tf"] == "5m" else 900
    if w["slot"] + win_len > max_red_ts - 3600:
        skipped_recent += 1
        continue
    bu, bd = w["sh"]["Up"], w["sh"]["Down"]
    uu, ud = w["usd"]["Up"], w["usd"]["Down"]
    spend = uu + ud
    if spend <= 0:
        continue
    red_sh, red_usd = red_by_cond.get(w["cond"], [0.0, 0.0])
    pnl = red_usd - spend
    paired = min(bu, bd)
    resid = abs(bu - bd)
    heavy = "Up" if bu >= bd else "Down"
    vw_u = uu / bu if bu else None
    vw_d = ud / bd if bd else None
    pvs = (vw_u + vw_d) if (vw_u is not None and vw_d is not None) else None
    paired_pnl = paired * (1.0 - pvs) if pvs is not None else 0.0
    # winner inference: redemption equals winning-side holdings (no sells)
    winner = None
    if red_sh > 0:
        winner = "Up" if abs(red_sh - bu) < abs(red_sh - bd) else "Down"
    elif red_sh == 0 and (bu > 0 or bd > 0):
        # nothing redeemed: the side(s) she held lost entirely (one-sided loser)
        winner = ("Down" if bu > bd else "Up") if (bu == 0 or bd == 0) else None
    vw_h = w["usd"][heavy] / w["sh"][heavy] if w["sh"][heavy] else 0.0
    resid_pnl = pnl - paired_pnl
    rows.append(dict(slug=slug, coin=w["coin"], tf=w["tf"], spend=spend, pnl=pnl,
                     paired=paired, resid=resid, pvs=pvs, paired_pnl=paired_pnl,
                     resid_pnl=resid_pnl, heavy=heavy, winner=winner, vw_h=vw_h,
                     one_sided=(paired == 0)))

print(f"windows settled+scored: {len(rows)} | skipped (too recent to have redeemed): {skipped_recent}")

def block(rs, label):
    n = len(rs)
    if not n: return
    wins = [r for r in rs if r["pnl"] > 0.005]
    losses = [r for r in rs if r["pnl"] < -0.005]
    flats = n - len(wins) - len(losses)
    tot = sum(r["pnl"] for r in rs)
    spend = [r["spend"] for r in rs]
    print(f"\n===== {label}: {n} windows =====")
    print(f"capital/window: mean ${st.mean(spend):.2f}  median ${st.median(spend):.2f}  "
          f"p90 ${sorted(spend)[int(n*.9)]:.2f}  max ${max(spend):.2f}")
    print(f"PROFITABLE: {len(wins)} ({100*len(wins)/n:.1f}%)  total +${sum(r['pnl'] for r in wins):,.2f}  avg +${st.mean([r['pnl'] for r in wins]):.3f}")
    print(f"LOSING:     {len(losses)} ({100*len(losses)/n:.1f}%)  total -${-sum(r['pnl'] for r in losses):,.2f}  avg -${-st.mean([r['pnl'] for r in losses]):.3f}")
    print(f"flat: {flats} | NET: ${tot:,.2f}  (${tot/n:.3f}/window)  ROI on deployed {100*tot/sum(spend):.2f}%")
    # profit sources across ALL windows
    p_pair = sum(r["paired_pnl"] for r in rs)
    p_res = sum(r["resid_pnl"] for r in rs)
    print(f"P&L sources: paired-spread {p_pair:+,.2f} | residual-settlement {p_res:+,.2f}")
    pos_pair = sum(r["paired_pnl"] for r in rs if r["paired_pnl"] > 0)
    neg_pair = sum(r["paired_pnl"] for r in rs if r["paired_pnl"] < 0)
    pos_res = sum(r["resid_pnl"] for r in rs if r["resid_pnl"] > 0)
    neg_res = sum(r["resid_pnl"] for r in rs if r["resid_pnl"] < 0)
    print(f"  paired: gross +{pos_pair:,.0f} / {neg_pair:,.0f}  |  residual: gross +{pos_res:,.0f} / {neg_res:,.0f}")
    # loss causes
    causes = defaultdict(lambda: [0, 0.0])
    for r in losses:
        if r["one_sided"]:
            c = "one-sided bet lost"
        elif r["resid_pnl"] < 0 and abs(r["resid_pnl"]) >= abs(min(r["paired_pnl"], 0)) and r["resid_pnl"] <= r["paired_pnl"]:
            c = "residual lost (heavy side ≠ winner)"
        elif r["pvs"] is not None and r["pvs"] > 1.0:
            c = "paired above $1 (pvs>1)"
        else:
            c = "other"
        causes[c][0] += 1
        causes[c][1] += r["pnl"]
    print("loss causes:")
    for c, (k, s) in sorted(causes.items(), key=lambda x: x[1][1]):
        print(f"  {c}: {k} windows, ${s:,.2f}")
    # win sources
    wc = defaultdict(lambda: [0, 0.0])
    for r in wins:
        if r["one_sided"]:
            c = "one-sided bet won"
        elif r["resid_pnl"] > abs(r["paired_pnl"]) and r["resid_pnl"] > 0:
            c = "residual won (dominant)"
        elif r["paired_pnl"] > 0:
            c = "paired spread (pvs<1, dominant)"
        else:
            c = "other"
        wc[c][0] += 1
        wc[c][1] += r["pnl"]
    print("win sources:")
    for c, (k, s) in sorted(wc.items(), key=lambda x: -x[1][1]):
        print(f"  {c}: {k} windows, ${s:,.2f}")

for tf in ("15m", "5m"):
    block([r for r in rows if r["tf"] == tf], f"{tf} (btc+eth)")
block(rows, "ALL")

# rebates in the same period
reb = json.load(open(f"{ROOT}/activity_MAKER_REBATE.json")) if False else None
import urllib.request
try:
    full = json.load(open(f"{ROOT}/activity_TRADE_2026_08_13.json"))[0]["proxyWallet"]
    req = urllib.request.Request(
        f"https://data-api.polymarket.com/activity?user={full}&type=MAKER_REBATE&limit=500",
        headers={"User-Agent": "curl/8"})
    rb = json.loads(urllib.request.urlopen(req, timeout=25).read())
    t0 = min(t["timestamp"] for t in trades)
    in_per = [x for x in rb if x["timestamp"] >= t0]
    print(f"\nMAKER_REBATE in sample period: {len(in_per)} payments, ${sum(float(x.get('usdcSize') or 0) for x in in_per):,.2f}")
except Exception as e:
    print("rebate fetch failed:", e)
