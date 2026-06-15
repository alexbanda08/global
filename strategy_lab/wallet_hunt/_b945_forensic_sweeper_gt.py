"""
GROUND-TRUTH verification of the ">90c late-window sweeper" hypothesis on b945's fresh tape.

For every fill at price >= 0.90 (and >= 0.95) in the final 3 minutes (off_s > 720):
  - join the slug's ACTUAL resolution outcome (canonical resolutions + CLOB winner for
    slugs past the canonical window)
  - compute realized PnL with the production fee model:
      WON  -> qty*(1-p)*(1-0.07*p)
      LOST -> -qty*p
  - report n, WR, $/fill, bootstrap CI95, loss tail, breakeven WR vs observed WR.
"""
import sys, os, json
sys.path.insert(0, "data/v4/canonical")
import numpy as np
import pandas as pd
import urllib.request

CACHE_DIR = "strategy_lab/wallet_hunt/cache/_pm_portfolio/0xb945945d"
TAPE_FILE = os.path.join(CACHE_DIR, "activity_TRADE_2026_06_12.json")
CLOB_CACHE = os.path.join(CACHE_DIR, "clob_winners_fresh_2026_06_12.json")

with open(TAPE_FILE) as f:
    raw = json.load(f)
df = pd.DataFrame(raw)
df["slot_s"] = df["slug"].str.extract(r"-(\d+)$")[0].astype(float)
df["off_s"] = df["timestamp"].astype(float) - df["slot_s"]

# ---------------------------------------------------------------- outcomes
# 1) canonical resolutions (covers slugs ending <= Jun 11 ~06:21)
from load import load_resolutions
res = load_resolutions()
res_btc15 = res[res["slug"].str.startswith("btc-updown-15m-")][["slug", "outcome"]]
slug_outcome = dict(zip(res_btc15["slug"], res_btc15["outcome"]))

slugs = sorted(df["slug"].unique())
cid_by_slug = df.groupby("slug")["conditionId"].first().to_dict()
print(f"slugs in tape: {len(slugs)}")
covered_canon = [s for s in slugs if s in slug_outcome]
print(f"covered by canonical resolutions: {len(covered_canon)}")

# 2) CLOB winner for the rest (and cross-check on covered ones)
if os.path.exists(CLOB_CACHE):
    with open(CLOB_CACHE) as f:
        clob_winners = json.load(f)
else:
    clob_winners = {}

missing = [s for s in slugs if s not in clob_winners]
for s in missing:
    cid = cid_by_slug[s]
    url = f"https://clob.polymarket.com/markets/{cid}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            m = json.loads(r.read())
        toks = m.get("tokens", [])
        winner = None
        for t in toks:
            if t.get("winner"):
                winner = t.get("outcome")  # 'Up' or 'Down'
        clob_winners[s] = winner
        print(f"  CLOB {s}: winner={winner}")
    except Exception as e:
        clob_winners[s] = None
        print(f"  CLOB {s}: ERROR {e}")

with open(CLOB_CACHE, "w") as f:
    json.dump(clob_winners, f, indent=1)

# cross-check canonical vs CLOB
agree = disagree = 0
for s in covered_canon:
    cw = clob_winners.get(s)
    if cw is None:
        continue
    if cw == slug_outcome[s]:
        agree += 1
    else:
        disagree += 1
        print(f"  DISAGREE {s}: canonical={slug_outcome[s]} clob={cw}")
print(f"canonical vs CLOB cross-check: {agree} agree / {disagree} disagree")

# final outcome map: canonical first, CLOB fallback
final_outcome = {}
for s in slugs:
    final_outcome[s] = slug_outcome.get(s) or clob_winners.get(s)
no_outcome = [s for s in slugs if final_outcome[s] is None]
print(f"slugs with NO outcome available: {len(no_outcome)} {no_outcome}")

# ---------------------------------------------------------------- economics
df["winner"] = df["slug"].map(final_outcome)
df["token"] = np.where(df["outcomeIndex"] == 0, "Up", "Down")
df["won"] = df["token"] == df["winner"]

REBATE_PER_SH = 0.0015  # pool-prorated estimate from lifetime MAKER_REBATE / volume


def pnl_07(row):
    q, p = row["size"], row["price"]
    if row["won"]:
        return q * (1 - p) * (1 - 0.07 * p)
    return -q * p


def boot_ci(x, n_boot=10000, seed=7):
    rng = np.random.default_rng(seed)
    x = np.asarray(x, dtype=float)
    means = np.array([rng.choice(x, len(x), replace=True).mean() for _ in range(n_boot)])
    return np.percentile(means, [2.5, 97.5])


def analyze(sub, label):
    sub = sub[sub["winner"].notna()].copy()
    if len(sub) == 0:
        print(f"\n--- {label}: no fills with outcome ---")
        return None
    sub["pnl"] = sub.apply(pnl_07, axis=1)
    sub["rebate"] = sub["size"] * REBATE_PER_SH
    n = len(sub)
    nslugs = sub["slug"].nunique()
    wr = sub["won"].mean()
    mean_pnl = sub["pnl"].mean()
    tot = sub["pnl"].sum()
    lo, hi = boot_ci(sub["pnl"].values)
    p_mean = sub["price"].mean()
    # breakeven WR at the entry price: WR_be = p / (p + (1-p)(1-0.07p))
    wr_be = p_mean / (p_mean + (1 - p_mean) * (1 - 0.07 * p_mean))
    # WR CI (Wilson)
    from scipy import stats as sp
    k = int(sub["won"].sum())
    wr_lo, wr_hi = sp.beta.ppf([0.025, 0.975], k + 0.5, n - k + 0.5)  # Jeffreys
    losses = sub[~sub["won"]]
    wins = sub[sub["won"]]
    print(f"\n--- {label} ---")
    print(f"n_fills={n}  n_slugs={nslugs}  mean_entry={p_mean:.3f}")
    print(f"WR={wr:.4f}  (Jeffreys CI95 [{wr_lo:.4f}, {wr_hi:.4f}])  breakeven_WR={wr_be:.4f}")
    print(f"clears breakeven (CI low > be)? {wr_lo > wr_be}")
    print(f"$/fill={mean_pnl:+.4f}  bootCI95 [{lo:+.4f}, {hi:+.4f}]  total=${tot:+.2f}")
    print(f"  + rebate est ({REBATE_PER_SH}/sh): $/fill={mean_pnl + sub['rebate'].mean():+.4f}  "
          f"total=${tot + sub['rebate'].sum():+.2f}")
    print(f"wins: n={len(wins)}, mean +${wins['pnl'].mean():.4f}" if len(wins) else "wins: 0")
    if len(losses):
        print(f"LOSS TAIL: n={len(losses)} ({len(losses)/n:.1%}), mean -${-losses['pnl'].mean():.4f}, "
              f"worst -${-losses['pnl'].min():.2f}, total -${-losses['pnl'].sum():.2f}")
        print(f"  one avg loss wipes {abs(losses['pnl'].mean())/wins['pnl'].mean():.1f} avg wins"
              if len(wins) else "")
        for _, r in losses.iterrows():
            print(f"    LOSS {r['slug']} off={r['off_s']:.0f}s p={r['price']:.2f} "
                  f"q={r['size']:.1f} pnl={r['pnl']:+.2f} (bought {r['token']}, winner {r['winner']})")
    else:
        print("LOSS TAIL: none in sample")
    return sub


print("\n================ GROUND-TRUTH: late-window sweeper ================")
late = df[df["off_s"] > 720]
print(f"fills in final 3 min: {len(late)}")

s90 = analyze(late[late["price"] >= 0.90], "price >= 0.90, off > 720s")
s95 = analyze(late[late["price"] >= 0.95], "price >= 0.95, off > 720s")

# also the loser-lottery side for context
s10 = analyze(late[late["price"] <= 0.10], "price <= 0.10, off > 720s (loser lottery)")

# whole-tape sanity: his overall fresh-tape PnL
allres = analyze(df, "ALL fresh-tape fills (context)")

# save
out = df[df["winner"].notna()].copy()
out["pnl_07"] = out.apply(pnl_07, axis=1)
out.to_parquet(os.path.join(CACHE_DIR, "fresh_tape_with_outcomes.parquet"), index=False)
print(f"\nsaved fresh_tape_with_outcomes.parquet ({len(out)} rows)")
