#!/bin/bash
# Bulk upload all research+guides not already in the notebook.
set +e
NB_ID="9a2cc979-1e65-401b-bd8e-73214566b456"
LOG=/tmp/nb_upload.log
: > "$LOG"

ALREADY="building_cyclops_style_bot.md|FINAL_SUMMARY.md|ROBUSTNESS_VERDICT.md|15MIN_BINARY_CRYPTO_STRATEGIES_RESEARCH.md|5min_strategy.md|PREDICTION_MARKET_STRATEGIES_COMPLETE_RESEARCH.md|polymarket-queue-sniper-guide.md|arbitrageguide4.md|phase4-tier2-strategies.md"

sweep() {
  find "$1" -type f -name "*.md" \
    -not -path "*/node_modules/*" -not -path "*/.git/*" -not -path "*/__pycache__/*" \
    -not -path "*/.venv/*" -not -path "*/venv/*" -not -path "*/worktrees/*" \
    -not -path "*/skills/*" -not -path "*/.pytest_cache/*" -not -path "*/.beads/*" \
    -not -path "*/phases/*" -not -path "*/debug/*" -not -path "*/_archive/*" \
    2>/dev/null
}
{
  sweep "/c/Users/alexandre bandarra/Desktop/global"
  sweep "/c/Users/alexandre bandarra/Desktop/automation plataform/QuanPlataform"
  sweep "/d/Storedata"
  sweep "/d/opt/storedata"
} | grep -iE "(docs/(research|plans?|audits?|specs|guides?)|/Quan_KnowledgeBase/|/KnowledgeBase/|strategy_lab/reports|cyclops|RESEARCH\.md|GUIDE\.md|[_-]guide\.md|strateg|arbitrag|scalp|market.?mak|microstruct|queue-sniper|binary|5min|15min|prediction_market|tier2)" \
| grep -viE "(SKILL\.md|playwright-cli|TESTING\.md|master-index\.md|/index\.md$|dashboard|terminal|codebase-map|session-handoff|path-forward|autoresearch-handoff|becker-dataset|binance-audit|data-audit|domain-research|2026-04-16-comprehensive|CONCERNS|CONVENTIONS|INTEGRATIONS\.md|NAUTILUS_INTEGRATION)" \
| sort -u > /tmp/all.txt

grep -vE "($ALREADY)$" /tmp/all.txt > /tmp/todo.txt

python -c "
import hashlib, pathlib
seen=set(); keep=[]
for ln in open(r'/tmp/todo.txt', encoding='utf-8'):
    p = ln.strip()
    if not p: continue
    try: d = pathlib.Path(p).read_bytes()
    except Exception: continue
    h = hashlib.md5(d).hexdigest()
    if h in seen: continue
    seen.add(h); keep.append(p)
open(r'/tmp/todo_dedup.txt','w',encoding='utf-8').writelines(k+chr(10) for k in keep)
print('to_upload:', len(keep))
" | tee -a "$LOG"

echo "" | tee -a "$LOG"
echo "=== WILL UPLOAD ===" | tee -a "$LOG"
awk -F'/' '{printf "  %-62s %s\n", $NF, $0}' /tmp/todo_dedup.txt | sort | tee -a "$LOG"

echo "" | tee -a "$LOG"
echo "=== UPLOADING ===" | tee -a "$LOG"
idx=0; ok=0; fails=0
while IFS= read -r f; do
  idx=$((idx+1))
  base=$(basename "$f")
  OUT=$(python -m notebooklm source add "$f" -n "$NB_ID" --title "$base" 2>&1)
  if echo "$OUT" | grep -qiE "^error|traceback|failed|unauthorized"; then
    echo "[$idx] $base  FAIL" | tee -a "$LOG"
    fails=$((fails+1))
  else
    echo "[$idx] $base  ok" | tee -a "$LOG"
    ok=$((ok+1))
  fi
done < /tmp/todo_dedup.txt

echo "" | tee -a "$LOG"
echo "RESULT: $ok added / $fails failed / $idx attempted" | tee -a "$LOG"
echo "END" >> "$LOG"
