"""A child process for the kill-and-resume test of check 1.

Usage: workflow_child.py PROJECT run-and-die | resume | run

`run-and-die` kills its own process with SIGKILL just before the experiment
stage starts, after the implementation stage has ended and been committed.
"""

import os
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from workflow_scripts import services  # noqa: E402

from utux.core.workflow import resume_workflow, run_workflow  # noqa: E402


def _die(node: str) -> None:
    if node == "experiment":
        os.kill(os.getpid(), signal.SIGKILL)


def main() -> None:
    project, mode = Path(sys.argv[1]), sys.argv[2]
    if mode == "run-and-die":
        run_workflow(project, services(project, before_stage=_die))
    elif mode == "resume":
        # The model was asked twice before the kill; nothing more is needed.
        resume_workflow(project, services(project, replies=()))
    elif mode == "run":
        run_workflow(project, services(project))
    else:
        raise SystemExit(f"unknown mode {mode}")


if __name__ == "__main__":
    main()
