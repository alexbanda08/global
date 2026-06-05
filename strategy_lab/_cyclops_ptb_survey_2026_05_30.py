"""Survey PTB square patterns + confidence + arrows across SIGNAL rows."""
import pandas as pd, sys, io, re
from collections import Counter
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
df = pd.read_csv(r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\wallet_hunt\cyclops_signals.csv")
print("PTB_SURVEY_2026_05_30 OUTPUT")
sig = df[df["type"] == "SIGNAL"]
RED, GRN = "🟥", "🟩"
ptb_lines = Counter()
arrow_c = Counter()
conf_c = Counter()
for _, r in sig.iterrows():
    raw = str(r["raw"])
    # PTB line: "BTC <arrow> PTB <squares>"
    m = re.search(r"BTC\s*([▲▼≈➡️↗↘])\s*PTB\s*([🟥🟩]*)", raw)
    if m:
        arrow, squares = m.group(1), m.group(2)
        nr = squares.count(RED); ng = squares.count(GRN)
        ptb_lines[(arrow, nr, ng, len(squares))] += 1
        arrow_c[arrow] += 1
    # confidence dots
    mc = re.search(r"Confidence\s*([●○]+)\s*(\w+)", raw)
    if mc:
        conf_c[(mc.group(1).count("●"), mc.group(2))] += 1
print("\nPTB (arrow, n_red, n_green, total_squares) -> count:")
for k, v in sorted(ptb_lines.items(), key=lambda x: -x[1]):
    print(f"  {k} -> {v}")
print("\narrow counts:", dict(arrow_c))
print("\nconfidence (n_dots, label) -> count:")
for k, v in sorted(conf_c.items()):
    print(f"  {k} -> {v}")
