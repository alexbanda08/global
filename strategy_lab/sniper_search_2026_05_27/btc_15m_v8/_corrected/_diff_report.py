"""Produce ORIG vs CORRECTED diff for V8 BTC 15m top-5."""
import pandas as pd
orig = pd.read_csv(r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/sniper_search_2026_05_27/btc_15m_v8/top_5_candidates_v8.csv")
corr = pd.read_csv(r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/sniper_search_2026_05_27/btc_15m_v8/_corrected/top_5_candidates_v8_CORRECTED.csv")

print("=" * 100)
print("V8 BTC 15m: ORIG (BUGGY 25x) vs CORRECTED ($25 stake)")
print("=" * 100)
print()
for i in range(5):
    o = orig.iloc[i]
    c = corr.iloc[i]
    print(f"--- Rank {i+1}: {c.gates} (off={c.off} dir={c.dir}) ---")
    print(f"  n_full              : {int(o.n_full):4d}  (unchanged)")
    print(f"  WR_full             : {o.wr_full*100:.2f}%   (unchanged: corr={c.wr_full*100:.2f}%)")
    print(f"  $/tr_full   ORIG: ${o.dpt_25_full:+10.3f}  ->  CORR: ${c.dpt_full:+10.3f}   ratio={o.dpt_25_full/c.dpt_full:.2f}x")
    print(f"  sum_full    ORIG: ${o.total_pnl_full:+11.2f}  ->  CORR: ${c.sum_full:+11.2f}   ratio={o.total_pnl_full/c.sum_full:.2f}x")
    print(f"  DD_full     ORIG: ${o.max_dd_25:+11.2f}  ->  CORR: ${c.dd_full:+11.2f}   ratio={abs(o.max_dd_25)/max(abs(c.dd_full),1e-6):.2f}x")
    print(f"  LS_full     ORIG: {int(o.loss_streak):4d}  ->  CORR: {int(c.loss_streak_full):4d}   (unchanged)")
    print(f"  p_full      ORIG: {o.bootstrap_p_full:.4f}  ->  CORR: {c.bootstrap_p_full:.4f}")
    print(f"  proj_32d    ORIG: ${o.proj_32d:+11.2f}  ->  CORR: ${c.proj_32d_lock:+11.2f}   ratio={o.proj_32d/c.proj_32d_lock:.2f}x")
    print(f"  proj_honest ORIG: ${o.proj_honest:+11.2f}  ->  CORR: ${c.proj_honest:+11.2f}   ratio={o.proj_honest/c.proj_honest:.2f}x")
    print()

print()
print("=" * 100)
print("KEY TAKEAWAY")
print("=" * 100)
print(f"Original V8 script multiplied pnl_legacy_usd by 25.0 in metrics()")
print(f"But pnl_legacy_usd was ALREADY built with NOTIONAL=25.0 in full_window_validation_v2.py")
print(f"=> All original $/tr, sum, DD, proj_* numbers were 25x INFLATED ($625 effective stake)")
print(f"WR, n, loss_streak, bootstrap_p (scale-invariant) — UNCHANGED")
