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
