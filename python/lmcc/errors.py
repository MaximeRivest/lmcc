"""Refusals.

Every failure in lmcc is a :class:`Refusal` with a stable ``code``
(contract/spec/errors.md), a ``hint`` naming the exact offender and what
to do, and — for parse refusals — a ``partial`` with what was read.
Silent wrong behavior is the one bug this library refuses to have.
"""

from __future__ import annotations


class Refusal(Exception):
    def __init__(self, code: str, hint: str, *, partial: dict | None = None):
        self.code = code
        self.hint = hint
        self.partial = partial
        super().__init__(f"[{code}] {hint}")


def refuse(code: str, hint: str, *, partial: dict | None = None) -> None:
    raise Refusal(code, hint, partial=partial)
