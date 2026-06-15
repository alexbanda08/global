"""Insert sleeve_ids into the BASELINE_DEPRECATED_POLY_UPDOWN_SLEEVES frozenset
in sleeve_registry.py. Idempotent. Makes a .bak.

Usage: python3 _add_deprecated.py <file> <id1> [id2 ...]
"""
import sys, shutil

path = sys.argv[1]
ids = sys.argv[2:]
src = open(path, encoding="utf-8").read()
lines = src.split("\n")

# locate the frozenset opening
anchor = next((i for i, l in enumerate(lines)
               if "BASELINE_DEPRECATED_POLY_UPDOWN_SLEEVES" in l and "frozenset(" in l), None)
if anchor is None:
    print("NOTFOUND anchor"); sys.exit(1)
brace = next(i for i in range(anchor, anchor + 5) if lines[i].strip() == "{")

added = []
for sid in ids:
    if f'"{sid}"' in src:
        print(f"ALREADY {sid}")
        continue
    added.append(f'        "{sid}",  # DEPRECATED-2026-06-08')

if not added:
    print("NOCHANGE"); sys.exit(0)

shutil.copy(path, path + ".bak-paneldep")
lines[brace + 1:brace + 1] = added
open(path, "w", encoding="utf-8").write("\n".join(lines))
print("INSERTED", len(added), "after line", brace + 1)
