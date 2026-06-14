# Future Work

## Deferred API layer

`f ask` and `f plan` stay out of the base CLI until the provider and spend model are
explicitly chosen. The intended shape is:

- [x] build prompts from `f context` profiles and topic search
  - Implemented as `f context <profile> --for <topic>` and reused by `f --run claude`
    for context injection.
- [ ] cache summaries by source-file hash so unchanged context is not re-summarized
- [ ] log each API call with model, token counts, estimated cost, and task/profile context
- [x] keep all base commands local-only; API calls happen only through explicit API commands
  - Base memory/task/search/digest commands remain local. Agent/API spend is behind the
    explicit `f --run claude ...` path; `f ask` and `f plan` are still deferred.

## Phase 3 agent-layer deferrals

Phase 3 shipped the first agent wrapper, transcript store, daemon routing, and
Telegram control surface. The current implementation is intentionally the v0
path: local `f --run claude ...` owns the process, uses Claude's headless
stream-json mode per turn, and records normalized events for later context work.

- [x] Claude headless stream-json adapter
  - Implemented as the first `AgentAdapter`, with normalized events, native
    session id capture, context injection, transcript writes, and daemon relay.
- [ ] persistent Claude stream-json or SDK-backed warm session
  - Keep the agent process/session warm across turns instead of paying the cold
    start and context setup cost for each turn. This is the main latency upgrade
    for the Phase 3 story.
- [ ] daemon-owned detached agent sessions
  - Move process ownership into `openfind` so a session can survive closing the
    terminal that launched `f --run`, while still accepting local and Telegram
    input.
- [x] Codex adapter
  - Implemented with `codex exec --json` and `codex exec resume --json`, safe
    argv construction, context-pack prompt composition, normalized events,
    native thread/session id capture, and an opt-in real-binary smoke test.
- [ ] opencode adapter
  - Add an adapter for opencode with the same `AgentAdapter` contract and
    transcript/daemon behavior as Claude.

## Local AI housekeeping

Phase 2 keeps dedup deterministic for reliability and speed. Later adapters can add
semantic help behind the same proposal-only boundary:

- [x] deterministic dedup baseline
  - Implemented by `f compact` tag-collision checks and optional `--deep-dedup`
    title/token similarity scoring.
- [ ] Ollama adapter for local summarization and dedup when `ollama` is installed
- [ ] llama.cpp command adapter for quantized local models
- [x] no automatic task mutation from model output; model suggestions must still be confirmed
  - Current model-facing features produce context, transcripts, relay messages, or
    suggestions; task mutation remains command/user driven.

## Cofounder memory sync

`f assign` records ownership locally and writes an audit line to the log.
Authorized-subset sync is deferred until the collaboration workflow is clearer,
likely as a profile-based export/import bundle before any networked sync.

- [x] `f assign` records local ownership and appends an audit log line.
- [ ] authorized-subset export/import bundle
- [ ] networked sync
