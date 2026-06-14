# Founder Context CLI — Build Spec (v2)

A single-player, local-first CLI that keeps your project state in one searchable place,
so you stop losing ideas in AI threads and stop re-priming AI from scratch.

Project: **OpenFin**. Command alias: **`f`**. Package: `openfin`.

---

## 0. Goal and the one acute pain

Make an idea you had once **findable in 3 seconds, not 20 minutes**, and make any new AI
thread **current with one command**. Everything else (tasks, digests, curation) is scaffolding
around those two.

Build priority: capture → search → context pack → tasks/overdue loop → curation.

---

## 1. Design principles

- **Plain text is canonical.** Markdown + a YAML task list, in a git repo. No DB, no server, no daemon in v1.
- **Parse on run.** Load files → act → write back. Personal scale → instant.
- **Capture is sub-second or it doesn't stick.** `f in "..."` appends one line and exits. Protect this above all.
- **AI-readable by construction.** State is markdown, so the context pack is concatenation + slicing.
- **Propose, never destroy.** Curation archives into the log; it never hard-deletes.
- **No automation of external actions.** No auto-posting, no auto-pinging. The memory surfaces material; you act.
- **The base tool calls no API.** Assembly is local and free. Metered spend lives only in the optional `ask`/`plan`/summarize layer.

---

## 2. Storage layout

`OPENFIN_HOME` env var → a git repo (default `~/openfin`).
`FOUNDER_HOME` remains a compatibility fallback.

```
openfin/
  charter.md          # L0 — identity, rarely changes; core of the context pack
  now.md              # L1 — current week: priorities, in-flight, blocked
  tasks.yaml          # structured tasks (canonical)
  inbox.md            # raw captures awaiting triage
  profiles.yaml       # context-profile definitions (see §6)
  log/
    2026-06.md        # L3 — append-only: ideas, decisions, done-items, captures, commits
```

All committed to git → free history, diffs, backup, sync. No derived/binary files in v1.

---

## 3. Schemas

### tasks.yaml — list of task objects

```yaml
- id: t-0001
  title: ping Tenity VC re thesis mismatch
  owner: me                 # default "me"; forward-compatible with cofounder sync later
  priority: P1              # P0 critical · P1 important · P2 normal · P3 someday
  status: open              # open · doing · blocked · done · dropped
  due: 2026-06-14           # ISO date or null
  recheck: null             # date to re-surface for a progress check (set on commit)
  created: 2026-06-13
  updated: 2026-06-13       # bumped on any status/edit — drives staleness flags
  tags: [investors]
  links: [outreach/tenity.md]
  notes: ""
```

IDs: incrementing `t-NNNN` (`max+1` on write). Short and typeable for `f done t-0007`.

### log/YYYY-MM.md — append-only, one line per entry

```markdown
## 2026-06-13

- 14:32 #idea #pricing meter by tokens-processed not seats — sidesteps the seat-count objection
- 15:10 #decision unified block_shape abstraction; contribute upstream, don't fork
- 16:45 #done t-0007 shipped PR-review skill v0
- 17:30 #commit t-0003 recheck 2026-06-15
- 18:20 #post shipped the quant abstraction — write up "per-tensor/channel/group as special cases"
```

Tag at capture (`#pricing`, `#post`, `#decision`) — costs nothing, makes search/profiles sharp.

### inbox.md — raw, pre-triage

```markdown
- 2026-06-13 14:32 ping design folks about onboarding flow
- 2026-06-13 14:50 idea: digest should lead with overdue only
```

### charter.md (L0) and now.md (L1) — hand-edited markdown

Charter sections are named by `##` headers so profiles can slice them:

```markdown
# maida.ai — Charter
## Mission
<one line>
## Cofounders
<names/handles>
## Stack
<list>
## Key decisions
- ...
## Non-goals
- ...
```

```markdown
# Now — week of 2026-06-09
_updated: 2026-06-13_

## Priorities
1. ...
## In flight
- ...
## Blocked / waiting on
- ...
```

`now.md` carries `_updated_`; if it goes stale (>7d) the digest flags it.

---

## 4. Command reference

### Capture (must be fast)
- `f in "<text>"` — append one timestamped line to `inbox.md`. Sub-second catch-all.
- `f add "<text>" [-p P1] [-d fri] [-t tag,tag]` — create a structured task directly.
- `f idea "<text>" [-t tag,tag]` — append a `#idea` line to the current month's log.

### Triage
- `f triage` — walk inbox items; each → task / idea / decision / note / drop. Empties the inbox.

### Views & search
- `f today` — overdue (loud) · today's top N · in-flight · waiting-on · stale flags. Says "run `f review`" if overdue/recheck items exist.
- `f overdue` — overdue list only.
- `f ls [--status x] [--tag y] [--owner z] [-p P1]` — filterable task list.
- `f search "<query>" [--tag x] [--since DATE]` — grep across charter, now, tasks, log, inbox; newest first, match highlighted. **The fix for the 20-minute hunt.**

### Task ops
- `f do <id>` → doing.  `f done <id>` → done (+ `#done <id>` to log).
- `f block <id> "<why>"` → blocked.  `f drop <id>` → dropped.
- `f edit <id>` — open in `$EDITOR` (or flags to set fields).

### Overdue accountability loop (§5a)
- `f review` — interactive pass over overdue tasks + tasks with `recheck` ≤ today. Per item: **commit / snooze / block / drop / done / skip.**

### Memory
- `f context [profile] [--for "<topic>"] [--copy]` — assemble a (scoped) context pack (§6).
- `f digest [morning|evening]` — formatted brief (§7).
- `f compact` — curation pass (§5).

Each command: load → act → write back. No persistent process.

---

## 5. Curation

### 5a. Overdue loop (`f review`)

The failure mode: an overdue task is *seen but never decided*, so it rots in the list.
Rule: **overdue items must resolve into a decision each time they surface.** `f review` gathers
overdue tasks + tasks whose `recheck` ≤ today, and for each forces one choice:

- **commit** → set `recheck = today + N` (ask or default +1d), append `#commit <id> recheck <date>` to log.
- **snooze** → push `due` to a new date; goes silent until then.
- **block** → status blocked (+ reason).
- **drop** → status dropped.
- **done** → status done.

If a `recheck` date arrives with no movement (status not advanced since the commit), it re-surfaces
louder: "committed <date>, nothing moved — recommit / snooze / drop?" (v1: re-prompt; auto-detect of
progress is a v2 refinement.) The loop must *reduce* prompts after a decision — snoozed items stay quiet.

### 5b. Archive + redundancy (`f compact`)

Non-destructive. Three jobs:

1. **Archive** — tasks `done`/`dropped` with `updated` > 14d → removed from `tasks.yaml`; a `#done`/`#dropped` line guaranteed in log. Moved, not deleted.
2. **Stale flags** — `open`/`doing` tasks with `updated` > 7d, plus `now.md` if `_updated_` > 7d → printed as a "still true?" list. Never auto-changed.
3. **Redundancy (superseded)** — flag where **≥2 open tasks share a tag and one is older/overdue** ("two open `#post` tasks, one overdue — consolidate?"). Plus optional `difflib` title-similarity match for cases tags miss. Always proposes; you confirm. (LLM semantic dedup deferred — it spends tokens; see §8.)

Mantra: **propose, never destroy. Archive = move to log.**
`#post`-tagged lines surfaced here (or `f ls --tag post`) are draft fodder — you write the post.

---

## 6. Context pack + profiles (`f context`)

**Selection is compression.** Profiles let you send only the slice a consumer needs, instead of the
whole brain — convenience *and* the primary cost lever (§8).

`profiles.yaml`:

```yaml
default:                      # everything
  charter_sections: all
  task_tags: all
  log_tags: all
  max_log_lines: 40
code:
  charter_sections: [Stack, Key decisions, Non-goals]
  task_tags: [code, eng, infra]
  log_tags: [decision]
  max_log_lines: 20
admin:
  charter_sections: [Mission, Cofounders]
  task_tags: [investors, ops, post, admin]
  log_tags: [decision, post]
  max_log_lines: 20
```

`f context [profile] [--for "<topic>"] [--copy]` emits, in order:
1. selected `charter.md` sections (sliced by `##` header)
2. `now.md` (full, or relevant sections)
3. open tasks filtered by the profile's tags, sorted by priority
4. recent log lines matching the profile's tags, capped at `max_log_lines`
5. **if `--for`**: grep hits from log/ideas matching the topic (the "pull the old idea" path)

`--copy` → clipboard (pyperclip); else stdout. **Footer prints a token estimate** (`chars/4`, or tiktoken
if you want accuracy); optional `--budget N` warns if exceeded.

Killer usage: `f context code --for "quant arch" --copy` → only the eng slice + the relevant decisions,
ready to paste into a coding agent. No investor noise, smaller payload.

---

## 7. Digest (`f digest`)

Read-only render; terminal in v1.

```
morning:  ⚠ OVERDUE (loud, → f review) · ▲ TODAY'S TOP 3 · ⋯ IN FLIGHT · ⏳ WAITING ON · ? STALE
evening:  ✓ CLOSED TODAY · ▲ TOMORROW'S TOP 3 · ⚠ SLIPPING
```

Short and ranked — lead with the 1–3 that matter; evening creates closure, not new loops.
Scheduling + phone delivery are Phase 2 (§10).

---

## 8. Efficiency & cost

**The base tool cannot overspend** — `f context --copy` → paste into a flat-rate subscription tool is
effectively free at the margin. Metered spend exists only in the optional `ask`/`plan`/summarize layer.
So scope efficiency work to that layer; do not pre-optimize the free path. Levers, in impact order:

1. **Profiles (§6)** — send a slice, not the brain. Biggest win, free, available now.
2. **Summary cache** — cache the compressed context summary keyed by a hash of the source files; regenerate only on change. *Compute compression once on write, reuse on every read.* Never re-summarize unchanged context. (Deferred with API layer.)
3. **Local model for housekeeping** — run summarize/dedup on a local quantized model; reserve the API (Opus/Sonnet) for actual reasoning (`f plan`). Decouples housekeeping tokens from thinking tokens. (Deferred.)
4. **Observability** — token readout on `f context` (now) + a per-call cost log when the API path lands, so spend is visible, not a surprise.

---

## 9. Tech stack

- Python 3.11+
- `typer` — CLI (type hints, fast, free `--help`)
- `pyyaml` — tasks/profiles
- `dateparser` — natural-language dates ("fri", "tomorrow", "in 3d")
- `rich` — color/tables (overdue red, today highlighted)
- `pyperclip` — clipboard
- `difflib` (stdlib) — fuzzy title match for redundancy
- Storage: plain files, parsed per invocation. No DB, no server, no daemon.

---

## 10. Build order (value-first, ~2.75h)

1. **0:00–0:30** — scaffold: config + load/save `tasks.yaml` + `add` `done` `ls` `today`. → working list.
2. **0:30–1:00** — `in` `idea` capture + `search` (grep). → **idea hunt solved.**
3. **1:00–1:30** — `context [profile] [--for] --copy` + token readout. → **AI re-priming solved.** (Profiles fold in here; same assembly code.)
4. **1:30–2:15** — NL dates + rich output + `overdue` + stale flags + **`f review`** (overdue commit/recheck loop) + `digest`.
5. **2:15–2:45** — `triage` + `compact` (incl. tag-collision redundancy; difflib optional).

Highest-value features (search + scoped context) done by ~90 min.
**To hold 2–3h:** ship profiles + the overdue loop tonight; defer fuzzy/LLM dedup and the entire API layer.

---

## 11. Deferred (Phase 2)

- Scheduled digests (launchd / systemd / cron → `f digest`), delivered to a Telegram bot or desktop notification (the off-laptop nudge).
- `f ask` / `f plan` — API over the context pack; **summary cache** + **local quantized model for housekeeping** + per-call cost log.
- LLM semantic dedup for redundancy.
- Auto-detect of progress in the overdue loop (status-advance/touch since commit).
- SQLite + FTS5 — drop-in when the corpus is large; markdown stays canonical, DB is a rebuildable index.
- Cofounder `f assign` + authorized-subset memory sync.
- Any web/dashboard UI (resist until proven necessary — it's another window to switch to).

---

## 12. Pitfalls for *this* build

- **Don't add the DB, API, or web UI tonight** — scope creep against 2–3h.
- **Capture stays sub-second** — short alias, `in` writes one line and exits. If capture leaves your flow, the store goes stale and the AI context goes wrong — worse than nothing.
- **Overdue must resolve to a decision** — listing without deciding is how tasks rot. But snoozed items go silent; the loop reduces prompts, never nags.
- **Don't pre-optimize the free path** — assembly is local and free; spend lives only in the opt-in API layer.
- **Keep canonical data plain text** — never trapped, AI reads it directly.
- **`compact` archives, never deletes.** Redundancy/stale checks propose; you confirm.
- **Tag at capture** — `#pricing`, `#post`, `#decision` cost nothing and make search, profiles, and redundancy sharp.
