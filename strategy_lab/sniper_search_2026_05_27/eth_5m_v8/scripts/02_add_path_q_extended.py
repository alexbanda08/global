"""V8 universe: extend with corrected Path Q signals based on PREVIOUS 15m slot outcome (causal)."""

import os
import pandas as pd
import numpy as np

ROOT = r"C:\Users\alexandre bandarra\Desktop\global"
UNIV = os.path.join(ROOT, r"data\v4\canonical\_results\_sniper_eth5m_v8_universe.parquet")
ETH_15M_FIRES = os.path.join(ROOT, r"data\v4\canonical\_results\_full_window_v3_2026_05_27\oos_fires_ETH_15m_full_v3.parquet")


def main():
    df = pd.read_parquet(UNIV)
    eth15 = pd.read_parquet(ETH_15M_FIRES)

    # Clean up any prior failed-run cols
    for c in ["streak_up_2bar", "streak_dn_2bar",
              "g_q_prev15m_winner_up", "g_q_prev15m_winner_dn",
              "g_q_prev15m_agrees", "g_q_prev15m_disagrees",
              "g_q_15m_streak_agrees", "eth15_winner"]:
        if c in df.columns:
            df = df.drop(columns=[c])

    is_up = (df["direction"] == "UP")

    # For each ETH 15m SLUG (one slot), the WIN direction is well-defined:
    # outcome column is 'Up'/'Down' (camelCase) — use `won` flag instead.
    # The winning rows are those with won==1; their direction is the actual winner.
    winners = eth15[eth15["won"] == 1].copy()
    slot_outcome = (winners.groupby("slot_start_us")["direction"].first()
                    .to_frame("eth15_winner")
                    .reset_index())
    slot_outcome["slot_end_us"] = (slot_outcome["slot_start_us"].astype("int64") + 900_000_000)

    # For each 5m fire, find the most recent ETH 15m slot whose slot_end_us <= ws_s_us (already resolved)
    slot_lookup = slot_outcome[["slot_end_us", "eth15_winner"]].rename(columns={"slot_end_us": "ts_us"}).sort_values("ts_us").reset_index(drop=True)

    keys = df[["slug", "ws_s_us"]].sort_values("ws_s_us").reset_index(drop=True)
    keys = pd.merge_asof(keys, slot_lookup,
                          left_on="ws_s_us", right_on="ts_us",
                          direction="backward", tolerance=1800_000_000)
    keys = keys.drop(columns=["ts_us"])

    df = df.merge(keys.drop_duplicates(["slug", "ws_s_us"]),
                  on=["slug", "ws_s_us"], how="left")

    # Gates (CAUSAL — uses only completed previous 15m slot winner)
    df["g_q_prev15m_winner_up"] = (df["eth15_winner"] == "UP").astype(int)
    df["g_q_prev15m_winner_dn"] = (df["eth15_winner"] == "DOWN").astype(int)
    df["g_q_prev15m_agrees"] = (
        (is_up & (df["eth15_winner"] == "UP")) |
        (~is_up & (df["eth15_winner"] == "DOWN"))
    ).astype(int)
    df["g_q_prev15m_disagrees"] = (
        (is_up & (df["eth15_winner"] == "DOWN")) |
        (~is_up & (df["eth15_winner"] == "UP"))
    ).astype(int)

    # Drop the helper col
    df = df.drop(columns=["eth15_winner"])

    # 2-bar consecutive 15m winners — momentum signal
    # Build slot-level 2-bar streak
    slot_outcome = slot_outcome.sort_values("slot_start_us").reset_index(drop=True)
    slot_outcome["prev_winner"] = slot_outcome["eth15_winner"].shift(1)
    slot_outcome["streak_up_2bar"] = ((slot_outcome["eth15_winner"] == "UP") & (slot_outcome["prev_winner"] == "UP")).astype(int)
    slot_outcome["streak_dn_2bar"] = ((slot_outcome["eth15_winner"] == "DOWN") & (slot_outcome["prev_winner"] == "DOWN")).astype(int)
    slot_lookup2 = slot_outcome[["slot_end_us", "streak_up_2bar", "streak_dn_2bar"]].rename(columns={"slot_end_us": "ts_us"})

    keys2 = df[["slug", "ws_s_us"]].sort_values("ws_s_us").reset_index(drop=True)
    keys2 = pd.merge_asof(keys2, slot_lookup2,
                           left_on="ws_s_us", right_on="ts_us",
                           direction="backward", tolerance=1800_000_000)
    keys2 = keys2.drop(columns=["ts_us"])
    df = df.merge(keys2.drop_duplicates(["slug", "ws_s_us"]),
                  on=["slug", "ws_s_us"], how="left")

    df["streak_up_2bar"] = df["streak_up_2bar"].fillna(0).astype(int)
    df["streak_dn_2bar"] = df["streak_dn_2bar"].fillna(0).astype(int)
    df["g_q_15m_streak_agrees"] = (
        (is_up & (df["streak_up_2bar"] == 1)) |
        (~is_up & (df["streak_dn_2bar"] == 1))
    ).astype(int)
    df = df.drop(columns=["streak_up_2bar", "streak_dn_2bar"])

    df.to_parquet(UNIV)
    print(f"  shape: {df.shape}")
    for g in ["g_q_prev15m_agrees", "g_q_prev15m_winner_up", "g_q_prev15m_winner_dn",
              "g_q_prev15m_disagrees", "g_q_15m_streak_agrees"]:
        print(f"  {g}: cov={df[g].fillna(0).astype(float).mean()*100:.2f}%")


if __name__ == "__main__":
    main()
