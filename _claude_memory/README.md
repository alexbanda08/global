# Claude auto-memory export — 2026-07-02
Snapshot of the Claude Code persistent memory for this project (17 files: `MEMORY.md` index + 16 memories), exported so a session on another machine can inherit the full research context.

## How to install on the new PC
Claude's memory lives OUTSIDE the repo, at a path derived from the project directory:
```
C:\Users\<YOU>\.claude\projects\<project-path-slug>\memory\
```
where `<project-path-slug>` = the absolute repo path with `\`/`:` replaced by `-` (e.g. repo at `C:\Users\alex\Desktop\global` → slug `C--Users-alex-Desktop-global`).

**Option A (proper install):** start one Claude Code session in the cloned repo (this creates the project dir), then copy every `*.md` from this folder into that `memory\` directory, replacing the fresh `MEMORY.md`. Next session loads them automatically.

**Option B (zero setup):** just tell the new session:
> "Read all files in `_claude_memory/` — these are your memories from the previous machine — then read `strategy_lab/reports/HANDOFF_2026_07_02_PAIRARB_V3_SCALP_WALLETS.md` and continue from §4."

## Notes
- These are point-in-time snapshots (exported 2026-07-02, commit-synced). If both PCs keep working, the copies WILL diverge — re-export from whichever machine worked last, or treat the handoff reports as the source of truth and memories as accelerators.
- Memories reference file:line and infra state as of their write date; verify against current code before asserting (standard memory rule).
