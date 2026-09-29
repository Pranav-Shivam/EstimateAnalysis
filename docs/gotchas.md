# Gotchas

## 2026-09-27

- `WebFetch` returns HTTP 403 on Medium article URLs. Medium blocks bot fetches outright, even for public posts. If you need the content, get it from a local export/markdown copy instead of trying to fetch the live URL.
- `WebFetch` returns HTTP 429 on LinkedIn profile URLs. LinkedIn blocks scraping regardless of the tool. Don't burn a call trying; ask the user directly for the background info instead.
- The TigerGraph blog post ("GraphRAG vs Vector RAG: Which Retrieval Approach Wins for Enterprise AI") is often cited alongside the "86% vs 32% multi-hop accuracy" GraphRAG stat, but it contains no benchmark numbers at all: purely qualitative architecture comparison. Verify a stat's actual source before reusing a citation list; don't assume adjacency in a sources section means the number lives in that link.
- A chained Bash command (`git init && mkdir ...`) that gets interrupted mid-execution can leave the first command's effect rolled back rather than partially applied. `git init` reported "Initialized empty Git repository" but the `.git` directory did not exist afterward. Always re-check state (`git status`) after an interrupted command rather than trusting the last printed output.

## 2026-09-28 (Phase 4)

- `gds.graph.project` used as a Cypher aggregation returns one row with a null graph name, not zero rows, when the MATCH finds nothing. Check for the null before calling an algorithm on the projection, or it fails with "graph does not exist".
- `SET n += {prop: null}` removes the property in Neo4j instead of storing null. A SKU with no list price therefore has no `list_price` property; read it with `n.list_price IS NULL`.
- Community edition has no composite node keys. Uniqueness across namespaces is enforced on a single `key` property holding `<namespace>:<id>`.
- GDS Leiden only accepts undirected projections. Declare `undirectedRelationshipTypes: ['*']` when projecting, and set `randomSeed` (and `concurrency: 1`) if two runs must agree.
- `gds.graph.drop(name, false)` returns a deprecated `schema` column; `YIELD graphName` alone avoids the notification.
- A Cypher pattern in a `RETURN` needs `EXISTS { ... }` or `COLLECT { ... }`; a bare pattern expression is rejected by current Neo4j.
- `MERGE (a)-[r:T]->(b)` collapses two relationships of the same type between the same pair of nodes into one. PRICE_VARIANCE is written with delete-then-CREATE so two lines for one SKU stay two edges.
