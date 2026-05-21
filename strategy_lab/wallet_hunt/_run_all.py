"""Combined runner: fingerprint + true PnL with engine_v2 fees + CLOB winners.

Outputs a single table for all 6 wallets so we can rank by realized edge.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fingerprint import fingerprint_wallet, classify_slug  # noqa: E402
from load import load_resolutions, load_klines_asof, asof_strict  # noqa: E402
from fees import poly_taker_fee_per_share, bps_to_rate, DEFAULT_CRYPTO_FEE_BPS  # noqa: E402

FEE_RATE = bps_to_rate(DEFAULT_CRYPTO_FEE_BPS)
CACHE = Path(__file__).resolve().parent / "cache"


def decode_pnl(wallet: str, winners: dict, klines: dict) -> dict:
    short = wallet.lower()[:10]
    odir = CACHE / short
    legs_p = odir / "per_leg.parquet"
    trades_p = odir / "trades.parquet"
    if not legs_p.exists() or not trades_p.exists():
        return {"short": short, "error": "no per_leg/trades"}
    legs = pd.read_parquet(legs_p)
    trades = pd.read_parquet(trades_p)

    legs["winner"] = legs.conditionId.map(winners)
    legs["resolved"] = legs.winner.notna()
    legs["won"] = legs.resolved & (legs.winner == legs.outcome)

    legs["leftover_shares"] = legs.buy_shares - legs.sell_shares
    legs["leftover_cost"] = legs.avg_buy_px * legs.leftover_shares
    legs["leftover_settle_value"] = np.where(
        legs.resolved & legs.won, legs.leftover_shares, 0.0
    )
    legs["leftover_pnl"] = legs.leftover_settle_value - legs.leftover_cost

    # Realized on closed portion (avg_sell - avg_buy) × matched_shares
    legs["matched"] = legs[["buy_shares", "sell_shares"]].min(axis=1)
    legs["realized_pnl"] = (legs.avg_sell_px.fillna(0) - legs.avg_buy_px.fillna(0)) * legs.matched

    # Real Polymarket fees on EVERY fill at the avg price (approximation — could be exact per-trade)
    legs["entry_fees"] = legs.buy_shares * legs.avg_buy_px.fillna(0).apply(
        lambda p: poly_taker_fee_per_share(p, FEE_RATE) if pd.notna(p) else 0
    )
    legs["exit_fees"] = legs.sell_shares * legs.avg_sell_px.fillna(0).apply(
        lambda p: poly_taker_fee_per_share(p, FEE_RATE) if pd.notna(p) else 0
    )
    legs["net_pnl"] = legs.realized_pnl + legs.leftover_pnl - legs.entry_fees - legs.exit_fees

    # Side-picking decode — does he agree with binance momentum?
    legs["mkt_asset"] = legs.mkt_asset.astype(object)
    res = legs[legs.resolved].copy()
    if len(res):
        def signal(r):
            if r.mkt_asset not in klines:
                return None
            end_us, prices = klines[r.mkt_asset]
            px_now = asof_strict(end_us, prices, int(r.slot_start_s) * 1_000_000)
            px_2m_ago = asof_strict(end_us, prices, (int(r.slot_start_s) - 120) * 1_000_000)
            if not (px_now and px_2m_ago):
                return None
            return "Up" if np.log(px_now / px_2m_ago) > 0 else "Down"
        res["binance_says"] = res.apply(signal, axis=1)
        res["matches_binance"] = res.outcome == res.binance_says
        wr_match = res[res.matches_binance].won.mean() if (res.matches_binance == True).any() else float("nan")
        wr_contra = res[~res.matches_binance & res.binance_says.notna()].won.mean() if (res.matches_binance == False).any() else float("nan")
    else:
        wr_match = wr_contra = float("nan")

    out = {
        "short": short,
        "n_legs": int(len(legs)),
        "n_resolved": int(res := int(legs.resolved.sum())),
        "won_pct_resolved": round(100 * legs[legs.resolved].won.mean(), 1) if legs.resolved.any() else 0,
        "wr_when_matches_binance": round(100 * wr_match, 1) if pd.notna(wr_match) else None,
        "wr_when_contradicts_binance": round(100 * wr_contra, 1) if pd.notna(wr_contra) else None,
        "realized_pnl_total": round(float(legs.realized_pnl.sum()), 2),
        "leftover_pnl_total": round(float(legs[legs.resolved].leftover_pnl.sum()), 2),
        "fees_total_in_out": round(float(legs.entry_fees.sum() + legs.exit_fees.sum()), 2),
        "net_pnl_resolved_only": round(float(legs[legs.resolved].net_pnl.sum()), 2),
        "pnl_per_resolved_leg": round(float(legs[legs.resolved].net_pnl.mean()), 4) if legs.resolved.any() else 0,
        "best_subgroup": None,
    }
    # Best subgroup
    best = None; best_val = -1e9
    for (tf, asset), sub in legs[legs.resolved].groupby(["tf", "mkt_asset"]):
        s = float(sub.net_pnl.sum())
        if s > best_val:
            best_val = s
            best = (tf, asset, len(sub), s, sub.won.mean())
    if best:
        out["best_subgroup"] = f"{best[1]} {best[0]}: n={best[2]} pnl=${best[3]:.0f} wr={best[4]*100:.1f}%"
    return out


def main():
    wallets = [
        "0xeebde7a0e019a63e6b476eb425505b7b3e6eba30",
        "0xce25e214d5cfe4f459cf67f08df581885aae7fdc",
        "0x89b5cdaaa4866c1e738406712012a630b4078beb",
        "0x7cde1da9d380bf8002ccbe8e0cb9474c4d71e48e",
        "0xcfb103c37c0234f524c632d964ed31f117b5f694",
        "0x04b6d7e930cf9e493c5e6ef24b496294f95594c8",
    ]

    # Load CLOB winners once
    print("Loading canonical resolutions...")
    canon = load_resolutions(source="upstream", with_clob_winner=True,
                              assets=["BTC", "ETH", "SOL"], timeframes=["5m", "15m"])
    win_col = "clob_winner" if "clob_winner" in canon.columns else "outcome"
    # Use chainlink outcome as fallback if clob missing
    if win_col == "clob_winner":
        canon[win_col] = canon[win_col].fillna(canon["outcome"])
    winners = canon.set_index("market_id")[win_col].to_dict()
    print(f"  loaded {len(winners):,} resolved markets (using {win_col})")

    # Klines for binance momentum decode
    print("Loading binance klines for side-decode...")
    klines = {a: load_klines_asof(a, source="binance-spot-ws", period_id="1MIN")
              for a in ("BTC", "ETH", "SOL")}

    # Fingerprint each
    print("\nFingerprinting...")
    fps = []
    for w in wallets:
        try:
            fp = fingerprint_wallet(w)
        except Exception as e:
            import traceback; traceback.print_exc()
            fp = {"short": w[:10], "error": str(e)[:60]}
        fps.append(fp)

    # PnL decode each
    print("\nPnL decoding (resolved markets, real Polymarket fees)...")
    pnls = []
    for w in wallets:
        pnl = decode_pnl(w, winners, klines)
        pnls.append(pnl)
        print(f"  {pnl['short']}: {pnl}")

    # Merge + print one summary
    merged = []
    for f, p in zip(fps, pnls):
        merged.append({**f, **{f"pnl_{k}": v for k, v in p.items() if k != "short"}})

    # Print table — KEY columns
    print("\n" + "=" * 160)
    print(f"{'wallet':<11} {'trades':>5} {'spnH':>4} {'tpm':>5} {'updwn%':>6} "
          f"{'med_px':>6} {'tr/leg':>6} {'BUY%':>5} {'bothS%':>6} "
          f"{'WR%':>5} {'matches':>7} {'contra':>6} {'$/leg':>7} {'class':<22}")
    print("-" * 160)
    for m in merged:
        if "error" in m:
            print(f"{m.get('short','-'):<11} ERROR: {m['error']}")
            continue
        cls = (m.get('strategy_class') or '-')[:22]
        print(f"{m.get('short','-'):<11} "
              f"{m.get('n_trades',0):>5} "
              f"{m.get('time_span_hours',0):>4.1f} "
              f"{m.get('trades_per_minute',0):>5.1f} "
              f"{m.get('up_down_focus_pct',0):>6.1f} "
              f"{(m.get('avg_buy_px_med') or 0):>6.3f} "
              f"{m.get('avg_trades_per_leg',0):>6.1f} "
              f"{m.get('side_BUY_pct',0):>5.1f} "
              f"{m.get('leg_pct_with_both_sides',0):>6.1f} "
              f"{(m.get('pnl_won_pct_resolved') or 0):>5.1f} "
              f"{(m.get('pnl_wr_when_matches_binance') or 0):>7.1f} "
              f"{(m.get('pnl_wr_when_contradicts_binance') or 0):>6.1f} "
              f"{(m.get('pnl_pnl_per_resolved_leg') or 0):>7.2f} "
              f"{cls:<22}")
    print()
    print("Best subgroups (resolved only):")
    for m in merged:
        if m.get('pnl_best_subgroup'):
            print(f"  {m.get('short')}: {m['pnl_best_subgroup']}")

    with open(CACHE / "_wallet_summary.json", "w") as f:
        json.dump(merged, f, indent=2, default=str)
    print(f"\nsaved cache/_wallet_summary.json")


if __name__ == "__main__":
    main()
