"""Typed exceptions raised by utux.

Every error raised deliberately by this package derives from `UtuxError`, so
callers can catch the package's failures without catching unrelated ones.
"""

from dataclasses import dataclass
from pathlib import Path

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


class ModelUnavailableError(ModelProviderError):
    """The provider could not be reached, or its server failed.

    Raised for a network failure or an upstream server error. The call may be
    retried, and this error is the trigger for falling back to another
    provider.
    """


class ModelRequestRejectedError(ModelProviderError):
    """The provider refused the request itself.

    Raised, for example, for an unknown model or an input longer than the
    model's context. Sending the same request again will fail again, so the
    call is not retried.
    """


class ScriptExhaustedError(UtuxError):
    """A scripted provider was called more often than its script has steps."""


class EventLogError(UtuxError):
    """The event log could not be read or written."""


class EventLogCorruptError(EventLogError):
    """The event log holds something that an intact log cannot hold.

    Raised for a last line that was only partly written and for event ids
    that do not increase. The log is never repaired or rewritten by utux.

    Attributes:
        path: The log file.
        line: The number of the offending line, counted from 1.
    """

    def __init__(self, path: Path, line: int, reason: str) -> None:
        self.path = path
        self.line = line
        super().__init__(f"{path}: line {line}: {reason}")


class SchemaExportError(UtuxError):
    """The JSON Schema files could not be written."""


class AtomicWriteError(UtuxError):
    """A file could not be written. The file it should replace is unchanged."""


class ProjectInitError(UtuxError):
    """A project could not be created. Nothing is left behind."""


class ModelProviderConfigError(UtuxError):
    """A model provider is configured in a way that cannot work.

    Raised when the provider is created, not when it is called.
    """


class ModelCallRefusedError(UtuxError):
    """utux declined to make a model call, for example under the data policy.

    No request was sent. This is not a `ModelProviderError`: the provider was
    never asked.
    """


class BudgetExhaustedError(ModelCallRefusedError):
    """A model call was refused because its budget is exhausted.

    The known cost has reached the project budget, or the budget of the
    call's stage. The provider was never asked.

    Attributes:
        refused_event_id: The `model_call` event that records the refusal.
    """

    def __init__(self, message: str, refused_event_id: str | None = None) -> None:
        super().__init__(message)
        self.refused_event_id = refused_event_id


class GoldSetError(UtuxError):
    """A gold release cannot be processed, for example split."""


class CheckpointDataError(UtuxError):
    """A checkpoint holds, or would hold, something other than plain data.

    The graph state of a run is ids, relative paths, hashes and small enums.
    A checkpoint that names a Python object to construct is refused rather
    than loaded, and so is a state that would need one.
    """


class UnknownCostNotAllowedError(ModelCallRefusedError):
    """A model call was refused because the provider reports no cost.

    An earlier successful call to the same external provider returned no
    cost, and `budget.allow_unknown_cost` is false. The provider was not asked.
    """


class ProjectLockedError(UtuxError):
    """Another command holds the lock of the project, so this one does not start."""


class StaleProjectLockError(ProjectLockedError):
    """The project lock was left by a process that is no longer running.

    It is reported, not taken over: a person checks that nothing is still
    writing and removes the lock file.
    """


class NotAProjectError(UtuxError):
    """A command that writes to a project was given a directory that is not one."""


class ExecutorError(UtuxError):
    """An executor could not run a step."""


class ExecutorUnavailableError(ExecutorError):
    """The sandbox of an executor cannot be used, for example Docker is missing.

    Nothing was run, and nothing falls back to running on the host.
    """


class ResultRecordingError(UtuxError):
    """The results of a run cannot be recorded as given.

    The manifest does not belong to the run, its outputs differ from what
    the run wrote, the run is already recorded, or the metrics file changed
    after the run. Nothing was written.
    """


class PackImageError(UtuxError):
    """A pack's image cannot be built, or its recorded digest cannot be read."""


class CommitError(UtuxError):
    """A stage commit could not be made."""


class RunRefusedError(UtuxError):
    """A run did not start, for example because commits fail in `auto` mode."""


class NoRunToResumeError(UtuxError):
    """There is no checkpointed run to resume."""


class CheckpointMismatchError(UtuxError):
    """The checkpoint database is not one of this project's runs.

    No `run_started` event in the project's log matches it, so it may come
    from another project or another copy; utux does not resume from it.
    """


class RunPausedError(UtuxError):
    """A run paused for a person's answer to an approval request.

    The process ends; `utux run` resumes once the answer is written.

    Attributes:
        approval_id: The request that waits.
    """

    def __init__(self, message: str, approval_id: str) -> None:
        super().__init__(message)
        self.approval_id = approval_id


class RunRejectedError(UtuxError):
    """A person rejected a request, so the run stops."""


class ApprovalMismatchError(UtuxError):
    """An answer cannot be taken: an edit does not match the edited file."""


class MethodFormatError(UtuxError):
    """`method.md` names no metric, or a metric line is not of the exact form.

    The run stops before the implementation; correct `method.md` and run again.
    """
