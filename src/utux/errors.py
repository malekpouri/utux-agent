"""Typed exceptions raised by utux.

Every error raised deliberately by this package derives from `UtuxError`, so
callers can catch the package's failures without catching unrelated ones.
"""

from dataclasses import dataclass

DOCUMENT_FIELD = "<document>"
"""Field name used for a problem that concerns a whole file, not one field."""


class UtuxError(Exception):
    """Base class for all errors raised by utux."""


class HashingError(UtuxError):
    """A file or directory could not be hashed."""


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


class ModelProviderError(UtuxError):
    """A call to a model provider failed.

    The message never contains an API key or the content of a message.
    """


class ModelAuthenticationError(ModelProviderError):
    """The provider has no valid credentials, or they were refused."""


class ModelRateLimitError(ModelProviderError):
    """The provider refused the call because of a rate limit.

    Attributes:
        retry_after_seconds: How long the provider asked the caller to wait,
            or None when it did not say.
    """

    def __init__(self, message: str, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class ModelTimeoutError(ModelProviderError):
    """The provider did not answer within the timeout of the request."""


class ModelInvalidResponseError(ModelProviderError):
    """The provider answered, but the answer is not a valid response."""


class ScriptExhaustedError(UtuxError):
    """A scripted provider was called more often than its script has steps."""
