# Security policy

## Reporting a vulnerability

Please do not report a suspected vulnerability in a public issue, a pull
request or a discussion.

Use GitHub's private vulnerability reporting instead: on the repository page,
open the **Security** tab and choose **Report a vulnerability**. The report
is visible only to you and the maintainers.

Please include:

- what the problem is and what an attacker could do with it;
- the steps or a minimal example to reproduce it;
- the commit or version you tested;
- whether you think it is already being exploited.

Do not include a working API key or anyone's personal data. The maintainer
replies in the private advisory, works on a fix there, and credits you in
the advisory unless you ask not to be named.

## Supported versions

utux Agent has no release yet. Only the `main` branch is supported, and
fixes go there.

## What to know before you use utux Agent

**Plugins and MCP servers run arbitrary code.** A domain pack, a plugin, an
MCP server or a tool reached through MCP is code that runs with the
permissions it is given, on your machine or wherever it is started. utux
cannot make untrusted code safe. Install only plugins and MCP servers whose
source you trust, as you would any other program.

utux has no plugin or MCP support yet. When it does, each plugin and MCP
server will have a permission manifest that you approve, and the core will
enforce it where it can: a tool allowlist per agent, and path and network
limits for servers run in containers (section 10 of the
[specification](docs/spec.md)). A server that runs outside a container is
limited only by your operating system. Tool and server output is treated as
untrusted data, never as an instruction, but that does not limit what the
code does when it runs.

**Model-written code.** utux never runs code written by a model on the host.
From milestone M1, such code runs only in a hardened Docker sandbox (see
section 10 of the [specification](docs/spec.md)). A container is not a
complete security boundary; a kernel or Docker vulnerability can break out of
it.

**API keys.** Keys are read from environment variables only and are never
written to a file, a log, an event or an error message. A key found anywhere
else is a vulnerability; please report it.

**Data sent to model providers.** Under the data policy `external_allowed`,
prompts go to the configured provider, such as OpenRouter. Under
`local_only`, every call to an external provider is refused. Choose the
policy that fits your data before you create a project.

**Cost.** Calls to a paid provider cost money. utux stops at the project
budget, with the limits described in [Cost and budget](docs/cost.md); a
provider that reports no cost is not limited by it.
