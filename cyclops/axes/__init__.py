"""Three-axis brain: Trend / Levels / Momentum.

Each module exposes a single vote function returning a signed int in
{-1, 0, +1}. No cross-imports between axis modules — each is independent
by design (spec §2).
"""
