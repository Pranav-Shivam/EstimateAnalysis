# 06. Gaps and Next Builds

An honest map of this project against eight capability areas an applied AI engineering role covers. Each is marked **Shown**, **Partly**, or **Not shown**, with the file or doc that proves it. For every Partly and Not shown, there is the smallest build that would close it, with an effort estimate.

Only one build has been done since this map was first written: the live agent run (areas 2 and 6). Everything else here is only listed. Effort estimates are my own rough guesses for one person, and they exclude live-API spend, which I would keep under a few dollars each.

## Summary

| Area | Status | One-line reason |
|---|---|---|
| Eval engineering | Shown (small scale) | Judge, golden set, kappa, sweep, and release gate all exist and ran live. The set is small and templated. |
| Agent and loop engineering (LangGraph) | Shown (small scale) | State machine, limits, and fail-closed behavior are built and tested, and ran live once over 40 emails. One run, no variance data. |
| Graph and retrieval engineering | Partly | Graph and router are built. Retrieval quality was never measured. |
| Context and memory | Partly | Graph and correction memory work. Skills, customer facts, and episodic recall are not built. |
| Observability and tracing | Partly | Spans are coded and tested with fakes. Never used against a real Langfuse. |
| Latency and cost engineering | Partly | Measured once in a script (tokens, seconds, dollars per stage). Not stored per quote, not on the dashboard, judge excluded. No cache. |
| Prompt engineering and versioning | Partly | Prompts changed with evidence. No version is stored with outputs. |
| Fine-tune versus RAG versus prompt | Partly (decision level only) | I have reasoned answers. I ran no comparison. |

---

## 1. Eval engineering: Shown (small scale)

**What is shown**
- LLM judge from a different vendor, forced tool call, three dimensions, min rollup: `backend/app/judge/service.py`, `backend/core/llm/anthropic_judge_client.py`, ADR-0004.
- Hand-labeled golden set, 32 cases (15 trust, 17 escalate): `backend/data/judge_golden_set.json`.
- Agreement measured by Cohen's kappa, threshold sweep over every observed score, lowest passing threshold chosen: `backend/app/judge/calibration.py`.
- False-auto-send release gate with a 5 percent ceiling: `backend/scripts/calibrate_judge.py`, `backend/app/judge/constant.py`.
- A real run that failed the gate (10.3 percent), then passed after prompt anchors: `../phase5-interview.md` addendum, `backend/data/judge_calibration.json`.
- Reviewer corrections stored as eval cases with full evidence: `backend/app/judge/models.py` (`EvalCaseRow`), `../phase6-interview.md`.

**What is missing**
- A held-out split. I tuned the prompt against the same 32 cases.
- A run-to-run variance report. I observed variance (3 misses, then 4) but did not record it as a metric.
- Any reviewer-corrected case in the gate: `eval_case_count` is 0.
- A same-vendor judge comparison, which would give ADR-0004 evidence.

**Smallest build.** Add a script mode that scores the golden set N times (for example 5), reports per-case score spread and worst-run false-auto-send, and splits cases into tune and hold-out sets. Add a same-vendor judge run for comparison. Effort: about 1 day, live spend a few dollars.

---

## 2. Agent and loop engineering with LangGraph: Shown (small scale)

**What is shown**
- State machine with agent, tools, and guardrails nodes and conditional edges: `backend/app/estimate/graph.py`.
- Retry and step limits (3 retries, 12 turns, recursion limit 100) and why each exists: `backend/app/estimate/constant.py`, `../phase3-interview.md`.
- Fail-closed exits: stale or unreachable graph, unreplaceable SKU, exhausted retries all end as `needs_review`.
- Tool-argument validation so a bad argument cannot abort the database transaction: `backend/app/estimate/tools.py`.
- A scripted agent driving the loop for tests: `backend/tests/app/estimate/fakes.py`, `backend/tests/test_phase4_acceptance.py`.

- A live run over 40 emails (10 each of discontinued swap, missing required part, wrong-category discount, clean) with the real GPT-4o agent, scored against the answer key: 30 correct, 9 sent to review with the right draft, 1 escalated (unknown customer), 0 wrong drafts marked ready. One run, $1.04 by my meter. Script: `backend/scripts/run_live_estimates.py`, tests: `backend/tests/scripts/test_live_run.py`, results: `backend/data/live_run_report.json`. The run happens in one transaction that is rolled back, so the dev database is untouched.

**What is missing**
- Repeat runs. Intake results moved between my three runs (parts resolved 42, 43, and 44 of 60), so agent results likely move too, and I have no spread.
- Scoring beyond parts and discounts: quantities are not checked.
- The judge has not scored those live drafts, so live false-auto-send is unmeasured.
- No LangGraph checkpointing or human-interrupt use. The human step happens after the run, in the review queue.
- The agent run holds one database transaction across up to 12 model calls (`../phase3-interview.md`).
- Intake in front of the agent is weak: the resolver ignores a part number typed in the email (44 of 60 parts resolved, 4 of 10 duplicate pairs found). Fixing it is the highest-value next change.

**Smallest builds.**
1. Fix the resolver to read a part number from the email text, then re-run the script and report before and after. Effort: about half a day, a dollar of spend.
2. Run the script 3 times and report the spread per scenario type, and add a quantity check. Effort: about half a day, about $3 of spend.
3. Score the live drafts with the judge and report live false-auto-send. Effort: about half a day.

---

## 3. Graph and retrieval engineering: Partly

**What is shown**
- Full schema in Neo4j, rebuilt from Postgres, namespaced, freshness-checked: `backend/app/graph/`, ADR-0002, `../phase4-interview.md`.
- Leiden communities with a fixed seed, local and global modes, cached LLM summaries: `backend/app/graph/service.py`, `backend/app/retrieval/summarizer.py`.
- Deterministic router across SQL, graph, and vector, with a table-driven test of its precedence: `backend/app/retrieval/router.py`.
- Graph-backed guardrails that block a left-in discontinued SKU or a missing required part: `backend/app/estimate/guardrails.py`, `backend/tests/test_phase4_acceptance.py` (30 planted cases).
- Graph explorer UI: `frontend/src/pages/GraphPage.tsx`.

**What is missing**
- Retrieval quality was never measured: no precision, no recall, no router accuracy.
- No graph-versus-vector comparison on my own data. The published numbers in `README.md` are external.
- The vector arm only searches SKU name, category, and family text (`backend/app/retrieval/vector.py`).

**Smallest build.** A retrieval check: 40 to 60 labeled questions, each with expected SKUs. Report router accuracy (right route chosen), then precision@5 and recall@5 per route, then the same questions forced through vector only, with before and after numbers. Effort: about 1 to 1.5 days, no paid calls beyond query embeddings.

---

## 4. Context and memory: Partly

**What is shown**
- Knowledge graph memory and its rebuild discipline: `backend/app/graph/`.
- Correction memory that compounds: a reviewer's fix becomes a list price, required part, or contract coverage, plus a graph write: `backend/app/consolidation/service.py`, `backend/tests/test_phase6_acceptance.py`.
- Episodic history stored in Postgres: requests, estimates, verdicts, review items, eval cases.
- Semantic memory of SKUs by embedding: `backend/app/retrieval/vector.py`.

**What is missing**
- Procedural memory as skill files. The rules live in a system prompt and guardrail code (`backend/app/estimate/prompts.py`).
- Per-customer facts retrieved by vector search.
- Episodic recall into the agent's context, such as "what did we quote this customer last time".
- Context management. The message list grows over up to 12 turns with no trimming or summarization, and I have not measured how large it gets.

**Smallest build.** One agent tool, `recent_quotes_for_customer`, that returns a customer's last few estimates from Postgres, plus a scripted-agent test showing it changes a draft. Then record prompt token counts per turn to see whether context growth matters. Effort: about 1 to 2 days.

---

## 5. Observability and tracing: Partly

**What is shown**
- Langfuse spans around the estimate run, each tool call, each graph-integrity check, each dedupe verdict: `backend/core/tracing/langfuse_client.py`, `backend/app/estimate/graph.py`, `backend/app/dedupe/service.py`.
- A true no-op with no keys, and never raises into the agent loop: `backend/tests/core/test_langfuse_client.py`.
- Product metrics computed from Postgres, with null instead of zero when unmeasured: `backend/app/metrics/`.
- A dashboard that shows them: `frontend/src/pages/DashboardPage.tsx`.

**What is missing**
- It has never been pointed at a real Langfuse instance, so I have not seen a real trace.
- No token counts, no cost, no `estimate_id` tag.
- Tool spans record full results, not arguments plus a summary, which matters once data goes to a hosted service (`../phase6-interview.md`).

**Smallest build.** Run a self-hosted Langfuse locally, point the app at it, run one seeded estimate, and screenshot the resulting trace. Add an `estimate_id` tag and redact tool results to a summary. Effort: about half a day.

---

## 6. Latency and cost engineering: Partly

**What is shown**
- Cost gates for the paid batch jobs: both `embed_skus.py` and `summarize_communities.py` are dry runs by default and print a token estimate before `--yes`: `backend/app/retrieval/vector.py`, `backend/app/retrieval/summarizer.py`.
- A zero-cost fast path: a `needs_review` draft skips the judge model: `backend/app/judge/service.py`.
- Summaries cached by content hash, and the restore snapshot so paid output is not paid twice: `backend/data/llm_snapshot.json.gz`.

- Measured once: per stage, from the live run. Extraction about 2 seconds and 0.2 cents per email. Agent run median 11 seconds (90th percentile 29, worst 40), about 2.3 cents average (worst about 6 cents), about 4.5 model calls and 7.8 thousand input tokens per run. Source: `backend/data/live_run_report.json`, meter in `backend/scripts/live_run/meter.py`. The seconds include the SDK waiting out a 30,000 tokens-per-minute rate limit, so they overstate a normal run.

**What is missing**
- Anything in the product. The numbers live in a script report, not on estimate rows, traces, or the dashboard.
- The judge's cost and latency (it did not run on the live drafts).
- Prices are from third-party pages, not OpenAI's own (`docs/research/openai-pricing-for-live-run.md`).
- The in-process cache ADR-0003 names. There is no cache in the code.
- Any load test, and only 40 runs at one point in time.

**Smallest build.** Capture input and output tokens and wall time per stage inside the app, using the same meter idea, and store them on the estimate and verdict rows. Add a dashboard panel with median and 95th percentile latency and cost per quote. Effort: about 1 day.

---

## 7. Prompt engineering and versioning: Partly

**What is shown**
- Three prompts with a clear job each: agent (`backend/app/estimate/prompts.py`), judge (`backend/app/judge/prompts.py`), community summary (`backend/app/retrieval/summarizer.py`).
- A prompt change driven by evidence and re-verified: the judge anchors, with calibration re-run twice. `../phase5-interview.md` addendum.
- Forced tool-call output for the judge instead of free text.

**What is missing**
- No version or hash stored with a verdict or estimate. A verdict row stores the model name but not the prompt (`backend/app/judge/models.py`), so I cannot tell which prompt produced an old score.
- Nothing enforces "re-calibrate after a prompt change". I rely on remembering it.
- No prompt regression test for the agent prompt beyond a unit test of its content.

**Smallest build.** Hash each prompt at import time, store the hash on estimate and verdict rows, and write the judge prompt hash into `judge_calibration.json`. At startup, warn or refuse auto-send if the running hash differs from the calibrated one. Effort: about half a day.

---

## 8. Fine-tune versus RAG versus prompt: Partly (decision level only)

**What is shown**
- A reasoned position, in file 04, question 10: facts that change and rules that must hold belong in tools, a graph, and code, not in weights.
- The same style of decision recorded in ADRs: vendor choice for the judge (ADR-0004), store choice (ADR-0001), queue choice (ADR-0003), each with rejected alternatives.

**What is missing**
- Any experiment. I ran no fine-tune, no few-shot comparison, and no prompt-only versus retrieval-augmented comparison on the same task.
- An ADR for this decision.

**Smallest build.** Pick one narrow step, intake extraction. Score three variants on the 60 emails against ground truth: the current prompt, the prompt with three few-shot examples, and (optionally) a small fine-tuned model. Report accuracy, cost, and latency in a table, and record the outcome as ADR-0005. Effort: about 1 to 2 days for prompt and few-shot; a fine-tune adds more and needs more labeled data than I have honestly generated.

---

## Order I would build them in

1. Fix the intake resolver for typed part numbers and re-run the live script (area 2). It is the biggest measured weakness and the cheapest fix.
2. Repeat runs for spread, score the live drafts with the judge (areas 2 and 1).
3. Cost and latency per quote in the product (area 6).
4. Retrieval precision and recall check (area 3), the most direct answer to "how do you evaluate retrieval".
5. Prompt hash and calibration binding (area 7), the cheapest and prevents a real failure.
6. Local Langfuse trace (area 5).
7. Judge variance and hold-out (area 1).
8. Episodic recall tool (area 4).
9. Extraction comparison ADR (area 8).
