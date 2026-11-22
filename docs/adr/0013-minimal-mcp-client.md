# ADR-0013: A minimal MCP client on the standard library

- Status: Accepted
- Date: 2026-11-22

## Context

Domain tools are reached through MCP (ADR-0005), and the `ToolProvider`
interface's v1 implementation is an MCP client (`docs/spec.md`, section 5).
M2 needs one server: BioMCP, as the PubMed source of the bio pilot pack
(`docs/spec.md`, sections 5 and 12; `docs/plan/M2.md`, M2-07). Each server
has a permission manifest, shown for approval before it is enabled and again
when it changes; the core enforces it where it can, logs every tool call by
the hashes of its arguments and result, and treats tool output as untrusted
data (`docs/spec.md`, section 10). On an MCP failure the tool is marked
unavailable, the agent is told, and the gap is recorded (`docs/spec.md`,
section 14).

MCP is JSON-RPC 2.0. A client over stdio starts the server as a child
process and exchanges one JSON message per line on its standard input and
output. Opening a session is an `initialize` request, in which client and
server agree on a protocol version, followed by the client's `initialized`
notification. Tools are listed with `tools/list` and called with
`tools/call`.

New runtime dependencies need approval, with their licence, size and
behaviour (`AGENTS.md`, section 10).

## Decision

utux reaches MCP servers through its own minimal client on the standard
library, for servers that run over stdio. It covers the session opening
(`initialize` and the `initialized` notification), `tools/list` and
`tools/call`, and nothing else: no resources, prompts, sampling, roots,
subscriptions or HTTP transports. No MCP SDK is added.

A server runs as a child process with an empty environment, apart from the
variables its permission manifest names. **For a server outside a container,
the paths and hosts in its manifest are shown and approved, but not
enforced.**

**A manifest approval binds** to the manifest's hash and to the version, or
the hash, of the server's executable. Any change of either asks for approval
again before the server runs. Its tool output is size-limited and
treated as data. A server that does not answer within a timeout, answers
with a protocol version the client does not support, or breaks the protocol,
is marked unavailable for the run.

## Alternatives rejected

- **The official MCP SDK for Python.** It covers the whole protocol and its
  transports. It would add a runtime dependency, with its own dependency tree,
  to use three methods, and every dependency needs the assessment of
  `AGENTS.md`, section 10. The three methods over newline-delimited JSON-RPC
  are small enough to write and test here.
- **Calling BioMCP's own Python API or its underlying web APIs directly.**
  This would skip MCP for the one server of M2, against ADR-0005, and leave
  the permission manifest without a client that applies it.
- **HTTP transports.** No server of M2 needs one, and a network transport
  would widen what the client must defend. They can be added in a later ADR.

## Consequences

- The client is small and fully under test: a scripted MCP server runs as a
  child process in the tests (M2-07), and protocol errors are typed.
- Only the parts of MCP that utux uses are supported. A server that needs
  more, for example sampling or resources, is not usable until the client
  grows, by a later decision.
- **A child process is not a sandbox.** The empty environment keeps
  credentials and host variables from the server, but the core cannot
  restrict the paths or hosts of a server run as a plain child process. The
  specification enforces those "for servers run in containers"
  (`docs/spec.md`, section 10). For a server run as a child process, the
  manifest's paths and hosts are shown and approved, not enforced. Running
  servers in the sandbox of M1 is left to a later decision.
- The protocol version the client supports is a constant. A change of MCP
  that the client must follow is a code change, tested like any other.
- Every tool call writes a `tool_call` event with the hashes of its arguments
  and result, and a failure marks the tool unavailable for the run.

### Acceptance, 2026-11-22

Accepted by the maintainer on 2026-11-22, with two additions now in the
decision: paths and hosts of a server outside a container are shown and
approved but not enforced, and an approval binds to the manifest's hash and
to the server executable's version or hash.

## Sources

- `docs/spec.md`, section 5 (`ToolProvider`, BioMCP in the bio pilot),
  section 10 ("MCP servers and plugins"), section 12 (the M2 row) and
  section 14 (MCP failure).
- `docs/adr/0005-mcp-for-domain-tools.md`: MCP for domain tools and the
  permission manifest.
- `docs/plan/M2.md`, M2-01 (the recommendation) and M2-07.
