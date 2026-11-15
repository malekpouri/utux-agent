# ADR-0005: MCP for domain tools

- Status: Accepted
- Date: 2026-11-15

## Context

The core knows nothing about any research domain; everything domain-specific
lives in a domain pack. Domain tools cannot be hard-coded into a general core.
The `ToolProvider` interface lists and calls domain tools.

## Decision

Domain tools are reached through MCP. The v1 implementation of `ToolProvider`
is an MCP client, and any MCP server is added by configuration, in the `tools`
entry of a domain pack.

Each MCP server has a permission manifest that states which tools it exposes,
which file paths it may read or write, which network hosts it may reach and
which credentials it receives.

## Alternatives rejected

- **Hard-coding domain tools into the core.** Rejected: domain tools cannot be
  hard-coded into a general core.
- **First-use confirmation alone as the safeguard.** Rejected as not enough;
  permission manifests are required.

## Consequences

- The CLI shows the manifest for approval before a server is enabled, and
  again whenever the manifest changes.
- The core enforces the manifest where it can: a tool allowlist per agent, and
  path and network restrictions for servers run in containers.
- Every tool call is logged with its arguments hash and result hash.
- Tool output is treated as untrusted data and never as instructions to an
  agent.
- On an MCP failure the tool is marked unavailable, the agent is told and the
  gap is recorded.
- A curated server list per pack is deferred.

## Sources

- `docs/spec.md`, section 5, "Six pluggable interfaces", row `ToolProvider`,
  and "Domain packs".
- `docs/spec.md`, section 6, technology stack table, row "Domain tools".
- `docs/spec.md`, section 10, "MCP servers and plugins".
- `docs/spec.md`, section 14, row "Error handling".
