"""Re-patch get_signal_current: revert the prior HL block, apply corrected one
that calls compute_hl_signal(sleeve_id) (isolated pool) WITHOUT the _deps.pool
guard. Restores from the newest .bak-hlcards-* first, then inserts.

Run on vps3:
  /opt/tradingvenue/.venv/bin/python /tmp/_patch_sleeves2.py
"""
from __future__ import annotations
import py_compile, shutil, sys, time, glob, os
from pathlib import Path

TARGET = Path("/opt/tradingvenue/backend/app/api/sleeves.py")
ANCHOR = "    if _deps.bar_engine is None and _deps.pool is None:\n"
MARK = "HL V52/XSM real signal introspection"

INSERT = '''    # --- HL V52/XSM real signal introspection (replaces 23-02 stub for HL) ---
    if not _is_polymarket_sleeve(sleeve_id):
        try:
            from backend.app.api._hl_signal import compute_hl_signal
            _res = await compute_hl_signal(sleeve_id)
            if _res is not None:
                _dir, _conf = _res
                return SignalCard(
                    sleeve_id=sleeve_id,
                    direction=_dir,
                    confidence=_conf,
                    edge_pp=None,
                    payout_x=None,
                    kelly_usd=None,
                    horizon_seconds=14400,
                    blocked=False,
                    block_reason=None,
                )
        except Exception:
            logger.warning(
                "hl_signal.compute_failed",
                extra={"event": "hl_signal.compute_failed", "sleeve_id": sleeve_id},
            )
'''


def main() -> int:
    # 1. Revert to the most recent pre-patch backup so we start from clean source.
    baks = sorted(glob.glob(str(TARGET) + ".bak-hlcards-*"), key=os.path.getmtime)
    src = TARGET.read_text(encoding="utf-8")
    if MARK in src:
        if not baks:
            print("[patch2] ABORT: patched but no backup to revert from")
            return 2
        shutil.copy2(baks[-1], TARGET)
        src = TARGET.read_text(encoding="utf-8")
        print(f"[patch2] reverted from {Path(baks[-1]).name}")
    if MARK in src:
        print("[patch2] ABORT: still marked after revert (bad backup)")
        return 2
    if src.count(ANCHOR) != 1:
        print(f"[patch2] ABORT: anchor count {src.count(ANCHOR)} != 1")
        return 2

    bak = TARGET.with_suffix(f".py.bak-hlcards2-{int(time.time())}")
    shutil.copy2(TARGET, bak)
    patched = src.replace(ANCHOR, INSERT + ANCHOR, 1)
    TARGET.write_text(patched, encoding="utf-8")
    try:
        py_compile.compile(str(TARGET), doraise=True)
    except py_compile.PyCompileError as e:
        shutil.copy2(bak, TARGET)
        print(f"[patch2] ROLLED BACK — compile failed: {e}")
        return 3
    print(f"[patch2] applied OK (backup {bak.name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
