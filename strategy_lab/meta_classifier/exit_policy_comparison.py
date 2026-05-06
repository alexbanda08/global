"""Exit-policy comparison — HOLD vs HEDGE vs SELL exits, on V3 and BTC_only.

Context: VPS3 shadow shows 0 hedges firing in 190 V3 trades. Production
HEDGE_HOLD policy never triggers because BarEngine on_tick wiring is
incomplete in paper mode (TV agent backlog). So V3 effectively runs
hold-to-resolution today.

We can deploy NEW sleeves with SELL exits to capture downside protection
without needing the on_tick hedge loop. Question: which exit policy works?

Policies tested:
  P0 HOLD             — hold-to-resolution (current production V3 reality)
  P1 HEDGE_REVERT     — canonical: BUY opposite-side ASK on Binance rev_bp=5
  P2 SELL_REVERT_BID  — SELL held side at top-bid on Binance rev_bp=5
  P3 SELL_FLOOR_040   — SELL held side if bid drops below 0.40 (stop-loss)
  P4 SELL_FLOOR_035   — SELL if bid drops below 0.35
  P5 SELL_TRAIL_10pct — SELL if bid drops 10% from peak (after entry)
  P6 SELL_TRAIL_15pct — SELL if bid drops 15% from peak
  P7 SELL_REVERT_8bp  — SELL on rev_bp=8 (looser trigger)

Each policy uses the SAME book + same fees + same entry semantics.

Tested on:
  • V3 fires (entry @ bucket 0, BTC, Apr 22 → Apr 29, prob_stack ≥ 0.65)
  • BTC_only fires (entry @ bucket 12, BTC, Apr 22 → May 4, top-10% |btc_ret_2m|)

Outputs:
  strategy_lab/results/meta_classifier/exit_policy_comparison.csv
  strategy_lab/reports/EXIT_POLICY_COMPARISON.md
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "strategy_lab"))

from book_walk import book_walk_fill              # noqa: E402
from polymarket_stats import equity_curve_stats   # noqa: E402

LEVELS = 10
NOTIONAL_USD = 25.0
FEE_RATE = 0.02
SPREAD_FILTER_BTC = 0.02

REFRESH = ROOT / "data" / "v4" / "refresh_2026_05_02"
KLINES = REFRESH / "binance_spot_1min_full.csv"
BOOK_BTC = REFRESH / "btc_book_depth_v3_full.csv"
UNIV_BTC = REFRESH / "btc_markets_minimal.csv"
V3_CSV = ROOT / "strategy_lab" / "data" / "polymarket" / "btc_features_v3.csv"

OUT_CSV = ROOT / "strategy_lab" / "results" / "meta_classifier" / "exit_policy_comparison.csv"
REPORT  = ROOT / "strategy_lab" / "reports" / "EXIT_POLICY_COMPARISON.md"

V3_CONF_THR = 0.65


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_book(path: Path) -> dict:
    cols_ap = [f"ask_price_{i}" for i in range(LEVELS)]
    cols_as = [f"ask_size_{i}"  for i in range(LEVELS)]
    cols_bp = [f"bid_price_{i}" for i in range(LEVELS)]
    cols_bs = [f"bid_size_{i}"  for i in range(LEVELS)]
    keep = ["slug", "bucket_10s", "outcome"] + cols_ap + cols_as + cols_bp + cols_bs
    df = pd.read_csv(path, usecols=keep)
    asks_p = df[cols_ap].to_numpy(dtype=float); asks_s = df[cols_as].to_numpy(dtype=float)
    bids_p = df[cols_bp].to_numpy(dtype=float); bids_s = df[cols_bs].to_numpy(dtype=float)
    out: dict = {}
    for i in range(len(df)):
        slug = df.slug.iat[i]
        if slug not in out: out[slug] = {}
        out[slug][(int(df.bucket_10s.iat[i]), df.outcome.iat[i])] = (asks_p[i], asks_s[i], bids_p[i], bids_s[i])
    return out


def load_btc_1m() -> pd.DataFrame:
    df = pd.read_csv(KLINES)
    df = df[df.symbol_id == "BINANCE_SPOT_BTC_USDT"].copy()
    df["ts_s"] = (df.time_period_start_us // 1_000_000).astype("int64")
    return df.sort_values("ts_s").reset_index(drop=True)[["ts_s", "price_close"]]


def asof_close(k1m: pd.DataFrame, ts: int) -> float:
    """End-time-indexed asof (1MIN bars). Avoids the bar-open-indexed
    lookahead bug fixed in extended_backtest_with_robustness 2026-05-06."""
    end_us = (k1m.ts_s.astype("int64") + 60).values * 1_000_000
    target_us = int(ts) * 1_000_000
    idx = int(np.searchsorted(end_us, target_us, side="right")) - 1
    return float("nan") if idx < 0 else float(k1m.price_close.iloc[idx])


# ---------------------------------------------------------------------------
# Multi-exit simulator
# ---------------------------------------------------------------------------

def sell_at_bid(bid_p: np.ndarray, bid_s: np.ndarray, shares: float) -> tuple[float, float]:
    """Walk bid book to sell `shares`. Returns (vwap_sell_price, gross_usd)."""
    remaining = float(shares)
    total_usd = 0.0
    total_shares = 0.0
    for p, s in zip(bid_p, bid_s):
        if not (np.isfinite(p) and np.isfinite(s)) or s <= 0 or p <= 0 or p >= 1:
            break
        if s >= remaining:
            total_usd += remaining * p
            total_shares += remaining
            remaining = 0
            break
        total_usd += s * p
        total_shares += s
        remaining -= s
    if total_shares <= 0:
        return float("nan"), 0.0
    return total_usd / total_shares, total_usd


def simulate(row: pd.Series, k1m: pd.DataFrame, book: dict, max_bucket: int,
             entry_bucket: int, policy: str,
             rev_bp: int = 5, floor: float | None = None,
             trail_pct: float | None = None,
             spread_filter: float | None = None) -> dict | None:
    sig = int(row.signal)
    held_outcome = "Up" if sig == 1 else "Down"
    other_outcome = "Down" if sig == 1 else "Up"

    slug = row.slug
    if slug not in book:
        return None
    slug_book = book[slug]

    entry_key = (entry_bucket, held_outcome)
    if entry_key not in slug_book:
        return None
    ask_p, ask_s, bid_p, bid_s = slug_book[entry_key]
    if spread_filter is not None and len(ask_p) and len(bid_p):
        if np.isfinite(ask_p[0]) and np.isfinite(bid_p[0]) and (ask_p[0] - bid_p[0]) > spread_filter:
            return {"skipped_spread": True}
    vwap_e, shares_e, usd_e, lvls_e, under_e = book_walk_fill(ask_p, ask_s, NOTIONAL_USD)
    if shares_e <= 0:
        return None
    if under_e and usd_e < NOTIONAL_USD * 0.5:
        return {"skipped_thin": True}

    ws = int(row.window_start_unix)
    btc_at_entry = asof_close(k1m, ws + entry_bucket * 10)

    # Walk post-entry buckets to detect exit triggers
    exit_event = None  # ('hedge'|'sell_revert'|'sell_floor'|'sell_trail', bucket, exit_data)
    peak_bid = bid_p[0] if len(bid_p) and np.isfinite(bid_p[0]) else 0.0

    if policy != "HOLD":
        for bucket in range(entry_bucket + 1, max_bucket + 1):
            # Update peak from this bucket's held-side bid
            held_key = (bucket, held_outcome)
            if held_key in slug_book:
                _, _, b_p, b_s = slug_book[held_key]
                cur_bid = b_p[0] if len(b_p) and np.isfinite(b_p[0]) else 0.0
                peak_bid = max(peak_bid, cur_bid)
            else:
                cur_bid = 0.0

            # Compute revert bp if needed
            bp_rev = None
            if policy in ("HEDGE_REVERT", "SELL_REVERT_BID", "SELL_REVERT_8BP"):
                ts_in_bucket = ws + bucket * 10
                btc_now = asof_close(k1m, ts_in_bucket)
                if np.isfinite(btc_at_entry) and np.isfinite(btc_now):
                    bp_rev = (btc_now - btc_at_entry) / btc_at_entry * 10000.0

            triggered = False
            policy_rev = rev_bp if policy != "SELL_REVERT_8BP" else 8
            if policy == "HEDGE_REVERT" and bp_rev is not None:
                triggered = (sig == 1 and bp_rev <= -policy_rev) or (sig == 0 and bp_rev >= policy_rev)
                if triggered:
                    other_key = (bucket, other_outcome)
                    if other_key not in slug_book:
                        triggered = False
                    else:
                        h_ask_p, h_ask_s, _, _ = slug_book[other_key]
                        top = h_ask_p[0] if len(h_ask_p) and np.isfinite(h_ask_p[0]) else float("nan")
                        if not (np.isfinite(top) and 0 < top < 1):
                            triggered = False
                        else:
                            target_h = shares_e * float(top)
                            vwap_h, shares_h, usd_h, _, under_h = book_walk_fill(h_ask_p, h_ask_s, target_h)
                            if shares_h <= 0:
                                triggered = False
                            else:
                                if shares_h < shares_e * 0.95 and not under_h:
                                    bump = shares_e * vwap_h
                                    vwap_h, shares_h, usd_h, _, under_h = book_walk_fill(h_ask_p, h_ask_s, bump)
                                exit_event = ("hedge", bucket, dict(vwap_h=vwap_h, shares_h=shares_h, usd_h=usd_h))
                                break

            elif policy in ("SELL_REVERT_BID", "SELL_REVERT_8BP") and bp_rev is not None:
                triggered = (sig == 1 and bp_rev <= -policy_rev) or (sig == 0 and bp_rev >= policy_rev)
                if triggered and held_key in slug_book:
                    _, _, b_p, b_s = slug_book[held_key]
                    sell_vwap, sell_gross = sell_at_bid(b_p, b_s, shares_e)
                    if np.isfinite(sell_vwap) and sell_gross > 0:
                        exit_event = ("sell_revert", bucket, dict(sell_vwap=sell_vwap, sell_gross=sell_gross))
                        break

            elif policy.startswith("SELL_FLOOR_") and floor is not None:
                if cur_bid > 0 and cur_bid <= floor:
                    if held_key in slug_book:
                        _, _, b_p, b_s = slug_book[held_key]
                        sell_vwap, sell_gross = sell_at_bid(b_p, b_s, shares_e)
                        if np.isfinite(sell_vwap) and sell_gross > 0:
                            exit_event = ("sell_floor", bucket, dict(sell_vwap=sell_vwap, sell_gross=sell_gross))
                            break

            elif policy.startswith("SELL_TRAIL_") and trail_pct is not None:
                if peak_bid > 0 and cur_bid > 0:
                    drawdown_from_peak = (peak_bid - cur_bid) / peak_bid
                    if drawdown_from_peak >= trail_pct:
                        if held_key in slug_book:
                            _, _, b_p, b_s = slug_book[held_key]
                            sell_vwap, sell_gross = sell_at_bid(b_p, b_s, shares_e)
                            if np.isfinite(sell_vwap) and sell_gross > 0:
                                exit_event = ("sell_trail", bucket, dict(sell_vwap=sell_vwap, sell_gross=sell_gross))
                                break

    outcome_up = int(row.outcome_up)
    sig_won = (sig == outcome_up)

    # Compute PnL based on what happened
    if exit_event is None:
        # Held to resolution
        if sig_won:
            gross = shares_e * 1.0
            profit_pre_fee = gross - usd_e
            fee = profit_pre_fee * FEE_RATE if profit_pre_fee > 0 else 0.0
            pnl = profit_pre_fee - fee
        else:
            pnl = -usd_e
        return dict(pnl=pnl, cost=usd_e, exit_reason="hold", sig_won=sig_won, vwap_e=vwap_e)

    kind, exit_bucket, ed = exit_event
    if kind == "hedge":
        cost = usd_e + ed["usd_h"]
        if sig_won:
            gross = shares_e * 1.0
            fee = shares_e * (1.0 - vwap_e) * FEE_RATE
        else:
            gross = ed["shares_h"] * 1.0
            fee = ed["shares_h"] * (1.0 - ed["vwap_h"]) * FEE_RATE
        pnl = gross - cost - fee
        return dict(pnl=pnl, cost=cost, exit_reason="hedge", sig_won=sig_won,
                    vwap_e=vwap_e, exit_bucket=exit_bucket, vwap_h=ed["vwap_h"])

    # SELL exits (revert/floor/trail) — close position by selling at bid
    sell_gross = ed["sell_gross"]
    profit_pre_fee = sell_gross - usd_e
    fee = max(profit_pre_fee, 0) * FEE_RATE  # fee on profit only (mirror hold logic)
    pnl = profit_pre_fee - fee
    return dict(pnl=pnl, cost=usd_e, exit_reason=kind, sig_won=sig_won,
                vwap_e=vwap_e, exit_bucket=exit_bucket, sell_vwap=ed["sell_vwap"])


def run(df: pd.DataFrame, k1m: pd.DataFrame, book: dict, entry_bucket: int,
        policy: str, label: str, **kwargs) -> dict:
    pnls, costs, ws_list = [], [], []
    sk_thin = sk_no_book = sk_spread = wins = 0
    exit_kinds = {"hold": 0, "hedge": 0, "sell_revert": 0, "sell_floor": 0, "sell_trail": 0}
    for _, row in df.iterrows():
        max_bucket = 89 if row.timeframe == "15m" else 29
        r = simulate(row, k1m, book, max_bucket, entry_bucket, policy, **kwargs)
        if r is None:
            sk_no_book += 1; continue
        if r.get("skipped_spread"):
            sk_spread += 1; continue
        if r.get("skipped_thin"):
            sk_thin += 1; continue
        pnls.append(r["pnl"]); costs.append(r["cost"]); ws_list.append(int(row.window_start_unix))
        if r["sig_won"]: wins += 1
        exit_kinds[r["exit_reason"]] = exit_kinds.get(r["exit_reason"], 0) + 1
    pnls = np.array(pnls); costs = np.array(costs)
    n = len(pnls)
    if n == 0:
        return {"label": label, "n": 0}
    eq = equity_curve_stats(pnls, trade_timestamps=np.array(ws_list, dtype=float))
    return dict(
        label=label, n=n, wins=wins,
        hit=float((pnls > 0).mean()),
        pnl_total=float(pnls.sum()),
        pnl_mean=float(pnls.mean()),
        pnl_min=float(pnls.min()),
        pnl_max=float(pnls.max()),
        pnl_std=float(pnls.std()),
        n_hold=exit_kinds.get("hold", 0),
        n_hedge=exit_kinds.get("hedge", 0),
        n_sell_revert=exit_kinds.get("sell_revert", 0),
        n_sell_floor=exit_kinds.get("sell_floor", 0),
        n_sell_trail=exit_kinds.get("sell_trail", 0),
        sk_thin=sk_thin, sk_no_book=sk_no_book, sk_spread=sk_spread,
        sharpe=eq["sharpe"], sortino=eq["sortino"], max_dd=eq["max_dd"],
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("[1] features + universe + book…")
    k1m = load_btc_1m()
    book = load_book(BOOK_BTC)
    uni = pd.read_csv(UNIV_BTC).dropna(subset=["window_start_unix", "outcome_up"])
    uni["outcome_up"] = uni["outcome_up"].astype(int)

    # ── V3 fires ──────────────────────────────────────────────────────────
    v3 = pd.read_csv(V3_CSV)
    v3["v3_conf"] = (v3["prob_stack"] - 0.5).abs() + 0.5
    v3_fire = v3[v3["v3_conf"] >= V3_CONF_THR].copy()
    v3_fire["signal"] = (v3_fire["prob_stack"] > 0.5).astype(int)
    v3_fire = v3_fire.merge(uni[["slug", "outcome_up", "timeframe"]].rename(
        columns={"timeframe": "tf_uni", "outcome_up": "ou_uni"}), on="slug", how="left", suffixes=("", "_x"))
    print(f"    V3 fires: {len(v3_fire)}")

    # ── BTC_only fires ────────────────────────────────────────────────────
    uni_btc = uni.copy()
    uni_btc["ret_2m"] = uni_btc["window_start_unix"].astype("int64").apply(
        lambda w: np.log(asof_close(k1m, int(w) + 120) / asof_close(k1m, int(w))))
    active = uni_btc[uni_btc["ret_2m"].notna()].copy()
    thr = active["ret_2m"].abs().quantile(0.90)
    btc_fire = active[active["ret_2m"].abs() >= thr].copy()
    btc_fire["signal"] = (btc_fire["ret_2m"] > 0).astype(int)
    print(f"    BTC_only fires: {len(btc_fire)}")

    # ── Run all policies on both signals ──────────────────────────────────
    POLICIES = [
        ("HOLD",            dict(policy="HOLD")),
        ("HEDGE_REVERT_5",  dict(policy="HEDGE_REVERT", rev_bp=5)),
        ("SELL_REVERT_5",   dict(policy="SELL_REVERT_BID", rev_bp=5)),
        ("SELL_REVERT_8",   dict(policy="SELL_REVERT_8BP", rev_bp=8)),
        ("SELL_FLOOR_040",  dict(policy="SELL_FLOOR_040", floor=0.40)),
        ("SELL_FLOOR_035",  dict(policy="SELL_FLOOR_035", floor=0.35)),
        ("SELL_TRAIL_10",   dict(policy="SELL_TRAIL_10", trail_pct=0.10)),
        ("SELL_TRAIL_15",   dict(policy="SELL_TRAIL_15", trail_pct=0.15)),
    ]

    results = []
    for sig_label, sig_df, entry_bkt, sf in [
        ("V3_BTC5m",     v3_fire,  0,  SPREAD_FILTER_BTC),
        ("BTC_only_5m",  btc_fire[btc_fire.timeframe == "5m"], 12, SPREAD_FILTER_BTC),
    ]:
        for pol_name, pol_kwargs in POLICIES:
            r = run(sig_df, k1m, book, entry_bkt, label=f"{sig_label} | {pol_name}",
                    spread_filter=sf, **pol_kwargs)
            results.append(r)
            if r["n"] > 0:
                triggers = (r["n_hedge"] + r["n_sell_revert"] + r["n_sell_floor"] + r["n_sell_trail"])
                print(f"  {r['label']:38s}  n={r['n']:4d}  hit={r['hit']*100:5.1f}%  "
                      f"pnl=${r['pnl_total']:+.2f}  mean=${r['pnl_mean']:+.4f}  "
                      f"std=${r['pnl_std']:.2f}  triggered={triggers:3d}  "
                      f"sharpe={r['sharpe']:+.2f}")

    df_res = pd.DataFrame(results)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df_res.to_csv(OUT_CSV, index=False)

    # ── Report ────────────────────────────────────────────────────────────
    L = [
        "# Exit Policy Comparison — HOLD vs HEDGE vs SELL\n",
        "_Generated: 2026-05-05_\n",
        "## Why this exists\n",
        "VPS3 shadow shows **0 hedges fired in 190 V3 paper trades** despite "
        "`TV_POLY_HEDGE_POLICY=HEDGE_HOLD`. Production V3 paper effectively runs "
        "`HOLD-to-resolution` because BarEngine `on_tick` wiring is incomplete "
        "(open in TV agent backlog).\n\n"
        "Question: instead of hedging (BUY opposite-side YES/NO at ASK), what if "
        "we SELL the held position at BID when the signal fails? SELL is simpler "
        "to wire (no opposite-side book needed) and may be what's deployable today.\n",
        "## Where the hedge logic came from\n",
        "Copied from `polymarket_signal_grid_realfills.py` lines 116-145 — the "
        "canonical UpDown engine that produced the published v2 numbers. The "
        "trigger is:\n```python\nbp = (binance_now - binance_at_entry) / binance_at_entry * 10000\nreverted = (sig==1 and bp <= -rev_bp) or (sig==0 and bp >= rev_bp)\n```\n"
        f"Default `rev_bp=5` (= REV_BP_THRESHOLD in `polymarket_updown_PROD_2026_05_05.py`).\n",
        "## Policies\n",
        "| ID | Trigger | Action |",
        "|---|---|---|",
        "| HOLD            | never            | hold to $1/$0 settlement |",
        "| HEDGE_REVERT_5  | rev ≥ 5bp        | BUY opposite side @ ASK (canonical) |",
        "| SELL_REVERT_5   | rev ≥ 5bp        | SELL held @ BID |",
        "| SELL_REVERT_8   | rev ≥ 8bp        | SELL held @ BID (looser trigger) |",
        "| SELL_FLOOR_040  | bid ≤ 0.40       | SELL held @ BID |",
        "| SELL_FLOOR_035  | bid ≤ 0.35       | SELL held @ BID |",
        "| SELL_TRAIL_10   | bid drops 10% from peak | SELL held @ BID |",
        "| SELL_TRAIL_15   | bid drops 15% from peak | SELL held @ BID |",
        "",
        "All policies: $25 stake, top-10 ASK book walk for entry, BID book walk for SELL exit, "
        "2% taker on profit only, BTC spread filter ≤ 0.02. Settlement on hold = $1/$0.",
        "",
        "## Results\n",
        "| Signal × Policy | n | hit% | total PnL | mean PnL | std | min PnL | max PnL | hold | hedge | sell | Sharpe |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in results:
        if r["n"] == 0: continue
        n_sell = r["n_sell_revert"] + r["n_sell_floor"] + r["n_sell_trail"]
        L.append(
            f"| {r['label']} | {r['n']} | {r['hit']*100:.1f}% | "
            f"${r['pnl_total']:+.2f} | ${r['pnl_mean']:+.4f} | "
            f"${r['pnl_std']:.2f} | ${r['pnl_min']:+.2f} | ${r['pnl_max']:+.2f} | "
            f"{r['n_hold']} | {r['n_hedge']} | {n_sell} | {r['sharpe']:+.2f} |"
        )

    # Verdict per signal
    L += ["", "## Best policy per signal\n"]
    for sig_label in ["V3_BTC5m", "BTC_only_5m"]:
        sub = [r for r in results if r["label"].startswith(sig_label) and r["n"] > 0]
        if not sub: continue
        best_total = max(sub, key=lambda r: r["pnl_total"])
        best_sharpe = max(sub, key=lambda r: r["sharpe"])
        L.append(f"### {sig_label}\n")
        L.append(f"- **Best total PnL**: {best_total['label'].split('|')[1].strip()} → ${best_total['pnl_total']:+.2f} ({best_total['hit']*100:.1f}% hit)")
        L.append(f"- **Best Sharpe**:    {best_sharpe['label'].split('|')[1].strip()} → Sharpe {best_sharpe['sharpe']:+.2f} (${best_sharpe['pnl_total']:+.2f})")
        # Versus HOLD baseline
        hold = next((r for r in sub if r["label"].endswith("HOLD")), None)
        if hold:
            delta_total = best_total["pnl_total"] - hold["pnl_total"]
            L.append(f"- vs HOLD baseline: best policy delivers **${delta_total:+.2f}** more than hold-to-resolution")
            if best_total["label"].endswith("HOLD"):
                L.append("- → **No exit policy beats HOLD** for this signal. Don't add an exit.")
            elif "SELL" in best_total["label"]:
                L.append(f"- → **SELL exit beats HOLD** by ${delta_total:.2f}. Consider deploying.")
            elif "HEDGE" in best_total["label"]:
                L.append(f"- → HEDGE exit beats HOLD by ${delta_total:.2f}, but requires `on_tick` wiring.")
        L.append("")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(L), encoding="utf-8")
    print(f"\n[report] wrote {REPORT}")
    print(f"[csv] wrote {OUT_CSV}")


if __name__ == "__main__":
    main()
