"""Phase 0 sanity tests — skeleton wires correctly without breaking the engine.

Run with:
    py -X utf8 -m strategy_lab.confluence.tests.test_skeleton

Validates:
  T1. Imports work (no circular imports, clean package layout).
  T2. tier_classifier.classify() with all-None inputs returns SKIP.
  T3. tier_classifier.classify() with hand-fed GOLD inputs returns GOLD.
  T4. enrich_universe() on a tiny df adds all expected feature columns.
  T5. apply_classifier() on a NaN-filled enriched df marks all rows SKIP.
  T6. summarize() reports skip_rate=1.0 when no layers built (Phase 0 state).
  T7. diagnose_no_op() returns the expected Phase-0 shape on a real universe sample.

NO backtest is run here — that's Phase 1 G1 gate territory.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT))


def _make_fake_universe(n: int = 5) -> pd.DataFrame:
    """Tiny fake universe just for shape testing — not a real backtest."""
    return pd.DataFrame({
        "slug": [f"btc-updown-5m-{1714766100 + i*300}" for i in range(n)],
        "asset": ["btc"] * n,
        "timeframe": ["5m"] * n,
        "window_start_unix": [1714766100 + i*300 for i in range(n)],
        "outcome_up": [(i % 2) for i in range(n)],
    })


def test_t1_imports() -> None:
    from strategy_lab.confluence import classify, enrich_universe, SKIP, BANKROLL_DEFAULT
    from strategy_lab.confluence import schema, tier_classifier, feature_join, sleeve_runner
    assert SKIP["tier"] == "SKIP"
    assert BANKROLL_DEFAULT > 0
    print("[T1] imports OK")


def test_t2_classify_none_inputs() -> None:
    from strategy_lab.confluence.tier_classifier import classify
    r = classify(structure_score=None, flow_score=None, trigger_active=None)
    assert r["tier"] == "SKIP"
    assert r["skip_reasons"] == ("missing_features",)
    print("[T2] None inputs → SKIP(missing_features) OK")


def test_t3_classify_gold() -> None:
    from strategy_lab.confluence.tier_classifier import classify
    r = classify(structure_score=0.6, flow_score=0.6, trigger_active=True)
    assert r["tier"] == "GOLD", f"got {r['tier']}"
    assert r["fair_prob"] == 0.72
    assert r["size_pct"] == 0.020
    # Now break GOLD → SILVER (no trigger)
    r2 = classify(structure_score=0.6, flow_score=0.6, trigger_active=False)
    assert r2["tier"] == "SILVER", f"got {r2['tier']}"
    # Bronze (low struct, but flow + trigger)
    r3 = classify(structure_score=0.1, flow_score=0.5, trigger_active=True)
    assert r3["tier"] == "BRONZE", f"got {r3['tier']}"
    # Guard wins even on GOLD-eligible
    r4 = classify(structure_score=0.6, flow_score=0.6, trigger_active=True,
                   guard_blocks=("guard_extreme_price",))
    assert r4["tier"] == "SKIP"
    assert "guard_extreme_price" in r4["skip_reasons"]
    print("[T3] GOLD/SILVER/BRONZE/guard logic OK")


def test_t4_enrich_columns() -> None:
    from strategy_lab.confluence.feature_join import enrich_universe
    from strategy_lab.confluence.schema import ALL_FEATURE_COLS
    df = _make_fake_universe()
    out = enrich_universe(df)
    missing = set(ALL_FEATURE_COLS) - set(out.columns)
    assert not missing, f"enrich_universe missed columns: {missing}"
    assert len(out) == len(df), "row count must not change"
    print(f"[T4] enrich_universe added {len(ALL_FEATURE_COLS)} feature cols OK")


def test_t5_apply_classifier_skip_all_phase0() -> None:
    from strategy_lab.confluence.feature_join import apply_classifier, enrich_universe
    df = _make_fake_universe()
    enr = enrich_universe(df)
    cls = apply_classifier(enr)
    assert (cls["tier"] == "SKIP").all(), "Phase 0: all rows must be SKIP (no features)"
    assert (cls["size_pct"] == 0.0).all()
    print("[T5] Phase-0 all-SKIP behavior OK")


def test_t6_summarize_phase0() -> None:
    from strategy_lab.confluence.feature_join import apply_classifier, enrich_universe, summarize
    df = _make_fake_universe(n=10)
    enr = enrich_universe(df)
    cls = apply_classifier(enr)
    s = summarize(cls)
    assert s["skip_rate"] == 1.0
    assert s["fire_rate"] == 0.0
    assert s["tier_counts"]["SKIP"] == 10
    print(f"[T6] Phase-0 summary OK: {s}")


def test_t7_diagnose_real_universe() -> None:
    """Optional: only runs if real refresh data is on disk."""
    refresh = ROOT / "data" / "v4" / "refresh_2026_05_06" / "market_resolutions_full.csv"
    if not refresh.exists():
        print(f"[T7] SKIP — no real refresh data at {refresh}")
        return
    from strategy_lab.meta_classifier.extended_backtest_with_robustness import load_universe
    from strategy_lab.confluence.sleeve_runner import diagnose_no_op
    uni = load_universe()
    sample = uni.head(200)
    s = diagnose_no_op(sample)
    assert s["skip_rate"] == 1.0, "real universe must also all-SKIP in Phase 0"
    print(f"[T7] Real universe (n=200) diagnose_no_op OK: skip_rate={s['skip_rate']:.2f}, coverage={s['feature_coverage']}")


def main() -> int:
    tests = [
        test_t1_imports,
        test_t2_classify_none_inputs,
        test_t3_classify_gold,
        test_t4_enrich_columns,
        test_t5_apply_classifier_skip_all_phase0,
        test_t6_summarize_phase0,
        test_t7_diagnose_real_universe,
    ]
    fails = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            print(f"[{t.__name__}] FAIL: {e}")
            fails += 1
        except Exception as e:
            print(f"[{t.__name__}] ERROR: {type(e).__name__}: {e}")
            fails += 1
    print(f"\n{'OK' if fails == 0 else f'{fails} FAILED'}  ({len(tests)} tests)")
    return fails


if __name__ == "__main__":
    raise SystemExit(main())
