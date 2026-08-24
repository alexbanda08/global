"""Extrai fills updown de cada wallet para parquet compacto."""
import json, re, os, sys
import pandas as pd

ROOT = r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/wallet_hunt/cache/_pm_portfolio"
OUT  = r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/wallet_hunt/_decode_2026_08_18"
SLUG = re.compile(r"^(btc|eth)-updown-(5m|15m)-(\d+)$")

WALLETS = {
    "PBot-6": ("0x21d0a97a", "activity_TRADE_2026_08_13.json", "activity_REDEEM_2026_08_13.json"),
    "PBot-2": ("0x095fd7cc", "activity_TRADE_2026_08_13.json", "activity_REDEEM_2026_08_13.json"),
    "PBot-3": ("0x74a2b82f", "activity_TRADE_2026_08_13.json", "activity_REDEEM_2026_08_13.json"),
    "PBot-5": ("0x1b58d3de", "activity_TRADE_2026_08_13.json", "activity_REDEEM_2026_08_13.json"),
    "b945":   ("0xb945945d", "activity_TRADE_2026_08_13.json", "activity_REDEEM_2026_08_13.json"),
    "b27":    ("0xb27bc932", "activity_TRADE_2026_08_13.json", "activity_REDEEM_2026_08_13.json"),
}

for name, (short, tf_file, rf_file) in WALLETS.items():
    p = os.path.join(ROOT, short, tf_file)
    if not os.path.exists(p):
        print(f"SKIP {name}: no {p}"); continue
    trades = json.load(open(p))
    rows = []
    for t in trades:
        m = SLUG.match(t.get("slug") or "")
        if not m: continue
        oc = t.get("outcome")
        if oc not in ("Up", "Down"): continue
        slot = int(m.group(3))
        rows.append((t["timestamp"], slot, m.group(1), m.group(2), oc,
                     t.get("side"), float(t["size"]), float(t["usdcSize"]),
                     float(t["price"]), t.get("conditionId"), t.get("asset"), t.get("slug")))
    df = pd.DataFrame(rows, columns=["ts","slot","coin","tf","outcome","side","sh","usd","px","cond","asset","slug"])
    df["wl"] = df.tf.map({"5m":300, "15m":900})
    df["dt"] = df.ts - df.slot                     # segundos relativos a abertura
    df["frac"] = df.dt / df.wl                     # 0..1 dentro da janela
    df.to_parquet(os.path.join(OUT, f"fills_{name}.parquet"))

    reds = json.load(open(os.path.join(ROOT, short, rf_file)))
    rr = []
    for r in reds:
        m = SLUG.match(r.get("slug") or "")
        if not m: continue
        rr.append((r["timestamp"], int(m.group(3)), m.group(1), m.group(2), r.get("outcome"),
                   float(r.get("size") or 0), float(r.get("usdcSize") or 0), r.get("conditionId"), r.get("slug")))
    rd = pd.DataFrame(rr, columns=["ts","slot","coin","tf","outcome","sh","usd","cond","slug"])
    rd.to_parquet(os.path.join(OUT, f"redeems_{name}.parquet"))
    print(f"{name:8s} fills={len(df):7d} ({df.ts.min()}..{df.ts.max()})  redeems={len(rd):7d}  "
          f"sides={df.side.value_counts().to_dict()}")
