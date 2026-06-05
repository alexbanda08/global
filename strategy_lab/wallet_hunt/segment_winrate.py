"""
Per-segment directional WIN-RATE for Up/Down wallets.

Goal: find wallets (or specific market segments of a wallet) that trade BTC/ETH/SOL
up-down DIRECTIONALLY with a high hit rate. We don't care about total profit — we
care about WR per (asset, timeframe). A wallet that is 60% overall but 70% on
btc-5m is a crack target for that one segment.

Method (no chain pull needed — data-api /trades carries canonical slug + outcome):
  1. Load each wallet's data-api trades (cached cache/<short>/trades.parquet, else fetch).
  2. Keep updown slugs only -> parse (asset, tf, slot_start_s) from canonical slug
     "{asset}-updown-{tf}-{slot_start_s}".
  3. Per (slug, outcome): net_qty = sum(BUY size) - sum(SELL size), notion-weighted avg buy px.
  4. A slug is DIRECTIONAL if the wallet ends net-long on exactly ONE outcome
     (the other side's net <= DUST). Paired / mint-and-sell slugs (net-long both, or
     net-flat via offsetting buy+sell) are excluded from WR (not directional bets).
  5. Join canonical resolutions by slug -> winner (Up/Down). WIN = held side == winner.
  6. Aggregate per (wallet, asset, tf): n_dir_resolved, n_win, WR, net_pnl_est, avg_px.
     Flag cells with n >= MIN_N and WR >= WR_FLAG.

PnL est per directional slug (hold-to-resolution, no fees):
    win  -> + net_qty * (1 - avg_buy_px)
    lose -> - net_qty * avg_buy_px
(approx; ignores any partial pre-resolution exits beyond the net. Good enough to rank.)

Usage:
    py -3 strategy_lab/wallet_hunt/segment_winrate.py --wallets 0x.. 0x..
    py -3 strategy_lab/wallet_hunt/segment_winrate.py --from-classification   # auto-pull updown-focused
    py -3 strategy_lab/wallet_hunt/segment_winrate.py --wallets 0x.. --min-n 30 --wr-flag 0.65 --fetch
"""
from __future__ import annotations
import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
from load import load_resolutions  # noqa: E402

CACHE = Path(__file__).resolve().parent / "cache"
DATA_API = "https://data-api.polymarket.com"
UA = {"User-Agent": "global-strategy-lab/1.0", "Accept": "application/json"}

# canonical updown slug: btc-updown-5m-1778910300
SLUG_RE = re.compile(r"^([a-z0-9]+)-updown-(\d+[mh])-(\d+)$", re.I)

DUST = 1.0  # shares; net position below this on the "other" side = treat as one-sided


# --------------------------------------------------------------------------- fetch
def _get(url: str, timeout: int = 20):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_trades(wallet: str, page_size: int = 500, max_pages: int = 60,
                 sleep_s: float = 0.1) -> pd.DataFrame:
    """Page data-api /trades via offset, then walk back via end_time past the 3500 cap."""
    w = wallet.lower()
    rows: list[dict] = []
    for param in ("user", "proxyWallet"):
        offset = 0
        page = 0
        while page < max_pages:
            url = f"{DATA_API}/trades?{param}={w}&limit={page_size}&offset={offset}"
            try:
                batch = _get(url)
            except Exception:
                break
            if not batch:
                break
            rows.extend(batch)
            page += 1
            if len(batch) < page_size:
                break
            offset += page_size
            time.sleep(sleep_s)
        if rows:
            break  # found data with this param
    if rows and len(rows) >= 3000:
        seen = {(r.get("transactionHash"), r.get("asset"), r.get("timestamp")) for r in rows}
        end_ts = min(int(r["timestamp"]) for r in rows if r.get("timestamp"))
        guard = 0
        while guard < max_pages:
            url = f"{DATA_API}/trades?user={w}&limit={page_size}&offset=0&end_time={end_ts}"
            try:
                batch = _get(url)
            except Exception:
                break
            if not batch:
                break
            new = [r for r in batch
                   if (r.get("transactionHash"), r.get("asset"), r.get("timestamp")) not in seen]
            for r in new:
                seen.add((r.get("transactionHash"), r.get("asset"), r.get("timestamp")))
            guard += 1
            if not new:
                end_ts -= 1
                continue
            rows.extend(new)
            end_ts = min(int(r["timestamp"]) for r in new)
            if len(batch) < page_size:
                break
            time.sleep(sleep_s)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    if "transactionHash" in df.columns:
        df = df.drop_duplicates(subset=["transactionHash", "asset", "timestamp"])
    return df


def load_wallet_trades(wallet: str, fetch: bool) -> pd.DataFrame:
    short = wallet.lower()[:10]
    fp = CACHE / short / "trades.parquet"
    if fp.exists() and not fetch:
        return pd.read_parquet(fp)
    df = fetch_trades(wallet)
    if not df.empty:
        (CACHE / short).mkdir(parents=True, exist_ok=True)
        df.to_parquet(fp, index=False)
    return df


# --------------------------------------------------------------------------- core
def parse_slug(slug: str):
    m = SLUG_RE.match(str(slug))
    if not m:
        return None, None, None
    return m.group(1).lower(), m.group(2).lower(), int(m.group(3))


def per_slug_positions(trades: pd.DataFrame) -> pd.DataFrame:
    """One row per (slug, outcome): net qty + size-weighted avg buy/sell px."""
    df = trades.copy()
    df["slug"] = df["slug"].astype(str)
    df["outcome"] = df["outcome"].astype(str)
    df["side"] = df["side"].astype(str).str.upper()
    df["size"] = pd.to_numeric(df["size"], errors="coerce").fillna(0.0)
    df["price"] = pd.to_numeric(df["price"], errors="coerce")

    parsed = df["slug"].apply(parse_slug)
    df["asset"] = parsed.apply(lambda x: x[0])
    df["tf"] = parsed.apply(lambda x: x[1])
    df = df[df["asset"].notna()].copy()  # updown only
    if df.empty:
        return df

    df["buy_sz"] = np.where(df["side"] == "BUY", df["size"], 0.0)
    df["sell_sz"] = np.where(df["side"] == "SELL", df["size"], 0.0)
    df["buy_notional"] = df["buy_sz"] * df["price"]
    df["sell_notional"] = df["sell_sz"] * df["price"]

    g = df.groupby(["slug", "asset", "tf", "outcome"], as_index=False).agg(
        buy_sz=("buy_sz", "sum"),
        sell_sz=("sell_sz", "sum"),
        buy_notional=("buy_notional", "sum"),
        sell_notional=("sell_notional", "sum"),
        n_trades=("size", "count"),
    )
    g["net_qty"] = g["buy_sz"] - g["sell_sz"]
    g["avg_buy_px"] = np.where(g["buy_sz"] > 0, g["buy_notional"] / g["buy_sz"], np.nan)
    return g


def directional_bets(pos: pd.DataFrame) -> pd.DataFrame:
    """Collapse per-slug to a single directional bet, or drop if not one-sided.

    Held side = outcome with the larger positive net_qty. Slug is directional iff
    exactly one outcome has net_qty > DUST (the other side net <= DUST).
    """
    out = []
    for slug, grp in pos.groupby("slug"):
        longs = grp[grp["net_qty"] > DUST]
        if len(longs) != 1:
            continue  # net-flat, or net-long both sides (paired/arb) -> not directional
        row = longs.iloc[0]
        out.append({
            "slug": slug,
            "asset": row["asset"],
            "tf": row["tf"],
            "held_side": row["outcome"],
            "net_qty": float(row["net_qty"]),
            "avg_buy_px": float(row["avg_buy_px"]),
            "n_trades": int(grp["n_trades"].sum()),
        })
    return pd.DataFrame(out)


def attach_outcomes(bets: pd.DataFrame, res: pd.DataFrame) -> pd.DataFrame:
    win = res[["slug", "outcome"]].rename(columns={"outcome": "winner"})
    m = bets.merge(win, on="slug", how="inner")  # inner = resolved only
    m["won"] = m["held_side"].str.lower() == m["winner"].str.lower()
    m["pnl"] = np.where(
        m["won"],
        m["net_qty"] * (1.0 - m["avg_buy_px"]),
        -m["net_qty"] * m["avg_buy_px"],
    )
    return m


def aggregate(m: pd.DataFrame, wallet: str) -> pd.DataFrame:
    if m.empty:
        return pd.DataFrame()
    seg = m.groupby(["asset", "tf"], as_index=False).agg(
        n=("won", "count"),
        n_win=("won", "sum"),
        net_pnl=("pnl", "sum"),
        avg_px=("avg_buy_px", "mean"),
        avg_qty=("net_qty", "mean"),
        up_bias=("held_side", lambda s: (s.str.lower() == "up").mean()),
    )
    seg["wr"] = seg["n_win"] / seg["n"]
    seg["pnl_per_bet"] = seg["net_pnl"] / seg["n"]
    seg.insert(0, "wallet", wallet.lower()[:10])
    # overall row
    overall = pd.DataFrame([{
        "wallet": wallet.lower()[:10], "asset": "ALL", "tf": "ALL",
        "n": len(m), "n_win": int(m["won"].sum()),
        "net_pnl": float(m["pnl"].sum()), "avg_px": float(m["avg_buy_px"].mean()),
        "avg_qty": float(m["net_qty"].mean()),
        "up_bias": float((m["held_side"].str.lower() == "up").mean()),
        "wr": float(m["won"].mean()), "pnl_per_bet": float(m["pnl"].mean()),
    }])
    return pd.concat([overall, seg], ignore_index=True)


# --------------------------------------------------------------------------- main
def candidate_wallets_from_classification() -> list[str]:
    fp = CACHE / "_lb_new_wallet_classification.csv"
    if not fp.exists():
        return []
    df = pd.read_csv(fp)
    ud = df[df["verdict"].isin(["UPDOWN_FOCUSED", "UPDOWN_MIXED"])]
    return ud["proxy_wallet"].dropna().astype(str).tolist()


def candidate_wallets_from_harvest(top_n: int = 300, min_trades: int = 40, max_trades: int = 8000) -> list[str]:
    """New wallets from market-level harvest, ranked by activity. Excludes mega-makers."""
    fp = CACHE / "_harvest_wallets.csv"
    if not fp.exists():
        return []
    df = pd.read_csv(fp)
    if "is_new" in df.columns:
        df = df[df["is_new"]]
    df = df[(df["n_trades_seen"] >= min_trades) & (df["n_trades_seen"] <= max_trades)]
    df = df.sort_values("n_trades_seen", ascending=False).head(top_n)
    return df["wallet"].dropna().astype(str).tolist()


def candidate_wallets_from_counterparties(top_n: int = 100) -> list[str]:
    """Counterparties that crossed our known directional updown wallets = updown participants."""
    fp = CACHE / "_lb_counterparties_scored.csv"
    if not fp.exists():
        return []
    df = pd.read_csv(fp)
    if "in_known_set" in df.columns:
        df = df[~df["in_known_set"].fillna(False)]
    df = df.sort_values("total_crosses", ascending=False).head(top_n)
    return df["counterparty"].dropna().astype(str).tolist()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wallets", nargs="+", default=None)
    ap.add_argument("--from-classification", action="store_true",
                    help="use updown-focused wallets from _lb_new_wallet_classification.csv")
    ap.add_argument("--from-counterparties", action="store_true",
                    help="use counterparties of known updown wallets from _lb_counterparties_scored.csv")
    ap.add_argument("--from-harvest", action="store_true",
                    help="use new wallets from market-level harvest (_harvest_wallets.csv)")
    ap.add_argument("--top-n", type=int, default=100, help="top-N counterparties/harvest by activity")
    ap.add_argument("--fetch", action="store_true", help="force re-fetch from data-api")
    ap.add_argument("--min-n", type=int, default=20, help="min resolved directional bets per segment to flag")
    ap.add_argument("--wr-flag", type=float, default=0.65, help="WR threshold to flag a segment")
    ap.add_argument("--out", default=str(CACHE / "_segment_winrate.csv"))
    args = ap.parse_args()

    wallets = list(args.wallets or [])
    if args.from_classification:
        wallets += candidate_wallets_from_classification()
    if args.from_counterparties:
        wallets += candidate_wallets_from_counterparties(args.top_n)
    if args.from_harvest:
        wallets += candidate_wallets_from_harvest(args.top_n)
    wallets = list(dict.fromkeys(w.lower() for w in wallets))  # dedup, preserve order
    if not wallets:
        print("No wallets. Pass --wallets or --from-classification.")
        return

    print(f"Loading canonical resolutions...")
    res = load_resolutions()[["slug", "outcome"]].dropna()
    res = res.drop_duplicates(subset=["slug"])
    print(f"  {len(res):,} resolved updown markets, window via slug suffix")

    all_rows = []
    for w in wallets:
        try:
            tr = load_wallet_trades(w, fetch=args.fetch)
        except Exception as e:
            print(f"  {w[:10]}: fetch ERROR {e}")
            continue
        if tr.empty or "slug" not in tr.columns:
            print(f"  {w[:10]}: no trades")
            continue
        pos = per_slug_positions(tr)
        if pos.empty:
            print(f"  {w[:10]}: no updown trades ({len(tr)} total)")
            continue
        bets = directional_bets(pos)
        n_slugs = pos["slug"].nunique()
        if bets.empty:
            print(f"  {w[:10]}: {n_slugs} updown slugs, 0 directional (all paired/flat)")
            continue
        m = attach_outcomes(bets, res)
        agg = aggregate(m, w)
        if agg.empty:
            print(f"  {w[:10]}: {len(bets)} directional bets, 0 resolved in window")
            continue
        dir_pct = len(bets) / n_slugs * 100
        ov = agg[agg["asset"] == "ALL"].iloc[0]
        print(f"  {w[:10]}: {n_slugs} slugs, {len(bets)} directional ({dir_pct:.0f}%), "
              f"{int(ov['n'])} resolved, overall WR {ov['wr']*100:.1f}%")
        all_rows.append(agg)

    if not all_rows:
        print("\nNo results.")
        return

    full = pd.concat(all_rows, ignore_index=True)
    full = full.sort_values(["wallet", "wr"], ascending=[True, False])
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    full.to_csv(args.out, index=False)

    # FLAGGED: high-WR segments with enough sample
    flagged = full[(full["n"] >= args.min_n) & (full["wr"] >= args.wr_flag)
                   & ~((full["asset"] == "ALL"))]
    flagged = flagged.sort_values("wr", ascending=False)

    print("\n" + "=" * 90)
    print(f"FLAGGED SEGMENTS  (n >= {args.min_n}, WR >= {args.wr_flag:.0%})  — crack targets")
    print("=" * 90)
    if flagged.empty:
        print("  none")
    else:
        show = flagged[["wallet", "asset", "tf", "n", "n_win", "wr", "pnl_per_bet",
                        "net_pnl", "avg_px", "avg_qty", "up_bias"]].copy()
        show["wr"] = (show["wr"] * 100).round(1)
        show["up_bias"] = (show["up_bias"] * 100).round(0)
        for c in ["pnl_per_bet", "net_pnl", "avg_px", "avg_qty"]:
            show[c] = show[c].round(3)
        print(show.to_string(index=False))

    print(f"\nFull table -> {args.out}  ({len(full)} wallet-segment rows)")


if __name__ == "__main__":
    main()
