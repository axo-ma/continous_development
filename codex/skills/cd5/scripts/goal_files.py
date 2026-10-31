"""Deprecated import compatibility; see planner_controls for current controls."""
try:
    from .planner_controls import permission, user_command, finish_or_wait, migrate
except ImportError:
    from planner_controls import permission, user_command, finish_or_wait, migrate
