"""F2 trigger threshold tuning — find the exact firing rule.

Starting from the discovery that the strongest fire-vs-control discriminators are:
  - up_asz (top-of-book ask size)  z = +1.16
  - offset_s (time into slug)       z = +0.28
  - sum_asks                         z = +0.23
  - rtds_ret_60s                     z = +0.11

And direction is CONTRARIAN to binance momentum (pick Down when binance ret > 0).

This script:
  1. Loads cache/_f2_features.parquet
  2. Sweeps thresholds on (up_asz OR dn_asz), offset_s, sum_asks
  3. For each threshold combination, reports precision/recall vs fire moments
  4. Picks the tightest combination that captures >50% of fires with
     >5× the control rate.
  5. Verifies direction-picker rule (contrarian to binance_ret_60s).
  6. Outputs the discovered trigger as a python function string.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

CACHE = Path(__file__).resolve().parent / "cache"


def main():
    df = pd.read_parquet(CACHE / "_f2_features.parquet")
    df["max_asz"] = df[["up_asz", "dn_asz"]].max(axis=1)
    fire = df[df.is_fire == 1].copy()
    ctrl = df[df.is_fire == 0].copy()
    print(f"Loaded {len(df)} rows: fires={len(fire)}  controls={len(ctrl)}")
    print()

    # ---- 1. Size threshold sweep ----
    print("=" * 80)
    print("Top-of-book size at fire (max of up_asz, dn_asz)")
    print("=" * 80)
    for thr in (50, 100, 200, 300, 500, 700, 1000, 1500, 2000):
        sub_f = fire[fire["max_asz"] >= thr]
        sub_c = ctrl[ctrl["max_asz"] >= thr]
        if len(ctrl) == 0 or len(fire) == 0:
            continue
        recall = len(sub_f) / len(fire)
        ctrl_rate = len(sub_c) / len(ctrl)
        lift = recall / ctrl_rate if ctrl_rate > 0 else float("inf")
        print(f"  max_asz>={thr:5d}:  fire_recall={recall*100:5.1f}%  "
              f"ctrl_rate={ctrl_rate*100:5.1f}%  lift={lift:.2f}x")
    print()

    # ---- 2. Offset threshold sweep ----
    print("=" * 80)
    print("Time into slug at fire (offset_s)")
    print("=" * 80)
    for thr in (30, 60, 90, 120, 150, 180, 210, 240):
        sub_f = fire[fire["offset_s"] >= thr]
        sub_c = ctrl[ctrl["offset_s"] >= thr]
        recall = len(sub_f) / len(fire) if len(fire) else 0
        ctrl_rate = len(sub_c) / len(ctrl) if len(ctrl) else 0
        lift = recall / ctrl_rate if ctrl_rate > 0 else float("inf")
        print(f"  offset_s>={thr:3d}:  fire_recall={recall*100:5.1f}%  "
              f"ctrl_rate={ctrl_rate*100:5.1f}%  lift={lift:.2f}x")
    print()

    # ---- 3. sum_asks threshold ----
    print("=" * 80)
    print("Sum of asks at fire")
    print("=" * 80)
    for thr in (1.000, 1.005, 1.010, 1.015, 1.020, 1.030, 1.050):
        sub_f = fire[fire["sum_asks"] >= thr]
        sub_c = ctrl[ctrl["sum_asks"] >= thr]
        recall = len(sub_f) / len(fire) if len(fire) else 0
        ctrl_rate = len(sub_c) / len(ctrl) if len(ctrl) else 0
        lift = recall / ctrl_rate if ctrl_rate > 0 else float("inf")
        print(f"  sum_asks>={thr:.3f}:  fire_recall={recall*100:5.1f}%  "
              f"ctrl_rate={ctrl_rate*100:5.1f}%  lift={lift:.2f}x")
    print()

    # ---- 4. Combined trigger rule (best AND) ----
    print("=" * 80)
    print("Combined rule sweep: max_asz>=X AND offset>=Y AND sum_asks>=Z")
    print("=" * 80)
    best = None
    for asz_thr in (200, 500, 1000):
        for off_thr in (90, 120, 150, 180):
            for sa_thr in (1.005, 1.010, 1.015, 1.020):
                m_f = ((fire["max_asz"] >= asz_thr)
                        & (fire["offset_s"] >= off_thr)
                        & (fire["sum_asks"] >= sa_thr))
                m_c = ((ctrl["max_asz"] >= asz_thr)
                        & (ctrl["offset_s"] >= off_thr)
                        & (ctrl["sum_asks"] >= sa_thr))
                recall = m_f.sum() / max(len(fire), 1)
                ctrl_rate = m_c.sum() / max(len(ctrl), 1)
                lift = recall / ctrl_rate if ctrl_rate > 0 else float("inf")
                precision = m_f.sum() / max(m_f.sum() + m_c.sum(), 1)
                if recall > 0.30 and precision > 0.05:
                    rec = {"max_asz": asz_thr, "offset": off_thr, "sum_asks": sa_thr,
                           "recall": recall, "ctrl_rate": ctrl_rate, "lift": lift,
                           "precision": precision, "n_fire_match": int(m_f.sum()),
                           "n_ctrl_match": int(m_c.sum())}
                    if best is None or rec["lift"] > best["lift"]:
                        best = rec
                    print(f"  asz>={asz_thr:4d}  off>={off_thr:3d}  sa>={sa_thr:.3f}  "
                          f"recall={recall*100:5.1f}%  ctrl={ctrl_rate*100:5.1f}%  "
                          f"lift={lift:5.2f}x  prec={precision*100:5.1f}%  "
                          f"n_f={int(m_f.sum())}  n_c={int(m_c.sum())}")

    print()
    if best:
        print(f"BEST RULE: {json.dumps(best, indent=2, default=str)}")

    # ---- 5. Direction picker accuracy at best threshold ----
    print()
    print("=" * 80)
    print("Direction picker @ best fire-rule")
    print("=" * 80)
    if best:
        fire_in_rule = fire[
            (fire["max_asz"] >= best["max_asz"])
            & (fire["offset_s"] >= best["offset"])
            & (fire["sum_asks"] >= best["sum_asks"])
        ]
        single = fire_in_rule[fire_in_rule.outcomes_picked.isin(["Up", "Down"])]
        print(f"  fires matching rule: {len(fire_in_rule)}")
        print(f"  single-leg fires: {len(single)}")
        if len(single) > 30:
            single = single.copy()
            single["picked_up"] = (single.outcomes_picked == "Up").astype(int)
            # Contrarian rule: pick Up when binance went DOWN, else pick Down
            single["rule_pick_up"] = (single.binance_ret_60s < 0).astype(int)
            single["matches"] = single.picked_up == single.rule_pick_up
            print(f"  contrarian rule match (binance_ret_60s sign-flipped): "
                  f"{single.matches.mean()*100:.2f}%")

            # Threshold-based: only fire when |binance_ret_60s| > thr
            for thr_bp in (1, 2, 3, 5):
                thr = thr_bp / 10000.0
                strong = single[single.binance_ret_60s.abs() > thr]
                if len(strong) > 5:
                    strong = strong.copy()
                    strong["rule_pick_up"] = (strong.binance_ret_60s < 0).astype(int)
                    strong["matches"] = strong.picked_up == strong.rule_pick_up
                    print(f"  |ret_60s|>{thr_bp}bp: n={len(strong):4d}  "
                          f"contrarian_match={strong.matches.mean()*100:5.1f}%")

    # ---- 6. Output the trigger ----
    print()
    print("=" * 80)
    print("Discovered trigger formula")
    print("=" * 80)
    if best:
        trigger = f"""
def f2_should_fire(book_up_ask: float, book_up_ask_size: float,
                    book_down_ask: float, book_down_ask_size: float,
                    binance_ret_60s: float,
                    offset_from_slot_start_s: int) -> tuple[bool, str | None]:
    \"\"\"Return (fire, direction). Direction is contrarian to binance_ret_60s.\"\"\"
    sum_asks = book_up_ask + book_down_ask
    max_asz = max(book_up_ask_size, book_down_ask_size)

    if max_asz < {best['max_asz']}:
        return False, None
    if offset_from_slot_start_s < {best['offset']}:
        return False, None
    if sum_asks < {best['sum_asks']}:
        return False, None
    # Skip if binance signal too weak (sub-bp)
    if abs(binance_ret_60s) < 1e-4:
        return False, None

    # Contrarian direction: fade binance recent move
    direction = "Down" if binance_ret_60s > 0 else "Up"
    return True, direction
"""
        print(trigger)
        (CACHE / "_f2_trigger_rule.py").write_text(trigger)
        print(f"saved -> {CACHE / '_f2_trigger_rule.py'}")


if __name__ == "__main__":
    main()
