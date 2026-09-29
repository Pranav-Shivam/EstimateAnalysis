# Phase 6 Interview Prep: Tracing, Corrections, and Memory That Compounds

This file exists so you can walk into an interview and explain this phase without re-reading code. Read the plain-English summary first, then use the questions to test yourself. Answers are written the way you'd actually say them out loud.

This one covers Phase 6 (Langfuse tracing, turning reviewer corrections into permanent facts, and the release gate).

---

## What Phase 6 actually is, in plain terms

Phase 5's judge can say "I'm not sure about this price, a human should check." Until now, though, a human's answer went nowhere. The next quote with the same predicted price would get flagged all over again. Phase 6 closes that loop, which is the "memory that compounds" claim the whole project is built to demonstrate. Four pieces:

1. **A way to record the answer.** `POST /v1/review/{id}/resolve` lets a reviewer approve a flagged item or correct it. A correction is validated at request time (right keys, right types, a positive price, a category that really belongs to a flagged line), so a bad correction fails the request instead of failing silently in a background job later.
2. **An eval case from every resolution.** Each resolution writes a labeled `eval_cases` row holding the full evidence the judge saw. That is the raw material for a bigger golden set, built from real human corrections instead of hand-authored ones.
3. **A consolidation job.** A correction is queued on `procrastinate` (Postgres-backed, per ADR-0003, no Redis) after the database commit. A worker turns it into a permanent fact in Postgres (a SKU list price, a required part, or a contract coverage category) and mirrors it into Neo4j as one edge or property. The next identical scenario finds a list price instead of a prediction, so the judge has nothing to flag.
4. **Tracing and a release gate.** Langfuse tracing wraps the agent loop, every tool call, every graph-integrity check, and every dedupe verdict. It is a no-op unless keys are configured. The release gate in `scripts/calibrate_judge.py` refuses to write a new threshold if the false-auto-send rate over the eval set is too high.

Proof it works, without any paid API: three acceptance tests plant a correction for each dimension (`price_provenance`, `graph_completion`, `contract_discount`), run consolidation, check the fact or edge exists and that the graph still reads as current, then run the identical scenario again and confirm it is trusted with no review item. One smoke test goes further and runs the real queue: a real deferred job, a real worker, against the local Postgres. The judge itself is a scripted fake in those tests, and that is stated in the test docstrings.

---

## Questions an interviewer might actually ask

### Walk me through what happens when a reviewer corrects a predicted price.

The request hits the resolve route. The service locks the review item row (so two clicks can't both win), validates the correction against real data, marks the row `corrected`, and saves an eval case, all in one transaction. The route commits, and only then enqueues the consolidation job. A worker picks it up, sets the SKU's list price in Postgres, marks the item `consolidated`, and updates the price on the SKU's node in Neo4j. Next time that SKU shows up, the price lookup returns a list price. The judge's evidence says "list," not "predicted," and the draft is trusted without a human. Approving instead of correcting records the label but changes no facts and queues nothing.

### Why does the job get enqueued after the commit and not inside the service?

Because procrastinate talks to Postgres on its own connection, so the job insert is not part of the request's transaction. Enqueue first and a worker can start before the correction is committed. It then sees the row still `open` and raises. If the commit later fails, an orphan job remains for a correction that never happened. The first version of this code did exactly that, and the task-level review caught it. Commit first, enqueue second, and if the enqueue fails the correction is safe and the reviewer's retry re-drives the job.

### The first version passed its tests and still could not have worked. What happened?

This is the best story from the phase. Every task passed review and 650 tests were green, but the final whole-branch review read procrastinate's source and found two Criticals. The worker used a synchronous connector, and a worker can only run on the async one, so `run_worker` would have crashed on startup. Also nothing ever created procrastinate's tables, and nothing opened the queue in the API process, so every real correction would have committed and then returned a 500, leaving the item stuck as `corrected` with no job. The tests hid all of it: they swapped in an in-memory connector or called the consolidation function directly, so the real queue path had never run once. The fix was a real smoke test that defers a job through the real connector and runs a real worker against Postgres. That test immediately found a third bug nobody predicted: on Windows, psycopg's async pool refuses the default event loop, so the worker needed an explicit selector loop. The lesson I'd give: a mock proves your code calls the queue, never that the queue works.

### How do you keep the graph from lying about being up to date?

The graph carries a fingerprint of the reference data it was built from, and every estimate checks it before trusting the graph. A single-edge consolidation could break that in three ways, and the review found all of them. It stamped the new fingerprint unconditionally, so if an earlier edge write had failed, a later success would stamp the graph "current" while it still lacked the earlier edge. The edge write was a `MATCH`, so a missing endpoint node meant zero edges written and it still stamped current. And a rebuild that reads data and then fingerprints it could stamp a fingerprint newer than what it actually loaded. The fixes fail closed: capture the fingerprint before the Postgres write, and stamp only if the stored value still equals it (a compare-and-set inside one Neo4j transaction). Count the edges really written and raise on zero. Have the rebuild take its fingerprint before it reads anything. The price of failing closed is that after a partial failure the graph reads stale, and estimates are blocked until someone runs a rebuild. I would rather block than send a wrong quote.

### What stops a bad correction from poisoning the reference data?

Validation at request time, and a lot of it, because the review found the first version accepted almost anything. It now requires exact keys, real numbers (a boolean is not a price), a price above zero and finite, and a SKU that doesn't require itself. For a contract correction, the category must be the actual category of a line flagged under that contract, so a reviewer can't accidentally extend a discount to something the judge never questioned. It also refuses a `corrected` outcome with no correction at all, which used to be a 500. There is a known remaining edge: a huge integer price can still raise an overflow error and return a 500 instead of a 422.

### The release gate measures false-auto-send rate. What is that and where does it fall short?

A false auto-send is a quote the system would send without a human that a human would have corrected. The gate re-scores the eval set at a candidate threshold and refuses to write it if that rate is over a ceiling. The first version scored eval cases on invented evidence: the stored data held only the flagged dimension, and the script filled every other field with defaults, so every case looked like a zero-dollar line. The numbers would have looked real and meant nothing. Now the full per-line evidence the judge actually saw is stored and used, and a malformed row fails loudly. Honest gaps: the rate is computed over all `ready` cases rather than only the auto-sent ones (which understates the risk among auto-sends, and is spec decision 8), and it only tries the lowest threshold that clears kappa.

### What does the tracing cover, and what does it deliberately not do?

One Langfuse trace per run, with spans for the agent loop, each tool call, each graph-integrity check, and each dedupe verdict. The client is a true no-op with no keys, and it never raises into the agent loop: a tracing failure must not break a quote. Gaps I would name myself: tool spans record the full result rather than the arguments plus a summary, which sends commercial data (customer names, discounts) to a hosted service once it is turned on; guardrail reads are one span, not one per read; and there is no `estimate_id` tag yet. It has also never been pointed at a real Langfuse instance. That needs approval, like the paid API runs.

### What is still not solved?

Say these plainly. A failed consolidation after its graph stamp leaves the graph stale until a manual rebuild, so the operational answer is "rebuild after a failed consolidation." With more than one worker there is a narrow window where two consolidations can race on the fingerprint reads. Eval case ids use count plus one, which would collide if a row were ever deleted. The API now needs Postgres at startup because the queue opens its connection pool there. A future procrastinate upgrade that ships new schema needs a new Alembic revision.

### How did the process itself go wrong, and what did you learn?

Three real things. The plan's example test code used a random UUID for an estimate id that is really a foreign key, and three separate tasks hit the same violation and fixed it the same way, which is the Phase 5 lesson again: spot-check a plan's test snippets against the schema before locking it. Parallel agents each get their own git worktree, but that worktree was created from a stale commit, so early parallel tasks landed missing earlier work; the fix that worked was baking a fast-forward merge by branch name into each agent's first instruction instead of correcting it afterward. And the whole-branch review, run on the most capable model, found the worker and queue failures that eleven passing task reviews could not, because they only exist in how the pieces connect.

---

## Quick-reference facts

- Route: `POST /v1/review/{review_item_id}/resolve`. Outcomes: `approved` or `corrected`. Errors: 404 not found, 409 already resolved with a different outcome, 400 dimension not resolvable, 422 invalid correction. Re-sending the identical correction on a `corrected` item re-drives the job.
- Consolidation handlers: `price_provenance` sets `Sku.list_price` plus the graph node property; `graph_completion` adds a `SkuRequirement` plus a `REQUIRES` edge; `contract_discount` adds a covered category plus a `COVERS` edge.
- Queue: `procrastinate` with the async `PsycopgConnector`, opened in the FastAPI lifespan; the worker runs via `scripts/run_worker.py`. Retry only on transient database errors, 5 attempts with exponential wait. A `consolidated` item is a no-op on redelivery.
- Migrations: 0006 (`review_items` resolution columns, `eval_cases`), 0007 (procrastinate's own schema, applied through Alembic).
- Graph freshness: compare-and-set on the stored fingerprint, fails closed, repaired by a rebuild.
- Tracing: Langfuse, no-op without keys, never raises into the agent loop. Never run against a hosted service.
- Release gate: `scripts/calibrate_judge.py` dry run by default; `--yes` is required to write a threshold. Never run for real.
- No real OpenAI, Anthropic, or Langfuse call anywhere in this phase.
- 687 automated tests, up from 598 before this phase.
- Process: eleven planned tasks plus two extra (the acceptance test, and a final fix wave of six commits), one review fix round on Task 8, one Opus whole-branch review that found two Critical and seven Important issues, and one scoped re-review that cleared them.
- Known deliberate gaps: trace payload shape and spans, gate denominator and single-threshold search, count-plus-one eval ids, a huge-integer price returning 500, and the manual rebuild after a partial graph failure.
