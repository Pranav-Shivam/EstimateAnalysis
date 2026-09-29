# Quote Estimation Agent

A proof-of-concept system that turns a messy, free-text quote request email into a correct, priced estimate: automatically, in minutes instead of hours.

## The Use Case

A B2B distributor (plumbing/HVAC supply, in this POC) receives quote requests as unstructured email: no part numbers, no fixed format, sent by whoever is on-site that day. Turning that into a priced, correct quote today takes a skilled rep 30-45 minutes, and the knowledge needed to get it right (which SKUs are discontinued, which products require an accessory nobody thought to ask for, which discount applies to which pricing category) lives in people's heads, not in the system.

That creates four compounding problems:

- **Slow**: median response time of 13+ hours; most B2B buyers book with whoever answers first.
- **Wrong**: discontinued items substituted incorrectly, required parts missed, discounts applied to categories a contract doesn't cover.
- **Duplicated**: the same job arrives twice (two people, two branches, a resend), gets quoted twice, at two different prices.
- **Forgetful**: when a rep fixes a mistake, the fix lives in that one quote. The next rep repeats it. When the rep leaves, the knowledge leaves with them.

## The Approach

An agent reads the email, plans its own steps (look up the customer, search the price book, check stock), and stops only when code-level guardrails pass, never on a discount the contract doesn't allow.

It draws on four kinds of memory, not one:

- **Procedural**: pricing rules and policy, loaded as skills.
- **Semantic**: durable facts about a customer (vector search).
- **Episodic**: what happened before (SQL + vector).
- **Knowledge graph**: how everything connects: substitutes, required parts, contract coverage. This is what catches the mistakes that are invisible in the text but visible in the relationships.

Before anything reaches a human, an LLM judge (a different model from the agent, so it doesn't share the agent's blind spots) scores the estimate against the price book, the contract, and the graph path that produced it. High-confidence quotes go straight out. Low-confidence ones go to a reviewer with the one specific thing to check, not the whole quote.

A dedupe step runs before any of this: cheap checks first (domain, address, zip), then graph relationships (not string matching) to catch the same job arriving from a different person or branch, and two separate fingerprints (one for *what* was asked, one for *how*) to tell a duplicate from a genuine revision.

Every human correction gets written back as a fact and a graph edge, so the same mistake is never made twice.

## Why This Beats What's Out There

Most quoting automation optimizes for speed alone, or retrieval alone:

- **Fast-but-shallow tools** (LLM-wraps-email-parsing) get the draft out quickly but miss relationships that aren't in the text: a discontinued SKU's replacement sitting in a pricing category the customer's contract doesn't cover, for instance.
- **Vector-RAG-only systems** retrieve chunks that *read* relevant but can't intersect facts across documents. Benchmarked multi-hop accuracy for vector-only retrieval sits around 32%, versus ~86% for graph-based retrieval on the same class of question.
- **Naive dedupe** (hash the raw text) fails in both directions: it misses a reworded duplicate and mistakes a genuine spec revision (changed finish, changed gauge) for a repeat.

This system is the combination: an agent loop with hard guardrails, a knowledge graph for the relationships vector search can't reach, a calibrated eval gate instead of blind trust, and a dedupe layer built on relationships and dual fingerprints instead of string matching. Each piece alone is available off the shelf. The combination, with memory that compounds instead of resetting every run, is not.

## Tech Stack

| Layer | Choice |
|---|---|
| Backend | FastAPI |
| Frontend | Vite + React + Tailwind + Ant Design |
| Relational + vector DB | Postgres + pgvector |
| Graph DB | Neo4j |
| Cache | in-process (`cachetools`) |
| Background jobs | Postgres-based (`procrastinate`) |
| Agent LLM | OpenAI GPT-4o |
| Judge LLM | Anthropic Claude Haiku |
| Embeddings | OpenAI (`text-embedding-3-small`) |
| Orchestration | LangGraph |
| Tracing / eval | Langfuse |
| Containerization | Docker Compose |
| Config | `.env` + pydantic-settings |

## Status

Proof of concept, in progress. Phases 1 to 4 are built: synthetic data generation, intake and dedupe, the pricing agent with code guardrails, and the Neo4j knowledge graph (the article's 10 node and 15 edge types, Leiden communities, local and global query modes, and a router over SQL, graph and vector search) with graph-backed guardrails that block a left-in discontinued SKU or a missing required part. No production data source exists; the dataset is generated to be structurally realistic (referential integrity, graph relationships, discontinued/substitute/required-part patterns) so every downstream component has something real to reason over.

## Sources

- Baytech Consulting, ["From Days to Minutes: Custom CPQ and Sales Velocity"](https://www.baytechconsulting.com/blog/from-days-to-minutes-custom-cpq-sales-velocity.md): 78% of B2B buyers pick the first credible proposal; 24–72hr average B2B quote response time.
- Proton.ai, ["RFQ Automation Software"](https://www.proton.ai/blog/rfq-automation-software): 13–14hr median quote turnaround, ~30hr average, from distributor interviews.
- Distribution Strategy Group, ["Beyond the Spreadsheet"](https://distributionstrategy.com/beyond-the-spreadsheet-transforming-order-quote-processes/): 40%+ of potential wins lost once a quote takes longer than 24hr.
- Broadn, ["Fast Quotes Boost Manufacturing Win Rates by Half"](https://www.broadn.io/blogs/fast-quoting-increases-manufacturing-win-rates): fast quoters can price up to 3% higher without losing the customer.
- Orbweaver, ["What Is the RFQ Process in the Electronic Components Supply Chain?"](https://www.orbweaver.com/?p=683): duplicate quotes inflate pipeline; regional duplicates create internal competition that erodes margin.
- Tian Pan, ["GraphRAG vs. Vector RAG: The Architecture Decision Teams Make Too Late"](https://tianpan.co/blog/2026-04-19-graphrag-vs-vector-rag-architecture-decision): 86% (GraphRAG) vs 32% (vector) accuracy on enterprise multi-hop benchmarks; author flags this as a worst-case-for-vector scenario, not universal.
- GraphRAG-Bench, ICLR 2026 ([arXiv:2502.11371](https://arxiv.org/html/2502.11371v3)): peer-reviewed, task-specific: simple lookup ties (60.9 vs 60.1), graph wins complex reasoning (53.4 vs 42.9) and multi-hop (70.3 vs 67.0). Primary citation for the multi-hop claim; more defensible than a single enterprise benchmark.
- Atlan, ["What Is GraphRAG?"](https://atlan.com/know/what-is-graphrag/): ungoverned data sources produce 30–40% more duplicate/ambiguous graph nodes; governed sources get 2–3x higher entity-resolution accuracy.
- HASH, ["Entity Resolution"](https://hash.ai/glossary/entity-resolution): merges should be edges, not deletes: reversible, with diff/merge history recorded.
- Apify, ["Entity Resolution Engine"](https://apify.com/that_red_bird/entity-resolver): oversized blocking keys (e.g. everyone sharing `gmail.com`) should be skipped rather than compared, to avoid comparison blowup.
- Galileo AI, ["How to Calibrate Your LLM Judge With Human Annotations"](https://galileo.ai/blog/calibrate-llm-judge-human-annotations) and Future AGI, ["LLM-as-a-Judge in 2026"](https://futureagi.com/blog/llm-as-a-judge/): calibration methodology for the eval gate: golden set of 50–200 human-labeled examples, Cohen's kappa >0.6 acceptable / >0.8 strong.
- Go Autonomous, [RFQ & Quote Automation](https://goautonomous.io/use-cases/rfq-quote-automation/): named-company proof points (Danfoss: quotes under 1 minute across 26 countries; Mediq: 91% of commercial requests handled autonomously).

Not cited: the TigerGraph GraphRAG/vector-RAG comparison is qualitative only and contains no benchmark numbers; dropped as a source for the 86%/32% claim despite being commonly paired with it elsewhere.
