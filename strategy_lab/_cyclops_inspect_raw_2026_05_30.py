"""Inspect raw cyclops message formats — dump one sample per type."""
import pandas as pd, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
df = pd.read_csv(r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\wallet_hunt\cyclops_signals.csv")
print("CYCLOPS_INSPECT_RAW_2026_05_30 OUTPUT")
print("total rows:", len(df))
for t in df["type"].unique():
    sub = df[df["type"] == t]
    print("\n" + "="*70)
    print(f"TYPE={t}  n={len(sub)}")
    for i, r in sub.head(3).iterrows():
        print("-"*50)
        print("msg_id", r["msg_id"], "post_ts", r["post_ts"], "dir", r["direction"])
        raw = str(r["raw"])
        # raw uses ' | ' as line join in some, '\n' in others
        print(repr(raw[:600]))
