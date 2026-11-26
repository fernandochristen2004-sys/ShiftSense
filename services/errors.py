"""Errors shared by the services layer."""


class ConflictError(RuntimeError):
    """The change clashes with existing data (a duplicate name, or a record in use)."""
