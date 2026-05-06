"""Phase 9 — Polymarket Trade Flow Imbalance (TFI).

Hypothesis: imbalance of buy-YES vs buy-NO TRADES on Polymarket reveals
informed flow. Should be orthogonal to V3 (returns/OI/taker on Binance)
and Phase 7 (orderbook depth derivative).

Data: VPS2 trades_v2 (18.88M rows, 13.9M BTC, 4100 distinct BTC slugs).
  Schema: timestamp_us, slug, asset_id, outcome ('Up'|'Down'), price,
          size, side ('buy'|'sell'), trade_id, ...
  buy YES  = (outcome='Up'   AND side='buy')   pushes price UP
  sell YES = (outcome='Up'   AND side='sell')  pushes price DOWN
  buy NO   = (outcome='Down' AND side='buy')   pushes price DOWN
  sell NO  = (outcome='Down' AND side='sell')  pushes price UP

Bullish $ = (Up_buy_size * Up_buy_price) + (Down_sell_size * Down_sell_price)
Bearish $ = (Down_buy_size * Down_buy_price) + (Up_sell_size * Up_sell_price)
TFI = (Bullish - Bearish) / (Bullish + Bearish)

For each market, aggregate at signal_time = window_start_unix:
  poly_tfi_2m       : TFI in [window_start, window_start + 120s]
  poly_tfi_5m       : TFI in [window_start, window_start + 300s]   (15m markets)
  poly_trade_count_2m
  poly_trade_count_5m
  poly_avg_trade_size_2m

Pulls aggregates server-side via psql to avoid hauling 14M raw rows.

Output: strategy_lab/data/meta_classifier/btc_trade_flow_v1.parquet
"""
from __future__ import annotations
import subprocess
import io
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

ROOT = Path("C:/Users/alexandre bandarra/Desktop/global")
MARKETS_MIN = ROOT / "data" / "v4" / "refresh_2026_05_02" / "btc_markets_minimal.csv"
PHASE7_PARQUET = ROOT / "strategy_lab" / "data" / "meta_classifier" / "btc_clob_momentum_v1.parquet"
V3_CSV = ROOT / "strategy_lab" / "data" / "polymarket" / "btc_features_v3.csv"
OUT_PARQUET = ROOT / "strategy_lab" / "data" / "meta_classifier" / "btc_trade_flow_v1.parquet"
RAW_CSV = ROOT / "data" / "v4" / "shadow_trades_2026_05_05_live" / "btc_trades_v2_aggregated.csv"
REPORT_PATH = ROOT / "strategy_lab" / "reports" / "PHASE9_POLYMARKET_TRADE_FLOW.md"

VPS_HOST = "root@[2605:a140:2323:6975::1]"
SSH_KEY = "~/.ssh/vps2_ed25519"

# ---------------------------------------------------------------------------
# 1. Server-side aggregation via psql heredoc
# ---------------------------------------------------------------------------

SQL_AGGREGATE = r"""
\set ON_ERROR_STOP on
BEGIN;

CREATE TEMP TABLE univ (
    slug TEXT PRIMARY KEY,
    timeframe TEXT,
    window_start BIGINT
);

\copy univ(slug, timeframe, window_start) FROM '/tmp/btc_universe.csv' CSV HEADER

CREATE INDEX univ_slug ON univ(slug);

-- 2-minute aggregation
CREATE TEMP TABLE agg_2m AS
SELECT
    u.slug,
    SUM(CASE WHEN t.outcome='Up'   AND t.side='buy'  THEN t.size*t.price ELSE 0 END) AS up_buy_usd_2m,
    SUM(CASE WHEN t.outcome='Up'   AND t.side='sell' THEN t.size*t.price ELSE 0 END) AS up_sell_usd_2m,
    SUM(CASE WHEN t.outcome='Down' AND t.side='buy'  THEN t.size*t.price ELSE 0 END) AS down_buy_usd_2m,
    SUM(CASE WHEN t.outcome='Down' AND t.side='sell' THEN t.size*t.price ELSE 0 END) AS down_sell_usd_2m,
    COUNT(*) AS n_trades_2m,
    SUM(t.size*t.price) AS total_usd_2m
FROM univ u
JOIN trades_v2 t
  ON t.slug = u.slug
 AND t.timestamp_us >= u.window_start * 1000000
 AND t.timestamp_us <  (u.window_start + 120) * 1000000
GROUP BY u.slug;

-- 5-minute aggregation
CREATE TEMP TABLE agg_5m AS
SELECT
    u.slug,
    SUM(CASE WHEN t.outcome='Up'   AND t.side='buy'  THEN t.size*t.price ELSE 0 END) AS up_buy_usd_5m,
    SUM(CASE WHEN t.outcome='Up'   AND t.side='sell' THEN t.size*t.price ELSE 0 END) AS up_sell_usd_5m,
    SUM(CASE WHEN t.outcome='Down' AND t.side='buy'  THEN t.size*t.price ELSE 0 END) AS down_buy_usd_5m,
    SUM(CASE WHEN t.outcome='Down' AND t.side='sell' THEN t.size*t.price ELSE 0 END) AS down_sell_usd_5m,
    COUNT(*) AS n_trades_5m,
    SUM(t.size*t.price) AS total_usd_5m
FROM univ u
JOIN trades_v2 t
  ON t.slug = u.slug
 AND t.timestamp_us >= u.window_start * 1000000
 AND t.timestamp_us <  (u.window_start + 300) * 1000000
GROUP BY u.slug;

CREATE TEMP TABLE final_out AS
SELECT u.slug, u.timeframe, u.window_start,
       COALESCE(a2.up_buy_usd_2m,0)   AS up_buy_usd_2m,
       COALESCE(a2.up_sell_usd_2m,0)  AS up_sell_usd_2m,
       COALESCE(a2.down_buy_usd_2m,0) AS down_buy_usd_2m,
       COALESCE(a2.down_sell_usd_2m,0) AS down_sell_usd_2m,
       COALESCE(a2.n_trades_2m,0)     AS n_trades_2m,
       COALESCE(a2.total_usd_2m,0)    AS total_usd_2m,
       COALESCE(a5.up_buy_usd_5m,0)   AS up_buy_usd_5m,
       COALESCE(a5.up_sell_usd_5m,0)  AS up_sell_usd_5m,
       COALESCE(a5.down_buy_usd_5m,0) AS down_buy_usd_5m,
       COALESCE(a5.down_sell_usd_5m,0) AS down_sell_usd_5m,
       COALESCE(a5.n_trades_5m,0)     AS n_trades_5m,
       COALESCE(a5.total_usd_5m,0)    AS total_usd_5m
FROM univ u
LEFT JOIN agg_2m a2 ON a2.slug = u.slug
LEFT JOIN agg_5m a5 ON a5.slug = u.slug;

\copy (SELECT * FROM final_out) TO '/tmp/btc_trade_flow_agg.csv' CSV HEADER

ROLLBACK;
"""


def pull_aggregates() -> pd.DataFrame:
    """SCP universe -> VPS, run aggregation SQL, fetch result."""
    universe = pd.read_csv(MARKETS_MIN)
    universe = universe.dropna(subset=["window_start_unix", "outcome_up"]).copy()
    universe["window_start_unix"] = universe["window_start_unix"].astype("int64")

    # Write minimal CSV for upload
    upload_tmp = ROOT / "data" / "v4" / "shadow_trades_2026_05_05_live"
    upload_tmp.mkdir(parents=True, exist_ok=True)
    upload_csv = upload_tmp / "btc_universe_for_vps.csv"
    universe[["slug", "timeframe", "window_start_unix"]].rename(
        columns={"window_start_unix": "window_start"}
    ).to_csv(upload_csv, index=False)
    print(f"[upload] wrote {upload_csv} ({len(universe)} markets)")

    # SCP to VPS
    scp_cmd = [
        "scp", "-i", str(Path.home() / ".ssh" / "vps2_ed25519"),
        "-o", "StrictHostKeyChecking=no",
        str(upload_csv),
        f"{VPS_HOST}:/tmp/btc_universe.csv",
    ]
    print(f"[scp] {' '.join(scp_cmd)}")
    subprocess.run(scp_cmd, check=True)

    # Write SQL to file and run via SSH
    sql_path = upload_tmp / "phase9_aggregate.sql"
    sql_path.write_text(SQL_AGGREGATE)
    scp_sql = [
        "scp", "-i", str(Path.home() / ".ssh" / "vps2_ed25519"),
        "-o", "StrictHostKeyChecking=no",
        str(sql_path),
        f"{VPS_HOST}:/tmp/phase9_aggregate.sql",
    ]
    subprocess.run(scp_sql, check=True)

    ssh_cmd = (
        "PGPASSWORD=$(grep TV_RO_PWD_PLAIN /etc/tv/tv-ro.env | cut -d= -f2) "
        "psql -h 127.0.0.1 -U tradingvenue_ro -d storedata -f /tmp/phase9_aggregate.sql"
    )
    print("[ssh] running aggregation SQL on VPS2...")
    res = subprocess.run(
        ["ssh", "-i", str(Path.home() / ".ssh" / "vps2_ed25519"),
         "-o", "StrictHostKeyChecking=no", VPS_HOST, ssh_cmd],
        capture_output=True, text=True
    )
    print("[ssh stderr]:", res.stderr[-500:])
    if res.returncode != 0:
        raise RuntimeError("psql aggregation failed")

    # Pull result back
    RAW_CSV.parent.mkdir(parents=True, exist_ok=True)
    scp_back = [
        "scp", "-i", str(Path.home() / ".ssh" / "vps2_ed25519"),
        "-o", "StrictHostKeyChecking=no",
        f"{VPS_HOST}:/tmp/btc_trade_flow_agg.csv",
        str(RAW_CSV),
    ]
    subprocess.run(scp_back, check=True)
    print(f"[scp back] saved {RAW_CSV}")

    df = pd.read_csv(RAW_CSV)
    print(f"[agg] {len(df)} rows pulled")
    return df


# ---------------------------------------------------------------------------
# 2. Feature engineering
# ---------------------------------------------------------------------------

def build_features(agg: pd.DataFrame) -> pd.DataFrame:
    df = agg.copy()
    # Bullish flow = buy Up + sell Down (both push UP-token price up)
    df["bull_2m"] = df["up_buy_usd_2m"] + df["down_sell_usd_2m"]
    df["bear_2m"] = df["down_buy_usd_2m"] + df["up_sell_usd_2m"]
    df["bull_5m"] = df["up_buy_usd_5m"] + df["down_sell_usd_5m"]
    df["bear_5m"] = df["down_buy_usd_5m"] + df["up_sell_usd_5m"]

    tot2 = df["bull_2m"] + df["bear_2m"]
    tot5 = df["bull_5m"] + df["bear_5m"]
    df["poly_tfi_2m"] = np.where(tot2 > 0, (df["bull_2m"] - df["bear_2m"]) / tot2, np.nan)
    df["poly_tfi_5m"] = np.where(tot5 > 0, (df["bull_5m"] - df["bear_5m"]) / tot5, np.nan)
    df["poly_trade_count_2m"] = df["n_trades_2m"]
    df["poly_trade_count_5m"] = df["n_trades_5m"]
    df["poly_avg_trade_size_2m"] = np.where(
        df["n_trades_2m"] > 0, df["total_usd_2m"] / df["n_trades_2m"], np.nan
    )
    df["poly_total_usd_2m"] = df["total_usd_2m"]

    out = df[["slug", "timeframe", "window_start",
              "poly_tfi_2m", "poly_tfi_5m",
              "poly_trade_count_2m", "poly_trade_count_5m",
              "poly_avg_trade_size_2m", "poly_total_usd_2m"]].copy()
    out = out.rename(columns={"window_start": "window_start_unix"})
    return out


# ---------------------------------------------------------------------------
# 3. Backtest blocks
# ---------------------------------------------------------------------------

def ic_table(df: pd.DataFrame, label: str, feats: list[str]) -> str:
    lines = [f"\n### IC table — {label} (n={len(df)})\n",
             "| Feature | n | IC (Spearman rho) | p-value |",
             "|---|---|---|---|"]
    for f in feats:
        sub = df.dropna(subset=[f, "outcome_up"])
        if len(sub) < 30 or sub[f].std() == 0:
            lines.append(f"| {f} | {len(sub)} | n/a | n/a |")
            continue
        rho, p = spearmanr(sub[f], sub["outcome_up"])
        sig = "***" if p < 0.001 else ("**" if p < 0.01 else ("*" if p < 0.05 else ""))
        lines.append(f"| {f} | {len(sub)} | {rho:+.4f} {sig} | {p:.2e} |")
    return "\n".join(lines)


def threshold_sweep(df: pd.DataFrame, feat: str, label: str) -> str:
    sub = df.dropna(subset=[feat, "outcome_up"]).copy()
    abs_vals = sub[feat].abs()
    lines = [f"\n### Threshold sweep — {feat} ({label}, n={len(sub)})\n",
             "| pct | threshold | n_fired | hit_rate | dir_split |",
             "|---|---|---|---|---|"]
    for q in [0.50, 0.75, 0.90, 0.95]:
        thr = abs_vals.quantile(q)
        fired = sub[abs_vals >= thr]
        if len(fired) == 0:
            continue
        # Direction: predict UP if feat>0 else DOWN
        pred = (fired[feat] > 0).astype(int)
        hit = (pred.values == fired["outcome_up"].astype(int).values).mean()
        n_up = int((pred == 1).sum())
        n_dn = int((pred == 0).sum())
        lines.append(f"| top {(1-q)*100:.0f}% | {thr:+.4f} | {len(fired)} | {hit:.1%} | up={n_up}/dn={n_dn} |")
    return "\n".join(lines)


def per_direction_table(df: pd.DataFrame, feat: str) -> str:
    """For top 5% |feat|, split hit rate by predicted direction."""
    sub = df.dropna(subset=[feat, "outcome_up"]).copy()
    thr = sub[feat].abs().quantile(0.95)
    fired = sub[sub[feat].abs() >= thr]
    pred = (fired[feat] > 0).astype(int).values
    truth = fired["outcome_up"].astype(int).values
    up_mask = pred == 1
    dn_mask = pred == 0
    lines = [f"\n### Per-direction (top 5% |{feat}|, n={len(fired)})\n",
             "| direction | n | hit_rate |",
             "|---|---|---|"]
    if up_mask.any():
        lines.append(f"| predict UP | {up_mask.sum()} | {(truth[up_mask]==1).mean():.1%} |")
    if dn_mask.any():
        lines.append(f"| predict DOWN | {dn_mask.sum()} | {(truth[dn_mask]==0).mean():.1%} |")
    return "\n".join(lines)


def orthogonality_check(p9: pd.DataFrame) -> str:
    """Correlation of poly_tfi vs Phase 7 imb_slope_2m on overlapping slugs."""
    p7 = pd.read_parquet(PHASE7_PARQUET)
    merged = p9.merge(p7[["slug", "imb_t", "imb_slope_2m", "abs_imb_t"]], on="slug", how="inner")
    lines = [f"\n### Cross-orthogonality vs Phase 7 (n={len(merged)})\n",
             "| Phase 9 feature | Phase 7 feature | Pearson r | Spearman rho |",
             "|---|---|---|---|"]
    for p9f in ["poly_tfi_2m", "poly_tfi_5m"]:
        for p7f in ["imb_t", "imb_slope_2m"]:
            sub = merged.dropna(subset=[p9f, p7f])
            if len(sub) < 30:
                lines.append(f"| {p9f} | {p7f} | n/a | n/a |")
                continue
            pr = sub[p9f].corr(sub[p7f])
            sr, _ = spearmanr(sub[p9f], sub[p7f])
            lines.append(f"| {p9f} | {p7f} | {pr:+.4f} | {sr:+.4f} |")
    return "\n".join(lines), merged


def trade_flow_vs_phase7_overlap(p9: pd.DataFrame, threshold_pctile: float = 0.95) -> str:
    """How much do top-5% |poly_tfi_2m| markets overlap with top-5% |imb_slope_2m|?"""
    p7 = pd.read_parquet(PHASE7_PARQUET)
    merged = p9.merge(p7[["slug", "imb_slope_2m"]], on="slug", how="inner")
    merged = merged.dropna(subset=["poly_tfi_2m", "imb_slope_2m"])
    thr_p9 = merged["poly_tfi_2m"].abs().quantile(threshold_pctile)
    thr_p7 = merged["imb_slope_2m"].abs().quantile(threshold_pctile)
    fire_p9 = merged["poly_tfi_2m"].abs() >= thr_p9
    fire_p7 = merged["imb_slope_2m"].abs() >= thr_p7
    both = (fire_p9 & fire_p7).sum()
    only_p9 = (fire_p9 & ~fire_p7).sum()
    only_p7 = (~fire_p9 & fire_p7).sum()
    return (f"\n### Top-5% gate overlap (n={len(merged)}, thr=p{threshold_pctile*100:.0f})\n"
            f"- only Phase 9 fires: {only_p9}\n"
            f"- only Phase 7 fires: {only_p7}\n"
            f"- BOTH fire:           {both}\n"
            f"- Jaccard:             {both/(only_p9+only_p7+both):.3f} (1.0 = perfect overlap, 0 = orthogonal)\n")


# ---------------------------------------------------------------------------
# 4. Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("Phase 9 — Polymarket Trade Flow Imbalance")
    print("=" * 60)

    # 1) Pull aggregates if not cached
    if RAW_CSV.exists():
        print(f"[cache hit] {RAW_CSV} exists, skipping VPS pull")
        agg = pd.read_csv(RAW_CSV)
    else:
        agg = pull_aggregates()

    # 2) Build features
    feats = build_features(agg)
    OUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    feats.to_parquet(OUT_PARQUET, index=False)
    print(f"[parquet] wrote {OUT_PARQUET} shape={feats.shape}")

    # 3) Join outcome_up
    universe = pd.read_csv(MARKETS_MIN)[["slug", "outcome_up"]].dropna()
    universe["outcome_up"] = universe["outcome_up"].astype(int)
    df = feats.merge(universe, on="slug", how="inner")

    # Filter to markets with at least 1 trade in 2m window
    df_active = df[df["poly_trade_count_2m"] >= 1].copy()
    df_active5 = df[df["poly_trade_count_5m"] >= 1].copy()

    # 4) Build report
    report = ["# Phase 9 — Polymarket Trade Flow Imbalance\n",
              f"_Generated: 2026-05-05_\n",
              "## Data\n",
              f"- Source: VPS2 `trades_v2` (18.88M rows, 13.9M BTC)\n",
              f"- Universe: {len(df)} BTC markets ({(df['timeframe']=='5m').sum()} 5m, "
              f"{(df['timeframe']=='15m').sum()} 15m)\n",
              f"- Markets with >=1 trade in first 2m: {len(df_active)} "
              f"({len(df_active)/len(df):.1%})\n",
              f"- Markets with >=1 trade in first 5m: {len(df_active5)} "
              f"({len(df_active5)/len(df):.1%})\n",
              f"- Median trades/market in 2m: {int(df_active['poly_trade_count_2m'].median())}\n",
              f"- Median trades/market in 5m: {int(df_active5['poly_trade_count_5m'].median())}\n",
              f"- Median total USD/market 2m: ${df_active['poly_total_usd_2m'].median():.0f}\n",
              ]

    feats_for_ic = ["poly_tfi_2m", "poly_tfi_5m",
                    "poly_trade_count_2m", "poly_trade_count_5m",
                    "poly_avg_trade_size_2m"]
    report.append("\n## IC vs outcome_up — ALL\n")
    report.append(ic_table(df_active, "all timeframes (active)", feats_for_ic))

    report.append("\n## IC by timeframe\n")
    for tf in ["5m", "15m"]:
        sub = df_active[df_active["timeframe"] == tf]
        if len(sub) > 0:
            report.append(ic_table(sub, f"{tf} markets", feats_for_ic))

    report.append("\n## Threshold sweep — poly_tfi_2m\n")
    report.append(threshold_sweep(df_active, "poly_tfi_2m", "all"))
    for tf in ["5m", "15m"]:
        sub = df_active[df_active["timeframe"] == tf]
        if len(sub) > 100:
            report.append(threshold_sweep(sub, "poly_tfi_2m", tf))

    report.append("\n## Threshold sweep — poly_tfi_5m (15m markets only)\n")
    sub15 = df_active5[df_active5["timeframe"] == "15m"]
    if len(sub15) > 100:
        report.append(threshold_sweep(sub15, "poly_tfi_5m", "15m"))

    report.append(per_direction_table(df_active, "poly_tfi_2m"))

    ortho_str, _ = orthogonality_check(df_active)
    report.append("\n## Orthogonality vs Phase 7\n")
    report.append(ortho_str)
    report.append(trade_flow_vs_phase7_overlap(df_active))

    # Print report to stdout for inspection
    full = "\n".join(report)
    print(full[:3000])

    # Verdict block — computed dynamically
    sub = df_active.dropna(subset=["poly_tfi_2m", "outcome_up"])
    if len(sub) >= 30:
        rho_ic, p_ic = spearmanr(sub["poly_tfi_2m"], sub["outcome_up"])
        thr95 = sub["poly_tfi_2m"].abs().quantile(0.95)
        fired = sub[sub["poly_tfi_2m"].abs() >= thr95]
        pred = (fired["poly_tfi_2m"] > 0).astype(int)
        hit_top5 = (pred.values == fired["outcome_up"].astype(int).values).mean()
        verdict = (
            f"\n## Verdict\n\n"
            f"- IC poly_tfi_2m: {rho_ic:+.4f} (p={p_ic:.2e}, n={len(sub)})\n"
            f"- Top 5% |TFI| hit rate: {hit_top5:.1%} on {len(fired)} markets\n"
        )
        report.append(verdict)

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(report), encoding="utf-8")
    print(f"\n[report] wrote {REPORT_PATH}")


if __name__ == "__main__":
    main()
