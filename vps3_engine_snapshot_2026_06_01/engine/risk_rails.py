# Phase 23 plan 04 — observability annotation only.
#
# Rails remain pure functions per CLAUDE.md invariant 5
# (rails fire BEFORE signal). The actual rail framework lives at
# backend/app/engine/risk_guardrails.py and the per-rail pure functions
# under backend/app/engine/rails/rail_NN_*.py — none of those change.
#
# The new shadow_simulated audit row introduced by plan 23-04 is written
# by the CALLER (PolymarketUpdownController) AFTER it has already received
# the rail's BLOCK / PASS / WARN decision. The caller uses
# ``_audit_shadow_simulated`` (controllers/polymarket_updown.py) to record
# what would have happened if the rail had not blocked the signal. The
# matching exit row is written by ``_audit_shadow_paper_resolved`` at the
# next bar boundary via ``_resolve_pending_shadow_entries``.
#
# Why this file exists at all (instead of nothing):
# - Discoverability — a future maintainer searching for "risk_rails" + the
#   word "shadow" should land here and immediately understand that the
#   rails themselves are unchanged.
# - Plan 23-04 acceptance criterion is a deterministic git-diff guard that
#   verifies risk_rails.py contributes zero added/removed function or
#   class signatures and zero non-comment, non-blank changed lines. This
#   file is comment-only — every line is either a ``#``-comment or blank
#   — so the guard passes by construction.
#
# DO NOT add behavior to this file. Behavior lives in:
#   backend/app/engine/risk_guardrails.py        (orchestrator)
#   backend/app/engine/rails/rail_NN_*.py        (per-rail pure functions)
#   backend/app/controllers/polymarket_updown.py (audit-row callers)
