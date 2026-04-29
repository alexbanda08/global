"""Deep analysis pass over scan_output.json to produce a compact digest
suitable for direct conversion into the registry YAML.

Reads scan_output.json + inspects individual files for:
 - signal-function shapes (dict with entries/exits)
 - deduplication fingerprint (feature_set + core signal expression shape)
 - canonical version selection
"""
from __future__ import annotations
import json, re
from pathlib import Path

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab")
SCAN = Path(r"C:\Users\alexandre bandarra\Desktop\global\scan_output.json")

HARNESS_RUNFILES = {
    # Audit/OOS/validate scripts — harnesses, not new strategies
    "run_v22_oos_audit","run_v23_oos_all","run_v24_oos","run_v25_oos",
    "run_v26_oos","run_v27_oos","run_v28_peryear_audit","run_v28_validate_winner",
    "run_v29_oos","run_v30_oos","run_v31_overfit_audit","run_v32_core_audit",
    "run_v33_audit","run_v34_audit","run_v38_smc_sweep","run_v38b_smc_mixes",
    "run_v38c_smc_xsm_breadth","run_v21b_fast","run_v22b_surgical",
}

# Read files (filtered) and extract docstrings + top-of-file comments
def first_lines(path: Path, n: int = 40) -> str:
    try:
        with path.open(encoding="utf-8", errors="replace") as f:
            lines = [next(f, "") for _ in range(n)]
        return "".join(lines)
    except Exception:
        return ""

def signal_signature(path: Path) -> str:
    """Pull a compact signature from a file: def names + the exact lines
    where entries/exits/short_entries/short_exits are defined."""
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    sig_lines = []
    for m in re.finditer(r"^def ([a-zA-Z_][a-zA-Z0-9_]*)\(", src, re.MULTILINE):
        if not m.group(1).startswith("_"):
            sig_lines.append(f"def {m.group(1)}")
    # Extract lines that define entries/exits
    for pat in (r"^\s*entries\s*=.*$", r"^\s*exits\s*=.*$",
                r"^\s*short_entries\s*=.*$", r"^\s*short_exits\s*=.*$",
                r"^\s*sl_stop\s*=.*$", r"^\s*tp_stop\s*=.*$", r"^\s*tsl\s*=.*$"):
        for m in re.finditer(pat, src, re.MULTILINE):
            line = m.group(0).strip()
            if len(line) < 180:
                sig_lines.append(line)
    return "\n".join(sig_lines[:50])

def compact_doc(path: Path) -> str:
    src = first_lines(path, 30)
    # strip quotes and excess whitespace
    m = re.search(r'"""(.+?)"""', src, re.DOTALL)
    if m:
        doc = m.group(1).strip()
        return re.sub(r"\s+"," ", doc)[:400]
    # fallback: top-of-file comments
    coms = []
    for ln in src.splitlines()[:25]:
        if ln.strip().startswith("#"):
            coms.append(ln.strip().lstrip("#").strip())
    return " ".join(coms)[:400]

def main():
    data = json.loads(SCAN.read_text())
    # Restrict to non-harness files to inspect
    targets = []
    for f in data["files"]:
        name = f["name"]
        if f["is_harness"]: continue
        if name in HARNESS_RUNFILES: continue
        # Exclude pure hunt files again (they import from strategies_vN.py and
        # just sweep params — not a new strategy)
        if re.match(r"^v\d+.*(hunt|sweep|audit|cross_sectional|xsm_variants|robustness|overfitting|cross_reference)", name):
            continue
        targets.append(f)

    digest = []
    for f in targets:
        p = ROOT / (f["name"] + ".py")
        sig = signal_signature(p)
        doc = compact_doc(p)
        digest.append({
            "name": f["name"],
            "file": f["file"],
            "funcs": f["funcs"][:30],  # cap
            "symbols": f["symbols"],
            "tfs": f["tfs"],
            "features": f["features"],
            "depends_on_derivatives": f["depends_on_derivatives"],
            "has_signal_logic": f["has_signal_logic"],
            "imports_strategies": f["imports_strategies"],
            "is_llm": f["is_llm"],
            "is_ml": f["is_ml"],
            "doc": doc,
            "signature": sig,
        })
    out = Path(r"C:\Users\alexandre bandarra\Desktop\global\digest.json")
    out.write_text(json.dumps(digest, indent=1))
    # summary to stdout
    print(f"candidates={len(targets)}")
    # By family heuristic
    cats = {"ml":0,"llm":0,"deriv":0,"plain":0}
    for d in digest:
        if d["is_llm"]: cats["llm"]+=1
        elif d["is_ml"]: cats["ml"]+=1
        elif d["depends_on_derivatives"]: cats["deriv"]+=1
        else: cats["plain"]+=1
    print("cat:", cats)
    print(f"wrote={out}")

if __name__ == "__main__":
    main()
