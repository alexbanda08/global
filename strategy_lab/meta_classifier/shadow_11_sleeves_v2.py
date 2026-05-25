"""Shadow sleeves backtest v2 — refreshed HoD + sleeve variant matrix.

Builds on shadow_11_sleeves_backtest.py with three additions per
HANDOFF_2026_05_22_MOMO_F7_MARKOV.md next-session priorities:

  1. Use REFRESHED HoD-Top-8 from _recompute_hod_top8.py output, compare
     to baseline (current shipped HoD).
  2. Sleeve #3 (momo v1 btc_15m): add M1V Markov variant — handoff
     hypothesis: spec's 70-85% WR claim came from M1V or F7+M1V, not
     pure HoD.
  3. Sleeve #2 (sniper eth_15m _hod_m5va) Markov inversion: test 4
     alternatives:
       (a) Anchor M5V Markov at SIGNAL time (slot_start - window_s)
           instead of fire_us = slot_start
       (b) M1V (1-min vol-adaptive) instead of M5V
       (c) M5F (5-min fixed-threshold) instead of vol-adaptive
       (d) Drop Markov entirely (HoD only)

OUTPUT:
  data/v4/canonical/_results/shadow_11_sleeves_v2.csv
  strategy_lab/reports/SHADOW_11_SLEEVES_V2_<run_date>.md
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab" / "markov_filter"))

from load import load_klines_asof  # noqa: E402
from markov_regime_micro import build_labels_for_asset, regime_at_us, BEAR, BULL  # noqa: E402

EV = ROOT / "data" / "v4" / "canonical" / "trading_events_30d.parquet"
RESULTS_DIR = ROOT / "data" / "v4" / "canonical" / "_results"
OUT_CSV = RESULTS_DIR / "shadow_11_sleeves_v2.csv"
HOD_REFRESH_DIR = (
    ROOT / "strategy_lab" / "markov_filter" / "_results" / "hod_refresh"
)

# Currently shipped HoD-Top-8 (baseline for comparison).
CURRENT_HOD: dict[tuple[str, str], list[int]] = {
    ("sniper",  "sol_5m"):  [0, 1, 2, 4, 8, 15, 19, 23],
    ("sniper",  "eth_15m"): [0, 6, 7, 9, 13, 14, 19, 22],
    ("momo",    "btc_15m"): [0, 1, 3, 5, 9, 14, 16, 20],
    ("sniper",  "btc_15m"): [0, 3, 10, 11, 12, 13, 14, 15],
    ("sniper",  "btc_5m"):  [0, 1, 3, 5, 12, 15, 19, 21],
    ("momo_v2", "btc_5m"):  [0, 2, 5, 6, 10, 12, 21, 23],
    ("momo_v2", "btc_15m"): [1, 11, 12, 16, 18, 20, 21, 22],
    ("momo_v2", "sol_5m"):  [4, 5, 6, 8, 10, 12, 14, 17],
    ("momo_v2", "eth_15m"): [0, 5, 8, 12, 16, 17, 20, 22],
    ("momo_v2", "sol_15m"): [1, 2, 5, 12, 13, 16, 17, 21],
    ("sniper",  "eth_5m"):  [0, 2, 11, 13, 14, 17, 20, 21],
}

# Canonical 11 sleeve definitions from the spec.
SHADOW_SLEEVES = [
    (1,  "poly_updown_sol_5m_sniper_hod",       "sniper",  "SOL", "5m",  ["hod"]),
    (2,  "poly_updown_eth_15m_sniper_hod_m5va", "sniper",  "ETH", "15m", ["hod", "m5va"]),
    (3,  "poly_updown_btc_15m_momo_hod",        "momo",    "BTC", "15m", ["hod"]),
    (4,  "poly_updown_btc_15m_sniper_hod",      "sniper",  "BTC", "15m", ["hod"]),
    (5,  "poly_updown_btc_5m_sniper_hod",       "sniper",  "BTC", "5m",  ["hod"]),
    (6,  "poly_updown_btc_5m_momo_v2_hod_mtf",  "momo_v2", "BTC", "5m",  ["hod", "mtf2"]),
    (7,  "poly_updown_btc_15m_momo_v2_hod",     "momo_v2", "BTC", "15m", ["hod"]),
    (8,  "poly_updown_sol_5m_momo_v2_hod",      "momo_v2", "SOL", "5m",  ["hod"]),
    (9,  "poly_updown_eth_15m_momo_v2_hod",     "momo_v2", "ETH", "15m", ["hod"]),
    (10, "poly_updown_sol_15m_momo_v2_hod",     "momo_v2", "SOL", "15m", ["hod"]),
    (11, "poly_updown_eth_5m_sniper_hod",       "sniper",  "ETH", "5m",  ["hod"]),
]

# Extra variants for the two priority sleeves.
EXTRA_VARIANTS = [
    # Sleeve #3 (momo v1 btc_15m) — add Markov & F7 stacks
    ("3.1", "btc_15m_momo_hod_m1va",       "momo",    "BTC", "15m", ["hod", "m1va"]),
    ("3.2", "btc_15m_momo_hod_m5va",       "momo",    "BTC", "15m", ["hod", "m5va"]),
    ("3.3", "btc_15m_momo_hod_f7",         "momo",    "BTC", "15m", ["hod", "f7"]),
    ("3.4", "btc_15m_momo_hod_f7_m1va",    "momo",    "BTC", "15m", ["hod", "f7", "m1va"]),
    # Sleeve #2 (sniper eth_15m) — investigate Markov inversion
    ("2.1", "eth_15m_sniper_hod_m5va_sig", "sniper",  "ETH", "15m", ["hod", "m5va_sig"]),
    ("2.2", "eth_15m_sniper_hod_m1va",     "sniper",  "ETH", "15m", ["hod", "m1va"]),
    ("2.3", "eth_15m_sniper_hod_m5f",      "sniper",  "ETH", "15m", ["hod", "m5f"]),
    ("2.4", "eth_15m_sniper_hod_only",     "sniper",  "ETH", "15m", ["hod"]),
]

EXPECTED = {
    1:  ("~65/wk",  "65-70%", "+$6 to +$10"),
    2:  ("~25/wk",  "70-80%", "+$10 to +$16"),
    3:  ("~20/wk",  "70-85%", "+$10 to +$16"),
    4:  ("~100/wk", "55-62%", "+$3 to +$5"),
    5:  ("~110/wk", "55-60%", "+$2 to +$4"),
    6:  ("~60/wk",  "58-65%", "+$3 to +$6"),
    7:  ("~35/wk",  "65-72%", "+$6 to +$9"),
    8:  ("~50/wk",  "58-65%", "+$3 to +$6"),
    9:  ("~25/wk",  "65-72%", "+$6 to +$10"),
    10: ("~18/wk",  "65-75%", "+$6 to +$10"),
    11: ("~80/wk",  "50-58%", "+$0 to +$3"),
}


# ---------------------------------------------------------------------------
# Helpers — payload parsing, family classification, gate primitives.
# ---------------------------------------------------------------------------

def classify_family(sleeve_id: str) -> str:
    if not isinstance(sleeve_id, str):
        return "unknown"
    s = sleeve_id.replace("poly_updown_", "")
    for suf in ("_HOLD", "_HEDGE", "_SELL"):
        if s.endswith(suf):
            s = s[: -len(suf)]
    if any(tok in s for tok in ("_f7", "_hod", "_INV", "_DOWN_INV", "_NIGHT")):
        return "modified"
    if "momo_v2" in s:
        return "momo_v2"
    if s.endswith("_momo") or "_momo_" in s:
        return "momo"
    if s.endswith("_sniper") or "_sniper_" in s:
        return "sniper"
    return "other"


def parse_payload(s):
    if isinstance(s, dict):
        return s
    try:
        return json.loads(s)
    except Exception:
        return {}


def asof_close(end_us: np.ndarray, prices: np.ndarray, target_us: int) -> float:
    """Causal close at-or-before target_us."""
    i = int(np.searchsorted(end_us, target_us, side="right")) - 1
    if i < 0 or i >= len(prices):
        return float("nan")
    return float(prices[i])


def ret_log(end_us: np.ndarray, prices: np.ndarray, t0_us: int, t1_us: int) -> float:
    c0 = asof_close(end_us, prices, t0_us)
    c1 = asof_close(end_us, prices, t1_us)
    if not (math.isfinite(c0) and math.isfinite(c1) and c0 > 0 and c1 > 0):
        return float("nan")
    return math.log(c1 / c0)


def rsi_at_anchor_us(end_us: np.ndarray, prices: np.ndarray, anchor_us: int) -> float:
    """Production-matching simple-mean Wilder RSI(14): 15 closes at offsets
    [-840, -780, ..., -60, 0] from anchor."""
    closes: list[float] = []
    for off_s in range(-840, 1, 60):
        c = asof_close(end_us, prices, anchor_us + off_s * 1_000_000)
        closes.append(c)
    if any(not math.isfinite(c) or c <= 0 for c in closes) or len(closes) < 15:
        return float("nan")
    arr = np.asarray(closes, dtype=np.float64)
    log_rets = np.log(arr[1:] / arr[:-1])
    gains = np.where(log_rets > 0, log_rets, 0.0).mean()
    losses = np.where(log_rets < 0, -log_rets, 0.0).mean()
    if losses == 0:
        return 100.0 if gains > 0 else 50.0
    if gains == 0:
        return 0.0
    rs = gains / losses
    return 100.0 - 100.0 / (1.0 + rs)


def hod_passes(fire_hour: int, allowed_hours) -> bool:
    return int(fire_hour) in set(allowed_hours)


def mtf2_passes(signal: str, ret_15m: float, ret_1h: float) -> bool:
    if signal not in ("UP", "DOWN"):
        return True
    if not (math.isfinite(ret_15m) and math.isfinite(ret_1h)):
        return False
    if signal == "UP":
        return ret_15m > 0 and ret_1h > 0
    return ret_15m < 0 and ret_1h < 0


def markov_passes(signal: str, regime: int) -> bool:
    if regime < 0:
        return False
    if signal == "UP":
        return regime == BULL
    if signal == "DOWN":
        return regime == BEAR
    return False


def f7_passes(signal: str, rsi: float) -> bool:
    if not math.isfinite(rsi):
        return False
    if signal == "UP":
        return rsi > 50
    if signal == "DOWN":
        return rsi < 50
    return False


# ---------------------------------------------------------------------------
# Data loading.
# ---------------------------------------------------------------------------

def load_events(window_days: int = 28) -> pd.DataFrame:
    print(f"[1] loading {EV.name}...")
    df = pd.read_parquet(EV)
    df = df[df.kind == "poly_updown_resolution"].copy()
    df["at_ts"] = pd.to_datetime(df["at"], utc=True, format="mixed", errors="coerce")
    df = df[df.at_ts.notna()].copy()
    df["p"] = df.data.apply(parse_payload)
    df["symbol"] = df.p.apply(lambda d: d.get("symbol"))
    df["tf"] = df.p.apply(lambda d: d.get("tf"))
    df["signal"] = df.p.apply(lambda d: d.get("signal"))
    df["won"] = df.p.apply(lambda d: bool(d.get("won")))
    df["pnl_usd"] = pd.to_numeric(df.p.apply(lambda d: d.get("pnl_usd")), errors="coerce")
    df["fam"] = df.sleeve_id.apply(classify_family)

    df = df[
        df.fam.isin(("momo", "momo_v2", "sniper"))
        & df.symbol.isin(("BTC", "ETH", "SOL"))
        & df.tf.isin(("5m", "15m"))
        & df.pnl_usd.notna()
    ].copy()

    max_ts = df.at_ts.max()
    cutoff = max_ts - pd.Timedelta(days=window_days)
    df = df[df.at_ts >= cutoff].copy()

    df["window_s"] = df.tf.map({"5m": 300, "15m": 900}).astype("int64")
    at_s = (df.at_ts.astype("int64") // 1_000_000_000).astype("int64")
    df["at_s"] = at_s
    fire_s = np.where(
        df.fam.values == "momo",
        at_s - 2 * df.window_s.values + 120,
        np.where(
            df.fam.values == "momo_v2",
            at_s - 2 * df.window_s.values + 60,
            at_s - df.window_s.values,
        ),
    )
    df["fire_s"] = fire_s
    # signal_s = ws_s = slot_start - window_s = at_s - 2*window_s (all families).
    df["signal_s"] = at_s - 2 * df.window_s.values
    df["fire_us"] = (df.fire_s.astype("int64") * 1_000_000)
    df["signal_us"] = (df.signal_s.astype("int64") * 1_000_000)
    df["fire_ts"] = pd.to_datetime(df.fire_s, unit="s", utc=True)
    df["fire_hour"] = df.fire_ts.dt.hour
    df["cell"] = df.symbol.str.lower() + "_" + df.tf

    print(f"    {len(df):,} fires after {window_days}d window clamp")
    print(f"    span: {df.at_ts.min()} -> {df.at_ts.max()}")
    return df


def load_klines_per_asset() -> dict:
    print("[2] loading 1MIN + 5MIN binance-spot-ws klines for BTC/ETH/SOL...")
    out = {}
    for a in ("BTC", "ETH", "SOL"):
        eu1, cl1 = load_klines_asof(a, "binance-spot-ws", "1MIN")
        eu5, cl5 = load_klines_asof(a, "binance-spot-ws", "5MIN")
        out[a] = {
            "1m": (eu1.astype("int64"), cl1.astype("float64")),
            "5m": (eu5.astype("int64"), cl5.astype("float64")),
        }
        print(f"    {a}: 1MIN n={len(eu1):,}  5MIN n={len(eu5):,}")
    return out


def load_markov_labels() -> dict:
    """Build M1V, M5V, M5F label arrays per asset."""
    print("[3] building Markov label arrays (M1V, M5V, M5F) per asset...")
    out = {}
    for a in ("BTC", "ETH", "SOL"):
        m1v_eu, _, m1v_lab = build_labels_for_asset(
            a, window_bars=20, bar_minutes=1, mode="vol_adaptive"
        )
        m5v_eu, _, m5v_lab = build_labels_for_asset(
            a, window_bars=20, bar_minutes=5, mode="vol_adaptive"
        )
        m5f_eu, _, m5f_lab = build_labels_for_asset(
            a, window_bars=20, bar_minutes=5, mode="fixed", fixed_threshold=0.003,
        )
        out[a] = {
            "m1v": (m1v_eu.astype("int64"), m1v_lab.astype("int8")),
            "m5v": (m5v_eu.astype("int64"), m5v_lab.astype("int8")),
            "m5f": (m5f_eu.astype("int64"), m5f_lab.astype("int8")),
        }
        c = lambda lab: {int(k): int(v) for k, v in zip(*np.unique(lab[lab >= 0], return_counts=True))}
        print(f"    {a}: M1V valid={int((m1v_lab>=0).sum()):>6}  "
              f"M5V valid={int((m5v_lab>=0).sum()):>5}  "
              f"M5F valid={int((m5f_lab>=0).sum()):>5}  | M5V dist={c(m5v_lab)}")
    return out


def load_refreshed_hod() -> dict[tuple[str, str], list[int]]:
    """Read the latest hod_refresh output."""
    if not HOD_REFRESH_DIR.exists():
        print("    [WARN] no hod_refresh dir - falling back to CURRENT_HOD only")
        return CURRENT_HOD
    runs = sorted(p for p in HOD_REFRESH_DIR.iterdir() if p.is_dir())
    if not runs:
        print("    [WARN] no hod_refresh runs - falling back to CURRENT_HOD only")
        return CURRENT_HOD
    latest = runs[-1]
    f = latest / "new_hod_top8.json"
    if not f.exists():
        print(f"    [WARN] {f} missing - falling back to CURRENT_HOD")
        return CURRENT_HOD
    raw = json.loads(f.read_text())
    refreshed = {tuple(k.split("__")): v for k, v in raw.items()}
    print(f"[*] loaded refreshed HoD from {latest.name} ({len(refreshed)} cells)")
    return refreshed


# ---------------------------------------------------------------------------
# Gate stack evaluation.
# ---------------------------------------------------------------------------

def evaluate_sleeve(
    df: pd.DataFrame,
    fam: str, asset: str, tf: str,
    gate_stack: list[str],
    hod_top8: dict[tuple[str, str], list[int]],
    klines: dict,
    markov: dict,
) -> dict:
    """Apply a gate stack to base sleeve fires; return stats dict."""
    cell = f"{asset.lower()}_{tf}"
    base = df[(df.fam == fam) & (df.symbol == asset) & (df.tf == tf)].copy()
    n_base = len(base)
    if n_base == 0:
        return dict(n_base=0, n_kept=0, wr=0.0, sum_pnl=0.0, per_trade=0.0,
                    n_per_week=0.0, skip_counts={})

    keep = pd.Series(True, index=base.index)
    skip = {g: 0 for g in gate_stack}

    # 1. HoD-Top-8 on FIRE hour
    if "hod" in gate_stack:
        allowed = hod_top8.get((fam, cell), [])
        mask = base.fire_hour.isin(allowed)
        skip["hod"] = int((keep & ~mask).sum())
        keep &= mask

    # 2. MTF2
    if "mtf2" in gate_stack:
        eu1, cl1 = klines[asset]["1m"]
        sub_idx = base.index[keep]
        m = pd.Series(False, index=base.index)
        for idx in sub_idx:
            r = base.loc[idx]
            t1 = int(r.fire_us)
            r15 = ret_log(eu1, cl1, t1 - 900 * 1_000_000, t1)
            r1h = ret_log(eu1, cl1, t1 - 3600 * 1_000_000, t1)
            if mtf2_passes(r.signal, r15, r1h):
                m[idx] = True
        skip["mtf2"] = int((keep & ~m).sum())
        keep &= m

    # 3. F7 RSI gate (binance 1m, ws_s anchor — verified 94.67% match prod)
    if "f7" in gate_stack:
        eu1, cl1 = klines[asset]["1m"]
        sub_idx = base.index[keep]
        m = pd.Series(False, index=base.index)
        for idx in sub_idx:
            r = base.loc[idx]
            ws_us = int(r.signal_us)   # signal_s = ws_s
            rsi = rsi_at_anchor_us(eu1, cl1, ws_us)
            if f7_passes(r.signal, rsi):
                m[idx] = True
        skip["f7"] = int((keep & ~m).sum())
        keep &= m

    # 4. Markov gates (m1va, m5va, m5va_sig, m5f)
    markov_gates = {
        "m1va":     ("m1v", "fire_us"),
        "m5va":     ("m5v", "fire_us"),
        "m5va_sig": ("m5v", "signal_us"),
        "m5f":      ("m5f", "fire_us"),
    }
    for gate, (lbl_key, ts_col) in markov_gates.items():
        if gate not in gate_stack:
            continue
        eu, lbl = markov[asset][lbl_key]
        sub_idx = base.index[keep]
        m = pd.Series(False, index=base.index)
        for idx in sub_idx:
            r = base.loc[idx]
            target_us = int(r[ts_col])
            regime = regime_at_us(eu, lbl, target_us)
            if markov_passes(r.signal, regime):
                m[idx] = True
        skip[gate] = int((keep & ~m).sum())
        keep &= m

    kept = base[keep]
    n = len(kept)
    wr = float(kept.won.mean()) if n else 0.0
    sum_pnl = float(kept.pnl_usd.sum()) if n else 0.0
    per_trade = float(kept.pnl_usd.mean()) if n else 0.0
    span_days = max((base.at_ts.max() - base.at_ts.min()).days, 1)
    n_per_week = n / span_days * 7

    return dict(
        n_base=n_base, n_kept=n,
        wr=wr, sum_pnl=sum_pnl, per_trade=per_trade,
        n_per_week=n_per_week,
        skip_counts=skip,
    )


# ---------------------------------------------------------------------------
# Main.
# ---------------------------------------------------------------------------

def main() -> int:
    df = load_events(window_days=28)
    klines = load_klines_per_asset()
    markov = load_markov_labels()
    refreshed_hod = load_refreshed_hod()

    rows = []

    # Pass A: 11 canonical sleeves with BOTH current and refreshed HoD.
    print("\n[4] PASS A — 11 canonical sleeves × {current, refreshed} HoD")
    for hod_label, hod in (("current", CURRENT_HOD), ("refreshed", refreshed_hod)):
        for sid, sleeve_id, fam, asset, tf, gates in SHADOW_SLEEVES:
            stats = evaluate_sleeve(df, fam, asset, tf, gates, hod, klines, markov)
            exp_n, exp_wr, exp_per = EXPECTED.get(sid, ("?", "?", "?"))
            row = dict(
                pass_id="A", hod=hod_label,
                sid=str(sid), sleeve_id=sleeve_id, fam=fam, asset=asset, tf=tf,
                gates="+".join(gates),
                n_base=stats["n_base"], n_kept=stats["n_kept"],
                n_per_week=round(stats["n_per_week"], 1),
                wr_pct=round(stats["wr"] * 100, 2),
                sum_pnl=round(stats["sum_pnl"], 2),
                per_trade=round(stats["per_trade"], 3),
                skip=json.dumps(stats["skip_counts"]),
                expected_n=exp_n, expected_wr=exp_wr, expected_per=exp_per,
            )
            rows.append(row)
            print(f"  [{hod_label:>9}] #{sid:>2} {sleeve_id:<42} "
                  f"base={stats['n_base']:>4} kept={stats['n_kept']:>4}  "
                  f"WR={stats['wr']*100:>5.2f}% ${stats['per_trade']:>+7.3f}  "
                  f"sum=${stats['sum_pnl']:>+8.2f}  [exp {exp_wr}, {exp_per}]")

    # Pass B: extra variants for sleeves #2 and #3 with REFRESHED HoD.
    print("\n[5] PASS B — extra variants for sleeves #2, #3 (refreshed HoD)")
    for sid, sleeve_id, fam, asset, tf, gates in EXTRA_VARIANTS:
        stats = evaluate_sleeve(df, fam, asset, tf, gates, refreshed_hod, klines, markov)
        row = dict(
            pass_id="B", hod="refreshed",
            sid=sid, sleeve_id=sleeve_id, fam=fam, asset=asset, tf=tf,
            gates="+".join(gates),
            n_base=stats["n_base"], n_kept=stats["n_kept"],
            n_per_week=round(stats["n_per_week"], 1),
            wr_pct=round(stats["wr"] * 100, 2),
            sum_pnl=round(stats["sum_pnl"], 2),
            per_trade=round(stats["per_trade"], 3),
            skip=json.dumps(stats["skip_counts"]),
            expected_n="-", expected_wr="-", expected_per="-",
        )
        rows.append(row)
        print(f"  [refreshed] #{sid:<5} {sleeve_id:<35} "
              f"base={stats['n_base']:>4} kept={stats['n_kept']:>4}  "
              f"WR={stats['wr']*100:>5.2f}% ${stats['per_trade']:>+7.3f}  "
              f"sum=${stats['sum_pnl']:>+8.2f}")

    out = pd.DataFrame(rows)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_CSV, index=False)
    print(f"\nSaved CSV: {OUT_CSV}")

    write_markdown_report(out)

    return 0


def write_markdown_report(out: pd.DataFrame) -> None:
    run_date = datetime.now(timezone.utc).strftime("%Y_%m_%d")
    report_path = (
        ROOT / "strategy_lab" / "reports" / f"SHADOW_11_SLEEVES_V2_{run_date}.md"
    )
    md: list[str] = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    md.append(f"# Shadow sleeves v2 - refreshed HoD + variants ({now})")
    md.append("")
    md.append("Re-runs 11 canonical sleeves with both current and refreshed HoD, "
              "and adds 8 extra variants for the two priority sleeves (#2, #3) "
              "per HANDOFF_2026_05_22 next steps.")
    md.append("")

    md.append("## Pass A — 11 canonical sleeves: current vs refreshed HoD")
    md.append("")
    pivot = out[out.pass_id == "A"].pivot_table(
        index=["sid", "sleeve_id"], columns="hod",
        values=["n_kept", "wr_pct", "per_trade", "sum_pnl"],
        aggfunc="first",
    )
    md.append("| # | sleeve | n (cur→ref) | WR% (cur→ref) | $/tr (cur→ref) | sum$ (cur→ref) |")
    md.append("|--:|---|---|---|---|---|")
    for (sid, sleeve_id), r in pivot.iterrows():
        try:
            md.append(
                f"| {sid} | `{sleeve_id}` | "
                f"{int(r[('n_kept','current')])}->{int(r[('n_kept','refreshed')])} | "
                f"{r[('wr_pct','current')]:.2f}->{r[('wr_pct','refreshed')]:.2f} | "
                f"${r[('per_trade','current')]:+.3f}->${r[('per_trade','refreshed')]:+.3f} | "
                f"${r[('sum_pnl','current')]:+.2f}->${r[('sum_pnl','refreshed')]:+.2f} |"
            )
        except Exception:
            md.append(f"| {sid} | `{sleeve_id}` | (data err) | - | - | - |")
    md.append("")

    md.append("## Pass B — Sleeve #3 variants (momo v1 btc_15m)")
    md.append("")
    md.append("Tests handoff hypothesis: spec's 70-85% WR claim came from M1V or "
              "F7+M1V, not pure HoD.")
    md.append("")
    md.append("| # | gate stack | n | WR% | $/tr | sum$ |")
    md.append("|--:|---|--:|--:|--:|--:|")
    s3 = out[(out.pass_id == "B") & out.sid.str.startswith("3.")].copy()
    s3_base = out[(out.pass_id == "A") & (out.hod == "refreshed") & (out.sid == "3")]
    if len(s3_base):
        r = s3_base.iloc[0]
        md.append(f"| 3 (baseline, refreshed HoD) | `{r.gates}` | {int(r.n_kept)} | "
                  f"{r.wr_pct:.2f} | ${r.per_trade:+.3f} | ${r.sum_pnl:+.2f} |")
    for _, r in s3.iterrows():
        md.append(f"| {r.sid} | `{r.gates}` | {int(r.n_kept)} | "
                  f"{r.wr_pct:.2f} | ${r.per_trade:+.3f} | ${r.sum_pnl:+.2f} |")
    md.append("")

    md.append("## Pass B — Sleeve #2 alternatives (sniper eth_15m Markov inversion)")
    md.append("")
    md.append("Tests four anti-inversion hypotheses for the m5va variant which cut "
              "490->44 fires at random (47.7%) WR in the v1 backtest.")
    md.append("")
    md.append("| # | gate stack | n | WR% | $/tr | sum$ |")
    md.append("|--:|---|--:|--:|--:|--:|")
    s2_base = out[(out.pass_id == "A") & (out.hod == "refreshed") & (out.sid == "2")]
    if len(s2_base):
        r = s2_base.iloc[0]
        md.append(f"| 2 (baseline _hod_m5va, refreshed HoD) | `{r.gates}` | {int(r.n_kept)} | "
                  f"{r.wr_pct:.2f} | ${r.per_trade:+.3f} | ${r.sum_pnl:+.2f} |")
    s2 = out[(out.pass_id == "B") & out.sid.str.startswith("2.")].copy()
    for _, r in s2.iterrows():
        md.append(f"| {r.sid} | `{r.gates}` | {int(r.n_kept)} | "
                  f"{r.wr_pct:.2f} | ${r.per_trade:+.3f} | ${r.sum_pnl:+.2f} |")
    md.append("")

    md.append("## Ensemble PnL — positive sleeves only (refreshed HoD, Pass A)")
    md.append("")
    a_ref = out[(out.pass_id == "A") & (out.hod == "refreshed")].copy()
    pos = a_ref[a_ref.sum_pnl > 0].copy()
    md.append(f"- Positive sleeves: **{len(pos)} / {len(a_ref)}**")
    md.append(f"- Ensemble sum_pnl @ $25 notional: **${pos.sum_pnl.sum():.2f}**")
    if len(pos):
        median_per_week = pos.n_per_week.median()
        md.append(f"- Median n/week per positive sleeve: {median_per_week:.1f}")
    md.append("")

    md.append(f"_data: `data/v4/canonical/_results/shadow_11_sleeves_v2.csv`_  ")
    md.append(f"_generated by `strategy_lab/meta_classifier/shadow_11_sleeves_v2.py`_")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(md), encoding="utf-8")
    print(f"Report: {report_path}")


if __name__ == "__main__":
    sys.exit(main())
