"""
TV CARDS FEED  — produce the exact dashboard payload for the 6 HL shadow cards.

The production TV dashboard shows "SHADOW (6)": 5 per-coin V52 bundles + 1 XSM.
Each per-coin card BUNDLES the sleeves on that coin and shows a card-level
SIGNAL (FLAT/LONG/SHORT) + CONFIDENCE (0-100) + recent activity.

This producer reads my local shadow outputs and emits `_tv_cards_feed.json` in
the dashboard's card shape. It is BOTH:
  (a) the concrete target schema the VPS3 TV agent should reproduce, and
  (b) a working reference producer (port its aggregation logic into the engine).

Card-level aggregation (per coin bundle):
  - net = sum(weight_i * dir_i) over sleeves currently OPEN (dir +1 long / -1 short)
  - SIGNAL = LONG if net>0, SHORT if net<0, else FLAT
  - CONFIDENCE = round(100 * |net| / sum(weight_i over bundle))   # 0-100
    (i.e. how much of the bundle's weight is aligned + open)
  - if a PENDING fire exists on the just-closed bar, SIGNAL reflects it (the
    action the bot will take at next open) and CONFIDENCE uses that sleeve's weight.

Run:  py shadow_v52/tv_cards_feed.py
"""
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime, timezone
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "shadow_v52"

# per-coin card -> sleeves in its bundle (+ each sleeve's V52 weight)
CARDS = {
    "V52-BTC":  [("STF_BTC", 0.12)],
    "V52-ETH":  [("CCI_ETH", 0.12), ("MFI_ETH", 0.10)],
    "V52-SOL":  [("STF_SOL", 0.12), ("MFI_SOL", 0.10)],
    "V52-AVAX": [("STF_AVAX", 0.12), ("LATBB_AVAX", 0.12), ("SVD_AVAX", 0.10)],
    "V52-LINK": [("VP_LINK", 0.10)],
}
COIN_OF = {"V52-BTC": "BTC", "V52-ETH": "ETH", "V52-SOL": "SOL", "V52-AVAX": "AVAX", "V52-LINK": "LINK"}


def _load(name):
    """Read a shadow CSV, tolerating the empty case.

    pd.read_csv raises EmptyDataError ("No columns to parse from file") on a
    zero-byte or header-less file. pending_fires_latest.csv is empty whenever no
    sleeve fired on the last closed bar — i.e. most runs — which crashed this
    whole feed and left _tv_cards_feed.json stale. Treat empty as no rows.
    """
    p = OUT / name
    if not p.exists() or p.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(p)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def build_feed():
    now = datetime.now(timezone.utc).isoformat()
    positions = _load("positions_latest.csv")
    pending = _load("pending_fires_latest.csv")
    ledger = _load("fires_ledger.csv")
    xsm = _load("xsm_status.csv")

    pos_by_sleeve = {r["sleeve"]: r for _, r in positions.iterrows()} if len(positions) else {}
    pend_by_sleeve = {r["sleeve"]: r for _, r in pending.iterrows()} if len(pending) else {}

    cards = []
    for card_name, bundle in CARDS.items():
        total_w = sum(w for _, w in bundle)
        net = 0.0
        open_sleeves = []
        pending_sleeves = []
        for sleeve, w in bundle:
            pr = pos_by_sleeve.get(sleeve, {})
            state = pr.get("state", "FLAT")
            if state == "OPEN":
                d = 1 if str(pr.get("direction")) == "LONG" else -1
                net += w * d
                open_sleeves.append(dict(sleeve=sleeve, direction=pr.get("direction"),
                                         entry_ts=pr.get("entry_ts"), entry_price=pr.get("entry_price"),
                                         unrealized_pct=pr.get("unrealized_pct"), weight=w))
            pf = pend_by_sleeve.get(sleeve)
            if pf is not None:
                pending_sleeves.append(dict(sleeve=sleeve, direction=pf.get("direction"),
                                            signal_bar_ts=pf.get("signal_bar_ts"), weight=w))

        # card signal: prefer pending (next action), else open net
        if pending_sleeves:
            pnet = sum((1 if p["direction"] == "LONG" else -1) * p["weight"] for p in pending_sleeves)
            sig = "LONG" if pnet > 0 else "SHORT" if pnet < 0 else "FLAT"
            conf = round(100 * abs(pnet) / total_w) if total_w else 0
        elif net != 0:
            sig = "LONG" if net > 0 else "SHORT"
            conf = round(100 * abs(net) / total_w) if total_w else 0
        else:
            sig, conf = "FLAT", 0

        # recent fires for this card's sleeves
        rf = []
        if len(ledger):
            sub = ledger[ledger["sleeve"].isin([s for s, _ in bundle])]
            sub = sub.sort_values("entry_ts", ascending=False).head(5)
            for _, r in sub.iterrows():
                rf.append(dict(sleeve=r["sleeve"], dir=r["direction"], entry_ts=r["entry_ts"],
                               exit_ts=r.get("exit_ts"), reason=r.get("reason"),
                               ret_pct=r.get("ret_pct"), paper_pnl=r.get("paper_pnl_usd")))
        last_fire = max((r["entry_ts"] for r in rf), default=None)
        n_fires = int(len(ledger[ledger["sleeve"].isin([s for s, _ in bundle])])) if len(ledger) else 0
        data_end = pos_by_sleeve.get(bundle[0][0], {}).get("data_end")

        cards.append(dict(
            card=card_name, fleet="V52", venue="hyperliquid_perp", coin=COIN_OF[card_name], tf="4h",
            bundle=[s for s, _ in bundle],
            signal=sig, confidence=conf,
            open_positions=open_sleeves, pending=pending_sleeves,
            n_fires=n_fires, last_fire=last_fire, recent_fires=rf,
            data_end=data_end,
        ))

    # XSM card
    xrow = xsm.iloc[-1].to_dict() if len(xsm) else {}
    xstate = xrow.get("status", "n/a")
    cards.append(dict(
        card="V52-XSM", fleet="XSM", venue="hyperliquid_perp", coin="9-coin-basket", tf="4h",
        bundle=["V24_multifilter"],
        signal="LONG" if xstate == "ACTIVE" else "FLAT",
        confidence=100 if xstate == "ACTIVE" else 0,
        filter_state=xstate,
        breadth=xrow.get("breadth"),
        btc_above_100dma=xrow.get("btc_above_100dma"),
        btc_50dma_rising=xrow.get("btc_50dma_rising"),
        target_basket=xrow.get("target_basket", "FLAT"),
        note="0% live allocation; only 5/9 coins HL-tradeable",
    ))

    feed = dict(generated=now, mode="shadow_paper", n_cards=len(cards), cards=cards)
    (OUT / "_tv_cards_feed.json").write_text(json.dumps(feed, indent=2, default=str), encoding="utf-8")
    return feed


def main():
    feed = build_feed()
    print(f"TV cards feed -> {OUT / '_tv_cards_feed.json'}  ({feed['n_cards']} cards)")
    for c in feed["cards"]:
        extra = f"breadth {c.get('breadth')}" if c["fleet"] == "XSM" else f"conf {c['confidence']} | fires {c.get('n_fires')}"
        print(f"  {c['card']:9s} {c['signal']:5s}  {extra}")


if __name__ == "__main__":
    main()
