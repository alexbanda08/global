#!/bin/bash
# Overnight orchestrator for the Path C meta-classifier pipeline.
#
# Sequence:
#   1. Wait for v1 Kronos inference (sample_count=5) to finish
#   2. Build labeled dataset (joins V3 + Kronos + ATR/ADX + outcome)
#   3. Train HGB meta-classifier with time-series CV + ablation backtest
#   4. Launch v2 quality inference (sample_count=30) in background for morning v2
#
# Usage: bash strategy_lab/run_overnight_meta.sh
#
# Logs: strategy_lab/logs/run_overnight_meta.log

set -uo pipefail

cd "/c/Users/alexandre bandarra/Desktop/global"

LOG=strategy_lab/logs/run_overnight_meta.log
V1_LOG=strategy_lab/logs/kronos_v3_infer.log
V1_PREDS=strategy_lab/results/kronos/kronos_btc_predictions_full.csv
V2_LOG=strategy_lab/logs/kronos_v2_quality.log
PY=python  # system python for build/train (sklearn etc)
KRPY='D:/kronos-venv/Scripts/python.exe'

ts() { date '+%Y-%m-%d %H:%M:%S'; }
log() { echo "[$(ts)] $*" | tee -a "$LOG"; }

log "=== overnight pipeline start ==="

# -------- Phase 1: wait for v1 inference --------
log "Phase 1: waiting for v1 inference (sample_count=5) to finish..."
while true; do
    if grep -q "Done in" "$V1_LOG" 2>/dev/null; then
        log "  v1 inference completed."
        break
    fi
    # also detect crash: process gone but no "Done in"
    if ! tasklist 2>/dev/null | grep -qi 'python.exe'; then
        log "  WARNING: no python process running but no 'Done in' marker found"
        log "  proceeding with whatever predictions are in the CSV..."
        break
    fi
    sleep 60
done

# Print v1 stats
log "v1 predictions row count: $(wc -l < "$V1_PREDS" 2>/dev/null || echo 0)"
log "v1 last log lines:"
tail -5 "$V1_LOG" 2>&1 | tee -a "$LOG"

# -------- Phase 2: build labeled dataset --------
log "Phase 2: build_dataset.py (joining V3 + Kronos + ATR/ADX + outcome)"
$PY strategy_lab/meta_classifier/build_dataset.py 2>&1 | tee -a "$LOG"
BUILD_RC=${PIPESTATUS[0]}
if [ "$BUILD_RC" != "0" ]; then
    log "  build_dataset FAILED rc=$BUILD_RC. Aborting."
    exit 1
fi

# -------- Phase 3: train + ablation --------
log "Phase 3: train_eval.py (HGB + isotonic + ablation backtest)"
$PY strategy_lab/meta_classifier/train_eval.py 2>&1 | tee -a "$LOG"
TRAIN_RC=${PIPESTATUS[0]}
if [ "$TRAIN_RC" != "0" ]; then
    log "  train_eval FAILED rc=$TRAIN_RC. Continuing to v2 inference anyway."
fi

# -------- Phase 4: launch v2 quality inference (sample_count=30) --------
log "Phase 4: launching v2 quality inference (sample_count=30, ~6h)"
nohup "$KRPY" -u strategy_lab/kronos_infer_v2_quality.py > "$V2_LOG" 2>&1 &
V2_PID=$!
log "  v2 inference PID: $V2_PID -> $V2_LOG"

log "=== overnight pipeline orchestration done ==="
log "Tomorrow morning: inspect strategy_lab/results/meta_classifier/v1_ablation_table.csv"
log "                  inspect strategy_lab/results/meta_classifier/v1_feature_importance.csv"
log "                  v2 inference should be done; re-run train_eval after pointing at v2 preds."
