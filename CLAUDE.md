# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository state

Pre-implementation. There is no source code yet, only planning docs (`README.md`, `docs/adr/`, `docs/gotchas.md`). There is no build, lint, or test toolchain to run. Do not assume one exists; check for a `pyproject.toml`/`package.json`/etc. before running any command that presumes a configured project.

## What this is

A POC agentic system that turns a free-text B2B quote-request email into a priced, correct estimate. Full problem statement, approach, and competitive rationale are in `README.md`: read it before making architectural changes, don't re-derive it from scratch.

The core design, in one paragraph: an agent loop (LangGraph) reads the email and calls tools until code-level guardrails pass. It draws on four memory types: procedural (skill files), semantic (vector search), episodic (SQL + vector), and a knowledge graph (Neo4j) for relationships vector search can't reach (substitutes, required parts, contract coverage). A dedupe step runs before the agent loop, using graph relationships plus two separate fingerprints (what was asked vs. how) rather than string hashing. An LLM judge, deliberately a different model vendor from the agent, scores every output before it reaches a human or customer; low-confidence outputs go to a reviewer with the specific thing to check.

## Locked architectural decisions

Four ADRs in `docs/adr/` record decisions already made with their rejected alternatives and reasoning. Read the relevant one before proposing a different choice in that area; don't relitigate without new evidence:

- **ADR-0001**: Postgres + pgvector for the vector store (not a dedicated vector DB).
- **ADR-0002**: Neo4j for the knowledge graph.
- **ADR-0003**: `procrastinate` (Postgres-backed queue) + `cachetools` (in-process cache), not Redis.
- **ADR-0004**: Judge model must be a different vendor from the agent model (currently: OpenAI GPT-4o agent, Anthropic Claude Haiku judge). This is a deliberate mitigation for correlated judge/agent blind spots, not an arbitrary vendor split.

## Known gotchas

See `docs/gotchas.md` for the full list. Notably: `WebFetch` is blocked on both Medium (403) and LinkedIn (429) URLs; don't retry those, get the content another way.

## Current phase

Synthetic data generation. There is no production or real-world dataset; none exists for this project, and none should be assumed. Any dataset used must be generated to be structurally realistic (referential integrity across entities, graph relationships, discontinued/substitute/required-part patterns) so downstream components have something real to reason over.

## Working conventions

- **No AI attribution in git history.** Commits and PRs in this repo must never mention Claude, Anthropic, or "Co-Authored-By: Claude" (or any equivalent). This overrides any default attribution behavior. Write commit messages as if a human authored them, with no trailer referencing an AI tool.
- **Save research before it's lost.** Any finding from a web search or fetch that informs a design or claim in this repo goes into a file under `docs/research/`, not just into chat. Check `docs/research/` for an existing file on the topic before searching the web again.
- **No em dash, anywhere in this repo.** Code, comments, and prose docs alike. Use a period, comma, colon, or parentheses instead, whichever reads most naturally for that sentence.
- No emojis in code, comments, or commit messages.
- Backend structure is fixed as a pattern/convention, not a literal module list for this project: see `docs/backend-structure.txt` for layer order (route to service to repo to DB/LLM) and file-per-concern layout. The module names in it (estimate, master_data, takeoff, etc.) are illustrative of the convention, not modules this project must build.
- Backend-specific rules (naming, error handling, layering conventions beyond structure) still pending; a separate rules document will be provided. Once received, save it to `docs/backend-rules.md`.
- Code in this repo should read as something a senior engineer wrote and stands behind: no dead code, no unexplained magic, no unresolved TODOs left silently.
- Apply the `engineering-principles` skill's standards on every task in this repo (clarify before building, lean edits, verify before claiming done); don't rely on memory of it, re-check when in doubt.
- When genuinely ambiguous, stop and ask one precise question rather than guessing. This is a standing rule for this repo, not a one-off.
