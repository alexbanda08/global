"""Decode b945/b27 up-down window behavior from refreshed activity (2026-08-13).

Per (wallet, slug) on (btc|eth)-updown-(5m|15m):
  buys/sells per outcome side, paired = min(buy_up, buy_dn),
  residual = |buy_up - buy_dn|, residual disposition (sold / merged / redeemed / expired),
  fill timing relative to slot_start (slug suffix = window OPEN, len 300/900s).

Outputs a text report to stdout. Run:  python _analyze_updown_behavior_2026_08_13.py <wallet_short>
"""
import json, os, re, sys, statistics as st
from collections import defaultdict

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "_pm_portfolio")
SLUG_RE = re.compile(r"^(btc|eth|sol|xrp)-updown-(5m|15m)-(\d+)$")

def load(short, typ):
    p = os.path.join(ROOT, short, f"activity_{typ}_2026_08_13.json")
    if not os.path.exists(p):
        return []
    with open(p) as f:
        return json.load(f)

def pct(x, n):
    return f"{100.0*x/n:.1f}%" if n else "—"

def analyze(short):
    trades = load(short, "TRADE")
    redeems = load(short, "REDEEM")
    merges = load(short, "MERGE")
    print(f"\n{'='*78}\n{short}: {len(trades)} trades, {len(redeems)} redeems, {len(merges)} merges")
    if trades:
        ts = [r["timestamp"] for r in trades]
        import time as _t
        print(f"coverage: {_t.strftime('%Y-%m-%d', _t.gmtime(min(ts)))} .. {_t.strftime('%Y-%m-%d %H:%M', _t.gmtime(max(ts)))} UTC")

    # redeem/merge indexed by conditionId
    redeem_by_cond = defaultdict(float)
    for r in redeems:
        redeem_by_cond[r.get("conditionId")] += float(r.get("size") or 0)
    merge_by_cond = defaultdict(float)
    for r in merges:
        merge_by_cond[r.get("conditionId")] += float(r.get("size") or 0)

    # windows
    W = {}
    other_volume = 0.0
    for t in trades:
        m = SLUG_RE.match(t.get("slug") or "")
        if not m:
            other_volume += float(t.get("usdcSize") or 0)
            continue
        coin, tf, slot = m.group(1), m.group(2), int(m.group(3))
        k = (coin, tf, t["slug"])
        w = W.setdefault(k, dict(slot=slot, tf=tf, coin=coin, cond=t.get("conditionId"),
                                 buy={"Up": [0.0, 0.0], "Down": [0.0, 0.0]},
                                 sell={"Up": [0.0, 0.0], "Down": [0.0, 0.0]},
                                 fills=[]))
        side = t.get("outcome")
        if side not in ("Up", "Down"):
            continue
        sh = float(t.get("size") or 0); usd = float(t.get("usdcSize") or 0)
        d = w["buy" if t["side"] == "BUY" else "sell"][side]
        d[0] += sh; d[1] += usd
        w["fills"].append((t["timestamp"] - slot, t["side"], side, sh, usd, float(t.get("price") or 0)))

    print(f"non-updown volume skipped: ${other_volume:,.0f}")

    for tf in ("5m", "15m"):
        wins = [w for w in W.values() if w["tf"] == tf]
        if not wins:
            continue
        win_len = 300 if tf == "5m" else 900
        n = len(wins)
        paired_tot = resid_tot = 0.0
        ratios = []
        pair_sums = []
        resid_sold_sh = resid_merged = resid_redeemed = resid_expired = 0.0
        resid_sell_px = []
        heavy_buy_px = []
        both_sided = 0
        for w in wins:
            bu, bd = w["buy"]["Up"][0], w["buy"]["Down"][0]
            paired = min(bu, bd); resid = abs(bu - bd)
            paired_tot += paired; resid_tot += resid
            if bu > 0 and bd > 0:
                both_sided += 1
                vu = w["buy"]["Up"][1]/bu; vd = w["buy"]["Down"][1]/bd
                pair_sums.append((paired, vu+vd))
            if paired > 0 or resid > 0:
                ratios.append(paired/resid if resid > 1e-9 else float("inf"))
            heavy = "Up" if bu > bd else "Down"
            hsh = w["buy"][heavy][0]
            if hsh > 0:
                heavy_buy_px.append(w["buy"][heavy][1]/hsh)
            sold_h = w["sell"][heavy][0]
            rs = min(resid, sold_h)
            resid_sold_sh += rs
            if w["sell"][heavy][0] > 0:
                resid_sell_px.append(w["sell"][heavy][1]/w["sell"][heavy][0])
            merged = min(merge_by_cond.get(w["cond"], 0.0), paired)
            resid_merged += 0  # merges consume pairs, not residual
            red = redeem_by_cond.get(w["cond"], 0.0)
            # redeem covers winning paired leg + winning residual; attribute leftover to residual
            resid_red = max(0.0, min(resid - rs, red - paired))
            resid_redeemed += resid_red
            resid_expired += max(0.0, resid - rs - resid_red)

        finite = [r for r in ratios if r != float("inf")]
        print(f"\n--- {tf}: {n} windows ({both_sided} two-sided = {pct(both_sided,n)}) ---")
        print(f"paired {paired_tot:,.0f} sh | residual {resid_tot:,.0f} sh | "
              f"RATIO paired:resid = {paired_tot/max(resid_tot,1e-9):.2f}")
        if finite:
            print(f"per-window ratio: median {st.median(finite):.2f}  mean {st.mean(finite):.2f}")
        if pair_sums:
            tot_p = sum(p for p, _ in pair_sums)
            wavg = sum(p*s for p, s in pair_sums)/tot_p
            srt = sorted(s for _, s in pair_sums)
            print(f"pair vwap-sum: weighted {wavg:.4f}  median {srt[len(srt)//2]:.4f}  "
                  f"p10 {srt[int(len(srt)*.1)]:.4f}  p90 {srt[int(len(srt)*.9)]:.4f}")
        print(f"RESIDUAL disposition: sold-before {pct(resid_sold_sh,resid_tot)} | "
              f"redeemed(won) {pct(resid_redeemed,resid_tot)} | expired(lost~) {pct(resid_expired,resid_tot)}")
        if heavy_buy_px:
            print(f"heavy-side buy px: mean {st.mean(heavy_buy_px):.3f}")
        if resid_sell_px:
            print(f"residual sell px: mean {st.mean(resid_sell_px):.3f}")

        # timing: usd-weighted buy distribution vs slot_start
        buckets = [(-1e9, 0, "pre-open"), (0, 60, "0-60s"), (60, 120, "60-120s"),
                   (120, 180, "120-180s"), (180, 240, "180-240s"), (240, 300, "240-300s")]
        if tf == "15m":
            buckets = [(-1e9, 0, "pre-open"), (0, 120, "0-2m"), (120, 300, "2-5m"),
                       (300, 600, "5-10m"), (600, 780, "10-13m"), (780, 900, "13-15m")]
        buy_usd = defaultdict(float); sell_usd = defaultdict(float)
        buy_n = defaultdict(int)
        tot_buy = tot_sell = 0.0
        late_buy_px = []; early_buy_px = []
        for w in wins:
            for off, side, outc, sh, usd, px in w["fills"]:
                off2 = min(off, win_len - 1)  # clamp post-close prints
                for lo, hi, name in buckets:
                    if lo <= off2 < hi:
                        if side == "BUY":
                            buy_usd[name] += usd; buy_n[name] += 1; tot_buy += usd
                            (late_buy_px if off2 >= win_len*0.6 else early_buy_px).append(px)
                        else:
                            sell_usd[name] += usd; tot_sell += usd
                        break
        print("timing (usd-weighted):  bucket | %buys | %sells | n_buys")
        for lo, hi, name in buckets:
            print(f"  {name:>9} | {pct(buy_usd[name],tot_buy):>6} | {pct(sell_usd[name],tot_sell):>6} | {buy_n[name]}")
        if early_buy_px and late_buy_px:
            print(f"buy px early(<60%) {st.mean(early_buy_px):.3f}  vs late(>60%) {st.mean(late_buy_px):.3f}")

    # monthly ratio drift (5m+15m combined)
    from time import gmtime, strftime
    bym = defaultdict(lambda: [0.0, 0.0])
    for w in W.values():
        mkey = strftime("%Y-%m", gmtime(w["slot"]))
        bu, bd = w["buy"]["Up"][0], w["buy"]["Down"][0]
        bym[mkey][0] += min(bu, bd); bym[mkey][1] += abs(bu - bd)
    print("\nmonthly paired:resid ratio:")
    for mk in sorted(bym):
        p, r = bym[mk]
        print(f"  {mk}: {p/max(r,1e-9):.2f}  (paired {p:,.0f} sh)")

if __name__ == "__main__":
    for short in (sys.argv[1:] or ["0xb945945d", "0xb27bc932"]):
        analyze(short)
