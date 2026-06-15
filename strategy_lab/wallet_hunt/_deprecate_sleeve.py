"""Comment out a SniperV5Sleeve(...) block from sniper_v5_sleeves.py by sleeve_id.
Paren-balanced (line-number independent). Idempotent. Makes a .bak.

Usage: python3 _deprecate_sleeve.py <file> <sleeve_id> [tag]
"""
import sys, shutil

path, sid = sys.argv[1], sys.argv[2]
tag = sys.argv[3] if len(sys.argv) > 3 else "DEPRECATED"
lines = open(path, encoding="utf-8").read().split("\n")

# find the sleeve_id line
idx = next((i for i, l in enumerate(lines) if f'sleeve_id="{sid}"' in l), None)
if idx is None:
    print(f"NOTFOUND {sid}")
    sys.exit(0)
if lines[idx].lstrip().startswith("#"):
    print(f"ALREADY_COMMENTED {sid}")
    sys.exit(0)

# walk back to the 'SniperV5Sleeve(' that opens this block
start = next(i for i in range(idx, -1, -1) if lines[i].strip().startswith("SniperV5Sleeve("))
# balance parens from start to find the closing line
depth = 0
end = None
for i in range(start, len(lines)):
    depth += lines[i].count("(") - lines[i].count(")")
    if depth == 0:
        end = i
        break
assert end is not None, "unbalanced"
# include a trailing comma line if the closing line is just ')' and next is ','? our style ends with '),'

shutil.copy(path, path + ".bak-deprecate")
for i in range(start, end + 1):
    if not lines[i].lstrip().startswith("#"):
        # preserve indentation, prefix comment marker
        ind = len(lines[i]) - len(lines[i].lstrip())
        lines[i] = lines[i][:ind] + f"# {tag} " + lines[i][ind:]
open(path, "w", encoding="utf-8").write("\n".join(lines))
print(f"COMMENTED {sid} lines {start+1}-{end+1}")
