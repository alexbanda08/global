"""V8: rank survivors, dedup by lockbox metric fingerprint, surface top candidates."""
import os
import pandas as pd
import numpy as np

ROOT = r"C:\Users\alexandre bandarra\Desktop\global"
RES = os.path.join(ROOT, r"strategy_lab\sniper_search_2026_05_27\eth_5m_v8\_results")
IN = os.path.join(RES, "v8_validated.csv")
OUT_RANKED = os.path.join(RES, "v8_ranked.csv")
OUT_TOP30 = os.path.join(RES, "v8_top30_unique.csv")
OUT_TOPV8NEW = os.path.join(RES, "v8_top_v8_new_only.csv")
OUT_TOP5 = os.path.join(RES, "top_5_candidates_v8.csv")


V8_NEW_GATES = {
    "g_sol_trend_slope_with", "g_sol_mp_skew_with",
    "g_2a_btc_sol_trend_with", "g_2a_btc_sol_mp_with",
    "g_3a_unanimity_trend", "g_3a_unanimity_full",
    "g_tod_asia_morning", "g_tod_european_morning",
    "g_tod_us_afternoon", "g_tod_us_evening", "g_tod_europe_us_window",
    "g_q_prev15m_agrees", "g_q_15m_streak_agrees",
    "g_grandparent_trend_with", "g_grandparent_strong_trend_with", "g_l_mtf_unanimity",
}


def main():
    df = pd.read_csv(IN)
    print(f"Loaded {len(df)} survivors")

    # add count of v8-new gates per stack
    def count_v8_new(stack):
        atoms = set(stack.split("&"))
        return len(atoms & V8_NEW_GATES)
    df["n_v8_new"] = df["gate_stack"].apply(count_v8_new)

    # Robust filter
    rob = df[(df.n_lockbox >= 25) &
             (df.dpt_25_train > 0) &
             (df.dpt_25_val > 0) &
             (df.dd_25_lockbox >= -300) &
             (df.loss_streak <= 6) &
             (df.bootstrap_p_lockbox <= 0.05)].copy()
    print(f"Robust: {len(rob)}")

    # Composite ranking score: balance honest projection, edge, and stability
    rob["score_objective"] = rob["dpt_25_lockbox"] * np.sqrt(rob["n_lockbox"]) * (1 + 0.1 * np.log10(np.maximum(rob["n_lockbox"], 1)))
    rob["score_honest"] = rob["proj_honest"]
    rob = rob.sort_values("score_honest", ascending=False).reset_index(drop=True)
    rob.to_csv(OUT_RANKED, index=False)

    # Dedup by lockbox fingerprint
    rob["fp"] = rob.apply(lambda r: f"{r.n_lockbox}|{r.wr_lockbox:.4f}|{r.dpt_25_lockbox:.3f}|{r.sum_25_lockbox:.2f}|{r.dd_25_lockbox:.2f}", axis=1)
    uniq = rob.drop_duplicates("fp").head(60).copy()
    uniq.to_csv(OUT_TOP30, index=False)
    print(f"Unique by fp: {len(uniq)}")

    # V8-new-containing
    v8new = uniq[uniq["n_v8_new"] >= 1].head(30)
    v8new.to_csv(OUT_TOPV8NEW, index=False)
    print(f"V8-new-containing (top 30): {len(v8new)}")

    # ---- Pick top 5 candidates ----
    # Criterion: prefer different (gate_stack_principal_family), highest proj_honest, diverse offsets
    families_seen = set()
    candidates = []
    for _, r in uniq.iterrows():
        atoms = frozenset(r.gate_stack.split("&"))
        # family: top 3 most-distinguishing gates
        fam_key = tuple(sorted(atoms))[:3]
        if fam_key in families_seen:
            continue
        families_seen.add(fam_key)
        candidates.append(r)
        if len(candidates) >= 5:
            break
    top5 = pd.DataFrame(candidates).reset_index(drop=True)
    top5["cand"] = [f"c{i+1}" for i in range(len(top5))]
    cols_order = ["cand"] + [c for c in top5.columns if c != "cand"]
    top5 = top5[cols_order]
    top5.to_csv(OUT_TOP5, index=False)
    print(f"\nTop 5 candidates:")
    print(top5[["cand", "offset", "depth", "gate_stack", "n_lockbox", "wr_lockbox",
                 "dpt_25_lockbox", "sum_25_lockbox", "dd_25_lockbox", "proj_32d", "proj_full", "proj_honest", "n_v8_new"]].to_string())


if __name__ == "__main__":
    main()
