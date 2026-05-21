"""Diagnose btc_15m_v2 and btc_5m_v2 momo for signal-inversion bug."""
import json
import pandas as pd
import numpy as np

ev = pd.read_csv('strategy_lab/markov_filter/_vps3_pull/post_f7_events.csv')
ev["at"] = pd.to_datetime(ev["at"], utc=True, format="mixed")

def diagnose(pattern: str, label: str):
    print(f"\n{'='*70}")
    print(f"DIAGNOSE: {label}  (pattern={pattern})")
    print(f"{'='*70}")
    res = ev[(ev["kind"] == "poly_updown_resolution") &
             ev["sleeve_id"].str.contains(pattern, na=False)].copy()
    rows = []
    for _, r in res.iterrows():
        try: d = json.loads(r["data"])
        except: continue
        d["sleeve_id"] = r["sleeve_id"]
        d["at"] = r["at"]
        rows.append(d)
    df = pd.DataFrame(rows)
    df["pnl_usd"] = pd.to_numeric(df["pnl_usd"], errors="coerce")
    df["entry_price"] = pd.to_numeric(df["entry_price"], errors="coerce")
    df["strike_price"] = pd.to_numeric(df["strike_price"], errors="coerce")
    df["settlement_price"] = pd.to_numeric(df["settlement_price"], errors="coerce")
    df["is_f7"] = df["sleeve_id"].str.endswith("_f7")

    print(f"\nTotal resolutions: {len(df)}")
    if len(df) == 0:
        print("NO DATA"); return

    f7 = df[df.is_f7]
    nf = df[~df.is_f7]
    print(f"  F7:    n={len(f7)}, WR={f7.won.mean()*100:.2f}%, $/trade=${f7.pnl_usd.mean():.2f}, sum=${f7.pnl_usd.sum():.2f}")
    print(f"  no_F7: n={len(nf)}, WR={nf.won.mean()*100:.2f}%, $/trade=${nf.pnl_usd.mean():.2f}, sum=${nf.pnl_usd.sum():.2f}")

    print(f"\nSignal vs outcome cross-tab (F7 fires):")
    print(pd.crosstab(f7["signal"], f7["outcome"], margins=True))

    print(f"\nSignal vs outcome cross-tab (no-F7 fires):")
    print(pd.crosstab(nf["signal"], nf["outcome"], margins=True))

    # Inversion test
    def inv_sig(s):
        if s == "UP": return "DOWN"
        if s == "DOWN": return "UP"
        return s
    for is_f7_val, lbl in [(True, "F7"), (False, "no_F7")]:
        sub = df[df.is_f7 == is_f7_val].copy()
        clean = sub[sub.outcome.isin(["Up","Down"])].copy()
        if clean.empty:
            print(f"\n  {lbl}: no clean resolutions"); continue
        clean["sig_inv"] = clean.signal.apply(inv_sig)
        clean["won_inv"] = (((clean.sig_inv == "UP") & (clean.outcome == "Up")) |
                            ((clean.sig_inv == "DOWN") & (clean.outcome == "Down")))
        wr_inv = clean.won_inv.mean() * 100
        wr_orig = clean.won.mean() * 100
        print(f"\n  {lbl} INVERSION TEST (clean rows n={len(clean)}):")
        print(f"    original WR:  {wr_orig:.2f}%")
        print(f"    inverted WR:  {wr_inv:.2f}%  ← {'CRITICAL — invert' if wr_inv > 70 else 'no clean inversion'}")
        if wr_inv > 70:
            # Approx PnL: $25 stake, 49 shares at ~0.5, fee ~$0.86
            approx_inv_sum = clean.won_inv.sum() * 23.10 + (~clean.won_inv).sum() * (-25.86)
            print(f"    approx inverted sum PnL: ${approx_inv_sum:+.2f}")

    # Time pattern
    print(f"\nHour-of-day pattern (F7 fires only):")
    f7_copy = f7.copy()
    f7_copy["hour"] = f7_copy["at"].dt.hour
    print(f7_copy.groupby("hour").agg(n=("won","size"), wr=("won","mean"), sum=("pnl_usd","sum")).round(3).to_string())


diagnose("btc_15m_momo_v2", "btc_15m momo_v2")
diagnose("btc_5m_momo_v2", "btc_5m momo_v2")
diagnose("eth_5m_momo_v2", "eth_5m momo_v2 (for comparison)")
diagnose("btc_15m_momo(?!_v2)", "btc_15m momo_v1 (control)")
