"""Produce a very compact human-readable digest for LLM consumption."""
import json
from pathlib import Path

d = json.loads(Path(r"C:\Users\alexandre bandarra\Desktop\global\digest.json").read_text())
out = Path(r"C:\Users\alexandre bandarra\Desktop\global\digest.txt")
lines = []
for r in d:
    lines.append(f"### {r['name']}  ({r['file']})")
    lines.append(f"  funcs: {', '.join(r['funcs'][:12])}")
    lines.append(f"  syms: {r['symbols'][:8]}  tfs: {r['tfs']}  sig:{r['has_signal_logic']}  ml:{r['is_ml']}  llm:{r['is_llm']}  deriv:{r['depends_on_derivatives']}")
    lines.append(f"  feats: {', '.join(r['features'][:15])}")
    if r['imports_strategies']:
        lines.append(f"  imports: {', '.join(r['imports_strategies'])}")
    if r['doc']:
        lines.append(f"  doc: {r['doc'][:220]}")
    # signature first 8 lines only
    sig = r['signature'].splitlines()[:10]
    for s in sig:
        lines.append(f"    | {s[:140]}")
    lines.append("")
out.write_text("\n".join(lines), encoding="utf-8")
print("wrote", out, "bytes=", out.stat().st_size)
