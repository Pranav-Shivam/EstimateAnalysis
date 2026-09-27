# Checklist

Tracks everything open on this project. Update as items close or new ones surface; don't let this drift out of sync with reality.

| Title | Description | Why this now | Status |
|---|---|---|---|
| Provide backend rules document | You mentioned a rules txt for backend beyond structure (naming, error handling, layering conventions etc.), not yet received | `docs/backend-structure.txt` only covers folder/file layout, not behavioral rules; CLAUDE.md has a placeholder waiting on this | Waiting on you |
| Write formal spec for sub-project 1 (synthetic data gen) | Design was discussed and approved in chat (catalog_gen, customer_gen, graph_export, scenario_gen, validate.py) but never written to `docs/adr/` or a spec file per the brainstorming process | Nothing is implementable yet without a written spec to build the implementation plan from | Not started |
| Get Anthropic API credit (~$5) | ADR-0004 locked in Claude Haiku as judge model; no Anthropic key exists yet, only OpenAI | Needed before any agent+judge code can actually run, not just be designed | Not started |
| Install Docker Desktop | You have WSL2 but Docker itself isn't installed yet; explicitly deferred earlier ("just requirements gathering phase") | Needed before Postgres, Neo4j, or Langfuse containers can run locally | Deferred by you |
| Write Docker Compose file | Postgres+pgvector, Neo4j (with GDS plugin for Leiden), Langfuse; no compose file exists yet | This is the concrete deliverable that makes "keep everything local" from the stack decisions actually runnable | Not started |
| Decide GitHub repo visibility and push | Local git repo initialized, nothing pushed; you said you want it public for the interview | Needed before it's usable as an interview artifact; currently only exists on your machine | Not started |
| Commit currently untracked/staged work | `README.md`, 4 ADRs, `docs/gotchas.md`, `docs/research/*`, `CLAUDE.md`, `docs/backend-structure.txt` are all sitting uncommitted | Nothing is version-controlled yet despite being the bulk of the project's documentation so far | Not started |
| Write specs for sub-projects 2-6 | Intake/dedupe, agent + pricing tools, knowledge graph, evals + review workflow, LLMOps/tracing; each needs its own design + spec, one at a time, per the decomposition agreed early on | Each sub-project's spec should only be written once the prior one is built or at least fully specced, to avoid designing against assumptions that later change | Not started |
| Set up `.env` / pydantic-settings | Config approach decided (ADR-level stack table) but no actual config module exists | First piece of real code any sub-project will need, regardless of which one gets built first | Not started |
