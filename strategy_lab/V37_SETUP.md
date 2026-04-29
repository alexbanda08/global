# V37 — Setup & smoke test

## 1. Environment audit (re-audited 2026-04-22 evening)

Pythons on this machine:
- `C:\Python314\python.exe` — Python 3.14.2. Has only `pyarrow`. Skip — too new for vbt/talib wheels.
- `C:\Users\alexandre bandarra\AppData\Local\Programs\Python\Python312\python.exe` — Python 3.12. Has `anthropic`+`pydantic`+`pyarrow` (we installed them). **`pandas` import HANGS in subprocess context — do not use.**
- **`D:\kronos-venv\Scripts\python.exe` — USE THIS ONE.** Already has `pandas`+`numpy`+`pyarrow`+full Kronos stack. Active virtualenv that's running the Kronos fine-tune (PID seen 17:09 onwards). `anthropic`+`pydantic` install in progress.

Other tools:
- `claude` CLI at `C:\Users\alexandre bandarra\AppData\Roaming\npm\claude.cmd` — npm-installed, on PATH ✓
- Logged into Max 20× subscription (confirmed: `claude --print "hi"` returns immediately)

## 1b. Bash-on-Windows gotchas discovered the hard way

- `subprocess.run(['claude', ...])` fails on Windows because `claude.cmd` (a batch file) isn't found by `CreateProcess`. Fix: `shutil.which("claude")` → full path. Already patched in `ClaudeCLIProvider`.
- Git Bash mangles `>` and `2>&1` redirects when commands run via the MCP background wrapper. Fix: write logs from inside Python (see `tiny_v37_check.py` and `smoke_v37.py` `log()` helper).
- Windows console default encoding `cp1252` chokes on `→` arrows in snapshot text. Fix: `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` at script start. Patched in `smoke_v37.py` and `tiny_v37_check.py`.

## 2. One-time setup (use the kronos-venv)

```powershell
# Install V37 deps into the working venv (other deps already there)
& "D:\kronos-venv\Scripts\python.exe" -m pip install "anthropic>=0.88.0" "pydantic>=2.0"

# Confirm everything imports
& "D:\kronos-venv\Scripts\python.exe" -c "import pandas, pyarrow, anthropic, pydantic; print('OK')"

# No ANTHROPIC_API_KEY needed for --provider claude-cli — uses your Max plan.
# Set OPENROUTER_API_KEY only if you plan to use --provider openrouter.
```

If you ever need a fresh venv: `py -3.12 -m venv .venv` then `pip install vectorbt==0.28.* pandas numpy ta-lib pyarrow anthropic pydantic`. Avoid Python 3.14 — wheels for vbt/talib are flaky.

## 3. Smoke tests — incrementally bigger

### 3a. Tiniest possible — just call claude --print once

```powershell
& "D:\kronos-venv\Scripts\python.exe" "C:\Users\alexandre bandarra\Desktop\global\strategy_lab\tiny_v37_check.py"
# Reads strategy_lab\tiny_v37_check.log for full progress.
# Should complete in ~30s. Proves: imports + claude.cmd subprocess + UTF-8 stdout.
```

### 3b. Single decision via the full provider stack

```powershell
& "D:\kronos-venv\Scripts\python.exe" "C:\Users\alexandre bandarra\Desktop\global\strategy_lab\smoke_v37.py" --coin SOLUSDT --provider claude-cli --model sonnet
# Reads strategy_lab\smoke_v37.log
# Builds snapshot from real SOL 4h parquet, calls Claude, parses Decision.
```

### 3c. Dry-run the historical runner (no LLM, just cache + scaffolding)

```powershell
& "D:\kronos-venv\Scripts\python.exe" -m strategy_lab.run_v37_claude_trader --coin SOLUSDT --dry-run
```

What this proves:
- `engine.load("SOLUSDT", "4h")` works from your data tree.
- `build_snapshot()` produces a well-formed prompt.
- Signal wrappers (`_entries_bbbreak_ls`, `_entries_htf_donchian_ls`,
  `_entries_cci_extreme`) return the expected 2-tuples of entry edges.

If this errors, fix before touching the API.

## 4. First real run — ONE coin, cheapest model

```powershell
py -m strategy_lab.run_v37_claude_trader --coin SOLUSDT --model claude-haiku-4-5
```

Haiku 4.5 should run the full 3-year SOL backtest for <$5 including the
Batch-API 50% discount. If the equity curve and trade count look sane,
upgrade to `claude-sonnet-4-6` (~3×) or `claude-opus-4-7` (~8× Haiku).

## 5. Full 5-coin portfolio run

```powershell
py -m strategy_lab.run_v37_claude_trader --model claude-opus-4-7
# ≈ 5500 batch requests, wall-clock ~1h, ~$120 on Opus 4.7
```

Output:
- `strategy_lab/results/v37/<COIN>/equity.csv` — per-coin equity curve
- `strategy_lab/results/v37/<COIN>/trades.csv` — every round-trip trade
- `strategy_lab/results/v37/<COIN>/decision_trace.csv` — Claude's calls
- `strategy_lab/results/v37/decisions_<COIN>.parquet` — raw decision cache (re-run-safe)
- `strategy_lab/results/v37/v37_summary.csv` — per-coin metrics

## 6. Post-run audit

Clone `run_v34_audit.py` → `run_v37_audit.py` and point it at the V37
equity CSVs. Must clear:
- per-year breakdown (no single year carrying the whole return)
- parameter plateau (re-run with lookback ∈ {100, 200, 300})
- randomized-entry null (shuffle Claude's strategy labels; V37 must beat 80%)
- MC bootstrap (monthly, n=1000)
- Deflated Sharpe (DSR ≥ 0.9 with N_trials ≈ 2000)

## 7. Known caveats in the current scaffold

- **Training-data leakage.** Claude may recognize crypto price patterns it
  saw in pre-training. The snapshot renders close as a percentile rank to
  mitigate this, but the ablation ("date-masked snapshot vs date-visible")
  in §7 of `V37_CLAUDE_TRADER_DESIGN.md` is mandatory before deploy.
- **No exit signals from Claude.** Exits come from `simulate()` ATR stops.
  When Claude picks `Flat`, we simply stop firing new entries — any open
  position rides until trail/TP/SL/max_hold closes it. This is conservative
  but means a "Flat" call doesn't immediately flatten the book. If that
  matters, add `force_exit_on_flat=True` in `simulate()` (not wired yet).
- **`size_mult` is ignored by `simulate()`.** Current simulate uses fixed
  `risk_per_trade` regardless of Claude's confidence. To honor size_mult,
  either patch simulate or post-scale the equity curve per decision window.
- **Decision cadence coarse-graining.** Daily (every 6 bars) is a
  cost/signal tradeoff. Try every-other-day (12 bars) or 4-hourly (1 bar)
  in the plateau test; cost scales linearly.
