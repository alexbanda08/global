"""Standalone SMS rule backtest on per-fire files.

Per (asset, tf, fire_offset_s, rule), report:
  n, WR, $/trade, sum_pnl_28d  (LegacyConfig 2%-on-profit fees, already in pnl_legacy_usd)

Rules:
  A — BOS continuation: bet UP within 5 bars of bos_buy; mirror DOWN.
  B — CHoCH reversal:  bet UP within 3 bars of choch_buy; mirror.
  C — Trend strength:  bet UP when trend_strength_raw >= 4; DOWN when <= -4.
  D — Top confidence:  bet WITH direction only when system_confidence == 90.
  E — RSI bullish div: bet UP on rsi_bullish_div=True; DOWN on rsi_bearish_div=True.
  F — CVD aligned:     bet sign(cvd) when cvd_level == 1 (High).
  G — Liquidity reclaim: bet UP at liquidity_dn (sweep+bounce); DOWN at liquidity_up.

The per-fire file already has both UP and DOWN versions (separate rows). Each row has
direction + outcome + won. So for each rule:
  - filter to rows that match the rule's signal direction
  - aggregate n, WR (mean of won), sum_pnl (sum of pnl_legacy_usd), $/tr

We output per (asset, tf, offset_s, rule).
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
RES = ROOT / "data" / "v4" / "canonical" / "_results"

S15_PATH = RES / "s15_with_sms.parquet"
S6_PATH = RES / "s6_with_sms.parquet"
V15M_PATH = RES / "v15m_with_sms.parquet"

OUT = RES / "sms_standalone_results.csv"
OUT_DETAIL = RES / "sms_standalone_detail.csv"


def signal_from_rule(df: pd.DataFrame, rule: str) -> pd.Series:
    """Returns the bet direction recommended by the rule: 'UP', 'DOWN', or 'NONE'."""
    n = len(df)
    sig = pd.Series(["NONE"] * n, index=df.index, dtype=object)

    if rule == "A_bos_continuation":
        # bos within last 5 bars (bars_since_bos_* between 0 and 5)
        up = (df["bars_since_bos_buy"] >= 0) & (df["bars_since_bos_buy"] <= 5)
        dn = (df["bars_since_bos_sell"] >= 0) & (df["bars_since_bos_sell"] <= 5)
        # If both fired recently, take the more recent
        both = up & dn
        prefer_up_when_both = df.loc[both, "bars_since_bos_buy"] <= df.loc[both, "bars_since_bos_sell"]
        # Default: pick the closer side
        sig[up & ~dn] = "UP"
        sig[dn & ~up] = "DOWN"
        if both.any():
            sig.loc[both[both].index[prefer_up_when_both.values]] = "UP"
            sig.loc[both[both].index[~prefer_up_when_both.values]] = "DOWN"

    elif rule == "B_choch_reversal":
        up = (df["bars_since_choch_buy"] >= 0) & (df["bars_since_choch_buy"] <= 3)
        dn = (df["bars_since_choch_sell"] >= 0) & (df["bars_since_choch_sell"] <= 3)
        both = up & dn
        prefer_up_when_both = df.loc[both, "bars_since_choch_buy"] <= df.loc[both, "bars_since_choch_sell"]
        sig[up & ~dn] = "UP"
        sig[dn & ~up] = "DOWN"
        if both.any():
            sig.loc[both[both].index[prefer_up_when_both.values]] = "UP"
            sig.loc[both[both].index[~prefer_up_when_both.values]] = "DOWN"

    elif rule == "C_trend_strength":
        sig[df["trend_strength_raw"] >= 4] = "UP"
        sig[df["trend_strength_raw"] <= -4] = "DOWN"

    elif rule == "D_top_confidence":
        # system_confidence==90 means |raw|==7. Direction = sign of raw.
        top = df["system_confidence"] == 90
        sig[top & (df["trend_strength_raw"] > 0)] = "UP"
        sig[top & (df["trend_strength_raw"] < 0)] = "DOWN"

    elif rule == "E_rsi_divergence":
        sig[df["rsi_bullish_div"] == 1] = "UP"
        sig[df["rsi_bearish_div"] == 1] = "DOWN"

    elif rule == "F_cvd_aligned":
        cvd_high = df["cvd_level"] == 1
        sig[cvd_high & (df["cvd_sign"] > 0)] = "UP"
        sig[cvd_high & (df["cvd_sign"] < 0)] = "DOWN"

    elif rule == "G_liquidity_reclaim":
        # Sweep-and-reverse: at liquidity_dn, bet UP (bounce); at liquidity_up, bet DOWN (rejection).
        # Only flag when BOTH sides aren't simultaneously hot (rare).
        only_dn = (df["liquidity_dn"] == 1) & (df["liquidity_up"] == 0)
        only_up = (df["liquidity_up"] == 1) & (df["liquidity_dn"] == 0)
        sig[only_dn] = "UP"
        sig[only_up] = "DOWN"

    else:
        raise ValueError(rule)
    return sig


RULES = [
    "A_bos_continuation",
    "B_choch_reversal",
    "C_trend_strength",
    "D_top_confidence",
    "E_rsi_divergence",
    "F_cvd_aligned",
    "G_liquidity_reclaim",
]


def aggregate(df: pd.DataFrame, asset: str, tf: str, offset_s, rule: str, sig: pd.Series):
    matched = sig == df["direction"]
    sel = df[matched & (sig != "NONE")]
    if len(sel) == 0:
        return None
    sum_pnl = float(sel["pnl_legacy_usd"].sum())
    n = len(sel)
    wins = int(sel["won"].sum())
    return {
        "asset": asset, "tf": tf, "offset_s": offset_s, "rule": rule,
        "n": n, "wins": wins, "WR": wins / n,
        "sum_pnl": sum_pnl, "dollar_per_trade": sum_pnl / n,
    }


def run_panel(path, tf_label, offset_col_name):
    df = pd.read_parquet(path)
    # Drop rows without SMS data (panel merge gap)
    df = df[df["bos_buy"].notna()].copy()
    # Make sure dtypes are sane
    for c in ("bos_buy", "bos_sell", "choch_buy", "choch_sell",
              "rsi_bullish_div", "rsi_bearish_div", "liquidity_up", "liquidity_dn"):
        df[c] = df[c].fillna(0).astype(np.int8)
    for c in ("bars_since_bos_buy", "bars_since_bos_sell",
              "bars_since_choch_buy", "bars_since_choch_sell"):
        df[c] = df[c].fillna(-1).astype(np.int32)
    df["trend_strength_raw"] = df["trend_strength_raw"].fillna(0).astype(int)
    df["system_confidence"] = df["system_confidence"].fillna(50).astype(int)
    df["cvd_level"] = df["cvd_level"].fillna(0).astype(int)
    df["cvd_sign"] = df["cvd_sign"].fillna(0).astype(int)

    print(f"\n[{tf_label}] {len(df):,} fires with SMS panel data")
    rows = []

    # Aggregate at multiple granularities
    for rule in RULES:
        sig = signal_from_rule(df, rule)
        # All-asset all-offset summary
        r = aggregate(df, "ALL", tf_label, "ALL", rule, sig)
        if r:
            rows.append(r)
        # Per asset (all offsets)
        for asset in ("BTC", "ETH", "SOL"):
            mask = df["asset"] == asset
            r = aggregate(df[mask], asset, tf_label, "ALL", rule, sig[mask])
            if r:
                rows.append(r)
        # Per (asset, offset)
        for asset in ("BTC", "ETH", "SOL"):
            for off in sorted(df.loc[df["asset"] == asset, offset_col_name].dropna().unique()):
                mask = (df["asset"] == asset) & (df[offset_col_name] == off)
                r = aggregate(df[mask], asset, tf_label, int(off), rule, sig[mask])
                if r and r["n"] >= 5:
                    rows.append(r)

    return rows


def main():
    all_rows = []
    print("=== S1.5 5m ===")
    all_rows += run_panel(S15_PATH, tf_label="s15_5m", offset_col_name="fire_offset_s")
    print("\n=== S6 5m ===")
    all_rows += run_panel(S6_PATH, tf_label="s6_5m", offset_col_name="fire_offset_s")
    print("\n=== V15M 15m ===")
    all_rows += run_panel(V15M_PATH, tf_label="v15m_15m", offset_col_name="fire_offset_s")

    res = pd.DataFrame(all_rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    res.to_csv(OUT, index=False)
    print(f"\nwrote {OUT} ({len(res)} rows)")

    print("\n=== TOP 30 by dollar_per_trade (n >= 50) ===")
    top = res[res["n"] >= 50].sort_values("dollar_per_trade", ascending=False).head(30)
    print(top.to_string(index=False))
    print("\n=== ALL-ASSET / ALL-OFFSET summaries by rule ===")
    summ = res[(res["asset"] == "ALL") & (res["offset_s"] == "ALL")]
    print(summ.to_string(index=False))

    print("\n=== TOP 15 BUCKETS by sum_pnl (n>=200) ===")
    top2 = res[res["n"] >= 200].sort_values("sum_pnl", ascending=False).head(15)
    print(top2.to_string(index=False))
    print("\n=== BOTTOM 15 BUCKETS by sum_pnl (n>=200) ===")
    bot2 = res[res["n"] >= 200].sort_values("sum_pnl").head(15)
    print(bot2.to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
