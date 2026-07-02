"""PROFILE b27 HFT scalper + relay — FRESH 2026-06-16.
b27 buys; exits inventory via relay 0xf3cfb6a6 (per CLAUDE.md). b27 /activity alone
is buys-heavy -> hold-PnL misleading. Pull both wallets, lb-api realized, char both."""
from __future__ import annotations
import sys, io, json, time
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import pandas as pd, requests
pd.set_option("display.width", 220); pd.set_option("display.max_columns", 40)
DATA = "https://data-api.polymarket.com"; LB = "http://lb-api.polymarket.com"
UA = {"User-Agent": "gsl/1.0", "Accept": "application/json"}
NOW = int(time.time())
B27 = "0xb27bc932bf8110d8f78e55da7d5f0497a18b5b82"
RELAY = "0xf3cfb6a6"  # prefix only known; need full — try from cache
WALLETS = {"b27": B27}
print("PROFILE_B27_FRESH OUTPUT START", flush=True)


def g(u, p, t=4):
    for _ in range(t):
        try:
            r = requests.get(u, params=p, headers=UA, timeout=25)
            if r.status_code == 200:
                return r.json()
            time.sleep(.4)
        except Exception:
            time.sleep(.4)
    return None


# try to recover full relay address from cached alchemy_transfers
try:
    at = pd.read_parquet(r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\wallet_hunt\cache\0xf3cfb6a6\alchemy_transfers.parquet")
    print("relay cache cols:", list(at.columns)[:12])
except Exception as e:
    print("no relay cache:", e)


def profile(tag, addr, days=4):
    cut = NOW - days * 86400
    acts, off = [], 0
    while True:
        pg = g(f"{DATA}/activity", {"user": addr, "limit": 500, "offset": off})
        if not isinstance(pg, list) or not pg:
            break
        acts += pg
        if min(int(a.get("timestamp", 0)) for a in pg) < cut or len(pg) < 500:
            break
        off += 500; time.sleep(.2)
    print(f"\n########## {tag} {addr} ##########")
    if not acts:
        print("NO ACTIVITY (data-api). Maybe inactive or trades only on-chain via CLOB ops.")
    else:
        df = pd.DataFrame(acts)
        for c in ("price", "size", "usdcSize", "timestamp"):
            if c in df:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        df["type"] = df.get("type", "").astype(str).str.upper(); df["side"] = df.get("side", "").astype(str).str.upper()
        df["slug"] = df.get("slug", "").astype(str)
        df["dt"] = pd.to_datetime(df.timestamp, unit="s", utc=True)
        w = df[df.timestamp >= cut].copy()
        print(f"span {df.dt.min()} .. {df.dt.max()} | last {days}d events={len(w)} types={w['type'].value_counts().to_dict()}")
        w["asset"] = w["slug"].str.extract(r"^([a-z0-9]+)-updown")[0]
        w["tf"] = w["slug"].str.extract(r"-updown-(\d+[mh])-")[0]
        b = w[(w.type == "TRADE") & (w.side == "BUY")]; s = w[(w.type == "TRADE") & (w.side == "SELL")]; rd = w[w.type == "REDEEM"]
        bc = float(b.usdcSize.sum()); sp = float(s.usdcSize.sum()); rp = float(rd.usdcSize.sum())
        print(f"BUY={len(b)} ${bc:.0f}  SELL={len(s)} ${sp:.0f}  REDEEM={len(rd)} ${rp:.0f}  net_cash=${rp+sp-bc:+.0f}")
        if len(b):
            print("market mix (first token):", w["slug"].str.extract(r"^([a-z0-9]+)")[0].value_counts().head(8).to_dict())
            print(f"buy entry px median={b.price.median():.3f} p10={b.price.quantile(.1):.3f} p90={b.price.quantile(.9):.3f}")
            print(f"buy size median={b['size'].median():.2f} notional median=${b.usdcSize.median():.2f} max=${b.usdcSize.max():.0f}")
            print("buy outcome mix:", b.outcome.value_counts().head(6).to_dict() if "outcome" in b else "n/a")
            if len(s):
                print(f"sell entry px median={s.price.median():.3f}  (SELLS present -> exits on this wallet)")
            # offset into window
            b2 = b.copy(); b2["slot"] = pd.to_numeric(b2["slug"].str.extract(r"-(\d+)\Z")[0], errors="coerce")
            o = (b2.timestamp - b2["slot"]).dropna(); o = o[(o >= -10) & (o <= 3700)]
            if len(o):
                print(f"buy offset into window median={o.median():.0f}s p10={o.quantile(.1):.0f} p90={o.quantile(.9):.0f}")
    for wd in ("1d", "7d", "all"):
        lb = g(f"{LB}/profit", {"window": wd, "address": addr})
        amt = lb[0].get("amount") if (lb and isinstance(lb, list)) else None
        nm = lb[0].get("pseudonym") if (lb and isinstance(lb, list)) else None
        print(f"  lb /profit {wd}: amount={amt}  name={nm}")
    # volume/leaderboard
    for wd in ("1d", "7d"):
        v = g(f"{LB}/volume", {"window": wd, "address": addr})
        amt = v[0].get("amount") if (v and isinstance(v, list)) else None
        print(f"  lb /volume {wd}: ${amt}")


for tag, addr in WALLETS.items():
    profile(tag, addr, days=4)
print("PROFILE_B27_FRESH OUTPUT END")
