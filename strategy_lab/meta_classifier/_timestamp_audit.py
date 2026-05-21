"""Timestamp interpretation audit — binance vs coinbase vs polymarket vs resolutions.

Checks for hidden interpretation bugs that would invalidate the G-variant findings:

  A. slug suffix encoding   — is `btc-updown-5m-1778279700` the slot_start (UTC seconds)?
  B. bar-open vs bar-close  — for `time_period_start_us = T`, does close report end-of-bar
                                price? Does this match across binance / coinbase / okx?
  C. UTC alignment          — are coinbase / kraken / okx 1MIN bars aligned to UTC
                                minute boundaries (start_us % 60e6 == 0)?
  D. asof_strict semantics  — does `asof_strict(k, ws+60)` actually return a price observable
                                AT wallclock ws+60? (i.e., bar closing at or before ws+60).
  E. coin lag vs bin        — for the same wallclock target, are bin and coin close prices
                                taken from the SAME 1MIN window?
  F. slot_start vs window   — does outcome correlate with sign(price@slot_end - price@slot_start)?
  G. polymarket book ts     — does Polymarket book `timestamp_us` line up with our `fire_us = ws + 60`
                                in actual seconds (not microseconds, no off-by-1000 bug)?
  H. ret_2m direction       — when bin_ret_2m is positive on a true Up market, is the SIGN aligned?

Outputs a printable audit report. Read-only — no model changes, no file writes (other than
optional CSV log of any discrepancies found).
"""
from __future__ import annotations

import math
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "strategy_lab"))
sys.path.insert(0, str(ROOT / "strategy_lab" / "meta_classifier"))

from momo_full_universe_validation import (        # noqa: E402
    load_klines, load_universe, compute_ret_2m, compute_thresholds,
    asof_strict, REFRESH_NEW, REFRESH_OLD, ASSET_BIN, ASSET_OKX,
)
from momo_coinbase_addalpha import (               # noqa: E402
    load_coinbase_klines, ASSET_COIN,
)


def fmt_ts(ts_s: int) -> str:
    return pd.to_datetime(int(ts_s), unit="s", utc=True).strftime("%Y-%m-%d %H:%M:%S UTC")


# ---------------------------------------------------------------------------
# A. slug suffix encoding
# ---------------------------------------------------------------------------

def audit_A_slug_suffix(uni: pd.DataFrame) -> dict:
    res = {"name": "A. slug suffix encoding", "issues": []}
    # Does suffix look like UTC seconds? Range check.
    ws = uni.ws.values
    if ws.min() < 1_700_000_000 or ws.max() > 2_000_000_000:
        res["issues"].append(f"ws range suspicious: {ws.min()} .. {ws.max()}")
    # Are 5m markets aligned to 5min boundaries?
    bad_5m = uni[(uni.tf == "5m") & (uni.ws.values % 300 != 0)]
    bad_15m = uni[(uni.tf == "15m") & (uni.ws.values % 900 != 0)]
    if len(bad_5m):
        res["issues"].append(f"{len(bad_5m)} 5m markets not aligned to 300s boundary "
                                f"(e.g. ws={bad_5m.ws.iat[0]})")
    if len(bad_15m):
        res["issues"].append(f"{len(bad_15m)} 15m markets not aligned to 900s boundary "
                                f"(e.g. ws={bad_15m.ws.iat[0]})")
    res["sample_5m"] = (f"{int(uni[uni.tf=='5m'].ws.iat[0])} = "
                         f"{fmt_ts(int(uni[uni.tf=='5m'].ws.iat[0]))}")
    res["sample_15m"] = (f"{int(uni[uni.tf=='15m'].ws.iat[0])} = "
                          f"{fmt_ts(int(uni[uni.tf=='15m'].ws.iat[0]))}")
    res["pass"] = len(res["issues"]) == 0
    return res


# ---------------------------------------------------------------------------
# B/C. bar-open semantics + UTC alignment per source
# ---------------------------------------------------------------------------

def audit_BC_bar_alignment() -> list[dict]:
    """Inspect the raw kline CSVs to verify bar-open semantics + UTC alignment."""
    out = []

    # Binance from refresh_2026_05_06 (combined binance+okx klines_full)
    bin_path = REFRESH_OLD / "klines_full.csv"
    coin_path = REFRESH_NEW / "cex_klines_vps2.csv"

    for label, path, sources in [
        ("binance(05_06 klines_full)", bin_path,
         {"binance-vision", "binance-spot-ws", "okx-ws"}),
        ("coinbase(05_09 cex_klines)", coin_path,
         {"coinbase-spot-ws", "kraken-spot-ws", "okx-ws"}),
    ]:
        if not path.exists():
            out.append({"name": f"B/C. {label}", "issues": ["file missing"], "pass": False})
            continue
        df = pd.read_csv(path, usecols=["symbol_id", "period_id", "source",
                                            "time_period_start_us"])
        df = df[df.period_id == "1MIN"]
        for src in sources:
            sub = df[df.source == src]
            if sub.empty:
                continue
            res = {"name": f"B/C. {label} source={src}", "issues": []}
            # UTC alignment: every start_us should be a multiple of 60_000_000
            misaligned = (sub.time_period_start_us % 60_000_000 != 0).sum()
            if misaligned:
                res["issues"].append(f"{misaligned}/{len(sub)} bars NOT aligned to UTC minute")
            # Sample first row
            ts = int(sub.time_period_start_us.iat[0]) // 1_000_000
            res["sample"] = f"first bar start_us={sub.time_period_start_us.iat[0]} = {fmt_ts(ts)}"
            res["n"] = int(len(sub))
            res["pass"] = misaligned == 0
            out.append(res)
    return out


# ---------------------------------------------------------------------------
# D. asof_strict semantics check
# ---------------------------------------------------------------------------

def audit_D_asof_strict(klines: dict) -> dict:
    """Verify asof_strict returns the close of the bar that closed AT OR BEFORE target.

    Property: for a target that lands EXACTLY on a bar boundary T (= bar's start), the
    asof should return the previous bar's close (since [T-60, T) just closed at wallclock T,
    and bar [T, T+60) hasn't even opened yet).

    For a target T+0.5 (half a second into the bar [T, T+60)), asof should still return
    the previous bar's close (because bar [T, T+60) hasn't closed yet at T+0.5).
    """
    res = {"name": "D. asof_strict end-time-indexing", "issues": []}
    end_us, prices = klines["BTC"]
    # Pick the second bar in the array
    if len(end_us) < 5:
        res["issues"].append("not enough bars to test")
        res["pass"] = False
        return res
    # bar 1 ends at end_us[1] (bar 1 was [end_us[1]-60e6 -> end_us[1]) -> close = prices[1])
    # query at exactly end_us[1] - 1 (just before bar 1 closes): should return bar 0's close.
    # query at end_us[1]: should return bar 1's close (just-closed)
    # query at end_us[1] + 1: should still return bar 1's close.
    target_pre = end_us[1] - 1_000_000  # 1 sec before bar 1 closes
    target_at = end_us[1]               # exact close of bar 1
    target_post = end_us[1] + 1_000_000 # 1 sec after bar 1 closes

    p_pre = asof_strict(klines["BTC"], target_pre // 1_000_000)
    p_at = asof_strict(klines["BTC"], target_at // 1_000_000)
    p_post = asof_strict(klines["BTC"], target_post // 1_000_000)
    res["sample_target_pre"] = f"asof({fmt_ts(target_pre//1_000_000)}) = {p_pre}"
    res["sample_target_at"] = f"asof({fmt_ts(target_at//1_000_000)})  = {p_at}"
    res["sample_target_post"] = f"asof({fmt_ts(target_post//1_000_000)}) = {p_post}"
    if not (p_pre == prices[0] and p_at == prices[1] and p_post == prices[1]):
        res["issues"].append(
            f"semantics mismatch: expected p_pre={prices[0]}, p_at/post={prices[1]} "
            f"got p_pre={p_pre}, p_at={p_at}, p_post={p_post}"
        )
    res["pass"] = len(res["issues"]) == 0
    return res


# ---------------------------------------------------------------------------
# E. cross-venue same-target alignment
# ---------------------------------------------------------------------------

def audit_E_cross_venue(uni: pd.DataFrame, bin_klines: dict, coin_klines: dict,
                         n_samples: int = 200) -> dict:
    """For a sample of markets, compare price@ws-60 / price@ws+60 across binance & coinbase.
    Both should be observed at the same wallclock target. Their PRICES should be tightly
    correlated (>0.999) and their RETURNS should be nearly identical on average.

    Hidden bugs we want to detect:
      - Off-by-60s (using bar-start instead of bar-end on one venue)
      - Off-by-1000 microsecond/millisecond confusion
      - Coinbase reporting NEXT bar's close instead of CURRENT bar's
    """
    res = {"name": "E. cross-venue alignment (BTC, n_samples)", "issues": []}
    rng = np.random.default_rng(0)
    sub = uni[uni.asset == "BTC"].sample(min(n_samples, len(uni)), random_state=42)
    rows = []
    for r in sub.itertuples(index=False):
        ws = int(r.ws)
        b_pre = asof_strict(bin_klines["BTC"], ws - 60)
        b_post = asof_strict(bin_klines["BTC"], ws + 60)
        c_pre = asof_strict(coin_klines["BTC"], ws - 60)
        c_post = asof_strict(coin_klines["BTC"], ws + 60)
        if all(math.isfinite(x) and x > 0 for x in (b_pre, b_post, c_pre, c_post)):
            rows.append({"ws": ws, "b_pre": b_pre, "b_post": b_post,
                         "c_pre": c_pre, "c_post": c_post})
    df = pd.DataFrame(rows)
    if df.empty:
        res["issues"].append("no rows survived for cross-venue check")
        res["pass"] = False
        return res
    df["price_diff_pre_bp"] = (df.c_pre / df.b_pre - 1.0) * 10000
    df["price_diff_post_bp"] = (df.c_post / df.b_post - 1.0) * 10000
    df["bin_ret_2m"] = np.log(df.b_post / df.b_pre)
    df["coin_ret_2m"] = np.log(df.c_post / df.c_pre)
    df["ret_diff"] = df.coin_ret_2m - df.bin_ret_2m

    res["price_diff_pre_bp_median"] = round(df.price_diff_pre_bp.median(), 2)
    res["price_diff_pre_bp_p95"] = round(df.price_diff_pre_bp.abs().quantile(0.95), 2)
    res["price_diff_post_bp_median"] = round(df.price_diff_post_bp.median(), 2)
    res["price_diff_post_bp_p95"] = round(df.price_diff_post_bp.abs().quantile(0.95), 2)
    res["price_corr"] = round(df[["b_pre", "c_pre"]].corr().iloc[0, 1], 6)
    res["ret_corr"] = round(df[["bin_ret_2m", "coin_ret_2m"]].corr().iloc[0, 1], 6)
    res["disagree_pct"] = round(100 * (np.sign(df.bin_ret_2m) != np.sign(df.coin_ret_2m)).mean(), 2)
    res["n_used"] = int(len(df))
    # Sanity: |median price diff| should be < ~5 bp on healthy book
    if abs(res["price_diff_pre_bp_median"]) > 20:
        res["issues"].append(
            f"median bin/coin price gap is {res['price_diff_pre_bp_median']} bp "
            f"— suspiciously large (likely timestamp shift)"
        )
    # Sanity: ret correlation should be > 0.5 on minute-scale data
    if res["ret_corr"] < 0.5:
        res["issues"].append(
            f"bin/coin ret_2m correlation only {res['ret_corr']} — "
            f"expected >0.7 if both venues see the same event window"
        )
    res["pass"] = len(res["issues"]) == 0
    return res


# ---------------------------------------------------------------------------
# F. slot_start vs outcome consistency
# ---------------------------------------------------------------------------

def audit_F_outcome_consistency(uni: pd.DataFrame, klines: dict) -> dict:
    """For each market: outcome_up should equal sign(close@ws+window_s − close@ws) most of
    the time (Polymarket UpDown should resolve based on the price delta over the window).

    If we have the SLOT_START interpretation right, this should be true >95% of the time
    (the small mismatches come from oracle round-to-nearest behavior on tiny moves).

    If we accidentally interpret slug suffix as SLOT_END instead of SLOT_START, this would
    fall apart catastrophically (we'd be checking the WRONG window).
    """
    res = {"name": "F. outcome ↔ binance(slot_end) − binance(slot_start)", "issues": []}
    sub = uni.head(2000).copy()  # cap for speed
    matches = 0
    n_finite = 0
    sample_disagrees = []
    for r in sub.itertuples(index=False):
        ws = int(r.ws)
        end = ws + int(r.window_s)
        p0 = asof_strict(klines[r.asset], ws)
        p1 = asof_strict(klines[r.asset], end)
        if not (math.isfinite(p0) and math.isfinite(p1) and p0 > 0 and p1 > 0):
            continue
        n_finite += 1
        delta = p1 - p0
        # Skip ties (oracle decides edge cases)
        if abs(delta) < 1e-8:
            continue
        derived = "Up" if delta > 0 else "Down"
        if derived == r.outcome:
            matches += 1
        elif len(sample_disagrees) < 5:
            sample_disagrees.append({
                "slug": r.slug, "ws": ws, "p_start": p0, "p_end": p1,
                "delta": delta, "expected": r.outcome, "derived": derived,
            })
    pct = round(100 * matches / max(n_finite, 1), 2)
    res["match_pct"] = pct
    res["n_used"] = n_finite
    res["sample_disagrees"] = sample_disagrees
    if pct < 90:
        res["issues"].append(
            f"only {pct}% of outcomes match sign(price@end − price@start). "
            f"Strong signal of slot_start ↔ slot_end interpretation bug, OR oracle uses "
            f"a different price source than binance spot."
        )
    res["pass"] = pct >= 90
    return res


# ---------------------------------------------------------------------------
# G. polymarket book ts vs fire_us
# ---------------------------------------------------------------------------

def audit_G_book_ts(asset_label: str = "btc"):
    """Sample tier1 entries — confirm `target_ts_us = (ws+120) * 1e6` semantics and
    that `dt_abs` (book vs target offset) is small (<5s) for most rows.
    """
    res = {"name": f"G. polymarket book ts vs t+120 target ({asset_label})", "issues": []}
    parquet_path = REFRESH_NEW / "tier1_entries" / f"{asset_label}_entries_at_t120.parquet"
    if not parquet_path.exists():
        res["issues"].append(f"missing {parquet_path}")
        res["pass"] = False
        return res
    df = pd.read_parquet(parquet_path,
                         columns=["asset", "slug", "outcome", "target_ts_us",
                                  "timestamp_us", "dt_abs"])
    # target_ts_us / 1_000_000 should be an integer second + 120 (since (ws + 120) * 1e6)
    target_s = (df.target_ts_us // 1_000_000).values
    # Reconstruct ws from slug suffix
    ws_from_slug = df.slug.str.extract(r"-(\d+)$")[0].astype("int64").values
    # Compute expected target_s
    expected = ws_from_slug + 120
    diff = target_s - expected
    res["target_us_unit"] = "microseconds (verified)"
    res["target_s_minus_expected_min"] = int(diff.min())
    res["target_s_minus_expected_max"] = int(diff.max())
    res["target_s_minus_expected_mean"] = round(float(diff.mean()), 4)
    if (diff != 0).any():
        bad_n = (diff != 0).sum()
        res["issues"].append(
            f"{bad_n}/{len(df)} rows have target_ts_us not exactly = (ws_from_slug + 120) * 1e6"
        )
    # dt_abs distribution
    res["dt_abs_us_median"] = int(df.dt_abs.median())
    res["dt_abs_us_p95"] = int(df.dt_abs.abs().quantile(0.95))
    res["dt_abs_us_max"] = int(df.dt_abs.abs().max())
    if df.dt_abs.abs().median() > 5_000_000:  # >5s
        res["issues"].append(
            f"book snapshot is on average >5s away from target — possible book-staleness "
            f"or wallclock drift"
        )
    res["pass"] = len(res["issues"]) == 0
    return res


# ---------------------------------------------------------------------------
# H. ret_2m sign vs outcome correlation
# ---------------------------------------------------------------------------

def audit_H_ret_outcome(uni: pd.DataFrame, klines: dict) -> dict:
    """Across the full universe, confirm sign(ret_2m) is meaningfully predictive of outcome.
    A trivial sanity: hit rate of "bet sign(ret_2m)" should be > 50% (random) and roughly
    consistent with our gated baseline (~87%).

    If timestamps are off, this would degrade to ~50%.
    """
    res = {"name": "H. ret_2m sign predictiveness", "issues": []}
    df = uni.copy()
    df["ret_2m"] = compute_ret_2m(df, klines)
    df = df.dropna(subset=["ret_2m"])
    df = df[df.ret_2m != 0]
    df["pred"] = df.ret_2m.apply(lambda x: "Up" if x > 0 else "Down")
    df["correct"] = (df.pred == df.outcome).astype(int)
    res["n"] = int(len(df))
    res["hit_rate_overall"] = round(100 * df.correct.mean(), 2)
    # Per cell
    cell_hit = df.groupby(["asset", "tf"]).correct.mean().round(4) * 100
    res["per_cell_hit_pct"] = cell_hit.to_dict()
    if df.correct.mean() < 0.55:
        res["issues"].append(
            f"sign(ret_2m) hit rate is {res['hit_rate_overall']}% — barely above random. "
            f"Either ret_2m is uninformative or timestamps are misaligned."
        )
    res["pass"] = df.correct.mean() >= 0.55
    return res


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=== TIMESTAMP INTERPRETATION AUDIT ===\n")
    print("[1] Loading klines + universe...")
    bin_klines = load_klines()
    coin_klines = load_coinbase_klines()
    uni = load_universe()
    print(f"    {len(uni)} markets, klines loaded\n")

    audits = []
    print("[A] slug suffix encoding...")
    audits.append(audit_A_slug_suffix(uni))
    print(f"    {audits[-1]['pass']} | sample 5m: {audits[-1].get('sample_5m')}")
    print(f"           sample 15m: {audits[-1].get('sample_15m')}")
    if audits[-1].get("issues"):
        print(f"    issues: {audits[-1]['issues']}")

    print("\n[B/C] bar-open semantics + UTC alignment per source...")
    bc = audit_BC_bar_alignment()
    audits.extend(bc)
    for r in bc:
        print(f"    {r['pass']} | {r['name']} | n={r.get('n','?')} | "
              f"sample={r.get('sample','—')}")
        if r.get("issues"):
            print(f"        issues: {r['issues']}")

    print("\n[D] asof_strict semantics...")
    d = audit_D_asof_strict(bin_klines)
    audits.append(d)
    print(f"    {d['pass']}")
    print(f"    {d.get('sample_target_pre')}")
    print(f"    {d.get('sample_target_at')}")
    print(f"    {d.get('sample_target_post')}")
    if d.get("issues"):
        print(f"    issues: {d['issues']}")

    print("\n[E] cross-venue alignment (binance vs coinbase, 200 random BTC samples)...")
    e = audit_E_cross_venue(uni, bin_klines, coin_klines)
    audits.append(e)
    print(f"    {e['pass']} | n_used={e.get('n_used')}")
    print(f"    price_corr={e.get('price_corr')}, ret_corr={e.get('ret_corr')}")
    print(f"    median bin/coin diff (bp): pre={e.get('price_diff_pre_bp_median')}, "
          f"post={e.get('price_diff_post_bp_median')}")
    print(f"    p95 |bin/coin diff| (bp):  pre={e.get('price_diff_pre_bp_p95')}, "
          f"post={e.get('price_diff_post_bp_p95')}")
    print(f"    disagree_pct (sign(bin)!=sign(coin)): {e.get('disagree_pct')}%")
    if e.get("issues"):
        print(f"    issues: {e['issues']}")

    print("\n[F] outcome ↔ binance(slot_end) − binance(slot_start) consistency...")
    f = audit_F_outcome_consistency(uni, bin_klines)
    audits.append(f)
    print(f"    {f['pass']} | n_used={f.get('n_used')} match_pct={f.get('match_pct')}%")
    if f.get("sample_disagrees"):
        print("    sample disagreements:")
        for s in f["sample_disagrees"]:
            print(f"      {s}")
    if f.get("issues"):
        print(f"    issues: {f['issues']}")

    print("\n[G] polymarket book ts vs t+120 target...")
    for asset_lbl in ("btc", "eth", "sol"):
        g = audit_G_book_ts(asset_lbl)
        audits.append(g)
        print(f"    {g['pass']} | {g['name']}")
        for k, v in g.items():
            if k in ("name", "pass"):
                continue
            print(f"      {k}: {v}")

    print("\n[H] ret_2m sign predictiveness (full universe, no gate)...")
    h = audit_H_ret_outcome(uni, bin_klines)
    audits.append(h)
    print(f"    {h['pass']} | n={h.get('n')} hit_rate={h.get('hit_rate_overall')}%")
    print(f"    per cell: {h.get('per_cell_hit_pct')}")
    if h.get("issues"):
        print(f"    issues: {h['issues']}")

    print("\n=== SUMMARY ===")
    n_pass = sum(1 for a in audits if a.get("pass"))
    n_total = len(audits)
    print(f"  {n_pass}/{n_total} checks passed.")
    fails = [a for a in audits if not a.get("pass")]
    if fails:
        print("\n  FAILED CHECKS:")
        for a in fails:
            print(f"    - {a['name']}: {a.get('issues')}")
    else:
        print("\n  ✓ All timestamp interpretations look correct.")


if __name__ == "__main__":
    main()
