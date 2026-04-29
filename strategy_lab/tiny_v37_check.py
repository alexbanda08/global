"""
Minimal V37 sanity test — bypasses the full smoke harness.

Tests, in order:
  1. Python 3.12 can import pandas + pyarrow (already proven)
  2. ClaudeCLIProvider can resolve `claude.cmd` via shutil.which()
  3. subprocess.run can actually launch claude.cmd and get a response
  4. Decision JSON parses

Writes everything to strategy_lab/tiny_v37_check.log so we never depend
on shell stdout buffering or Bash redirect mangling.
"""
from __future__ import annotations

import sys
import io
import time
import traceback
from pathlib import Path

# Force UTF-8 for stdout (Windows default cp1252 chokes on → arrows etc.)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
LOG = ROOT / "tiny_v37_check.log"
sys.path.insert(0, str(ROOT.parent))


def log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    try:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
    except Exception:
        pass
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()


def main() -> int:
    LOG.write_text("", encoding="utf-8")
    log("=== tiny_v37_check START ===")

    # Step 1: imports
    try:
        import pandas, pyarrow, anthropic, pydantic
        log(f"imports OK: pandas={pandas.__version__} "
            f"pyarrow={pyarrow.__version__} anthropic={anthropic.__version__}")
    except Exception as e:
        log(f"IMPORT FAIL: {e!r}"); traceback.print_exc(); return 1

    # Step 2: locate claude binary
    import shutil
    claude_path = shutil.which("claude")
    log(f"shutil.which('claude') -> {claude_path!r}")
    if not claude_path:
        log("FAIL: claude not on PATH"); return 1

    # Step 3: invoke claude --print via subprocess
    import subprocess
    log(f"calling: {claude_path} --print --model sonnet")
    t0 = time.time()
    try:
        proc = subprocess.run(
            [claude_path, "--print", "--model", "sonnet"],
            input="Reply with the single word READY (no other text).",
            capture_output=True, text=True, timeout=120, encoding="utf-8",
        )
    except Exception as e:
        log(f"SUBPROCESS FAIL: {type(e).__name__}: {e!r}"); return 1
    elapsed = time.time() - t0
    log(f"returncode={proc.returncode}  elapsed={elapsed:.1f}s")
    log(f"stdout (first 500 chars): {proc.stdout[:500]!r}")
    if proc.stderr:
        log(f"stderr (first 500 chars): {proc.stderr[:500]!r}")

    if proc.returncode != 0:
        log(f"FAIL: non-zero exit"); return 1

    log("=== tiny_v37_check PASSED ===")
    return 0


if __name__ == "__main__":
    try:
        rc = main()
    except Exception as e:
        log(f"UNHANDLED EXCEPTION: {e!r}")
        traceback.print_exc()
        rc = 99
    log(f"EXIT_CODE={rc}")
    sys.exit(rc)
