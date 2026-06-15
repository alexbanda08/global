"""
HL SLEEVE CARDS builder.

Generates one card per HL shadow sleeve (9 V52 + 1 XSM) as JSON in
shadow_v52/cards/, plus a SLEEVE_CARDS.md index. Each card merges:
  - static spec (signal, gate, exit, variant, weight)
  - validated metrics (from the 2026-05-26 optimization audit)
  - LIVE shadow status (from fires_ledger.csv / positions_latest.csv / xsm_status.csv)

Re-run any time (cheap) to refresh the live-status block on each card.

    py shadow_v52/build_sleeve_cards.py
"""
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime, timezone
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "shadow_v52"
CARDS = OUT / "cards"
CARDS.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Static spec + validated metrics (gated config = the deployed variant).
# Metrics from optimized_v52_metrics.csv (best gate per sleeve) + b1 BTC card.
# ---------------------------------------------------------------------------
SPECS = [
    dict(card_id="v52_stf_btc", fleet="V52", name="STF_BTC", coin="BTC", tf="4h",
         family="trend (SuperTrend)", signal="SuperTrend(10, 3.0) flip + EMA(200) regime",
         variant="V45 (volume>1.1x20MA)", gate="FUND_Z<2", exit="regime-adaptive REGIME_EXITS_4H",
         weight=0.12, new=True,
         validated=dict(sharpe=1.00, cagr=0.244, mdd=-0.284, calmar=0.86, sh_2024=-0.59, sh_2025=0.87, sh_2026=3.61),
         notes="NEW sleeve — fills the missing V52 BTC slot. Best of 6 BTC candidates; counter-cyclical (+3.61 Sharpe in 2026)."),
    dict(card_id="v52_cci_eth", fleet="V52", name="CCI_ETH", coin="ETH", tf="4h",
         family="mean-reversion (CCI)", signal="CCI(20) extreme cross +/-150, ADX(14)<22",
         variant="V41 (regime exits)", gate="FUND_Z<2", exit="regime-adaptive REGIME_EXITS_4H",
         weight=0.12, new=False,
         validated=dict(sharpe=1.411, cagr=0.289, mdd=-0.1847, calmar=1.565, sh_2024=2.032, sh_2025=1.091, sh_2026=0.42),
         notes="Mean-reversion at CCI extremes. FUND_Z gate lifts Sharpe 1.32->1.41."),
    dict(card_id="v52_stf_sol", fleet="V52", name="STF_SOL", coin="SOL", tf="4h",
         family="trend (SuperTrend)", signal="SuperTrend(10, 3.0) flip + EMA(200) regime",
         variant="baseline", gate="FUND_Z<2", exit="EXIT_4H (tp10/sl2/trail6/hold60)",
         weight=0.12, new=False,
         validated=dict(sharpe=1.148, cagr=0.2833, mdd=-0.2096, calmar=1.352, sh_2024=0.752, sh_2025=2.123, sh_2026=-0.717),
         notes="FUND_Z gate lifts Sharpe 0.99->1.15. Weak in 2026 low-vol SOL regime."),
    dict(card_id="v52_stf_avax", fleet="V52", name="STF_AVAX", coin="AVAX", tf="4h",
         family="trend (SuperTrend)", signal="SuperTrend(10, 3.0) flip + EMA(200) regime",
         variant="V45 (volume>1.1x20MA)", gate="FUND_Z<2", exit="regime-adaptive REGIME_EXITS_4H",
         weight=0.12, new=False,
         validated=dict(sharpe=2.30, cagr=0.7181, mdd=-0.1279, calmar=5.614, sh_2024=2.595, sh_2025=2.628, sh_2026=0.422),
         notes="STRONGEST sleeve. FUND_Z gate: Sharpe 2.10->2.30, MDD -16.3%->-12.8%. Permutation p=0.000."),
    dict(card_id="v52_latbb_avax", fleet="V52", name="LATBB_AVAX", coin="AVAX", tf="4h",
         family="range-fade (Bollinger)", signal="Lateral BB(20,2.0) fade, ADX(14)<18",
         variant="baseline", gate="FUND_Z<2", exit="EXIT_4H (tp10/sl2/trail6/hold60)",
         weight=0.12, new=False,
         validated=dict(sharpe=1.59, cagr=0.3116, mdd=-0.1472, calmar=2.118, sh_2024=2.603, sh_2025=1.165, sh_2026=0.148),
         notes="Range-bound fade (low ADX). Rarest fire cadence (~8/yr). FUND_Z gate lifts 1.52->1.59."),
    dict(card_id="v52_mfi_sol", fleet="V52", name="MFI_SOL", coin="SOL", tf="4h",
         family="volume (MFI)", signal="MFI(14) extreme 25/75",
         variant="V41 (regime exits)", gate="ATR_NOTOPVOL", exit="regime-adaptive REGIME_EXITS_4H",
         weight=0.10, new=False,
         validated=dict(sharpe=1.12, cagr=0.416, mdd=-0.3803, calmar=1.094, sh_2024=2.121, sh_2025=0.619, sh_2026=-0.083),
         notes="ATR_NOTOPVOL gate: Sharpe 0.63->1.12 (+0.49, biggest volume-sleeve lift)."),
    dict(card_id="v52_vp_link", fleet="V52", name="VP_LINK", coin="LINK", tf="4h",
         family="volume (Volume-Profile)", signal="Volume-profile rotation (win=60, n_bins=15)",
         variant="baseline", gate="ATR_NOTOPVOL", exit="EXIT_4H (tp10/sl2/trail6/hold60)",
         weight=0.10, new=False,
         validated=dict(sharpe=1.634, cagr=0.6497, mdd=-0.305, calmar=2.13, sh_2024=2.053, sh_2025=2.107, sh_2026=-1.12),
         notes="Highest-fire-cadence sleeve. ATR_NOTOPVOL gate: Sharpe 1.35->1.63."),
    dict(card_id="v52_svd_avax", fleet="V52", name="SVD_AVAX", coin="AVAX", tf="4h",
         family="volume (Signed-Vol-Divergence)", signal="Signed-volume divergence (lookback=20, cvd_win=50)",
         variant="baseline", gate="ATR_NOTOPVOL", exit="EXIT_4H (tp10/sl2/trail6/hold60)",
         weight=0.10, new=False,
         validated=dict(sharpe=0.538, cagr=0.1136, mdd=-0.2834, calmar=0.401, sh_2024=0.736, sh_2025=-0.222, sh_2026=2.072),
         notes="Weakest full-window Sharpe but +2.07 in 2026 (counter-cyclical). ATR gate lifts 0.38->0.54."),
    dict(card_id="v52_mfi_eth", fleet="V52", name="MFI_ETH", coin="ETH", tf="4h",
         family="volume (MFI)", signal="MFI(14) extreme 25/75",
         variant="baseline", gate="ATR_NOTOPVOL", exit="EXIT_4H (tp10/sl2/trail6/hold60)",
         weight=0.10, new=False,
         validated=dict(sharpe=0.683, cagr=0.1729, mdd=-0.3196, calmar=0.541, sh_2024=1.088, sh_2025=0.261, sh_2026=0.975),
         notes="ATR_NOTOPVOL gate: Sharpe 0.27->0.68 (+0.47)."),
    dict(card_id="xsm_v24_multifilter", fleet="XSM", name="V24-XSM", coin="9-coin basket", tf="4h",
         family="cross-sectional momentum",
         signal="Long top-4 of 9 by 14d momentum, weekly rebalance",
         variant="multi_filter (breadth>=5/9 + BTC>100dMA + BTC 50dMA rising)",
         gate="regime filter (the multi_filter itself)", exit="weekly rebalance / filter-off -> cash",
         weight=0.0, new=False,
         validated=dict(sharpe=0.69, cagr=None, mdd=None, calmar=None, sh_2024=None, sh_2025=None, sh_2026=None),
         notes="Separate book. 0% live allocation until more coins join HL (only 5/9 HL-tradeable). "
               "Defensive by design: filter passed only ~4.5% of 2026 bars. Relaxations all hurt."),
]


def load_live_status():
    """Per-sleeve fire counts + last fire + current state, from shadow outputs."""
    status = {}
    ledger_p = OUT / "fires_ledger.csv"
    if ledger_p.exists():
        led = pd.read_csv(ledger_p)
        for name, g in led.groupby("sleeve"):
            status[name] = dict(
                ledger_fires=int(len(g)),
                last_fire=str(g["entry_ts"].max()),
                ledger_paper_pnl=round(float(g["paper_pnl_usd"].sum()), 2),
                ledger_win_rate=round(float((g["ret_pct"] > 0).mean()) * 100, 1),
            )
    pos_p = OUT / "positions_latest.csv"
    if pos_p.exists():
        pos = pd.read_csv(pos_p)
        for _, r in pos.iterrows():
            nm = r.get("sleeve")
            status.setdefault(nm, {})
            status[nm]["current_state"] = r.get("state")
            if r.get("state") == "OPEN":
                status[nm]["open_dir"] = r.get("direction")
                status[nm]["open_entry_ts"] = r.get("entry_ts")
                status[nm]["unrealized_pct"] = r.get("unrealized_pct")
    return status


def load_xsm_status():
    p = OUT / "xsm_status.csv"
    if not p.exists():
        return {}
    df = pd.read_csv(p)
    last = df.iloc[-1].to_dict()
    return last


def main():
    now = datetime.now(timezone.utc).isoformat()
    live = load_live_status()
    xsm = load_xsm_status()

    cards = []
    for spec in SPECS:
        card = dict(spec)
        card["status"] = "shadow_paper"
        card["venue"] = "hyperliquid_perp"
        card["card_built"] = now
        if spec["fleet"] == "XSM":
            card["live"] = dict(
                state=xsm.get("status", "n/a"),
                breadth=xsm.get("breadth", "n/a"),
                btc_above_100dma=xsm.get("btc_above_100dma", "n/a"),
                btc_50dma_rising=xsm.get("btc_50dma_rising", "n/a"),
                target_basket=xsm.get("target_basket", "FLAT"),
            )
        else:
            card["live"] = live.get(spec["name"], dict(current_state="FLAT", ledger_fires=0))
        path = CARDS / f"{spec['card_id']}.json"
        path.write_text(json.dumps(card, indent=2, default=str), encoding="utf-8")
        cards.append(card)

    # ---- MD index ----
    md = ["# HL Sleeve Cards", "",
          f"**Built:** {now}", "**Mode:** shadow_paper | **Venue:** hyperliquid_perp",
          f"**Fleet:** {len([c for c in cards if c['fleet']=='V52'])} V52 sleeves + 1 XSM basket", "",
          "## V52 fleet (9 sleeves)", "",
          "| Card | Coin | TF | Family | Gate | Weight | Val Sharpe | 2026 Sh | Live state | Fires | Last fire |",
          "|---|---|---|---|---|---:|---:|---:|---|---:|---|"]
    for c in cards:
        if c["fleet"] != "V52":
            continue
        lv = c["live"]
        md.append(f"| {c['name']}{' NEW' if c.get('new') else ''} | {c['coin']} | {c['tf']} | {c['family']} | "
                  f"{c['gate']} | {c['weight']:.0%} | {c['validated']['sharpe']} | {c['validated'].get('sh_2026','-')} | "
                  f"{lv.get('current_state','FLAT')} | {lv.get('ledger_fires',0)} | {str(lv.get('last_fire','-'))[:16]} |")
    md += ["", "## XSM basket", ""]
    xc = next(c for c in cards if c["fleet"] == "XSM")
    lv = xc["live"]
    md += [f"- **{xc['name']}** — {xc['signal']}",
           f"- Filter: **{lv.get('state')}** (breadth {lv.get('breadth')}, BTC>100dMA={lv.get('btc_above_100dma')}, 50dMA_rising={lv.get('btc_50dma_rising')})",
           f"- Current basket: `{lv.get('target_basket')}`",
           f"- Live allocation: **0%** ({xc['notes']})", ""]
    md += ["## Per-card files", "", "One JSON per sleeve in `shadow_v52/cards/`:"]
    for c in cards:
        md.append(f"- `cards/{c['card_id']}.json` — {c['name']} ({c['coin']})")
    (OUT / "SLEEVE_CARDS.md").write_text("\n".join(md), encoding="utf-8")

    print(f"Built {len(cards)} sleeve cards -> {CARDS}")
    print(f"  V52: {len([c for c in cards if c['fleet']=='V52'])}  XSM: 1")
    print(f"  index -> {OUT / 'SLEEVE_CARDS.md'}")


if __name__ == "__main__":
    main()
