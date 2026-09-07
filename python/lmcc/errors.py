"""Refusals.

Every failure in lmcc is a :class:`Refusal` with a stable ``code``
(contract/spec/errors.md), a ``hint`` naming the exact offender and what
to do, a ``fix`` — the one next action as plain data, carried by every
refusal that fires before render — and, for parse refusals, a
``partial`` with what was read. Silent wrong behavior is the one bug
this library refuses to have.
"""

from __future__ import annotations


class Refusal(Exception):
    def __init__(self, code: str, hint: str, *, fix: dict | None = None,
                 partial: dict | None = None):
        self.code = code
        self.hint = hint
        self.fix = fix
        self.partial = partial
        super().__init__(f"[{code}] {hint}")

    def describe(self) -> dict:
        """The refusal as plain data: ``{code, hint, fix, partial}``."""
        return {"code": self.code, "hint": self.hint, "fix": self.fix, "partial": self.partial}


def refuse(code: str, hint: str, *, fix: dict | None = None,
           partial: dict | None = None) -> None:
    raise Refusal(code, hint, fix=fix, partial=partial)
