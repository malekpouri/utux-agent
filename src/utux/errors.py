"""Typed exceptions raised by utux.

Every error raised deliberately by this package derives from `UtuxError`, so
callers can catch the package's failures without catching unrelated ones.
"""

from dataclasses import dataclass

DOCUMENT_FIELD = "<document>"
"""Field name used for a problem that concerns a whole file, not one field."""


class UtuxError(Exception):
    """Base class for all errors raised by utux."""


@dataclass(frozen=True)
class Problem:
    """One reason why a contract file is not valid.

    Attributes:
        field: Dotted path of the field, for example `budget.total_usd`, or
            `DOCUMENT_FIELD` when the problem concerns the whole file.
        reason: One-line explanation for a person.
        code: Stable identifier of the kind of problem, for programs and tests.
    """

    field: str
    reason: str
    code: str


class ContractValidationError(UtuxError):
    """A contract file does not match its schema.

    The message has one line per problem, in the form `file: field: reason`,
    and lists every problem that was found, not only the first.

    Attributes:
        source: The file, as the caller named it.
        problems: Every problem found, in the order the validator reported them.
    """

    def __init__(self, source: str, problems: tuple[Problem, ...]) -> None:
        self.source = source
        self.problems = problems
        super().__init__(
            "\n".join(f"{source}: {problem.field}: {problem.reason}" for problem in problems)
        )
