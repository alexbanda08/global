"""Refined: matched-pair economics + sleeve selection over full history."""
import json, re, collections, datetime as dt
P = "strategy_lab/wallet_hunt/cache/_pm_portfolio/0xb945945d/"
tr = json.load(open(P + "activity_TRADE.json"))
rd = json.load(open(P + "activity_REDEEM.json"))
rx = re.compile(r"^([a-z]+)-updown-(\d+m)-(\d+)$")


def pct(a, p):
    a = sorted(a); return a[int(p * (len(a) - 1))]

# ---- matched-pair economics on the 40 recent markets ----
mk = collections.defaultdict(lambda: {'Up': [0.0, 0.0], 'Down': [0.0, 0.0]})  # [usdc, shares]
for t in tr:
    if t['side'] != 'BUY':
        continue
    oc = t['outcome']
    if oc in ('Up', 'Down'):
        mk[t['conditionId']][oc][0] += t['usdcSize']
        mk[t['conditionId']][oc][1] += t['size']

tot_matched_shares = 0.0; tot_locked_cost = 0.0; tot_residual_shares = 0.0
edges = []
for c, d in mk.items():
    u_usd, u_sh = d['Up']; n_usd, n_sh = d['Down']
    if u_sh == 0 or n_sh == 0:
        continue
    matched = min(u_sh, n_sh)
    pu = u_usd / u_sh; pn = n_usd / n_sh          # avg price each leg
    pair_cost = pu + pn                            # cost to hold 1 matched pair
    locked_cost = matched * pair_cost
    tot_matched_shares += matched
    tot_locked_cost += locked_cost
    tot_residual_shares += abs(u_sh - n_sh)
    edges.append((matched * (1.0 - pair_cost)))   # $ locked profit (one side pays $1)

print("=== matched-pair economics (40 recent BTC-15m markets, 2 days) ===")
print("matched pairs (shares): %.0f" % tot_matched_shares)
print("locked cost $: %.0f   implied payout $: %.0f" % (tot_locked_cost, tot_matched_shares))
print("LOCKED net profit $ (sum matched*(1-paircost)): %.2f" % sum(edges))
print("residual (unmatched) shares carried directional: %.0f (%.1f%% of matched)" %
      (tot_residual_shares, 100 * tot_residual_shares / tot_matched_shares))
print("avg pair_cost weighted: %.4f" % (tot_locked_cost / tot_matched_shares))

# ---- sleeve selection over full history via REDEEM tape ----
print("\n=== REDEEM tape sleeve selection (longer history) ===")
rts = [r['timestamp'] for r in rd]
print("redeem window:", dt.datetime.utcfromtimestamp(min(rts)), "->",
      dt.datetime.utcfromtimestamp(max(rts)))
coin = collections.Counter(); tf = collections.Counter()
for r in rd:
    m = rx.match(r.get('slug') or '')
    if m:
        coin[m.group(1)] += 1; tf[m.group(2)] += 1
print("redeem coin dist:", dict(coin.most_common()))
print("redeem tf dist:", dict(tf.most_common()))

# coin/tf over time buckets (weekly) to see rotation
wk = collections.defaultdict(collections.Counter)
for r in rd:
    m = rx.match(r.get('slug') or '')
    if not m:
        continue
    w = dt.datetime.utcfromtimestamp(r['timestamp']).strftime('%Y-%U')
    wk[w][m.group(1) + '-' + m.group(2)] += 1
print("\nweekly sleeve mix (coin-tf : count):")
for w in sorted(wk):
    top = dict(wk[w].most_common(4))
    print(" ", w, top)
