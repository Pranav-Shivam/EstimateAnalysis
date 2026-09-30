# Phase 7 Interview Prep: The Reviewer UI and the Visible Feedback Loop

This file exists so you can walk into an interview and explain this phase without re-reading code. Read the plain-English summary first, then use the questions to test yourself. Answers are written the way you'd actually say them out loud.

This one covers Phase 7 (the read-only backend endpoints, the seed script, and the React review app).

---

## What Phase 7 actually is, in plain terms

Phase 6 made a reviewer's correction turn into a permanent fact. Nobody could see it happen, though: there was no screen. Phase 7 adds one, and proves the loop visibly. A reviewer opens a queue, sees one flagged fact with the evidence behind it, corrects it, and later sees the same quote re-estimated cleanly next to the original flagged estimate.

Three pieces:

1. **Read-only backend endpoints.** The list of review items gains a status filter. New endpoints list quotes, return a quote with every estimate, judge verdict, dedupe verdict and review item, and report three rates. The only write the UI does is the existing resolve route from Phase 6.
2. **A seed script.** There is no API key and no production data, so the demo data has to come from somewhere. The script runs the real intake, dedupe, estimate and judge code on Phase 1 scenarios, with only the three model clients replaced by scripted stand-ins.
3. **The app.** Vite, React, TypeScript, Tailwind 4 and Ant Design 6. Four screens: the review queue, a quote detail page, an all-quotes list, and a dashboard.

Proof it works: I ran it. With the dev database seeded, the queue showed four open flags. I corrected the price, graph and contract flags in a real browser, ran the replay, and each of those quotes then showed a clean latest estimate with an "auto-sent" notice, next to the earlier flagged estimate marked as applied. The dashboard showed the correction rate move from "no data yet" to 100% (3 of 3).

---

## Questions an interviewer might actually ask

### What does Phase 7 prove that the earlier phases did not?

That the memory-that-compounds claim is visible to a person, not only to a test. In Phase 6 an acceptance test proved a later identical scenario skips review. Here a reviewer does the correction by hand and sees the second estimate appear clean. It also proves the loop through the real interface, including the failure paths: a bad price is blocked in the browser, and a backend rejection is shown as the backend wrote it.

### Why did the backend stay read-only apart from one existing write?

The UI needs to see data, not create new kinds of it. Every new endpoint is a GET assembled from tables earlier phases already fill. The one write, resolving a review item, already had validation, locking and the consolidation queue behind it. A second write path would have meant a second set of rules to keep in sync. It also kept the phase from touching the paid-API pipeline: there is deliberately no button that triggers intake or the agent.

### Why does the seed script drive the real services instead of inserting fixture rows?

Fixture rows drift. Hand-written evidence would not match the shape the judge really stores, and a hand-inserted flagged quote cannot be re-run after a correction. By running intake, dedupe, the estimate agent's guardrails and graph check, and the judge on real scenarios, the stored evidence and review items are produced by production code. Only the model calls are replaced. So when the replay runs, the "clean second estimate" comes from the same code path a live system would use.

### What does the scripted judge prove, and what does it not?

It proves the plumbing: a correction reaches the reference data and graph, and the next estimate's evidence changes. The first review of this phase caught that my replay judge could not see graph or contract gaps at all, so two of the three "it worked" proofs would have passed even if consolidation had written nothing. The fix makes the replay judge watch exactly what each resolved flag was about, and a test that stubs consolidation out now expects the quote to stay flagged. What it still does not prove is a real model's judgment. The judge, the extraction and the quantities (all 1) are scripted, and the real calibrated run is still blocked on a missing API key.

### How does the UI avoid inventing evidence?

It only shows what the judge stored at judging time: the price source, the peer range, the contract coverage, the required parts. That is an audit snapshot, not a live graph query. That is what a reviewer needs to check the one flagged fact, and it means the screen can never disagree with what the judge actually saw. The cost is that it does not show a live graph view, which is listed as a gap.

### Why do Tailwind and Ant Design need cascade layers?

Both style the same elements. Tailwind ships a reset that would override antd's component styles, and antd's CSS-in-JS would fight Tailwind utilities. CSS cascade layers fix the order. The app wraps antd in a style provider that emits into a layer, and the stylesheet declares the layer order before importing Tailwind, so the reset sits below antd and Tailwind utilities sit above it. I checked this against antd's own docs, and then looked at the rendered page to confirm nothing was clobbered.

### Why generate the TypeScript types from the backend's OpenAPI schema?

So a backend change that breaks the UI fails the type check instead of the browser. There is a script that regenerates the types and another that fails if the committed file is stale. A small honest detail: the type generator crashes under TypeScript 7, which no longer ships the compiler API it needs, so the project is pinned to TypeScript 5.9.3 until the tool catches up.

### What did the review of this phase catch?

Four Important issues, all real. The replay judge blind spot above. A seed that could plant its gaps twice and leave a partial state it then refused to fix, so it now refuses to plant twice and prints how to recover. A planted gap that could silently change another demo case if the dataset were regenerated, so the gap scenarios now reserve their SKUs first. And a correction form that offered every line of an estimate, which would let a reviewer overwrite a real list price by picking the wrong line, so it now offers only the lines the judge doubted. The lesson I would give: a green test suite told me nothing about any of these, because the tests were written against the same assumptions.

### What did building it against the real dataset teach you?

The plan assumed the dataset's unpriced SKUs appear in scenarios. They appear in none. So the price-gap demo plants the gap by removing one SKU's list price, the same way the graph gap is planted by deleting one requirement, and the reviewer's correction restores it. Failing loudly when a role cannot be filled, instead of quietly running a demo with a story missing, is what surfaced this.

### What is still not solved?

Say these plainly. There is no UI to trigger the pipeline, because that needs paid API keys. Guardrail-blocked drafts are shown read-only because the backend rejects resolving them. There is no auth. Eight minor review findings are deferred, for example a 409 on resolve leaves the Approve and Correct buttons showing, and the quotes list loads full rows with no pagination. And the seed script refuses to run twice on the same data; recovery is a reload plus deleting the seeded rows.

---

## Quick-reference facts

- New endpoints: `GET /v1/review?status=open|resolved|all`, `GET /v1/quotes`, `GET /v1/quotes/{id}`, `GET /v1/metrics`. CORS allows `http://localhost:7050` from a setting.
- Rates: auto-send = trusted verdicts / all verdicts; correction = corrected items / resolved items; duplicate = requests with a `DUPLICATE_OF` verdict / requests with any dedupe verdict. A rate is null, never 0, when its denominator is 0, and the dashboard says "no data yet".
- Seed: `scripts/seed_demo.py` (dry run by default, `--yes` writes, `--replay` re-runs resolved quotes). Roles: clean x2, discontinued, price gap, graph gap, contract gap, duplicate pair, revision pair, blocked (guardrail).
- Frontend: React 19.3, Vite 8, Tailwind 4.3, antd 6.6, TanStack Query 5, react-router 8, Vitest 5; TypeScript pinned to 5.9.3.
- Tests at the end of the phase (after the graph explorer): 747 backend on a fresh database, 81 frontend; 689 backend before the phase.
- Observed in a browser: queue with 4 flags, price detail with evidence, client-side price validation, guardrail read-only, three corrections, replay, two-estimate quote detail, dashboard rates.
- Known gaps: no pipeline-trigger UI, guardrail items read-only, evidence is a stored snapshot, scripted judge, no auth, deferred minors.

## Addendum: the graph explorer, dashboard charts and moving to another machine

### The first version showed graph evidence as text. Why was that wrong, and how did you find out?

The phase's own spec had a line, "evidence is a stored snapshot, not a live graph view", which quietly dropped the thing that makes a knowledge graph worth building: being able to see and walk the relationships. I found out when the owner ran the app and asked where the graph was. The honest answer was that I had scoped it out while planning and not flagged it as a loss. The lesson I would say in an interview: a "non-goal" in a spec is a decision the user has to be able to see, so I now call out any feature the roadmap promised that a spec defers.

### How is the graph explorer organised, and why not just draw everything?

Levels. The graph has 1712 nodes and 2506 edges, which drawn at once is an unreadable hairball. So the page opens on the schema map (one circle per node type, one arrow per relationship type, with counts), a click on a type loads its 60 most connected nodes, and a click on any node adds its neighbors one hop at a time. A separate button draws everything for people who want the whole picture, with names hidden at that size. Neighbor lists are capped at 60 and the response carries a `truncated` flag, because a category hub has hundreds of members and silently cutting would mislead.

### You reported "too slow to load". What was actually slow?

Not what it looked like. The API answered in 14 ms and the page itself rendered in about 1.4 seconds. I timed the layout on the real full graph in Node: Cytoscape's built-in `cose` layout took 20.5 seconds for 1712 nodes, freezing the tab. I tried fCoSE, which did the same graph in 0.2 seconds at draft quality (5 seconds at full quality), and switched to it. The general point: measure each layer separately before optimizing, and time the suspected culprit on real data instead of guessing.

### Two more things a screenshot caught that no test could

I could not click in headless Chrome, but I could load pages and look. A small graph was fitted to the box and zoomed until its labels filled the screen, so I capped the zoom. Every click re-randomised the layout, which would scramble the picture as you hop, so expansion now keeps existing positions. The dashboard's edge chart drew only every other label because the axis skipped what it could not fit, and the bars were caught mid-animation. All of that passed 81 tests, because tests check behaviour, not appearance.

### How would this run on another machine without paying the LLM providers again?

Everything that cost an LLM call is exported to one file, `data/llm_snapshot.json.gz` (650 SKU embeddings and 56 community summaries, 4 MB). A restore script loads it with no API call. It refuses to load if any embedded SKU is missing from the database, because embeddings attached to the wrong products would make vector search quietly wrong. The graph is a rebuildable projection of Postgres, the demo quotes come from scripted stand-ins, and the judge calibration is a small JSON file, so nothing else costs money. I proved it on a fresh database with deliberately invalid API keys: 650 embeddings and 56 summaries restored, the embedding script reported 0 SKUs needing work, and vector search returned sensible neighbors. The steps are in `docs/new-machine-setup.md`. The community summaries are keyed by a hash of each community's SKUs and Leiden runs with a fixed seed, which is why restored summaries still match a rebuilt graph.

### What did the test suite say on the dev database, and what does it tell you?

Two acceptance tests fail on the seeded dev database and pass on a fresh one, because they count absolute rows and the seed adds 11 quotes. Same class of bug as Phase 2's shared-database lesson. It is a known minor, not a regression, and I confirmed it by running the full suite (747 passing) against a clean database.

### Facts for this addendum

- Routes added: `/v1/graph/search`, `/v1/graph/nodes/{id}/neighbors`, `/v1/graph/nodes?label=`, `/v1/graph/schema`, `/v1/graph/full`, `/v1/graph/stats`; `/v1/metrics` gained `flags_by_dimension`.
- The dev graph has 10 node types and 12 of the 15 edge types; `FOR_PROJECT`, `VARIANT_OF` and `SUPERSEDES` never occur in the demo data.
- Quote nodes have no name property, so the explorer labels them with their UUID.
- Layout timings on 1712 nodes: `cose` 20.5 s (300 iterations) and 44 s (1000), fCoSE 0.2 s draft and 5.2 s default.
