"""
Recovery service — placeholder.

This module will orchestrate the full recovery workflow:
  intake case → score → decide → execute → record outcome.

Not yet implemented.
"""

from __future__ import annotations

# from app.decision.engine import decide
# from app.execution.executor import execute


def process_case(case) -> dict:
    """Full recovery workflow. Not yet implemented."""
    raise NotImplementedError(
        "RecoveryService is not yet implemented. "
        "Use app.decision.engine.decide() directly for now."
    )
