# ADR-0001: Use Postgres + pgvector instead of a dedicated vector database

## Status
Proposed

## Context
The system's semantic memory needs a vector store for durable customer facts (per the article's four-memory design: procedural, semantic, episodic, knowledge graph). This is a 2-4 week POC targeting ~500-800 SKUs and ~100-150 customers, run locally on the developer's own machine before any cloud deployment.

## Decision Drivers
- Small data scale for the POC (hundreds, not millions, of vectors), no need for a horizontally-scaled ANN index.
- Minimizing the number of services to run and operate during a time-boxed POC.
- Postgres is already required for relational/episodic data, so reusing it avoids a second stateful service.

## Decision
Use Postgres with the `pgvector` extension as the vector store, instead of a dedicated vector database (Qdrant, Weaviate, etc.).

## Alternatives Considered
- **Qdrant / Weaviate (dedicated vector DB)**: would offer more specialized ANN performance tuning and horizontal scaling, but adds a separate service to run, secure, and pay for with no benefit at this POC's scale ("no separate service, one less thing to run/pay for, good enough at your scale (500-800 SKUs)").

## Consequences
- **Positive**: one fewer service to run locally and in the cloud later; unified backup/ops story with the relational data; no extra vendor/billing relationship.
- **Negative / accepted trade-offs**: pgvector's ANN performance and feature set lag purpose-built vector databases at large scale. This becomes a real constraint if the dataset grows well beyond POC size and would need revisiting then.

## Notes
Decided during stack-selection discussion; carried into `README.md` tech stack table.
