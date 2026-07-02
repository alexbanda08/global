---
name: feedback-subagent-model
description: Always use the sonnet model when spawning subagents/Agent tool calls
metadata: 
  node_type: memory
  type: feedback
  originSessionId: bfe34212-35ae-4881-be0b-242363b3896b
---

Always spawn subagents (Agent tool) with `model: "sonnet"`.

**Why:** User explicitly requested this on 2026-05-28. Likely cost/speed preference for the parallel research-heavy wallet-hunt work.

**How to apply:** On every Agent tool call, set the `model` parameter to `"sonnet"` regardless of agent type (Explore, general-purpose, gsd-* agents, etc.). Applies to this project's work unless the user overrides for a specific task.

**Workflows too (reaffirmed 2026-06-05):** This ALSO applies to the `Workflow` tool. Workflow `agent()` calls inherit the main session model (Opus) by default — a deep-research run cost ~5.2M Opus tokens because the skill template sets no model. So: every `agent()` call inside a workflow script MUST pass `{model: "sonnet"}`. Since invoking a skill workflow by `name:` regenerates the script WITHOUT the override, the procedure is: launch the workflow, then Edit the generated script to add `model: "sonnet"` to every `agent()` opts and re-run via `scriptPath` — OR author/patch the script with sonnet before the first run. Never run an Opus-model workflow fan-out.
