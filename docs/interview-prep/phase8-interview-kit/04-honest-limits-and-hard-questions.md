# 04. Honest Limits and Hard Questions

Part A is what I say up front. Part B is the 12 questions I expect, with short spoken answers. Every limit in Part A was checked in the code or docs. The check is named in brackets.

---

## Part A. Honest limits (say these first)

A senior engineer names the weak spots before being asked. I use this as a short list, then move on.

1. **The data is synthetic.** Everything is generated: 650 SKUs, 125 customers, 60 emails with planted situations. So the system is shown to work on data shaped the way I expect real data to be shaped. It says nothing about real email variety. [`backend/data`, `docs/roadmap.md` Phase 1]

2. **The live GPT-4o run was small and single-shot.** On 2026-09-30 I ran real intake over all 60 emails and the real agent over 40 (10 per scenario type: discontinued swap, missing required part, wrong-category discount, clean), once, for $1.04 by my meter. Earlier smoke runs, and the run before I added rate-limit retries, gave slightly different intake numbers, so results move between runs. The judge has not scored those live drafts. The agent scoring checks which parts are on the draft and whether a discount was wrongly applied, not quantities or prices (the guardrails own prices). [`backend/data/live_run_report.json`, `backend/scripts/run_live_estimates.py`]

2b. **Live intake is weaker than the tests suggested.** The right parts were resolved on 44 of 60 emails and the right customer on 51 of 60. Nearly all part misses are emails that type a part number ("Name (SKU-0601)"): the resolver matches names and ignores the number. 9 of 10 missing-required-part emails were affected. Customer misses are mostly emails signed with a first name only. I have not fixed this. [`backend/data/live_run_report.json`, `backend/app/intake/resolution.py`]

2c. **Live dedupe got 4 of 10 pairs; the 10 of 10 test injects the answer key.** The misses come from 2b (empty part sets) and from an unresolved customer on the earlier email, so blocking found no candidate. There were no false merges. [`backend/data/live_run_report.json`, `backend/tests/test_phase2_acceptance.py`]

3. **The seeded demo uses scripted stand-ins, not a live model.** The demo's judge scores are fixed numbers (for example 0.2 for a doubted fact, 0.95 for a trusted one), and every quote's line quantities are 1 even when the email says 4. The stored model name on a verdict still reads `claude-haiku-4-5-20251001`, so I say out loud that the demo scores are scripted. What is real in the demo is everything downstream of the model calls. [`backend/scripts/demo/fakes.py`, screenshot 02]

4. **The calibration set is small and templated.** 32 cases, of which 29 reach the judge. They come from a few templates: thin predicted price, strong predicted price, healthy contract, expiring contract, clean line, and three guardrail-blocked cases. There is no escalate case for the graph-completion dimension that the judge scores. I tuned the judge prompt against this same set. So the perfect separation (kappa 1.00) is real but weak evidence. [`backend/data/judge_golden_set.json`, `judge_calibration.json`]

5. **The judge is not deterministic.** Before the prompt fix it missed 3 cases on one run and 4 on the next. After the fix, three runs passed. Any prompt or model change means re-running calibration. [`../phase5-interview.md` addendum]

6. **The false-auto-send number is computed over all scored cases, not only auto-sent ones.** The code divides by every scored case, so it understates the risk among cases that actually get sent. Also the calibration file records `eval_case_count: 0`: no reviewer-corrected cases have entered the gate yet. [`backend/app/judge/calibration.py`, `judge_calibration.json`, `../phase6-interview.md`]

7. **Three of fifteen graph edge types never occur in the demo data.** `FOR_PROJECT`, `VARIANT_OF`, and `SUPERSEDES` are defined and coded but have zero edges. The dev graph has 10 node types and 12 edge types. [`/v1/graph/stats`, `backend/app/graph/constant.py`]

8. **Price prediction is weak by construction.** It takes the median list price of category peers. In the synthetic data, list prices are random per part, so the median is close to noise. The design point is that a prediction is always labeled and never mistaken for a lookup. [`../phase3-interview.md`]

9. **Dedupe has no sense of time, and the style fingerprint is recorded but not used to decide.** Only the SKU set decides duplicate, revision, or distinct. Its acceptance test checks the classifier against test data built from the same logic, so that check is somewhat circular. [`backend/app/dedupe/fingerprints.py`, `../phase2-interview.md`]

10. **Contract dates use a fixed constant.** `DATASET_AS_OF = 2024-09-01`, because the synthetic contracts span 2023 to 2027 and only 9 of 125 are active on the real current date. The judge also uses this constant, not each estimate's own as-of date. [`backend/app/estimate/constant.py`, `../phase5-interview.md`]

11. **Cost and latency were measured once, in a script, not in the product.** They are not stored per quote, not on the dashboard, and exclude the judge. The latency figures include the SDK waiting out rate-limit retries on a 30,000 tokens-per-minute organization limit. Prices come from third-party pages, not OpenAI's own (`docs/research/openai-pricing-for-live-run.md`). ADR-0003 also names an in-process `cachetools` cache. There is no such dependency or cache in the code. [`backend/pyproject.toml`, `grep` for cache use]

12. **Tracing has never touched a hosted service.** Langfuse is a no-op without keys. Tool spans record full results, which would send customer names and discounts to a hosted service once turned on. [`../phase6-interview.md`]

13. **Operational gaps, deferred on purpose.** No pipeline-trigger UI. No auth. Guardrail-blocked drafts are read-only in the UI. A failed graph sync after a correction needs a manual rebuild. A huge integer price can return a 500 instead of a 422. Eight minor review findings are deferred (for example, a 409 on resolve leaves stale buttons). [`../phase6-interview.md`, `../phase7-interview.md`]

14. **Two acceptance tests fail on a database that already holds the seeded demo.** They count absolute rows. I ran the suite on 2026-09-30: 745 pass, 2 fail on the dev database. On a clean database all 747 pass, per the Phase 7 doc. [`docs/new-machine-setup.md`]

---

## Part B. The 12 hardest questions

Each has a short spoken answer, then a pointer.

### 1. Why a graph and not just vector search?

"Because the mistakes I care about are relationship questions, not similarity questions. A discontinued part is replaced by another part, which may itself be replaced. The replacement requires an accessory. The customer's contract covers some categories and not others. Vector search returns text that reads relevant. It cannot intersect those facts across records. A graph walks them, and it returns the path, which is also the evidence a reviewer needs.

I want to be straight about the limit. On this small data, SQL with recursive queries could answer the three planted checks. My Phase 4 notes say Postgres would end up simulating a graph. I chose Neo4j in ADR-0002 for open-ended hops, community detection, and readable paths, and I only evaluated Neo4j. The published numbers I cite for graph over vector are external, and one of them is flagged by its own author as a worst case for vector. I have not measured graph versus vector on my own data. That is on my gap list."
Pointer: ADR-0002, `../phase4-interview.md`, `docs/research/graphrag-vs-vector-rag.md`.

### 2. Why a different vendor for the judge?

"So the judge does not share the agent's blind spots. If both are the same model, agreement can just mean the same mistake made twice. The source article names this failure. GPT-4o is the agent and Claude Haiku is the judge, and I accepted about five dollars of spend for it.

The caveat: I never ran a same-vendor judge on my golden set to compare. So the decision rests on reasoning, not my own measurement. And a different vendor did not fix calibration by itself. Haiku noticed risks but scored them too high until I added explicit prompt anchors."
Pointer: ADR-0004, `../phase5-interview.md`, story 4 in file 03.

### 3. How did you choose the threshold?

"I did not copy the article's 0.85. I hand-labeled 32 cases as trust or escalate. I took every distinct score the judge produced as a candidate threshold. For each, I computed Cohen's kappa between 'judge says trust at this cutoff' and my label. I picked the lowest threshold with kappa at least 0.6, because lower means more auto-trusted at the same agreement. If nothing clears the bar, the script writes nothing.

The result was 0.85 with kappa 1.00, which happens to match the article, and I say so as a coincidence. Two limits: the threshold depends on the prompt, so I re-calibrate after any prompt change. And 29 scored cases from a few templates is thin."
Pointer: `backend/app/judge/calibration.py`, `../phase5-interview.md`, `docs/research/llm-judge-calibration.md`.

### 4. What does false-auto-send mean, and why that metric?

"A false auto-send is a quote the system would send without a human that a human would have corrected. It is the expensive error, because it goes to a customer. A false escalation only wastes reviewer time. So the release gate caps false auto-sends at 5 percent and refuses to write a threshold above it. My first live run scored 10.3 percent, so the gate blocked the release, which is what it is for.

Where it falls short: my version divides by all scored cases, not just auto-sent ones, so it understates the rate among sent quotes. It is also computed on a small set."
Pointer: `backend/scripts/calibrate_judge.py`, `../phase6-interview.md`.

### 5. How does dedupe avoid over-merging?

"Four things. Blocking: only compare requests sharing a customer, site, or contract. Content: a duplicate needs an identical, non-empty SKU set. A revision needs a strict superset with at least 40 percent overlap, so one shared bolt does not link a big order. Default: anything else is distinct, so the failure direction is 'do not merge'. And a verdict is a row and a graph edge, not a delete, so a wrong merge is reversible.

The limits: the 40 percent floor is my choice and was not tuned on data. There is no time dimension, so a legitimate reorder of the same parts looks like a duplicate. And the test data was built from the same logic the classifier checks. When I ran it live with the real model in front of it, it got 4 of 10 pairs, but every miss was a missed match, and there were zero false merges. So the safe direction held. The cost was under-merging, caused by intake not resolving part numbers."
Pointer: `backend/app/dedupe/fingerprints.py`, `../phase2-interview.md`, `backend/data/live_run_report.json`, story 3.

### 6. What breaks at 100x volume?

"In the order I expect it to hurt:
- The agent run holds one database transaction across up to 12 model calls. Fine for a POC, wrong at volume.
- The queue is Postgres-backed. ADR-0003 says the ceiling is lower than Redis, and the honest scaling answer is a swap I have not benchmarked.
- The graph is a full rebuild from Postgres, and estimates are blocked while it is stale. With many corrections a day I would want incremental sync everywhere. Today only single-fact syncs are incremental.
- With more than one consolidation worker there is a narrow race on the fingerprint reads.
- Neo4j Community has one database per instance, which I worked around with namespaces.
- Judge cost grows linearly with volume, and I have no measured cost per quote yet.
I have not load-tested any of this, so these are predictions from the code, not measurements."
Pointer: ADR-0003, `../phase3-interview.md` (deliberately unfinished), `../phase6-interview.md` (not solved).

### 7. How would you evaluate retrieval?

"I have not done this yet, and I would say so. What I would build: a labeled set of 40 to 60 questions of the kinds the router handles, each with the expected SKUs or answer. Then measure precision@k and recall@k per route. Then run each question through the router, and also through each single route, to see whether routing beats always using one. I would report router accuracy separately: did it pick the right route. And I would put graph versus vector side by side on the multi-hop questions, with before and after numbers."
Pointer: file 06 (retrieval row), `backend/app/retrieval/router.py`.

### 8. What is the cost and latency per quote?

"I measured it once, in a script, on 2026-09-30. Extraction was about 2 seconds and a fifth of a cent per email. The agent run took a median of 11 seconds, 90th percentile 29, worst 40, and cost about 2.3 cents on average, worst about 6 cents. It averaged about 4.5 model calls and 7.8 thousand input tokens per run. So roughly 2.5 cents per quote, plus the judge, which I did not include. Three caveats. The seconds include the SDK waiting out rate limits, so they overstate a normal run. The prices come from third-party pages. And it is 40 runs, once. Structure: one extraction call, up to 12 agent turns, at most four submissions, and one judge call, or none if the guardrails already rejected the draft. Next I would store tokens and time per stage on each row and show median and 95th percentile on the dashboard."
Pointer: `backend/data/live_run_report.json`, `backend/scripts/live_run/meter.py`, `docs/research/openai-pricing-for-live-run.md`, file 06.

### 9. What would you do with real data?

"Start in shadow mode: run the system beside the reps and never send anything. Compare my draft to the rep's final quote. Every difference becomes a labeled case, so the golden set comes from real corrections instead of my hand labels. Then recalibrate the threshold on real labels, and report false-auto-send per dimension. I would replace the price prediction, because a median of random synthetic prices is meaningless on real data. I would add time to dedupe. I would redact tool results before sending traces to a hosted service. And I would add auth before anyone outside the team sees it."
Pointer: `../phase6-interview.md` (eval cases), file 06.

### 10. Why not fine-tune?

"The errors here are about facts that change and rules that must hold: which part is discontinued this month, which category a contract covers. A fine-tuned model bakes facts in and goes stale. Tools and a graph keep them live, and a correction updates one row. Guardrails give a guarantee where a tuned model gives a better probability. And I have no labeled real data, so there is nothing honest to tune on.

Where I would consider it: a stable, narrow step with lots of labeled examples, such as extraction, to cut cost and latency, or distilling the judge. I have not run any fine-tuning experiment, so this is a decision argument, not a result."
Pointer: file 06 (fine-tune row).

### 11. Did you write this yourself?

"I designed it, made the decisions, and verified the results. The implementation was done with AI coding assistants, in small test-first tasks, each reviewed by a separate fresh session. The review found real bugs that passing tests did not, like the customer-discount bypass and a queue that could not start. I can explain any part, and I keep the decisions and their reasons in ADRs and phase docs. The architecture comes from the article I started from and from what I know about this kind of system. The code in this repo is all new, and the eval layer is what I added to learn."
Pointer: `../phase1-interview.md` (review process), `../phase3-interview.md` (how it was built).

### 12. What is the weakest part, and what would you not trust?

"Intake. The live run showed it resolves the right parts on only 44 of 60 emails, because it ignores a part number typed in the email, and that made live duplicate detection 4 of 10. I found that by running the real model, not from my tests. Second, the judge's threshold, because it comes from 29 templated cases, and the judge has not scored the live drafts. Third, the graph-completion dimension, because the golden set has no case that stresses it. What I do trust more: the agent plus guardrails. Over 40 live runs, 30 were correct, 9 went to review with the right draft, 1 escalated because the customer was unknown, and none went out wrong on the checks I scored. That is one run of 40, so it is a first data point, not a claim. The right next step is fixing the resolver and re-running."
Pointer: Part A above (2, 2b, 2c), `backend/data/live_run_report.json`, file 06.
