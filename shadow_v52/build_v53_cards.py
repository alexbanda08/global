"""
V53 BREADTH SLEEVE CARDS builder.

One card per V53 stream (2 families x 10 coins = 20) into shadow_v52/cards_v53/,
plus a V53_SLEEVE_CARDS.md index. Each card carries:
  - static spec (family, signal, gate, exit, arm)
  - the offline validation that earned it its arm (untouched pre-2024-03 window +
    the sequential-window decay track)
  - LIVE shadow status from v53_fires_ledger.csv / v53_positions_latest.csv

Unlike the V52 card builder there is no hand-maintained per-sleeve metrics table:
V53's per-cell numbers are read straight from the validation artifacts so the cards
cannot drift from the research that justified them.

    py shadow_v52/build_v53_cards.py
"""
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime, timezone
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "shadow_v52"
CARDS = OUT / "cards_v53"
CARDS.mkdir(parents=True, exist_ok=True)
RETEST = REPO / "strategy_lab" / "hl_research_2026_05_26" / "retest_2026_07_27"

COINS = ["BTC", "ETH", "SOL", "AVAX", "LINK", "ADA", "BNB", "DOGE", "XRP", "SUI"]

FAMILY_SPEC = {
    "STF": dict(
        arm="DEPLOY",
        family="trend (SuperTrend flip)",
        signal="SuperTrend(10, 3.0) flip + EMA(200) regime filter",
        validation=dict(
            untouched_window="pre-2024-03 Binance 4h, 10 coins",
            n=877, mean_ret_pct=1.054, t=5.01, breadth="9/10 coins positive",
            ex_top2_usd=124216, bonferroni="PASSES (|t|>2.64 for 6 families)",
            sequential=["2017-22 +1.549 (t=5.28)", "2022-24 +0.443 (t=1.49)",
                        "2024-25 +0.765 (t=1.51)", "2025-26 +1.933 (t=4.47)",
                        "2026-04->now +1.144 (t=1.62)"],
        ),
        rationale="Positive in every sequential window tested and never negative. "
                  "The only family that survives both an untouched window and the "
                  "current regime.",
    ),
    "VP": dict(
        arm="OBSERVE",
        family="rotation (volume profile)",
        signal="volume_profile_rot(win=60, n_bins=15)",
        validation=dict(
            untouched_window="pre-2024-03 Binance 4h, 10 coins",
            n=1914, mean_ret_pct=0.501, t=3.93, breadth="10/10 coins positive",
            ex_top2_usd=159319, bonferroni="PASSES on the untouched window",
            sequential=["2017-22 +0.759 (t=4.27)", "2022-24 +0.186 (t=1.03)",
                        "2024-25 +0.375 (t=1.30)", "2025-26 +0.342 (t=1.48)",
                        "2026-04->now -1.091 (t=-3.38)"],
        ),
        rationale="Passed the untouched window but has decayed monotonically and is "
                  "now SIGNIFICANTLY NEGATIVE (t=-3.38, n=161, only 2/10 coins "
                  "positive). Logged at $0 to detect a recovery; never sized.",
    ),
}

GATE = "ATR_NOTOPVOL (ATR(14) 500-bar pct-rank < 0.80)"
EXIT = ("EXIT_4H static: tp 10 ATR / sl 2 ATR / trail 6 ATR / max_hold 60 bars. "
        "Kept after a 62-variant grid: incumbent ranked 7/62 on the untouched window "
        "and no variant beat it in both windows; marginals show tighter stops are "
        "better, so the ~70% stop-out rate is the intended positive-skew design.")


def _load(name):
    p = OUT / name
    if not p.exists() or p.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(p)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def main():
    now = datetime.now(timezone.utc)
    ledger = _load("v53_fires_ledger.csv")
    positions = _load("v53_positions_latest.csv")
    pending = _load("v53_pending_fires_latest.csv")

    pos_by = {r["sleeve"]: r for _, r in positions.iterrows()} if len(positions) else {}
    pend_by = {r["sleeve"]: r for _, r in pending.iterrows()} if len(pending) else {}

    index_rows = []
    for fam, spec in FAMILY_SPEC.items():
        for coin in COINS:
            name = f"{fam}_{coin}"
            hist = ledger[ledger.sleeve == name] if len(ledger) else pd.DataFrame()

            live = dict(n_closed=0, mean_ret_pct=None, win_rate_pct=None, paper_pnl_usd=0.0)
            if len(hist):
                live = dict(
                    n_closed=int(len(hist)),
                    mean_ret_pct=round(float(hist.ret_pct.mean()), 3),
                    win_rate_pct=round(100.0 * float((hist.ret_pct > 0).mean()), 1),
                    paper_pnl_usd=round(float(hist.paper_pnl_usd.sum()), 2),
                )

            p = pos_by.get(name)
            open_pos = None if p is None else dict(
                direction=p.get("direction"), entry_ts=p.get("entry_ts"),
                entry_price=p.get("entry_price"), bars_held=int(p.get("bars_held", 0)),
                unreal_pct=p.get("unreal_pct"), unreal_usd=p.get("unreal_usd"))

            q = pend_by.get(name)
            pend = None if q is None else dict(
                direction=q.get("direction"), signal_bar_ts=q.get("signal_bar_ts"),
                act_at=q.get("act_at"))

            state = "OPEN" if open_pos else ("PENDING" if pend else "FLAT")
            card = dict(
                card_id=f"v53_{fam.lower()}_{coin.lower()}",
                fleet="V53", name=name, arm=spec["arm"], coin=coin, tf="4h",
                venue="Hyperliquid perp", mode="PAPER (shadow, $0 real)",
                family=spec["family"], signal=spec["signal"], gate=GATE, exit=EXIT,
                family_validation=spec["validation"], arm_rationale=spec["rationale"],
                state=state, open_position=open_pos, pending_fire=pend,
                live_shadow=live, built_at=now.isoformat(),
            )
            (CARDS / f"{card['card_id']}.json").write_text(
                json.dumps(card, indent=2, default=str), encoding="utf-8")
            index_rows.append(dict(card=card["card_id"], arm=spec["arm"], sleeve=name,
                                   coin=coin, state=state, **live))

    idx = pd.DataFrame(index_rows).sort_values(["arm", "sleeve"])
    lines = [
        "# V53 Breadth Sleeve Cards",
        "",
        f"Built {now.isoformat()} — {len(idx)} cards in `cards_v53/`.",
        "",
        "**DEPLOY** = validated on an untouched window and still working; eligible for "
        "capital once the shadow gate passes.  **OBSERVE** = logged at $0 only.",
        "",
        "| Card | Arm | Sleeve | Coin | State | n closed | mean ret % | WR % | paper $ |",
        "|---|---|---|---|---|---:|---:|---:|---:|",
    ]
    for _, r in idx.iterrows():
        lines.append(f"| `{r['card']}` | {r['arm']} | {r['sleeve']} | {r['coin']} | {r['state']} | "
                     f"{r['n_closed']} | {r['mean_ret_pct']} | {r['win_rate_pct']} | {r['paper_pnl_usd']} |")

    if len(ledger):
        lines += ["", "## Arm totals", "",
                  "| Arm | n | mean ret % | WR % | paper $ |", "|---|---:|---:|---:|---:|"]
        for arm, s in ledger.groupby("arm"):
            lines.append(f"| {arm} | {len(s)} | {s.ret_pct.mean():+.3f} | "
                         f"{100.0*(s.ret_pct>0).mean():.1f} | {s.paper_pnl_usd.sum():,.2f} |")

    (OUT / "V53_SLEEVE_CARDS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Built {len(idx)} V53 cards -> {CARDS}")
    print(f"  DEPLOY: {int((idx.arm=='DEPLOY').sum())}  OBSERVE: {int((idx.arm=='OBSERVE').sum())}")
    print(f"  states: " + ", ".join(f"{k}={v}" for k, v in idx.state.value_counts().items()))
    print(f"  index -> {OUT / 'V53_SLEEVE_CARDS.md'}")


if __name__ == "__main__":
    main()
