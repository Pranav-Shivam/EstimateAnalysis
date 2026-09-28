# Neo4j Community Edition, GDS, and Leiden

Researched 2026-09-28 for Phase 4 (feeds ADR-0002 follow-through and the Phase 4 spec).

## Is Leiden available in the Community Edition?

Yes. GDS core features, Leiden included, ship in both editions. The Community edition of GDS limits concurrency to 4 CPU cores and the model catalog to 3 models; neither matters for a graph of a few thousand nodes.

Source: Neo4j GDS manual, Leiden and Introduction pages.
https://neo4j.com/docs/graph-data-science/current/algorithms/leiden/
https://neo4j.com/docs/graph-data-science/current/introduction/

## Leiden facts that shape the design

- Undirected relationships only: it refuses a directed projection. The projection must declare `orientation: 'UNDIRECTED'` for every relationship type used.
- Parameters: `gamma` (resolution, default 1.0; higher gives more, smaller communities), `theta` (default 0.01), `maxLevels` (default 10), `randomSeed` (optional), `includeIntermediateCommunities` (default false).
- Deterministic only when `randomSeed` is set. Without it two runs can label communities differently.
- Modes: stream, stats, mutate, write.
- Leiden is not parallelised (secondary source, GDS issue threads), which is irrelevant at this scale.

## Running GDS in Docker

The image installs GDS at startup from the `NEO4J_PLUGINS` env var:

```
--env NEO4J_PLUGINS='["graph-data-science"]'
```

The download happens at container start, so the first start needs internet access. Docs example uses `neo4j:latest`; no version constraints are documented on that page.

Source: https://neo4j.com/docs/graph-data-science/current/installation/installation-docker/

## Version gotcha

GitHub issues neo4j/neo4j#13535 (5.24.1 community) and #13563 (5.26.0) show the auto-fetched GDS build failing to load on a Neo4j version it was not built for (`io/prometheus/client/Collector` not found; "no compatible graph-data-science plugin found"). Lesson: pin an exact Neo4j image tag and verify the plugin loaded (`RETURN gds.version()`), rather than trusting `latest`.
https://github.com/neo4j/neo4j/issues/13563
https://github.com/neo4j/neo4j/issues/13535

## Image tags seen on Docker Hub (2026-09-28)

`2026.09.0-community`, `2026.09-community`, `5.26.31-community` (LTS line), plus `latest`/`community`. GDS 2026.09 is the current manual version.

## Verified locally (2026-09-28)

`docker run` of `neo4j:2026.09.0-community` with `NEO4J_PLUGINS='["graph-data-science"]'` started cleanly (log line `Started.`, GDS extension registered) and `RETURN gds.version()` returned `2026.09.0`. HTTP (17474) and Bolt (17687) answered from Windows through WSL port forwarding. The dev Postgres (PostgreSQL 18.6, port 5433) lists pgvector 0.8.6 as available.

## Local environment findings (2026-09-28, earlier in the session)

- Docker Desktop daemon was not running when checked (`docker ps` could not reach the engine pipe).
- Host ports 5432 (an unrelated Postgres) and 5433 (the project Postgres) are in use. 7474 and 7687 were free at check time but are Neo4j defaults, so the project maps Neo4j to non-default host ports.
