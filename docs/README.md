# OpenFin Documentation

OpenFin is a local-first founder helper CLI. It keeps tasks, logs, project
memory, search data, context packs, and agent transcripts in files under one
OpenFin home directory.

Start here:

- [Usage](usage.md): install, initialize, capture work, manage tasks, build
  context packs, run agent sessions, and use Telegram relay.
- [Architecture](architecture.md): storage layout, module boundaries, command
  flow, agent instrumentation, daemon routing, and reliability principles.
- [SDK](sdk.md): Python APIs and extension points for storage, context packs,
  agent adapters, daemon clients, and Telegram integrations.
- [Development](development.md): local setup, tests, linting, TDD workflow, and
  how to add commands or adapters.
- [Operations](operations.md): OpenFin home management, daemon behavior,
  Telegram setup, scheduled digests, backups, and security notes.

## Current Scope

OpenFin currently focuses on:

- Plain-text project memory and task tracking.
- AI-ready context packs assembled from local state.
- Claude and Codex adapters behind an agent adapter seam.
- `openfind`, a local Unix-socket daemon that routes agent events and remote
  input.
- Optional Telegram relay owned by the daemon.

The web/dashboard surface is intentionally deferred.
