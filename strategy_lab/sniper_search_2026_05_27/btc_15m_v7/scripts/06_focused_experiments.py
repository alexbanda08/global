"""V7 BTC 15m — 3 FOCUSED EXPERIMENTS (3rd retry).

V6 winner reference: g_tr_above_ema200 + g_mp_skew_strong + g_rf_with @ offset 600 DOWN
  -> n=34, WR=85.3%, $/tr=+$11.81, DD=$72

3 experiments:
1. V6 winner + g_hurst_reverting (hurst<0.40)
2. V6 winner + g_parent_1h_ranging (BTC 1h close vs 1h SMA20 |dev|<0.5%)
3. ETH 15m trend slope cross-asset trigger added to V6 winner

Plus baseline replication of V6 winner alone.

Outputs:
- top_5_candidates_v7.csv
- SNIPER_BTC_15M_V7_REPORT.md
- 1 cumulative PnL PNG (best sleeve)
"""
import sys, time, os
import numpy as np
import pandas as pd

sys.path.insert(0, "data/v4/canonical")
from load import load_klines, load_klines_asof

OUT_DIR = "strategy_lab/sniper_search_2026_05_27/btc_15m_v7"
PLOT_DIR = f"{OUT_DIR}/plots"
os.makedirs(PLOT_DIR, exist_ok=True)

t0 = time.time()
def log(m): print(f"[{time.time()-t0:6.1f}s] {m}", flush=True)

# ============== Load V7 panel ==============
log("loading V7 panel")
PANEL = "data/v4/canonical/_results/sniper_btc15m_v7_gated.parquet"
df = pd.read_parquet(PANEL)
df["fire_date"] = pd.to_datetime(df["fire_us"], unit="us", utc=True)
df = df[(df["entry_vwap"] >= 0.10) & (df["entry_vwap"] <= 0.90)].copy()
df = df.sort_values("fire_us").reset_index(drop=True)
log(f"  rows: {len(df)}  days: {df.fire_date.dt.date.nunique()}")

# ============== Build g_parent_1h_ranging ==============
# BTC 1h close vs SMA20 within +/- 0.5% (no trending dominance) — aggregate from 1m spot-ws (covers full window)
log("aggregating BTC 1m -> 1h spot-ws for parent_1h_ranging (full fire window)")
btc1m = load_klines("BTC", "binance-spot-ws", "1MIN")
log(f"  1m rows: {len(btc1m)}")
btc1m["hour_start_us"] = (btc1m.time_period_start_us // (3600 * 1_000_000)) * (3600 * 1_000_000)
btc1h = btc1m.groupby("hour_start_us", as_index=False).agg(
    time_period_start_us=("hour_start_us", "first"),
    price_close=("price_close", "last"),
).sort_values("time_period_start_us").reset_index(drop=True)
log(f"  aggregated to 1h: {len(btc1h)} bars")

# 1h SMA20 and dev pct
btc1h["sma20"] = btc1h.price_close.rolling(20, min_periods=20).mean()
btc1h["dev_pct"] = (btc1h.price_close - btc1h.sma20) / btc1h.sma20
btc1h["bar_end_us"] = btc1h.time_period_start_us.values.astype("int64") + 3600 * 1_000_000

# at-or-before searchsorted for each fire_us
end_us_1h = btc1h["bar_end_us"].values.astype("int64")
dev_pct = btc1h["dev_pct"].values.astype("float64")
fire_us = df["fire_us"].values.astype("int64")
idx = np.searchsorted(end_us_1h, fire_us, side="right") - 1
idx_safe = np.where(idx >= 0, idx, 0)
parent_dev = np.where(idx >= 0, dev_pct[idx_safe], np.nan)
df["parent_1h_dev_pct"] = parent_dev
df["g_parent_1h_ranging"] = ((np.abs(parent_dev) < 0.005)).astype("int8")  # |dev|<0.5%
log(f"  g_parent_1h_ranging fire_rate={df.g_parent_1h_ranging.mean():.3f}")

# ============== Build g_eth_slope_with (ETH 15m slope direction-aligned) ==============
log("aggregating ETH 1m -> 15m spot-ws for cross-asset slope")
eth1m = load_klines("ETH", "binance-spot-ws", "1MIN")
log(f"  ETH 1m rows: {len(eth1m)}")
eth1m["q_start_us"] = (eth1m.time_period_start_us // (900 * 1_000_000)) * (900 * 1_000_000)
eth15 = eth1m.groupby("q_start_us", as_index=False).agg(
    time_period_start_us=("q_start_us", "first"),
    price_close=("price_close", "last"),
).sort_values("time_period_start_us").reset_index(drop=True)
log(f"  ETH aggregated to 15m: {len(eth15)}")

eth15 = eth15.sort_values("time_period_start_us").reset_index(drop=True)
# 30-min slope (2 x 15m bars) — close[-1] / close[-3] - 1, evaluated at end of bar 1
eth15["slope_30m"] = eth15.price_close.pct_change(2)
eth15["bar_end_us"] = eth15.time_period_start_us.values.astype("int64") + 900 * 1_000_000
end_eth = eth15["bar_end_us"].values.astype("int64")
slope_eth = eth15["slope_30m"].values.astype("float64")
idx_eth = np.searchsorted(end_eth, fire_us, side="right") - 1
idx_safe_eth = np.where(idx_eth >= 0, idx_eth, 0)
eth_slope = np.where(idx_eth >= 0, slope_eth[idx_safe_eth], np.nan)
df["eth_slope_30m"] = eth_slope
# direction-aligned: UP -> eth_slope > 0, DOWN -> eth_slope < 0
df["g_eth_slope_with"] = (
    ((df.direction == "UP") & (df.eth_slope_30m > 0)) |
    ((df.direction == "DOWN") & (df.eth_slope_30m < 0))
).fillna(False).astype("int8")
log(f"  g_eth_slope_with fire_rate={df.g_eth_slope_with.mean():.3f}")
log(f"  g_eth_slope_with on DOWN-only fire_rate={df[df.direction=='DOWN'].g_eth_slope_with.mean():.3f}")

# ============== Splits ==============
TRAIN_START = pd.Timestamp("2026-04-28", tz="UTC")
TRAIN_END   = pd.Timestamp("2026-05-16", tz="UTC")
VAL_END     = pd.Timestamp("2026-05-22", tz="UTC")
LOCK_END    = pd.Timestamp("2026-05-26", tz="UTC")

tr_mask = (df.fire_date >= TRAIN_START) & (df.fire_date < TRAIN_END)
va_mask = (df.fire_date >= TRAIN_END) & (df.fire_date < VAL_END)
lo_mask = (df.fire_date >= VAL_END) & (df.fire_date < LOCK_END)
df_tr = df[tr_mask].copy()
df_va = df[va_mask].copy()
df_lo = df[lo_mask].copy()
log(f"split: tr={len(df_tr)} va={len(df_va)} lo={len(df_lo)}")
LO_DAYS = max(1, (LOCK_END - VAL_END).days)
SCALE_28D = 28.0 / LO_DAYS


def compute_dd(pnl_arr):
    if len(pnl_arr) == 0: return 0.0
    cum = np.cumsum(pnl_arr)
    peak = np.maximum.accumulate(cum)
    return float(-(cum - peak).min())


def max_loss_streak(won_arr):
    if len(won_arr) == 0: return 0
    streak = mx = 0
    for w in won_arr:
        if w == 0: streak += 1; mx = max(mx, streak)
        else: streak = 0
    return mx


def daily_sharpe(d):
    if len(d) == 0: return 0.0
    daily = d.groupby(d.fire_date.dt.date)["pnl_legacy_usd"].sum()
    if len(daily) < 2 or daily.std() == 0: return 0.0
    return float(daily.mean() / daily.std() * np.sqrt(365))


def bootstrap_p(d_lock, n_shuffles=1000, seed=42):
    if len(d_lock) < 5: return np.nan
    daily = d_lock.groupby(d_lock.fire_date.dt.date)["pnl_legacy_usd"].sum().values
    n_days = len(daily)
    if n_days < 2: return np.nan
    rng = np.random.default_rng(seed)
    boot = rng.choice(daily, size=(n_shuffles, n_days), replace=True).sum(axis=1)
    p = float((boot <= 0).sum() / n_shuffles)
    return max(p, 1.0 / n_shuffles)


def evaluate(d, gates, offset, direction):
    d = d[d.fire_offset_s == offset]
    if direction != "BOTH":
        d = d[d.direction == direction]
    if gates:
        m = np.ones(len(d), dtype=bool)
        for g in gates:
            m &= (d[g].values == 1)
        d = d[m]
    if len(d) == 0:
        return None
    pnl = d["pnl_legacy_usd"].values  # already at $25 stake per canonical convention
    won = d["won"].values.astype(int)
    return dict(
        n=len(d), wr=float(won.mean()),
        dpt=float(pnl.mean()),
        sum_pnl=float(pnl.sum()),
        max_dd=compute_dd(pnl),
        loss_streak=max_loss_streak(won),
        unique_days=int(d.fire_date.dt.date.nunique()),
        sharpe=daily_sharpe(d),
        sub=d,
    )


# ============== 4 SLEEVES ==============
V6_BASE = ["g_tr_above_ema200", "g_mp_skew_strong_with", "g_rf_with"]
OFFSET = 600
DIR = "DOWN"

sleeves = [
    ("V6_baseline",                     V6_BASE),
    ("V7_exp1_plus_hurst_reverting",    V6_BASE + ["g_hurst_reverting"]),
    ("V7_exp2_plus_parent_1h_ranging",  V6_BASE + ["g_parent_1h_ranging"]),
    ("V7_exp3_plus_eth_slope_with",     V6_BASE + ["g_eth_slope_with"]),
]

rows = []
for name, gates in sleeves:
    log(f"\nSLEEVE: {name}  gates={gates}")
    m_tr = evaluate(df_tr, gates, OFFSET, DIR)
    m_va = evaluate(df_va, gates, OFFSET, DIR)
    m_lo = evaluate(df_lo, gates, OFFSET, DIR)
    if m_lo is None:
        log("  LOCKBOX: 0 fires — skip")
        rows.append(dict(
            sleeve_id=name, anchor="offset_600s", gate_stack="+".join(gates),
            weights="", conviction_method="B",
            n_train=m_tr["n"] if m_tr else 0,
            n_val=m_va["n"] if m_va else 0,
            n_lockbox=0,
            wr_train=m_tr["wr"] if m_tr else 0,
            wr_val=m_va["wr"] if m_va else 0,
            wr_lockbox=0,
            dpt_25_train=m_tr["dpt"] if m_tr else 0,
            dpt_25_val=m_va["dpt"] if m_va else 0,
            dpt_25_lockbox=0,
            sum_25_28d_const=0,
            max_dd_25=0, loss_streak=0, sharpe=0,
            bootstrap_p_lockbox=np.nan, obj_score=0,
            offset=OFFSET, direction=DIR, v7_path="focused_experiment",
        ))
        continue
    bp = bootstrap_p(m_lo["sub"])
    obj = m_lo["dpt"] * np.sqrt(m_lo["n"])
    log(f"  TRAIN:    n={m_tr['n']:4d}  WR={m_tr['wr']:.3f}  $/tr={m_tr['dpt']:+.3f}")
    log(f"  VAL:      n={m_va['n']:4d}  WR={m_va['wr']:.3f}  $/tr={m_va['dpt']:+.3f}")
    log(f"  LOCKBOX:  n={m_lo['n']:4d}  WR={m_lo['wr']:.3f}  $/tr={m_lo['dpt']:+.3f}  DD={m_lo['max_dd']:.1f}  LS={m_lo['loss_streak']}  Sh={m_lo['sharpe']:.2f}  p={bp:.4f}  obj={obj:.2f}")
    rows.append(dict(
        sleeve_id=name, anchor="offset_600s", gate_stack="+".join(gates),
        weights="", conviction_method="B",
        n_train=m_tr["n"], n_val=m_va["n"], n_lockbox=m_lo["n"],
        wr_train=m_tr["wr"], wr_val=m_va["wr"], wr_lockbox=m_lo["wr"],
        dpt_25_train=m_tr["dpt"], dpt_25_val=m_va["dpt"], dpt_25_lockbox=m_lo["dpt"],
        sum_25_28d_const=m_lo["sum_pnl"] * SCALE_28D,
        max_dd_25=m_lo["max_dd"], loss_streak=m_lo["loss_streak"], sharpe=m_lo["sharpe"],
        bootstrap_p_lockbox=bp, obj_score=obj,
        offset=OFFSET, direction=DIR, v7_path="focused_experiment",
    ))

# ============== Save CSV ==============
df_out = pd.DataFrame(rows)
df_out = df_out.sort_values("obj_score", ascending=False).reset_index(drop=True)
CSV = f"{OUT_DIR}/top_5_candidates_v7.csv"
df_out.to_csv(CSV, index=False)
log(f"\nsaved: {CSV}  rows={len(df_out)}")
print(df_out.to_string(index=False))

# ============== V7 bar check ==============
def pass_v7_bar(r):
    return (r.wr_lockbox >= 0.65 and r.dpt_25_lockbox >= 4.0 and
            r.max_dd_25 <= 500 and r.loss_streak <= 14 and
            (pd.isna(r.bootstrap_p_lockbox) or r.bootstrap_p_lockbox <= 0.05) and
            r.dpt_25_train > 0 and r.dpt_25_val > 0 and r.dpt_25_lockbox > 0)

df_out["passes_v7"] = df_out.apply(pass_v7_bar, axis=1)
log(f"\nsleeves passing V7 bar: {df_out.passes_v7.sum()} / {len(df_out)}")

# ============== Cumulative PnL plot for best sleeve ==============
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(13, 7))
    colors = {"V6_baseline": "black", "V7_exp1_plus_hurst_reverting": "C3",
              "V7_exp2_plus_parent_1h_ranging": "C1", "V7_exp3_plus_eth_slope_with": "C0"}
    for name, gates in sleeves:
        m_lo = evaluate(df_lo, gates, OFFSET, DIR)
        if m_lo is None or m_lo["n"] == 0:
            continue
        sub = m_lo["sub"].sort_values("fire_us")
        pnl_cum = sub["pnl_legacy_usd"].values.cumsum()
        ts = pd.to_datetime(sub["fire_us"].values, unit="us", utc=True)
        lw = 2.5 if name == "V6_baseline" else 1.8
        ax.plot(ts, pnl_cum, "o-", linewidth=lw, alpha=0.85,
                label=f"{name}  n={m_lo['n']}  WR={m_lo['wr']:.3f}  $/tr={m_lo['dpt']:+.2f}",
                color=colors.get(name, "gray"))
    ax.axhline(0, color="black", lw=0.5)
    ax.set_title(f"V7 BTC 15m focused experiments — Lockbox cumulative PnL ($25 stake)\nbase = V6 winner @ offset 600 DOWN")
    ax.set_xlabel("Fire time (UTC)")
    ax.set_ylabel("Cumulative PnL ($)")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best", fontsize=9)
    plt.tight_layout()
    png = f"{PLOT_DIR}/v7_focused_comparison.png"
    plt.savefig(png, dpi=110)
    plt.close()
    log(f"  saved: {png}")
except Exception as e:
    log(f"  plot skipped: {e}")

log("\nDONE")
