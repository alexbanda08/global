"""Diagnose: which sleeves pass without strict active-days requirement?
A 1-active-day lockbox is risky but may still satisfy WR/$/tr if the day is huge."""
import pandas as pd, numpy as np
RES = "strategy_lab/sniper_search_2026_05_27/eth_5m/_results"
res = pd.read_csv(f"{RES}/all_validated.csv")

# Brief profile (strict)
def profile_pass(row, stake):
    n = row[f"n_lockbox"]
    wr = row[f"wr_lockbox"]
    dpt = row[f"dpt_lockbox_{stake}"]
    dd = row[f"dd_lockbox_{stake}"]
    ls = row["ls_lockbox"]
    sh = row["sharpe_lockbox"]
    p = row["boot_p_lockbox"]
    dpt_thr = 3.0 if stake == 25 else 30.0
    dd_thr = -300.0 if stake == 25 else -3000.0
    return (
        n >= 5 and n <= 500 and
        wr >= 0.75 and
        dpt >= dpt_thr and
        dd >= dd_thr and
        ls <= 6 and
        sh >= 2.0 and
        p <= 0.05
    )

res["pass_25"] = res.apply(lambda r: profile_pass(r, 25), axis=1)
res["pass_250"] = res.apply(lambda r: profile_pass(r, 250), axis=1)
res["has_depth_gate"] = res["sleeve_id"].str.contains("g_book_depth_supports_250(?!_)", regex=True)

print(f"pass_25 (no depth gate constraint): {res['pass_25'].sum()}")
print(f"pass_250 (depth gate required): {(res['pass_250'] & res['has_depth_gate']).sum()}")

# Show what's actually passing
pp25 = res[res["pass_25"]].sort_values("dpt_lockbox_25", ascending=False)
print(f"\n== Pass at $25 ({len(pp25)}) ==")
for _, r in pp25.head(20).iterrows():
    print(f"  WR_l={r['wr_lockbox']:.3f} $/tr_l={r['dpt_lockbox_25']:+.2f} n_l={r['n_lockbox']} ad={int(r['active_days_lockbox'])} dd=${r['dd_lockbox_25']:.0f} ls={int(r['ls_lockbox'])} sh={r['sharpe_lockbox']:.1f} p={r['boot_p_lockbox']:.3f} | tr WR={r['wr_train']:.3f}/n={r['n_train']} val WR={r['wr_val']:.3f}/n={r['n_val']} $/tr_v={r['dpt_val_25']:+.2f}")
    print(f"    {r['sleeve_id']}")

pp250 = res[res["pass_250"] & res["has_depth_gate"]].sort_values("dpt_lockbox_250", ascending=False)
print(f"\n== Pass at $250 with depth gate ({len(pp250)}) ==")
for _, r in pp250.head(20).iterrows():
    print(f"  WR_l={r['wr_lockbox']:.3f} $/tr_250={r['dpt_lockbox_250']:+.1f} n_l={r['n_lockbox']} ad={int(r['active_days_lockbox'])} dd_250=${r['dd_lockbox_250']:.0f} ls={int(r['ls_lockbox'])} sh={r['sharpe_lockbox']:.1f} p={r['boot_p_lockbox']:.3f} | tr WR={r['wr_train']:.3f}/n={r['n_train']} val WR={r['wr_val']:.3f}/n={r['n_val']}")
    print(f"    {r['sleeve_id']}")
