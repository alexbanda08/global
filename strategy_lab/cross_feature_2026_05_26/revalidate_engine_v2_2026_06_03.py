"""
Phase-A re-validation: run the 6 cross-feature lockbox survivors through the
PRODUCTION fill engine (engine_v2) instead of the LegacyConfig (2%-on-profit) +
1Hz books used in the original 2026-05-26 study.

Same fires, same feature values (read straight from master.parquet) — ONLY the
fill + fee accounting changes:
  - books reloaded at NATIVE 10Hz (subsample_1hz=False)   [was 1Hz]
  - fill_at_book: 85ms latency, min_book_events=25, spread_filter=0.02
  - fee model reported THREE ways per fire:
      legacy   = 2%-on-profit winner-only   (the original study's number)
      livemimic= 0.07*p*(1-p) BOTH legs     (engine_v2 LiveMimicConfig, conservative/harsh)
      win07    = 0.07*p*(1-p) winner-only    (CLAUDE.md operator-confirmed production truth)

Hold-to-resolution directional bet (this is what the study tested). won = bet side
matches chainlink outcome.

Output: REVALIDATION_ENGINE_V2_2026_06_03.{md,csv}
"""
import sys, json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "strategy_lab"))
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))

from engine_v2 import LiveMimicConfig, LegacyConfig, fill_at_book, hold_pnl  # noqa
from load import load_orderbook_l25_streaming  # noqa

MASTER = ROOT / "strategy_lab" / "cross_feature_2026_05_26" / "master.parquet"
OUT_MD = ROOT / "strategy_lab" / "reports" / "REVALIDATION_ENGINE_V2_2026_06_03.md"
OUT_CSV = ROOT / "strategy_lab" / "cross_feature_2026_05_26" / "revalidation_engine_v2_2026_06_03.csv"
SPREAD = 0.02
BATCH = 400
RNG = np.random.default_rng(7)

# ---- survivor rule defs ----------------------------------------------------
def masks(d, rule):
    if rule == "XF-I":
        up = (d.mp_skew > 0) & (d.hawkes_lambda_imbalance > 0.1)
        dn = (d.mp_skew < 0) & (d.hawkes_lambda_imbalance < -0.1)
    elif rule == "XF-J":
        up = (d.hawkes_lambda_imbalance > 0.2) & (d.lm_last_jump_dir_60s > 0)
        dn = (d.hawkes_lambda_imbalance < -0.2) & (d.lm_last_jump_dir_60s < 0)
    elif rule == "DISAGR-HAWKES":
        up = (d.mp_skew > 0) & (d.imb5_diff < 0) & (d.hawkes_lambda_imbalance > 0.2)
        dn = (d.mp_skew < 0) & (d.imb5_diff > 0) & (d.hawkes_lambda_imbalance < -0.2)
    else:
        raise ValueError(rule)
    return up.to_numpy(), dn.to_numpy()

SURVIVORS = [
    ("XF-J  BTC 5m  @180 BOTH", "XF-J",          "BTC", "5m", 180, "both", dict(n=41,  wr=87.8, dpt=6.98)),
    ("DISAGR SOL 5m @210 DN",   "DISAGR-HAWKES", "SOL", "5m", 210, "dn",   dict(n=35,  wr=100.0, dpt=6.54)),
    ("XF-I  SOL 15m @240 UP",   "XF-I",          "SOL", "15m",240, "up",   dict(n=56,  wr=78.6, dpt=6.31)),
    ("XF-I  SOL 15m @240 BOTH", "XF-I",          "SOL", "15m",240, "both", dict(n=105, wr=72.4, dpt=4.09)),
    ("XF-I  BTC 5m  @150 UP",   "XF-I",          "BTC", "5m", 150, "up",   dict(n=198, wr=76.8, dpt=3.56)),
    ("XF-I  BTC 5m  @150 BOTH", "XF-I",          "BTC", "5m", 150, "both", dict(n=419, wr=74.0, dpt=2.32)),
]

def winner_only_07(vwap, shares, won, rate=0.07):
    if won:
        return shares * (1.0 - vwap) * (1.0 - rate * vwap)
    return -shares * vwap

def boot_ci(x, n=10000):
    if len(x) < 2:
        return (float("nan"), float("nan"))
    idx = RNG.integers(0, len(x), size=(n, len(x)))
    means = np.asarray(x)[idx].mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))

def tstat(x):
    x = np.asarray(x, float)
    if len(x) < 2 or x.std(ddof=1) == 0:
        return float("nan")
    return float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x))))

# ---- build fire list -------------------------------------------------------
m = pd.read_parquet(MASTER)
print(f"master rows={len(m)}", flush=True)

fires = []  # (sv_idx, slug, asset, fire_us, token_outcome, won)
for si, (name, rule, asset, tf, off, side, _) in enumerate(SURVIVORS):
    d = m[(m.asset == asset) & (m.tf == tf) & (m.fire_offset_s == off)].reset_index(drop=True)
    up, dn = masks(d, rule)
    if side == "up":
        sel = up
        bet = np.where(sel, "Up", None)
    elif side == "dn":
        sel = dn
        bet = np.where(sel, "Down", None)
    else:  # both
        sel = up | dn
        bet = np.where(up, "Up", np.where(dn, "Down", None))
    dd = d[sel].copy()
    betsel = bet[sel]
    for r, tok in zip(dd.itertuples(), betsel):
        won = (tok == r.outcome)
        fires.append((si, r.slug, asset, int(r.fire_us), tok, bool(won)))
print(f"total fires across 6 survivors={len(fires)}", flush=True)

fires_df = pd.DataFrame(fires, columns=["sv", "slug", "asset", "fire_us", "token", "won"])

# ---- fill each fire through engine_v2 (batched per asset to bound RAM) ------
cfg_lm = LiveMimicConfig()
pnl_lm = {}; pnl_win07 = {}; pnl_leg = {}; filled = {}; vwap_rec = {}
for asset in sorted(fires_df.asset.unique()):
    sub = fires_df[fires_df.asset == asset]
    slugs_all = sorted(sub.slug.unique())
    print(f"[{asset}] {len(sub)} fires, {len(slugs_all)} slugs", flush=True)
    for b0 in range(0, len(slugs_all), BATCH):
        bs = set(slugs_all[b0:b0 + BATCH])
        bsub = sub[sub.slug.isin(bs)]
        tmin = int(bsub.fire_us.min()) - 130_000_000
        tmax = int(bsub.fire_us.max()) + 1_000_000
        books = load_orderbook_l25_streaming(asset.lower(), slugs=bs,
                                             subsample_1hz=False,
                                             min_ts_us=tmin, max_ts_us=tmax)
        for r in bsub.itertuples():
            f = fill_at_book(books, r.slug, r.token, r.fire_us, cfg=cfg_lm,
                             spread_filter=SPREAD)
            key = r.Index
            if f is None:
                filled[key] = False
                continue
            filled[key] = True
            vwap_rec[key] = f["vwap"]
            pnl_lm[key] = hold_pnl(f, won=r.won, cfg=cfg_lm)
            pnl_win07[key] = winner_only_07(f["vwap"], f["shares"], r.won)
            # legacy 2%-on-profit winner-only for reference (same fill)
            pnl_leg[key] = hold_pnl(f, won=r.won, cfg=LegacyConfig())
        del books
        print(f"   batch {b0//BATCH}: cum_filled={sum(filled.values())}", flush=True)

# ---- aggregate per survivor ------------------------------------------------
rows = []
for si, (name, rule, asset, tf, off, side, orig) in enumerate(SURVIVORS):
    idxs = fires_df.index[fires_df.sv == si]
    n_fire = len(idxs)
    fk = [k for k in idxs if filled.get(k, False)]
    n_fill = len(fk)
    if n_fill == 0:
        rows.append(dict(survivor=name, n_fire=n_fire, n_fill=0))
        continue
    won = np.array([fires_df.at[k, "won"] for k in fk])
    p_lm = np.array([pnl_lm[k] for k in fk])
    p_w7 = np.array([pnl_win07[k] for k in fk])
    p_lg = np.array([pnl_leg[k] for k in fk])
    vw = np.array([vwap_rec[k] for k in fk])
    ci7 = boot_ci(p_w7); cilm = boot_ci(p_lm)
    rows.append(dict(
        survivor=name, n_fire=n_fire, n_fill=n_fill,
        fill_rate=round(n_fill / n_fire, 3),
        wr=round(100 * won.mean(), 1), mean_vwap=round(vw.mean(), 3),
        legacy_dpt=round(p_lg.mean(), 3),
        win07_dpt=round(p_w7.mean(), 3), win07_t=round(tstat(p_w7), 2),
        win07_ci_lo=round(ci7[0], 3), win07_ci_hi=round(ci7[1], 3),
        livemimic_dpt=round(p_lm.mean(), 3), livemimic_t=round(tstat(p_lm), 2),
        livemimic_ci_lo=round(cilm[0], 3), livemimic_ci_hi=round(cilm[1], 3),
        orig_lockbox_n=orig["n"], orig_lockbox_wr=orig["wr"], orig_lockbox_dpt=orig["dpt"],
    ))

res = pd.DataFrame(rows)
res.to_csv(OUT_CSV, index=False)
print("\n", res.to_string(index=False), flush=True)

# ---- markdown report -------------------------------------------------------
def verdict(r):
    if r.get("n_fill", 0) < 30: return "⏸ LOW-N"
    if r["win07_ci_lo"] > 0 and r["livemimic_ci_lo"] > 0: return "✅ SURVIVES (both fees)"
    if r["win07_ci_lo"] > 0: return "🟡 SURVIVES win-only (dies under harsh)"
    return "🔴 DEAD"

lines = ["# Phase-A re-validation — 6 cross-feature survivors through engine_v2 — 2026-06-03", "",
         f"Full-window fires (Apr24→May25), native 10Hz L25, 85ms latency, min_book_events=25, "
         f"spread_filter={SPREAD}. Hold-to-resolution directional bet.", "",
         "Fees: **win07** = 0.07×p×(1−p) winner-only (production truth, CLAUDE.md). "
         "**livemimic** = 0.07 both-leg (conservative). **legacy** = 2%-on-profit (original study).", "",
         "| survivor | n_fire | n_fill | fill% | WR | vwap | legacy $/tr | win07 $/tr | win07 t | win07 CI | livemimic $/tr | LM CI | orig lockbox | verdict |",
         "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|"]
for _, r in res.iterrows():
    rd = r.to_dict()
    if rd.get("n_fill", 0) == 0:
        lines.append(f"| {rd['survivor']} | {rd['n_fire']} | 0 | — | — | — | — | — | — | — | — | — | n={rd.get('orig_lockbox_n')} | 🔴 NO FILLS |")
        continue
    lines.append(
        f"| {rd['survivor']} | {rd['n_fire']} | {rd['n_fill']} | {rd['fill_rate']} | {rd['wr']} | {rd['mean_vwap']} "
        f"| {rd['legacy_dpt']:+} | {rd['win07_dpt']:+} | {rd['win07_t']} | [{rd['win07_ci_lo']:+},{rd['win07_ci_hi']:+}] "
        f"| {rd['livemimic_dpt']:+} | [{rd['livemimic_ci_lo']:+},{rd['livemimic_ci_hi']:+}] "
        f"| n={rd['orig_lockbox_n']} {rd['orig_lockbox_wr']}% +${rd['orig_lockbox_dpt']} | {verdict(rd)} |")
lines += ["", "## Notes",
          "- n_fire here = FULL-window fires (vs the original 4-day lockbox n). engine_v2 test gets max power.",
          "- A survivor must clear win07 CI>0. ✅ also clears the harsh both-leg fee.",
          "- The original lockbox $/tr used LegacyConfig (2%-on-profit) + 1Hz books → compare the `legacy $/tr` "
          "column to `orig lockbox` to isolate the 10Hz/latency/fill effect from the fee effect."]
OUT_MD.write_text("\n".join(lines), encoding="utf-8")
print(f"\nwrote {OUT_MD}", flush=True)
