"""The workflow graph of a run (milestone M1).

LangGraph is used only inside this package. Importing it switches LangSmith
tracing off for the whole process, before any graph of this package can be
built: with tracing on, LangChain sends each node's inputs and outputs to
LangSmith's servers, and a user's `LANGSMITH_TRACING=true`, set for other
work, would otherwise switch it on (`docs/plan/M1.md`, M1-02).
`langsmith.configure(enabled=False)` takes precedence over that environment
variable. It opens no connection and writes no file.
"""

import langsmith

langsmith.configure(enabled=False)
