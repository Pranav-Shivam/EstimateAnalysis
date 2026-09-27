# ADR-0003: Use Postgres-based queue (procrastinate) + in-process cache instead of Redis

## Status
Proposed

## Context
The system needs (1) caching for repeated retrieval-router lookups and (2) a background job mechanism for the "consolidate every N conversations" step (episodic memory to semantic memory/graph writes) and async email intake, so the API doesn't block on the full agent loop. The developer had no Redis instance available: "I am not sure how I can implement Redis locally. I don't have any Redis. Currently, I don't have any subscription."

## Decision Drivers
- No existing Redis instance or familiarity with running one locally.
- Minimizing new stateful services during a 2-4 week POC.
- Postgres is already running for relational and vector data.
- Preference for a cloud migration path that doesn't require translating to a different managed service later.

## Decision
Use `procrastinate` (a Postgres-backed task queue using `SKIP LOCKED`) for background jobs, and an in-process cache (`cachetools`) for retrieval-router caching. No separate cache/queue service is run.

## Alternatives Considered
- **Redis + Celery**: the most mature, industry-standard combination, but rejected as the heaviest option with ops overhead not justified at this scale ("good interview name-drop but ops overhead you don't need at this scale").
- **Redis + Arq**: async-native and a better fit for FastAPI's asyncio model than Celery, but still requires standing up and operating a Redis instance the developer doesn't have.
- **Redis + RQ**: simplest Redis-based option, but synchronous, which sits awkwardly inside an async FastAPI application.
- **Postgres `LISTEN/NOTIFY`** (raw, without procrastinate): viable, but lower-level and requires writing more plumbing code than a library provides.
- **RabbitMQ**: no advantage over Redis for this use case, and migrating it to a managed cloud equivalent (Azure Service Bus / AWS MQ) is a translation, not a drop-in swap, unlike a managed Postgres.

## Consequences
- **Positive**: zero new stateful services to run or pay for during the POC; reuses the Postgres instance already required; migration to any cloud's managed Postgres is a connection-string change, not a service swap.
- **Negative / accepted trade-offs**: lower throughput ceiling than a Redis-backed queue if the system needs to scale past POC volume. If asked "how would you scale this," the answer is an acknowledged future swap to Celery+Redis, not a currently-benchmarked path.

## Notes
Decided after a comparative research pass across Redis+Celery, Redis+Arq, Redis+RQ, Postgres `LISTEN/NOTIFY`, RabbitMQ, and in-process caching. Carried into `README.md` tech stack table.
