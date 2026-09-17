"""Define application errors shared across domain-facing boundaries.

These errors describe revision conflicts and missing resources independently
of the persistence, file-system, command-line, or web adapter that detects them.
"""


class Conflict(ValueError):
    """Indicate that an expected revision or idempotency identity no longer matches."""


class Missing(ValueError):
    """Indicate that a requested domain resource does not exist."""
