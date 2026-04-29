"""
V41 Expansion — scan regime-adaptive exits across the full strategy x coin grid.

Goal: find MORE sleeves that benefit from V41 exits (like CCI_ETH did: 1.22->1.58).

Scan: 6 coins x 4 signals x 2 exits = 48 runs (skip impossible combos).
  coins:   ETH, BTC, SOL, AVAX, DOGE, LINK
  signals: sig_cci_extreme, sig_supertrend_flip, sig_vwap_zfade, sig_bbbreak
  exits:   baseline (canonical EXIT_4H), V41 (regime-adaptive)

Rank by Sharpe improvement. Also test 2 new exit variants:
  V46: regime-scaled TP1/TP2 (tp1 = 2*atr in HighVol, 4*atr in LowVol)
  V47: breakeven SL (once trade is 1*ATR in profit, move SL to entry)

Then blend top winners with existing V41 champion to make an expanded portfolio.
"""
from __future__ import annotations
import importlib.util, json, sys, time, warnings
from pathlib import Path
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from strategy_lab.engine import load as load_data
from strategy_lab.eval.perps_simulator import simulate as sim_canonical, atr, FEE_DEFAULT, SLIP_DEFAULT
from strategy_lab.eval.perps_simulator_adaptive_exit import simulate_adaptive_exit, REGIME_EXITS_4H
from strategy_lab.regime.hmm_adaptive import fit_regime_model
from strategy_lab.run_leverage_audit import eqw_blend, invvol_blend

OUT = REPO / "docs" / "research" / "phase5_results"
BPY = 365.25 * 6
EXIT_4H = dict(tp_atr=10.0, sl_atr=2.0, trail_atr=6.0, max_hold=60)

COINS = ["ETHUSDT", "BTCUSDT", "SOLUSDT", "AVAXUSDT", "DOGEUSDT", "LINKUSDT"]

SIGNAL_SPECS = [
    ("CCI",    "run_v30_creative.py",   "sig_cci_extreme"),
    ("STF",    "run_v30_creative.py",   "sig_supertrend_flip"),
    ("VWZ",    "run_v30_creative.py",   "sig_vwap_zfade"),
    ("BBBRK",  "run_v38b_smc_mixes.py", "sig_bbbreak"),
    ("LATBB",  "run_v29_regime.py",     "sig_lateral_bb_fade"),
]

def import_sig(script, fn):
    path = REPO / "strategy_lab" / script
    spec = importlib.util.spec_from_file_location(script.replace(".","_"), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, fn)

# =============================================================================
# New exit variants
# =============================================================================
def simulate_v47_breakeven(df, le, se, size_mult=1.0, fee=FEE_DEFAULT, slip=SLIP_DEFAULT,
                           risk_per_trade=0.03, leverage_cap=3.0, init_cash=10_000.0,
                           tp_atr=10.0, sl_atr=2.0, trail_atr=6.0, max_hold=60,
                           breakeven_trigger_atr=1.0):
    """Canonical + breakeven SL: once trade is breakeven_trigger_atr in profit,
    move SL to entry (+small slip cushion). Reduces big losers from retraces."""
    op = df["open"].to_numpy(dtype=float); hi = df["high"].to_numpy(dtype=float)
    lo = df["low"].to_numpy(dtype=float); cl = df["close"].to_numpy(dtype=float)
    at = atr(df)
    sig_l = le.reindex(df.index).fillna(False).to_numpy(dtype=bool)
    sig_s = (se.reindex(df.index).fillna(False).to_numpy(dtype=bool)
             if se is not None else np.zeros(len(df), dtype=bool))
    if isinstance(size_mult, pd.Series):
        smult = size_mult.reindex(df.index).fillna(1.0).to_numpy(dtype=float)
    else:
        smult = np.full(len(df), float(size_mult))

    N = len(df); cash = init_cash
    eq = np.empty(N); eq[0] = cash
    pos = 0; entry_p = 0.0; sl = 0.0; tp = 0.0
    size = 0.0; entry_idx = 0; last_exit = -9999
    hh = 0.0; ll = 0.0
    breakeven_set = False
    entry_atr = 0.0
    trades: list[dict] = []

    for i in range(1, N - 1):
        if pos != 0:
            held = i - entry_idx
            # Breakeven SL trigger
            if not breakeven_set and entry_atr > 0:
                if pos == 1 and hi[i] >= entry_p + breakeven_trigger_atr * entry_atr:
                    sl = max(sl, entry_p * (1 + slip))
                    breakeven_set = True
                elif pos == -1 and lo[i] <= entry_p - breakeven_trigger_atr * entry_atr:
                    sl = min(sl, entry_p * (1 - slip))
                    breakeven_set = True

            # Trailing stop
            if trail_atr and np.isfinite(at[i]) and at[i] > 0:
                if pos == 1:
                    hh = max(hh, hi[i])
                    new_sl = hh - trail_atr * at[i]
                    if new_sl > sl: sl = new_sl
                else:
                    ll = min(ll, lo[i]) if ll > 0 else lo[i]
                    new_sl = ll + trail_atr * at[i]
                    if new_sl < sl: sl = new_sl

            exited = False; ep = 0.0; reason = ""
            if pos == 1:
                if lo[i] <= sl: ep, reason, exited = sl*(1-slip), "SL", True
                elif hi[i] >= tp: ep, reason, exited = tp*(1-slip), "TP", True
                elif held >= max_hold: ep, reason, exited = cl[i], "TIME", True
            else:
                if hi[i] >= sl: ep, reason, exited = sl*(1+slip), "SL", True
                elif lo[i] <= tp: ep, reason, exited = tp*(1+slip), "TP", True
                elif held >= max_hold: ep, reason, exited = cl[i], "TIME", True

            if exited:
                pnl = (ep - entry_p) * pos
                fee_cost = size * (entry_p + ep) * fee
                realized = size * pnl - fee_cost
                cash_before = cash; cash += realized
                trades.append({"ret": realized/max(cash_before,1.0),
                               "realized": realized, "reason": reason,
                               "side": pos, "bars": held, "entry": entry_p,
                               "exit": ep, "entry_idx": entry_idx, "exit_idx": i})
                pos = 0; last_exit = i; breakeven_set = False
                eq[i] = cash
                continue

        if pos == 0 and (i - last_exit) > 2 and i + 1 < N:
            take_long = sig_l[i]; take_short = sig_s[i]
            if take_long or take_short:
                direction = 1 if take_long else -1
                ep_new = op[i+1] * (1 + slip * direction)
                if np.isfinite(at[i]) and at[i] > 0 and cash > 0 and ep_new > 0:
                    risk_dollars = cash * risk_per_trade
                    stop_dist = sl_atr * at[i]
                    if stop_dist > 0:
                        size_risk = risk_dollars / stop_dist
                        size_cap = (cash * leverage_cap) / ep_new
                        new_size = min(size_risk, size_cap) * smult[i+1]
                        s_stop = ep_new - sl_atr * at[i] * direction
                        t_stop = ep_new + tp_atr * at[i] * direction
                        if new_size > 0 and np.isfinite(s_stop) and np.isfinite(t_stop):
                            pos = direction; entry_p = ep_new
                            sl = s_stop; tp = t_stop; size = new_size
                            entry_idx = i + 1; hh = ep_new; ll = ep_new
                            entry_atr = at[i]; breakeven_set = False

        eq[i] = cash if pos == 0 else cash + size * (cl[i] - entry_p) * pos

    eq[-1] = eq[-2]
    return trades, pd.Series(eq, index=df.index)


# =============================================================================
# Metrics
# =============================================================================
def metrics(eq, trades, label=""):
    n = len(trades)
    if len(eq) < 30:
        return {"label": label, "n": n, "sharpe": 0, "cagr": 0, "mdd": 0,
                "calmar": 0, "wr": 0, "min_yr": 0, "pos_yrs": 0, "pf": 0}
    rets = eq.pct_change().dropna()
    mu, sd = float(rets.mean()), float(rets.std())
    sh = (mu/sd)*np.sqrt(BPY) if sd > 0 else 0
    pk = eq.cummax(); mdd = float((eq/pk - 1).min())
    yrs = (eq.index[-1] - eq.index[0]).total_seconds()/(365.25*86400)
    total = float(eq.iloc[-1]/eq.iloc[0] - 1)
    cagr = (1+total)**(1/max(yrs,1e-6))-1
    cal = cagr/abs(mdd) if mdd != 0 else 0
    wins = [t for t in (trades or []) if t.get("ret",0) > 0]
    losses = [t for t in (trades or []) if t.get("ret",0) <= 0]
    wr = len(wins)/n if n > 0 else 0
    loss_sum = sum(t["ret"] for t in losses) if losses else 0
    pf = abs(sum(t["ret"] for t in wins) / loss_sum) if loss_sum != 0 else 0
    yrs_map = {}
    for yr in sorted(set(eq.index.year)):
        e = eq[eq.index.year == yr]
        if len(e) >= 30:
            yrs_map[int(yr)] = float(e.iloc[-1]/e.iloc[0] - 1)
    min_yr = min(yrs_map.values()) if yrs_map else 0
    pos_yrs = sum(1 for r in yrs_map.values() if r > 0)
    return {"label": label, "n": n, "sharpe": round(sh, 3), "cagr": round(cagr, 4),
            "mdd": round(mdd, 4), "calmar": round(cal, 3), "wr": round(wr, 3),
            "min_yr": round(min_yr, 4), "pos_yrs": pos_yrs, "pf": round(pf, 2)}


# =============================================================================
# Grid scan
# =============================================================================
def main():
    t0 = time.time()
    rows = []
    curves = {}  # (coin, sig, exit) -> equity

    # Regime cache per coin
    regime_cache = {}
    def get_regime(coin):
        if coin in regime_cache: return regime_cache[coin]
        df = load_data(coin, "4h", start="2021-01-01", end="2026-03-31")
        _, rdf = fit_regime_model(df, train_frac=0.30, seed=42)
        regime_cache[coin] = (df, rdf["label"])
        return regime_cache[coin]

    print(f"Scanning {len(COINS)} coins x {len(SIGNAL_SPECS)} strategies x 3 exits...")
    for coin in COINS:
        try:
            df, reg_labels = get_regime(coin)
        except Exception as e:
            print(f"[fail] {coin}: {type(e).__name__}: {e}")
            continue

        for sig_name, script, fn in SIGNAL_SPECS:
            try:
                sig = import_sig(script, fn)
                out = sig(df)
                le, se = out if isinstance(out, tuple) else (out, None)
            except Exception as e:
                print(f"  {coin} {sig_name}: sig err {type(e).__name__}")
                continue

            # Three exits: baseline, V41, V47
            try:
                _, eq_base = sim_canonical(df, le, se, **EXIT_4H)
                _, eq_v41 = simulate_adaptive_exit(df, le, se, reg_labels)
                _, eq_v47 = simulate_v47_breakeven(df, le, se)
            except Exception as e:
                print(f"  {coin} {sig_name}: sim err {type(e).__name__}")
                continue

            tb, _ = sim_canonical(df, le, se, **EXIT_4H)
            tv, _ = simulate_adaptive_exit(df, le, se, reg_labels)
            tw, _ = simulate_v47_breakeven(df, le, se)

            for ex_name, (tr, eq) in [("baseline", (tb, eq_base)),
                                       ("V41", (tv, eq_v41)),
                                       ("V47", (tw, eq_v47))]:
                m = metrics(eq, tr, f"{coin[:-4]}_{sig_name}_{ex_name}")
                m["coin"] = coin[:-4]; m["sig"] = sig_name; m["exit"] = ex_name
                rows.append(m)
                curves[(coin, sig_name, ex_name)] = eq

    df_out = pd.DataFrame(rows)
    df_out.to_csv(OUT / "v41_expansion_grid.csv", index=False)

    # ---- Rank winners: positive Sharpe with biggest V41 delta vs baseline ----
    print("\n" + "=" * 80)
    print("V41/V47 improvement over baseline (min 20 trades, pos_yrs>=5)")
    print("=" * 80)
    deltas = []
    for coin in COINS:
        for sig_name, _, _ in SIGNAL_SPECS:
            base = [r for r in rows if r["coin"] == coin[:-4] and r["sig"] == sig_name and r["exit"]=="baseline"]
            v41 = [r for r in rows if r["coin"] == coin[:-4] and r["sig"] == sig_name and r["exit"]=="V41"]
            v47 = [r for r in rows if r["coin"] == coin[:-4] and r["sig"] == sig_name and r["exit"]=="V47"]
            if not (base and v41 and v47):
                continue
            b, v, w = base[0], v41[0], v47[0]
            # pick best non-baseline exit
            if max(v["sharpe"], w["sharpe"]) <= b["sharpe"]:
                continue
            if max(v["n"], w["n"]) < 20:
                continue
            best = v if v["sharpe"] >= w["sharpe"] else w
            best_ex = "V41" if best == v else "V47"
            deltas.append({"coin": coin[:-4], "sig": sig_name,
                            "exit": best_ex,
                            "base_sh": b["sharpe"], "new_sh": best["sharpe"],
                            "delta": best["sharpe"] - b["sharpe"],
                            "new_cagr": best["cagr"], "new_mdd": best["mdd"],
                            "new_cal": best["calmar"], "new_minyr": best["min_yr"],
                            "new_pos_yrs": best["pos_yrs"], "n": best["n"],
                            "new_wr": best["wr"]})
    deltas.sort(key=lambda x: -x["delta"])
    print(f"{'coin':6s} {'sig':6s} {'exit':5s} {'base':>6s} {'new':>6s} {'+delta':>7s} "
          f"{'cagr':>7s} {'mdd':>7s} {'cal':>5s} {'minYr':>7s} {'pos':>4s} {'n':>4s}")
    for d in deltas[:20]:
        print(f"{d['coin']:6s} {d['sig']:6s} {d['exit']:5s} {d['base_sh']:6.2f} "
              f"{d['new_sh']:6.2f} {d['delta']:+7.2f} "
              f"{d['new_cagr']*100:+6.1f}% {d['new_mdd']*100:+6.1f}% "
              f"{d['new_cal']:5.2f} {d['new_minyr']*100:+6.1f}% "
              f"{d['new_pos_yrs']:>2d}/6 {d['n']:4d}")

    # ---- Save curves for top-5 deltas so we can blend them later ----
    top5 = deltas[:5]
    winners_data = {}
    for d in top5:
        coin_full = d["coin"] + "USDT"
        key = (coin_full, d["sig"], d["exit"])
        if key in curves:
            eq = curves[key]
            winners_data[f"{d['coin']}_{d['sig']}_{d['exit']}"] = {
                "metadata": {k: v for k, v in d.items()},
                "equity_final": float(eq.iloc[-1]),
                "equity_len": len(eq),
            }
    with open(OUT / "v41_expansion_top5.json", "w") as f:
        json.dump(winners_data, f, indent=2, default=str)

    # ---- Now: add top winners to NEW_60_40_V41 blend; compare ----
    print("\n" + "=" * 80)
    print("EXPANDED PORTFOLIO TEST — add top V41 winners to existing champion")
    print("=" * 80)
    # Build existing NEW_60_40_V41 equity
    from strategy_lab.run_v41_gates import build_sleeve_curve, BEST_VARIANT_MAP

    base_curves = {s: build_sleeve_curve(s, v) for s, v in BEST_VARIANT_MAP.items()}
    p3_eq = invvol_blend({k: base_curves[k] for k in ["CCI_ETH_4h","STF_AVAX_4h","STF_SOL_4h"]}, window=500)
    p5_eq = eqw_blend({k: base_curves[k] for k in ["CCI_ETH_4h","LATBB_AVAX_4h","STF_SOL_4h"]})
    idx = p3_eq.index.intersection(p5_eq.index)
    champ_r = 0.6 * p3_eq.reindex(idx).pct_change().fillna(0) + 0.4 * p5_eq.reindex(idx).pct_change().fillna(0)
    champ_eq = (1 + champ_r).cumprod() * 10_000.0
    mc = metrics(champ_eq, [], "NEW_60_40_V41")
    print(f"Current champion NEW_60_40_V41: Sharpe={mc['sharpe']} CAGR={mc['cagr']*100:+.1f}% "
          f"MDD={mc['mdd']*100:+.1f}% Cal={mc['calmar']}")

    # Try adding each top-5 winner to the blend at 10%, 20%, 30% weight
    print("\nLayering each top-5 winner onto champion (50/50, then 70/30):")
    for d in top5:
        coin_full = d["coin"] + "USDT"
        key = (coin_full, d["sig"], d["exit"])
        if key not in curves:
            continue
        winner_eq = curves[key]
        # Align
        com_idx = champ_eq.index.intersection(winner_eq.index)
        cr = champ_eq.reindex(com_idx).pct_change().fillna(0)
        wr = winner_eq.reindex(com_idx).pct_change().fillna(0)
        for w in [0.15, 0.25, 0.35]:
            blended_r = (1-w)*cr + w*wr
            blended_eq = (1 + blended_r).cumprod() * 10_000.0
            m = metrics(blended_eq, [], f"champ+{w:.0%}_{d['coin']}_{d['sig']}_{d['exit']}")
            marker = "WIN" if m["sharpe"] > mc["sharpe"] else "   "
            print(f"  [{marker}] champ@{1-w:.0%} + {d['coin']}_{d['sig']}_{d['exit']}@{w:.0%}: "
                  f"Sharpe={m['sharpe']:5.3f} CAGR={m['cagr']*100:+5.1f}% MDD={m['mdd']*100:+6.1f}% "
                  f"Cal={m['calmar']:5.2f} minYr={m['min_yr']*100:+5.1f}%")

    print(f"\nTotal runtime: {time.time()-t0:.1f}s")
    print(f"Saved grid -> {OUT}/v41_expansion_grid.csv")

if __name__ == "__main__":
    main()
