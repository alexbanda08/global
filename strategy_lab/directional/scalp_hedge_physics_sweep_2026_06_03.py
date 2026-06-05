"""
Sweep all scalp/hedge/physics policies off the cache. Writes SCALP_HEDGE_PHYSICS_SWEEP_2026_06_03.md.
"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
CACHE = ROOT / "strategy_lab" / "directional" / "_results" / "scalp_hedge_physics_cache_2026_06_03.parquet"
FIRES = ROOT / "strategy_lab" / "lag_taker_fires_oos_2026_06_01.parquet"
OUT = ROOT / "strategy_lab" / "reports" / "SCALP_HEDGE_PHYSICS_SWEEP_2026_06_03.md"
RNG = np.random.default_rng(5)
EXIT_DTS = [30, 45, 60, 75, 90, 120, 150, 180]; TP = [60, 65, 70, 75]

def boot_ci(x, n=8000):
    x = np.asarray(x, float); x = x[np.isfinite(x)]
    if len(x) < 3: return (np.nan, np.nan)
    idx = RNG.integers(0, len(x), size=(n, len(x))); mu = x[idx].mean(1)
    return float(np.percentile(mu, 2.5)), float(np.percentile(mu, 97.5))
def tstat(x):
    x = np.asarray(x, float); x = x[np.isfinite(x)]
    if len(x) < 3 or x.std(ddof=1) == 0: return np.nan
    return float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x))))
def agg(p):
    p = np.asarray(p, float); p = p[np.isfinite(p)]
    if not len(p): return dict(n=0, dpt=np.nan, t=np.nan, ci=(np.nan, np.nan), wr=np.nan)
    return dict(n=len(p), dpt=round(p.mean(), 3), t=round(tstat(p), 2),
                ci=tuple(round(v, 2) for v in boot_ci(p)), wr=round(100*(p > 0).mean(), 1))

def hold07(ev, sh, won): return sh*(1-ev)*(1-0.07*ev) if won else -sh*ev
def scalp_pnl(ev, sh, exit_bid, won, fee):
    if not np.isfinite(exit_bid):  # no exit -> hold
        return hold07(ev, sh, won)
    rt = (exit_bid - ev) * sh
    rt -= fee * sh * (ev*(1-ev) + exit_bid*(1-exit_bid))
    return rt

c = pd.read_parquet(CACHE)
fires = pd.read_parquet(FIRES)[["slug", "fire_us", "segment"]]
c = c.merge(fires, on=["slug", "fire_us"], how="left")
F = c[c.filled].copy()
print(f"cache n={len(c)} filled={len(F)}", flush=True)

L = ["# Autonomous scalp / hedge / physics sweep — 2026-06-03", "",
     f"Universe: lag-taker fires re-filled @10Hz (n_filled={len(F)} of {len(c)}). engine_v2 85ms latency, "
     "min_book_events=25, spread 0.05. $/tr win07-style; scalp round-trip fees shown at 0 / 0.015 / 0.07.", ""]

def deployed(d): return d[(d.asset.isin(["BTC", "ETH"])) & (d.delta_bps >= 5) & (d.entry_vwap < 0.55)]

# ============ BLOCK 1: EXIT-TIMING SWEEP ============
L += ["## Block 1 — Exit-timing sweep (deployed cell: BTC+ETH, delta>=5, entry_vwap<0.55)", "",
      "| policy | n | scalp-WR | $/tr fee0 | $/tr 0.015 | $/tr 0.07 | t(0.015) | CI(0.015) |",
      "|---|--:|--:|--:|--:|--:|--:|--:|"]
D = deployed(F)
def row_policy(name, exitcol_fn):
    p0 = [scalp_pnl(r.entry_vwap, r.shares, exitcol_fn(r), r.won, 0.0) for r in D.itertuples()]
    p15 = [scalp_pnl(r.entry_vwap, r.shares, exitcol_fn(r), r.won, 0.015) for r in D.itertuples()]
    p7 = [scalp_pnl(r.entry_vwap, r.shares, exitcol_fn(r), r.won, 0.07) for r in D.itertuples()]
    a0, a15, a7 = agg(p0), agg(p15), agg(p7)
    return f"| {name} | {a15['n']} | {round(100*np.mean([(exitcol_fn(r)>r.entry_vwap) for r in D.itertuples() if np.isfinite(exitcol_fn(r))]),1)} | {a0['dpt']:+} | {a15['dpt']:+} | {a7['dpt']:+} | {a15['t']} | [{a15['ci'][0]:+},{a15['ci'][1]:+}] |"
# HOLD
L.append(f"| HOLD-to-resolution | {len(D)} | — | {agg([hold07(r.entry_vwap,r.shares,r.won) for r in D.itertuples()])['dpt']:+} | (same) | (same) | {agg([hold07(r.entry_vwap,r.shares,r.won) for r in D.itertuples()])['t']} | {agg([hold07(r.entry_vwap,r.shares,r.won) for r in D.itertuples()])['ci']} |")
for dt in EXIT_DTS:
    L.append(row_policy(f"TIME+{dt}s", (lambda dt: lambda r: getattr(r, f"bid_{dt}"))(dt)))
for tp in TP:
    def mk(tp):
        def f(r):
            hit = getattr(r, f"tp_hit_{tp}_dt")
            return (tp/100.0) if np.isfinite(hit) else (r.bid_180 if np.isfinite(r.bid_180) else np.nan)
        return f
    L.append(row_policy(f"TP@0.{tp} (else +180/hold)", mk(tp)))
L.append(row_policy("ORACLE best-exit (path max)", lambda r: r.bid_pathmax))
L.append("")

# ============ BLOCK 2: PHYSICS VOL-REGIME GATES on scalp TIME+60 ============
L += ["## Block 2 — Physics volatility-regime gates (scalp TIME+60s, fee=0.015, deployed cell)", ""]
D2 = D[np.isfinite(D.get("phys_speed_abs"))].copy() if "phys_speed_abs" in D else D.iloc[0:0]
def scalp60(d, fee=0.015): return np.array([scalp_pnl(r.entry_vwap, r.shares, r.bid_60, r.won, fee) for r in d.itertuples()])
if len(D2):
    base = agg(scalp60(D2)); L.append(f"baseline (all w/ physics): n={base['n']} $/tr={base['dpt']:+} t={base['t']} CI{base['ci']}\n")
    L += ["| gate | n | $/tr(0.015) | t | CI | WR>0 |", "|---|--:|--:|--:|--:|--:|"]
    def gaterow(name, mask):
        d = D2[mask]; a = agg(scalp60(d))
        L.append(f"| {name} | {a['n']} | {a['dpt']:+} | {a['t']} | [{a['ci'][0]:+},{a['ci'][1]:+}] | {a['wr']} |")
    for b in ["quiet <5","normal 5-10","active 10-15","storm 15-25","hurricane >=25"]:
        gaterow(f"bucket={b}", D2.phys_bucket == b)
    for thr in [20,30,40,50]:
        gaterow(f"dist_abs>={thr}", D2.phys_dist_abs >= thr)
    for thr in [5,10,15]:
        gaterow(f"speed_abs>={thr}", D2.phys_speed_abs >= thr)
    gaterow("speed_away>=10", D2.phys_speed_away >= 10)
    gaterow("WEAK_COMBO_kept (dist>=30 OR away>=10)", (D2.phys_dist_abs >= 30) | (D2.phys_speed_away >= 10))
    gaterow("d_speed>=0 (accelerating)", D2.phys_d_speed >= 0)
    gaterow("margin>0 (won't cross strike)", D2.phys_margin > 0)
else:
    L.append("*(no physics features in cache — check chainlink/strike join)*")
L.append("")

# ============ BLOCK 3: HEDGE ============
L += ["## Block 3 — Hedge", "",
      "### 3a. Stop-loss salvage on HOLD (cut held token at bid when it falls; vs pure hold)", "",
      "| policy | n | $/tr(0.015) | t | CI |", "|---|--:|--:|--:|--:|"]
def stoploss_pnl(d, stop_drop, dt_grid=(30,60,90,120), fee=0.015):
    out = []
    for r in d.itertuples():
        ev, sh = r.entry_vwap, r.shares; cut = None
        for dt in dt_grid:
            b = getattr(r, f"bid_{dt}")
            if np.isfinite(b) and b <= ev - stop_drop:
                cut = b; break
        out.append(scalp_pnl(ev, sh, cut, r.won, fee) if cut is not None else hold07(ev, sh, r.won))
    return np.array(out)
ah = agg([hold07(r.entry_vwap, r.shares, r.won) for r in D.itertuples()])
L.append(f"| HOLD (control) | {ah['n']} | {ah['dpt']:+} | {ah['t']} | {ah['ci']} |")
for sd in [0.05, 0.10, 0.15, 0.20]:
    a = agg(stoploss_pnl(D, sd)); L.append(f"| stop if bid<=entry-{sd} | {a['n']} | {a['dpt']:+} | {a['t']} | [{a['ci'][0]:+},{a['ci'][1]:+}] |")
L += ["", "### 3b. Buy-opposite hedge (buy lead + buy opposite token; paired, capped loss)", "",
      "| hedge | n | $/tr(0.015) | t | CI | note |", "|---|--:|--:|--:|--:|---|"]
def buyopp_pnl(d, oppcol, fee=0.015):
    out = []
    for r in d.itertuples():
        ev, sh = r.entry_vwap, r.shares
        oppv = getattr(r, oppcol, np.nan)
        lead = hold07(ev, sh, r.won)
        if not np.isfinite(oppv) or oppv <= 0 or oppv >= 1:
            out.append(lead); continue
        opp_sh = (ev * sh) / oppv * 0.5   # hedge half the lead notional onto opposite
        hedge = (opp_sh*(1-oppv)*(1-0.07*oppv)) if (not r.won) else (-opp_sh*oppv)  # opp wins iff lead lost
        out.append(lead + hedge - fee*opp_sh*oppv*(1-oppv))
    return np.array(out)
for col in ["oppask_30", "oppask_60", "opp_ask_min"]:
    if col in D.columns:
        a = agg(buyopp_pnl(D, col)); L.append(f"| buy-opp @ {col} (50% notional) | {a['n']} | {a['dpt']:+} | {a['t']} | [{a['ci'][0]:+},{a['ci'][1]:+}] | vs HOLD {ah['dpt']:+} |")
L.append("")

# ============ BLOCK 4: SEGMENTS + GENERALITY ============
L += ["## Block 4 — Scalp TIME+60 by segment + universe generality (fee=0.015)", "",
      "| cut | n | $/tr | t | CI |", "|---|--:|--:|--:|--:|"]
def seg_row(name, d):
    a = agg(scalp60(d)); L.append(f"| {name} | {a['n']} | {a['dpt']:+} | {a['t']} | [{a['ci'][0]:+},{a['ci'][1]:+}] |")
seg_row("deployed cell (all seg)", D)
for s in ["fit_IS","fit_OOS","bwd_oos","fwd_oos"]:
    seg_row(f"  segment={s}", D[D.segment == s])
seg_row("BTC only", D[D.asset=="BTC"]); seg_row("ETH only", D[D.asset=="ETH"])
seg_row("no vwap filter (delta>=5)", F[(F.asset.isin(["BTC","ETH"]))&(F.delta_bps>=5)])
seg_row("vwap<0.55 ALL delta", F[(F.asset.isin(["BTC","ETH"]))&(F.entry_vwap<0.55)])
for dl in [3,5,8,10]:
    seg_row(f"delta>={dl} & vwap<0.55", F[(F.asset.isin(["BTC","ETH"]))&(F.delta_bps>=dl)&(F.entry_vwap<0.55)])
L.append("")

# ============ BLOCK 5: physics-gated BEST scalp ============
L += ["## Block 5 — Best scalp × best physics gate (stacked)", ""]
if len(D2):
    combos = [("storm+ (speed>=15)", D2.phys_speed_abs>=15), ("active+ (speed>=10)", D2.phys_speed_abs>=10),
              ("dist>=40", D2.phys_dist_abs>=40), ("d_speed>=0", D2.phys_d_speed>=0),
              ("speed>=10 & d_speed>=0", (D2.phys_speed_abs>=10)&(D2.phys_d_speed>=0))]
    L += ["| stacked gate | n | TIME+60 $/tr | t | CI |", "|---|--:|--:|--:|--:|"]
    for nm, mk in combos:
        a = agg(scalp60(D2[mk])); L.append(f"| {nm} | {a['n']} | {a['dpt']:+} | {a['t']} | [{a['ci'][0]:+},{a['ci'][1]:+}] |")
L.append("")
OUT.write_text("\n".join(str(x) for x in L), encoding="utf-8")
print("wrote", OUT, flush=True)
print("\n".join(str(x) for x in L[:60]), flush=True)
