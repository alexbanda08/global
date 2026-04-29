"""
V38 — Smart Money Concepts (SMC) signal library.

Wraps joshyattridge/smart-money-concepts (https://github.com/joshyattridge/smart-money-concepts)
so its ICT-inspired indicators (FVG, Order Blocks, BOS/CHoCH, Liquidity, Swing HL)
can be used as entry signals inside the same sim harness as V23-V37.

Installation:
    pip install smartmoneyconcepts

All signals follow the lab convention:
    sig_xxx(df, *params) -> tuple[pd.Series[bool], pd.Series[bool]]  # (long, short)

Signals fire on bar CLOSE; `simulate()` handles the next-bar-open fill.

Tested coin universe (same as V23-V34):
    BTCUSDT, ETHUSDT, SOLUSDT, LINKUSDT, ADAUSDT, XRPUSDT, BNBUSDT, DOGEUSDT, AVAXUSDT

Families exposed:
  1. FVG_ENTRY           — long when a fresh bullish FVG prints; short on bearish
  2. FVG_FILL_FADE       — fade extremes: long when bearish FVG gets mitigated
                            (short squeeze), short when bullish FVG is mitigated
  3. OB_TOUCH            — long when price taps an unmitigated bullish OB, short mirror
  4. BOS_CONTINUATION    — trade in direction of latest Break of Structure
  5. CHOCH_REVERSAL      — trade against structure on Change of Character flip
  6. LIQUIDITY_SWEEP_FADE — fade liquidity grabs (classic ICT stop-run reversal)

Same fee model as V23-V34 simulate(): 0.045 % taker + 3 bps slippage + next-bar-open fills.
"""
from __future__ import annotations
import sys, pickle, time, warnings
warnings.filterwarnings("ignore")
from pathlib import Path
import numpy as np
import pandas as pd

try:
    from smartmoneyconcepts import smc
except ImportError as e:
    raise ImportError(
        "smartmoneyconcepts not installed. Run: pip install smartmoneyconcepts"
    ) from e

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from strategy_lab.run_v16_1h_hunt import simulate, metrics, atr, ema

# ================================================================
# Paths & config (mirrors run_v30_creative.py / run_v34_expand.py)
# ================================================================
FEAT = Path(__file__).resolve().parent / "features" / "multi_tf"
OUT = Path(__file__).resolve().parent / "results" / "v38"
OUT.mkdir(parents=True, exist_ok=True)

FEE = 0.00045
BPH = {"15m": 4, "30m": 2, "1h": 1, "2h": 0.5, "4h": 0.25}
SINCE = pd.Timestamp("2020-01-01", tz="UTC")

COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "ADAUSDT",
         "XRPUSDT", "BNBUSDT", "DOGEUSDT", "AVAXUSDT"]


def _load(sym, tf):
    p = FEAT / f"{sym}_{tf}.parquet"
    if not p.exists():
        return None
    df = pd.read_parquet(p).dropna(subset=["open", "high", "low", "close"])
    return df[df.index >= SINCE]


def _smc_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    """
    smc expects lowercase column names: open, high, low, close, (volume).
    Our lab DataFrames already use lowercase, but a few older parquets capitalise.
    This is a defensive normaliser.
    """
    cols = {c.lower(): c for c in df.columns}
    required = ["open", "high", "low", "close"]
    missing = [c for c in required if c not in cols]
    if missing:
        raise ValueError(f"DataFrame missing columns {missing}; has {list(df.columns)}")
    out = df[[cols[c] for c in required]].copy()
    out.columns = required
    if "volume" in cols:
        out["volume"] = df[cols["volume"]].values
    return out


def _ffill_to_series(frame: pd.DataFrame, col: str, index: pd.Index) -> pd.Series:
    """Forward-fill an SMC sparse frame back onto the full OHLC index."""
    s = frame[col].reindex(index)
    return s.ffill()


# ================================================================
# 1. FVG entry — fresh Fair Value Gap
# ================================================================
def sig_fvg_entry(df: pd.DataFrame, join_consecutive: bool = False) -> tuple[pd.Series, pd.Series]:
    """
    Enter on the bar that closes immediately after a FVG prints.

    Long  = bullish FVG printed on this bar (FVG == 1)
    Short = bearish FVG printed on this bar (FVG == -1)

    Signal fires once per FVG (no re-entry while gap remains unfilled).
    """
    ohlc = _smc_ohlc(df)
    fvg = smc.fvg(ohlc, join_consecutive=join_consecutive)
    # smc.fvg returns a DataFrame aligned with the ohlc index (NaN on non-FVG bars)
    fvg_col = fvg["FVG"].reindex(df.index)
    long_sig = (fvg_col == 1).fillna(False).astype(bool)
    short_sig = (fvg_col == -1).fillna(False).astype(bool)
    return long_sig, short_sig


# ================================================================
# 2. FVG fill fade — mean-reversion on gap fill
# ================================================================
def sig_fvg_fill_fade(df: pd.DataFrame, join_consecutive: bool = True) -> tuple[pd.Series, pd.Series]:
    """
    Fade the bar that MITIGATES (fills) an existing FVG — classic ICT rejection entry.

    When a bearish FVG is mitigated (price pushes up into it), go SHORT.
    When a bullish FVG is mitigated (price drops into it), go LONG.
    """
    ohlc = _smc_ohlc(df)
    fvg = smc.fvg(ohlc, join_consecutive=join_consecutive)

    long_sig = pd.Series(False, index=df.index)
    short_sig = pd.Series(False, index=df.index)

    # MitigatedIndex is an integer index of the bar that mitigated each FVG
    mitigated = fvg.dropna(subset=["MitigatedIndex"])
    for fvg_i, row in mitigated.iterrows():
        m_i = int(row["MitigatedIndex"])
        if m_i < 0 or m_i >= len(df.index):
            continue
        ts = df.index[m_i]
        if row["FVG"] == 1:
            # Bullish FVG filled from above → bounce long
            long_sig.loc[ts] = True
        elif row["FVG"] == -1:
            # Bearish FVG filled from below → rejection short
            short_sig.loc[ts] = True

    return long_sig.astype(bool), short_sig.astype(bool)


# ================================================================
# 3. Order Block touch
# ================================================================
def sig_ob_touch(df: pd.DataFrame, close_mitigation: bool = False,
                 min_ob_pct: float = 0.0) -> tuple[pd.Series, pd.Series]:
    """
    Enter when price touches an Order Block whose strength >= min_ob_pct.

    Long  = touch of an active bullish OB (bounce expected).
    Short = touch of an active bearish OB (rejection expected).

    close_mitigation: pass through to smc.ob()
    min_ob_pct: minimum OB strength (0..1) from smc's Percentage col
    """
    ohlc = _smc_ohlc(df)
    shl = smc.swing_highs_lows(ohlc, swing_length=50)
    ob = smc.ob(ohlc, shl, close_mitigation=close_mitigation)

    long_sig = pd.Series(False, index=df.index)
    short_sig = pd.Series(False, index=df.index)

    # For each OB, mark the first bar after OB print that touches the zone
    for i, row in ob.dropna(subset=["OB"]).iterrows():
        if row["Percentage"] < min_ob_pct:
            continue
        top, bot = row["Top"], row["Bottom"]
        pos = df.index.get_loc(i) if i in df.index else None
        if pos is None:
            continue
        # Walk forward until an OB-touch bar (or mitigation)
        m_i = row.get("MitigatedIndex")
        end_pos = int(m_i) if pd.notna(m_i) else len(df.index) - 1
        for j in range(pos + 1, min(end_pos + 1, len(df.index))):
            lo, hi = df["low"].iat[j], df["high"].iat[j]
            if lo <= top and hi >= bot:
                ts = df.index[j]
                if row["OB"] == 1:
                    long_sig.loc[ts] = True
                else:
                    short_sig.loc[ts] = True
                break  # one entry per OB
    return long_sig.astype(bool), short_sig.astype(bool)


# ================================================================
# 4. BOS continuation
# ================================================================
def sig_bos_continuation(df: pd.DataFrame, swing_length: int = 50,
                         close_break: bool = True) -> tuple[pd.Series, pd.Series]:
    """
    Trade in the direction of the latest Break of Structure.

    Long  = bullish BOS prints on this bar (trend continuation up)
    Short = bearish BOS prints on this bar
    """
    ohlc = _smc_ohlc(df)
    shl = smc.swing_highs_lows(ohlc, swing_length=swing_length)
    bc = smc.bos_choch(ohlc, shl, close_break=close_break)

    # BOS column: 1 bullish, -1 bearish, NaN otherwise
    bos_col = bc["BOS"].reindex(df.index)
    long_sig = (bos_col == 1).fillna(False).astype(bool)
    short_sig = (bos_col == -1).fillna(False).astype(bool)
    return long_sig, short_sig


# ================================================================
# 5. CHOCH reversal
# ================================================================
def sig_choch_reversal(df: pd.DataFrame, swing_length: int = 50,
                      close_break: bool = True) -> tuple[pd.Series, pd.Series]:
    """
    Trade AGAINST prior structure when a Change of Character prints.

    Long  = bullish CHoCH on this bar (prior downtrend flipped to up)
    Short = bearish CHoCH (prior uptrend flipped to down)
    """
    ohlc = _smc_ohlc(df)
    shl = smc.swing_highs_lows(ohlc, swing_length=swing_length)
    bc = smc.bos_choch(ohlc, shl, close_break=close_break)

    ch_col = bc["CHOCH"].reindex(df.index)
    long_sig = (ch_col == 1).fillna(False).astype(bool)
    short_sig = (ch_col == -1).fillna(False).astype(bool)
    return long_sig, short_sig


# ================================================================
# 6. Liquidity sweep fade
# ================================================================
def sig_liquidity_sweep_fade(df: pd.DataFrame, swing_length: int = 50,
                            range_percent: float = 0.01) -> tuple[pd.Series, pd.Series]:
    """
    Fade liquidity grabs — ICT-style stop-run reversal.

    When buy-side liquidity is swept (price pokes above a swing high and fails),
    go SHORT. When sell-side is swept (poke below and recover), go LONG.
    """
    ohlc = _smc_ohlc(df)
    shl = smc.swing_highs_lows(ohlc, swing_length=swing_length)
    liq = smc.liquidity(ohlc, shl, range_percent=range_percent)

    long_sig = pd.Series(False, index=df.index)
    short_sig = pd.Series(False, index=df.index)

    # Liquidity col: 1 bullish (sell-side swept, bounce long), -1 bearish
    liq_col = liq["Liquidity"].reindex(df.index)
    # Mark the sweep bar: use `End` index if available; else the liquidity-print bar
    end_col = liq["End"] if "End" in liq.columns else None
    for i, val in liq_col.items():
        if pd.isna(val):
            continue
        # use End bar if set, else fall back to the liquidity-level bar
        fade_i = i
        if end_col is not None and i in end_col.index and pd.notna(end_col.loc[i]):
            try:
                fade_i = df.index[int(end_col.loc[i])]
            except Exception:
                fade_i = i
        if fade_i not in df.index:
            continue
        if val == 1:     # sell-side sweep → bounce long
            long_sig.loc[fade_i] = True
        elif val == -1:  # buy-side sweep → reject short
            short_sig.loc[fade_i] = True
    return long_sig.astype(bool), short_sig.astype(bool)


# ================================================================
# Combined / composite entries (examples)
# ================================================================
def sig_smc_confluence(df: pd.DataFrame, swing_length: int = 50) -> tuple[pd.Series, pd.Series]:
    """
    Confluence signal: require BOS in trend direction AND OB touch within last N bars.
    Stricter entry — much fewer trades, higher expected win rate.
    """
    bos_l, bos_s = sig_bos_continuation(df, swing_length=swing_length)
    ob_l, ob_s = sig_ob_touch(df)

    # Require OB touch within 10 bars of a BOS in same direction
    window = 10
    bos_l_recent = bos_l.rolling(window, min_periods=1).max().astype(bool)
    bos_s_recent = bos_s.rolling(window, min_periods=1).max().astype(bool)

    long_sig = ob_l & bos_l_recent
    short_sig = ob_s & bos_s_recent
    return long_sig.astype(bool), short_sig.astype(bool)


# ================================================================
# Runner — sweep SMC families across the 9-coin universe
# ================================================================
def run_one(df, sig_fn, name, params, lev=3.0, risk=0.01, tp=3.0, sl=2.0, tr=1.0, mh=48):
    """Runs a single (signal, param-set) pair through the standard simulate() harness."""
    lsig, ssig = sig_fn(df, **params)
    pnl, trades = simulate(df, lsig, ssig, tp=tp, sl=sl, tr=tr, mh=mh,
                           risk=risk, lev=lev, fee=FEE)
    m = metrics(pnl, trades)
    return {"strategy": name, "params": params, **m}


def sweep(tf: str = "4h", coins: list[str] | None = None):
    """
    Default sweep — one entry per family on every coin in the basket.
    Extend with parameter grids as needed.
    """
    coins = coins or COINS
    families = [
        ("FVG_ENTRY",           sig_fvg_entry,            {"join_consecutive": False}),
        ("FVG_FILL_FADE",       sig_fvg_fill_fade,        {"join_consecutive": True}),
        ("OB_TOUCH",            sig_ob_touch,             {"min_ob_pct": 0.30}),
        ("BOS_CONTINUATION",    sig_bos_continuation,     {"swing_length": 50}),
        ("CHOCH_REVERSAL",      sig_choch_reversal,       {"swing_length": 50}),
        ("LIQUIDITY_SWEEP",     sig_liquidity_sweep_fade, {"swing_length": 50, "range_percent": 0.01}),
        ("SMC_CONFLUENCE",      sig_smc_confluence,       {"swing_length": 50}),
    ]

    results = []
    for sym in coins:
        df = _load(sym, tf)
        if df is None:
            print(f"[skip] {sym} {tf} — no data")
            continue
        for name, fn, params in families:
            try:
                t0 = time.time()
                r = run_one(df, fn, name, params)
                r.update({"symbol": sym, "tf": tf, "elapsed_s": round(time.time() - t0, 2)})
                results.append(r)
                print(f"{sym} {tf} {name}: Sharpe={r.get('sharpe', float('nan')):.2f} "
                      f"CAGR={r.get('cagr', float('nan')):.1%} "
                      f"DD={r.get('maxdd', float('nan')):.1%} "
                      f"trades={r.get('n_trades', 0)}")
            except Exception as e:
                print(f"[err]  {sym} {tf} {name}: {type(e).__name__}: {e}")

    out_path = OUT / f"v38_smc_sweep_{tf}.pkl"
    with open(out_path, "wb") as f:
        pickle.dump(results, f)
    print(f"\nWrote {len(results)} results → {out_path}")
    return results


if __name__ == "__main__":
    # Default run: 4h bars, all 9 coins, one param set per family
    sweep(tf="4h")
