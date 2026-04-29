"""One-shot scan of strategy_lab/ to build the canonical registry.

Reads every root-level run_v*.py and strategies*.py, extracts signal-function
names, feature dependencies, symbols, timeframes. Writes a compact JSON summary
to stdout for the LLM to consume (kept tiny on purpose).
"""
from __future__ import annotations
import json
import re
from pathlib import Path

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab")

EXCLUDE_SUBDIRS = {"data","logs","reports","results","external","kronos_ft",
                   "hyperliquid","features","__pycache__","pine","prompts"}

# Harness identifiers: scripts that drive sweeps, build PDFs, audits, validators,
# dashboards — they don't DEFINE signal logic.
HARNESS_PREFIXES = (
    "build_","per_asset_report","final_report","dashboard",
    "analyze","run_sweep","run_alt_tests","run_dashboard","smoke_",
    "tiny_","advanced_simulator","alpha_analysis","detailed_metrics",
    "edge_hunt","fetch_","features_","hwr_hunt","iaf_multi_compare",
    "kronos_","live_forward","native_to_iaf","portfolio","portfolio_audit",
    "robust_validate","run_v22_oos_audit","run_v23_oos_all","run_v24_oos",
    "run_v25_oos","run_v26_oos","run_v27_oos","run_v28_peryear_audit",
    "run_v28_validate_winner","run_v29_oos","run_v30_oos","run_v31_overfit_audit",
    "run_v32_core_audit","run_v33_audit","run_v34_audit","run_v38_smc_sweep",
    "run_v38b_smc_mixes","run_v38c_smc_xsm_breadth","test_combos","v18_robustness",
    "v21_leverage_sweep","v30_overfitting_audit","v35_cross_reference",
    "v36_hybrid_leverage","validate","validate_alternatives","walk_forward",
    "run_per_asset",
    # v8_hunt/v10_hunt/v11_hunt etc. are hunt/sweep drivers that import from
    # strategies_vN.py — they're harnesses for parameter search
    "v8_hunt","v10_hunt","v11_hunt","v12_hunt","v19_20_hunt",
    "v15_xsm_variants","v17_pairs_trading","v29_long_short_deep",
    "v14_cross_sectional","v16_ml_rank","v23_low_dd_xsm",
)

def is_harness(name: str) -> bool:
    if name == "engine" or name == "__init__": return True
    for p in HARNESS_PREFIXES:
        if name == p or name.startswith(p): return True
    return False

def read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""

FEATURE_PATTERNS = {
    "atr": r"\batr\b|_atr\(|atr_pct|ATR",
    "adx": r"\badx\b|ADX",
    "rsi": r"\brsi\b|RSI",
    "macd": r"\bmacd\b|MACD",
    "bollinger": r"\bBBANDS\b|bb_upper|bb_lower|bollinger",
    "donchian": r"donchian|don_len|rolling_max|rolling\(.+\)\.max",
    "kalman": r"kalman|_kalman_filter",
    "ott": r"\b_ott\b|var_ma|VAR_MA",
    "supertrend": r"supertrend|SUPERTREND",
    "ichimoku": r"ichimoku|tenkan|kijun|senkou",
    "heikin_ashi": r"heikin|ha_close|ha_open",
    "ema": r"\bema\b|\.ewm\(",
    "hma": r"\bhma\b|hull_ma",
    "keltner": r"keltner",
    "squeeze": r"squeeze|TTM",
    "gaussian_channel": r"gaussian_channel|gauss",
    "kalman_range": r"range_kalman|kalman_range",
    "stoch": r"\bstoch\b|stochastic",
    "funding": r"funding",
    "open_interest": r"open_interest|\bOI\b|oi_",
    "liquidations": r"liquidation|liq_cascade",
    "taker_delta": r"taker_delta|taker_buy",
    "long_short_ratio": r"long_short|ls_ratio|ls_extreme",
    "ml_classifier": r"RandomForest|XGB|LightGBM|sklearn|lightgbm|lgb\.",
    "kronos": r"kronos",
    "smc_ob": r"order_block|\bOB\b|smc_|bos_|choch",
    "ict": r"\bICT\b|fair_value_gap|fvg",
    "pairs": r"pairs|zscore.*pair|cointegr",
    "grid": r"grid_|grid_step|_grid_",
    "kc_bounce": r"keltner_bounce|kc_bounce",
}

SYMBOL_RE = re.compile(r'"([A-Z]{2,6}USDT)"')
TF_RE = re.compile(r'"(1m|3m|5m|15m|30m|1h|2h|4h|6h|8h|12h|1d|1w)"')

def scan(path: Path) -> dict:
    src = read(path)
    name = path.stem
    info = {"file": str(path.relative_to(ROOT.parent)).replace("\\","/"),
            "name": name,
            "funcs": [],
            "imports_strategies": [],
            "symbols": sorted(set(SYMBOL_RE.findall(src))),
            "tfs": sorted(set(TF_RE.findall(src))),
            "features": [],
            "size": len(src),
            "is_harness": is_harness(name)}
    # function defs (signal-shaped only)
    for m in re.finditer(r"^def ([a-zA-Z_][a-zA-Z0-9_]*)\(", src, re.MULTILINE):
        fn = m.group(1)
        if fn.startswith("_"): continue
        # Heuristic: only include fns that eventually return dict with entries/exits
        # or which look like strategy names. For runner files we care if ANY function
        # defines entries/exits
        info["funcs"].append(fn)
    # detect entries/exits to confirm signal logic
    info["has_signal_logic"] = bool(re.search(r"\bentries\s*=", src) and re.search(r"\bexits\s*=", src))
    # imports from strategies_vN
    for m in re.finditer(r"from (strategies[\w_]*) import|import (strategies[\w_]*)", src):
        n = m.group(1) or m.group(2)
        if n: info["imports_strategies"].append(n)
    # feature detection
    for feat, pat in FEATURE_PATTERNS.items():
        if re.search(pat, src, re.IGNORECASE):
            info["features"].append(feat)
    # derivatives dependency
    info["depends_on_derivatives"] = any(f in info["features"] for f in
        ("funding","open_interest","liquidations","taker_delta","long_short_ratio"))
    # LLM / meta
    info["is_llm"] = bool(re.search(r"anthropic|claude_trader|llm_", src, re.IGNORECASE))
    # ML
    info["is_ml"] = "ml_classifier" in info["features"] or "kronos" in info["features"]
    return info

def main():
    py_files = [p for p in ROOT.glob("*.py")]
    results = [scan(p) for p in py_files]
    results.sort(key=lambda r: r["name"])

    # Also collect README content (trim)
    readme = (ROOT / "README.md")
    readme_text = readme.read_text(encoding="utf-8", errors="replace") if readme.exists() else ""

    # Reports directory: look for documented perf
    reports_dir = ROOT / "reports"
    report_md = []
    if reports_dir.exists():
        for md in reports_dir.glob("*.md"):
            report_md.append({"file": md.name, "size": md.stat().st_size})

    out = {
        "total_py": len(py_files),
        "files": results,
        "readme_size": len(readme_text),
        "reports": report_md,
    }
    # Write to disk instead of stdout to keep context clean
    outp = Path(r"C:\Users\alexandre bandarra\Desktop\global\scan_output.json")
    outp.write_text(json.dumps(out, indent=1))
    # Print a small summary
    print(f"scanned={len(py_files)}")
    harnesses = [r for r in results if r["is_harness"]]
    sigfiles = [r for r in results if not r["is_harness"] and r["has_signal_logic"]]
    noisig = [r for r in results if not r["is_harness"] and not r["has_signal_logic"]]
    print(f"harnesses={len(harnesses)}")
    print(f"signal_files={len(sigfiles)}")
    print(f"no_signal_logic_nonharness={len(noisig)}")
    print(f"wrote={outp}")

if __name__ == "__main__":
    main()
