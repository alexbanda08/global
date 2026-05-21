import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fingerprint import fingerprint_wallet

wallets = [
    "0xeebde7a0e019a63e6b476eb425505b7b3e6eba30",
    "0xce25e214d5cfe4f459cf67f08df581885aae7fdc",
    "0x89b5cdaaa4866c1e738406712012a630b4078beb",
    "0x7cde1da9d380bf8002ccbe8e0cb9474c4d71e48e",
    "0xcfb103c37c0234f524c632d964ed31f117b5f694",
    "0x04b6d7e930cf9e493c5e6ef24b496294f95594c8",
]

all_fp = []
for w in wallets:
    try:
        fp = fingerprint_wallet(w)
    except Exception as e:
        import traceback; traceback.print_exc()
        fp = {"wallet": w, "short": w[:10], "error": str(e)[:60]}
    all_fp.append(fp)

print(f"{'wallet':<10} {'trades':>6} {'spanH':>6} {'tpm':>5} {'val$':>7} {'pos':>4} {'BUY%':>5} "
      f"{'updwn%':>6} {'med_px':>6} {'tr/leg':>6} {'1trd%':>5} {'bothS%':>6} CLASS")
print("-" * 130)
for fp in all_fp:
    if "error" in fp:
        print(f"{fp.get('short','-'):<10} ERROR: {fp['error']}")
        continue
    print(f"{fp.get('short','-'):<10} {fp.get('n_trades',0):>6} "
          f"{fp.get('time_span_hours',0):>6.1f} {fp.get('trades_per_minute',0):>5.2f} "
          f"{(fp.get('portfolio_value_now') or 0):>7.0f} {fp.get('open_positions',0):>4} "
          f"{fp.get('side_BUY_pct',0):>5.1f} {fp.get('up_down_focus_pct',0):>6.1f} "
          f"{(fp.get('avg_buy_px_med') or 0):>6.3f} {fp.get('avg_trades_per_leg',0):>6.1f} "
          f"{fp.get('leg_pct_single_trade',0):>5.1f} {fp.get('leg_pct_with_both_sides',0):>6.1f} "
          f"{fp.get('strategy_class','-')}")

with open(Path(__file__).resolve().parent / "cache" / "_fingerprints.json", "w") as f:
    json.dump(all_fp, f, indent=2, default=str)
print("\nsaved cache/_fingerprints.json")
