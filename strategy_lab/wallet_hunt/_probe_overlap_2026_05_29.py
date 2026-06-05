"""Probe market-type + canonical-window overlap for the 5 target wallets.
Canonical L25 covers BTC/ETH/SOL up-down 1m/5m/15m slugs, Apr 22 - May 29.
Up-down slug heuristic: eventSlug/slug contains 'up-or-down' OR title matches
'... Up or Down ...'; canonical suffix = trailing 10-digit unix epoch.
"""
import re, datetime as dt
import pandas as pd

BASE = r"strategy_lab/wallet_hunt/cache"
WALLETS = {
    "0fe40e88": "0x0fe40e88/trades.parquet",
    "4ee29e4e": "0x4ee29e4e/trades.parquet",
    "a42f127d": "0xa42f127d/trades.parquet",
    "eebde7a0": "0xeebde7a0/0xeebde7a0_trades.parquet",
}
WIN_LO = int(dt.datetime(2026, 4, 22, tzinfo=dt.timezone.utc).timestamp())
WIN_HI = int(dt.datetime(2026, 5, 29, 14, tzinfo=dt.timezone.utc).timestamp())

epoch_suffix = re.compile(r"-(\d{10})$")

def updown_mask(df):
    s = df["slug"].fillna("").str.lower()
    e = df.get("eventSlug", pd.Series([""]*len(df))).fillna("").str.lower()
    t = df.get("title", pd.Series([""]*len(df))).fillna("").str.lower()
    return (s.str.contains("up-or-down") | e.str.contains("up-or-down")
            | t.str.contains("up or down"))

for tag, rel in WALLETS.items():
    try:
        df = pd.read_parquet(BASE + "/" + rel)
    except Exception as ex:
        print(f"\n=== {tag}: LOAD FAIL {ex}"); continue
    ts = pd.to_numeric(df["timestamp"], errors="coerce")
    lo, hi = ts.min(), ts.max()
    def f(x):
        return dt.datetime.utcfromtimestamp(int(x)).strftime("%Y-%m-%d %H:%M") if pd.notna(x) else "NA"
    ud = updown_mask(df)
    in_win = ts.between(WIN_LO, WIN_HI)
    ud_win = ud & in_win
    # canonical epoch-suffix slugs
    has_suf = df["slug"].fillna("").str.contains(epoch_suffix)
    print(f"\n=== {tag}  n={len(df)}  range {f(lo)} -> {f(hi)} UTC")
    print(f"  up-down trades: {int(ud.sum())}  | up-down & in-window: {int(ud_win.sum())}  | epoch-suffix slugs: {int(has_suf.sum())}")
    # asset breakdown for up-down-in-window
    sub = df[ud_win]
    if len(sub):
        # infer asset from slug
        a = sub["slug"].str.extract(r"(bitcoin|ethereum|solana|btc|eth|sol)", expand=False).fillna("?")
        print("  ud-in-window asset mix:", a.value_counts().to_dict())
        print("  ud-in-window side mix:", sub["side"].value_counts().to_dict())
    # top non-up-down event types
    nonud = df[~ud]
    top_ev = nonud["eventSlug"].fillna("").str.replace(r"-\d+$", "", regex=True).value_counts().head(5)
    print("  top NON-up-down eventSlug roots:")
    for k, v in top_ev.items():
        print(f"     {v:5d}  {k[:60]}")
