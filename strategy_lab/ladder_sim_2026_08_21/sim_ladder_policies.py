# Ladder pairing-policy simulation on 2+ weeks of VPS3-collected btc-updown-5m tape.
# Question 1: does a 1-clip-per-pairing guard (max imbalance = 1 clip until the
#   opposite side fills) destroy volume/profit, or does it remove the naked-window
#   loss mode? Operator worry: price goes one way, accumulates that side, never
#   comes back -> guard leaves us with 5 lonely shares.
# Question 2: volatility filter — best windows are sideways; test causal pre-window
#   vol features as an entry throttle.
#
# Grounded in the LIVE ladder v3 mechanics (poly_ladder.rs, Ireland):
#   - one 5-sh clip per side, GTC bid at (touch - 2 ticks), tick 0.01, requoted
#   - G3 pvs gate: bid capped at pair_max_sum - opp_vwap (live 1.00, paper 0.99)
#   - GLT exists in code (glt_cap_q=4 sh) but live tape shows 25x0 windows -> the
#     guard we simulate is the INTENDED design, not enforced on the live path
# Fill model (no book; trade tape only):
#   - touch proxy for token = last print price on that token (pre-open prints seed it)
#   - CONSERVATIVE fill: a taker-SELL print strictly BELOW our bid fills the clip
#     (price priority: the book traded through our level). Fill px = our bid.
#   - OPTIMISTIC fill: print at <= our bid (queue-front assumption). Reported as bound.
# No residual cuts / no T-tail backstop modeled: residual rides to Chainlink settle.
# Maker fills pay no fee on these markets (b945 rule: never apply taker fees to maker fills).

import sys, gzip, math, csv, json
from collections import defaultdict

DIR = r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\ladder_sim_2026_08_21"
TICK = 0.01
DEPTH = 2 * TICK          # quote 2 ticks below touch
CLIP_SH = 5.0
WINDOW_S = 300

# ---------------------------------------------------------------- data loading
def load_resolutions():
    res = {}
    with open(DIR + r"\btc5m_resolutions_2wk.csv", newline="") as fh:
        for row in csv.DictReader(fh):
            res[row["slug"]] = {
                "slot_start_s": int(row["slot_start_us"]) // 1_000_000,
                "winner": row["outcome"],          # 'Up' | 'Down'
            }
    return res

def load_trades():
    """per-slug list of (t_s, outcome, price, size, is_sell), time-sorted (file is)."""
    by_slug = defaultdict(list)
    op = gzip.open if (DIR + r"\btc5m_trades_2wk.csv.gz") else open
    with gzip.open(DIR + r"\btc5m_trades_2wk.csv.gz", "rt", newline="") as fh:
        rd = csv.reader(fh)
        header = next(rd)
        ix = {c: i for i, c in enumerate(header)}
        it, isl, io, ip, isz, isd = (ix[c] for c in
            ("timestamp_us", "slug", "outcome", "price", "size", "side"))
        for row in rd:
            by_slug[row[isl]].append((
                int(row[it]) / 1e6, row[io][0] == "U",
                float(row[ip]), float(row[isz]), row[isd] == "sell"))
    return by_slug

# ---------------------------------------------------------------- simulation core
def rt(p):  # round DOWN to tick (matches round_to_tick + strictly-below clamp intent)
    return math.floor(p / TICK + 1e-9) * TICK

class Side:
    __slots__ = ("sh", "cost", "quote")
    def __init__(self):
        self.sh = 0.0; self.cost = 0.0; self.quote = None
    @property
    def vwap(self):
        return self.cost / self.sh if self.sh > 0 else None

def sim_window(prints, slot_start, winner_up, policy, pair_max_sum=1.00,
               entry_window_s=60, optimistic=False, max_clips_side=7,
               requote_hold_s=0.0):
    """policy: 'nolimit' | 'guard1' | 'guard2'
    entry_window_s: after this, NEW-exposure bids are cancelled; completion
      (imbalance-reducing) bids stay for the whole window. None = no entry cut.
    Returns dict of window results + fill list."""
    up, dn = Side(), Side()
    touch = {True: None, False: None}      # last print per token
    slot_end = slot_start + WINDOW_S
    fills = []
    imb_cap = {"nolimit": 1e9, "guard1": 1.0 * CLIP_SH, "guard2": 2.0 * CLIP_SH}[policy]

    def allowed(side_is_up, t):
        """may this side have a resting bid now? (evaluated pre-print, causal)"""
        s, o = (up, dn) if side_is_up else (dn, up)
        if s.sh >= max_clips_side * CLIP_SH - 1e-9:
            return False
        imb = s.sh - o.sh
        if imb >= imb_cap - 1e-9:                      # guard: heavy side pauses
            return False
        elapsed = t - slot_start
        if entry_window_s is not None and elapsed > entry_window_s:
            # post-window: only completion (fill must REDUCE |up-dn|) may rest
            if imb >= -1e-9:                           # not the light side -> no bid
                return False
        # G3 pvs gate: our bid + opposite vwap must stay <= pair_max_sum
        return True

    def quote_px(side_is_up):
        tch = touch[side_is_up]
        if tch is None:
            return None
        q = rt(tch - DEPTH)
        o = dn if side_is_up else up
        if o.sh > 0:                                   # G3 cap
            cap = rt(pair_max_sum - o.vwap)
            if cap <= 0:
                return None
            q = min(q, cap)
        return q if q >= TICK - 1e-9 else None

    for (t, is_up, px, sz, is_sell) in prints:
        if t >= slot_end:
            break
        if t >= slot_start and is_sell:
            # evaluate fill against the CURRENT resting quote (set before this print)
            s = up if is_up else dn
            q = s.quote
            if q is not None:
                hit = (px < q - 1e-9) if not optimistic else (px <= q + 1e-9)
                if hit:
                    s.sh += CLIP_SH; s.cost += CLIP_SH * q
                    fills.append((t - slot_start, "Up" if is_up else "Dn", q))
                    s.quote = None                     # clip consumed; requote below
        # update touch AFTER fill evaluation (print at t informs quotes for t+)
        touch[is_up] = px
        # requote both sides (causal: uses state incl. this print's touch)
        for flag in (True, False):
            s = up if flag else dn
            s.quote = quote_px(flag) if (t >= slot_start - 1 and allowed(flag, max(t, slot_start))) else None
    # ---- settle
    paired = min(up.sh, dn.sh)
    resid_up = up.sh - paired
    resid_dn = dn.sh - paired
    payout = paired * 1.0 + (resid_up if winner_up else resid_dn) * 1.0
    cost = up.cost + dn.cost
    pvs = ((up.vwap or 0) + (dn.vwap or 0)) if paired > 0 else None
    return {
        "pnl": payout - cost, "cost": cost, "payout": payout,
        "up_sh": up.sh, "dn_sh": dn.sh, "paired": paired,
        "resid": resid_up + resid_dn,
        "resid_won": (resid_up > 0 and winner_up) or (resid_dn > 0 and not winner_up),
        "pvs": pvs, "fills": fills,
    }

# ---------------------------------------------------------------- vol features
def load_vol_features():
    """causal per-slot features from BTC 1s closes: trailing realized vol / range."""
    ts, cl = [], []
    with gzip.open(DIR + r"\btc_1s_2wk.csv.gz", "rt", newline="") as fh:
        rd = csv.reader(fh); next(rd)
        for row in rd:
            ts.append(int(row[0]) // 1_000_000); cl.append(float(row[1]))
    # index closes by second for O(1) lookups
    px = dict(zip(ts, cl))
    def series(t0, t1):
        out = []
        last = None
        for t in range(t0, t1):
            v = px.get(t)
            if v is not None:
                last = v
            if last is not None:
                out.append(last)
        return out
    feats = {}
    for t in range(ts[0] + 900, ts[-1], WINDOW_S):
        if t % WINDOW_S:  # align on 5m boundary
            continue
        w5 = series(t - 300, t)
        w15 = series(t - 900, t)
        if len(w5) < 250 or len(w15) < 800:
            continue
        r5 = [math.log(w5[i+1] / w5[i]) for i in range(len(w5) - 1) if w5[i] > 0]
        rv5 = math.sqrt(sum(x * x for x in r5)) * 1e4                 # bp per 5m
        rng5 = (max(w5) - min(w5)) / w5[-1] * 1e4                     # bp
        rng15 = (max(w15) - min(w15)) / w15[-1] * 1e4
        drift5 = abs(w5[-1] - w5[0]) / w5[0] * 1e4
        feats[t] = {"rv5": rv5, "rng5": rng5, "rng15": rng15, "drift5": drift5}
    return feats

# ---------------------------------------------------------------- main
def main():
    res = load_resolutions()
    print(f"resolutions: {len(res)} windows", flush=True)
    trades = load_trades()
    print(f"slugs with trades: {len(trades)}", flush=True)

    POLICIES = [
        # name, policy, entry_window_s, pair_max_sum, optimistic
        ("P0_nolimit_fullwin", "nolimit", None, 1.00, False),
        ("P0_nolimit_60s",     "nolimit", 60,   1.00, False),
        ("P1_guard1_60s",      "guard1",  60,   1.00, False),
        ("P1_guard1_60s_s99",  "guard1",  60,   0.99, False),
        ("P1_guard1_60s_s97",  "guard1",  60,   0.97, False),
        ("P2_guard2_60s",      "guard2",  60,   1.00, False),
        ("P3_guard1_fullwin",  "guard1",  None, 1.00, False),
        ("P1_guard1_60s_OPT",  "guard1",  60,   1.00, True),
        ("P0_nolimit_60s_OPT", "nolimit", 60,   1.00, True),
    ]
    rows = []           # per-window per-policy results
    for slug, meta in sorted(res.items(), key=lambda kv: kv[1]["slot_start_s"]):
        pr = trades.get(slug)
        if not pr:
            continue
        t0 = meta["slot_start_s"]; win_up = meta["winner"] == "Up"
        for (name, pol, ew, pms, opt) in POLICIES:
            r = sim_window(pr, t0, win_up, pol, pair_max_sum=pms,
                           entry_window_s=ew, optimistic=opt)
            rows.append({"slug": slug, "slot": t0, "policy": name,
                         "winner": meta["winner"], **{k: v for k, v in r.items() if k != "fills"}})
    with open(DIR + r"\sim_results.json", "w") as fh:
        json.dump(rows, fh)
    print(f"sim rows: {len(rows)}", flush=True)

    feats = load_vol_features()
    with open(DIR + r"\vol_features.json", "w") as fh:
        json.dump(feats, fh)
    print(f"vol feature slots: {len(feats)}", flush=True)

if __name__ == "__main__":
    main()
