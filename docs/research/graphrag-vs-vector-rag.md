# GraphRAG vs Vector RAG

Researched 2026-09-27, feeding ADR-0002 and the README "Why This Beats What's Out There" section.

## Verified benchmark numbers

**Tian Pan, "GraphRAG vs. Vector RAG: The Architecture Decision Teams Make Too Late"**
https://tianpan.co/blog/2026-04-19-graphrag-vs-vector-rag-architecture-decision

- Enterprise multi-hop tasks: GraphRAG 86% accuracy, vector RAG 32%.
- Schema-bound queries requiring complex aggregation: vector RAG drops to 0%, graph-based retrieval hits 90%.
- Queries involving 10+ entities: vector RAG degrades to 0%, GraphRAG sustains above 70%.
- Author's own caveat: these are enterprise benchmarks the author flags as "cherry-picked for the worst case" for vector RAG. On simple semantic search (find documents about a topic), both approaches perform comparably and graph adds overhead with no benefit.

**GraphRAG-Bench, ICLR 2026** (peer-reviewed, more defensible than a single enterprise benchmark)
https://arxiv.org/html/2502.11371v3

- Simple fact retrieval: text chunks 60.9 vs graph 60.1, effectively a tie.
- Complex reasoning: graph 53.4 vs chunks 42.9, a +10 point graph win.
- Multi-hop (MultiHop-RAG): graph-guided retrieval 70.3 vs chunks 67.0.
- Conclusion of the paper: graph structure helps specifically on complex/multi-hop tasks, not universally.

**NICD (UK National Innovation Centre for Data), independent 2026 study** (via secondary source, not read directly)
https://hydradb.com/blog/graphrag-adoption-accuracy-statistics

- 510 complex questions tested. GraphRAG answered 65.3% correctly vs vector-only RAG's 28.9%.
- GraphRAG scored ~80% higher on truthfulness than vector-only RAG.

## When NOT to use GraphRAG

**VentureBeat, "Stop graphing everything: When GraphRAG actually beats vector RAG"**
https://venturebeat.com/orchestration/stop-graphing-everything-when-graphrag-actually-beats-vector-rag

Not fetched directly this session (found via search only). Worth reading before citing, since the title suggests it argues the counter-case (don't route everything through the graph). Relevant to the "hybrid retrieval router, ~80% of queries don't need graph" claim in the source article.

## Governance cost of building the graph

**Atlan, "What Is GraphRAG?"**
https://atlan.com/know/what-is-graphrag/

- Ungoverned source data produces 30-40% more duplicate or ambiguous nodes in the graph.
- Example failure mode: "Customer" node conflates a trial user, a paying account, and a Salesforce object into one node when source metadata isn't governed.
- Governed sources get 2-3x higher accuracy on entity-resolution benchmarks vs ungoverned extraction.

## Dead end, do not cite for the 86%/32% stat

**TigerGraph, "GraphRAG vs Vector RAG: Which Retrieval Approach Wins for Enterprise AI"**
https://www.tigergraph.com/blog/graphrag-vs-vector-rag/

Fetched and verified: this post is purely qualitative (architecture description only). It contains **no benchmark numbers**. It is commonly cited alongside the 86%/32% stat elsewhere but does not itself contain it. Use Tian Pan or GraphRAG-Bench instead.

## Blocked, unverified

**Ajay Srinivasan, Medium, "Graph RAG vs Vector RAG: Choosing the Right Architecture for Enterprise Use Cases"**
https://medium.com/@ajaysrinivasan87/graph-rag-vs-vector-rag-choosing-the-right-architecture-for-enterprise-use-cases-f3f6205f959f

Returned HTTP 403 (Medium blocks bot fetch, see `docs/gotchas.md`). Could not verify the "~80% simple lookup / ~15% graph reasoning / ~5% agentic planning" query-split claim attributed to this source in the original Medium article. Treat that specific split as unconfirmed until re-verified some other way.
