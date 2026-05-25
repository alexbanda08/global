"""Unit tests for canonical cash_pnl().

Three wallet archetypes covered:
  1. Pure-taker buy-and-hold-to-resolution (BDH) — TRADE buys + REDEEM only
  2. Paired-bid maker — TRADE buys+sells + MAKER_REBATE + REDEEM
  3. HFT scalper — TRADE buys+sells + MERGE + SPLIT + MAKER_REBATE

Run:
    py -X utf8 strategy_lab/wallet_hunt/test_cash_pnl.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cash_pnl import cash_pnl, maker_rebate_share


def _df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_pure_taker_bdh():
    """BDH wallet: buys at 0.40, holds, REDEEMs winners at $1.00.

    100 shares × $0.40 = $40 paid (TRADE BUY).
    60 shares × $1.00 = $60 redeemed (REDEEM).
    Realized = -40 + 60 = +20.
    """
    rows = [
        {"type": "TRADE",  "side": "BUY",  "usdcSize": 40.0},
        {"type": "REDEEM", "side": "",     "usdcSize": 60.0},
    ]
    r = cash_pnl(_df(rows))
    assert abs(r["realized"] - 20.0) < 1e-6, r
    assert r["unrealized"] == 0.0
    assert r["total"] == 20.0
    print("PASS  test_pure_taker_bdh         realized=$20")


def test_paired_bid_maker():
    """Paired-bid maker: bids both Up + Down at 0.45 each.

    Both fills, gets MAKER_REBATE on both, holds, one side REDEEMs.
        BUY Up   100 @ 0.45 → -$45
        BUY Down 100 @ 0.45 → -$45
        MAKER_REBATE                 +$1.20
        REDEEM (winner)              +$100
    Realized = -45 - 45 + 1.20 + 100 = +11.20.
    """
    rows = [
        {"type": "TRADE",        "side": "BUY", "usdcSize": 45.0},
        {"type": "TRADE",        "side": "BUY", "usdcSize": 45.0},
        {"type": "MAKER_REBATE", "side": "",    "usdcSize": 1.20},
        {"type": "REDEEM",       "side": "",    "usdcSize": 100.0},
    ]
    r = cash_pnl(_df(rows))
    assert abs(r["realized"] - 11.20) < 1e-6, r
    rebate = maker_rebate_share(_df(rows))
    # income total = 1.20 + 100 = 101.20; rebate / total = 0.01186
    assert abs(rebate - (1.20 / 101.20)) < 1e-6, rebate
    print(f"PASS  test_paired_bid_maker      realized=$11.20  "
          f"rebate_share={rebate:.4f}")


def test_hft_scalper_with_mint_and_merge():
    """HFT scalper: mints pairs via SPLIT, sells both sides, merges residual.

        SPLIT (mint 100 pairs)   -$100
        TRADE SELL 100 Up @ 0.55  +$55
        TRADE SELL 100 Dn @ 0.50  +$50
        MAKER_REBATE              +$2.00
        MERGE (recover 30 pairs)  +$30
    Realized = -100 + 55 + 50 + 2 + 30 = +37.
    """
    rows = [
        {"type": "SPLIT",        "side": "",     "usdcSize": 100.0},
        {"type": "TRADE",        "side": "SELL", "usdcSize": 55.0},
        {"type": "TRADE",        "side": "SELL", "usdcSize": 50.0},
        {"type": "MAKER_REBATE", "side": "",     "usdcSize": 2.0},
        {"type": "MERGE",        "side": "",     "usdcSize": 30.0},
    ]
    r = cash_pnl(_df(rows))
    assert abs(r["realized"] - 37.0) < 1e-6, r
    bd = r["breakdown"]
    assert bd["TRADE_buys"] == 0.0
    assert bd["TRADE_sells"] == 105.0
    assert bd["MERGE"] == 30.0
    assert bd["MAKER_REBATE"] == 2.0
    assert bd["SPLIT"] == -100.0
    print(f"PASS  test_hft_scalper           realized=$37.00  breakdown={bd}")


def test_unrealized_open_positions():
    """Open positions add unrealized."""
    act_rows = [
        {"type": "TRADE", "side": "BUY",  "usdcSize": 50.0},
        {"type": "TRADE", "side": "SELL", "usdcSize": 20.0},
    ]
    pos_df = pd.DataFrame([
        {"currentValue": 35.5},
        {"currentValue": 14.5},
    ])
    r = cash_pnl(_df(act_rows), positions_df=pos_df)
    assert abs(r["realized"] - (-30.0)) < 1e-6
    assert abs(r["unrealized"] - 50.0) < 1e-6
    assert abs(r["total"] - 20.0) < 1e-6
    print(f"PASS  test_unrealized            realized=-30  unrealized=50  total=20")


def test_empty_input():
    r = cash_pnl(pd.DataFrame())
    assert r["realized"] == 0.0
    assert r["unrealized"] == 0.0
    assert r["total"] == 0.0
    print("PASS  test_empty_input")


def test_signed_breakdown_consistency():
    """Sum of signed breakdown contributions should equal realized."""
    rows = [
        {"type": "TRADE",        "side": "BUY",  "usdcSize": 100.0},
        {"type": "TRADE",        "side": "SELL", "usdcSize": 80.0},
        {"type": "REDEEM",       "side": "",     "usdcSize": 50.0},
        {"type": "MERGE",        "side": "",     "usdcSize": 25.0},
        {"type": "MAKER_REBATE", "side": "",     "usdcSize": 3.0},
        {"type": "SPLIT",        "side": "",     "usdcSize": 40.0},
        {"type": "DEPOSIT",      "side": "",     "usdcSize": 10.0},
        {"type": "WITHDRAWAL",   "side": "",     "usdcSize": 5.0},
        {"type": "REWARD",       "side": "",     "usdcSize": 2.0},
        {"type": "CONVERSION",   "side": "",     "usdcSize": 7.0},
    ]
    r = cash_pnl(_df(rows))
    # Don't double-count TRADE_buys / TRADE_sells (TRADE_net captures both).
    bd_excl_net = {k: v for k, v in r["breakdown"].items()
                    if k not in ("TRADE_buys", "TRADE_sells")}
    s = sum(bd_excl_net.values())
    assert abs(s - r["realized"]) < 1e-6, (s, r["realized"], bd_excl_net)
    print(f"PASS  test_signed_breakdown      realized=${r['realized']}  sum={s}")


if __name__ == "__main__":
    test_pure_taker_bdh()
    test_paired_bid_maker()
    test_hft_scalper_with_mint_and_merge()
    test_unrealized_open_positions()
    test_empty_input()
    test_signed_breakdown_consistency()
    print("\nAll cash_pnl unit tests PASSED.")
