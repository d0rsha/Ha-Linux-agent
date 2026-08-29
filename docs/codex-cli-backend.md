# Codex CLI backend decision (v0.2)

## Decision

Do **not** use Codex CLI as a drop-in LLM provider for the core HA agent in v0.2.

Codex CLI is a coding/agent harness rather than an OpenAI-compatible model endpoint. Current Codex supports non-interactive `codex exec` runs and JSONL output, and Codex itself can connect directly to Home Assistant MCP. Those capabilities make it useful as a separate delegated agent, but they do not give the HA agent the same deterministic provider contract as an HTTP model API.

## Why not put Codex inside the provider abstraction?

The provider abstraction expects the model backend to return tool calls to this application, after which **this application** authorizes and executes them. Running a second agent harness inside that boundary would duplicate planning/tool logic and can blur the approval boundary.

There is also a deployment mismatch: Codex is installed on the Linux host while `ha-agent` runs in Docker. Exposing an unrestricted host shell, mounting the Docker socket, or sharing broad host credentials just to invoke Codex would weaken the isolation model.

## Supported direction

Use OpenAI, OpenRouter, or another OpenAI-compatible HTTP endpoint as the core LLM provider.

If Codex integration is wanted later, treat it as **delegation**, not a provider:

1. Run a narrow host-side service that owns Codex authentication.
2. Give it a small request schema (for example, coding/diagnostic tasks only).
3. Invoke `codex exec --json --ephemeral` or an appropriate Codex app-server interface.
4. Return bounded structured results to the HA agent.
5. Do not expose generic shell execution to the HA container.

Alternatively, configure Codex itself as an MCP client of Home Assistant for interactive/admin workflows. Keep its credentials and permissions separate from this agent.

## Revisit criteria

Revisit a direct provider implementation only if Codex exposes a stable model-style API whose tool calls are returned to the outer application without Codex independently executing them.
