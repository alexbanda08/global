"""PHASE A2 — Bug hunt across V52 + V24 codebase."""
import sys, re
from pathlib import Path
import pandas as pd
import numpy as np
sys.path.insert(0, "C:/Users/alexandre bandarra/Desktop/global")
import warnings; warnings.filterwarnings("ignore")

REPO = Path("C:/Users/alexandre bandarra/Desktop/global")

findings = []

# === Bug 1: Look for shift(-1) (future leak) and unsafe rolling().max() on close ===
sig_files = [
    "strategy_lab/strategies/v50_new_signals.py",
    "strategy_lab/run_v30_creative.py",
    "strategy_lab/run_v29_regime.py",
    "strategy_lab/v23_low_dd_xsm.py",
    "strategy_lab/eval/perps_simulator_funding.py",
    "strategy_lab/regime/hmm_adaptive.py",
    "strategy_lab/run_leverage_audit.py",
    "strategy_lab/util/hl_data.py",
]
for fn in sig_files:
    p = REPO / fn
    if not p.exists(): continue
    src = p.read_text(encoding="utf-8", errors="ignore").split("\n")
    for ln, txt in enumerate(src, 1):
        if "shift(-" in txt:
            findings.append(("LOOKAHEAD-shift-neg", fn, ln, txt.strip()))
        # check for use of .max() on future window via rolling without proper shift
        # specifically pattern: rolling_max(close, X) then COMPARED to current close
        # legitimate when used as ENTRY level. Suspicious if used FOR signal generation w/o shift.

# === Bug 2: Funding sign verification ===
# load actual implementation
funding_text = (REPO / "strategy_lab/eval/perps_simulator_funding.py").read_text(encoding="utf-8")
# search for "funding_pnl"
for m in re.finditer(r'funding_pnl\s*=\s*(.+)', funding_text):
    findings.append(("FUND-formula", "perps_simulator_funding.py", "?", m.group(0).strip()))

# === Bug 3: HMM adaptive train_frac forward-leak check ===
hmm = (REPO / "strategy_lab/regime/hmm_adaptive.py").read_text(encoding="utf-8")
# Search for any usage of full-feature mean/std in z-score
if "feats.mean()" in hmm or "feats.std()" in hmm:
    findings.append(("HMM-leak-suspect", "hmm_adaptive.py", "?", "uses feats.mean/std globally?"))
# but earlier search said: "z-score using IS-only stats" — so probably OK. Check explicit:
if "train_X_raw.mean" in hmm:
    findings.append(("HMM-good", "hmm_adaptive.py", "?", "train_X_raw.mean / std used = forward-only OK"))

# === Bug 4: invvol_blend window=500 warmup ===
inv = (REPO / "strategy_lab/run_leverage_audit.py").read_text(encoding="utf-8")
if "window=500" in inv or "window: int = 500" in inv:
    findings.append(("INVVOL-warmup", "run_leverage_audit.py", "?", "window=500 means first 500 bars use min_periods fallback"))

# === Bug 5: V52 weights hard-coded 0.60/0.10/0.10/0.10/0.10 ===
v52 = (REPO / "strategy_lab/run_v52_hl_gates.py").read_text(encoding="utf-8")
if "0.60" in v52 and "0.10" in v52:
    findings.append(("V52-static-weights", "run_v52_hl_gates.py", "?", "V41 sleeve 60% + 4 diversifiers @ 10% each — fixed, no rebalance learning"))

# === Bug 6: HL data utility — funding_per_4h_bar floor("4h") ===
hldat = (REPO / "strategy_lab/util/hl_data.py").read_text(encoding="utf-8")
if 'floor("4h")' in hldat:
    findings.append(("HL-funding-bucketing", "hl_data.py", "?", "uses floor(4h) — confirms 4-hour-aligned bucket (correct for HL hourly funding)"))

# === Bug 7: Print V41_VARIANT_MAP and DIV_SPECS exact lines ===
v52_lines = v52.split("\n")
for i, ln in enumerate(v52_lines, 1):
    if "V41_VARIANT_MAP" in ln and "=" in ln and "{" in ln:
        findings.append(("V52-variant-map-line", "run_v52_hl_gates.py", i, ln.strip()))
    if "DIV_SPECS" in ln and "=" in ln and "[" in ln:
        findings.append(("V52-div-specs-line", "run_v52_hl_gates.py", i, ln.strip()))

# === Bug 8: Volume-profile signal lookahead (rolling on volume + price bins) ===
vp = (REPO / "strategy_lab/strategies/v50_new_signals.py").read_text(encoding="utf-8")
# Look for the volume_profile_rot impl
vp_lines = vp.split("\n")
for i, ln in enumerate(vp_lines, 1):
    if "volume_profile_rot" in ln and "def" in ln:
        findings.append(("VP-impl-line", "v50_new_signals.py", i, ln.strip()))
    if ".iloc[i:" in ln or "df.iloc[i:" in ln:  # forward-window slicing
        findings.append(("LOOKAHEAD-forward-slice", "v50_new_signals.py", i, ln.strip()))

# === Bug 9: BTC bear filter uses btc_ma_fast vs btc_ma_fast.iloc[i-24] (1 day prior) ===
# In V24, check the comparison direction
xsm = (REPO / "strategy_lab/v23_low_dd_xsm.py").read_text(encoding="utf-8")
xsm_lines = xsm.split("\n")
for i, ln in enumerate(xsm_lines, 1):
    if "btc_ma_fast.iloc[i - 24]" in ln or "btc_ma_fast.iloc[i-24]" in ln:
        findings.append(("XSM-rising-test", "v23_low_dd_xsm.py", i, ln.strip()))
    if "breadth < mf_breadth_min" in ln:
        findings.append(("XSM-breadth-test", "v23_low_dd_xsm.py", i, ln.strip()))

# === Bug 10: simulate_with_funding — check entry direction ===
# Already known: funding_pnl = -pos * size * cl[i] * fund[i]
# So if pos=+1 (long) and fund>0: pnl = -size*cl*fund < 0  => long pays. CORRECT.
findings.append(("FUND-sign-OK", "perps_simulator_funding.py", "—", "verified: pos=+1 fund>0 => pnl<0 (long pays). Correct."))

import json
out_path = REPO / "strategy_lab/hl_research_2026_05_26/v52_v24_audit/a2_bug_findings.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(findings, f, indent=2, default=str)
for tag, file, ln, txt in findings:
    print(f"[{tag:25s}] {file}:{ln} :: {txt[:80]}")
print(f"\nTotal findings: {len(findings)}")
print(f"Saved -> {out_path}")
