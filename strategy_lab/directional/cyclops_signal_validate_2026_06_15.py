"""VALIDATE the decoded Cyclops strategy on LOCAL canonical data — 2026-06-15
Decoded rule (from cyclops_decode_5d): mid-window, when Binance has already moved
>= THR bps from window-open in one direction, BUY that (favorite) side, HOLD to
resolution. Cyclops 5d: align 100%, binance@fire predicts close 92.3%, WR 96% @
median entry 0.83.

This tests the SIGNAL edge on canonical (Apr 22 -> Jun 11), big n, klines-only
(no L25 needed): for BTC/ETH 5m slugs, if Binance moved >=THR bps (aligned) by
offset t, what is P(close finishes same direction)?  vs base rate. That P is the
conditional WR the bot is monetizing. Compare to the 0.83 poly price it pays.

Run: C:/Python314/python.exe strategy_lab/directional/cyclops_signal_validate_2026_06_15.py
"""
from __future__ import annotations
import sys, io
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical")
import numpy as np, pandas as pd
pd.set_option("display.width", 240); pd.set_option("display.max_columns", 40)
TAG = "CYCLOPS_SIGNAL_VALIDATE_2026_06_15"; print(TAG, "OUTPUT START", flush=True)

from load import load_resolutions, load_klines_1s  # noqa

WIN = 300  # 5m
OFFSETS = [60, 90, 120, 180, 240]      # secs into window to evaluate the binance move
THRS = [3.0, 5.0, 8.0, 10.0]           # bps thresholds

# ---- resolutions: BTC/ETH 5m ----
res = load_resolutions()
res.columns = [c.lower() for c in res.columns]
print("res cols:", list(res.columns)[:20], flush=True)
slugcol = "slug" if "slug" in res.columns else [c for c in res.columns if "slug" in c][0]
res = res[res[slugcol].astype(str).str.contains("updown-5m", na=False)].copy()
res["asset"] = res[slugcol].astype(str).str.extract(r"^([a-z0-9]+)-updown")[0]
res = res[res["asset"].isin(["btc", "eth"])].copy()
res["slot_start"] = pd.to_numeric(res[slugcol].astype(str).str.extract(r"-(\d+)\Z")[0], errors="coerce")
res = res.dropna(subset=["slot_start"])
res["slot_start"] = res["slot_start"].astype(int)
# outcome -> Up/Down. find outcome col
outcol = next((c for c in ("outcome", "winner", "clob_winner", "result") if c in res.columns), None)
print("outcome col:", outcol, "sample:", res[outcol].dropna().unique()[:6] if outcol else None, flush=True)
print(f"BTC/ETH 5m resolutions: {len(res)}  range slot {res.slot_start.min()}..{res.slot_start.max()}", flush=True)


def up_flag(v):
    s = str(v).strip().lower()
    if s in ("up", "1", "true", "yes"):
        return 1
    if s in ("down", "0", "false", "no"):
        return 0
    return np.nan


res["won_up"] = res[outcol].map(up_flag)
res = res.dropna(subset=["won_up"])
res["won_up"] = res["won_up"].astype(int)

out = []
for asset in ("btc", "eth"):
    sub = res[res.asset == asset]
    if not len(sub):
        continue
    kl = load_klines_1s(asset.upper())  # canonical 1s
    kl.columns = [c.lower() for c in kl.columns]
    tcol = "time_period_start_us" if "time_period_start_us" in kl.columns else [c for c in kl.columns if c.endswith("_us")][0]
    ccol = "price_close" if "price_close" in kl.columns else ("close" if "close" in kl.columns else "price")
    k = kl[[tcol, ccol]].dropna().copy()
    k["sec"] = (k[tcol] // 1_000_000).astype(np.int64)
    k = k.drop_duplicates("sec").set_index("sec")[ccol].sort_index()
    kmin, kmax = int(k.index.min()), int(k.index.max())
    s2 = sub[(sub.slot_start >= kmin) & (sub.slot_start + WIN <= kmax)].copy()
    print(f"\n[{asset}] klines {ccol}@{tcol} secs {kmin}..{kmax}; slugs in range: {len(s2)}", flush=True)
    idx = k.index.values; vals = k.values

    def px(sec):
        i = np.searchsorted(idx, sec, side="right") - 1
        return vals[i] if i >= 0 else np.nan

    p_open = np.array([px(s) for s in s2.slot_start.values])
    p_close = np.array([px(s + WIN) for s in s2.slot_start.values])
    won_up = s2.won_up.values
    base_up = won_up.mean()
    for off in OFFSETS:
        p_off = np.array([px(s + off) for s in s2.slot_start.values])
        ret = (p_off / p_open - 1) * 1e4  # bps open->offset
        for thr in THRS:
            # fired: |ret|>=thr ; favorite = sign(ret); win if close finishes same dir
            up_fire = ret >= thr
            dn_fire = ret <= -thr
            fired = up_fire | dn_fire
            n = int(fired.sum())
            if n < 20:
                continue
            fav_up = up_fire  # among fired, favorite is Up where ret>=thr
            # win = favorite side matches realized outcome
            win = np.where(up_fire, won_up == 1, np.where(dn_fire, won_up == 0, False))
            wr = win[fired].mean()
            # EV at poly fav price 0.83 (winner-only fee 0.07*p*(1-p))
            p = 0.83
            fee = 0.07 * p * (1 - p)
            ev = wr * ((1 - p) * (1 - fee)) - (1 - wr) * p
            out.append(dict(asset=asset, off=off, thr=thr, n=n,
                            fire_rate=round(fired.mean(), 3), WR=round(wr * 100, 1),
                            base=round(base_up * 100, 1), EV_at_083=round(ev, 4)))

T = pd.DataFrame(out)
print("\n=== CONDITIONAL WR: P(close aligns | binance moved >=THR bps by offset) ===")
print("(WR = realized win-rate of the favorite the bot would buy; EV at poly price 0.83 incl winner-only fee)")
print(T.sort_values(["asset", "off", "thr"]).to_string(index=False))

print("\n=== READ ===")
for asset in ("btc", "eth"):
    a = T[T.asset == asset]
    if not len(a):
        continue
    best = a.loc[a.EV_at_083.idxmax()]
    print(f"[{asset}] best cell: off={best.off:.0f}s thr={best.thr:.0f}bps  n={best.n:.0f}  "
          f"WR={best.WR:.1f}%  EV@0.83={best.EV_at_083:+.4f}/share  (fire_rate={best.fire_rate:.2f})")
print("\nCyclops live 5d ref: median off~124s, |move|~7.6bps, WR 96.2% (n=26), entry 0.83.")
print(TAG, "OUTPUT END")
