# Phase 1 Interview Prep: Synthetic Data Generation

This file exists so you can walk into an interview and explain this phase of the project without re-reading code. Read the plain-English summary first, then use the questions to test yourself. Answers are written the way you'd actually say them out loud, not textbook definitions.

A new file like this gets created after every phase. This one covers Phase 1 only, plus anything from setup that a reasonable interviewer would expect you to know already.

---

## What Phase 1 actually is, in plain terms

There is no real customer data for this project. It doesn't exist yet. So before any AI agent, any database, or any dedupe logic can be built, something has to generate a fake but realistic dataset to build and test against: fake parts catalog, fake customers, fake contracts, and fake "customer emails" that each hide a specific tricky situation (a discontinued part, a missing required part, a discount that doesn't apply, a duplicate request, a follow-up revision, or a plain normal request).

Six small Python programs do this, each with one job:

1. **`config.py`** — one shared source of truth for "how much data to make" (650-800 parts, 125-150 customers, 60 test emails) and a fixed random seed, so the same run always produces the same output.
2. **`catalog_gen.py`** — builds the parts catalog. Some parts are discontinued and point at their replacement. Some parts require a second part to actually work.
3. **`customer_gen.py`** — builds customers, each with contacts, job sites, and a contract that covers only some part categories at a discount.
4. **`graph_export.py`** — converts the catalog and customers into "nodes and edges," the format needed later to load this into a graph database (Neo4j). Neo4j itself isn't installed yet, this is just preparing the data for when it is.
5. **`scenario_gen.py`** — the interesting one. It picks real facts from the already-generated catalog and customers (e.g. "this real part is discontinued and this real part replaces it"), then hands those facts to an AI chat platform with strict instructions to write a believable customer email around them, without ever stating what the "trick" is. A human pastes the prompt in, pastes the reply back, and the code checks the reply for quality (right shape, doesn't give away the answer, isn't empty).
6. **`validate.py`** — the checker. Confirms every reference in the data actually points to something real, confirms there are exactly 60 test emails covering all 6 situations evenly, and confirms regenerating everything with the same seed gives back the exact same data.

Everything was built test-first (write a failing test, then the smallest code to pass it), one small task at a time, and every task was reviewed by a second, independent pass before moving on — similar to how a real engineering team works with pull requests and code review, except the "reviewer" here was a fresh AI session with no memory of writing the code, specifically so it couldn't rubber-stamp its own work.

---

## Questions an interviewer might actually ask

### Why generate synthetic data instead of just using real examples?

Because there is no real dataset for this project — it's a proof of concept, not a live product with real customer history yet. Every later phase (deduping, the AI agent, the evaluation harness) needs *something* structurally realistic to run against: real-looking referential integrity, real-looking edge cases like discontinued parts, real-looking messy customer emails. Synthetic data lets you build and test all of that before a single real customer ever sends a request.

### What does "referential integrity" mean here, and why does it matter?

It means every reference in the data actually points to something that exists. If a part says "discontinued, replaced by SKU-0231," SKU-0231 had better actually exist in the catalog and not itself be discontinued. If a test email references customer CUST-0042, that customer had better actually be in the generated customer list. Without checking this, you could easily generate a dataset that looks fine at a glance but silently has dangling references — and any code built on top of it later (the agent, the dedupe logic) would fail in confusing ways that have nothing to do with the actual bug.

### Why use a fixed random seed? What does that actually buy you?

A seed is the starting number a random number generator uses. Same seed, same sequence of "random" numbers, every time, on every machine. That means running the whole generation pipeline twice produces byte-for-byte identical output. That matters because later phases write tests against this data — if the data changed every run, those tests would be flaky for reasons that have nothing to do with actual bugs. Determinism is what makes "regenerate and re-test" a meaningful, repeatable action instead of a coin flip.

### There are three separate seeds (seed, seed+1, seed+2) for catalog, customers, and scenarios — why not just reuse the same one everywhere?

Reusing the exact same seed across independent random number generators can create hidden correlation between their outputs — e.g. the catalog's shuffle order and the customer's shuffle order ending up suspiciously similar just because they started from the same internal state. Offsetting the seed per generator keeps each one independently seeded (so the correlation risk goes away) while the whole pipeline is still 100% reproducible from one single top-level seed value.

### What's a "discontinued/replaced_by" relationship, and why bother modeling it in fake data?

It's a real business pattern: a distributor stops selling part A and tells customers to order part B instead. Modeling it in the fake catalog means later phases (the AI agent, specifically) have a real, testable case to handle: "customer asked for a part that doesn't exist anymore — does the system correctly catch that and suggest the replacement, or does it just fail or silently order the wrong thing?" You can't test that behavior if your fake data never contains a discontinued part in the first place.

### Why does the scenario generator not just call an LLM directly from the Python code?

Two reasons. First, cost and control — this is a one-time data-generation step, not a live feature, so there's no need to wire up API keys and billing for something you run a handful of times. Second, and more important: it keeps a human in the loop to sanity-check the AI's output before it becomes "ground truth" test data. The code decides every fact ahead of time (which part, which customer, what the twist is) — the AI's only job is writing believable prose around already-decided facts. That separation means a bad or hallucinated AI reply can be rejected and regenerated without ever risking the AI inventing wrong facts that quietly become part of your test suite.

### What is a "label leak" and why is it a real problem here?

Each test email is supposed to secretly contain a specific tricky situation (say, "this is actually a duplicate of another request") — but the email text itself must never say that out loud, the same way a photo caption written by a human wouldn't include the answer to "is this a cat or a dog." If the generated email literally says "this is a duplicate," it stops being a meaningful test of whether the downstream dedupe logic can figure that out on its own — the answer's just sitting there in plain text. So there's a check that scans each generated email for exactly this kind of self-revealing language and rejects it if found, sending it back to be regenerated with different wording.

### Was that label-leak check foolproof? Walk me through what went wrong.

No, and it's worth knowing the story because it shows a real debugging arc. The first version checked for the situation's name as plain substrings (e.g. checking if "pair" appears anywhere in the text). That backfired two ways: it falsely flagged innocent words (the word "repair" contains "pair" as a substring, so a totally normal email about a repair job got wrongly rejected), and it also completely missed obvious real leaks that used only one of two expected words. The fix was to match on whole words only, plus a short list of single "red flag" words per situation type. But that fix introduced its own smaller gap: it matches on word boundaries, and an underscore character counts as "part of a word" to the matching engine, so if someone typed the literal internal code name straight into an email (like `duplicate_pair` as one glued-together word), it still slips through undetected. That gap was found, written down, and deliberately left unfixed rather than patched hastily in a rush — a good interview point about knowing when to stop and flag something instead of quietly guessing at another fix.

### Why does file encoding matter enough to be a real bug here?

Different operating systems assume different default text encodings when you open a file without specifying one. On this Windows setup, the default isn't UTF-8. Chat platforms typically reply in UTF-8, which can include curly quotes, accented letters, or other non-plain-ASCII characters. Reading that text without explicitly saying `encoding="utf-8"` either scrambles those characters into gibberish (mojibake) or, worse, crashes outright on the ones Windows genuinely can't map to its own default — and a single crash was severe enough to kill the entire batch-processing run, not just skip one bad file. Explicitly specifying the encoding removes the ambiguity entirely, and it's a good habit for any code that might run cross-platform.

### What's the difference between "referential integrity" and "business rule correctness," and why does that distinction matter for the validator?

Referential integrity just asks "does this reference point at something that exists, and does it belong where it claims to belong?" — pure existence and ownership checks, nothing about whether the situation makes logical sense. Business rule correctness goes further: "is this SKU that's supposed to be discontinued actually marked discontinued in the catalog?" or "is this category that's supposed to be uncovered by the contract actually uncovered?" Phase 1's validator deliberately only does the first kind. That's a real scoping decision, not an oversight — the deeper semantic checks were raised during review and explicitly set aside as future work, because conflating "does it exist" with "does it make business sense" makes a checker harder to reason about and debug when it fails.

### Why generate node/edge files for a graph database that isn't even installed yet?

Because the shape of the future graph (which entities become nodes, which relationships become edges) is a design decision that's much easier to get right on paper — sorry, in flat files — than to redo after real data is already loaded into a live database. Building the export logic now, and testing it against real generated data now, means that when Neo4j is eventually stood up, it's a loading step, not a redesign.

### Why did the plan add a "Customer -> Contract" edge that wasn't in the original design?

It came up during planning, not as an afterthought bug: the original graph schema listed "Contract covers Category" but never linked a Contract back to the Customer who owns it, which would have left every Contract node floating in the graph with no way to ask "which contracts does this customer have?" Catching that gap before writing any code, instead of after, is the whole point of writing a design spec and reviewing it before implementation starts.

### Explain "test-driven development" the way you actually practiced it here, not the textbook definition.

For every function: write a test that describes the behavior you want, run it and watch it fail (there's no code yet, so it should fail for an obvious reason like "function doesn't exist"), then write the smallest amount of code that makes that specific test pass, then run it again and confirm it's green. Repeat per function. The value isn't ceremony — it's that you get a working, previously-failing check for every single behavior before you can convince yourself it's done, instead of writing a pile of code and hoping it's right.

### Why have a separate AI "reviewer" check the AI "implementer's" work instead of just trusting the implementer's own self-review?

Because an implementer grading its own work has an obvious blind spot — anything it got wrong by misunderstanding the task, it'll also misunderstand when checking itself. A fresh reviewer with no memory of writing the code, looking only at the diff and the actual requirements, catches a different class of mistake. This isn't unique to AI — it's the same reason human engineering teams don't let people merge their own unreviewed pull requests. In this project it caught several real bugs the implementer's own self-review missed, including one where a fix for one problem (word-boundary matching) accidentally reopened a different, older problem.

### What's a git worktree, and why use one for this work instead of just working directly on the main branch?

A worktree is a separate folder that's still part of the same git repository, checked out on its own branch, so you can work on something in isolation without touching your main branch's files at all. It matters here because building 9 tasks' worth of new code is not something you want happening directly on `master` while it's in progress — if something goes wrong halfway through, `master` is completely unaffected, and you only merge once everything is finished, tested, and reviewed.

### Three commits ended up with "Co-Authored-By: Claude" attribution lines, and you rewrote git history to remove them. Why does that matter, and was it safe to do?

This project's own rules explicitly say commits must never mention AI authorship — a deliberate choice, not a formatting nitpick. A few AI implementer sessions added that trailer anyway, out of habit from a different default behavior. Rewriting history to strip it was safe specifically because this branch existed only locally, had never been pushed anywhere, and had no other collaborators depending on those exact commit hashes — the three conditions that make a history rewrite low-risk instead of dangerous. Rewriting published history that other people have already pulled is a very different, much riskier operation, and that distinction is worth being able to explain clearly.

### What would you do differently, or what's still incomplete after Phase 1?

A few honest things: the label-leak detector's underscore/word-boundary gap is a known, flagged, unfixed issue. There's no automated way yet to run the "human pastes prompt into a chat platform" step — it's still a manual loop by design, but a small helper CLI for it would make the workflow smoother. And the deeper business-rule checks in the validator (is a discontinued SKU actually discontinued, is an uncovered category actually uncovered) were scoped out deliberately and would be a reasonable next addition if this phase were revisited.

---

## Quick-reference facts (in case you get asked something specific and blank on numbers)

- Catalog size: 500-800 SKUs (default 650). Customers: 100-150 (default 125). Scenario test emails: exactly 60, 10 per situation type, across 6 types.
- 6 scenario types: discontinued part swap, missing required part, discount category mismatch, duplicate request, revised request, plain normal request.
- Graph schema: 4 node types (SKU, Customer, Contract, Category), 5 edge types (REPLACED_BY, REQUIRES, BELONGS_TO, HAS_CONTRACT, COVERS).
- 76 automated tests, all passing, covering every generator and the validator.
- No real API calls happen in this phase's code — the only place an AI model is involved is a human manually pasting a prepared prompt into a chat platform and pasting the reply back in.
