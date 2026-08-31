"""Named refusals.

Every failure in a15 carries a stable machine-readable code and a message
that names the exact offender (the field, the codec, the missing fact).
The codes are part of the contract: `contract/spec/errors.md` lists them,
and the corpus asserts them. Silent wrong behavior is the one bug this
library refuses to have.
"""

from __future__ import annotations


class A15Error(Exception):
    """A refusal with a stable code.

    Attributes:
        code: stable identifier from contract/spec/errors.md, e.g. "unknown-codec".
        detail: the human message, without the code prefix.
        partial: for parse errors, whatever values were recovered before failing.
    """

    def __init__(self, code: str, detail: str, *, partial: dict | None = None):
        self.code = code
        self.detail = detail
        self.partial = partial
        super().__init__(f"[{code}] {detail}")


def refuse(code: str, detail: str, *, partial: dict | None = None) -> None:
    raise A15Error(code, detail, partial=partial)
