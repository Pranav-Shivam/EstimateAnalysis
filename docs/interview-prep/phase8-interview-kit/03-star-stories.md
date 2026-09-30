# 03. STAR Stories

Six stories from this repo. STAR means Situation, Task, Action, Result. I add a fifth beat, "what I would do differently", because interviewers ask it every time.

Every fact here comes from `../phase*-interview.md`, `backend/data/judge_calibration.json`, the ADRs, or `git log`. Each story is about two minutes spoken. Where a number came from a phase doc, the doc is named.

A note on voice. This project was built with AI coding assistants doing implementation and review under my direction, test first, in small tasks. In the stories, "I" means I made the decision, set the direction, and verified the result. If an interviewer asks who typed the code, I say so plainly (see question 11 in file 04).

---

## Story 1. The judge that failed its release gate

**Situation.** I had built a judge that scores each draft on three dimensions and a calibration script that picks the confidence threshold. Until then the script had only run on hand-assigned scores, because I had no key for the judge vendor. When I finally ran it against the real model (Claude Haiku, 2026-09-30), it failed my release gate.

**Task.** The gate says the false-auto-send rate must be at most 5 percent. That is the share of cases the judge would send without a human that my labels say needed one. I needed to get under the ceiling honestly, without loosening the standard.

**Action.**
- The first live run gave 10.3 percent. Three cases would have auto-sent wrongly: a price predicted from only 4 peers, and two contracts expiring in 26 and 27 days. Haiku's own rationale said "moderate risk of lapsing", but it scored them 0.65 to 0.73, the same range as cases I labeled trustworthy. So no threshold could separate them. The script refused to write a threshold.
- Before changing anything, I looked at what separated my two label groups. Escalate cases had 3 to 4 peers or under 30 days to expiry. Trust cases had 31 or more peers or 560 or more days. The gap was wide, so a round policy number was safe to pick.
- I added two explicit anchors to the judge prompt: a predicted price from fewer than 10 peers scores 0.4 or lower, and a contract expiring within 30 days scores 0.5 or lower.
- I did not edit the labels and I did not raise the ceiling. That would weaken the standard to make a number pass.
- I re-ran calibration twice.

**Result.** Both runs gave threshold 0.85, kappa 1.00, false-auto-send 0.000, stored in `backend/data/judge_calibration.json`. Source: `../phase5-interview.md` addendum.

**The caveat I say myself.** The golden set has 32 cases and I tuned the prompt against it. The 32 cases come from a handful of templates (thin predicted prices, expiring contracts, healthy contracts, clean lines), and the graph-completion dimension has no escalate case that the judge scores. So a pass is real, but weak evidence. The judge is also not deterministic: it missed 3 cases on one run and 4 on the next before the fix.

**What I would do differently.** Split the golden set into a tuning half and a held-out half before touching the prompt. Run each prompt version several times and report the worst run, not the best. Grow the set from real reviewer corrections, which Phase 6 already stores as eval cases.

---

## Story 2. The graph layout that took 20 seconds

**Situation.** The reviewer UI's first version showed graph evidence only as text. I added a graph explorer page. When I opened it, I reported that it was too slow to load.

**Task.** Find out what was slow before changing anything.

**Action.**
- I did not guess. I timed each layer. The API answered in 14 ms. The page itself rendered in about 1.4 seconds.
- I then timed the layout on the real full graph in Node: 1712 nodes. Cytoscape's built-in `cose` layout took 20.5 seconds at 300 iterations and 44 seconds at 1000. That was the freeze.
- I tried the fCoSE layout on the same graph: 0.2 seconds at draft quality and 5.2 seconds at default quality. I switched to it, using draft quality only when the graph is dense (`frontend/src/components/GraphCanvas.tsx`).
- I also changed the design so the page rarely draws the whole graph. It opens on a schema map, then a type's 60 most connected nodes, then one hop at a time. Neighbor lists cap at 60 and return a `truncated` flag, because a category hub has hundreds of members and a silent cut would mislead.

**Result.** The explorer loads at `/graph` and the layout no longer freezes the tab. Two more issues showed up only in screenshots and were fixed: a small graph zoomed until its labels filled the screen (I capped the zoom), and every click re-randomized the layout (expansion now keeps existing positions). Source: `../phase7-interview.md` addendum, commit `68a95ea`.

**What I would do differently.** Put a layout-time budget in a test. Tests checked behavior and passed with the slow layout, because tests do not measure how a page feels.

---

## Story 3. Duplicate or revision: two fingerprints

**Situation.** The same job can arrive twice, and a customer can also send a changed version of an earlier request. If the system treats a revision as a duplicate, it drops the customer's change. If it treats a duplicate as new, the customer gets two quotes at two prices.

**Task.** Separate three outcomes reliably: duplicate, revision, distinct. And do it without a model call, so it is cheap and repeatable.

**Action.**
- Intake stores two fingerprints for each request. The content fingerprint is the set of SKUs code resolved. The style fingerprint is the email's normalized word tokens (`dedupe/fingerprints.py`).
- Blocking comes first: only compare against requests sharing a customer, site, or contract. This stops unrelated customers ordering the same cheap washer from looking like duplicates.
- Then classify on the content fingerprint. Identical non-empty sets are a duplicate. A strict superset that still overlaps at least 40 percent (Jaccard) is a revision. Everything else is distinct.
- The 40 percent floor exists so a request for one bolt does not become a "revision" of an unrelated fifty-item order just because that bolt appears in both.
- Two empty sets must never count as identical. If SKU resolution failed for two requests, both sets are empty, and a naive overlap calculation would call them duplicates. The code treats empty as never matching.

**Result.** An acceptance test runs the real classifier over the 60 synthetic emails against their planted answer key (5 duplicate pairs, 5 revision pairs, the rest distinct) and every verdict matches. Source: `../phase2-interview.md`. That test passes on a clean database and fails on the seeded dev database, because it counts absolute rows (`docs/new-machine-setup.md`).

**The result I trust more.** That test inserts the correct SKU sets directly, so it never runs the model. On 2026-09-30 I ran the real GPT-4o intake in front of the same classifier, on the same 10 pairs. Only 4 pairs came out right (`backend/data/live_run_report.json`, one run; earlier smoke runs gave 3 and 5, so the number moves). The classifier was not the problem. Intake failed to resolve the parts: it looks names up but ignores a part number typed in the email, such as "Aftermarket Belt 20x25 (SKU-0601)", so the SKU set came out empty and the pair looked distinct. Two revision pairs also got no verdict at all, because the earlier email's customer was never resolved and blocking found no shared customer. There were zero false merges: every miss was a missed match, in the safe direction.

**What I say about the style fingerprint.** It is computed and stored, and its similarity is saved on each verdict, but it does not change the label today. Only the content fingerprint decides. I say that up front rather than let the two-fingerprint claim sound bigger than it is.

**What I would do differently.** Run the live check when I built the test, not at the end. Fix the resolver to read a part number typed in the email, then re-run and compare. Use the style fingerprint for a real purpose, such as flagging near-identical text as a resend, and add a time dimension. Right now a genuine reorder weeks later of the same parts looks like a duplicate, because requests carry no meaningful timestamp in the dedupe logic.

---

## Story 4. The cross-vendor judge decision (ADR-0004)

**Situation.** I needed a judge for every draft. The only API key I had at the time was OpenAI's, which was also the agent's provider. The cheapest path was a smaller OpenAI model as the judge.

**Task.** Choose a judge that would not share the agent's blind spots, at a cost I accepted.

**Action.**
- The article I started from says same-model judging tends to share blind spots. The failure I worry about is not sloppiness. It is a model missing something it was never going to catch, and then a second copy of it agreeing.
- I considered a same-vendor judge (cheaper, no second key) and a local Ollama model (free, different family, weaker quality). I rejected the first because it contradicts the reasoning above, and the second because judge quality matters and about five dollars of spend was acceptable.
- I chose GPT-4o as the agent and Claude Haiku as the judge, and wrote it up as ADR-0004 with the rejected alternatives.

**Result.** The judge ran live over the golden set on 2026-09-30 and caught the risky cases in its rationales. It also taught me something the ADR did not predict: a different vendor does not fix calibration. Haiku noticed the risk but scored it too high until I added explicit anchors (Story 1). Source: `../phase5-interview.md`.

**The honest caveat.** I never ran the comparison the decision implies. I did not score the same golden set with a same-vendor judge to see whether it agreed more with the agent. So ADR-0004 rests on reasoning from the source article, not on my own measurement.

**What I would do differently.** Run the cheap experiment: score the golden set with a same-vendor judge and compare agreement and false-auto-send. Then the ADR has evidence, not just an argument.

---

## Story 5. The migration snapshot: never pay for LLM output twice

**Situation.** Two pieces of data in this project cost model calls to produce: 650 SKU embeddings and 56 community summaries. I generated them once against the real data on 2026-09-30 (about 20 thousand tokens in total). A new machine has none of my keys, and re-running the paid steps there would cost money again and could give different text.

**Task.** Make a fresh machine reach a working demo with zero API calls and the same data.

**Action.**
- I exported everything that cost an LLM call into one file, `backend/data/llm_snapshot.json.gz` (4 MB), and wrote a restore script (`scripts/restore_llm_data.py`).
- The restore refuses to load if any embedded SKU is missing from the database. Embeddings attached to the wrong products would make vector search quietly wrong, so the safe behavior is to stop.
- Community summaries are keyed by a hash of each community's SKUs, and Leiden runs with a fixed seed. So a rebuilt graph finds the same communities and the restored summaries still match.
- Everything else is rebuildable: the graph from Postgres, the demo quotes from scripted stand-ins, the judge calibration from a small JSON file.

**Result.** I proved it on a fresh database with deliberately invalid API keys. It restored 650 embeddings and 56 summaries, the embedding script then reported 0 SKUs needing work, and vector search returned sensible neighbors. The steps are in `docs/new-machine-setup.md`. Source: `../phase7-interview.md` addendum.

**What I say about the money.** The dollar amount is tiny, well under a cent. The point was reproducibility and being able to set up the project with no secrets, not the savings.

**What I would do differently.** Version the snapshot with the embedding model name and a content hash of each SKU's text, so a changed product name is detected instead of silently keeping a stale vector.

---

## Story 6. The graph that was missing from the UI

**Situation.** Phase 7 was the reviewer UI. My Phase 7 spec had a line saying the evidence path is a stored snapshot, not a live graph view. That line quietly dropped the thing that makes a knowledge graph worth building: being able to see and walk the relationships. I ran the app and asked where the graph was.

**Task.** Fix the gap, and understand why I had not caught it earlier.

**Action.**
- The honest answer was that the scope cut happened during planning and was never flagged as a loss. All 81 frontend tests passed, and none of them could notice a missing feature nobody asked them to check.
- I built the explorer (schema overview, most-connected nodes by type, one-hop expansion, a draw-everything button) and dashboard bar charts for flags by dimension and graph counts.
- I verified by looking at the rendered result, not only the tests. Screenshots caught the layout, zoom, and chart-label problems that tests could not.
- I changed my working habit: when a spec defers something the roadmap promised, call it out as a decision the user must approve.

**Result.** The graph is visible at `/graph`, and the dashboard charts show every label. The kit's screenshots in `images/` come from that UI.

**The lesson I say.** The user-visible result is the thing to verify. Passing tests told me the code did what I wrote. They could not tell me I had written the wrong scope. Source: `../phase7-interview.md` addendum, commits `68a95ea` and `0c3c558`.

**What I would do differently.** Before locking any spec, diff its non-goals against the roadmap's "done when" lines for that phase. Anything in one and not the other gets raised with the user, in writing.
