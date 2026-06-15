"""Surgical patch: wire the HL signal introspection into get_signal_current,
replacing the 23-02 stub for HL sleeves only (Poly sleeves unchanged).

Idempotent (skips if already patched). Backs up the original. Verifies the
file still imports (py_compile) before declaring success.

Run on vps3:
  /opt/tradingvenue/.venv/bin/python /tmp/_patch_sleeves.py
"""
from __future__ import annotations
import py_compile, shutil, sys, time
from pathlib import Path

TARGET = Path("/opt/tradingvenue/backend/app/api/sleeves.py")

ANCHOR = "    if _deps.bar_engine is None and _deps.pool is None:\n"

INSERT = '''    # --- HL V52/XSM real signal introspection (replaces 23-02 stub for HL) ---
    if not _is_polymarket_sleeve(sleeve_id) and _deps.pool is not None:
        try:
            from backend.app.api._hl_signal import compute_hl_signal
            _res = await compute_hl_signal(_deps.pool, sleeve_id)
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

MARK = "HL V52/XSM real signal introspection"


def main() -> int:
    src = TARGET.read_text(encoding="utf-8")
    if MARK in src:
        print("[patch] already applied — no-op")
        return 0
    n = src.count(ANCHOR)
    if n != 1:
        print(f"[patch] ABORT: anchor found {n} times (expected 1)")
        return 2
    bak = TARGET.with_suffix(f".py.bak-hlcards-{int(time.time())}")
    shutil.copy2(TARGET, bak)
    patched = src.replace(ANCHOR, INSERT + ANCHOR, 1)
    TARGET.write_text(patched, encoding="utf-8")
    try:
        py_compile.compile(str(TARGET), doraise=True)
    except py_compile.PyCompileError as e:
        shutil.copy2(bak, TARGET)  # rollback
        print(f"[patch] ROLLED BACK — compile failed: {e}")
        return 3
    print(f"[patch] applied OK (backup {bak.name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
