"""Re-run the canonical ws_s self-test as a cyclops precondition.

Per CLAUDE.md and spec §9: every backtest must verify the ws_s convention
before doing anything else. We inherit canonical's `_test_ws_s.py` instead
of duplicating its assertions — if their test passes, our anchor math is
guaranteed correct.
"""

from __future__ import annotations

import subprocess
import sys

from cyclops.conventions import CANONICAL, ROOT


def test_canonical_ws_s_self_test_passes():
    """Invokes data/v4/canonical/_test_ws_s.py with the project Python."""
    script = CANONICAL / "_test_ws_s.py"
    assert script.exists(), f"canonical ws_s test missing: {script}"

    result = subprocess.run(
        [sys.executable, "-X", "utf8", str(script)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )

    combined = result.stdout + "\n" + result.stderr
    assert result.returncode == 0, (
        f"canonical _test_ws_s.py exited {result.returncode}\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    assert "=== ALL CHECKS PASSED ===" in combined, (
        "canonical ws_s test did not print the pass banner.\n"
        f"OUTPUT:\n{combined}"
    )


def test_data_io_reexports_ws_s_helpers():
    """The wrapper module must expose ws_s helpers without leaking sys.path."""
    from cyclops import data_io

    assert callable(data_io.slug_to_ws_s)
    assert callable(data_io.add_ws_s)
    assert callable(data_io.ret_2m_at_ws)
    assert callable(data_io.asof_strict)


def test_slug_to_ws_s_convention():
    """Spot-check: slug suffix - window_s = ws_s (the previous slot's start)."""
    from cyclops import data_io
    from cyclops.conventions import WINDOW_S

    # eth-updown-5m-1778342700 → slot_start = 1778342700, ws_s = 1778342400
    ws_s = data_io.slug_to_ws_s("eth-updown-5m-1778342700", "5m")
    assert ws_s == 1778342700 - WINDOW_S["5m"]

    # btc-updown-15m-1778342700 → slot_start = 1778342700, ws_s = 1778341800
    ws_s = data_io.slug_to_ws_s("btc-updown-15m-1778342700", "15m")
    assert ws_s == 1778342700 - WINDOW_S["15m"]
