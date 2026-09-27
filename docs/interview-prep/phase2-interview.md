# Phase 2 Interview Prep: Intake and Dedupe

This file exists so you can walk into an interview and explain this phase without re-reading code. Read the plain-English summary first, then use the questions to test yourself. Answers are written the way you'd actually say them out loud.

This one covers Phase 2 (intake and dedupe) plus a few things from Phase 1 that a reasonable interviewer would expect you to still remember.

---

## What Phase 2 actually is, in plain terms

Phase 1 built fake data. Phase 2 is where the system first does something with it: turn a raw customer email into structured data (intake), and figure out whether that request is brand new, a duplicate of something already submitted, or a follow-up revision of an earlier request (dedupe).

This is also the first phase with a real running application, not just standalone scripts. Five new pieces:

1. **Postgres**, running in Docker, holding both the reference data (SKUs, customers, contracts) copied in from Phase 1's files, and the app's own tables (`quote_requests`, `dedupe_verdicts`).
2. **Intake**: one call to OpenAI's structured-output API turns an email's raw text into a typed object (customer name, line items, quantities) — but the model only sees words on a page, so it extracts *names as written*, not real IDs.
3. **Entity resolution**: matches those extracted names back to real customer/SKU records already in the database. Exact match first; if that fails, a fuzzy "close enough" match; if neither gives exactly one confident answer, it stays unresolved rather than guessing.
4. **Dedupe**: for a new request, find other requests that plausibly belong to the same customer (same customer, same site, or same contract), then compare what was actually asked for. Identical parts list = duplicate. Same parts plus one more = revision. Anything else = distinct.
5. A FastAPI layer exposing intake and dedupe as two HTTP endpoints, following this project's fixed route-to-service-to-repo layering.

The proof that it works: Phase 1 built 60 fake emails with a known right answer baked in (5 pairs that are genuine duplicates, 5 pairs that are genuine revisions, the rest distinct). Phase 2's last task feeds all 60 through the real classifier and checks every single verdict against that known answer key. It passes.

---

## Questions an interviewer might actually ask

### Why does intake need a whole entity-resolution step? Why not just have the LLM return the real database IDs directly?

Because the LLM never sees the database. It only sees the words in an email. A customer signs off as "Anil" or writes "Chrome Sprayer" instead of the SKU's full catalog name — the model can only report what's actually on the page, and inventing a plausible-looking ID it never actually saw would be exactly the kind of hallucination this system is built to avoid. So extraction and resolution are two separate, honest steps: extraction says "here's the text I found," resolution says "here's what that text most likely refers to in our real records" — and if resolution can't be confident, it says so instead of guessing.

### Walk me through what happens when an email doesn't clearly name the customer.

This came up for real: one of Phase 1's fake emails is signed only "-Anil," never stating a company name at all. The first version of the extraction schema had `customer_name_as_written` as a required field, which meant OpenAI's structured-output mode was forced to invent something just to satisfy the schema, directly undercutting the instruction to never invent facts. The fix was to make that field nullable. Then entity resolution has to explicitly handle "there was no name to resolve" as a distinct case from "there was a name but it didn't match anything" — both end up with `customer_id = None`, but for different reasons, and the code has to not crash on the first one.

### Explain the "two ambiguous candidates" case in entity resolution. Why not just pick the closer match?

Because closer isn't the same as certain. If an email says "Zenith" and there happen to be two real customers named "Zenith Contractors" and "Zenith Plumbing," a similarity score might rank one slightly above the other, but that's not evidence the model actually meant that one — it's evidence the input was genuinely ambiguous. The design rule here, and the same rule the whole project follows elsewhere, is: an unresolved guess is safer than a resolved wrong guess. So zero matches and multiple qualifying matches are treated the same way — both resolve to "unknown," never to a coin flip.

### What's "blocking" in the dedupe classifier, and why do it before comparing content?

Blocking is a cheap first filter: only compare a new request against requests that share the same customer, the same site, or the same contract. Without it, you'd be comparing every new request against every other request ever submitted, which gets expensive fast and also just doesn't make sense — two completely unrelated customers ordering the same two-dollar washer isn't a duplicate, it's a coincidence. Blocking narrows the field to "plausibly related" before any real comparison work happens.

### Once you have two blocked candidates, how does the classifier actually decide duplicate vs. revision vs. distinct?

It looks at the set of SKUs each request asked for. If the two sets are exactly identical, that's a duplicate — same job, asked for twice. If one set is a strict superset of the other (everything in the smaller one, plus at least one more item) and they still overlap enough to be clearly related, that's a revision — the customer added something to an earlier ask. Anything else is distinct. This maps directly onto how Phase 1's fake duplicate and revision pairs were actually constructed, so it's not an arbitrary rule invented after the fact — it's the same logic the test data was generated from, checked in reverse.

### Why is there a floor on the revision check (has to share at least 40% of items), instead of any superset counting?

Because otherwise a request for one bolt would count as a "revision" of a completely unrelated order for fifty different items, just because that one bolt happens to also appear in the bigger order. The floor exists so a superset relationship only counts as a revision when the two requests are still substantially the same job, not when they merely overlap by coincidence on a shared, common part.

### What real bug did the empty-set case expose, and why does it matter?

If a request's SKUs never resolved to anything (extraction failed, or entity resolution came up empty), its SKU set is empty. Two different unresolved requests would both have empty sets, and a naive "how much do these two sets overlap" calculation can accidentally treat two empty sets as "100% identical" — which would wrongly flag them as duplicates of each other, for no reason connected to what was actually asked for. The fix is explicit: an empty set never counts as identical to another empty set, and never counts as a meaningful subset of anything. Nothing about "having nothing to compare" should ever look like "matching perfectly."

### Tell me about a real SQLAlchemy bug you hit, not a hypothetical one.

The ORM models for customers, sites, and contracts originally had only foreign key *columns* linking them (a site row stores its customer's ID as a plain string), with no `relationship()` declared between the Python classes. That looked sufficient on paper — the actual database enforces the foreign key regardless. But when a customer and its site were both newly created and inserted together in one batch, the ORM tried to insert the site before the customer existed yet, and the database rejected it. It turns out SQLAlchemy's insert-ordering logic, which decides "customer row goes in before site row" when you commit several new objects at once, is driven by declared `relationship()` links between the Python classes, not by the raw foreign key columns underneath them. Removing the relationships (because a reviewer flagged them as unrequested extra code) actually broke real behavior; the empirical test failure was the proof, and put them back. The lesson: a foreign key column and an ORM relationship look similar but do two different jobs, and only one of them tells the ORM what order to insert things in.

### What happened with the Postgres port, and why does it matter beyond "it was annoying"?

Mid-build, the project's own Postgres container was silently failing to start (a version-specific volume-mount change in the Postgres 18 Docker image), and — separately — the developer's machine already had an unrelated project's Postgres instance listening on the exact same default port. While the real container was down, a migration and some tests connected to *that other* Postgres instead, without any error, because nothing about a successful TCP connection tells you which actual database answered. It created a stray, harmless-but-real database on someone else's server. The fix wasn't just "start the container correctly" — it was moving this project's Postgres to a non-default port entirely, so the two can never again be silently confused for each other, regardless of which one happens to be running at any given moment.

### What's the "shared test database" bug pattern that showed up more than once?

A few early tests asserted things like "there is exactly one row in this table" or "the table is empty." That's true right up until a loader script permanently seeds hundreds of real rows into that same database — which is exactly what this phase's own data-loading step does, on purpose, as its final step. After that, "exactly one row" and "empty" are never true again, for reasons that have nothing to do with whether the code being tested is actually correct. The fix, applied every time this pattern showed up, was the same: stop asserting a global count, and instead check specifically for the rows a given test itself created. It's a good general lesson about testing against a shared, persistent resource instead of a disposable, empty one.

### Walk me through the most serious bug the final review caught, and why none of the 120 passing tests had caught it already.

The route that's supposed to call OpenAI never actually passed the real API key to the OpenAI client — it constructed the client with no key at all, which only works if the key happens to already be sitting in an environment variable, and this project deliberately loads its key from a `.env` file into a settings object instead, which is a different thing. Every single test that exercised that code path replaced the real OpenAI client with a fake one before the bug could ever run, which is exactly the right thing for a unit test to do, and exactly why it couldn't catch this: the bug only exists on the one code path no test was allowed to touch, the real live call. It's a sharp reminder that a fully green test suite proves the code behaves correctly under the conditions you wrote tests for, not under every condition that exists.

### What's the "commit happens after the response is sent" bug, and why is it subtle?

The database session was set up to automatically save its changes as cleanup work that runs after a request finishes, inside a dependency-injection pattern. That looks like it happens "during" the request from a quick read of the code, but the actual framework runs that cleanup *after* the response has already gone out over the network. So a client could receive a freshly created ID back from one call, immediately use that ID in a second call, and occasionally get "not found" — not because anything was wrong with the ID, but because the save hadn't actually landed yet when the second call arrived. It's the kind of race that a normal, unhurried test run will never expose (there's no delay between test steps to expose a save that only lags by microseconds), but a real client hitting the API twice in a row absolutely can. The fix was to save explicitly, at the moment the work is actually done, rather than trusting an implicit cleanup step whose timing wasn't what it looked like.

### Some findings from the final review were deliberately left unfixed. What were they, and why not just fix everything?

A few examples: the classifier doesn't yet handle two dedupe requests happening on exactly the same data twice (it would write a duplicate audit row rather than recognizing it already did this comparison); the blocking signal that's supposed to catch "same contract, different customer contact" is currently untestable against real data, because Phase 1's fake customers each only ever have exactly one contract — the code path is correct, there's just no fake data shaped in a way that would ever exercise it. And a live end-to-end check — actually calling OpenAI on all 60 real emails, not a mocked stand-in — was intentionally not built in this session, because running it means spending real money on a real API key without the person who owns that key being awake to see it happen. All three are documented as known, explicit gaps rather than silently ignored, which is the difference between "unfinished" and "irresponsibly finished."

### Why go to the trouble of a live Postgres 18 database for a POC instead of something lighter, like SQLite, for testing?

Because one of the architecture's locked decisions from Phase 0 is Postgres plus a vector-search extension for later phases, and testing against a different, lighter database than the one actually used in production is exactly how subtle, database-specific bugs slip through undetected — column types, constraint timing, and insert-ordering behavior aren't guaranteed to match between two different database engines. Given this project's whole premise is proving out real engineering judgment, testing against the real thing from day one is the more honest choice, even though it costs a bit of setup complexity (a running Docker container) that a lighter, in-memory substitute wouldn't.

### What would you say is still missing or worth revisiting after Phase 2?

Honestly: the dedupe classifier still has no sense of time — it can't distinguish a genuine duplicate submission from a customer legitimately reordering the exact same parts weeks later, because nothing in the data model carries a meaningful timestamp yet. Calling `run_dedupe` twice on the same request writes duplicate audit rows instead of recognizing it already ran. And the live, real-API extraction path across all 60 real emails still hasn't actually been exercised end-to-end with a real key — everything up to that boundary is proven, but that specific boundary is an open, acknowledged gap, not a false claim of completeness.

---

## Quick-reference facts

- New tables: `skus`, `customers`, `sites`, `contracts` (loaded from Phase 1's files), plus `quote_requests` and `dedupe_verdicts` (written by this phase's own code).
- Postgres runs via Docker Compose on host port 5433 (deliberately not the Postgres default, to avoid colliding with anything else already on a developer's machine).
- Entity resolution: exact case-insensitive match first, then a fuzzy "close enough" match above a strict similarity threshold; zero or multiple qualifying matches both resolve to "unknown," never a guess.
- Dedupe classifier: identical SKU sets = duplicate; one set a superset of the other, sharing at least 40% overlap = revision; otherwise distinct.
- 120 automated tests, all passing, including one acceptance test that runs the real classifier against all 60 of Phase 1's ground-truth-labeled emails and checks every verdict.
- No test in the default suite makes a real call to OpenAI; the one path that does is fully mocked everywhere it's exercised.
