# ADR-0002: Use Neo4j for the knowledge graph

## Status
Proposed

## Context
The architecture requires a knowledge graph to store entities and typed relationships (customers, contracts, SKUs, substitutes, required parts) and to run community detection (Leiden) for graph-summary retrieval, per the source article's design. The developer's stated constraint for local graph DB choice was explicitly open-ended: "whichever is easy to work on my machine."

## Decision Drivers
- Ease of local setup (must run via Docker on the developer's machine).
- Needs built-in support for Leiden community detection without extra tooling.
- Needs a clean migration path to a managed cloud offering later, on either Azure or AWS, without rewriting queries.

## Decision
Use Neo4j Community Edition, run locally via Docker, as the graph database.

## Alternatives Considered
Only Neo4j was evaluated. The developer deferred the choice ("whichever is easy"), and Neo4j was proposed as the default because it has the GDS plugin with Leiden built in, matches the query language used throughout the reference architecture, and has a managed equivalent (Neo4j Aura) available on both Azure and AWS marketplaces for a no-code-change migration. No competing graph database (e.g. Memgraph, ArangoDB, Amazon Neptune) was actually discussed or rejected on its merits.

## Consequences
- **Positive**: simplest local setup path (single Docker container); Leiden community detection available out of the box via GDS; same Cypher query surface carries over to the managed Neo4j Aura offering later, on either cloud.
- **Negative / accepted trade-offs**: locking into Neo4j's query language and ecosystem now, without having compared it against alternatives on cost or performance. If Aura pricing or Neo4j-specific limitations become a problem later, that comparison hasn't been done yet.

## Notes
Decided during stack-selection discussion; carried into `README.md` tech stack table.

Verified 2026-09-28: `neo4j:2026.09.0-community` with `NEO4J_PLUGINS='["graph-data-science"]'` starts cleanly and `gds.version()` returns 2026.09.0, so Leiden works on Community edition. The image tag is pinned in `docker-compose.yml` because an auto-fetched GDS build has failed on other Neo4j versions. Host ports 17474 and 17687 are used to avoid the defaults. See `docs/research/neo4j-gds-leiden-community.md`.
