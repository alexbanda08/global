"""Drill into V8-new-gate sleeves: best per V8 path."""
import os
import pandas as pd

ROOT = r"C:\Users\alexandre bandarra\Desktop\global"
RES = os.path.join(ROOT, r"strategy_lab\sniper_search_2026_05_27\eth_5m_v8\_results")
RANKED = os.path.join(RES, "v8_ranked.csv")

V8_PATHS = {
    "J_2asset": {"g_2a_btc_sol_trend_with", "g_2a_btc_sol_mp_with",
                  "g_3a_unanimity_trend", "g_3a_unanimity_full",
                  "g_sol_trend_slope_with", "g_sol_mp_skew_with"},
    "K_TOD": {"g_tod_asia_morning", "g_tod_european_morning",
              "g_tod_us_afternoon", "g_tod_us_evening", "g_tod_europe_us_window"},
    "Q_15m": {"g_q_prev15m_agrees", "g_q_15m_streak_agrees"},
    "L_grandparent": {"g_grandparent_trend_with", "g_grandparent_strong_trend_with",
                       "g_l_mtf_unanimity"},
}


def main():
    df = pd.read_csv(RANKED)
    print(f"Total ranked: {len(df)}")

    for path_name, gates in V8_PATHS.items():
        mask = df["gate_stack"].apply(lambda s: bool(gates & set(s.split("&"))))
        sub = df[mask].sort_values("proj_honest", ascending=False).head(10)
        print(f"\n=== Path {path_name} ({len(df[mask])} survivors total, top 10 by proj_honest) ===")
        if len(sub) > 0:
            print(sub[["offset", "depth", "gate_stack", "n_lockbox", "wr_lockbox",
                       "dpt_25_lockbox", "sum_25_lockbox", "dd_25_lockbox",
                       "n_full", "wr_full", "dpt_25_full", "sum_25_full",
                       "proj_32d", "proj_full", "proj_honest"]].to_string(max_colwidth=80))


if __name__ == "__main__":
    main()
